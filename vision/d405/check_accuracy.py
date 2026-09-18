# -*- coding: utf-8 -*-
"""**카메라가 말하는 거리가 실제와 맞나** — "일정한가" 가 아니라 "맞나" 를 잰다.

왜 따로 재나
------------
앞서 잰 것은 **흔들림**(같은 자리를 여러 번 봤을 때 얼마나 일정한가)이다. 그것만으로는
**늘 똑같이 5 mm 틀리는 것**을 못 잡는다 — 그런 오차는 흔들림 0.4 mm 로 멀쩡하게 나온다.

그리고 그런 오차가 가장 위험하다. 손목 카메라 장착값을 맞출 때 **그대로 넘어가서**
모든 파지가 같은 방향으로 어긋난다. 우리 오차 예산이 1 cm 인데(2026-09-18 실측:
1 cm 밀면 잘 되던 자세의 44 % 가 실패) 5 mm 면 절반을 먹는다.

게다가 **깊이 다듬기를 우리가 새로 켰다.** 옆 화소·앞뒤 장면을 섞는 계산이라 값을
조금씩 끌어당길 수 있는데 아직 아무도 확인하지 않았다.

🛑 **2026-09-18 — 지금은 재지 않기로 했다 (사용자 결정)**
------------------------------------------------------
이유:

1. **줄자 기준점이 애매하다.** D405 의 깊이 기준점이 앞면 유리의 정확히 어디인지
   확실하지 않아, 줄자로 잰 값 자체에 몇 mm 오차가 들어간다. 그러면 몇 mm 를 찾으려다
   몇 mm 를 새로 들여오는 꼴이다.
2. **어차피 손목에 달 때 흡수된다.** 거리가 늘 3 mm 짧게 나오는 것과 카메라가 3 mm
   앞에 붙은 것은 **계산상 구분되지 않는다.** 손-눈 맞추기(BACKLOG D-7)가 장착값을
   풀 때 이 상수 오차를 함께 흡수한다. 그때 한 번에 재는 편이 정확하고 싸다.

⚠️ **다만 흡수되지 않는 오차가 하나 있다 — 배율.** 거리에 비례해 커지는 오차는
   장착값으로 못 메운다. 그건 `--object`(크기 확인)로만 잡히므로, **손목에 달고 나서
   장착값을 맞춘 뒤** 한 번은 크기를 확인할 것.

아래 도구는 그대로 두었다. 로봇팔·그리퍼와 통합한 뒤 쓰면 된다.

두 가지를 잰다
--------------
**① 거리가 맞나** (`--flat`)
   평평한 것(벽·책·상자 옆면)을 카메라 정면에 두고, **줄자로 잰 거리**를 넣는다.
   카메라가 말하는 거리와 비교한다. 면을 맞춰서 재므로 화소 하나의 잡음에 안 흔들린다.

**② 크기가 맞나** (`--object`)
   크기를 아는 물체(캔·컵)를 두고 **줄자로 잰 크기**를 넣는다. 거리가 맞아도 **배율이
   틀리면** 크기가 어긋난다 — 거리와 배율은 다른 오차다.

⚠️ 다듬기를 켠 것과 끈 것을 **둘 다** 재서 나란히 보여 준다. 다듬기가 값을 끌어당기는지
   그 자리에서 드러난다.

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1

거리 확인 — 평평한 것을 카메라 정면 20 cm 에 두고 줄자로 잰 뒤:

    python vision/d405/check_accuracy.py --flat --true-cm 20

크기 확인 — 캔을 두고 지름을 줄자로 잰 뒤(예: 5.3 cm):

    python vision/d405/check_accuracy.py --object --true-cm 5.3

⚠️ 줄자는 **카메라 앞면 유리**에서 잰다. D405 의 깊이 기준점은 앞면 유리 근처다
   (정확한 기준점은 제조사 도면에 있으나 우리는 mm 단위를 다투는 것이 아니라
   cm 단위 오차를 찾는 것이므로 이것으로 충분하다).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 가운데에서 이 비율만큼만 본다. 가장자리는 렌즈 끝이라 덜 믿을 만하고, 평평한 것을
#: 화면 가득 채우지 않아도 되게 한다.
CENTER_FRAC = 0.4

#: 몇 장면을 모아 볼지.
FRAMES = 15


def center_patch(depth_m, frac=CENTER_FRAC):
    """화면 가운데 네모만 잘라낸다."""
    h, w = depth_m.shape
    dh, dw = int(h * frac / 2), int(w * frac / 2)
    return depth_m[h // 2 - dh:h // 2 + dh, w // 2 - dw:w // 2 + dw]


def plane_distance(depth_m, intr, frac=CENTER_FRAC):
    """가운데 네모에 **면을 맞춰** 카메라에서 그 면까지의 거리를 낸다.

    화소 하나를 읽으면 잡음에 흔들리므로, 수천 개로 면을 맞춰 **면까지의 수직 거리**를
    쓴다. 면이 얼마나 평평한지도 같이 돌려준다(평평하지 않으면 잘못 겨눈 것이다).
    """
    h, w = depth_m.shape
    dh, dw = int(h * frac / 2), int(w * frac / 2)
    ys, xs = np.mgrid[h // 2 - dh:h // 2 + dh, w // 2 - dw:w // 2 + dw]
    z = depth_m[h // 2 - dh:h // 2 + dh, w // 2 - dw:w // 2 + dw]
    ok = z > 0
    if ok.sum() < 200:
        return None
    zz = z[ok]
    px = (xs[ok] - intr.ppx) * zz / intr.fx
    py = (ys[ok] - intr.ppy) * zz / intr.fy
    pts = np.stack([px, py, zz], axis=1).astype(np.float64)

    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[-1]
    if n[2] > 0:                       # 법선을 카메라 쪽으로 맞춘다
        n = -n
    resid = (pts - c) @ n
    return dict(dist_m=float(abs(c @ n)),          # 원점(카메라)에서 면까지 수직 거리
                center_z_m=float(np.median(zz)),   # 가운데 화소들의 거리 중앙값
                flat_mm=float(np.std(resid) * 1000.0),
                tilt_deg=float(np.degrees(np.arccos(min(1.0, abs(n[2]))))),
                pixels=int(ok.sum()), valid_frac=float(ok.mean()))


def grab(rs, w, h, filt, frames=FRAMES):
    """장면을 모아 **거리 사진 평균**과 초점거리 정보를 돌려준다."""
    pipe = rs.pipeline()
    conf = rs.config()
    conf.enable_stream(rs.stream.depth, w, h, rs.format.z16, 30)
    prof = pipe.start(conf)
    scale = prof.get_device().first_depth_sensor().get_depth_scale()
    dec = rs.decimation_filter(2)
    tod, toz = rs.disparity_transform(True), rs.disparity_transform(False)
    spa, tem = rs.spatial_filter(), rs.temporal_filter()
    stack, intr = [], None
    try:
        for i in range(frames + 15):
            d = pipe.wait_for_frames(5000).get_depth_frame()
            if not d:
                continue
            if filt:
                d = toz.process(tem.process(spa.process(tod.process(dec.process(d)))))
            if i < 15:
                continue
            if intr is None:
                intr = d.profile.as_video_stream_profile().get_intrinsics()
            stack.append(np.asanyarray(d.get_data()).astype(np.float32) * scale)
    finally:
        pipe.stop()
    if not stack:
        return None, None
    a = np.stack(stack)
    valid = a > 0
    out = np.where(valid.any(axis=0),
                   np.divide(np.where(valid, a, 0).sum(axis=0),
                             np.maximum(valid.sum(axis=0), 1)), 0.0)
    return out, intr


def reset(rs):
    devs = list(rs.context().query_devices())
    if not devs:
        return
    devs[0].hardware_reset()
    for _ in range(25):
        time.sleep(1.0)
        if list(rs.context().query_devices()):
            break
    time.sleep(2.0)


def main() -> int:
    ap = argparse.ArgumentParser(description="깊이가 실제와 맞나 (거리·크기)")
    ap.add_argument("--flat", action="store_true", help="평평한 것까지의 거리를 확인")
    ap.add_argument("--object", action="store_true", help="물체 크기를 확인")
    ap.add_argument("--true-cm", type=float, required=True,
                    help="줄자로 잰 참값(cm). --flat 이면 거리, --object 면 가장 긴 변")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    if not (args.flat or args.object):
        print(__doc__)
        return 2

    import pyrealsense2 as rs
    if not list(rs.context().query_devices()):
        print("카메라가 안 보인다. USB 를 다시 꽂을 것.")
        return 2

    print("=== 깊이가 실제와 맞나 ===")
    print("줄자로 잰 참값: {:.2f} cm".format(args.true_cm))
    print("⚠️ 줄자는 **카메라 앞면 유리**에서 쟀다고 가정한다.")
    print()

    rows = []
    for filt in (False, True):
        reset(rs)
        try:
            depth, intr = grab(rs, args.width, args.height, filt)
        except Exception as e:
            print("{} — 읽기 실패: {}".format("다듬기 켬" if filt else "날것", e))
            continue
        if depth is None:
            continue
        label = "다듬기 켬" if filt else "날것"

        if args.flat:
            got = plane_distance(depth, intr)
            if got is None:
                print("{}: 가운데에 값이 너무 적다 — 평평한 것을 화면 가운데에 채울 것".format(label))
                continue
            rows.append((label, got))
        else:
            from segment_objects import find_objects
            ys, xs = np.nonzero(depth > 0)
            z = depth[ys, xs]
            pts = np.stack([(xs - intr.ppx) * z / intr.fx,
                            (ys - intr.ppy) * z / intr.fy, z], axis=1)
            objs, _, note = find_objects(pts)
            if not objs:
                print("{}: 물체를 못 찾았다 ({})".format(label, note))
                continue
            o = objs[0]
            rows.append((label, dict(size_cm=o.size * 100, max_cm=o.max_side_m * 100,
                                     dist_m=o.distance_m, pixels=o.n_points)))

    if not rows:
        print("잴 수 있는 장면이 없다.")
        return 2

    print("-" * 70)
    if args.flat:
        print("{:<10s} {:>10s} {:>10s} {:>10s} {:>9s} {:>9s}".format(
            "", "잰 거리cm", "차이mm", "평평함mm", "기울기도", "값있음"))
        for label, g in rows:
            diff_mm = (g["dist_m"] * 100 - args.true_cm) * 10
            print("{:<10s} {:>10.2f} {:>+10.1f} {:>10.2f} {:>9.1f} {:>8.0%}".format(
                label, g["dist_m"] * 100, diff_mm, g["flat_mm"], g["tilt_deg"],
                g["valid_frac"]))
        print()
        worst = max(abs((g["dist_m"] * 100 - args.true_cm) * 10) for _, g in rows)
        tilt = max(g["tilt_deg"] for _, g in rows)
        if tilt > 20:
            print("⚠️ 면이 {:.0f}도 기울어 보인다 — 카메라를 정면으로 겨누고 다시 재라.".format(tilt))
        print("**차이 {:.1f} mm**".format(worst))
        if worst <= 3:
            print("→ 우리 오차 예산(1 cm)에 견주면 무시할 만하다. 그대로 쓴다.")
        elif worst <= 10:
            print("→ 예산의 상당 부분을 먹는다. 손목 장착값을 맞출 때 **이만큼 빼 주는 것**을")
            print("   고려할 것. 다만 줄자 자체의 오차도 이 정도이므로 여러 거리에서 다시 재라.")
        else:
            print("→ **너무 크다.** 줄자 기준점(카메라 앞면 유리)을 다시 확인하고,")
            print("   그래도 크면 카메라 보정을 의심해야 한다.")
    else:
        print("{:<10s} {:>10s} {:>10s} {:>22s} {:>9s}".format(
            "", "잰 크기cm", "차이mm", "가로x세로x깊이 cm", "거리m"))
        for label, g in rows:
            diff_mm = (g["max_cm"] - args.true_cm) * 10
            print("{:<10s} {:>10.2f} {:>+10.1f} {:>8.1f}x{:.1f}x{:.1f} {:>12.3f}".format(
                label, g["max_cm"], diff_mm, *g["size_cm"], g["dist_m"]))
        print()
        print("⚠️ 한쪽에서만 보므로 **뒤쪽이 안 잡혀 크기가 작게 나오는 것이 정상**이다.")
        print("   가장 긴 변(보이는 쪽 폭)만 견주는 것이 맞다.")
    print("-" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
