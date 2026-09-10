# -*- coding: utf-8 -*-
"""게이트 2 오라클 탐색 — **과제가 애초에 풀리는가**를 판정한다.

docs/SUPERDEX_POC_PLAN.md §0 "내일 바로 이어서 할 것"의 갈림길이다. 학습 4회(v1~v4)가
전부 정책이 초기값에서 움직이지 않은 채 끝났는데, 원인이 둘 중 하나다:

  (A) **학습 설정 문제** — 성공 궤적은 존재하는데 PPO가 못 찾는다
  (B) **과제 가해성 문제** — 성공 궤적 자체가 (거의) 없다

이 스크립트는 정책을 학습하지 않고 **개루프 궤적을 그리드로 훑어**, 각 시드에서
성공시키는 궤적이 존재하는지 센다. 존재하면 (A), 존재하지 않으면 (B)다. 이 구분 없이
보상·탐색을 더 손대는 것은 어느 쪽인지 모르고 고치는 것이다.

탐색 공간 — 개루프 파라미터 3개:
  final_frac : 최종 폐쇄율 (open -> full 보간)
  ramp_steps : 그 폐쇄율까지 도달하는 데 쓰는 스텝 수
  hold_frac  : 도달 후 유지할 폐쇄율 (조임 여유. final_frac 이상)

액션 의미론은 환경과 동일하다 — 매 스텝 절대 목표각을 주고, 환경이 EMA로 평활화한다.
따라서 여기서 성공한 궤적은 **정책이 낼 수 있는 액션 시퀀스**이며, 도달 불가능한
이상적 제어가 아니다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/gate2_oracle_search.py
    python superdex/scripts/gate2_oracle_search.py --seeds 20 --min-tips 2
    python superdex/scripts/gate2_oracle_search.py --grace 80 --episode-seconds 1.5
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))

import rtauto_config as cfg  # noqa: E402,F401  (환경이 asset 경로를 여기서 읽는다)


def run_trajectory(env, seed, final_frac, ramp_steps, hold_frac, place_x=None):
    """개루프 궤적 하나를 끝까지 돌리고 최종 지표를 돌려준다."""
    if place_x is not None:
        env.place = np.array([place_x, env.place[1], env.place[2]], dtype=float)
    env.reset(seed=seed)
    info = {}
    best_tips = 0
    for t in range(env.max_steps):
        if t < ramp_steps:
            frac = final_frac * (t + 1) / ramp_steps
        else:
            frac = hold_frac
        a = env._pose_at(frac).astype(np.float32)
        _, _, term, trunc, info = env.step(a)
        best_tips = max(best_tips, info.get("tips_touching", 0))
        if term or trunc:
            break
    return {
        "success": bool(info.get("is_success", False)),
        "tips_end": int(info.get("tips_touching", 0)),
        "tips_best": int(best_tips),
        "dist": float(info.get("dist", float("nan"))),
        "force_max": float(info.get("tip_force_max", 0.0)),
        "dropped": bool(term),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 2 오라클 탐색 (과제 가해성 판정)")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=9000,
                    help="평가 스크립트와 같은 시드 대역을 기본으로 쓴다")
    ap.add_argument("--episode-seconds", type=float, default=1.0)
    ap.add_argument("--grace", type=int, default=None, help="grace_steps 오버라이드")
    ap.add_argument("--min-tips", type=int, default=None, help="min_tips 오버라이드")
    ap.add_argument("--place-jitter", type=float, default=None)
    ap.add_argument("--object", default=None,
                    help="파지 대상 프리팹 (assets 상대경로). 예: "
                         "prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab")
    ap.add_argument("--place-x", type=str, default="0.03",
                    help="손바닥 앞 거리 후보들(콤마 구분). 물체가 커지면 중심이 더 멀어야 한다")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv

    env_cfg = {"episode_seconds": args.episode_seconds}
    if args.grace is not None:
        env_cfg["grace_steps"] = args.grace
    if args.min_tips is not None:
        env_cfg["min_tips"] = args.min_tips
    if args.place_jitter is not None:
        env_cfg["place_jitter"] = args.place_jitter
    if args.object is not None:
        env_cfg["object_prefab"] = args.object

    env = Dg5fGraspEnv(env_cfg)

    FINAL = [0.6, 0.8, 1.0]
    RAMP = [30, 60]
    EXTRA = [0.0, 0.1]           # 도달 후 추가로 조이는 여유
    PLACE_X = [float(v) for v in args.place_x.split(",")]
    # ⚠️ 중복 제거가 필요하다. f=1.0 이면 extra 0.0 과 0.1 이 hold=min(1.0, f+e)=1.0 으로
    # 같은 튜플이 되어, 그대로 두면 per_traj 딕셔너리 키가 충돌해 같은 궤적을 두 번 세고
    # 성공 횟수·평균 tips_best 가 부풀려진다(실측에서 평균 tips_best 7.80 > 최대 5 로 발견).
    grid = list(dict.fromkeys(
        (f, r, min(1.0, f + e), px)
        for f, r, e, px in itertools.product(FINAL, RAMP, EXTRA, PLACE_X)
    ))

    print(f"환경: episode {env.episode_seconds}s ({env.max_steps} 스텝), grace {env.grace_steps}, "
          f"min_tips {env.min_tips}, hold_radius {env.hold_radius}, jitter {env.place_jitter}")
    print(f"물체: {env.object_prefab}")
    print(f"그리드: final {FINAL} x ramp {RAMP} x extra {EXTRA} x place_x {PLACE_X} = {len(grid)} 궤적")
    print(f"시드: {args.seed0}..{args.seed0 + args.seeds - 1} ({args.seeds}개)")
    print(f"총 롤아웃 {len(grid) * args.seeds}개\n")

    t0 = time.perf_counter()
    per_seed = {}
    per_traj = {g: {"succ": 0, "tips_best_sum": 0} for g in grid}
    steps = 0

    for i in range(args.seeds):
        seed = args.seed0 + i
        solved_by = []
        best = {"tips_best": -1}
        for g in grid:
            r = run_trajectory(env, seed, *g)
            steps += env.max_steps
            if r["success"]:
                solved_by.append(g)
                per_traj[g]["succ"] += 1
            per_traj[g]["tips_best_sum"] += r["tips_best"]
            if r["tips_best"] > best["tips_best"]:
                best = dict(r, traj=g)
        per_seed[seed] = {"solved_by": solved_by, "best": best}
        mark = "OK " if solved_by else "-- "
        print(f"{mark}seed {seed}: 성공 궤적 {len(solved_by):2d}/{len(grid)}  "
              f"최선 tips_best={best['tips_best']} (tips_end={best['tips_end']}, "
              f"dist={best['dist']:.4f}, f={best['traj'][0]:.1f}/ramp={best['traj'][1]}/x={best['traj'][3]:.2f})")

    elapsed = time.perf_counter() - t0
    solvable = [s for s, v in per_seed.items() if v["solved_by"]]

    print(f"\n=== 판정 ===")
    print(f"성공 궤적이 존재하는 시드: {len(solvable)}/{args.seeds} = {len(solvable) / args.seeds:.0%}")
    print(f"측정: {steps} 스텝, {elapsed:.1f}s -> {steps / elapsed:.0f} steps/s")

    if per_seed:
        tips_best_all = [v["best"]["tips_best"] for v in per_seed.values()]
        print(f"시드별 최선 tips_best 분포: min {min(tips_best_all)}  "
              f"중앙 {int(np.median(tips_best_all))}  max {max(tips_best_all)}  "
              f"(성공 요구 {env.min_tips})")

    print(f"\n--- 궤적별 성공률 (상위 8개) ---")
    ranked = sorted(per_traj.items(), key=lambda kv: (-kv[1]["succ"], -kv[1]["tips_best_sum"]))
    for g, st in ranked[:8]:
        print(f"  final={g[0]:.1f} ramp={g[1]:2d} hold={g[2]:.1f} x={g[3]:.2f}: "
              f"성공 {st['succ']:2d}/{args.seeds}  평균 tips_best {st['tips_best_sum'] / args.seeds:.2f}")

    frac_solvable = len(solvable) / max(args.seeds, 1)
    print(f"\n--- 결론 ---")
    if frac_solvable >= 0.7:
        print("(A) **학습 설정 문제.** 대부분의 시드에 성공 궤적이 존재한다 —")
        print("    개루프로도 풀리므로 PPO가 못 찾는 것이다. 탐색/설정을 고쳐야 한다.")
    elif frac_solvable <= 0.3:
        print("(B) **과제 가해성 문제.** 성공 궤적이 거의 없다 —")
        print("    보상·탐색을 더 손대도 소용없다. 과제 정의(min_tips, grace, jitter,")
        print("    episode 길이, 물체 크기)를 먼저 완화해야 한다.")
    else:
        print("(A/B 경계.) 성공 궤적이 일부 시드에만 존재한다 — 과제가 과도하게 좁다.")
        print("    학습 가능성은 있으나 성공률 상한이 낮다. 과제 완화와 탐색 개선을 함께 봐야 한다.")

    print("\n이 수치를 docs/SUPERDEX_POC_PLAN.md §10 진행 기록에 남긴다.")
    env.close()


if __name__ == "__main__":
    main()
