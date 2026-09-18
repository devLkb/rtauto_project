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

> 카메라(D405)를 쓰는 PC라면 `pip check`가
> `ultralytics ... requires opencv-python, which is not installed`를 낼 수 있다.
> **정상이다** — 이유와 확인 방법은 아래 §3-1 (1)에 있다.

비전 시연만 하는 PC에서는 마지막 `mlagents-learn` 검증은 생략할 수 있다. 검증된 핵심
조합은 `mediapipe==0.10.11`, `opencv-contrib-python==4.8.1.78`,
`numpy==1.23.5`, `protobuf==3.20.3`이다. `ur_rtde`(UR16e 팔 디지털 트윈,
`arm/ur_rtde_bridge.py`)는 이 조합과 버전 충돌 이력이 없어 같은 venv에 공존한다 —
검증된 버전은 `ur_rtde==1.6.5`(Windows/Linux 모두 PyPI 휠 제공, 별도 빌드 도구 불필요).

## 3-1. 손목 카메라(D405)를 쓰는 PC에서 추가로 할 일

카메라를 꽂아 쓰는 PC에서만 필요하다. **이 네 단계를 안 하면 카메라 쪽이 조용히
반쪽으로 돈다** — 물체 찾기가 통째로 꺼지거나, 제조사 사양값으로 계산해 어긋난다.
(2026-09-18 리눅스 노트북에서 실제로 밟아 확인했다.)

### (1) 준비물 다시 맞추기 — **이미 만들어 둔 가상환경에서도 한 번 더**

`pyrealsense2`(카메라를 여는 것)와 `ultralytics`(물체를 찾는 것)는
`requirements-vision.txt`에 **2026-09-18에 추가됐다.** 그 전에 만든 가상환경에는 없다.

```powershell
.\vision\.vision\Scripts\Activate.ps1
python -m pip install -r requirements-vision.txt
```

```bash
source vision/.vision/bin/activate
python -m pip install -r requirements-vision.txt
```

🛑 **설치가 끝나면 `torch`와 `opencv`가 바뀌지 않았는지 반드시 확인한다.**
`ultralytics`는 둘 다 자기 취향대로 갈아치우려 든다.

```bash
python -c "import torch, cv2; print(torch.__version__, cv2.__version__)"
```

- `torch`가 `2.1.1`이 아니면: `python -m pip install "torch==2.1.1" "torchvision==0.16.1"`
- `cv2`가 `4.8.1`이 아니면 (= `opencv-python`이 끼어든 것):

```bash
python -m pip uninstall -y opencv-python opencv-contrib-python
python -m pip install "opencv-contrib-python==4.8.1.78"
```

> 왜 이런 일이 나나: `opencv-python`과 `opencv-contrib-python`은 **같은 폴더에 같은
> 이름으로** 깔린다. 둘이 겹치면 나중에 깔린 쪽이 앞의 것을 덮어써, 어느 쪽 기능이
> 살아 있는지 알 수 없는 상태가 된다. 우리가 고정한 것은 `opencv-contrib-python`이다.

⚠️ 이렇게 되돌리면 `python -m pip check`가 아래 한 줄을 낸다. **정상이고, 고치지 않는다.**

```
ultralytics 8.4.155 requires opencv-python, which is not installed.
```

`ultralytics`가 요구하는 것은 **`cv2`라는 기능**이고 그것은 `opencv-contrib-python`이
똑같이 제공한다. 설치 목록의 이름만 다를 뿐이다. 여기서 `opencv-python`을 다시 깔면
위의 덮어쓰기 문제로 되돌아간다. (2026-09-18 확인: 이 상태로 물체 찾기가 정상 동작한다.)

### (2) 카메라가 알려 주는 실측값을 `.env`에 넣기

**카메라 개체마다 다르므로 코드에 굳히지 않는다**(원칙 1). 그래서 `.env`(git 비추적)에
들어가고, **다른 PC로 옮기면 그 값이 따라오지 않는다.** 새 PC에서 한 번 돌린다.

```powershell
python vision/d405/probe_d405.py --info --env
```

```bash
python vision/d405/probe_d405.py --info --env
```

마지막에 `RTAUTO_D405_FX=...` 로 시작하는 줄들이 나온다. **그대로 복사해 `.env` 끝에
붙인다.** `RTAUTO_D405_CALIB_WIDTH` / `_HEIGHT`(잰 해상도)도 같이 넣어야 한다 —
없으면 다른 해상도로 물어볼 때 **2배 틀린 값이 조용히 나간다.**

```
RTAUTO_D405_CALIB_WIDTH=1280
RTAUTO_D405_CALIB_HEIGHT=720
```

확인(넣은 값이 실제로 읽히는지):

```bash
python arm/eye_in_hand.py --check
```

→ `카메라 내부: fx ... (실측값)` 이라고 나오면 성공. `(시야각에서 계산)` 이면 아직 안 들어간 것이다.
(그 아래 "손목 카메라 장착값을 아직 안 쟀다" 경고는 **정상이다** — 팔에 달고 재는 값이라 따로다.)

### (3) 물체 찾기 모델 파일 만들기 (인터넷 되는 곳에서 한 번만)

이 파일은 용량이 커서 저장소에 안 들어간다(`.gitignore`). 받아서 구워야 한다.

```powershell
mkdir vision/d405/weights -Force
curl.exe -L -o vision/d405/weights/yoloe26-n-seg.pt "https://huggingface.co/openvision/yoloe26-n-seg/resolve/main/model.pt"
python vision/d405/make_ready.py
```

```bash
mkdir -p vision/d405/weights
curl -fL -o vision/d405/weights/yoloe26-n-seg.pt "https://huggingface.co/openvision/yoloe26-n-seg/resolve/main/model.pt"
python vision/d405/make_ready.py
```

`vision/d405/weights/yoloe26-n-seg-ready.pt` (약 11.5 MB)가 생기면 끝이다.

- 굽는 도중 **242 MB짜리 글자 이해용 모델**을 내려받아 리포 루트에 `mobileclip2_b.ts`로
  남긴다. **지워도 된다**(필요하면 다시 받는다). git은 이 파일을 무시한다.
- 굽는 것은 **여기서 한 번만** 한다. 시연 노트북에는 `...-ready.pt` 한 개만 있으면 된다.

### (4) 되는지 확인

```bash
python -m unittest discover -s vision/d405/tests -p "test_*.py"
python vision/d405/yolo_assist.py --save
```

- 시험은 **14개 전부 통과**여야 한다.
- `--save`는 사진 한 장을 찍어 `vision/d405/results/yolo_<시각>.png`로 남긴다.
  화면에 `⚠️ YOLO 를 못 쓴다` 가 뜨면 (1)이나 (3)이 덜 된 것이다.

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
RTAUTO_VISION_CAMERA_WIDTH=max
RTAUTO_VISION_CAMERA_HEIGHT=max
RTAUTO_VISION_CAMERA_FPS=30
RTAUTO_VISION_CAMERA_MIN_FPS=15
RTAUTO_VISION_CAMERA_BACKEND=auto
```

`WIDTH`/`HEIGHT`의 기본값 `max`는 **이 웹캠에서 쓸 수 있는 가장 좋은 화면**을 쓰라는
뜻이다. 처음 한 번만 실제로 큰 크기부터 열어 보며 **크기와 속도를 같이 재서** 고르고,
그 값을 `vision/dg5f/camera_caps_cache.json`에 적어 둬 다음 실행부터는 건너뛴다.
숫자를 적으면 그 크기로 고정된다.

**왜 속도까지 보나** — 큰 화면이 항상 좋은 게 아니기 때문이다. 같은 웹캠 실측(2026-09-16):

| 화면 크기 | 초당 들어온 장수 |
|---|---|
| 2592×1944 | 1장 (손 동작을 따라갈 수 없음) |
| 1920×1080 | 30장 ← 가장 좋음 |
| 1280×720 | 7.5장 (크기는 더 작은데 더 느리다) |
| 640×480 | 30장 |

`MIN_FPS`(기본 15)보다 느린 크기는 **더 크더라도 버린다.** 내 웹캠이 어떤지 확인하려면
(카메라만 잠깐 열었다 닫는다):

```bash
python vision/dg5f/camera_caps.py 0                  # 0번 카메라
python vision/dg5f/camera_caps.py 0 --refresh        # 저장된 값 무시하고 다시 탐색
python vision/dg5f/camera_caps.py 0 --backend=dshow --fourcc=MJPG   # 다른 조합과 비교
```

Windows에서는 **백엔드(`msmf`/`dshow`)와 압축 형식(`MJPG`) 조합에 따라 결과가 크게
달라진다.** 위 명령으로 조합을 비교해 가장 좋은 쪽을 `.env`에 적는다.

### 카메라가 두 대 이상일 때 (노트북 내장 + 외장 웹캠)

어느 번호가 어느 카메라인지 한 번에 보려면:

```bash
python vision/dg5f/camera_caps.py --list
```

```text
  번호      화면 크기     초당 장수   비고
     0    640x480         30.0장
     1   1920x1080        30.0장   ← 가장 좋음(auto가 고르는 것)
```

원하는 번호를 `.env`의 `RTAUTO_VISION_CAMERA_INDEX`에 적으면 고정된다. **번호 대신
`auto`를 적으면** 실행할 때마다 꽂혀 있는 것 중 가장 좋은 카메라를 알아서 고른다 —
Windows에서는 재부팅이나 USB 포트 변경으로 번호가 뒤바뀔 수 있어서, 노트북으로 옮겨
다닐 때는 `auto`가 안전하다.

```dotenv
RTAUTO_VISION_CAMERA_INDEX=auto
```

**기본값은 `ask`다** — 그냥 실행하면 작은 창이 떠서 카메라 목록과 각 카메라의 사진을
보여 주고, 하나를 골라 시작한다. **시작 시간은 이 PC 실측(카메라 1대)으로 번호 고정 3.2초 / `ask` 4.5초 / `auto` 4.5초다.
1초가 아까우면 번호를 고정한다.**

```dotenv
RTAUTO_VISION_CAMERA_INDEX=ask
```

`.env`를 고치지 않고 **이번 실행만** 고르고 싶으면 실행할 때 `--pick`을 붙인다:

```bash
python vision/dg5f/vision_node_dg5f.py --pick
```

시작 시간은 이 PC 실측(카메라 1대)으로 번호 고정 3.2초 / `ask` 4.5초 / `auto` 4.5초다.
1초가 아까우면 번호를 고정한다.

⚠️ `auto`는 첫 실행에서 카메라를 모두 열어 보느라 시간이 조금 더 걸린다(찾은 값은 저장돼
다음부터는 빠르다). 그리고 "가장 좋다"의 기준은 **속도 기준을 넘는 것 중 화면이 가장 큰
것**이라, 내장 카메라가 더 좋으면 내장을 고른다.

Linux에서는 `ls /dev/video*` 또는 `v4l2-ctl --list-devices`의 번호가 곧 인덱스다.

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
