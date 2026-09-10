# -*- coding: utf-8 -*-
"""게이트 4 — DR 재학습이 회복시키는가, 그리고 **원래 성능을 깎지 않는가**.

`gate4_dr_sweep.py` 가 "DR 없이 학습한 정책이 어디서 깨지는가"를 답했다(2단계에서 최악
슬립 ×5). 이 스크립트는 그 다음 질문 두 개를 **체크포인트 계열**로 답한다:

1. **회복되는가 / 몇 스텝 드는가** — DR 을 켜고 이어서 학습한 체크포인트들을 **DR 켠
   조건**에서 평가한다. 게이트 4의 판정 문장 "샘플 비용이 몇 배로 뛰는가"가 이것이다.
2. **원래 성능을 깎지 않는가** — 같은 체크포인트들을 **DR 끈 조건**에서도 평가한다.
   DR 학습이 평균에 맞추느라 기준 조건 성능을 떨어뜨리는 것은 흔한 실패이고, 그걸
   못 보면 "일반화됐다"가 실은 "전부 못하게 됐다"일 수 있다.

## 왜 학습 곡선(`return_mean`)으로 판정하지 않는가

이 프로젝트에서 이미 두 번 밟은 함정이다. 학습 중 `return_mean` 은 **확률적 정책**의
값이라 결정론적 성능을 크게 과소평가한다(v1 실측: 학습 중 ~20 vs 결정론적 45.1).
v2·v3·v4 를 곡선만 보고 중단해 낭비했다. 그래서 판정은 항상 체크포인트를 결정론적으로
평가해서 한다 — 이 스크립트가 그것을 계열로 자동화한 것이다.

## 지표

**슬립을 정본으로 본다** — 특히 **최악값**이다. 게이트 2에서 확인했듯 판정을 지탱하는
것은 평균이 아니라 최악값이고, FOUP 처럼 무거운 물체에서는 "가끔 크게 미끄러진다"가
치명적이다. 거리 기준은 물체 크기에 의존하므로 참고로만 찍는다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate4_dr_recovery.py --run dg5f_grasp_dr2 --start superdex/results/dg5f_grasp_v8_iter0300
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate4_dr_recovery.py --run dg5f_grasp_dr2 --start superdex/results/dg5f_grasp_v8_iter0300
```

`--run` 은 결과 폴더 이름이고 `<run>_iter####` 체크포인트를 자동으로 모은다.
`--start` 는 이어받기 시작점(= DR 학습 0 스텝 지점)이며 비교 기준으로 함께 평가한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402

# 학습에 쓴 DR 범위와 **같아야** 한다. 다르면 "회복했는가"를 다른 과제로 묻는 셈이다.
# gate4_dr_sweep.py 의 2단계와 같은 값이다 — 두 스크립트가 같은 사실을 말하도록 여기에
# 명시적으로 적고, 바꿀 때 함께 바꾼다.
DR_ON = {"dr_mass_range": [0.25, 4.0], "dr_friction_range": [0.10, 0.70]}


def evaluate(ckpt: Path, env_config: dict, episodes: int, seed0: int) -> dict:
    """체크포인트 하나를 결정론적으로 평가한다."""
    from dg5f_grasp_env import Dg5fGraspEnv
    from eval_policy import load_policy

    env = Dg5fGraspEnv(env_config)
    policy = load_policy(ckpt, env.joint_low, env.joint_high)

    rows = []
    for ep in range(episodes):
        obs, _ = env.reset(seed=seed0 + ep)
        info = {}
        for _ in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            if term or trunc:
                break
        rows.append({
            "tips": int(info.get("tips_touching", 0)),
            "dist": float(info.get("dist", float("nan"))),
            "slip": float(info.get("slip", float("nan"))),
            "established": bool(info.get("grasp_established", False)),
        })
    min_tips, hold_radius = env.min_tips, env.hold_radius
    env.close()

    est = np.array([r["established"] for r in rows])
    tips_ok = np.array([r["tips"] >= min_tips for r in rows])
    dist_ok = np.array([r["dist"] < hold_radius for r in rows])
    slips = np.array([r["slip"] for r in rows], dtype=float)
    ok = est & np.isfinite(slips)
    slip_est = slips[ok]
    return {
        "established": float(est.mean()),
        "slip_med": float(np.median(slip_est)) if slip_est.size else float("nan"),
        "slip_max": float(slip_est.max()) if slip_est.size else float("nan"),
        # 슬립 기준 성공: 종료 시 지문 조건 + 슬립이 허용치 이내 (게이트 2 정본 기준)
        "slip_success": float(
            (tips_ok & ok & (slips < SLIP_TOL)).mean()
        ),
        "dist_success": float((tips_ok & dist_ok).mean()),
    }


SLIP_TOL = 0.03  # 게이트 2와 같은 허용 변위 [m]. 게이트 0 스크립트 파지는 0.0013 이었다


def collect_checkpoints(run: str, start: Path | None) -> list[tuple[str, Path]]:
    """(레이블, 경로) 목록. `<run>_iter####` 를 번호순으로 모으고 시작점을 앞에 둔다."""
    results_dir = Path(cfg.SUPERDEX_RESULTS_DIR)
    found = []
    for p in sorted(results_dir.glob(f"{run}_iter*")):
        m = re.search(r"_iter(\d+)$", p.name)
        if m and p.is_dir():
            found.append((int(m.group(1)), p))
    found.sort()
    out = []
    if start is not None:
        out.append(("시작(DR 0스텝)", start))
    out += [(f"iter{n:04d}", p) for n, p in found]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 4 DR 회복 곡선")
    ap.add_argument("--run", default="dg5f_grasp_dr2", help="결과 폴더 이름 접두사")
    ap.add_argument("--start", default=None,
                    help="이어받기 시작점 체크포인트 (DR 학습 0 스텝 지점)")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--env-config", default='{"episode_seconds": 1.0}',
                    help="DR 외의 환경 설정. 학습 때와 같아야 한다")
    args = ap.parse_args()

    base_config = json.loads(args.env_config)
    for k in DR_ON:
        if k in base_config:
            sys.exit(f"--env-config 에 {k} 를 넣지 마라 — 이 스크립트가 켜고 끈다.")

    start = None
    if args.start:
        start = Path(args.start)
        if not start.is_absolute():
            start = REPO_ROOT / start
        if not start.is_dir():
            sys.exit(f"시작 체크포인트가 없다: {start}")

    ckpts = collect_checkpoints(args.run, start)
    if not ckpts:
        sys.exit(f"체크포인트를 찾지 못했다: {cfg.SUPERDEX_RESULTS_DIR}/{args.run}_iter*")

    print(f"=== 게이트 4 DR 회복 곡선: {args.run} ===")
    print(f"체크포인트 {len(ckpts)}개 × 조건 2개 × {args.episodes} 에피소드")
    print(f"DR 조건: {DR_ON}")
    print(f"슬립 허용치: {SLIP_TOL} m\n")

    rows = []
    for label, path in ckpts:
        on = evaluate(path, {**base_config, **DR_ON}, args.episodes, args.seed0)
        off = evaluate(path, dict(base_config), args.episodes, args.seed0)
        rows.append((label, on, off))
        print(f"{label:<16} DR켬 성립 {on['established']:.0%} 슬립최대 {on['slip_max']:.4f} "
              f"슬립기준 {on['slip_success']:.0%}  |  "
              f"DR끔 슬립최대 {off['slip_max']:.4f} 슬립기준 {off['slip_success']:.0%}")

    print()
    print("=" * 88)
    print(f"{'체크포인트':<16} | {'DR 켠 조건':^33} | {'DR 끈 조건':^30}")
    print(f"{'':<16} | {'성립':>6} {'슬립중앙':>9} {'슬립최대':>9} {'슬립기준':>6} | "
          f"{'성립':>6} {'슬립최대':>9} {'슬립기준':>6}")
    for label, on, off in rows:
        print(f"{label:<16} | {on['established']:>5.0%} {on['slip_med']:>9.4f} "
              f"{on['slip_max']:>9.4f} {on['slip_success']:>5.0%} | "
              f"{off['established']:>5.0%} {off['slip_max']:>9.4f} "
              f"{off['slip_success']:>5.0%}")
    print("=" * 88)

    first, last = rows[0], rows[-1]
    print("\n판정 — 판정을 지탱하는 것은 평균이 아니라 **최악값**이다 (게이트 2 원칙):")

    d_on = last[1]["slip_max"] - first[1]["slip_max"]
    print(f"\n1) 회복했는가 (DR 켠 조건 최악 슬립): "
          f"{first[1]['slip_max']:.4f} -> {last[1]['slip_max']:.4f} ({d_on:+.4f} m)")
    if last[1]["slip_max"] < first[1]["slip_max"] * 0.7:
        print("   -> **회복 중.** 최악 슬립이 30% 이상 줄었다")
    elif last[1]["slip_max"] <= first[1]["slip_max"] * 1.1:
        print("   -> **정체.** 이 예산에서는 회복되지 않았다 — 아래 해석 두 가지를 보라")
    else:
        print("   -> **악화.** DR 학습이 오히려 나쁘게 만들었다")

    d_off = last[2]["slip_max"] - first[2]["slip_max"]
    print(f"\n2) 원래 성능을 깎았는가 (DR 끈 조건 최악 슬립): "
          f"{first[2]['slip_max']:.4f} -> {last[2]['slip_max']:.4f} ({d_off:+.4f} m)")
    if last[2]["slip_max"] > first[2]["slip_max"] * 1.5:
        print("   -> ⚠️ **깎였다.** 일반화를 얻고 기준 조건을 잃은 것이므로 순이득이 아니다")
    else:
        print("   -> 유지됐다")

    print("\n⚠️ 정체로 나왔다면 해석이 **두 가지**다. 하나로 단정하지 마라:")
    print("   (a) 샘플이 더 필요하다 — 이터레이션을 늘려 재확인")
    print("   (b) DR 범위가 비현실적이다 — 질량 ×4 는 2.2 kg 이고, DG-5F-M 의 실제")
    print("       파지력 상한은 아직 미확정이다(U8). 손이 물리적으로 못 드는 무게라면")
    print("       학습으로 풀리지 않는 과제를 푸는 중인 것이다 (게이트 2 발견 6과 같은 함정)")


if __name__ == "__main__":
    main()
