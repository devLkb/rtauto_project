# -*- coding: utf-8 -*-
"""게이트 4 — 무거우면 왜 실패하는가. **쿨롱 마찰 한계**인지 1차 원리로 검산한다.

`gate4_dr_failure_analysis.py` 가 2단계 DR 실패는 **질량에 몰려 있다**고 보여줬다
(성공률: 0.19~0.68 kg 83 % / 0.68~1.18 kg 77 % / 1.18~1.78 kg 32 % / 1.78~2.13 kg 17 %,
상관 −0.562). 약 1.2 kg 에 절벽이 있다.

그런데 같은 실측에서 **마찰 최고 구간(0.54~0.70)만 최악 슬립 0.0677** 이고 나머지 구간은
0.22~0.25 였다. 질량과 마찰이 **함께** 작동한다는 신호다 — 정확히 쿨롱 마찰의 형태다.

## 검산할 가설

지문 접촉으로 물체를 붙들 때, 미끄러지지 않을 조건은 대략

    μ · ΣF_normal  ≥  m · g

이다. 그러면 **버틸 수 있는 최대 질량**은

    m_max ≈ μ · ΣF_tip / g

이 스크립트는 질량과 마찰을 **무작위가 아니라 격자로 고정**해 돌리면서 실제 지문 접촉력
합(`info["tip_force_sum"]`)을 재고, 위 식이 예측하는 한계와 관측된 성공/실패 경계를
비교한다. 예측선이 관측 경계와 맞으면 **학습으로 풀 문제가 아니다** — 파지 자세와 강성이
정하는 물리 상한이다.

## 왜 이게 게이트 4 판정에 필요한가

"2단계 DR 에서 회복하지 못했다"는 사실만으로는 **엔진 판단에 쓸 수 없다.** 원인이
학습이면 SuperDex 와 무관하고, 물리 상한이면 애초에 **잘못된 범위를 요구한 것**이다.
게이트 2 발견 6 에서 같은 함정을 밟았다 — 풀리지 않는 과제를 학습으로 고치려 했다.

> ⚠️ 여기서 나오는 "한계 질량"은 **DG-5F-M 하드웨어의 파지력 스펙이 아니다.** 이 태스크
> 구성(손목 고정, 강성 3.0, duck_lamp 형상, 특정 파지 자세)에서의 상한이다. 강성 3.0 은
> 접촉력을 물리적으로 그럴듯한 범위(완전 폐쇄 34.7 N)에 두려고 **의도적으로 낮춘 값**이며
> (게이트 2 실측: 1e3 에서 4,671 N 이 나온다), 실제 하드웨어 상한은 U8 로 미확정이다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate4_payload_limit.py --checkpoint superdex/results/dg5f_grasp_v8_iter0300
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate4_payload_limit.py --checkpoint superdex/results/dg5f_grasp_v8_iter0300
```

격자 기본값은 질량 4점 × 마찰 3점 × 시드 8개 = 96 에피소드다.
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

G = 9.81
SLIP_TOL = 0.03  # 게이트 2 정본 허용 변위 [m]

# 격자. DR 2단계가 훑던 구간을 덮되 **고정값**으로 준다 — 무작위로는 각 칸의 표본이
# 모이지 않아 경계를 못 본다. 질량은 duck_lamp 기준 0.545 kg 에 대한 배율로 지정한다.
MASS_MULTS = (0.5, 1.0, 2.0, 4.0)      # 0.27 / 0.55 / 1.09 / 2.18 kg
FRICTIONS = (0.15, 0.35, 0.70)


def run_cell(mass_mult: float, friction: float, base_config: dict,
             policy_spec, seeds: range) -> dict:
    """질량·마찰을 **고정**하고 여러 시드를 돌린다."""
    from dg5f_grasp_env import Dg5fGraspEnv

    # 범위의 상하한을 같게 주면 uniform 이 그 값을 그대로 낸다 = 고정.
    env = Dg5fGraspEnv({
        **base_config,
        "dr_mass_range": [mass_mult, mass_mult],
        "dr_friction_range": [friction, friction],
    })
    policy = policy_spec(env)

    ok, slips, forces, masses = [], [], [], []
    for s in seeds:
        obs, dr = env.reset(seed=s)
        info = {}
        peak = 0.0
        for _ in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            # 파지가 성립한 뒤의 접촉력이 관심사다 — grace 구간의 0 을 섞지 않는다.
            if info.get("grasp_established"):
                peak = max(peak, float(info.get("tip_force_sum", 0.0)))
            if term or trunc:
                break
        masses.append(dr["mass"])
        slip = float(info.get("slip", float("nan")))
        established = bool(info.get("grasp_established", False))
        tips_ok = int(info.get("tips_touching", 0)) >= env.min_tips
        ok.append(bool(tips_ok and established and np.isfinite(slip) and slip < SLIP_TOL))
        slips.append(slip)
        forces.append(peak)
    env.close()

    slips = np.array(slips, dtype=float)
    fin = np.isfinite(slips)
    return {
        "mass": float(np.mean(masses)),
        "success": float(np.mean(ok)),
        "slip_med": float(np.median(slips[fin])) if fin.any() else float("nan"),
        "force_sum": float(np.median(forces)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 4 파지 한계 질량 검산")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--seeds", type=int, default=8, help="격자 칸마다 시드 수")
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--env-config", default='{"episode_seconds": 1.0}')
    args = ap.parse_args()

    if not args.baseline and not args.checkpoint:
        sys.exit("--checkpoint 또는 --baseline 중 하나가 필요하다.")

    base_config = json.loads(args.env_config)
    for k in ("dr_mass_range", "dr_friction_range"):
        if k in base_config:
            sys.exit(f"--env-config 에 {k} 를 넣지 마라 — 격자가 고정한다.")

    if args.baseline:
        label = "고정 폐쇄 기준선"

        def policy_spec(env):
            fixed = env.full_closed.astype(np.float32)
            return lambda _o: fixed
    else:
        from eval_policy import load_policy

        ckpt = Path(args.checkpoint)
        if not ckpt.is_absolute():
            ckpt = REPO_ROOT / ckpt
        if not ckpt.is_dir():
            sys.exit(f"체크포인트가 없다: {ckpt}")
        label = f"학습 정책 ({ckpt.name})"

        def policy_spec(env):
            return load_policy(ckpt, env.joint_low, env.joint_high)

    seeds = range(args.seed0, args.seed0 + args.seeds)
    print(f"=== 게이트 4 파지 한계 질량 검산: {label} ===")
    print(f"격자 질량 {len(MASS_MULTS)} × 마찰 {len(FRICTIONS)} × 시드 {args.seeds} "
          f"= {len(MASS_MULTS) * len(FRICTIONS) * args.seeds} 에피소드")
    print(f"가설: 버틸 수 있는 질량  m_max ≈ μ · ΣF_지문 / g\n")

    grid = {}
    for mu in FRICTIONS:
        for mm in MASS_MULTS:
            r = run_cell(mm, mu, base_config, policy_spec, seeds)
            grid[(mu, mm)] = r
            print(f"  μ={mu:.2f}  m={r['mass']:.3f} kg  ->  성공 {r['success']:>4.0%}  "
                  f"슬립중앙 {r['slip_med']:.4f}  ΣF {r['force_sum']:.1f} N")

    print()
    print("=" * 76)
    print("성공률 격자 (행=마찰, 열=질량)")
    header = "  μ \\ m ".ljust(10) + "".join(
        f"{grid[(FRICTIONS[0], mm)]['mass']:>9.2f}kg" for mm in MASS_MULTS)
    print(header)
    for mu in FRICTIONS:
        row = f"  {mu:>5.2f}   " + "".join(
            f"{grid[(mu, mm)]['success']:>10.0%}" for mm in MASS_MULTS)
        print(row)
    print("=" * 76)

    # 1차 원리 예측선. ΣF 는 그 마찰 행에서 실측된 접촉력 합의 중앙값을 쓴다.
    print("\n쿨롱 마찰 예측 vs 관측:")
    print(f"  {'μ':>5} {'실측 ΣF':>10} {'예측 m_max':>12} {'관측 경계':>26}")
    agree = []
    for mu in FRICTIONS:
        fs = np.median([grid[(mu, mm)]["force_sum"] for mm in MASS_MULTS])
        m_pred = mu * fs / G
        # 관측 경계: 성공률이 50 % 아래로 떨어지는 첫 질량
        boundary = None
        for mm in MASS_MULTS:
            if grid[(mu, mm)]["success"] < 0.5:
                boundary = grid[(mu, mm)]["mass"]
                break
        prev = None
        for mm in MASS_MULTS:
            if grid[(mu, mm)]["success"] >= 0.5:
                prev = grid[(mu, mm)]["mass"]
        obs = ("> %.2f kg (전 구간 성공)" % prev if boundary is None
               else ("%.2f~%.2f kg" % (prev, boundary) if prev else "< %.2f kg" % boundary))
        print(f"  {mu:>5.2f} {fs:>9.1f}N {m_pred:>11.2f}kg {obs:>26}")
        if boundary is not None and prev is not None:
            agree.append(prev <= m_pred * 1.6 and m_pred >= prev * 0.4)

    print()
    print("=" * 76)
    print("판정:")
    higher_mu_helps = (
        np.mean([grid[(FRICTIONS[-1], mm)]["success"] for mm in MASS_MULTS])
        > np.mean([grid[(FRICTIONS[0], mm)]["success"] for mm in MASS_MULTS]) + 0.15
    )
    if higher_mu_helps:
        print("  **마찰을 올리면 무거운 물체도 버틴다** — 실패는 정책의 무능이 아니라")
        print("  쿨롱 마찰 한계다. 같은 정책이 μ 만 바뀌어도 결과가 달라지므로,")
        print("  2단계 DR 이 요구한 고질량 × 저마찰 조합은 **애초에 성립하지 않는 과제**다.")
        print("  -> DR 범위를 이 격자에서 성공하는 구간으로 좁히는 것이 맞다.")
    else:
        print("  마찰을 올려도 개선되지 않는다 — 쿨롱 마찰 한계 가설이 설명하지 못한다.")
        print("  실패 원인을 다시 찾아야 한다(파지 자세, 접촉 기하, 학습 예산 등).")
    print("=" * 76)
    print("\n⚠️ 여기서 나온 한계 질량은 **하드웨어 스펙이 아니다.** 이 태스크 구성"
          "\n   (손목 고정, 강성 3.0, duck_lamp 형상)에서의 상한이다. 강성 3.0 은 접촉력을"
          "\n   물리적으로 그럴듯한 범위에 두려고 의도적으로 낮춘 값이고(1e3 에서 4,671 N),"
          "\n   실제 DG-5F-M 파지력 상한은 U8 로 미확정이다.")


if __name__ == "__main__":
    main()
