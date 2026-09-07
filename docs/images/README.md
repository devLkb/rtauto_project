# `docs/images/` — 문서·발표용 그림

문서와 발표 자료가 참조하는 PNG를 모아 둔다. **대부분 스크립트로 다시 만들 수 있는
생성물**이므로, 그림을 손으로 편집하지 말고 생성 스크립트를 고친다.

## 파일 4개

| 파일 | 내용 | 만드는 방법 |
|---|---|---|
| `dg5f_grasp_lift_curves.png` | 여러 학습 런의 곡선 비교 3단 패널 (누적 보상 / 성공률 / 에피소드 길이) | `python tools/plot_grasp_lift_curves.py` |
| `dg5f_grasp_lift_slide_training.png` | 발표용 — 배포 정책의 학습 곡선 | `python tools/plot_grasp_lift_slides.py` |
| `dg5f_grasp_lift_slide_tradeoff.png` | 발표용 — top-down 계수 스윕의 자세 vs 신뢰성 트레이드오프 | 〃 (같은 명령이 두 장을 함께 만든다) |
| `dg5f_grasp_panel_v3.png` | 파지 패널 구성 그림 | 수동 캡처 |

## 다시 만들기

**터미널 1 (bash 또는 PowerShell, 리포 루트, 그래프 렌더링)**

```bash
source vision/.vision/bin/activate
python tools/plot_grasp_lift_curves.py
python tools/plot_grasp_lift_slides.py
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python tools/plot_grasp_lift_curves.py
python tools/plot_grasp_lift_slides.py
```

- 입력은 `training/results/<run_id>/`의 TensorBoard 이벤트 파일이다. **해당 런이 로컬에 없으면
  그려지지 않는다.**
- matplotlib 백엔드를 `Agg`로 고정해 화면 없이 실행된다.
- 출력 경로 기본값이 이 폴더다. `plot_grasp_lift_curves.py`는 `-o`로 바꿀 수 있다.

## 주의

- 이 그림들은 **`DG5FGraspLift`(구세대, UR5e + 왼손)** 결과다. 현역 `DG5FPicknPlace`의 태그는
  `PicknPlace/*`라 같은 스크립트로는 그려지지 않는다.
- 문서에서 그림을 참조할 때는 **무엇을 보여주는 그림인지 캡션으로 적는다.** 나중에 런이 바뀌면
  그림만 남고 맥락이 사라진다.

## 관련 문서

- [`tools/README.md`](../../tools/README.md) §3·§4 — 렌더링 스크립트 상세
- [`docs/docs2/`](../docs2/README.md) — 이 그림을 쓰는 발표 자료
- [`docs/TRAINING_RUN_LEDGER.md`](../TRAINING_RUN_LEDGER.md) — 각 런의 판정 이력

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- docs/images/README.md`
- **갱신 대상**: `docs/images/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `tools/README.md` §3·§4
- **용어는 [`GLOSSARY`](../GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

