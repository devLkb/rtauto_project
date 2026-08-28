# DG5F Pick + Place → Grasp + Lift (`DG5FPicknPlace`)

`Assets/MLAgents/picknplace`의 설계 근거. 아키텍처·보상 셰이핑의 원조는
[`docs/DG5F_GRASP_LIFT.md`](DG5F_GRASP_LIFT.md) — 이 문서는 GraspLift 대비
**무엇이, 왜 달라졌는지**만 다룬다.

> **2026-08-27 갱신: place 단계를 되돌렸다.** 이 문서는 2026-08-26에 두 번
> 갱신됐다(§1은 FOUP 손잡이를 직접 잡는 태스크, §2 이후는 큐브를 집어 FOUP
> 형태 고정 플랫폼 위 랜덤 지점에 내려놓는 진짜 pick-and-place). 둘 다
> **현재 코드와 무관하다** — 확정 하드웨어(UR16e+오른손) 위에서 grasp+lift부터
> 먼저 다지는 편이 지금 시점에 더 값지다고 판단해 place(운반+배치) 단계를
> 하루 만에 다시 뺐다. 아래 §2~4는 이제 **grasp+lift만** 다루는 내용으로
> 갱신됐고, place 관련 서술(플랫폼·마커·운반·배치 판정)은 git 이력에서만
> 찾을 수 있다.

## 왜 새 behavior인가

`DG5F_GraspLiftTraining.unity`는 UR5e + DG5F **왼손** + 사각기둥 목표물로
구현돼 있다. 확정된 하드웨어는 UR16e + DG5F **오른손**이다. 이 behavior는
GraspLift의 "파지+들어올려 유지" 태스크를 확정 하드웨어로 그대로 포팅한
것 — 물리 로직·보상 셰이핑·커리큘럼 구조는 GraspLift와 사실상 동일하고,
바뀐 것은 로봇 프리팹(UR16e+오른손)과 오른손 파지 포즈(`RightFistDeg`,
미러 재구성)뿐이다.

## 큐브(파지 대상)

일반 큐브. GraspLift의 `BlockWidth`/`BlockHeight` 기본값과 **완전히 동일한
지오메트리**(0.035 × 0.12 × 0.035 m, 즉 12cm 사각기둥)를 그대로 재사용한다.
`GraspLiftHandGeometryProbe`가 실측 검증한 손 오포지션 아퍼처(3.1-3.6 cm)에
맞춰진 값이라, 접근·정렬·파지·대향각/케이지 판정·리프트 로직 전부를 거의
그대로 포팅했다 — GraspLift 절반은 실제 학습으로 검증된 코드다. 매 에피소드
큐브는 바닥의 랜덤 위치에 스폰되고, 로봇은 큐브를 집어 목표 높이까지
들어올려 유지해야 한다.

## 태스크 단계 (에이전트 상태 기계)

`Dg5fPicknPlaceAgent`는 GraspLift와 동일한 두 단계로 진행한다:

1. **접근(Approaching)** — 포텐셜 기반 셰이핑(거리 포텐셜, 정밀 접근,
   top-down 정렬, 그립 클로저, 접촉/대향각/케이지 판정). `_graspConfirmed`가
   될 때까지.
2. **리프트(Lifting)** — `_graspConfirmed` 이후. 큐브를 스폰 높이 대비
   `CurrentLiftTargetHeight`(커리큘럼에 따라 5/8/10 cm)까지 들어올려
   `CurrentLiftHoldSeconds` 동안 저속으로 유지하면 성공. 손을 놓치면(grace
   구간 후 높이가 최고치의 30% 밑으로 떨어지면) `Dropped`로 실패 처리된다 —
   GraspLift와 완전히 동일한 grace-then-height-regression 로직.

## Observation/Action shape

- `ObservationSize = 57`, `ActionSize = 7` — GraspLift와 완전히 동일한 슬롯
  구성. 0..48번 슬롯은 팔 관절 위치/속도, 손 클로저, 목표 상대 위치/속도/
  각속도, 손끝 상대 위치, 접촉 플래그, 팔 타겟. 49..56번은 접촉/파지/리프트
  진행도, 리프트 유지 진행도, 접근 거리, 에피소드 진행도
  (`Dg5fPicknPlaceAgent.CollectObservations`의 슬롯별 주석 참고).
- observation 크기가 GraspLift와 동일하므로, 원한다면 GraspLift의
  `DG5FGraspLift.onnx`를 `--initialize-from`으로 이어받는 것도 이론상
  가능하다(팔/손 관절 이름 매핑이 달라 실제로는 검증 필요 — 아직 시도 안 함).

## GraspLift 대비 바뀐 것

로봇 프리팹(`ur16e_dg5f_right.prefab`), 손 이름공간(`rl_dg_*`), 파지 포즈
(`RightFistDeg`, 미러 재구성 근거는 `Dg5fPicknPlaceSpec.cs` 주석 참고),
behavior 이름(`DG5FPicknPlace`)뿐이다. 보상 상수·커리큘럼 임계값·워크스페이스
치수는 전부 GraspLift와 동일한 값을 그대로 가져왔다(`Dg5fGraspLiftSpec.cs`
원본 주석에 각 상수의 근거가 있다).

또한 GraspLift에 없던 안전 제약 2개가 이 behavior에만 추가됐다
(2026-08-27, headless 학습 착수 전 요청 반영):

- **자기충돌 방지**: `PicknPlaceSelfCollisionSensor` — 손가락끼리, 또는
  팔/손이 서로 다른(직접 연결되지 않은) 링크와 접촉하면 `UnsafeSurfaceContact`
  와 동일한 심각도(-2.0)로 에피소드를 즉시 종료한다. `RobotSelfCollisionIgnore`
  가 로봇 전체 콜라이더 쌍의 물리 충돌 반응을 이미 꺼두고 있어(지골 겹침으로
  인한 접촉 진동 방지, 그 컴포넌트 주석 참고) `OnCollisionEnter`를 재사용할 수
  없다 — 대신 각 물리 콜라이더 옆에 같은 모양의 **트리거 전용 섀도 콜라이더**를
  추가해 물리 반응은 건드리지 않고 겹침만 감지한다(`Physics.IgnoreCollision`은
  트리거 콜백을 막지 않음). "자기충돌"의 정의는 두 콜라이더의 소유
  ArticulationBody가 같지 않고 부모-자식(관절로 직접 연결)도 아닌 경우 —
  인접 링크의 설계상 겹침(지골끼리, 손목-손마운트)은 정상으로 제외된다.
  `PicknPlaceTrainingSceneBuilder.ConfigureSelfCollisionSensors`/
  `AddTriggerShadow` 참고.
- **엄지 방향 제약**: 손끝(`fingerTips[0]`, finger index 1 = 엄지)에서 기저
  관절(`_handJoints[0]`)로의 벡터를 "엄지가 가리키는 방향"으로 근사해(URDF
  임포트 로컬 축 관례를 모르는 상태에서도 안전한, 위치 기반 근사)
  `TopDownAlignment`/`TopDownAngleDegrees`를 재사용, 바닥 방향(0°)에 가까울수록
  커지는 연속 페널티(`ThumbDownPenalty`)를 매 결정마다 부과한다. 60° 안쪽은
  무료, 기본 스케일 -0.10(환경 파라미터 `thumb_down_penalty_scale`로 조정
  가능). `GraspPosturePenaltyScale`(기본 0, 꺼짐)과 달리 이 페널티는 **기본
  켜짐** — 실험적 스윕이 아니라 이번 학습에서 요구된 하드 제약이기 때문.
  각도 임계값·스케일 모두 초기 추정값이라 실제 학습 곡선을 보고 재조정이
  필요할 수 있다.

  > **2026-08-28 재조정 — 기본 스케일이 보상 예산을 압도했다.** `DecisionPeriod`
  > 가 5(0.1초)이고 `EpisodeTimeoutSeconds`가 20초라 에피소드는 약 200 결정이다.
  > 즉 기본 스케일 -0.10은 에피소드당 최대 **-20.0**인데, 이 태스크가 줄 수 있는
  > 양의 보상 총합은 최대 약 **+12.2**다(접근 2.5 + top-down 0.3 + 클로저 1.0 +
  > 접촉 0.4 + 파지 1.0 + 리프트 포텐셜 2.0 + 성공 5.0). 셰이핑 항 하나가 태스크
  > 보상 전체보다 크면 자세를 다듬는 게 아니라 **"가만히 있기"와 "안전
  > 페널티(-2.0)로 자진 종료하기"가 최적 정책**이 된다 — `Dg5fPicknPlaceAgent`의
  > 2026-08-27 진단 주석이 기록한 "움직임 거의 0으로 수렴, ContactCount 200만
  > 스텝 내내 평탄" 증상과 정확히 맞는다. `training/config/dg5f_picknplace.yaml`의
  > 환경 파라미터 `thumb_down_penalty_scale: -0.01`로 상한을 -2.0(종료 페널티와
  > 같은 자릿수)까지 낮췄다. **제약 자체는 그대로다 — 가중치만 바꿨다.** C# 기본값을
  > 안 건드린 이유는 이 값을 스윕 가능한 손잡이로 남겨두기 위해서다(같은 상수를
  > 두 곳에 적지 않는다, 원칙 1). 이 재조정이 실제로 효과가 있었는지는
  > [`docs/TRAINING_RUN_LEDGER.md`](TRAINING_RUN_LEDGER.md)의 런 원장에서 확인할 것.

## 커리큘럼

`grasp_stage` (1..3): 큐브 스폰 annulus를 좁은 범위→전체 범위로, 리프트
목표 높이/유지시간을 5cm·0.25s → 8cm·0.35s → 10cm·0.5s로 함께 조인다.
GraspLift의 `grasp_stage`와 완전히 동일한 패턴.

## 미착수·재검증 필요 항목

- 팔 xDrive 게인, `ArmSafeMinDeg/MaxDeg`의 한 코너 — GraspLift 단계부터
  이어지는 UR16e 재검증 미착수 항목(`docs/SIM2REAL_ROADMAP.md` Phase 2).
- 큐브 스폰 위치가 로봇 워크스페이스 안에서 실제로 도달 가능한지는 좌표
  계산으로만 확인했다 — Unity Editor에서 실제 Play로 씬을 돌려봐야 확정된다.

## Place(운반+배치)로 다시 확장할 때

Phase 4(웨이퍼 케이스 재타겟, `docs/SIM2REAL_ROADMAP.md` §8)에서 실제 FOUP
스펙이 도착하면 place 단계를 다시 붙인다. 2026-08-26에 한 번 구현했던
플랫폼+마커+운반+배치 설계(포텐셜 함수, 도착/정착 판정, 관련 상수)는 git
이력에 남아있으니 그때 참고할 것 — 그대로 되살리기보다는 실제 웨이퍼 스펙
(치수·허용오차·파지 방식)에 맞춰 다시 설계해야 한다는 점은 로드맵 §8에
이미 정리돼 있다.

## 실행

Unity 메뉴 순서와 `mlagents-learn` 실행 명령은
[`training/README.md`](../training/README.md)의 "DG5F Grasp + Place 인프라,
현재는 Grasp + Lift" 절 참고. 장시간 학습은 그 절의 **"headless 학습"**
경로(빌드된 플레이어 + `--no-graphics`)를 쓴다 — Editor에 붙이는 방식은
확인용이다.

## 런 판정·격리

학습 런의 진행 판정(게이트 G1~G4), 실패 런 격리 규칙(`training/results/failure/`,
`.../legacy/`), 이 behavior가 지금까지 빠졌던 실패 양상 목록은
[`docs/TRAINING_RUN_LEDGER.md`](TRAINING_RUN_LEDGER.md)가 정본이다. 새 런을
시작하거나 끝낼 때마다 그 문서의 원장 표를 갱신한다.
