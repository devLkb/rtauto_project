# -*- coding: utf-8 -*-
"""multi_camera_capture.py 로직 검증 — 실물 웹캠 없이 cv2.VideoCapture를 가짜로 갈아끼운다.

카메라가 물려 있지 않은 개발 PC에서도 돌아가야 의미가 있으므로, 여기서는 절대로 진짜
cv2.VideoCapture를 열지 않는다(FakeCapture만 사용). "카메라 3대 중 1대가 없을 때 나머지
2대는 정상 동작하는가"가 핵심 검증 대상 — 실물 웹캠 유무와 무관하게 지금 확인 가능하다.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import multi_camera_capture as mcc


class FakeCapture:
    """cv2.VideoCapture 흉내 — 지정된 인덱스 집합만 '열리는' 카메라로 취급한다."""

    openable_indices = set()
    read_delay_indices = set()  # 이 인덱스는 read()가 잠깐 실패했다가 성공(재시도 경로 검증용)

    def __init__(self, index, backend=None):
        self.index = index
        self._opened = index in FakeCapture.openable_indices
        self._props = {}
        self._read_calls = 0
        self.released = False

    def isOpened(self):
        return self._opened

    def set(self, prop, value):
        self._props[prop] = value
        return True

    def get(self, prop):
        return self._props.get(prop, 0)

    def read(self):
        self._read_calls += 1
        if self.index in FakeCapture.read_delay_indices and self._read_calls == 1:
            return False, None
        import numpy as np
        return True, np.zeros((4, 4, 3), dtype="uint8")

    def release(self):
        self.released = True


class MultiCameraCaptureTest(unittest.TestCase):
    def setUp(self):
        FakeCapture.openable_indices = set()
        FakeCapture.read_delay_indices = set()

    def test_open_all_reports_per_camera_success(self):
        FakeCapture.openable_indices = {0, 2}
        mgr = mcc.MultiCameraCapture(indices=[0, 1, 2], capture_factory=FakeCapture)
        result = mgr.open_all()
        self.assertEqual(result, {0: True, 1: False, 2: True})
        self.assertIn("카메라 1", mgr.streams[1].error)
        self.assertFalse(mgr.all_opened())
        self.assertTrue(mgr.any_opened())

    def test_all_cameras_missing_is_reported_not_raised(self):
        FakeCapture.openable_indices = set()
        mgr = mcc.MultiCameraCapture(indices=[0, 1, 2], capture_factory=FakeCapture)
        result = mgr.open_all()
        self.assertEqual(result, {0: False, 1: False, 2: False})
        self.assertFalse(mgr.any_opened())

    def test_read_all_returns_frames_only_for_opened_cameras(self):
        FakeCapture.openable_indices = {0, 2}
        mgr = mcc.MultiCameraCapture(indices=[0, 1, 2], capture_factory=FakeCapture)
        mgr.open_all()
        mgr.start_all()
        try:
            deadline = time.time() + 2.0
            frames = mgr.read_all()
            while (frames[0] is None or frames[2] is None) and time.time() < deadline:
                time.sleep(0.02)
                frames = mgr.read_all()
            self.assertIsNotNone(frames[0])
            self.assertIsNotNone(frames[2])
            self.assertIsNone(frames[1])  # 못 연 카메라는 항상 None
        finally:
            mgr.stop_all()

    def test_stop_all_releases_underlying_capture(self):
        FakeCapture.openable_indices = {0}
        mgr = mcc.MultiCameraCapture(indices=[0], capture_factory=FakeCapture)
        mgr.open_all()
        mgr.start_all()
        underlying = mgr.streams[0]._cap
        mgr.stop_all()
        self.assertTrue(underlying.released)
        self.assertFalse(mgr.streams[0].opened)

    def test_default_indices_come_from_config(self):
        mgr = mcc.MultiCameraCapture(capture_factory=FakeCapture)
        self.assertEqual(mgr.indices, list(mcc.VISION_CAMERA_INDICES))

    def test_start_before_open_raises(self):
        stream = mcc.CameraStream(0, capture_factory=FakeCapture)
        with self.assertRaises(RuntimeError):
            stream.start()


if __name__ == "__main__":
    unittest.main()
