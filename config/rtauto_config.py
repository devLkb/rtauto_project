# -*- coding: utf-8 -*-
"""프로젝트 전역 설정 레지스트리 — IP/포트/경로를 절대 다른 파일에 리터럴로 복사하지 말고
항상 여기서 읽을 것.

값 우선순위: 환경변수 > 레포 루트 .env(git 비추적) > 아래 기본값.
.env 작성법은 .env.example 참고 — 복사해서 .env로 저장하고 필요한 값만 채우면 된다.

이 파일 자체를 리터럴 IP/포트의 유일한 출처로 유지한다: 새 포트가 필요하면 여기 추가하고
다른 파일에서는 import해서 쓴다 (숫자를 다시 타이핑하지 않는다).
"""
import os
import sys
from pathlib import Path

# PyInstaller로 얼린 실행파일(예: vision_node_dg5f.exe)에서는 __file__이 압축 해제된
# 임시 폴더(sys._MEIPASS)를 가리켜 실제 배포 폴더와 무관해진다. 그 경우 exe 파일이
# 실제로 놓인 디렉터리를 기준으로 삼는다 — Unity 쪽 RtautoConfig.cs가 빌드된
# .exe 옆(Application.dataPath 기준)에서 .env를 찾는 것과 같은 관례를 맞춘 것.
if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys.executable).resolve().parent
else:
    REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    # 우선순위: 프로세스 환경변수 > .env > .env.example (.env.example 헤더가 명시한 계약).
    # setdefault라 먼저 넣은 값이 이긴다 → .env를 .env.example보다 먼저 읽는다.
    # .env.example까지 읽는 덕분에 새 PC에서 `cp .env.example .env` 없이도 공유 기본값이
    # 그대로 적용된다 — 웹캠만 꽂고 바로 시연하는 흐름에 필요하다.
    # Unity 쪽(Assets/Scripts/RtautoConfig.cs, MLAgents/Editor/BuildEnvironment.cs)도
    # 같은 두 파일을 같은 순서로 읽는다. 세 리더가 어긋나면 안 된다.
    for name in (".env", ".env.example"):
        _merge_dotenv(REPO_ROOT / name)


def _merge_dotenv(env_path):
    if not env_path.is_file():
        return
    # utf-8-sig: Windows 메모장/PowerShell Set-Content가 BOM을 붙여 저장하는 일이 잦은데,
    # BOM이 남으면 첫 줄 키가 '﻿RTAUTO_...'가 돼 조용히 무시된다.
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Linux/macOS 사용자가 습관적으로 붙이는 `export KEY=value`도 받아준다.
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        # 따옴표로 감싼 값에서 따옴표를 벗긴다 — 안 벗기면 경로/IP에 " 가 섞여 들어간다.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def _env(name, default=""):
    return os.environ.get(name, default)


# ---------------- 네트워크 (Unity ↔ Python vision 스크립트) ----------------
UNITY_IP = _env("RTAUTO_UNITY_IP", "127.0.0.1")

# Unity(Assets/Scripts/Dg5fSender.cs)가 실물 SDK 브리지로 관절각을 쏠 때의 대상 IP.
# UNITY_IP의 반대 방향이다 — 저건 "Unity가 어디 있나", 이건 "dg5f_sdk_bridge.py가 어디 있나".
# 보통 Unity와 브리지를 같은 PC에서 돌리므로 기본값이 로컬이다.
DG5F_BRIDGE_IP = _env("RTAUTO_DG5F_BRIDGE_IP", "127.0.0.1")

# 실물 DG-5F 그리퍼 자신의 IP (링크로컬 — 그리퍼용 이더넷에 꽂았을 때만 도달 가능).
# 기본값 없음: 머신·배선마다 다르고, 틀린 IP로 조용히 시도하면 원인 파악이 어렵다.
DG5F_IP = _env("RTAUTO_DG5F_IP", "")


def resolve_gripper_ip(value):
    """브리지 스크립트들의 `--ip` 인자 해석 — 세 브리지가 같은 규칙을 공유한다.

      None  → 드라이런 (실물 미접속, 수신값만 출력)
      ""    → 값 없이 `--ip`만 준 경우 → 위 DG5F_IP(.env의 RTAUTO_DG5F_IP)
      그 외 → 명시한 IP (일회성 실험·다른 그리퍼)

    ⚠️ `--ip`를 아예 생략했을 때만 드라이런이다. `--ip`를 줬는데 .env가 비어 있으면
    조용히 드라이런으로 빠지지 않고 ValueError를 낸다 — 그렇지 않으면 "실물이 안
    움직인다"로 오해하고 하드웨어를 의심하게 된다.
    """
    if value != "":
        return value
    if not DG5F_IP:
        raise ValueError(
            "--ip를 값 없이 줬지만 .env의 RTAUTO_DG5F_IP가 비어 있다 — "
            ".env에 RTAUTO_DG5F_IP=<그리퍼 IP>를 넣거나 --ip <IP>로 직접 줄 것")
    return DG5F_IP

# UDP 포트 레지스트리 — 각 포트는 이 파일에서만 숫자로 정의한다. 새로 포트를 쓸 일이 생기면
# 여기부터 확인해서 겹치지 않는 번호를 고를 것 (과거 DG5F 실물 브리지와 ZED 좌표 송신이
# 둘 다 5007을 써서 같은 PC에서 동시 실행 시 UDP 바인드 충돌이 나는 문제가 있었다 — 2026-08-25 수정).
PORT_SVH_JOINTS = int(_env("RTAUTO_PORT_SVH_JOINTS", "5005"))    # 레거시 SVH 손 관절 트윈
PORT_DG5F_SIM = int(_env("RTAUTO_PORT_DG5F_SIM", "5006"))        # → Unity Dg5fReceiver (DG5F 손 관절 트윈)
PORT_ZED_TARGET = int(_env("RTAUTO_PORT_ZED_TARGET", "5007"))    # ⛔ 폐기 — ZED 객체 검출 경로 전용.
# vision/zed_object_detection/은 더 이상 쓰지 않는다(수신 측 Unity CameraTargetReceiver.cs도 이미 삭제됨).
# 과거 포트 충돌 이력이 있으니 이 번호를 다른 용도로 재사용하지 말 것. 상세: vision/zed_object_detection/DEPRECATED.md
PORT_DG5F_BRIDGE = int(_env("RTAUTO_PORT_DG5F_BRIDGE", "5008"))  # vision_node --bridge → dg5f_sdk_bridge.py (실물 SDK)
PORT_UR_ARM_BRIDGE = int(_env("RTAUTO_PORT_UR_ARM_BRIDGE", "5009"))  # Unity UrArmSender → arm/ur_rtde_bridge.py
PORT_UR_ARM_SIM = int(_env("RTAUTO_PORT_UR_ARM_SIM", "5010"))    # arm/ur_rtde_bridge.py --echo-to-unity → Unity UrArmReceiver (팔 관절 트윈)

# ---------------- UR16e RTDE (URSim/실물 팔) ----------------
# URSim을 도커로 로컬 실행하면 포트가 호스트로 매핑돼 PC 입장에서는 127.0.0.1로 보인다
# (docs/SIM2REAL_ROADMAP.md §9 "URSim 선행 개발 경로" 참고) — 그래서 다른 IP 키(DG5F_IP 등)와
# 달리 기본값을 비워두지 않는다. 실물로 전환할 때는 .env의 RTAUTO_UR_IP만 실제 컨트롤박스
# IP로 바꾸면 되고, 그 외 코드는 그대로다(원칙 1이 이 전환의 성립 조건).
UR_IP = _env("RTAUTO_UR_IP", "127.0.0.1")


def resolve_ur_ip(value):
    """arm/ur_rtde_bridge.py의 `--ip` 인자 해석 — resolve_gripper_ip와 같은 규칙.

      None  → 드라이런 (RTDE 미접속, 수신값만 출력)
      ""    → 값 없이 `--ip`만 준 경우 → 위 UR_IP(.env의 RTAUTO_UR_IP, 기본 127.0.0.1=URSim 로컬)
      그 외 → 명시한 IP (실물 컨트롤박스 등)
    """
    return UR_IP if value == "" else value


# 공용 venv의 파이썬 실행 파일. Unity의 UrArmBridgeLauncher("UR16e 팔" 패널의 "브리지 실행"
# 버튼)가 이 값으로 arm/ur_rtde_bridge.py를 직접 띄운다 — 사람이 터미널을 하나 더 열어
# venv를 활성화하는 단계를 없애기 위한 것.
# 비워두면 양쪽(파이썬/Unity)이 각자 OS에 맞는 공용 venv 기본 경로를 쓴다
# (docs/PYTHON_ENV_SETUP.md §2의 vision/.vision). 다른 venv를 쓰면 .env에서 덮어쓸 것.
PYTHON_EXE = _env("RTAUTO_PYTHON", "")


def python_exe():
    """공용 venv 파이썬의 절대경로. 상대경로는 저장소 루트 기준으로 해석한다.

    Unity 쪽 UrArmBridgeLauncher.cs가 같은 키(RTAUTO_PYTHON)와 같은 OS별 기본값을 쓴다 —
    한쪽만 고치면 "터미널에서는 되는데 버튼으로는 안 된다"가 되므로 함께 고칠 것.
    """
    if PYTHON_EXE:
        path = Path(PYTHON_EXE)
        return path if path.is_absolute() else (REPO_ROOT / path)
    relative = ("vision/.vision/Scripts/python.exe" if sys.platform.startswith("win")
                else "vision/.vision/bin/python")
    return REPO_ROOT / relative


# UR16e 관절 각속도 상한[deg/s] — ur_rtde_bridge.py가 틱당 슬루 리밋으로 환산해 URSim/실물
# 급격한 목표 점프를 막는다. ⚠️ DG5F_MAX_DEG_PER_SEC과 달리 **실측 근거 없음** — UR16e
# 카탈로그상 관절 최고속도(대략 120 deg/s대, 관절별로 다름)의 한참 아래로 잡은 보수적
# 추정 초기값이다. 실물/URSim에서 --track 유사 검증 후 조정할 것.
UR_MAX_DEG_PER_SEC = float(_env("RTAUTO_UR_MAX_DEG_PER_SEC", "30"))

# ML-Agents 트레이너 <-> Unity 플레이어 gRPC 포트의 시작값. --num-envs N이면
# BASE..BASE+N-1을 쓴다. 위 UDP 레지스트리(5005~5008)와 겹치지 않게 5100부터 잡았다 —
# 프로토콜이 달라 충돌하진 않지만, 포트 하나를 두 용도로 문서화하면 다음 사람이 헷갈린다.
PORT_MLAGENTS_BASE = int(_env("RTAUTO_PORT_MLAGENTS_BASE", "5100"))

# ---------------- DG5F 손 관절 속도 한계 ----------------
# 실물 DG-5F가 안전하게 따라올 수 있는 관절 각속도 상한[deg/s]. 두 곳이 이 값을 공유한다:
#   1) vision/dg5f/dg5f_sdk_bridge.py — 틱당 슬루 리밋(= 이 값 / 송신 Hz)으로 환산해 실물 보호
#   2) unity/Assets/MLAgents/picknplace/Runtime/Dg5fFistButton.cs — Unity 트윈도 같은 속도로 제한
# 왜 Unity에도 거는가: 트윈의 목적이 "시뮬과 실물이 서로를 검증하는 것"인데, 시뮬이 실물보다
# 빠르게 움직이면 시뮬에서 성공한 파지가 실물에서 실패하는 것을 잡아내지 못한다. 나중에 RL
# 정책을 실물에 올릴 때도 같은 간극이 그대로 문제가 된다(로드맵 Phase 2 도메인 랜덤화 항목).
# 근거: 하드웨어 설명서 §3.1 각 관절 무부하 속도 75 RPM = 450 deg/s. 부하·마찰·보수적 PID
# 게인을 감안해 그 1/4 이하로 잡은 보수적 초기값이다. 실물이 튀지 않으면 조금씩 올려도 된다.
DG5F_MAX_DEG_PER_SEC = float(_env("RTAUTO_DG5F_MAX_DEG_PER_SEC", "100"))

# ---------------- DG5F 파지 자세(티칭) ----------------
# 실물 손을 사람이 직접 원하는 파지 자세로 잡아놓고 그 관절각을 캡처해 저장하는 파일.
#   쓰기: vision/dg5f/dg5f_readback_bridge.py --capture-pose
#   읽기: unity/.../Dg5fFistButton.cs 의 "파지하기" 버튼
# 주먹(Dg5fPicknPlaceSpec.RightFistDeg)은 코드에 박힌 상수지만, 파지 자세는 대상 물체마다
# 달라지므로(종이컵/FOUP 손잡이/…) 코드가 아니라 이 파일로 뺀다. 값은 **우리 규약**
# (URDF/Unity 기준, deg) — 실물 SDK 규약과의 부호 차이는 캡처할 때 이미 변환된다.
DG5F_GRASP_POSE_FILE = _env("RTAUTO_DG5F_GRASP_POSE", "config/dg5f_grasp_pose.json")

# ---------------- DG5F 접촉 감지 (손끝 센서가 없어서 대신 쓰는 것) ----------------
# 🛑 이 손에는 **손끝 힘·촉감 센서가 없다**(CLAUDE.md 하드웨어 표). 그래서 "물체에 닿았다"를
# 직접 읽을 수 없고, 관절마다 들어오는 세 가지로 **추정**한다:
#   1) 모터 전류(mA)  — 뭔가에 막히면 올라간다
#   2) 시킨 각도와 실제 각도의 차이(deg) — 막히면 시킨 데까지 못 간다
#   3) 관절 속도(rpm) — 막히면 멈춘다
# 단위 근거: vendor/dgsdk-python/libs/DGDataTypes.h §ReceivedGripperData
#   (joint=degree, current=mA, velocity=rpm, temperature=°C).
#
# ⚠️ **아래 숫자는 전부 실측 전 잠정값이다.** 실물에 붙여 재기 전에는 믿지 마라.
#    전류 기준값(무부하 전류)은 관절마다·각도마다 다르므로 **숫자 하나로 못 박지 않는다** —
#    hand/measure_baseline.py 로 재서 파일(DG5F_BASELINE_FILE)로 만들고, 여기 값들은
#    "그 기준값에서 얼마나 벗어나야 접촉으로 볼지"의 배수·여유로만 쓴다.
#    설계 정본: docs/GRASP_CONTACT_DETECTION.md

# ---------------- "좋은 자세" 를 고르는 기준 ----------------
# 잡은 뒤 물체가 손 안에서 돌아간 각도(도)가 이 값 이하여야 **고를 만한 자세**로 본다.
#
# ⚠️ **성공/실패 판정은 이것과 무관하다.** 시뮬레이터의 성공 기준(손끝 3개 접촉 + 물체가
#    손 중심 근처 유지)은 그대로 두고, 이 값은 **성공한 자세들 중에서 어느 것을 고를지**
#    에만 쓴다 (2026-09-18 사용자 결정). 그래야 예전 결과와 계속 비교할 수 있다.
#
# 쓰는 곳: superdex/scripts/{build_pose_dataset,train_pose_predictor,pose_score_sweep,
#          watch_grasp}.py — 네 군데가 이 값 하나를 본다(숫자를 베끼지 않는다).
#
# 실측 근거 (2026-09-18, 물체 9종 324칸):
#   기울기 안 봄  -> 좋은 자세 124칸(38%), 물체별 최소  6개
#   5도 이하      -> 좋은 자세  42칸(13%), 물체별 최소  2개   <- 지금 값
#   8도 이하      -> 좋은 자세  63칸(19%), 물체별 최소  4개
#   10도 이하     -> 좋은 자세  85칸(26%), 물체별 최소  4개
# 성공한 자세 전체의 중앙값이 8도이고, 물체 9종 모두 **0~3도짜리 자세를 하나씩은** 갖고
# 있다. 5도는 "거의 안 돌아감" 에 해당한다.
# 👉 학습이 표본 부족으로 안 되면 **여기부터 8~10도로 올려 본다.**
GRASP_GOOD_TILT_DEG = float(_env("RTAUTO_GRASP_GOOD_TILT_DEG", "5.0"))

#: 무부하 전류 기준표. hand/measure_baseline.py 가 만든다. **없으면 접촉 감지를 거부한다.**
DG5F_BASELINE_FILE = _env("RTAUTO_DG5F_BASELINE", "config/dg5f_current_baseline.json")

#: 접촉으로 보려면 전류가 기준값에서 "흔들림의 몇 배" 이상 올라야 하는가.
#: 크게 잡으면 살짝 닿은 것을 놓치고, 작게 잡으면 마찰만으로 오판한다.
DG5F_CONTACT_CURRENT_SIGMA = float(_env("RTAUTO_DG5F_CONTACT_CURRENT_SIGMA", "6"))

#: 위 배수와 별개로 **무조건 넘어야 하는 전류 증가분(mA)**. 흔들림이 0에 가까운 관절에서
#: 잡음만으로 기준을 넘는 것을 막는 바닥값이다.
DG5F_CONTACT_CURRENT_FLOOR_MA = float(_env("RTAUTO_DG5F_CONTACT_CURRENT_FLOOR_MA", "80"))

#: 시킨 각도와 실제 각도가 이만큼(deg) 이상 벌어져야 "못 가고 있다"로 본다.
#: ⚠️ 이 조건은 **뺄 수 없다.** 이게 없으면 "시킨 데까지 다 가서 멈춘 관절"을
#:    접촉으로 오판한다(멈춰 있고 오차도 없는 것은 접촉의 반대다).
DG5F_CONTACT_POS_ERR_DEG = float(_env("RTAUTO_DG5F_CONTACT_POS_ERR_DEG", "2.0"))

#: 관절 속도가 이것(rpm) 아래로 떨어져야 "멈췄다"로 본다.
DG5F_CONTACT_VEL_RPM = float(_env("RTAUTO_DG5F_CONTACT_VEL_RPM", "3.0"))

#: 위 조건이 **몇 번 연속**으로 만족해야 접촉으로 확정하는가. 순간적으로 넘은 것은 버린다.
#: 통신 주기가 약 5 ms 이므로 8번이면 대략 40 ms 다.
DG5F_CONTACT_HOLD_TICKS = int(_env("RTAUTO_DG5F_CONTACT_HOLD_TICKS", "8"))

#: 손가락 몇 개가 닿아야 "잡았다"로 보고 더 조이기를 멈추는가.
#: 시뮬레이터의 성공 기준(min_tips=3)과 같은 값으로 시작한다.
DG5F_CONTACT_MIN_FINGERS = int(_env("RTAUTO_DG5F_CONTACT_MIN_FINGERS", "3"))

#: 닫기를 포기할 때까지의 시간(초). 이 안에 손가락 수가 안 차면 "헛잡음"으로 끝낸다.
DG5F_CLOSE_TIMEOUT_S = float(_env("RTAUTO_DG5F_CLOSE_TIMEOUT_S", "3.0"))

#: 이 전류(mA)를 넘으면 물체·손을 지키려고 즉시 멈추고 편다. 하드웨어 보호용 상한.
#: ⚠️ 실측 전 잠정값 — 무부하 전류를 재기 전에는 이 값이 안전한지 알 수 없다.
DG5F_CURRENT_LIMIT_MA = float(_env("RTAUTO_DG5F_CURRENT_LIMIT_MA", "800"))

#: 이 온도(°C)를 넘으면 멈춘다. 오래 쥐고 있으면 모터가 뜨거워진다.
DG5F_TEMP_LIMIT_C = float(_env("RTAUTO_DG5F_TEMP_LIMIT_C", "65"))

#: 새 상태값이 이 시간(초) 동안 안 들어오면 통신이 끊긴 것으로 보고 명령을 멈춘다.
DG5F_FRAME_TIMEOUT_S = float(_env("RTAUTO_DG5F_FRAME_TIMEOUT_S", "0.5"))

# ---------------- 잡았는지 확인하기 (들어올린 뒤) ----------------
#: 확인하려고 팔을 들어올리는 높이(m)와 속도(m/s). 낮고 느릴수록 안전하다.
GRASP_LIFT_HEIGHT_M = float(_env("RTAUTO_GRASP_LIFT_HEIGHT_M", "0.05"))
GRASP_LIFT_SPEED_MPS = float(_env("RTAUTO_GRASP_LIFT_SPEED_MPS", "0.02"))

#: 들어올린 뒤 **일부러 조금 더 조여 보는** 각도(deg). 이것이 "집어보기"다.
#: ⚠️ 왜 필요한가: 닿은 관절은 목표를 그 자리에 세워 두므로, 물체가 빠져도 손가락이
#:    거의 안 움직인다(0.5도 수준). 그래서 "손가락이 더 닫혔나" 만 보면 놓친 것을
#:    못 잡는다 — hand/tests/test_grasp_contact.py 에서 이 구멍이 드러났다.
#:    조금 더 조여 보면 **물체가 있으면 못 움직이고, 없으면 그만큼 들어간다.**
#: 물체를 찌그러뜨리지 않게 작게 잡는다.
GRASP_PROBE_DEG = float(_env("RTAUTO_GRASP_PROBE_DEG", "5.0"))

#: 집어보기를 시켰을 때 손가락이 이만큼(deg) 이상 실제로 움직이면 **빈손**이다.
#: GRASP_PROBE_DEG 보다 작아야 한다(다 들어가기 전에 알아채려는 것).
GRASP_SLIP_CLOSE_DEG = float(_env("RTAUTO_GRASP_SLIP_CLOSE_DEG", "3.0"))

#: 들어올린 뒤 전류가 잡은 직후 대비 이 비율 아래로 떨어지면 놓친 것으로 본다.
GRASP_SLIP_CURRENT_RATIO = float(_env("RTAUTO_GRASP_SLIP_CURRENT_RATIO", "0.5"))

#: UR16e 내장 힘 센서로 무게를 확인할 때, 물체가 있다고 볼 최소 힘 변화(N).
#: ⚠️ UR 내장 힘 센서의 잡음은 수 N 수준이라 **가벼운 물체(100 g = 약 1 N)는 못 본다.**
#:    가벼운 물체에서는 이 확인을 건너뛰고 손가락 각도·전류·카메라 쪽을 쓴다.
GRASP_FT_MIN_DELTA_N = float(_env("RTAUTO_GRASP_FT_MIN_DELTA_N", "3.0"))

# ---------------- MediaPipe 카메라 ----------------
# 카메라 열거 순서와 지원 모드는 PC/드라이버마다 다르므로 vision 스크립트에 고정하지 않는다.
# 카메라 번호. 숫자면 그 번호로 고정, "auto"면 가장 좋은 것을 알아서, "ask"면 실행할 때마다
# 선택 창을 띄워 사람에게 물어본다(vision_node_dg5f.py는 --pick 으로도 한 번만 물어볼 수 있다).
# 화면 크기와 마찬가지로 **문자열 그대로** 두고 해석은 vision/dg5f/camera_caps.py가 한다.
#
# 왜 auto가 필요한가: 노트북에 외장 웹캠을 꽂으면 카메라가 두 대가 되는데, 어느 쪽이 0번인지
# OS가 정하고 재부팅·USB 포트 변경으로 뒤바뀐다. 번호를 박아 두면 모르는 사이에 화질 나쁜
# 내장 카메라로 돌 수 있다. 어느 번호가 어느 카메라인지 보려면:
#     python vision/dg5f/camera_caps.py --list
#
# 기본값이 "ask"인 이유(2026-09-16): 카메라가 두 대 이상이면 **묻는 게 맞다.** 번호를
# 기본값으로 박아 두면 노트북에서 내장 카메라로 조용히 도는 일이 생긴다. 대신 카메라가
# 한 대뿐이면 **묻지 않고 바로 시작**하므로 평소에는 달라지는 게 없다.
#   비용: 시작할 때 카메라를 찾느라 1~2초가 더 걸린다(실측, 카메라 1대 기준).
#         그게 싫으면 숫자를 적어 고정한다 — 그러면 찾는 과정 자체를 건너뛴다.
VISION_CAMERA_INDEX = _env("RTAUTO_VISION_CAMERA_INDEX", "ask").strip()

# 화면 크기는 **숫자가 아니라 문자열 그대로** 둔다 — 기본값 "max"가 "이 웹캠이 낼 수 있는
# 가장 큰 크기"라는 뜻이기 때문이다. 실제 해석과 카메라 적용은 vision/dg5f/camera_caps.py
# 한 곳이 담당한다(parse_size_spec). 숫자(예: "1280")를 넣으면 그 크기로 고정된다.
#
# 왜 기본이 max인가(2026-09-16): 예전 기본값은 1280x720 고정이었다. 손가락 끝처럼 작은
# 부분은 화면에 찍히는 점이 적을수록 위치가 흔들려서, 웹캠이 더 큰 화면을 낼 수 있는데도
# 720p로 잘라 쓸 이유가 없다. 720p만 되는 웹캠이면 결과는 예전과 똑같다(요청이 깎일 뿐).
VISION_CAMERA_WIDTH = _env("RTAUTO_VISION_CAMERA_WIDTH", "max").strip()
VISION_CAMERA_HEIGHT = _env("RTAUTO_VISION_CAMERA_HEIGHT", "max").strip()
VISION_CAMERA_FPS = int(_env("RTAUTO_VISION_CAMERA_FPS", "30"))
VISION_CAMERA_BACKEND = _env("RTAUTO_VISION_CAMERA_BACKEND", "auto").strip().lower()

# 영상 압축 형식(네 글자, 예: MJPG). 비워 두면 카메라 기본 포맷과 MJPG를 모두 실측해
# 최소 FPS를 만족하는 가장 큰 화면을 자동 선택한다. 압축 없이 보내면 USB 대역폭이 모자라
# 큰 화면이 느려지는 웹캠이 흔하지만, 포맷별 지원 상태가 달라 무조건 MJPG를 강제하지 않는다.
# 값을 명시하면 자동 비교 없이 그 포맷만 사용한다.
VISION_CAMERA_FOURCC = _env("RTAUTO_VISION_CAMERA_FOURCC", "").strip()

# "쓸 만하다"의 기준선 — 화면 크기를 자동으로 고를 때 **이보다 느린 크기는 버린다**.
# 왜 필요한가(2026-09-16 실측): 같은 웹캠이 2592x1944에서는 초당 1장, 1920x1080에서는
# 초당 30장이었다. 큰 화면이 항상 좋은 게 아니라서, 크기만 보고 고르면 손 동작을 전혀
# 따라가지 못하는 설정이 선택된다. 30장을 원하면 25 정도로 올린다.
VISION_CAMERA_MIN_FPS = float(_env("RTAUTO_VISION_CAMERA_MIN_FPS", "15"))

# 미리보기 창을 모니터에 몇 픽셀 폭으로 띄울지(세로는 실제 영상 비율에 맞춰 계산된다).
# 캡처 크기와는 무관한 **보기 편의** 값이다 — 창을 키워도 인식 정확도는 변하지 않는다.
# 4K로 캡처하면 창이 모니터를 넘어가므로 상한이 필요하다.
VISION_PREVIEW_WIDTH = int(_env("RTAUTO_VISION_PREVIEW_WIDTH", "1280"))

# 다중 웹캠(디지털 트윈 다시점 모니터링 등, vision/dg5f/multi_camera_capture.py)용 인덱스
# 목록 — 쉼표구분("0,1,2"). 비워두면 위 VISION_CAMERA_INDEX 하나만 쓴다 — 기존 단일
# 카메라 스크립트(vision_node_dg5f.py 등)는 이 값과 무관하게 그대로 동작한다.
_VISION_CAMERA_INDICES_RAW = _env("RTAUTO_VISION_CAMERA_INDICES", "").strip()
VISION_CAMERA_INDICES = (
    [int(v) for v in _VISION_CAMERA_INDICES_RAW.split(",") if v.strip()]
    if _VISION_CAMERA_INDICES_RAW
    # 다중 카메라는 "여러 대를 동시에" 쓰는 용도라 auto(한 대 고르기)가 의미 없다.
    # 위 설정이 auto면 여기서는 0번 하나로 본다 — 여러 대를 쓸 거면 INDICES를 직접 적는다.
    else [int(VISION_CAMERA_INDEX) if VISION_CAMERA_INDEX.isdigit() else 0]
)

# ---------------- 경로 (머신마다 다름 — 기본값 없음, 없으면 각 스크립트가 명확히 에러) ----------------
UNITY_PROJECT = _env("RTAUTO_UNITY_PROJECT", "")   # tools/urdf_hand_import용 Unity 프로젝트 루트
UNITY_CLI = _env("RTAUTO_UNITY_CLI", "")           # unity-cli 실행파일 경로
DG5F_DLL = _env("RTAUTO_DG5F_DLL", "")             # 비우면 dg5f_sdk_bridge.py가 상대경로 기본값 사용

# 공식 벤더 파이썬 SDK(dgsdk) 바이너리 디렉터리 — vision/dg5f/dg5f_sdk_bridge_dgsdk.py(미검증,
# 드라이런 전용) 가 쓴다. 저장소에 vendor로 커밋돼 있어(vision/dg5f/vendor/dgsdk-python/libs)
# 기본값이 있다 — 다른 DLL/so로 바꿔 실험할 때만 비워지지 않은 값으로 오버라이드한다.
DG5F_DGSDK_LIB_DIR = _env("RTAUTO_DG5F_DGSDK_LIB_DIR", "")

# Universal_Robots_ROS2_Description 체크아웃 루트 (urdf/, meshes/, config/가 바로 안에 있는 폴더).
# urdf 빌드 스크립트(urdf/build_arm_hand.py)가 xacro 해석과 메시 복사에 쓴다.
# 저장소에 포함하지 않는 외부 공개 레포이므로 머신마다 위치가 다르다 — 기본값 없음.
UR_DESCRIPTION = _env("RTAUTO_UR_DESCRIPTION", "")

# ---------------- eye-in-hand 카메라 (Intel RealSense D405) ----------------
# 손목에 다는 3D 카메라. 점 덩어리 합성(superdex/scripts/synth_pointcloud.py)이 읽는다.
#
# ✅ **2026-09-18 실물로 쟀다** (시리얼 262622272449, 1280x720). 아래 기본값은 여전히
# 제조사 공개 사양이지만, **실측값은 `.env` 에 들어가 이것을 덮어쓴다** — 카메라 개체마다
# 다르므로 코드 기본값으로 굳히지 않는다(원칙 1).
#   잰 법 : python vision/d405/probe_d405.py --info --env
#   결과 : 가로 시야각 **89.81도**(사양 87 — +2.8 차이), 세로 **58.56도**(사양 58)
#          초점거리 fx=fy=642.10, 화면 중심 (640.69, 361.43) — 한가운데(640, 360)가 아니다
# ⚠️ 시야각 2.8도 차이는 **20 cm 앞에서 가장자리 약 1 cm** 다. "1 cm 밀면 44% 실패" 와
#    같은 크기이므로 그냥 넘길 값이 아니었다.
# ⚠️ 아직 못 잰 것: 실제 유효 깊이 범위(D405_NEAR_M / D405_FAR_M). 물체를 놓고
#    `--depth` 로 거리별로 재야 한다.
D405_FOV_H_DEG = float(_env("RTAUTO_D405_FOV_H_DEG", "87"))    # 가로 시야각
D405_FOV_V_DEG = float(_env("RTAUTO_D405_FOV_V_DEG", "58"))    # 세로 시야각
D405_NEAR_M = float(_env("RTAUTO_D405_NEAR_M", "0.07"))        # 이보다 가까우면 못 잰다
D405_FAR_M = float(_env("RTAUTO_D405_FAR_M", "0.50"))          # 잘 재는 거리의 상한
# 합성에 쓸 사진 크기. 실물 해상도(최대 1280x720)를 그대로 쓰면 느리므로 줄여서 쓴다 —
# 학습 입력으로는 점 개수가 중요하지 화소 수가 중요하지 않다.
D405_SYNTH_WIDTH = int(_env("RTAUTO_D405_SYNTH_WIDTH", "160"))
D405_SYNTH_HEIGHT = int(_env("RTAUTO_D405_SYNTH_HEIGHT", "120"))

# ---------------- 손목 카메라가 팔 끝에 어떻게 붙었나 (D-6) ----------------
# 🛑 **이 값이 없으면 카메라가 와도 본 것을 로봇 좌표로 못 옮긴다.**
# 카메라는 "내 앞 20 cm 에 물체가 있다" 까지만 안다. 그걸 "로봇 기준으로 어디" 로
# 바꾸려면 **카메라가 팔 끝의 어디에 어떤 방향으로 붙었는지**를 알아야 한다.
# docs/EXTERNAL_GRASP_POLICY_SURVEY.md §9 가 "이게 먼저다" 라고 지목한 항목이다.
#
# ⚠️ **기본값 0 은 "아직 안 쟀다" 는 뜻이지 "붙은 자리가 원점" 이라는 뜻이 아니다.**
#    0 인 채로도 배관은 돌지만(원칙 2 — 새 머신에서 바로 실행 가능), 결과를 믿으면 안 된다.
#    `arm/eye_in_hand.py --check` 가 이 상태를 눈에 띄게 알려 준다.
#
# 재는 법: 체커보드 같은 표식을 고정해 두고 팔을 여러 자세로 옮기며 찍어, 팔 자세와
#         카메라가 본 표식 위치를 맞춰 푼다(= 흔히 말하는 손-눈 맞추기).
#         BACKLOG D-7 / FESTA_PREGRASP_PLAN Q2.

#: 카메라가 어느 링크에 붙어 있는가. **`tool0` 이 기본이다** — `flange` 와 위치는 같지만
#: 방향이 120도 다르다(2026-09-17 URSim 실측으로 확인한 실제 버그).
D405_MOUNT_PARENT = _env("RTAUTO_D405_MOUNT_PARENT", "tool0")

#: 그 링크 기준 카메라 위치 (x, y, z) [m]. 0,0,0 = 아직 안 쟀다.
D405_MOUNT_XYZ_M = tuple(
    float(v) for v in _env("RTAUTO_D405_MOUNT_XYZ_M", "0,0,0").split(","))

#: 그 링크 기준 카메라 방향 (roll, pitch, yaw) [도]. 0,0,0 = 아직 안 쟀다.
D405_MOUNT_RPY_DEG = tuple(
    float(v) for v in _env("RTAUTO_D405_MOUNT_RPY_DEG", "0,0,0").split(","))


def d405_mount_measured():
    """손목 카메라 장착값을 **실제로 쟀는가**. 전부 0이면 아직 안 잰 것으로 본다.

    ⚠️ 정말로 0,0,0 인 장착은 현실에 없다(카메라가 팔 끝 축 위 한 점에 부피 없이
    붙을 수는 없다). 그래서 0을 "안 쟀음" 신호로 써도 안전하다.
    """
    return any(abs(v) > 1e-9 for v in D405_MOUNT_XYZ_M + D405_MOUNT_RPY_DEG)


#: 카메라 내부 값(초점거리·중심). 0 이면 위 시야각에서 계산해 쓴다.
#: 실물에서는 RealSense SDK 가 알려 주는 값을 여기에 넣는다 — 개체마다 다르다.
#: ⚠️ **이 값은 잰 해상도에서만 맞는다.** 아래 D405_CALIB_* 에 잰 해상도를 함께 적고,
#:    다른 해상도로 물어보면 그 비율만큼 **자동으로 환산한다**(arm/eye_in_hand.py).
#:    안 그러면 640x480 으로 물었는데 1280x720 값이 그대로 나가 **2배 틀린다.**
#:    2026-09-18 에 시험이 이 버그를 잡았다.
D405_CALIB_WIDTH = int(_env("RTAUTO_D405_CALIB_WIDTH", "1280"))
D405_CALIB_HEIGHT = int(_env("RTAUTO_D405_CALIB_HEIGHT", "720"))
D405_FX = float(_env("RTAUTO_D405_FX", "0"))
D405_FY = float(_env("RTAUTO_D405_FY", "0"))
D405_CX = float(_env("RTAUTO_D405_CX", "0"))
D405_CY = float(_env("RTAUTO_D405_CY", "0"))

# 팔+손 결합 URDF — **손 관절 20개의 "순서"의 유일한 정본**이다.
# contracts/grasp_prepose.py가 이 파일을 읽어 관절 이름 순서를 얻는다. 관절 이름 목록을
# 다른 파일에 다시 타이핑하지 않는다(원칙 1). 저장소 안에 있는 파일이라 기본값이 있고,
# 다른 손(왼손 등)으로 실험할 때만 오버라이드한다.
ARM_HAND_URDF = _env("RTAUTO_ARM_HAND_URDF", "") or str(
    REPO_ROOT / "urdf" / "ur16e_dg5f_right_build" / "ur16e_dg5f_right.urdf"
)

# vision/dg5f/analyze_teleop.py·analyze_thumbik.py가 읽는 Unity 조인트 로그·URDF 폴더.
# 머신마다 다른 경로라 기본값 없음 — 없으면 각 스크립트가 --logs-dir/--urdf-dir 요구로 명확히 에러.
DG5F_UNITY_LOGS = _env("DG5F_UNITY_LOGS", "")
DG5F_URDF_DIR = _env("DG5F_URDF_DIR", "")

# ---------------- ML-Agents 학습 (DG5FPicknPlace) ----------------
# Unity 쪽 BuildEnvironment.cs가 읽는 것과 "같은" .env 키를 여기서도 읽는다.
# 빌드가 어디에 산출물을 두는지와 학습 런처가 어디서 플레이어를 찾는지가 갈라지면
# 새 PC에서 조용히 어긋나므로, 키 이름을 두 번째 파일에 다시 타이핑하지 않는다.
import sys as _sys

_IS_WINDOWS = _sys.platform.startswith("win")

PICKNPLACE_BUILD_OUTPUT = _env(
    "DG5F_PICKNPLACE_WINDOWS_BUILD_OUTPUT" if _IS_WINDOWS else "DG5F_PICKNPLACE_BUILD_OUTPUT",
    "")
PICKNPLACE_PLAYER_NAME = _env(
    "DG5F_PICKNPLACE_WINDOWS_PLAYER_NAME" if _IS_WINDOWS else "DG5F_PICKNPLACE_PLAYER_NAME",
    "")

# 학습 씬에 구워지는 병렬 영역 수와 mlagents-learn이 띄우는 플레이어 프로세스 수.
# 총 에이전트 수 = TRAIN_AREAS x TRAIN_NUM_ENVS. 둘 다 머신 사양(코어/RAM)에 묶인
# 값이라 코드가 아니라 .env에서 바꾼다.
TRAIN_AREAS = int(_env("DG5F_PICKNPLACE_TRAINING_AREAS", "40"))
TRAIN_NUM_ENVS = int(_env("RTAUTO_TRAIN_NUM_ENVS", "1"))


def picknplace_player_path():
    """빌드된 DG5FPicknPlace 플레이어의 절대경로 (없으면 None).

    mlagents-learn --env에 넘길 값. 상대경로는 저장소 루트 기준으로 해석한다 —
    Unity BuildEnvironment.ResolvePath와 같은 규칙.
    """
    if not PICKNPLACE_BUILD_OUTPUT or not PICKNPLACE_PLAYER_NAME:
        return None
    output = Path(PICKNPLACE_BUILD_OUTPUT)
    if not output.is_absolute():
        output = REPO_ROOT / output
    return (output / PICKNPLACE_PLAYER_NAME).resolve()


def _repo_path(name, default_relative):
    """저장소 상대 기본값을 갖는 경로. .env에서 절대경로로 덮어쓸 수 있다."""
    value = _env(name, default_relative).strip() or default_relative
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path)


# ---------------- ML-Agents 학습 산출물 경로 ----------------
# 다른 경로들과 달리 저장소 상대 기본값이 있다 — 머신마다 다른 값이 아니라 리포 레이아웃이라서다.
# 학습 산출물이 커져 다른 디스크로 빼야 하면 .env에서 절대경로로 덮어쓴다.
# failure/legacy는 results 아래로 파생시킨다: 숫자·경로를 두 번 타이핑하지 않는다(원칙 1).
#   results/<run-id>          진행 중이거나 아직 판정하지 않은 런
#   results/failure/<run-id>  실패로 판정해 격리한 런 (training/scripts/archive_run.py가 옮긴다)
#   results/legacy/<run-id>   과거 behavior의 런 — 참고용 보존, 재개 대상 아님
# 각 런의 판정 근거는 docs/TRAINING_RUN_LEDGER.md가 정본이다.
TRAINING_RESULTS_DIR = _repo_path("RTAUTO_TRAINING_RESULTS_DIR", "training/results")
TRAINING_FAILURE_DIR = TRAINING_RESULTS_DIR / "failure"
TRAINING_LEGACY_DIR = TRAINING_RESULTS_DIR / "legacy"

# ---------------- 다중 웹캠 3D 캘리브레이션 (calibrate_intrinsics.py / calibrate_extrinsics.py) ----------------
# 체스보드 내부 코너 개수(가로x세로)·한 칸 실측 변(mm) — 실제 보유한 보드에 맞춰 .env에서 덮어쓸 것.
# 기본값은 OpenCV 예제에서 흔히 쓰는 9x6(10x7 사각형) 보드 기준.
CALIB_BOARD_COLS = int(_env("RTAUTO_CALIB_BOARD_COLS", "9"))
CALIB_BOARD_ROWS = int(_env("RTAUTO_CALIB_BOARD_ROWS", "6"))
CALIB_SQUARE_SIZE_MM = float(_env("RTAUTO_CALIB_SQUARE_SIZE_MM", "25.0"))
# 카메라별 intrinsics(intrinsics_cam<N>.json)·다중뷰 extrinsics(extrinsics.json) 저장 폴더.
# 저장소 상대 기본값 — 다른 디스크로 빼야 하면 .env에서 절대경로로 덮어쓴다.
CALIB_DIR = _repo_path("RTAUTO_CALIB_DIR", "vision/dg5f/camera_calib")

# ---------------- 로봇 구성 (하드웨어 스펙, 2026-08-25 확정) ----------------
# 스펙 변동 가능성이 통보돼 있어 코드에 박지 않고 여기서 바꾼다.
UR_TYPE = _env("RTAUTO_UR_TYPE", "ur16e")          # 이전 자산은 ur5e 기준이었다
DG5F_HAND = _env("RTAUTO_DG5F_HAND", "right")      # DG-5F-M-R = 오른손
DG5F_SHORT = _env("RTAUTO_DG5F_SHORT", "0") == "1"  # short 변형 여부("M"이 short면 1)


def dg5f_variant():
    """urdf/dg5f/ 아래 URDF·메시 폴더 이름 (예: dg5f_right, dg5f_left_short)."""
    return f"dg5f_{DG5F_HAND}" + ("_short" if DG5F_SHORT else "")


def dg5f_link_prefix():
    """DG5F URDF 링크 접두사 — 왼손 'll_', 오른손 'rl_' (URDF 실측)."""
    return "ll_" if DG5F_HAND == "left" else "rl_"


# ---------------- SuperDex PoC (브랜치 SuperDexTest 전용, 2026-09-07 신설) ----------------
# 평가 계획·게이트·회귀 기준은 docs/SUPERDEX_POC_PLAN.md가 정본이다.
# SuperDex는 Python 3.12 전용이라 기존 3.10.11 venv와 섞지 않는다 — venv를 분리한다.

# project_superdex 클론 루트. asset 트리(assets/)가 저장소 안에만 있고 wheel에는 없어서
# 클론이 필수다. 저장소에 포함하지 않는 외부 공개 레포이므로 머신마다 위치가 다르다
# — UR_DESCRIPTION과 같은 이유로 기본값 없음.
SUPERDEX_REPO = _env("RTAUTO_SUPERDEX_REPO", "")

# asset 트리. 비우면 SUPERDEX_REPO/assets로 파생시킨다 — 경로를 두 번 타이핑하지 않는다.
# SuperDex 자신은 SUPERDEX_ASSETS_PATH 환경변수를 읽으므로, 런처가 이 값을 그 이름으로
# 내보내야 한다(superdex_lab README의 계약).
_SUPERDEX_ASSETS_RAW = _env("RTAUTO_SUPERDEX_ASSETS", "").strip()

# wheel 버전 핀은 여기가 아니라 requirements-superdex.txt가 정본이다
# (requirements-mlagents.txt와 같은 관례 — 버전 문자열을 두 곳에 타이핑하지 않는다).
# alpha 단계라 main/최신을 따라가면 6개월간 반복 파손된다 — docs/SUPERDEX_POC_PLAN.md §9 R3.

# 물리 스텝 주기. 동봉 예제(examples/control/example_osc_jsc_control.py) 실측값 1/200 s.
# 접촉 시뮬레이션 품질에 직결되는 값이라 게이트 0에서 검증 대상이다.
SUPERDEX_SIM_HZ = int(_env("RTAUTO_SUPERDEX_SIM_HZ", "200"))

# PPO 할인율. **학습기(train_ppo.py)와 환경의 potential-based shaping 이 반드시 같은 값을
# 써야 한다** — Ng et al. 1999 의 "최적 정책이 바뀌지 않는다"는 보장이 `F = gamma*Phi(s') -
# Phi(s)` 의 gamma 와 MDP 할인율이 같을 때만 성립하기 때문이다. 두 곳에 따로 타이핑하면
# 조용히 어긋나고(실제로 어긋나 있었다 — 환경 gamma=1 vs 학습 0.99, 2026-09-14 수정),
# 그 차이가 스텝마다 `-(1-gamma)*dist` 라는 거리 벌점으로 남는다.
# 그래서 정본을 여기 하나로 둔다(원칙 1). 바꾸면 학습기와 환경이 함께 따라간다.
SUPERDEX_PPO_GAMMA = float(_env("RTAUTO_SUPERDEX_PPO_GAMMA", "0.99"))

# Ray env runner 수. SuperDex 기본값 32는 세 작업 머신 어느 쪽의 스레드 수도 넘는다
# (회사 Ryzen 5 7600 = 6C/12T, 집 Ryzen 7 7800X3D = 8C/16T,
#  개인 노트북 Core Ultra 5 225H = 14C/14T). train_samples.py가 가용 CPU에 맞춰 자동
# 캡하지만, learner 1개와 OS·Unity 여유를 남긴 값을 여기서 준다.
#
# 머신마다 다른 값을 코드에 박지 않기 위해 **스레드 수에서 파생**시킨다(원칙 1·2) —
# 새 PC에서 .env를 건드리지 않아도 그 머신에 맞는 값이 나와야 한다.
#   12T -> 8, 16T -> 12, 14T -> 10. 실측 후 더 좋은 값이 나오면 .env로 덮어쓴다.
#
# ⚠️ 이 파생은 **스레드 수만 본다 — RAM 을 보지 않는다.** 개인 노트북은 RAM 이 16 GB로
#    다른 두 대(32 GB)의 절반이라 10 runner 가 메모리에서 먼저 막힐 수 있다. OOM 이 나면
#    이 기본값을 고치지 말고 .env 의 RTAUTO_SUPERDEX_ENV_RUNNERS 로 낮춘다.
def _default_env_runners():
    threads = os.cpu_count() or 4
    return max(2, threads - 4)


SUPERDEX_ENV_RUNNERS = int(_env("RTAUTO_SUPERDEX_ENV_RUNNERS", str(_default_env_runners())))

# 물리는 CPU이지만 learner(신경망 갱신)는 GPU를 쓸 수 있다. SuperDex 기본값은 0인데
# Windows 두 대는 CUDA GPU가 있으므로(회사 RTX 2080 8 GB / 집 RTX 4070 Ti 12 GB) 1을
# 기본으로 두고 시험한다. GPU가 없거나 torch가 CPU 빌드면 0으로 내린다.
#
# 🛑 **개인 노트북(2026-09-10 추가)은 여기에 해당한다** — Intel Arc 내장 GPU 뿐이라
#    CUDA 가 없고 torch 도 CPU 빌드(2.14.0+cpu)다. 그 머신의 .env 에
#    RTAUTO_SUPERDEX_GPUS_PER_LEARNER=0 을 넣어 두었다. 기본값 1 을 0 으로 바꾸지는
#    않는다 — 주 작업 환경인 회사 머신에는 1 이 맞기 때문이다(원칙 1: 머신마다 다른 값은
#    코드 기본값이 아니라 .env). docs/SUPERDEX_POC_PLAN.md §8 참고.
#
# ⚠️ RTX 2080은 Turing(sm_75)이라 **bf16을 지원하지 않는다.** 혼합정밀도를 켤 때
# bf16이 아니라 fp16을 쓰거나 fp32로 둔다 — 4070 Ti(Ada)에서만 통하는 설정을 그대로
# 회사 머신에 가져오면 런타임 에러가 난다. VRAM도 8 GB로 12 GB보다 작다.
SUPERDEX_GPUS_PER_LEARNER = int(_env("RTAUTO_SUPERDEX_GPUS_PER_LEARNER", "1"))

# 학습 산출물·ONNX 정책 산출물. 저장소 상대 기본값 — 머신마다 다른 값이 아니라 리포
# 레이아웃이라서다(TRAINING_RESULTS_DIR과 같은 관례). 다른 디스크로 빼려면 .env에서 절대경로로.
SUPERDEX_RESULTS_DIR = _repo_path("RTAUTO_SUPERDEX_RESULTS_DIR", "superdex/results")
SUPERDEX_POLICY_DIR = _repo_path("RTAUTO_SUPERDEX_POLICY_DIR", "superdex/policies")


def superdex_assets_path():
    """SuperDex asset 트리 절대경로 (설정이 없으면 None).

    SUPERDEX_ASSETS_PATH 환경변수로 내보낼 값이다 — SuperDex Lab이 벤치마크·bot asset을
    그 이름으로 찾는다.
    """
    if _SUPERDEX_ASSETS_RAW:
        path = Path(_SUPERDEX_ASSETS_RAW)
        return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
    if not SUPERDEX_REPO.strip():
        return None
    return (Path(SUPERDEX_REPO.strip()) / "assets").resolve()


def superdex_python_path():
    """SuperDex 전용 3.12 venv의 python 실행파일 (PYTHON_EXE와 같은 OS별 관례)."""
    override = _env("RTAUTO_SUPERDEX_PYTHON", "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else (REPO_ROOT / path)
    relative = "superdex/.venv/Scripts/python.exe" if _IS_WINDOWS else "superdex/.venv/bin/python"
    return REPO_ROOT / relative


def superdex_hand_asset():
    """DG5F 손 단독 asset의 assets/ 상대경로.

    변형(long/short, left/right)은 새 키를 만들지 않고 DG5F_HAND·DG5F_SHORT에서 파생시킨다
    — 같은 사실을 두 곳에 타이핑하지 않는다(원칙 1).

    경로 형식은 공식 조합 asset(fr3_dg5f_short_right.superdex_bot)이 손 asset을
    "//hands/dg5f_short/right/dg5f_short_right.superdex_bot"으로 참조하는 것을 확인해
    확정했다(2026-09-07, U2 해소). 두 표기가 같은 파일을 가리킨다:
      - Python에서 load_bot_prefab_from_file()에 넘길 때: "bots/hands/..." (assets/ 기준)
      - .superdex_bot 파일 안에서 참조할 때:              "//hands/..."   (assets/bots/ 기준,
        그 폴더의 .superdex_root 가 루트를 표시한다)
    이 함수는 앞쪽(Python용) 형식을 돌려준다.

    ⚠️ DG-5F-M이 long wrist인지 short wrist인지는 아직 미확정이다(U1) — 기본값은 long.
    확정 전까지 이 반환값은 잠정이며, DG5F_SHORT를 뒤집으면 기존 파이프라인의 URDF·메시
    선택(dg5f_variant())까지 함께 바뀐다. docs/SUPERDEX_POC_PLAN.md §12 참고.
    """
    variant = "dg5f_short" if DG5F_SHORT else "dg5f_long"
    return f"bots/hands/{variant}/{DG5F_HAND}/{variant}_{DG5F_HAND}.superdex_bot"


def superdex_hand_asset_ref():
    """위 경로의 .superdex_bot 내부 참조 표기 ("//hands/...").

    ⚠️ 이 표기는 **공식 asset 트리 안에 있는 결합 파일**에서만 통한다. 우리 결합 파일은
    우리 리포의 별도 asset 루트에 있으므로 superdex_hand_asset_tagged_ref()를 쓴다
    (U7 결정, 2026-09-09) — 아래 "U7" 블록 참고.
    """
    return "//" + superdex_hand_asset().removeprefix("bots/")


# ---------------- U7 — 우리 asset을 우리 리포에 두고 공식 트리를 태그로 참조한다 ----------
# (2026-09-09 실측으로 확정. superdex/scripts/gate3_asset_root_probe.py 가 판정 근거다.)
#
# 문제: 공식 Tesollo DG5F asset은 재배포 제한이 있어 우리 저장소에 커밋할 수 없는데(U4),
#       결합 bot은 팔(base)과 손(AttachBot.path)을 둘 다 참조해야 한다.
#
# 실측한 참조 규칙 (네이티브 로더가 거부 메시지로 알려준다:
# "Absolute bot paths are not allowed; use //, @tag/, or a file-relative path"):
#
#   //...      결합 파일이 속한 asset 루트 기준. **다른 트리로는 못 넘어간다** (실패)
#   절대경로   금지 (실패)
#   ../        루트 밖으로 올라가는 것 금지 (실패)
#   @tag/...   `.superdex_root` 에 정의된 태그 기준. **다른 트리로 넘어간다** (통과)
#
# `.superdex_root` 는 빈 마커가 아니라 **`{"@tag": "경로"}` JSON 사전**이다. 대상 폴더에도
# `.superdex_root` 가 있어야 한다(공식 assets/bots/ 에 있다 — 확인함).
#
# 따라서:
#   - 우리 팔 asset·결합 파일 -> 우리 리포(SUPERDEX_OUR_ASSETS_DIR)에 커밋. 공식 asset은
#     한 바이트도 복사하지 않는다.
#   - `.superdex_root` 는 클론 위치를 담아 **머신마다 다르므로 생성물이고 git 비추적**이다
#     (superdex/scripts/gate3_setup_asset_root.py 가 만든다 — 원칙 1·2).

# 우리가 만든 SuperDex asset의 루트. 리포 레이아웃이라 저장소 상대 기본값을 준다
# (SUPERDEX_RESULTS_DIR과 같은 관례).
SUPERDEX_OUR_ASSETS_DIR = _repo_path("RTAUTO_SUPERDEX_OUR_ASSETS_DIR", "superdex/assets")

# 공식 asset 트리를 가리킬 태그 이름. 네이티브 검증 규칙은 '@' + 영문자/숫자/밑줄이다.
SUPERDEX_OFFICIAL_TAG = _env("RTAUTO_SUPERDEX_OFFICIAL_TAG", "@superdex")

# 손을 플랜지에 붙일 때의 회전 (쿼터니언 x, y, z, w). 하드코딩이 아니라 캘리브레이션
# 상수이므로 정본을 여기 하나만 둔다(원칙 1).
#
# ✅ **확정됐다 (2026-09-09): identity(회전 없음).** 결합 bot의 손 자세를 정본인 결합
# URDF(`tool0_to_dg_mount`, parent `tool0`, origin identity)와 대조해 **최대 차이
# 1.49e-08**로 일치함을 확인했다 — `superdex/scripts/gate3_verify_hand_mount.py`.
#
# ⚠️ 이 값은 **눈으로 판정하면 안 된다.** 손이 플랜지 축으로 180° 돌아가 붙어도 자기접촉
# 0·관절 한계 일치·시뮬 안정성이 전부 통과하고, 오른손은 여전히 오른손으로 보인다.
# 공식 fr3 조합은 Z축 180°(0,0,1,~0)를 쓰지만 그것은 fr3 플랜지 규약이라 베끼면 안 된다.
# 바꿔야 할 일이 생기면 .env의 RTAUTO_SUPERDEX_HAND_MOUNT_QUAT로 주고 위 스크립트로
# 다시 판정한다.
SUPERDEX_HAND_MOUNT_QUAT = tuple(
    float(v) for v in _env("RTAUTO_SUPERDEX_HAND_MOUNT_QUAT", "0,0,0,1").split(",")
)


def superdex_our_bots_root():
    """우리 asset 루트의 `bots/` 폴더 (`.superdex_root` 가 놓이는 곳, 절대경로)."""
    return SUPERDEX_OUR_ASSETS_DIR / "bots"


def superdex_hand_asset_tagged_ref():
    """공식 손 asset의 `@tag/` 참조 표기 — 우리 결합 파일의 AttachBot.path 에 넣는 값.

    superdex_hand_asset()에서 파생시켜 손 변형(long/short, left/right)을 두 번 타이핑하지
    않는다(원칙 1). 머신 의존 경로가 없으므로 이 값이 들어간 결합 파일은 **커밋 가능하다**.
    """
    return f"{SUPERDEX_OFFICIAL_TAG}/" + superdex_hand_asset().removeprefix("bots/")


def superdex_arm_asset():
    """우리 UR 팔 asset의 우리 루트 기준 상대경로. Studio bake 산출물이 놓일 자리다."""
    return f"bots/arms/{UR_TYPE}/{UR_TYPE}.superdex_bot"


def superdex_arm_asset_ref():
    """위 팔 asset의 결합 파일 내부 참조 표기 ("//arms/...").

    팔은 **우리 루트 안**에 있으므로 태그가 아니라 `//` 로 가리킨다.
    """
    return "//" + superdex_arm_asset().removeprefix("bots/")


def superdex_combo_asset():
    """팔+손 결합 asset의 우리 루트 기준 상대경로.

    공식 조합 asset의 명명 규칙(`fr3_dg5f_short/right/fr3_dg5f_short_right.superdex_bot`,
    실측)을 그대로 따라 UR 기종·손 변형에서 파생시킨다.
    """
    _, _, variant, hand, _ = superdex_hand_asset().split("/")
    stem = f"{UR_TYPE}_{variant}_{hand}"
    return f"bots/arm_hand_combos/{UR_TYPE}_{variant}/{hand}/{stem}.superdex_bot"
