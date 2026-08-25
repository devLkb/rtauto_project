# DG5FGraspReadyReach 학습 계획

## 고정 계약

- Behavior `DG5FGraspReadyReach`, spec `2.0.0`
- observation/action `37/6`
- 열린 손 20관절 고정, 팔 6축만 policy 제어
- `10 cm` 상부 waypoint 후 수직 하강
- 패널 접촉과 조기 하강은 즉시 실패
- `1 cm / 0.05 m/s / 15° / 상부 45° cone / 0.25초` 후 팔 잠금

세부 인덱스와 경계값은 [`AGENT_SPEC.md`](AGENT_SPEC.md)가 유일한 계약이다.

## 실행 순서

1. EditMode/PlayMode 계약 및 scene 테스트
2. Linux player 재빌드
3. 정확히 512 agent-step communicator smoke
4. checkpoint·curriculum 없이 fresh PPO를 최대 5M steps 학습
5. 미학습 seed 500개 결정론 평가

| PPO 항목 | 값 |
|---|---:|
| batch / buffer | 256 / 2048 |
| learning rate | `3e-4`, linear |
| hidden units / layers | 256 / 3 |
| gamma / lambda | `0.99 / 0.95` |
| max steps | 5,000,000 |
| trainer normalization | false |

이전 `DG5FGraspPointReach` checkpoint 변환과 curriculum 설정은 사용하거나 유지하지 않는다.
`--initialize-from`은 launcher에서 거부한다. 같은 새 run을 중단 후 이어갈 때만
`--resume`을 사용한다.

## 승인

- 500 seed 성공률 90% 이상
- 모든 성공 행이 잠금 조건을 전부 충족
- 패널 접촉, 조기 하강, Transit clearance 위반, 비유한 물리, workspace 실패 0건
- 통과 모델 중 평균 최종 오차, median 완료 시간, p95 완료 시간 순으로 선택

512-step smoke와 training reward 상승은 수렴 또는 승인 근거가 아니다. MediaPipe 연결과
손가락 파지는 승인된 팔 정책 이후 별도 integration 단계에서 진행한다.
