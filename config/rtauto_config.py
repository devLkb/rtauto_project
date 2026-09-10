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

# ---------------- MediaPipe 카메라 ----------------
# 카메라 열거 순서와 지원 모드는 PC/드라이버마다 다르므로 vision 스크립트에 고정하지 않는다.
VISION_CAMERA_INDEX = int(_env("RTAUTO_VISION_CAMERA_INDEX", "0"))
VISION_CAMERA_WIDTH = int(_env("RTAUTO_VISION_CAMERA_WIDTH", "1280"))
VISION_CAMERA_HEIGHT = int(_env("RTAUTO_VISION_CAMERA_HEIGHT", "720"))
VISION_CAMERA_FPS = int(_env("RTAUTO_VISION_CAMERA_FPS", "30"))
VISION_CAMERA_BACKEND = _env("RTAUTO_VISION_CAMERA_BACKEND", "auto").strip().lower()

# 다중 웹캠(디지털 트윈 다시점 모니터링 등, vision/dg5f/multi_camera_capture.py)용 인덱스
# 목록 — 쉼표구분("0,1,2"). 비워두면 위 VISION_CAMERA_INDEX 하나만 쓴다 — 기존 단일
# 카메라 스크립트(vision_node_dg5f.py 등)는 이 값과 무관하게 그대로 동작한다.
_VISION_CAMERA_INDICES_RAW = _env("RTAUTO_VISION_CAMERA_INDICES", "").strip()
VISION_CAMERA_INDICES = (
    [int(v) for v in _VISION_CAMERA_INDICES_RAW.split(",") if v.strip()]
    if _VISION_CAMERA_INDICES_RAW else [VISION_CAMERA_INDEX]
)

# ---------------- 경로 (머신마다 다름 — 기본값 없음, 없으면 각 스크립트가 명확히 에러) ----------------
UNITY_PROJECT = _env("RTAUTO_UNITY_PROJECT", "")   # tools/urdf_hand_import용 Unity 프로젝트 루트
UNITY_CLI = _env("RTAUTO_UNITY_CLI", "")           # unity-cli 실행파일 경로
DG5F_DLL = _env("RTAUTO_DG5F_DLL", "")             # 비우면 dg5f_sdk_bridge.py가 상대경로 기본값 사용

# Universal_Robots_ROS2_Description 체크아웃 루트 (urdf/, meshes/, config/가 바로 안에 있는 폴더).
# urdf 빌드 스크립트(urdf/build_arm_hand.py)가 xacro 해석과 메시 복사에 쓴다.
# 저장소에 포함하지 않는 외부 공개 레포이므로 머신마다 위치가 다르다 — 기본값 없음.
UR_DESCRIPTION = _env("RTAUTO_UR_DESCRIPTION", "")

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

# Ray env runner 수. SuperDex 기본값 32는 두 작업 머신 어느 쪽의 스레드 수도 넘는다
# (회사 Ryzen 5 7600 = 6C/12T, 집 Ryzen 7 7800X3D = 8C/16T). train_samples.py가 가용
# CPU에 맞춰 자동 캡하지만, learner 1개와 OS·Unity 여유를 남긴 값을 여기서 준다.
#
# 머신마다 다른 값을 코드에 박지 않기 위해 **스레드 수에서 파생**시킨다(원칙 1·2) —
# 새 PC에서 .env를 건드리지 않아도 그 머신에 맞는 값이 나와야 한다.
#   12T -> 8, 16T -> 12. 실측 후 더 좋은 값이 나오면 .env로 덮어쓴다.
def _default_env_runners():
    threads = os.cpu_count() or 4
    return max(2, threads - 4)


SUPERDEX_ENV_RUNNERS = int(_env("RTAUTO_SUPERDEX_ENV_RUNNERS", str(_default_env_runners())))

# 물리는 CPU이지만 learner(신경망 갱신)는 GPU를 쓸 수 있다. SuperDex 기본값은 0인데
# 두 머신 모두 CUDA GPU가 있으므로(회사 RTX 2080 8 GB / 집 RTX 4070 Ti 12 GB) 1을
# 기본으로 두고 시험한다. GPU가 없거나 torch가 CPU 빌드면 0으로 내린다.
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
