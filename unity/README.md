# `unity/` — Unity 프로젝트 (시뮬레이션·학습 환경·시연 화면)

로봇을 화면에 띄우고 물리를 계산하며, 강화학습 환경과 시연 UI를 제공하는 Unity 프로젝트다.
이 폴더 안에서 **물리 = Unity 자체 엔진(PhysX)** 이고, 학습 에이전트 로직도 Unity가 소유한다.

## 목차

1. [프로젝트 기본 정보](#1-프로젝트-기본-정보)
2. [폴더 구조](#2-폴더-구조)
3. [씬 목록 — 어느 씬이 무엇인가](#3-씬-목록--어느-씬이-무엇인가)
4. [어셈블리 구조 (컴파일 의존 방향)](#4-어셈블리-구조-컴파일-의존-방향)
5. [에디터 메뉴 전체 경로](#5-에디터-메뉴-전체-경로)
6. [따라 하기: 새 PC에서 로봇 자산 만들기](#6-따라-하기-새-pc에서-로봇-자산-만들기)
7. [따라 하기: 시연 씬 실행](#7-따라-하기-시연-씬-실행)
8. [플레이어 빌드](#8-플레이어-빌드)
9. [알려진 제한](#9-알려진-제한)
10. [관련 문서](#10-관련-문서)

## 1. 프로젝트 기본 정보

| 항목 | 값 | 출처 |
|---|---|---|
| Unity 버전 | **6000.4.0f1** | `ProjectSettings/ProjectVersion.txt` |
| ML-Agents 패키지 | `com.unity.ml-agents` **4.0.0** | `Packages/manifest.json` |
| URDF Importer | `com.unity.robotics.urdf-importer` (git URL) | 〃 |
| unity-cli 커넥터 | `com.youngwoocho02.unity-cli-connector` (git URL) | 〃 — `tools/urdf_hand_import`이 사용 |
| 그 외 | Cinemachine 2.10.6, Input System 1.19.0, Timeline 1.8.11, uGUI 2.0.0 | 〃 |
| 중력 | `(0, -9.81, 0)` | `ProjectSettings/DynamicsManager.asset` |
| Solver Iterations | **20** (기본 6보다 높다) | 〃 — 다관절 접촉 안정성을 위해 올린 값 |

> Unity 버전을 올릴 때는 `tools/unity_firewall_toggle.ps1`의 규칙 이름
> (`"Unity 6000.4.0f1 Editor"`)도 함께 바꿔야 한다.

## 2. 폴더 구조

```text
unity/
├── Assets/
│   ├── Scripts/        ★ 통신·구동·IK·로깅 공용 C#   → Scripts/README.md
│   ├── MLAgents/       ★ 강화학습 에이전트·씬 빌더    → MLAgents/README.md
│   ├── Editor/         URDF 임포트·변형 교체 메뉴      → Editor/README.md
│   ├── Robots/         임포트된 로봇 프리팹·메시       → Robots/README.md
│   ├── Scenes/         씬 4개 (§3)
│   ├── Script/         ⛔ 잔재(단수 s) — Rainbow Robotics 소켓 코드 → Script/README.md
│   ├── Prefab/         과거 팀 시절 팔 프리팹 잔재
│   ├── Meterial/       Black/White 머티리얼 (오타 포함 원본 이름 유지)
│   └── Plugins/        네이티브 플러그인
├── Packages/           manifest.json / packages-lock.json
└── ProjectSettings/    물리·품질·태그 등 프로젝트 설정
```

`Assets/Scripts`(복수)와 `Assets/Script`(단수)는 **완전히 다른 것**이다. 현역은 복수형이다.

> `Assets/` 아래 폴더의 `README.md`는 Unity가 **다음에 프로젝트를 열 때 `.meta` 파일을 생성**한다.
> 이 저장소는 소스 `Assets`의 `.meta`를 의도적으로 추적하므로(`.gitignore` 주석 참고),
> 그때 생기는 `README.md.meta`도 함께 커밋한다.

## 3. 씬 목록 — 어느 씬이 무엇인가

| 씬 파일 | 용도 | 상태 |
|---|---|---|
| `Assets/Scenes/Pipeline_Demo_GraspLift.unity` | **시연용 메인 씬.** 수동 손·팔 조작, URSim 연동, 자동/수동 UI | 현역 (생성물 — 직접 편집 금지) |
| `Assets/Scenes/UR16eDG5FRight_Preview.unity` | UR16e+오른손 URDF를 임포트해 슬라이더로 검수하는 씬 | 현역 |
| `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity` | **학습 씬** (기본 40영역 병렬) | 현역 (생성물 — 직접 편집 금지) |
| `Assets/MLAgents/GraspLift/DG5F_GraspLiftTraining.unity` | 이전 세대(UR5e+왼손) 학습 씬 | 구세대 |
| `Assets/Scenes/DG5F_Import.unity`, `RobotArm.unity` | 손 단독 임포트 확인 / 과거 팔 실험 | 잔재 |

> **"생성물 — 직접 편집 금지"의 의미**: 이 씬들은 에디터 메뉴가 프리팹에서 절차적으로
> 다시 만든다. 손으로 고치면 다음 재생성 때 조용히 사라진다. 바꾸고 싶으면 **생성기 코드를
> 고치고 메뉴를 다시 실행**한다.

## 4. 어셈블리 구조 (컴파일 의존 방향)

```text
KDT.RobotScripts (Assets/Scripts)        ← 가장 아래층. 통신·구동·IK·로깅
        ▲
KDT.PicknPlaceTraining (RL 런타임) ──── KDT.PicknPlaceTraining.Editor / .Tests / .PlayModeTests
KDT.GraspLiftTraining (구세대)     ──── 같은 구조
KDT.MLAgents.Editor (빌드 도구)
```

**아래층이 위층을 참조하면 순환 참조로 컴파일이 깨진다.** 그래서 관절 이름 같은 상수가
양쪽에 의도적으로 중복돼 있는 곳이 있다.

⚠️ **한쪽만 고치면 조용히 어긋나는 쌍**

| 쌍 | 내용 |
|---|---|
| `Dg5fPicknPlaceSpec.ArmLinks` ↔ `UrArmJointNames.Names` | 팔 관절 이름 (순환 참조 회피용 중복) |
| `Dg5fHandDriver.JointLabels` ↔ `dg5f_angles.CHANNEL_NAMES` | 손 20채널 순서 |
| `RtautoConfig.cs` ↔ `config/rtauto_config.py` ↔ `BuildEnvironment.cs` | 설정 읽기 3구현 |

## 5. 에디터 메뉴 전체 경로

| 메뉴 | 스크립트 |
|---|---|
| `KDT > Import UR16e+DG5F-Right Preview Scene` | `Editor/ImportUr16eDg5fRightPreview.cs` |
| `KDT > Preview Scene에 조작 컴포넌트 추가` | `Editor/SetupPreviewSceneControls.cs` |
| `Tools > Robots > Create UR16e DG5F Right Prefab` | `Robots/Editor/CreateUr16eDg5fRightPrefab.cs` |
| `Tools > DG5F > Right / Right Short / Left / Left Short` | `Editor/DG5FVariantSwitcher.cs` |
| `Tools > ML-Agents > Build DG5F PicknPlace Training Scene` | `MLAgents/picknplace/Editor/PicknPlaceTrainingSceneBuilder.cs` |
| `Tools > ML-Agents > Build PicknPlace Pipeline Demo Scene` | `MLAgents/picknplace/Editor/PicknPlacePipelineDemoSceneBuilder.cs` |
| `Tools > ML-Agents > Build DG5F PicknPlace Windows/Linux Player` | `MLAgents/picknplace/Editor/PicknPlaceTrainingBuild.cs` |
| `Tools > ML-Agents > Diagnose PicknPlace Arm Poses` | `MLAgents/picknplace/Editor/PicknPlacePoseDiagnostic.cs` |
| `Tools > ML-Agents > Diagnose PicknPlace Thumb Orientation` | `MLAgents/picknplace/Editor/PicknPlaceThumbDiagnostic.cs` |

## 6. 따라 하기: 새 PC에서 로봇 자산 만들기

> Unity 창 이름 기준: **Project 창**은 기본 위치 에디터 하단, **Hierarchy 창**은 좌측,
> **Inspector 창**은 우측, **Console 창**은 `Window > General > Console`에서 연다.

**사전 조건**: [`urdf/README.md`](../urdf/README.md)의 결합 URDF 빌드가 끝나 있어야 한다
(`urdf/ur16e_dg5f_right_build/ur16e_dg5f_right.urdf`가 존재).

1. Unity Hub에서 `unity/` 폴더를 프로젝트로 열고, 첫 임포트가 끝날 때까지 기다린다.
2. 상단 메뉴 **`KDT > Import UR16e+DG5F-Right Preview Scene`** 클릭.
   → `Assets/Scenes/UR16eDG5FRight_Preview.unity`가 만들어지고 로봇이 임포트된다.
3. **`KDT > Preview Scene에 조작 컴포넌트 추가`** 클릭.
   → 그 씬의 로봇에 슬라이더 UI(`HandSliderUI`)와 자기충돌 무시(`RobotSelfCollisionIgnore`)가 붙는다.
4. 여기서 ▶(Play)를 눌러 슬라이더로 관절을 돌려 본다. **관절이 떨리거나 발진하면**
   자기충돌 무시·초기 포즈 동기화가 붙었는지 Inspector 창에서 확인한다(§9).
5. **`Tools > Robots > Create UR16e DG5F Right Prefab`** 클릭.
   → `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab` 저장. 씬 자체는 건드리지 않는다.
6. **`Tools > ML-Agents > Build DG5F PicknPlace Training Scene`** 클릭.
   → 위 프리팹으로부터 학습 씬을 절차적으로 생성한다(기본 40영역).
7. **`Tools > ML-Agents > Build PicknPlace Pipeline Demo Scene`** 클릭.
   → 학습 영역 하나를 떼어 시연 씬을 만든다.

각 단계에서 Console 창에 빨간 에러가 없어야 다음으로 넘어간다.

## 7. 따라 하기: 시연 씬 실행

1. Project 창에서 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`를 **더블클릭**해 연다.
2. 에디터 상단 중앙의 ▶(Play)를 누른다. 다시 누르면 멈춘다.
   ⚠️ **Play 중 Inspector에서 바꾼 값은 정지하면 사라진다.**
3. 화면 좌우에 HUD 패널이 뜬다. 각 패널의 의미:

| 패널 | 무엇을 바꾸나 | 컴포넌트 |
|---|---|---|
| 제어 모드 (자동/수동) | 팔·손 목표를 정책이 정할지 사람이 정할지 | `PicknPlaceControlModeSwitcher` |
| 팔 관절 패널 | UR16e 6축 슬라이더 + URSim 연동 방향 | `PicknPlaceArmJointPanel` |
| 주먹 / 펴기 / 파지하기 / 웹캠 복귀 | 손 프리셋 자세 재생과 제어권 반환 | `Dg5fFistButton` |
| 손 트윈 방향 (sim→real / real→sim / 끊기) | Unity와 실물 중 어느 쪽이 따라갈지 | `Dg5fTwinModeSwitcher` |

4. 웹캠으로 손을 조작하려면 [`vision/README.md`](../vision/README.md) §6의 절차를 함께 실행한다.
5. URSim과 팔을 연동하려면 [`arm/README.md`](../arm/README.md) §5의 절차를 함께 실행한다.

> **주먹 버튼을 누르면 손 제어권이 버튼에 넘어가고, 계속 유지된다.** 웹캠으로 돌아가려면
> **웹캠 복귀 버튼**을 눌러야 한다(`Dg5fFistButton.ReleaseHandToTracking()`).

## 8. 플레이어 빌드

장시간 학습은 Editor가 아니라 **빌드된 플레이어**를 `--no-graphics`로 띄운다.

Editor 메뉴 **`Tools > ML-Agents > Build DG5F PicknPlace Windows Player`**(또는 `... Linux Player`)를
쓰거나, Editor를 **닫고** 배치모드로 실행한다 — Unity는 한 프로젝트를 두 번 열지 못한다.

```powershell
& "C:/Program Files/Unity/Hub/Editor/6000.4.0f1/Editor/Unity.exe" -batchmode -quit -nographics `
    -projectPath unity `
    -executeMethod KDT.PicknPlaceTraining.Editor.PicknPlaceTrainingBuild.BuildWindowsPlayer `
    -logFile unity_batch_logs/build_windows_player.log
```

```bash
"$UNITY_EDITOR" -batchmode -quit -nographics \
    -projectPath unity \
    -executeMethod KDT.PicknPlaceTraining.Editor.PicknPlaceTrainingBuild.BuildLinuxPlayer \
    -logFile unity_batch_logs/build_linux_player.log
```

- 이 메뉴는 **씬 재생성을 먼저 자동 실행**하므로 씬 빌드 메뉴를 따로 돌릴 필요가 없다.
- 출력 경로·실행파일명은 `.env`(`DG5F_PICKNPLACE_WINDOWS_BUILD_OUTPUT` / `..._PLAYER_NAME`)에서
  온다 — 코드에 경로가 박혀 있지 않다(원칙 1).
- Linux 빌드는 후처리로 `build-support/linux/libdl.so.2`를 주입한다
  ([`build-support/README.md`](../build-support/README.md)).
- ⚠️ **학습 영역 수는 플레이어에 구워진다.** `.env`의 `DG5F_PICKNPLACE_TRAINING_AREAS`를 바꿨다면
  씬 재생성 → 재빌드를 해야 반영된다.

## 9. 알려진 제한

1. **저장된 데모 씬에서 자동 파지가 바로 되지 않는다.** 2026-09-07 코드 대조 기준
   `Pipeline_Demo_GraspLift.unity`의 `Dg5fPicknPlaceAgent`는 비활성(`m_Enabled: 0`)이고,
   자동 전환 코드는 `EndEpisode()`를 부르지만 Agent를 다시 `enabled=true`로 만들지 않는다.
   자동/수동 UI가 있다는 사실만으로 자동 파지가 된다고 안내할 수 없다.
2. **송신과 수신을 동시에 켜면 되먹임 루프가 생긴다.** `Unity 목표 → 로봇 → 실제각 → 다시
   Unity 목표`로 서로를 덮어쓴다. 모드 전환 컴포넌트들이 방향을 상호배타로 강제하는 이유다.
3. **웹캠과 실물 손 피드백이 같은 UDP 5006으로 들어온다.** `Dg5fReceiver`는 출처를 구별하지
   않으므로 동시에 켜면 값이 섞인다.
4. **`RobotConfig.cs`는 UR5e+SVH 시절 파일**이라 현재 학습 물리값이 아니다. 학습 씬의 드라이브는
   `Dg5fPicknPlaceSpec`의 값이 정본이다.
5. **설정 파일 탐색 위치가 Python과 다르다.** Unity Editor는 `Assets`의 두 단계 위, Windows
   플레이어는 `Demo_Data`의 두 단계 위를 본다.

## 10. 관련 문서

- [`unity/Assets/Scripts/README.md`](Assets/Scripts/README.md) — 통신·구동·IK C# 상세
- [`unity/Assets/MLAgents/README.md`](Assets/MLAgents/README.md) — 강화학습 에이전트 상세
- [`docs/modules/UNITY.md`](../docs/modules/UNITY.md) — Unity 모듈 전체 설명(정본)
- [`training/README.md`](../training/README.md) — 학습 실행 절차
- [`urdf/README.md`](../urdf/README.md) — 임포트 이전 단계

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/README.md`
- **갱신 대상**: `unity/**` (프로젝트 설정·씬·메뉴)가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/UNITY.md`, `training/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

