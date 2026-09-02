# -*- coding: utf-8 -*-
"""multiview_landmarks.py 검증 — 가짜 MediaPipe 결과 객체로 배선(wiring)만 확인.

실제 MediaPipe 정확도 검증은 여기서 하지 않는다(그건 실물 카메라+손으로만 가능). 여기서는
"MediaPipe 결과 형태(multi_hand_landmarks[0].landmark[i].x/y, 정규화 0~1)를 픽셀로
바꾸고 삼각측량에 올바르게 넘기는가"라는 배선만 합성 데이터로 확인한다.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import camera_calibration as cc
from multiview_landmarks import hand_landmarks_to_pixels, triangulate_hands


class _FakeLandmark:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class _FakeLandmarkList:
    def __init__(self, points_xy):
        self.landmark = [_FakeLandmark(x, y) for x, y in points_xy]


class _FakeMediapipeResult:
    def __init__(self, landmark_list):
        self.multi_hand_landmarks = [landmark_list] if landmark_list is not None else []


def _synthetic_rig(width=640, height=480):
    K = np.array([[800.0, 0.0, width / 2], [0.0, 800.0, height / 2], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    centers = {0: np.array([0.0, 0.0, 0.0]),
               1: np.array([100.0, 0.0, 0.0]),
               2: np.array([50.0, 80.0, 0.0])}
    intrinsics = {idx: {"camera_matrix": K, "dist_coeffs": dist} for idx in centers}
    extrinsics = {idx: (np.eye(3), -c) for idx, c in centers.items()}
    return cc.build_camera_rig(intrinsics, extrinsics, verbose=False), K, extrinsics


def _project_to_normalized(K, R, t, points_world, width, height):
    cam_pts = (R @ points_world.T).T + t
    proj = (K @ cam_pts.T).T
    pixels = proj[:, :2] / proj[:, 2:3]
    return pixels / np.array([width, height])  # MediaPipe 규약: 0~1 정규화


class HandLandmarksToPixelsTest(unittest.TestCase):
    def test_scales_normalized_coords_to_pixels(self):
        ll = _FakeLandmarkList([(0.5, 0.5), (0.25, 0.75)])
        pixels = hand_landmarks_to_pixels(ll, width=640, height=480)
        np.testing.assert_allclose(pixels, [[320.0, 240.0], [160.0, 360.0]])


class TriangulateHandsTest(unittest.TestCase):
    def test_recovers_landmarks_from_three_camera_results(self):
        width, height = 640, 480
        rig, K, extrinsics = _synthetic_rig(width, height)
        world_points = np.array([[0.0, 0.0, 700.0], [20.0, -10.0, 650.0], [-30.0, 15.0, 800.0]])

        per_camera_results = {}
        for idx, (R, t) in extrinsics.items():
            norm = _project_to_normalized(K, R, t, world_points, width, height)
            per_camera_results[idx] = (_FakeMediapipeResult(_FakeLandmarkList(norm)), width, height)

        recovered = triangulate_hands(per_camera_results, rig, min_views=2)
        self.assertIsNotNone(recovered)
        np.testing.assert_allclose(recovered, world_points, atol=1e-2)

    def test_missing_detection_in_one_camera_still_recovers_from_the_rest(self):
        width, height = 640, 480
        rig, K, extrinsics = _synthetic_rig(width, height)
        world_points = np.array([[5.0, 5.0, 700.0]])

        per_camera_results = {}
        for idx in (0, 1):
            R, t = extrinsics[idx]
            norm = _project_to_normalized(K, R, t, world_points, width, height)
            per_camera_results[idx] = (_FakeMediapipeResult(_FakeLandmarkList(norm)), width, height)
        per_camera_results[2] = (_FakeMediapipeResult(None), width, height)  # 카메라 2는 미검출

        recovered = triangulate_hands(per_camera_results, rig, min_views=2)
        self.assertIsNotNone(recovered)
        np.testing.assert_allclose(recovered, world_points, atol=1e-2)

    def test_all_cameras_missing_detection_returns_none(self):
        width, height = 640, 480
        rig, _, _ = _synthetic_rig(width, height)
        per_camera_results = {idx: (_FakeMediapipeResult(None), width, height) for idx in (0, 1, 2)}
        self.assertIsNone(triangulate_hands(per_camera_results, rig, min_views=2))


if __name__ == "__main__":
    unittest.main()
