# -*- coding: utf-8 -*-
"""점 덩어리에서 **물체만 남긴다** — 책상과 배경을 뺀다.

왜 필요한가
-----------
카메라가 한 번에 주는 점이 **60만 개**인데 대부분 책상·벽·모니터다. 우리가 자세를
정할 때 보는 것은 **물체 하나**뿐이다. 그래서 물체만 잘라내야 한다.

`docs/EXTERNAL_GRASP_POLICY_SURVEY.md` 가 "🟡 없음 — 만들어야 한다" 로 지목한 부분이다.

왜 YOLO 를 안 쓰나
------------------
YOLO 같은 것은 **미리 배운 종류**만 찾는다. 우리 목적은 **처음 보는 물체**를 잡는
것이라 정면으로 어긋난다(`CLAUDE.md` 프로젝트 목적).

대신 **생김새만 보고** 나눈다. 물체는 책상 위에 놓여 있으므로:

1. 가장 넓은 **평평한 면**(책상)을 찾는다
2. 그 면과 그 아래를 버린다
3. 남은 점들을 **서로 붙어 있는 덩어리**로 묶는다 → 덩어리 하나가 물체 하나

배운 것이 하나도 없으므로 **처음 보는 물체에도 그대로 된다.**

어떻게 평평한 면을 찾나
-----------------------
점 3개를 아무거나 뽑아 면을 만들고, 그 면에 가까운 점이 몇 개인지 센다. 이걸 여러 번
반복해 **가장 많은 점이 붙은 면**을 고른다. 책상은 화면에서 가장 넓으므로 이게 책상이다.

⚠️ **책상이 안 보이면 이 방법이 틀린 면을 고른다** — 벽이나 물체 자체의 평평한 면을
   책상으로 착각할 수 있다. 그래서 `plane_ok()` 로 **"고른 면이 정말 바닥 같은가"** 를
   확인하고, 아니면 평면 빼기를 건너뛴다(조용히 틀리지 않게).

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트) — **눈으로 보기**:

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/segment_objects.py --live

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python vision/d405/segment_objects.py --live

한 장만 찍어 파일로 남기기:

    python vision/d405/segment_objects.py --save
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 면에서 이만큼(m) 안쪽이면 "그 면 위의 점" 으로 본다. 깊이 흔들림(파지 거리에서
#: 0.4 mm 수준)보다 넉넉히 크게 잡아야 책상이 깨끗이 빠진다.
PLANE_TOL_M = 0.008

#: 평평한 면 찾기를 몇 번 시도하나. 많을수록 정확하지만 느리다.
PLANE_TRIES = 200

#: 이 비율보다 적은 점이 붙은 면은 "책상" 으로 안 본다 — 책상이 안 보이는 장면에서
#: 엉뚱한 면을 빼지 않으려는 장치다.
PLANE_MIN_FRAC = 0.15

#: 덩어리로 묶을 때 쓰는 격자 칸 크기(m). 이 정도 안에 붙어 있으면 같은 물체로 본다.
#: 작으면 물체 하나가 여러 개로 쪼개지고, 크면 옆 물체와 붙는다.
CLUSTER_CELL_M = 0.012

#: 이보다 점이 적은 덩어리는 버린다(잡음).
MIN_POINTS = 120

#: 물체로 볼 크기 범위(m). 손이 잡을 수 있는 것만 남긴다 —
#: 근거: superdex/scripts/survey_object_assets.py 의 크기 기준(최소변 4 cm ~ 최대변 16 cm).
#: 여기서는 카메라가 한쪽만 보므로 조금 느슨하게 잡는다.
MIN_SIZE_M = 0.02
MAX_SIZE_M = 0.30


@dataclass
class ObjectCloud:
    """잘라낸 물체 하나."""
    points: np.ndarray          # (N, 3) 카메라 기준 좌표(m)
    center: np.ndarray          # (3,) 가운데
    size: np.ndarray            # (3,) 가로·세로·깊이 크기
    n_points: int

    @property
    def max_side_m(self) -> float:
        return float(self.size.max())

    @property
    def distance_m(self) -> float:
        return float(self.center[2])


def fit_plane(points, tries=PLANE_TRIES, tol=PLANE_TOL_M, seed=0):
    """가장 많은 점이 붙어 있는 **평평한 면**을 찾는다.

    돌려주는 것: `(법선 3개, 상수, 그 면에 붙은 점 표시)`.
    면 위의 점은 `법선·점 + 상수 ≈ 0` 을 만족한다.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return None, None, np.zeros(len(pts), dtype=bool)
    rng = np.random.default_rng(seed)
    best_n, best_d, best_in = None, None, np.zeros(len(pts), dtype=bool)
    # 속도를 위해 일부만 보고 면을 찾는다 — 면을 정하는 데는 이걸로 충분하다
    sample = pts if len(pts) <= 20000 else pts[rng.choice(len(pts), 20000, replace=False)]
    for _ in range(tries):
        idx = rng.choice(len(sample), 3, replace=False)
        a, b, c = sample[idx]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        d = -float(n @ a)
        inliers = np.abs(sample @ n + d) < tol
        if best_in is None or inliers.sum() > best_in.sum():
            best_n, best_d, best_in = n, d, inliers
    if best_n is None:
        return None, None, np.zeros(len(pts), dtype=bool)
    # 정한 면으로 **전체 점**을 다시 판정한다
    return best_n, best_d, np.abs(pts @ best_n + best_d) < tol


def plane_ok(points, inliers, min_frac=PLANE_MIN_FRAC):
    """찾은 면을 **책상으로 믿어도 되나**.

    붙은 점이 너무 적으면 책상이 아니라 우연히 맞은 면일 수 있다. 그때는 빼지 않는다 —
    물체를 통째로 지워 버리는 것보다 배경이 남는 편이 낫다.
    """
    return len(points) > 0 and float(inliers.mean()) >= min_frac


def remove_plane(points, colors=None):
    """책상 면과 **그 뒤쪽(더 먼 쪽)** 을 뺀다.

    면만 빼면 책상 아래·뒤의 점이 남는다. 물체는 책상 **앞쪽(카메라 쪽)** 에 있으므로
    면보다 카메라 쪽에 있는 점만 남긴다.
    """
    pts = np.asarray(points, dtype=np.float64)
    n, d, inl = fit_plane(pts)
    if n is None or not plane_ok(pts, inl):
        return pts, colors, None, "평평한 면을 못 찾았다 — 배경을 그대로 둔다"

    signed = pts @ n + d
    # 점이 많은 쪽이 아니라 **평균이 어느 쪽인가** 로 앞뒤를 정한다
    front = signed > PLANE_TOL_M
    back = signed < -PLANE_TOL_M
    keep = front if front.sum() >= back.sum() else back
    note = "평평한 면 제거 — 붙은 점 {:.0%}, 남긴 점 {:.0%}".format(
        float(inl.mean()), float(keep.mean()))
    return pts[keep], (colors[keep] if colors is not None else None), (n, d), note


def cluster(points, cell=CLUSTER_CELL_M, min_points=MIN_POINTS):
    """서로 붙어 있는 점들을 **덩어리**로 묶는다.

    칸 격자에 점을 넣고, 붙어 있는 칸끼리 이어 붙인다. 학습이 필요 없고 빠르다.
    """
    from scipy import ndimage

    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < min_points:
        return []
    lo = pts.min(axis=0)
    idx = np.floor((pts - lo) / cell).astype(np.int64)
    shape = idx.max(axis=0) + 1
    if np.prod(shape.astype(np.float64)) > 4e7:      # 너무 크면 칸을 키운다
        return cluster(points, cell * 2, min_points)

    grid = np.zeros(shape, dtype=bool)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    labels, n = ndimage.label(grid, structure=np.ones((3, 3, 3), dtype=int))
    per_point = labels[idx[:, 0], idx[:, 1], idx[:, 2]]

    out = []
    for k in range(1, n + 1):
        sel = per_point == k
        if int(sel.sum()) < min_points:
            continue
        p = pts[sel]
        size = p.max(axis=0) - p.min(axis=0)
        if not (MIN_SIZE_M <= float(size.max()) <= MAX_SIZE_M):
            continue
        out.append(ObjectCloud(points=p.astype(np.float32),
                               center=p.mean(axis=0), size=size, n_points=int(sel.sum())))
    out.sort(key=lambda o: -o.n_points)
    return out


def find_objects(points, colors=None, near=None, far=None):
    """점 덩어리 → **물체 목록**. 한 줄로 쓰는 입구.

    돌려주는 것: `(물체 목록, 남은 점, 설명 문구)`
    """
    pts = np.asarray(points, dtype=np.float64)
    near = cfg.D405_NEAR_M if near is None else near
    far = cfg.D405_FAR_M if far is None else far
    sel = (pts[:, 2] >= near) & (pts[:, 2] <= far)
    pts, colors = pts[sel], (colors[sel] if colors is not None else None)
    if len(pts) == 0:
        return [], pts, "그 거리 범위({:.2f}~{:.2f} m) 안에 점이 없다".format(near, far)

    rest, rest_c, plane, note = remove_plane(pts, colors)
    objs = cluster(rest)
    return objs, rest, "{} / 덩어리 {}개".format(note, len(objs))


def describe(objs: List[ObjectCloud]) -> str:
    if not objs:
        return "물체를 못 찾았다"
    lines = []
    for i, o in enumerate(objs[:6]):
        lines.append("  {}번  점 {:6d}개  거리 {:.3f} m  크기 {:.1f}x{:.1f}x{:.1f} cm".format(
            i + 1, o.n_points, o.distance_m, *(o.size * 100)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 눈으로 보기 (원칙 6)
# --------------------------------------------------------------------------
def _to_points(depth_m, intr, color_img=None):
    ys, xs = np.nonzero(depth_m > 0)
    z = depth_m[ys, xs]
    pts = np.stack([(xs - intr.ppx) * z / intr.fx,
                    (ys - intr.ppy) * z / intr.fy, z], axis=1)
    cols = None
    if color_img is not None and color_img.shape[:2] == depth_m.shape:
        cols = color_img[ys, xs]
    return pts, cols, (ys, xs)


#: 물체마다 다른 색으로 칠한다(BGR).
OBJ_COLORS = ((0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255),
              (255, 0, 255), (255, 255, 0))


def main() -> int:
    ap = argparse.ArgumentParser(description="책상·배경을 빼고 물체만 남긴다")
    ap.add_argument("--live", action="store_true", help="실시간 창으로 본다")
    ap.add_argument("--save", action="store_true", help="한 장 찍어 사진·점으로 남긴다")
    ap.add_argument("--near", type=float, default=None)
    ap.add_argument("--far", type=float, default=None)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--cloud", default=None, help="카메라 대신 저장해 둔 npz 로 시험")
    args = ap.parse_args()

    near = cfg.D405_NEAR_M if args.near is None else args.near
    far = cfg.D405_FAR_M if args.far is None else args.far

    # --- 저장된 점으로 시험 (카메라 없이) ---------------------------------
    if args.cloud:
        data = np.load(args.cloud, allow_pickle=True)
        pts = data["points"].astype(np.float64)
        objs, rest, note = find_objects(pts, near=near, far=far)
        print("=== 물체 잘라내기 (저장된 점) ===")
        print("파일: {}  점 {}개".format(args.cloud, len(pts)))
        print(note)
        print(describe(objs))
        return 0

    if not (args.live or args.save):
        print(__doc__)
        return 2

    import cv2
    from view_d405 import colorize, put_lines
    from d405_stream import open_depth

    print("=== 물체 잘라내기 ===")
    print("책상(평평한 면)을 찾아 빼고, 남은 점을 덩어리로 묶는다.")
    print("배운 것이 없으므로 **처음 보는 물체에도 된다.**")
    print("키: q 끝내기 / s 사진 저장")
    print()

    stream = open_depth(args.width, args.height, color=True)
    win = "물체 잘라내기  (왼쪽: 색 사진   오른쪽: 찾은 물체)"
    try:
        while True:
            got, intr = stream.frames(count=1, warmup=2)
            if not got:
                continue
            depth_m, color = got[0]
            pts, cols, (ys, xs) = _to_points(depth_m, intr, None)
            objs, rest, note = find_objects(pts, near=near, far=far)

            # 찾은 물체를 화면에 칠한다 — 어느 점이 어느 물체인지 보이게
            paint = colorize(depth_m, near, far)
            if objs:
                # 각 물체의 점을 화면 좌표로 되돌려 칠한다
                for oi, o in enumerate(objs[:len(OBJ_COLORS)]):
                    px = np.round(o.points[:, 0] * intr.fx / o.points[:, 2] + intr.ppx)
                    py = np.round(o.points[:, 1] * intr.fy / o.points[:, 2] + intr.ppy)
                    ok = ((px >= 0) & (px < depth_m.shape[1])
                          & (py >= 0) & (py < depth_m.shape[0]))
                    paint[py[ok].astype(int), px[ok].astype(int)] = OBJ_COLORS[oi]

            view_c = cv2.resize(color, (640, 480)) if color is not None else np.zeros(
                (480, 640, 3), np.uint8)
            view_o = cv2.resize(paint, (640, 480), interpolation=cv2.INTER_NEAREST)
            view_c = put_lines(view_c, ["색 사진"])
            lines = ["찾은 물체 {}개   ({})".format(len(objs), note)]
            for i, o in enumerate(objs[:4]):
                lines.append("  {}번 {:.1f}x{:.1f}x{:.1f} cm  거리 {:.2f} m  점 {}개".format(
                    i + 1, *(o.size * 100), o.distance_m, o.n_points))
            view_o = put_lines(view_o, lines)
            both = np.hstack([view_c, view_o])

            if args.save:
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "segment_{}.png".format(stamp)), both)
                np.savez_compressed(
                    RESULTS_DIR / "segment_{}.npz".format(stamp),
                    **{"obj{}".format(i): o.points for i, o in enumerate(objs)})
                print(note)
                print(describe(objs))
                print("저장: {}".format(RESULTS_DIR / "segment_{}.png".format(stamp)))
                break

            cv2.imshow(win, both)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "segment_{}.png".format(stamp)), both)
                print("사진 저장 / " + note)
                print(describe(objs))
    finally:
        stream.close()
        try:
            import cv2 as _c
            _c.destroyAllWindows()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
