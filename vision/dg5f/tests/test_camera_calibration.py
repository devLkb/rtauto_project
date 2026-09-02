# -*- coding: utf-8 -*-
"""camera_calibration.py 검증 — 실물 카메라 없이 합성(synthetic) 카메라 3대로 삼각측량 정확도를 확인.

실물 웹캠이 아직 연결 안 된 상태에서도 "여러 시점의 2D를 하나의 3D로 정확히 복원하는가"라는
핵심 수학은 이렇게 검증 가능하다: 알고 있는 3D 점을 가상의 카메라 3대에 투영해 2D 좌표를
만든 뒤, 그 2D 좌표만 갖고 원래 3D 점을 얼마나 정확히 복원하는지 비교한다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import camera_calibration as cc
from calibrate_extrinsics import _average_rt


def _synthetic_rig():
    """세 카메라(회전 없음, 위치만 다름)가 +Z 방향을 보는 합성 리그. 왜곡 없음(dist=0)."""
    K = np.array([[800.0, 0.0, 320.0],
                  [0.0, 800.0, 240.0],
                  [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    centers = {0: np.array([0.0, 0.0, 0.0]),
               1: np.array([100.0, 0.0, 0.0]),
               2: np.array([50.0, 80.0, 0.0])}
    intrinsics = {idx: {"camera_matrix": K, "dist_coeffs": dist} for idx in centers}
    # X_cam = R@X_world + t, R=identity → t = -center
    extrinsics = {idx: (np.eye(3), -c) for idx, c in centers.items()}
    return intrinsics, extrinsics, K, dist, centers


def _project(K, dist, R, t, points_world):
    """cv2 없이 직접 투영(왜곡 없음 가정) — 테스트 데이터 생성용 순수 계산."""
    cam_pts = (R @ points_world.T).T + t
    proj = (K @ cam_pts.T).T
    pixels = proj[:, :2] / proj[:, 2:3]
    return pixels


class ChessboardObjectPointsTest(unittest.TestCase):
    def test_shape_and_spacing(self):
        objp = cc.chessboard_object_points(cols=9, rows=6, square_size_mm=25.0)
        self.assertEqual(objp.shape, (54, 3))
        self.assertTrue(np.allclose(objp[:, 2], 0.0))
        # 두 번째 코너(같은 행, 다음 열)는 한 칸(25mm)만큼 X가 커야 한다
        self.assertAlmostEqual(objp[1, 0] - objp[0, 0], 25.0)


class TriangulationTest(unittest.TestCase):
    def test_recovers_known_3d_points_from_three_views(self):
        intrinsics, extrinsics, K, dist, centers = _synthetic_rig()
        rig = cc.build_camera_rig(intrinsics, extrinsics)

        rng = np.random.default_rng(0)
        n_points = 21  # 손 랜드마크 개수와 맞춰 현실적인 사용례로
        world_points = np.column_stack([
            rng.uniform(-100, 100, n_points),
            rng.uniform(-100, 100, n_points),
            rng.uniform(500, 900, n_points),
        ])

        per_camera_pixels = {}
        for idx, (R, t) in extrinsics.items():
            per_camera_pixels[idx] = _project(K, dist, R, t, world_points)

        recovered = cc.triangulate_landmark_set(per_camera_pixels, rig, min_views=2)
        self.assertIsNotNone(recovered)
        np.testing.assert_allclose(recovered, world_points, atol=1e-3)

    def test_works_with_only_two_of_three_cameras(self):
        intrinsics, extrinsics, K, dist, centers = _synthetic_rig()
        rig = cc.build_camera_rig(intrinsics, extrinsics)
        world_points = np.array([[10.0, -20.0, 700.0], [-30.0, 40.0, 600.0]])

        per_camera_pixels = {}
        for idx in (0, 1):
            R, t = extrinsics[idx]
            per_camera_pixels[idx] = _project(K, dist, R, t, world_points)
        per_camera_pixels[2] = None  # 카메라 2는 이번 프레임에 손을 못 봤다고 가정

        recovered = cc.triangulate_landmark_set(per_camera_pixels, rig, min_views=2)
        self.assertIsNotNone(recovered)
        np.testing.assert_allclose(recovered, world_points, atol=1e-3)

    def test_single_view_is_insufficient(self):
        intrinsics, extrinsics, K, dist, centers = _synthetic_rig()
        rig = cc.build_camera_rig(intrinsics, extrinsics)
        world_points = np.array([[0.0, 0.0, 700.0]])
        R, t = extrinsics[0]
        per_camera_pixels = {0: _project(K, dist, R, t, world_points), 1: None, 2: None}

        recovered = cc.triangulate_landmark_set(per_camera_pixels, rig, min_views=2)
        self.assertIsNone(recovered)

    def test_recovers_known_3d_points_with_lens_distortion(self):
        """왜곡=0인 앞선 테스트만으로는 undistort_normalize가 실제로 왜곡을 없애는지 검증되지
        않는다(항등 변환이어도 통과함) — 실제 렌즈처럼 0이 아닌 dist_coeffs로 픽셀을 만들어,
        그걸 다시 없애고 삼각측량까지 정확히 되는지 확인한다."""
        K = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
        dist = np.array([0.15, -0.08, 0.001, -0.0005, 0.01])  # 실측 배럴 왜곡과 유사한 크기
        centers = {0: np.array([0.0, 0.0, 0.0]), 1: np.array([120.0, 0.0, 0.0]),
                   2: np.array([60.0, 90.0, 0.0])}
        intrinsics = {idx: {"camera_matrix": K, "dist_coeffs": dist} for idx in centers}
        extrinsics = {idx: (np.eye(3), -c) for idx, c in centers.items()}
        rig = cc.build_camera_rig(intrinsics, extrinsics, verbose=False)

        rng = np.random.default_rng(7)
        world_points = np.column_stack([
            rng.uniform(-80, 80, 21), rng.uniform(-80, 80, 21), rng.uniform(500, 900, 21),
        ])
        per_camera_pixels = {}
        for idx, (R, t) in extrinsics.items():
            rvec, _ = cv2.Rodrigues(R)
            pixels, _ = cv2.projectPoints(world_points, rvec, t, K, dist)
            per_camera_pixels[idx] = pixels.reshape(-1, 2)

        recovered = cc.triangulate_landmark_set(per_camera_pixels, rig, min_views=2)
        self.assertIsNotNone(recovered)
        np.testing.assert_allclose(recovered, world_points, atol=1e-3)

    def test_triangulate_point_needs_at_least_two_views(self):
        self.assertIsNone(cc.triangulate_point([(np.eye(3, 4), (0.0, 0.0))]))


class BuildCameraRigTest(unittest.TestCase):
    def test_drops_cameras_missing_extrinsics_without_crashing(self):
        intrinsics, extrinsics, K, dist, centers = _synthetic_rig()
        extrinsics_missing_one = {idx: rt for idx, rt in extrinsics.items() if idx != 2}
        rig = cc.build_camera_rig(intrinsics, extrinsics_missing_one, verbose=False)
        self.assertEqual(sorted(rig.keys()), [0, 1])
        self.assertNotIn(2, rig)

    def test_verbose_reports_dropped_cameras(self):
        import io
        from contextlib import redirect_stdout

        intrinsics, extrinsics, K, dist, centers = _synthetic_rig()
        extrinsics_missing_one = {idx: rt for idx, rt in extrinsics.items() if idx != 2}
        out = io.StringIO()
        with redirect_stdout(out):
            cc.build_camera_rig(intrinsics, extrinsics_missing_one, verbose=True)
        self.assertIn("2", out.getvalue())


class IntrinsicsExtrinsicsIOTest(unittest.TestCase):
    def test_intrinsics_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            K = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
            dist = np.array([0.1, -0.05, 0.001, 0.002, 0.0])
            cc.save_intrinsics(tmp, 0, K, dist, 640, 480)
            loaded = cc.load_intrinsics(tmp, 0)
            self.assertEqual(loaded["index"], 0)
            self.assertEqual((loaded["image_width"], loaded["image_height"]), (640, 480))
            np.testing.assert_allclose(loaded["camera_matrix"], K)
            np.testing.assert_allclose(loaded["dist_coeffs"], dist)

    def test_missing_intrinsics_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(cc.load_intrinsics(tmp, 5))

    def test_load_all_intrinsics_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            K, dist = np.eye(3), np.zeros(5)
            cc.save_intrinsics(tmp, 0, K, dist, 640, 480)
            cc.save_intrinsics(tmp, 2, K, dist, 640, 480)
            loaded = cc.load_all_intrinsics(tmp, [0, 1, 2])
            self.assertEqual(sorted(loaded.keys()), [0, 2])

    def test_extrinsics_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cameras = {0: (np.eye(3), np.zeros(3)),
                       1: (np.eye(3), np.array([100.0, 0.0, 0.0]))}
            cc.save_extrinsics(tmp, cameras, square_size_mm=25.0)
            loaded, square = cc.load_extrinsics(tmp)
            self.assertEqual(square, 25.0)
            self.assertEqual(set(loaded.keys()), {0, 1})
            np.testing.assert_allclose(loaded[1][1], [100.0, 0.0, 0.0])

    def test_missing_extrinsics_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cameras, square = cc.load_extrinsics(tmp)
            self.assertEqual(cameras, {})
            self.assertIsNone(square)


class AverageRtTest(unittest.TestCase):
    def test_identical_captures_average_to_the_same_pose(self):
        R = np.eye(3)
        t = np.array([10.0, 20.0, 300.0])
        R_avg, t_avg = _average_rt([(R, t)] * 5)
        np.testing.assert_allclose(R_avg, R, atol=1e-9)
        np.testing.assert_allclose(t_avg, t, atol=1e-9)

    def test_output_rotation_stays_orthogonal(self):
        rng = np.random.default_rng(1)
        rt_list = []
        for _ in range(6):
            noise = rng.normal(scale=0.02, size=3)
            R_noisy, _ = cv2.Rodrigues(noise)
            rt_list.append((R_noisy, rng.normal(scale=1.0, size=3)))
        R_avg, _ = _average_rt(rt_list)
        np.testing.assert_allclose(R_avg @ R_avg.T, np.eye(3), atol=1e-9)
        self.assertAlmostEqual(np.linalg.det(R_avg), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
