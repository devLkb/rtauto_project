# -*- coding: utf-8 -*-
"""게이트 4 — domain randomization 스윕. 정책이 **어디서 깨지는지**와 **비용**을 잰다.

`docs/SIM2REAL_ROADMAP.md`/`SUPERDEX_POC_PLAN.md` §5 게이트 4의 판정 문장은 두 개다:

> 정책이 유지되는가, 샘플 비용이 몇 배로 뛰는가.

원안은 "DR을 켜고 재학습한다"였지만, **먼저 물어야 할 것이 있다**: DR 없이 학습한 v8
정책이 애초에 얼마나 견디는가. 견딘다면 재학습 예산(원 추정 3~10배)이 필요 없다.
견디지 못하는 지점을 찾으면 **거기서부터** 학습하면 된다.

그래서 이 스크립트는 재학습을 하지 않고, 같은 정책을 **DR 폭을 넓혀가며** 평가해
성능 열화 곡선을 만든다. 폭마다 벽시계 시간도 재서 DR 자체의 스텝 비용을 분리한다.

## 흔드는 것

리셋마다 물체의 **밀도(→질량)** 와 **coulomb 마찰계수**를 흔든다
(`Dg5fGraspEnv` 의 `dr_mass_range` / `dr_friction_range`). 기준값은 duck_lamp 실측
질량 0.545 kg, 마찰 0.25 다.

**크기(scale)는 흔들지 않는다** — 기하를 바꾸려면 프리팹을 다시 올려야 해서 리셋 비용이
자릿수로 뛴다. 물체 종류 교체(`--object-prefab`)가 그 자리를 대신한다.

## 지표 — 평균이 아니라 최악값을 본다

게이트 2에서 확인한 것처럼 판정을 지탱하는 것은 평균이 아니라 최악값이다. FOUP 처럼
무거운 물체에서는 "가끔 크게 미끄러진다"가 치명적이다. 그래서 슬립의 **중앙과 최대**를
함께 찍는다. 물체 크기에 의존하는 거리 기준도 참고로 남긴다(§0 "계획 변경" 2번).

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate4_dr_sweep.py --checkpoint superdex/results/dg5f_grasp_v8_iter0250
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate4_dr_sweep.py --checkpoint superdex/results/dg5f_grasp_v8_iter0250
```

기준선(고정 폐쇄 정책)과 비교하려면 `--baseline`. 30 에피소드 × 4단계로 몇 분 걸린다.
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

import rtauto_config as cfg  # noqa: E402,F401

# DR 단계. 기준값(질량 0.545 kg, 마찰 0.25)을 중심으로 폭을 넓혀간다.
# 이름은 출력 표의 행 레이블이다.
#   mass     : 밀도 배율 (lo, hi)
#   friction : coulomb 계수 절대 범위
# 3단계 마찰 0.05 는 거의 미끄러운 표면, 1.0 은 고무에 가깝다. 질량 8배(4.4 kg)는
# DG-5F-M 의 실제 파지력 상한(U8 미확정)을 넘을 가능성이 큰 — 즉 **깨지는 것이 정상인**
# 지점이다. 깨지는 곳을 찾는 것이 이 스윕의 목적이다.
LEVELS = [
    ("0 없음", None, None),
    ("1 좁음", (0.5, 2.0), (0.15, 0.50)),
    ("2 중간", (0.25, 4.0), (0.10, 0.70)),
    ("3 넓음", (0.10, 8.0), (0.05, 1.00)),
]


def run_level(env_config: dict, policy_spec, episodes: int, seed0: int):
    """한 DR 단계를 평가한다. (지표 dict, 소요초, 스텝수) 를 돌려준다."""
    from dg5f_grasp_env import Dg5fGraspEnv

    env = Dg5fGraspEnv(env_config)
    policy = policy_spec(env)

    rows, steps = [], 0
    t0 = time.perf_counter()
    for ep in range(episodes):
        obs, _ = env.reset(seed=seed0 + ep)
        info = {}
        for _ in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            steps += 1
            if term or trunc:
                break
        rows.append({
            "tips": int(info.get("tips_touching", 0)),
            "dist": float(info.get("dist", float("nan"))),
            "slip": float(info.get("slip", float("nan"))),
            "established": bool(info.get("grasp_established", False)),
        })
    elapsed = time.perf_counter() - t0
    min_tips, hold_radius = env.min_tips, env.hold_radius
    env.close()

    est = np.array([r["established"] for r in rows])
    tips_ok = np.array([r["tips"] >= min_tips for r in rows])
    dist_ok = np.array([r["dist"] < hold_radius for r in rows])
    slips = np.array([r["slip"] for r in rows], dtype=float)
    dists = np.array([r["dist"] for r in rows], dtype=float)
    # 파지가 성립한 에피소드에서만 슬립이 정의된다.
    slip_est = slips[est & np.isfinite(slips)]
    # ⚠️ 솔버가 터진 에피소드를 **분리해 센다.** 극단적인 질량·마찰에서 Mochi 가
    # "Solution explosion detected" 와 NaN 을 뱉는 것을 실측했다(2026-09-09). 이걸
    # 세지 않으면 "정책이 못 버텼다"와 "물리가 터졌다"를 구분할 수 없고, DR 폭을
    # 넓힌 결과가 정책 평가인지 수치 실패인지 알 수 없게 된다.
    nonfinite = int((est & ~np.isfinite(slips)).sum() + (~np.isfinite(dists)).sum())
    return {
        "n": len(rows),
        "established": float(est.mean()),
        "slip_med": float(np.median(slip_est)) if slip_est.size else float("nan"),
        "slip_max": float(slip_est.max()) if slip_est.size else float("nan"),
        "dist_success": float((tips_ok & dist_ok).mean()),
        "nonfinite": nonfinite,
    }, elapsed, steps


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 4 DR 스윕")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--baseline", action="store_true",
                    help="학습 정책 대신 고정 폐쇄 기준선으로 스윕한다")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--slip-tol", type=float, default=0.03,
                    help="슬립 기준 허용 변위 [m]. 게이트 0 스크립트 파지는 0.0013 이었다")
    ap.add_argument("--env-config", default='{"episode_seconds": 1.0}',
                    help="DR 외의 환경 설정. 학습 때와 같아야 비교가 성립한다")
    args = ap.parse_args()

    if not args.baseline and not args.checkpoint:
        sys.exit("--checkpoint 또는 --baseline 중 하나가 필요하다.")

    base_config = json.loads(args.env_config)
    for k in ("dr_mass_range", "dr_friction_range"):
        if k in base_config:
            sys.exit(f"--env-config 에 {k} 를 넣지 마라 — 스윕이 단계마다 설정한다.")

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
        if not ckpt.exists():
            sys.exit(f"체크포인트가 없다: {ckpt}")
        label = f"학습 정책 ({ckpt.name})"

        def policy_spec(env):
            return load_policy(ckpt, env.joint_low, env.joint_high)

    print(f"=== 게이트 4 DR 스윕: {label} ===")
    print(f"에피소드 {args.episodes} × 단계 {len(LEVELS)}  "
          f"(시드 {args.seed0}..{args.seed0 + args.episodes - 1}, 단계마다 동일)")
    print(f"환경 설정: {base_config}")
    print(f"기준 물성: 질량 0.545 kg, coulomb 마찰 0.25 (duck_lamp 실측)\n")

    results = []
    for name, mass_r, fric_r in LEVELS:
        c = dict(base_config)
        if mass_r:
            c["dr_mass_range"] = list(mass_r)
        if fric_r:
            c["dr_friction_range"] = list(fric_r)
        desc = "-" if not mass_r else f"질량 ×{mass_r[0]}~{mass_r[1]}, 마찰 {fric_r[0]}~{fric_r[1]}"
        print(f"[{name}] {desc}")
        m, elapsed, steps = run_level(c, policy_spec, args.episodes, args.seed0)
        m["name"], m["desc"] = name, desc
        m["steps_per_s"] = steps / elapsed if elapsed > 0 else float("nan")
        results.append(m)
        print(f"    성립 {m['established']:.0%}  슬립 중앙 {m['slip_med']:.4f} "
              f"최대 {m['slip_max']:.4f}  거리기준 {m['dist_success']:.0%}  "
              f"비정상수치 {m['nonfinite']}  {m['steps_per_s']:.0f} steps/s")

    print()
    print("=" * 78)
    print(f"{'단계':<8} {'파지성립':>8} {'슬립중앙':>10} {'슬립최대':>10} "
          f"{'거리기준':>8} {'NaN':>5} {'steps/s':>9}")
    for m in results:
        print(f"{m['name']:<8} {m['established']:>7.0%} {m['slip_med']:>10.4f} "
              f"{m['slip_max']:>10.4f} {m['dist_success']:>7.0%} "
              f"{m['nonfinite']:>5d} {m['steps_per_s']:>9.0f}")
    print("=" * 78)

    base, widest = results[0], results[-1]
    # 판정은 **최악값**으로 한다 — 게이트 2에서 확인한 원칙이다.
    print("\n판정 (DR 없음 대비):")
    for m in results[1:]:
        d_est = m["established"] - base["established"]
        r_slip = (m["slip_max"] / base["slip_max"]) if base["slip_max"] else float("nan")
        verdict = "유지" if (d_est >= -0.1 and r_slip <= 1.5) else "열화"
        print(f"  {m['name']}: 파지성립 {d_est:+.0%}, 최악 슬립 ×{r_slip:.2f}  -> **{verdict}**")

    bad = [m for m in results if m["nonfinite"]]
    if bad:
        print()
        print("⚠️ **비정상 수치(NaN/발산)가 나온 단계가 있다** — 그 단계의 열화는")
        print("   정책 실패가 아니라 물리 솔버 실패일 수 있다. 판정을 그대로 믿지 마라:")
        for m in bad:
            print(f"     {m['name']}: {m['nonfinite']}/{m['n']} 에피소드")

    cost = base["steps_per_s"] / widest["steps_per_s"] if widest["steps_per_s"] else float("nan")
    print(f"\nDR 자체의 스텝 비용: ×{cost:.2f} "
          f"({base['steps_per_s']:.0f} -> {widest['steps_per_s']:.0f} steps/s)")
    print("  (리셋마다 actor 속성만 바꾸므로 씬 재생성이 없다 — 1에 가까워야 정상)")
    print("\n⚠️ 이 스윕은 **재학습 없이** 기존 정책의 견딤을 잰 것이다. 샘플 요구가 몇 배로"
          "\n   뛰는지는 DR을 켜고 실제로 학습해야 나온다 — 어느 단계부터 학습이 필요한지를"
          "\n   위 표로 정하는 것이 이 스크립트의 목적이다.")


if __name__ == "__main__":
    main()
