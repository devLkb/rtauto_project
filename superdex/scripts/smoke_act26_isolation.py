# -*- coding: utf-8 -*-
"""act26 결합 환경의 리셋·분리 구동 smoke 검사.

UR16e 6축과 DG5F 20축이 하나의 26차원 절대 목표각 배열에서 각각의 슬롯만 실제로
움직이는지 수치로 판정한다. 대상 물체·보상·성공 판정은 여기서 바꾸지 않는다.

실행 (bash, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/smoke_act26_isolation.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))

import rtauto_config as cfg  # noqa: E402  (환경의 경로 정본)
import superdex.physics as physics  # noqa: E402


def joint_pose(env) -> np.ndarray:
    """현재 actor 관절각을 action 배열과 같은 순서로 읽는다."""
    pose = physics.DynamicArrayReal(env.n_dofs)
    env.actor.get_articulated_pose(pose)
    return np.asarray([float(v) for v in pose], dtype=np.float64)


def moved_target(env, before: np.ndarray, dof: int) -> np.ndarray:
    """현재 자세에서 충분히 떨어진, 해당 관절 한계 안의 절대 목표각 하나를 만든다."""
    low, high = float(env.joint_low[dof]), float(env.joint_high[dof])
    target = before.copy()
    candidate = low + 0.70 * (high - low)
    if abs(candidate - before[dof]) < 0.10 * (high - low):
        candidate = low + 0.30 * (high - low)
    target[dof] = candidate
    return target


def drive(env, action: np.ndarray, steps: int) -> np.ndarray:
    for _ in range(steps):
        _, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            raise RuntimeError("분리 구동 검사 도중 환경이 일찍 끝났다")
    return joint_pose(env)


def check(label: str, value: float, predicate: bool, requirement: str) -> None:
    print(f"{label:<12}: {value:.6e} rad  ({requirement})")
    if not predicate:
        raise RuntimeError(f"{label} 판정 실패: {value:.6e} rad")


def main() -> None:
    ap = argparse.ArgumentParser(description="UR16e+DG5F act26 분리 구동 smoke")
    ap.add_argument("--steps", type=int, default=120, help="각 단독 명령의 물리 스텝 수")
    ap.add_argument("--min-motion", type=float, default=1e-3,
                    help="명령한 관절 묶음의 최소 실제 이동 [rad]")
    ap.add_argument("--isolation-tol", type=float, default=2e-4,
                    help="명령하지 않은 관절 묶음의 최대 허용 이동 [rad]")
    args = ap.parse_args()

    if args.steps <= 0:
        sys.exit("--steps 는 양수여야 한다")

    from dg5f_grasp_env import Dg5fGraspEnv

    env = Dg5fGraspEnv({
        "control_mode": "arm_hand26",
        "physics_threads": 0,
        "episode_seconds": 2.0,
        "grace_steps": args.steps + 1,
        "place_jitter": 0.0,
        "start_frac": 0.0,
        "action_smooth": 1.0,
        # 큰 관절 목표에도 솔버 경고 없이 실제 응답을 볼 수 있는 smoke 전용 이득이다.
        "stiffness": 1.0e3,
        "damping": 1.0e2,
    })
    try:
        obs, _ = env.reset(seed=20260910)
        root_dofs = env.actor.get_articulated_shape_info().dof_info[0].get_size()
        if obs.shape != (77,) or env.observation_space.shape != (77,):
            raise RuntimeError(f"관찰 77차원 계약 불일치: reset={obs.shape}, space={env.observation_space.shape}")
        if env.action_space.shape != (26,) or env.n_dofs != 26:
            raise RuntimeError(f"행동 26차원 계약 불일치: action={env.action_space.shape}, dof={env.n_dofs}")
        if root_dofs != 0:
            raise RuntimeError(f"베이스가 용접되지 않았다: root DOF {root_dofs}")

        print("=== act26 결합 환경 smoke ===")
        print(f"모드/관찰/행동: {env.control_mode} / {obs.shape[0]} / {env.action_space.shape[0]}")
        print(f"root DOF       : {root_dofs} (0 = 베이스 용접)")
        print(f"액션 0..5      : {list(env.dof_names[:6])}")
        print(f"액션 6..25     : {list(env.dof_names[6:])}")

        arm_before = joint_pose(env)
        arm_action = arm_before.copy()
        arm_index = int(env.arm_dofs[0])
        arm_action[arm_index] = moved_target(env, arm_before, arm_index)[arm_index]
        arm_after = drive(env, arm_action, args.steps)
        arm_moved = float(np.max(np.abs(arm_after[env.arm_dofs] - arm_before[env.arm_dofs])))
        hand_still = float(np.max(np.abs(arm_after[env.hand_dofs] - arm_before[env.hand_dofs])))
        print("[팔 액션만]")
        check("팔 최대 이동", arm_moved, arm_moved >= args.min_motion, f">= {args.min_motion:.1e}")
        check("손 최대 이동", hand_still, hand_still <= args.isolation_tol, f"<= {args.isolation_tol:.1e}")

        env.reset(seed=20260910)
        hand_before = joint_pose(env)
        hand_action = hand_before.copy()
        hand_index = int(env.flex_dofs[0])
        if hand_index not in env.hand_dofs:
            raise RuntimeError(f"손 굽힘 DOF가 hand 슬롯이 아니다: {hand_index}")
        hand_action[hand_index] = moved_target(env, hand_before, hand_index)[hand_index]
        hand_after = drive(env, hand_action, args.steps)
        arm_still = float(np.max(np.abs(hand_after[env.arm_dofs] - hand_before[env.arm_dofs])))
        hand_moved = float(np.max(np.abs(hand_after[env.hand_dofs] - hand_before[env.hand_dofs])))
        print("[손 액션만]")
        check("손 최대 이동", hand_moved, hand_moved >= args.min_motion, f">= {args.min_motion:.1e}")
        check("팔 최대 이동", arm_still, arm_still <= args.isolation_tol, f"<= {args.isolation_tol:.1e}")

        print("=== act26 smoke: 통과 ===")
    finally:
        env.close()


if __name__ == "__main__":
    main()
