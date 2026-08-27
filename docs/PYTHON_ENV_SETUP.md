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
mlagents-learn --help
```

비전 시연만 하는 PC에서는 마지막 `mlagents-learn` 검증은 생략할 수 있다. 검증된 핵심
조합은 `mediapipe==0.10.11`, `opencv-contrib-python==4.8.1.78`,
`numpy==1.23.5`, `protobuf==3.20.3`이다.

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
