# -*- coding: utf-8 -*-
"""게이트 0 — DG5F 손 단독 asset 구조 조사 (headless, 학습 없음).

docs/SUPERDEX_POC_PLAN.md §5 게이트 0의 0-6/0-8 준비 단계다. 파지 테스트를 쓰기 전에
"이 손이 SuperDex 안에서 어떤 관절·링크·한계를 갖는지"를 실측해 둔다 — 파지 자세와
물체 배치가 전부 이 값에서 나온다.

동봉 예제는 physics.debugger.attach()로 GUI 디버거를 기다리며 블로킹한다. 이 스크립트는
붙지 않고 headless로 돌고, steps/sec까지 측정한다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/gate0_hand_probe.py
    python superdex/scripts/gate0_hand_probe.py --steps 4000
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·asset 위치의 유일한 출처 — 원칙 1)

# SuperDex는 asset 트리를 SUPERDEX_ASSETS_PATH 환경변수로 찾는다. import 전에 넣는다.
_assets = cfg.superdex_assets_path()
if _assets is None:
    sys.exit(
        "RTAUTO_SUPERDEX_REPO(또는 RTAUTO_SUPERDEX_ASSETS)가 .env에 없다.\n"
        "docs/SUPERDEX_POC_PLAN.md §11 0-5 참고."
    )
os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))

import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402
from superdex.physics.paths import resolve_asset  # noqa: E402


def describe(obj, keys):
    """알려진 속성만 안전하게 뽑는다 — 바인딩 필드명이 바뀌어도 죽지 않게."""
    out = {}
    for k in keys:
        if hasattr(obj, k):
            try:
                out[k] = getattr(obj, k)
            except Exception as exc:  # 바인딩이 던지는 경우
                out[k] = f"<{type(exc).__name__}>"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="DG5F 손 asset 구조 조사")
    ap.add_argument("--steps", type=int, default=2000, help="headless 스텝 수 (측정용)")
    ap.add_argument(
        "--threads",
        type=int,
        default=0,
        help="physics worker threads (0=단일, -1=자동). 기본 0으로 단일 env 속도를 잰다",
    )
    args = ap.parse_args()

    asset_rel = cfg.superdex_hand_asset()
    asset_path = resolve_asset(asset_rel)
    print(f"assets root : {_assets}")
    print(f"hand asset  : {asset_rel}")
    print(f"resolved    : {asset_path}")
    print(f"hand config : DG5F_HAND={cfg.DG5F_HAND}  DG5F_SHORT={cfg.DG5F_SHORT}")
    print(f"precision   : {'fp64' if physics.uses_double_precision() else 'fp32'}")
    print()

    physics.initialize(num_worker_threads=args.threads)
    scene = physics.create_scene("Gate0 Hand Probe")
    scene.set_gravity([0, 0, -9.81])

    prefab = robotics.load_bot_prefab_from_file(str(asset_path))
    print(f"=== prefab: {prefab.name} ===")
    print(f"links : {len(prefab.links)}")
    print(f"joints: {len(prefab.joints)}")
    print()

    print("=== 링크 ===")
    for i in range(len(prefab.links)):
        link = prefab.links[i]
        info = describe(link, ["name", "mass", "has_gravity"])
        print(f"  [{i:2d}] {info}")
    print()

    # 필드명은 실측 확인: min_limit / max_limit / effort_limit / limit_stiffness /
    # limit_damping / inertia / axis / parent_link_from_joint / friction / name / type.
    print("=== 움직이는 관절 (REVOLUTE) — 한계는 rad, 괄호는 deg ===")
    print(f"  {'dof':>3} {'name':<18} {'axis':<9} {'min':>9} {'max':>9} "
          f"{'min°':>7} {'max°':>7} {'effort':>8}")
    dof = 0
    movable = []
    for i in range(len(prefab.joints)):
        joint = prefab.joints[i]
        if getattr(joint, "type", None) != physics.ArticulatedJointType.REVOLUTE:
            continue
        # axis는 Real3. min_limit/max_limit/effort_limit도 축별 Real3라서 이 관절이 도는
        # 축 성분만 뽑는다 — 스칼라로 착각하면 float() 변환에서 죽는다(실측 확인).
        ax = [round(float(v), 0) for v in joint.axis]
        if 1.0 in ax:
            k, axis_s = ax.index(1.0), "xyz"[ax.index(1.0)]
        elif -1.0 in ax:
            k, axis_s = ax.index(-1.0), "-" + "xyz"[ax.index(-1.0)]
        else:
            k, axis_s = 0, "?"
        lo, hi = float(joint.min_limit[k]), float(joint.max_limit[k])
        eff_raw = getattr(joint, "effort_limit", None)
        try:
            eff = float(eff_raw[k]) if eff_raw is not None else float("nan")
        except TypeError:
            eff = float(eff_raw)
        print(f"  {dof:>3} {joint.name:<18} {axis_s:<9} {lo:>9.4f} {hi:>9.4f} "
              f"{lo * 57.29578:>7.1f} {hi * 57.29578:>7.1f} {eff:>8.3f}")
        movable.append((dof, joint.name, lo, hi))
        dof += 1
    print()
    print(f"움직이는(REVOLUTE) 관절 수 = {dof}")
    print()

    # 손가락별 묶음 — 파지 자세를 손가락 단위로 만들 때 쓴다.
    fingers = {}
    for d, name, lo, hi in movable:
        parts = name.split("_")
        if len(parts) >= 4:
            fingers.setdefault(parts[2], []).append(d)
    print("=== 손가락별 DOF (1 = 엄지) ===")
    for f in sorted(fingers):
        print(f"  finger {f}: dof {fingers[f]}")
    print()

    ctx = robotics.create_context()
    bot = robotics.create_bot(scene, prefab, ctx)
    actor = bot.get_articulated_actor()
    num_dofs = actor.get_num_dofs()
    num_root = actor.get_articulated_shape_info().dof_info[0].get_size()
    print(f"=== live bot: {bot.get_name()} ===")
    print(f"actor num_dofs : {num_dofs}")
    print(f"root dofs      : {num_root}  (0이면 world에 고정, 6이면 free-floating)")

    pose = physics.DynamicArrayReal(num_dofs)
    actor.get_articulated_pose(pose)
    print(f"default pose   : {[round(float(v), 4) for v in pose]}")
    print()

    # 바닥판 — 손이 떠 있는지 바닥에 놓이는지 확인용.
    ground = physics.create_plane_shape(normal=[0, 0, 1], distance=0)
    scene.create_rigid_actor(name="ground", shape=ground, is_static=True)

    # headless 측정. 컨트롤러 없이 순수 물리 스텝 비용을 잰다 (하한값).
    dt = 1.0 / cfg.SUPERDEX_SIM_HZ
    print(f"=== headless {args.steps} 스텝 ({cfg.SUPERDEX_SIM_HZ} Hz, threads={args.threads}) ===")
    t0 = time.perf_counter()
    for _ in range(args.steps):
        scene.step(dt)
    elapsed = time.perf_counter() - t0

    sps = args.steps / elapsed if elapsed > 0 else float("inf")
    print(f"wall clock     : {elapsed:.3f} s")
    print(f"steps/sec      : {sps:.1f}")
    print(f"realtime factor: {sps * dt:.2f}x  (1.0 = 실시간)")
    print(f"집계 추정      : {sps:.0f} x {cfg.SUPERDEX_ENV_RUNNERS} runner "
          f"= {sps * cfg.SUPERDEX_ENV_RUNNERS:.0f} steps/s")
    print()
    print("※ 컨트롤러·접촉 물체가 없는 하한값이다. 파지 테스트에서는 더 느려진다.")

    robotics.destroy_bot(scene, bot)
    physics.shutdown()


if __name__ == "__main__":
    main()
