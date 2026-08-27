# -*- coding: utf-8 -*-
"""프로젝트 전역 설정 레지스트리 — IP/포트/경로를 절대 다른 파일에 리터럴로 복사하지 말고
항상 여기서 읽을 것.

값 우선순위: 환경변수 > 레포 루트 .env(git 비추적) > 아래 기본값.
.env 작성법은 .env.example 참고 — 복사해서 .env로 저장하고 필요한 값만 채우면 된다.

이 파일 자체를 리터럴 IP/포트의 유일한 출처로 유지한다: 새 포트가 필요하면 여기 추가하고
다른 파일에서는 import해서 쓴다 (숫자를 다시 타이핑하지 않는다).
"""
import os
from pathlib import Path

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

# UDP 포트 레지스트리 — 각 포트는 이 파일에서만 숫자로 정의한다. 새로 포트를 쓸 일이 생기면
# 여기부터 확인해서 겹치지 않는 번호를 고를 것 (과거 DG5F 실물 브리지와 ZED 좌표 송신이
# 둘 다 5007을 써서 같은 PC에서 동시 실행 시 UDP 바인드 충돌이 나는 문제가 있었다 — 2026-08-25 수정).
PORT_SVH_JOINTS = int(_env("RTAUTO_PORT_SVH_JOINTS", "5005"))    # 레거시 SVH 손 관절 트윈
PORT_DG5F_SIM = int(_env("RTAUTO_PORT_DG5F_SIM", "5006"))        # → Unity Dg5fReceiver (DG5F 손 관절 트윈)
PORT_ZED_TARGET = int(_env("RTAUTO_PORT_ZED_TARGET", "5007"))    # → Unity CameraTargetReceiver (ZED 객체 좌표)
PORT_DG5F_BRIDGE = int(_env("RTAUTO_PORT_DG5F_BRIDGE", "5008"))  # vision_node --bridge → dg5f_sdk_bridge.py (실물 SDK)

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
