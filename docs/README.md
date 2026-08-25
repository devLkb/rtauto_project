# 문서 인덱스

## DG5FGraspLift 강화학습 (현재 활성 정책)

- **기준 문서**: [`DG5F_GRASP_LIFT.md`](DG5F_GRASP_LIFT.md) — Agent 계약·보상·실행법
- **실물 이관 계획**: [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md) — 단계별 순서와 리스크
- 발표자료: [`GRASP_LIFT_발표자료.md`](GRASP_LIFT_발표자료.md)
- 설명: [`GRASP_LIFT_설명.md`](GRASP_LIFT_설명.md)

제품 파이프라인은 `목표 좌표 -> RL 파지+들어올리기(GraspLift) -> MediaPipe 손 파지`다.

## 지난 세대 (archives/)

DG5FGraspReadyReach(팔 이동만)와 구세대 DG5FGrasp/DG5FStableGrasp(파지만)는
GraspLift로 완전히 대체되어 Unity 씬·코드가 삭제됐다. 계약 문서는 역사 기록으로
[`archives/`](archives/)에 보존한다 — 지금 실행 지침으로 쓰지 말 것:
[`ML_AGENTS_LEARNING_FLOW.md`](archives/ML_AGENTS_LEARNING_FLOW.md),
[`AGENT_SPEC.md`](archives/AGENT_SPEC.md), [`AGENT_SPEC_V3.md`](archives/AGENT_SPEC_V3.md),
[`ML_AGENTS_DESIGN.md`](archives/ML_AGENTS_DESIGN.md),
[`ML_AGENTS_ROADMAP.md`](archives/ML_AGENTS_ROADMAP.md),
[`ML_AGENTS_TRAINING_GUIDE.md`](archives/ML_AGENTS_TRAINING_GUIDE.md),
[`DG5F_GRASP_READY_REACH_HANDOFF.md`](archives/DG5F_GRASP_READY_REACH_HANDOFF.md),
[`DG5F_GRASP_57X7_FLOOR_SAFE_DEMO.md`](archives/DG5F_GRASP_57X7_FLOOR_SAFE_DEMO.md),
[`train_plan.md`](archives/train_plan.md)

## DG5F 비전 텔레옵

- 시작점: [`../vision/dg5f/README.md`](../vision/dg5f/README.md)
- 보정: [`../vision/dg5f/CALIBRATION_GUIDE.md`](../vision/dg5f/CALIBRATION_GUIDE.md)
- 역할: 강화학습이 목표에 도달한 뒤 DG5F 손 20관절을 조작

텔레옵의 20관절 프로토콜은 유지되지만 강화학습 observation/action과는 독립이다.

## 이력과 진단

- [`WORKLOG.md`](WORKLOG.md): 프로젝트의 누적 작업 기록과 의사결정
- [`DEBUG_OSCILLATION_20260707.md`](DEBUG_OSCILLATION_20260707.md): 초기 진동 원인 분석
- [`DEBUG_OSCILLATION_20260708.md`](DEBUG_OSCILLATION_20260708.md): 관성 수정과 최종 검증

WORKLOG의 예전 단계형 파지 기록은 당시 이력이며 현재 실행 지침이 아니다. 활성 정책
계약은 항상 `AGENT_SPEC.md`를 우선한다.
