# -*- coding: utf-8 -*-
"""채점표(D-2)에서 **"성공"으로 적힌 자세들이 정말 잡은 것인지** 손의 모든 부위 힘으로 검사한다 (B-8).

왜 (2026-09-22 사용자 발견 → 2026-09-23 이 도구):
  채점표 `pose_score_*.json` 의 성공 판정(`is_success`)은 **손끝 5곳의 접촉 수**만 본다.
  손끝이 아닌 관절에 물체가 끼어서 버텨도 "성공"이 된다. 종이컵 옆 자세 하나에서는
  손끝 아닌 관절에 마지막까지 수백~수천 N 이 걸려 있었다(`diagnose_wedge_contact.py`).
  이 도구는 그게 **채점표 전체에 얼마나 퍼져 있는지** 센다.

무엇이 다른가 — `diagnose_wedge_contact.py` 는 **학습된 정책**으로 돌렸지만, 채점표는
**정해진 쥐기 동작**(`pose_score_sweep.TRAJECTORIES`)으로 매겼다. 여기서는 채점표와 **같은 동작·
같은 환경 설정**으로 다시 돌리며, 매 스텝 손의 **모든 링크**에 걸린 접촉력을 잰다.

판단에 쓰는 실물 기준 (docs/modules/DG5F_JOINT_RANGES.md §7, 제조사 설명서 12쪽):
  손가락 끝 최대 힘 97 N. 실제 손은 어느 부위로도 이보다 세게 누를 수 없다 — 시뮬레이터에서
  이보다 큰 힘은 손이 누른 것이 아니라 **물체가 손가락을 파고든 계산 오류**로 본다.

실행 (터미널 1, PowerShell, 리포 루트)::

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/audit_grasp_forces.py --per-object 3 --seeds 2

결과: `superdex/results/audit_grasp_forces_<시각>.json` + 터미널 요약.
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
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401  (환경이 asset 경로를 여기서 읽는다)

RESULTS_DIR = REPO_ROOT / "superdex" / "results"

#: 실물 손끝 최대 힘[N] — 이보다 큰 접촉력은 실물로는 나올 수 없다(위 설명).
HAND_MAX_FORCE_N = 97.0
#: 이 힘[N] 이상이면 "그 부위가 물체를 떠받친다" 로 본다(diagnose_wedge_contact 와 같은 기준).
TOUCH_N = 0.05


def pick_rows(table, per_object, exclude):
    """채점표에서 성공률 100% 행을 물체마다 고르게 per_object 개씩 고른다."""
    by = {}
    for r in table["rows"]:
        if r.get("rate", 0) >= 1.0 and r["object"] not in exclude:
            by.setdefault(r["object"], []).append(r)
    out = []
    for obj, rs in by.items():
        idx = np.linspace(0, len(rs) - 1, min(per_object, len(rs))).round().astype(int)
        out.extend(rs[i] for i in sorted(set(idx)))
    return out


def link_actors(env):
    """손·팔의 모든 링크 actor 를 (짧은 이름 → actor) 로. 손끝/손가락 관절/그 밖으로 나눈다."""
    from dg5f_grasp_env import TIP_LINKS
    bot = env.bot.get_name()
    by = {}
    for h in env.actor.get_nested_link_actors():
        a = env.scene.get_actor(h)
        n = a.get_name()
        by[n[len(bot) + 1:] if n.startswith(bot + "/") else n] = a
    tips = set(TIP_LINKS)
    kind = {}
    for n in by:
        if n in tips:
            kind[n] = "tip"
        elif n.startswith("dg5f_link_") and n.split("_")[-1] in ("1", "2", "3", "4"):
            kind[n] = "finger"
        else:
            kind[n] = "other"      # 손바닥·팔 등
    return by, kind


def run_trial(env, seed, final_frac, ramp_steps, hold_frac, actors, kind):
    """채점표와 같은 쥐기 동작(gate2_oracle_search.run_trajectory)을 돌리며 힘을 잰다."""
    env.reset(seed=seed)
    info, best_tips = {}, 0
    peak = {"tip": 0.0, "finger": 0.0, "other": 0.0}
    hold_peak = {"tip": 0.0, "finger": 0.0, "other": 0.0}
    last = {"tip": 0.0, "finger": 0.0, "other": 0.0}
    worst_link, worst_f = "", 0.0
    hold_speed = []
    for t in range(env.max_steps):
        frac = final_frac * (t + 1) / ramp_steps if t < ramp_steps else hold_frac
        _, _, term, trunc, info = env.step(env._pose_at(frac).astype(np.float32))
        best_tips = max(best_tips, info.get("tips_touching", 0))
        now = {"tip": 0.0, "finger": 0.0, "other": 0.0}
        for n, a in actors.items():
            try:
                f = float(np.linalg.norm(np.asarray(
                    env.block.get_contact_force_from_actor_world(a), dtype=float)))
            except Exception:
                f = 0.0
            k = kind[n]
            now[k] = max(now[k], f)
            if f > worst_f:
                worst_f, worst_link = f, n
        for k in now:
            peak[k] = max(peak[k], now[k])
            if t >= ramp_steps:
                hold_peak[k] = max(hold_peak[k], now[k])
        last = now
        if t >= ramp_steps:
            hold_speed.append(float(np.linalg.norm(np.asarray(env.block.get_linear_velocity(), dtype=float))))
        if term or trunc:
            break
    return {
        "success": bool(info.get("is_success", False)),
        "tips_best": int(best_tips),
        "dropped": bool(term),
        "peak": peak, "hold_peak": hold_peak, "last": last,
        "worst_link": worst_link, "worst_force": worst_f,
        "hold_speed_max": max(hold_speed) if hold_speed else 0.0,
        "hold_speed_median": float(np.median(hold_speed)) if hold_speed else 0.0,
    }


def verdict(t):
    """실물 기준으로 본 판정 한 줄. 채점표의 '성공' 이 무엇이었는지 가른다."""
    if not t["success"]:
        return "실패(채점표와 다름)"
    if max(t["last"]["finger"], t["last"]["other"]) > HAND_MAX_FORCE_N:
        return "끼어서 버팀(손끝 아닌 곳 > 97 N, 마지막까지)"
    if max(t["hold_peak"].values()) > HAND_MAX_FORCE_N:
        return "잡는 중 비현실적 힘(> 97 N)"
    if t["last"]["finger"] > TOUCH_N or t["last"]["other"] > TOUCH_N:
        return "성공(손끝 아닌 곳도 닿음, 97 N 이하)"
    return "성공(손끝만)"


def main() -> int:
    ap = argparse.ArgumentParser(description="채점표 성공 자세의 손 전 부위 힘 검사 (B-8)")
    ap.add_argument("--table", default="superdex/results/pose_score_18obj.json")
    ap.add_argument("--per-object", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--exclude", default="duck_lamp",
                    help="뺄 물체(콤마). 2026-09-23 사용자 지시로 duck_lamp 제외가 기본")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv
    from pose_score_sweep import OBJECTS, TRAJECTORIES

    table_path = Path(args.table)
    if not table_path.is_absolute():
        table_path = REPO_ROOT / table_path
    table = json.loads(table_path.read_text(encoding="utf-8"))
    exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
    rows = pick_rows(table, args.per_object, exclude)
    print(f"채점표 {table_path.name}: 성공률 100% 행 중 {len(rows)}개 검사 "
          f"(물체당 최대 {args.per_object}, 시드 {args.seeds}, 쥐기 동작 {len(TRAJECTORIES)}개, 제외 {sorted(exclude)})",
          flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"audit_grasp_forces_{time.strftime('%Y%m%d_%H%M%S')}.json"
    results = []
    t0 = time.time()
    for obj in dict.fromkeys(r["object"] for r in rows):
        prefab, actor, ref = OBJECTS[obj]
        config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0,
                  "episode_seconds": table.get("episode_seconds", 1.0)}
        if actor:
            config["object_actor"] = actor
        env = Dg5fGraspEnv(config)
        try:
            actors, kind = link_actors(env)
            for r in (r for r in rows if r["object"] == obj):
                env.place = np.asarray(r["place"], dtype=float)
                env.place_rot = np.asarray(r["place_rot"], dtype=float)
                for i in range(args.seeds):
                    for traj in TRAJECTORIES:
                        tr = run_trial(env, args.seed0 + i, *traj, actors, kind)
                        tr.update(object=obj, place=r["place"], rot_name=r["rot_name"],
                                  seed=args.seed0 + i, trajectory=list(traj))
                        tr["verdict"] = verdict(tr)
                        results.append(tr)
                print(f"  [{obj}] {r['rot_name']:>8s} {r['place']} — "
                      + ", ".join(t["verdict"][:12] for t in results[-args.seeds * len(TRAJECTORIES):])
                      + f"   ({time.time() - t0:.0f}s)", flush=True)
        finally:
            env.close()
        out_path.write_text(json.dumps({"table": table_path.name, "hand_max_force_n": HAND_MAX_FORCE_N,
                                        "results": results}, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    succ = [t for t in results if t["success"]]
    print(f"\n=== 요약: 시도 {len(results)}회, 그중 성공 판정 {len(succ)}회 ===")
    from collections import Counter
    for v, n in Counter(t["verdict"] for t in results).most_common():
        print(f"  {v}: {n}회")
    print("\n물체별 (성공 판정 중 '끼어서 버팀' 비율 / 손끝 아닌 곳 마지막 힘 중앙값 N):")
    for obj in dict.fromkeys(t["object"] for t in results):
        s = [t for t in succ if t["object"] == obj]
        if not s:
            print(f"  {obj:>14s}: 성공 판정 없음")
            continue
        wedge = sum(1 for t in s if t["verdict"].startswith("끼어서"))
        med = float(np.median([max(t["last"]["finger"], t["last"]["other"]) for t in s]))
        print(f"  {obj:>14s}: {wedge}/{len(s)}   {med:9.1f} N")
    print(f"\n저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
