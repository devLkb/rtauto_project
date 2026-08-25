# DG5FGraspReadyReach 로드맵

## 현재 구현

- [x] Behavior `DG5FGraspReadyReach`, spec `2.0.0`, observation/action `37/6`
- [x] 팔 6축 policy 제어와 열린 손 20관절 target 고정
- [x] 10 cm 상부 waypoint와 하강 단계
- [x] 움직이는 로봇 collider의 패널 접촉 실패 처리
- [x] 위치·속도·palm 자세·상부 cone 0.25초 후 팔 latch
- [x] 20개 독립 학습 영역과 고정 크기 target
- [x] fresh PPO, smoke 생성기, 500-seed 평가 계약

## 검증 및 학습

1. EditMode/PlayMode와 Python 계약 테스트를 계속 통과시킨다.
2. Linux player를 새 이름으로 빌드하고 512-step communicator smoke를 수행한다.
3. checkpoint 없이 최대 5M PPO를 학습한다.
4. 500개 미학습 seed에서 성공률 90%와 안전 위반 0건을 확인한다.

## 후속 integration

승인된 policy 이후 MediaPipe 20관절을 DG5F 손 target으로 매핑한다. 카메라 좌표는
robot-base 미터 좌표로 보정하고 timestamp, stale target, workspace validation을 거쳐
target Transform에 주입한다. MediaPipe가 파지하는 동안 팔은 latch 상태를 유지하고,
상위 상태 기계만 `ReleaseArmLock()`을 호출한다.

후속 단계는 현재 37/6 policy tensor를 변경하지 않는다.
