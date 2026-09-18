# -*- coding: utf-8 -*-
"""**얼마나 빗나가도 여전히 잡히나** — 손목 카메라 장착값의 허용 오차를 정한다.

왜 이 숫자가 필요한가
---------------------
손목 카메라가 팔 끝의 어디에 붙었는지(`D405_MOUNT_*`)를 **틀리게 적으면, 그 틀린 만큼
그대로 손이 엉뚱한 자리로 간다.** 그러면 물어야 할 것은 하나다:

    **몇 mm, 몇 도까지는 틀려도 되는가?**

이 숫자를 모르면 "줄자로 대충 재도 되나" 를 판단할 수 없다. 그래서 잰다.

어떻게 재나
-----------
채점표에서 **확실히 잘 되는 자세**(성공률 100%)를 골라, 일부러 조금씩 **빗나가게** 한 뒤
다시 잡아 본다. 빗나감을 키워 가며 성공률이 언제 무너지는지 본다.

- 위치: 앞뒤(x) / 좌우(y) / 위아래(z) 각각 ± 로 밀어 본다
- 방향: 제자리 회전(yaw) / 눕히기(tilt) 를 ± 로 돌려 본다

⚠️ 이것은 **시뮬레이터 안의 숫자**다. 실물은 더 나쁠 수 있다(물체가 미끄러지고, 카메라
깊이가 흔들리고, 팔에도 오차가 있다). 그러니 여기서 나온 값을 **상한**으로 보고,
실제 목표는 그보다 넉넉하게 잡아야 한다.

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/pose_tolerance_sweep.py --table superdex/results/pose_score_13obj.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401

from pose_score_sweep import OBJECTS, TRAJECTORIES, score_pose  # noqa: E402

RESULTS_DIR = REPO_ROOT / "superdex" / "results"

#: 밀어 볼 거리(mm). 0 은 대조군 — 안 밀었을 때도 정말 되는지 확인한다.
OFFSETS_MM = (0, 2, 5, 8, 12, 20, 30)

#: 돌려 볼 각도(도).
ANGLES_DEG = (0, 2, 5, 10, 20)


def _quat_mul(a, b):
    """쿼터니언 곱 (x, y, z, w). a 를 먼저, 그다음 b."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _quat_axis(axis, rad):
    s = math.sin(rad / 2.0)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(rad / 2.0))


def best_poses(table_path, per_object):
    """물체마다 **확실히 잘 되는 자세**를 몇 개씩 고른다 (성공률 100%, 덜 돌아간 순)."""
    rows = json.loads(Path(table_path).read_text(encoding="utf-8"))["rows"]
    by = defaultdict(list)
    for r in rows:
        if r["rate"] >= 0.99:
            by[r["object"]].append(r)

    def tilt(r):
        v = r.get("tilt_median_deg")
        return 999.0 if v is None else float(v)

    out = {}
    for name, rs in by.items():
        out[name] = sorted(rs, key=tilt)[:per_object]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="빗나감 허용치 재기 (손목 카메라 장착 오차)")
    ap.add_argument("--table", required=True, help="채점표 json")
    ap.add_argument("--per-object", type=int, default=2, help="물체당 시험할 좋은 자세 수")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--objects", default=None, help="쉼표로 고른 물체만 (기본: 표에 있는 전부)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    picks = best_poses(args.table, args.per_object)
    if args.objects:
        want = [n.strip() for n in args.objects.split(",") if n.strip()]
        picks = {k: v for k, v in picks.items() if k in want}
    if not picks:
        print("표에 성공률 100% 자세가 없다.")
        return 2

    # (밀기 6방향 + 안 밀기) × 거리 + (돌리기 4방향) × 각도
    shifts = [("안 밀었을 때", np.zeros(3), None, 0.0)]
    for mm in OFFSETS_MM[1:]:
        d = mm / 1000.0
        for label, vec in (("앞뒤", (1, 0, 0)), ("좌우", (0, 1, 0)), ("위아래", (0, 0, 1))):
            for sign in (+1, -1):
                shifts.append(("{} {:+d}mm".format(label, sign * mm),
                               np.asarray(vec, dtype=float) * d * sign, None, float(mm)))
    turns = []
    for deg in ANGLES_DEG[1:]:
        rad = math.radians(deg)
        for label, axis in (("제자리회전", (0, 0, 1)), ("눕히기", (1, 0, 0))):
            for sign in (+1, -1):
                turns.append(("{} {:+d}도".format(label, sign * deg),
                              np.zeros(3), _quat_axis(axis, rad * sign), float(deg)))

    total = sum(len(v) for v in picks.values()) * (len(shifts) + len(turns))
    print("=== 빗나감 허용치 재기 ===")
    print("채점표   : {}".format(args.table))
    print("물체 {}종 × 좋은 자세 {}개 × 빗나감 {}가지 = {}칸".format(
        len(picks), args.per_object, len(shifts) + len(turns), total))
    print("칸마다 {}번씩 잡아 본다".format(args.seeds * len(TRAJECTORIES)))
    print()

    from dg5f_grasp_env import Dg5fGraspEnv
    from gate2_oracle_search import run_trajectory

    # 빗나감 크기 -> 성공률들
    by_shift = defaultdict(list)
    by_turn = defaultdict(list)
    rows = []
    t0 = time.perf_counter()
    done = 0

    for name, poses in picks.items():
        prefab, actor, ref = OBJECTS[name]
        config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0}
        if actor:
            config["object_actor"] = actor
        env = Dg5fGraspEnv(config)
        try:
            print("[{}]".format(name), flush=True)
            for base in poses:
                base_place = np.asarray(base["place"], dtype=float)
                base_rot = tuple(base["place_rot"])
                for label, shift, turn, size in shifts + turns:
                    pose = {"place": (base_place + shift).tolist(),
                            "place_rot": list(_quat_mul(base_rot, turn) if turn else base_rot),
                            "rot_name": base["rot_name"]}
                    got = score_pose(env, pose, args.seeds, args.seed0, run_trajectory)
                    rows.append(dict(object=name, base_rot=base["rot_name"],
                                     shift=label, size=size, **got))
                    (by_turn if turn else by_shift)[size].append(got["rate"])
                    done += 1
                print("   자세 {} 끝 — {}/{}".format(base["rot_name"], done, total), flush=True)
        finally:
            env.close()
            try:
                import superdex.physics as physics
                physics.destroy_scene(env.scene)
            except Exception:
                pass

    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / "pose_tolerance_{}.json".format(time.strftime("%Y%m%d_%H%M%S")))
    out_path.write_text(json.dumps({
        "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "from_table": str(args.table), "seeds": args.seeds, "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 62)
    print("**얼마나 밀려도 잡히나** (원래 100% 되던 자세 기준)")
    print("-" * 62)
    base_rate = float(np.mean(by_shift.get(0.0, [1.0]))) if 0.0 in by_shift else 1.0
    for mm in OFFSETS_MM:
        vals = by_shift.get(float(mm))
        if not vals:
            continue
        keep = float(np.mean([v >= 0.99 for v in vals]))
        print("  {:2d} mm 밀면  →  여전히 100% 성공하는 자세 {:3.0f}%   (평균 성공률 {:.0%})".format(
            mm, 100 * keep, float(np.mean(vals))))
    print()
    print("**얼마나 돌아가도 잡히나**")
    print("-" * 62)
    for deg in ANGLES_DEG[1:]:
        vals = by_turn.get(float(deg))
        if not vals:
            continue
        keep = float(np.mean([v >= 0.99 for v in vals]))
        print("  {:2d} 도 돌리면 →  여전히 100% 성공하는 자세 {:3.0f}%   (평균 성공률 {:.0%})".format(
            deg, 100 * keep, float(np.mean(vals))))
    print()
    print("⚠️ 시뮬레이터 안의 숫자다. 실물은 더 나쁠 수 있으니 목표는 더 빡빡하게 잡는다.")
    print("저장: {}  ({:.0f}초)".format(out_path, time.perf_counter() - t0))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
