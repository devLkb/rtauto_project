# -*- coding: utf-8 -*-
"""`spawn_mode="workspace"` 판정 — 물체별 사람 상수 없이 지면 위 무작위 배치가 성립하는가.

기존 `place` 는 **물체마다 사람이 맞춘 손바닥 기준 offset** 이었다. 게이트 4 에서 이 값이
성공을 지배했고(paper_cup 은 배치만 바꿔 30 % -> 100 %), 범용 파지로 목적이 바뀐 뒤로는
고쳐야 할 결함이다(로드맵 v17). workspace 모드는 그 상수를 없애고 물체를 지면 위
무작위 위치에 놓는다 — 대신 팔이 스스로 접근해야 한다.

이 스크립트가 판정하는 것:

1. **안착 높이가 실측된다** — 물체가 지면에 붙어 있고 파묻히거나 떠 있지 않다.
2. **스폰이 도달 가능 범위 안이다** — 팔 FK 로 측정한 envelope 밖으로 나가지 않는다.
3. **커리큘럼이 단조롭다** — spawn_radius_frac 을 올리면 스폰 거리가 실제로 멀어진다.
4. **리셋 직후 즉시 낙하 종료가 나지 않는다** — 절대 상수 0.25 m 를 그대로 쓰면
   먼 스폰이 첫 스텝에서 종료돼 학습이 시작조차 못 한다. 이걸 막았는지 본다.
5. **palm 모드는 영향받지 않는다** — 기존 게이트 0·2·4 재현 조건 보존.

실행 (bash, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/smoke_workspace_spawn.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))

from dg5f_grasp_env import (  # noqa: E402
    Dg5fGraspEnv, SPAWN_MODE_PALM, SPAWN_MODE_WORKSPACE,
)

_fail = 0


def check(label, value, ok, expect):
    global _fail
    mark = "통과" if ok else "실패"
    if not ok:
        _fail += 1
    print(f"  {mark}  {label:34s} {value}   (기대 {expect})")


def main():
    ap = argparse.ArgumentParser(description="workspace 스폰 판정")
    ap.add_argument("--episodes", type=int, default=10)
    args = ap.parse_args()

    print("=== workspace 스폰 smoke ===")
    env = Dg5fGraspEnv({"control_mode": "arm_hand26",
                        "spawn_mode": SPAWN_MODE_WORKSPACE})
    try:
        print(f"실측 안착높이   : {env._rest_z:.4f} m")
        print(f"실측 도달범위   : 샘플링 [{env._reach_lo:.3f}, {env._reach_hi:.3f}] m / "
              f"최대 {env._reach_max:.3f} m (베이스 xy={np.round(env._base_xy, 3)})")
        print("  참고: UR16e 스펙 리치는 900 mm — 측정 상한이 이 값에 가까워야 한다.")

        # 1. 안착 높이가 지면 위 유한한 값인가
        check("안착높이 > 0 (파묻히지 않음)", f"{env._rest_z:.4f} m",
              env._rest_z > 0.0, "> 0")
        check("안착높이 < 0.3 (떠 있지 않음)", f"{env._rest_z:.4f} m",
              env._rest_z < 0.3, "< 0.3 m")

        # 2·3. 커리큘럼 단조성 + 도달범위 준수
        medians = []
        for frac in (0.0, 0.5, 1.0):
            env.spawn_radius_frac = frac
            dists, radii, zs = [], [], []
            for k in range(args.episodes):
                env.reset(seed=4000 + k)
                pos = np.asarray(env.block.get_root_transform().translation, float)
                dists.append(env._spawn_dist)
                radii.append(float(np.linalg.norm(pos[:2] - env._base_xy)))
                zs.append(float(pos[2]))
            medians.append(float(np.median(dists)))
            # 판정 기준은 분위수 상한(_reach_hi)이 아니라 **실측 최대 도달거리**다.
            # frac=0 의 앵커는 팔 현재 자세의 FK 위치라 분위수 상한을 넘을 수 있는데,
            # 그건 도달 불가가 아니라 분위수가 실제 최대를 과소평가한 것뿐이다.
            tol = 1e-6 + env.place_jitter * 2
            check(f"frac={frac:.1f} 스폰 반경 <= 실측 최대도달",
                  f"max {max(radii):.3f} m",
                  max(radii) <= env._reach_max + tol, f"<= {env._reach_max + tol:.3f} m")
            check(f"frac={frac:.1f} 지면 안착 z 일정",
                  f"{np.mean(zs):.4f} m",
                  float(np.ptp(zs)) < 1e-6, "분산 ~0")
        check("커리큘럼 단조 증가", f"{[round(m,3) for m in medians]}",
              medians[0] < medians[1] < medians[2], "frac 클수록 멀어짐")

        # 4. 리셋 직후 즉시 낙하 종료가 나면 안 된다 (먼 스폰에서 특히)
        env.spawn_radius_frac = 1.0
        insta = 0
        for k in range(args.episodes):
            env.reset(seed=9100 + k)
            hold = np.asarray(
                [(lo + hi) / 2 for lo, hi in zip(env.action_space.low,
                                                 env.action_space.high)],
                dtype=np.float32)
            term = False
            for _ in range(env.grace_steps + 5):     # 중력이 켜지는 시점을 넘겨서 본다
                _, _, term, trunc, _ = env.step(hold)
                if term or trunc:
                    break
            insta += int(term)
        check("중력 직후 즉시 낙하종료", f"{insta}/{args.episodes}",
              insta == 0, "0 건")

        # 5. 접근 shaping 이 **정책 불변**인가 — 이론값과 수치로 대조한다.
        #
        # potential-based shaping 의 정리(Ng et al. 1999)는 "할인 리턴이 -Phi(s0) 만큼만
        # 달라진다"는 것이다. 같은 궤적을 shaping 켜고/끄고 돌려 **할인** 리턴 차이를 재면
        # 이론값과 맞아야 한다:
        #     차이 = w * ( -Phi(s0) + gamma^T * Phi(s_T) )
        # 종료(낙하)로 끝나면 흡수 상태라 Phi(s_T)=0, 시간 초과로 끝나면 Phi(s_T)=-dist_T 다.
        # ⚠️ **할인하지 않은 단순 합으로 재면 이 검사는 통과하지 않는다** — 그게 바로
        # gamma 를 맞춰야 하는 이유이고, 2026-09-14 에 고친 결함이다.
        g = env.shaping_gamma
        worst = 0.0
        for k in range(args.episodes):
            rets, ends = {}, {}
            for w in (0.0, 1.0):
                env.approach_shaping = w
                env.reset(seed=7000 + k)
                rng = np.random.default_rng(7000 + k)
                ret, t = 0.0, 0
                for t in range(env.max_steps):
                    a = rng.uniform(env.action_space.low, env.action_space.high).astype(np.float32)
                    _, r, term, trunc, info = env.step(a)
                    ret += (g ** t) * r
                    if term or trunc:
                        break
                rets[w] = ret
                ends[w] = (t, term, float(info["dist"]), env._spawn_dist)
            steps_t, term_t, dist_t, d0 = ends[1.0]
            phi_T = 0.0 if term_t else -dist_t
            expect = d0 + (g ** (steps_t + 1)) * phi_T
            worst = max(worst, abs((rets[1.0] - rets[0.0]) - expect))
        env.approach_shaping = 1.0
        check("shaping 이 할인 리턴을 -Phi(s0) 만큼만 바꾼다", f"최대 오차 {worst:.2e}",
              worst < 1e-6, "< 1e-6")
    finally:
        env.close()

    # 5. palm 모드 보존 — 기존 기본값이 그대로인지
    env2 = Dg5fGraspEnv({"control_mode": "arm_hand26"})
    try:
        check("기본 spawn_mode 는 palm", env2.spawn_mode,
              env2.spawn_mode == SPAWN_MODE_PALM, SPAWN_MODE_PALM)
        check("palm 모드 접근 shaping 꺼짐", env2.approach_shaping,
              env2.approach_shaping == 0.0, "0.0")
    finally:
        env2.close()

    if _fail:
        print(f"\n=== workspace 스폰 smoke: 실패 {_fail}건 ===")
        sys.exit(1)
    print("\n=== workspace 스폰 smoke: 통과 ===")


if __name__ == "__main__":
    main()
