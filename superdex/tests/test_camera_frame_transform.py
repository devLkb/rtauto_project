# -*- coding: utf-8 -*-
"""`superdex/scripts/camera_frame_transform.py`의 회귀 시험 (P1-9, 2026-09-21 코드 리뷰).

무엇을 확인하나
---------------
- 자세를 한 좌표 기준에서 다른 기준으로 옮겼다가 되돌리면 원래 값이 나오는가
  (되돌리기가 진짜 역변환인가).
- **핵심 시험**: 같은 물리적인 손 자세를, 서로 다른 두 카메라 시점 기준으로 각각
  옮겨서 `train_pose_predictor._features()`(손바닥 기준 점 특징)를 계산하면,
  **시점이 달라도 똑같은 특징이 나오는가.** 이게 성립해야 "카메라 시점마다 점
  구름·자세를 새로 계산해 짝짓는" 재설계(D-4)가 안전하다 — 안 그러면 시점을
  바꿨다고 같은 자세의 의미가 달라지는 꼴이라 학습이 엉망이 된다.
- 점 구름과 자세를 **같은** 변환으로 옮기면 그 상대 관계(거리·방향)가 안 바뀌는가.

시뮬레이터가 필요 없다 — 전부 합성 변환(임의의 카메라 위치·방향)으로 시험한다.

돌리는 법 (리포 루트, superdex/.venv):

    superdex/.venv/Scripts/Activate.ps1
    python -m unittest superdex.tests.test_camera_frame_transform -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

from camera_frame_transform import (  # noqa: E402
    invert_transform, matrix_to_pose, object_pose_to_camera_frame,
    pose_to_matrix, transform_points, transform_pose,
)
from train_pose_predictor import _features  # noqa: E402


def _quat_from_axis_angle(axis, angle_rad):
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    s = np.sin(angle_rad / 2.0)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(angle_rad / 2.0)])


# 두 개의 서로 다른(그럴듯한) 카메라 시점 — 위치도 방향도 다르다.
_CAM_A = pose_to_matrix(
    pos=(0.15, -0.20, 0.30),
    quat=_quat_from_axis_angle((1.0, 0.3, 0.0), np.radians(35.0)),
)
_CAM_B = pose_to_matrix(
    pos=(-0.10, 0.25, 0.18),
    quat=_quat_from_axis_angle((0.0, 1.0, 0.4), np.radians(-70.0)),
)

# 물체 기준 좌표계 자체도 세계 기준으로 임의 위치/방향에 있다고 둔다.
_T_WORLD_OBJ = pose_to_matrix(
    pos=(0.05, 0.02, 0.01),
    quat=_quat_from_axis_angle((0.2, 0.1, 1.0), np.radians(50.0)),
)


class TestPoseMatrixRoundTrip(unittest.TestCase):
    def test_pose_to_matrix_and_back_is_identity(self):
        pos = (0.1, -0.2, 0.3)
        quat = _quat_from_axis_angle((0.0, 0.0, 1.0), np.radians(40.0))
        mat = pose_to_matrix(pos, quat)
        pos2, quat2 = matrix_to_pose(mat)
        np.testing.assert_allclose(pos2, pos, atol=1e-8)
        # 쿼터니언은 부호가 반대여도 같은 회전이다 — 둘 다 확인.
        same = np.allclose(quat2, quat, atol=1e-6) or np.allclose(quat2, -np.asarray(quat), atol=1e-6)
        self.assertTrue(same)

    def test_transform_then_invert_returns_original_pose(self):
        pos = (0.02, 0.03, -0.01)
        quat = _quat_from_axis_angle((1.0, 1.0, 0.0), np.radians(75.0))
        t_cam_obj = invert_transform(_CAM_A) @ _T_WORLD_OBJ
        pos_cam, quat_cam = transform_pose(t_cam_obj, pos, quat)
        t_obj_cam = invert_transform(t_cam_obj)
        pos_back, quat_back = transform_pose(t_obj_cam, pos_cam, quat_cam)
        np.testing.assert_allclose(pos_back, pos, atol=1e-6)
        same = (np.allclose(quat_back, quat, atol=1e-6)
                or np.allclose(quat_back, -np.asarray(quat), atol=1e-6))
        self.assertTrue(same)

    def test_identity_transform_is_a_no_op(self):
        pos = (0.01, 0.02, 0.03)
        quat = _quat_from_axis_angle((0.0, 1.0, 0.0), np.radians(20.0))
        pos2, quat2 = transform_pose(np.eye(4), pos, quat)
        np.testing.assert_allclose(pos2, pos, atol=1e-8)
        np.testing.assert_allclose(quat2, quat, atol=1e-6)


class TestSameGraspAcrossCameraViews(unittest.TestCase):
    """핵심 시험 — 같은 물리적 자세가 시점을 바꿔도 손바닥 기준 특징이 그대로인가."""

    def setUp(self):
        rng = np.random.default_rng(7)
        self.points_obj = rng.normal(size=(30, 3)).astype(np.float64) * 0.02
        self.pose_pos_obj = np.array([0.01, -0.005, 0.02])
        self.pose_quat_obj = _quat_from_axis_angle((0.3, 0.6, 0.1), np.radians(65.0))

    def _features_in_view(self, t_world_cam):
        t_cam_obj = invert_transform(t_world_cam) @ _T_WORLD_OBJ
        pos_cam, quat_cam = transform_pose(t_cam_obj, self.pose_pos_obj, self.pose_quat_obj)
        points_cam = transform_points(t_cam_obj, self.points_obj)
        return _features(points_cam, pos_cam, quat_cam)

    def test_cloud_feature_matches_object_frame_baseline(self):
        """`_features()`가 돌려주는 두 값 중 **점 구름 특징**(cloud_f, 손바닥 기준으로
        옮긴 점들)은 좌표 기준을 바꿔도 그대로다 — 위 클래스 docstring의 대수적
        증명이 실제 코드에서도 성립하는지 확인."""
        cloud_f_obj, _ = _features(self.points_obj, self.pose_pos_obj, self.pose_quat_obj)
        cloud_f_a, _ = self._features_in_view(_CAM_A)
        np.testing.assert_allclose(cloud_f_a, cloud_f_obj, atol=1e-6)

    def test_cloud_features_are_identical_across_two_different_camera_views(self):
        cloud_f_a, _ = self._features_in_view(_CAM_A)
        cloud_f_b, _ = self._features_in_view(_CAM_B)
        np.testing.assert_allclose(
            cloud_f_a, cloud_f_b, atol=1e-6,
            err_msg="같은 물리적 자세인데 카메라 시점에 따라 손바닥 기준 점 특징이 달라졌다")

    def test_pose_feature_is_NOT_frame_invariant_known_gap_for_camera_frame_redesign(self):
        """🛑 **이 시험은 일부러 "다르다"를 확인한다 — 통과하는 게 정상이다.**

        `_features()`가 돌려주는 두 번째 값(pose_f)은 `pose_quat`을 **그대로**
        내보낸다(train_pose_predictor.py 줄 116) — 손바닥 기준으로 옮기지 않은
        **절대** 방향이다. 물체 기준으로는 물체마다 기준이 고정돼 있어 문제가
        안 됐지만, **카메라 시점마다 기준이 달라지는 재설계(D-4, P1-9)에서는
        같은 물리적 자세인데 어느 시점에서 찍었느냐에 따라 이 값이 달라진다** —
        즉 예측기가 "이 자세가 좋은가"가 아니라 "카메라를 어디 뒀었나"를 배울
        위험이 생긴다.

        이 시험은 그 사실을 **막는** 시험이 아니라 **기록해 두는** 시험이다.
        `build_pose_dataset.py`를 카메라 기준으로 실제로 다시 엮을 때(아직 안
        했다 — 이 모듈 docstring, 시뮬레이터 필요) `train_pose_predictor._features()`
        의 pose_f 항도 같이 재검토해야 한다는 근거로 남긴다
        (`claudeDocs/BACKLOG.md` D-4 항목에 링크).
        """
        _, pose_f_a = self._features_in_view(_CAM_A)
        _, pose_f_b = self._features_in_view(_CAM_B)
        self.assertFalse(
            np.allclose(pose_f_a, pose_f_b, atol=1e-6),
            "pose_f가 시점에 상관없이 같아졌다 — _features()가 바뀌었다면 이 시험과 "
            "위의 '알려진 문제' 설명을 함께 갱신할 것")

    def test_object_pose_to_camera_frame_helper_matches_manual_composition(self):
        """빌드 스크립트가 실제로 부를 헬퍼(`object_pose_to_camera_frame`)가
        수작업으로 합성한 변환과 같은 결과를 내는지 — 실제 연결 지점의 계약."""
        pos_manual, quat_manual = self._pose_via_manual_compose(_CAM_A)
        pos_helper, quat_helper = object_pose_to_camera_frame(
            self.pose_pos_obj, self.pose_quat_obj, _T_WORLD_OBJ, _CAM_A)
        np.testing.assert_allclose(pos_helper, pos_manual, atol=1e-8)
        np.testing.assert_allclose(quat_helper, quat_manual, atol=1e-8)

    def _pose_via_manual_compose(self, t_world_cam):
        t_cam_obj = invert_transform(t_world_cam) @ _T_WORLD_OBJ
        return transform_pose(t_cam_obj, self.pose_pos_obj, self.pose_quat_obj)


class TestPointsAndPoseStayInSameFrame(unittest.TestCase):
    def test_relative_distance_between_points_and_pose_is_frame_invariant(self):
        """점 구름과 자세를 **같은** 변환으로 옮기면 손바닥-점 사이 거리는 그대로다 —
        점 구름과 자세가 실제로 같은 기준으로 짝지어져 있는지 보는 구조적 시험."""
        points = np.array([[0.03, 0.0, 0.0], [0.0, 0.03, 0.0], [-0.02, -0.02, 0.01]])
        pos = np.array([0.0, 0.0, 0.0])
        quat = np.array([0.0, 0.0, 0.0, 1.0])
        dist_before = np.linalg.norm(points - pos[None, :], axis=1)

        t_cam_obj = invert_transform(_CAM_B) @ _T_WORLD_OBJ
        points_cam = transform_points(t_cam_obj, points)
        pos_cam, _ = transform_pose(t_cam_obj, pos, quat)
        dist_after = np.linalg.norm(points_cam - pos_cam[None, :], axis=1)

        np.testing.assert_allclose(dist_after, dist_before, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
