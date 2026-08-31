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

# UDP 포트 레지스트리 — 각 포트는 이 파일에서만 숫자로 정의한다. 새로 포트를 쓸 일이 생기면
# 여기부터 확인해서 겹치지 않는 번호를 고를 것 (과거 DG5F 실물 브리지와 ZED 좌표 송신이
# 둘 다 5007을 써서 같은 PC에서 동시 실행 시 UDP 바인드 충돌이 나는 문제가 있었다 — 2026-08-25 수정).
PORT_SVH_JOINTS = int(_env("RTAUTO_PORT_SVH_JOINTS", "5005"))    # 레거시 SVH 손 관절 트윈
PORT_DG5F_SIM = int(_env("RTAUTO_PORT_DG5F_SIM", "5006"))        # → Unity Dg5fReceiver (DG5F 손 관절 트윈)
PORT_ZED_TARGET = int(_env("RTAUTO_PORT_ZED_TARGET", "5007"))    # → Unity CameraTargetReceiver (ZED 객체 좌표)
PORT_DG5F_BRIDGE = int(_env("RTAUTO_PORT_DG5F_BRIDGE", "5008"))  # vision_node --bridge → dg5f_sdk_bridge.py (실물 SDK)

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
