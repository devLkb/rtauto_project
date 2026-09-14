# -*- coding: utf-8 -*-
"""물체별 오라클 탐색 스윕 — **이 물체가 이 손으로 애초에 잡히는가**를 물체마다 판정한다.

docs/SUPERDEX_POC_PLAN.md §0 인수인계의 "물체 다양성 확보" 항목이다. 공식 asset 전수
조사(`survey_object_assets.py`)에서 확실히 쓸 수 있는 형상은 3종뿐이었고, `shape_box`
도형 12종(3.8~5.0 cm)은 **미검증 구간**으로 남았다 — 2.5 cm 블록은 3지 접촉이 기하적으로
성립하지 않았고(게이트 2) 9.3 cm 컵은 성립했지만, 그 사이는 아무도 재지 않았다.

방법은 `gate2_oracle_search.py` 와 같다. 정책을 학습하지 않고 개루프 폐쇄 궤적을
그리드로 훑어, 각 시드에 성공 궤적이 **존재하는지** 센다. 학습과 무관하게 과제 자체의
가해성을 가르므로 싸고 결정적이다.

## 이 스윕이 gate2_oracle_search.py 와 다른 점 두 가지

1. **조립 프리팹에서 조각 하나만 쓴다** (`object_actor`). `shape_box` 는 도형 12조각 +
   몸체 + 뚜껑이 한 프리팹이다. 그대로 넣으면 env 가 첫 조각을 집고 나머지 13개를 같은
   자리에 겹쳐 둔다.
2. **물체 기준점을 질량중심으로 둔다** (`object_ref="com"`). actor root 는 메시 원점이라
   asset 마다 제각각이다 — shape_box 조각 대부분은 한쪽 면(질량중심에서 2 cm), block_red 는
   모서리다. root 기준이면 4 cm 조각을 중심이 2 cm 어긋난 채 시험하게 되고, 그건
   paper_cup 에서 이미 겪은 **배치 confound** 다(배치만 바꿔 30 % -> 100 %).

대조군은 기존 조건(root)으로 함께 돌려 이 스윕의 눈금을 게이트 2 실측에 맞춘다:
duck_lamp(성공 궤적 시드 7/10)·block_red(1/10). block_red 는 com 으로도 돌려,
"2.5 cm 는 기하적으로 불가"라는 판정이 모서리 원점 배치 탓이었는지도 가른다.

## 실행

터미널 1 (bash, 리포 루트, 약 1시간 — 끝날 때까지 띄워 둔다):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/object_oracle_sweep.py
```

터미널 1 (PowerShell, 리포 루트):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/object_oracle_sweep.py
```

한 물체만: `--only square,star`. 대조군 생략: `--no-controls`.
정상이면 물체마다 `[square] 성공 궤적 시드 7/10 ...` 한 줄이 찍히고, 끝에 표와 판정이 나온다.
결과 JSON 은 `superdex/results/object_oracle_<시각>.json` 에 남는다(git 비추적).
멈추려면 `Ctrl+C`.
"""
from __future__ import annotations

import argparse
import itertools
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

SHAPE_BOX = "prefabs/shape_box/shape_box.mochi_prefab"
SHAPE_BOX_PIECES = ("cross", "triangle", "square", "trapezoid", "rectangle", "pentagon",
                    "parallelogram", "octagon", "hexagon", "ellipse", "diamond", "star")

# (표시이름, 프리팹, actor, 기준점, 게이트 2 실측 — 성공 궤적 시드 수 / 10)
CONTROLS = (
    ("duck_lamp[root]", "prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab", None, "root", 7),
    ("block_red[root]", "prefabs/box_and_blocks/block_red.mochi_prefab", None, "root", 1),
    ("block_red[com]", "prefabs/box_and_blocks/block_red.mochi_prefab", None, "com", None),
)

# gate2_oracle_search.py 와 같은 궤적 그리드. 폐쇄율·도달 스텝·추가 조임 여유.
FINAL = (0.6, 0.8, 1.0)
RAMP = (30, 60)
EXTRA = (0.0, 0.1)


def sweep_one(env_config, seeds, seed0, place_xs):
    """물체 하나. 시드마다 그리드 전체를 돌려 성공 궤적이 있는지 센다."""
    from dg5f_grasp_env import Dg5fGraspEnv
    from gate2_oracle_search import run_trajectory

    env = Dg5fGraspEnv(env_config)
    # f=1.0 이면 extra 0.0/0.1 이 같은 궤적이 된다 — 중복 제거(gate2_oracle_search 와 같은 이유)
    grid = list(dict.fromkeys(
        (f, r, min(1.0, f + e), px)
        for f, r, e, px in itertools.product(FINAL, RAMP, EXTRA, place_xs)
    ))
    per_traj = {g: 0 for g in grid}
    solvable, tips_best, drops, steps = 0, [], 0, 0
    t0 = time.perf_counter()
    try:
        mass = float(env.block.get_mass())
        for i in range(seeds):
            seed = seed0 + i
            ok, best = False, 0
            for g in grid:
                r = run_trajectory(env, seed, *g)
                steps += env.max_steps
                ok |= r["success"]
                per_traj[g] += int(r["success"])
                best = max(best, r["tips_best"])
                drops += int(r["dropped"])
            solvable += int(ok)
            tips_best.append(best)
        min_tips = env.min_tips
    finally:
        env.close()
        try:
            import superdex.physics as physics
            physics.destroy_scene(env.scene)   # 물체마다 씬이 쌓이지 않게
        except Exception:
            pass
    top = max(per_traj.items(), key=lambda kv: kv[1])
    return {
        "solvable": solvable, "seeds": seeds, "grid": len(grid),
        "best_traj": list(top[0]), "best_traj_succ": top[1],
        "tips_best_median": float(np.median(tips_best)), "tips_best_max": int(max(tips_best)),
        "drop_rate": drops / max(1, seeds * len(grid)), "min_tips": min_tips,
        "mass_kg": mass, "steps": steps, "seconds": time.perf_counter() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="물체별 오라클 탐색 스윕 (파지 가해성)")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=9000,
                    help="gate2_oracle_search.py 와 같은 시드 대역")
    ap.add_argument("--episode-seconds", type=float, default=1.0)
    ap.add_argument("--place-x", default="0.02,0.03,0.04",
                    help="손바닥 앞 거리 후보(콤마 구분). 작은 물체는 손바닥에 더 가까워야 할 수 있다")
    ap.add_argument("--ref", default="com", choices=("com", "root"),
                    help="shape_box 조각의 물체 기준점")
    ap.add_argument("--only", default=None, help="조각 이름만 (예: square,star). 대조군은 --no-controls")
    ap.add_argument("--no-controls", action="store_true")
    args = ap.parse_args()

    pieces = SHAPE_BOX_PIECES
    if args.only:
        wanted = args.only.split(",")
        bad = [w for w in wanted if w not in SHAPE_BOX_PIECES]
        if bad:
            sys.exit(f"없는 조각: {bad}. 가능한 값: {list(SHAPE_BOX_PIECES)}")
        pieces = tuple(p for p in SHAPE_BOX_PIECES if p in wanted)

    targets = [] if args.no_controls else list(CONTROLS)
    targets += [(f"{p}[{args.ref}]", SHAPE_BOX, p, args.ref, None) for p in pieces]
    place_xs = [float(v) for v in args.place_x.split(",")]

    print(f"=== 물체별 오라클 스윕: {len(targets)}개 대상 × 시드 {args.seeds} "
          f"({args.seed0}..{args.seed0 + args.seeds - 1}) ===")
    print(f"그리드: final {FINAL} × ramp {RAMP} × extra {EXTRA} × place_x {place_xs}")
    print("조건: control_mode=hand20 (게이트 2 와 같은 손 단독 기준선), 리셋 회전 identity\n")

    results = []
    for label, prefab, actor, ref, gate2 in targets:
        c = {"control_mode": "hand20", "episode_seconds": args.episode_seconds,
             "object_prefab": prefab, "object_ref": ref}
        if actor is not None:
            c["object_actor"] = actor
        m = sweep_one(c, args.seeds, args.seed0, place_xs)
        m.update(label=label, prefab=prefab, actor=actor, ref=ref, gate2_solvable=gate2)
        results.append(m)
        ref_note = f"  (게이트 2 실측 {gate2}/10)" if gate2 is not None else ""
        bt = m["best_traj"]
        print(f"[{label}] 성공 궤적 시드 {m['solvable']}/{m['seeds']}{ref_note}  "
              f"최선 고정궤적 {m['best_traj_succ']}/{m['seeds']} (f={bt[0]}/ramp={bt[1]}/x={bt[3]})  "
              f"tips_best 중앙 {m['tips_best_median']:.0f}/max {m['tips_best_max']}  "
              f"낙하 {m['drop_rate']:.0%}  {m['mass_kg']*1000:.1f} g  "
              f"{m['steps'] / m['seconds']:.0f} steps/s", flush=True)

    print("\n" + "=" * 88)
    print(f"{'대상':<22} {'성공시드':>8} {'최선고정':>8} {'tips중앙':>8} {'tips최대':>8} {'낙하':>6}  판정")
    for m in results:
        frac = m["solvable"] / max(1, m["seeds"])
        verdict = ("잡힌다" if frac >= 0.7 else
                   "기하적으로 어렵다" if frac <= 0.3 else "경계 — 성공 상한이 낮다")
        print(f"{m['label']:<22} {m['solvable']:>5}/{m['seeds']:<2} "
              f"{m['best_traj_succ']:>5}/{m['seeds']:<2} {m['tips_best_median']:>8.0f} "
              f"{m['tips_best_max']:>8d} {m['drop_rate']:>6.0%}  {verdict}")
    print("=" * 88)
    print("판정 경계는 gate2_oracle_search.py 와 같다: ≥70 % 잡힌다 / ≤30 % 기하적으로 어렵다.")

    out = REPO_ROOT / "superdex" / "results" / f"object_oracle_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"args": vars(args), "results": results}, ensure_ascii=False, indent=2))
    print(f"\n결과 JSON: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
