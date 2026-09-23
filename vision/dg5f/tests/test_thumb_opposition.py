# -*- coding: utf-8 -*-
"""엄지 대향(1_2)·중지 벌림(3_1) — **사용자 손 녹화**로 확인하는 시험 (2026-09-23).

재료: `fixtures/handposes_20260923.json` — `record_hand_poses.py` 녹화
(`logs/handposes_20260923_144628.csv`, git 미추적)에서 자세마다 20장면을 뽑은 것.

지키는 것 (사용자 지적에서 온 것):
- "손바닥을 쫙 폈는데 엄지가 앞으로 나온다" → **엄지를 붙인 편 손은 1_2 ≈ 0**
- "앞으로 와야 할 때와 옆에 있어야 할 때가 구분이 안 된다" → 옆으로 벌리기는 0 근처,
  앞으로 내밀기·새끼 뿌리 대기·집게는 확실히 앞으로
- "중지가 좌우로 안 움직인다" → 검지 쪽 / 약지 쪽 기울이기가 반대 부호로 나온다
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dg5f_angles as A  # noqa: E402

FIXTURE = HERE / "fixtures" / "handposes_20260923.json"


def _robot(pose, channel):
    frames = json.loads(FIXTURE.read_text(encoding="utf-8"))["poses"][pose]
    i = A.CHANNEL_NAMES.index(channel)
    return np.array([A.map_to_dg5f(A.compute_raw(np.array(f)), hand="right", mode="direct")[i]
                     for f in frames])


class ThumbOppositionTests(unittest.TestCase):
    def setUp(self):
        self._method = A.THUMB_OPP_METHOD
        A.THUMB_OPP_METHOD = "lift_cross"

    def tearDown(self):
        A.THUMB_OPP_METHOD = self._method

    def test_엄지를_붙인_편_손은_앞으로_안_나온다(self):
        v = _robot("flat", "thumb_opp")
        self.assertGreater(np.median(v), -5.0)
        self.assertGreater(v.min(), -15.0, "한 장면이라도 크게 앞으로 튀면 안 된다")

    def test_옆으로_벌리기는_앞으로_안_나온다(self):
        self.assertGreater(np.median(_robot("spread", "thumb_opp")), -10.0)

    def test_앞으로_와야_하는_자세는_앞으로_나온다(self):
        self.assertLess(np.median(_robot("thumb_front", "thumb_opp")), -60.0)
        self.assertLess(np.median(_robot("oppose", "thumb_opp")), -70.0)
        self.assertLess(np.median(_robot("pinch", "thumb_opp")), -35.0)

    def test_옛_방식은_편_손에서도_앞으로_나왔다(self):
        """고치기 전 문제를 붙잡아 둔다 — 옛 방식으로 되돌리면 이 결함이 다시 보여야 한다."""
        A.THUMB_OPP_METHOD = "distance"
        self.assertLess(np.median(_robot("flat", "thumb_opp")), -30.0)

    def test_로봇_한계를_넘지_않는다(self):
        for pose in ("flat", "oppose", "thumb_front", "fist"):
            v = _robot(pose, "thumb_opp")
            self.assertTrue(np.all(v <= 0.0) and np.all(v >= -A.THUMB_OPP_GAIN - 1e-9), pose)


class MiddleAbductionTests(unittest.TestCase):
    def test_중지_좌우가_반대로_나온다(self):
        to_index = np.median(_robot("middle_to_index", "middle_abd"))
        to_ring = np.median(_robot("middle_to_ring", "middle_abd"))
        self.assertLess(to_index, -5.0)
        self.assertGreater(to_ring, 5.0)

    def test_곧게_편_중지는_0_근처다(self):
        for pose in ("flat", "fingers_together"):
            self.assertLess(abs(np.median(_robot(pose, "middle_abd"))), 3.0, pose)


if __name__ == "__main__":
    unittest.main()
