# -*- coding: utf-8 -*-
"""**손끝(지문) 밖의 다른 부위가 물체를 떠받치고 있는지** 손끝 힘과 나란히 측정한다.

배경: `dg5f_grasp_env.py`의 성공 판정은 **손끝(TIP_LINKS) 5곳의 접촉력만** 읽는다
(`self.tip_actors` — env.py 503~516행). 엄지 뿌리 관절처럼 손끝이 아닌 부위는 애초에
힘을 잴 방법이 없다. 그래서 물체가 그런 부위에 끼여서 버티고 있어도, 손끝 3곳만
살짝 닿으면 "파지 성립"으로 기록된다 — 2026-09-22 사용자가 화면으로 본 것("엄지
1번 관절에 끼어 있다")이 이 맹점 때문일 가능성이 있다는 가설을 여기서 실측으로
확인한다.

이 스크립트는 **모든 손 링크**에 대해 `block.get_contact_force_from_actor_world()`를
불러(지문 5곳에만 쓰던 것과 같은 API), 학습된 정책이 실제로 어느 부위로 물체를
지탱하는지 매 스텝 기록한다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/diagnose_wedge_contact.py --object paper_cup ^
    --place 0.05,0.0,0.03 --place-rot 0.3826834323650898,0.0,0.0,0.9238795325112867
```

화면 출력 없이(뷰어 없이) 숫자만 찍는다 — 진단용이라 빠르게 여러 에피소드를 돌린다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401

PAPER_CUP_PREFAB = "prefabs/paper_cups/paper_cup.mochi_prefab"


def main() -> None:
    ap = argparse.ArgumentParser(description="손끝 밖 부위의 접촉력을 실측해 '관절 끼임' 가설을 확인한다")
    ap.add_argument("--checkpoint", default="superdex/results/dg5f_grasp_v8_iter0300")
    ap.add_argument("--object", default="paper_cup")
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--episode-seconds", type=float, default=1.0)
    ap.add_argument("--place", default=None, help="'x,y,z' — 손바닥 기준 물체 배치")
    ap.add_argument("--place-rot", default=None, help="'x,y,z,w' — 물체 방향 쿼터니언")
    ap.add_argument("--force-threshold", type=float, default=0.05,
                    help="이 힘[N] 이상이면 '닿아 있다'고 본다 (env의 tip_force_threshold와 같은 기준)")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv, TIP_LINKS
    from eval_policy import load_policy

    ckpt = Path(args.checkpoint)
    if not ckpt.is_absolute():
        ckpt = REPO_ROOT / ckpt
    if not ckpt.is_dir():
        sys.exit(f"체크포인트가 없다: {ckpt}")

    env_config = {
        "control_mode": "hand20",
        "episode_seconds": args.episode_seconds,
        "object_prefab": PAPER_CUP_PREFAB if args.object == "paper_cup" else args.object,
    }
    if args.place:
        env_config["place"] = [float(v) for v in args.place.split(",")]
    if args.place_rot:
        env_config["place_rot"] = [float(v) for v in args.place_rot.split(",")]

    env = Dg5fGraspEnv(env_config)
    policy = load_policy(ckpt, env.joint_low, env.joint_high)

    # --- 손의 모든 링크 actor를 이름으로 모은다 (지문 5곳만 모으던 env._init_와 같은 패턴) ---
    bot_name = env.bot.get_name()
    by_name = {}
    for h in env.actor.get_nested_link_actors():
        a = env.scene.get_actor(h)
        name = a.get_name()
        short = name[len(bot_name) + 1:] if name.startswith(bot_name + "/") else name
        by_name[short] = a

    tip_set = set(TIP_LINKS)
    # 지문이 아닌 손가락 관절 링크만 추린다 (팔레트·손바닥 등은 항상 물체와 가깝지
    # 않으므로 노이즈를 줄이려 "_1"~"_4" 접미사가 붙은 손가락 관절 링크만 본다).
    joint_links = sorted(
        n for n in by_name
        if n.startswith("dg5f_link_") and n not in tip_set
        and n.split("_")[-1] in ("1", "2", "3", "4")
    )
    print(f"측정 대상 비-지문 관절 링크 {len(joint_links)}개: {joint_links}")
    print(f"지문 링크 5개: {sorted(tip_set)}")
    print()

    def force_on(actor) -> float:
        try:
            f = np.asarray(env.block.get_contact_force_from_actor_world(actor), dtype=float)
            return float(np.linalg.norm(f))
        except Exception:
            return 0.0

    tip_actor_by_name = {ln: a for ln, a in zip(TIP_LINKS, env.tip_actors)}
    joint_actor_by_name = {ln: by_name[ln] for ln in joint_links}

    summary = []
    for ep in range(args.episodes):
        obs, _ = env.reset(seed=args.seed0 + ep)
        max_joint_force = {ln: 0.0 for ln in joint_links}
        max_tip_force = {ln: 0.0 for ln in TIP_LINKS}
        final_joint_force = {ln: 0.0 for ln in joint_links}
        final_tip_force = {ln: 0.0 for ln in TIP_LINKS}
        max_speed_after_grasp = 0.0
        grasp_established_step = None
        info = {}
        for step in range(env.max_steps):
            obs, _r, term, trunc, info = env.step(policy(obs))
            for ln, a in joint_actor_by_name.items():
                f = force_on(a)
                final_joint_force[ln] = f
                if f > max_joint_force[ln]:
                    max_joint_force[ln] = f
            for ln, a in tip_actor_by_name.items():
                f = force_on(a)
                final_tip_force[ln] = f
                if f > max_tip_force[ln]:
                    max_tip_force[ln] = f
            if info.get("grasp_established") and grasp_established_step is None:
                grasp_established_step = step
            if grasp_established_step is not None:
                v = float(np.linalg.norm(np.asarray(env.block.get_linear_velocity(), dtype=float)))
                max_speed_after_grasp = max(max_speed_after_grasp, v)
            if term or trunc:
                break

        held_joints = {ln: f for ln, f in max_joint_force.items() if f > args.force_threshold}
        held_tips = {ln: f for ln, f in max_tip_force.items() if f > args.force_threshold}
        print(f"--- 에피소드 {ep + 1}/{args.episodes} (시드 {args.seed0 + ep}) ---")
        print(f"  파지 성립: {'예' if grasp_established_step is not None else '아니오'}"
              f"  지문 접촉 손끝: {info.get('tips_touching', 0)}개  "
              f"슬립: {info.get('slip', float('nan')):.4f} m  "
              f"낙하: {'예' if term else '아니오'}")
        print(f"  손끝(지문) 힘이 실린 곳({len(held_tips)}/5): "
              + ", ".join(f"{ln}={f:.2f}N" for ln, f in sorted(held_tips.items())))
        if held_joints:
            print(f"  ⚠️ 지문이 아닌 관절에도 힘이 실렸다({len(held_joints)}곳, 에피소드 중 최댓값): "
                  + ", ".join(f"{ln}={f:.2f}N" for ln, f in sorted(held_joints.items(), key=lambda kv: -kv[1])))
        else:
            print("  지문이 아닌 관절에는 유의미한 힘이 없었다 — '관절 끼임' 가설 기각")
        held_final_joints = {ln: f for ln, f in final_joint_force.items() if f > args.force_threshold}
        held_final_tips = {ln: f for ln, f in final_tip_force.items() if f > args.force_threshold}
        print(f"  마지막 스텝(정착 상태) 손끝 힘: "
              + (", ".join(f"{ln}={f:.2f}N" for ln, f in sorted(held_final_tips.items())) or "없음"))
        print(f"  마지막 스텝(정착 상태) 비-지문 관절 힘: "
              + (", ".join(f"{ln}={f:.2f}N" for ln, f in sorted(held_final_joints.items(), key=lambda kv: -kv[1])) or "없음"))
        print(f"  파지 성립 후 물체 최대 속도(떨림 지표): {max_speed_after_grasp:.4f} m/s")
        print()

        summary.append({
            "ep": ep, "held_joints": held_joints, "held_tips": held_tips,
            "max_speed": max_speed_after_grasp,
        })

    n_wedge = sum(1 for s in summary if s["held_joints"])
    print("=== 종합 ===")
    print(f"{args.episodes}개 에피소드 중 {n_wedge}개에서 손끝이 아닌 관절에 "
          f"{args.force_threshold} N 넘는 힘이 실렸다.")
    if n_wedge > 0:
        all_joints = {}
        for s in summary:
            for ln, f in s["held_joints"].items():
                all_joints[ln] = max(all_joints.get(ln, 0.0), f)
        print("가장 자주/세게 힘이 실린 관절 상위 5개: "
              + ", ".join(f"{ln}={f:.2f}N" for ln, f in
                          sorted(all_joints.items(), key=lambda kv: -kv[1])[:5]))
    env.close()


if __name__ == "__main__":
    main()
