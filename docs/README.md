# 문서 인덱스

## 디렉터리별 README

각 폴더에 그 폴더의 코드를 파일 단위로 설명하는 README가 있다. 전체 목록은 리포 루트
[`README.md`](../README.md)의 "디렉터리별 README 지도"에 있다. 모듈 문서와의 역할 분담은
[`modules/README.md`](modules/README.md)를 본다.

용어 표기의 정본은 [`GLOSSARY.md`](GLOSSARY.md)다.

## 코드가 무슨 일을 하는지 (모듈 지도)

- **[`MODULE_GUIDE.md`](modules/MODULE_GUIDE.md)** — 전체 데이터 흐름 + 영역별 문서 입구.
  "이 스크립트 왜 있지?" 싶을 때 여기부터.
  - [Unity](modules/UNITY.md) · [강화학습](modules/RL_TRAINING.md) ·
    [비전/텔레옵](modules/VISION_TELEOP.md) · [실물 브리지](modules/REAL_BRIDGES.md) ·
    [설정·빌드 도구](modules/BUILD_TOOLING.md)

## DG5FPicknPlace 강화학습 (현재 개발 기준: UR16e + 오른손)

- **현재 구조와 계약 요약**: [`modules/RL_TRAINING.md`](modules/RL_TRAINING.md) — 관찰·행동·성공 조건·현재 한계
- **실행 절차**: [`../training/README.md`](../training/README.md)
- **이식·설계 이력**: [`DG5F_PICKNPLACE.md`](DG5F_PICKNPLACE.md) — GraspLift에서 바뀐 점
- **이전 세대 기준선**: [`DG5F_GRASP_LIFT.md`](DG5F_GRASP_LIFT.md) — UR5e + 왼손의 설계와 실험
- **실물 이관 계획**: [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md) — 단계별 순서와 리스크
- 발표자료: [`GRASP_LIFT_발표자료.md`](docs2/GRASP_LIFT_발표자료.md)
- 설명: [`GRASP_LIFT_설명.md`](docs2/GRASP_LIFT_설명.md)

현재 PicknPlace의 과제는 **파지+들어올리기**이며 운반·내려놓기는 포함하지 않는다.
RL 자동 조작과 MediaPipe 수동 조작은 제어권을 전환하는 별도 경로다.
실물에서 카메라 인식부터 자율 파지까지 연결하는 것은 후속 과제이며,
현재 구현·제한은 [`MODULE_GUIDE.md`](modules/MODULE_GUIDE.md)를 먼저 확인한다.

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
- 역할: 웹캠의 사람 손 동작으로 DG5F 손 20관절을 수동 조작. RL 실행 없이도 사용 가능

텔레옵의 20관절 프로토콜은 유지되지만 강화학습 observation/action과는 독립이다.

## 이력과 진단

- [`WORKLOG.md`](archives/WORKLOG.md): 프로젝트의 누적 작업 기록과 의사결정
- [`DEBUG_OSCILLATION_20260707.md`](archives/DEBUG_OSCILLATION_20260707.md): 초기 진동 원인 분석
- [`DEBUG_OSCILLATION_20260708.md`](archives/DEBUG_OSCILLATION_20260708.md): 관성 수정과 최종 검증

WORKLOG와 archives의 정책 계약은 당시 이력이며 현재 실행 지침이 아니다.
현재 계약 요약은 `modules/RL_TRAINING.md`, 구현 기준은
[`Dg5fPicknPlaceSpec.cs`](../unity/Assets/MLAgents/picknplace/Runtime/Dg5fPicknPlaceSpec.cs)와
[`Dg5fPicknPlaceAgent.cs`](../unity/Assets/MLAgents/picknplace/Runtime/Dg5fPicknPlaceAgent.cs)다.
2026-09-07 문서 대조는 코드·씬 설정 기준이며 실물 재시험을 뜻하지 않는다.
