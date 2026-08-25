# DG5FGraspReadyReach 학습 흐름

## 무엇을 배우는가

정책은 열린 DG5F 손을 공의 파지 준비 위치로 옮긴 뒤 팔을 고정한다. 손가락을 쥐는
행동은 배우지 않으며 MediaPipe 연동은 다음 파이프라인에서 수행한다.

## 한 episode

1. 팔 6축 상태와 DG5F 손 20관절을 초기 prefab 자세로 복원한다.
2. 패널 위 반경 0.20~0.85 m, 전 방위에서 4 cm 지름 공을 배치한다.
3. `Transit`에서 공 10 cm 위 waypoint로 이동한다.
4. waypoint 3 cm 이내에서 `Descend`로 전환해 공 위에서 하강한다.
5. 거리 1 cm, 속도 0.05 m/s, palm 오차 15°, 상부 45° cone을 0.25초 유지한다.
6. 팔 target을 잠그고 성공 종료한다.

패널 접촉, 낮은 높이의 수평 이동, workspace 이탈, 비유한 물리는 즉시 실패하고 20초면
timeout된다. 이 규칙이 손이나 팔로 바닥을 쓸어 가는 shortcut을 막는다.

## Unity와 PPO

Unity는 37개 관측을 보내고 PPO는 팔 6축 연속 action을 반환한다. Unity는 action을
xDrive target 증분으로 적용하고 waypoint 진전, palm 정렬, 시간, 성공과 안전 실패를
보상한다. 20개 독립 영역이 서로 다른 seed로 병렬 실행된다.

학습 순서는 Unity 계약 테스트 → Linux player → 512-step 통신 smoke → fresh 5M PPO →
500-seed 결정론 평가다. smoke와 평균 reward 상승만으로 모델을 승인하지 않는다.

세부 계약은 [`AGENT_SPEC.md`](AGENT_SPEC.md), 명령은
[`ML_AGENTS_TRAINING_GUIDE.md`](ML_AGENTS_TRAINING_GUIDE.md)를 참고한다.
