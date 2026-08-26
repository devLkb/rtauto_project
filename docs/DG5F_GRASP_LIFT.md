# DG5F Grasp + Lift (behavior `DG5FGraspLift`)

`Grasp` 브랜치의 파지·들어올리기 학습 구현. 요구사항은
[`docs/GraspClaude.md`](GraspClaude.md), 참고 설계는 Isaac Lab
[`VAlikV/IsaacLab_delto_envs`](https://github.com/VAlikV/IsaacLab_delto_envs)
(`envs/tesolo_delto_UR_env/delto_env.py`).

Isaac Lab 구현에서 가져온 것은 **설계 의도뿐**이다. 코드는 Unity 물리 /
ML-Agents 구조에 맞게 전부 새로 작성했다.

| Isaac Lab | 우리 구현 | 비고 |
|---|---|---|
| `grasp_contact_min = 3` | `GraspContactMinimum = 3` | 동일한 근거(3점 이상이어야 케이지) |
| `_force_closure_score` (쌍별 각도) | `MaximumOppositionAngleDegrees` + `IsForceClosureLike` | O(n²) 각도 계산은 동일, sigmoid score 대신 임계 판정 |
| `grasp_max_dist` (COM ↔ 파지중심) | `GraspCenterMaxDistance` | 동일 개념 |
| `grasp_hold_steps = 20` | `GraspConfirmSeconds = 0.3 s` | step이 아니라 시뮬레이션 시간 기준 |
| 스크립트 lift (`lift_delta_deg` 보간) | **없음** — 정책이 직접 팔을 올린다 | 스크립트 상승은 "파지 후 들어올리기"를 학습시키지 못한다 |
| `success_height = 0.12` | `LiftTargetHeight = 0.10` (커리큘럼 0.05→0.10) | |
| `slip_grace = 10 steps` | `SlipGraceSeconds = 0.20 s` | |
| `tilt_fail_deg` 종료 | `ObjectToppled` (`ToppleLimitDegrees = 45°`, −0.3) | 파지 확정 전 전도만 종료하며 `topple_limit_deg`로 조정 |
| 실린더 Ø0.06 × 0.15 m | Cube 0.035 × 0.12 × 0.035 m | 아래 "학습 Object" 참고 |

---

## 결과 — 0.09 m Grasp + Lift 기준선

학습 run `dg5f_grasp_lift_stability_5m`은 3.2M step에서 수렴을 확인하고
중단했다. 두 curriculum은 모두 마지막 lesson에 도달했다:
`block_com_height_fraction = 0.30`, `grasp_stage = 3`(10 cm lift를 0.5 s
유지). 학습 중 3.075M step 측정값은 다음과 같다.

| stat | 값 |
|---|---:|
| `GraspLift/Success` | **0.987** |
| `GraspLift/GraspConfirmed` | 0.998 |
| `GraspLift/FinalLiftHeight` | 0.142 m |
| `GraspLift/LiftHoldSeconds` | 0.496 s (요구 0.50 s) |
| `Failure/ObjectToppled` | 5000-step window당 1.2 |
| `Failure/Dropped` | 1.4 |

학습 경로는 **0%**(앞선 6개 run, 합계 약 1.9M step) → **3.3%**(390k) →
**60%**(780k) → **98.7%**(3.075M)였다. 즉 전도 local optimum 제거와 단계적
난이도 복원이 실제 성능 상승으로 이어졌고, 중간 수치가 아래 설계 결정의
근거다.

이 절에서 평가한 당시 배포 모델은
`unity/Assets/MLAgents/GraspLift/Models/DG5FGraspLift.onnx`이며 checkpoint
`DG5FGraspLift-3199988`과 동일하다. SHA-256은
`6e3eab478cfa95f1a9670db007a9fbddcdb65f00212b03b72371915de2137a66`이다.
이후 0.12 m policy가 같은 경로의 배포 모델을 대체했으며, 오늘의 top-down
fine-tune 후보는 그 모델을 대체하지 않았다. 모델은
`GraspLiftTrainingArea.prefab`에 연결되고 scene의 20개 학습 area가 이
prefab 설정을 상속한다. 이 연결은 한동안 저장소의 HEAD에서 빠져 있었지만
현재는 builder가 배포 ONNX를 직접 할당하며, 20개 area 모두의 model non-null /
`DeterministicInference = true` / behavior name을 PlayMode test가 검증한다
(아래 8절).

당시 배포 정책을 학습 조건에서 `--resume --inference`로만 실행한 control
evaluation(학습 없음)도 결과를 재현했다.

| 조건/config | Success | GraspConfirmed | FinalLiftHeight | Failure/ObjectToppled |
|---|---:|---:|---:|---:|
| COM 0.30 (학습 조건, 전도각 약 33°) / `dg5f_grasp_lift_eval_com030.yaml` | 0.9895 | 0.9939 | 0.142 m | 1.11 |
| COM 0.50 (균일 밀도, 전도각 약 21°) / `dg5f_grasp_lift_eval_com050.yaml` | **0.9632** | 0.9730 | 0.138 m | 2.43 |

두 평가 모두 `--resume --inference`이므로 학습은 일어나지 않았고, 집계는 정책이
교체된 직후의 전이 구간(첫 두 summary window)을 제외한 값이다. 대조군 n=23,
시험군 n=8 window.

**당시 학습용 무게중심 완화가 결과를 부풀린 것이 아니다.** 무게중심 보정이 전혀 없는
균일 밀도 블록에서도 96.3%이며 하락폭은 2.6%p다. 전도 실패가 1.11 → 2.43으로
두 배 늘어난 것이 하락의 대부분을 설명한다 — 전도각이 33°에서 21°로 좁아졌으니
예상되는 방향이다. 무게중심 커리큘럼은 **학습을 가능하게 하기 위한 장치**였고
최종 정책은 그 장치 없이도 동작한다.

## 1. 왜 새 Behavior인가

기존 `DG5FGrasp`(= `Assets/MLAgents/Grasp`)는 이름과 달리 **파지 전 top-down
접근(pre-grasp reach)만** 학습한다. 손가락 20관절은 정책이 건드리지 않고
prefab의 열린 자세로 고정되며(`enablePolicyClosure = false`), 7번째 action은
호환용으로 무시된다. 성공 조건도 "물체 표면 3 cm 안에서 top-down 자세를
0.3초 유지"까지다.

그 구조 위에 파지를 얹을 수 없는 결정적인 이유가 두 가지 있다.

1. **하강 자체가 실패로 처리된다.** `IsUnsafeLowClearanceMotion` /
   `IsMisalignedDescent`가 패널 10 cm 이내로 내려오는 동작을 중단시키고,
   패널에 닿는 모든 로봇 콜라이더가 `SafetyPenalty(-2)`로 에피소드를 끝낸다.
   파지는 손가락이 테이블 근처까지 내려가야 가능하므로 정반대 계약이다.
2. **손이 정책 제어 대상이 아니다.**

그래서 `Assets/MLAgents/GraspLift/`에 새 Behavior를 만들었다. 기존
`Grasp`/`Reach` 코드는 파이프라인 데모·텔레옵 씬이 계속 쓰므로 **손대지
않았다**.

다만 관측/행동 shape은 **의도적으로 기존과 동일한 57/7**로 맞췄다. 이미
학습된 pre-grasp 정책(25.3° / 69%,
[`DG5F_PREGRASP_ANGLE_RESULT.md`](DG5F_PREGRASP_ANGLE_RESULT.md))을
`--initialize-from`으로 그대로 물려받기 위해서다. CPU 학습 환경에서 접근
단계를 처음부터 다시 배우는 것은 비용이 너무 크다.

---

## 2. 학습 Object — Cube

기존 공(반지름 2 cm)은 DG5F(손가락 길이 ~13 cm)에 비해 너무 작아 안정적인
파지가 불가능하다. `GraspClaude.md`가 허용한 대로 Cube로 교체했다.

> **크기는 추측이 아니라 실측으로 정했다.** 최초 구현은 URDF 산술로 0.055 m를
> 골랐는데, 시뮬레이터에서 닫힌 손을 실제로 재보니 대향 가능 범위 밖이라
> 물리적으로 파지가 불가능했다. 아래 "닫힌 손 실측" 절 참고.

| 항목 | 값 | 근거 |
|---|---|---|
| 크기 | 0.035 × 0.12 × 0.035 m (기본값) | `BlockWidth = 0.035`, `BlockHeight = 0.12`; 폭과 높이는 `block_width` / `block_height` 환경 파라미터로 런타임 변경 가능 |
| Mass | `CurrentBlockMass = 폭²×높이×1800 kg/m³` | `BlockDensity = 1800`; 부피에 비례 — 큰 블록이 자동으로 무거워져 난이도가 실제 물체처럼 스케일된다 |
| Collider | BoxCollider (primitive Cube 기본) | |
| Physics material | staticFriction 1.5 / dynamicFriction 1.2, combine **Maximum** | 참고 구현의 object `static_friction = 2.0`과 같은 의도. 패널은 0.8/Average로 남겨서 "밀면 미끄러지고, 잡으면 안 미끄러지게" 분리 |
| Rigidbody | mass = `CurrentBlockMass`, useGravity, **ContinuousDynamic** | 고정 0.12 kg이 아니며, 손가락이 물리 스텝보다 빠르게 닫힐 때 discrete 검출이 블록을 뚫는 것을 막는다 |
| 초기화 범위 | robot-base local 반경 0.35–0.55 m 환형(면적 균등), Y축 랜덤 yaw, 패널 위 | reach 과제(0.35–0.70)보다 좁힘 — 파지는 난도가 훨씬 높다 |

**단면 0.035 m**: 최초 0.055 m는 DG5F URDF의 검지/중지/약지 knuckle span
약 0.049 m를 근거로 골랐지만, 아래 실측에서 확인된 대향 가능 폭
3.1–3.6 cm보다 넓어 파지가 불가능했다. 현재 기본값 `BlockWidth = 0.035`는
그 실측 범위의 상단에 맞춘 값이다.

**높이 0.12 m**: 손가락이 knuckle부터 ~0.13 m라 납작한 큐브를 테이블 위에
두면 파지 시 손가락이 테이블을 뚫어야 한다. 참고 구현이 굳이 0.15 m 높이
실린더를 쓴 것과 같은 이유다. 0.09 m 기준선에서 확인한 패널 drag를 줄이기
위해 0.12 m를 기본값으로 승격했고, 손이 **윗부분만 공중에서** 감쌀 수 있게
했다.

### 닫힌 손 실측 (`GraspLiftHandGeometryProbe`)

씬을 로드하고 에이전트를 끈 뒤 손만 닫으면서 palm-local 좌표를 측정한 결과:

| closure | fingertip centroid (palm-local) | thumb–index | thumb–middle |
|---|---|---|---|
| 0.00 | (0.017, 0.153, 0.014) | 0.208 m | 0.224 m |
| 0.50 | (0.004, 0.104, 0.090) | 0.045 m | 0.067 m |
| **0.75** | (−0.006, 0.066, 0.075) | **0.036 m** | **0.031 m** |
| 1.00 | (−0.012, 0.049, 0.041) | 0.063 m | 0.046 m |

두 가지가 확정됐다.

1. **대향 가능 폭은 약 3.1–3.6 cm다.** 5.5 cm 블록은 손가락이 마주 볼 수조차 없다.
   따라서 기본 폭을 3.5 cm로 낮추고, `block_width` 파라미터로 실측 비교가 가능하게 했다.
2. **closure 1.0은 0.75보다 나쁜 그립이다.** 완전히 쥐면 손가락이 서로 지나쳐
   간격이 다시 벌어진다(0.036 → 0.063 m). 그래서 폐합 보상을 closure에 단순 비례로
   주면 안 되고, 최적 그립 closure에서 포화시켜야 한다
   (`EffectiveGripClosure`, 아래 Reward 절).

또한 closure 1.0의 centroid (−0.012, 0.049, 0.041)는 설정된 GraspPoint
(0, 0.05, 0.04)와 1.2 cm 차이로, **GraspPoint 위치 자체는 옳았음**이 확인됐다.

### 높이

높이를 처음에 0.12 m로 잡았다가 0.10 m, 다시 0.09 m로 낮춰 기준선을
학습했다. 이후 패널 drag의 geometry 원인을 확인해 기본값을 0.12 m로 다시
승격했다. 아래 전도 분석은 0.09 m 기준선에 대한 기록이다.
0.035 × 0.09 m 블록의 균일 밀도 무게중심은 바닥에서 0.045 m이므로 정적
전도각은 `atan(0.0175/0.045) ≈ 21.3°`에 불과하다. 실제 probe A의
`FinalLiftHeight = −0.0216 m`, `MaxObjectTiltDegrees = 95.1°`는 초기 정책이
블록을 거의 매 에피소드 옆으로 눕혔음을 확인했다.

### 전도 안정성 커리큘럼

형상과 접촉면은 그대로 두고 Rigidbody의 local `centerOfMass`만 아래로
내린다. `block_com_height_fraction`은 블록 바닥에서 잰 높이를 전체 높이의
비율로 표현하며, `0.5`가 균일 밀도다. 아래 curriculum의 당시 목표는
`0.30`이었고 현재 0.12 m 기본 geometry는 `0.20`이다. 정적
전도각은 `atan(폭/2 ÷ COM 높이)`로 계산한다.

| lesson | `block_com_height_fraction` | COM 높이 | 정적 전도각 | 의도 |
|---|---:|---:|---:|---|
| `stable_base` | 0.05 | 0.05×0.09 = 0.0045 m | `atan(0.0175/0.0045) = 75.6°` | 초기 접촉에도 거의 넘어지지 않게 해 파지·상승을 먼저 학습 |
| `semi_stable` | 0.15 | 0.0135 m | `atan(0.0175/0.0135) = 52.4°` | 안정성 보조를 중간 수준으로 제거 |
| `uniform_like` | 0.30 | 0.027 m | `atan(0.0175/0.027) = 33.0°` | probe B와 같은 실제 목표 |

`0.15`의 전도각을 약 49°로 적은 초기 계산은 높이 0.10 m를 사용한 값
(`atan(0.0175/0.015) = 49.4°`)이다. 이 표의 `BlockHeight = 0.09` 기준으로는
52.4°가 맞다.

`topple_limit_deg`는 파지 확정 전 허용 기울기를 정하며 기본값과 장기 학습
설정 모두 45°다(유효 범위 5–180°, 180°는 진단용 비활성화). 기울기가
한계에 도달하면 `ObjectToppled`로 −0.3을 받고 종료한다. 파지 확정 뒤에는
손이 물체를 재배향할 수 있도록 이 판정을 적용하지 않는다.

---

## 3. Observation (57차원)

슬롯 0..48은 reach 체크포인트와 **의미·순서·정규화가 동일**하다(전이 목적).
49..56만 grasp/lift용으로 재정의했다.

| 슬롯 | 개수 | 내용 | 정규화 |
|---|---|---|---|
| 0–5 | 6 | 팔 6관절 각도 | `ArmSafeMin/MaxDeg` → [−1,1] |
| 6–11 | 6 | 팔 6관절 각속도 | /π, clamp |
| 12 | 1 | 손 closure | ×2−1 |
| 13–15 | 3 | (파지 목표점 − graspPoint), robot-base 좌표 | /1.0 m |
| 16–18 | 3 | 블록 선속도, robot-base | /2 m·s⁻¹ |
| 19–21 | 3 | 블록 각속도, robot-base | /10 rad·s⁻¹ |
| 22 | 1 | 블록 높이 − 스폰 높이 | /0.2 m |
| 23–37 | 15 | 손가락 5개 끝 − 블록 중심, **palm 좌표** | /0.2 m |
| 38–42 | 5 | 손가락 끝 접촉 플래그 | 0/1 |
| 43–48 | 6 | 팔 xDrive 지령값 | `ArmSafeMin/Max` → [−1,1] |
| 49 | 1 | **손바닥 접촉 플래그** | 0/1 |
| 50 | 1 | **접촉점 수 / 6** | 0..1 |
| 51 | 1 | **grasp dwell 진행률** | 0..1 |
| 52 | 1 | **grasp 확정 여부** | 0/1 |
| 53 | 1 | **lift 진행률** (높이/목표높이) | 0..1 |
| 54 | 1 | **lift hold 진행률** | 0..1 |
| 55 | 1 | graspPoint↔목표점 거리 | /0.85 m |
| 56 | 1 | 경과 시간 / 20 s | 0..1 |

"파지 목표점"은 블록 중심이 아니라 **중심 + 수직 2.5 cm**(윗면 2.0 cm 아래)다.
top-down power grasp에서 손바닥은 윗면 위에 있고 손가락이 윗부분을 감싸므로,
palm grasp volume 중심을 기하학적 중심에 맞추면 손바닥이 블록 안으로 들어간다.

---

## 4. Action (연속 7차원)

| 인덱스 | 의미 | 적용 |
|---|---|---|
| 0–5 | 팔 6관절 목표각 **증분** | `±2°/decision`, 물체 8 cm 이내에서는 ×0.35, `ArmSafeMin/MaxDeg` clamp |
| 6 | 손 closure **증분** | `±0.08/decision`, closure∈[0,1] |

closure 하나가 DG5F 20관절 전부를 prefab의 열린 자세 ↔ 검증된 주먹 자세
(`LeftFistDeg`)로 보간한다. 20차원 개별 제어 대신 1차원으로 둔 이유:

* 이 자세는 이미 실기에서 검증된 파지 자세다.
* CPU 학습에서 20차원 손 탐색은 현실적으로 수렴하지 않는다.
* 7차원 유지 = reach 정책 전이 가능.

decision period 5, fixed step 0.02 s → 0.1 s마다 결정, 20 s 에피소드 = 200 결정.

---

## 5. Reward

모든 항은 `Dg5fGraspLiftSpec`에 상수로 있고 코드에 사유 주석이 있다.

### 접근 (grasp 확정 전에만 계산)

| 항 | 식 | 이유 |
|---|---|---|
| 시간 비용 | `-0.001` / decision | 제자리 진동이 공짜가 되지 않게 |
| 접근 potential | `Δφ`, `φ = 1·(1 − clamp01(d/0.85))`, 손바닥이 물체를 향할 때만 | potential-based shaping이라 최적 정책을 바꾸지 않으면서 접근을 학습 가능하게 만든다. 손바닥 반대편에서 다가가는 것은 파지로 이어지지 않으므로 게이트 |
| 미세 접근 potential | `Δφ`, `φ = 1.5·(1 − clamp01(d/0.12))`, 손바닥이 물체를 향할 때만 | `FineApproachPotentialMaximum = 1.5`, `FineApproachDistance = 0.12`; coarse 항이 거의 평평한 마지막 12 cm에 파지 가능한 정밀 접근 gradient를 준다 |
| top-down potential | `Δmax φ`, `φ = 0.3·p²`, `p = (70° − angle)/(70° − 35°)`, 물체 20 cm 이내 & 물체보다 위일 때만 | `TopDownAlignmentRewardDistance = 0.20`; 손바닥이 아래를 향해야 파지가 가능. reach 과제에선 주 목표였지만 여기선 보조라 가중치를 0.5 → 0.3으로 낮췄다. 신기록 갱신분만 지급해 왕복 farming 차단 |
| 근접 제어 페널티 | `-0.002 · Σa²/6` (물체 8 cm 이내) | 물체 옆에서 팔을 거칠게 쓰면 블록을 쳐낸다 |

### 파지

| 항 | 식 | 이유 |
|---|---|---|
| 폐합 potential | `Δmax φ`, `φ = 1.0 × clamp01(closure/0.75)` (물체 4.5 cm 이내일 때만) | `CloseNearObjectReward = 1.0`, `GraspReadyDistance = 0.045`; 실측 최적 closure 0.75에서 포화한다. **신기록분만** 지급하므로 에피소드당 총액은 1.0이고 손을 폈다 쥐는 farming은 불가능하다 |
| 폐합 원거리 페널티 | `Δclosure⁺ × (−0.25)` (물체 4.5 cm 밖) | 공중에서 주먹을 쥐는 전형적인 degenerate 행동. 페널티는 왕복으로 farming할 수 없으므로 이쪽은 per-step delta로 둔다. 여는 동작은 항상 0 |
| 접촉 potential | `Δmax φ`, `φ = 0.4·clamp01(n/3)` | 손가락을 실제로 블록에 올리는 것에 dense credit. 신기록분만 지급 → 툭툭 치기 farming 불가 |
| grasp 진행 potential | `Δmax (1.0 × dwell/0.3 s)` | 유효 파지를 유지하는 것에 부분 점수. 신기록분만 지급하므로 확정까지 총 지급액이 정확히 `GraspConfirmReward = 1.0` |

### 들어올리기

| 항 | 식 | 이유 |
|---|---|---|
| lift potential | `Δφ` (신기록 아님), `φ = 2.0 · clamp01(h/목표높이)` | 이 단계의 주 보상. **신기록이 아니라 매 스텝 델타**라서, 블록이 다시 내려가면 받았던 shaping을 그대로 토해낸다 — 떨어뜨림에 정확히 필요한 gradient |
| 성공 | `+5.0` (에피소드 종료) | 목표 높이·안정 유지 달성 |

### 잘못된 행동

| 항 | 값 | 조건 |
|---|---|---|
| `UnsafeSurfaceContact` | −2.0, 종료 | 움직이는 **팔 링크**가 패널에 충돌 |
| `Dropped` | −1.0, 종료 | 파지 확정 후 0.2 s 넘게 접촉 상실 **그리고** 최고 높이의 30% 아래로 낙하 |
| `ObjectPushedAway` | −0.5, 종료 | `PushAwayPenalty = −0.5`; 파지 전 블록이 스폰 위치에서 수평 `PushAwayDistance = 0.30 m` 초과 밀림 |
| `ObjectToppled` | −0.3, 종료 | 파지 확정 전 기울기 ≥ `ToppleLimitDegrees = 45°`; `topple_limit_deg`로 조정 가능 |
| `ObjectOutOfBounds` | −1.0, 종료 | 블록이 패널 밖으로 떨어지거나 작업공간(0.85 m) 이탈 |
| 닫힌 빈손 상승 | −0.004 / decision | `!grasp && closure ≥ 0.3 && graspPoint가 패널 위 15 cm 초과`. **"Grasp 없이 팔만 상승"** 대책. 절벽형 페널티 대신 지속적인 소액이라 가치함수를 불안정하게 만들지 않는다 |
| 팔 action 변화율 | `action_rate_penalty_scale · Σ(Δa)²/6` / decision | 명령의 급격한 반전을 줄이는 품질 항. 스펙 기본 −0.001, 환경 파라미터로 조절 |
| 손-패널 접촉 | `hand_surface_penalty_per_second · 접촉 시간` | 파지 확정 전 scraping을 직접 계측·부과. 스펙 기본 −0.05/s |
| grasp 자세 | `grasp_posture_penalty_scale · clamp((angle−35°)/(90°−35°))` / decision | 4.5 cm grasp volume 안, 파지 확정 전에만 side-grasp 비용 부과. 기본 0으로 inert |
| `Timeout`, `NonFinitePhysics` | 0 | shaping이 이미 도달 정도를 반영한다. 여기에 절벽을 더하면 "아예 시도하지 않는" 정책이 최적이 되어버린다 |

---

## 6. Grasp 성공 판정

**손가락을 닫았다는 것만으로는 절대 성공이 아니다.** 아래 4개를 **모두**
연속 0.3초 동안 만족해야 파지 확정이다(한 프레임이라도 깨지면 dwell 0으로 리셋).

1. **접촉점 ≥ 3** — 손가락 끝 5개 + 손바닥 중 3개 이상이 블록에 접촉.
2. **대향(force-closure proxy)** — 블록 중심에서 각 접촉점으로의 방향 중
   가장 벌어진 쌍의 각도 ≥ 90°. 이게 없으면 세 손가락으로 한쪽 면만 찌르는
   것도 파지로 오판된다.
3. **기하 구속** — 블록 중심과 접촉점 centroid 거리 ≤ 5 cm
   (`GraspCenterMaxDistance = 0.05`). 케이지 가장자리에
   걸친 것이 아니라 블록이 케이지 **안**에 있어야 한다.
4. **closure ≥ 0.3** — 손가락이 실제로 굽혀져 있어야 한다.

접촉 센서는 **콜라이더 GameObject에 붙인다**. URDF 임포터가 콜라이더를 링크의
`Collisions` 자식 아래에 두기 때문에, 링크에만 붙이면 `OnCollision*`이 오지
않는다(기존 `GraspContactSensor`의 실제 버그 — 아래 8절).

## 7. Lift 성공 판정 / Episode

**성공**: 파지 확정 이후
`블록 높이 − 스폰 높이 ≥ 목표높이`(커리큘럼 0.05 → 0.08 → 0.10 m) **그리고**
`|블록 선속도| ≤ 0.5 m/s`인 상태를 `LiftHoldSeconds`(0.25 → 0.35 → 0.50 s)
연속 유지. 던져 올린 블록은 "들고 있는" 것이 아니므로 속도 조건을 넣었다.

**실패**: `UnsafeSurfaceContact` / `Dropped` / `ObjectPushedAway` /
`ObjectToppled` / `ObjectOutOfBounds` / `NonFinitePhysics` / `Timeout`(20 s).

**Reset** (`OnEpisodeBegin`):

1. `RefreshGraspStage()` / `RefreshBlockWidth()` / `RefreshBlockHeight()` / `RefreshToppleLimit()` /
   `RefreshBlockCenterOfMass()` — 커리큘럼과 환경 파라미터 반영.
2. 에피소드 상태 전부 초기화 (closure, dwell, 확정 플래그, hold, slip, 최고 높이, 모든 potential, 종료 사유).
3. 로봇: 팔 6 + 손 20관절 전부 `xDrive.target` / `jointPosition` / `jointVelocity`를 prefab 초기값으로 되돌림. 그 뒤 팔 지령 재적용 + closure 0으로 손 개방.
4. 블록: 유효 스폰을 최대 32회 재추첨 → `isKinematic = true`, `useGravity = false`, 선/각속도 0, 위치·**Y축 yaw만** 랜덤 회전(항상 똑바로 서서 시작), `Physics.SyncTransforms()`.
5. 접촉·안전 센서 전부 `ResetContacts()`.
6. 2 physics step 뒤 `ReleaseObject()` — articulation 콜라이더 transform이 직접 쓴 `jointPosition`보다 한 스텝 늦기 때문. 이때 스폰 높이와 potential 기준선을 **다시 latch**해서 정착 프레임이 보상을 새게 하지 않는다.

### 환경 파라미터

`Dg5fGraspLiftSpec.cs`에 실제 등록된 환경 파라미터는 9개다. 품질 항 3개를
포함해 명시적으로 열거하면 다음과 같다.

| 파라미터 | 기본값 / 범위 | 용도 |
|---|---|---|
| `block_width` | 0.035 m / 0.025–0.060 m | 손의 대향 aperture에 맞춰 블록 폭과 부피 기반 질량을 함께 변경 |
| `block_height` | 0.12 m / 0.06–0.15 m | graspable region 높이와 부피 기반 질량을 함께 변경 |
| `grasp_stage` | 3 / 1–3 | spawn 반경, lift 목표(0.05→0.08→0.10 m), hold(0.25→0.35→0.50 s) curriculum |
| `topple_limit_deg` | 45° / 5–180° | 파지 확정 전 전도 종료각; 180°는 진단용 비활성화 |
| `block_com_height_fraction` | 0.20 / 0.05–0.50 | 블록 바닥 기준 COM 높이와 전도 난이도 조절; 0.50은 균일 밀도 |
| `topdown_potential_max` | 0.3 / 0–5 | 0.20 m 안쪽·70° 미만에서만 작동하는 new-best top-down potential 상한 |
| `action_rate_penalty_scale` | −0.001 / −1–0 | 6개 팔 action의 decision 간 변화율 비용 |
| `hand_surface_penalty_per_second` | −0.05 / −5–0 | 파지 확정 전 손-패널 접촉 시간 비용 |
| `grasp_posture_penalty_scale` | **0** / −1–0 | grasp volume 안에서 35°를 넘는 자세의 decision별 비용 |

스펙 기본값에서 완전히 inert한 항은 값이 0인
`grasp_posture_penalty_scale`뿐이다. `action_rate_penalty_scale`과
`hand_surface_penalty_per_second`는 기본값이 작지만 0은 아니다. 배포 정책의
순수 baseline과 두 inference evaluation config는 품질 항 3개를 모두 0으로
override해 학습 당시 정책의 행동을 그대로 측정한다.

---

## 8. 구현 중 발견한 기존 코드 문제

### 구현 산출물과 기존 코드 처리

변경·추가 산출물은 다음처럼 분리했다(`.meta`와 assembly definition은 같은
폴더의 Unity 산출물에 포함).

| 역할 | 파일 |
|---|---|
| task 계약·agent | `Runtime/Dg5fGraspLiftSpec.cs`, `Runtime/Dg5fGraspLiftAgent.cs` |
| 접촉 계측 | `Runtime/GraspLiftObjectContactSensor.cs`, `Runtime/GraspLiftSurfaceContactSensor.cs`, `Runtime/GraspLiftHandSurfaceSensor.cs` |
| scene 생성·build | `Editor/GraspLiftTrainingSceneBuilder.cs`, `Editor/GraspLiftTrainingBuild.cs` |
| Unity asset | `DG5F_GraspLiftTraining.unity`, `GraspLiftTrainingArea.prefab`, block/panel physics material, `Models/DG5FGraspLift.onnx` |
| 검증 | `Tests/EditMode/Dg5fGraspLiftSpecTests.cs`, `Tests/PlayMode/GraspLiftSceneTests.cs`, `Tests/PlayMode/GraspLiftHandGeometryProbe.cs` |
| 학습 | `training/config/dg5f_grasp_lift*.yaml`, `training/scripts/train_dg5f_grasp_lift.sh`, `training/scripts/evaluate_dg5f_grasp_lift_topdown.sh`, `training/scripts/prepare_dg5f_grasp_lift_transfer.py` |
| 문서 | `docs/DG5F_GRASP_LIFT.md` |

표의 Unity 상대 경로는 모두
`unity/Assets/MLAgents/GraspLift/`를 기준으로 한다.

삭제한 기존 코드는 없다. 기존 `Assets/MLAgents/Grasp`와 Reach 구현은
파이프라인 demo·teleop scene을 위해 유지하지만, 새 `DG5FGraspLift`
Behavior는 그것을 runtime 구성으로 사용하지 않는다. observation/action
shape이 같은 이유는 코드 재사용이 아니라 pre-grasp checkpoint 전이를
위해서다.

1. **`GraspContactSensor`가 동작하지 않는다.** `GraspTrainingSceneBuilder`가
   센서를 `ll_dg_N_tip` GameObject에 붙이는데, URDF 임포터는 콜라이더를
   `ll_dg_N_tip/Collisions/...` 아래에 만든다. Unity는 `OnCollision*`을
   콜라이더의 GameObject로 보내므로 이 센서는 한 번도 발화하지 않는다.
   → 기존 observation 슬롯 38–42(손가락 접촉)는 **항상 0**이었다. reach
   과제는 접촉을 쓰지 않아 드러나지 않았다. 새 구현은 링크와 각 콜라이더
   양쪽에 센서를 붙이고 `contactIndex`로 묶어 OR 집계한다.
2. **패널 안전 센서가 손 링크까지 덮는다.** `ConfigureSafetySensors`가 root가
   아닌 모든 콜라이더를 계측하므로 손가락이 테이블에 닿기만 해도 −2점 종료다.
   파지 학습에서는 성립할 수 없어, 새 빌더는 `_dg_`/`ll_dg_mount` 하위를
   제외하고 **팔 링크만** 계측한다.
3. **손 xDrive forceLimit 7.5 N**은 열린 자세 유지용이라 파지력이 없다. 새
   씬은 손 관절을 stiffness 1500 / damping 120 / forceLimit 20으로 올린다.
4. **`GraspCenterMaxDistance`가 너무 느슨했다(내 구현 버그).** 7 cm였을 때, 손가락이
   테이블에 서 있는 블록에 그냥 닿아 있기만 해도 파지 계약이 충족됐다. 그래서
   `GraspConfirmed`가 57%인데 `BestLiftHeight`는 0.005 m인 모순된 상태가 나왔다.
   5 cm로 조였다.
5. **첫 블록 크기(5.5 cm)가 손의 대향 가능 범위보다 넓었다.** `GraspLiftHandGeometryProbe`로
   닫힌 손을 실측한 결과 thumb–index 최소 간격이 약 3.1–3.6 cm(closure 0.75)였다.
   5.5 cm 블록은 애초에 손가락이 마주 볼 수 없어 물리적으로 파지가 불가능했다.
   → 블록 폭을 `block_width` 환경 파라미터로 빼서 **재빌드 없이** 실측 비교할 수 있게 했다.
6. **전이 체크포인트의 탐색이 붕괴해 있다.** reach 정책은 거의 결정적
   (entropy ≈ −0.16, log_sigma ≈ −2)이고, 7번째 grip action은 학습 중 무시돼서
   출력 head가 임의값이다. 그대로 로드하면 grip 축을 사실상 탐색하지 않는다.
   → `prepare_dg5f_grasp_lift_transfer.py`가 grip mean head를 0으로 만들고
   log_sigma를 팔 −0.7 / grip 0.0으로 재설정한다. 원본 파일은 수정하지 않는다.
7. **넘어진 블록이 파지 보상을 수집하는 local optimum이 있었다.** 파지 확정
   전 기울기 종료가 없을 때는 옆으로 누운 블록도 contact/opposition/cage 계약을
   만족한다. 따라서 폐합 `+1.0`, 접촉 `+0.4`, 파지 진행 `+1.0`은 받을 수 있지만
   lift potential은 구조적으로 0에 머문다. 이것이 앞선 네 run이 누적 보상
   약 1.75, lift 0에서 함께 plateau한 원인이었다.

   같은 transferred pre-grasp 체크포인트에서 두 환경 파라미터만 바꾼
   150k-step probe의 tail mean은 다음과 같다. 원본 run은
   `training/results/dg5f_grasp_lift_probeA_tilt`와
   `training/results/dg5f_grasp_lift_probeB_fix`에 있다.

   | metric | probe A (`topple_limit_deg=180`, `block_com_height_fraction=0.5`) | probe B (`45`, `0.30`) |
   |---|---:|---:|
   | `GraspLift/MaxObjectTiltDegrees` | 95.1 | 42.8 |
   | `GraspLift/ObjectTiltDegrees` (final) | 83.9 | 40.7 |
   | `GraspLift/FinalLiftHeight` | −0.0216 | +0.0008 |
   | `GraspLift/FinalDistanceMeters` | 0.0885 | 0.0550 |
   | `GraspLift/ContactCount` | 1.24 | 1.16 |
   | `GraspLift/FinalClosure` | 0.32 | 0.21 |
   | `GraspLift/GraspConfirmed` | 0.158 | 0.062 (0.106 → 0.023으로 하락) |
   | `GraspLift/BestLiftHeight` | 0.0002 | 0.0003 |
   | `GraspLift/Success` | 0.0 | 0.0 |
   | `Failure/ObjectToppled` (5000-step window당) | 1.4 | 36.4 |
   | `Failure/Timeout` | 20.0 | 6.0 |
   | `Environment/Episode Length` | 약 179 | 110 |

   probe A의 최대 95.1°/종료 83.9°는 블록이 사실상 매 에피소드 옆으로
   누웠음을 입증한다. probe B는 `FinalLiftHeight`를 처음으로 양수로 만들며
   이 local optimum을 제거했지만, 해결책 자체가 새 벽이 됐다.
   `ObjectToppled`가 지배적인 종료가 됐고 `GraspConfirmed`는 0.158에서
   0.062로 붕괴했으며 에피소드는 약 11초에 끝났다.
8. **committed scene에 brain이 연결되지 않았다.** HEAD의 training prefab은
   `m_Model: {fileID: 0}`였고 `GraspLiftTrainingSceneBuilder`도 ONNX를
   할당하지 않았다. `BehaviorType.Default`에서 model도 trainer도 없으면
   ML-Agents는 조용히 heuristic policy로 fallback하며, 이 heuristic은 zero
   action을 쓴다. fresh checkout에서 Play를 눌렀을 때 떨림 없는 부드러운
   화면이 보이더라도 학습 policy가 실행된 증거가 아니었다.

   builder가 이제
   `Assets/MLAgents/GraspLift/Models/DG5FGraspLift.onnx`를 직접 할당하고,
   없으면 기대 경로를 명시한 warning을 남긴다. prefab의 model reference도
   저장했으며 PlayMode test는 20개 area 전부에서 model non-null,
   `DeterministicInference = true`, behavior name `DG5FGraspLift`를
   검증한다. `ModelAsset`을 참조하기 위해 Editor와 PlayModeTests asmdef에
   `Unity.InferenceEngine`도 추가했다. **교훈은 움직임을 눈으로 해석하기
   전에 실제 model reference와 행동 출력을 검증해야 하며, scene 재생성
   불변식은 사람의 기억이 아니라 builder와 test가 소유해야 한다는 것이다.**
9. **`BlockSpawnsUprightAndRestingOnThePanel`이 physics settling을 spawn
   계약으로 잘못 검사했다.** test는 block을 release한 뒤 fixed update 8회를
   기다리고, 그 상태에 정확한 spawn predicate `IsValidSpawn`의 block-bottom
   tolerance 1e-5 m를 적용했다. 정상 settling 뒤 측정 offset은 6.0e-5 m여서
   실제 spawn 결함 없이 실패했다. 이번 변경을 stash한 상태에서도 재현해
   pre-existing임을 확인했다.

   test는 object release 전에 spawn geometry를 검사하도록 고쳤고 tolerance는
   완화하지 않았다. **교훈은 초기화 계약을 검증할 때 물리가 상태를 바꾸기
   전에 관찰해야 하며, 서로 다른 시점의 계약을 tolerance 확대로 섞으면 안
   된다는 것이다.**
10. **검증 상태:** GraspLift EditMode 55/55, GraspLift PlayMode 7/7이다.
    project-wide PlayMode에는 별개의 pre-existing failure
    `GraspTrainingSceneTests.TrainingSceneLoadsWithV1ContractAndSingleDriveOwner`
    (`Dg5fFingerIK` enabled)가 하나 남아 있다. GraspLift 변경과 무관하고 이번
    범위에서는 고치지 않았다.

---

## 모션 품질 조사 — 0.09 m 기준선에서 시작한 별도 목표

과제를 해결한 뒤 사람이 policy를 관찰하면서 기존 지표에는 보이지 않던 두
결함을 발견했다. 접근 중 팔이 떨렸고, 측면 접근에서 엄지가 패널을 긁었다.
성공 판정은 모션 품질을 전혀 보지 않으므로 **Success 98.7%와 두 결함은
동시에 존재할 수 있었다.**

이를 측정하기 위해 다음 통계를 추가했다.

| stat | 측정 의미 | 좋은 값 |
|---|---|---|
| `GraspLift/MeanArmActionRate` | 에피소드의 decision별 6축 팔 action delta 제곱합 평균 | baseline 0.401보다 낮되, 물리 단위 환산과 실제 영상에서 함께 더 부드러울 것 |
| `GraspLift/HandSurfaceContactSeconds` | 파지 확정 전 손 링크가 패널에 닿은 누적 시간 | 0 s에 가까울 것 |
| `GraspLift/TopDownAngleDegrees` | 에피소드 종료 시 손바닥의 top-down 이탈각 | 작을수록 좋지만 grasp 뒤 자세까지 포함하므로 단독 최적화 기준으로 쓰지 않음 |
| `GraspLift/GraspPostureAngleDegrees` | grasp volume 안에서 파지를 commit하는 동안의 top-down 이탈각 | 목표 ≤35° |

마지막 통계가 별도로 필요했다. 종료 시점의
`TopDownAngleDegrees`는 lift 뒤 자세를 재므로 약 83°였지만, 실제 파지를
commit하는 동안은 약 73°였다. 측정 시점 하나로 약 10°가 과대평가되며, 종료
각도로 가중치를 정했다면 잘못된 세기로 sweep했을 것이다.

### Baseline과 200k fine-tune sweep

`dg5f_grasp_lift_s0_baseline`은 배포 policy를 품질 보상 항 모두 0으로 두고
inference한 기준선이다.

| run | Success | GraspPostureAngleDegrees | TopDownAngleDegrees | HandSurfaceContactSeconds | MeanArmActionRate | return |
|---|---:|---:|---:|---:|---:|---:|
| S0 `dg5f_grasp_lift_s0_baseline` | 0.9956 | 72.8° | 83.1° | 3.45 s | 0.401 | 약 11.0 |

아래 네 run은 모두 같은 3.2M checkpoint에서 시작한 200k fine-tune이다.

| run | 바꾼 weight | Success | target stat | return |
|---|---|---:|---|---:|
| S1 `grasp_posture_penalty_scale = -0.1` | 자세 | 0.9921 | GraspPostureAngle 71.6° (72.8°에서) | 10.62 |
| S2 `grasp_posture_penalty_scale = -0.3` | 자세 | 0.9896 | GraspPostureAngle 71.7° | 9.86 |
| S3 `hand_surface_penalty_per_second = -0.5` | scraping | 0.9865 | HandSurfaceContactSeconds 3.40 s (3.45 s에서) | 9.73 |
| S4 `action_rate_penalty_scale = -0.05` | tremble | 0.9925 | MeanArmActionRate 0.397 (0.401에서) | 10.88 |

### 판정

1. **자세 penalty만으로는 자세를 고칠 수 없었다.** penalty를 3배
   (−0.1 → −0.3)로 키워도 개선은 사실상 같은 1.2°였고, return만
   10.62에서 9.86으로 떨어졌다. 수렴한 policy가 비용을 흡수했으며 측면
   파지는 이 penalty fine-tune으로 빠져나오지 못하는 깊은 local optimum이었다.

   **여기서 내렸던 `TopDownAlignmentPotential` 판정은 0.09 m geometry에만
   맞았고, 일반 결론으로는 틀렸다.** 이 항은 물체 0.20 m 안쪽, 진입각 70°
   미만에서만 new-best potential을 지급한다. 당시 grasp 자세 72.8°는 활성
   영역 밖이라 gradient가 정확히 0이었으므로, 그 geometry에서
   `topdown_potential_max`를 올리는 run을 피하라는 판단은 맞았다. 그러나
   승격한 0.12 m geometry의 배포 policy는 66.52°로 gate 안에 들어왔다.
   따라서 같은 weight 증가는 이제 자세를 66.52° → 62.35°(1.5) →
   57.39°(2.25) → 54.37°(3.0)로 강하고 단조롭게 이동시킨다. 앞선 penalty
   sweep의 약 1.2°와 다른 효과다. 아래 실험은 이 조건 변화 때문에 수행했다.
2. **scraping은 나쁜 습관이 아니라 0.09 m 당시 해법의 일부였다.** penalty는 파지
   확정 전에만 부과되고, 3.4 s 접촉은 접근과 손 닫기 내내 손이 패널 위에
   있다는 뜻이다. 수평에 가까운 손바닥으로 테이블 위 3.5 cm 폭 블록을
   잡으려면 손가락이 블록 중간보다 아래까지 내려가야 한다. policy 입장에서는
   “3.4 s 접촉하고 성공(+5와 lift shaping 약 +2)”과 “피하고 실패”의
   비교이므로 −1.75를 내는 것이 명백히 유리하다. 성공을 파괴하지 않고
   weight만으로 고칠 수 없고, 해법은 기하 변경이다.
3. **tremble은 reward 문제가 아니었다.** `MeanArmActionRate = 0.40`은 6개
   관절의 decision 간 action delta 제곱합이다. 관절당 약 0.26 action,
   ±2°/decision scale에서는 decision마다 관절당 약 0.5°, 즉 약 5°/s인
   매끄러운 명령 궤적이다. 이 물리 단위 환산으로 reward-side 진단이
   틀렸음을 바로잡았다.

   보이는 떨림은 inference 때의 Gaussian sampling에서 왔다
   (`m_DeterministicInference = 0`). scene builder는 이제
   `DeterministicInference = true`를 강제해 scene 재생성으로 이 문제가
   돌아오지 않게 한다. 다른 후보였던 physics-level oscillation은
   [`DEBUG_OSCILLATION_20260708.md`](DEBUG_OSCILLATION_20260708.md)에
   기록된 대로 이미 해결됐다.

### 0.12 m top-down potential fine-tune

배포된 0.12 m policy에서 `topdown_potential_max`를 1.5(T1), 3.0(T2),
2.25(T3)로 올려 각각 600k step fine-tune했다. T4는 T1을 같은 1.5로 계속
학습해 총 1.2M step에 도달한 run이다. 모두 learning rate 1e-4이며 학습 중
`grasp_posture_penalty_scale = -0.1`,
`hand_surface_penalty_per_second = -0.5`도 함께 켰다.

같은 배포 policy의 grasp posture는 0.12 m 승격 당시 측정에서 67.1°였고,
이번 nominal inference window(n=17)에서는 66.52°였다. 서로 다른 측정
window에서 나온 값이며, 그 사이 배포 모델을 교체한 것이 아니다. 아래 비교는
후보들과 같은 방식으로 다시 잰 66.52°를 baseline으로 쓴다.

| 조건 | training RUN_ID |
|---|---|
| T1 1.5 / 600k | `dg5f_grasp_lift_t1_topdown150` |
| T2 3.0 / 600k | `dg5f_grasp_lift_t2_topdown300` |
| T3 2.25 / 600k | `dg5f_grasp_lift_t3_topdown225` |
| T4 1.5 / 1.2M total | `dg5f_grasp_lift_t4_topdown150_long` |

nominal evaluation copy의 RUN_ID는 각각
`dg5f_grasp_lift_eval_t1_topdown150`,
`dg5f_grasp_lift_eval_t2_topdown300`,
`dg5f_grasp_lift_eval_t3_topdown225`,
`dg5f_grasp_lift_eval_t4_topdown150_long`이고, COM 0.50 copy는 각각
`dg5f_grasp_lift_eval_t1_com050`, `dg5f_grasp_lift_eval_t2_com050`,
`dg5f_grasp_lift_eval_t3_com050`, `dg5f_grasp_lift_eval_t4_com050`이다.

평가는 policy update 없이 품질 penalty를 모두 0으로, 비교용
`topdown_potential_max`를 기본값 0.3으로 되돌린 뒤 nominal COM 0.20과
균일 밀도 COM 0.50에서 수행했다. 아래 값은 resume 직후 전이 구간을 제외한
summary window mean이다. Success의 `±`는 window 표본 표준편차이고,
Dropped/Toppled는 5k-step summary bucket당 평균 발생 수다.

| COM | policy | n | Success ± SD | posture | topdown | contact | best | hold | reward | Dropped | Toppled |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | Deployed | 17 | 99.413% ±0.891%p | 66.52° | 78.73° | 1.076 s | 0.1435 m | 0.4971 s | 11.201 | 0.176 | 0.059 |
| 0.20 | T1 1.5 | 535 | 99.426% ±0.836%p | 62.35° | 75.83° | 1.055 s | 0.1444 m | 0.4971 s | 11.200 | 0.361 | 0.030 |
| 0.20 | T3 2.25 | 41 | 98.336% ±1.357%p | 57.39° | 71.71° | 1.117 s | 0.1433 m | 0.4917 s | 11.115 | 1.024 | 0.195 |
| 0.20 | T4 1.5 long | 41 | 98.947% ±1.089%p | 58.65° | 73.55° | 1.076 s | 0.1442 m | 0.4947 s | 11.187 | 0.854 | 0 |
| 0.20 | T2 3.0 | 538 | 96.269% ±2.115%p | 54.37° | 68.46° | 1.075 s | 0.1402 m | 0.4813 s | 10.970 | 2.736 | 0.117 |
| 0.50 | Deployed | 515 | 99.240% ±0.959%p | 66.46° | 79.37° | 1.113 s | 0.1435 m | 0.4962 s | 11.189 | 0.437 | 0.155 |
| 0.50 | T1 1.5 | 41 | 98.713% ±1.410%p | 62.24° | 75.68° | 1.065 s | 0.1421 m | 0.4936 s | 11.146 | 0.829 | 0.195 |
| 0.50 | T3 2.25 | 41 | 97.164% ±1.818%p | 57.04° | 71.27° | 1.130 s | 0.1403 m | 0.4858 s | 11.036 | 1.976 | 0.268 |
| 0.50 | T4 1.5 long | 41 | 97.683% ±1.405%p | 58.80° | 73.45° | 1.069 s | 0.1409 m | 0.4884 s | 11.095 | 1.732 | 0.122 |
| 0.50 | T2 3.0 | 41 | 95.842% ±2.313%p | 54.57° | 68.16° | 1.049 s | 0.1368 m | 0.4792 s | 10.930 | 3.024 | 0.195 |

**window 길이 주의:** deployed nominal은 n=17뿐인 반면, evaluator 수정 전에
끝없이 실행된 T1/T2 nominal은 n=535/538이다. 따라서 nominal COM 유의성
비교가 가장 약하고, 같은 n=41로 맞춘 COM 0.50 window가 가장 깨끗한 비교다.

Welch 비교에서 T1은 deployed보다 COM 0.50 Success가 −0.527%p
(`p ≈ 0.023`)였다. T3는 nominal −1.077%p(`p ≈ 0.00090`), COM 0.50
−2.075%p(`p < 1e-8`)였다. T4는 nominal −0.465%p(`p ≈ 0.099`)로
구별되지 않았지만 COM 0.50에서는 −1.556%p(`p < 1e-8`)였다. T4를 T1과
직접 비교하면 posture는 nominal/COM 0.50에서 −3.69°/−3.44° 더 내려갔지만
Success도 −0.479%p(`p ≈ 0.0086`)/−1.029%p(`p ≈ 0.0014`) 내려갔다.

판정은 다음과 같다.

1. potential weight가 커질수록 자세는 단조롭게 개선되지만 robustness를
   지불한다. 자세 곡선의 diminishing-return knee는 약 2.25지만 safety
   knee는 1.5 이하에 있다.
2. 두 COM의 Success, Failure/Dropped, lift height, hold time을 모두 놓고
   deployed를 지배하는 설정은 없다. **배포 모델은 교체하지 않았다.**
3. T4는 1.5에서 학습을 늘리면 자세가 plateau하지 않고 계속 내려가지만,
   Success와 drop도 함께 악화됨을 보였다. 안전 weight에서 step을 늘리는
   것도 공짜가 아니다.
4. 3.0에서도 posture는 약 54.4°로 목표 35°보다 약 19° 높고, Success는
   약 3%p 낮아졌다. 3.0 초과 weight는 시험하지 않았으므로 이 방법으로
   35°가 불가능하다고 증명한 것은 아니지만 reliability 추세는 추가 sweep을
   지지하지 않는다.

## 남은 문제

- **측면 파지는 고쳐지지 않았다.** 배포 policy의 grasp posture는 nominal
  66.52°, 균일 COM 66.46°로 목표 ≤35°를 크게 벗어난다. potential
  fine-tune은 자세를 움직였지만 모든 자세 이득이 robustness 비용을 동반했다.
- 배포 모델은 **변경하지 않는다.** 두 COM Success, Failure/Dropped, lift
  height, hold time을 함께 보존하면서 자세를 개선한 후보가 없기 때문이다.
- 권장 다음 단계는 pre-grasp checkpoint에서 **잡기를 처음 배우는 순간부터**
  자세를 채점하는 from-scratch grasp retrain이다. 0.12 m geometry가 potential
  gate를 열어 준 사실은 확인했지만, 이미 수렴한 grasp를 뒤늦게 미는 방식은
  목표 35°에 닿기 전에 reliability를 잃었다. 이 재학습도 현재 배포 성능을
  회복한다는 보장은 없으므로 별도 후보로 평가해야 한다.

---

## 9. 실행

> 아래 절차는 위 결과를 실제로 만들어낸 전용 GPU Linux 학습서버 기준
> 기록이다. 그 서버는 폐지됐고 지금은 로컬 Windows 단독 머신(RTX 2080)뿐이라
> `train_dg5f_grasp_lift.sh`/`evaluate_dg5f_grasp_lift_topdown.sh`를 포함한
> bash 자동화가 그대로 돌지 않는다(`training/archives/scripts/README.md`
> 참고). Windows에서 지금 실제로 되는 절차는
> [`training/README.md`](../training/README.md)의 "DG5F Grasp + Lift" 절
> (Unity Editor에 붙여 `mlagents-learn` 직접 실행)이다.

```bash
cd <repo-root>   # 과거 전용 학습서버(/home/lkb/...) 경로였음 — 서버 폐지, 지금은 로컬 1대뿐이라 저장소 루트로 이동
source vision/.vision/bin/activate
```

### 씬 + Linux player 빌드

Unity 메뉴 **Tools > ML-Agents > Build DG5F Grasp Lift Linux Player**,
또는 배치 모드:

```bash
~/Unity/Hub/Editor/6000.4.0f1/Editor/Unity -batchmode -nographics -quit \
  -projectPath "$PWD/unity" \
  -executeMethod KDT.GraspLiftTraining.Editor.GraspLiftTrainingBuild.BuildLinuxPlayer \
  -logFile "$PWD/training/logs/grasplift_build.log"
```

### EditMode 테스트

```bash
~/Unity/Hub/Editor/6000.4.0f1/Editor/Unity -batchmode -runTests \
  -testPlatform EditMode -projectPath "$PWD/unity" \
  -testFilter "KDT.GraspLiftTraining.Tests" \
  -testResults "$PWD/training/test-results/grasplift-editmode.xml" \
  -logFile "$PWD/training/logs/grasplift_editmode.log"
```

### 학습

```bash
# 안정성 커리큘럼 + pre-grasp reach 정책에서 전이
RUN_ID=dg5f_grasp_lift_stability_5m \
CONFIG=training/config/dg5f_grasp_lift_stability_curriculum.yaml \
TIME_SCALE=20 TORCH_DEVICE=cpu \
  training/scripts/train_dg5f_grasp_lift.sh start --transfer

# 기존 grasp_stage-only config에서 전이
RUN_ID=dg5f_grasp_lift_5m TIME_SCALE=20 TORCH_DEVICE=cpu \
  training/scripts/train_dg5f_grasp_lift.sh start --transfer

# 처음부터
RUN_ID=dg5f_grasp_lift_stability_scratch \
CONFIG=training/config/dg5f_grasp_lift_stability_curriculum.yaml \
  training/scripts/train_dg5f_grasp_lift.sh start

# 중단된 run 재개
RUN_ID=dg5f_grasp_lift_stability_5m \
CONFIG=training/config/dg5f_grasp_lift_stability_curriculum.yaml \
  training/scripts/train_dg5f_grasp_lift.sh resume
```

### 설정 파일

| config | 용도 |
|---|---|
| `training/config/dg5f_grasp_lift.yaml` | 기본 grasp-stage curriculum |
| `training/config/dg5f_grasp_lift_stability_curriculum.yaml` | 성공 run에 사용한 grasp-stage + COM 안정성 curriculum |
| `training/config/dg5f_grasp_lift_probe_tilt.yaml` | 균일 COM·전도 종료 비활성 probe A |
| `training/config/dg5f_grasp_lift_probe_fix.yaml` | COM 0.30·45° 전도 종료 probe B |
| `training/config/dg5f_grasp_lift_quality_v2.yaml` | 모션 품질 계측과 fine-tune용 통합 설정 |
| `training/config/dg5f_grasp_lift_s1_posture010.yaml` | S1 자세 penalty −0.1 sweep |
| `training/config/dg5f_grasp_lift_s2_posture030.yaml` | S2 자세 penalty −0.3 sweep |
| `training/config/dg5f_grasp_lift_s3_scrape050.yaml` | S3 scraping −0.5/s sweep |
| `training/config/dg5f_grasp_lift_s4_rate005.yaml` | S4 action-rate −0.05 sweep |
| `training/config/dg5f_grasp_lift_eval_com030.yaml` | 이전 0.09 m policy의 COM 0.30 inference-only control |
| `training/config/dg5f_grasp_lift_eval_com050.yaml` | 이전 0.09 m policy의 COM 0.50 inference-only robustness 평가 |
| `training/config/dg5f_grasp_lift_h012_topdown.yaml` | 0.12 m geometry 승격 fine-tune |
| `training/config/dg5f_grasp_lift_eval_deployed.yaml` | 현재 0.12 m 배포 policy의 COM 0.20 inference-only control |
| `training/config/dg5f_grasp_lift_eval_h012_com050.yaml` | 현재 0.12 m 배포 policy의 COM 0.50 inference-only robustness 평가 |
| `training/config/dg5f_grasp_lift_t1_topdown150.yaml` | T1: 0.12 m policy에서 top-down 1.5, 600k fine-tune |
| `training/config/dg5f_grasp_lift_t2_topdown300.yaml` | T2: top-down 3.0, 600k fine-tune |
| `training/config/dg5f_grasp_lift_t3_topdown225.yaml` | T3: top-down 2.25, 600k fine-tune |
| `training/config/dg5f_grasp_lift_t4_topdown150_long.yaml` | T4: T1을 top-down 1.5로 총 1.2M step까지 계속 학습 |
| `training/config/dg5f_grasp_lift_eval_t1_topdown150.yaml` | T1의 COM 0.20 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t1_com050.yaml` | T1의 COM 0.50 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t2_topdown300.yaml` | T2의 COM 0.20 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t2_com050.yaml` | T2의 COM 0.50 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t3_topdown225.yaml` | T3의 COM 0.20 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t3_com050.yaml` | T3의 COM 0.50 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t4_topdown150_long.yaml` | T4의 COM 0.20 inference-only 평가 |
| `training/config/dg5f_grasp_lift_eval_t4_com050.yaml` | T4의 COM 0.50 inference-only 평가 |

성공 run의 PPO YAML은 57/7 pre-grasp checkpoint와 호환되도록
`normalize: false`, hidden 256 × 3 layer를 유지한다. PPO는
batch 2048 / buffer 20480, learning rate 0.0003 linear decay,
`gamma = 0.995`, `time_horizon = 256`, `summary_freq = 5000`이며
`grasp_stage`와 `block_com_height_fraction` 두 progress curriculum,
`topple_limit_deg = 45`를 추가했다. 품질 sweep은 같은 network와 rollout
shape을 유지하되 이미 수렴한 policy를 보존하기 위해 learning rate를
0.0001로 낮추고 각각 200k step으로 제한했다. eval config는
`action_rate_penalty_scale`, `hand_surface_penalty_per_second`,
`grasp_posture_penalty_scale`을 모두 0으로 고정한다.

player는 `training/builds/DG5FGraspLift/DG5FGraspLift.x86_64`다.

### 학습 없는 평가

원본 run을 보존하려면 학습된 run directory를 평가용 RUN_ID로 복사한 뒤,
해당 copy에 대해 `resume --inference`를 실행한다. `--inference` 때문에 PPO
update는 일어나지 않는다.

**이 ML-Agents version에서는 `--inference`가 YAML의 `max_steps`를
존중하지 않는다.** 따라서 inference evaluation은 스스로 종료하지 않는다.
T1 평가는 800k에서 멈춰야 했지만 3.27M step까지 실행됐고 script의 두 번째
phase가 시작되지 않았다. 과거 `dg5f_grasp_lift_eval_h012_com050`에
`max_steps = 1700000`인데도 3,999,946까지 checkpoint가 남은 것도 같은
함정으로 설명된다. 그 session은 수동으로 종료됐고 당시 trap은 기록되지
않았다.

top-down 실험은 `training/scripts/evaluate_dg5f_grasp_lift_topdown.sh`로
평가한다. script는 resume 지점 이후 명시적인 inference step budget
(기본 200k)과 wall-clock timeout을 동시에 적용하고, 각 phase를 독립 process
group으로 실행한다. budget 도달 시 그 group 전체를 종료하며, 목표 전에
process가 끝나거나 timeout이면 nonzero로 종료해 다음 phase를 성공처럼
진행하지 않는다. **교훈은 inference-only 여부와 실행 종료 조건은 별개이며,
evaluator가 직접 step·시간 경계를 소유해야 한다는 것이다.**

```bash
# T1의 COM 0.20과 COM 0.50을 각각 bounded inference로 평가
training/scripts/evaluate_dg5f_grasp_lift_topdown.sh \
  dg5f_grasp_lift_t1_topdown150 both
```

직접 `train_dg5f_grasp_lift.sh resume --inference`를 실행하면 위 종료
경계가 없으므로, top-down 후보 평가는 반드시 bounded evaluator를 통한다.

### 관찰할 지표

`GraspLift/GraspConfirmed` → `GraspLift/BestLiftHeight` → `GraspLift/Success`
순서로 올라와야 한다. 마지막 lesson에서 좋은 policy는
`GraspConfirmed`와 `Success`가 1에 가깝고, `BestLiftHeight`와
`FinalLiftHeight`가 0.10 m 이상이며, `LiftHoldSeconds`가 요구값 0.50 s에
도달해야 한다. `Failure/ObjectPushedAway`가 줄지 않으면 접근이
거칠다는 뜻이고, `GraspLift/FinalClosure`가 0에 머물면 grip 탐색이 다시
붕괴한 것이다. `GraspLift/ObjectTiltDegrees`는 종료 시 기울기,
`GraspLift/MaxObjectTiltDegrees`는 에피소드 중 최대 기울기다. 둘 다 0°가
직립, 90°가 옆으로 누운 상태이며 `Failure/ObjectToppled`와 함께 안정성
커리큘럼이 단순히 에피소드를 조기 종료시키는지 확인해야 한다. 모든
`Failure/*`는 0에 가까울수록 좋다.

모션 품질은 `GraspLift/GraspPostureAngleDegrees ≤ 35°`와
`GraspLift/HandSurfaceContactSeconds ≈ 0 s`가 목표다.
`GraspLift/TopDownAngleDegrees`는 작을수록 좋지만 lift 뒤 종료 자세이므로
grasp 순간 판단에는 posture 통계를 우선한다. `GraspLift/MeanArmActionRate`는
0.401 baseline보다 낮은 방향을 보되, 반드시 action scale을 물리 단위로
환산하고 deterministic inference 영상과 함께 판단한다.
