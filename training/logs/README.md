# `training/logs/` — 학습 런의 부수 산출물

학습을 돌릴 때 스크립트와 셸이 남긴 **작은 부수 파일**들이 모이는 곳이다.
실제 학습 지표(TensorBoard 이벤트·체크포인트)는 여기가 아니라 `training/results/`에 쌓인다
(`.gitignore` 대상).

## 지금 들어 있는 것

| 파일 | 무엇 |
|---|---|
| `dg5f_v1_far360_headless_20260716_*.pid` | headless 학습 프로세스의 PID 기록 |
| `dg5f_v1_continued_gpu_20260721.stop-at-1000000.sh` | 지정 스텝에서 학습을 멈추기 위한 일회성 셸 스크립트 |
| `dg5f_v1_palm_facing_gpu_20260721.contract.txt` | 그 런의 계약(설정·기대값)을 고정해 둔 메모 |

전부 **구세대 V1 런의 기록**이다. 현재 학습 경로에서 자동으로 생성되지 않는다.

## 파일 이름 규칙

```text
<run-id>[.<용도>].<확장자>
예) dg5f_v1_palm_facing_gpu_20260721.contract.txt
```

`run-id`에 날짜를 넣어 두면 나중에 `training/results/<run-id>/`와 짝을 맞출 수 있다.

## PID 파일은 무엇에 쓰나

`mlagents_learn_compat.py`의 `_install_pid_file()`이 학습 프로세스의 PID를 남기고
`atexit`에서 정리한다. **강제 종료된 런은 PID 파일이 남는다** — 남아 있는 플레이어
프로세스를 찾아 죽일 때 단서가 된다(`train_picknplace.py`의 `kill_stale_players()`가
기본적으로 이 정리를 자동으로 한다).

## 여기 두면 안 되는 것

- **체크포인트·이벤트 파일** → `training/results/<run-id>/`
- **실패 판정과 이유** → `training/scripts/archive_run.py`로 격리하면 런 폴더 안에 `RUN.md`가
  생기고, 판정 이력의 정본은 [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md)다
- **Unity 관절 로그** → Editor는 `unity/Logs/`, 플레이어는 실행파일 옆 `Logs/`

## 관련 문서

- [`training/README.md`](../README.md) — 학습 실행과 결과 디렉터리 규칙
- [`training/scripts/README.md`](../scripts/README.md) — 런처·격리 도구
- [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md) — 런 판정 이력(정본)

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/logs/README.md`
- **갱신 대상**: `training/logs/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `training/scripts/README.md`
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

