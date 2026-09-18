# -*- coding: utf-8 -*-
"""**시뮬레이터가 만든 점 덩어리가 실물과 비슷한가** — 이 길의 최대 미검증 항목.

왜 이게 제일 중요한가
---------------------
예측기(D-4)는 **시뮬레이터가 만든 가짜 점 덩어리**로만 배웠다. 실물 카메라 점이
그것과 많이 다르면, 시뮬에서 아무리 잘 돼도 **실물에서 그대로 못 쓴다.**
`docs/FESTA_PREGRASP_PLAN.md` 가 D-3 을 "이 길의 최대 미검증 항목" 이라 적은 이유다.

무엇을 견주나 — 예측기가 실제로 보는 것만
------------------------------------------
예측기는 점 좌표만 본다(§7-3). 그러니 견줄 것도 **점의 성질**뿐이다:

=====================  ==============================================
재는 것                 왜
=====================  ==============================================
점 개수                 너무 다르면 뽑아 쓰는 256개의 성격이 달라진다
물체 크기               같은 물체인데 크기가 다르면 좌표가 안 맞는다
점 촘촘한 정도           듬성듬성한지 빽빽한지
표면에서 튀는 정도       실물에는 잡음이 있고 시뮬에는 없다 ← **가장 다를 곳**
한쪽만 보이는 정도       둘 다 한 방향에서만 봤나
=====================  ==============================================

⚠️ **"많이 다르다" 가 곧 "틀렸다" 는 아니다.** 예를 들어 실물이 더 촘촘한 것은
   문제가 아니다(어차피 256개만 뽑아 쓴다). 반대로 **실물에만 잡음이 있는 것**은
   문제다 — 시뮬에서 배운 것이 매끈한 표면만 알기 때문이다.
   그래서 항목마다 **"이건 괜찮다 / 이건 고쳐야 한다"** 를 같이 적는다.

돌리는 법
---------
1) 실물 점 먼저 만든다 — 물체 하나를 카메라 앞 20 cm 에 두고
   터미널 1 (PowerShell, 리포 루트):

       vision/.vision/Scripts/Activate.ps1
       python vision/d405/segment_objects.py --save --near 0.09 --far 0.40

2) 견준다:

       python vision/d405/compare_real_vs_sim.py \
           --real vision/d405/results/segment_<시각>.npz \
           --sim  superdex/results/pose_dataset_18obj.npz
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402,F401

#: 표면에서 얼마나 튀는지 잴 때, 한 점 둘레에서 몇 개를 보고 면을 맞출지.
NEIGHBORS = 12


def roughness_mm(points, k=NEIGHBORS, sample=2000, seed=0):
    """**표면에서 얼마나 튀나** (mm). 작을수록 매끈하다.

    점 하나 둘레의 이웃 `k` 개로 작은 면을 맞추고, 그 면에서 얼마나 벗어나는지 본다.
    시뮬레이터 점은 삼각형 면 위에 정확히 얹히므로 0에 가깝고, 실물은 잡음만큼 뜬다.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < k + 1:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pts), min(sample, len(pts)), replace=False)
    out = []
    for i in idx:
        d = np.linalg.norm(pts - pts[i], axis=1)
        near = pts[np.argsort(d)[1:k + 1]]
        if len(near) < 3:
            continue
        c = near.mean(axis=0)
        # 가장 평평한 방향(가장 작은 퍼짐)을 면의 법선으로 본다
        _, _, vt = np.linalg.svd(near - c, full_matrices=False)
        out.append(abs(float((pts[i] - c) @ vt[-1])))
    return float(np.median(out) * 1000.0) if out else float("nan")


def spacing_mm(points, sample=2000, seed=0):
    """이웃한 점끼리 **얼마나 떨어져 있나** (mm). 촘촘한 정도."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pts), min(sample, len(pts)), replace=False)
    out = []
    for i in idx:
        d = np.linalg.norm(pts - pts[i], axis=1)
        d.sort()
        out.append(d[1])
    return float(np.median(out) * 1000.0)


def one_sided(points, k=NEIGHBORS, sample=1500, seed=0):
    """**한 방향에서만 봤나** — 1에 가까울수록 한쪽만, 0에 가까울수록 사방에서 봤다.

    각 점에서 **면이 바라보는 방향**(법선)을 구해 모아 평균낸다. 한 방향에서만 찍었으면
    모든 면이 카메라 쪽을 보므로 방향이 한데 모여 1에 가깝고, 물체를 빙 둘러 찍었으면
    서로 상쇄돼 0에 가깝다.

    ⚠️ 처음에는 "가운데에서 점까지의 방향" 을 평균냈는데 **그건 한쪽만 봤는지를 못
    잰다** — 면이 대칭이기만 하면 어느 쪽에서 봤든 0에 가깝게 나온다(2026-09-18 발견).
    법선을 봐야 한다.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < k + 1:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pts), min(sample, len(pts)), replace=False)
    normals = []
    center = pts.mean(axis=0)
    for i in idx:
        d = np.linalg.norm(pts - pts[i], axis=1)
        near = pts[np.argsort(d)[1:k + 1]]
        if len(near) < 3:
            continue
        _, _, vt = np.linalg.svd(near - near.mean(axis=0), full_matrices=False)
        nvec = vt[-1]
        # 법선 방향은 부호가 둘 다 가능하다 — **바깥쪽**(가운데 반대)으로 맞춰 준다
        if nvec @ (pts[i] - center) < 0:
            nvec = -nvec
        normals.append(nvec)
    if not normals:
        return float("nan")
    return float(np.linalg.norm(np.mean(normals, axis=0)))


def summarize(points, label):
    pts = np.asarray(points, dtype=np.float64)
    size = pts.max(axis=0) - pts.min(axis=0)
    return dict(label=label, n=len(pts), size_cm=size * 100,
                span_cm=float(np.linalg.norm(size)) * 100,
                spacing_mm=spacing_mm(pts), rough_mm=roughness_mm(pts),
                one_sided=one_sided(pts))


def load_real(path):
    """`segment_objects.py --save` 가 남긴 물체들."""
    d = np.load(path, allow_pickle=True)
    out = []
    for k in d.files:
        if k.startswith("obj"):
            out.append((k, d[k].astype(np.float64)))
    return out


def load_sim(path, limit=None):
    """`build_pose_dataset.py` 가 남긴 점 덩어리들 (물체 기준 좌표)."""
    d = np.load(path, allow_pickle=True)
    pts = d["points"].astype(np.float64)
    start = d["cloud_start"]
    names = [str(v) for v in d["cloud_object"]]
    out = []
    seen = set()
    for i, name in enumerate(names):
        if name in seen:            # 물체마다 한 장만 — 방향만 다른 같은 물체다
            continue
        seen.add(name)
        out.append((name, pts[start[i]:start[i + 1]]))
        if limit and len(out) >= limit:
            break
    return out


def verdict(real, sim):
    """항목마다 **괜찮은가 고쳐야 하나**. 다르다고 무조건 문제는 아니다."""
    lines = []

    def row(name, r, s, ok, why):
        mark = "괜찮다" if ok else "**확인 필요**"
        lines.append("  {:<16s} 실물 {:>9s}   시뮬 {:>9s}   {}  — {}".format(
            name, r, s, mark, why))

    rn, sn = np.median([x["n"] for x in real]), np.median([x["n"] for x in sim])
    row("점 개수", "{:.0f}".format(rn), "{:.0f}".format(sn), True,
        "어차피 256개만 뽑아 쓰므로 개수 차이는 문제가 아니다")

    rs, ss = np.median([x["span_cm"] for x in real]), np.median([x["span_cm"] for x in sim])
    row("물체 크기(cm)", "{:.1f}".format(rs), "{:.1f}".format(ss),
        abs(rs - ss) < max(rs, ss) * 0.6,
        "같은 물체를 견준 게 아니면 달라도 된다. 자릿수가 다르면 단위를 의심")

    rp, sp = np.median([x["spacing_mm"] for x in real]), np.median([x["spacing_mm"] for x in sim])
    row("점 간격(mm)", "{:.2f}".format(rp), "{:.2f}".format(sp), True,
        "촘촘함 차이는 뽑아 쓸 때 맞춰진다")

    rr, sr = np.median([x["rough_mm"] for x in real]), np.median([x["rough_mm"] for x in sim])
    ok = rr < max(1.0, sr * 3 + 0.5)
    row("표면 잡음(mm)", "{:.2f}".format(rr), "{:.2f}".format(sr), ok,
        "**여기가 핵심.** 실물에만 잡음이 크면 시뮬에서 배운 것이 매끈한 면만 알게 된다")

    ro, so = np.median([x["one_sided"] for x in real]), np.median([x["one_sided"] for x in sim])
    row("한쪽만 보임", "{:.2f}".format(ro), "{:.2f}".format(so), abs(ro - so) < 0.35,
        "둘 다 한 방향에서만 봐야 한다(1에 가까울수록 한쪽). 크게 다르면 학습 입력이 다르다")

    return lines, dict(rough_real=rr, rough_sim=sr)


def main() -> int:
    ap = argparse.ArgumentParser(description="실물 점 덩어리 vs 시뮬레이터 점 덩어리")
    ap.add_argument("--real", required=True, help="segment_objects.py --save 가 만든 npz")
    ap.add_argument("--sim", required=True, help="build_pose_dataset.py 가 만든 npz")
    ap.add_argument("--sim-limit", type=int, default=8)
    args = ap.parse_args()

    real_clouds = load_real(args.real)
    sim_clouds = load_sim(args.sim, args.sim_limit)
    if not real_clouds:
        print("실물 파일에 물체가 없다: {}".format(args.real))
        return 2
    if not sim_clouds:
        print("시뮬 파일에 점 덩어리가 없다: {}".format(args.sim))
        return 2

    print("=== 실물 vs 시뮬레이터 점 덩어리 ===")
    print("실물: {} (물체 {}개)".format(args.real, len(real_clouds)))
    print("시뮬: {} (물체 {}개)".format(args.sim, len(sim_clouds)))
    print()

    real = [summarize(p, n) for n, p in real_clouds]
    sim = [summarize(p, n) for n, p in sim_clouds]

    for title, group in (("실물", real), ("시뮬레이터", sim)):
        print("[{}]".format(title))
        print("  {:<14s} {:>7s} {:>9s} {:>10s} {:>11s} {:>10s}".format(
            "물체", "점수", "크기cm", "점간격mm", "표면잡음mm", "한쪽만"))
        for x in group:
            print("  {:<14s} {:>7d} {:>9.1f} {:>10.2f} {:>11.2f} {:>10.2f}".format(
                x["label"][:14], x["n"], x["span_cm"], x["spacing_mm"],
                x["rough_mm"], x["one_sided"]))
        print()

    lines, got = verdict(real, sim)
    print("=" * 78)
    print("**견주기** (다르다고 무조건 문제는 아니다 — 항목마다 따로 본다)")
    print("-" * 78)
    for ln in lines:
        print(ln)
    print()
    if got["rough_real"] > max(1.0, got["rough_sim"] * 3 + 0.5):
        print("👉 실물 표면 잡음이 시뮬보다 크게 높다. 다음 중 하나를 해야 한다:")
        print("   ① 시뮬레이터 점에 **같은 크기의 잡음을 섞어** 학습시킨다 (권장 — 싸다)")
        print("   ② 실물 점을 더 다듬는다 (이미 다듬기는 켜 둔 상태다)")
    else:
        print("👉 표면 잡음은 비슷한 수준이다 — 시뮬에서 배운 것이 실물에서도 통할 만하다.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
