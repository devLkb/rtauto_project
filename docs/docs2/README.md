# `docs/docs2/` — 설명·발표·조사 문서 (한국어 서술형)

기술 계약서가 아니라 **사람에게 설명하기 위한 문서**들이다. 발표 자료, 개념 설명, 기술 선택의
이유, 외부 SDK 조사 기록이 들어 있다.

정확한 값·계약이 필요하면 여기가 아니라 [`docs/modules/`](../modules/README.md)와 코드를 본다.

## 문서 6개

| 문서 | 성격 | 언제 읽나 |
|---|---|---|
| [`GRASP_LIFT_발표자료.md`](GRASP_LIFT_발표자료.md) | 발표 슬라이드 원고 | 결과를 남에게 보여줘야 할 때 |
| [`GRASP_LIFT_설명.md`](GRASP_LIFT_설명.md) | GraspLift 과제를 서술형으로 풀어 쓴 설명 | 강화학습 과제를 처음 이해할 때 |
| [`기술선택_설명.md`](기술선택_설명.md) | 왜 이 기술 스택인가 | "왜 Unity인가", "왜 이 경로인가"를 설명해야 할 때 |
| [`ONNX_인계_설명.md`](ONNX_인계_설명.md) | 학습된 정책(ONNX)을 넘겨받아 쓰는 법 | 모델 파일만 받았을 때 |
| [`TESOLLO_SDK_설명.md`](TESOLLO_SDK_설명.md) | DG-5F SDK 사용법 설명 | 손 브리지를 손볼 때 |
| [`TESOLLO_SDK_기술부채_조사.md`](TESOLLO_SDK_기술부채_조사.md) | **SDK 제약 조사 기록** | 실물 손 연결이 안 될 때 |

## 특히 중요한 것 하나

[`TESOLLO_SDK_기술부채_조사.md`](TESOLLO_SDK_기술부채_조사.md)는 **지금도 실무에 직접 영향을
주는 결론**을 담고 있다.

> DG-5F는 **프로토콜·제어모드와 무관하게 TCP 세션을 전체에서 1개만 받는다**(2026-08-31 실물 실측).
> DGManager를 켜둔 채로는 개발자모드 SDK 경로도, 사용자모드 Modbus 경로도 붙지 않는다.

그래서 실물을 쓰려면 **SDK 브리지를 유일한 클라이언트로 쓰거나**, DGManager 연결을 끊고
readback 브리지로 자세를 캡처하거나 둘 중 하나를 택해야 한다 →
[`docs/modules/REAL_BRIDGES.md`](../modules/REAL_BRIDGES.md) §2.

## 그림은 어디에

발표 자료가 참조하는 PNG는 [`docs/images/`](../images/README.md)에 있고,
[`tools/plot_grasp_lift_slides.py`](../../tools/README.md)로 다시 렌더링할 수 있다.

## 읽을 때의 규칙

- **서술형 설명과 값의 정본은 다르다.** 숫자가 코드와 다르면 **코드가 맞다.**
- 발표 자료는 **작성 시점의 결과**다. 최신 학습 결과를 보려면
  [`docs/TRAINING_RUN_LEDGER.md`](../TRAINING_RUN_LEDGER.md)와 TensorBoard를 본다.
- 여기 문서 대부분은 **구세대 GraspLift(UR5e + 왼손)** 기준이다. 현역은 UR16e + 오른손이다.

## 관련 문서

- [`docs/README.md`](../README.md) — 문서 인덱스
- [`docs/modules/`](../modules/README.md) — 코드 모듈 설명(값의 정본에 가까운 쪽)
- [`docs/SIM2REAL_ROADMAP.md`](../SIM2REAL_ROADMAP.md) — 아키텍처 확정 사항

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- docs/docs2/README.md`
- **갱신 대상**: `docs/docs2/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/README.md`
- **용어는 [`GLOSSARY`](../GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

