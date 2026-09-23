# -*- coding: utf-8 -*-
"""`record_hand_poses.py` 녹화를 읽어, 엄지·중지 **후보 계산식들이 자세를 얼마나 잘 가르는지** 비교한다.

돌리는 법 (리포 루트, vision 가상환경)::

    python vision/dg5f/analyze_hand_poses.py                 # 가장 최근 handposes_*.csv
    python vision/dg5f/analyze_hand_poses.py <파일.csv>

표의 숫자는 자세마다의 **중앙값 [5%~95%]** 다. 좋은 계산식은 ① 같은 자세 안에서
폭이 좁고 ② 다른 자세끼리 겹치지 않는다. 맨 아래 "가르는 힘" 은 두 자세 사이의
중앙값 차이를 두 자세의 폭(5%~95%) 평균으로 나눈 값 — **1 보다 크면 안 겹친다.**
"""
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dg5f_angles as A  # noqa: E402
from dg5f_paths import LOG_DIR  # noqa: E402


def load(path):
    import pandas as pd
    d = pd.read_csv(path)
    d = d[(d.detected == 1) & (d.pose != "-")]
    img = np.stack([d[[f"lm{i}_x", f"lm{i}_y", f"lm{i}_z"]].to_numpy() for i in range(21)], axis=1)
    img[:, :, 1] *= (d.frame_h / d.frame_w).to_numpy()[:, None]   # landmarks_to_xyz 와 같은 등방 보정
    world = np.stack([d[[f"wl{i}_x", f"wl{i}_y", f"wl{i}_z"]].to_numpy() for i in range(21)], axis=1)
    return d.pose.to_numpy(), img, world


def load_d3(path):
    """D405 녹화(`--camera d405`)면 관절 입체 위치(장면x21x3, m, 못 읽은 것은 NaN). 아니면 None."""
    import pandas as pd
    d = pd.read_csv(path)
    if "d30_x" not in d.columns:
        return None
    d = d[(d.detected == 1) & (d.pose != "-")]
    return np.stack([d[[f"d3{i}_x", f"d3{i}_y", f"d3{i}_z"]].to_numpy(dtype=float)
                     for i in range(21)], axis=1)


#: 엄지·중지 값 계산에 쓰는 관절 — D405 에서 이 중 하나라도 깊이를 못 읽은 장면은 뺀다.
NEEDED = sorted({0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 13, 17})


def features(lm):
    """한 장면의 후보 값들. 이름 → 값."""
    out = {}
    out["대향량(현재)"] = A.thumb_opp_amount_lm(lm)
    out["opp_dist(옛)"] = A._thumb_opposition(lm)
    out["thumb_cmc_abd(현재)"] = np.degrees(A._thumb_abduction(lm))
    for k, v in A.thumb_features(lm).items():
        out[k] = v
    out["middle_abd(현재)"] = np.degrees(A._abduction(lm, A.MIDDLE))
    out["middle_mcp"] = np.degrees(A._bend_mcp(lm, A.MIDDLE))
    return out


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(LOG_DIR, "handposes_*.csv")))
        if not files:
            print("handposes_*.csv 가 없다 — 먼저 record_hand_poses.py 로 녹화할 것.")
            return 2
        path = files[-1]
    print("파일:", path)
    all_poses, img, world = load(path)
    sources = [("이미지 점", img), ("world 점", world)]
    d3 = load_d3(path)
    if d3 is not None:
        sources.append(("D405 입체 점", d3))
    for src_name, pts in sources:
        keep = np.all(np.isfinite(pts[:, NEEDED, :]), axis=(1, 2))
        poses, pts = all_poses[keep], pts[keep]
        if not keep.all():
            print(f"\n({src_name}: 필요한 관절 깊이를 다 읽은 장면만 씀 — "
                  f"{keep.sum()}/{keep.size}, 자세별: " + ", ".join(
                      f"{q} {int(keep[all_poses == q].sum())}/{int((all_poses == q).sum())}"
                      for q in dict.fromkeys(all_poses)) + ")")
        if not len(pts):
            continue
        rows = [features(p) for p in pts]
        names = list(rows[0])
        vals = {n: np.array([r[n] for r in rows]) for n in names}
        order = [p for p in dict.fromkeys(poses)]
        print(f"\n=== {src_name} — 자세별 중앙값 [5%~95%] ===")
        print("자세".ljust(18) + "".join(n[:22].rjust(24) for n in names))
        stats = {}
        for p in order:
            m = poses == p
            line = f"{p} ({m.sum()})".ljust(18)
            for n in names:
                v = vals[n][m]
                lo, med, hi = np.percentile(v, [5, 50, 95])
                stats[(p, n)] = (lo, med, hi)
                line += f"{med:8.2f} [{lo:6.2f}~{hi:6.2f}]".rjust(24)
            print(line)
        print("\n가르는 힘 (1보다 크면 두 자세가 안 겹친다)")
        for a, b in [("flat", "oppose"), ("flat", "pinch"), ("flat", "thumb_front"),
                     ("spread", "flat"), ("spread", "oppose"),
                     ("fingers_together", "fingers_spread"),
                     ("middle_to_index", "middle_to_ring"),
                     ("flat_side", "pinch_side"), ("flat_side", "thumb_front_side"),
                     ("spread_side", "thumb_front_side")]:
            if (a, names[0]) not in stats or (b, names[0]) not in stats:
                continue
            line = f"  {a} vs {b}".ljust(34)
            for n in names:
                la, ma, ha = stats[(a, n)]
                lb, mb, hb = stats[(b, n)]
                width = ((ha - la) + (hb - lb)) / 2.0
                line += f"{n[:14]} {abs(ma - mb) / width if width > 1e-9 else 0:5.2f}  "
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
