# `training/scripts/` — 학습 실행·감시·정리 스크립트

학습을 **시작하고, 잘 되고 있는지 판정하고, 끝난 런을 정리하는** 파이썬 도구 모음이다.
학습 과제 자체(관찰·행동·보상)는 Unity에 있다 →
[`unity/Assets/MLAgents/README.md`](../../unity/Assets/MLAgents/README.md).
실행 절차 전체는 [`training/README.md`](../README.md)가 정본이다.

## 목차

1. [파일 한눈에 보기](#1-파일-한눈에-보기)
2. [학습 실행 — `train_picknplace.py`](#2-학습-실행--train_picknplacepy)
3. [ONNX 내보내기 래퍼 — `mlagents_learn_compat.py`](#3-onnx-내보내기-래퍼--mlagents_learn_compatpy)
4. [학습 감시·판정 — `picknplace_monitor.py`](#4-학습-감시판정--picknplace_monitorpy)
5. [끝난 런 격리 — `archive_run.py`](#5-끝난-런-격리--archive_runpy)
6. [정책 이어받기(transfer) 3종](#6-정책-이어받기transfer-3종)
7. [환경 검증 — `validate_unity_environment.py`](#7-환경-검증--validate_unity_environmentpy)
8. [⛔ 구세대 모니터 3종](#8--구세대-모니터-3종)
9. [관련 문서](#9-관련-문서)

## 1. 파일 한눈에 보기

| 파일 | 줄 수 | 상태 | 역할 |
|---|---|---|---|
| `train_picknplace.py` | 216 | **현역** | 학습 런처 (headless 병렬) |
| `mlagents_learn_compat.py` | 126 | **현역** | `mlagents-learn` 엔트리포인트 래퍼 |
| `picknplace_monitor.py` | 273 | **현역** | 진행 상황 출력 + 게이트 판정 |
| `archive_run.py` | 165 | **현역** | 끝난 런을 `failure/`·`legacy/`로 격리 |
| `prepare_dg5f_grasp_lift_transfer.py` | 278 | 전이 | 체크포인트를 새 behavior 이름 아래로 복사 |
| `bootstrap_v1_to_joint26.py` | 376 | 전이(구) | 57/7 정책을 116/26으로 확장 |
| `prepare_hold_curriculum_init.py` | 60 | 전이(구) | 새 관찰 슬롯의 노이즈를 낮춘 체크포인트 |
| `validate_unity_environment.py` | 118 | 보조 | 플레이어·설정·manifest 해시 대조 |
| `grasp_metrics.py` | 489 | ⛔ 구세대 | `Reach/*`·`Grasp/*` 태그 전용 |
| `show_dg5f_metrics.py` | 163 | ⛔ 구세대 | V1 지표 출력 |
| `dg5f_status.py` | 120 | ⛔ 구세대 | 최신 scalar 출력 |

## 2. 학습 실행 — `train_picknplace.py`

### 왜 `mlagents-learn`을 직접 치지 않는가

두 가지 이유가 있고 둘 다 **새 PC에서 반드시 문제가 되는 것**이다.

1. **플레이어 경로·포트·병렬 수가 머신마다 다르고 그 정본은 `.env`다**(원칙 1).
   명령줄에 경로를 손으로 적기 시작하면 어긋난다.
2. **ml-agents는 설정 yaml을 로케일 기본 인코딩으로 읽는다.** 한국어 Windows(cp949)에서는
   주석에 em-dash나 한글이 하나만 있어도 `UnicodeDecodeError`로 죽는다 — 이 저장소의 설정
   파일들은 둘 다 쓴다. 런처는 파이썬을 **`-X utf8`로 띄워** 로케일과 무관하게 UTF-8로 읽게 한다.

### 실행 인자

```text
python training/scripts/train_picknplace.py --run-id <이름> [옵션…]
```

| 인자 | 기본값 | 출처·설명 |
|---|---|---|
| `--run-id` | **필수** | — |
| `--config` | `training/config/dg5f_picknplace.yaml` | `DEFAULT_CONFIG` |
| `--num-envs` | `.env`의 `RTAUTO_TRAIN_NUM_ENVS` | 동시 플레이어 수 |
| `--base-port` | 5100 | `cfg.PORT_MLAGENTS_BASE` |
| `--results-dir` | `training/results` | `cfg.TRAINING_RESULTS_DIR` |
| `--max-steps` | (yaml 값) | yaml의 `max_steps`만 바꾼 사본을 만들어 넘긴다(스모크 테스트용) |
| `--editor` | off | 빌드 없이 Unity Editor에 붙는다(환경 항상 1개) |
| `--graphics` | off | 기본은 `--no-graphics`(headless) |
| `--resume` / `--force` | off | 이어서 / 덮어쓰기 |
| `--timeout-wait` | 600 | `DEFAULT_TIMEOUT_WAIT` |
| `--keep-stale-players` | off | 기본은 **남아 있는 플레이어 프로세스를 먼저 죽인다** |
| `--dry-run` | off | 명령만 출력 |
| `passthrough` | — | 나머지 인자는 `mlagents-learn`에 그대로 전달 |

### 내부 단계

| 함수 | 하는 일 |
|---|---|
| `resolve_player()` | `cfg.picknplace_player_path()`로 플레이어 경로 확정(없으면 안내 후 실패) |
| `kill_stale_players(player)` | 이전 런이 남긴 플레이어 프로세스 정리 — ml-agents가 종료 시 워커를 놓치는 일이 잦고, 살아남은 프로세스가 다음 런의 CPU를 갉아먹는다 |
| `resolve_config(args)` | `--max-steps`가 있으면 `training/results/<run-id>_config.yaml` 사본 생성 |
| `build_command(args)` | `python -X utf8 mlagents_learn_compat.py …` 형태로 조립 |

### 알아둘 것

- **총 에이전트 수 = `DG5F_PICKNPLACE_TRAINING_AREAS`(빌드에 구워진 값, 기본 40) × `--num-envs`.**
  영역 수는 `.env`만 고쳐선 안 바뀐다(씬 재생성 → 재빌드 필요).
- `--num-envs`는 **머신마다 측정해서 정한다.** 물리코어보다 많이 띄우면 플레이어들이 트레이너와
  CPU를 다퉈 오히려 느려진다. 측정 예:
  `--run-id bench6 --num-envs 6 --max-steps 300000 --force` 후
  `training/results/bench6/run_logs/timers.json`의 `TrainerController.start_learning`으로 step/s 계산.
- **트레이너를 강제 종료하면** `run_logs/training_status.json`이 안 써져 `--resume` 시 커리큘럼
  lesson이 첫 단계로 되돌아간다(정책 가중치는 체크포인트에서 그대로 이어진다).
- GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 확인한다 — `cpu`로 두면 이 ml-agents
  dev 빌드의 전역 디바이스 버그로 죽는다.

## 3. ONNX 내보내기 래퍼 — `mlagents_learn_compat.py`

`train_picknplace.py`가 `mlagents-learn` 대신 **엔트리포인트로 부르는 파일**이다.

**무엇을 고치나**: 최신 CUDA PyTorch의 `torch.onnx.export` 기본 경로는 **dynamo exporter**인데,
그 경로는 onnxscript와 더 새로운 ONNX를 요구한다. ML-Agents 1.2.0.dev0의 exporter는 legacy
경로로 작성돼 있어, 그대로 두면 **학습이 다 끝난 뒤 모델 저장에서 실패한다.**

`_legacy_onnx_export(*args, **kwargs)`가 legacy 경로를 명시적으로 선택하도록 감싸며,
비전·protobuf 의존성 고정을 건드리지 않는다. `_install_pid_file()`은 PID 파일을 남겨
`atexit`에서 정리한다.

> 직접 `mlagents-learn`을 쓰려면 **같은 조치를 직접 해야 한다.**

## 4. 학습 감시·판정 — `picknplace_monitor.py`

학습은 몇 시간씩 걸린다. "지금 잘 되고 있나"를 사람이 눈으로 판단하지 않게 만드는 도구다.

```text
python training/scripts/picknplace_monitor.py --run-id <이름>          # 진행 상황 출력
python training/scripts/picknplace_monitor.py --run-id <이름> --gate   # 게이트 판정, 실패 시 종료코드 1
python training/scripts/picknplace_monitor.py --run-id <이름> --json   # 기계 판독용
```

behavior 상수는 `BEHAVIOR = "DG5FPicknPlace"`이고, `METRICS` 표의 태그는
`Dg5fPicknPlaceAgent.RecordOutcome`이 쓰는 태그와 **1:1**이다.

### 출력하는 지표(`METRICS`)

| 표시명 | 태그 | 단위 |
|---|---|---|
| 누적 보상 / 에피소드 길이 | `Environment/Cumulative Reward` · `Episode Length` | — / step |
| 성공률 | `PicknPlace/Success` | % |
| 파지 확정률 | `PicknPlace/GraspConfirmed` | % |
| 접촉 손가락 수 | `PicknPlace/ContactCount` | 개 |
| 종료 거리 | `PicknPlace/FinalDistanceMeters` | cm |
| 최고/최종 리프트 높이 | `BestLiftHeight` · `FinalLiftHeight` | cm |
| 리프트 유지 시간 / 완료 시간 | `LiftHoldSeconds` · `CompletionSeconds` | s |
| 손바닥-물체 정렬 최대 | `MaxPalmFacingAlignment` | — |
| 하향 파지각 | `TopDownAngleDegrees` | ° |
| 엄지 깊이 | `ThumbBelowOtherTipsMeters` | cm (**0 이하가 정상**) |
| 물체 (최대) 기울기 | `ObjectTiltDegrees` · `MaxObjectTiltDegrees` | ° (10° 이하 무료 구간) |
| 손-바닥 접촉 시간 | `HandSurfaceContactSeconds` | s |
| 팔 액션 변화율 | `MeanArmActionRate` | — |
| 커리큘럼 단계 | `Environment/Lesson Number/grasp_stage` | — |
| 정책 엔트로피 / 가치 추정 | `Policy/Entropy` · `Policy/Extrinsic Value Estimate` | — |

실패 태그는 `Failure/` 접두사로 합계를 읽는다.

### 4개 게이트(`GATES`) — 임계값 근거는 [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md)

| 게이트 | 스텝 | 태그 | 최소 | 못 넘기면 |
|---|---|---|---|---|
| **G1 접근** | 300k | `MaxPalmFacingAlignment` | > 0.0 | 손바닥이 물체를 한 번도 향하지 않으면 접근 그래디언트 자체가 없다 = **정지 정책 데드락** |
| **G2 접촉** | 800k | `ContactCount` | > 0.20 | 평균 0.2개 손가락도 못 건드리면 파지 학습이 시작조차 안 됨 |
| **G3 파지** | 2M | `GraspConfirmed` | > 0.05 | 파지 계약(대향각/케이지)이 이 손·큐브 조합에서 성립하지 않는다는 신호 |
| **G4 성공** | 4M | `Success` | > 0.10 | 남은 스텝으로 뒤집히지 않음 |

> ⚠️ **`--gate` 실패는 종료코드 1만 돌려준다. 학습 프로세스를 죽이지 않는다.**
> 자동 감시를 구성하려면 반복 호출과 종료코드를 처리하는 실행 주체를 따로 만들어야 한다.

주요 함수: `load_scalars(dir)` · `window_mean(points, count)` · `best_so_far(points)` ·
`latest_step(scalars)` · `report(scalars, window)` · `evaluate_gates(...)`.

결과를 해석할 때는 최근 보상뿐 아니라 **파지 확정·리프트 성공·실패 이유를 함께** 본다.

## 5. 끝난 런 격리 — `archive_run.py`

```text
python training/scripts/archive_run.py --run-id <이름> --to failure \
    --reason "G2 접촉 게이트 실패: 80만 스텝 ContactCount 0.00"
```

**왜 필요한가.** 실패한 정책을 `training/results/`에 쌓아두면
(a) 어느 체크포인트가 살아 있는 기준선인지 사람이 매번 다시 판단해야 하고,
(b) `--resume`이나 `--initialize-from`이 **죽은 런을 가리키는 사고**가 난다.

격리 자체보다 **왜 실패했는지를 런 옆에 남기는 것**이 이 스크립트의 핵심이다.

| 상수·인자 | 값 |
|---|---|
| `DESTINATIONS` | `{"failure": TRAINING_FAILURE_DIR, "legacy": TRAINING_LEGACY_DIR}` |
| `SUMMARY_NAME` | `RUN.md` — 런 폴더 안에 남기는 요약 문서 |
| `--run-id` / `--to` / `--reason` | 옮길 런 / 목적지 / 실패 사유 |

`find_event_directories()`로 이벤트 파일을 찾고 `final_scalars()`로 마지막 지표를 읽어
`write_summary()`가 `RUN.md`를 쓴다. 실행하면 **`docs/TRAINING_RUN_LEDGER.md`에 붙여넣을 표
행을 출력**한다 — 판정 이력의 정본은 그 문서다.

## 6. 정책 이어받기(transfer) 3종

처음부터 학습하지 않고 이미 학습된 가중치를 씨앗으로 쓰는 스크립트들이다.

### `prepare_dg5f_grasp_lift_transfer.py` (278줄)

`mlagents-learn --initialize-from RUN`은 `<results>/RUN/<behavior>/checkpoint.pt`를 찾는다.
그래서 소스 체크포인트를 **새 behavior 이름 아래로 복사**해야 한다.
**가중치는 바이트 단위 그대로 복사되고 원본은 절대 수정하지 않는다.**

| 상수 | 값 |
|---|---|
| `BEHAVIOR` | `DG5FGraspLift` |
| `EXPECTED_OBSERVATIONS` / `EXPECTED_ACTIONS` | 57 / 7 |
| `EXPECTED_HIDDEN_UNITS` / `EXPECTED_HIDDEN_LAYERS` | 256 / 3 |
| `DEFAULT_SOURCE_RUN_ID` | `dg5f_grasp_lift_transfer_source_599887` |
| `GRIP_ACTION_INDEX` | 6 |
| `DEFAULT_ARM_LOG_SIGMA` | −0.7 (σ ≈ 행동 범위의 0.50) |
| `DEFAULT_GRIP_LOG_SIGMA` | 0.0 (σ = 1.0 — **그립은 처음부터 탐색**) |

인자: `--source`(필수) · `--results-dir` · `--source-run-id` · `--arm-log-sigma` ·
`--grip-log-sigma` · `--keep-grip-head` · `--verify-only`.
`validate_checkpoint()`가 관찰·행동·은닉층 모양을 먼저 검사하고, `retune_exploration()`이
탐색 표준편차를 다시 잡는다. `sha256_file()`로 복사 무결성을 확인한다.

### `bootstrap_v1_to_joint26.py` (376줄)

구버전 57관찰/7행동 정책을 **116관찰/26행동**으로 확장한다.
출력은 `--initialize-from` 전용 런 디렉터리이며, **학습된 옵티마이저 모멘트가 없고 global step은 0**이다.

| 상수 | 값 |
|---|---|
| `SOURCE_BEHAVIOR` / `TARGET_BEHAVIOR` | `DG5FGrasp` / `DG5FGraspJoint` |
| 관찰 / 행동 | 57 → 116 / 7 → 26 |
| `DEFAULT_SEED` | 21026 |
| `EXPECTED_SOURCE_STEP` | 526647 |

가중치 키 이름을 직접 다룬다(`network_body._body_endoder.seq_layers.0.weight`,
`action_model._continuous_distribution.mu.weight/bias`, `log_sigma`, `_GlobalSteps__global_step`).
`POLICY_SHAPES`/`CRITIC_SHAPES`로 모양을 검증하고 `verify_conversion()`이 변환 결과를 재확인한다.

### `prepare_hold_curriculum_init.py` (60줄)

커리큘럼 전환용으로 **새로 추가된 관찰 슬롯(`NEW_OBSERVATION_COLUMNS = (50, 51, 52)`)의
노이즈를 낮춘** 체크포인트를 만든다. `--arm-sigma`(0.2) / `--ignored-sigma`(0.05).

## 7. 환경 검증 — `validate_unity_environment.py`

별도로 제공한 **manifest(빌드 명세 파일)** 와 플레이어·DLL의 해시, 설정의 behavior 등을 대조한다.

```text
python training/scripts/validate_unity_environment.py --env <플레이어> --config <yaml> --manifest <json>
```

`sha256(path)` · `_positive_int(manifest, key)` · `validate(environment, config, manifest_path)`.

> ⚠️ **`train_picknplace.py`가 자동 호출하지 않는다.** 필요할 때 따로 돌린다.
> 이 모듈의 테스트(`training/tests/test_validate_unity_environment.py`)는 현재 저장소에서
> 100% 통과하는 유일한 테스트라 **새 PC 설치 확인용**으로도 쓴다.

## 8. ⛔ 구세대 모니터 3종

`grasp_metrics.py` · `show_dg5f_metrics.py` · `dg5f_status.py`는 **폐기된 behavior의
`Reach/*`·`Grasp/*` 태그에 묶여 있어 현역 PicknPlace에는 쓸 수 없다.**
현역 모니터는 `picknplace_monitor.py` 하나다.

참고로 남은 판정 기준: `dg5f_status.py`의 `STAGE_ONE_GATE_STEPS = 100_000` /
`CURRICULUM_PARAMETER = "joint26_stage"` — 100k 스텝까지 커리큘럼이 첫 lesson에 머물면
즉시 중단한다는 V2 hand-first 판정이다
([`docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md`](../../docs/V2_TRAINING_FAILURE_ANALYSIS_20260717.md) §5).

## 9. 관련 문서

- [`training/README.md`](../README.md) — 학습 실행 절차(정본)
- [`training/config/README.md`](../config/README.md) — 하이퍼파라미터·커리큘럼
- [`training/tests/README.md`](../tests/README.md) — 파이썬 회귀 테스트
- [`docs/modules/RL_TRAINING.md`](../../docs/modules/RL_TRAINING.md) — RL 모듈 전체 설명
- [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md) — 런 판정 이력·게이트 근거

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/scripts/README.md`
- **갱신 대상**: `training/scripts/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `training/README.md`, `docs/modules/RL_TRAINING.md`
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

