# 문서 인덱스

**무엇부터 읽어야 하는지**를 정하는 곳이다. 여기 없는 문서는
[`archives/`](archives/README.md)에 있고, 그건 **읽지 않아도 되는 것**이다.

> 직전 세션이 어디까지 했는지는 여기가 아니라 [`../claudeDocs/`](../claudeDocs/README.md)에 있다.
> 새 대화는 거기부터 읽는다(최상위 [`CLAUDE.md`](../CLAUDE.md) 원칙 5).

---

## 1. 지금 무엇이 현행인가 — 이것만은 헷갈리지 말 것

**파지 강화학습은 2026-09-09에 Unity 에서 SuperDex 로 옮겨갔다.**
Unity 는 버려진 게 아니라 **디지털 트윈·시각화·ROS2 통합**을 계속 맡는다.

| 무엇 | 현행 | 어디에 |
|---|---|---|
| 파지 학습(강화학습) | **SuperDex** (파이썬 3.12, `superdex/.venv/`) | [`SUPERDEX_POC_PLAN.md`](SUPERDEX_POC_PLAN.md) |
| 로봇을 화면에 띄우고 실물과 잇는 것 | **Unity** | [`modules/UNITY.md`](modules/UNITY.md) |
| 손동작으로 로봇 손 조작 | **웹캠 + MediaPipe** | [`modules/VISION_TELEOP.md`](modules/VISION_TELEOP.md) |
| Unity 안의 파지 학습(`DG5FPicknPlace`) | **이전 세대** — 코드는 남아 있지만 새로 학습하지 않는다 | 아래 §5 |

---

## 2. 최상위 정본 — 순서대로

| 순서 | 문서 | 무엇이 들어 있나 |
|---|---|---|
| 1 | [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md) | **최상위 정본.** 확정된 구조, 단계별 계획, 위험 요소. 다른 문서와 다르면 이게 맞다 |
| 2 | [`SUPERDEX_POC_PLAN.md`](SUPERDEX_POC_PLAN.md) | **파지 학습의 정본.** §0 에 판정·실측값·재현 명령·함정이 전부 있다 |
| 3 | [`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md) | **무엇을 보고 무엇을 움직이는가의 계약.** §0-2 가 "어디까지를 할 수 있다고 보는가"의 정의 |
| 4 | [`PYTHON_ENV_SETUP.md`](PYTHON_ENV_SETUP.md) | 새 컴퓨터에서 바로 시작하기. **윈도우와 리눅스 둘 다** 다룬다 |

## 3. 골라 읽는 문서

| 문서 | 언제 읽나 |
|---|---|
| [`GLOSSARY.md`](GLOSSARY.md) | 용어를 어떻게 적을지 정할 때. **표기의 정본** |
| [`GRASP_POINT_ARCHITECTURE.md`](GRASP_POINT_ARCHITECTURE.md) | "어디를 잡을지 스스로 정하게" 하는 구조를 왜 이렇게 골랐는지. **2026-09-10 채택됨** — 계약 자체는 위 `RL_POLICY_REDESIGN.md` v6 에 들어갔고, 이 문서는 **고른 이유의 기록**이다 |
| [`../ai_festa_plan.md`](../ai_festa_plan.md) | **11월 전시** 준비. 기한이 있는 유일한 묶음이다 |
| [`advice/`](advice/) | **바깥 조언자에게 물어서 받은 답의 전문.** 요약은 `claudeDocs/daily/` 에 있고 여기엔 줄이지 않은 원문을 둔다. ⚠️ **조언이지 정본이 아니다** — 우리가 직접 돌려서 확인하기 전까지는 |

## 4. 코드가 무슨 일을 하는지 — [`modules/`](modules/README.md)

"이 스크립트 왜 있지?" 싶을 때. 입구는 **[`MODULE_GUIDE.md`](modules/MODULE_GUIDE.md)** 다.

[Unity](modules/UNITY.md) · [Unity 안의 학습](modules/RL_TRAINING.md) ·
[비전/손동작](modules/VISION_TELEOP.md) · [실물 브리지](modules/REAL_BRIDGES.md) ·
[설정·빌드 도구](modules/BUILD_TOOLING.md) ·
[그리퍼 관절 한계](modules/DG5F_JOINT_RANGES.md) ·
**[그림 9장으로 보기](modules/ARCHITECTURE.md)**

> 🔶 `modules/` 는 **2026-09-07** 기준이라, 강화학습을 Unity 일로 설명한다.
> 파지 학습은 2026-09-09 에 SuperDex 로 옮겨갔다 — 각 문서 맨 위에 안내를 달아 두었다.

**값이 서로 다르면 코드가 맞다.** 그다음이 모듈 문서, 그다음이 폴더별 README 다.

## 5. 이전 세대지만 아직 살아 있는 것 — 지우면 안 되는 이유

아래 둘은 **Unity 안의 파지 학습(`DG5FPicknPlace`)** 시절 문서다. 새로 학습하지는 않지만,
**지금 돌아가는 스크립트가 이 문서를 근거로 인용**하고 있어서 archives 로 보내지 않았다.

| 문서 | 누가 아직 쓰나 |
|---|---|
| [`DG5F_PICKNPLACE.md`](DG5F_PICKNPLACE.md) | `training/scripts/picknplace_monitor.py` 의 상수 근거, [`modules/RL_TRAINING.md`](modules/RL_TRAINING.md) |
| [`TRAINING_RUN_LEDGER.md`](TRAINING_RUN_LEDGER.md) | 학습 런 판정 기준(게이트)의 정본 — `training/scripts/` 여러 곳이 주석으로 가리킨다 |

## 6. 사람에게 설명하는 문서 — [`docs2/`](docs2/README.md)

계약서가 아니라 **설명하려고 쓴 글**이다. 지금 남은 3개는 전부 **실물 손(DG-5F)** 관련이라
아직 쓸모가 있다.

| 문서 | 언제 읽나 |
|---|---|
| [`TESOLLO_SDK_기술부채_조사.md`](docs2/TESOLLO_SDK_기술부채_조사.md) | **실물 손이 연결 안 될 때 제일 먼저.** DG-5F 는 전체에서 TCP 연결을 하나만 받는다(2026-08-31 실측) |
| [`TESOLLO_SDK_설명.md`](docs2/TESOLLO_SDK_설명.md) | 손 브리지를 손볼 때 |
| [`ONNX_인계_설명.md`](docs2/ONNX_인계_설명.md) | 학습 결과 파일(ONNX)만 받아서 써야 할 때 |

## 7. 안 읽어도 되는 것 — [`archives/`](archives/README.md)

**현재 실행 지침으로 쓰지 않는다.** 그대로 따라 하면 없는 파일을 찾다 막힌다.
필요한 건 숫자와 절차가 아니라 **결론과 그 이유**뿐이다.

무엇이 왜 거기 있는지는 [`archives/README.md`](archives/README.md)가 설명한다.

---

## 문서를 고칠 때

- 문서에 적은 **파일 경로·스크립트 이름이 실제로 있는지 확인한다**(최상위 `CLAUDE.md` 원칙 2).
  없는 경로를 남기면 새 컴퓨터에서 그대로 따라 하다 막힌다.
- 과거 기록의 "현재"는 **그 문서가 쓰인 때의 현재**다. 오늘의 상태로 읽지 않는다.
- 사용자가 읽을 문장은 **전문용어 없이** 쓴다(원칙 4). 용어 표기는
  [`GLOSSARY.md`](GLOSSARY.md)를 따른다.
- 문서를 archives 로 옮겼으면 **그 문서를 가리키던 링크도 같이 고친다.**

## 문서 이력

| 변경 일자 | 변경 내용 | 변경 사유 |
|---|---|---|
| 2026-09-16 | 인덱스 전면 개정. 구세대 6개를 `archives/`로 이동 | 인덱스가 Unity 파지 학습을 "현재 개발 기준"으로 안내하고 있었으나 파지 학습은 2026-09-09 에 SuperDex 로 이관됐다. SuperDex 문서가 인덱스에 아예 없어 새 세션이 폐기된 경로를 붙잡는 상태였다 |
| 2026-09-07 | 최초 작성 | — |
