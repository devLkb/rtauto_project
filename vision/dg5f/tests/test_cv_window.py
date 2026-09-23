# -*- coding: utf-8 -*-
"""`vision/cv_window.py` — 창 X 로 닫기 판정 시험 (가짜 OpenCV, 화면 없이 돈다)."""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vision/
import cv_window  # noqa: E402


class FakeCv2(types.SimpleNamespace):
    class error(Exception):
        pass

    WND_PROP_VISIBLE = 4

    def __init__(self, states):
        super().__init__()
        self.states = list(states)      # getWindowProperty 가 차례로 돌려줄 값

    def getWindowProperty(self, _name, _prop):
        v = self.states.pop(0)
        if v == "err":
            raise FakeCv2.error("no window")
        return v

    def waitKey(self, _ms):
        return -1


class ClosedTests(unittest.TestCase):
    def setUp(self):
        cv_window._seen_visible.clear()
        self._real = sys.modules.get("cv2")

    def tearDown(self):
        if self._real is not None:
            sys.modules["cv2"] = self._real
        else:
            sys.modules.pop("cv2", None)

    def _use(self, states):
        sys.modules["cv2"] = FakeCv2(states)

    def test_보였다가_사라지면_닫힌_것이다(self):
        self._use([1.0, 1.0, 0.0])
        self.assertFalse(cv_window.closed("w"))
        self.assertFalse(cv_window.closed("w"))
        self.assertTrue(cv_window.closed("w"))

    def test_한_번도_안_보였으면_닫혔다고_하지_않는다(self):
        """창이 보이는지 알려 주지 않는 환경 — 멀쩡한 창을 닫혔다고 보고 끝내면 안 된다."""
        self._use([-1.0, -1.0, "err"])
        for _ in range(3):
            self.assertFalse(cv_window.closed("w"))

    def test_창이_사라져_에러가_나도_닫힌_것이다(self):
        self._use([1.0, "err"])
        self.assertFalse(cv_window.closed("w"))
        self.assertTrue(cv_window.closed("w"))

    def test_여러_창_중_하나만_닫혀도_닫힌_것이다(self):
        self._use([1.0, 1.0, 1.0, 0.0])
        self.assertFalse(cv_window.closed("a", "b"))
        self.assertTrue(cv_window.closed("a", "b"))

    def test_키를_기다리다_창을_닫으면_끝난다(self):
        self._use([1.0, 1.0, 0.0])
        self.assertEqual(cv_window.wait_any_key_or_close("w", poll_ms=1), -1)


if __name__ == "__main__":
    unittest.main()
