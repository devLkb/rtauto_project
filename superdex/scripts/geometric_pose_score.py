# -*- coding: utf-8 -*-
"""**계산으로만** 자세를 채점한다 — 학습한 것과 견주기 위한 상대 (계약 R3, 계획서 §8).

왜 이게 필요한가
----------------
계획서 §8 의 첫 번째 합격 기준이 **"계산 방식보다 나은가"** 다. 배운 것이 아무리 그럴듯해
보여도, **사람이 손으로 짠 단순한 규칙보다 못하면 값어치가 없다.** 그래서 같은 재료·같은
채점 방식으로 돌리는 상대를 만든다.

- 이기면 → 배우는 방향이 맞다는 근거가 된다
- 지면  → 지금 학습은 접고 이 규칙을 쓰면 된다

규칙 — 딱 두 가지만 본다
------------------------
**"파지 중심에 물체가 있고, 그 부분이 손에 들어갈 만큼 작으면 좋은 자세."**

    점수 = (파지할 공 안에 든 점의 비율) − (파지 중심에서 물체 중심까지 거리 ÷ 파지 반경)

앞 항은 "손 안에 물체가 있나", 뒤 항은 "가운데에 잘 놓였나" 다. 맞출 손잡이를 늘리면
슬그머니 학습이 되어 버리므로 **두 항에서 더 늘리지 않는다.**

입력은 학습한 쪽과 **똑같다** — 점 덩어리와 자세 후보뿐이다(§7-3). 시뮬레이터만 아는
값은 안 쓴다. 그래야 공정한 비교다.

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python superdex/scripts/geometric_pose_score.py --data superdex/results/pose_dataset_13obj.npz
"""
from __future__ import annotations

import argparse
import sys
from math import comb
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402

# ---------------------------------------------------------------------------
# 손의 생김새 — **실측값이다**(2026-09-18, 시뮬레이터 안에서 직접 재서 얻음).
# 재는 법: 손을 완전히 벌린 상태와 완전히 오므린 상태에서 손끝 5개의 위치를
#          손바닥 좌표계로 읽었다. 짐작한 값이 아니다.
#
#   손바닥 기준 축
#     z = 손가락이 앞으로 뻗는 방향 (벌리면 손끝 z=0.20 m, 오므리면 z=0.04 m)
#     x = 손바닥이 바라보는 쪽      (오므리면 손끝이 x=0.013 -> 0.06 m 로 감긴다)
#     y = 엄지 <-> 새끼 방향
#
#   벌림 폭(손끝끼리 최대 거리) 0.232 m / 오므렸을 때 0.089 m
# ---------------------------------------------------------------------------

#: 오므렸을 때 손끝 5개와 손바닥이 둘러싸는 자리. 물체가 여기 있어야 잡힌다.
GRASP_CENTER_PALM = np.array([0.0356, 0.0007, 0.0426])

#: 그 자리를 감싸는 공의 반지름(m). 오므렸을 때 손끝끼리 최대 거리 0.089 m 의 절반.
GRASP_RADIUS_M = 0.0447


def _quat_to_matrix(q):
    """쿼터니언 (x, y, z, w) → 3x3."""
    x, y, z, w = [float(v) for v in q]
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def score_pose(points_obj, palm_pos, palm_quat):
    """자세 하나를 계산으로 채점한다. 높을수록 좋은 자세.

    `points_obj` 는 물체 기준 점 덩어리, `palm_pos`/`palm_quat` 는 물체 기준 손바닥 자세.
    """
    rot = _quat_to_matrix(palm_quat)
    # 물체 기준 점 -> 손바닥 기준 점
    pts = (np.asarray(points_obj, dtype=float) - np.asarray(palm_pos, dtype=float)) @ rot
    if len(pts) == 0:
        return -1.0

    d = np.linalg.norm(pts - GRASP_CENTER_PALM, axis=1)
    inside = float(np.mean(d <= GRASP_RADIUS_M))          # 손 안에 든 점의 비율
    off = float(np.linalg.norm(pts.mean(0) - GRASP_CENTER_PALM)) / GRASP_RADIUS_M
    return inside - off


#: ⚠️ **좋은 자세가 0개인 물체는 채점에서 뺀다.** 어떤 방법을 써도 무조건 실패라서
#: 평균만 깎고 방법끼리의 차이를 가리지 못한다. 대신 **몇 종이 그랬는지 따로 적는다** —
#: 숨기는 것이 아니라 "이 물체는 지금 기준으로는 아예 못 잡는다" 는 별개의 사실이다.
#: (2026-09-18: sphere 는 둥글어 손 안에서 구르고, duck_lamp 는 물렁해 전부 5도를 넘었다)


def load(path):
    data = np.load(path, allow_pickle=True)
    pts = data["points"].astype(np.float64)
    start = data["cloud_start"]
    cloud_obj = [str(v) for v in data["cloud_object"]]
    clouds = {}
    for i, name in enumerate(cloud_obj):
        clouds.setdefault(name, []).append(pts[start[i]:start[i + 1]])
    rate = data["pose_rate"].astype(np.float64)
    tilt = (data["pose_tilt"].astype(np.float64) if "pose_tilt" in data.files
            else np.zeros_like(rate))
    return (clouds, data["pose_pos"].astype(np.float64),
            data["pose_quat"].astype(np.float64), rate, tilt,
            [str(v) for v in data["pose_object"]])


def main() -> int:
    ap = argparse.ArgumentParser(description="계산으로만 자세 채점 (학습한 것의 상대)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--good-rate", type=float, default=0.99)
    ap.add_argument("--max-tilt", type=float, default=cfg.GRASP_GOOD_TILT_DEG)
    args = ap.parse_args()

    clouds, pose_pos, pose_quat, rate, tilt, pose_obj = load(args.data)
    objects = list(dict.fromkeys(pose_obj))

    print("=== 계산으로만 자세 채점 (학습한 것의 상대) ===")
    print("데이터   : {}".format(args.data))
    print("규칙     : 파지할 공 안에 든 점의 비율 − 파지 중심에서 물체 중심까지 거리")
    print("입력     : 점 덩어리 + 자세 후보 — 학습한 쪽과 **똑같다** (§7-3)")
    print("좋은 자세: 잡히고(성공률 {:.0%} 이상) 그리고 잡은 뒤 {:.0f}도 이하로 돌아간 것".format(
        args.good_rate, args.max_tilt))
    print()

    hit1, hit3, chance1, chance3 = [], [], [], []
    impossible = []
    for name in objects:
        idx = [k for k, o in enumerate(pose_obj) if o == name]
        label = np.array([1.0 if (rate[k] >= args.good_rate and tilt[k] <= args.max_tilt)
                          else 0.0 for k in idx])
        # 같은 자세를 점 덩어리 여러 장으로 채점해 평균낸다 — 학습한 쪽과 같은 방식
        scores = np.array([
            float(np.mean([score_pose(c, pose_pos[k], pose_quat[k])
                           for c in clouds.get(name, [])]))
            for k in idx])
        order = np.argsort(-scores)
        top1 = float(label[order[0]] >= 0.5)
        top3 = float(label[order[:3]].max() >= 0.5)
        n, g = len(idx), int(label.sum())
        if g == 0:
            impossible.append(name)
            print("  [{:<12s}] — 좋은 자세가 0개라 채점에서 뺀다 (후보 {}개)".format(name, n))
            continue
        c1 = g / n
        c3 = 1.0 - (comb(n - g, 3) / comb(n, 3) if n - g >= 3 else 0.0)
        hit1.append(top1)
        hit3.append(top3)
        chance1.append(c1)
        chance3.append(c3)
        print("  [{:<12s}] 1등 {} / 3등 안 {}   (후보 {}개 중 좋은 자세 {}개)".format(
            name, "O" if top1 else "X", "O" if top3 else "X", n, g))

    print()
    print("=" * 70)
    print("**계산 규칙** — 후보를 다 매기고 위에서 고르기")
    print("  1등으로 고른 자세가 좋았던 물체: {:.0%} ({}종 중 {}종)".format(
        np.mean(hit1), len(hit1), int(sum(hit1))))
    print("  3등 안에 좋은 자세가 있던 물체 : {:.0%} ({}종 중 {}종)".format(
        np.mean(hit3), len(hit3), int(sum(hit3))))
    print("  아무거나 1개 찍기              : {:.0%}".format(np.mean(chance1)))
    print("  아무거나 3개 찍기              : {:.0%}".format(np.mean(chance3)))
    if impossible:
        print()
        print("  ⚠️ 좋은 자세가 0개라 뺀 물체 {}종: {}".format(
            len(impossible), ", ".join(impossible)))
        print("     (지금 기준 — 잡히고 **그리고** 5도 이하로만 돌아가는 자세 — 으로는")
        print("      이 물체들을 아예 못 잡는다. 어떤 방법을 써도 실패다)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
