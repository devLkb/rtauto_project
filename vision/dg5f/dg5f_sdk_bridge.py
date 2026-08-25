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
  python dg5f_sdk_bridge.py                          # 드라이런 — DLL 안 씀, 수신값만 출력(패킷 경로 검증)
  python dg5f_sdk_bridge.py --ip 169.254.186.72      # 실물 연결 (기본 모델 5f_left)
  python dg5f_sdk_bridge.py --ip <IP> --model 5f_right --unmirror
      --unmirror: vision_node를 left로 돌리면서(왼손 Unity 트윈) 실물이 오른손일 때 —
                  왼손 미러 채널 부호를 되돌려 오른손 규약으로 변환
  종료: Ctrl+C (SystemStop + Disconnect 자동)

⚠️ 첫 실물 구동 전 필수 확인 (모르면 움직이지 말 것):
  1. JOINT_ORDER/JOINT_SIGN/JOINT_OFFSET_DEG — 우리 채널(엄지1_1..새끼5_4, URDF 기준)과
     실물 관절 번호·방향·영점 대응은 **미검증**. --pose 로 한 관절씩 살살 보내며 확정할 것.
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
from config.rtauto_config import PORT_DG5F_BRIDGE, DG5F_DLL as CONFIG_DG5F_DLL

# ---------------- 우리 패킷 계약 (dg5f_angles와 동일) ----------------
N_JOINTS = 20
MIN_PACKET_BYTES = 4 * N_JOINTS          # v1(<20f>) 이상이면 앞 20f만 사용 (수신기 관례와 동일)
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

# ---------------- 우리 채널 → SDK float[20] 대응 (⚠️ 실물 검증 전 잠정) ----------------
# SDK 배열은 손가락당 4개 × 5그룹(F1..F5, 샘플 MoveJointFinger 참조). F1=엄지로 가정
# (DG_GRASP_MODE_5F_2FINGER_1_AND_2 = 엄지+검지 핀치 → F1이 엄지) — 우리 순서와 같으면 항등.
JOINT_ORDER = list(range(20))            # sdk[i] = ours[JOINT_ORDER[i]]
JOINT_SIGN = [1.0] * 20                  # 방향 반대 관절은 -1로
JOINT_OFFSET_DEG = [0.0] * 20            # 영점 차이는 여기로 (sdk = sign*ours + offset)
# 안전 클램프 — URDF 리밋보다 넉넉하되 물리 밖 금지. 실물 리밋 확인 후 좁힐 것.
JOINT_CLAMP = [(-130.0, 130.0)] * 20

# ---------------- SDK ctypes 바인딩 (DGDataTypes.h 레이아웃 그대로) ----------------
# RTAUTO_DG5F_DLL(.env)로 오버라이드 가능 — 없으면 스크립트 기준 상대경로 기본값 사용.
DEFAULT_DLL = CONFIG_DG5F_DLL or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "태슬로sdk", "DGSDKSample_ver_2_0_1", "DGSDK", "DGSDK.dll")
DG_RESULT_NONE = 0
CONTROL_MODE_DEVELOPER = 1
COMMUNICATION_MODE_ETHERNET = 0
DEVELOPER_MODE_RECEIVED_DATA_TYPE_JOINT = 0x01
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

    def _check(self, name, res):
        if res != DG_RESULT_NONE:
            raise RuntimeError(f"{name} 실패 — DG_RESULT={res} (DGDataTypes.h 참조)")

    def connect(self, ip, port, model_code):
        sys_set = GripperSystemSetting()
        sys_set.comport = b"COM1"                  # Ethernet 모드에선 미사용(샘플 관례)
        sys_set.ip = ip.encode("ascii")
        sys_set.port = port
        sys_set.readTimeout = 1000
        sys_set.controlMode = CONTROL_MODE_DEVELOPER   # MoveServoJoint 필수 조건
        sys_set.communicationMode = COMMUNICATION_MODE_ETHERNET
        sys_set.slaveID = 1
        sys_set.baudrate = 115200
        self._check("SetGripperSystem", self.dll.SetGripperSystem(sys_set))

        self._check("ConnectToGripper", self.dll.ConnectToGripper())

        opt = GripperSetting()                     # 배열들은 ctypes가 0으로 초기화
        opt.model = model_code
        opt.movingInpose = 0.4
        opt.receivedDataType[0] = DEVELOPER_MODE_RECEIVED_DATA_TYPE_JOINT
        self._check("SetGripperOption", self.dll.SetGripperOption(opt))

        # 샘플(GripperConnect)과 동일한 보수적 게인 — 실물 튜닝은 별도
        self.dll.SetJointGainPIDAllEqual(1.0, 5.0, 0.05, 0.1)
        self._check("SystemStart", self.dll.SystemStart())

    def servo(self, deg20):
        arr = (ctypes.c_float * 20)(*deg20)
        return self.dll.MoveServoJoint(arr)

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


def main():
    ap = argparse.ArgumentParser(description="DG-5F 실물 SDK 브리지")
    ap.add_argument("--ip", default=None, help="그리퍼 IP — 생략 시 드라이런(수신값 출력만)")
    ap.add_argument("--port", type=int, default=502, help="그리퍼 Modbus TCP 포트 (기본 502)")
    ap.add_argument("--model", default="5f_left", choices=sorted(MODELS),
                    help="실물 모델 (기본 5f_left)")
    ap.add_argument("--listen", type=int, default=PORT_DG5F_BRIDGE,
                    help=f"UDP 수신 포트 (vision_node --bridge와 동일해야 함, 기본 {PORT_DG5F_BRIDGE})")
    ap.add_argument("--dll", default=DEFAULT_DLL, help="DGSDK.dll 경로")
    ap.add_argument("--hz", type=float, default=50.0, help="실물 송신 상한 Hz (기본 50)")
    ap.add_argument("--max-step", type=float, default=2.0,
                    help="틱당 관절 최대 변화량[deg] — 점프 방지 슬루 리밋 (기본 2.0)")
    ap.add_argument("--lpf", type=float, default=0.3,
                    help="SDK 내장 저역필터 alpha (0=사용 안 함, 기본 0.3)")
    ap.add_argument("--unmirror", action="store_true",
                    help="왼손 스트림(vision_node left)을 오른손 실물 규약으로 부호 변환")
    ap.add_argument("--pose", default=None,
                    help="검증용 1회 포즈: 'idx:deg[,idx:deg...]' 나머지 0으로 MoveServoJoint 후 종료. "
                         "예) --pose 6:20 (검지 pip만 20°)")
    args = ap.parse_args()

    dry = args.ip is None
    sdk = None
    if not dry:
        dll_path = os.path.abspath(args.dll)
        if not os.path.exists(dll_path):
            print(f"[오류] DLL 없음: {dll_path}")
            return
        sdk = Dg5fSdk(dll_path)
        print(f"[연결] {args.ip}:{args.port} model={args.model}(0x{MODELS[args.model]:X}) "
              f"DEVELOPER 모드")
        sdk.connect(args.ip, args.port, MODELS[args.model])
        if args.lpf > 0:
            sdk.dll.SetLowPassFilterAlpha(1, ctypes.c_float(args.lpf))
        print("[연결] SystemStart 완료")

        if args.pose is not None:   # 관절 대응 검증 모드 — 한 포즈 보내고 종료
            target = [0.0] * N_JOINTS
            for item in args.pose.split(","):
                i, d = item.split(":")
                target[int(i)] = float(d)
            print(f"[pose] MoveServoJoint {target}")
            sdk.servo(target)
            time.sleep(1.0)
            sdk.close()
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.listen))
    sock.settimeout(0.2)
    print(f"[수신] UDP :{args.listen} 대기 — vision_node_dg5f.py [left|right] --bridge 로 송신"
          + (" (드라이런: 실물 송신 없음)" if dry else ""))

    period = 1.0 / args.hz
    last_sent_t = 0.0
    last_cmd = None          # 슬루 리밋 기준 (첫 패킷은 그대로 통과)
    last_print = 0.0
    stale_warned = False
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
            if len(data) < MIN_PACKET_BYTES:
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
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        if sdk is not None:
            sdk.close()
            print("[종료] SystemStop + Disconnect 완료")


if __name__ == "__main__":
    main()
