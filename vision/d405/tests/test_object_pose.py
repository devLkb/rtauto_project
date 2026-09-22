# -*- coding: utf-8 -*-
"""`vision/d405/object_pose.py` 시험 — **카메라 없이** 전부 돈다.

돌리는 법 (리포 루트)::

    source vision/.vision/bin/activate          # bash
    vision/.vision/Scripts/Activate.ps1         # PowerShell
    python -m unittest vision.d405.tests.test_object_pose -v
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from object_pose import (  # noqa: E402
    FRAME_BASE,
    FRAME_CAMERA,
    LYING,

    ObjectPoseError,
    STANDING,
    _split_source,
    estimate_pose,
    from_object_cloud,
    principal_axes,
    robust_center,
    valid_points,
)


def box_points(center, size, n=500, seed=0):
    """가운데 `center`, 크기 `size` 인 **네모 덩어리** 안에 점을 고루 뿌린다."""
    rng = np.random.default_rng(seed)
    return np.asarray(center) + (rng.random((n, 3)) - 0.5) * np.asarray(size)


class TestValidPoints(unittest.TestCase):
    def test_거리0과_숫자아닌_값은_버린다(self):
        pts = np.array([
            [0.0, 0.0, 0.0],          # 거리 0 = "못 쟀다"
            [0.1, 0.1, 0.2],          # 정상
            [np.nan, 0.0, 0.2],       # NaN
            [0.0, np.inf, 0.2],       # Inf
            [0.0, 0.0, -0.1],         # 음수 거리
        ])
        kept = valid_points(pts)
        self.assertEqual(len(kept), 1)
        np.testing.assert_allclose(kept[0], [0.1, 0.1, 0.2])

    def test_모양이_아니면_막는다(self):
        with self.assertRaises(ObjectPoseError):
            valid_points(np.zeros((5, 2)))


class TestRobustCenter(unittest.TestCase):
    def test_튀는_점_몇_개에_끌려가지_않는다(self):
        """**이것이 중앙값을 쓰는 이유다.** 평균이면 눈에 띄게 밀린다."""
        good = box_points([0.0, 0.0, 0.30], [0.06, 0.06, 0.06], n=200)
        # 반짝이는 면에서 1 m 뒤에 찍힌 가짜 점 10개
        bad = box_points([0.0, 0.0, 1.30], [0.02, 0.02, 0.02], n=10, seed=1)
        pts = np.vstack([good, bad])

        center, kept = robust_center(pts)
        mean_z = float(pts[:, 2].mean())

        self.assertAlmostEqual(center[2], 0.30, delta=0.01)
        self.assertGreater(mean_z, 0.33)                 # 평균은 3 cm 이상 밀렸다
        self.assertEqual(len(kept), 200)                 # 튀는 10개를 버렸다

    def test_쓸_점이_없으면_막는다(self):
        with self.assertRaises(ObjectPoseError):
            robust_center(np.zeros((10, 3)))


class TestPrincipalAxes(unittest.TestCase):
    def test_가장_긴_방향을_찾는다(self):
        pts = box_points([0.4, 0.0, 0.3], [0.04, 0.04, 0.20], n=800)
        axes, extents = principal_axes(pts)

        # 가장 긴 축은 Z 와 나란해야 한다(부호는 상관없다 — 축에는 앞뒤가 없다)
        self.assertGreater(abs(float(axes[2, 0])), 0.98)
        self.assertAlmostEqual(float(extents[0]), 0.20, delta=0.02)
        # ⚠️ 두 번째 축은 0.04 가 아니라 **0.04 ~ 0.057** 사이로 나오는 것이 정상이다.
        #    단면이 정사각형(4x4 cm)이면 어느 쪽이 "두 번째로 긴 축"인지 정해지지
        #    않아 대각선(4x√2 = 5.7 cm) 쪽으로 잡힐 수 있다. 이건 버그가 아니라
        #    돌려도 같은 모양인 물체의 성질이고, 그래서 `orientation_valid` 가 따로 있다.
        self.assertGreaterEqual(float(extents[1]), 0.035)
        self.assertLessEqual(float(extents[1]), 0.060)

    def test_오른손_좌표계로_나온다(self):
        axes, _ = principal_axes(box_points([0, 0, 0.3], [0.05, 0.10, 0.03], n=400))
        self.assertAlmostEqual(float(np.linalg.det(axes)), 1.0, places=6)

    def test_점이_너무_적으면_막는다(self):
        with self.assertRaises(ObjectPoseError):
            principal_axes(np.random.default_rng(0).random((4, 3)) + 0.3)


class TestEstimatePose(unittest.TestCase):
    def test_세워진_것과_누운_것을_가른다(self):
        standing = estimate_pose(box_points([0.4, 0.0, 0.3], [0.05, 0.05, 0.15], n=600),
                                 frame=FRAME_BASE, confidence=0.9)
        lying = estimate_pose(box_points([0.4, 0.0, 0.3], [0.15, 0.05, 0.05], n=600),
                              frame=FRAME_BASE, confidence=0.9)

        self.assertTrue(standing.orientation_valid)
        self.assertEqual(standing.posture(), STANDING)
        self.assertLess(standing.tilt_deg(), 10.0)

        self.assertTrue(lying.orientation_valid)
        self.assertEqual(lying.posture(), LYING)
        self.assertGreater(lying.tilt_deg(), 80.0)

    def test_돌려도_같은_모양이면_방향을_모른다고_말한다(self):
        """🛑 **아는 척하지 않는 것**이 이 시험의 요점이다 (원통·공)."""
        cube = estimate_pose(box_points([0.4, 0.0, 0.3], [0.08, 0.08, 0.08], n=800),
                             frame=FRAME_BASE, confidence=0.9)
        self.assertFalse(cube.orientation_valid)
        self.assertIn("방향", cube.note)
        self.assertEqual(cube.posture(), "모름")

    def test_점이_아주_적으면_위치만_낸다(self):
        pts = np.array([[0.1, 0.0, 0.25], [0.11, 0.01, 0.25], [0.1, 0.0, 0.26]])
        pose = estimate_pose(pts, frame=FRAME_CAMERA)
        self.assertFalse(pose.orientation_valid)
        self.assertAlmostEqual(pose.position[2], 0.25, delta=0.01)
        self.assertIn("방향을 재지 못했다", pose.note)

    def test_좌표_기준_이름을_확인한다(self):
        with self.assertRaises(ObjectPoseError):
            estimate_pose(box_points([0, 0, 0.3], [0.05] * 3), frame="world")


class TestTransformed(unittest.TestCase):
    """**좌표 기준 바꾸기 — 이 파이프라인에서 가장 조용히 틀리는 자리다.**"""

    @staticmethod
    def _transform(rot_z_deg, xyz):
        t = np.eye(4)
        a = math.radians(rot_z_deg)
        t[:3, :3] = np.array([[math.cos(a), -math.sin(a), 0],
                              [math.sin(a), math.cos(a), 0],
                              [0, 0, 1]])
        t[:3, 3] = xyz
        return t

    def test_아는_변환을_넣으면_아는_좌표가_나온다(self):
        pose = estimate_pose(box_points([0.0, 0.0, 0.30], [0.04, 0.04, 0.12], n=400),
                             frame=FRAME_CAMERA, confidence=0.8)
        # 90도 돌리고 (1, 2, 3) 만큼 옮긴다
        moved = pose.transformed(self._transform(90.0, [1.0, 2.0, 3.0]), FRAME_BASE)

        expected = np.array([0.0, 0.0, 3.30])   # (x, y) 는 0 이라 회전해도 0
        expected[0] += 1.0
        expected[1] += 2.0
        np.testing.assert_allclose(moved.position, expected, atol=0.01)
        self.assertEqual(moved.frame, FRAME_BASE)

    def test_옮겨도_크기와_점_개수는_그대로다(self):
        pose = estimate_pose(box_points([0.0, 0.0, 0.30], [0.04, 0.04, 0.12], n=400),
                             frame=FRAME_CAMERA)
        moved = pose.transformed(self._transform(37.0, [0.1, -0.2, 0.3]), FRAME_BASE)
        np.testing.assert_allclose(moved.extents, pose.extents)
        self.assertEqual(moved.n_points, pose.n_points)

    def test_회전하면_기운_각도가_따라_바뀐다(self):
        """좌표를 90도 눕히면 **서 있던 것이 누운 것으로** 판정돼야 한다."""
        pose = estimate_pose(box_points([0.0, 0.0, 0.30], [0.04, 0.04, 0.15], n=600),
                             frame=FRAME_CAMERA)
        # 카메라 기준에서는 위쪽을 직접 알려 줘야 물어볼 수 있다(아래 시험 참고)
        self.assertLess(pose.tilt_deg(up=(0.0, 0.0, 1.0)), 10.0)

        tip = np.eye(4)
        tip[:3, :3] = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])   # X축 90도
        moved = pose.transformed(tip, FRAME_BASE)
        self.assertGreater(moved.tilt_deg(), 80.0)


class TestPostureNeedsBaseFrame(unittest.TestCase):
    """🛑 **2026-09-22 실물 D405 가 잡아낸 진짜 버그.**

    똑바로 서 있는 주스병을 카메라로 보고 "누워 있음(기운 각도 81도)"이라고 했다.
    카메라 좌표는 **Z가 앞쪽(거리)** 이라, 로봇 기준의 위쪽인 (0, 0, 1)을 그대로
    갖다 쓰면 세로로 선 물체가 카메라 광축과 직각이 되어 "누웠다"로 나온다.
    이제는 **조용히 틀린 답을 내는 대신 막는다.**
    """

    @staticmethod
    def _standing_in_camera():
        """카메라 앞에 **똑바로 서 있는** 병 — 카메라 기준에서는 길이가 -Y 쪽이다."""
        return estimate_pose(box_points([0.0, 0.0, 0.25], [0.06, 0.15, 0.06], n=600),
                             frame=FRAME_CAMERA, label="bottle", confidence=0.81)

    def test_카메라_기준에서는_놓인_모습을_묻지_못한다(self):
        pose = self._standing_in_camera()
        with self.assertRaises(ObjectPoseError):
            pose.posture()
        with self.assertRaises(ObjectPoseError):
            pose.tilt_deg()

    def test_로봇_기준으로_옮기면_제대로_나온다(self):
        """카메라가 똑바로 앞을 본다면 카메라의 -Y 가 로봇의 +Z(위)다."""
        pose = self._standing_in_camera()
        cam_to_base = np.eye(4)
        cam_to_base[:3, :3] = np.array([[0.0, 0.0, 1.0],     # 카메라 Z(앞) → 로봇 X
                                        [-1.0, 0.0, 0.0],    # 카메라 X     → 로봇 -Y
                                        [0.0, -1.0, 0.0]])   # 카메라 -Y(위) → 로봇 +Z
        cam_to_base[:3, 3] = [0.3, 0.0, 0.4]
        moved = pose.transformed(cam_to_base, FRAME_BASE)
        self.assertEqual(moved.posture(), STANDING)
        self.assertLess(moved.tilt_deg(), 10.0)

    def test_설명_한_줄은_막지_않고_모른다고_적는다(self):
        """사람이 보는 줄까지 예외로 끊으면 화면이 통째로 안 나온다."""
        text = self._standing_in_camera().describe()
        self.assertIn("아직 모름", text)

    def test_4x4가_아니면_막는다(self):
        pose = estimate_pose(box_points([0, 0, 0.3], [0.04, 0.04, 0.12], n=200))
        with self.assertRaises(ObjectPoseError):
            pose.transformed(np.eye(3), FRAME_BASE)


class TestFromObjectCloud(unittest.TestCase):
    class _Cloud:
        def __init__(self, points, source, estimated=False):
            self.points, self.source, self.estimated = points, source, estimated

    def test_YOLO_이름과_확신을_갈라낸다(self):
        self.assertEqual(_split_source("YOLO:cup 89%"), ("cup", 0.89))
        self.assertEqual(_split_source("YOLO:water bottle 77%"), ("water bottle", 0.77))
        self.assertEqual(_split_source("모양"), ("모양", 0.0))

    def test_ObjectCloud_를_그대로_받는다(self):
        cloud = self._Cloud(box_points([0.0, 0.0, 0.25], [0.05, 0.05, 0.12], n=300),
                            "YOLO:cup 86%", estimated=True)
        pose = from_object_cloud(cloud)
        self.assertEqual(pose.label, "cup")
        self.assertAlmostEqual(pose.confidence, 0.86)
        self.assertTrue(pose.estimated)
        self.assertIn("어림잡은", pose.note)
        self.assertEqual(pose.frame, FRAME_CAMERA)


if __name__ == "__main__":
    unittest.main()
