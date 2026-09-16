# ⛔ `docs/archives/` — 폐기된 세대의 설계 문서와 작업 기록

**여기 있는 문서를 현재 실행 지침으로 쓰지 않는다.** 폐기된 behavior
(`DG5FGraspReadyReach`, 구세대 `DG5FGrasp`/`DG5FStableGrasp`)의 계약과, 그 시절의 설명·발표물이다.
해당 Unity 씬·코드는 이미 삭제됐고, 그대로 따라 하면 없는 파일을 찾다 막힌다.

**지금 무엇이 현행인지는 [`docs/README.md`](../README.md) §1 이 정리한다.**
짧게 적으면 — 파지 학습은 2026-09-09 에 Unity 에서 **SuperDex** 로 옮겨갔고
([`SUPERDEX_POC_PLAN.md`](../SUPERDEX_POC_PLAN.md)), 로봇 하드웨어도 UR5e + 왼손 에서
**UR16e + 오른손** 으로 바뀜다. 여기 문서 대부분은 **둘 다 바뀌기 전**에 쓴 것이다.

## 무엇이 들어 있나

### 폐기된 behavior의 계약·설계

| 문서 | 내용 |
|---|---|
| `AGENT_SPEC.md` · `AGENT_SPEC_V3.md` | 구세대 에이전트 계약(관찰·행동·보상) |
| `ML_AGENTS_DESIGN.md` | 학습 구조 설계 |
| `ML_AGENTS_LEARNING_FLOW.md` | 학습 흐름 |
| `ML_AGENTS_ROADMAP.md` | 당시 로드맵 |
| `ML_AGENTS_TRAINING_GUIDE.md` | 당시 학습 실행 가이드 |
| `train_plan.md` | 학습 계획 |
| `DG5F_GRASP_READY_REACH_HANDOFF.md` | ReadyReach(팔 이동만) 인계 |
| `DG5F_GRASP_57X7_FLOOR_SAFE_DEMO.md` | 57관찰/7행동 바닥 안전 데모 |
| `DG5F_PREGRASP_ANGLE_RESULT.md` · `DG5F_PREGRASP_REWARD_AND_TELEOP_HANDOFF.md` | 프리그래스프 실험 결과·인계 |
| `THUMB_RETARGET_20260714.md` | 엄지 리타게팅 작업 |
| `DG5F_GRASP_LIFT.md` | **구세대 GraspLift(UR5e + 왼손)의 설계·보상·판정 근거.** 관찰 57 / 행동 7 |
| `DG5F_TOPDOWN_TRANSFER.md` | 구세대 `DG5FGrasp` 위에서 손바닥을 아래로 향하게 재학습한 기록 |
| `V2_TRAINING_FAILURE_ANALYSIS_20260717.md` | V2 실패 학습 3건의 원인 구분 분석 |

### 진단 기록 — 지금도 읽을 가치가 있는 것

| 문서 | 왜 남겼나 |
|---|---|
| `DEBUG_OSCILLATION_20260707.md` | **초기 진동 원인 분석.** 자기충돌 무시·초기 포즈 동기화가 왜 필요한지의 원 기록 |
| `DEBUG_OSCILLATION_20260708.md` | 관성 수정과 최종 검증. 임포터 기본 관성(1kg/(1,1,1)) 함정의 근거 |

이 두 건의 결론은 현재 코드
(`RobotSelfCollisionIgnore.cs` · `RobotInitialPoseSync.cs` · `phys_compare.py`)에 반영돼 있다 →
[`unity/Assets/Scripts/README.md`](../../unity/Assets/Scripts/README.md) §3.

### 설명·발표물 — 구세대 기준

원래 `docs/docs2/` 에 있던 것을 2026-09-16 에 옮겨 왔다. 내용이 틀려서가 아니라
**그 시절의 사실**이기 때문이다 — 지금 읽으면 현행 구성으로 오해한다.

| 문서 | 내용 | 왜 지금 쓰지 않나 |
|---|---|---|
| `GRASP_LIFT_발표자료.md` | GraspLift 결과 발표 원고 | UR5e + 왼손 결과다 |
| `GRASP_LIFT_설명.md` | GraspLift 과제를 서술형으로 풀어 쓴 설명 | 〱 |
| `기술선택_설명.md` | "왜 이 기술을 골람는가" | **UR5e 전제**이고, 파지 학습을 Unity 가 맡는다는 전제로 쓰였다. 둘 다 바뀜다 |

현재의 기술 선택 근거는 [`SIM2REAL_ROADMAP.md`](../SIM2REAL_ROADMAP.md) 와
[`SUPERDEX_POC_PLAN.md`](../SUPERDEX_POC_PLAN.md) §1 이다.

### 작업 기록

| 문서 | 내용 |
|---|---|
| `WORKLOG.md` | 프로젝트의 누적 작업 기록과 의사결정 |
| `KSJ_20260721_WORKLOG.md` | 개인 작업 기록 |
| `PROJECT_HANDOFF.md` | 과거 인계 문서 |
| `GraspClaude.md` | 파지 관련 작업 메모 |

## 읽을 때의 규칙

1. **"현재"라고 쓰인 문장은 그 문서가 쓰인 시점의 현재다.** 오늘의 구현 상태로 읽지 않는다.
2. **경로·스크립트명이 지금도 존재한다고 가정하지 않는다.** 대부분 삭제됐다.
3. 유용한 것은 **결론과 그 근거**다 — 숫자와 절차가 아니라.
4. 여기 내용을 다시 쓰려면 **현재 코드로 재확인**한 뒤 현역 문서에 옮긴다.

## 관련 문서

- [`docs/README.md`](../README.md) — 문서 인덱스
- [`docs/modules/`](../modules/README.md) — 현재 코드의 모듈 설명
- [`training/archives/README.md`](../../training/archives/README.md) — 폐기된 설정·스크립트

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |
| v1.1 | 2026-09-16 | devlkb | 구세대 문서 6개 편입(GraspLift 계약·발표물·기술선택 설명 등) | `docs/` 최상위와 `docs2/` 에 폐기된 세대의 문서가 섮여 있어 새 세션이 현행으로 오해했다 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- docs/archives/README.md`
- **갱신 대상**: `docs/archives/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/README.md`
- **용어는 [`GLOSSARY`](../GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

