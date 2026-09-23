# -*- coding: utf-8 -*-
"""SuperDex 관절 추종 상한(`joint_saturation`)이 **쥐는 힘을 실제로 묶는지** 재는 실험 (B-8, 2026-09-23).

질문: 실물 손은 관절 힘에 한계가 있어(정격 0.4 N·m / 최대 2 N·m) 물체를 수천 N 으로 누를 수 없다.
시뮬레이터는 지금 관절을 "용수철 세기(stiffness)"로만 움직이고 힘 한계가 없다. `saturation` 을 걸면
(1) 쥐는 힘이 줄어드나, (2) 그래도 잡히나, (3) 끼어서 생기는 수천 N 은 사라지나 — 를 본다.

실행 (터미널 1, PowerShell, 리포 루트)::

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/probe_joint_saturation.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401

#: 실험 자세: (물체, 자리, 방향 이름, 방향 쿼터니언). 채점표에서 "성공"인데 끼임이 보인 것 + 작은 블록.
CASES = [
    ("paper_cup", [0.03, 0.0, 0.03], "yaw+0", [0.0, 0.0, 0.0, 1.0]),
    ("block_red", [0.03, 0.0, 0.03], "yaw+0", [0.0, 0.0, 0.0, 1.0]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sats", default="-1,1.0,0.3,0.1,0.03,0.01")
    ap.add_argument("--seed", type=int, default=9000)
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv
    from pose_score_sweep import OBJECTS, TRAJECTORIES
    from audit_grasp_forces import link_actors, run_trial

    sats = [float(s) for s in args.sats.split(",")]
    for obj, place, rot_name, quat in CASES:
        prefab, actor, ref = OBJECTS[obj]
        print(f"\n=== {obj} {rot_name} {place} — 쥐기 동작 {TRAJECTORIES[0]} ===")
        print(f"{'saturation':>10s} {'성공':>4s} {'손끝최대':>9s} {'손끝마지막':>10s} "
              f"{'손끝아닌곳마지막':>14s} {'최악 부위':>16s} {'유지중 속도':>10s}")
        for sat in sats:
            config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0,
                      "episode_seconds": 1.0, "joint_saturation": sat}
            if actor:
                config["object_actor"] = actor
            env = Dg5fGraspEnv(config)
            try:
                env.place = np.asarray(place, dtype=float)
                env.place_rot = np.asarray(quat, dtype=float)
                actors, kind = link_actors(env)
                t = run_trial(env, args.seed, *TRAJECTORIES[0], actors, kind)
            finally:
                env.close()
            print(f"{sat:>10g} {('예' if t['success'] else '아니오'):>4s} {t['peak']['tip']:9.1f} "
                  f"{t['last']['tip']:10.1f} {max(t['last']['finger'], t['last']['other']):14.1f} "
                  f"{t['worst_link'][-16:]:>16s} {t['hold_speed_max']:10.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
