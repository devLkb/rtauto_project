# 강화학습(RL) 모듈 설명

"로봇이 스스로 물체를 잡아 드는 정책"을 만드는 부분. 두 덩어리로 나뉜다.

- **Unity 쪽(`unity/Assets/MLAgents/**`)** — 과제 정의. 무엇을 보고(관찰), 무엇을 움직이고(행동),
  무엇을 잘하면 점수를 주는지(보상).
- **파이썬 쪽(`training/**`)** — 학습을 돌리고, 결과를 읽고, 실패한 런을 격리한다.

실행 절차는 [`training/README.md`](../../training/README.md)가 정본이다.
이 문서는 학습의 입력·출력, Unity·비전·실물과의 경계, 각 파일의 역할을 설명한다.

## 0. 큰 그림

```text
 Unity 학습 씬(기본 40영역)     ←→  mlagents-learn (PPO)  →  .onnx 정책 파일
   Dg5fPicknPlaceAgent가                  ↑                        ↓
   관찰 57개를 만들고 행동 7개를          training/config/*.yaml    대응 모델을 지정하고
   받아 관절에 씀                          (학습 설정)               자동 모드에서 추론
```

**정책**은 관찰값을 받아 행동을 계산하는 학습 결과다. **관찰**은 정책에 주는 상태값,
**행동**은 정책이 내놓는 제어값, **보상**은 학습 중 행동을 평가하는 점수다.
한 번의 시도를 **에피소드**, 여러 시도를 묶어 실행·저장한 학습 작업을 **런(run)**이라고 한다.
PPO는 이 프로젝트가 사용하는 학습 알고리즘이고, ONNX는 학습한 정책을 추론용으로 저장하는 형식이다.

**behavior 이름**은 Unity와 Python이 같은 과제·정책을 가리키기 위한 식별자다.

| behavior | 하드웨어 | 위치 | 상태 |
|---|---|---|---|
| `DG5FPicknPlace` | UR16e + DG-5F-M-R **오른손** (확정 스펙) | `MLAgents/picknplace/` | **현역** |
| `DG5FGraspLift` | UR5e + 왼손 | `MLAgents/GraspLift/` | 검증된 기준선, 구세대 |

picknplace는 GraspLift를 확정 하드웨어로 **거의 그대로 이식**한 것이다. 그래서 파일 이름만 다르고
내용이 쌍둥이인 것들이 많다. 새 작업은 picknplace 쪽에서 한다.

이름에 PicknPlace가 남아 있지만 **현재 과제는 잡기 → 들어올려 유지하기**다. 운반·내려놓기(place)는
포함하지 않는다. 배경은 [DG5F_PICKNPLACE.md](../DG5F_PICKNPLACE.md)에 있다.

### 정책은 무엇을 보고 움직이나

| 필요한 정보 | 현재 값을 만드는 곳 | 실물 이관에서 달라지는 점 |
|---|---|---|
| 팔 각도·속도 | Unity 물리 관절 | 실물 관절 상태를 읽어 같은 규약으로 변환해야 함 |
| 물체 위치·속도·각속도, 손끝과의 상대 위치 | Unity 물체·로봇의 내부 좌표 | 실제 물체 인식과 카메라↔로봇 좌표 변환이 필요 |
| 손끝·손바닥 접촉 | Unity 접촉 센서 | 대응 실물 신호를 확보하거나 관찰을 재설계해야 함 |
| 파지·리프트 진행도 | Agent 내부 상태 | 실물에서도 같은 의미로 상태를 계산해야 함 |

**현재 학습 입력은 카메라 영상이 아니다.** Unity가 시뮬레이션의 상태를 직접 알고 있어 만드는 값이다.
웹캠 텔레옵은 사람이 손을 조작하는 별도 경로이며, 다중 카메라 모듈도 이 57개 관찰에 자동 연결되지 않는다.
ONNX 파일과 장비 브리지가 있다고 실물 자율 파지가 완성되는 것은 아니다.
근거: [CollectObservations](../../unity/Assets/MLAgents/picknplace/Runtime/Dg5fPicknPlaceAgent.cs).

### 학습과 시연은 어떻게 다른가

학습에서는 Python 트레이너가 Unity와 관찰·행동·보상을 주고받으며 정책을 갱신한다.
시연 경로에서는 Unity가 지정된 ONNX 모델로 행동을 계산한다. 데모는 수동으로 시작하고,
자동 전환 코드는 에피소드 리셋을 요청한다. **현재 저장된 데모는 Agent가 비활성이며 자동 전환이
이를 다시 켜지 않는 제한**이 있다. [Unity 문서](UNITY.md)의 현재 씬 상태를 확인한다.
모델이 없으면 데모 빌더가 모델을 만들어 주지 않으며, 파일이 있다는 사실만으로 파지 성공도 보장되지 않는다.
모델을 고를 때는 behavior·로봇 기종·관찰과 행동의 의미·평가 결과를 함께 확인한다.

정책은 팔 6축과 손 개폐 1축을 출력한다. 비전 텔레옵의 손 20축 패킷과 다른 계약이며,
Agent가 손 개폐 값을 20개 관절 목표각으로 확장한다. 수동 버튼의 `dg5f_grasp_pose.json`은
이 과정에서 사용하지 않는다. [Unity 제어권 설명](UNITY.md)을 함께 읽는다.

## 1. 과제 정의 — 핵심 2개 파일

### `Runtime/Dg5fPicknPlaceSpec.cs` — 과제 계약서

숫자와 규칙만 모아둔 정적 클래스. **이 파일이 "무엇이 성공인가"의 정본**이다.

- 정책 모양: 관찰 57개 / 행동 7개(팔 6축 + 손 개폐 1축). GraspLift와 크기는 같지만
  크기가 같다는 것만으로 다른 로봇의 정책을 그대로 사용할 수 있다는 뜻은 아니다.
- 물체 기본 규격: 0.035 × 0.12 × 0.035 m 사각기둥, 밀도 1800 kg/m³. 코드 이름은 cube이며
  크기·무게중심 등은 환경 파라미터에 따라 달라질 수 있다.
- 파지 확정: 접촉 센서 지점 3개 이상, 접촉 방향의 최대 벌어진 각도 90° 이상,
  접촉 중심과 물체 중심 거리 5cm 이내, 손 폐합률 0.30 이상인 후보 상태를 0.3초 유지.
- 들어올리기: 목표 상승 높이와 물체 속도 ≤0.50 m/s 조건을 정해진 시간 유지.
  커리큘럼 1/2/최종 단계의 높이는 **5/8/10cm**, 유지 시간은 **0.25/0.35/0.5초**다.
- 각종 페널티: 행동 급변, 손이 바닥을 긁음, 물체 기울어짐(topple), 자세 불량 등.
- `Set*Parameter` 계열 — 커리큘럼(난이도 점진 상승)에서 YAML이 값을 갈아끼울 수 있게 하는 통로.

### `Runtime/Dg5fPicknPlaceAgent.cs` — 에이전트 본체

ML-Agents의 `Agent`를 상속한 컴포넌트. 매 스텝 하는 일:

1. 관찰 수집 — 관절각, 손·물체 상대 위치, 접촉 상태 등 57개 값을 만든다.
2. 행동 적용 — 정책이 준 7개 값을 팔 6관절 + 손 개폐 비율로 바꿔 `xDrive.target`에 쓴다.
   손가락 20관절은 "펴진 자세 ↔ 검증된 주먹 자세" 사이를 스칼라 하나로 보간한다.
3. 보상 계산 및 에피소드 종료 판정.

> **학습 씬에서 xDrive에 쓰는 것은 이 컴포넌트뿐**이라는 게 설계 규칙이다. 다른 구동자
> (텔레옵 수신, 주먹 버튼)가 동시에 쓰면 결과가 실행 순서에 따라 달라진다.

### 접촉 센서 4종 — 에이전트에 "무엇이 닿았는지" 알려주는 부품

| 파일 | 감지 대상 |
|---|---|
| `PicknPlaceObjectContactSensor.cs` | 손끝 5개 + 손바닥이 **물체**에 닿았는가 (파지 판정의 입력) |
| `PicknPlaceSurfaceContactSensor.cs` | **팔**이 바닥에 닿았는가 (안전 실패). 손가락은 일부러 제외 — 바닥의 물체를 잡으려면 닿을 수밖에 없다 |
| `PicknPlaceHandSurfaceSensor.cs` | 손이 바닥을 긁고 있는가 (실패가 아니라 감점 요소) |
| `PicknPlaceSelfCollisionSensor.cs` | 로봇이 자기 몸에 닿았는가. 물리 충돌을 다시 켜면 진동이 생기므로, **트리거 전용 그림자 콜라이더**로 겹침만 감지한다 |

## 2. 학습 실행 (`training/scripts/`)

| 파일 | 하는 일 |
|---|---|
| `train_picknplace.py` | **학습 런처.** `mlagents-learn`을 직접 치지 않는 이유는 플레이어 경로·포트·병렬 수가 머신마다 다르고 그 정본이 `.env`이기 때문. 기본은 headless 병렬 학습, `--editor`로 에디터 붙이기 |
| `mlagents_learn_compat.py` | ML-Agents 1.x가 요구하는 **구버전 ONNX 내보내기 경로**를 강제하는 래퍼. 최신 PyTorch의 기본 exporter를 쓰면 학습 끝에 모델 저장이 실패한다 |
| `validate_unity_environment.py` | 별도로 제공한 manifest(빌드 명세 파일)와 플레이어·DLL의 해시, 설정의 behavior 등을 대조. 현재 `train_picknplace.py`가 자동 호출하지는 않음 |

## 3. 학습 감시·판정 (`training/scripts/`)

학습은 몇 시간씩 걸리므로 "지금 잘 되고 있나"를 사람이 눈으로 판단하지 않게 만드는 도구들이다.

| 파일 | 하는 일 |
|---|---|
| `picknplace_monitor.py` | **현역 모니터.** 저장된 `PicknPlace/*` 지표를 한 번 읽고 보고. `--gate`는 게이트 중심으로 출력하며 실패 시 종료코드 1. **학습 프로세스를 직접 중단하지 않음** |
| `grasp_metrics.py`, `show_dg5f_metrics.py`, `dg5f_status.py` | 이전 세대 behavior(`Reach/*`, `Grasp/*` 태그)용 모니터. **picknplace에는 쓸 수 없다** |
| `archive_run.py` | 끝난 런을 `failure/`·`legacy/`로 격리하고 실패 이유를 문서로 남긴다. 죽은 체크포인트를 `--resume`이 가리키는 사고를 막는 게 목적 |
| `tools/plot_grasp_lift_curves.py`, `tools/plot_grasp_lift_slides.py` | TensorBoard 로그를 발표용 그래프 PNG로 렌더링 |

모니터의 실패 판정을 받은 뒤 학습을 종료하고 기록·격리하는 것은 별도 단계다.
자동 감시를 구성하려면 반복 호출과 종료코드를 처리하는 실행 주체가 필요하며 현재 런처에 내장되어 있지 않다.
결과를 해석할 때는 최근 보상뿐 아니라 파지 확정·리프트 성공·실패 이유를 함께 본다.
근거: [모니터](../../training/scripts/picknplace_monitor.py), [런처](../../training/scripts/train_picknplace.py).

학습이 시작되지 않으면 플레이어 경로·현재 OS용 빌드·트레이너 연결 로그를 확인한다.
코드를 바꿨는데 지표가 그대로라면 **기존 빌드로 학습 중인지** 확인한다.
자동 시연이 움직이지 않으면 Unity의 수동 시작 상태·Agent 활성 상태·모델 지정을 먼저 확인한다.

## 4. 정책 이어받기 (transfer)

처음부터 학습하지 않고 이미 학습된 가중치를 씨앗으로 쓰는 스크립트들.

| 파일 | 하는 일 |
|---|---|
| `prepare_dg5f_grasp_lift_transfer.py` | 기존 체크포인트를 **새 behavior 이름 아래로 복사**해 `--initialize-from` 소스로 만든다(가중치는 바이트 단위 그대로) |
| `bootstrap_v1_to_joint26.py` | 구버전 정책(57관찰/7행동)을 확장된 관절 규격으로 늘린다 |
| `prepare_hold_curriculum_init.py` | 커리큘럼 전환용으로 새로 추가된 관찰 슬롯의 노이즈를 낮춘 체크포인트를 만든다 |

## 5. 설정 파일 (`training/config/*.yaml`)

PPO 하이퍼파라미터 + 커리큘럼. 파일 이름이 곧 실험 이름이다.

- `dg5f_picknplace.yaml` — **현역 학습 설정.** 주석에 왜 이 값인지(측정된 처리량 수치 포함)가 적혀 있다.
- `dg5f_grasp_lift*.yaml` — GraspLift 계열. `t1/t2/t3/t4_topdown*`는 보상 계수 스윕 실험,
  `s1~s4`는 자세·긁힘·행동률 페널티 스윕, `*_eval_*`은 평가 전용(학습 없이 성능 측정).

## 6. 테스트 (`training/tests/`, Unity `Tests/`)

| 위치 | 하는 일 |
|---|---|
| `MLAgents/picknplace/Tests/EditMode/Dg5fPicknPlaceSpecTests.cs` | 보상·성공 판정 로직의 단위 테스트(로봇 없이 순수 계산 검증) |
| `MLAgents/picknplace/Tests/PlayMode/PicknPlaceSceneTests.cs` | 생성된 학습 씬이 계약대로인지(오브젝트 구성·물리) 검증 |
| `MLAgents/GraspLift/Tests/PlayMode/GraspLiftSceneTests.cs` | 위와 같고, 추가로 **물리적 실현 가능성 프로브** — "닫힌 손이 이 블록을 들고 버틸 수 있는가"를 직접 확인한다. PPO는 물리적으로 불가능한 파지를 학습할 수 없으므로 이 질문을 학습 곡선으로 추측하지 않는다 |
| `MLAgents/GraspLift/Tests/PlayMode/GraspLiftHandGeometryProbe.cs` | 합격/불합격이 아니라 **측정 도구**. 손을 닫았을 때 손끝이 실제로 어디 가는지 재서 블록 크기를 URDF 계산이 아닌 시뮬 실측으로 정한다 |
| `training/tests/test_*.py` | 파이썬 스크립트와 과거 behavior 계약의 회귀 테스트 |

## 7. 코드 레벨 핵심 — 관찰 57칸·행동 7칸의 실제 내용

"관찰 57개"라는 숫자만으로는 실물 이관도, 모델 호환 판정도 못 한다. 아래가 그 57칸의 실제 배치다.
정본은 `Runtime/Dg5fPicknPlaceAgent.cs`의 `CollectObservations`이며, 값은 전부 정규화·클램프된다.

### 7-1. 관찰 벡터 배치 (인덱스 → 내용)

| 인덱스 | 내용 | 정규화 방식 |
|---|---|---|
| `0..5` | 팔 6관절 실제각 | `ArmSafeMin/MaxDeg` 범위를 −1~+1로 |
| `6..11` | 팔 6관절 각속도 | `rad/s ÷ π`, ±1 클램프 |
| `12` | 손 폐합률(closure) | `closure*2−1` (0~1 → −1~+1) |
| `13..15` | **파지 목표점 − 손 grasp point** (로봇 베이스 좌표) | ÷1.0 m |
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

씬 참조(`cubeTarget`·`robotBase`·`palm`·`graspPoint`·`fingerTips`·`contactSensors`) 중 하나라도 없거나
물리값이 NaN/∞이면 **57칸 전부 0을 넣고 빠져나온다.** 학습이 안 되는데 에러도 없으면 이 경로를 의심한다.

⚠️ 관찰은 **모두 시뮬레이터 내부 상태**다. `13..21`(물체 위치·속도)과 `38..42`·`49`(접촉)는
실물에 대응 신호가 없어, 실물 이관 시 이 칸들을 어디서 채울지가 남은 과제다.

### 7-2. 행동 벡터와 그 스케일

`OnActionReceived(ActionBuffers)` — 연속 7개, 각 −1~+1로 클램프된다.

- `[0..5]` 팔 6축의 **각도 증분**. 실제 증분 = `action × MaxDegPerSec[i] × TrainingSpeedFraction(0.5) × 결정주기`.
  결정주기는 `DecisionRequester.DecisionPeriod`(씬 빌더가 5로 설정) × `fixedDeltaTime`(0.02s) = **0.1초**.
  즉 관절 0은 한 결정에 최대 `120 × 0.5 × 0.1 = 6°` 움직인다. 관절마다 상한이 다르다는 점이 핵심이다.
  물체 0.08 m 이내(`NearObjectControlClearance`)에선 `NearObjectArmDeltaScale = 0.35`가 곱해져 미세동작이 된다.
- `[6]` 손 개폐 증분. `gripDeltaPerDecision = 0.08`을 곱해 폐합률 0~1을 이동시키고,
  `ApplyGripTargets()`가 "펴진 자세 ↔ `RightFistDeg`" 사이를 스칼라 하나로 보간해 20관절에 쓴다.
- `DecisionRequester`가 씬에 없으면 결정주기를 1스텝으로 가정해 **의도보다 5배 느리게 움직이고 경고만 찍는다.**

### 7-3. 성공·실패 판정의 실제 상수 (`Dg5fPicknPlaceSpec`)

`SpecVersion = "3.0.0"`, `BehaviorName = "DG5FPicknPlace"`, `ObservationSize = 57`, `ActionSize = 7`.

| 판정 | 함수 | 상수 |
|---|---|---|
| 파지 후보 | `IsGraspCandidate(...)` | 접촉 ≥`GraspContactMinimum`(3), 최대 대향각 ≥`GraspOppositionAngleDeg`(90°), 접촉중심-물체중심 ≤`GraspCenterMaxDistance`(0.05 m), 폐합률 ≥`MinimumGraspClosure`(0.30) |
| 파지 확정 | `IsGraspConfirmed(sec)` | 후보 상태를 `GraspConfirmSeconds`(0.30초) 유지 → +`GraspConfirmReward`(1.0) |
| 안정 리프트 | `IsStableLift(h, speed)` | 목표 높이 도달 + 물체 속도 ≤`LiftMaximumSpeed`(0.50 m/s) |
| 성공 | `IsLiftComplete(sec)` | 안정 리프트를 `CurrentLiftHoldSeconds` 유지 → +`LiftSuccessReward`(5.0) |
| 타임아웃 | `ReachedEpisodeTimeout` | `EpisodeTimeoutSeconds`(20초) |

**커리큘럼(`grasp_stage` 1/2/3)이 바꾸는 값** — `CurrentLiftTargetHeight` 5/8/**10 cm**,
`CurrentLiftHoldSeconds` 0.25/0.35/**0.50초**, 스폰 반경 `CurrentMinimum/MaximumSpawnRadius`
(최종 0.37~0.58 m 환형).

**실패 사유 문자열과 페널티** (`FailurePenalty(reason)`):
`UnsafeSurfaceContact` −2.0 / `SelfCollision` −2.0 / `Dropped` −1.0 / `ObjectOutOfBounds` −1.0 /
`ObjectPushedAway` −0.5 / `ObjectToppled` −0.3. 이 문자열이 그대로 TensorBoard `Failure/<reason>` 태그가
되므로, **모니터에서 보이는 태그 이름과 코드가 같은 문자열**이다.

**지속 페널티**: 결정마다 `DecisionTimePenalty`(−0.001), 행동 급변 `ActionRatePenaltyScale`(−0.001),
물체 근처 행동 크기 `NearObjectActionPenaltyScale`(−0.002), 손이 바닥 긁음
`HandSurfacePenaltyPerSecond`(−0.05/초), 엄지가 아래를 향함 `ThumbDownPenaltyScale`(−0.05),
든 물체 기울어짐 `LiftTiltPenaltyScale`(−0.02, 10° 이하 무료·30°에서 포화).

> 페널티 설계 규칙(코드·YAML 주석에 근거가 적혀 있다): **한 에피소드 전체를 최대 비용으로 채워도
> 리프트 성공 1회의 보상을 넘지 않아야 한다.** 2026-08-28에 −0.10짜리 엄지 페널티가
> 200결정 × −0.10 = −20으로 최대 획득 가능 보상(+12.2)을 압도해 학습이 정지 정책으로
> 수렴한 사고가 이 규칙의 출처다.

### 7-4. YAML이 갈아끼울 수 있는 파라미터 이름

`environment_parameters`에 이 이름으로 적으면 `Set*Parameter` 계열이 런타임에 받는다.
**여기 없는 상수는 재컴파일·재빌드를 해야 바뀐다.**

`grasp_stage` · `cube_width` · `cube_height` · `cube_com_height_fraction` · `topple_limit_deg` ·
`topdown_potential_max` · `action_rate_penalty_scale` · `hand_surface_penalty_per_second` ·
`grasp_posture_penalty_scale` · `thumb_down_penalty_scale` · `lift_tilt_penalty_scale`

### 7-5. TensorBoard 태그 — 무엇을 보면 되나

`Dg5fPicknPlaceAgent.RecordOutcome()`이 에피소드마다 기록한다.

- `PicknPlace/Success`, `GraspConfirmed`, `ContactCount`, `BestLiftHeight`, `FinalLiftHeight`,
  `FinalDistanceMeters`, `GraspSeconds`, `LiftHoldSeconds`, `CompletionSeconds`, `FinalClosure`
- 자세·품질: `TopDownAngleDegrees`, `MaxPalmFacingAlignment`, `ThumbBelowOtherTipsMeters`,
  `GraspPostureAngleDegrees`, `ObjectTiltDegrees`, `MaxObjectTiltDegrees`, `MeanArmActionRate`,
  `HandSurfaceContactSeconds`
- 커리큘럼: `Curriculum/GraspStage`, `Curriculum/CubeWidth`, `Curriculum/CubeHeight`
- 실패: `Failure/<reason>` (합계)

`picknplace_monitor.py --gate`가 판정하는 **4개 게이트**(`GATES` 상수, 근거는 `docs/TRAINING_RUN_LEDGER.md`):

| 게이트 | 스텝 | 태그 | 최소 | 못 넘기면 |
|---|---|---|---|---|
| G1 접근 | 300k | `MaxPalmFacingAlignment` | >0.0 | 접근 그래디언트 자체가 없음 = 정지 정책 데드락 |
| G2 접촉 | 800k | `ContactCount` | >0.20 | 파지 학습이 시작조차 안 됨 |
| G3 파지 | 2M | `GraspConfirmed` | >0.05 | 파지 계약이 이 손·큐브 조합에서 성립 안 함 |
| G4 성공 | 4M | `Success` | >0.10 | 남은 스텝으로 뒤집히지 않음 |

`--gate` 실패 시 **종료코드 1**만 돌려준다. 학습 프로세스를 죽이지는 않는다.

### 7-6. 학습 실행의 실제 인자

`train_picknplace.py`는 `mlagents_learn_compat.py`를 엔트리포인트로 `mlagents-learn`을 부른다.

| 인자 | 기본값 | 출처 |
|---|---|---|
| `--run-id` | **필수** | — |
| `--config` | `training/config/dg5f_picknplace.yaml` | |
| `--num-envs` | `.env`의 `RTAUTO_TRAIN_NUM_ENVS` | 동시 플레이어 수 |
| `--base-port` | 5100 | `cfg.PORT_MLAGENTS_BASE` |
| `--results-dir` | `training/results` | `cfg.TRAINING_RESULTS_DIR` |
| `--editor` | off | 플레이어 대신 Unity 에디터에 붙는다 |
| `--resume` / `--force` / `--dry-run` / `--timeout-wait`(600) | | |
| `--keep-stale-players` | off | 기본은 **남아 있는 플레이어 프로세스를 먼저 죽인다** |

총 에이전트 수 = `DG5F_PICKNPLACE_TRAINING_AREAS`(빌드에 구워진 값, 기본 40) × `--num-envs`.
**영역 수는 플레이어 빌드에 고정**되므로 `.env`만 고쳐선 안 바뀐다(씬 재생성 → 재빌드 필요).

현역 학습 설정(`dg5f_picknplace.yaml`)의 핵심: PPO, `batch_size 4096` / `buffer_size 40960` /
`num_epoch 3` / `learning_rate 3e-4 linear` / `hidden_units 256` × `num_layers 3` /
`gamma 0.995`(리프트 보상이 파지 후 최대 10초 뒤에 오므로 길게) / `time_horizon 256` /
`max_steps 20M` / `normalize false` / `device cuda`.
`num_envs` 10은 측정값이다 — 4/6/8/10/12 envs에서 1643/1932/2206/2390/2266 steps/s로
10 부근에서 처리량이 꺾인다(8코어를 트레이너와 다투기 시작).

### 7-7. 접촉 센서의 구현 차이

| 센서 | 판정 방식 | 노출 |
|---|---|---|
| `PicknPlaceObjectContactSensor` | `OnCollisionEnter/Stay/Exit`, `targetCollider`와의 접촉만 | `IsTouching`, `LastImpulse`, `contactIndex`(손끝 0~4, 손바닥 5) |
| `PicknPlaceSurfaceContactSensor` | 팔 링크의 바닥 충돌 → `agent.NotifyUnsafeSurfaceContact()` | 즉시 실패 종료 |
| `PicknPlaceHandSurfaceSensor` | 손의 바닥 접촉 **시간**을 누적 | 실패가 아니라 초당 감점 |
| `PicknPlaceSelfCollisionSensor` | **`OnTriggerEnter/Stay`** — 물리 충돌을 켜면 진동이 생기므로 트리거 전용 그림자 콜라이더로 겹침만 감지 | `HasViolation`, `IsSelfCollision(a,b)` |

에피소드 시작마다 `ResetContacts()`로 초기화한다 — 새 센서를 추가하면 이 호출도 함께 넣어야 한다.
