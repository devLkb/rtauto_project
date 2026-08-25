# DG5F 열린 손 파지 준비 도달 설계

## 범위

```text
현재: 랜덤 공 위치 -> RL이 열린 손과 팔을 안전하게 배치 -> 팔 잠금
후속: MediaPipe 손 20관절 인식 -> 잠긴 팔 위에서 실제 파지
```

현재 정책은 카메라나 MediaPipe를 입력으로 사용하지 않는다. Unity가 만든 목표 좌표에
대해 팔 6축만 학습하고, 손 20관절은 prefab의 열린 자세로 유지한다.

## 바닥 쓸기 방지

거리만 최소화하면 Agent는 손이나 팔을 패널에 붙여 수평 이동하는 shortcut을 선택할 수
있다. 이를 보상 조정만으로 완화하지 않고 환경 계약으로 차단한다.

1. 먼저 공 중심 10 cm 위 waypoint를 목표로 한다.
2. waypoint 3 cm 이내와 clearance 10 cm 이상을 동시에 만족해야 하강 단계로 간다.
3. 하강 중에는 공과 수평 거리 5 cm 안에 있어야 한다.
4. root base를 제외한 움직이는 로봇 collider가 패널에 닿으면 즉시 실패한다.

따라서 낮은 높이에서의 수평 접근은 terminal penalty를 받고 성공 trajectory가 될 수 없다.

## 파지 준비와 잠금

위치만 맞고 손등이 공을 향하는 상태를 방지하기 위해 palm 자세를 성공 조건에 포함한다.
GraspPoint가 1 cm 이내이고 느리며, palm이 목표 방향 15° 이내이고 공 위쪽 45° cone에
있는 상태를 0.25초 유지해야 한다. 그 후 6축 xDrive target을 latch한다. 학습은 성공
종료하고, 배포는 `ReleaseArmLock()` 전까지 계속 고정할 수 있다.

## 학습과 평가

37개 관측에는 관절 상태, 목표/waypoint 오차, clearance, 속도, palm 방향, 단계와 hold가
포함된다. 행동은 팔 6개뿐이다. checkpoint와 curriculum 없이 5M-step fresh PPO를
사용한다. 최종 평가는 500개 미학습 seed에서 성공률과 모든 안전 조건을 함께 검증한다.

수치·인덱스의 단일 출처는 [`AGENT_SPEC.md`](AGENT_SPEC.md)다.
