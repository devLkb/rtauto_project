# `config/` — 모든 IP·포트·경로의 유일한 정본

이 폴더에는 파일이 두 개뿐이지만, **저장소에서 가장 자주 참조되는 폴더**다.
CLAUDE.md 원칙 1("하드코딩 절대 금지")이 실제로 구현된 곳이기 때문이다.

| 파일 | 역할 |
|---|---|
| [`rtauto_config.py`](rtauto_config.py) | 경로·IP·포트·하드웨어 구성의 정본. Python 코드는 전부 이 모듈을 import한다 |
| [`dg5f_grasp_pose.json`](dg5f_grasp_pose.json) | 실물 DG-5F에서 캡처한 파지 자세 20관절각. Unity의 '파지하기' 버튼이 읽는다 |

## 목차

1. [왜 설정을 한 곳에 모으는가](#1-왜-설정을-한-곳에-모으는가)
2. [값 우선순위와 로딩 규칙](#2-값-우선순위와-로딩-규칙)
3. [`rtauto_config.py` 전체 설정 지도](#3-rtauto_configpy-전체-설정-지도)
4. [헬퍼 함수 — "값 없이 `--ip`"가 되는 이유](#4-헬퍼-함수--값-없이---ip가-되는-이유)
5. [같은 `.env`를 읽는 세 구현](#5-같은-env를-읽는-세-구현)
6. [`dg5f_grasp_pose.json` 스키마](#6-dg5f_grasp_posejson-스키마)
7. [따라 하기: 새 PC에서 설정 잡기 / 새 값 추가하기](#7-따라-하기-새-pc에서-설정-잡기--새-값-추가하기)
8. [관련 문서](#8-관련-문서)

## 1. 왜 설정을 한 곳에 모으는가

이 저장소는 과거 5인 팀 체제에서 `C:\Users\...` 경로와 포트 충돌이 광범위하게 퍼졌던 이력이 있다.
같은 포트 번호가 파이썬 세 파일과 C# 두 파일에 각각 타이핑돼 있으면, **한 곳만 고쳤을 때 에러가
전혀 나지 않고 그냥 통신이 안 된다.** 파이썬은 새 포트로 쏘고 Unity는 옛 포트에서 기다리는
"조용한 실패"가 이 폴더가 존재하는 이유다.

규칙은 하나다. **새 포트·경로가 필요하면 `rtauto_config.py`에 추가하고, 다른 파일은 그걸 import한다.
숫자·경로를 두 번째 파일에 다시 타이핑하지 않는다.**

> 관절 오프셋·클램프 같은 **물리/캘리브레이션 상수**는 하드코딩과 다르다. 그것들은 정당한
> 데이터이며, 여기가 아니라 각 도메인의 정본 파일(`Dg5fPicknPlaceSpec.cs`,
> `dg5f_sdk_bridge.JOINT_CLAMP_RIGHT` 등)에 모은다.

## 2. 값 우선순위와 로딩 규칙

```text
프로세스 환경변수  >  리포 루트 .env(git 비추적)  >  .env.example  >  코드 기본값
```

`_load_dotenv()`가 `.env` → `.env.example` 순서로 읽고, 값 주입에 `os.environ.setdefault()`를
쓴다. **먼저 넣은 값이 이기므로** 위 우선순위가 성립한다.

`.env.example`까지 읽는 것이 중요하다 — 새 PC에서 `cp .env.example .env`를 하지 않아도
공유 기본값이 그대로 적용되어, 웹캠만 꽂고 바로 시연할 수 있다.

`_merge_dotenv(path)`가 흡수하는 실수들:

| 관용 처리 | 왜 필요한가 |
|---|---|
| `utf-8-sig`로 읽기 | Windows 메모장/`Set-Content`가 BOM을 붙이면 첫 줄 키가 `﻿RTAUTO_...`가 돼 **조용히 무시된다** |
| `export KEY=value` 접두사 제거 | Linux/macOS 사용자가 습관적으로 붙인다 |
| 값 양끝 따옴표 제거 | 안 벗기면 경로·IP에 `"`가 섞여 들어간다 |
| `#` 주석·빈 줄·`=` 없는 줄 건너뛰기 | — |

**`REPO_ROOT` 계산**: 보통은 `config/rtauto_config.py`의 두 단계 위. 단 PyInstaller로 얼린
실행파일(`sys.frozen`)에서는 `__file__`이 임시 해제 폴더를 가리키므로 **exe가 놓인 디렉터리**를
기준으로 삼는다. Unity `RtautoConfig.cs`가 빌드된 실행파일 옆에서 `.env`를 찾는 관례와 맞춘 것이다.

## 3. `rtauto_config.py` 전체 설정 지도

### 3-1. 포트 (`PORT_*`)

| Python 상수 | `.env` 키 | 기본 | 보내는 쪽 → 받는 쪽 |
|---|---|---|---|
| `PORT_SVH_JOINTS` | `RTAUTO_PORT_SVH_JOINTS` | 5005 | ⛔ 레거시 SVH 손 |
| `PORT_DG5F_SIM` | `RTAUTO_PORT_DG5F_SIM` | 5006 | 비전 / 손 브리지 echo → Unity `Dg5fReceiver` |
| `PORT_ZED_TARGET` | `RTAUTO_PORT_ZED_TARGET` | 5007 | ⛔ 폐기(ZED). **다른 용도로 재사용 금지** |
| `PORT_DG5F_BRIDGE` | `RTAUTO_PORT_DG5F_BRIDGE` | 5008 | Unity `Dg5fSender` / 비전 `--bridge` → 손 SDK 브리지 |
| `PORT_UR_ARM_BRIDGE` | `RTAUTO_PORT_UR_ARM_BRIDGE` | 5009 | Unity `UrArmSender` → 팔 RTDE 브리지 |
| `PORT_UR_ARM_SIM` | `RTAUTO_PORT_UR_ARM_SIM` | 5010 | 팔 브리지 `--echo-to-unity` → Unity `UrArmReceiver` |
| `PORT_MLAGENTS_BASE` | `RTAUTO_PORT_MLAGENTS_BASE` | 5100 | `mlagents-learn --base-port` (플레이어 수만큼 위로 소비) |

> 5007을 비워 둔 이유: 과거 ZED 좌표 송신과 DG5F 브리지가 충돌해 브리지를 5008로 옮긴 이력이 있다.
> 되살릴 계획이 없어도 재사용하면 같은 사고가 반복된다.

### 3-2. IP

| 상수 | `.env` 키 | 기본 | 무엇을 가리키나 |
|---|---|---|---|
| `UNITY_IP` | `RTAUTO_UNITY_IP` | 127.0.0.1 | Unity가 실행되는 PC |
| `DG5F_BRIDGE_IP` | `RTAUTO_DG5F_BRIDGE_IP` | 127.0.0.1 | Unity가 손 명령을 보낼 브리지 PC |
| `DG5F_IP` | `RTAUTO_DG5F_IP` | (빈 값) | 손 **장비** 주소 |
| `UR_IP` | `RTAUTO_UR_IP` | 127.0.0.1 | 팔 컨트롤박스 / 로컬 URSim |

**브리지 PC 주소와 장비 주소는 다른 값**이다. 이 구분을 놓치면 "브리지는 뜨는데 실물이 안 움직임"이 된다.

### 3-3. 경로

`PYTHON_EXE`(`RTAUTO_PYTHON`) · `UNITY_PROJECT` · `UNITY_CLI` · `DG5F_DLL` · `UR_DESCRIPTION` ·
`DG5F_UNITY_LOGS` · `DG5F_URDF_DIR` · `DG5F_GRASP_POSE_FILE`(`RTAUTO_DG5F_GRASP_POSE`,
기본 `config/dg5f_grasp_pose.json`).

학습 산출물 경로는 저장소 상대 기본값을 갖는다 — 머신마다 다른 값이 아니라 리포 레이아웃이기 때문이다.

```text
TRAINING_RESULTS_DIR = training/results        진행 중·미판정 런
TRAINING_FAILURE_DIR = …/results/failure       실패로 판정해 격리한 런
TRAINING_LEGACY_DIR  = …/results/legacy        과거 behavior의 런(재개 대상 아님)
```

failure/legacy는 results에서 **파생**시킨다 — 경로를 두 번 타이핑하지 않기 위해서다.
판정 근거의 정본은 [`docs/TRAINING_RUN_LEDGER.md`](../docs/TRAINING_RUN_LEDGER.md).

### 3-4. 하드웨어 구성

| 상수 | `.env` 키 | 기본 | 비고 |
|---|---|---|---|
| `UR_TYPE` | `RTAUTO_UR_TYPE` | `ur16e` | 이전 자산은 ur5e 기준이었다 |
| `DG5F_HAND` | `RTAUTO_DG5F_HAND` | `right` | DG-5F-M-R = 오른손 |
| `DG5F_SHORT` | `RTAUTO_DG5F_SHORT` | `0` | short 변형 여부 |
| `UR_MAX_DEG_PER_SEC` | `RTAUTO_UR_MAX_DEG_PER_SEC` | 30 | 팔 속도 상한(미검증 보수값) |
| `DG5F_MAX_DEG_PER_SEC` | `RTAUTO_DG5F_MAX_DEG_PER_SEC` | 100 | 손 속도 상한 |

**스펙 변동 가능성이 통보된 상태**라 코드에 박지 않고 여기서 바꾼다(CLAUDE.md 하드웨어 절).

### 3-5. 카메라·캘리브레이션

`VISION_CAMERA_INDEX`(0) · `WIDTH`(1280) · `HEIGHT`(720) · `FPS`(30) · `BACKEND`(`auto`) ·
`VISION_CAMERA_INDICES`(다중 카메라용, 쉼표 구분) ·
`CALIB_BOARD_COLS`(9) · `CALIB_BOARD_ROWS`(6) · `CALIB_SQUARE_SIZE_MM`(25.0) ·
`CALIB_DIR`(`vision/dg5f/camera_calib`).

보드 값은 **내부 코너 개수**다(9×6은 10×7 사각형 보드). 실제 보유한 보드에 맞춰 `.env`에서 덮어쓴다.

### 3-6. 학습·빌드

| 상수 | `.env` 키 | 기본 |
|---|---|---|
| `TRAIN_AREAS` | `DG5F_PICKNPLACE_TRAINING_AREAS` | 40 (플레이어 하나에 들어갈 학습 영역 수) |
| `TRAIN_NUM_ENVS` | `RTAUTO_TRAIN_NUM_ENVS` | 1 (동시 플레이어 수) |
| `PICKNPLACE_BUILD_OUTPUT` / `PICKNPLACE_PLAYER_NAME` | OS별 키 | 플레이어 출력 폴더·실행파일 이름 |

⚠️ **총 에이전트 수 = 빌드에 구워진 영역 수 × 플레이어 수.** 영역 수는 플레이어에 고정되므로
`.env`만 고쳐서는 바뀌지 않는다 — 학습 씬 재생성 → 플레이어 재빌드가 필요하다.

## 4. 헬퍼 함수 — "값 없이 `--ip`"가 되는 이유

브리지들이 `--ip`를 값 없이 받아 `.env`로 떨어질 수 있는 것은 아래 함수들 덕분이다.

| 함수 | 하는 일 |
|---|---|
| `resolve_ur_ip(value)` / `resolve_gripper_ip(value)` | 빈 문자열이면 `.env`의 장비 IP를, 값이 있으면 그 값을. `None`이면 드라이런 |
| `python_exe()` | `RTAUTO_PYTHON`이 비어 있으면 현재 인터프리터로 폴백 |
| `picknplace_player_path()` | 출력 폴더 + 플레이어 이름 + **현재 OS의 확장자**를 조합. 상대경로는 저장소 루트 기준 |
| `dg5f_variant()` | `right`/`left` × `short` → URDF·메시 폴더 이름 (`dg5f_right`, `dg5f_left_short` …) |
| `dg5f_link_prefix()` | URDF 링크 접두사 — 왼손 `ll_`, 오른손 `rl_` (URDF 실측) |
| `_repo_path(key, default)` | 저장소 루트 기준 `Path` 객체. `.env`에서 절대경로로 덮어쓸 수 있다 |

## 5. 같은 `.env`를 읽는 세 구현

C#은 파이썬을 import할 수 없으므로 **같은 우선순위를 의도해 `.env`를 각자 파싱한다.**
셋이 어긋나면 조용한 실패가 난다.

| 구현 | 파일 | 담당 |
|---|---|---|
| Python | `config/rtauto_config.py` | 모든 파이썬 코드 |
| Unity 런타임 | `unity/Assets/Scripts/RtautoConfig.cs` | 씬에서 도는 컴포넌트 |
| Unity 빌드 도구 | `unity/Assets/MLAgents/Editor/BuildEnvironment.cs` | 플레이어 빌드 경로·이름 |

| 항목 | Python | C# 런타임 |
|---|---|---|
| 파일 병합 | `_load_dotenv()` → `_merge_dotenv()` | `EnsureLoaded()` → `Merge()` |
| 값 읽기 | `_env(name, default)` | `GetString(key, fallback)` / `GetInt(key, fallback)` |
| 저장소 루트 | `config/` 기준 상대 계산(얼린 exe는 exe 폴더) | `ResolveRepositoryRoot()` = `Application.dataPath`의 두 단계 위 |
| 실패 처리 | 숫자 변환에서 **예외가 날 수 있다** | **절대 예외를 던지지 않는다.** 파싱 실패 시 `fallback` |
| 진단 | — | `RtautoConfig.SourceLabel`로 어느 파일에서 읽었는지 노출 |

⚠️ **배포 시 탐색 위치가 다르다** — Python exe는 자기 폴더, Windows Unity 플레이어는
`Demo_Data`의 두 단계 위(= 실행파일 폴더의 **상위** 폴더). 배포 폴더에 `.env` 하나를 놓았다고
양쪽이 같은 값을 읽는다는 보장이 없다. 자세한 표는
[`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) "설정 파일을 찾는 위치".

## 6. `dg5f_grasp_pose.json` 스키마

실물 DG-5F를 교시 모드로 잡은 뒤 `dg5f_readback_bridge.py --capture-pose`로 캡처한 자세다.

| 필드 | 예시 값 | 설명 |
|---|---|---|
| `name` | `grasp_papercup` | 자세 이름(`--pose-name`) |
| `hand` | `5f_right` | SDK 모델 코드 |
| `captured_utc` | `2026-08-31T06:09:56Z` | 캡처 시각 |
| `source` | `real DG-5F readback (…)` | 출처 |
| `convention` | 채널 순서·부호 규약 설명 | 우리 규약(URDF·Unity 기준 deg). SDK 규약과의 부호 차이는 `from_sdk_frame`에서 이미 변환됨 |
| `channels[20]` | `thumb_cmc`, `thumb_opp`, … | 채널 이름 |
| `deg[20]` | `-2.1, -92.55, …` | 관절각[deg] |

**Unity가 실제로 검사하는 것은 `deg`의 길이가 20인지 하나뿐**이다(`channels`는 읽지 않는다).
파일이 없거나 길이가 다르면 예외를 던지지 않고 Console에 안내만 남긴 뒤 '파지하기' 버튼을
비활성화한다 — 자세 파일이 없다고 데모 씬이 죽으면 안 되기 때문이다.

⚠️ 이 파일은 **수동 버튼 전용**이다. RL 자동 제어는 이걸 읽지 않고
`Dg5fPicknPlaceSpec.RightFistDeg`를 쓴다. 자세를 새로 녹화해도 학습 정책은 바뀌지 않는다.

## 7. 따라 하기: 새 PC에서 설정 잡기 / 새 값 추가하기

### 7-1. 새 PC 초기 설정

**터미널 1 (bash 또는 PowerShell, 리포 루트)**

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

`.env`는 git 비추적이다. 머신마다 다른 값(장비 IP, Unity 경로, DLL 경로, Python 경로)만
채우면 되고, 나머지는 `.env.example`의 공유 기본값이 그대로 적용된다.

현재 적용값을 확인하려면:

```bash
source vision/.vision/bin/activate
python -c "from config import rtauto_config as c; print(c.UR_IP, c.PORT_UR_ARM_BRIDGE, c.picknplace_player_path())"
```

값이 바뀌지 않으면 **실행한 터미널의 환경변수**를 확인한다 — 환경변수가 `.env`보다 우선한다.

### 7-2. 새 포트·경로를 추가할 때

1. `rtauto_config.py`에 상수를 추가한다: `PORT_NEW = int(_env("RTAUTO_PORT_NEW", "5011"))`
2. `.env.example`에 같은 키와 기본값·설명 주석을 추가한다.
3. Unity에서도 읽어야 하면 `RtautoConfig.GetInt("RTAUTO_PORT_NEW", 5011)`로 읽는다.
   **C# 쪽에 숫자를 다시 타이핑하지 않는다.**
4. 사용하는 파이썬 파일은 `from config import rtauto_config as cfg` 후 `cfg.PORT_NEW`.

### 7-3. 설정이 반영되는 시점

설정은 **시작 시 읽거나 캐시**한다. 실행 중 즉시 반영을 기대하지 말고, Python은 재시작하고
Unity는 설정을 다시 로드하는 세션에서 적용값을 확인한다.

## 8. 관련 문서

- [`.env.example`](../.env.example) — 전체 키 목록과 설명(정본)
- [`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) — 설정·빌드 모듈 전체 설명
- [`unity/Assets/Scripts/README.md`](../unity/Assets/Scripts/README.md) — `RtautoConfig.cs` 구현
- [`docs/TRAINING_RUN_LEDGER.md`](../docs/TRAINING_RUN_LEDGER.md) — 학습 런 판정 이력

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- config/README.md`
- **갱신 대상**: `config/**`, `.env.example`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/BUILD_TOOLING.md`, `unity/Assets/Scripts/RtautoConfig.cs`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

