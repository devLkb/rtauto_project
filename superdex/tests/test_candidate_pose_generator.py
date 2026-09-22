# -*- coding: utf-8 -*-
"""`superdex/scripts/candidate_pose_generator.py`의 회귀 시험 (P1-8, 2026-09-21 코드 리뷰).

무엇을 확인하나
---------------
- 점 구름만 넣으면 후보가 나오는가(물체 이름 같은 추가 정보 없이).
- 나온 자세가 기하적으로 말이 되는가: 손바닥 z축이 물체 중심을 향하는가,
  방향벡터가 전부 위쪽 반구에서만 나오는가(바닥 밑에서 접근하는 후보가 없는가),
  쿼터니언이 단위길이인가.
- 같은 입력이면 같은 결과가 나오는가(결정적 — 재현 가능해야 채점기 비교가 의미있다).
- 좌표 기준을 바꾸지 않는가(넣은 점 구름과 나온 후보 위치가 같은 스케일/원점 근처인가).
- `geometric_pose_score._quat_to_matrix`와 서로 맞물리는 쿼터니언 규약인가.

돌리는 법 (리포 루트, superdex/.venv):

    superdex/.venv/Scripts/Activate.ps1
    python -m unittest superdex.tests.test_candidate_pose_generator -v
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

from candidate_pose_generator import generate_candidates  # noqa: E402
from geometric_pose_score import GRASP_CENTER_PALM, _quat_to_matrix  # noqa: E402


def _cloud(center=(0.3, 0.1, 0.05), radius=0.03, n=200, seed=0):
    rng = np.random.default_rng(seed)
    offsets = rng.normal(size=(n, 3)) * radius * 0.4
    return np.asarray(center, dtype=np.float64) + offsets


class TestGenerateCandidatesBasics(unittest.TestCase):
    def test_empty_points_returns_empty_candidates(self):
        pos, quat = generate_candidates(np.zeros((0, 3)))
        self.assertEqual(pos.shape, (0, 3))
        self.assertEqual(quat.shape, (0, 4))

    def test_no_object_identity_parameter_exists(self):
        """CLAUDE.md '범용 파지' 원칙 — 물체 이름/식별을 받는 인자가 있으면 안 된다."""
        params = set(inspect.signature(generate_candidates).parameters)
        for banned in ("object_name", "object_id", "label", "class_id"):
            self.assertNotIn(banned, params)

    def test_returns_requested_number_of_candidates(self):
        pos, quat = generate_candidates(_cloud(), n_directions=8)
        self.assertEqual(pos.shape, (8, 3))
        self.assertEqual(quat.shape, (8, 4))

    def test_all_values_finite(self):
        pos, quat = generate_candidates(_cloud(), n_directions=10)
        self.assertTrue(np.isfinite(pos).all())
        self.assertTrue(np.isfinite(quat).all())

    def test_quaternions_are_unit_norm(self):
        _, quat = generate_candidates(_cloud(), n_directions=10)
        norms = np.linalg.norm(quat, axis=1)
        np.testing.assert_allclose(norms, np.ones(len(quat)), atol=1e-8)

    def test_deterministic_same_input_same_output(self):
        cloud = _cloud()
        pos1, quat1 = generate_candidates(cloud, n_directions=10)
        pos2, quat2 = generate_candidates(cloud, n_directions=10)
        np.testing.assert_array_equal(pos1, pos2)
        np.testing.assert_array_equal(quat1, quat2)


class TestGenerateCandidatesGeometry(unittest.TestCase):
    def test_positions_are_standoff_distance_from_centroid(self):
        cloud = _cloud(center=(0.3, 0.1, 0.05), radius=0.03)
        centroid = cloud.mean(axis=0)
        pos, _ = generate_candidates(cloud, n_directions=10)
        expected_standoff = float(np.linalg.norm(GRASP_CENTER_PALM)) + float(
            np.max(np.linalg.norm(cloud - centroid, axis=1))
        )
        dist = np.linalg.norm(pos - centroid[None, :], axis=1)
        np.testing.assert_allclose(dist, np.full(len(pos), expected_standoff), atol=1e-8)

    def test_candidates_stay_in_upper_hemisphere_of_up_axis(self):
        """바닥 밑에서(위 방향과 반대쪽에서) 접근하는 후보는 나오면 안 된다."""
        cloud = _cloud()
        centroid = cloud.mean(axis=0)
        up = np.array([0.0, 0.0, 1.0])
        pos, _ = generate_candidates(cloud, n_directions=16, up_axis=up)
        dirs = pos - centroid[None, :]
        dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
        self.assertTrue((dirs @ up > 0).all(), "위쪽 반구를 벗어난 접근 방향이 있다")

    def test_palm_forward_axis_points_toward_centroid(self):
        """쿼터니언이 나타내는 손바닥 z축(손가락 방향)을 실제로 돌려 보면 물체
        중심을 향해야 한다 — `geometric_pose_score._quat_to_matrix`로 검증."""
        cloud = _cloud()
        centroid = cloud.mean(axis=0)
        pos, quat = generate_candidates(cloud, n_directions=10)
        for p, q in zip(pos, quat):
            rot = _quat_to_matrix(q)
            forward_world = rot @ np.array([0.0, 0.0, 1.0])
            to_centroid = centroid - p
            to_centroid = to_centroid / np.linalg.norm(to_centroid)
            cos_angle = float(np.dot(forward_world, to_centroid))
            self.assertGreater(cos_angle, 0.999, "손바닥 z축이 물체 중심을 향하지 않는다")

    def test_output_frame_matches_input_frame_not_recentered(self):
        """입력 점 구름을 다른 원점으로 옮기면 후보도 그만큼 옮겨져야 한다 —
        좌표 기준을 바꾸지 않는다는 것(P1-9와 같은 원칙)을 확인한다."""
        cloud = _cloud(center=(0.3, 0.1, 0.05))
        shift = np.array([10.0, -5.0, 2.0])
        pos_a, _ = generate_candidates(cloud, n_directions=6)
        pos_b, _ = generate_candidates(cloud + shift, n_directions=6)
        np.testing.assert_allclose(pos_b - pos_a, np.tile(shift, (6, 1)), atol=1e-8)

    def test_custom_standoff_is_respected(self):
        cloud = _cloud()
        centroid = cloud.mean(axis=0)
        pos, _ = generate_candidates(cloud, n_directions=5, standoff=0.5)
        dist = np.linalg.norm(pos - centroid[None, :], axis=1)
        np.testing.assert_allclose(dist, np.full(5, 0.5), atol=1e-8)


if __name__ == "__main__":
    unittest.main()
