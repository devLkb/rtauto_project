# -*- coding: utf-8 -*-
"""camera_caps.py 검증 — 실물 웹캠 없이 가짜 카메라로 돌린다.

여기서 확인하려는 것은 "웹캠이 낼 수 있는 최대 화면 크기를 정말로 찾아내는가"와
"저화질 웹캠에서 무리한 요청을 해도 멀쩡히 동작하는가" 두 가지다. 둘 다 실물 카메라
없이 지금 확인할 수 있어야 의미가 있다 — 카메라가 안 꽂힌 PC에서도 이 테스트는 돈다.

가짜 카메라(FakeCamera)는 실제 웹캠 드라이버의 두 가지 행동을 흉내 낸다:
  ① snap  — 지원하지 않는 크기를 요청받으면 **가장 가까운(넘지 않는) 지원 크기**로 깎는다
             (흔한 동작. 아주 큰 값을 요청하면 곧 최대치가 나온다)
  ② reject — 지원하지 않는 크기 요청을 **무시하고 원래 크기를 유지**한다
             (이 경우 후보 목록을 큰 것부터 하나씩 시도해야 최대치를 찾을 수 있다)
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import camera_caps as cc

# OpenCV 속성 번호(cv2 없이 돌리기 위해 여기서만 쓰는 값). 실제 코드는 cv2 상수를 쓴다.
PROP_WIDTH, PROP_HEIGHT, PROP_FPS = 3, 4, 5


class FakeCamera:
    """지원 크기 목록을 가진 가짜 웹캠. mode="snap" 또는 "reject"."""

    def __init__(self, supported, mode="snap", start=None, fps=30.0):
        self.supported = sorted(supported, key=lambda s: s[0] * s[1])
        self.mode = mode
        self.size = start or self.supported[0]
        self.fps = fps
        self.set_calls = []
        self.released = False
        self.broken = False

    # --- cv2.VideoCapture 흉내 ---
    def isOpened(self):
        return True

    def set(self, prop, value):
        self.set_calls.append((prop, value))
        if prop == PROP_WIDTH:
            self._pending_width = int(value)
            return True
        if prop == PROP_HEIGHT:
            self._apply(getattr(self, "_pending_width", self.size[0]), int(value))
            return True
        if prop == PROP_FPS:
            self.fps = float(value)
            return True
        return True

    def _apply(self, width, height):
        if (width, height) in self.supported:
            self.size = (width, height)
            if self.mode != "dead":
                self.broken = False       # 지원하는 크기를 주면 다시 살아난다
            return
        if self.mode == "snap":
            smaller = [s for s in self.supported if s[0] <= width and s[1] <= height]
            self.size = smaller[-1] if smaller else self.supported[0]
        elif self.mode in ("explode", "dead"):
            # 2026-09-16 실물 증상: 지원하지 않는 크기를 요청하면 스트림이 깨지고
            # 그 다음 read()가 False가 아니라 **예외**를 던진다.
            self.broken = True
        # mode == "reject": 아무것도 하지 않는다(원래 크기 유지)

    def get(self, prop):
        if prop == PROP_WIDTH:
            return float(self.size[0])
        if prop == PROP_HEIGHT:
            return float(self.size[1])
        if prop == PROP_FPS:
            return float(self.fps)
        return 0.0

    def read(self):
        if self.broken:
            raise RuntimeError("cv2.error 흉내 — 깨진 스트림에서 읽기")
        return True, np.zeros((self.size[1], self.size[0], 3), dtype="uint8")

    def release(self):
        self.released = True


class FakeCv2:
    """camera_caps가 쓰는 cv2 기능만 흉내 낸 대역."""
    CAP_PROP_FRAME_WIDTH = PROP_WIDTH
    CAP_PROP_FRAME_HEIGHT = PROP_HEIGHT
    CAP_PROP_FPS = PROP_FPS
    CAP_PROP_BUFFERSIZE = 38
    CAP_PROP_FOURCC = 6
    # 백엔드 상수 — open_camera가 backend_names()로 이 표를 읽는다.
    CAP_ANY, CAP_MSMF, CAP_DSHOW = 0, 1400, 700
    CAP_V4L2, CAP_AVFOUNDATION, CAP_GSTREAMER = 200, 1200, 1800

    @staticmethod
    def VideoWriter_fourcc(*chars):
        return float(sum(ord(c) << (8 * i) for i, c in enumerate(chars)))


def _quiet(*_args, **_kwargs):
    """테스트 출력이 지저분해지지 않게 로그를 버린다."""


class CameraCapsTest(unittest.TestCase):
    def setUp(self):
        # cv2를 가짜로 갈아끼운다 — OpenCV가 설치돼 있지 않은 PC에서도 이 테스트는 돈다.
        self._real_cv2 = cc._cv2
        cc._cv2 = lambda: FakeCv2
        self._tmp = tempfile.mkdtemp(prefix="camcaps_")
        self.cache = os.path.join(self._tmp, "cache.json")
        # 크기를 바꾼 뒤 기다리는 시간을 없애 테스트를 빠르게 유지한다(로직에는 영향 없음).
        self._real_sleep = cc._VERIFY_SLEEP
        cc._VERIFY_SLEEP = 0.0
        # 속도 측정은 진짜로 하면 후보마다 1.5초가 걸린다 — 가짜 카메라별 속도표로 대신한다.
        # (speeds에 없는 크기는 충분히 빠른 것으로 본다.)
        self._real_measure = cc.measure_fps
        self.speeds = {}
        cc.measure_fps = lambda cap, **kw: self.speeds.get(getattr(cap, "size", None), 30.0)

    def _write_cache(self, data):
        with io.open(self.cache, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def tearDown(self):
        cc._cv2 = self._real_cv2
        cc._VERIFY_SLEEP = self._real_sleep
        cc.measure_fps = self._real_measure

    # ---------------- 설정값 해석 ----------------
    def test_max_words_mean_maximum(self):
        for word in ("max", "MAX", "auto", " best ", ""):
            self.assertIsNone(cc.parse_size_spec(word), word)

    def test_number_is_kept(self):
        self.assertEqual(cc.parse_size_spec("1280"), 1280)
        self.assertEqual(cc.parse_size_spec(720), 720)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            cc.parse_size_spec("hd화질")

    # ---------------- 최대 크기 찾기 ----------------
    def test_finds_max_on_snapping_driver(self):
        cam = FakeCamera([(640, 480), (1280, 720), (1920, 1080)], mode="snap")
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                   cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))
        self.assertEqual(fmt.how, "probe")

    def test_finds_max_on_rejecting_driver(self):
        cam = FakeCamera([(640, 480), (1280, 720), (1920, 1080)], mode="reject")
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                   cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))

    def test_low_quality_camera_stays_at_its_own_maximum(self):
        """640x480만 되는 싸구려 웹캠에 최대치를 요구해도 깨지지 않고 640x480으로 열린다."""
        for mode in ("snap", "reject"):
            cam = FakeCamera([(640, 480)], mode=mode)
            _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                       cache_path=self.cache, log=_quiet)
            self.assertEqual((fmt.width, fmt.height), (640, 480), mode)

    def test_fixed_size_is_requested_as_is(self):
        cam = FakeCamera([(640, 480), (1280, 720), (1920, 1080)], mode="snap")
        _, fmt = cc.apply_best_format(cam, width="1280", height="720",
                                   cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1280, 720))
        self.assertEqual(fmt.how, "fixed")
        # 고정 크기로 열 때는 최대치 탐색을 하지 않는다 — 탐색 결과 파일도 만들지 않는다.
        self.assertFalse(os.path.exists(self.cache))

    # ---------------- 크기만 보지 않고 속도까지 본다 ----------------
    def test_big_but_too_slow_mode_is_rejected(self):
        """실물 증상 그대로: 2592x1944는 초당 1장이라 못 쓴다 → 1920x1080을 고른다."""
        cam = FakeCamera([(640, 480), (1920, 1080), (2592, 1944)], mode="snap")
        self.speeds = {(2592, 1944): 1.0, (1920, 1080): 30.0, (640, 480): 30.0}
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                      cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))
        self.assertEqual(fmt.measured_fps, 30.0)

    def test_all_modes_slow_falls_back_to_the_largest(self):
        """전부 기준 미달이면 그중 가장 큰 것으로 열되, 경고를 남긴다."""
        cam = FakeCamera([(640, 480), (1920, 1080)], mode="snap")
        self.speeds = {(1920, 1080): 5.0, (640, 480): 8.0}
        messages = []
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                      cache_path=self.cache, log=messages.append)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))
        self.assertTrue(any("경고" in m for m in messages), messages)

    def test_min_fps_can_be_raised(self):
        """30장을 요구하면 25장짜리 큰 화면 대신 30장짜리 작은 화면을 고른다."""
        cam = FakeCamera([(640, 480), (1920, 1080)], mode="snap")
        self.speeds = {(1920, 1080): 25.0, (640, 480): 30.0}
        _, fmt = cc.apply_best_format(cam, width="max", height="max", min_fps=30.0,
                                      cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (640, 480))

    # ---------------- 드라이버가 망가지는 경우(2026-09-16 실물에서 겪음) ----------------
    def test_driver_that_breaks_is_revived_and_still_finds_max(self):
        """지원 안 하는 크기를 요청해 스트림이 깨져도, 되살려서 최대치를 찾아낸다."""
        cam = FakeCamera([(640, 480), (1280, 720)], mode="explode")
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                      cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1280, 720))

    def test_driver_that_stays_dead_is_reopened(self):
        """되돌려도 안 살아나면 카메라를 다시 연다 — 그래도 최대치를 찾아야 한다."""
        made = []

        def make():
            cam = FakeCamera([(640, 480), (1280, 720)], mode="dead")
            made.append(cam)
            return cam

        def reopen(old):
            old.release()       # 다시 여는 쪽이 옛 카메라를 닫는다(camera_caps의 약속)
            return make()

        _, fmt = cc.apply_best_format(make(), width="max", height="max",
                                      cache_path=self.cache, log=_quiet, reopen=reopen)
        self.assertEqual((fmt.width, fmt.height), (1280, 720))
        self.assertGreater(len(made), 1)          # 실제로 다시 열었다
        self.assertTrue(made[0].released)         # 옛 카메라는 닫혔다

    # ---------------- 찾은 값 저장/재사용 ----------------
    def test_second_run_reuses_saved_maximum(self):
        supported = [(640, 480), (1280, 720), (1920, 1080)]
        first = FakeCamera(supported, mode="reject")
        cc.apply_best_format(first, width="max", height="max",
                             cache_path=self.cache, log=_quiet)
        with io.open(self.cache, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(list(saved.values())[0]["width"], 1920)
        self.assertIn("measured_fps", list(saved.values())[0])

        second = FakeCamera(supported, mode="reject")
        _, fmt = cc.apply_best_format(second, width="max", height="max",
                                   cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))
        self.assertEqual(fmt.how, "cache")
        # 저장값을 썼다면 후보 목록을 훑지 않는다 — 크기 요청은 가로·세로 한 번씩뿐이다.
        self.assertEqual(len([c for c in second.set_calls if c[0] == PROP_WIDTH]), 1)

    def test_saved_value_that_no_longer_fits_is_reprobed(self):
        """카메라를 다른 것으로 바꿔 꽂으면 저장값이 안 맞는다 → 스스로 다시 찾아야 한다."""
        self._write_cache({cc._cache_key(0, "auto", ""): {"width": 1920, "height": 1080}})
        cam = FakeCamera([(640, 480)], mode="reject")
        _, fmt = cc.apply_best_format(cam, width="max", height="max",
                                   cache_path=self.cache, log=_quiet)
        self.assertEqual((fmt.width, fmt.height), (640, 480))
        self.assertEqual(fmt.how, "probe")

    def test_already_correct_size_skips_the_slow_set_call(self):
        """이미 최대 크기로 열려 있으면 cap.set()을 부르지 않는다(웹캠에 따라 1회 3.5초)."""
        cam = FakeCamera([(640, 480), (1920, 1080)], mode="snap", start=(1920, 1080))
        self._write_cache({cc._cache_key(0, "auto", ""): {"width": 1920, "height": 1080}})
        cc.apply_best_format(cam, width="max", height="max", fps=30,
                             cache_path=self.cache, log=_quiet)
        self.assertEqual([c for c in cam.set_calls if c[0] in (PROP_WIDTH, PROP_HEIGHT)], [])

    # ---------------- 카메라가 여러 대일 때 고르기 ----------------
    def _multi_factory(self, table):
        """번호별로 다른 가짜 카메라를 주는 공장. 표에 없는 번호는 '안 열림'."""
        made = {}

        class Missing:
            def isOpened(self):
                return False

            def release(self):
                pass

        def factory(index, backend=None):
            if index not in table:
                return Missing()
            cam = FakeCamera(table[index], mode="snap")
            made.setdefault(index, []).append(cam)
            return cam

        return factory, made

    def test_index_spec_parsing(self):
        self.assertIsNone(cc.parse_index_spec("auto"))
        self.assertIsNone(cc.parse_index_spec(" AUTO "))
        self.assertEqual(cc.parse_index_spec("1"), 1)
        self.assertEqual(cc.parse_index_spec(0), 0)
        with self.assertRaises(ValueError):
            cc.parse_index_spec("첫번째")
        with self.assertRaises(ValueError):
            cc.parse_index_spec("-1")

    def test_list_cameras_skips_empty_slots(self):
        """0번과 2번만 꽂혀 있어도 둘 다 찾아낸다(중간 번호가 비어 있어도 멈추지 않는다)."""
        factory, _ = self._multi_factory({0: [(640, 480)], 2: [(1920, 1080)]})
        cams = cc.list_cameras(cache_path=self.cache, log=_quiet, capture_factory=factory)
        self.assertEqual([c["index"] for c in cams], [0, 2])

    def test_auto_picks_the_better_camera(self):
        """노트북 상황: 0번=내장(640x480), 1번=외장 웹캠(1920x1080) → 1번을 고른다."""
        factory, _ = self._multi_factory({0: [(640, 480)], 1: [(640, 480), (1920, 1080)]})
        picked = cc.pick_best_index(cache_path=self.cache, log=_quiet,
                                    capture_factory=factory)
        self.assertEqual(picked, 1)

    def test_auto_prefers_speed_over_size(self):
        """더 커도 너무 느리면 안 고른다 — 1번이 크지만 초당 2장이면 0번을 고른다."""
        factory, _ = self._multi_factory({0: [(1280, 720)], 1: [(640, 480), (2592, 1944)]})
        self.speeds = {(2592, 1944): 2.0}
        picked = cc.pick_best_index(cache_path=self.cache, log=_quiet,
                                    capture_factory=factory)
        self.assertEqual(picked, 0)

    def test_auto_returns_none_when_no_camera(self):
        factory, _ = self._multi_factory({})
        self.assertIsNone(cc.pick_best_index(cache_path=self.cache, log=_quiet,
                                             capture_factory=factory))

    def test_open_camera_accepts_auto_and_reports_the_number(self):
        """open_camera에 "auto"를 주면 스스로 고르고, 고른 번호를 결과에 담아 돌려준다."""
        factory, _ = self._multi_factory({0: [(640, 480)], 1: [(640, 480), (1920, 1080)]})
        cap, fmt = cc.open_camera("auto", cache_path=self.cache, log=_quiet,
                                  capture_factory=factory)
        self.assertIsNotNone(cap)
        self.assertEqual(fmt.index, 1)
        self.assertEqual((fmt.width, fmt.height), (1920, 1080))

    # ---------------- 사람에게 물어서 고르기(ask) ----------------
    def test_ask_spec_is_recognised(self):
        for word in ("ask", "ASK", " pick ", "choose"):
            self.assertEqual(cc.parse_index_spec(word), cc.ASK, word)

    def test_ask_shows_the_list_and_uses_the_answer(self):
        """창 대신 가짜 응답을 끼워 넣어, 고른 번호가 그대로 쓰이는지 본다."""
        import camera_picker
        factory, _ = self._multi_factory({0: [(640, 480)], 1: [(640, 480), (1920, 1080)]})
        shown = {}

        def fake_choose(cams, recommended_index=None, **_kw):
            shown["cams"] = cams
            shown["recommended"] = recommended_index
            return 0                                   # 사람이 0번을 골랐다고 치자

        real = camera_picker.choose
        camera_picker.choose = fake_choose
        try:
            cap, fmt = cc.open_camera("ask", cache_path=self.cache, log=_quiet,
                                      capture_factory=factory)
        finally:
            camera_picker.choose = real
        self.assertEqual([c["index"] for c in shown["cams"]], [0, 1])
        self.assertEqual(shown["recommended"], 1)      # 추천은 더 좋은 1번
        self.assertEqual(fmt.index, 0)                 # 그래도 사람이 고른 0번으로 연다
        self.assertEqual((fmt.width, fmt.height), (640, 480))

    def test_ask_can_be_cancelled(self):
        """선택 창을 닫으면(취소) 카메라를 열지 않는다 — 아무 카메라나 켜지 않는다."""
        import camera_picker
        factory, _ = self._multi_factory({0: [(640, 480)], 1: [(1920, 1080)]})
        real = camera_picker.choose
        camera_picker.choose = lambda *a, **k: None
        try:
            cap, fmt = cc.open_camera("ask", cache_path=self.cache, log=_quiet,
                                      capture_factory=factory)
        finally:
            camera_picker.choose = real
        self.assertIsNone(cap)
        self.assertIsNone(fmt)

    def test_preview_photo_is_collected_when_asked(self):
        factory, _ = self._multi_factory({0: [(640, 480)]})
        cams = cc.list_cameras(cache_path=self.cache, log=_quiet, capture_factory=factory,
                               with_preview=True)
        self.assertIsNotNone(cams[0]["preview"])
        self.assertEqual(cams[0]["preview"].shape[:2], (480, 640))

    # ---------------- 미리보기 창 크기 ----------------
    def test_preview_keeps_aspect_ratio(self):
        self.assertEqual(cc.preview_size(640, 480, 1280), (640, 480))    # 원본보다 키우지 않는다
        self.assertEqual(cc.preview_size(1920, 1080, 1280), (1280, 720))
        self.assertEqual(cc.preview_size(3840, 2160, 1280), (1280, 720))
        self.assertEqual(cc.preview_size(1280, 960, 1280), (1280, 960))  # 4:3은 4:3 그대로

    def test_preview_survives_unknown_size(self):
        self.assertEqual(cc.preview_size(0, 0, 1280), (1280, 720))


if __name__ == "__main__":
    unittest.main()
