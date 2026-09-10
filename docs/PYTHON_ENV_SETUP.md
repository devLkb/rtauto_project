# Python 환경 설치 (Windows / Linux)

이 저장소의 MediaPipe 텔레옵과 Unity ML-Agents는 Python 3.10.11 가상환경 하나를
공유한다. 시스템 Python이나 단순히 `mediapipe`만 설치된 환경은 버전 조합이 다를 수
있으므로 아래 requirements로 맞춘다.

이 문서는 **처음 쓰는 PC에서 clone 직후부터 텔레옵/학습 실행까지**를 다룬다. 절차에
문서화되지 않은 수동 단계가 필요했다면 그건 버그다 — `CLAUDE.md` 원칙 2 참고.

> **명령 표기.** 각 단계는 Windows(PowerShell)와 Linux(bash)를 나란히 적는다. macOS는
> Linux 절차와 같되 `apt` 단계만 건너뛴다. 저장소 안의 상대 경로는 문서에서 `/`로
> 쓴다 — PowerShell도 `/`를 그대로 받아들인다.

## 1. 준비

| | Windows | Linux (Ubuntu 22.04 기준) |
|---|---|---|
| Python | 3.10.11 64-bit (python.org installer) | 3.10.x (`deadsnakes` PPA 또는 배포판 기본) |
| Git | Git for Windows | `git` |
| Unity | 6000.4.0f1 | 6000.4.0f1 (Unity Hub for Linux) |

Git이 필요한 이유는 `requirements-mlagents.txt`가 ML-Agents를 고정된 Git 커밋에서
설치하기 때문이다.

Linux는 OpenCV 미리보기 창(`cv2.imshow`)과 웹캠 접근에 시스템 패키지가 더 필요하다.

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 v4l-utils
```

웹캠 접근 권한이 없으면 카메라가 열리지 않는다. 한 번만 실행하고 **재로그인**한다.

```bash
sudo usermod -aG video $USER
```

저장소 루트로 이동한 뒤 Python 버전을 확인한다.

```powershell
py -3.10 -c "import sys; print(sys.version)"
```

```bash
python3.10 -c "import sys; print(sys.version)"
```

## 2. 공용 가상환경 생성

가상환경 경로는 `vision/.vision`으로 통일한다 (`.gitignore`에 등록돼 있다).

```powershell
py -3.10 -m venv vision/.vision
.\vision\.vision\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel
python -m pip install -r requirements-vision.txt
```

```bash
python3.10 -m venv vision/.vision
source vision/.vision/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements-vision.txt
```

> 활성화 스크립트 위치가 OS마다 다르다 — Windows는 `Scripts/Activate.ps1`(cmd는
> `Scripts\activate.bat`), Linux/macOS는 `bin/activate`. 아래 문서와 `training/README.md`의
> 예시 명령에 이 차이가 반복해서 나온다.
>
> PowerShell에서 활성화가 실행 정책으로 막히면 그 세션에서만 허용한다:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

ML-Agents 학습도 사용할 PC에서는 CUDA용 PyTorch를 먼저 설치하고 ML-Agents를
설치한다. GPU가 없는 시연 전용 PC는 첫 명령을 건너뛰고 CPU용 `torch==2.1.1`을
설치하면 된다 (`python -m pip install torch==2.1.1`).

```bash
python -m pip install torch==2.1.1+cu121 --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements-mlagents.txt
```

`nvidia-smi`로 드라이버가 지원하는 CUDA 버전을 확인하고 그 이하의 휠을 고른다
(정확히 일치시킬 필요는 없다).

`setuptools==81.0.0`은 의도적으로 고정한다. 이 프로젝트의 ML-Agents 버전은
`pkg_resources`를 사용하며 setuptools 82 이상에서는 해당 모듈이 제거되어
`mlagents-learn` 시작이 실패한다.

## 3. 설치 검증

두 OS 공통이다. 가상환경이 활성화된 상태에서 실행한다.

```bash
python -m pip check
python -c "import cv2, mediapipe as mp, numpy; print(cv2.__version__, mp.__version__, numpy.__version__); print(mp.solutions.hands)"
python -c "import rtde_control, rtde_receive; print('ur_rtde OK')"
mlagents-learn --help
```

비전 시연만 하는 PC에서는 마지막 `mlagents-learn` 검증은 생략할 수 있다. 검증된 핵심
조합은 `mediapipe==0.10.11`, `opencv-contrib-python==4.8.1.78`,
`numpy==1.23.5`, `protobuf==3.20.3`이다. `ur_rtde`(UR16e 팔 디지털 트윈,
`arm/ur_rtde_bridge.py`)는 이 조합과 버전 충돌 이력이 없어 같은 venv에 공존한다 —
검증된 버전은 `ur_rtde==1.6.5`(Windows/Linux 모두 PyPI 휠 제공, 별도 빌드 도구 불필요).

## 4. PC별 설정

`.env.example`을 `.env`로 복사한다. Unity와 Python을 같은 PC에서 실행하면 IP와 UDP
포트는 기본값을 그대로 사용한다.

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

카메라가 여러 개이거나 기본 카메라가 잘못 선택되면 `.env`에서 다음 값을 조정한다.

```dotenv
RTAUTO_VISION_CAMERA_INDEX=0
RTAUTO_VISION_CAMERA_WIDTH=1280
RTAUTO_VISION_CAMERA_HEIGHT=720
RTAUTO_VISION_CAMERA_FPS=30
RTAUTO_VISION_CAMERA_BACKEND=auto
```

카메라 인덱스는 `0`, `1`, `2` 순으로 시험한다. Linux에서는 `ls /dev/video*` 또는
`v4l2-ctl --list-devices`의 번호가 곧 인덱스다.

`RTAUTO_VISION_CAMERA_BACKEND`는 `auto`로 열리지 않을 때만 OS에 맞게 바꾼다 —
Windows는 `msmf`/`dshow`, Linux는 `v4l2`/`gstreamer`, macOS는 `avfoundation`.
카메라 드라이버가 요청 해상도를 지원하지 않으면 미리보기 하단의 `SOURCE` 값이 실제
입력 해상도다.

`.env`는 `KEY=value` 한 줄씩 쓰며, 값의 따옴표와 앞의 `export `는 자동으로 벗겨진다.
우선순위는 **프로세스 환경변수 > `.env` > 코드 기본값**이다.

## 5. 오른손 텔레옵 실행

사용자·카메라·촬영 위치가 바뀌면 최초 한 번 보정한다.

```powershell
python vision/dg5f/calibrate_dg5f.py
```

```bash
python vision/dg5f/calibrate_dg5f.py
```

Unity에서 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`를 열고 Play한 뒤 다음 명령을
실행한다.

```bash
python vision/dg5f/vision_node_dg5f.py right
```

미리보기에서 `RIGHT HAND DETECTED`가 표시되면 Unity UDP 포트로 관절값을 전송한다.
종료는 미리보기 창에서 `q`를 누른다.

Unity가 다른 PC에서 실행된다면 Python PC의 `.env`에 `RTAUTO_UNITY_IP=<Unity PC의
IPv4>`를 설정하고 Unity PC의 방화벽에서 UDP 5006 인바운드를 허용해야 한다
(포트 기본값은 `config/rtauto_config.py`의 `PORT_DG5F_SIM`).

## 문제 해결

- `No module named 'pkg_resources'`: 가상환경을 활성화하고
  `python -m pip install setuptools==81.0.0`을 실행한다.
- `mediapipe has no attribute solutions`: 임의 최신 버전을 제거하고
  `python -m pip install -r requirements-vision.txt --force-reinstall`로 복구한다.
- **Linux** `ImportError: libGL.so.1: cannot open shared object file`: 1절의 `libgl1`
  등 시스템 패키지를 설치하지 않은 것이다.
- **Linux** 카메라가 안 열림: `ls /dev/video*`로 장치 존재를 확인하고, 장치는 있는데
  실패하면 `video` 그룹 권한(1절)과 재로그인 여부를 확인한다.
- **Linux** `cv2.imshow`가 아무 창도 안 띄움: SSH나 WSL2처럼 디스플레이가 없는
  환경이다. `$DISPLAY`가 설정돼 있어야 한다 (WSL2는 WSLg 필요).
- **Windows** 카메라가 안 열림: 설정 > 개인 정보 > 카메라에서 데스크톱 앱 접근을
  켜고, 다른 앱이 카메라를 점유 중인지 확인한다.
- 카메라 창만 크고 영상이 흐림: 하단 `SOURCE` 해상도를 확인한다. 원본이 640×480보다
  낮으면 소프트웨어 확대만으로 실제 디테일을 복원할 수 없으므로 HD 웹캠/드라이버가
  필요하다.
- `bad interpreter: /bin/bash^M` (Linux에서 `.sh` 실행 시): 저장소 루트에
  `.gitattributes`가 줄바꿈을 LF로 고정한다. 이 오류가 나면 CRLF로 체크아웃된
  것이므로 `git rm --cached -r . && git reset --hard`로 재정규화한다.
- Unity가 반응하지 않음: Unity Play 상태, `.env`의 IP/포트, 방화벽을 확인한다.

## 부록 — SuperDex 전용 가상환경 (파지 RL의 현행 경로)

DG5F 파지 강화학습은 **SuperDex 로 이관됐고 2026-09-09 채택이 확정돼 `main` 에 머지됐다**
(이전 판이 적어 둔 "브랜치 `SuperDexTest` 한정"은 더 이상 사실이 아니다). SuperDex 는
**Python 3.12 전용 wheel** 이라 위 §2의 공용 venv(3.10.11 — mediapipe + ML-Agents)와
**섞지 않고 분리**한다.

| venv | Python | 용도 | 위치 |
|---|---|---|---|
| 공용 (§2) | 3.10.11 | mediapipe 텔레옵, ML-Agents, UR RTDE 브리지 | `vision/.vision/` |
| SuperDex | 3.12 | SuperDex Physics/Robotics/Lab, RLlib, ONNX | `superdex/.venv/` |

`.gitignore`의 `.venv/` 패턴이 모든 깊이에서 매칭하므로 `superdex/.venv/`는 이미 추적
제외다. 요구사항은 [`../requirements-superdex.txt`](../requirements-superdex.txt)가 정본이다.

게이트별 배경·판정 기준은 [`SUPERDEX_POC_PLAN.md`](SUPERDEX_POC_PLAN.md) 가 정본이다.
아래는 **새 머신에서 clone 직후부터 결합 bot 이 로드되기까지** 실제로 밟아야 하는
최소 경로다(원칙 2). 2026-09-10 개인 노트북(Ubuntu 24.04.4)에서 처음부터 수행해 검증했다.

### A-1. Python 3.12 확인

Windows 는 python.org installer, Ubuntu 24.04 는 **시스템 python3.12 가 이미 있다**
(`3.12.3` 확인). 없으면 `sudo apt install -y python3.12 python3.12-venv`.

```powershell
py -3.12 --version
```

```bash
python3.12 --version
```

### A-2. venv 생성·활성화

**터미널 1 (리포 루트)** — 이 터미널을 A-5 까지 계속 쓴다.

```powershell
py -3.12 -m venv superdex/.venv
superdex/.venv/Scripts/Activate.ps1
python -m pip install --upgrade pip wheel
```

```bash
python3.12 -m venv superdex/.venv
source superdex/.venv/bin/activate
python -m pip install --upgrade pip wheel
```

프롬프트 앞에 `(.venv)` 가 붙어야 한다.

### A-3. torch 를 **먼저** 설치한다 — 머신마다 다르다

`requirements-superdex.txt` 에 torch 가 없는 것은 의도된 것이다(빌드가 머신마다 다르다).

| 머신 | GPU | 명령 |
|---|---|---|
| 회사 / 집 (Windows) | RTX 2080 / 4070 Ti | `pip install torch --index-url https://download.pytorch.org/whl/cu124` |
| **개인 노트북 (Ubuntu)** | Intel Arc 내장 — **CUDA 없음** | `pip install torch --index-url https://download.pytorch.org/whl/cpu` |

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

- CUDA 머신: `True` 여야 한다.
- **개인 노트북: `False` 가 정상이다** (실측 `2.14.0+cpu`). CPU learner 로도 진행되지만
  느리므로 성능 판정 기준으로 쓰지 않는다.

### A-4. SuperDex 설치

```bash
python -m pip install -r requirements-superdex.txt
python -m pip check
python -c "import superdex.physics, superdex.robotics; print('superdex import OK')"
```

`No broken requirements found.` 와 `superdex import OK` 가 나와야 한다. 소스 빌드는
필요 없다 — Windows/Linux/macOS 모두 pre-built wheel 이 있다.

### A-5. 공식 asset 클론 + `.env` + asset 루트 생성

공식 Tesollo 손 asset 은 **wheel 에 없고 `project_superdex` 클론 안에만 있다.** 이 단계를
건너뛰면 결합 bot 이 손을 찾지 못한다.

```bash
git clone --branch stable https://github.com/facebookresearch/project_superdex.git \
    ~/workspace/project_superdex
```

`stable` = `v1.0.0` = 커밋 `1d71509`, 약 **1.2 GB**. 리포 루트 `.env` 에 위치를 적는다
(머신마다 다르므로 `.env` 에만 — 원칙 1):

```dotenv
RTAUTO_SUPERDEX_REPO=/home/<user>/workspace/project_superdex
# CUDA GPU 가 없는 머신만 — 코드 기본값 1 을 0 으로 내린다
RTAUTO_SUPERDEX_GPUS_PER_LEARNER=0
```

그다음 **한 번만** 실행해 `.superdex_root`(비추적 생성물)를 만든다:

```bash
python -u superdex/scripts/gate3_setup_asset_root.py
```

`=== 게이트 3 배선: 통과 — 결합 bot 이 로드된다 ===` 와 `links=41 joints=41` 이 나오면
성공이다.

### A-6. 설정이 그 머신 값으로 풀리는지 확인

```bash
python -c "import sys;sys.path.insert(0,'config');import rtauto_config as c;\
print(c.superdex_assets_path(), c.SUPERDEX_ENV_RUNNERS, c.SUPERDEX_GPUS_PER_LEARNER)"
```

개인 노트북 실측: `.../project_superdex/assets 10 0` — runner 10 은
`os.cpu_count()-4` = 14−4 에서 파생된 값이다. ⚠️ 이 파생은 **스레드만 보고 RAM 을 보지
않는다.** 16 GB 머신에서 OOM 이 나면 `.env` 의 `RTAUTO_SUPERDEX_ENV_RUNNERS` 를 낮춘다.

> ⚠️ **Studio(`superdex-studio`) 의 SDF bake 는 GUI 앱이라 자동화할 수 없다.** 새 팔
> asset 을 구울 때만 필요하며, 이미 구운 `superdex/assets/bots/arms/ur16e/` 가 커밋돼
> 있어 위 절차만으로 결합 bot 이 로드된다. Linux 에서의 Studio 동작은 미확인이다.
