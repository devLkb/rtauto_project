# ⛔ 이 폴더는 폐기됐다 — 사용하지 않는다

ZED 2i 스테레오 카메라로 물체 3D 좌표를 검출해 Unity로 보내려던 경로다.
**현재 파이프라인 어디에도 연결돼 있지 않다.** 새 작업의 출발점으로 삼지 말 것.

- 수신 측인 Unity `Assets/Scripts/CameraTargetReceiver.cs`가 이미 저장소에 없다 —
  `zed_sender.py`를 실행해도 받는 쪽이 없다.
- `config/rtauto_config.py`의 `PORT_ZED_TARGET`(5007)도 이 경로 전용이라 현재 쓰이지 않는다.
  과거 포트 충돌 이력이 있으므로 **다른 용도로 재사용하지 말 것.**
- 물체 위치 인식이 다시 필요해지면 하드웨어·라이브러리 선택부터 새로 정한다.
  이 코드를 되살리는 것을 전제하지 않는다.

상세: [`docs/modules/VISION_TELEOP.md`](../../docs/modules/VISION_TELEOP.md) §4
