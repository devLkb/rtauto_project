# ⛔ `training/archives/` — 폐기된 behavior의 설정·스크립트·실패 기록

**여기 있는 것을 현재 실행 지침으로 쓰지 않는다.** 지금 동작하지 않거나, 동작하더라도
현재 하드웨어·behavior와 맞지 않는다. 남겨 둔 이유는 하나다 — **왜 그렇게 했고 왜 실패했는지**를
나중에 다시 물을 수 있게 하기 위해서다.

현재 실행 지침은 [`training/README.md`](../README.md)다.

## 구조

```text
training/archives/
├── config/       폐기된 학습 설정 YAML   → config/README.md
├── scripts/      폐기된 실행 셸 스크립트 → scripts/README.md
└── V2_*.md       V2 학습 실패 기록 5건
```

## 실패 기록 5건 — 파일 이름이 곧 결론이다

| 파일 | 무엇이 실패했나 |
|---|---|
| `V2_CLOSURE_FAILED.md` | 폐합(closure) 접근 실패 |
| `V2_HANDFIRST_STALEBUILD_FAILED.md` | hand-first 실험이 **낡은 빌드로 학습**돼 무효가 된 건 |
| `V2_HANDFIRST2_GATE_STOPPED.md` | hand-first 2차가 게이트에서 중단 |
| `V2_JOINT26_LR1E4_FAILED.md` | joint26, 학습률 1e-4 실패 |
| `V2_JOINT26_LR5E5_FAILED.md` | joint26, 학습률 5e-5 실패 |

> `V2_HANDFIRST_STALEBUILD_FAILED.md`의 교훈은 지금도 유효하다: **코드를 바꿨는데 지표가
> 그대로라면 기존 빌드로 학습 중인지부터 의심한다.** 학습 씬·에이전트 코드는 플레이어에
> 구워지므로 재빌드 없이는 반영되지 않는다.

전체 분석은 [`docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md`](../../docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md)에 있다.

## `scripts/` — 왜 실행되지 않나

전용 GPU Linux 학습서버(`/root/venvs/ax310`, `tmux`·`xvfb-run`·`setsid` 전제) 전용 스크립트였다.
**그 서버가 폐지되고 지금은 로컬 단독 머신뿐이라 애초에 실행이 안 된다.**
상세는 [`scripts/README.md`](scripts/README.md).

`--transfer` 전이는 이제 `training/scripts/prepare_dg5f_grasp_lift_transfer.py`를 직접 호출해
준비한다.

## `config/` — 폐기된 설정

폐기된 behavior(ReadyReach, grasp v2/v3, surface-hold 커리큘럼)의 YAML이다.
상세는 [`config/README.md`](config/README.md).

⚠️ `training/tests/`의 여러 테스트가 **이미 삭제된** 이 계열 설정 파일을 아직 참조해
`FileNotFoundError`로 실패한다 — [`training/tests/README.md`](../tests/README.md) §3 참고.

## 이 폴더를 다룰 때의 규칙

1. **새 작업의 출발점으로 삼지 않는다.** 현역은 `training/config/dg5f_picknplace.yaml`과
   `training/scripts/train_picknplace.py`다.
2. **문서에 여기 경로를 실행 지침으로 적지 않는다.** 새 PC 사용자가 그대로 따라 하다 막힌다
   (CLAUDE.md 원칙 2 위반).
3. **지우지 않는다.** 실패의 이유가 지금의 설계 규칙(예: 페널티 크기 상한)의 근거다.

## 관련 문서

- [`training/README.md`](../README.md) — 현재 실행 지침(정본)
- [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md) — 런 판정 이력
- [`docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md`](../../docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md) — V2 실패 분석
- [`docs/archives/`](../../docs/archives/) — 폐기된 behavior의 설계 문서

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/archives/README.md`
- **갱신 대상**: `training/archives/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/TRAINING_RUN_LEDGER.md`
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

