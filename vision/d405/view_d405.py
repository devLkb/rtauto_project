# -*- coding: utf-8 -*-
"""D405 가 **지금 무엇을 보고 있는지** 화면으로 본다 (원칙 6).

왜 눈으로 봐야 하나
-------------------
숫자만 보면 놓치는 것이 있다. 2026-09-17 에도 화면에서 "손가락이 종이컵을 뚫고
들어간다" 를 발견해 물리 접촉을 실측하게 됐다. 깊이 카메라는 특히 **눈으로 봐야
아는 것**이 많다 — 어떤 물체는 통째로 안 찍히고, 어떤 면은 구멍이 숭숭 뚫린다.

창에 무엇이 보이나
------------------
왼쪽에 **색 사진**, 오른쪽에 **깊이를 색으로 칠한 그림**이 나란히 뜬다.

    깊이 색깔:  가까움 ← 빨강 · 노랑 · 초록 · 파랑 → 멂 ·  **검정 = 값이 없음**

**검정이 중요하다.** 그 자리는 카메라가 거리를 못 잰 곳이다. 물체가 검정으로 나오면
그 물체는 지금 조건에서 **안 보이는 것**이고, 손목에 달아도 못 쓴다.

화면 가운데 십자 자리의 거리와, 값이 있는 화소 비율을 위에 적어 준다.

누르는 키
---------
====  ==========================================================
 q    끝내기
 s    지금 화면을 사진으로 저장 (색 + 깊이)
 c    지금 점 덩어리를 파일로 저장 (나중에 시뮬레이터 것과 견주려고)
 3    **3차원으로 돌려 보기** — 점 덩어리를 띄운다 (창을 닫으면 계속)
 r    깊이 색칠 범위를 지금 장면에 맞춰 다시 잡는다
====  ==========================================================

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/view_d405.py

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python vision/d405/view_d405.py

가까운 것만 보고 싶으면(파지 거리):

    python vision/d405/view_d405.py --near 0.09 --far 0.35

⚠️ 창이 안 뜨면 원격 접속 중일 수 있다. 그때는 `--save-only` 로 사진만 남긴다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 창에 띄울 크기. 너무 크면 느리고 너무 작으면 안 보인다.
VIEW_W, VIEW_H = 640, 360

#: 사진 한 장만 찍을 때(`--save-only`) 버리는 장면 수. 시간 다듬기가 채워질 시간을 준다.
SETTLE_FRAMES = 20


def colorize(depth_m, near, far):
    """깊이(m) → 보기 좋은 색. **값이 없는 곳은 검정**으로 남긴다.

    값이 없는 곳을 억지로 칠하면 "안 보이는 물체" 를 못 알아채게 된다 — 그래서
    일부러 검정으로 둔다.
    """
    import cv2

    valid = (depth_m > 0) & np.isfinite(depth_m)
    span = max(1e-6, far - near)
    norm = np.clip((depth_m - near) / span, 0.0, 1.0)
    # 가까운 쪽이 빨강이 되도록 뒤집어서 넣는다
    img = cv2.applyColorMap(((1.0 - norm) * 255).astype(np.uint8), cv2.COLORMAP_JET)
    img[~valid] = 0
    return img


#: 한글을 그릴 글꼴. ⚠️ **OpenCV 의 글자 그리기는 한글을 못 쓴다** — 전부 `???` 로
#: 나온다(2026-09-18 실측). 그래서 PIL 로 그린다. 글꼴이 없으면 영어로 물러선다.
#: 경로는 OS 마다 다르므로 후보를 훑는다(원칙 2 — 다른 머신에서도 돌아야 한다).
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\malgun.ttf",                          # 윈도우 맑은 고딕
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",         # 리눅스
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",              # 맥
)
_font_cache = {}


def _font(size=15):
    if size in _font_cache:
        return _font_cache[size]
    got = None
    try:
        from PIL import ImageFont
        for path in _FONT_CANDIDATES:
            if Path(path).exists():
                got = ImageFont.truetype(path, size)
                break
    except Exception:
        got = None
    _font_cache[size] = got
    return got


def _text_width(font, text):
    """글자가 화면에서 차지하는 가로 길이(화소). 글꼴이 없으면 어림잡는다."""
    if font is None:
        return len(text) * 9
    try:
        return int(font.getlength(text))
    except AttributeError:                          # 오래된 Pillow
        return int(font.getsize(text)[0])


def _wrap(lines, font, max_width):
    """**화면 밖으로 잘리지 않게** 줄을 나눈다.

    빈칸에서 먼저 나누고, 빈칸 없이 긴 덩어리는 글자 단위로 자른다.
    (한글은 빈칸이 적어 글자 단위 자르기가 실제로 필요하다)
    """
    out = []
    for text in lines:
        if _text_width(font, text) <= max_width:
            out.append(text)
            continue
        cur = ""
        for word in text.split(" "):
            trial = word if not cur else cur + " " + word
            if _text_width(font, trial) <= max_width:
                cur = trial
                continue
            if cur:
                out.append(cur)
            while _text_width(font, word) > max_width:   # 한 낱말이 통째로 길 때
                cut = len(word)
                while cut > 1 and _text_width(font, word[:cut]) > max_width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            cur = word
        if cur:
            out.append(cur)
    return out


def put_lines(img, lines, color=(255, 255, 255), max_width=None):
    """왼쪽 위에 여러 줄을 적는다. 한글이 되게 PIL 로 그린다.

    `max_width` 를 넘는 줄은 **알아서 접는다**(기본: 사진 너비). 전에는 그냥 잘려서
    화면 밖으로 나갔다 — 사용자가 화면에서 발견(2026-09-18).
    """
    font = _font()
    max_width = (img.shape[1] - 16) if max_width is None else int(max_width)
    lines = _wrap(list(lines), font, max_width)

    if font is None:                    # 글꼴이 없으면 OpenCV 로(영어만 제대로 나온다)
        import cv2
        for i, t in enumerate(lines):
            y = 20 + i * 20
            cv2.putText(img, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
            cv2.putText(img, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        return img

    from PIL import Image, ImageDraw
    pil = Image.fromarray(img[:, :, ::-1])          # BGR -> RGB
    draw = ImageDraw.Draw(pil)
    for i, t in enumerate(lines):
        xy = (8, 6 + i * 20)
        # 검은 테두리를 먼저 그려 어떤 배경에서도 읽히게
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
            draw.text((xy[0] + dx, xy[1] + dy), t, font=font, fill=(0, 0, 0))
        draw.text(xy, t, font=font, fill=color[::-1])
    return np.asarray(pil)[:, :, ::-1].copy()       # RGB -> BGR


def put_labels(img, labels, size=22):
    """**그림 위 아무 자리에나** 글자를 적는다 — 덩어리마다 번호를 찍을 때 쓴다.

    `labels` 는 `(x, y, 글자, 색BGR)` 목록. `(x, y)` 는 글자의 **가운데**다.
    화면 밖으로 나가지 않게 안쪽으로 밀어 넣는다.

    왜 필요한가: 목록에는 "99번" 이라고 적혀 있는데 **그림의 어느 덩어리가 99번인지**
    알 수가 없었다(2026-09-18 사용자 지적). 한글이 섞이므로 PIL 로 그린다.
    """
    if not labels:
        return img
    font = _font(size)
    h, w = img.shape[:2]

    if font is None:
        import cv2
        for x, y, text, col in labels:
            p = (int(np.clip(x - 8, 2, w - 20)), int(np.clip(y, 14, h - 4)))
            cv2.putText(img, text, p, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            cv2.putText(img, text, p, cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 1)
        return img

    from PIL import Image, ImageDraw
    pil = Image.fromarray(img[:, :, ::-1])
    draw = ImageDraw.Draw(pil)
    # 글자가 클수록 테두리도 두껍게 — 얇으면 초록 덩어리 위에서 안 읽힌다
    pad = max(1, size // 10)
    ring = [(dx, dy) for dx in range(-pad, pad + 1) for dy in range(-pad, pad + 1)
            if (dx, dy) != (0, 0)]
    for x, y, text, col in labels:
        tw = _text_width(font, text)
        px = int(np.clip(x - tw / 2, 2, max(2, w - tw - 2)))
        py = int(np.clip(y - size / 2, 2, max(2, h - size - 2)))
        for dx, dy in ring:
            draw.text((px + dx, py + dy), text, font=font, fill=(0, 0, 0))
        draw.text((px, py), text, font=font, fill=tuple(col[::-1]))
    return np.asarray(pil)[:, :, ::-1].copy()


def to_points(depth_m, intr, color_img=None):
    """깊이 사진 → 점 덩어리(m) + 각 점의 색."""
    ys, xs = np.nonzero(depth_m > 0)
    z = depth_m[ys, xs]
    pts = np.stack([(xs - intr.ppx) * z / intr.fx,
                    (ys - intr.ppy) * z / intr.fy, z], axis=1)
    cols = None
    if color_img is not None and color_img.shape[:2] == depth_m.shape:
        cols = color_img[ys, xs][:, ::-1] / 255.0      # BGR -> RGB
    return pts, cols


def show_3d(pts, cols, near, far, max_points=40000):
    """점 덩어리를 **3차원으로 돌려 본다**. 창을 닫으면 원래 화면으로 돌아온다."""
    try:
        import matplotlib
        import matplotlib.pyplot as plt  # noqa: F401
    except ImportError:
        print("matplotlib 이 없어 3차원 보기를 건너뛴다.")
        return
    import matplotlib.pyplot as plt

    sel = (pts[:, 2] >= near) & (pts[:, 2] <= far)
    p = pts[sel]
    c = cols[sel] if cols is not None else None
    if len(p) == 0:
        print("그 거리 범위 안에 점이 없다.")
        return
    if len(p) > max_points:                   # 너무 많으면 느리다
        idx = np.random.default_rng(0).choice(len(p), max_points, replace=False)
        p, c = p[idx], (c[idx] if c is not None else None)

    fig = plt.figure(figsize=(9, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(p[:, 0], p[:, 2], -p[:, 1], s=1,
               c=(c if c is not None else p[:, 2]), cmap=None if c is not None else "jet")
    ax.set_xlabel("좌우 (m)")
    ax.set_ylabel("앞뒤 = 카메라에서 멀어지는 쪽 (m)")
    ax.set_zlabel("위아래 (m)")
    ax.set_title("D405 가 본 점 {}개  ({:.2f}~{:.2f} m)".format(len(p), near, far))
    # 세 축의 길이 비율을 같게 — 안 그러면 물체가 찌그러져 보인다
    rng_ = np.ptp(np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1), axis=0).max() / 2.0
    mid = np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1).mean(axis=0)
    ax.set_xlim(mid[0] - rng_, mid[0] + rng_)
    ax.set_ylim(mid[1] - rng_, mid[1] + rng_)
    ax.set_zlim(mid[2] - rng_, mid[2] + rng_)
    print("3차원 창을 띄웠다 — 마우스로 끌어서 돌려 볼 수 있다. 닫으면 계속된다.")
    plt.show()


def main() -> int:
    ap = argparse.ArgumentParser(description="D405 실시간 보기 (원칙 6)")
    ap.add_argument("--near", type=float, default=None,
                    help="색칠 시작 거리(m). 안 주면 **지금 장면에 맞춰 자동**")
    ap.add_argument("--far", type=float, default=None,
                    help="색칠 끝 거리(m). 안 주면 자동")
    ap.add_argument("--fixed-range", action="store_true",
                    help="색 범위를 설정값(D405_NEAR_M~FAR_M)으로 고정한다")
    ap.add_argument("--width", type=int, default=848)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--save-only", action="store_true",
                    help="창을 안 띄우고 사진만 저장한다(원격 접속 등 창이 안 될 때)")
    ap.add_argument("--note", default="", help="무엇을 찍는지 (파일 이름에 들어간다)")
    ap.add_argument("--compare", action="store_true",
                    help="**날것과 다듬기 켠 것을 나란히** 보여 준다 (무엇이 좋아졌는지 눈으로)")
    ap.add_argument("--raw", action="store_true", help="다듬기를 끄고 날것만 본다")
    args = ap.parse_args()

    try:
        import cv2
        import pyrealsense2 as rs
    except ImportError as e:
        print("필요한 것이 없다: {}".format(e))
        return 2

    # ⚠️ **색 범위는 성능이 아니라 보기다.** RealSense Viewer 는 장면에 맞춰 색 범위를
    #    자동으로 늘리는데, 우리가 범위를 고정해 두면 그 밖은 한 색으로 눌려 "Viewer 가
    #    더 잘 본다" 처럼 보인다(2026-09-18 사용자 지적). 실제로 재 보면 잡히는 화소
    #    비율은 같다. 그래서 **기본을 자동**으로 바꾸고, 고정하려면 --fixed-range 를 준다.
    auto_range = (args.near is None and args.far is None and not args.fixed_range)
    near = cfg.D405_NEAR_M if args.near is None else args.near
    far = cfg.D405_FAR_M if args.far is None else args.far

    def start_once():
        pipe = rs.pipeline()
        conf = rs.config()
        conf.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, 30)
        conf.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, 30)
        profile = pipe.start(conf)
        pipe.wait_for_frames(4000)             # 진짜 영상이 오는지 확인
        return pipe, profile

    try:
        pipe, profile = start_once()
    except Exception:
        # ⚠️ 파란 화면·강제 종료 뒤에는 **장치는 보이는데 영상이 안 오는** 상태로 남는다
        #    (2026-09-18 실측). 그때는 재설정하면 살아난다.
        print("카메라가 영상을 안 준다 — 재설정하고 다시 연다...")
        devs = list(rs.context().query_devices())
        if not devs:
            print("카메라가 안 보인다. USB 를 다시 꽂을 것.")
            return 2
        devs[0].hardware_reset()
        for _ in range(20):
            time.sleep(1.0)
            if list(rs.context().query_devices()):
                break
        time.sleep(2.0)
        pipe, profile = start_once()

    align = rs.align(rs.stream.color)          # 깊이를 색 사진에 맞춰 겹친다
    scale = profile.get_device().first_depth_sensor().get_depth_scale()
    intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()

    # --- 깊이 다듬기 ---------------------------------------------------------
    # **지어내지 않는 것만** 켠다. 구멍 메우기는 없는 값을 만들어 내므로 안 쓴다 —
    # 근거와 실측표는 vision/d405/d405_stream.py 머리말.
    use_filter = not args.raw
    dec = rs.decimation_filter(2)
    to_disp, to_depth = rs.disparity_transform(True), rs.disparity_transform(False)
    spatial, temporal = rs.spatial_filter(), rs.temporal_filter()

    def smooth(frame):
        return to_depth.process(temporal.process(spatial.process(
            to_disp.process(dec.process(frame)))))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=== D405 실시간 보기 ===")
    print("깊이 색: 가까움 빨강 → 멂 파랑,  **검정 = 거리를 못 잰 곳**")
    if auto_range:
        print("색칠 범위: **지금 장면에 맞춰 자동** (RealSense Viewer 와 같은 방식)")
        print("  고정하려면 --fixed-range 또는 --near/--far 를 줄 것")
    else:
        print("색칠 범위 {:.2f} ~ {:.2f} m (고정)".format(near, far))
    print("🛑 **구멍 메우기는 안 쓴다** — 화면이 Viewer 보다 덜 차 보일 수 있는데,")
    print("   그 빈 곳은 **실제로 거리를 못 잰 곳**이다. 지어내지 않는다.")
    print("키: q 끝내기 / s 사진 저장 / c 점 덩어리 저장 / 3 3차원 보기 / r 범위 다시 잡기")
    if args.compare:
        print("비교 모드: 왼쪽 색 사진 / 가운데 **날것** / 오른쪽 **다듬기 켬**")
        print("  -> 검정(못 잰 곳)이 오른쪽에서 얼마나 줄었는지 보면 된다")
    elif args.raw:
        print("날것 모드 (다듬기 꺼짐)")
    else:
        print("다듬기 켜짐 — 구멍 메우기는 **안 쓴다**(없는 값을 지어내므로)")
    print()

    # 창 제목은 영어로 — OpenCV 가 한글 제목을 깨뜨린다
    win = "D405  (left: photo / right: depth)"
    frames_seen = 0
    try:
        while True:
            fs = align.process(pipe.wait_for_frames())
            d = fs.get_depth_frame()
            c = fs.get_color_frame()
            if not d or not c:
                continue
            frames_seen += 1
            raw_m = np.asanyarray(d.get_data()).astype(np.float32) * scale
            color = np.asanyarray(c.get_data())
            if use_filter or args.compare:
                sm = smooth(d)
                filt_m = np.asanyarray(sm.get_data()).astype(np.float32) * scale
            else:
                filt_m = raw_m
            depth_m = raw_m if args.raw else filt_m

            if auto_range:
                # 지금 장면의 거리 분포에 맞춘다. 양 끝 몇 %는 버려야 튀는 값에 안 끌린다.
                got_d = depth_m[depth_m > 0]
                if got_d.size > 500:
                    lo, hi = np.percentile(got_d, (2, 92))
                    if hi - lo > 0.02:
                        # 갑자기 바뀌면 눈이 피로하므로 조금씩 따라간다
                        near += (float(lo) - near) * 0.25
                        far += (float(hi) - far) * 0.25

            dcol = colorize(depth_m, near, far)
            h, w = depth_m.shape
            cy, cx = h // 2, w // 2
            center = float(depth_m[cy, cx])
            valid = float((depth_m > 0).mean())
            in_band = float(((depth_m >= near) & (depth_m <= far)).mean())

            view_c = cv2.resize(color, (VIEW_W, VIEW_H))
            view_d = cv2.resize(dcol, (VIEW_W, VIEW_H))
            for img in (view_c, view_d):
                cv2.drawMarker(img, (VIEW_W // 2, VIEW_H // 2), (255, 255, 255),
                               cv2.MARKER_CROSS, 16, 1)
            view_c = put_lines(view_c, ["색 사진 (사람 눈으로 보는 것)"])
            view_d = put_lines(view_d, [
                "깊이 — 가까움 빨강 / 멂 파랑 / **검정 = 거리를 못 잼**",
                "실제로 본 값만 표시 (구멍 메우기 안 씀)",
                ("가운데 십자 거리 {:.3f} m".format(center) if center > 0
                 else "가운데 십자: 거리를 못 잼"),
                "값 있는 화소 {:.0%}   이 범위 안 {:.0%}".format(valid, in_band),
                "색칠 범위 {:.2f} ~ {:.2f} m".format(near, far),
            ])
            if args.compare:
                rcol = cv2.resize(colorize(raw_m, near, far), (VIEW_W, VIEW_H),
                                  interpolation=cv2.INTER_NEAREST)
                rcol = put_lines(rcol, [
                    "① 날것 (지금까지 쓰던 것)",
                    "값 있는 화소 {:.0%}".format(float((raw_m > 0).mean())),
                ])
                view_d = put_lines(cv2.resize(
                    colorize(filt_m, near, far), (VIEW_W, VIEW_H),
                    interpolation=cv2.INTER_NEAREST), [
                    "② 다듬기 켬 — 지어내지 않음",
                    "값 있는 화소 {:.0%}".format(float((filt_m > 0).mean())),
                    "가운데 십자 {:.3f} m".format(center) if center > 0 else "가운데: 못 잼",
                ])
                both = np.hstack([view_c, rcol, view_d])
            else:
                both = np.hstack([view_c, view_d])

            if args.save_only and frames_seen <= SETTLE_FRAMES:
                # ⚠️ **바로 찍으면 안 된다.** 시간 다듬기(앞뒤 장면 맞추기)는 장면이
                #    몇 장 쌓여야 값을 내놓는다. 첫 장면을 찍으면 값이 있는 화소가
                #    14 % 밖에 안 나온다(2026-09-18 실측) — 실제 성능이 아니다.
                continue

            if args.save_only:
                stem = args.note or time.strftime("%Y%m%d_%H%M%S")
                path = RESULTS_DIR / "view_{}.png".format(stem)
                cv2.imwrite(str(path), both)
                print("사진 저장: {}  (가운데 {:.3f} m, 값 있는 화소 {:.0%})".format(
                    path, center, valid))
                break

            cv2.imshow(win, both)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
            if key == ord("s"):
                stem = time.strftime("%Y%m%d_%H%M%S")
                path = RESULTS_DIR / "view_{}.png".format(stem)
                cv2.imwrite(str(path), both)
                print("사진 저장: {}".format(path))
            if key == ord("c"):
                pts, cols = to_points(depth_m, intr, color)
                stem = time.strftime("%Y%m%d_%H%M%S")
                path = RESULTS_DIR / "cloud_{}.npz".format(stem)
                np.savez_compressed(path, points=pts.astype(np.float32),
                                    colors=(cols.astype(np.float32) if cols is not None
                                            else np.zeros((0, 3), np.float32)),
                                    note=np.asarray(args.note))
                near_far = pts[(pts[:, 2] >= near) & (pts[:, 2] <= far)]
                print("점 덩어리 저장: {}  (전체 {}개, 범위 안 {}개)".format(
                    path, len(pts), len(near_far)))
            if key == ord("3"):
                pts, cols = to_points(depth_m, intr, color)
                cv2.destroyWindow(win)
                show_3d(pts, cols, near, far)
            if key == ord("r"):
                got = depth_m[(depth_m > 0)]
                if got.size:
                    near = float(np.percentile(got, 2))
                    far = float(np.percentile(got, 90))
                    print("색칠 범위를 지금 장면에 맞췄다: {:.2f} ~ {:.2f} m".format(near, far))
    finally:
        pipe.stop()
        try:
            import cv2 as _cv
            _cv.destroyAllWindows()
        except Exception:
            pass
    print("끝. 장면 {}장 봤다.".format(frames_seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
