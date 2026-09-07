# 설정 · 빌드 · 주변 도구 모듈 설명

설정값과 로봇 모델을 각 프로그램이 사용할 수 있는 형태로 준비하는 부분이다.

## 먼저 이해할 입력과 산출물

이 문서의 도구는 장비 주소·경로 설정, 로봇 모델 생성, Unity 임포트·빌드를 담당한다.
URDF는 로봇의 링크·관절·물리값을 적은 모델 파일이고, 메시는 화면과 충돌 계산에 쓰는 형상이다.
프리팹은 Unity에서 재사용하는 로봇 원본, 플레이어는 Unity Editor 없이 실행하는 빌드 결과다.

현재 결합 로봇이 학습에 들어가는 흐름은 다음과 같다. 범용 손 임포트 도구는 §3에 따로 설명한다.

```text
UR description + DG5F URDF/메시
  → build_arm_hand.py → 결합 URDF/메시
  → Preview 임포트 → 로봇 프리팹 추출
  → 학습 씬·학습 영역 프리팹 생성
      ├→ 학습용 플레이어 빌드 → Python 학습 런처
      └→ 데모 씬 생성 → 대응 정책을 사용한 시연
```

각 생성기는 입력을 읽어 새 산출물을 만든다. **원본을 고쳤다고 기존 씬·플레이어가 자동 갱신되지는 않는다.**
메뉴와 담당 파일은 [UNITY.md](UNITY.md)의 에디터 툴 표에 있다.

## 1. 설정 정본 — `config/rtauto_config.py`

이 저장소에서 가장 중요한 규칙 하나: **경로·IP·포트를 코드에 리터럴로 적지 않는다**(CLAUDE.md 원칙 1).
Python은 이 설정 모듈을 읽고, Unity 런타임은 `RtautoConfig.cs`, Unity 빌드 도구는
`BuildEnvironment.cs`가 설정 파일을 각각 읽는다. 모든 값이 Python을 거쳐 전달되는 구조는 아니다.

우선순위: **환경변수 > 리포 루트 `.env` > `.env.example` > 코드 기본값**

`.env`가 없어도 `.env.example`의 공유 기본값은 적용된다. 장비 IP·외부 모델 경로처럼
머신별로 필요한 값과 Python·Unity 의존성 설치까지 자동으로 준비된다는 뜻은 아니다.

### 여기 들어 있는 값들

| 분류 | 예시 키 |
|---|---|
| 포트 | `PORT_DG5F_SIM`(5006, Unity 손 트윈) · `PORT_ZED_TARGET`(5007) · `PORT_DG5F_BRIDGE`(5008, 실물 손) · `PORT_UR_ARM_BRIDGE`(5009, Unity→팔) · `PORT_UR_ARM_SIM`(5010, 팔→Unity) · `PORT_MLAGENTS_BASE`(5100) |
| IP | `UNITY_IP` · `DG5F_IP` · `UR_IP`(기본 127.0.0.1 = 로컬 URSim) |
| 경로 | `PYTHON_EXE` · `UNITY_PROJECT` · `UNITY_CLI` · `DG5F_DLL` · `UR_DESCRIPTION` · `TRAINING_RESULTS_DIR` |
| 하드웨어 | `UR_TYPE`(ur16e) · `DG5F_HAND`(right) · 속도 상한 `UR_MAX_DEG_PER_SEC` / `DG5F_MAX_DEG_PER_SEC` |
| 카메라 | `VISION_CAMERA_INDEX/WIDTH/HEIGHT/FPS/BACKEND`, 체스보드 규격 `CALIB_BOARD_*` |
| 학습 | `TRAIN_AREAS`(40) · `TRAIN_NUM_ENVS` · 플레이어 출력 경로/이름 |

표의 키는 Python 상수 이름이다. `.env`에는 대응하는 환경변수 이름을 적는다.

| Python 상수 | 실제 `.env` 키 | 무엇을 지정하나 |
|---|---|---|
| `UNITY_IP` | `RTAUTO_UNITY_IP` | Unity가 실행되는 PC의 주소 |
| `DG5F_BRIDGE_IP` | `RTAUTO_DG5F_BRIDGE_IP` | Unity가 명령을 보낼 손 브리지 PC의 주소 |
| `DG5F_IP` / `UR_IP` | `RTAUTO_DG5F_IP` / `RTAUTO_UR_IP` | 손 장비 / 팔 컨트롤러 주소 |
| `PYTHON_EXE` | `RTAUTO_PYTHON` | Unity 팔 런처가 실행할 Python |
| `TRAIN_AREAS` | `DG5F_PICKNPLACE_TRAINING_AREAS` | 플레이어 하나에 들어갈 학습 영역 수 |
| `TRAIN_NUM_ENVS` | `RTAUTO_TRAIN_NUM_ENVS` | 동시에 실행할 플레이어 수 |

나머지 키와 기본값은 [`.env.example`](../../.env.example),
[Python 설정 모듈](../../config/rtauto_config.py)을 참고한다. 환경변수가 `.env`보다 우선하므로
파일을 바꿔도 값이 그대로라면 실행한 터미널의 환경변수도 확인한다.

### 설정 파일을 찾는 위치 — 현재 배포 제한

2026-09-07 코드 대조 기준 위치다. 다음 차이는 **현재 미수정 구현**이며 공통 배포 규칙으로 오해하지 않는다.

| 실행 형태 | `.env`·`.env.example` 탐색 위치 |
|---|---|
| Python 소스 실행 | `config/rtauto_config.py`를 기준으로 계산한 저장소 루트 |
| PyInstaller 실행파일 | 그 실행파일이 있는 폴더 |
| Unity Editor | `unity/Assets`에서 두 단계 위인 저장소 루트 |
| 일반적인 Windows Unity 플레이어 | `Demo_Data`에서 두 단계 위, 즉 **실행파일 폴더의 상위 폴더** |

따라서 배포 폴더에 `.env` 하나를 놓으면 양쪽이 반드시 같은 값을 읽는다는 보장은 없다.
`RunDemo.ps1`은 비전 exe를 하위 폴더에서 실행하므로 각 프로그램의 실제 탐색 위치를 따로 대조해야 한다.
이 문서는 Windows 플레이어의 현재 경로 계산을 설명하며 다른 플랫폼의 배포 구조까지 검증한 것은 아니다.

근거: [RtautoConfig.cs의 ResolveRepositoryRoot](../../unity/Assets/Scripts/RtautoConfig.cs),
[배포 런처](../../vision/dg5f/RunDemo.ps1).

**같은 값을 읽는 형제 파일**: `unity/Assets/Scripts/RtautoConfig.cs` (C#은 파이썬을 import할 수 없어
같은 우선순위를 의도해 `.env`를 직접 파싱한다). 이게 없으면 `.env`에서 포트를 바꿨을 때 파이썬은 새 포트로 쏘고
Unity는 옛 포트에서 기다리는 **에러 없는 조용한 실패**가 난다.

빈 값·잘못된 숫자의 처리까지 동일하지는 않다. Python의 숫자 변환은 오류를 낼 수 있고,
Unity 런타임의 정수 설정은 기본값으로 돌아간다. 설정은 시작 시 읽거나 캐시하므로 실행 중 즉시 반영을
기대하지 않는다. Python은 재시작하고, Unity는 설정을 다시 로드하는 세션에서 적용값을 확인한다.

### 설정·모델을 바꾼 뒤 무엇을 다시 만들어야 하나

| 바꾼 것 | 반영 경로 |
|---|---|
| IP·포트·카메라 설정 | 송수신 프로그램 재시작 후 실제 적용값 확인 |
| 학습 영역 수 | 학습 씬 재생성 → 플레이어 재빌드. 기존 exe의 영역 수는 그대로 |
| 동시 플레이어 수 | 다음 학습 실행 시 적용. 총 에이전트 수는 **빌드에 들어간 영역 수 × 플레이어 수** |
| URDF·로봇 물리값 | 해당 임포트·프리팹·씬 생성 경로를 다시 거친 뒤 물리 검증·재빌드 |
| 보상·관찰·행동 코드 | 학습용 플레이어 재빌드, 정책 계약·재학습 필요 여부 확인 |

근거: [학습 씬 생성기](../../unity/Assets/MLAgents/picknplace/Editor/PicknPlaceTrainingSceneBuilder.cs).

## 2. 로봇 모델 만들기 — `urdf/`

| 파일 | 하는 일 |
|---|---|
| `urdf/build_arm_hand.py` | **UR 팔 + DG5F 손을 하나의 URDF로 결합**한다. 기종(`--ur-type`)과 좌우(`--hand`)가 파라미터. UR tool0에 `dg_mount`를 고정 연결하고, mesh 경로를 상대경로로 통일하고, 메시 실파일도 출력 폴더로 복사한다(빌드 폴더 자체가 임포트 소스) |
| `urdf/ur16e_dg5f_right_build/` | 위 스크립트의 산출물 — **현재 쓰는 결합 URDF + 메시** |
| `urdf/dg5f/` | 손 단독 URDF 4종(오른/왼 × 일반/숏) + 메시 |

- 링크 접두사가 손마다 다르다: 왼손 `ll_`, 오른손 `rl_`. 관절 이름 매칭 코드가 이 규칙에 의존한다.
- DG5F는 mimic 관절이 없다 — 20관절 전부 독립.
- UR description은 외부 공개 레포라 저장소에 포함하지 않는다. 경로는 `.env`의 `RTAUTO_UR_DESCRIPTION`.

## 3. URDF → Unity 임포트 — `tools/urdf_hand_import/`

URDF를 Unity에 넣으면 그냥은 못 쓴다. 그 격차를 메우는 4단계 도구다.

| 파일 | 단계 | 하는 일 |
|---|---|---|
| `import_hand.py` | ① 임포트 | URDF·메시를 Unity `Assets/Robots/`로 복사하고 경로를 패치한 뒤, unity-cli로 URDF-Importer 실행 → 결과 감사 → 프리팹 저장 |
| `phys_compare.py` | ② 검증 | Unity에 들어간 물리값을 URDF 원본과 **전수 대조**(질량·무게중심·관성·리밋·토크). 좌표계 변환까지 반영. PhysX 최소 관성 클램프처럼 알려진 정상 편차는 WARN으로 구분 |
| `setup_drive.py` | ③ 구동 준비 | 임포트 직후엔 모터가 꺼져 있다(stiffness=0). 드라이브 게인 설정 + 중력 끄기 + 루트 고정 + 자기충돌 무시·초기 포즈 동기화 컴포넌트 부착. **멱등**(재실행 안전) |
| `probe_test.py` | ④ 움직임 검증 | 관절에 사각파를 넣어 추종 오차·진동을 판정. 정착오차 ≤1.0°, 잔여진동 ≤0.5°. **`--urdf` 제공 시** 리밋 검사도 수행하며 ±0.5° 여유 밖의 침범 0건이 기준 |

> `setup_drive.py`의 주석에 중요한 트레이드오프가 적혀 있다: `forceLimit`을 URDF의 실제 토크값으로 두면
> 작은 오차에도 토크가 포화돼 **뱅뱅 진동**이 난다. 그래서 사실상 무제한으로 올리고 **하드웨어 토크 상한
> 재현을 포기**했다. 실물 이관 때 다시 봐야 할 지점.

이 설명은 **범용 setup_drive 도구**의 기본값이다. 현재 PicknPlace 학습 씬 빌더는 별도로 드라이브를
설정하며, 팔은 `UrArmLimits.MaxEffortNm`, 손은 `Dg5fPicknPlaceSpec.HandDriveForceLimit`를 쓴다.
범용 도구의 값을 현재 학습 물리값으로 간주하지 않는다. 도구 사용법은
[임포트 도구 README](../../tools/urdf_hand_import/README.md)를 참고한다.

## 4. 기타 도구

| 파일 | 하는 일 |
|---|---|
| `build-support/linux/libdl.so.2` | Linux headless 플레이어 빌드 후처리에 쓰는 벤더링된 라이브러리. Windows/macOS에서 Linux 빌드를 만들 수 있게 한다 |
| `tools/unity_firewall_toggle.ps1` / `.bat` | Unity Editor의 공용 프로필 인바운드 방화벽 규칙을 허용↔차단 토글. 다른 PC에서 UDP를 받아야 할 때만 잠깐 열고 닫는 용도(관리자 권한 자동 승격) |
| `tools/plot_grasp_lift_*.py` | 학습 곡선 그래프 렌더링 → [RL_TRAINING.md](RL_TRAINING.md) 참고 |
| `.gitattributes` | 저장소 줄바꿈을 LF로 고정. 없으면 Windows에서 커밋한 `.sh`가 Linux에서 `bad interpreter: /bin/bash^M`으로 죽는다 |
| `requirements-mlagents.txt` / `requirements-vision.txt` | 의존성. 버전 조합 근거는 [`docs/PYTHON_ENV_SETUP.md`](../PYTHON_ENV_SETUP.md) |
