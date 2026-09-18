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
from yolo_assist import Detection, split_by_boxes      # noqa: E402


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

class TestNoDoubleCounting(unittest.TestCase):
    """**한 물건이 둘로 세어지면 안 된다** (2026-09-18 사용자 발견).

    확신 기준을 70 % 로 올려도 남았다 — 두 번째 덩어리가 YOLO 가 아니라 **모양** 쪽에서
    나왔기 때문이다. 그래서 남는 점 자체를 없애야 한다.
    """

    def test_leftovers_inside_the_outline_are_consumed(self):
        """테두리 안에서 **크기 계산에 안 쓴 점도** 같은 거리대면 소비해야 한다."""
        det = _cup_detection(280, 190, 360, 290)
        # 테두리의 왼쪽 1/4 에만 촘촘히 값이 있다 → 크기는 테두리로 추정하게 된다
        pts, pix = _points_on_rect(281, 190, 300, 290, z=0.25, step=1)

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        self.assertTrue(objs[0].estimated)
        self.assertEqual(len(rest), 0,
                         "테두리 안의 점이 남아 모양 쪽이 같은 물건을 또 만든다")

    def test_points_just_outside_the_outline_are_absorbed(self):
        """테두리 **바로 바깥**으로 삐져나온 점은 그 물체에 합친다."""
        det = _cup_detection(280, 190, 360, 290)
        inside, pix_in = _points_on_rect(281, 190, 359, 290, z=0.25, step=1)
        halo, pix_halo = _points_on_rect(362, 190, 368, 290, z=0.25, step=1)

        pts = np.vstack([inside, halo])
        pix = (np.concatenate([pix_in[0], pix_halo[0]]),
               np.concatenate([pix_in[1], pix_halo[1]]))

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1, "삐져나온 껍질이 따로 물체가 됐다")
        self.assertEqual(len(rest), 0)

    def test_a_separate_object_is_not_eaten(self):
        """**떨어져 있는 다른 물건은 안 먹는다** — 나란히 놓인 컵이 하나로 합쳐지면 안 된다."""
        det = _cup_detection(280, 190, 360, 290)
        inside, pix_in = _points_on_rect(281, 190, 359, 290, z=0.25, step=1)
        other, pix_other = _points_on_rect(460, 190, 540, 290, z=0.25, step=1)

        pts = np.vstack([inside, other])
        pix = (np.concatenate([pix_in[0], pix_other[0]]),
               np.concatenate([pix_in[1], pix_other[1]]))

        objs, rest = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                    depth_shape=DEPTH_SHAPE, intr=_Intr)

        self.assertEqual(len(objs), 1)
        self.assertGreaterEqual(len(rest), len(other) * 0.9,
                                "옆에 있는 다른 물건까지 먹어 치웠다")

class TestNoJunkRectangles(unittest.TestCase):
    """**말도 안 되는 크기는 물체로 내지 않는다** (2026-09-18 사용자 발견:
    *"의미없는 주변부까지 사각형까지 탐지해버린다"*).

    덩어리로 잰 물체에는 2~30 cm 라는 상식 검사가 처음부터 있었는데, 테두리로 추정하는
    쪽에는 빠져 있었다. 그래서 큰 테두리(헛 검출)가 그대로 큰 물체가 됐다.
    """

    def test_a_huge_outline_makes_no_object(self):
        # 화면을 거의 다 덮는 테두리 — 0.25 m 에서 40 cm 가 넘는다
        det = _cup_detection(20, 20, 620, 460, conf=0.4, name="tv remote")
        pts, pix = _points_on_rect(30, 30, 60, 60, z=0.25, step=3)   # 거리값은 구석에만

        objs, _ = split_by_boxes(pts, pix, [det], COLOR_SHAPE,
                                 depth_shape=DEPTH_SHAPE, intr=_Intr)

        for o in objs:
            self.assertFalse(o.estimated,
                             "손에 안 들어오는 크기를 추정으로 만들어 냈다")


class TestTrackNumbersAreStable(unittest.TestCase):
    """**번호가 물체를 따라다녀야** 한다 — 목록 순서가 바뀌어도.

    2026-09-18 사용자 발견: *"14번 17번 이런식으로 번갈아서 나온다"*. 목록은 점 개수
    순으로 정렬되는데 그 순서가 장면마다 뒤바뀌어 가까운 두 물체가 번호를 맞바꿨다.
    """

    def _obj(self, x):
        from segment_objects import ObjectCloud
        c = np.array([x, 0.0, 0.25])
        return ObjectCloud(points=np.array([c], dtype=np.float32), center=c,
                           size=np.array([0.05, 0.05, 0.05]), n_points=1)

    def test_order_does_not_swap_numbers(self):
        from segment_objects import Tracker

        tracker = Tracker()
        a, b = self._obj(0.00), self._obj(0.04)      # 4 cm 떨어진 두 물체
        tracker.update([a, b])
        first = (a.track_id, b.track_id)
        self.assertNotEqual(*first)

        # 다음 장면에서 **목록 순서가 뒤집혀 들어온다** (점 개수가 뒤바뀐 경우)
        a2, b2 = self._obj(0.002), self._obj(0.042)
        tracker.update([b2, a2])

        self.assertEqual(a2.track_id, first[0], "같은 물체인데 번호가 바뀌었다")
        self.assertEqual(b2.track_id, first[1], "같은 물체인데 번호가 바뀌었다")

if __name__ == "__main__":
    unittest.main()
