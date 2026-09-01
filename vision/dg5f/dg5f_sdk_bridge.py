# -*- coding: utf-8 -*-
"""실물 Tesollo DG-5F SDK 브리지 — vision_node UDP 패킷 [0..19] 관절각[deg]을
DGSDK.dll(ctypes)로 실물 그리퍼에 중계한다.

구조 (Unity 트윈과 실물을 같은 스트림으로 동시 구동):
  vision_node_dg5f.py [left|right] --bridge
     ├→ Unity Dg5fReceiver (config/rtauto_config.PORT_DG5F_SIM, 기본 5006, 트윈)
     └→ 이 브리지 (config/rtauto_config.PORT_DG5F_BRIDGE, 기본 5008) → DGSDK.dll → 실물 (Modbus TCP :502, DEVELOPER 모드)
     (구 포트 5007은 ZED 좌표 송신(zed_sender.py)과 충돌해 5008로 변경 — config/rtauto_config.py 참조)

SDK 근거 (태슬로sdk/DGSDKSample_ver_2_0_1, 2026-07-20 확인):
  - MAX_JOINT_COUNT=20 (5손가락×4관절), 각도 단위 degrees — 우리 20채널과 1:1
  - 초기화 순서: SetGripperSystem → ConnectToGripper → SetGripperOption → SystemStart
  - 실시간 구동: MoveServoJoint(float[20]) — DEVELOPER 모드 전용, 모션타임 무시
  - 구조체 레이아웃: DGDataTypes.h (GripperSystemSetting/GripperSetting) 그대로 ctypes 매핑

사용:
  python dg5f_sdk_bridge.py                # 드라이런 — DLL 안 씀, 수신값만 출력(패킷 경로 검증)
  python dg5f_sdk_bridge.py --ip           # 실물 연결 — IP는 .env의 RTAUTO_DG5F_IP에서 읽는다
                                           # (기본 모델 5f_right — DG-5F-M-R 확정)
  python dg5f_sdk_bridge.py --ip <IP> --model 5f_right --unmirror
      --ip <IP>: .env 값 대신 일회성으로 다른 그리퍼를 지정할 때만
      --unmirror: vision_node를 left로 돌리면서(왼손 Unity 트윈) 실물이 오른손일 때 —
                  왼손 미러 채널 부호를 되돌려 오른손 규약으로 변환
  종료: Ctrl+C (SystemStop + Disconnect 자동)

관절 대응은 **2026-08-31 실물 실측으로 확정됐다** — JOINT_ORDER 항등(Motor N ↔ 채널 N-1),
JOINT_SIGN 전 채널 +1, JOINT_OFFSET_DEG 0, JOINT_CLAMP는 채널별 실제 가동범위. 근거와
함정은 아래 상수 정의부 주석과 docs/SIM2REAL_ROADMAP.md §5 참고.

⚠️ 새 관절·새 하드웨어를 처음 움직일 때 (기존 DG-5F-M-R에는 해당 없음):
  1. --jog IDX:DEG 로 한 관절씩 단독 구동하고 **전류를 함께 볼 것**. 부호를 잘못 잡으면
     반대편 하드 스톱을 밀며 1.5 A로 스톨하는데, 증상은 "안 움직인다"로 보인다(실측 전례).
  2. 처음엔 --max-step 을 작게(기본 2°/틱) + 손 벌린 rest 자세에서 시작.
"""
import argparse
import ctypes
import os
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (
    PORT_DG5F_BRIDGE, DG5F_DLL as CONFIG_DG5F_DLL, DG5F_MAX_DEG_PER_SEC,
    UNITY_IP, PORT_DG5F_SIM, DG5F_IP, resolve_gripper_ip,
)

# ---------------- 우리 패킷 계약 (dg5f_angles와 동일) ----------------
N_JOINTS = 20
MIN_PACKET_BYTES = 4 * N_JOINTS          # v1(<20f>) 이상이면 앞 20f만 사용 (수신기 관례와 동일)
# Unity UI(Dg5fTwinModeSwitcher)가 방향 전환에 쓰는 제어 패킷의 머리표.
# 관절 패킷은 80바이트 이상이라 길이·머리표 어느 쪽으로도 겹치지 않는다.
CONTROL_MAGIC = b"DG5FMODE"
# 왼손 스트림 → 오른손 실물 변환(--unmirror)용. dg5f_angles.LEFT_MIRROR_CHANNELS와 같은 내용을
# 채널 인덱스로 고정 (임포트하면 보정 로드 출력이 섞여서 상수로 복사; 채널 순서 변경 시 함께 수정).
CHANNEL_NAMES = [
    "thumb_cmc", "thumb_opp", "thumb_mcp", "thumb_ip",
    "index_abd", "index_mcp", "index_pip", "index_dip",
    "middle_abd", "middle_mcp", "middle_pip", "middle_dip",
    "ring_abd", "ring_mcp", "ring_pip", "ring_dip",
    "pinky_cmc", "pinky_lat", "pinky_mcp", "pinky_pip",
]
MIRROR_IDX = [0, 1, 2, 3, 4, 8, 12, 16, 17]   # LEFT_MIRROR_CHANNELS 해당 인덱스

# ---------------- 우리 채널 → SDK float[20] 대응 ----------------
# ★2026-08-31 벤더 하드웨어 설명서로 확정 (그 전까지 "미검증 가정값"이었음).
#   출처: [테솔로] DG-5F-M_하드웨어_설명서_KR_v2_0_0.pdf
#          §3.3.1 모터 순서 및 구동 범위 (DG-5F-M 오른손) / §3.3.2 모터 방향
#   - 손가락 번호: Finger 1=엄지, 2=검지, 3=중지, 4=약지, 5=새끼 (§3.3.1 도면)
#   - 모터 번호: 손가락당 뿌리→끝 순서로 4개씩 연번.
#       F1 엄지 = Motor 1~4 / F2 검지 = 5~8 / F3 중지 = 9~12 / F4 약지 = 13~16 / F5 새끼 = 17~20
#   - 따라서 **Motor N ↔ 우리 채널 인덱스 N-1**로 정확히 일치 → JOINT_ORDER는 항등이 맞다.
#   - §3.3.2 "화살표 방향이 양의 방향" 도면에서 굽힘 관절의 양의 방향이 손을 오므리는 쪽 →
#     우리 규약(굽힘=양수)과 일치 → JOINT_SIGN 전부 +1이 맞다.
#   ⚠️ 영점(JOINT_OFFSET_DEG)은 이 문서로 확정되지 않았다. §3.1.2 Zero Position 도면상
#     "전 관절 0 = 손가락을 쫙 편 상태, 엄지는 옆으로 벌림"이라 우리 규약과 어긋나 보이지 않지만,
#     실측(dg5f_readback_bridge.py --teach --probe)으로 확인하기 전까지는 0으로 둔다.
JOINT_ORDER = list(range(20))            # sdk[i] = ours[JOINT_ORDER[i]] — 하드웨어 설명서로 확정
# 부호: 전 채널 +1 (설명서 §3.3.2 화살표 = 굽힘 방향 = 양수, 우리 규약과 동일).
#
# ★thumb_opp(1_2)를 한때 -1로 뒤집었다가 되돌린 기록 (2026-08-31) — 같은 실수를 반복하지 않도록:
#   설명서 §3.3.1의 "Motor 2 (0° to 155°)"만 보고 "URDF는 -155..0인데 실물은 0..155이니 거울"
#   이라고 판단해 JOINT_SIGN[1]=-1을 넣었다. **틀렸다.** 그 표는 부호 없는 이동량 표기이고,
#   실물 엔코더/명령 프레임은 URDF와 같은 부호를 쓴다.
#   실측 근거(--jog 1:60, 전류 로깅):
#     · 출발 실제각 -88.9° — 0..155 범위 밖. 사람이 잡아둔 '종이컵 파지(깊은 대향)' 자세였다.
#     · 명령이 음수인 동안 전류 0mA·미동 없음 → 컨트롤러가 그 구간을 구동하지 않음
#     · 명령이 +로 넘어가자 즉시 구동, 실제각이 +3.7°에서 **하드 스톱**에 걸려 정지
#     · 그 상태로 1350~1600mA를 계속 소모(스톨)
#   → 실제 가동 범위는 대략 [-90, +4]로 URDF(-155..0)와 부호가 일치한다.
#   부호를 뒤집었던 탓에 Unity의 대향 명령(-80)이 +80으로 나가 반대편 스톱에 박혔고,
#   초기 주먹 로그에서 thumb_opp 실제각이 +2~3°에 고정돼 "아예 안 움직인다"로 보였다.
#   그건 무응답이 아니라 반대 방향으로 밀고 있던 것이다.
JOINT_SIGN = [1.0] * 20
JOINT_OFFSET_DEG = [0.0] * 20            # ⚠️ 미확정(위 주석) — 영점 차이 발견 시 여기로

# 관절별 하드웨어 구동 범위[deg] — **DG-5F-M 오른손** 기준, 위 설명서 §3.3.1 실측 표 그대로.
#   기존에는 전 관절 (-130,130) 뭉뚱그린 값이라 실제 리밋을 한참 넘겨 명령할 수 있었다
#   (예: 엄지 1_1은 실제 -22~77인데 -130까지 허용 → 리밋 방향으로 밀어붙임 = 하드웨어 손상 위험).
#   이제 채널별 실제 범위로 좁힌다. 이것이 "관절 대응 미검증" 안전 부채의 핵심 완화책이다.
#   ⚠️ **왼손(DG-5F-M-L)은 좌우 비대칭 채널의 부호가 뒤집힌다** — 벌림(abd)·엄지 1_1·새끼 5_1/5_2가
#     해당(설명서의 왼손 도면 §3.3.1 참조). 우리 하드웨어는 오른손 확정(DG-5F-M-R)이라 그 표만 싣는다.
#     왼손 지원이 필요해지면 비대칭 채널을 negate&swap 한 표를 별도로 둘 것.
JOINT_CLAMP_RIGHT = [
    (-22.0,  77.0),   #  0 thumb_cmc   Motor 1
    # thumb_opp: 설명서 표는 "0..155"지만 그건 부호 없는 이동량이다. 실물 엔코더/명령 프레임은
    # URDF와 같은 음수 대향 규약이며, --jog 실측에서 +3.7°에 하드 스톱이 확인됐다(그 위로
    # 명령하면 1.5A로 스톨). 상한을 0으로 잡아 스톱에 밀어붙이지 않게 한다.
    (-155.0,  0.0),   #  1 thumb_opp   Motor 2  (URDF -155..0 / 실측 하드스톱 ≈ +3.7)
    (-90.0,  90.0),   #  2 thumb_mcp   Motor 3
    (-90.0,  90.0),   #  3 thumb_ip    Motor 4
    (-31.0,  20.0),   #  4 index_abd   Motor 5
    (  0.0, 115.0),   #  5 index_mcp   Motor 6
    (-90.0,  90.0),   #  6 index_pip   Motor 7
    (-90.0,  90.0),   #  7 index_dip   Motor 8
    (-30.0,  30.0),   #  8 middle_abd  Motor 9   (dg5f_angles.URDF_LIMITS_DEG는 ±25 — 설명서가 더 넓다)
    (  0.0, 115.0),   #  9 middle_mcp  Motor 10
    (-90.0,  90.0),   # 10 middle_pip  Motor 11
    (-90.0,  90.0),   # 11 middle_dip  Motor 12
    (-15.0,  32.0),   # 12 ring_abd    Motor 13
    (  0.0, 110.0),   # 13 ring_mcp    Motor 14
    (-90.0,  90.0),   # 14 ring_pip    Motor 15
    (-90.0,  90.0),   # 15 ring_dip    Motor 16
    (  0.0,  60.0),   # 16 pinky_cmc   Motor 17
    (-15.0,  90.0),   # 17 pinky_lat   Motor 18
    (-90.0,  90.0),   # 18 pinky_mcp   Motor 19
    (-90.0,  90.0),   # 19 pinky_pip   Motor 20
]
JOINT_CLAMP = JOINT_CLAMP_RIGHT

# ---------------- SDK ctypes 바인딩 (DGDataTypes.h 레이아웃 그대로) ----------------
# RTAUTO_DG5F_DLL(.env)로 오버라이드 가능 — 없으면 스크립트 기준 상대경로 기본값 사용.
DEFAULT_DLL = CONFIG_DG5F_DLL or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "태슬로sdk", "DGSDKSample_ver_2_0_1", "DGSDK", "DGSDK.dll")
DG_RESULT_NONE = 0
CONTROL_MODE_DEVELOPER = 1
COMMUNICATION_MODE_ETHERNET = 0
DEVELOPER_MODE_RECEIVED_DATA_TYPE_JOINT = 0x01
DEVELOPER_MODE_RECEIVED_DATA_TYPE_CURRENT = 0x02
DEVELOPER_MODE_RECEIVED_DATA_TYPE_MODULE_ERROR_CODE = 0x07
MODELS = {  # DGDataTypes.h DG_MODEL
    "5f_left": 0x5F12, "5f_right": 0x5F22,
    "5f_s_left": 0x5F14, "5f_s_right": 0x5F24,
    "5f_s15_left": 0x5F34, "5f_s15_right": 0x5F44,
}


class GripperSystemSetting(ctypes.Structure):
    _fields_ = [("comport", ctypes.c_char * 32),
                ("ip", ctypes.c_char * 32),
                ("port", ctypes.c_int),
                ("readTimeout", ctypes.c_int),
                ("controlMode", ctypes.c_int),
                ("communicationMode", ctypes.c_int),
                ("slaveID", ctypes.c_int),
                ("baudrate", ctypes.c_int)]


class GripperSetting(ctypes.Structure):
    _fields_ = [("jointOffset", ctypes.c_float * 20),
                ("jointInpose", ctypes.c_float * 20),
                ("tcpInpose", ctypes.c_float * 5),
                ("orientationInpose", ctypes.c_float * 5),
                ("receivedDataType", ctypes.c_int * 8),
                ("movingInpose", ctypes.c_float),
                ("jointCount", ctypes.c_int),
                ("fingerCount", ctypes.c_int),
                ("model", ctypes.c_int),
                ("dutyByteLength", ctypes.c_int8)]


# ---------------- 콜백용 구조체 (DGDataTypes.h / dg_python-main types.py 대조, 2026-08-31) ----------------
# 읽기(dg5f_readback_bridge.py)에서 GetReceivedGripperData(폴링)와 별개로 필요 —
# 아래 connect()가 ConnectToGripper() 전에 이 콜백들을 등록하지 않으면 DLL이 내부적으로
# (아마 연결 성공 시 OnConnected 등을) 널 함수포인터로 호출해 "access violation writing 0x0"으로
# 죽는다(2026-08-31 실물 실측, 매뉴얼 10.1 ConnectToGripper 예제가 연결 전 콜백 등록을 명시).
# 콜백 인자로 쓰이는 구조체라 값 자체를 안 써도 레이아웃은 정확해야 한다(ABI 언마샬링).
N_FINGERS = 5


class ReceivedGripperData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("joint", ctypes.c_float * N_JOINTS),
        ("current", ctypes.c_int * N_JOINTS),
        ("velocity", ctypes.c_int * N_JOINTS),
        ("temperature", ctypes.c_float * N_JOINTS),
        ("TCP", ctypes.c_float * (6 * N_FINGERS)),
        ("moving", ctypes.c_int),
        ("targetArrived", ctypes.c_int),
        ("blendMoveState", ctypes.c_int),
        ("currentBlendIndex", ctypes.c_int),
        ("productID", ctypes.c_int),
        ("firmwareVersion", ctypes.c_int),
        ("moduleErrorCode", ctypes.c_int),
        ("controlPeriod", ctypes.c_int),
    ]


class ReceivedFingertipSensorData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("sensorType", ctypes.c_int),
        ("attachedFinger", ctypes.c_int * N_FINGERS),
        ("forceTorque", ctypes.c_float * (6 * N_FINGERS)),
        ("tactile", ctypes.c_uint16 * (18 * N_FINGERS)),
    ]


class ReceivedGPIOData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("GPIO", ctypes.c_int * 4)]


# 콜백 함수 포인터 타입 (DGSDK.h 시그니처 그대로, cdecl — CDLL 로드와 일치시킴)
ConnectedToGripperCallback = ctypes.CFUNCTYPE(None)
DisconnectedToGripperCallback = ctypes.CFUNCTYPE(None)
ReceivedGripperDatasCallback = ctypes.CFUNCTYPE(None, ReceivedGripperData)
CommunicationPeriodCallback = ctypes.CFUNCTYPE(None, ctypes.c_int)
ReceivedSensorCallback = ctypes.CFUNCTYPE(None, ReceivedFingertipSensorData)
ReceivedGPIOCallback = ctypes.CFUNCTYPE(None, ReceivedGPIOData)


class Dg5fSdk:
    """DGSDK.dll 래퍼 — 초기화 시퀀스와 MoveServoJoint만 노출."""

    def __init__(self, dll_path):
        self.dll = ctypes.CDLL(dll_path)   # extern "C" cdecl
        self.dll.SetGripperSystem.argtypes = [GripperSystemSetting]
        self.dll.SetGripperSystem.restype = ctypes.c_int
        self.dll.SetGripperOption.argtypes = [GripperSetting]
        self.dll.SetGripperOption.restype = ctypes.c_int
        for name in ("ConnectToGripper", "DisconnectToGripper",
                     "SystemStart", "SystemStop"):
            getattr(self.dll, name).restype = ctypes.c_int
        self.dll.MoveServoJoint.argtypes = [ctypes.POINTER(ctypes.c_float)]
        self.dll.MoveServoJoint.restype = ctypes.c_int
        self.dll.MoveJointAll.argtypes = [ctypes.POINTER(ctypes.c_float)]
        self.dll.MoveJointAll.restype = ctypes.c_int
        self.dll.SetMotionTimeAllEqual.argtypes = [ctypes.c_int]
        self.dll.SetMotionTimeAllEqual.restype = ctypes.c_int
        self.dll.SetLowPassFilterAlpha.argtypes = [ctypes.c_int, ctypes.c_float]
        self.dll.SetLowPassFilterAlpha.restype = ctypes.c_int
        self.dll.SetJointGainPIDAllEqual.argtypes = [ctypes.c_float] * 4
        self.dll.SetJointGainPIDAllEqual.restype = ctypes.c_int
        self.dll.CallbackForOnConnected.argtypes = [ConnectedToGripperCallback]
        self.dll.CallbackForOnConnected.restype = ctypes.c_int
        self.dll.CallbackForOnDisconnected.argtypes = [DisconnectedToGripperCallback]
        self.dll.CallbackForOnDisconnected.restype = ctypes.c_int
        self.dll.CallbackForOnReceivedGripperData.argtypes = [ReceivedGripperDatasCallback]
        self.dll.CallbackForOnReceivedGripperData.restype = ctypes.c_int
        self.dll.CallbackForOnCommunicationPeriod.argtypes = [CommunicationPeriodCallback]
        self.dll.CallbackForOnCommunicationPeriod.restype = ctypes.c_int
        self.dll.CallbackForOnReceivedFingertipSensorData.argtypes = [ReceivedSensorCallback]
        self.dll.CallbackForOnReceivedFingertipSensorData.restype = ctypes.c_int
        self.dll.CallbackForOnReceivedGPIOData.argtypes = [ReceivedGPIOCallback]
        self.dll.CallbackForOnReceivedGPIOData.restype = ctypes.c_int
        # 상태 읽기 — 명령 대비 실제 추종을 보려면 같은 연결에서 읽어야 한다(그리퍼가 클라이언트
        # 1개만 허용하므로 별도 프로세스로 읽을 수 없다, 2026-08-31 실측).
        self.dll.GetReceivedGripperData.argtypes = [ctypes.POINTER(ReceivedGripperData)]
        self.dll.GetReceivedGripperData.restype = ctypes.c_int
        self._recv = ReceivedGripperData()
        # 수동 교시(힘 풀기) — Unity UI의 real→sim 모드에서 쓴다.
        self.dll.ManualTeachMode.argtypes = [ctypes.c_int]
        self.dll.ManualTeachMode.restype = ctypes.c_int
        self._callback_refs = []   # ctypes 콜백 트램폴린 GC 방지용 — connect()에서 채움

    def _check(self, name, res):
        if res != DG_RESULT_NONE:
            raise RuntimeError(f"{name} 실패 — DG_RESULT={res} (DGDataTypes.h 참조)")

    def connect(self, ip, port, model_code, control_mode=CONTROL_MODE_DEVELOPER,
                set_gains=True, gain_p=2.0, gain_d=5.0, gain_i=0.05, gain_ilimit=0.1):
        sys_set = GripperSystemSetting()
        sys_set.comport = b"COM1"                  # Ethernet 모드에선 미사용(샘플 관례)
        sys_set.ip = ip.encode("ascii")
        sys_set.port = port
        sys_set.readTimeout = 60000           # 매뉴얼 10.1 TCP/IP 예제값(우리 이전 1000은 임의값)
        sys_set.controlMode = control_mode   # MoveServoJoint 쓰려면 DEVELOPER 필수(기본값).
                                              # 읽기 전용 클라이언트(dg5f_readback_bridge.py)는
                                              # OPERATOR로 붙여야 할 수도 있어 매개변수로 뺌.
        sys_set.communicationMode = COMMUNICATION_MODE_ETHERNET
        sys_set.slaveID = 1
        sys_set.baudrate = 115200
        self._check("SetGripperSystem", self.dll.SetGripperSystem(sys_set))

        # ⚠️ 매뉴얼 10.1 ConnectToGripper 예제(InitializedCallback)가 명시: 콜백을 등록하지
        # 않고 ConnectToGripper()를 부르면 DLL이 연결 성공 시 내부적으로 호출하는 콜백이
        # 널 포인터라 "access violation writing 0x0"으로 죽는다(2026-08-31 실물 실측 확인).
        # 실제 데이터는 안 써도(폴링 GetReceivedGripperData로 따로 읽음) 콜백 자체는 반드시
        # 등록해야 한다. self._callback_refs에 보관해 GC로 트램폴린이 회수되지 않게 한다.
        def _noop0():
            pass

        def _noop1(_arg):
            pass

        cbs = [
            ("CallbackForOnConnected", ConnectedToGripperCallback(_noop0)),
            ("CallbackForOnDisconnected", DisconnectedToGripperCallback(_noop0)),
            ("CallbackForOnReceivedGripperData", ReceivedGripperDatasCallback(_noop1)),
            ("CallbackForOnCommunicationPeriod", CommunicationPeriodCallback(_noop1)),
            ("CallbackForOnReceivedFingertipSensorData", ReceivedSensorCallback(_noop1)),
            ("CallbackForOnReceivedGPIOData", ReceivedGPIOCallback(_noop1)),
        ]
        for name, cb in cbs:
            self._callback_refs.append(cb)          # GC 방지 — 연결 유지 중엔 계속 들고 있을 것
            self._check(name, getattr(self.dll, name)(cb))

        self._check("ConnectToGripper", self.dll.ConnectToGripper())

        opt = GripperSetting()                     # 배열들은 ctypes가 0으로 초기화
        opt.model = model_code
        opt.movingInpose = 0.4
        # 수신할 데이터 종류 (DGDataTypes.h enum DEVELOPER_MODE_RECEIVED_DATA_TYPE).
        # 관절각만 받으면 ReceivedGripperData의 current/moduleErrorCode가 안 채워져서, 어떤 관절이
        # "명령은 받는데 안 움직일 때" 원인(토크 부족 vs 미구동 vs 모듈 이상)을 가릴 수가 없다.
        # 전류와 모듈 에러코드를 함께 요청해 진단에 쓴다 — 2026-08-31 thumb_opp 무응답 조사에서 추가.
        opt.receivedDataType[0] = DEVELOPER_MODE_RECEIVED_DATA_TYPE_JOINT
        opt.receivedDataType[1] = DEVELOPER_MODE_RECEIVED_DATA_TYPE_CURRENT
        opt.receivedDataType[2] = DEVELOPER_MODE_RECEIVED_DATA_TYPE_MODULE_ERROR_CODE
        self._check("SetGripperOption", self.dll.SetGripperOption(opt))

        if set_gains:
            # ★게인은 연결할 때마다 반드시 넣어야 한다 (2026-08-31 실측으로 확정).
            #   넣지 않고 돌려봤더니 **전 관절이 아예 움직이지 않았다** — 개발자 모드 연결에서는
            #   그리퍼에 저장된 게인이 승계되지 않는 것으로 보인다(DGManager로 튜닝해둔 값이
            #   있어도 마찬가지). 그래서 set_gains 기본값은 True다.
            # ★P=2.0인 이유: 예전 값 1.0은 너무 약해 **최대 부하 관절인 thumb_opp(엄지 대향)가
            #   명령 80°에 1°도 응답하지 않았다** (--track 실측: 이동량 80.0 / 실제시작 없음 /
            #   최종오차 78.2). 나머지 저부하 굽힘 관절만 12~23° 끌리며 움직여, "유니티와 실물
            #   움직임이 다르다"의 실제 원인이었다. 매뉴얼 §11.2 예제값도 2.0이며, 같은 절이
            #   "P가 높으면 빨리 도달하나 떨림이 생길 수 있다"고 경고하므로 올릴 때는 조금씩.
            self.dll.SetJointGainPIDAllEqual(gain_p, gain_d, gain_i, gain_ilimit)
            print(f"[게인] P={gain_p} D={gain_d} I={gain_i} iLimit={gain_ilimit}")
        self._check("SystemStart", self.dll.SystemStart())

    def servo(self, deg20):
        arr = (ctypes.c_float * 20)(*deg20)
        return self.dll.MoveServoJoint(arr)

    def read(self):
        """실물 관절 실제각 20개(SDK 규약, deg). 아직 데이터가 없으면 None."""
        if self.dll.GetReceivedGripperData(ctypes.byref(self._recv)) != DG_RESULT_NONE:
            return None
        joints = list(self._recv.joint)
        # 연결 직후 첫 프레임은 데이터 도착 전이라 구조체가 통째로 0이다 — 추종오차 통계를
        # 오염시키므로 걸러낸다(dg5f_readback_bridge.run_rest와 같은 처리).
        return None if all(v == 0.0 for v in joints) else joints

    def read_diag(self):
        """진단용: (관절각, 전류[mA], 모듈에러코드). read()와 달리 빈 프레임도 그대로 준다.

        전류는 "명령은 받는데 안 움직인다"의 원인을 가르는 핵심 신호다 —
        전류가 흐르는데 각도가 안 변하면 토크 부족/기구 구속, 전류가 0이면 애초에 구동되지 않는 것.
        connect()에서 receivedDataType에 CURRENT를 함께 요청해야 채워진다.
        """
        if self.dll.GetReceivedGripperData(ctypes.byref(self._recv)) != DG_RESULT_NONE:
            return None, None, None
        return (list(self._recv.joint), list(self._recv.current),
                int(self._recv.moduleErrorCode))

    def close(self):
        try:
            self.dll.SystemStop()
        finally:
            self.dll.DisconnectToGripper()


def to_sdk_frame(ours, unmirror):
    """우리 채널 20개 → SDK float[20] (미러 복원 → 재배열 → 부호/영점 → 클램프)."""
    v = list(ours)
    if unmirror:
        for i in MIRROR_IDX:
            v[i] = -v[i]
    out = []
    for i in range(N_JOINTS):
        d = JOINT_SIGN[i] * v[JOINT_ORDER[i]] + JOINT_OFFSET_DEG[i]
        lo, hi = JOINT_CLAMP[i]
        out.append(min(hi, max(lo, d)))
    return out


def from_sdk_frame(sdk):
    """SDK float[20](실물 readback) → 우리 채널 20개. to_sdk_frame의 역변환.

    실물을 읽어 Unity 트윈으로 되돌리는 경로(dg5f_readback_bridge.py)가 쓴다. 이 변환을
    빼먹으면 부호가 다른 채널이 Unity 리밋에서 잘려 트윈만 안 움직인다 —
    실제로 thumb_opp(우리 -155..0 / 실물 0..155)가 그랬다. 두 방향이 반드시 같은
    JOINT_ORDER/SIGN/OFFSET 표를 쓰게 하려고 여기 나란히 둔다(정본 하나 원칙).

    ⚠️ 클램프는 되돌리지 않는다(정보가 이미 사라졌으므로). unmirror도 다루지 않는다 —
    읽기 경로는 실물이 곧 정본이라 미러 복원 대상이 아니다.
    """
    ours = [0.0] * N_JOINTS
    for i in range(N_JOINTS):
        sign = JOINT_SIGN[i] if JOINT_SIGN[i] != 0.0 else 1.0
        ours[JOINT_ORDER[i]] = (sdk[i] - JOINT_OFFSET_DEG[i]) / sign
    return ours


def main():
    ap = argparse.ArgumentParser(description="DG-5F 실물 SDK 브리지")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="그리퍼 IP. 아예 생략하면 드라이런(수신값 출력만), 값 없이 --ip만 "
                         "주면 .env의 RTAUTO_DG5F_IP를 쓴다"
                         + (f" (현재 {DG5F_IP})" if DG5F_IP else " (현재 비어 있음)"))
    ap.add_argument("--port", type=int, default=502, help="그리퍼 Modbus TCP 포트 (기본 502)")
    ap.add_argument("--model", default="5f_right", choices=sorted(MODELS),
                    help="실물 모델 (기본 5f_right — 하드웨어 확정: DG-5F-M-R, M=표준/비-short)")
    ap.add_argument("--listen", type=int, default=PORT_DG5F_BRIDGE,
                    help=f"UDP 수신 포트 (vision_node --bridge와 동일해야 함, 기본 {PORT_DG5F_BRIDGE})")
    ap.add_argument("--dll", default=DEFAULT_DLL, help="DGSDK.dll 경로")
    ap.add_argument("--hz", type=float, default=50.0, help="실물 송신 상한 Hz (기본 50)")
    # 슬루 리밋은 "틱당 몇 도"가 아니라 "초당 몇 도"가 물리적으로 의미 있는 양이다.
    # 그래서 정본은 config의 DG5F_MAX_DEG_PER_SEC 하나이고, 여기서 --hz로 나눠 틱당 값으로
    # 환산한다 — Unity 쪽 Dg5fFistButton도 같은 값을 읽어 트윈이 실물보다 빠르지 않게 한다.
    # (--hz를 바꿔도 실제 각속도가 따라 변하지 않는다는 부수 이득도 있다.)
    ap.add_argument("--max-deg-per-sec", type=float, default=DG5F_MAX_DEG_PER_SEC,
                    help=f"관절 각속도 상한[deg/s] — 정본은 .env의 "
                         f"RTAUTO_DG5F_MAX_DEG_PER_SEC (현재 {DG5F_MAX_DEG_PER_SEC:g})")
    ap.add_argument("--max-step", type=float, default=None,
                    help="틱당 관절 최대 변화량[deg]을 직접 지정 — 주면 --max-deg-per-sec를 무시한다"
                         " (기본: 각속도 상한 / --hz 로 자동 환산)")
    ap.add_argument("--lpf", type=float, default=0.3,
                    help="SDK 내장 저역필터 alpha (0=사용 안 함, 기본 0.3)")
    ap.add_argument("--unmirror", action="store_true",
                    help="왼손 스트림(vision_node left)을 오른손 실물 규약으로 부호 변환")
    # 게인은 **연결할 때마다 넣어야 한다**(2026-08-31 실측): 안 넣고 돌리면 전 관절이 아예
    # 움직이지 않았다. 개발자 모드 연결에서는 그리퍼에 저장된 값이 승계되지 않는 것으로 보인다.
    ap.add_argument("--no-set-gains", dest="set_gains", action="store_false",
                    help="PID 게인을 넣지 않는다(실험용). ⚠️ 실측상 게인 없이는 실물이 전혀 "
                         "움직이지 않았다 — 정상 구동에는 쓰지 말 것")
    ap.set_defaults(set_gains=True)
    ap.add_argument("--gain-p", type=float, default=2.0,
                    help="P 게인 (기본 2.0 = 매뉴얼 §11.2 예제값). 예전 값 1.0은 너무 약해 "
                         "최대 부하 관절 thumb_opp가 명령 80°에 1°도 응답하지 않았다(2026-08-31 실측). "
                         "높이면 도달이 빨라지지만 매뉴얼 경고대로 떨림이 생길 수 있다")
    ap.add_argument("--gain-d", type=float, default=5.0, help="D 게인")
    ap.add_argument("--gain-i", type=float, default=0.05, help="I 게인")
    ap.add_argument("--gain-ilimit", type=float, default=0.1, help="I 적분 한계")
    ap.add_argument("--echo-to-unity", action="store_true",
                    help="실물의 실제각을 읽어 Unity Dg5fReceiver(포트 PORT_DG5F_SIM)로 되돌려 보낸다 — "
                         "'Unity 명령 → 실물 → 다시 Unity' 왕복 비교용. 그리퍼가 클라이언트 1개만 "
                         "허용해 dg5f_readback_bridge.py를 동시에 못 돌리므로 이 브리지가 직접 한다. "
                         "⚠️ Unity에서 Dg5fSender(송신)와 Dg5fHandDriver(수신)를 동시에 켜면 "
                         "Unity→실물→Unity→실물 피드백 루프가 된다 — 한 번에 하나만 켤 것")
    ap.add_argument("--echo-ip", default=UNITY_IP, help="--echo-to-unity 대상 IP")
    ap.add_argument("--echo-port", type=int, default=PORT_DG5F_SIM,
                    help=f"--echo-to-unity 대상 포트 (기본 {PORT_DG5F_SIM})")
    ap.add_argument("--track", default=None, metavar="CSV",
                    help="명령 vs 실제 추종 기록 — 매 틱 [보낸 각도 / 실물 실제 각도]를 CSV로 저장하고 "
                         "요약을 출력한다. '유니티와 실물 움직임이 다르다'를 정량화할 때 쓴다: "
                         "어느 채널이 언제 움직이기 시작해 언제 도착하는지 시각별로 남는다. "
                         "예) --track logs/track.csv")
    ap.add_argument("--track-channels", default="0,1",
                    help="--track 실행 중 화면에 실시간 표시할 채널 인덱스 (기본 0,1 = 엄지 X·Z축)")
    ap.add_argument("--jog", default=None, metavar="IDX:DEG",
                    help="관절 하나만 단독으로 천천히 움직여 응답을 확인한다 — 어느 모터가 실제로 "
                         "구동되는지 가리는 용도. 나머지 관절은 현재 자세 그대로 둔다(0으로 안 보냄). "
                         "슬루 리밋으로 서서히 올렸다가 원위치로 되돌린 뒤 종료하며, 매 틱 명령/실제를 "
                         "출력한다. 예) --jog 0:40 (엄지 1_1을 40°로) / --jog 1:60 "
                         "⚠️ 값은 **실물 SDK 규약**이다(우리 규약 아님) — 하드웨어 설명서 §3.3.1의 "
                         "Motor(N)가 곧 IDX(N-1)이고 범위도 그 표를 따른다")
    ap.add_argument("--jog-hold", type=float, default=1.5,
                    help="--jog에서 목표에 도달한 뒤 유지할 시간(초) (기본 1.5)")
    ap.add_argument("--pose", default=None,
                    help="검증용 1회 포즈: 'idx:deg[,idx:deg...]' 나머지 0으로 MoveServoJoint 후 종료. "
                         "예) --pose 6:20 (검지 pip만 20°)")
    args = ap.parse_args()

    try:
        args.ip = resolve_gripper_ip(args.ip)
    except ValueError as e:
        print(f"[오류] {e}")
        return

    if args.max_step is None:
        args.max_step = args.max_deg_per_sec / max(1e-6, args.hz)
    print(f"[슬루] 각속도 상한 {args.max_deg_per_sec:g} deg/s @ {args.hz:g} Hz "
          f"→ 틱당 {args.max_step:.2f}° (Unity Dg5fFistButton도 같은 상한을 읽는다)")

    dry = args.ip is None

    # UDP 수신 소켓을 실물 연결보다 **먼저** 잡는다 (2026-09-01).
    #   순서가 반대면, 포트가 이미 점유된 상태에서 ConnectToGripper·게인설정·SystemStart까지
    #   다 끝낸 뒤 bind에서 죽는다 — 그리퍼는 서보가 켜진 채 세션만 끊기고, 다음 실행이
    #   ConnectToGripper DG_RESULT=500으로 거부된다(세션이 아직 물려 있어서). 실패는
    #   하드웨어를 건드리기 전에 나야 한다.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", args.listen))
    except OSError as e:
        sock.close()
        print(f"[오류] UDP :{args.listen} 바인드 실패 — {e}")
        print("       같은 포트를 듣는 브리지가 이미 떠 있을 가능성이 높다. 점유 프로세스 확인:")
        print("         Windows: powershell -Command "
              f"'Get-NetUDPEndpoint -LocalPort {args.listen} | Select-Object OwningProcess'")
        print(f"         Linux  : ss -lunp | grep :{args.listen}")
        return
    sock.settimeout(0.2)

    sdk = None
    if not dry:
        dll_path = os.path.abspath(args.dll)
        if not os.path.exists(dll_path):
            print(f"[오류] DLL 없음: {dll_path}")
            return
        sdk = Dg5fSdk(dll_path)
        print(f"[연결] {args.ip}:{args.port} model={args.model}(0x{MODELS[args.model]:X}) "
              f"DEVELOPER 모드")
        sdk.connect(args.ip, args.port, MODELS[args.model],
                    set_gains=args.set_gains, gain_p=args.gain_p, gain_d=args.gain_d,
                    gain_i=args.gain_i, gain_ilimit=args.gain_ilimit)
        if not args.set_gains:
            print("[게인] ⚠️ 게인을 넣지 않았다 — 실측상 이 상태에서는 실물이 전혀 움직이지 않는다. "
                  "--no-set-gains를 뺀 기본 동작을 쓸 것")
        if args.lpf > 0:
            sdk.dll.SetLowPassFilterAlpha(1, ctypes.c_float(args.lpf))
        print("[연결] SystemStart 완료")

        if args.jog is not None:
            run_jog(sdk, args)
            sdk.close()
            sock.close()
            return

        if args.pose is not None:   # 관절 대응 검증 모드 — 한 포즈 보내고 종료
            target = [0.0] * N_JOINTS
            for item in args.pose.split(","):
                i, d = item.split(":")
                target[int(i)] = float(d)
            print(f"[pose] MoveServoJoint {target}")
            sdk.servo(target)
            time.sleep(1.0)
            sdk.close()
            sock.close()
            return

    print(f"[수신] UDP :{args.listen} 대기 — vision_node_dg5f.py [left|right] --bridge 로 송신"
          + (" (드라이런: 실물 송신 없음)" if dry else ""))

    period = 1.0 / args.hz
    last_sent_t = 0.0
    # 슬루 리밋의 기준점. ★반드시 '실물의 현재 자세'로 시작해야 한다 (2026-08-31).
    #   None으로 두면 첫 패킷이 속도 제한을 그냥 통과해, 실물이 어떤 자세로 있든 Unity의
    #   기본 자세(대개 손 편 상태)로 **서보 최고 속도로 튄다**. 깊은 파지 자세에서 연결하면
    #   90° 가까이를 한 번에 튕기므로 물건을 놓치거나 손가락이 부딪힌다.
    #   실물 상태를 못 읽으면(드라이런 등) 어쩔 수 없이 None으로 두되, 그 사실을 알린다.
    last_cmd = None
    if not dry:
        for _ in range(50):
            last_cmd = sdk.read()
            if last_cmd is not None:
                break
            time.sleep(period)
        if last_cmd is None:
            print("[슬루] ⚠️ 실물 현재 자세를 읽지 못했습니다 — 첫 명령이 속도 제한 없이 나갑니다.")
        else:
            print(f"[슬루] 실물 현재 자세를 기준점으로 잡았습니다 "
                  f"(엄지 {last_cmd[0]:.1f}/{last_cmd[1]:.1f}°) — 여기서부터 서서히 이동합니다.")
    last_print = 0.0
    stale_warned = False
    teach_on = False        # Unity 제어 패킷으로 켜고 끈다 (real→sim 모드)

    if args.echo_to_unity:
        if args.echo_port == args.listen:
            print(f"[오류] --echo-port({args.echo_port})가 수신 포트와 같습니다 — 자기 자신에게 "
                  "되쏘는 무한 루프가 됩니다. 다른 포트를 지정하세요.")
            return
        if dry:
            print("[echo] 드라이런에서는 읽을 실물이 없어 되돌려 보낼 값도 없습니다.")
        else:
            print(f"[echo] 실물 실제각 → Unity {args.echo_ip}:{args.echo_port} 반사 "
                  "(Unity에서 Dg5fSender와 Dg5fHandDriver를 동시에 켜지 말 것 — 피드백 루프)")

    track_f = None
    track_ch = []
    track_t0 = None
    if args.track:
        if dry:
            print("[track] 드라이런에서는 실물 실제각을 읽을 수 없어 명령값만 기록됩니다.")
        track_path = Path(args.track)
        track_path.parent.mkdir(parents=True, exist_ok=True)
        track_f = open(track_path, "w", encoding="utf-8")
        track_f.write("t_sec," + ",".join(f"cmd_{n}" for n in CHANNEL_NAMES)
                      + "," + ",".join(f"act_{n}" for n in CHANNEL_NAMES) + "\n")
        try:
            track_ch = [int(x) for x in args.track_channels.split(",") if x.strip() != ""]
        except ValueError:
            track_ch = [0, 1]
        print(f"[track] 기록 시작: {track_path}  (실시간 표시 채널: "
              + ", ".join(f"[{i}]{CHANNEL_NAMES[i]}" for i in track_ch) + ")")
    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                stale_warned = False
            except socket.timeout:
                if not stale_warned and last_cmd is not None:
                    print("[hold] 패킷 끊김 — 마지막 자세 유지(실물은 위치 유지)")
                    stale_warned = True
                continue
            # ── Unity UI가 보내는 제어 패킷 ──────────────────────────────────
            # 관절 패킷(≥80바이트)과 길이로 구분된다. 이게 있어야 첫 사용자가 명령줄을 다시
            # 치지 않고 Unity 버튼만으로 sim→real / real→sim 방향을 바꿀 수 있다.
            #   b"DG5FMODE" + 1바이트 : 0 = sim→real(교시 해제, 서보 유지)
            #                           1 = real→sim(교시 모드 — 힘을 풀어 사람이 손으로 자세를 잡음)
            if data.startswith(CONTROL_MAGIC):
                if dry or len(data) < len(CONTROL_MAGIC) + 1:
                    continue
                want_teach = data[len(CONTROL_MAGIC)] == 1
                if want_teach != teach_on:
                    r = sdk.dll.ManualTeachMode(1 if want_teach else 0)
                    if r == DG_RESULT_NONE:
                        teach_on = want_teach
                        print(f"[모드] {'real→sim (교시 ON — 손으로 자세를 잡으세요)' if want_teach else 'sim→real (교시 OFF — Unity가 구동)'}")
                        # 교시에서 빠져나올 때 실물의 현재 자세를 명령 기준으로 삼는다.
                        # 안 그러면 교시 전 마지막 명령으로 홱 되돌아간다.
                        if not want_teach:
                            cur = sdk.read()
                            if cur is not None:
                                last_cmd = list(cur)
                    else:
                        print(f"[모드] ManualTeachMode 실패 DG_RESULT={r}")
                continue

            if len(data) < MIN_PACKET_BYTES:
                continue
            if teach_on:
                # 교시 중에는 Unity가 보낸 관절 명령을 실물에 쓰지 않는다(사람이 손으로 잡는 중).
                continue
            ours = struct.unpack_from(f"<{N_JOINTS}f", data)
            target = to_sdk_frame(ours, args.unmirror)

            now = time.time()
            if now - last_sent_t < period:
                continue
            # 슬루 리밋 — 트래킹 점프/오클루전 복귀 시 실물이 튀지 않게 틱당 변화 제한
            if last_cmd is not None and args.max_step > 0:
                step = args.max_step
                target = [p + min(step, max(-step, t - p))
                          for p, t in zip(last_cmd, target)]
            last_cmd = target
            last_sent_t = now

            if dry:
                if now - last_print >= 0.5:
                    print("[dry]", " ".join(f"{v:6.1f}" for v in target))
                    last_print = now
            else:
                res = sdk.servo(target)
                if res != DG_RESULT_NONE and now - last_print >= 0.5:
                    print(f"[경고] MoveServoJoint DG_RESULT={res}")
                    last_print = now

            # 실제각 읽기 — --track(기록)과 --echo-to-unity(트윈 반사)가 같은 값을 쓴다.
            actual = None
            if (track_f is not None or args.echo_to_unity) and not dry:
                actual = sdk.read()

            if args.echo_to_unity and actual is not None:
                # 실물 SDK 규약 → 우리(URDF/Unity) 규약으로 되돌린 뒤 송신 (thumb_opp 부호 등).
                echo = from_sdk_frame(actual)
                sock.sendto(struct.pack(f"<{N_JOINTS}f", *echo), (args.echo_ip, args.echo_port))

            if track_f is not None:
                # 명령 직후 같은 틱에 읽은 실제각. 명령과의 시간차가 곧 추종 지연이다.
                if track_t0 is None:
                    track_t0 = now
                rel = now - track_t0
                act_cols = (",".join(f"{v:.2f}" for v in actual) if actual
                            else ",".join([""] * N_JOINTS))
                track_f.write(f"{rel:.3f}," + ",".join(f"{v:.2f}" for v in target)
                              + "," + act_cols + "\n")
                if now - last_print >= 0.25:
                    parts = []
                    for i in track_ch:
                        if 0 <= i < N_JOINTS:
                            a = f"{actual[i]:6.1f}" if actual else "   ---"
                            parts.append(f"[{i}]{CHANNEL_NAMES[i]:<10} 명령{target[i]:6.1f} 실제{a}")
                    print(f"[track {rel:5.2f}s] " + "  |  ".join(parts))
                    last_print = now
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        if track_f is not None:
            track_f.close()
            summarize_track(args.track)
        if sdk is not None and teach_on:
            # 교시 모드를 켠 채 끊으면 손이 힘 풀린 상태로 남는다 — 반드시 해제.
            sdk.dll.ManualTeachMode(0)
            print("[모드] 교시 모드 해제")
        if sdk is not None:
            sdk.close()
            print("[종료] SystemStop + Disconnect 완료")


def run_jog(sdk, args):
    """관절 하나만 슬루 리밋으로 천천히 움직였다가 원위치 — 어느 모터가 실제로 응답하는지 가린다.

    --pose와 달리 ① 나머지 관절을 0으로 밀지 않고 현재 자세를 유지하며(엉뚱한 관절이 같이
    움직여 판단을 흐리지 않게) ② 목표를 한 번에 던지지 않고 서서히 올리고 ③ 끝나면 출발점으로
    되돌린 뒤 SystemStop한다. --pose는 큰 값을 즉시 던지고 1초 만에 시스템을 껐기 때문에
    '안 움직임'이 관절 탓인지 명령 방식 탓인지 구분할 수 없었다.
    """
    try:
        idx_s, deg_s = args.jog.split(":")
        idx, goal = int(idx_s), float(deg_s)
    except ValueError:
        print(f"[jog] 형식 오류: --jog IDX:DEG (예: --jog 0:40). 받은 값: {args.jog!r}")
        return
    if not 0 <= idx < N_JOINTS:
        print(f"[jog] IDX는 0~{N_JOINTS - 1} 범위여야 합니다.")
        return

    lo, hi = JOINT_CLAMP[idx]
    clamped = min(hi, max(lo, goal))
    if clamped != goal:
        print(f"[jog] 목표 {goal:.1f}° → 하드웨어 범위 [{lo:.0f},{hi:.0f}]로 클램프: {clamped:.1f}°")
    goal = clamped

    start = None
    for _ in range(50):                       # 실제 자세를 잡을 때까지 잠깐 대기
        start = sdk.read()
        if start is not None:
            break
        time.sleep(1.0 / args.hz)
    if start is None:
        print("[jog] 실물 상태를 읽지 못했습니다 — 중단합니다.")
        return

    print(f"[jog] [{idx}] {CHANNEL_NAMES[idx]} : {start[idx]:.1f}° → {goal:.1f}° "
          f"(나머지 19관절은 현재 자세 유지, 틱당 {args.max_step:.2f}°)")
    print(f"{'t':>6} {'명령':>8} {'실제':>8} {'차이':>8} {'전류mA':>8}")
    peak_current = 0

    period = 1.0 / args.hz
    cmd = list(start)
    t0 = time.time()

    def ramp_to(target_deg, hold_sec, phase):
        nonlocal peak_current
        peak_actual, act = start[idx], None
        while True:
            d = target_deg - cmd[idx]
            cmd[idx] += max(-args.max_step, min(args.max_step, d))
            sdk.servo(cmd)
            time.sleep(period)
            act, cur, errcode = sdk.read_diag()
            now = time.time() - t0
            if act is not None:
                peak_actual = max(peak_actual, act[idx], key=lambda v: abs(v - start[idx]))
                ma = cur[idx] if cur else 0
                peak_current = max(peak_current, abs(ma))
                print(f"{now:6.2f} {cmd[idx]:8.1f} {act[idx]:8.1f} "
                      f"{act[idx] - cmd[idx]:8.1f} {ma:8d}")
                if errcode:
                    print(f"[jog] ⚠️ moduleErrorCode={errcode} (부록 2 에러 리스트 참조)")
            if abs(target_deg - cmd[idx]) < 1e-6:
                break
        # 목표 도달 후 유지 — 서보가 뒤늦게 따라오는지 본다
        hold_until = time.time() + hold_sec
        while time.time() < hold_until:
            sdk.servo(cmd)
            time.sleep(period)
            act, cur, _ = sdk.read_diag()
            if act is not None:
                peak_actual = max(peak_actual, act[idx], key=lambda v: abs(v - start[idx]))
                if cur:
                    peak_current = max(peak_current, abs(cur[idx]))
        if act is not None:
            print(f"[jog] {phase} 종료 — 명령 {cmd[idx]:.1f}° / 실제 {act[idx]:.1f}°")
        return peak_actual

    peak = ramp_to(goal, args.jog_hold, "전진")
    moved = abs(peak - start[idx])
    asked = abs(goal - start[idx])
    ramp_to(start[idx], 0.5, "복귀")

    print("-" * 50)
    print(f"[jog] 요구 이동량 {asked:.1f}° / 실제 최대 이동량 {moved:.1f}° "
          f"= 도달률 {(moved / asked * 100 if asked > 1e-6 else 0):.0f}%   "
          f"최대 전류 {peak_current} mA")
    if asked > 5.0 and moved < asked * 0.1:
        print(f"[jog] ★ [{idx}] {CHANNEL_NAMES[idx]}는 단독으로도 응답하지 않는다 "
              "— 다른 관절과의 간섭이 아니다.")
        # 전류가 원인을 가른다. 임계 50mA는 '유의미하게 힘을 쓰는 중'의 대략적 기준이며
        # 실측으로 조정할 것(정격 전류는 하드웨어 설명서 §3.1 참조).
        if peak_current > 50:
            print(f"[jog]   전류는 {peak_current} mA 흐른다 → 구동은 되는데 못 움직이는 것이다. "
                  "토크 한계이거나 기구적으로 물려 있다. 하드웨어 설명서가 말하는 "
                  "'Torque limit mode'(SetTorqueLimitMode) 확인 대상.")
        else:
            print(f"[jog]   전류가 거의 없다({peak_current} mA) → 애초에 구동 명령이 그 모터에 "
                  "닿지 않는다. 채널 매핑이나 모터/모듈 이상 쪽이다.")
    elif asked > 5.0 and moved < asked * 0.7:
        print(f"[jog] [{idx}] {CHANNEL_NAMES[idx]}는 움직이지만 목표에 못 미친다 "
              f"(최대 전류 {peak_current} mA) — 부하·토크 한계이거나 기구적으로 막혀 있다.")
    else:
        print(f"[jog] [{idx}] {CHANNEL_NAMES[idx]}는 정상 응답한다.")


def summarize_track(path):
    """--track CSV에서 채널별 '움직이기 시작한 시각'과 '도착 시각'을 뽑는다.

    '엄지 X축이 먼저 움직이고 Y축이 나중에 움직인다'가 정말 순차 동작인지, 아니면 같이
    출발해서 이동량 차이로 도착만 늦는 것인지 구분하려고 만들었다. 전자면 start_t가 서로
    다르고, 후자면 start_t는 같은데 end_t만 다르다.
    """
    MOVE_EPS = 1.0        # 이 각도[deg] 이상 움직였으면 '움직였다'로 본다 (센서 노이즈 ±0.3)
    try:
        rows = [l.rstrip("\n").split(",") for l in open(path, encoding="utf-8")]
    except OSError as e:
        print(f"[track] 요약 실패 — {e}")
        return
    if len(rows) < 3:
        print("[track] 표본이 너무 적어 요약을 건너뜁니다.")
        return
    hdr, data = rows[0], rows[1:]

    def col(name):
        try:
            j = hdr.index(name)
        except ValueError:
            return None
        out = []
        for r in data:
            if j >= len(r) or r[j] == "":
                out.append(None)
            else:
                try:
                    out.append(float(r[j]))
                except ValueError:
                    out.append(None)
        return out

    ts = [float(r[0]) for r in data]
    print(f"\n[track] 요약 — {path}  ({len(data)}틱, {ts[-1]:.2f}초)")
    # '최대오차'는 이동 중 순간 지연까지 포함하므로 "늦게라도 도달"과 "끝내 미도달"을 못 가른다.
    # '최종오차'(마지막 샘플의 명령-실제 차)가 그 구분을 해준다.
    print(f"{'채널':<12} {'이동량':>8} {'명령시작':>9} {'실제시작':>9} {'실제도착':>9} "
          f"{'최대오차':>9} {'도달률':>9}")
    print("-" * 74)
    for n in CHANNEL_NAMES:
        cmd, act = col(f"cmd_{n}"), col(f"act_{n}")
        if not cmd:
            continue
        c0 = cmd[0]
        travel = max(abs(c - c0) for c in cmd)
        if travel < MOVE_EPS:
            continue                      # 안 움직인 채널은 표에서 뺀다
        # ⚠️ 기준 시각은 반드시 '명령이 움직이기 시작한 순간'이어야 한다. t=0을 기준으로 삼으면
        #   직전 실행이 남긴 자세나 연결 직후 정착 노이즈가 '실제시작'으로 잡혀,
        #   명령보다 먼저 움직인 것처럼 보인다(2026-08-31 실측에서 명령 3.68s / 실제 0.04s로 나옴).
        cs_i = next((k for k, c in enumerate(cmd) if abs(c - c0) >= MOVE_EPS), None)
        cs = ts[cs_i] if cs_i is not None else None
        # 명령 시작 이후 구간만 본다 (인덱스로 자른다 — 시각 값으로 되찾으면 중복 시각에서 틀린다).
        start_i = cs_i if cs_i is not None else 0
        pairs = ([(t, a, c) for t, a, c in
                  zip(ts[start_i:], act[start_i:], cmd[start_i:]) if a is not None]
                 if act else [])
        if pairs:
            a_ref = pairs[0][1]                       # 명령 시작 시점의 실제각 = 출발점
            as_ = next((t for t, a, _ in pairs if abs(a - a_ref) >= MOVE_EPS), None)
            final = cmd[-1]
            ae = next((t for t, a, _ in pairs if abs(a - final) <= MOVE_EPS), None)
            err = max(abs(a - c) for _, a, c in pairs)
            # ★'도달률' = 실제로 움직인 폭 / 명령이 요구한 폭.
            #   '최종오차'만 보면 안 되는 이유(2026-08-31에 실제로 오판함): 주먹 쥐었다 펴는
            #   왕복 동작에서는 끝에 명령도 실제도 출발점으로 돌아오므로, 그 관절이 한 번도
            #   움직이지 않았어도 최종오차가 작게 나온다. 실제로 thumb_opp가 명령 80°에 내내
            #   2~3°였는데 최종오차는 2.3으로 '정상'처럼 보였다. 도달률은 그 경우 ~1%로 드러난다.
            a_travel = max(a for _, a, _ in pairs) - min(a for _, a, _ in pairs)
            reach = (a_travel / travel * 100.0) if travel > 1e-6 else None
        else:
            as_ = ae = err = reach = None
        fmt = lambda v: f"{v:9.2f}" if v is not None else "        -"
        flag = "  ← 무응답" if (reach is not None and reach < 10.0) else ""
        rch = f"{reach:8.0f}%" if reach is not None else "        -"
        print(f"{n:<12} {travel:8.1f} {fmt(cs)} {fmt(as_)} {fmt(ae)} {fmt(err)} {rch}{flag}")
    print("-" * 74)
    print("[track] 해석")
    print("  · '실제시작'이 채널마다 크게 다르면 실물이 순차로 움직이는 것,")
    print("    비슷한데 '실제도착'만 다르면 같이 출발해 이동량 차이로 늦는 것이다")
    print("    (후자라면 Unity도 등속 슬루를 쓰므로 이미 같은 프로파일).")
    print("  · '실제시작'이 '-'인 채널은 **아예 응답하지 않은** 것이다 — 게인 부족이나 기구 간섭.")
    print("  · '도달률'이 핵심 지표다 — 실제로 움직인 폭 / 명령이 요구한 폭. 왕복 동작에서는")
    print("    한 번도 안 움직인 관절도 끝에는 제자리라 '오차'가 작게 보이므로 도달률로 판단할 것.")
    print("  · 주먹 포즈는 손가락이 손바닥·서로에 닿아 물리적으로 목표각까지 못 가는 게 정상이라,")
    print("    접촉 이후의 잔류 오차는 오차가 아니라 구속으로 봐야 한다.")


if __name__ == "__main__":
    main()
