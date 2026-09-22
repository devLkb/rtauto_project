# -*- coding: utf-8 -*-
"""`d405_stream.reset_temporal_history()` 검증 — **카메라 없이도** 필터 객체만으로 돈다.

무엇을 확인하나
---------------
시간 다듬기(temporal filter)는 pyrealsense2 2.58.4 실측으로 확인한 대로 기본
persistency mode 가 **3 = "Valid in 2/last 4"** 다(0=Disabled 가 아니다) — 즉 과거
프레임 값을 얼마간 들고 있다가 지금 프레임이 비어도 그 값을 대신 내놓을 수 있다.
eye-in-hand 로 팔이 움직이면 이 과거 값이 새 관측 위치에 섞여 나올 수 있으므로,
`reset_temporal_history()` 로 **필터 내부 상태를 통째로 새 것으로 바꿔치기** 해야 한다
(pyrealsense2 필터 객체에는 "내부 상태만 지우는" API 가 따로 없다 — 새 객체로
바꾸는 것이 유일한 방법. `d405_stream.py` 머리말 참고).

이 시험은 실제 카메라가 없어도, **실제 `pyrealsense2` 모듈**(이 컴퓨터에 설치돼
있다면)로 필터 객체를 만들어 `reset_temporal_history()` 가 새 객체로 바꿔치기하는지만
확인한다 — 카메라를 열지 않으므로 하드웨어가 없어도 스킵 없이 돈다.

돌리는 법 (터미널 1, PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python -m unittest vision.d405.tests.test_d405_stream -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyrealsense2 as rs
    _HAVE_RS = True
except ImportError:
    _HAVE_RS = False

import d405_stream as ds  # noqa: E402


@unittest.skipUnless(_HAVE_RS, "pyrealsense2 가 설치돼 있지 않다")
class TestResetTemporalHistory(unittest.TestCase):
    def test_reset_swaps_in_a_fresh_temporal_filter_object(self):
        """새 객체로 바뀌어야 한다 — pyrealsense2 필터에는 내부 상태만 지우는 API가 없다."""
        filt = ds.DepthFilters(rs)
        before = filt.temporal
        filt.reset_temporal_history()
        after = filt.temporal
        self.assertIsNot(before, after,
                         "reset 후에도 같은 객체다 — 과거 프레임을 여전히 들고 있을 수 있다")
        self.assertIsInstance(after, type(before))

    def test_reset_does_not_touch_other_filters(self):
        """시간 다듬기만 바뀌어야 한다 — 줄이기·공간 다듬기까지 새로 만들 이유가 없다."""
        filt = ds.DepthFilters(rs)
        dec_before, spatial_before = filt.dec, filt.spatial
        filt.reset_temporal_history()
        self.assertIs(filt.dec, dec_before)
        self.assertIs(filt.spatial, spatial_before)

    def test_depthstream_delegates_when_filters_present(self):
        """`DepthStream.reset_temporal_history()` 가 실제로 필터를 바꿔치기하는지."""
        filt = ds.DepthFilters(rs)
        stream = ds.DepthStream.__new__(ds.DepthStream)   # 카메라 없이 최소 구성으로
        stream.filters = filt
        before = filt.temporal
        stream.reset_temporal_history()
        self.assertIsNot(filt.temporal, before)

    def test_depthstream_is_a_noop_without_filters(self):
        """다듬기를 안 쓰는 스트림(`filters=None`)에서는 아무 일도 안 하고 넘어간다."""
        stream = ds.DepthStream.__new__(ds.DepthStream)
        stream.filters = None
        stream.reset_temporal_history()   # 예외가 나면 안 된다


if __name__ == "__main__":
    unittest.main()
