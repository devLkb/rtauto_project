# -*- coding: utf-8 -*-
"""D405 를 여는 **유일한 자리** — 다듬기와 되살리기를 한 군데 모은다 (원칙 1).

왜 따로 뺐나
------------
카메라를 여는 코드가 여러 파일에 흩어지면, 다듬기를 한쪽에만 켜는 실수가 난다. 그러면
"보기 창에서는 잘 보이는데 실제 쓰는 값은 나쁘다" 같은 일이 생긴다. 그래서 여는 일은
여기 한 군데서만 한다.

깊이 다듬기 — **왜 켜야 하고, 무엇은 켜면 안 되나**
----------------------------------------------------
날것 그대로 쓰면 **가까운 거리에서 값이 나오다 말다 한다.** 2026-09-18 실측:

===============  =========  ==================  =====================
거리              ① 날것     ② 안전한 다듬기      ③ ② + 구멍 메우기
===============  =========  ==================  =====================
0.10 ~ 0.15 m     73 %       **81 %**            100 %
0.15 ~ 0.20 m     53 %       **83 %**            100 %
0.20 ~ 0.25 m     50 %       **81 %**            100 %
0.25 ~ 0.30 m     86 %       **91 %**            100 %
===============  =========  ==================  =====================
(숫자는 "여러 장면에서 **늘** 값이 나온 화소의 비율")

**② 를 쓴다.** 줄이기·옆 화소 맞추기·앞뒤 장면 맞추기만 한다 — 전부 **실제로 본 값**에서
나온다. 흔들림도 같이 좋아진다(0.15~0.20 m 에서 0.76 → 0.42 mm).

🛑 **③ 구멍 메우기는 쓰지 않는다.** 100 % 로 보이지만 **없는 값을 지어낸다** —
0.05~0.10 m 구간의 화소가 500 개에서 14,987 개로 늘었고 그 흔들림이 7 mm 였다.
파지에서는 위험하다: 없는 면을 있다고 보고 손을 갖다 대게 된다.
그래서 `fill_holes=True` 는 **일부러 기본값이 아니고**, 켜면 경고를 찍는다.

⚠️ 줄이기(decimation) 때문에 **사진 크기가 절반**이 된다(640x480 → 320x240).
   우리는 점 개수가 중요하지 화소 수가 중요하지 않으므로 손해가 아니다.

카메라가 멈췄을 때
------------------
파란 화면·강제 종료 뒤에는 **장치는 보이는데 영상이 안 들어오는** 상태로 남는다
(2026-09-18 실측). `open_depth()` 가 그것을 알아서 감지해 **재설정하고 다시 연다.**
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402,F401

#: 맞춰 볼 해상도 후보. 앞에서부터 되는 것을 쓴다.
PREFERRED = ((848, 480, 30), (640, 480, 30), (1280, 720, 30))

#: 첫 장면을 기다리는 시간(ms). 이걸 넘기면 카메라가 멈춘 것으로 보고 재설정한다.
FIRST_FRAME_TIMEOUT_MS = 4000

#: 자동 밝기와 시간 다듬기가 자리 잡을 때까지 버리는 장면 수.
WARMUP_FRAMES = 12


def reset_device(rs, wait_s=30.0):
    """카메라를 재설정하고 다시 붙을 때까지 기다린다."""
    devs = list(rs.context().query_devices())
    if not devs:
        return False
    devs[0].hardware_reset()
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        time.sleep(1.0)
        if list(rs.context().query_devices()):
            time.sleep(2.0)          # 붙자마자 열면 또 멈춘다 — 조금 더 기다린다
            return True
    return False


class DepthFilters:
    """깊이 다듬기 묶음. **지어내지 않는 것들만** 기본으로 켠다.

    시간 다듬기(temporal filter)의 과거 프레임 문제 — **왜 reset 이 필요한가**
    -----------------------------------------------------------------------
    `rs.temporal_filter()` 는 만들 때 "Holes Fill"(persistency mode) 옵션의
    **기본값이 3 = "Valid in 2/last 4"** 다(2026-09-21, 이 컴퓨터에 설치된
    pyrealsense2 2.58.4 로 직접 확인 — 추측 아님). 즉 **꺼져 있는(0=Disabled) 것이
    아니라 항상 얼마간의 과거를 들고 있다**: 어떤 화소가 최근 4개 프레임 중 2개
    이상에서 값이 있었다면, 지금 프레임에서 그 화소가 안 보여도 필터가 **과거 값을
    이어서 내놓는다.** (참고로 8=Always on 은 무한 지속이라 더 심하고, 0=Disabled 는
    지속을 아예 안 쓴다 — 우리는 기본값 3을 그대로 쓴다. 정지 상태에서는 이 지속이
    깜빡이는 화소를 메워 주는 **장점**이기도 하다.)

    eye-in-hand 에서는 이게 문제가 된다: 팔이 위치 A 에서 B 로 이동한 직후에도
    필터 내부에 위치 A 의 값이 몇 프레임 남아 있을 수 있다 — **`reset_temporal_history()`
    없이 정지 직후 바로 찍으면 위치 A 의 흔적이 위치 B 관측에 섞여 나올 수 있다.**

    pyrealsense2 필터 객체에는 "내부 상태만 지우는" API 가 없다(`temporal_filter`
    가 가진 메서드는 `get_option`/`set_option`/`process` 뿐 — 2026-09-21 확인).
    그래서 유일한 방법은 **새 필터 객체로 바꿔치기**하는 것이다 — 새 객체는 과거
    프레임을 하나도 안 가지고 있으므로 그 자체로 초기화 효과를 낸다.
    """

    def __init__(self, rs, decimate=2, fill_holes=False):
        self.rs = rs
        self.decimate = decimate
        self.dec = rs.decimation_filter(decimate) if decimate > 1 else None
        self.to_disp = rs.disparity_transform(True)    # 다듬기는 시차 쪽이 낫다
        self.spatial = rs.spatial_filter()
        self.temporal = rs.temporal_filter()
        self.to_depth = rs.disparity_transform(False)
        self.hole = None
        if fill_holes:
            print("⚠️ 구멍 메우기를 켰다 — **없는 값을 지어낸다.** 파지 판단에 쓰지 마라.")
            self.hole = rs.hole_filling_filter(1)

    def reset_temporal_history(self):
        """**시간 다듬기가 들고 있던 과거 프레임을 버린다.**

        팔이 움직여 관측 위치가 바뀔 때 부른다 — 그러지 않으면 이전 위치의 깊이가
        새 위치의 첫 몇 프레임에 섞여 나올 수 있다(위 클래스 설명 참고).

        쓰는 법 (eye-in-hand)::

            팔 이동 시작
            → 팔 정지
            → stream.reset_temporal_history()   # 과거 위치의 흔적을 버린다
            → stream.frames(count=1, warmup=WARMUP_FRAMES)  # 새 자리에서 다시 데운다
        """
        self.temporal = self.rs.temporal_filter()

    def process(self, depth_frame):
        f = depth_frame
        if self.dec is not None:
            f = self.dec.process(f)
        f = self.to_disp.process(f)
        f = self.spatial.process(f)
        f = self.temporal.process(f)
        if self.hole is not None:
            f = self.hole.process(f)
        return self.to_depth.process(f)


class DepthStream:
    """열린 카메라 하나. `with` 로 쓰면 알아서 닫는다."""

    def __init__(self, rs, pipe, profile, mode, filters, color):
        self.rs = rs
        self.pipe = pipe
        self.profile = profile
        self.mode = mode
        self.filters = filters
        self.has_color = color
        self.scale = profile.get_device().first_depth_sensor().get_depth_scale()
        self._align = rs.align(rs.stream.color) if color else None

    def reset_temporal_history(self):
        """**팔이 움직여 관측 위치가 바뀌었을 때** 부른다 — 이전 위치의 시간 다듬기
        흔적을 버린다. 필터를 안 쓰면(`filters=None`) 아무 일도 안 한다.

        자세한 이유는 `DepthFilters.reset_temporal_history()` 참고.
        """
        if self.filters is not None:
            self.filters.reset_temporal_history()

    @property
    def intrinsics(self):
        """다듬기를 거친 **결과 크기 기준**의 초점거리·중심.

        ⚠️ 줄이기를 켜면 사진이 작아져 초점거리도 같이 줄어든다. 원본 값을 쓰면
        점 덩어리가 통째로 어긋난다 — 그래서 **다듬은 장면에서 직접 읽는다.**
        """
        raise NotImplementedError("frames() 가 돌려주는 값을 쓸 것")

    def frames(self, count=1, warmup=WARMUP_FRAMES):
        """장면을 받아 `(깊이 m, 색 사진 또는 None, 초점거리 정보)` 로 돌려준다."""
        import numpy as np

        out = []
        intr = None
        for i in range(warmup + count):
            fs = self.pipe.wait_for_frames()
            if self._align is not None:
                fs = self._align.process(fs)
            d = fs.get_depth_frame()
            if not d:
                continue
            if self.filters is not None:
                d = self.filters.process(d)
            if i < warmup:            # 준비 장면도 다듬기에 통과시켜야 시간 다듬기가 찬다
                continue
            if intr is None:
                intr = d.profile.as_video_stream_profile().get_intrinsics()
            c = fs.get_color_frame() if self.has_color else None
            out.append((np.asanyarray(d.get_data()).astype(np.float32) * self.scale,
                        np.asanyarray(c.get_data()) if c else None))
        return out, intr

    def close(self):
        try:
            self.pipe.stop()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def open_depth(width=None, height=None, fps=30, color=False,
               decimate=2, fill_holes=False, filters=True, retry_reset=True):
    """깊이(필요하면 색까지) 스트림을 연다. **멈춰 있으면 재설정하고 다시 연다.**"""
    import pyrealsense2 as rs

    if not list(rs.context().query_devices()):
        raise RuntimeError(
            "카메라가 안 보인다. USB 를 다시 꽂고(가능하면 본체 뒤 USB 3.0), "
            "다른 프로그램(RealSense Viewer, 다른 파이썬 창)이 쥐고 있지 않은지 볼 것.")

    tries = [(width, height, fps)] if width else list(PREFERRED)
    last = None
    for attempt in range(2):
        for w, h, f in tries:
            pipe = rs.pipeline()
            conf = rs.config()
            conf.enable_stream(rs.stream.depth, w, h, rs.format.z16, f)
            if color:
                conf.enable_stream(rs.stream.color, w, h, rs.format.bgr8, f)
            try:
                profile = pipe.start(conf)
                pipe.wait_for_frames(FIRST_FRAME_TIMEOUT_MS)   # 진짜 들어오는지 확인
                return DepthStream(
                    rs, pipe, profile, (w, h, f),
                    DepthFilters(rs, decimate, fill_holes) if filters else None,
                    color)
            except Exception as e:
                last = e
                try:
                    pipe.stop()
                except Exception:
                    pass
        if attempt == 0 and retry_reset:
            print("카메라가 영상을 안 준다 — 재설정하고 다시 연다. (파란 화면·강제 종료 뒤에")
            print("장치는 보이는데 영상이 안 나오는 상태로 남는 일이 있다)")
            if not reset_device(rs):
                break
    raise RuntimeError("깊이 스트림을 열지 못했다: {}".format(last))
