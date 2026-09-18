# -*- coding: utf-8 -*-
"""깊이가 **어디서 잘 나오고 어디서 비는가** — 거리 × 각도로 표를 만든다.

왜 표로 만드나
--------------
"D405 는 7 cm 부터 50 cm 까지 잘 잰다" 는 제조사 말이다. 우리가 알아야 하는 것은 다르다:

    **우리 물체를, 우리가 볼 각도에서, 얼마나 떨어져서 보면 제대로 잡히나?**

특히 걱정되는 것:

- **종이컵** — 옆에서 보면 벽이 거의 선처럼 보인다
- **납작한 판** — 눕혀 놓고 옆에서 보면 두께가 안 잡힐 수 있다
- **매끈한 면** — 비스듬히 보면 빛이 튕겨 나가 값이 빈다

이 표가 **"손목 카메라를 어느 각도로 달아야 하나"** 의 근거가 된다. 지금은 근거가 없다.

⚠️ 카메라 내부값(초점거리·시야각)은 **카메라를 어느 방향으로 두든 안 변한다** — 그건
`probe_d405.py --info` 로 이미 쟀다. 여기서 재는 것은 **장면에 따라 달라지는 것**이다.

어떻게 쓰나 — 사람이 물체를 옮겨 가며 찍는다
---------------------------------------------
한 칸 찍을 때마다 물체를 옮기고 명령을 한 번 돌린다. 그때마다 **무엇을 어떻게 놓았는지**
`--object` `--dist` `--angle` 로 적어 주면 표에 함께 쌓인다.

터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1

    # 종이컵을 카메라 앞 10 cm 에 정면으로 놓고
    python vision/d405/depth_matrix.py --object 종이컵 --dist 10 --angle 0

    # 같은 컵을 45도 비스듬히
    python vision/d405/depth_matrix.py --object 종이컵 --dist 10 --angle 45

    # 다 찍은 뒤 표 보기
    python vision/d405/depth_matrix.py --report

찍을 때 지키면 좋은 것:

1. **물체만 보이게** 한다 — 뒤에 벽이 가까우면 배경까지 잡혀 숫자가 좋아 보인다
2. 거리는 자로 **카메라 앞면부터** 잰다
3. 각도 0 = 물체의 넓은 면을 **정면으로** 본 것, 90 = 옆에서 본 것

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python vision/d405/depth_matrix.py --object 종이컵 --dist 10 --angle 0
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402

from probe_d405 import grab_depth, open_pipe, read_intrinsics, to_points  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"
TABLE = RESULTS_DIR / "depth_matrix.json"

#: 물체가 있을 만한 자리만 본다 — 화면 가운데 이 비율만큼. 배경이 섞이면 숫자가 좋아 보인다.
CENTER_FRACTION = 0.4


def center_box(h, w, frac=CENTER_FRACTION):
    dh, dw = int(h * frac / 2), int(w * frac / 2)
    return h // 2 - dh, h // 2 + dh, w // 2 - dw, w // 2 + dw


def measure(stack, scale, intr):
    """한 장면의 깊이 품질. **화면 가운데만** 본다."""
    d = stack.astype(np.float64) * scale
    n, h, w = d.shape
    y0, y1, x0, x1 = center_box(h, w)
    mid = d[:, y0:y1, x0:x1]
    valid = mid > 0

    frac = float(valid.mean())
    always = valid.all(axis=0)
    jitter = float(np.median(mid[:, always].std(axis=0)) * 1000.0) if always.any() else float("nan")
    dist = float(np.median(mid[valid])) if valid.any() else float("nan")

    # 점 덩어리로 바꿨을 때 몇 개나 남나 — 학습 입력과 같은 형태로 본다
    last = d[-1]
    pts = to_points(last, intr)
    in_band = pts[(pts[:, 2] >= cfg.D405_NEAR_M) & (pts[:, 2] <= cfg.D405_FAR_M)]

    return dict(valid_frac=frac, jitter_mm=jitter, median_dist_m=dist,
                points_total=int(len(pts)), points_in_band=int(len(in_band)),
                center_fraction=CENTER_FRACTION)


def load_table():
    if TABLE.exists():
        return json.loads(TABLE.read_text(encoding="utf-8"))
    return {"rows": []}


def report(table):
    rows = table.get("rows", [])
    if not rows:
        print("아직 찍은 것이 없다. --object/--dist/--angle 로 한 칸씩 찍어라.")
        return 1

    print("=== 깊이가 어디서 잘 나오나 ===")
    print("(화면 가운데 {:.0%} 만 본 값이다 — 배경이 섞이지 않게)".format(CENTER_FRACTION))
    print()
    objs = list(dict.fromkeys(r["object"] for r in rows))
    for name in objs:
        mine = [r for r in rows if r["object"] == name]
        print("[{}]".format(name))
        print("  {:>6s} {:>6s} | {:>8s} {:>8s} {:>8s} {:>8s}".format(
            "거리cm", "각도", "값있음", "흔들림", "잰거리", "점개수"))
        print("  " + "-" * 56)
        for r in sorted(mine, key=lambda r: (r["dist_cm"], r["angle_deg"])):
            m = r["measure"]
            print("  {:>6.0f} {:>5.0f}도 | {:>7.0%} {:>7.2f}mm {:>7.3f}m {:>8d}".format(
                r["dist_cm"], r["angle_deg"], m["valid_frac"], m["jitter_mm"],
                m["median_dist_m"], m["points_in_band"]))
        print()

    print("-" * 62)
    print("읽는 법")
    print("  값있음  : 물체 자리에서 깊이가 나온 화소 비율. 낮으면 **안 보이는 것**이다")
    print("  흔들림  : 같은 자리 거리가 얼마나 들쭉날쭉한가. 클수록 못 믿는다")
    print("  잰거리  : 카메라가 말한 거리. 자로 잰 값과 다르면 그만큼 틀린 것이다")
    print("  점개수  : 점 덩어리로 바꿨을 때 남는 점 (설정 거리 범위 안)")
    print()
    bad = [r for r in rows if r["measure"]["valid_frac"] < 0.5]
    if bad:
        print("⚠️ 절반도 안 잡힌 칸 {}개:".format(len(bad)))
        for r in bad:
            print("   {} / {:.0f}cm / {:.0f}도 → {:.0%}".format(
                r["object"], r["dist_cm"], r["angle_deg"], r["measure"]["valid_frac"]))
        print("   이 조건에서는 물체를 못 본다. 손목 카메라 각도를 정할 때 피해야 한다.")
    off = [r for r in rows
           if np.isfinite(r["measure"]["median_dist_m"])
           and abs(r["measure"]["median_dist_m"] * 100 - r["dist_cm"]) > 1.0]
    if off:
        print()
        print("⚠️ 자로 잰 거리와 1 cm 넘게 차이 나는 칸 {}개:".format(len(off)))
        for r in off:
            print("   {} / 자 {:.0f}cm vs 카메라 {:.1f}cm".format(
                r["object"], r["dist_cm"], r["measure"]["median_dist_m"] * 100))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="깊이 품질을 거리 × 각도로 재기")
    ap.add_argument("--object", default=None, help="지금 놓은 물체 이름")
    ap.add_argument("--dist", type=float, default=None, help="카메라 앞면부터 거리(cm)")
    ap.add_argument("--angle", type=float, default=0.0,
                    help="보는 각도(도). 0=넓은 면을 정면으로, 90=옆에서")
    ap.add_argument("--report", action="store_true", help="지금까지 찍은 표를 본다")
    ap.add_argument("--cloud", action="store_true", help="점 덩어리도 파일로 남긴다")
    args = ap.parse_args()

    table = load_table()
    if args.report:
        return report(table)
    if not args.object or args.dist is None:
        print(__doc__)
        return 2

    try:
        import pyrealsense2 as rs
    except ImportError:
        print("pyrealsense2 가 없다 — `pip install pyrealsense2` 후 다시.")
        return 2
    if not list(rs.context().query_devices()):
        print("카메라가 안 보인다. USB 를 다시 꽂고 다른 프로그램이 쥐고 있지 않은지 확인.")
        return 2

    pipe, profile, mode = open_pipe(rs)
    try:
        intr = read_intrinsics(rs, profile)
        scale = profile.get_device().first_depth_sensor().get_depth_scale()
        print("찍는 중: {} / {:.0f}cm / {:.0f}도 ... ".format(
            args.object, args.dist, args.angle), end="", flush=True)
        stack = grab_depth(rs, pipe)
        if stack is None:
            print("실패 — 깊이 장면을 못 받았다.")
            return 2
        m = measure(stack, scale, intr)
        print("끝")
        print()
        print("  값이 있는 화소  : {:.0%}".format(m["valid_frac"]))
        print("  같은 자리 흔들림: {:.2f} mm".format(m["jitter_mm"]))
        print("  카메라가 잰 거리: {:.3f} m   (자로 잰 값 {:.2f} m)".format(
            m["median_dist_m"], args.dist / 100.0))
        print("  점 덩어리       : {}개 (설정 거리 범위 안 {}개)".format(
            m["points_total"], m["points_in_band"]))
        if m["valid_frac"] < 0.5:
            print("  ⚠️ 절반도 안 잡혔다 — 이 조건에서는 물체를 제대로 못 본다.")
        if abs(m["median_dist_m"] * 100 - args.dist) > 1.0:
            print("  ⚠️ 자로 잰 값과 {:.1f} cm 차이 난다.".format(
                abs(m["median_dist_m"] * 100 - args.dist)))

        table["rows"].append(dict(
            at=time.strftime("%Y-%m-%d %H:%M:%S"), object=args.object,
            dist_cm=args.dist, angle_deg=args.angle, mode=list(mode), measure=m))
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        TABLE.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print("표에 쌓았다 ({}칸): {}".format(len(table["rows"]), TABLE))

        if args.cloud:
            depth_m = stack[-1].astype(np.float64) * scale
            pts = to_points(depth_m, intr)
            path = RESULTS_DIR / "cloud_{}_{:.0f}cm_{:.0f}deg.npz".format(
                args.object, args.dist, args.angle)
            np.savez_compressed(path, points=pts.astype(np.float32),
                                object=np.asarray(args.object),
                                dist_cm=np.asarray(args.dist),
                                angle_deg=np.asarray(args.angle),
                                intrinsics=np.asarray(json.dumps(intr)))
            print("점 덩어리 저장: {}".format(path))
    finally:
        pipe.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
