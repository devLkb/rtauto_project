# -*- coding: utf-8 -*-
"""`exposure_sweep.py` 의 **순수 계산 로직** 검증 — 카메라 없이 돈다 (D-10).

실물 D405 로 노출을 실제로 훑는 것은 이 시험의 범위가 아니다(카메라가 있어야만
가능하다). 여기서는 카메라와 무관한 부분 — ROI 파싱·좌표 환산·통계 계산 — 만 확인한다.

돌리는 법 (터미널 1, PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python -m unittest vision.d405.tests.test_exposure_sweep -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import exposure_sweep as es  # noqa: E402


class TestRoiParsing(unittest.TestCase):
    def test_parses_x_y_w_h(self):
        self.assertEqual(es._parse_roi("10,20,30,40"), (10, 20, 30, 40))

    def test_none_when_not_given(self):
        self.assertIsNone(es._parse_roi(None))
        self.assertIsNone(es._parse_roi(""))

    def test_bad_format_exits_loudly_instead_of_guessing(self):
        with self.assertRaises(SystemExit):
            es._parse_roi("10,20,30")   # 3개뿐 — 조용히 넘어가면 안 된다

    def test_zero_size_rejected(self):
        with self.assertRaises(SystemExit):
            es._parse_roi("10,20,0,40")


class TestRoiScaling(unittest.TestCase):
    def test_scales_down_when_target_is_half_resolution(self):
        """색 사진(640x480) 기준 ROI를 줄인 깊이 사진(320x240)으로 옮기면 절반이 된다."""
        roi = (100, 80, 40, 60)
        scaled = es._scale_roi(roi, (480, 640), (240, 320))
        self.assertEqual(scaled, (50, 40, 20, 30))

    def test_identity_when_same_resolution(self):
        roi = (10, 20, 30, 40)
        self.assertEqual(es._scale_roi(roi, (480, 640), (480, 640)), roi)


class TestDepthStats(unittest.TestCase):
    def test_valid_ratio_excludes_zero_depth(self):
        d = np.array([[0.2, 0.0, 0.2], [0.0, 0.0, 0.3]], dtype=np.float32)
        st = es._frame_stats(d)
        self.assertAlmostEqual(st["valid_ratio"], 3.0 / 6.0)
        self.assertEqual(st["point_count"], 3)

    def test_median_and_std_only_over_valid_pixels(self):
        d = np.array([0.10, 0.20, 0.30, 0.0, 0.0], dtype=np.float32)
        st = es._frame_stats(d)
        self.assertAlmostEqual(st["median_m"], 0.20)
        self.assertAlmostEqual(st["std_m"], float(np.std([0.10, 0.20, 0.30])))

    def test_all_zero_gives_nan_not_a_fake_value(self):
        d = np.zeros((4, 4), dtype=np.float32)
        st = es._frame_stats(d)
        self.assertEqual(st["valid_ratio"], 0.0)
        self.assertEqual(st["point_count"], 0)
        self.assertTrue(np.isnan(st["median_m"]))
        self.assertTrue(np.isnan(st["std_m"]))

    def test_roi_stats_crops_before_computing(self):
        d = np.zeros((10, 10), dtype=np.float32)
        d[2:5, 2:5] = 0.25   # 3x3 = 9개 값
        st = es._roi_stats(d, (2, 2, 3, 3))
        self.assertEqual(st["point_count"], 9)
        self.assertAlmostEqual(st["valid_ratio"], 1.0)
        self.assertAlmostEqual(st["median_m"], 0.25)

    def test_roi_partially_outside_frame_is_clipped_not_error(self):
        d = np.full((10, 10), 0.3, dtype=np.float32)
        st = es._roi_stats(d, (8, 8, 10, 10))   # 프레임 밖으로 튀어나감
        self.assertEqual(st["point_count"], 4)   # 8..10 x 8..10 만 유효


if __name__ == "__main__":
    unittest.main()
