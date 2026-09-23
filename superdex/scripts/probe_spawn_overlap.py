# -*- coding: utf-8 -*-
"""물체가 **처음 놓일 때부터 손과 겹쳐 있는지** 잰다 (B-8, 2026-09-23).

가설: 채점표(D-2)의 자리 격자 중 일부는 물체를 손바닥 속에 박힌 채로 시작시킨다. 그러면 쥐기
전부터 시뮬레이터가 둘을 떼어 놓으려고 수천 N 을 내고, 이것이 "손끝 아닌 곳 수천 N" 과
"유지 중 물체 속도 0.7 m/s" 의 원인일 수 있다.

방법: 손을 **편 채로(쥐지 않고)** 몇 스텝 돌리며 손 전 부위 접촉력을 잰다. 편 손에서 힘이 크면
쥐기와 상관없이 처음부터 겹친 것이다.

실행 (터미널 1, PowerShell, 리포 루트)::

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/probe_spawn_overlap.py
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--objects", default="paper_cup,block_red,sphere,fdt_peg,shapebox_body,star")
    ap.add_argument("--xs", default="0.03,0.05,0.07,0.09")
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--seed", type=int, default=9000)
    ap.add_argument("--table", default=None,
                    help="채점표 JSON 을 주면 그 표의 **모든 행**을 편 손으로 검사해 '처음부터 겹침' 을 센다")
    ap.add_argument("--exclude", default="duck_lamp")
    ap.add_argument("--overlap-n", type=float, default=1.0,
                    help="편 손에서 이 힘[N]을 넘으면 처음부터 겹친 것으로 본다")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv
    from pose_score_sweep import OBJECTS
    from audit_grasp_forces import link_actors

    def open_hand_force(env, actors, place, quat):
        env.place = np.asarray(place, dtype=float)
        env.place_rot = np.asarray(quat, dtype=float)
        env.reset(seed=args.seed)
        worst, worst_link = 0.0, ""
        for _ in range(args.steps):
            env.step(env._pose_at(0.0).astype(np.float32))
            for n, a in actors.items():
                try:
                    f = float(np.linalg.norm(np.asarray(
                        env.block.get_contact_force_from_actor_world(a), dtype=float)))
                except Exception:
                    f = 0.0
                if f > worst:
                    worst, worst_link = f, n
        return worst, worst_link

    if args.table:
        import json
        import time
        tp = Path(args.table)
        table = json.loads(tp.read_text(encoding="utf-8"))
        exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
        rows = [r for r in table["rows"] if r["object"] not in exclude]
        out = []
        for obj in dict.fromkeys(r["object"] for r in rows):
            prefab, actor, ref = OBJECTS[obj]
            config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0,
                      "episode_seconds": 1.0}
            if actor:
                config["object_actor"] = actor
            env = Dg5fGraspEnv(config)
            try:
                actors, _ = link_actors(env)
                for r in (r for r in rows if r["object"] == obj):
                    f, link = open_hand_force(env, actors, r["place"], r["place_rot"])
                    out.append(dict(object=obj, place=r["place"], rot_name=r["rot_name"],
                                    rate=r.get("rate", 0.0), open_hand_force=f, link=link,
                                    overlap=f > args.overlap_n))
            finally:
                env.close()
            s = [o for o in out if o["object"] == obj]
            ok = [o for o in s if o["rate"] >= 1.0]
            print(f"  {obj:>14s}: 전체 {len(s)}줄 중 겹침 {sum(o['overlap'] for o in s)}  |  "
                  f"성공률 100% {len(ok)}줄 중 겹침 {sum(o['overlap'] for o in ok)}", flush=True)
        ok = [o for o in out if o["rate"] >= 1.0]
        print(f"\n=== 합계: 전체 {len(out)}줄 중 처음부터 겹침 {sum(o['overlap'] for o in out)}줄  |  "
              f"'성공률 100%' {len(ok)}줄 중 겹침 {sum(o['overlap'] for o in ok)}줄 ===")
        res = REPO_ROOT / "superdex" / "results"
        res.mkdir(parents=True, exist_ok=True)
        p = res / f"spawn_overlap_{time.strftime('%Y%m%d_%H%M%S')}.json"
        p.write_text(json.dumps({"table": tp.name, "overlap_n": args.overlap_n, "steps": args.steps,
                                 "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p}")
        return 0

    xs = [float(v) for v in args.xs.split(",")]
    print(f"편 손으로 {args.steps} 스텝 — 각 칸: 손 전 부위 접촉력 최대 N (최악 부위)")
    print("물체".ljust(15) + "".join(f"x={x:.2f}".rjust(24) for x in xs))
    for obj in [o.strip() for o in args.objects.split(",") if o.strip()]:
        prefab, actor, ref = OBJECTS[obj]
        config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0, "episode_seconds": 1.0}
        if actor:
            config["object_actor"] = actor
        env = Dg5fGraspEnv(config)
        line = obj.ljust(15)
        try:
            actors, _kind = link_actors(env)
            for x in xs:
                env.place = np.array([x, 0.0, 0.03])
                env.place_rot = np.array([0.0, 0.0, 0.0, 1.0])
                env.reset(seed=args.seed)
                worst, worst_link = 0.0, ""
                for _ in range(args.steps):
                    env.step(env._pose_at(0.0).astype(np.float32))      # 편 손 그대로
                    for n, a in actors.items():
                        try:
                            f = float(np.linalg.norm(np.asarray(
                                env.block.get_contact_force_from_actor_world(a), dtype=float)))
                        except Exception:
                            f = 0.0
                        if f > worst:
                            worst, worst_link = f, n
                line += f"{worst:9.1f} ({worst_link.replace('dg5f_link_', '')[:10]:>10s})".rjust(24)
        finally:
            env.close()
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
