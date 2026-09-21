# -*- coding: utf-8 -*-
"""`segment_objects.remove_plane()` 검증 — **카메라 없이** 돈다.

무엇을 확인하나
---------------
평평한 면(책상)을 뺄 때 남기는 쪽을 **점 개수**가 아니라 **카메라 원점**으로 정하는지
확인한다(2026-09-21 코드 리뷰로 발견·수정). 점 구름은 카메라 기준 좌표계이므로 카메라는
항상 원점 `(0,0,0)`에 있다 — 평면 방정식에 원점을 넣으면 카메라가 어느 쪽인지 점 개수와
무관하게 정해진다.

이 시험은 일부러 **카메라에서 먼 쪽(배경)에 점을 더 많이** 두고, **가까운 쪽(물체)에는
적게** 둔다. 예전 방식("점이 많은 쪽 = 카메라 쪽")이었다면 배경을 남기고 물체를 지웠을
것이다 — 이 시험이 그 회귀를 잡는다.

돌리는 법 (터미널 1, PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python -m unittest vision.d405.tests.test_segment_objects -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import segment_objects as so  # noqa: E402


class TestRemovePlaneCameraSide(unittest.TestCase):
    def _scene(self, rng):
        """책상(넓음, 점 300개) + 카메라 쪽 물체(작음, 점 50개) + 먼 쪽 배경(큼, 점 200개).

        배경이 물체보다 점이 훨씬 많다 — "점이 많은 쪽"을 고르면 배경이 남는다.
        """
        desk = np.column_stack([
            rng.uniform(-0.3, 0.3, 300),
            rng.uniform(-0.3, 0.3, 300),
            np.full(300, 0.30) + rng.normal(0, 0.0003, 300),
        ])
        near_object = np.column_stack([
            rng.uniform(-0.05, 0.05, 50),
            rng.uniform(-0.05, 0.05, 50),
            np.full(50, 0.15),
        ])
        far_background = np.column_stack([
            rng.uniform(-0.3, 0.3, 200),
            rng.uniform(-0.3, 0.3, 200),
            np.full(200, 0.60),
        ])
        return desk, near_object, far_background

    def test_picks_camera_side_even_when_far_side_has_more_points(self):
        rng = np.random.default_rng(0)
        desk, near_object, far_background = self._scene(rng)
        pts = np.vstack([desk, near_object, far_background])

        kept, _, plane, note = so.remove_plane(pts)

        self.assertIsNotNone(plane, "평면을 찾지 못했다 — 시험 장면 구성을 확인하라: " + note)
        # 카메라(원점)에 더 가까운 쪽(z가 작은 쪽 = near_object)만 남아야 한다.
        self.assertGreater(len(kept), 0)
        self.assertTrue(np.all(kept[:, 2] < 0.3),
                         "카메라에서 먼 쪽(배경)이 섞여 있다 — 점 개수로 고른 것으로 의심된다")
        # far_background(200개)가 아니라 near_object(50개) 쪽을 남겼는지 — "많은 쪽"이
        # 아니라 "카메라 쪽"을 골랐다는 직접적인 증거.
        self.assertLess(len(kept), 100,
                         "남은 점이 200개에 가깝다 — far_background(먼 쪽)를 남긴 것으로 보인다")

    def test_flips_correctly_when_plane_normal_points_the_other_way(self):
        """법선 방향은 fit_plane 내부에서 임의로 정해진다(3점을 어떤 순서로 뽑았느냐에 따라
        뒤집힐 수 있다) — d의 부호로 판정하므로 법선이 반대로 나와도 결과가 같아야 한다."""
        rng = np.random.default_rng(1)
        desk, near_object, far_background = self._scene(rng)
        pts = np.vstack([desk, near_object, far_background])

        n, d, inl = so.fit_plane(pts)
        self.assertIsNotNone(n)
        # 법선을 강제로 뒤집어 d의 부호도 반대로 만든 뒤, remove_plane과 같은 판정 로직을
        # 직접 재현해 카메라 쪽이 항상 같은 점 집합으로 나오는지 확인한다.
        flipped_n, flipped_d = -n, -d
        signed = pts @ n + d
        signed_flipped = pts @ flipped_n + flipped_d
        camera_side = signed > so.PLANE_TOL_M if d > 0 else signed < -so.PLANE_TOL_M
        camera_side_flipped = (
            signed_flipped > so.PLANE_TOL_M if flipped_d > 0 else signed_flipped < -so.PLANE_TOL_M
        )
        np.testing.assert_array_equal(camera_side, camera_side_flipped)

    def test_no_plane_found_keeps_original_points(self):
        """책상이 안 보이면(면을 못 찾으면) 통째로 지우지 않고 원본을 그대로 돌려준다."""
        rng = np.random.default_rng(2)
        # 평평한 면이 없는 무작위 점 구름(구 표면 근사) — 어떤 3점을 뽑아도 다른 점들이
        # 거의 안 붙는다.
        pts = rng.normal(size=(200, 3)) * 0.1
        pts[:, 2] += 0.3  # 카메라 앞쪽으로

        kept, _, plane, note = so.remove_plane(pts)

        self.assertIsNone(plane)
        self.assertEqual(len(kept), len(pts))


def _obj(cx, cy, cz, n=200):
    return so.ObjectCloud(
        points=np.zeros((n, 3), dtype=np.float32),
        center=np.array([cx, cy, cz], dtype=np.float64),
        size=np.array([0.06, 0.06, 0.06], dtype=np.float64),
        n_points=n)


class TestTrackerReset(unittest.TestCase):
    """eye-in-hand 이동 중 번호가 잘못 이어 붙지 않도록 하는 `Tracker.reset()`."""

    def test_same_scene_keeps_the_same_id(self):
        """정상 상태(카메라 가만히, 물체도 가만히) — 흔들림 정도는 번호가 유지돼야 한다."""
        t = so.Tracker()
        first = t.update([_obj(0.10, 0.02, 0.20)])
        self.assertEqual(first[0].track_id, 1)
        second = t.update([_obj(0.101, 0.021, 0.199)])   # 미세한 흔들림
        self.assertEqual(second[0].track_id, 1)

    def test_reset_clears_old_tracks_so_ids_start_a_new_session(self):
        """`reset()` 뒤에는 예전 위치와 가까워도 **다시 잇지 않는다** — 새 세션이다."""
        t = so.Tracker()
        first = t.update([_obj(0.10, 0.02, 0.20)])
        self.assertEqual(first[0].track_id, 1)

        t.reset()
        # 이동 뒤 카메라 기준으로는 물체가 전혀 다른 자리에 있는 것처럼 보일 수 있다.
        moved = t.update([_obj(-0.30, 0.15, 0.40)])
        self.assertNotEqual(moved[0].track_id, 1,
                             "reset() 뒤에도 이전 track과 이어붙었다 — 세션이 안 끊겼다")

    def test_reset_does_not_reuse_ids(self):
        """번호를 재사용하면 "3번"이 다른 두 물체를 가리켜 화면에서 헷갈린다."""
        t = so.Tracker()
        first = t.update([_obj(0.10, 0.02, 0.20)])
        first_id = first[0].track_id
        t.reset()
        second = t.update([_obj(0.10, 0.02, 0.20)])   # 같은 자리라도
        self.assertGreater(second[0].track_id, first_id)


class TestGraspCandidate(unittest.TestCase):
    """`is_grasp_candidate()` — 2026-09-21 사용자 결정: "모양" 안전망은 화면엔 계속
    보여주되, 잡으러 가는 후보로는 YOLO 가 확실히 인식한 것만 믿는다.
    """

    def test_yolo_sourced_object_is_a_candidate(self):
        o = _obj(0.1, 0.0, 0.25)
        o.source = "YOLO:bottle 63%"
        self.assertTrue(so.is_grasp_candidate(o))

    def test_geometry_only_object_is_not_a_candidate(self):
        o = _obj(0.1, 0.0, 0.25)
        o.source = "모양"                    # ObjectCloud 기본값과 같다
        self.assertFalse(so.is_grasp_candidate(o))

    def test_default_source_is_not_a_candidate(self):
        """소유자를 아예 안 정한 물체(기본값)는 안전하게 "후보 아님" 쪽으로 떨어져야 한다."""
        o = _obj(0.1, 0.0, 0.25)
        self.assertFalse(so.is_grasp_candidate(o))


if __name__ == "__main__":
    unittest.main()
