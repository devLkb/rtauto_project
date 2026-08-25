# DG5FGraspReadyReach Agent Spec 2.0.0

이 문서는 Unity Agent, PPO 설정, 평가기의 단일 계약이다. 정책은 **UR5e 팔 6축만**
제어한다. DG5F 손 20관절은 prefab의 편 자세로 유지하며 policy I/O에 포함하지 않는다.
MediaPipe 입력과 실제 파지 동작은 후속 integration 범위다.

## Policy

- Behavior: `DG5FGraspReadyReach`
- vector observations: 37, stack 1
- continuous actions: 6
- decision period: 5 physics steps
- episode timeout: 20 simulation seconds (`MaxStep=0`)

## Observation order

길이는 미터, 속도는 m/s다. 위치·방향 벡터는 명시된 좌표계에서 정규화하고 각 성분을
`[-1, 1]`로 clamp한다. trainer normalization은 사용하지 않는다.

| 인덱스 | 길이 | 값 |
|---:|---:|---|
| `0..5` | 6 | 안전 범위로 정규화한 팔 관절각 |
| `6..11` | 6 | 정규화한 팔 관절속도 |
| `12..17` | 6 | 정규화한 팔 xDrive target |
| `18..20` | 3 | robot-base 좌표의 `(target - GraspPoint) / 1.05` |
| `21..23` | 3 | robot-base 좌표의 `(active waypoint - GraspPoint) / 1.05` |
| `24` | 1 | 목표 중심 거리 `/ 1.05` |
| `25` | 1 | 목표까지 수평 거리 `/ 1.05` |
| `26` | 1 | 패널 상면으로부터 GraspPoint 높이 `/ 0.20` |
| `27..29` | 3 | robot-base 좌표의 GraspPoint 선속도 `/ 1.0` |
| `30..32` | 3 | palm 좌표의 `(target - palm) / 0.20` |
| `33` | 1 | palm 전방과 palm→target 방향의 dot product |
| `34` | 1 | target→palm 방향과 world up의 dot product |
| `35` | 1 | 단계: Transit `-1`, Descend `0`, Locked `1` |
| `36` | 1 | 잠금 조건 연속 유지 진행도 `0..1` |

NaN/Infinity는 관측으로 내보내지 않고 episode를 실패 종료한다.

## Action order

`0..5`는 `shoulder_pan`, `shoulder_lift`, `elbow`, `wrist_1`, `wrist_2`,
`wrist_3`의 target 증분이다. 행동을 `[-1,1]`로 clamp한 뒤 일반 구간은 decision당
최대 `2°`, active waypoint 10 cm 이내에서는 `1°`를 적용한다. 절대 상한은 `4°`다.
관절 target은 URDF 한계와 프로젝트 안전 한계에 clamp한다.

손 20관절은 초기 prefab xDrive target을 episode 시작 시 복원하고 매 제어/물리 step에
다시 적용한다. 팔 action은 손 target에 쓸 수 없다.

## Target, reset, 접근 단계

- 빨간 공 반지름은 `0.02 m`, 중심은 패널 상면에서 `0.02 m`다.
- robot-base 평면 반경 `0.20..0.85 m`, 방위각 `0..360°`를 균등 표본화한다.
- 패널 밖, 로봇 collider와 겹침, 초기 GraspPoint 거리 10 cm 미만 표본은 거부한다.
- 공은 solid collider와 kinematic Rigidbody를 사용하므로 밀려나지 않는다.
- reset은 팔 상태/속도/target, 열린 손 target, 목표, 단계, hold와 보상 기억을 초기화한다.

접근은 두 단계다.

1. **Transit**: 공 중심의 정확히 `0.10 m` 위 pre-grasp waypoint로 이동한다.
2. waypoint 거리 `<=0.03 m`이고 패널 상면 clearance `>=0.10 m`이면 **Descend**로
   전환해 공으로 하강한다.

clearance가 10 cm보다 낮을 때 Transit 상태이거나, 목표 수평 거리 5 cm 밖이면
`PrematureDescent` 실패다. root base를 제외한 움직이는 로봇 collider가 패널과 닿으면
`UnsafeSurfaceContact` 실패다. 따라서 바닥을 쓸며 접근하는 trajectory는 성공할 수 없다.

## Reward와 종료

- active waypoint 거리 감소량 `2.0 * (이전 거리 - 현재 거리)`
- Descend 중 palm 정렬 개선량 `0.25 * (현재 정렬 - 이전 정렬)`
- Descend 진입 `+0.25`
- 매 decision `-0.001`
- 잠금 성공 `+4.0`
- timeout `-1.0`
- 조기 하강, 패널 접촉, workspace 이탈, 비유한 물리 `-2.0`

아래 조건을 모두 `0.25 s` 연속 만족하면 팔을 잠근다.

- GraspPoint와 공 중심 거리 `<=0.01 m`
- GraspPoint 속도 `<=0.05 m/s`
- palm 전방이 목표를 향하는 오차 `<=15°` (`dot >= cos 15°`)
- palm이 공 위쪽 45° cone 안에 있음 (`dot >= cos 45°`)

학습과 평가는 잠금 시 episode를 성공 종료한다. 배포에서 `endEpisodeOnLock=false`이면
6개 팔 target을 latch해 계속 재적용하며, 외부 코드가 `ReleaseArmLock()`을 호출할 때만
해제한다. 이 상태에서 후속 MediaPipe 손 제어가 손가락을 움직일 수 있다.

## Evaluation gate

학습과 겹치지 않는 seed 500개를 결정론 평가한다.

- 성공률 `>=90%`
- 성공 행 모두 거리/속도/자세/상부 cone/0.25초 조건 충족
- 전체 행에서 패널 접촉, 조기 하강, 비유한 물리, workspace 실패 0건
- Transit 최소 clearance `>=0.10 m`
- 중복 seed 0건

카메라 좌표 수신은 이 spec 밖이다. 후속 adapter는 보정된 robot-base 좌표를 target에
주입하되 37/6 policy shape를 바꾸지 않는다.
