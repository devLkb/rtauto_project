# -*- coding: utf-8 -*-
"""카메라 선택 창(camera_picker.py) 검증 — 창을 띄우지 않는 부분만 본다.

창 자체는 사람이 눌러야 하므로 자동 검증 대상이 아니다. 대신 **창 없이도 맞아야 하는 것**을
확인한다: 목록에 뭐라고 쓰는지, 한 대뿐일 때 안 묻는지, 창을 못 띄울 때 터미널로 물어보는지.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import camera_picker


CAMS = [
    {"index": 0, "width": 640, "height": 480, "measured_fps": 30.0, "preview": None},
    {"index": 1, "width": 1920, "height": 1080, "measured_fps": 29.8, "preview": None},
]


class CameraPickerTest(unittest.TestCase):
    def test_label_shows_number_size_and_speed(self):
        text = camera_picker.describe(CAMS[1], recommended_index=1)
        self.assertIn("1번", text)
        self.assertIn("1920x1080", text)
        self.assertIn("30장", text)          # 초당 장수는 반올림해 보여 준다
        self.assertIn("추천", text)

    def test_only_recommended_row_is_marked(self):
        self.assertNotIn("추천", camera_picker.describe(CAMS[0], recommended_index=1))

    def test_single_camera_is_not_asked_about(self):
        """고를 게 하나뿐이면 창을 띄우지 않는다 — 쓸데없이 클릭하게 만들지 않는다."""
        opened = []
        real = camera_picker._choose_with_window
        camera_picker._choose_with_window = lambda *a, **k: opened.append(1)
        try:
            self.assertEqual(camera_picker.choose([CAMS[0]]), 0)
        finally:
            camera_picker._choose_with_window = real
        self.assertEqual(opened, [], "카메라가 한 대인데 창을 띄웠다")

    def test_no_camera_returns_none(self):
        self.assertIsNone(camera_picker.choose([]))

    def test_falls_back_to_terminal_when_window_fails(self):
        """화면 없는 환경(서버 등)에서 창이 안 뜨면 터미널로 묻는다."""
        real_window = camera_picker._choose_with_window
        real_input = camera_picker._choose_in_terminal
        camera_picker._choose_with_window = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("화면 없음"))
        camera_picker._choose_in_terminal = lambda cams, rec: 1
        try:
            self.assertEqual(camera_picker.choose(CAMS, recommended_index=1), 1)
        finally:
            camera_picker._choose_with_window = real_window
            camera_picker._choose_in_terminal = real_input


if __name__ == "__main__":
    unittest.main()
