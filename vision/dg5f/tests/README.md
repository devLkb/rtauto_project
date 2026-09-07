# `vision/dg5f/tests/` — 다중 카메라 캘리브레이션 수학 테스트

**카메라 없이** 돌아가는 `unittest` 모듈들이다. 합성(가상) 카메라를 만들어 삼각측량 수학과
캡처 스레딩 로직이 맞는지 검증한다.

> ⚠️ **이 테스트가 통과한다고 실제 카메라의 동기화나 캘리브레이션 정확도가 보장되지 않는다.**
> 수학과 코드 경로만 검증한다.

## 파일 3개

| 파일 | 검증 대상 | 무엇을 확인하나 |
|---|---|---|
| `test_camera_calibration.py` | `camera_calibration.py` | **합성 카메라 3대 시나리오** — 보드 좌표계 3D 점을 세 카메라에 투영한 뒤 DLT로 되돌려 원래 점이 복원되는지 |
| `test_multiview_landmarks.py` | `multiview_landmarks.py` | 카메라별 픽셀 좌표 → `(21,3)` 3D 랜드마크 변환. `min_views=2` 미만인 랜드마크가 버려지는지 |
| `test_multi_camera_capture.py` | `multi_camera_capture.py` | 카메라 N대를 각각 전용 스레드로 구동하는 로직 — 한 대가 느려도 나머지가 유지되는지 |

## 실행

리포 루트에서 실행한다.

```bash
source vision/.vision/bin/activate
python -m unittest discover -s vision/dg5f/tests -p 'test_*.py'
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python -m unittest discover -s vision/dg5f/tests -p 'test_*.py'
```

## 좌표계 규약 (테스트가 전제하는 것)

- `(R, t)`는 **"보드 좌표계 → 카메라 좌표계"** 변환이다.
- 세 카메라가 **같은 순간 같은 보드**를 봤다는 전제 덕분에 별도 번들 조정 없이 공통 좌표계가
  만들어진다.
- ⚠️ 실시간 경로에 **프레임 좌우 반전을 넣으면 안 된다** — 캘리브레이션을 원본 프레임으로 했다.
- 보드 기준 3D 좌표를 로봇에 쓰려면 **보드/카메라 좌표계 ↔ 로봇 베이스 변환이 별도로 필요**하다.
  현재 그 변환은 구현돼 있지 않다.

## 이 경로의 현재 위치

다중 카메라 삼각측량은 **단일 웹캠 텔레옵과 별개의 실험 경로**다. 현재 라이브 텔레옵은
카메라 1대를 쓰며, 이 모듈은 그것을 건드리지 않는다. RL의 57칸 관찰에도 자동 연결되지 않는다.

## 관련 문서

- [`vision/README.md`](../../README.md) §3-5 — 다중 카메라 경로 개요
- [`vision/dg5f/CALIBRATION_GUIDE.md`](../CALIBRATION_GUIDE.md) — 보정 절차
- [`docs/modules/VISION_TELEOP.md`](../../../docs/modules/VISION_TELEOP.md) §3·§6-5 — 함수 상세
- [`config/README.md`](../../../config/README.md) §3-5 — 체스보드 규격 설정 키

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- vision/dg5f/tests/README.md`
- **갱신 대상**: `vision/dg5f/tests/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/VISION_TELEOP.md` §6-5
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

