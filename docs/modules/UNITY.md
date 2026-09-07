# Unity 모듈 설명

`unity/Assets/**`의 C# 스크립트가 각각 무슨 일을 하는지 정리한다.
강화학습 에이전트 본체(`MLAgents/**`)는 양이 많아 [RL_TRAINING.md](RL_TRAINING.md)에서 따로 다루고,
여기서는 **로봇을 실제로 움직이는 공용 스크립트 + 데모 UI + 에디터 툴**을 본다.

## 0. 씬 목록 — 어느 씬이 무엇인가

| 씬 파일 | 용도 | 상태 |
|---|---|---|
| `Assets/Scenes/Pipeline_Demo_GraspLift.unity` | **시연용 메인 씬.** 학습된 정책 자동 실행 ↔ 사람 수동 조작 전환, URSim 연동까지 여기서 한다 | 현역 |
| `Assets/Scenes/UR16eDG5FRight_Preview.unity` | UR16e + 오른손 URDF를 임포트해 관절 슬라이더로 확인하는 검수용 씬 | 현역 |
| `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity` | 학습 씬(로봇 40개 병렬). **손으로 편집 금지** — 에디터 메뉴로 재생성되는 산출물 | 현역 |
| `Assets/MLAgents/GraspLift/DG5F_GraspLiftTraining.unity` | 이전 세대(UR5e+왼손) 학습 씬 | 구세대 |
| `Assets/Scenes/DG5F_Import.unity`, `RobotArm.unity` | 손 단독 임포트 확인 / 과거 팔 실험 씬 | 잔재 |

## 1. 통신 — 밖과 주고받는 4개 컴포넌트

이름 규칙이 일정하다: **Receiver = 밖에서 Unity로**, **Sender = Unity에서 밖으로**.

| 파일 | 방향 | 하는 일 |
|---|---|---|
| `Scripts/Dg5fReceiver.cs` | 밖 → Unity | 파이썬 비전이 UDP(기본 5006)로 쏘는 손 20관절각을 받아 들고만 있는다. 패킷 길이로 버전(v1~v6)을 판별해 상위 호환 |
| `Scripts/Dg5fHandDriver.cs` | (소비) | Receiver가 받은 20채널 각도를 실제 손가락 관절 `xDrive.target`에 넣는다. URDF 리밋 clamp + 부드럽게 보간만 담당 |
| `Scripts/Dg5fSender.cs` | Unity → 밖 | Unity 손 관절값을 UDP(기본 5008)로 내보내 **실물 그리퍼를 Unity가 구동**. 안전상 기본값이 꺼짐 |
| `Scripts/UrArmReceiver.cs` | 밖 → Unity | UR 브리지가 보내는 팔 6관절 실제각(기본 5010) 수신 |
| `Scripts/UrArmTwinDriver.cs` | (소비) | 그 6관절 값을 팔 `ArticulationBody`에 적용 — "URSim을 움직이면 Unity가 따라온다" |
| `Scripts/UrArmSender.cs` | Unity → 밖 | Unity 팔 목표각을 UDP(기본 5009)로 브리지에 보내 URSim/실물을 구동. 역시 기본값 꺼짐 |

> ⚠️ **되먹임 루프 주의.** 송신과 수신을 동시에 켜면 `Unity 목표 → 로봇 → 실제각 → 다시 Unity 목표`로
> 서로를 덮어쓴다. 그래서 아래 "모드 전환" 컴포넌트들이 방향을 상호배타로 강제한다.

관련 지원 파일:
- `Scripts/RtautoConfig.cs` — 리포 루트 `.env`/`.env.example`을 C#에서 읽는 어댑터. 포트를
  파이썬과 Unity가 **같은 파일 하나**에서 읽게 만드는 장치(원칙 1). 절대 예외를 던지지 않고
  실패 시 기본값으로 조용히 떨어진다.
- `Scripts/UrArmJointNames.cs` / `UrArmLimits.cs` — UR16e 6관절의 링크 이름과 실물 속도·토크 한계.
  값의 근거는 URDF. 어셈블리 순환 참조를 피하려고 RL 쪽 `Dg5fPicknPlaceSpec`과 값이 중복돼 있으니
  **한쪽을 바꾸면 다른 쪽도 바꿔야 한다.**

## 2. 로봇 물리 셋업 — "왜 이걸 안 하면 로봇이 떨리나"

이 세 개는 URDF를 Unity에 넣었을 때 생기는 고질적 문제를 막는 스크립트다.

| 파일 | 하는 일 | 안 붙이면 |
|---|---|---|
| `Scripts/RobotSelfCollisionIgnore.cs` | 로봇 자기 콜라이더끼리의 충돌을 무시 | 인접 손가락 마디가 설계상 겹쳐 있어 PhysX가 밀어내고 드라이브가 되끌어오는 **접촉 진동**(명령 0인데 ±20~100° 발진) |
| `Scripts/RobotInitialPoseSync.cs` | Play 시작 시 관절 실제 위치를 목표값으로 텔레포트 | 영점 자세에서 목표 자세로 팔이 홱 들려 손가락이 채찍처럼 휘둘리고 수십 초 출렁임 |
| `Scripts/RobotConfig.cs` | 관절 게인·리밋 등 튜닝 파라미터 단일 출처. 값마다 출처를 `[REAL-UR]/[REAL-URDF]/[PLACEHOLDER]`로 표시 | 값이 여러 파일로 흩어짐. **UR5e+SVH 시절 파일이라 지금은 참고용** |

## 3. 사람이 손으로 조작하는 경로

| 파일 | 하는 일 |
|---|---|
| `Scripts/HandSliderUI.cs` | 화면 슬라이더로 관절을 직접 돌린다. 원래 UR5e+SVH용, 지금은 Preview 씬 검수에 사용 |
| `Scripts/ArmTargetIK.cs` | 목표 오브젝트 위치로 손끝을 보내는 CCD IK(위치만, 자세 미제어) |
| `Scripts/Dg5fFingerIK.cs` | **손끝 위치 리타게팅.** 사람 손끝 위치를 로봇 손 치수로 복원해 그 손가락 4관절을 IK로 보낸다. 채널별 각도 매핑으로는 재현 못 하는 엄지 결합운동(OK 사인 등)을 위해 존재. 손가락 5개가 같은 컴포넌트를 `fingerIndex`만 바꿔 공유 |
| `Scripts/Dg5fFingerIKMode.cs` | 5개 손가락 IK의 구동 방식을 드롭다운 하나로 일괄 전환(Play 중 실시간 A/B 비교용) |
| `Scripts/Dg5fIKVectorDebug.cs` | IK가 이번 프레임에 실제로 계산한 목표 벡터를 선으로 그린다(산식 복제 없이 값을 읽어 그림) |
| `MLAgents/picknplace/Runtime/PicknPlaceArmJointPanel.cs` | **데모 씬의 팔 조작 창구.** UR16e 6축 슬라이더 + URSim 연동 방향 선택. 방향 상호배타를 여기서 강제 |
| `MLAgents/picknplace/Runtime/Dg5fFistButton.cs` | 웹캠 없이 버튼 하나로 주먹 쥐기/펴기. 누르는 동안 다른 손 구동자(텔레옵·정책)를 잠시 멈춤 |
| `MLAgents/picknplace/Runtime/Dg5fTwinModeSwitcher.cs` | 손의 디지털 트윈 **방향 전환 UI**(sim→real / real→sim / 끊기). 파이썬 브리지에도 제어 패킷을 보내 실물 교시 모드까지 함께 바꾼다 |
| `MLAgents/picknplace/Runtime/PicknPlaceControlModeSwitcher.cs` | 데모 씬의 자동(정책) ↔ 수동(사람) 전환 토글 |
| `MLAgents/picknplace/Runtime/PicknPlaceFreeFlyCamera.cs` | 데모 카메라를 Scene 뷰처럼 날아다니게 조작(우클릭 회전, WASD 이동) |
| `Scripts/DemoUiLayout.cs` | 화면 HUD 박스들이 서로 겹치지 않게 좌표를 계산해 쌓는 공용 배치기. 각 패널이 y좌표를 직접 박아 두던 시절 실제로 여러 번 겹쳤다 |

GraspLift(구세대)에도 같은 역할의 쌍둥이가 있다: `GraspLiftControlModeSwitcher`,
`GraspLiftTeleopNudge`(마우스 조이스틱 방식 팔 조작), `GraspLiftDemoCameraSwitcher`.

## 4. 로깅

| 파일 | 하는 일 |
|---|---|
| `Scripts/Dg5fLogFile.cs` | `Logs/` 아래 CSV를 여는 **유일한 통로**. 초 단위 타임스탬프 + 중복 시 접미사로 절대 덮어쓰지 않는다(같은 분에 두 번 Play하면 앞 로그가 사라지던 사고 때문) |
| `Scripts/Dg5fJointLogger.cs` | 50Hz로 [수신값 / 목표각 / 실측각] 20관절을 CSV 기록. 타임스탬프가 unix 초라 파이썬 비전 로그와 바로 시간 정렬된다 → `vision/dg5f/analyze_teleop.py`로 분석 |

## 5. 씬 소품 생성기

`Scripts/RandomPillarGenerator.cs`, `RandomPillarSpawner.cs`, `RandomShelfStack.cs` —
무작위 기둥/선반을 절차적으로 만든다. 학습 씬 장애물·배경 실험용이며 현재 파이프라인의 필수 요소는 아니다.

## 6. 에디터 툴 (Play 하지 않고 메뉴에서 실행하는 것들)

Unity 상단 메뉴에서 실행되는 스크립트들이다. **씬 파일을 직접 편집하는 대신 이것들을 다시 돌리는 게 규칙.**

| 파일 | 메뉴 | 하는 일 |
|---|---|---|
| `Editor/ImportUr16eDg5fRightPreview.cs` | `KDT > Import UR16e+DG5F-Right Preview Scene` | URDF를 임포트해 Preview 씬을 만든다 |
| `Editor/SetupPreviewSceneControls.cs` | `KDT > Preview Scene에 조작 컴포넌트 추가` | 그 씬 로봇에 슬라이더 UI·자기충돌 무시를 붙인다 |
| `Robots/Editor/CreateUr16eDg5fRightPrefab.cs` | — | Preview 씬의 로봇을 프리팹으로 추출(학습 씬 빌더의 입력이 된다) |
| `Editor/DG5FVariantSwitcher.cs` | `Tools > DG5F > Right/Left/…` | 씬의 손을 오른손/왼손/숏 변형으로 교체 |
| `MLAgents/picknplace/Editor/PicknPlaceTrainingSceneBuilder.cs` | `Tools > ML-Agents > …` | **학습 씬을 프리팹에서 통째로 재생성** |
| `MLAgents/picknplace/Editor/PicknPlacePipelineDemoSceneBuilder.cs` | — | 학습 영역 1개를 떼어내 시연 씬을 만든다(성공해도 리셋하지 않고 마지막 자세 유지) |
| `MLAgents/picknplace/Editor/PicknPlaceTrainingBuild.cs` | `Tools > ML-Agents > …` | headless 학습용 standalone 플레이어 빌드(Windows/Linux 두 타깃) |
| `MLAgents/Editor/BuildEnvironment.cs` | — | 빌드 스크립트가 `.env`에서 출력 경로·플레이어 이름을 읽는 어댑터 |
| `MLAgents/Editor/LinuxPlayerPostProcess.cs` | — | Linux 플레이어 빌드 후처리(`libdl.so.2` 셰임 주입 — `build-support/linux/`) |
| `MLAgents/picknplace/Editor/PicknPlacePoseDiagnostic.cs` | `Tools > ML-Agents > Diagnose PicknPlace Arm Poses` | 후보 홈 자세들을 실제 씬 기하로 재서 "내려다보는 준비자세"를 데이터로 고르게 한다 |
| `MLAgents/picknplace/Editor/PicknPlaceThumbDiagnostic.cs` | — | 엄지 자세를 실측해 보상 제약값의 근거를 만든다 |

## 7. 어셈블리 구조 (컴파일 의존 방향)

```text
KDT.RobotScripts (Assets/Scripts)        ← 가장 아래층. 통신·구동·IK·로깅
        ▲
KDT.PicknPlaceTraining (RL 런타임) ──── KDT.PicknPlaceTraining.Editor / .Tests
KDT.GraspLiftTraining (구세대)     ──── 같은 구조
```
아래층이 위층을 참조하면 **순환 참조로 컴파일이 깨진다.** 그래서 관절 이름 같은 상수가
양쪽에 중복돼 있는 곳이 있다(`UrArmJointNames.cs` 주석 참고).

## 8. 잔재 — `Assets/Script/` (단수)

`ActionAPI.cs`, `RBSocket.cs`, `Globals.cs`, `Const.cs`, `BufferUtil.cs`, `JointOperation.cs`.
`com.rainbow.external` 네임스페이스 = Rainbow Robotics 협동로봇 소켓 통신 코드로,
현재 UR16e 파이프라인 어디에서도 참조되지 않는다. 과거 팀 시절 잔재.
`JointOperation.cs`의 CCD IK만 `Scripts/ArmTargetIK.cs`로 이식돼 살아 있다.
