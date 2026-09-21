# -*- coding: utf-8 -*-
"""`superdex/scripts/train_pose_predictor.py`의 순수 로직(torch 없이) 회귀 시험.

무엇을 확인하나
---------------
`_features()`/`load_pairs()`는 torch를 전혀 쓰지 않는다(`train_pose_predictor.py`가
torch를 모듈 최상단에서 import하지 않고 `make_model(torch, nn)`처럼 인자로 받는
구조라서) — 그래서 이 시험은 **torch 없이도** CI에서 돌 수 있다(P2-4).

- `_features()`가 점 구름을 손바닥 기준으로 옮기고, 출력이 항상 유한한 숫자인지
- `load_pairs()`가 애매한 성공률(BAD_RATE~GOOD_RATE 사이)을 학습에서 빼는지
- `load_pairs()`가 각 자세를 **같은 물체의 점 구름들**과만 짝짓는지(다른 물체 것과
  안 섞이는지) — §7-3이 지키려는 "입력 분리"와는 별개로, 데이터 자체가 맞게
  짝지어지는지를 보는 배관 시험이다.

돌리는 법 (리포 루트, superdex/.venv, torch 설치 여부와 무관):

    superdex/.venv/Scripts/Activate.ps1
    python -m unittest superdex.tests.test_train_pose_predictor_features -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

from train_pose_predictor import (  # noqa: E402
    BAD_RATE, GOOD_RATE, _features, load_pairs,
)


class TestFeatures(unittest.TestCase):
    def test_output_is_finite_and_shaped_like_input_points(self):
        rng = np.random.default_rng(0)
        points = rng.normal(size=(30, 3)).astype(np.float64) * 0.05
        pose_pos = np.array([0.01, -0.02, 0.03], dtype=np.float64)
        pose_quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)

        cloud_f, pose_f = _features(points, pose_pos, pose_quat)

        self.assertEqual(cloud_f.shape, points.shape)
        self.assertEqual(pose_f.shape, (4,))
        self.assertTrue(np.isfinite(cloud_f).all())
        self.assertTrue(np.isfinite(pose_f).all())

    def test_translates_points_relative_to_palm(self):
        """손바닥 위치를 원점으로 옮긴다 — 손바닥 자체를 넣으면 결과가 0 근처여야 한다."""
        pose_pos = np.array([0.1, 0.2, 0.3], dtype=np.float64)
        pose_quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)  # 항등 회전
        cloud_f, _ = _features(np.array([pose_pos]), pose_pos, pose_quat)
        np.testing.assert_allclose(cloud_f[0], [0.0, 0.0, 0.0], atol=1e-5)


def _write_dataset(path: Path) -> None:
    """물체 2종(a, b), 자세 5개(좋음/나쁨/애매 섞임) — load_pairs()가 애매한 것을
    빼고 물체별로 점 구름을 제대로 짝짓는지 보는 최소 데이터셋."""
    rng = np.random.default_rng(1)
    cloud_a1 = rng.normal(size=(10, 3)).astype(np.float32) * 0.02
    cloud_a2 = rng.normal(size=(10, 3)).astype(np.float32) * 0.02
    cloud_b1 = rng.normal(size=(10, 3)).astype(np.float32) * 0.02
    points = np.concatenate([cloud_a1, cloud_a2, cloud_b1])
    cloud_start = np.array([0, 10, 20, 30], dtype=np.int64)
    cloud_object = np.array(["a", "a", "b"], dtype=object)

    pose_pos = np.zeros((5, 3), dtype=np.float32)
    pose_quat = np.tile(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32), (5, 1))
    # 0: a, 좋음(1.0) / 1: a, 나쁨(0.0) / 2: a, 애매(0.5, 빠져야 함) /
    # 3: b, 좋음(1.0) / 4: b, 나쁨(0.0)
    pose_rate = np.array([1.0, 0.0, 0.5, 1.0, 0.0], dtype=np.float32)
    pose_tilt = np.array([1.0, 999.0, 1.0, 1.0, 999.0], dtype=np.float32)
    pose_object = np.array(["a", "a", "a", "b", "b"], dtype=object)

    np.savez_compressed(
        path, points=points, cloud_start=cloud_start, cloud_object=cloud_object,
        pose_pos=pose_pos, pose_quat=pose_quat, pose_rate=pose_rate,
        pose_tilt=pose_tilt, pose_object=pose_object,
        frame=np.asarray("camera"), made_from=np.asarray("test"),
    )


class TestLoadPairs(unittest.TestCase):
    def test_ambiguous_rate_is_dropped(self):
        """BAD_RATE~GOOD_RATE 사이(애매한 성공률)인 자세 2번은 학습에서 빠져야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ds.npz"
            _write_dataset(path)
            samples, objects = load_pairs(str(path))

        self.assertEqual(sorted(objects), ["a", "b"])
        pose_indices = {s[4] for s in samples}
        self.assertNotIn(2, pose_indices, "애매한 성공률(0.5)인 자세가 학습에 섞여 들어갔다")
        self.assertIn(0, pose_indices)
        self.assertIn(3, pose_indices)

    def test_each_pose_only_pairs_with_its_own_object_clouds(self):
        """물체 a의 자세(0, 1)는 물체 a의 점 구름(2장)하고만 짝지어져야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ds.npz"
            _write_dataset(path)
            samples, _ = load_pairs(str(path))

        a_pairs = [s for s in samples if s[4] in (0, 1)]
        b_pairs = [s for s in samples if s[4] in (3, 4)]
        self.assertEqual(len(a_pairs), 2 * 2)  # 자세 2개 x 물체 a 점 구름 2장
        self.assertEqual(len(b_pairs), 2 * 1)  # 자세 2개 x 물체 b 점 구름 1장
        self.assertTrue(all(s[3] == "a" for s in a_pairs))
        self.assertTrue(all(s[3] == "b" for s in b_pairs))

    def test_labels_require_both_rate_and_tilt(self):
        """성공률만 좋고(rate>=GOOD_RATE) 기울기가 나쁘면 label은 0이어야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ds_tilt.npz"
            points = np.random.default_rng(2).normal(size=(10, 3)).astype(np.float32) * 0.02
            np.savez_compressed(
                path, points=points, cloud_start=np.array([0, 10], dtype=np.int64),
                cloud_object=np.array(["a"], dtype=object),
                pose_pos=np.zeros((1, 3), dtype=np.float32),
                pose_quat=np.tile(np.array([0, 0, 0, 1], dtype=np.float32), (1, 1)),
                pose_rate=np.array([1.0], dtype=np.float32),
                pose_tilt=np.array([999.0], dtype=np.float32),  # 성공률은 좋지만 기울기가 나쁨
                pose_object=np.array(["a"], dtype=object),
                frame=np.asarray("camera"), made_from=np.asarray("test"),
            )
            samples, _ = load_pairs(str(path))
        labels = {s[4]: s[2] for s in samples}
        self.assertEqual(labels[0], 0.0, "성공률은 좋지만 기울기가 나쁜 자세가 좋은 것으로 잘못 라벨링됨")


if __name__ == "__main__":
    unittest.main()
