# -*- coding: utf-8 -*-
"""`yolo_assist.py` 검증 — **카메라도 YOLO 모델도 없이** 돈다.

무엇을 확인하나
---------------
1. **좌표가 맞는가** — 깊이 사진은 줄이기(decimation) 때문에 색 사진의 **절반 크기**다
   (640x480 → 320x240). 그래서 깊이 화소 번호를 그대로 YOLO 테두리에 대면 **엉뚱한 곳**을
   보게 된다. 실제로 그렇게 되어 있었다(2026-09-18 발견).
2. **거리값이 듬성듬성해도 물체를 내는가** — 흰 종이컵은 값이 몇 개밖에 안 나온다.
   그때도 위치와 크기를 내야 한다.
3. **여러 장을 합치면 값이 늘어나는가** — 지어내지 않고, 한 번이라도 나온 값만 모은다.

돌리는 법 (터미널 1, PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python -m pytest vision/d405/tests/test_yolo_assist.py -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import depth_stack                                     # noqa: E402
from yolo_assist import (Detection, split_by_boxes, ESTIMATE_BAND_M,   # noqa: E402
                         find_objects_hybrid, suppress_cross_class_duplicates,
                         CROSS_CLASS_MIN_DEPTH_POINTS)
import rtauto_config as cfg                            # noqa: E402  (yolo_assist가 먼저 sys.path를 잡아 둔다)


class _Intr:
    """D405 의 초점거리·중심을 흉내 낸 것. 줄인 사진(320x240) 기준이다."""
    fx = fy = 320.0
    ppx, ppy = 160.0, 120.0


COLOR_SHAPE = (480, 640)      # 색 사진 (세로, 가로)
DEPTH_SHAPE = (240, 320)      # 줄인 깊이 사진 — **색 사진의 절반**


def _cup_detection(u1, v1, u2, v2, conf=0.9, name="cup"):
    """색 사진 좌표 `(u1,v1)~(u2,v2)` 를 꽉 채우는 테두리를 가진 YOLO 결과 하나."""
    mask = np.zeros(COLOR_SHAPE, dtype=np.float32)
    mask[v1:v2, u1:u2] = 1.0
    return Detection(name=name, conf=conf, box=(u1, v1, u2, v2), mask=mask)


def _points_on_rect(u1, v1, u2, v2, z, step=2):
    """색 사진 좌표의 네모 안을 채우는 3D 점과 **깊이 사진 기준** 화소 번호를 만든다."""
    us = np.arange(u1 + 1, u2 - 1, step, dtype=float)
    vs = np.arange(v1 + 1, v2 - 1, step, dtype=float)
    uu, vv = np.meshgrid(us, vs)
    uu, vv = uu.ravel(), vv.ravel()
    du, dv = uu / 2.0, vv / 2.0                 # 색 → 깊이 좌표 (절반)
    pts = np.stack([(du - _Intr.ppx) * z / _Intr.fx,
                    (dv - _Intr.ppy) * z / _Intr.fy,
                    np.full(du.shape, z)], axis=1)
    return pts, (du, dv)


class TestCoordinateSpace(unittest.TestCase):
    """깊이 화소 번호를 **색 사진 좌표로 환산**하고 나서 테두리에 대야 한다."""

    def test_center_object_is_found(self):
        # 색 사진 한가운데에 있는 컵. 환산을 빠뜨리면 이 점들은 테두리 밖으로 밀려난다.
        det = _cup_detection(280, 200, 360, 300)
        pts, pix = _points_on_rect(280, 200, 360, 300, z=0.25)

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1, "가운데 있는 컵을 통째로 놓쳤다 — 좌표 환산 문제")
        self.assertLess(len(rest), len(pts) * 0.1, "컵의 점이 남은 점으로 새어 나갔다")

    def test_points_outside_mask_are_left_alone(self):
        """테두리 밖의 점은 **건드리지 않고** 모양 쪽으로 넘겨야 한다."""
        det = _cup_detection(40, 40, 120, 140)
        inside, pix_in = _points_on_rect(40, 40, 120, 140, z=0.20)
        outside, pix_out = _points_on_rect(400, 300, 480, 400, z=0.30)

        pts = np.vstack([inside, outside])
        pix = (np.concatenate([pix_in[0], pix_out[0]]),
               np.concatenate([pix_in[1], pix_out[1]]))

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        self.assertGreaterEqual(len(rest), len(outside) * 0.9,
                                "테두리 밖의 점까지 먹어 치웠다")


class TestSparseDepth(unittest.TestCase):
    """**흰 종이컵처럼 값이 몇 개 안 나올 때도** 위치와 크기를 내야 한다."""

    def test_few_points_still_give_an_object(self):
        # 색 사진에서 80x100 화소짜리 컵인데, 거리값은 **12개**밖에 없다.
        det = _cup_detection(280, 190, 360, 290)
        pts, pix = _points_on_rect(280, 190, 360, 290, z=0.25, step=2)
        keep = np.linspace(0, len(pts) - 1, 12).astype(int)
        pts, pix = pts[keep], (pix[0][keep], pix[1][keep])

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1, "점이 적다고 물체를 통째로 버렸다")
        o = objs[0]
        self.assertTrue(o.estimated, "추정으로 낸 것임을 표시해야 한다")

        # 참값: 가로 80 화소 → 깊이 사진 40 화소 → 40 * 0.25 / 320 = 3.1 cm
        #       세로 100 화소 → 50 화소 → 50 * 0.25 / 320 = 3.9 cm
        self.assertAlmostEqual(o.size[0], 0.0313, delta=0.004)
        self.assertAlmostEqual(o.size[1], 0.0391, delta=0.004)
        self.assertAlmostEqual(o.distance_m, 0.25, delta=0.01)

    def test_nothing_at_all_is_still_nothing(self):
        """값이 **하나도 없으면** 지어내지 않는다 — 물체를 안 낸다."""
        det = _cup_detection(280, 190, 360, 290)
        far_pts, far_pix = _points_on_rect(40, 40, 100, 100, z=0.30)

        objs, rest = split_by_boxes(far_pts, far_pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(objs, [], "거리값이 없는데 물체를 지어냈다")
        self.assertEqual(len(rest), len(far_pts))


class TestOwnership(unittest.TestCase):
    """**소유(ownership)와 계측(measurement)은 다르다** — 마스크 안의 점은 크기 계산에
    실제로 썼는지와 무관하게 전부 이 YOLO 물체가 소유하며, 다른 후보(geometry 쪽)로
    다시 넘어가면 안 된다 (2026-09-21, 바깥 조언자 진단 — 세션 18 §B의 재발 방지 시험).
    """

    def test_owned_but_unmeasured_points_do_not_leak_to_geometry_fallback(self):
        """마스크 안에 거리 차가 큰 두 무리가 있으면 `_merge_pieces()`가 **가까운 무리만**
        계측에 쓴다. 예전에는 나머지(먼 무리)가 "쓰지 않은 점"으로 남에게 넘어가
        모양 쪽에서 **같은 물체를 또 만들었다.** 지금은 둘 다 이 detection의 소유라서
        `rest` 로 새어 나가면 안 된다."""
        det = _cup_detection(280, 190, 360, 290)
        near, near_pix = _points_on_rect(280, 190, 360, 290, z=0.20)
        # ESTIMATE_BAND_M(0.05m) 보다 훨씬 먼 무리 — 같은 마스크 안이지만 병합 대상이 아니다.
        far, far_pix = _points_on_rect(280, 190, 360, 290, z=0.20 + 10 * ESTIMATE_BAND_M)

        pts = np.vstack([near, far])
        pix = (np.concatenate([near_pix[0], far_pix[0]]),
              np.concatenate([near_pix[1], far_pix[1]]))

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1, "가까운 무리로 물체 하나는 나와야 한다")
        self.assertAlmostEqual(objs[0].distance_m, 0.20, delta=0.01,
                               msg="계측은 여전히 가까운 무리를 써야 한다")
        self.assertEqual(len(rest), 0,
                         "계측에 안 쓴(먼 무리) 점이 geometry fallback으로 새어 나갔다 — "
                         "같은 물체가 또 생길 수 있다")

    def test_higher_confidence_detection_owns_partially_overlapping_points(self):
        """두 YOLO 마스크가 **부분적으로 겹치면**(포함 관계 아님), 겹친 점은 확신이
        높은 쪽이 갖는다 — 나란히 놓인 컵처럼 박스가 살짝 겹칠 때를 흉내낸다.

        ⚠️ **일부러 포함 비율을 낮게 잡는다(완전히 겹치지 않게).** 두 마스크가
        **완전히** 겹치는(포함 관계) 경우는 2026-09-21 신설된
        `suppress_cross_class_duplicates()`가 `split_by_boxes()` 이전에 먼저
        하나로 줄인다(class 이름과 무관하게, 점 개수 기준) — 그건
        `TestCrossClassDuplicate`가 따로 검증한다. 이 시험은 그 앞 단계를 통과하고
        **남은** 두 detection 사이에서 `split_by_boxes()`의 확신 기준 점 배정이
        맞는지만 본다."""
        det_low = _cup_detection(280, 190, 340, 290, conf=0.4, name="cup")   # 왼쪽 위주
        det_high = _cup_detection(310, 190, 360, 290, conf=0.9, name="cup")  # 오른쪽 위주
        pts, pix = _points_on_rect(280, 190, 360, 290, z=0.25)

        objs, rest = split_by_boxes(pts, pix, [det_low, det_high], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 2, "부분 겹침인데 하나로 줄었다 — 앞 단계가 잘못 합쳤다")
        sources = [o.source for o in objs]
        self.assertTrue(any("90%" in s for s in sources), "확신 높은 쪽이 안 보인다")
        self.assertTrue(any("40%" in s for s in sources), "확신 낮은 쪽이 통째로 사라졌다")

    def test_not_object_points_never_become_a_grasp_candidate(self):
        """사람(`person`) 같은 `NOT_OBJECT` 안의 점은 물체로도, geometry fallback
        후보로도 다시 나오면 안 된다."""
        det = _cup_detection(280, 190, 360, 290, conf=0.9, name="person")
        pts, pix = _points_on_rect(280, 190, 360, 290, z=0.25)

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(objs, [], "사람 영역에서 잡을 물체를 만들었다")
        self.assertEqual(len(rest), 0, "사람 영역의 점이 geometry fallback 후보로 남았다")


class TestGeometryFallbackToggle(unittest.TestCase):
    """`find_objects_hybrid(geometry_fallback=...)` — 2026-09-21 사용자 결정으로
    `yolo_assist.py` 의 기본값은 꺼짐(`False`)이지만, 함수 자체의 기본값은 켜짐
    (`True`, 기존 호출부·시험과 호환)이다. 여기서는 둘 다 명시적으로 확인한다.

    `segment_objects.find_objects()`(평면 제거 + RANSAC 군집화)는 다른 시험에서
    이미 검증돼 있다 — 여기서는 **그걸 다시 재현하지 않고**, "꺼져 있으면 아예 안
    부른다 / 켜져 있으면 결과를 합친다"는 `find_objects_hybrid()` 자체의 분기만
    가짜(`find_objects`)로 갈아끼워 확인한다.
    """

    def _scene_with_one_yolo_object(self):
        det = _cup_detection(280, 190, 360, 290, conf=0.9, name="cup")
        pts, pix = _points_on_rect(280, 190, 360, 290, z=0.25)
        return pts, pix, det

    def test_fallback_on_calls_geometry_and_merges_its_result(self):
        import unittest.mock as mock

        import segment_objects

        pts, pix, det = self._scene_with_one_yolo_object()
        fake_shape_obj = segment_objects.ObjectCloud(
            points=np.zeros((10, 3), np.float32), center=np.array([1.0, 1.0, 0.9]),
            size=np.array([0.05, 0.05, 0.05]), n_points=10)
        with mock.patch("segment_objects.find_objects",
                        return_value=([fake_shape_obj], np.zeros((0, 3)), "가짜 설명")) as m:
            objs, note, dets = find_objects_hybrid(
                pts, pix, np.zeros((*COLOR_SHAPE, 3), np.uint8), None,
                depth_shape=DEPTH_SHAPE, intr=_Intr, dets=[det], geometry_fallback=True)
        m.assert_called_once()
        self.assertEqual(len(objs), 2, "안전망을 켰는데 가짜 모양 물체가 안 섞였다")
        self.assertIn("모양으로 추가 1개", note)

    def test_fallback_off_never_calls_geometry(self):
        import unittest.mock as mock

        import segment_objects

        pts, pix, det = self._scene_with_one_yolo_object()
        with mock.patch("segment_objects.find_objects") as m:
            objs, note, dets = find_objects_hybrid(
                pts, pix, np.zeros((*COLOR_SHAPE, 3), np.uint8), None,
                depth_shape=DEPTH_SHAPE, intr=_Intr, dets=[det], geometry_fallback=False)
        m.assert_not_called()
        self.assertEqual(len(objs), 1, "안전망을 껐는데 물체 수가 달라졌다")
        self.assertEqual(objs[0].source, "YOLO:cup 90%")
        self.assertIn("안전망 꺼짐", note)

    def test_default_keeps_old_behavior_for_existing_callers(self):
        """함수 차원의 기본값은 `True` — 기존 호출부·시험을 깨면 안 된다."""
        import unittest.mock as mock

        import segment_objects

        pts, pix, det = self._scene_with_one_yolo_object()
        with mock.patch("segment_objects.find_objects") as m:
            m.return_value = ([], np.zeros((0, 3)), "가짜 설명")
            find_objects_hybrid(pts, pix, np.zeros((*COLOR_SHAPE, 3), np.uint8), None,
                                depth_shape=DEPTH_SHAPE, intr=_Intr, dets=[det])
        m.assert_called_once()


def _color_points_on_rect(u1, v1, u2, v2, z, step=2):
    """`suppress_cross_class_duplicates` 단위 시험 전용 — **색 사진 좌표 그대로**인
    3D 점과 픽셀 좌표를 만든다(`_points_on_rect` 는 깊이 사진 좌표로 절반 환산해서
    나오므로, 그 함수를 그대로 쓰면 안 된다 — 이 함수는 `Detection.contains()` 가
    기대하는 색 사진 좌표를 바로 준다)."""
    us = np.arange(u1 + 1, u2 - 1, step, dtype=float)
    vs = np.arange(v1 + 1, v2 - 1, step, dtype=float)
    uu, vv = np.meshgrid(us, vs)
    uu, vv = uu.ravel(), vv.ravel()
    pts = np.stack([(uu - _Intr.ppx) * z / _Intr.fx,
                    (vv - _Intr.ppy) * z / _Intr.fy,
                    np.full(uu.shape, z)], axis=1)
    return pts, uu, vv


class TestCrossClassDuplicate(unittest.TestCase):
    """`suppress_cross_class_duplicates()` — **같은 물체가 서로 다른 class 이름으로
    두 번 잡히는 것**을 하나로 줄인다 (2026-09-21, 실물 페트병이 `cup 73%` +
    `bottle 44%` 로 동시에 잡힌 것을 재현·수정).

    🛑 **D-9(YOLO+모양 안전망 사이의 중복)와 다른 문제다** — 여기는 YOLO 결과
    안에서, 서로 다른 class 이름표가 같은 물리적 물체를 가리키는 경우만 다룬다.
    """

    def test_larger_complete_mask_can_beat_higher_confidence_partial_mask(self):
        """실측 재현: `cup 73%`(병 윗부분만) vs `bottle 44%`(병 전체). **confidence가
        낮아도** 더 넓게(전체를) 덮은 쪽을 남겨야 한다."""
        cup = _cup_detection(300, 190, 360, 230, conf=0.73, name="cup")       # 윗부분만
        bottle = _cup_detection(280, 190, 360, 290, conf=0.44, name="bottle")  # 병 전체
        pts, px, py = _color_points_on_rect(280, 190, 360, 290, z=0.25)

        kept, debug_lines = suppress_cross_class_duplicates(
            [cup, bottle], pts, px, py, COLOR_SHAPE, debug=True)

        self.assertEqual(len(kept), 1, "중복이 하나로 안 줄었다")
        self.assertEqual(kept[0].name, "bottle",
                         "confidence 가 높다고 부분 영역(cup)을 남겼다 — 전체를 "
                         "덮은 쪽(bottle)을 남겨야 한다")
        self.assertTrue(debug_lines, "디버그 정보가 안 남았다")

    def test_cross_class_nested_duplicate_removed(self):
        """Case A — 작은 detection 이 큰 detection 안에 완전히 포함되고 같은 거리면
        **1개로 줄어야 한다.**"""
        small = _cup_detection(300, 190, 340, 220, conf=0.6, name="cup")
        big = _cup_detection(280, 190, 360, 290, conf=0.6, name="bottle")
        pts, px, py = _color_points_on_rect(280, 190, 360, 290, z=0.25)

        kept, _ = suppress_cross_class_duplicates([small, big], pts, px, py, COLOR_SHAPE)
        self.assertEqual(len(kept), 1)

    def test_two_real_objects_are_kept(self):
        """Case B — 컵 하나 + 병 하나가 화면에서도, 거리에서도 서로 안 겹치면 **2개
        유지되어야 한다.**"""
        cup = _cup_detection(40, 40, 120, 140, conf=0.9, name="cup")
        bottle = _cup_detection(400, 300, 480, 400, conf=0.8, name="bottle")
        cup_pts, cup_px, cup_py = _color_points_on_rect(40, 40, 120, 140, z=0.20)
        bot_pts, bot_px, bot_py = _color_points_on_rect(400, 300, 480, 400, z=0.30)
        pts = np.vstack([cup_pts, bot_pts])
        px = np.concatenate([cup_px, bot_px])
        py = np.concatenate([cup_py, bot_py])

        kept, _ = suppress_cross_class_duplicates([cup, bottle], pts, px, py, COLOR_SHAPE)
        self.assertEqual(len(kept), 2, "서로 다른 진짜 물체 두 개가 하나로 합쳐졌다")

    def test_overlap_but_depth_different_are_kept(self):
        """Case C — 2D 로는 많이 겹쳐도(앞쪽 작은 컵, 뒤쪽 병) **거리가 다르면
        2개 유지되어야 한다.**

        카메라 한 화소는 거리를 하나만 잴 수 있다 — 그래서 "앞쪽 작은 컵이 뒤쪽
        큰 병의 일부를 가린" 장면을 합성할 때, 가려진 안쪽 사각형은 **앞쪽 거리
        (0.20m)**, 그 바깥의 남은 큰 영역은 **뒤쪽 거리(0.45m)**로 나눠 채운다."""
        front_cup = _cup_detection(300, 210, 340, 250, conf=0.8, name="cup")       # 작고, 안쪽
        back_bottle = _cup_detection(280, 190, 360, 290, conf=0.7, name="bottle")  # 크고, 바깥까지

        outer_pts, outer_px, outer_py = _color_points_on_rect(280, 190, 360, 290, z=0.45)
        inner_pts, inner_px, inner_py = _color_points_on_rect(300, 210, 340, 250, z=0.20)
        # 바깥 점 중 안쪽 사각형과 겹치는 화소는 뺀다 — 같은 화소가 두 거리를 가질 수 없다.
        keep_outer = ~((outer_px >= 300) & (outer_px <= 340) & (outer_py >= 210) & (outer_py <= 250))
        pts = np.vstack([outer_pts[keep_outer], inner_pts])
        px = np.concatenate([outer_px[keep_outer], inner_px])
        py = np.concatenate([outer_py[keep_outer], inner_py])

        kept, _ = suppress_cross_class_duplicates(
            [front_cup, back_bottle], pts, px, py, COLOR_SHAPE)
        self.assertEqual(len(kept), 2,
                         "2D 겹침만 보고 거리가 다른(앞/뒤) 두 물체를 하나로 합쳤다")

    def test_no_depth_does_not_aggressively_remove(self):
        """Case E — 거리값이 모자라면(둘 중 하나라도) **확신 없이 지우지 않는다.**"""
        cup = _cup_detection(300, 190, 340, 220, conf=0.7, name="cup")
        bottle = _cup_detection(280, 190, 360, 290, conf=0.6, name="bottle")
        # 점을 CROSS_CLASS_MIN_DEPTH_POINTS 보다 적게만 준다 — 대표 거리를 못 낸다.
        few = max(1, CROSS_CLASS_MIN_DEPTH_POINTS - 2)
        all_pts, all_px, all_py = _color_points_on_rect(280, 190, 360, 290, z=0.25, step=1)
        idx = np.linspace(0, len(all_pts) - 1, few).astype(int)
        pts, px, py = all_pts[idx], all_px[idx], all_py[idx]

        kept, _ = suppress_cross_class_duplicates([cup, bottle], pts, px, py, COLOR_SHAPE)
        self.assertEqual(len(kept), 2,
                         "거리값이 모자란데도 겹침만 보고 하나를 지웠다")

    def test_same_class_nested_duplicate_is_also_removed(self):
        """🛑 **2026-09-21 실물 재현으로 뒤집힌 가정.** 처음엔 "같은 class 끼리는
        YOLO 자체 NMS(agnostic_nms 포함)가 정리한다"고 보고 건드리지 않았다.
        그런데 사용자가 실물에서 `cup 86%, cup 63%, cup 38%` 가 **한 병 위에
        동시에 3번** 잡히는 것을 재현했다 — 작은 detection 이 큰 detection 안에
        포함되면 IoU 가 낮게 나와 **class 가 같아도** NMS 를 통과한다. 그래서
        class 이름은 더 이상 안 보고, 포함 관계로만 판단한다."""
        small = _cup_detection(300, 190, 340, 220, conf=0.86, name="cup")   # 뚜껑만
        big = _cup_detection(280, 190, 360, 290, conf=0.38, name="cup")     # 병 전체
        pts, px, py = _color_points_on_rect(280, 190, 360, 290, z=0.25)

        kept, debug_lines = suppress_cross_class_duplicates(
            [small, big], pts, px, py, COLOR_SHAPE, debug=True)
        self.assertEqual(len(kept), 1, "같은 class 인데도 포함 관계인 중복이 안 줄었다")
        self.assertTrue(debug_lines)

    def test_same_class_disjoint_real_objects_are_kept(self):
        """Case D 의 진짜 취지 — **나란히 놓인 서로 다른 진짜 물체(같은 class)**는
        겹치는 부분이 적어 포함 비율이 낮으므로 계속 분리 유지돼야 한다."""
        cup_a = _cup_detection(40, 40, 120, 140, conf=0.9, name="cup")
        cup_b = _cup_detection(400, 300, 480, 400, conf=0.8, name="cup")
        a_pts, a_px, a_py = _color_points_on_rect(40, 40, 120, 140, z=0.20)
        b_pts, b_px, b_py = _color_points_on_rect(400, 300, 480, 400, z=0.30)
        pts = np.vstack([a_pts, b_pts])
        px = np.concatenate([a_px, b_px])
        py = np.concatenate([a_py, b_py])

        kept, debug_lines = suppress_cross_class_duplicates(
            [cup_a, cup_b], pts, px, py, COLOR_SHAPE, debug=True)
        self.assertEqual(len(kept), 2, "나란히 놓인 서로 다른 같은-class 물체를 합쳤다")
        self.assertEqual(debug_lines, [])


class TestOutOfRangeNoise(unittest.TestCase):
    """D405 가 못 믿는 거리(너무 가깝거나 먼)의 잡음이 진짜 물체를 밀어내면 안 된다.

    2026-09-21 코드 리뷰로 발견: `split_by_boxes()`가 `near`/`far` 검사를 전혀 안 해서,
    렌즈 코앞 반사 같은 잡음이 YOLO 박스 안에 섞이면 `_merge_pieces()`가 "가장 가까운
    조각"을 고르는 로직 때문에 그 잡음을 물체로 내고 진짜 물체는 사라졌다.
    """

    def test_near_camera_noise_does_not_replace_the_real_object(self):
        det = _cup_detection(280, 190, 360, 290)
        real, real_pix = _points_on_rect(280, 190, 360, 290, z=0.25)
        # D405_NEAR_M(기본 0.07m)보다 훨씬 가까운 잡음 — 렌즈 반사 등으로 흔히 생긴다.
        noise_z = cfg.D405_NEAR_M / 2.0
        noise, noise_pix = _points_on_rect(280, 190, 360, 290, z=noise_z)

        pts = np.vstack([real, noise])
        pix = (np.concatenate([real_pix[0], noise_pix[0]]),
              np.concatenate([real_pix[1], noise_pix[1]]))

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1, "잡음과 실제 물체가 하나로 합쳐지거나 사라졌다")
        self.assertAlmostEqual(objs[0].distance_m, 0.25, delta=0.01,
                               msg="믿을 수 없는 거리의 잡음이 실제 물체 대신 뽑혔다")

    def test_far_background_noise_is_dropped_too(self):
        det = _cup_detection(280, 190, 360, 290)
        real, real_pix = _points_on_rect(280, 190, 360, 290, z=0.25)
        # D405_FAR_M(기본 0.50m)보다 훨씬 먼 점 — 잘 안 잡히는 먼 배경.
        far_z = cfg.D405_FAR_M * 2.0
        far, far_pix = _points_on_rect(280, 190, 360, 290, z=far_z)

        pts = np.vstack([real, far])
        pix = (np.concatenate([real_pix[0], far_pix[0]]),
              np.concatenate([real_pix[1], far_pix[1]]))

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        self.assertAlmostEqual(objs[0].distance_m, 0.25, delta=0.01)


class TestDepthStack(unittest.TestCase):
    """여러 장을 합치면 값이 나온 화소가 늘어난다 — **지어내는 것이 아니다.**"""

    def test_union_of_valid_pixels(self):
        a = np.zeros((4, 4), dtype=np.float32)
        b = np.zeros((4, 4), dtype=np.float32)
        c = np.zeros((4, 4), dtype=np.float32)
        a[0, 0] = 0.20
        b[1, 1] = 0.30
        c[2, 2] = 0.40
        merged, stats = depth_stack.stack([a, b, c])

        self.assertEqual(int((merged > 0).sum()), 3)
        self.assertAlmostEqual(float(merged[0, 0]), 0.20, places=5)
        self.assertAlmostEqual(float(merged[2, 2]), 0.40, places=5)
        self.assertEqual(stats["frames"], 3)
        self.assertGreater(stats["after_valid"], stats["single_valid"])

    def test_median_of_what_was_seen(self):
        """같은 화소에 값이 여러 번 나오면 **중앙값**을 쓴다 — 튀는 값에 안 흔들린다."""
        frames = []
        for z in (0.20, 0.21, 0.90):          # 마지막은 튄 값
            f = np.zeros((2, 2), dtype=np.float32)
            f[0, 0] = z
            frames.append(f)
        merged, _ = depth_stack.stack(frames)
        self.assertAlmostEqual(float(merged[0, 0]), 0.21, places=5)

    def test_min_hits_drops_one_off_noise(self):
        """`min_hits` 를 올리면 **한 번만 반짝한 값**을 버린다."""
        a = np.zeros((2, 2), dtype=np.float32)
        b = np.zeros((2, 2), dtype=np.float32)
        a[0, 0] = 0.20
        b[0, 0] = 0.20
        a[1, 1] = 0.50                        # 한 장에서만 나온 값
        merged, _ = depth_stack.stack([a, b], min_hits=2)
        self.assertAlmostEqual(float(merged[0, 0]), 0.20, places=5)
        self.assertEqual(float(merged[1, 1]), 0.0)



class TestScreenText(unittest.TestCase):
    """화면 글자 — **잘리지 않고, 번호가 그림 안에 들어가야** 한다."""

    def setUp(self):
        import view_d405
        self.v = view_d405

    def test_long_line_is_folded_not_cut(self):
        font = self.v._font()
        long_line = ("YOLO: cup 89%, cup 87%, cup 86%, keyboard 72%, bottle 57%, "
                     "pen 55% / 모양으로 추가 2개 (평평한 면 제거 — 붙은 점 44%)")
        folded = self.v._wrap([long_line], font, 624)
        self.assertGreater(len(folded), 1, "긴 줄을 안 접었다 — 화면 밖으로 잘린다")
        for line in folded:
            self.assertLessEqual(self.v._text_width(font, line), 624)
        # 글자를 잃지 않았는지 — 빈칸만 빼고 다 남아 있어야 한다
        self.assertEqual("".join(folded).replace(" ", ""),
                         long_line.replace(" ", ""))

    def test_label_stays_inside_the_picture(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        out = self.v.put_labels(img, [(-50, -50, "3", (255, 255, 255)),
                                      (700, 700, "104 추정", (0, 255, 255))])
        self.assertEqual(out.shape, img.shape)
        self.assertGreater(int((out > 0).sum()), 0, "화면 밖으로 나가 아무것도 안 그려졌다")

    def test_no_labels_is_harmless(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        self.assertIs(self.v.put_labels(img, []), img)


class TestWholeScreenRuns(unittest.TestCase):
    """**카메라 없이** 화면 그리기까지 통째로 돌려 본다.

    그리기 코드는 실물 카메라가 있어야만 도는 자리라 시험이 안 닿았다. 가짜 카메라를
    끼워 `main()` 을 그대로 돌리면 오타·좌표 실수가 여기서 걸린다(원칙 2 — 카메라가
    없는 다른 머신에서도 확인할 수 있어야 한다).
    """

    def test_save_writes_a_picture(self):
        import shutil
        import tempfile

        import cv2  # noqa: F401  (없으면 이 시험은 건너뛴다)
        import d405_stream
        import yolo_assist

        class Intr:
            fx = fy = 320.0
            ppx, ppy = 160.0, 120.0

        def scene():
            d = np.zeros((240, 320), np.float32)
            yy, _ = np.mgrid[0:240, 0:320]
            d[:] = 0.30 + (yy - 120) * 0.0004        # 비스듬한 책상
            d[90:150, 60:100] = 0.20                 # 물체 1
            d[80:160, 170:210] = 0.23                # 물체 2
            d[30:60, 250:300] = 0.0                  # 값이 없는 구멍
            return d, np.full((480, 640, 3), 90, np.uint8)

        class Stream:
            def frames(self, count=1, warmup=0):
                return [tuple(x.copy() for x in scene()) for _ in range(count)], Intr

            def close(self):
                pass

        tmp = Path(tempfile.mkdtemp())
        keep = (d405_stream.open_depth, yolo_assist.RESULTS_DIR, sys.argv)
        try:
            d405_stream.open_depth = lambda *a, **k: Stream()
            yolo_assist.RESULTS_DIR = tmp
            sys.argv = ["yolo_assist.py", "--save", "--frames", "3",
                        "--weights", "no_such_model.pt"]
            self.assertEqual(yolo_assist.main(), 0)

            shots = list(tmp.glob("yolo_*.png"))
            self.assertEqual(len(shots), 1, "사진을 안 남겼다")
            img = cv2.imread(str(shots[0]))
            self.assertEqual(img.shape, (480, 1280, 3), "화면 크기가 달라졌다")
        finally:
            d405_stream.open_depth, yolo_assist.RESULTS_DIR, sys.argv = keep
            shutil.rmtree(tmp, ignore_errors=True)


class TestHoleyObject(unittest.TestCase):
    """거리값이 **숭숭 뚫린** 물체 — 조각 하나만 쓰면 크기가 반토막 난다.

    2026-09-18 실측: 뒤쪽에 반쯤 가린 7 cm 짜리 종이컵이 **3.2 cm** 로 나왔다.
    """

    def _cup_with_gaps(self, gaps):
        """테두리는 280~360 인데 거리값은 `gaps` 구간에만 있는 컵."""
        det = _cup_detection(280, 190, 360, 290)
        chunks = [_points_on_rect(a, 190, b, 290, z=0.25, step=1) for a, b in gaps]
        pts = np.vstack([c[0] for c in chunks])
        pix = (np.concatenate([c[1][0] for c in chunks]),
               np.concatenate([c[1][1] for c in chunks]))
        return det, pts, pix

    def test_pieces_of_one_object_are_put_back_together(self):
        # 컵의 왼쪽 끝과 오른쪽 끝에만 값이 있다 — 가운데는 뚫렸다
        det, pts, pix = self._cup_with_gaps([(281, 300), (340, 359)])

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        # 조각 하나만 쓰면 1.5 cm 안팎, 합치면 참값(3.1 cm)에 가까워야 한다
        self.assertGreater(objs[0].size[0], 0.025,
                           "조각 하나만 써서 크기가 반토막 났다")

    def test_a_sliver_falls_back_to_the_outline(self):
        # 테두리의 왼쪽 1/4 에만 값이 있다 — 이걸로 크기를 재면 안 된다
        det, pts, pix = self._cup_with_gaps([(281, 300)])

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        o = objs[0]
        self.assertTrue(o.estimated, "점이 일부만 덮었는데 그 크기를 그대로 믿었다")
        self.assertAlmostEqual(o.size[0], 0.0313, delta=0.004)   # 테두리에서 나온 참값

    def test_full_coverage_keeps_the_measured_size(self):
        """제대로 덮였으면 **점으로 잰 크기를 쓴다** — 함부로 추정으로 넘기지 않는다."""
        det, pts, pix = self._cup_with_gaps([(281, 359)])

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        self.assertFalse(objs[0].estimated, "잘 덮였는데도 추정으로 넘겼다")

if __name__ == "__main__":
    unittest.main()
