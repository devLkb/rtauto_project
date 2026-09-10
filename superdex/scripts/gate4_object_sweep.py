# -*- coding: utf-8 -*-
"""게이트 4 — 물체 일반화 스윕. 학습에 쓰지 않은 물체로 정책이 넘어가는가.

게이트 4의 다른 축이다. `gate4_dr_sweep.py` 가 **같은 물체의 물성**(질량·마찰)을 흔들었다면
여기서는 **물체 자체**를 바꾼다. 계획 §5 게이트 4의 "실린더 + 산업 물체 1종 추가"가 이것이다.

## 왜 크기(scale) 무작위화 대신 물체 교체인가

기하를 바꾸려면 프리팹을 다시 올려야 해서 **리셋마다** 하면 비용이 자릿수로 뛴다. 물체
교체는 env 하나당 한 번만 올리면 되므로, 같은 질문("기하 변화에 견디는가")을 훨씬 싸게
묻는다. 다만 이 방식은 **에피소드 안에서** 기하가 고정되므로 진짜 DR 이 아니라
**일반화 평가**다 — 학습에 쓰려면 물체를 섞어 돌리는 별도 작업이 필요하다.

## ⚠️ 결과를 읽을 때 반드시 함께 볼 것 — 실패에 두 종류가 있다

1. **기하적으로 불가능한 실패.** 게이트 2 발견 6에서 확인했다: 2.5 cm 블록은 사람 크기
   손에 너무 작아 **3지 접촉이 성립하지 않는다**(오라클 그리드 탐색에서 성공 궤적이
   존재하는 시드 1/10). 작은 물체가 실패하는 것은 정책 일반화 실패가 아니라 **과제가
   애초에 안 풀리는 것**이다. 그래서 작은 물체들을 **대조군으로 남겨 둔다** — 빼 버리면
   "큰 물체만 골랐다"가 되고, 넣고 실패로 세면 "일반화가 안 된다"는 오판이 된다.

2. **배치가 그 물체에 안 맞는 실패.** 스폰 오프셋 `place` 는 손바닥 좌표계 값이고
   duck_lamp 기준으로 잡혔다(0.04, 0, 0.04). 물체가 크게 다르면 이 값도 달라야 할 수
   있다. 기본값으로 실패한 물체는 **배치를 바꿔 재확인하기 전에는** "정책이 못 한다"고
   결론내지 마라 — `--only <물체> --place x,y,z` 로 한 물체만 다른 배치로 돌릴 수 있다.

## 지표

`hold_radius`(거리) 기준은 **물체 크기에 의존한다** — duck_lamp 은 반대각선이 약 8.9 cm 라
완벽한 파지에서도 6 cm 를 넘을 수 있다(§0 "계획 변경" 2번). 물체가 바뀌는 이 스윕에서는
거리 기준이 특히 무의미하므로 **슬립(물체 크기 무관)을 정본으로 본다.** 거리 기준은
참고로만 찍는다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate4_object_sweep.py --checkpoint superdex/results/dg5f_grasp_v8_iter0250
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate4_object_sweep.py --checkpoint superdex/results/dg5f_grasp_v8_iter0250
```

`--baseline` 으로 고정 폐쇄 기준선과 비교할 수 있다. DR 을 함께 켜려면 `--env-config`.
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

# 평가할 물체. AABB·질량은 게이트 2에서 실측한 값이다(dg5f_grasp_env.py 주석과 같은 출처).
#   (표시이름, prefab 상대경로, 설명, 손 크기에 대해 파지가 기하적으로 성립하는가)
OBJECTS = [
    ("duck_lamp", "prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab",
     "11.9×11.0×7.5 cm / 545 g — **학습에 쓴 물체**(기준)", True),
    ("paper_cup", "prefabs/paper_cups/paper_cup.mochi_prefab",
     "9.3×9.4×11.3 cm / 15 g — 원통형, 크기는 비슷한데 **36배 가볍다**", True),
    ("sphere", "prefabs/sphere/sphere.mochi_prefab",
     "3 cm / 10 g — 대조군(작다)", False),
    ("block_red", "prefabs/box_and_blocks/block_red.mochi_prefab",
     "2.5 cm / 15.6 g — 대조군(게이트 2에서 기하적 불가 확인)", False),
]


def run_object(env_config: dict, policy_spec, episodes: int, seed0: int):
    """물체 하나를 평가한다. (지표, 소요초, 스텝수)."""
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
    slip_est = slips[est & np.isfinite(slips)]
    # 솔버 실패를 정책 실패와 섞지 않는다 — gate4_dr_sweep 과 같은 이유.
    nonfinite = int((est & ~np.isfinite(slips)).sum() + (~np.isfinite(dists)).sum())
    return {
        "n": len(rows),
        "established": float(est.mean()),
        "tips_mean": float(np.mean([r["tips"] for r in rows])),
        "slip_med": float(np.median(slip_est)) if slip_est.size else float("nan"),
        "slip_max": float(slip_est.max()) if slip_est.size else float("nan"),
        "dist_success": float((tips_ok & dist_ok).mean()),
        "nonfinite": nonfinite,
    }, elapsed, steps


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 4 물체 일반화 스윕")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--slip-tol", type=float, default=0.03)
    ap.add_argument("--env-config", default='{"episode_seconds": 1.0}',
                    help="DR 등 나머지 환경 설정. 학습 때와 같아야 비교가 성립한다")
    ap.add_argument("--place", default=None,
                    help="모든 물체에 같은 스폰 오프셋 'x,y,z' 를 강제한다(손바닥 좌표계). "
                         "기본은 환경 기본값 — 물체별 조정은 위 docstring 경고 참고")
    ap.add_argument("--only", default=None,
                    help="쉼표로 구분한 물체 표시이름만 돌린다 (예: duck_lamp,paper_cup)")
    args = ap.parse_args()

    if not args.baseline and not args.checkpoint:
        sys.exit("--checkpoint 또는 --baseline 중 하나가 필요하다.")

    base_config = json.loads(args.env_config)
    if "object_prefab" in base_config:
        sys.exit("--env-config 에 object_prefab 를 넣지 마라 — 스윕이 물체마다 설정한다.")
    if args.place:
        base_config["place"] = [float(v) for v in args.place.split(",")]

    wanted = set(args.only.split(",")) if args.only else None
    objects = [o for o in OBJECTS if wanted is None or o[0] in wanted]
    if not objects:
        sys.exit(f"--only 에 맞는 물체가 없다. 가능한 값: {[o[0] for o in OBJECTS]}")

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

    print(f"=== 게이트 4 물체 일반화 스윕: {label} ===")
    print(f"에피소드 {args.episodes} × 물체 {len(objects)}  "
          f"(시드 {args.seed0}..{args.seed0 + args.episodes - 1}, 물체마다 동일)")
    print(f"환경 설정: {base_config}")
    print("정본 지표는 **슬립**이다 — 거리 기준은 물체 크기에 의존해 여기선 무의미하다.\n")

    results = []
    for name, prefab, desc, feasible in objects:
        c = dict(base_config)
        c["object_prefab"] = prefab
        print(f"[{name}] {desc}")
        m, elapsed, steps = run_object(c, policy_spec, args.episodes, args.seed0)
        m.update(name=name, feasible=feasible,
                 steps_per_s=steps / elapsed if elapsed > 0 else float("nan"))
        results.append(m)
        print(f"    성립 {m['established']:.0%}  지문평균 {m['tips_mean']:.2f}  "
              f"슬립 중앙 {m['slip_med']:.4f} 최대 {m['slip_max']:.4f}  "
              f"거리기준 {m['dist_success']:.0%}  비정상수치 {m['nonfinite']}")

    print()
    print("=" * 80)
    print(f"{'물체':<12} {'기하가능':>8} {'파지성립':>8} {'지문평균':>9} "
          f"{'슬립중앙':>10} {'슬립최대':>10} {'거리기준':>8} {'NaN':>5}")
    for m in results:
        print(f"{m['name']:<12} {'예' if m['feasible'] else '아니오':>8} "
              f"{m['established']:>7.0%} {m['tips_mean']:>9.2f} "
              f"{m['slip_med']:>10.4f} {m['slip_max']:>10.4f} "
              f"{m['dist_success']:>7.0%} {m['nonfinite']:>5d}")
    print("=" * 80)

    ref = next((m for m in results if m["name"] == "duck_lamp"), None)
    print("\n판정:")
    for m in results:
        if not m["feasible"]:
            print(f"  {m['name']}: 대조군 — 게이트 2에서 **기하적 불가**로 확인된 크기다. "
                  f"실패해도 일반화 실패가 아니다")
            continue
        if ref is None or m["name"] == "duck_lamp":
            continue
        d_est = m["established"] - ref["established"]
        r_slip = (m["slip_max"] / ref["slip_max"]) if ref["slip_max"] else float("nan")
        verdict = "일반화" if (d_est >= -0.1 and r_slip <= 1.5) else "열화"
        print(f"  {m['name']}: duck_lamp 대비 파지성립 {d_est:+.0%}, "
              f"최악 슬립 ×{r_slip:.2f}  -> **{verdict}**")

    bad = [m for m in results if m["nonfinite"]]
    if bad:
        print()
        print("⚠️ 비정상 수치(NaN/발산)가 나온 물체가 있다 — 그 물체의 열화는 정책 실패가")
        print("   아니라 물리 솔버 실패일 수 있다:")
        for m in bad:
            print(f"     {m['name']}: {m['nonfinite']}/{m['n']} 에피소드")

    print("\n⚠️ 기본 스폰 오프셋은 duck_lamp 기준(place=0.04,0,0.04)이다. 기하적으로 가능한")
    print("   물체가 실패했다면 **배치를 바꿔 재확인하기 전에는** 정책 탓으로 돌리지 마라")
    print("   — `--place x,y,z` 로 강제할 수 있다.")


if __name__ == "__main__":
    main()
