# Unity 모듈 설명

`unity/Assets/**`의 C# 스크립트가 각각 무슨 일을 하는지 정리한다.
강화학습 에이전트 본체(`MLAgents/**`)는 양이 많아 [RL_TRAINING.md](RL_TRAINING.md)에서 따로 다루고,
여기서는 **Unity 안의 로봇 구동 + 데모 UI + 에디터 툴**을 본다.

## 먼저 이해할 역할과 연결

Unity는 화면에 로봇을 보여주고 물리를 계산하는 프로그램이다. 웹캠이나 실물에서 받은 관절각을
시뮬레이션에 반영하거나, 학습된 정책·사람이 정한 목표각을 실물 브리지로 보낼 수 있다.
실물 통신 자체는 [REAL_BRIDGES.md](REAL_BRIDGES.md)의 Python 프로그램이 담당한다.

`씬`은 로봇·물체·카메라를 배치한 실행 화면, `컴포넌트`는 그 안에 붙이는 기능 부품이다.
`ArticulationBody`는 물리 관절이며, `xDrive.target`은 그 관절이 **도달하려는 각도**다.
목표각과 실제로 도달한 각도는 물리·접촉·속도 제한 때문에 다를 수 있다.

**자동/수동**은 목표를 누가 정하는지, **트윈 방향**은 Unity와 실물 중 어느 쪽이 상대를 따라가는지를
정한다. 아래 표는 각 경로의 역할이며 모든 모드 조합을 검증했다는 의미는 아니다.

| 사용 상황 | 팔 목표를 정하는 쪽 | 손 목표를 정하는 쪽 | 전환 시 알아둘 점 |
|---|---|---|---|
| 수동 웹캠 조작, 손 트윈 Off | 팔 관절 패널 | 비전 → Receiver → HandDriver | 현재 데모는 수동으로 시작. 웹캠은 별도로 실행 |
| 주먹·펴기·저장 파지 버튼 | 현재 팔 제어 유지 | FistButton 프리셋 | 한 번 누르면 제어권을 유지. **웹캠 실시간 조작으로** 버튼으로 반환 |
| RL 자동 | PicknPlaceAgent | PicknPlaceAgent의 손 개폐 값 | 대응 ONNX 모델과 Agent 활성화가 전제. 현재 저장 씬의 제한은 아래 참고 |
| 손 sim→real | 팔 연동과 별개 | Unity 프리셋 → Sender → 손 브리지 | 웹캠 구동을 끄고 실물 자세 동기화를 시도한 뒤 송신 |
| 손 real→sim | 팔 연동과 별개 | 실물 피드백 → HandDriver가 의도된 경로 | **현재 SDK 브리지의 교시 중 피드백 결함은 REAL_BRIDGES 참고** |
| 팔 URSim→Unity | URSim 실제각 → TwinDriver | 현재 손 제어 유지 | 팔 패널에서 팔 연동 방향을 별도로 선택 |

근거: [자동/수동 전환](../../unity/Assets/MLAgents/picknplace/Runtime/PicknPlaceControlModeSwitcher.cs),
[손 방향 전환](../../unity/Assets/MLAgents/picknplace/Runtime/Dg5fTwinModeSwitcher.cs).

**현재 저장된 데모 씬의 자동 제어 제한:** 2026-09-07 코드 대조 시
`Pipeline_Demo_GraspLift.unity`의 `Dg5fPicknPlaceAgent`는 비활성(`m_Enabled: 0`)이다.
자동 전환 코드는 `EndEpisode()`를 호출하지만 Agent를 다시 활성화하지 않는다.
자동/수동 UI가 있다는 사실만으로 저장된 씬에서 자동 파지가 바로 된다고 안내할 수 없다.
이는 씬 구성·전환 구현의 확인 과제로 남아 있으며, 문서 수정 중 자동 시연을 실행 검증하지 않았다.

## 0. 씬 목록 — 어느 씬이 무엇인가

| 씬 파일 | 용도 | 상태 |
|---|---|---|
| `Assets/Scenes/Pipeline_Demo_GraspLift.unity` | **시연용 메인 씬.** 수동 손·팔 조작과 URSim 연동. 자동/수동 UI는 있으나 현재 Agent 비활성 상태는 위 제한 참고 | 현역 |
| `Assets/Scenes/UR16eDG5FRight_Preview.unity` | UR16e + 오른손 URDF를 임포트해 관절 슬라이더로 확인하는 검수용 씬 | 현역 |
| `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity` | 학습 씬(로봇 40개 병렬). **손으로 편집 금지** — 에디터 메뉴로 재생성되는 산출물 | 현역 |
| `Assets/MLAgents/GraspLift/DG5F_GraspLiftTraining.unity` | 이전 세대(UR5e+왼손) 학습 씬 | 구세대 |
| `Assets/Scenes/DG5F_Import.unity`, `RobotArm.unity` | 손 단독 임포트 확인 / 과거 팔 실험 씬 | 잔재 |

## 1. 통신 — 송수신 4개와 관절 구동 2개

이름 규칙이 일정하다: **Receiver = 밖에서 Unity로**, **Sender = Unity에서 밖으로**.

| 파일 | 방향 | 하는 일 |
|---|---|---|
| `Scripts/Dg5fReceiver.cs` | 밖 → Unity | 파이썬 비전이 UDP(기본 5006)로 쏘는 손 20관절각을 받아 들고만 있는다. 패킷 길이로 버전(v1~v6)을 판별해 상위 호환 |
| `Scripts/Dg5fHandDriver.cs` | (소비) | 수신 각도를 Unity 손가락의 목표각에 적용. 리밋 제한·보간·오래된 입력 차단을 담당하며, 활성 IK가 맡은 손가락은 건너뜀 |
| `Scripts/Dg5fSender.cs` | Unity → 밖 | Unity 손 관절값을 UDP(기본 5008)로 내보내 **실물 그리퍼를 Unity가 구동**. 안전상 기본값이 꺼짐 |
| `Scripts/UrArmReceiver.cs` | 밖 → Unity | UR 브리지가 보내는 팔 6관절 실제각(기본 5010) 수신 |
| `Scripts/UrArmTwinDriver.cs` | (소비) | 그 6관절 값을 팔 `ArticulationBody`에 적용 — "URSim을 움직이면 Unity가 따라온다" |
| `Scripts/UrArmSender.cs` | Unity → 밖 | Unity 팔 목표각을 UDP(기본 5009)로 브리지에 보내 URSim/실물을 구동. 역시 기본값 꺼짐 |

> ⚠️ **되먹임 루프 주의.** 송신과 수신을 동시에 켜면 `Unity 목표 → 로봇 → 실제각 → 다시 Unity 목표`로
> 서로를 덮어쓴다. 그래서 아래 "모드 전환" 컴포넌트들이 방향을 상호배타로 강제한다.

이 UI가 외부 Python 프로그램까지 종료하는 것은 아니다. 웹캠과 실물 손 피드백은 모두 UDP 5006으로
들어오며 `Dg5fReceiver`는 송신 출처를 구별하지 않는다. **실물 피드백을 볼 때는 웹캠 송신을 멈춘다.**

관련 지원 파일:

- `Scripts/RtautoConfig.cs` — 리포 루트 `.env`/`.env.example`을 C#에서 읽는 어댑터. 포트를
  파이썬과 Unity가 **같은 파일 하나**에서 읽게 만드는 장치(원칙 1). 절대 예외를 던지지 않고
  실패 시 기본값으로 조용히 떨어진다. 배포 시 탐색 위치는 Python과 다르므로
  [BUILD_TOOLING.md](BUILD_TOOLING.md)의 설정 위치 표를 확인한다.
- `Scripts/UrArmJointNames.cs` / `UrArmLimits.cs` — UR16e 6관절의 링크 이름과 실물 속도·토크 한계.
  값의 근거는 URDF. **관절 이름**은 `Dg5fPicknPlaceSpec.ArmLinks`와 함께 갱신해야 한다.
  속도·토크 한계는 `UrArmLimits`를 학습 에이전트·씬 빌더에서도 공용으로 참조한다.

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
| `MLAgents/picknplace/Runtime/Dg5fFistButton.cs` | 주먹·펴기·저장된 파지 자세 재생. 버튼을 누르면 웹캠·정책의 손 구동을 멈추고 제어권을 계속 보유. 웹캠 복귀는 별도 버튼 |
| `MLAgents/picknplace/Runtime/Dg5fTwinModeSwitcher.cs` | 손의 디지털 트윈 **방향 전환 UI**(sim→real / real→sim / 끊기). 파이썬 브리지에도 제어 패킷을 보내 실물 교시 모드까지 함께 바꾼다 |
| `MLAgents/picknplace/Runtime/PicknPlaceControlModeSwitcher.cs` | 데모 씬의 자동(정책) ↔ 수동(사람) 전환 토글 |
| `MLAgents/picknplace/Runtime/PicknPlaceFreeFlyCamera.cs` | 데모 카메라를 Scene 뷰처럼 날아다니게 조작(우클릭 회전, WASD 이동) |
| `Scripts/DemoUiLayout.cs` | 화면 HUD 박스들이 서로 겹치지 않게 좌표를 계산해 쌓는 공용 배치기. 각 패널이 y좌표를 직접 박아 두던 시절 실제로 여러 번 겹쳤다 |

GraspLift(구세대)에도 같은 역할의 쌍둥이가 있다: `GraspLiftControlModeSwitcher`,
`GraspLiftTeleopNudge`(마우스 조이스틱 방식 팔 조작), `GraspLiftDemoCameraSwitcher`.

### 저장한 파지 자세는 어디에 쓰이나

실물 readback 캡처 또는 Unity의 현재 자세 녹화 → `config/dg5f_grasp_pose.json` →
FistButton의 **파지하기** 버튼 순서다. 파일 경로는 `RTAUTO_DG5F_GRASP_POSE`로 바꿀 수 있다.
파일이 없거나 읽을 수 없으면 해당 버튼은 비활성화된다. RL 자동 제어는 이 파일을 읽지 않고
`Dg5fPicknPlaceSpec.RightFistDeg`를 사용하므로, 자세를 녹화했다고 학습 정책이 바뀌지는 않는다.

근거: [자세 저장·로드와 웹캠 복귀](../../unity/Assets/MLAgents/picknplace/Runtime/Dg5fFistButton.cs).

## 4. 로깅

| 파일 | 하는 일 |
|---|---|
| `Scripts/Dg5fLogFile.cs` | `Logs/` 아래 CSV를 여는 **유일한 통로**. 초 단위 타임스탬프 + 중복 시 접미사로 절대 덮어쓰지 않는다(같은 분에 두 번 Play하면 앞 로그가 사라지던 사고 때문) |
| `Scripts/Dg5fJointLogger.cs` | 50Hz로 [수신값 / 목표각 / 실측각] 20관절을 CSV 기록. 타임스탬프가 unix 초라 파이썬 비전 로그와 바로 시간 정렬된다 → `vision/dg5f/analyze_teleop.py`로 분석 |

여기서 **실측각은 Unity 물리 관절의 현재각**이며 실물 장비 센서값과 구분한다.
Editor 로그는 `unity/Logs/`, Windows 플레이어 로그는 실행파일 옆 `Logs/`에 기록된다.
서로 다른 PC의 로그를 비교하려면 두 PC의 시계도 맞아야 한다.

### 손이 움직이지 않을 때 확인 순서

1. 비전 미리보기에서 손이 잡히는지 확인한다. 안 잡히면 [비전 문서](VISION_TELEOP.md)로 간다.
2. Unity Console에서 수신 포트 바인드 오류와 수신 상태를 확인한다. 두 프로그램의 IP·포트를 대조한다.
3. 수신 중인데 멈춰 있으면 자동/수동, 프리셋의 제어권, 트윈 방향을 확인한다. 주먹 버튼 뒤에는 웹캠 복귀가 필요하다.
4. Unity만 움직이고 실물이 멈춰 있으면 [브리지 문서](REAL_BRIDGES.md)의 접속·드라이런·모드 상태를 확인한다.

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

## 9. 코드 레벨 핵심 — 실제 이름·기본값

파일 역할만으로는 답이 안 나오는 질문("어느 값이 정본인가", "무엇을 호출하면 제어권이 바뀌나",
"패킷이 몇 바이트여야 하나")을 위한 절이다. 아래 값은 **인스펙터/`.env`로 바뀔 수 있는 기본값**이며,
정본은 항상 괄호 안의 소스 파일이다.

### 9-1. 통신 컴포넌트의 공개 계약

| 클래스 | 상수·필드 | 기본값 | 비고 |
|---|---|---|---|
| `Dg5fReceiver` | `ChannelCount` | 20 | `GetAngles(float[20])`가 유일한 각도 접근 통로 |
| | `port` / `ActivePort` | 5006 / `.env` | **인스펙터 `port`는 `.env`가 없을 때의 최후 기본값.** 실제 사용 포트는 `ActivePort` |
| | `secondsSinceLastPacket` | ∞ | 0.5 이상이면 송신 끊김으로 본다 |
| | `GetThumbTip` / `GetFingerTip` / `GetWristTipVector` / `GetPinchDistance` / `GetRawRadians` | — | 각각 v2~v6 필드. 해당 필드가 안 온 패킷이면 `false` 반환 |
| `Dg5fSender` | `sendEnabled` | **false** | 안전 기본값 — 씬을 Play했다고 실물이 움직이면 안 된다 |
| | `bridgeIp` / `bridgePort` / `sendHz` | 127.0.0.1 / 5008 / 50 | |
| | `sendCommandedAngle` | true | true=`xDrive.target`(목표각), false=실측각 송신 |
| `UrArmReceiver` | `ChannelCount` / `port` | 6 / 5010 | `GetAngles(float[6])` |
| `UrArmSender` | `sendEnabled` / `bridgePort` / `sendHz` | **false** / 5009 / 10 | 팔은 10Hz — 브리지 `--hz` 기본값과 짝 |
| `UrArmTwinDriver` | `driveEnabled` / `lerpSpeed` | **false** / 15 | URSim→Unity 방향을 켜는 스위치 |
| `Dg5fHandDriver` | `enableTracking` / `lerpSpeed` / `staleTimeout` | true / 12 / 1.0초 | `staleTimeout` 초과 시 **마지막 포즈 유지**(0으로 안 떨어진다) |
| | `isolateJoint` | `None_전체동작` | 한 관절만 수신값으로 움직이고 19개를 0으로 얼리는 격리 디버그 |
| | `debugThumbLog` / `logRadiansToFile` | **true** | 디버그용 임시 ON. 시연·측정 전에 끈다 |

**패킷 길이 = 버전**(`Dg5fReceiver` 주석과 `dg5f_angles.PACKET_FMT="<72f"`가 정본):
20f=v1 / 24f=v2(엄지끝+핀치) / 25f=v3(+끝거리 비율) / 37f=v4(+검지~새끼 리치벡터) /
52f=v5(+손목→끝 벡터 5개) / **72f=v6(현재 송신 형식, +compute_raw 20채널 라디안)**.
수신기는 **앞 20개만 있으면 동작**하고 나머지는 길이를 보고 선택적으로 읽는다.

### 9-2. 관절 매핑 규칙 — 이름 매칭이지 순서 매칭이 아니다

`Dg5fHandDriver.Start()`는 자식 `ArticulationBody` 중 이름에 `_dg_`가 들어간 것만 골라
**접미사 `_dg_<손가락1~5>_<마디1~4>`**로 사전을 만든 뒤 패킷 인덱스 `(f-1)*4+(j-1)`에 꽂는다.
그래서 오른손(`rl_dg_*`)/왼손(`ll_dg_*`) 프리팹이 같은 코드로 동작한다.
매핑에 실패하면 `[Dg5fHandDriver] 관절 못 찾음: _dg_f_j` 에러가 Console에 뜨고,
성공 시 `관절 매핑 20/20, 포트 NNNN 수신 대기` 한 줄이 찍힌다 — **이 로그가 1차 판정 기준**이다.

팔은 `UrArmJointNames.Names`(링크 이름 6개)와 `UrArmLimits.IndexOf(linkName)`으로 찾는다.

### 9-3. 물리·안전 상수의 정본

| 상수 | 값 | 소스 |
|---|---|---|
| 팔 관절 최대속도[deg/s] | `{120, 120, 180, 180, 180, 180}` | `UrArmLimits.MaxDegPerSec` |
| 팔 관절 최대토크[Nm] | `{330, 330, 150, 54, 54, 54}` | `UrArmLimits.MaxEffortNm` |
| 팔 안전 관절범위[deg] | min `{-180,-120,20,-180,-150,-180}` / max `{180,-20,140,0,-30,180}` | `Dg5fPicknPlaceSpec.ArmSafeMin/MaxDeg` |
| 홈 자세[deg] | `{0, -60, 90, -120, -30, 0}` | `Dg5fPicknPlaceSpec.HomeArmDeg` |
| 주먹 자세 20각[deg] | — | `Dg5fPicknPlaceSpec.RightFistDeg` (RL 자동 제어가 쓰는 정본) |

**주의:** `RobotConfig.cs`는 UR5e+SVH 시절 파일이라 현재 학습 물리값이 아니다. 학습 씬의 드라이브는
`Dg5fPicknPlaceSpec.ArmDriveStiffness/Damping`(10000/200)과 `HandDriveStiffness/Damping/ForceLimit`
(1500/120/20)이 정본이다.

### 9-4. 제어권을 실제로 바꾸는 메서드

UI 버튼 뒤에서 호출되는 것들. 스크립트로 자동화하거나 새 UI를 붙일 때 이 이름을 쓴다.

| 호출 | 무슨 일이 일어나나 |
|---|---|
| `PicknPlaceControlModeSwitcher.SetManualMode(bool)` | 자동↔수동 전환. 수동 진입 시 `agent.PauseForManualControl()`, 자동 복귀 시 `EndEpisode()`. **Agent를 다시 `enabled=true`로 만들지는 않는다**(§0의 저장 씬 제한) |
| `Dg5fPicknPlaceAgent.PauseForManualControl()` | 에이전트가 `xDrive`에 쓰는 것을 멈춘다 |
| `Dg5fFistButton.SetFist(bool)` / `SetGrasp(bool)` | 프리셋 자세 재생. 손 제어권을 계속 보유 |
| `Dg5fFistButton.ReleaseHandToTracking()` | **웹캠 복귀 버튼의 본체.** 이걸 부르기 전엔 웹캠 패킷이 와도 손이 안 움직인다 |
| `Dg5fFistButton.RecordGraspPose(out string)` | 현재 자세를 `dg5f_grasp_pose.json`으로 저장 |
| `Dg5fTwinModeSwitcher.SetMode(TwinMode.Off/SimToReal/RealToSim)` | 손 트윈 방향. `Start()`에서 무조건 `Off`로 시작한다(안전) |
| `PicknPlaceArmJointPanel.SetActive/SyncFromCurrentPose/PullFromUrsim/FullReset` | 팔 패널의 활성화·현재자세 동기화·URSim 자세 끌어오기·초기화 |
| `UrArmBridgeLauncher.Launch() / Stop()` | 팔 브리지 프로세스 기동·정리. `IsRunning`·`Status`로 상태 확인 |

`Dg5fTwinModeSwitcher`의 인스펙터 `syncTimeout`(기본 2초)·`syncSettle`(0.8초)이
sim→real 진입 전 자세 동기화 대기값이다 — **피드백이 안 오면 이 시간 뒤 그냥 진행한다**
([REAL_BRIDGES.md](REAL_BRIDGES.md)의 교시 피드백 제한과 직결).

### 9-5. 로그 파일 규칙

`Dg5fLogFile.Create(prefix, out path)`가 **유일한 CSV 생성 통로**다.
`Logs/<prefix>_<초단위 타임스탬프>.csv`, 같은 이름이 있으면 접미사를 붙여 **절대 덮어쓰지 않는다.**
현재 이 통로를 쓰는 것: `Dg5fJointLogger`(`unity_dg5f_*`, 50Hz, 수신/목표/실측 20관절),
`Dg5fHandDriver`(`rad_dg5f_*`, 비전 라디안 vs 관절 라디안), `Dg5fFingerIK`(IK 디버그).
타임스탬프가 unix 초라 파이썬 로그와 그대로 시간 정렬된다(`vision/dg5f/analyze_teleop.py`).

### 9-6. 에디터 메뉴 전체 경로

| 메뉴 | 스크립트 |
|---|---|
| `KDT > Import UR16e+DG5F-Right Preview Scene` | `Editor/ImportUr16eDg5fRightPreview.cs` |
| `KDT > Preview Scene에 조작 컴포넌트 추가` | `Editor/SetupPreviewSceneControls.cs` |
| `Tools > Robots > Create UR16e DG5F Right Prefab` | `Robots/Editor/CreateUr16eDg5fRightPrefab.cs` |
| `Tools > DG5F > Right / Right Short / Left / Left Short` | `Editor/DG5FVariantSwitcher.cs` |
| `Tools > ML-Agents > Build DG5F PicknPlace Training Scene` | `picknplace/Editor/PicknPlaceTrainingSceneBuilder.cs` |
| `Tools > ML-Agents > Build PicknPlace Pipeline Demo Scene` | `picknplace/Editor/PicknPlacePipelineDemoSceneBuilder.cs` |
| `Tools > ML-Agents > Build DG5F PicknPlace Windows/Linux Player` | `picknplace/Editor/PicknPlaceTrainingBuild.cs` |
| `Tools > ML-Agents > Diagnose PicknPlace Arm Poses` | `picknplace/Editor/PicknPlacePoseDiagnostic.cs` |
| `Tools > ML-Agents > Diagnose PicknPlace Thumb Orientation` | `picknplace/Editor/PicknPlaceThumbDiagnostic.cs` |

씬 빌더가 참조하는 고정 경로(바꾸면 빌더가 깨진다):
입력 프리팹 `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab`,
학습 씬 `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity`,
데모 씬 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`(원본 영역 이름 `DG5F_PicknPlaceTrainingArea_00`),
배포 모델 `Assets/MLAgents/picknplace/Models/DG5FPicknPlace.onnx`.
영역 수는 `.env`의 `DG5F_PICKNPLACE_TRAINING_AREAS`(기본 40), 배치는 3m 간격 `ceil(√N)`열 격자다.
