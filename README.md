# KDT_1_AX_rtauto — UR16e + DG-5F-M-R 디지털 트윈

확정 하드웨어인 UR16e와 Tesollo DG-5F-M-R 오른손으로 파지·들어올리기를 검증하는
디지털 트윈 프로젝트다. 현재 시연 씬에서는 MediaPipe가 오른손 손가락을 구동하고,
사용자가 Unity 화면 오른쪽 패널의 6축 관절 슬라이더로 팔을 직접 움직인다.

```text
Unity 수동 팔 IK (UR16e)
  + MediaPipe 오른손 관절 20채널
  -> UDP -> DG-5F-M-R 디지털 트윈
        -> UDP -> dg5f_sdk_bridge.py -> DGSDK -> 실물 DG-5F-M-R   (2026-09-01 동작 확인)
```

강화학습 환경은 동일 하드웨어의 12cm 블록 grasp+lift 태스크(obs 57 / act 7)를 제공한다.
현재 시연은 정책 없이 수동 팔 조작과 손 미러링을 우선한다. 최신 아키텍처와 결정은
`docs/SIM2REAL_ROADMAP.md`가 정본이다.

## 리포 구조

| 폴더 | 내용 |
|---|---|
| `unity/` | Unity 프로젝트 (Assets + Packages + ProjectSettings — Library는 열 때 자동 생성) |
| `vision/dg5f/` | **DG5F 텔레옵 파이프라인**: 보정→웹캠 트래킹→UDP 송신 + 검증/분석 도구 |
| `arm/` | **UR16e RTDE 브리지**: Unity ↔ URSim/실물 팔 디지털 트윈 (`ur_rtde_bridge.py`) |
| `tools/urdf_hand_import/` | URDF→Unity 임포트/물리검증/구동준비/프로브 범용 스크립트 |
| `urdf/dg5f/` | Tesollo DG5F URDF+메시 원본 4변형 (검증 스크립트의 대조 기준) |
| `urdf/build_arm_hand.py` | UR 팔+DG5F 손 결합 URDF 빌더 (기종·좌우 파라미터화) |
| `docs/` | Agent 계약, ML-Agents 설계·학습 가이드, 전체 작업 이력 |
| `training/` | DG5FGraspPointReach PPO 설정, 학습·평가 도구 |

### 디렉터리별 README 지도

각 폴더에 **그 폴더 안의 코드를 파일 단위로 설명하는 README**가 있다. 폴더를 열었을 때
"이게 뭐지"의 답은 그 폴더의 README에, "이 기능이 어디서 어떻게 이어지지"의 답은
[`docs/modules/`](docs/modules/README.md)에 있다.

| 폴더 | README | 다루는 것 |
|---|---|---|
| `arm/` | [README](arm/README.md) | UR16e RTDE 브리지, URSim 실행, 재접속 로직 |
| `config/` | [README](config/README.md) | 모든 IP·포트·경로의 정본, `.env` 우선순위 |
| `urdf/` | [README](urdf/README.md) | 결합 URDF 빌더 5단계, 링크 이름 규칙 |
| `tools/` | [README](tools/README.md) | 임포트 도구, 학습 곡선 렌더링, 방화벽 토글 |
| `build-support/` | [README](build-support/README.md) | Linux 플레이어 빌드 후처리 자산 |
| `vision/` | [README](vision/README.md) | 손 텔레옵 흐름, 브리지 3종, 검증 도구 |
| `vision/dg5f/` | [README](vision/dg5f/README.md) | 채널·매핑·패킷 계약(정본) |
| `vision/dg5f/tests/` | [README](vision/dg5f/tests/README.md) | 다중 카메라 캘리브레이션 수학 테스트 |
| `unity/` | [README](unity/README.md) | 프로젝트 정보, 씬 목록, 에디터 메뉴, 빌드 |
| `unity/Assets/Scripts/` | [README](unity/Assets/Scripts/README.md) | 통신·구동·IK·로깅 C# 파일별 상세 |
| `unity/Assets/MLAgents/` | [README](unity/Assets/MLAgents/README.md) | 관찰 57칸·행동 7칸·판정 상수·씬 빌더 |
| `unity/Assets/Editor/` | [README](unity/Assets/Editor/README.md) | 로봇 임포트·검수 메뉴 |
| `unity/Assets/Robots/` | [README](unity/Assets/Robots/README.md) | 임포트된 프리팹·메시(생성물) |
| `training/` | [README](training/README.md) | 학습 실행 절차(정본) |
| `training/scripts/` | [README](training/scripts/README.md) | 런처·모니터·격리·전이 스크립트 |
| `training/config/` | [README](training/config/README.md) | PPO 설정·커리큘럼·실험 파일 이름 규칙 |
| `training/tests/` | [README](training/tests/README.md) | 파이썬 회귀 테스트와 현재 통과 상태 |
| `docs/` | [README](docs/README.md) | 문서 인덱스 |
| `docs/modules/` | [README](docs/modules/README.md) | 기능 단위 모듈 설명 5종 |

용어 표기는 [`docs/GLOSSARY.md`](docs/GLOSSARY.md)를 정본으로 쓴다 — 같은 것을 같은 말로
부르기 위한 표준 용어표이며, 새 용어를 도입하면 거기에 먼저 추가한다.
각 README 끝에는 **문서 이력**(버전·일자·변경자·내용·사유)과 함께 갱신할 문서 목록이 있다.

폐기·잔재 폴더에도 **왜 남겨 두었고 쓰면 안 되는지**를 적은 README를 두었다:
[`unity/Assets/Script/`](unity/Assets/Script/README.md)(단수, Rainbow Robotics 잔재) ·
[`vision/zed_object_detection/`](vision/zed_object_detection/DEPRECATED.md) ·
[`training/archives/`](training/archives/README.md) · [`docs/archives/`](docs/archives/README.md)

## 새 환경 셋업

### 1. Unity
- **Unity 6000.4.0f1** (다른 버전은 ArticulationBody 물리 재검증 필요)
- Unity Hub → Open → `unity/` 폴더 선택. 첫 오픈 시 Library 생성으로 수 분 소요.
- 렌더 파이프라인: Built-in (URP 아님 — 머티리얼 마젠타면 확인)
- 시연 씬: `Assets/Scenes/Pipeline_Demo_GraspLift.unity`
- 결합 프리팹: `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab`
- ML-Agents 학습 환경: `Assets/MLAgents/picknplace/` (`DG5FPicknPlace`라는 기존 이름을
  유지하지만 현재 태스크는 place가 제거된 grasp+lift다.)
- 학습 실행법은 `training/README.md`, 계약과 근거는 `docs/DG5F_PICKNPLACE.md` 참고.

### 2. Python — **3.10.11 권장, 비전+ML-Agents 공용 가상환경 1개**

설치 절차(Windows/Linux, 초보자 기준)는 [`docs/PYTHON_ENV_SETUP.md`](docs/PYTHON_ENV_SETUP.md)로
분리했다 — conda/pyenv 없이 `venv`만으로 진행한다. 아래는 버전 선택 근거와
검증된 패키지 조합만 요약.

버전 선택 근거:
- **ML-Agents(mlagents)는 Python 3.10.x 전용**이며 패치버전은 안 가린다
  (2026-07-14 `3.10.12`, `3.10.4` 모두 동작 확인). **3.10.11로 고정**한 이유는
  Windows용 설치 파일이 배포되는 마지막 3.10 패치가 3.10.11이기 때문
  (3.10.12부터는 "보안 패치만" 단계로 들어가 소스만 배포 — 2026-08-26 확인).
- 기존 판단은 `mediapipe 0.10.14`(protobuf 4.x 계열) 때문에 ML-Agents(protobuf 3.x)와
  가상환경을 분리해야 한다는 것이었으나, **`mediapipe==0.10.11`로 낮추면 `protobuf==3.20.3`에서
  동작**해 ML-Agents와 같은 venv에 공존 가능하다.
- 현재 검증된 핵심 버전: `mediapipe==0.10.11`, `protobuf==3.20.3`, `numpy==1.23.5`,
  `opencv-contrib-python==4.8.1.78`, `mlagents/mlagents_envs==1.2.0.dev0`.
- **torch**: 전용 학습 서버(VDI)가 없어져 이제 본학습도 이 로컬 GPU에서 돌리므로
  `torch==2.1.1+cpu`가 아니라 **드라이버 CUDA 버전에 맞는 CUDA 빌드**를 설치한다
  (`nvidia-smi`로 CUDA 버전 확인 후 고르기 — 예: 드라이버가 지원하는 최대 CUDA가
  12.3이면 그 이하인 `cu121` 휠로 충분. PyTorch는 CUDA 버전을 정확히 맞추는 게 아니라
  "드라이버가 지원하는 버전 이하"인 배포 휠 중에서 고르는 것).
- `mlagents/mlagents_envs==1.2.0.dev0`은 `requirements-mlagents.txt`에 Release 23 커밋으로
  고정했다. **GPU가 있는 머신에서 `torch_settings.device: cpu`로 학습 config를 돌리면
  안 됨** — 이 dev 빌드는 모듈 로드 시 GPU가 있으면 PyTorch 전역 기본 디바이스를
  cuda로 걸어두고, 이후 `device: cpu` 설정이 이걸 되돌리지 못하는 버그가 있어
  `cpu vs cuda:0` 텐서 불일치로 죽는다 (`mlagents/torch_utils/torch.py`
  `set_torch_config`). GPU 머신에서는 학습 config의 `torch_settings.device`를
  **`cuda`로 맞출 것** (`training/config/dg5f_grasp_lift.yaml` 참고).

설치 후 `pip check`와 `mlagents-learn --help`를 반드시 확인한다. 텔레옵 스크립트(`vision/`)도
같은 공용 venv에서 실행한다.

### 3. (선택) unity-cli — 에디터를 CLI로 제어 (임포트/프로브 자동화에 사용)
- https://github.com/akiojin/unity-cli 설치 후 Unity 프로젝트에 커넥터 패키지 추가.
- 없어도 텔레옵 자체는 동작 (Play는 에디터에서 직접).

### 4. 로컬 설정 (새 PC에서 1회)
머신마다 다른 경로/IP/포트는 코드에 하드코딩하지 않고 레포 루트 `.env`(git 비추적, `.env.example`
복사) 하나로 관리한다 — 값과 우선순위는 `config/rtauto_config.py` 참고.
- `RTAUTO_UNITY_PROJECT`, `RTAUTO_UNITY_CLI` — `tools/urdf_hand_import/import_hand.py`
  (및 이를 재사용하는 probe_test/phys_compare/setup_drive)의 Unity 프로젝트·unity-cli 경로.
  안 채우면 `--project`/`--cli`를 직접 넘겨야 하며, 둘 다 없으면 명확한 에러로 멈춘다.
- `RTAUTO_UNITY_IP`, `RTAUTO_PORT_*` — Unity ↔ Python vision 스크립트 UDP 통신. 이 PC에서
  Unity가 로컬로 돈다면 기본값 그대로 둬도 된다.
- `vision/dg5f/analyze_teleop.py`는 환경변수 `DG5F_UNITY_LOGS`, `DG5F_URDF_DIR` 또는
  `--logs-dir/--urdf-dir` 인자로 대체 가능

## 빠른 시연 (웹캠 1대, 이 PC만 — 설정 불필요)

디지털 트윈 시연은 **웹캠만 꽂으면** 바로 된다. 별도 기기 연동도, 포트/IP 설정도 없다.

1. Unity에서 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`를 열고 **Play ▶**
   (수동 모드로 자동 시작 — 학습된 정책 없이 동작한다)
2. 손 트래킹 실행:
   ```bash
   python vision/dg5f/vision_node_dg5f.py right
   ```
3. 화면 좌상단 **"손 트래킹: 수신중"**(초록)이 뜨면 연결된 것이다. 주황색
   **"대기중"**이면 2번이 아직 안 돌고 있다는 뜻.

조작은 두 가지다 — **손가락**은 웹캠 앞에서 오른손을 움직이면 그대로 미러링되고,
**팔**은 화면 **오른쪽 "UR16e 팔" 패널**의 6축 관절 슬라이더(Shoulder Pan / Shoulder
Lift / Elbow / Wrist 1~3)로 움직인다.

> **화면 배치 (2026-09-04 정리)**: **왼쪽 열 = 손·모드**(제어 모드 → 디지털 트윈 방향(손)
> → 손 프리셋 → 실물 손 송신), **오른쪽 열 = 팔·URSim**(UR16e 팔 패널). 패널 좌표는
> `DemoUiLayout`이 순서대로 쌓아 계산하므로 패널이 늘거나 높이가 바뀌어도 겹치지 않는다.
> 예전에 있던 **팔 조이스틱·높이 슬라이더(작업공간 IK)는 제거**했다 — URSim RTDE가
> 관절각 단위라 두 조작 방식이 같은 관절 목표를 다퉜다.

왼쪽 프리셋 패널의 버튼(**주먹 쥐기 / 손 펴기 / 파지하기**)은 웹캠 없이 자세를 재생한다.
프리셋과 웹캠은 같은 관절을 건드리므로 **한 번에 하나만** 손을 쥔다 — 지금 누가 쥐고
있는지는 같은 패널의 **"손 주인: …"** 표시로 항상 보인다. 프리셋을 누르면 주인이 프리셋으로
넘어가고, **"웹캠 실시간 조작으로"** 버튼을 누르면 **현재 자세를 유지한 채** 웹캠으로
돌아온다(자세가 초기화되지 않는다).

> 포트는 Unity와 Python이 **같은 파일 하나**(레포 루트 `.env`, 없으면 `.env.example`)를
> 읽으므로 손댈 일이 없다. 5006이 다른 프로그램과 겹칠 때만 `.env`의
> `RTAUTO_PORT_DG5F_SIM`을 바꾸면 양쪽이 함께 따라온다. 카메라가 여러 대라
> 엉뚱한 게 잡히면 `.env`의 `RTAUTO_VISION_CAMERA_INDEX`를 0, 1, 2로 바꿔본다.
> 사용자·카메라가 바뀌었으면 최초 1회 `python vision/dg5f/calibrate_dg5f.py`로 보정한다.

## 실물 그리퍼까지 연결한 시연 (웹캠 → MediaPipe → Unity → 실물 DG-5F)

위 트윈 시연에 실물 그리퍼를 붙인 것. 웹캠으로 잡은 손 자세가 Unity 트윈을 거쳐 실물
DG-5F-M-R까지 전달된다. **2026-09-01 동작 확인.**

전제 조건 세 가지 — 하나라도 빠지면 브리지가 연결 단계에서 멈춘다:
- 랜선이 **그리퍼용 이더넷**에 꽂혀 있어야 한다. 그리퍼는 보통 링크로컬(169.254.x.x)이라
  사무망에 꽂힌 상태에서는 아예 도달하지 않는다(`ping <그리퍼IP>`로 먼저 확인).
- `.env`에 `RTAUTO_DG5F_IP`가 채워져 있어야 한다(`.env.example` 참고).
- **DGManager는 종료할 것.** 그리퍼는 프로토콜·제어모드와 무관하게 TCP 세션을 **1개만**
  받는다(2026-08-31 실측) — DGManager가 붙어 있으면 우리 브리지가 못 들어간다.

1. **실물 브리지**를 먼저 띄운다. IP는 `.env`에서 읽으므로 값을 적지 않는다:
   ```bash
   python vision/dg5f/dg5f_sdk_bridge.py --ip --model 5f_right
   ```
   `[수신] UDP :5008 대기`가 뜨면 준비된 것이다.
   `ConnectToGripper 실패 — DG_RESULT=500`이 나오면 **5~10초 기다렸다 재시도**한다 —
   직전 세션이 아직 물려 있는 것이다(그리퍼가 세션 1개만 받는 것의 이면).
2. Unity에서 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`를 열고 **Play ▶**
3. **손 트래킹**을 띄워 트윈이 먼저 내 손을 따라오게 한다:
   ```bash
   python vision/dg5f/vision_node_dg5f.py right
   ```
   좌상단이 **"손 트래킹: 수신중"**(초록)인지 확인.
4. 손을 **편 중립 자세**로 두고, Unity 화면 **왼쪽 열의 `실물 송신 OFF` 토글을 ON**으로 바꾼다.
   이 순서를 지키는 이유: 트윈이 이미 내 손 자세를 잡고 있으면 실물의 이동량이 0에 가깝다.
   순서를 뒤집으면 실물이 트윈의 기본 자세(손 편 상태)까지 한 번에 움직인다 —
   브리지 슬루 리밋(`RTAUTO_DG5F_MAX_DEG_PER_SEC`, 기본 100 deg/s)이 속도는 막아주지만
   "움직일 필요 자체"를 없애주지는 못한다.

> ⚠️ **좌하단 "sim → real" 버튼은 이 시연에서 쓰지 않는다.** 그 모드는 되먹임 루프를
> 막으려고 `Dg5fReceiver`/`Dg5fHandDriver`를 끄는데, 그게 바로 웹캠 미러링 경로다
> (그 모드의 구동 소스는 웹캠이 아니라 주먹/파지 버튼이다). 4번의 `실물 송신` 토글만 쓴다.
> "연결 끊기"는 실물 송신만 멈추고 웹캠 미러링은 유지한다.
>
> ⚠️ **브리지에 `--echo-to-unity`를 붙이지 않는다.** 그 옵션은 실물 상태를 5006으로
> 되쏘는데, 5006은 웹캠 스트림이 쓰는 포트라 두 스트림이 섞인다.
>
> 브리지가 `UDP :5008 바인드 실패`로 멈추면 같은 포트를 듣는 브리지가 이미 떠 있는 것이다.
> 에러 메시지가 점유 프로세스 확인 명령을 함께 출력한다.

트윈과 실물을 **Unity를 거치지 않고** 같은 웹캠 스트림으로 병렬 구동하려면(더 단순하지만
Unity 관절이 아니라 비전 패킷이 실물에 직접 간다):
```bash
python vision/dg5f/vision_node_dg5f.py right --bridge
```

## UR16e 팔 디지털 트윈 (Unity ↔ URSim)

**2026-09-04 착수.** 손(DG5F)과 별개로 팔(UR16e)을 Unity와 URSim(UR 공식 가상
컨트롤박스) 사이에서 왕복시키는 경로. 실물 UR16e는 Manual→Automatic 모드 전환
안전 비밀번호가 아직 없어 실물 검증은 보류 중이지만(`docs/SIM2REAL_ROADMAP.md` §11),
URSim은 이 블로커와 무관하게 지금 바로 검증할 수 있다.

```text
Unity UrArmSender.cs -> UDP:5009 -> arm/ur_rtde_bridge.py -> RTDE servoJ -> URSim
                                          |
                                          '--echo-to-unity--> UDP:5010 -> Unity UrArmReceiver.cs
```

1. **URSim 실행** (도커 필요):
   ```powershell
   .\arm\run_ursim.ps1
   ```
   ```bash
   ./arm/run_ursim.sh
   ```
   펜던트 화면: `http://localhost:6080/vnc.html`. 첫 부팅 시 안전 설정 초기화 화면이
   나오면 기본값으로 Confirm — URSim은 실물과 달리 Manual→Automatic 전환에 별도
   비밀번호가 걸려 있지 않다. **이어서 펜던트 화면 하단의 `Power off` 표시를 눌러
   `Power On` → `Brake Release`(또는 `Start`)까지 진행할 것** — 이걸 안 하면
   로봇이 정지 상태라 다음 단계에서 브리지가 붙어도 `servoJ`가 거부되거나 조용히
   씹힌다(실물도 동일 — 컨트롤박스 전원만 켠 상태와 "구동 가능" 상태는 다르다).
2. **RTDE 브리지** 실행 — **Unity 안의 버튼으로 띄우는 게 기본**이다(3번 참고).
   "UR16e 팔" 패널의 **`브리지 실행`** 버튼이 아래 명령을 저장소 루트에서 그대로 실행하고,
   Play를 멈추면 프로세스를 죽인다(살려두면 UDP 포트를 쥔 채 남아 다음 실행이 바인드
   실패로 죽는다). 별도 콘솔 창이 열려 브리지 로그가 그대로 보인다.

   터미널에서 직접 띄우고 싶으면 — **터미널 2 (PowerShell/bash, 리포 루트, RTDE 브리지)**,
   위 URSim 창과는 별개다. 텔레옵과 같은 공용 venv(`vision/.vision`,
   `docs/PYTHON_ENV_SETUP.md` §2)를 활성화한다. `ur_rtde`는 `requirements-vision.txt`에
   포함돼 있어 이 venv에 이미 설치돼 있다:
   ```powershell
   .\vision\.vision\Scripts\Activate.ps1
   python arm/ur_rtde_bridge.py --ip --echo-to-unity
   ```
   ```bash
   source vision/.vision/bin/activate
   python arm/ur_rtde_bridge.py --ip --echo-to-unity
   ```
   `--ip`만 주면 `.env`의 `RTAUTO_UR_IP`(기본 `127.0.0.1` = 로컬 URSim)를 쓴다.
   `[연결] RTDE 접속 완료`가 뜨면 준비된 것이다. 종료는 `Ctrl+C`.

   > 버튼이 쓰는 파이썬은 `.env`의 `RTAUTO_PYTHON`이고, 비워두면 OS별 공용 venv 기본
   > 경로(Windows `vision/.vision/Scripts/python.exe`)를 쓴다. venv를 아직 안 만들었다면
   > 버튼이 "파이썬 없음 — venv 먼저 만들 것"으로 실패하고 Console에 만드는 법이 찍힌다.
3. **Unity 에디터에서 Play.**
   1. Project 창(에디터 하단)에서 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`를
      더블클릭해 연다.
   2. 에디터 상단 중앙의 **▶(Play)** 버튼을 누른다. 다시 누르면 멈춘다.
   3. Game 화면 **오른쪽 "UR16e 팔" 패널**에 URSim 연동 UI가 나온다. 필요한 컴포넌트
      (`UrArmSender`/`UrArmReceiver`/`UrArmTwinDriver`)는 씬에 이미 붙어 있고,
      씬을 새로 빌드해도 `PicknPlacePipelineDemoSceneBuilder`가 자동으로 붙인다 —
      손으로 추가할 것은 없다.

   패널 맨 위 **`브리지 실행`** 버튼을 누르면 2번의 파이썬 브리지가 뜬다(콘솔 창이 따로
   열린다). 아래 **`브리지: 실행 중`** 표시로 상태를 확인한다. **`브리지 중지`**로 내리고,
   Play를 멈춰도 자동으로 내려간다.

   그 아래 **"URSim 연동 방향"**에서 방향을 고른다. 둘은 **상호배타**라 하나를 켜면
   다른 하나가 자동으로 꺼진다(되먹임 루프 방지 — Unity 목표 → URSim → echo → 다시 Unity):

   | 버튼 | 방향 | 무슨 일이 일어나나 |
   |---|---|---|
   | `Unity→URSim` | Unity가 URSim을 구동 | 관절 슬라이더(또는 자동 모드의 정책)가 URSim을 움직인다 |
   | `URSim→Unity` | URSim이 Unity를 구동 | **펜던트에서 직접 조그**하거나 URScript를 돌리면 Unity가 따라온다. 이때 슬라이더는 잠긴다 |

   그 아래 초록색 **"URSim: 수신중"**이 뜨면 브리지가 붙은 것이고, 주황색
   **"URSim: 대기중"**이면 2번 브리지가 안 돌고 있다는 뜻이다. 각 관절 줄에는
   `명령각 / URSim 실제각`이 함께 표시돼 추종 오차를 바로 볼 수 있다.
   **"URSim 실제각으로 맞추기"** 버튼은 Unity 자세를 URSim 현재 자세로 한 번에 맞춘다 —
   두 자세가 벌어진 채 `Unity→URSim`을 켜면 URSim이 그 간극만큼 한꺼번에 움직이므로,
   켜기 전에 눌러두면 안전하다.

포트·IP는 전부 `.env`(`RTAUTO_PORT_UR_ARM_BRIDGE`/`RTAUTO_PORT_UR_ARM_SIM`/`RTAUTO_UR_IP`)
에서 관리한다 — 실물로 전환할 때는 `RTAUTO_UR_IP`만 컨트롤박스 IP로 바꾸면 된다(원칙 1).
관절 순서·부호·슬루 리밋 등 상세는 `arm/ur_rtde_bridge.py` 안내문 및
`docs/SIM2REAL_ROADMAP.md` §9 "URSim 선행 개발 경로" 참고.

## 다른 PC에 exe로 배포 (설치 없이 시연)

현재 데모(`Pipeline_Demo_GraspLift`)는 학습된 정책이 아직 없어 **웹캠 텔레옵이 유일한
동작 경로**다 — 즉 "설치 없이 exe만 받아서 실행"하려면 두 실행파일이 함께 필요하다.
Unity 빌드만으로는 손이 안 움직인다(웹캠 신호가 없으므로).

1. **Unity 빌드**: File > Build Settings에서 활성 씬이
   `Assets/Scenes/Pipeline_Demo_GraspLift.unity`(인덱스 0)인지 확인 후 Windows Standalone으로
   Build. 산출물(`KDT_robot_AI.exe` + `KDT_robot_AI_Data/`)은 그 자체로 설치 불필요 —
   폴더째 복사하면 다른 PC에서 바로 실행된다.
2. **웹캠 트래킹 exe화**: 비전+ML-Agents 공용 venv(3.10.11)를 활성화한 상태에서
   ```powershell
   .\vision\dg5f\build_demo_exe.ps1
   ```
   실행. `vision/dg5f/dist/vision_node_dg5f/` 폴더째가 산출물이다 — mediapipe가 모델
   파일과 네이티브 바이너리를 들고 다녀서 `--onefile`이 아니라 폴더 배포로 만들었다.
3. 1번과 2번의 산출물을 한 폴더에 모으고 `vision/dg5f/RunDemo.ps1`을 그 폴더에 복사해
   넣으면(스크립트 안 폴더 구조 주석 참고) 더블클릭 한 번으로 웹캠 트래킹 + Unity가
   함께 뜬다.

> ⚠️ **PyInstaller로 mediapipe를 묶는 건 버전마다 깨지는 사례가 흔하다.** 빌드가
> 끝났다고 끝난 게 아니다 — 산출물 폴더를 레포 밖으로 옮겨서 실제로 실행해보고 웹캠이
> 뜨는지, 콘솔에 관절각이 찍히는지 반드시 확인할 것. 배포 대상 PC에는 웹캠 자체는
> 있어야 한다(텔레옵이 유일한 동작 경로이므로).
>
> 자동(정책 기반) 모드가 준비되면 이 웹캠 의존성 자체가 사라진다 — Unity의 ONNX 추론은
> 이미 임베디드라 Unity 빌드 하나만으로 시연이 끝난다. 현재는 `Assets/MLAgents/picknplace/`
> 쪽 정책이 아직 학습되지 않아(`PicknPlaceControlModeSwitcher`가 기본 수동모드로 시작하는
> 이유) 이 경로를 쓸 수 없다.

## 텔레옵 실행 (UR16e + 오른손 모델)

```bash
python vision/dg5f/calibrate_dg5f.py  # 새 사용자/카메라에서 최초 1회 보정
# Unity에서 Pipeline_Demo_GraspLift 씬 Play ▶ (수동 모드로 자동 시작)
python vision/dg5f/vision_node_dg5f.py right
```
- 프로토콜/채널 순서/좌표계 계약은 `vision/dg5f/README.md` 참고 (v2: 관절각 20 + 엄지끝 위치 + 핀치)
- 웹캠 없이 오른손 배선 검증: `python probe_sender.py fist right` / `open right`
- 추종 정량 분석: `python analyze_teleop.py latest latest --hand right`
  (Unity 쪽은 Dg5fJointLogger가 Play마다 자동 기록)

## 새 핸드 URDF 임포트 (범용 파이프라인)

```bash
cd tools/urdf_hand_import
python import_hand.py <hand.urdf> --prefab --verify   # 복사→패치→임포트→물리 전수대조→프리팹
python setup_drive.py <이름>                           # 구동 준비 일괄 (Controller 제거/게인/중력 등)
python probe_test.py <이름> --urdf <hand.urdf>         # 전 관절 사각파 구동 검증
```
자세한 절차·함정 목록은 `tools/urdf_hand_import/README.md`.

## 강화학습 계약

- Behavior: `DG5FPicknPlace` (레거시 이름, 현재 동작은 grasp+lift)
- observation 57개, continuous action 7개(UR16e 팔 6 + 손 closure 1)
- 모델: UR16e + DG-5F-M-R 오른손
- 대상: 0.035×0.12×0.035m 블록
- 성공: force-closure 파지를 확인하고 목표 높이까지 들어 올려 유지
학습·평가 명령은 [`training/README.md`](training/README.md)를 따른다.

## 현재 상태 / 알려진 이슈 (2026-07-20)

- ✅ DG5F 4변형 임포트·물리검증·구동검증 완료, 굽힘 텔레옵 전 채널 PASS(상관 1.00)
- ✅ 엄지 손끝 위치 리타게팅 v2 + 핀치 스냅 (OK 사인 접촉 프로브 검증 완료)
- ⚠️ **엄지 라이브 움직임이 부드럽지 않음** — 진행 중. 후보: 데드밴드 동결/재가동 경계,
  CCD 스텝 제한, 비전 깊이 노이즈. `docs/WORKLOG.md` §20-3 미해결 항목 참고.
- ✅ UR5e+DG5F 결합 및 GraspPoint 기준점 검증
- ✅ 단일 GraspPoint 팔 도달 환경 전환 및 512 max-step 통신 smoke
- ⏳ 5M 본학습과 미학습 고정 seed 500회 승인 평가
- ⬜ 벌림(n_1)·새끼접기(5_1) 채널 게이트 해제
