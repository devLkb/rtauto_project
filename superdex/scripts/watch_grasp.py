# -*- coding: utf-8 -*-
"""학습된 파지 정책을 **눈으로 본다.** SuperDex 뷰어 창에 실시간으로 띄운다.

게이트 0~4 의 판정은 전부 숫자였다(슬립, 접촉 수, 성공률). 이 스크립트는 그 숫자가
실제로 어떤 동작인지 **보기 위한 것**이지 판정 도구가 아니다.

## 무엇이 보이는가

- **떠 있는 DG-5F 손 하나.** 팔은 없다 — 게이트 2 태스크가 **손목 고정**이라 손만
  제어한다(`world_joint` 를 world 에 용접해 DOF 가 정확히 20). 팔+손 결합체는 게이트 3
  에서 만들었지만 그것을 구동하는 정책은 아직 없다(§5 "작업 경계").
- **물체 하나와 바닥판.** 씬은 이게 전부다 — 학습용 최소 구성이지 "테스트 룸"이 아니다.
- **에피소드 구조**: 처음 `grace_steps`(기본 40스텝 = 0.2초) 동안은 **무중력**이고, 그
  뒤 중력이 켜진다. 성공은 "떨어뜨리지 않고 3지 이상 접촉을 유지"다. **들어올리지
  않는다** — 손목이 고정이라 lift 동작 자체가 없다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/watch_grasp.py --checkpoint superdex/results/dg5f_grasp_v8_iter0300
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/watch_grasp.py --checkpoint superdex/results/dg5f_grasp_v8_iter0300
```

**GPU 와 디스플레이가 필요하다** — 원격 터미널만 있는 환경에서는 창이 못 뜬다.
그럴 때는 `--record out.mp4` 로 오프스크린 렌더링해 동영상으로 뽑는다.

창이 뜨면 마우스로 시점을 돌릴 수 있다. 종료는 창을 닫거나 터미널에서 `Ctrl+C`.

## 비교해서 보고 싶을 때

```powershell
python -u superdex/scripts/watch_grasp.py --baseline
```

`--baseline` 은 학습 정책 대신 **고정 폐쇄**(그냥 꽉 쥐는 스크립트 동작)를 돌린다.
게이트 2 에서 학습 정책이 이긴 상대가 이것이다 — 최악 슬립 17.5 cm vs 4.5 cm.

느리게 보려면 `--slowdown 4` (4배 느리게). 물체를 바꾸려면 `--object paper_cup`.
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

# 물체 짧은 이름 -> prefab 경로. gate4_object_sweep.py 와 같은 목록이다.
OBJECTS = {
    "duck_lamp": "prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab",
    "paper_cup": "prefabs/paper_cups/paper_cup.mochi_prefab",
    "sphere": "prefabs/sphere/sphere.mochi_prefab",
    "block_red": "prefabs/box_and_blocks/block_red.mochi_prefab",
}
# 물체별로 맞는 스폰 오프셋. duck_lamp 값을 다른 물체에 그대로 쓰면 잡지 못한다
# (게이트 4 실측: paper_cup 은 배치만 바꿔 성립률 30 % -> 100 %).
PLACES = {"paper_cup": (0.06, 0.0, 0.06)}


HAND_COLOR = (0.62, 0.65, 0.70)   # 차분한 회청색 — 손
TIP_COLOR = (0.95, 0.75, 0.20)    # 노랑 — 지문(접촉 판정의 주인공)
OBJECT_COLOR = (0.85, 0.25, 0.30) # 빨강 — 파지 대상


def paint(viewer, env) -> None:
    """손·지문·물체를 서로 다른 색으로 칠한다.

    기본 렌더링은 링크마다 무작위 색을 준다. 손과 물체가 똑같이 알록달록해서
    **무엇이 물체인지 눈으로 구분되지 않는다**(실측 — 첫 렌더가 그랬다).
    성공 판정이 "지문 3개 이상 접촉"이므로 지문만 따로 강조한다.
    """
    from dg5f_grasp_env import TIP_LINKS

    bot_name = env.bot.get_name()
    tip_names = {f"{bot_name}/{n}" for n in TIP_LINKS} | set(TIP_LINKS)
    for actor in viewer.get_actors():
        r = viewer.get_actor_renderer(actor)
        if r is None or not hasattr(r, "set_front_face_color"):
            continue  # 바닥판(StaticPlaneRenderer)은 그대로 둔다
        name = actor.get_name()
        if name.startswith("block"):
            color = OBJECT_COLOR
        elif name in tip_names:
            color = TIP_COLOR
        elif name.startswith(bot_name):
            color = HAND_COLOR
        else:
            continue
        r.set_front_face_color(color)


def main() -> None:
    ap = argparse.ArgumentParser(description="학습된 파지 정책을 뷰어로 본다")
    ap.add_argument("--checkpoint", default="superdex/results/dg5f_grasp_v8_iter0300")
    ap.add_argument("--baseline", action="store_true",
                    help="학습 정책 대신 고정 폐쇄(스크립트 동작)를 돌린다")
    ap.add_argument("--object", default="duck_lamp", choices=sorted(OBJECTS))
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--slowdown", type=float, default=1.0,
                    help="실시간 대비 배속 (4 = 4배 느리게). 물리는 그대로다")
    ap.add_argument("--episode-seconds", type=float, default=1.0,
                    help="학습 때와 같은 1.0 이 기본. 늘리면 유지 구간을 더 오래 본다")
    ap.add_argument("--camera-distance", type=float, default=0.38,
                    help="파지 중심에서 카메라까지 거리 [m]. 작을수록 확대된다")
    ap.add_argument("--record", default=None,
                    help="창 대신 오프스크린 렌더링해 이 경로에 mp4 로 저장한다")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv
    from superdex.physics.viewer import Viewer, ViewerCfg

    env_config = {
        "episode_seconds": args.episode_seconds,
        "object_prefab": OBJECTS[args.object],
    }
    if args.object in PLACES:
        env_config["place"] = list(PLACES[args.object])

    env = Dg5fGraspEnv(env_config)

    if args.baseline:
        fixed = env.full_closed.astype(np.float32)
        policy = lambda _o: fixed  # noqa: E731
        label = "고정 폐쇄 기준선 (학습 안 한 스크립트 동작)"
    else:
        from eval_policy import load_policy

        ckpt = Path(args.checkpoint)
        if not ckpt.is_absolute():
            ckpt = REPO_ROOT / ckpt
        if not ckpt.is_dir():
            sys.exit(f"체크포인트가 없다: {ckpt}")
        policy = load_policy(ckpt, env.joint_low, env.joint_high)
        label = f"학습 정책 {ckpt.name}"

    print(f"정책   : {label}")
    print(f"물체   : {args.object}  ({env.object_prefab})")
    print(f"에피소드: {args.episodes}  각 {args.episode_seconds}초 "
          f"(처음 {env.grace_steps}스텝은 무중력)")
    print(f"배속   : 실시간의 1/{args.slowdown:g}")
    print()
    print("⚠️ 팔은 없다 — 손목 고정 태스크라 손 20관절만 제어한다.")
    print("⚠️ 들어올리지 않는다 — 중력 하에서 떨어뜨리지 않고 버티는 것이 성공이다.")
    print()

    frames = []
    viewer = Viewer(ViewerCfg(size=(1280, 720), offscreen=bool(args.record)))
    try:
        dt = env.dt
        for ep in range(args.episodes):
            obs, _ = env.reset(seed=args.seed0 + ep)
            # 리셋마다 씬 구성이 바뀔 수 있으므로 다시 물려 준다.
            viewer.set_scene(env.scene)

            # ⚠️ 자동 프레이밍(snap_follow_camera / frame_scene)을 쓰면 안 된다.
            # 바닥이 **무한 평면**이라 씬 경계가 사실상 무한대로 잡히고, 카메라가
            # 아득히 멀어져 손과 물체가 화면 가운데 점 하나로 보인다(실측).
            # 손목이 용접돼 손이 거의 안 움직이므로 **파지 중심을 실측해 고정 시점**을
            # 잡는 편이 낫다.
            center = env._grasp_center(env._link_positions())
            d = args.camera_distance
            viewer.set_camera_view(
                look_from=center + np.array([d, -d, 0.4 * d]),
                look_at=center,
                up_dir=[0.0, 0.0, 1.0],
            )
            paint(viewer, env)

            info = {}
            for _ in range(env.max_steps):
                t0 = time.perf_counter()
                obs, _r, term, trunc, info = env.step(policy(obs))
                frame = viewer.render()
                if args.record and frame is not None:
                    frames.append(np.asarray(frame))
                if term or trunc:
                    break
                # 실시간에 맞춰 재생한다. 없으면 물리 속도로 순식간에 지나간다.
                if not args.record:
                    lag = dt * args.slowdown - (time.perf_counter() - t0)
                    if lag > 0:
                        time.sleep(lag)

            slip = float(info.get("slip", float("nan")))
            print(f"  에피소드 {ep + 1}/{args.episodes} (시드 {args.seed0 + ep}): "
                  f"지문 {info.get('tips_touching', 0)}개  "
                  f"슬립 {slip:.4f} m  "
                  f"{'낙하' if term else '유지'}")
    except KeyboardInterrupt:
        print("\n중단됨.")
    finally:
        viewer.close()
        env.close()

    if args.record and frames:
        import imageio  # superdex-physics 의 의존이라 별도 설치가 필요 없다

        out = Path(args.record)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        imageio.mimsave(str(out), frames, fps=int(1.0 / env.dt / max(args.slowdown, 1)))
        print(f"\n저장: {out}  ({len(frames)} 프레임)")


if __name__ == "__main__":
    main()
