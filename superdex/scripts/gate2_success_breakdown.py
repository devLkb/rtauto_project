# -*- coding: utf-8 -*-
"""게이트 2 성공 조건 분해 — 두 조건이 **같은 에피소드에서 겹치는가**를 본다.

성공 판정은 `지문 min_tips개 이상 접촉` AND `블록이 파지중심 hold_radius 내` 의 **동시**
충족이다. v8 실측에서 모순적인 상황이 나왔다:

    지표              v8 @200    기준선(고정 폐쇄)
    성공률            12/30 40%   14/30 47%
    평균 지문 접촉    3.43        3.03      <- v8이 더 좋다
    평균 최종 거리    0.0669      0.0904    <- v8이 더 좋다
    낙하              1/30        5/30      <- v8이 더 좋다

**평균이 전부 더 좋은데 성공률이 낮다** = 두 조건이 같은 에피소드에서 겹치지 않는다.
이 스크립트는 에피소드별 (지문 수, 거리)를 2x2 로 교차 집계해 어느 조건이 병목인지 가른다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/gate2_success_breakdown.py --baseline --episodes 30
    python superdex/scripts/gate2_success_breakdown.py --checkpoint superdex/results/dg5f_grasp_v8_iter0200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 2 성공 조건 분해")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--env-config", default=None)
    args = ap.parse_args()

    if not args.baseline and not args.checkpoint:
        sys.exit("--checkpoint 또는 --baseline 중 하나가 필요하다.")

    from dg5f_grasp_env import Dg5fGraspEnv
    from eval_policy import load_policy

    env = Dg5fGraspEnv(json.loads(args.env_config) if args.env_config else {})

    if args.baseline:
        fixed = env.full_closed.astype(np.float32)
        policy = lambda _o: fixed  # noqa: E731
        label = "고정 폐쇄 기준선"
    else:
        ckpt = Path(args.checkpoint)
        if not ckpt.is_absolute():
            ckpt = REPO_ROOT / ckpt
        policy = load_policy(ckpt, env.joint_low, env.joint_high)
        label = f"학습 정책 ({ckpt.name})"

    rows = []
    for ep in range(args.episodes):
        obs, _ = env.reset(seed=args.seed0 + ep)
        info = {}
        for _ in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            if term or trunc:
                break
        rows.append({
            "seed": args.seed0 + ep,
            "tips": int(info.get("tips_touching", 0)),
            "dist": float(info.get("dist", float("nan"))),
            "dropped": bool(term),
            "success": bool(info.get("is_success", False)),
        })
    env.close()

    tips_ok = np.array([r["tips"] >= env.min_tips for r in rows])
    dist_ok = np.array([r["dist"] < env.hold_radius for r in rows])
    n = len(rows)

    print(f"\n=== 성공 조건 분해: {label} ===")
    print(f"에피소드 {n}  (시드 {args.seed0}..{args.seed0 + n - 1})")
    print(f"조건: 지문 >= {env.min_tips}  AND  거리 < {env.hold_radius} m\n")

    print(f"{'':22s} {'거리 OK':>9s} {'거리 X':>9s} {'합':>6s}")
    print(f"{'지문 OK':22s} {int((tips_ok & dist_ok).sum()):>9d} "
          f"{int((tips_ok & ~dist_ok).sum()):>9d} {int(tips_ok.sum()):>6d}")
    print(f"{'지문 X':22s} {int((~tips_ok & dist_ok).sum()):>9d} "
          f"{int((~tips_ok & ~dist_ok).sum()):>9d} {int((~tips_ok).sum()):>6d}")
    print(f"{'합':22s} {int(dist_ok.sum()):>9d} {int((~dist_ok).sum()):>9d} {n:>6d}")

    print(f"\n지문 조건 단독 충족률 : {tips_ok.sum()}/{n} = {tips_ok.mean():.0%}")
    print(f"거리 조건 단독 충족률 : {dist_ok.sum()}/{n} = {dist_ok.mean():.0%}")
    print(f"동시 충족(=성공)      : {(tips_ok & dist_ok).sum()}/{n} = {(tips_ok & dist_ok).mean():.0%}")

    # 어느 조건이 병목인가 — 실패 에피소드를 원인별로 가른다.
    only_tips = int((tips_ok & ~dist_ok).sum())
    only_dist = int((~tips_ok & dist_ok).sum())
    neither = int((~tips_ok & ~dist_ok).sum())
    print(f"\n실패 원인 분해:")
    print(f"  지문은 됐지만 거리 초과 : {only_tips}  <- 파지는 성립, 물체를 밀어냈다")
    print(f"  거리는 됐지만 지문 부족 : {only_dist}  <- 가까이 뒀지만 못 쥐었다")
    print(f"  둘 다 실패              : {neither}")

    if only_tips > only_dist:
        print(f"\n-> **거리 조건이 병목**이다. 파지 자체는 성립하는데 물체를 밀어낸다.")
    elif only_dist > only_tips:
        print(f"\n-> **지문 조건이 병목**이다. 물체는 가까이 있는데 접촉을 못 만든다.")
    else:
        print(f"\n-> 두 조건이 비슷하게 병목이다.")

    print(f"\n--- 에피소드별 (지문, 거리) ---")
    for r in rows:
        mk = "OK" if r["success"] else ("  " if not r["dropped"] else "DR")
        t = "T" if r["tips"] >= env.min_tips else "-"
        d = "D" if r["dist"] < env.hold_radius else "-"
        print(f"  {mk} seed {r['seed']}  지문 {r['tips']} [{t}]  "
              f"거리 {r['dist']:.4f} [{d}]")


if __name__ == "__main__":
    main()
