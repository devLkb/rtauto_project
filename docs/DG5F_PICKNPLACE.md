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
현재는 Grasp + Lift" 절 참고.
