# -*- coding: utf-8 -*-
"""`depth_landmarks.py` — 관절 점 + 깊이 → 입체 위치 시험 (카메라 없이, 가짜 깊이 사진)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import depth_landmarks as D  # noqa: E402

W, H = 848, 480
FX, FY, CX, CY = 420.0, 420.0, 430.0, 238.0


def project(p):
    """카메라 기준 점(m) → 사진 위 비율 좌표 (뒤집기 전)."""
    x, y, z = p
    return ((FX * x / z + CX) / W, (FY * y / z + CY) / H)


def depth_with(points, background=0.0, r=3):
    d = np.full((H, W), background, dtype=np.float32)
    for p in points:
        u, v = project(p)
        ui, vi = int(round(u * W)), int(round(v * H))
        d[vi - r:vi + r + 1, ui - r:ui + r + 1] = p[2]
    return d


class DepthLandmarkTests(unittest.TestCase):
    def test_점을_제자리로_되돌린다(self):
        pts = [(0.02, -0.01, 0.35), (-0.05, 0.03, 0.40), (0.0, 0.0, 0.30)]
        got, ok = D.landmarks_3d([project(p) for p in pts], depth_with(pts), FX, FY, CX, CY,
                                 max_from_wrist=None)
        self.assertTrue(ok.all())
        np.testing.assert_allclose(got, pts, atol=2e-3)   # 화소 반올림만큼의 오차

    def test_거울_모드면_좌우가_뒤집힌_점이_나온다(self):
        """사진·깊이를 좌우로 뒤집으면 세상이 거울상이 된다 — x 만 부호가 바뀌어야 한다."""
        pts = [(0.04, 0.02, 0.33), (-0.03, -0.02, 0.38)]
        depth = depth_with(pts)[:, ::-1]                      # cv2.flip(depth, 1) 과 같다
        lm = [(1.0 - (u + 0.5 / W) - 0.5 / W, v) for u, v in (project(p) for p in pts)]
        got, ok = D.landmarks_3d(lm, depth, FX, FY, CX, CY, mirror=True, max_from_wrist=None)
        self.assertTrue(ok.all())
        np.testing.assert_allclose(got, [(-x, y, z) for x, y, z in pts], atol=2e-3)

    def test_깊이가_없으면_NaN_이고_지어내지_않는다(self):
        got, ok = D.landmarks_3d([(0.5, 0.5)], np.zeros((H, W), np.float32), FX, FY, CX, CY)
        self.assertFalse(ok[0])
        self.assertTrue(np.isnan(got[0]).all())

    def test_손목에서_너무_먼_깊이는_버린다(self):
        """손 뒤 배경(책상 등)을 읽은 관절은 버린다."""
        wrist, tip = (0.0, 0.05, 0.35), (0.0, -0.05, 0.35)
        depth = depth_with([wrist, tip])
        u, v = project(tip)
        ui, vi = int(round(u * W)), int(round(v * H))
        depth[vi - 3:vi + 4, ui - 3:ui + 4] = 0.90            # 손끝 자리에 멀리 있는 배경
        got, ok = D.landmarks_3d([project(wrist), project(tip)], depth, FX, FY, CX, CY)
        self.assertTrue(ok[0])
        self.assertFalse(ok[1])

    def test_범위_밖_깊이는_안_쓴다(self):
        self.assertTrue(np.isnan(D.sample_depth(np.full((5, 5), 0.02, np.float32), 2, 2,
                                                near=0.07, far=0.5)))
        self.assertTrue(np.isnan(D.sample_depth(np.zeros((5, 5), np.float32), 99, 99)))


if __name__ == "__main__":
    unittest.main()
