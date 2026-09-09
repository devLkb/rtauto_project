# -*- coding: utf-8 -*-
"""게이트 4 — DR 실패가 **무엇과 상관되는가**. 학습 문제인가 물리 한계인가.

2단계 DR 재학습이 **정체했다**(120만 스텝 추가, DR 조건 최악 슬립 0.2388 → 0.2413).
`gate4_dr_recovery.py` 가 경고한 대로 해석이 두 가지다:

  (a) 샘플이 더 필요하다 — 학습 문제
  (b) DR 범위가 비현실적이다 — 손이 물리적으로 못 드는 무게가 섞여 있다

**게이트 2에서 이미 같은 함정을 밟았다.** 발견 6: v1~v4 의 학습 수정들은 애초에 풀리지
않는 과제(2.5 cm 블록, 3지 접촉이 기하적으로 불가)를 고치려 한 것이었고, 오라클 탐색으로
"성공 궤적이 존재하는가"를 직접 물어서야 원인이 드러났다. 같은 실수를 반복하지 않기 위해
**추측 대신 측정**한다.

## 방법 — 실패를 흔든 변수에 대고 분해한다

DR 이 흔드는 것은 질량과 마찰 둘뿐이다. 에피소드마다 **실제로 뽑힌 값**과 결과(슬립)를
같이 기록하면, 실패가 어느 변수의 어느 구간에 몰려 있는지 바로 보인다.

- 실패가 **고질량 구간에 몰린다** → (b). 파지력 상한을 넘은 것이고 학습으로 안 풀린다.
  DR 범위를 손이 실제로 감당하는 구간으로 좁히는 것이 맞다.
- 실패가 **저마찰 구간에 몰린다** → (b) 의 다른 형태. 마찰이 없으면 어떤 정책도 못 잡는다.
- 실패가 **고르게 퍼져 있다** → (a). 학습 예산 문제이므로 이터레이션을 늘릴 근거가 된다.

환경이 `reset()` 의 info 로 그 에피소드에 적용된 값을 돌려주므로(`_apply_domain_randomization`)
추가 계측 없이 잰다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate4_dr_failure_analysis.py --checkpoint superdex/results/dg5f_grasp_dr2_iter0250
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate4_dr_failure_analysis.py --checkpoint superdex/results/dg5f_grasp_dr2_iter0250
```

에피소드를 넉넉히(기본 90) 돌려야 구간별로 표본이 남는다.
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

# gate4_dr_recovery.py / gate4_dr_sweep.py 의 2단계와 같은 범위여야 한다.
DR_ON = {"dr_mass_range": [0.25, 4.0], "dr_friction_range": [0.10, 0.70]}
SLIP_TOL = 0.03  # 게이트 2 정본 허용 변위 [m]


def bin_report(name: str, values: np.ndarray, ok: np.ndarray, slips: np.ndarray,
               unit: str, n_bins: int = 4) -> float:
    """값을 분위로 나눠 구간별 성공률·슬립을 찍고, 최저/최고 구간 성공률 차이를 돌려준다."""
    edges = np.quantile(values, np.linspace(0, 1, n_bins + 1))
    edges[-1] += 1e-9
    print(f"\n  {name} 구간별:")
    print(f"    {'구간':<22} {'n':>3} {'슬립기준 성공':>12} {'슬립중앙':>10} {'슬립최대':>10}")
    rates = []
    for i in range(n_bins):
        m = (values >= edges[i]) & (values < edges[i + 1])
        if not m.any():
            continue
        s = slips[m & np.isfinite(slips)]
        rate = float(ok[m].mean())
        rates.append(rate)
        print(f"    {edges[i]:.3f}~{edges[i+1]:.3f} {unit:<8} {int(m.sum()):>3} "
              f"{rate:>11.0%} "
              f"{(np.median(s) if s.size else float('nan')):>10.4f} "
              f"{(s.max() if s.size else float('nan')):>10.4f}")
    return (max(rates) - min(rates)) if rates else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 4 DR 실패 원인 분해")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--episodes", type=int, default=90)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--env-config", default='{"episode_seconds": 1.0}')
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv
    from eval_policy import load_policy

    ckpt = Path(args.checkpoint)
    if not ckpt.is_absolute():
        ckpt = REPO_ROOT / ckpt
    if not ckpt.is_dir():
        sys.exit(f"체크포인트가 없다: {ckpt}")

    env = Dg5fGraspEnv({**json.loads(args.env_config), **DR_ON})
    policy = load_policy(ckpt, env.joint_low, env.joint_high)

    print(f"=== 게이트 4 DR 실패 원인 분해: {ckpt.name} ===")
    print(f"에피소드 {args.episodes}  DR: {DR_ON}  슬립 허용치 {SLIP_TOL} m")
    print(f"기준 물성: 질량 0.545 kg, 마찰 0.25\n")

    mass, fric, slip, tips_ok, est = [], [], [], [], []
    for ep in range(args.episodes):
        _obs, dr = env.reset(seed=args.seed0 + ep)
        info = {}
        obs = _obs
        for _ in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            if term or trunc:
                break
        mass.append(dr["mass"])
        fric.append(dr["friction"])
        slip.append(float(info.get("slip", float("nan"))))
        tips_ok.append(int(info.get("tips_touching", 0)) >= env.min_tips)
        est.append(bool(info.get("grasp_established", False)))
    env.close()

    mass = np.array(mass); fric = np.array(fric)
    slip = np.array(slip); tips_ok = np.array(tips_ok); est = np.array(est)
    ok = tips_ok & est & np.isfinite(slip) & (slip < SLIP_TOL)

    print(f"전체 슬립 기준 성공: {ok.sum()}/{len(ok)} = {ok.mean():.0%}")
    print(f"질량 범위 {mass.min():.3f}~{mass.max():.3f} kg  "
          f"마찰 범위 {fric.min():.3f}~{fric.max():.3f}")

    d_mass = bin_report("질량", mass, ok, slip, "kg")
    d_fric = bin_report("마찰", fric, ok, slip, "")

    # 상관: 성공(0/1)과 각 변수의 스피어만 대신 단순 점이연 상관으로 충분하다.
    def corr(x):
        if x.std() < 1e-12 or ok.std() < 1e-12:
            return float("nan")
        return float(np.corrcoef(x, ok.astype(float))[0, 1])

    print(f"\n  성공과의 상관계수:  질량 {corr(mass):+.3f}   마찰 {corr(fric):+.3f}")

    print()
    print("=" * 78)
    print("판정:")
    # 구간별 성공률 격차가 크면 그 변수가 지배한다. 0.3 = 최저·최고 구간이 30%p 차이.
    dominant = None
    if d_mass >= 0.3 and d_mass >= d_fric:
        dominant = "질량"
    elif d_fric >= 0.3:
        dominant = "마찰"

    if dominant:
        print(f"  실패가 **{dominant}에 몰려 있다** (구간 간 성공률 격차 "
              f"{max(d_mass, d_fric):.0%}p).")
        print(f"  -> 학습 예산 문제가 아니라 **물리 한계**로 보인다. DR 범위를 손이 실제로")
        print(f"     감당하는 구간으로 좁히는 것이 맞다. 질량 상한의 근거는 DG-5F-M 의")
        print(f"     파지력 스펙(U8, 미확정)이며, 확정 전에는 위 구간표의 성공률이")
        print(f"     떨어지기 시작하는 지점을 잠정 상한으로 쓴다.")
    else:
        print(f"  실패가 **고르게 퍼져 있다** (질량 격차 {d_mass:.0%}p, 마찰 {d_fric:.0%}p).")
        print(f"  -> 특정 물성 구간의 문제가 아니다. **학습 예산 문제**로 보이므로")
        print(f"     이터레이션을 늘려 재확인할 근거가 된다.")
    print("=" * 78)


if __name__ == "__main__":
    main()
