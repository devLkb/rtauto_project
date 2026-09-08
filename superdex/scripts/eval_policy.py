# -*- coding: utf-8 -*-
"""학습된 정책을 DG5FGraspEnv에서 평가한다 (게이트 2 판정).

기준선과 나란히 비교하는 것이 요점이다. `--baseline` 을 주면 학습 정책 대신
"완전 폐쇄만 지령하는 고정 정책"을 돌려 같은 지표를 낸다 — 게이트 2의 판정은
**고정 정책 대비 얼마나 올라가는가**다(docs/SUPERDEX_POC_PLAN.md 게이트 2 절).

평가는 **결정론적**으로 한다: 학습 시 액션 분포의 평균만 쓰고 표본추출하지 않는다.
ONNX로 내보낼 정책과 같은 동작이어야 하기 때문이다(게이트 1의 래퍼와 동일한 경로).

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/eval_policy.py --baseline --episodes 30
    python superdex/scripts/eval_policy.py --checkpoint superdex/results/dg5f_grasp --episodes 30
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

import rtauto_config as cfg  # noqa: E402,F401  (환경이 asset 경로를 여기서 읽는다)


def load_policy(ckpt: Path, act_low, act_high):
    """체크포인트에서 결정론적 정책 함수를 만든다 (게이트 1의 래퍼와 같은 변환)."""
    import torch
    from ray.rllib.core.rl_module.multi_rl_module import MultiRLModule

    rl_dir = ckpt / "learner_group" / "learner" / "rl_module"
    multi = MultiRLModule.from_checkpoint(str(rl_dir))
    module = multi[list(multi.keys())[0]]
    module.eval()
    act_dim = len(act_low)
    low = np.asarray(act_low, dtype=np.float64)
    high = np.asarray(act_high, dtype=np.float64)

    def policy(obs):
        with torch.no_grad():
            out = module.forward_inference(
                {"obs": torch.as_tensor(obs[None, :].copy())}
            )
        mean = out["action_dist_inputs"].cpu().numpy()[0, :act_dim]
        # RLlib NormalizeAndClipActions 와 동일한 unsquash (게이트 1 실측)
        a = low + (mean + 1.0) * (high - low) / 2.0
        return np.clip(a, low, high)

    return policy


def main() -> None:
    ap = argparse.ArgumentParser(description="DG5FGraspEnv 정책 평가")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--baseline", action="store_true",
                    help="완전 폐쇄 고정 정책으로 평가 (기준선)")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--env-config", default=None, help="환경 설정 JSON")
    ap.add_argument("--seed0", type=int, default=9000, help="평가 시드 시작값")
    args = ap.parse_args()

    if not args.baseline and not args.checkpoint:
        sys.exit("--checkpoint 또는 --baseline 중 하나가 필요하다.")

    from dg5f_grasp_env import Dg5fGraspEnv

    env_config = json.loads(args.env_config) if args.env_config else {}
    env = Dg5fGraspEnv(env_config)

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

    succ = 0
    tips, fmax, rets, dists, drops = [], [], [], [], 0
    for ep in range(args.episodes):
        obs, _ = env.reset(seed=args.seed0 + ep)
        total, info = 0.0, {}
        for _ in range(env.max_steps):
            obs, r, term, trunc, info = env.step(policy(obs))
            total += r
            if term or trunc:
                break
        succ += int(info.get("is_success", False))
        drops += int(term)
        tips.append(info.get("tips_touching", 0))
        fmax.append(info.get("tip_force_max", 0.0))
        dists.append(info.get("dist", np.nan))
        rets.append(total)
    env.close()

    n = args.episodes
    print(f"\n=== 평가: {label} ===")
    print(f"에피소드            : {n}  (시드 {args.seed0}..{args.seed0 + n - 1})")
    print(f"성공률              : {succ}/{n} = {succ / n:.0%}"
          f"   (엄격 기준: 지문 {env.min_tips}개 이상 + 파지중심 {env.hold_radius} m 내)")
    print(f"낙하(조기종료)      : {drops}/{n}")
    print(f"평균 지문 접촉      : {np.mean(tips):.2f}")
    print(f"평균 최대 지문력    : {np.mean(fmax):.1f} N   (한계 {env.tip_force_limit} N)")
    print(f"평균 최종 거리      : {np.nanmean(dists):.4f} m")
    print(f"평균 리턴           : {np.mean(rets):.1f}")
    print("\n이 숫자를 docs/SUPERDEX_POC_PLAN.md §10 진행 기록에 남긴다.")


if __name__ == "__main__":
    main()
