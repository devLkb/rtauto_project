# `Assets/MLAgents/` — 강화학습 과제 정의와 씬 생성기

"로봇이 스스로 물체를 잡아 드는 정책"의 **Unity 쪽 절반**이다. 무엇을 보고(관찰),
무엇을 움직이고(행동), 무엇을 잘하면 점수를 주는지(보상)를 여기서 정한다.
학습을 돌리는 파이썬 쪽은 [`training/`](../../../training/README.md)에 있다.

## 목차

1. [폴더 구조와 behavior 2개](#1-폴더-구조와-behavior-2개)
2. [핵심 2파일 — Spec과 Agent](#2-핵심-2파일--spec과-agent)
3. [관찰 57칸의 실제 배치](#3-관찰-57칸의-실제-배치)
4. [행동 7칸과 그 스케일](#4-행동-7칸과-그-스케일)
5. [성공·실패 판정 상수](#5-성공실패-판정-상수)
6. [접촉 센서 4종](#6-접촉-센서-4종)
7. [시연용 UI 컴포넌트 5종](#7-시연용-ui-컴포넌트-5종)
8. [에디터 도구 — 씬 생성기·빌더·진단](#8-에디터-도구--씬-생성기빌더진단)
9. [테스트](#9-테스트)
10. [GraspLift(구세대)와의 관계](#10-grasplift구세대와의-관계)
11. [관련 문서](#11-관련-문서)

## 1. 폴더 구조와 behavior 2개

```text
Assets/MLAgents/
├── Editor/                     빌드 공용 어댑터 (KDT.MLAgents.Editor)
│   ├── BuildEnvironment.cs        .env에서 빌드 출력 경로·플레이어 이름을 읽는다
│   └── LinuxPlayerPostProcess.cs  Linux 빌드 후 libdl.so.2 셰임 주입
├── picknplace/                 ★ 현역 — UR16e + DG-5F-M-R 오른손
│   ├── Runtime/                   Agent·Spec·센서·UI (KDT.PicknPlaceTraining)
│   ├── Editor/                    씬 생성기·플레이어 빌더·진단 (…​.Editor)
│   ├── Tests/{EditMode,PlayMode}/ 계약·씬 검증
│   ├── Models/DG5FPicknPlace.onnx 배포 정책
│   ├── DG5F_PicknPlaceTraining.unity   학습 씬 (생성물)
│   └── PicknPlaceTrainingArea.prefab   학습 영역 프리팹 (생성물)
└── GraspLift/                  구세대 — UR5e + 왼손 (같은 구조의 쌍둥이)
```

| behavior | 하드웨어 | 위치 | 상태 |
|---|---|---|---|
| `DG5FPicknPlace` | UR16e + DG-5F-M-R **오른손** (확정 스펙) | `picknplace/` | **현역** |
| `DG5FGraspLift` | UR5e + 왼손 | `GraspLift/` | 검증된 기준선, 구세대 |

**behavior 이름**은 Unity와 Python이 같은 과제·정책을 가리키기 위한 식별자다. picknplace는
GraspLift를 확정 하드웨어로 거의 그대로 이식한 것이라 **파일 이름만 다르고 내용이 쌍둥이**인
것이 많다. **새 작업은 picknplace 쪽에 한다.**

> 이름에 PicknPlace가 남아 있지만 **현재 과제는 잡기 → 들어올려 유지하기**다.
> 운반·내려놓기(place)는 포함하지 않는다.

## 2. 핵심 2파일 — Spec과 Agent

### `Runtime/Dg5fPicknPlaceSpec.cs` (978줄) — 과제 계약서

숫자와 규칙만 모아 둔 **정적 클래스**. 이 파일이 **"무엇이 성공인가"의 정본**이다.

| 상수 | 값 |
|---|---|
| `SpecVersion` | `"3.0.0"` |
| `BehaviorName` | `"DG5FPicknPlace"` |
| `ObservationSize` / `ActionSize` | 57 / 7 |
| `ArmJointCount` / `HandJointCount` / `FingerCount` | 6 / 20 / 5 |
| `ContactPointCount` / `PalmContactIndex` | 6 (손끝 5 + 손바닥) / 5 |
| `EpisodeTimeoutSeconds` | 20 s |
| `DecisionTimePenalty` | −0.001 |
| `PanelWidth` / `PanelDepth` / `PanelThickness` | 1.80 / 1.80 / 0.25 m |
| `SupportTopHeight` | 0 m |
| `MaximumObjectDistance` | 0.90 m |
| `CubeWidth` / `CubeHeight` | 0.035 / 0.12 m (밀도 1800 kg/m³) |
| `MinimumCubeWidth` ~ `MaximumCubeWidth` | 0.025 ~ 0.060 m |
| `MinimumCubeHeight` | 0.06 m |
| `HomeArmDeg` | `{0, −60, 90, −120, −30, 0}` |
| `ArmSafeMin/MaxDeg` | min `{−180,−120,20,−180,−150,−180}` / max `{180,−20,140,0,−30,180}` |
| `ArmDriveStiffness/Damping` | 10000 / 200 |
| `HandDriveStiffness/Damping/ForceLimit` | 1500 / 120 / 20 |
| `RightFistDeg[20]` | RL 자동 제어가 쓰는 주먹 자세 |

`Set*Parameter` 계열 메서드가 커리큘럼(YAML `environment_parameters`)에서 값을 갈아끼우는 통로다.

> ⚠️ **수동 버튼의 `config/dg5f_grasp_pose.json`과 `RightFistDeg`는 다른 것이다.**
> 자세를 녹화해도 학습 정책은 바뀌지 않는다.

### `Runtime/Dg5fPicknPlaceAgent.cs` (1156줄) — 에이전트 본체

ML-Agents `Agent`를 상속한 컴포넌트. 매 스텝 세 가지를 한다.

1. **관찰 수집** — `CollectObservations()`가 57개 값을 만든다(§3).
2. **행동 적용** — `OnActionReceived()`가 7개 값을 팔 6관절 + 손 개폐로 바꿔 `xDrive.target`에 쓴다(§4).
3. **보상 계산 및 종료 판정** — `RecordOutcome()`이 TensorBoard 태그를 기록한다.

씬 참조 필드(하나라도 비면 관찰이 전부 0이 된다):

| 필드 | 무엇 |
|---|---|
| `cubeTarget` / `cubeCollider` | 목표 물체 |
| `pedestal` / `pedestalCollider` | 받침 |
| `robotBase` / `palm` / `graspPoint` | 좌표 기준 Transform |
| `fingerTips[5]` | 손끝 |
| `contactSensors[6]` / `safetySensors[]` / `handSurfaceSensors[]` / `selfCollisionSensors[]` | 접촉 센서(§6) |

| 튜닝 필드 | 기본값 |
|---|---|
| `useDeterministicSpawns` / `spawnSeed` | false / 12345 |
| `endEpisodeOnSuccess` | true |
| `gripDeltaPerDecision` | 0.08 |

노출 프로퍼티: `CurrentClosure` · `CurrentEpisodeSeconds` · `IsGraspConfirmed` ·
`CurrentGraspSeconds` · `CurrentContactCount` — 시연 UI가 읽는다.

> **학습 씬에서 `xDrive`에 쓰는 것은 이 컴포넌트뿐**이라는 게 설계 규칙이다. 다른 구동자
> (텔레옵 수신, 주먹 버튼)가 동시에 쓰면 결과가 실행 순서에 따라 달라진다. 그래서 씬 빌더가
> 경쟁 구동자를 자동으로 비활성화한다(`CompetingDriverTypes`).

## 3. 관찰 57칸의 실제 배치

"관찰 57개"라는 숫자만으로는 실물 이관도, 모델 호환 판정도 못 한다. 값은 전부 정규화·클램프된다.

| 인덱스 | 내용 | 정규화 |
|---|---|---|
| `0..5` | 팔 6관절 실제각 | `ArmSafeMin/MaxDeg` 범위를 −1~+1로 |
| `6..11` | 팔 6관절 각속도 | `rad/s ÷ π`, ±1 클램프 |
| `12` | 손 폐합률(closure) | `closure×2−1` |
| `13..15` | 파지 목표점 − 손 grasp point (로봇 베이스 좌표) | ÷1.0 m |
| `16..18` | 물체 선속도 (베이스 좌표) | ÷2.0 |
| `19..21` | 물체 각속도 (베이스 좌표) | ÷10.0 |
| `22` | 스폰 높이 대비 물체 상승량 | ÷0.2 m |
| `23..37` | 손끝 5개 − 물체중심 (**손바닥 좌표**) | ÷0.2 m |
| `38..42` | 손끝 5개 접촉 플래그 | 0/1 |
| `43..48` | 팔 6관절 **명령 목표각**(`xDrive.target`) | 관절 범위 정규화 |
| `49` | 손바닥 접촉 플래그 | 0/1 |
| `50` | 접촉 지점 수 ÷ 6 | 0~1 |
| `51` | 파지 확정 진행도 (`_graspSeconds`/0.3초) | 0~1 |
| `52` | 파지 확정 여부 | 0/1 |
| `53` | 리프트 진행도 | 0~1 |
| `54` | 리프트 유지 진행도 | 0~1 |
| `55` | 파지 거리 ÷ 0.90 m | 0~1 |
| `56` | 경과 시간 ÷ 20초 | 0~1 |

**씬 참조가 하나라도 없거나 물리값이 NaN/∞이면 57칸 전부 0을 넣고 빠져나온다.**
학습이 안 되는데 에러도 없으면 이 경로를 의심한다.

⚠️ 관찰은 **모두 시뮬레이터 내부 상태**다. `13..21`(물체 위치·속도)과 `38..42`·`49`(접촉)는
실물에 대응 신호가 없어, **실물 이관 시 이 칸들을 어디서 채울지가 남은 과제**다.
현재 학습 입력은 카메라 영상이 아니며, 웹캠 텔레옵이 이 값을 대신 공급하지 않는다.

## 4. 행동 7칸과 그 스케일

`OnActionReceived(ActionBuffers)` — 연속 7개, 각 −1~+1로 클램프된다.

**`[0..5]` 팔 6축의 각도 증분**

```text
실제 증분 = action × MaxDegPerSec[i] × TrainingSpeedFraction(0.5) × 결정주기
결정주기 = DecisionRequester.DecisionPeriod(씬 빌더가 5로 설정) × fixedDeltaTime(0.02s) = 0.1초
```

즉 관절 0은 한 결정에 최대 `120 × 0.5 × 0.1 = 6°` 움직인다. **관절마다 상한이 다르다.**
물체 0.08 m 이내(`NearObjectControlClearance`)에선 `NearObjectArmDeltaScale = 0.35`가 곱해져
미세동작이 된다.

**`[6]` 손 개폐 증분** — `gripDeltaPerDecision = 0.08`을 곱해 폐합률 0~1을 이동시키고,
`ApplyGripTargets()`가 "펴진 자세 ↔ `RightFistDeg`" 사이를 **스칼라 하나로 보간**해 20관절에 쓴다.

⚠️ `DecisionRequester`가 씬에 없으면 결정주기를 1스텝으로 가정해 **의도보다 5배 느리게 움직이고
경고만 찍는다.**

> 정책은 팔 6축 + 손 개폐 1축을 출력한다. 비전 텔레옵의 손 20축 패킷과는 **다른 계약**이다.

## 5. 성공·실패 판정 상수

| 판정 | 함수 | 상수 |
|---|---|---|
| 파지 후보 | `IsGraspCandidate(...)` | 접촉 ≥`GraspContactMinimum`(3), 최대 대향각 ≥`GraspOppositionAngleDeg`(90°), 접촉중심−물체중심 ≤`GraspCenterMaxDistance`(0.05 m), 폐합률 ≥`MinimumGraspClosure`(0.30) |
| 파지 확정 | `IsGraspConfirmed(sec)` | 후보 상태를 `GraspConfirmSeconds`(0.30초) 유지 → **+`GraspConfirmReward`(1.0)** |
| 안정 리프트 | `IsStableLift(h, speed)` | 목표 높이 도달 + 물체 속도 ≤`LiftMaximumSpeed`(0.50 m/s) |
| 성공 | `IsLiftComplete(sec)` | 안정 리프트를 `CurrentLiftHoldSeconds` 유지 → **+`LiftSuccessReward`(5.0)** |
| 타임아웃 | `ReachedEpisodeTimeout` | `EpisodeTimeoutSeconds`(20초) |

**커리큘럼(`grasp_stage` 1/2/3)이 바꾸는 값**

| 값 | 1단계 | 2단계 | 최종 |
|---|---|---|---|
| `CurrentLiftTargetHeight` | 5 cm | 8 cm | **10 cm** |
| `CurrentLiftHoldSeconds` | 0.25 s | 0.35 s | **0.50 s** |
| 스폰 반경 | — | — | 0.37~0.58 m 환형 |

**실패 사유와 페널티** (`FailurePenalty(reason)`)

| 사유 문자열 | 페널티 |
|---|---|
| `UnsafeSurfaceContact` | −2.0 |
| `SelfCollision` | −2.0 |
| `Dropped` | −1.0 |
| `ObjectOutOfBounds` | −1.0 |
| `ObjectPushedAway` | −0.5 |
| `ObjectToppled` | −0.3 |

이 문자열이 그대로 TensorBoard `Failure/<reason>` 태그가 된다 — **모니터에서 보이는 태그 이름과
코드가 같은 문자열**이다.

**지속 페널티**: 결정마다 `DecisionTimePenalty`(−0.001), 행동 급변
`ActionRatePenaltyScale`(−0.001), 물체 근처 행동 크기 `NearObjectActionPenaltyScale`(−0.002),
손이 바닥 긁음 `HandSurfacePenaltyPerSecond`(−0.05/초), 엄지가 아래를 향함
`ThumbDownPenaltyScale`(−0.05), 든 물체 기울어짐 `LiftTiltPenaltyScale`(−0.02, 10° 이하 무료·30°에서 포화).

> **페널티 설계 규칙**: 한 에피소드 전체를 최대 비용으로 채워도 **리프트 성공 1회의 보상을
> 넘지 않아야 한다.** 2026-08-28에 −0.10짜리 엄지 페널티가 200결정 × −0.10 = −20으로 최대
> 획득 가능 보상(+12.2)을 압도해 학습이 **정지 정책으로 수렴**한 사고가 이 규칙의 출처다.

**YAML이 갈아끼울 수 있는 파라미터 이름** (여기 없는 상수는 재컴파일·재빌드가 필요하다):
`grasp_stage` · `cube_width` · `cube_height` · `cube_com_height_fraction` · `topple_limit_deg` ·
`topdown_potential_max` · `action_rate_penalty_scale` · `hand_surface_penalty_per_second` ·
`grasp_posture_penalty_scale` · `thumb_down_penalty_scale` · `lift_tilt_penalty_scale`

## 6. 접촉 센서 4종

| 파일 | 감지 대상 | 판정 방식 | 노출 |
|---|---|---|---|
| `PicknPlaceObjectContactSensor.cs` (68줄) | 손끝 5 + 손바닥이 **물체**에 닿았는가 | `OnCollisionEnter/Stay/Exit`, `targetCollider`와의 접촉만 | `IsTouching`, `LastImpulse`, `contactIndex`(손끝 0~4, 손바닥 5) |
| `PicknPlaceSurfaceContactSensor.cs` (71줄) | **팔**이 바닥에 닿았는가 | 충돌 시 `agent.NotifyUnsafeSurfaceContact()` | `HasUnsafeContact`, `unsafeSurfaces[]` → **즉시 실패 종료** |
| `PicknPlaceHandSurfaceSensor.cs` (56줄) | 손이 바닥을 긁고 있는가 | 접촉 **시간**을 누적 | `IsTouching` → 실패가 아니라 **초당 감점** |
| `PicknPlaceSelfCollisionSensor.cs` (66줄) | 로봇이 자기 몸에 닿았는가 | **`OnTriggerEnter/Stay`** — 트리거 전용 그림자 콜라이더 | `HasViolation`, `IsSelfCollision(a,b)`, `owningBody` |

**팔은 바닥 접촉이 실패, 손가락은 아니다.** 바닥의 물체를 잡으려면 손가락은 닿을 수밖에 없기
때문에 일부러 제외했다.

**자기충돌은 왜 트리거인가.** 물리 충돌을 다시 켜면 인접 마디 겹침으로 진동이 생긴다
(`RobotSelfCollisionIgnore`가 막는 그 문제). 그래서 겹침만 감지하는 그림자 콜라이더를 쓴다.

에피소드 시작마다 `ResetContacts()`로 초기화한다 — **새 센서를 추가하면 이 호출도 함께 넣어야 한다.**

## 7. 시연용 UI 컴포넌트 5종

학습에는 쓰이지 않고 데모 씬에서만 도는 것들이다.

| 파일 | 줄 수 | 역할 | 핵심 메서드·필드 |
|---|---|---|---|
| `PicknPlaceControlModeSwitcher.cs` | 159 | 자동(정책) ↔ 수동(사람) 전환 | `SetManualMode(bool)`, `IsManual`, `startInManualMode`(true), `handOnlyManualMode` |
| `PicknPlaceArmJointPanel.cs` | 309 | UR16e 6축 슬라이더 + URSim 연동 방향 (상호배타 강제) | `SetActive`, `SyncFromCurrentPose()`, `PullFromUrsim()`, `FullReset()`, `IsActive` |
| `Dg5fFistButton.cs` | 516 | 주먹·펴기·저장 파지 자세 재생, 자세 저장, 웹캠 복귀 | `SetFist(bool)`, `SetGrasp(bool)`, `ReleaseHandToTracking()`, `RecordGraspPose(out string)`, `ResyncToCurrentPose()` |
| `Dg5fTwinModeSwitcher.cs` | 247 | 손 트윈 방향 전환 + 브리지에 제어 패킷 송신 | `SetMode(TwinMode.Off/SimToReal/RealToSim)`, `syncTimeout`(2s), `syncSettle`(0.8s), `ControlMagic`=`"DG5FMODE"` |
| `PicknPlaceFreeFlyCamera.cs` | 103 | 데모 카메라를 Scene 뷰처럼 조작(우클릭 회전, WASD) | `moveSpeed`(1.5), `sprintMultiplier`(3), `lookSensitivity`(3), 속도 0.2~10 |

### 제어권이 실제로 바뀌는 지점

| 호출 | 무슨 일이 일어나나 |
|---|---|
| `PicknPlaceControlModeSwitcher.SetManualMode(true)` | `agent.PauseForManualControl()` — 에이전트가 `xDrive`에 쓰는 것을 멈춘다 |
| `…SetManualMode(false)` | `EndEpisode()` 호출. **Agent를 다시 `enabled=true`로 만들지는 않는다**(알려진 제한) |
| `Dg5fFistButton.SetFist/SetGrasp` | 프리셋 자세 재생. **손 제어권을 계속 보유한다** |
| `Dg5fFistButton.ReleaseHandToTracking()` | **웹캠 복귀 버튼의 본체.** 이걸 부르기 전엔 웹캠 패킷이 와도 손이 안 움직인다 |
| `Dg5fTwinModeSwitcher.SetMode(...)` | `Start()`에서 무조건 `Off`로 시작한다(안전) |

`Dg5fFistButton`의 주요 필드: `sequentialClosing`(true, 순차 폐합), `stageTolerance`(1.5°),
`driveHand`(true), `maxJointDegPerSec`(**Start()에서 `.env` 값으로 채운다** — 코드에 박지 않는다),
`graspPoseFile`(빈 값이면 `.env`의 `RTAUTO_DG5F_GRASP_POSE`).
`GraspPose` 직렬화 구조체는 `name`·`hand`·`captured_utc`·`source`·`convention`·`channels[]`·`deg[]`.

`Dg5fTwinModeSwitcher`의 제어 패킷은 **길이로 관절 패킷과 구분된다** — 매직 8바이트 +
모드 1바이트 = 9바이트, 관절 패킷은 80바이트 이상.

## 8. 에디터 도구 — 씬 생성기·빌더·진단

### `PicknPlaceTrainingSceneBuilder.cs` (597줄) — 학습 씬 재생성

**씬 파일을 직접 편집하는 대신 이걸 다시 돌리는 게 규칙이다.**

| 상수 | 값 |
|---|---|
| `SourceRobotPath` | `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab` |
| `TrainingPrefabPath` | `Assets/MLAgents/picknplace/PicknPlaceTrainingArea.prefab` |
| `TrainingScenePath` | `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity` |
| `DeployedModelPath` | `Assets/MLAgents/picknplace/Models/DG5FPicknPlace.onnx` |
| `CubeMaterialPath` / `*PhysicsMaterialPath` | 큐브·패널 머티리얼 |
| `TrainingAreaCountKey` | `DG5F_PICKNPLACE_TRAINING_AREAS` (기본 40) |
| `TrainingAreaSpacing` | 3 m |
| 배치 | `TrainingAreaColumns = ceil(√N)` 열 격자 |

주요 단계: `Build()` → `PopulateTrainingAreas()` → `ConfigureTrainingAreaInstance(area, index)` →
`LayoutCenter()` → `DisableCompetingDrivers(robot)` → `ConfigureJointDrives(robot)`.

`CompetingDriverTypes`는 **에이전트와 같은 관절에 쓰는 컴포넌트 목록**이다. 학습 씬에서 이들을
꺼야 결과가 실행 순서에 좌우되지 않는다. 매 빌드마다 배포 ONNX를 다시 읽어
BehaviorParameters에 연결한다.

**경로를 옮기면 빌더가 깨진다.** 파일을 옮길 일이 있으면 이 상수들을 함께 고친다.

### `PicknPlacePipelineDemoSceneBuilder.cs` (346줄) — 시연 씬 생성

학습 씬의 `DG5F_PicknPlaceTrainingArea_00` 하나를 떼어
`Assets/Scenes/Pipeline_Demo_GraspLift.unity`로 만든다.

| 상수 | 값 |
|---|---|
| `SourceAreaName` | `DG5F_PicknPlaceTrainingArea_00` |
| `DemoScenePath` | `Assets/Scenes/Pipeline_Demo_GraspLift.unity` |
| `HandRootName` / `WrongHandRootName` | `rl_dg_palm` / `ll_dg_palm` |
| `FreeFlyCameraStartOffset` | `(0.4, 0.3, −0.4)` |

**손 루트 이름을 확인해 `ll_dg_palm`(왼손)이면 거부한다** — 구세대 프리팹으로 데모를 만드는
사고를 막기 위해서다. 단계: `ConfigureAgent` → `ConfigureManualTeleop` → `ConfigureCamera` →
`SetInferenceOnly`. 성공해도 리셋하지 않고 마지막 자세를 유지한다(시연용).

### `PicknPlaceTrainingBuild.cs` (92줄) — 플레이어 빌드

`BuildWindowsPlayer()` / `BuildLinuxPlayer()`. 대상 씬은
`Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity` 하나이며,
**씬 재생성을 먼저 자동 실행**한다.

### 진단 도구 2종 — 값의 근거를 데이터로 만든다

| 파일 | 하는 일 |
|---|---|
| `PicknPlacePoseDiagnostic.cs` (153줄) | 후보 홈 자세들을 실제 씬 기하로 재서 "내려다보는 준비자세"를 **데이터로 고른다**. `RunSweep()` → `LogPose()` |
| `PicknPlaceThumbDiagnostic.cs` (217줄) | 엄지 자세를 실측해 보상 제약값의 근거를 만든다. `Physics.Simulate(fixedDeltaTime)`로 한 스텝씩 진행하며 `xDrive.target`을 읽는다 |

### 빌드 공용 어댑터 (`MLAgents/Editor/`)

| 파일 | 하는 일 |
|---|---|
| `BuildEnvironment.cs` | `.env`에서 출력 경로·플레이어 이름을 읽는다. `Load()` → `GetPath(keys…)` / `GetFileName(keys…)` / `GetPositiveInt(fallback, keys…)`. **키를 여러 개 받는 이유는 옛 키 이름이 남아 있어도 동작하게 하기 위해서다** |
| `LinuxPlayerPostProcess.cs` | Linux 플레이어 빌드 후 `build-support/linux/libdl.so.2` 주입 |

## 9. 테스트

| 위치 | 하는 일 |
|---|---|
| `picknplace/Tests/EditMode/Dg5fPicknPlaceSpecTests.cs` | 보상·성공 판정 로직의 단위 테스트(로봇 없이 순수 계산 검증) |
| `picknplace/Tests/PlayMode/PicknPlaceSceneTests.cs` | 생성된 학습 씬이 계약대로인지(오브젝트 구성·물리) 검증 |
| `GraspLift/Tests/PlayMode/GraspLiftSceneTests.cs` | 위와 같고, 추가로 **물리적 실현 가능성 프로브** — "닫힌 손이 이 블록을 들고 버틸 수 있는가"를 직접 확인 |
| `GraspLift/Tests/PlayMode/GraspLiftHandGeometryProbe.cs` | 합격/불합격이 아니라 **측정 도구**. 손을 닫았을 때 손끝이 실제로 어디 가는지 재서 블록 크기를 URDF 계산이 아닌 **시뮬 실측**으로 정한다 |

> **왜 물리 프로브가 필요한가.** PPO는 물리적으로 불가능한 파지를 학습할 수 없다. 그 질문을
> 학습 곡선으로 추측하는 대신 씬에서 직접 재는 것이다.

실행: Unity 메뉴 `Window > General > Test Runner` → EditMode / PlayMode 탭.
과거 실행 결과 XML은 [`training/test-results/`](../../../training/test-results/)에 있다.

## 10. GraspLift(구세대)와의 관계

`GraspLift/`에는 picknplace와 **같은 역할의 쌍둥이**가 있다.

| picknplace | GraspLift |
|---|---|
| `Dg5fPicknPlaceAgent` / `Spec` | `Dg5fGraspLiftAgent` / `Dg5fGraspLiftSpec` |
| `PicknPlaceObjectContactSensor` 등 4종 | `GraspLiftObjectContactSensor` 등 3종 |
| `PicknPlaceControlModeSwitcher` | `GraspLiftControlModeSwitcher` |
| — | `GraspLiftTeleopNudge`(마우스 조이스틱 팔 조작), `GraspLiftDemoCameraSwitcher` |
| `PicknPlaceTrainingSceneBuilder` 등 | `GraspLiftTrainingSceneBuilder` 등 |

관찰 57 / 행동 7로 **크기는 같지만, 크기가 같다는 것만으로 다른 로봇의 정책을 그대로 쓸 수
있다는 뜻은 아니다.** 모델을 고를 때는 behavior 이름·로봇 기종·관찰과 행동의 의미·평가 결과를
함께 확인한다.

> `Dg5fGraspLiftSpec.cs`의 주석이 `*.sim.mjcf.xml`을 관절값 검증 출처로 언급하는데, 이는 그
> 수치가 어떻게 나왔는지에 대한 **기록일 뿐 의존성이 아니다**(MuJoCo 경로는 폐기됨).

## 11. 관련 문서

- [`docs/modules/RL_TRAINING.md`](../../../docs/modules/RL_TRAINING.md) — RL 모듈 전체 설명(정본)
- [`training/README.md`](../../../training/README.md) — 학습 실행 절차
- [`training/config/README.md`](../../../training/config/README.md) — 하이퍼파라미터·커리큘럼
- [`training/scripts/README.md`](../../../training/scripts/README.md) — 학습 런처·모니터
- [`docs/DG5F_PICKNPLACE.md`](../../../docs/DG5F_PICKNPLACE.md) — 이식·설계 이력
- [`docs/TRAINING_RUN_LEDGER.md`](../../../docs/TRAINING_RUN_LEDGER.md) — 런 판정 이력

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/Assets/MLAgents/README.md`
- **갱신 대상**: `unity/Assets/MLAgents/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/RL_TRAINING.md` §7, `training/config/README.md`
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

