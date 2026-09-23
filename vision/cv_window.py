# -*- coding: utf-8 -*-
"""OpenCV 창을 **X 버튼으로도** 닫을 수 있게 하는 공용 도우미 (2026-09-23 사용자 요청).

왜 필요한가: OpenCV 창은 X 를 눌러도 프로그램에 "닫혔다" 고 알려 주지 않는다. 그래서
예전 도구들은 `q` 로만 끝낼 수 있었고, X 를 누르면 다음 장면을 그릴 때 창이 **다시 떴다.**
창이 보이는지를 매 장면 물어보고, 보이다가 안 보이게 되면 "사람이 닫았다" 로 본다.

쓰는 법 — `waitKey` 바로 뒤에서 부른다(다음 `imshow` 전에 불러야 한다. `imshow` 가 닫힌
창을 다시 만들어 버리기 때문이다)::

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or cv_window.closed(WINDOW_NAME):
        break

`closed()` 는 **한 번이라도 보였던 창만** 닫혔다고 판정한다. 창이 보이는지 알려 주지
않는 환경(일부 리눅스 창 방식)에서는 끝까지 False 라 예전처럼 `q` 로 끝내면 된다 —
멀쩡한 창을 닫혔다고 잘못 보고 프로그램을 끝내는 일은 없다.
"""

_seen_visible = set()


def closed(*names):
    """이 이름의 창 중 하나라도 **사람이 닫았으면** True."""
    import cv2

    for name in names:
        try:
            visible = cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE)
        except cv2.error:
            visible = -1
        if visible >= 1:
            _seen_visible.add(name)
        elif name in _seen_visible:
            _seen_visible.discard(name)
            return True
    return False


def wait_any_key_or_close(name, poll_ms=100):
    """`cv2.waitKey(0)` 대신 — 아무 키를 누르거나 창을 닫을 때까지 기다린다. 누른 키(닫으면 -1)."""
    import cv2

    while True:
        key = cv2.waitKey(poll_ms)
        if key != -1:
            return key & 0xFF
        if closed(name):
            return -1
