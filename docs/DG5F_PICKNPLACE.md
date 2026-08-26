# DG5F Pick + Place (`DG5FPicknPlace`)

`Assets/MLAgents/picknplace`의 설계 근거. 아키텍처·보상 셰이핑의 원조는
[`docs/DG5F_GRASP_LIFT.md`](DG5F_GRASP_LIFT.md) — 이 문서는 GraspLift 대비
**무엇이, 왜 달라졌는지**만 다룬다.

> 이 문서는 2026-08-26에 두 번 갱신됐다. 1차 버전(§1 참고)은 FOUP 손잡이를
> 직접 잡는 태스크였다. 착수 직후 방향을 바꿔 지금 구현(§2 이후)은 **큐브를
> 바닥에서 집어 FOUP 형태 고정 플랫폼 위 랜덤 지점에 내려놓는 진짜
> pick-and-place**다. 1차 버전의 설계 기록은 git 이력에 남아있으니 필요하면
> 참고하되, 현재 코드와는 대부분 무관하다.

## 왜 새 behavior인가

`DG5F_GraspLiftTraining.unity`는 UR5e + DG5F **왼손** + 사각기둥 목표물로
구현돼 있다. 확정된 하드웨어는 UR16e + DG5F **오른손**이고, 여기에 더해
사용자가 요청한 것은 place까지 포함한 진짜 pick-and-place다. GraspLift는
"파지+들어올려 유지"까지만 다루고 place가 없다.

## 큐브(픽) + FOUP 플랫폼(플레이스) — 역할 분리

- **픽 대상**: 일반 큐브. GraspLift의 `BlockWidth`/`BlockHeight` 기본값과
  **완전히 동일한 지오메트리**(0.035 × 0.12 × 0.035 m)를 그대로 재사용한다.
  `GraspLiftHandGeometryProbe`가 실측 검증한 손 오포지션 아퍼처(3.1-3.6 cm)에
  맞춰진 값이라, 접근·정렬·파지·대향각/케이지 판정 로직 전부를 거의 그대로
  포팅했다 — 이 절반은 실제 학습으로 검증된 코드다.
- **플레이스 목표**: FOUP 형태(박스 몸체 + 상단 손잡이) 고정 플랫폼. **더 이상
  잡는 대상이 아니다** — `Rigidbody`가 없는 완전히 정적인 오브젝트로, 매
  에피소드 절대 움직이지 않는다. 손잡이는 순수 장식(시각적으로 FOUP처럼
  보이게 하는 용도)이고 파지 판정과는 무관하다.
- 매 에피소드: 큐브는 바닥의 랜덤 위치(플랫폼 풋프린트를 피해서)에 스폰되고,
  플랫폼 윗면 위의 랜덤 지점(마커)이 새로 선택된다. 로봇은 큐브를 집어
  플랫폼 위로 옮기고, 마커 위치에 정확히 내려놓아야 한다.

## 태스크 단계 (에이전트 상태 기계)

`Dg5fPicknPlaceAgent`는 세 단계로 진행한다:

1. **접근(Approaching)** — GraspLift와 동일한 포텐셜 기반 셰이핑(거리
   포텐셜, 정밀 접근, top-down 정렬, 그립 클로저, 접촉/대향각/케이지 판정).
   `_graspConfirmed`가 될 때까지.
2. **운반(Carrying)** — `_graspConfirmed` 이후. 큐브가 향해야 할 지점을
   동적으로 계산한다: 마커 위 수평 정렬(`ArrivalXZToleranceMeters` 이내) +
   호버 높이(`TransportClearanceHeight`) 도달 전까지는 "마커 위 호버 지점"을
   향하고, 도달(sticky 플래그 `_hasArrivedAboveMarker`)한 뒤에는 목표가
   "마커 자체(플랫폼 윗면 높이)"로 낮아진다. 이 2단 웨이포인트 덕분에 큐브를
   플랫폼 옆면으로 밀어붙이지 않고 위로 넘겨서 내리도록 유도한다.
   포텐셜 함수(`TransportPotential`)는 GraspLift의 `ApproachPotential`과 같은
   plain-delta 방식이라 보상 파밍이 불가능하다.
3. **배치(Placing)** — 손을 놓았을 때(`IsGraspCandidate`가 더 이상 참이 아닐
   때) 큐브가 마커 위치·플랫폼 높이·저속·직립 조건(`IsAtRestOnTarget`)을
   모두 만족하면 정착 타이머(`_settleSeconds`)가 돌기 시작한다.
   `PlaceSettleSeconds`(0.5 s) 동안 유지되면 성공. **별도의 "놓기" 액션은
   없다** — 기존 그립 클로저 연속 액션을 0으로 낮추는 것 자체가 놓는 행동이라,
   정책이 "마커 위에서 손을 펴는" 것을 스스로 학습해야 한다.
   손을 놓았는데 목표 위치가 아니면(`IsAtRestOnTarget`이 거짓) 기존
   GraspLift의 Dropped 판정과 동일한 grace-then-height-regression 로직으로
   실패 처리된다 — 단, 기준이 "스폰 높이 대비 리프트량"이 아니라 "바닥 기준
   절대 높이"로 바뀌었다(목적지 높이가 스폰 높이와 다르므로).

## Observation/Action shape

- `ObservationSize = 63`, `ActionSize = 7` — GraspLift/1차 PicknPlace의
  57/7에서 관측이 늘었다. 0..48번 슬롯은 GraspLift와 동일한 의미(팔 관절
  위치/속도, 손 클로저, 목표 상대 위치/속도/각속도, 손끝 상대 위치, 접촉
  플래그, 팔 타겟)를 유지한다. 49번 이후가 새로운 place 상태
  (`Dg5fPicknPlaceAgent.CollectObservations`의 슬롯별 주석 참고): 접촉/파지
  진행도, 큐브→마커 상대 벡터, 수평 정렬·수직 클리어런스 진행도, 도착/정착
  플래그, 정착 진행도, 에피소드 진행도.
- observation 크기가 바뀌었으므로 GraspLift의 `DG5FGraspLift.onnx`를
  `--initialize-from`으로 이어받을 수 없다 — 처음부터 학습한다(config의
  `max_steps`를 GraspLift보다 늘린 이유이기도 하다).

## GraspLift 대비 바뀐/새 상수 (근거)

| 상수 | 값 | 이유 |
|---|---|---|
| `EpisodeTimeoutSeconds` | 35 s | 운반+배치 단계가 추가돼 접근+파지만 있던 GraspLift(20s)보다 김 |
| 큐브 스폰 annulus | 0.37-0.58 m | GraspLift와 완전히 동일 — 같은 지오메트리라 재검증 불필요 |
| `PlatformLocalPosition` | (0.60, h/2, 0) 고정 | 리치(0.90m) 안, 큐브 spawn annulus와 분리 가능한 위치 |
| `PlatformExclusionRadius` | 0.30 m | 큐브가 플랫폼 풋프린트(대각선 절반 ~0.21m)와 겹치지 않도록 |
| `ToppleLimitDegrees` | 45° | 1차 버전의 15°(웨이퍼 가정)에서 되돌림 — 이제 일반 큐브라 GraspLift 기준이 맞음 |
| `TransportPotentialMaximum` | 2.0 | GraspLift의 `LiftPotentialMaximum`을 대체하는 새 지배적 셰이핑 항 |
| `PlaceSuccessReward` | 6.0 | GraspLift의 `LiftSuccessReward`(5.0)보다 큼 — 배치까지가 최종 목표라서 |
| `LiftClearanceReward` | 1.0 (1회성) | "일단 들어올렸다"는 중간 마일스톤, 최종 보상과 분리 |

바뀌지 않은 것(GraspLift에서 그대로 재사용, 근거는 `Dg5fGraspLiftSpec.cs`
원본 주석 참고): 접근/정렬 포텐셜, 그립 개폐 곡선, 접촉/대향각/케이지 판정,
팔 관절 안전 범위, 오른손 파지 포즈(`RightFistDeg`, 미러 재구성 근거는
`Dg5fPicknPlaceSpec.cs` 주석 및 로드맵 "오른손 파지 포즈는 되돌리면 나온다"
절 참고).

## 커리큘럼

- `pick_stage` (1..3): 큐브 스폰 annulus를 좁은 범위→전체 범위로 확장.
  GraspLift의 `grasp_stage`와 동일한 패턴.
- `place_stage` (1..3): 마커 랜덤화 범위(`MarkerRangeMeters`)와 배치
  허용오차(`PlacePositionToleranceMeters`)를 함께 조인다 — 초반엔 플랫폼
  중앙 근처에 넉넉한 허용오차로, 후반엔 전체 윗면에 3cm 정밀도로.

## 미착수·재검증 필요 항목

- 팔 xDrive 게인, `ArmSafeMinDeg/MaxDeg`의 한 코너 — GraspLift 단계부터
  이어지는 UR16e 재검증 미착수 항목(`docs/SIM2REAL_ROADMAP.md` Phase 2).
- 플랫폼/큐브 위치가 로봇 워크스페이스 안에서 실제로 도달 가능하고 서로
  겹치지 않는지는 좌표 계산으로만 확인했다 — Unity Editor에서 실제 Play로
  씬을 돌려봐야 확정된다.
- `TransportClearanceHeight`(0.08m), `ArrivalXZToleranceMeters`(0.05m),
  `PlaceSettleSeconds`(0.5s) 등 새 셰이핑 상수는 전부 초기 추정값이라 실제
  학습 곡선을 보고 튜닝이 필요하다(GraspLift의 여러 상수들이 실측 후
  수정됐던 것과 같은 과정).

## 실행

Unity 메뉴 순서와 `mlagents-learn` 실행 명령은
[`training/README.md`](../training/README.md)의 "DG5F Pick + Place" 절 참고.
