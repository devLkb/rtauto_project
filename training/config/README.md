# `training/config/` — 학습 설정(YAML)

`mlagents-learn`에 넘기는 **PPO 하이퍼파라미터 + 커리큘럼 + 환경 파라미터**다.
**파일 이름이 곧 실험 이름**이며, 파일 상단 주석에 "왜 이 값인지"가 측정 수치와 함께 적혀 있다.

과제 자체의 상수(무엇이 성공인가)는 여기가 아니라 Unity의 `Dg5fPicknPlaceSpec.cs`에 있다 →
[`unity/Assets/MLAgents/README.md`](../../unity/Assets/MLAgents/README.md) §5.

## 목차

1. [파일 이름 읽는 법](#1-파일-이름-읽는-법)
2. [현역 설정 — `dg5f_picknplace.yaml`](#2-현역-설정--dg5f_picknplaceyaml)
3. [YAML이 갈아끼울 수 있는 값과 없는 값](#3-yaml이-갈아끼울-수-있는-값과-없는-값)
4. [커리큘럼 구조](#4-커리큘럼-구조)
5. [GraspLift 계열 설정 목록](#5-grasplift-계열-설정-목록)
6. [평가 전용(`*_eval_*`) 설정](#6-평가-전용_eval_-설정)
7. [새 실험 설정을 만들 때](#7-새-실험-설정을-만들-때)
8. [관련 문서](#8-관련-문서)

## 1. 파일 이름 읽는 법

```text
dg5f_<behavior>[_eval]_<실험 이름>.yaml
```

| 조각 | 뜻 |
|---|---|
| `picknplace` | 현역 behavior `DG5FPicknPlace` (UR16e + 오른손) |
| `grasp_lift` | 구세대 behavior `DG5FGraspLift` (UR5e + 왼손) |
| `_eval_` | **평가 전용** — `--resume --inference`로 돌려 학습이 일어나지 않는다 |
| `t1`~`t4` | top-down 보상 계수 스윕 (1.50 / 3.00 / 2.25 / 1.50 long) |
| `s1`~`s4` | 자세·긁힘·행동률 페널티 스윕 |
| `com020`/`com030`/`com050` | 물체 무게중심 높이 비율 (0.20 / 0.30 / 0.50) |
| `h012` | 물체 높이 0.12 m |
| `probe_*` | 진단용 짧은 프로브 |

## 2. 현역 설정 — `dg5f_picknplace.yaml`

behavior `DG5FPicknPlace`, trainer `ppo`.

### 하이퍼파라미터

| 항목 | 값 | 왜 |
|---|---|---|
| `batch_size` / `buffer_size` | 4096 / 40960 | GraspLift의 2048/20480에서 **함께 2배**. 20영역 런에서 GPU 사용률이 ~17%에 그쳐(병목은 PPO 업데이트가 아니라 환경 처리량) 업데이트의 상대적 모양(buffer:batch 비, epoch)을 유지한 채 스케일업 |
| `learning_rate` / `schedule` | 3e-4 / `linear` | |
| `beta` / `beta_schedule` | 0.01 / `constant` | |
| `epsilon` / `lambd` / `num_epoch` | 0.2 / 0.95 / 3 | |
| `normalize` | **false** | |
| `hidden_units` × `num_layers` | 256 × 3 | 전이 스크립트가 이 모양을 검증한다 |
| `gamma` | **0.995** | **리프트 보상이 파지 후 최대 ~10초 뒤에 오므로** 할인 지평을 길게 |
| `time_horizon` | 256 | |
| `max_steps` | **20,000,000** | 5M은 buffer 40960 기준 ~122회 PPO 업데이트뿐이라 파지 커리큘럼에 얇았다. 20M이면 ~488회이면서 여전히 며칠이 아닌 몇 시간 |
| `keep_checkpoints` / `checkpoint_interval` | 20 / 200,000 | |
| `summary_freq` | 5000 | |
| `threaded` | false | |
| `torch_settings.device` | **`cuda`** | ⚠️ GPU 머신에서 `cpu`로 두면 이 ml-agents dev 빌드가 죽는다(프로세스 전역 디바이스를 되돌리지 못함) |

### `num_envs`는 추측이 아니라 측정값이다

**집 머신**(RTX 4070 Ti / 32 GB / Ryzen 7 7800X3D, **8C**/16T)에서 300k 스텝 런으로 측정:

| envs | 4 | 6 | 8 | **10** | 12 |
|---|---|---|---|---|---|
| steps/s | 1643 | 1932 | 2206 | **2390** | 2266 |

10을 조금 넘기면 플레이어들이 트레이너와 **8 물리코어를 다투기 시작**해 처리량이 꺾인다.
`10 envs × 40 영역 = 400 에이전트`이며, 이때 20M 스텝이 약 2.5시간이다.

> ⚠️ **이 10은 회사 머신에 그대로 쓸 수 없다 (2026-09-07).** 위 측정의 꺾이는 지점은
> **물리코어 8개**에서 나온 것이고, 주 작업 환경인 회사 머신은 **Ryzen 5 7600 = 물리코어
> 6개**(RTX 2080 8 GB / 32 GB)다. 코어가 2개 적으므로 처리량은 **10보다 이른 지점에서
> 꺾인다** — 6~8 부근을 다시 측정해야 한다. 값 자체는 `.env`의 `RTAUTO_TRAIN_NUM_ENVS`로
> 빠져 있어 코드 수정은 필요 없지만(원칙 1), **회사 머신에서 10을 쓰면 트레이너와 코어를
> 다퉈 느려진다.** 머신 목록은 [`../../docs/SIM2REAL_ROADMAP.md`](../../docs/SIM2REAL_ROADMAP.md)
> 상단 v15.1 참고.

> **에이전트 수를 늘렸다고 batch/buffer를 다시 키우지 않았다.** 검증된 업데이트 모양
> (buffer:batch 비, epoch, horizon)을 그대로 두고 **버퍼를 채우는 실제 시간만 줄인 것**이다.

### 환경 파라미터 2개 — 값보다 이력이 중요하다

**`thumb_down_penalty_scale: -0.05`**

요구사항은 "엄지가 작업면을 향하면 안 된다"이다(나중 pick-and-place 단계에서 플랫폼 옆에
놓아야 하므로). 그런데 이 항목은 **두 번 틀렸다.**

1. 원래 판독은 **각도**(엄지 base→tip vs 수직 아래, 60° 초과 무료)에 −0.10/결정이었다.
   2026-08-28에 계산해 보니 200결정 × −0.10 = **−20.0** 대 최대 획득 가능 총합 **+12.2**로,
   과제 전체를 압도했다. 런은 **거의 움직이지 않는 정책**으로 수렴했고 `ContactCount`가
   200만 스텝 넘게 평평했다. 임시로 −0.01로 낮췄다.
2. 2026-08-30에 실제로 재 보니(`Tools > ML-Agents > Diagnose PicknPlace Thumb Orientation`)
   **판독 자체가 틀렸다.** 팔 자세를 고정한 채 grip closure만 0→0.75로 움직여도 그 각도가
   71.5°→6.8°로 흔들렸고, 엄지 근위 마디는 30.0°로 일정했다 — **손이 얼마나 닫혔는지를 재고
   있었던 것이다.** −0.01로 약화한 것은 증상만 가리고 "파지를 벌주는 신호"는 남겨 두었다.

지금 판독은 **엄지 끝이 가장 낮은 다른 손끝보다 얼마나 아래인가(깊이)** 이고, −0.05는
"한 에피소드 전체를 최대 비용으로 채워도 리프트 1회 보상을 넘지 않는다"는 규칙으로 정한 값이다.

**`lift_tilt_penalty_scale: -0.02`**

기둥을 기울인 채 옮겨도 아무 비용이 없었다 — `IsToppled`는 파지 확정 후 적용을 멈추고,
리프트 성공 판정은 자세를 무시한다. 그래서 평균 기울기가 6M 스텝까지 27→29°로 표류했다.
**물체를 든 동안 결정마다 등급별 비용**을 매기고 10° 이하는 무료로 두었다.
런 중간에 `--resume`으로 도입했으므로 **그 스텝부터 보상이 바뀐다.** 성공률 정의는 일부러
건드리지 않아 곡선이 런 전체에서 비교 가능하다. 측정 효과: **27.5° → 15.3°, 성공률 98 → 99%.**

## 3. YAML이 갈아끼울 수 있는 값과 없는 값

`environment_parameters`에 아래 이름으로 적으면 Unity의 `Set*Parameter` 계열이 런타임에 받는다.

```text
grasp_stage · cube_width · cube_height · cube_com_height_fraction · topple_limit_deg ·
topdown_potential_max · action_rate_penalty_scale · hand_surface_penalty_per_second ·
grasp_posture_penalty_scale · thumb_down_penalty_scale · lift_tilt_penalty_scale
```

⚠️ **여기 없는 상수는 재컴파일·재빌드를 해야 바뀐다.** 예를 들어 `GraspConfirmSeconds`나
`ArmSafeMin/MaxDeg`를 바꾸려면 `Dg5fPicknPlaceSpec.cs`를 고치고 플레이어를 다시 빌드해야 한다.

⚠️ **학습 영역 수(`DG5F_PICKNPLACE_TRAINING_AREAS`)는 YAML이 아니라 `.env`이며, 플레이어
빌드에 구워진다.** 씬 재생성 → 재빌드가 필요하다.

## 4. 커리큘럼 구조

`grasp_stage`가 난이도를 3단계로 올린다. GraspLift의 것을 **그대로 재사용**했다(큐브 기하가 동일).

| lesson | `grasp_stage` | 진급 조건 | Unity 쪽 효과 |
|---|---|---|---|
| `lift_5cm_near` | 1.0 | `measure: progress`, `threshold 0.25`, `min_lesson_length 1000`, `signal_smoothing` | 리프트 목표 5 cm / 유지 0.25 s |
| `lift_8cm` | 2.0 | 〃 `threshold 0.55` | 8 cm / 0.35 s |
| `lift_10cm_target` | 3.0 | (최종) | **10 cm / 0.50 s**, 스폰 반경 0.37~0.58 m 환형 |

`measure: progress`는 **전체 스텝 진행률** 기준이다. 그래서 트레이너를 강제 종료해
`training_status.json`이 안 써진 상태로 `--resume`하면 lesson이 1단계로 되돌아가지만,
이미 지난 스텝 비율만큼 `min_lesson_length` 뒤에 다시 올라온다(정책 가중치는 그대로 이어진다).

## 5. GraspLift 계열 설정 목록

behavior `DG5FGraspLift`(UR5e + 왼손). 참고용 기준선이며 **새 작업은 picknplace 쪽에 한다.**

| 파일 | max_steps | 성격 |
|---|---|---|
| `dg5f_grasp_lift.yaml` | 5M | 기본 학습 설정 |
| `dg5f_grasp_lift_stability_curriculum.yaml` | 5M | 안정성 커리큘럼 |
| `dg5f_grasp_lift_h012_topdown.yaml` | 1.5M | **배포 정책의 설정** — 0.12 m 블록 + top-down 미세조정 |
| `dg5f_grasp_lift_quality_v2.yaml` | 1M | 동작 품질 미세조정(성공률 0.98 유지 전제) |
| `dg5f_grasp_lift_t1_topdown150.yaml` | 600k | `topdown_potential_max` 1.50 |
| `dg5f_grasp_lift_t2_topdown300.yaml` | 600k | 〃 3.00 (side-grasp 국소최적 탈출 시도) |
| `dg5f_grasp_lift_t3_topdown225.yaml` | 600k | 〃 2.25 (T1과 T2의 무릎점 가설) |
| `dg5f_grasp_lift_t4_topdown150_long.yaml` | — | T1을 600k 더 이어서 |
| `dg5f_grasp_lift_s1_posture010.yaml` | 200k | 파지 자세 페널티 0.10 |
| `dg5f_grasp_lift_s2_posture030.yaml` | 200k | 〃 0.30 |
| `dg5f_grasp_lift_s3_scrape050.yaml` | 200k | **엄지 긁힘을 직접 과금** — 자세 강제가 성공률을 깎을 때의 대안 |
| `dg5f_grasp_lift_s4_rate005.yaml` | 200k | 팔 행동 변화율 페널티 |
| `dg5f_grasp_lift_probe_tilt.yaml` | 150k | **진단 A** — 과제를 바꾸지 않고 블록 기울기만 측정 |
| `dg5f_grasp_lift_probe_fix.yaml` | 150k | **진단 B** — A와 두 가지(COM 0.30, 45° 종료)만 다르게 |

> 진단 프로브 A/B의 설계가 좋은 예다. **lesson·하이퍼파라미터·스텝 예산을 전부 고정**하고
> 두 가지만 바꿔 비교를 격리했다.

스윕 결과를 그림으로 뽑는 도구는 [`tools/plot_grasp_lift_slides.py`](../../tools/README.md) §4다.

## 6. 평가 전용(`*_eval_*`) 설정

`--resume --inference`로 돌려 **학습이 일어나지 않는다.** 정책 성능을 측정만 한다.

공통 규칙 두 가지가 있다.

1. **`max_steps`는 대상 체크포인트의 스텝보다 커야 한다.** 예: 배포 체크포인트가
   step 1,500,077이면 `max_steps`를 그보다 크게 잡는다. 아니면 즉시 종료된다.
2. **모든 동작 품질 페널티를 끄고, `topdown_potential_max`는 기본값(0.30)으로 되돌린다.**
   그래야 return이 배포 기준선과 비교 가능하다 — 실험의 큰 계수로 부풀지 않는다.

| 파일 쌍 | 무엇을 가르나 |
|---|---|
| `*_eval_com030.yaml` ↔ `*_eval_com050.yaml` | 무게중심 0.30 vs 0.50(균일 밀도). `Success`와 `Failure/ObjectToppled`를 비교 |
| `*_eval_t{1,2,3,4}_topdown*.yaml` ↔ `*_eval_t{1,2,3,4}_com050.yaml` | 각 스윕 런의 공칭 조건 vs 균일밀도 강건성 |
| `dg5f_picknplace_eval_com020.yaml` ↔ `..._com050.yaml` | **현역 behavior의 진단 쌍** — 학습된 정책이 왜 기둥을 수직에서 ~15° 벗어나 든 채 옮기는가. 파지점은 12 cm 기둥의 10 cm 지점인데 무게중심은 2.4 cm(`cube_com_height_fraction 0.20`)라 **질량의 7.6 cm가 그립 아래에 매달린다** — 이 구조 때문인지 보상 때문인지를 두 설정이 분리한다 |

## 7. 새 실험 설정을 만들 때

1. **가장 가까운 기존 파일을 복사**하고 이름에 실험 의도를 담는다.
2. **파일 상단 주석에 가설과 판정 규칙을 쓴다.** 이 폴더의 파일들이 전부 그렇게 돼 있고,
   그게 나중에 결과를 해석할 수 있게 만드는 유일한 장치다.
3. **한 번에 하나만 바꾼다.** lesson·하이퍼파라미터·스텝 예산을 고정해야 비교가 성립한다.
4. `torch_settings.device`가 `cuda`인지 확인한다.
5. 실행:
   ```bash
   source vision/.vision/bin/activate
   python training/scripts/train_picknplace.py --run-id <이름> --config training/config/<파일>.yaml
   ```
6. 끝난 뒤에는 **반드시 판정하고 격리**한다 →
   `python training/scripts/archive_run.py --run-id <이름> --to failure --reason "…"`

> ⚠️ **한글·em-dash 주석 주의.** ml-agents는 yaml을 로케일 기본 인코딩으로 읽어 한국어
> Windows(cp949)에서 `UnicodeDecodeError`로 죽는다. `train_picknplace.py`가 `-X utf8`로
> 띄워 이를 막는다 — 직접 `mlagents-learn`을 쓸 때는 같은 조치를 해야 한다.

## 8. 관련 문서

- [`training/README.md`](../README.md) — 학습 실행 절차(정본)
- [`training/scripts/README.md`](../scripts/README.md) — 런처·모니터·격리 도구
- [`training/archives/config/README.md`](../archives/config/README.md) — 폐기된 설정
- [`unity/Assets/MLAgents/README.md`](../../unity/Assets/MLAgents/README.md) — 상수·커리큘럼의 Unity 쪽 정본
- [`docs/TRAINING_RUN_LEDGER.md`](../../docs/TRAINING_RUN_LEDGER.md) — 런 판정 이력
- [`docs/DG5F_PICKNPLACE.md`](../../docs/DG5F_PICKNPLACE.md) — 자세 제약 설계 배경

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/config/README.md`
- **갱신 대상**: `training/config/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `unity/Assets/MLAgents/README.md` §5, `docs/TRAINING_RUN_LEDGER.md`
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

