# `training/tests/` — 파이썬 회귀 테스트

학습 스크립트와 **과거 behavior 계약**을 지키는 `unittest` 모듈들이다.
Unity 쪽 테스트(보상 로직·씬 검증)는 여기가 아니라
[`unity/Assets/MLAgents/`](../../unity/Assets/MLAgents/README.md) §9의 Test Runner로 돌린다.

> ⚠️ **먼저 알아야 할 사실: 이 폴더의 대부분은 현재 통과하지 않는다.**
> 새 PC 설치가 잘못된 게 아니다. 폐기된 behavior의 테스트가 이미 삭제된 config·스크립트·`.cs`를
> 계속 읽고 있어서다. 아래 §2에 파일별 현재 상태를 적어 두었다.

## 목차

1. [설치 확인용으로 쓰는 테스트](#1-설치-확인용으로-쓰는-테스트)
2. [파일별 현재 상태](#2-파일별-현재-상태)
3. [실패가 두 종류인 이유](#3-실패가-두-종류인-이유)
4. [실행 방법](#4-실행-방법)
5. [새 테스트를 추가할 때](#5-새-테스트를-추가할-때)
6. [관련 문서](#6-관련-문서)

## 1. 설치 확인용으로 쓰는 테스트

**`test_validate_unity_environment.py`가 현재 저장소 상태에서 100% 통과하는 유일한 모듈**이라
새 PC 설치 확인용으로 쓴다.

```bash
source vision/.vision/bin/activate
python -m unittest discover -s training/tests -p 'test_validate_unity_environment.py'
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python -m unittest discover -s training/tests -p 'test_validate_unity_environment.py'
```

`Ran 4 tests ... OK`가 나오면 설치가 정상이다.

## 2. 파일별 현재 상태

2026-09-07 저장소 상태에서 실제로 실행해 확인한 결과다.

| 파일 | 테스트 수 | 대상 | 현재 상태 |
|---|---|---|---|
| `test_validate_unity_environment.py` | 4 | `validate_unity_environment.py`의 manifest 대조 | ✅ **OK** |
| `test_bootstrap_v1_to_joint26.py` | 5 | 57/7 → 116/26 체크포인트 확장 | ⚠️ 의존성(`torch`) 필요 |
| `test_dg5f_topdown_transfer_contract.py` | 7 | top-down 전이 계약 | ⚠️ 의존성(`onnx`) 필요 |
| `test_evaluate_dg5f_topdown.py` | 5 | 폐기된 `training.scripts.evaluate_dg5f_topdown` | ⛔ 대상 스크립트 없음 |
| `test_evaluate_dg5f_grasp_point_reach.py` | 9 | 폐기된 ReadyReach 평가 스크립트 | ⛔ 대상 파일 없음 |
| `test_grasp_point_reach_contract.py` | 5 | 폐기된 ReadyReach 계약 | ⛔ 〃 |
| `test_ready_reach_curriculum_policy.py` | 2 | `training/policy/ready_reach/*.cs` | ⛔ 〃 |
| `test_grasp_demo_floor_contract.py` | 3 | `config/dg5f_grasp_demo_floor_finetune.yaml` | ⛔ 설정 파일 없음 |
| `test_grasp_surface_hold3s_contract.py` | 2 | `config/dg5f_grasp_surface_hold3s_finetune.yaml` | ⛔ 〃 |
| `test_grasp_surface_hold_curriculum_contract.py` | 2 | `config/dg5f_grasp_surface_hold_curriculum.yaml` | ⛔ 〃 |
| `test_handfirst_training_contract.py` | 4 | v2 hand-first 학습 계약 | ⛔ 대상 설정 없음 |

**현역 behavior(`DG5FPicknPlace`)를 검증하는 파이썬 테스트는 아직 없다.**
현역 과제의 계약 검증은 Unity EditMode 테스트(`Dg5fPicknPlaceSpecTests.cs`)가 담당한다.

## 3. 실패가 두 종류인 이유

같은 "FAILED"라도 원인이 다르고, **대응이 다르다.**

| 종류 | 증상 | 원인 | 대응 |
|---|---|---|---|
| **의존성 미설치** | `ModuleNotFoundError: No module named 'torch'` / `'onnx'` | venv를 활성화하지 않았거나 학습용 패키지를 안 깔았다 | venv를 활성화한다. 설치는 [`docs/PYTHON_ENV_SETUP.md`](../../docs/PYTHON_ENV_SETUP.md) |
| **대상이 삭제됨** | `FileNotFoundError: … dg5f_grasp_surface_hold3s_finetune.yaml` 등 | 폐기된 behavior의 config·스크립트·`.cs`가 이미 지워졌는데 테스트만 남았다 | **테스트 쪽을 정리해야 한다.** 파일을 되살리는 것이 아니다 |

전자는 **환경 문제**, 후자는 **잔재 정리 과제**다. 두 번째 유형을 "설치가 잘못됐다"로 읽으면
멀쩡한 새 PC를 고치려 들게 된다 — 이 절을 둔 이유다.

> 삭제된 대상의 설계 기록은 git 이력과 [`docs/archives/`](../../docs/archives/)에 남아 있다.

## 4. 실행 방법

**전체 실행 (현재는 실패가 정상)**

```bash
source vision/.vision/bin/activate
python -m unittest discover -s training/tests -p 'test_*.py'
```

**한 모듈만**

```bash
python -m unittest discover -s training/tests -p 'test_bootstrap_v1_to_joint26.py'
```

**한 테스트만**

```bash
python -m unittest training.tests.test_validate_unity_environment -v
```

리포 루트에서 실행한다 — 테스트들이 `Path(__file__).parents[1]` / `[2]`로 저장소 경로를 계산한다.

## 5. 새 테스트를 추가할 때

1. **현역 대상만 검증한다.** 폐기된 behavior의 계약을 새로 고정하지 않는다.
2. **파일 경로를 하드코딩하지 않는다.** 기존 테스트처럼 `Path(__file__).parents[n]` 기준으로
   계산하고, 설정값은 `config/rtauto_config.py`에서 읽는다(원칙 1).
3. **대상 파일이 없으면 `skipUnless`로 건너뛰게 한다.** 지금 이 폴더가 겪는 문제
   (대상이 사라졌는데 테스트가 `FileNotFoundError`로 죽는 것)가 반복되지 않게 하는 방법이다.
4. 추가한 뒤 `training/README.md`의 설치 확인 절차와 이 문서의 표를 함께 갱신한다.

## 6. 관련 문서

- [`training/README.md`](../README.md) — 설치 확인 절차와 실패 안내
- [`training/scripts/README.md`](../scripts/README.md) — 테스트가 검증하는 스크립트들
- [`docs/PYTHON_ENV_SETUP.md`](../../docs/PYTHON_ENV_SETUP.md) — venv 구성(Windows/Linux)
- [`unity/Assets/MLAgents/README.md`](../../unity/Assets/MLAgents/README.md) §9 — Unity 쪽 테스트
- [`training/test-results/README.md`](../test-results/README.md) — Unity 테스트 실행 결과 XML

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/tests/README.md`
- **갱신 대상**: `training/tests/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `training/README.md` 설치 확인 절
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

