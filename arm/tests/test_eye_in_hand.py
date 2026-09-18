# -*- coding: utf-8 -*-
"""손목 카메라 좌표 옮기기 시험 — **카메라도 팔도 없이** 돈다.

여기서 확인하는 것은 **계산**이지 통신이 아니다. 특히:

- 팔이 움직이면 같은 "카메라가 본 점" 이 로봇 기준으로 **따라 움직이는가**
- 장착값이 0일 때 **"안 쟀다" 고 분명히 말하는가** (조용히 틀린 좌표를 내놓지 않기)
- 회전 순서를 바꿔 적어도 되는가 (안 된다 — 같은 숫자가 다른 방향을 뜻한다)

돌리는 법 (리포 루트, numpy 가 있는 가상환경으로):

    python -m unittest arm.tests.test_eye_in_hand -v
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arm.eye_in_hand import (  # noqa: E402
    CameraMount, camera_to_base, depth_to_points_cam, intrinsics, points_to_base,
    pose_to_matrix, rotvec_to_matrix, rpy_to_matrix,
)


def mount(xyz=(0.0, 0.0, 0.0), rpy=(0.0, 0.0, 0.0), measured=True):
    return CameraMount("tool0", tuple(xyz), tuple(rpy), measured)


class RotationTests(unittest.TestCase):
    def test_돌리지_않으면_그대로다(self):
        np.testing.assert_allclose(rpy_to_matrix(0, 0, 0), np.eye(3), atol=1e-12)
        np.testing.assert_allclose(rotvec_to_matrix([0, 0, 0]), np.eye(3), atol=1e-12)

    def test_회전은_길이를_바꾸지_않는다(self):
        for rpy in [(10, 20, 30), (-90, 45, 180), (5, -175, 60)]:
            r = rpy_to_matrix(*rpy)
            np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-10)
            self.assertAlmostEqual(float(np.linalg.det(r)), 1.0, places=10)

    def test_z축_90도는_x를_y로_보낸다(self):
        """방향 규약을 못 박아 둔다 — 나중에 누가 순서를 바꾸면 여기서 걸린다."""
        got = rpy_to_matrix(0, 0, 90) @ np.array([1.0, 0.0, 0.0])
        np.testing.assert_allclose(got, [0.0, 1.0, 0.0], atol=1e-12)

    def test_회전_순서를_바꾸면_다른_방향이_된다(self):
        """같은 숫자라도 순서가 다르면 다른 방향이다 — 그래서 한 군데에만 적어 둔다."""
        a = rpy_to_matrix(30, 40, 50)
        b = rpy_to_matrix(50, 40, 30)
        self.assertGreater(float(np.abs(a - b).max()), 0.1)

    def test_회전벡터도_길이를_안_바꾼다(self):
        r = rotvec_to_matrix([0.3, -1.2, 0.7])
        np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-10)


class TransformTests(unittest.TestCase):
    def test_팔이_움직이면_본_점도_따라_움직인다(self):
        """팔을 x 로 10 cm 옮기면, 같은 화면의 점도 로봇 기준으로 10 cm 옮겨져야 한다."""
        m = mount(xyz=(0.05, 0.0, 0.02))
        p0, _ = points_to_base([[0, 0, 0.2]], [0.3, 0.0, 0.4, 0, 0, 0], m)
        p1, _ = points_to_base([[0, 0, 0.2]], [0.4, 0.0, 0.4, 0, 0, 0], m)
        np.testing.assert_allclose(p1[0] - p0[0], [0.1, 0.0, 0.0], atol=1e-12)

    def test_장착_위치가_그대로_더해진다(self):
        """팔 끝이 원점에 있고 안 돌아 있으면, 결과 = 장착 위치 + 본 위치."""
        m = mount(xyz=(0.01, -0.02, 0.03))
        got, _ = points_to_base([[0.0, 0.0, 0.2]], [0, 0, 0, 0, 0, 0], m)
        np.testing.assert_allclose(got[0], [0.01, -0.02, 0.23], atol=1e-12)

    def test_팔이_돌면_본_방향도_같이_돈다(self):
        """팔 끝을 Z 로 90도 돌리면 카메라 앞(+Z)은 그대로지만 옆(+X)은 +Y 가 된다."""
        m = mount()
        pose = [0, 0, 0, 0, 0, math.pi / 2]        # Z 축 90도
        got, _ = points_to_base([[0.1, 0.0, 0.0]], pose, m)
        np.testing.assert_allclose(got[0], [0.0, 0.1, 0.0], atol=1e-9)

    def test_변환은_거리를_보존한다(self):
        """옮기고 돌리기만 하므로 점끼리의 거리는 안 변한다 — 크기가 틀어지면 버그다."""
        m = mount(xyz=(0.04, 0.01, -0.02), rpy=(15, -30, 60))
        pts = np.array([[0.0, 0.0, 0.15], [0.03, -0.02, 0.18], [-0.05, 0.04, 0.22]])
        moved, _ = points_to_base(pts, [0.2, -0.3, 0.5, 0.4, -0.2, 1.1], m)
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertAlmostEqual(float(np.linalg.norm(pts[i] - pts[j])),
                                       float(np.linalg.norm(moved[i] - moved[j])),
                                       places=10)

    def test_4x4_가_올바른_형태다(self):
        t = camera_to_base([0.1, 0.2, 0.3, 0.1, 0.2, 0.3], mount(xyz=(0.01, 0, 0)))
        self.assertEqual(t.shape, (4, 4))
        np.testing.assert_allclose(t[3], [0, 0, 0, 1], atol=1e-12)


class UnmeasuredTests(unittest.TestCase):
    def test_안_쟀으면_경고를_돌려준다(self):
        """조용히 틀린 좌표를 내놓지 않는 것이 이 시험의 목적이다."""
        _, warn = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], mount(measured=False))
        self.assertIsNotNone(warn)
        self.assertIn("아직 안 쟀다", warn)

    def test_쟀으면_경고가_없다(self):
        _, warn = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0],
                                 mount(xyz=(0.05, 0, 0)))
        self.assertIsNone(warn)

    def test_안_쟀어도_계산은_돌아간다(self):
        """원칙 2 — 새 머신에서 설치 직후 바로 실행은 돼야 한다(값을 믿는 것과 별개)."""
        got, _ = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], mount(measured=False))
        self.assertEqual(got.shape, (1, 3))
        self.assertTrue(np.isfinite(got).all())


class DepthTests(unittest.TestCase):
    def test_깊이에서_점이_나온다(self):
        depth = np.full((8, 10), 0.2)
        pts = depth_to_points_cam(depth)
        self.assertEqual(len(pts), 80)
        np.testing.assert_allclose(pts[:, 2], 0.2)

    def test_너무_가깝거나_먼_화소는_버린다(self):
        """D405 가 못 재는 거리의 값을 그대로 쓰면 없는 물체를 만들어 낸다."""
        depth = np.array([[0.01, 0.2], [5.0, np.nan]])
        pts = depth_to_points_cam(depth)
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(float(pts[0, 2]), 0.2)

    def test_화면_가운데_점은_정면에_있다(self):
        depth = np.full((10, 10), 0.3)
        pts = depth_to_points_cam(depth)
        fx, fy, cx, cy, _ = intrinsics(10, 10)
        # 중심은 화면 안에 있어야 한다(실측값이든 계산값이든)
        self.assertTrue(0 <= cx <= 10, cx)
        self.assertLess(float(np.abs(pts[:, 0]).min()), 1e-9 + 0.3 * 0.5 / fx)

    def test_실측값은_해상도에_맞춰_환산된다(self):
        """⚠️ 잰 해상도의 값을 그대로 쓰면 **2배 틀린다** — 2026-09-18 에 시험이 잡았다."""
        import rtauto_config as c
        if not (c.D405_FX > 0 and c.D405_FY > 0):
            self.skipTest("실측값이 .env 에 없다 — 환산할 것이 없다")
        fx_big, _, cx_big, _, real = intrinsics(c.D405_CALIB_WIDTH, c.D405_CALIB_HEIGHT)
        fx_half, _, cx_half, _, _ = intrinsics(c.D405_CALIB_WIDTH // 2,
                                               c.D405_CALIB_HEIGHT // 2)
        self.assertTrue(real)
        self.assertAlmostEqual(fx_big, c.D405_FX, places=6)
        self.assertAlmostEqual(fx_half, c.D405_FX / 2, places=6)   # 절반이어야 한다
        self.assertAlmostEqual(cx_half, c.D405_CX / 2, places=6)
        # 중심은 늘 화면 안에 있어야 한다
        self.assertTrue(0 <= cx_half <= c.D405_CALIB_WIDTH // 2)

    def test_사진이_2차원이_아니면_거부한다(self):
        with self.assertRaises(ValueError):
            depth_to_points_cam(np.zeros((4, 4, 3)))


if __name__ == "__main__":
    unittest.main()
