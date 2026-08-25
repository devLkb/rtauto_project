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
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


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

# ---------------- 경로 (머신마다 다름 — 기본값 없음, 없으면 각 스크립트가 명확히 에러) ----------------
UNITY_PROJECT = _env("RTAUTO_UNITY_PROJECT", "")   # tools/urdf_hand_import용 Unity 프로젝트 루트
UNITY_CLI = _env("RTAUTO_UNITY_CLI", "")           # unity-cli 실행파일 경로
DG5F_DLL = _env("RTAUTO_DG5F_DLL", "")             # 비우면 dg5f_sdk_bridge.py가 상대경로 기본값 사용
