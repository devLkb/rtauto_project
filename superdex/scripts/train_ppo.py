# -*- coding: utf-8 -*-
"""SuperDex Gym 환경을 RLlib PPO로 학습한다 (우리 저장소의 학습 진입점).

**왜 동봉 `train_samples.py`를 쓰지 않는가.**
그건 외부 클론의 *샘플 앱*이고 구버전 Ray 기준으로 작성돼 있어, 우리가 핀한 스택에서
연달아 깨진다(docs/SUPERDEX_POC_PLAN.md "게이트 1 블로커" 참고):

  1. `superdex-lab` wheel에 `.train.json`이 없어 학습 대상 discover 실패
  2. `CheckpointConfig(checkpoint_frequency=...)`가 Ray 2.58 `train.v2`에서 예외
  3. `num_learners>=1`이 Windows에서 torch.distributed libuv 오류

게이트 2에서 DG5FGraspEnv용 학습기를 어차피 우리가 소유해야 하므로, 외부 샘플 앱에
환경변수로 맞추는 대신 여기서 직접 PPO를 구성한다. 위 3개가 전부 사라진다:
레시피 discover를 쓰지 않고, 폐기된 인자를 쓰지 않고, 기본이 `num_learners=0`이다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/train_ppo.py --env cart_pole --iters 5
    python superdex/scripts/train_ppo.py --env cart_pole --iters 30 --num-learners 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·러너 수의 유일한 출처 — 원칙 1)

_assets = cfg.superdex_assets_path()
if _assets is None:
    sys.exit("RTAUTO_SUPERDEX_REPO가 .env에 없다 — docs/SUPERDEX_POC_PLAN.md §11 0-5 참고.")
os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))


# 우리 저장소가 소유한 환경. SuperDex Lab의 discover 대상이 아니므로 여기서 직접 등록한다.
OWN_ENVS = {"dg5f_grasp": "dg5f_grasp_env:Dg5fGraspEnv"}


def make_own_env(spec, env_config):
    """superdex/envs/ 아래의 우리 환경을 env runner 프로세스에서 만든다."""
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
    mod_name, cls_name = spec.split(":")
    cls = getattr(importlib.import_module(mod_name), cls_name)
    return cls(env_config)


def make_superdex_env(env_id):
    """env runner 프로세스 안에서 SuperDex gym 환경을 등록하고 만든다.

    등록은 프로세스마다 필요하다 — 워커에서 register_all_envs()를 부르지 않으면
    gym.make가 그 id를 모른다.
    """
    import gymnasium as gym
    from superdex.lab.gym.utils.env_discovery import register_all_envs

    register_all_envs()
    return gym.make(env_id)


def resolve_env_id(short_name):
    from superdex.lab.gym.utils.env_discovery import get_env_short_names, register_all_envs

    register_all_envs()
    entries = get_env_short_names(include_test_only=True)
    if short_name not in entries:
        sys.exit(f"'{short_name}' 환경이 없다. 가능한 값: {sorted(entries)}")
    return entries[short_name].env_id


def main() -> None:
    ap = argparse.ArgumentParser(description="SuperDex Gym + RLlib PPO 학습")
    ap.add_argument("--env", default="cart_pole", help="환경 short name")
    ap.add_argument("--iters", type=int, default=5, help="학습 이터레이션 수")
    ap.add_argument("--num-env-runners", type=int, default=None,
                    help="기본값은 config의 SUPERDEX_ENV_RUNNERS (cpu_count-4)")
    ap.add_argument("--num-learners", type=int, default=0,
                    help="0 = 로컬 learner(분산 없음). Windows에서 1 이상은 "
                         "torch.distributed libuv 문제를 만날 수 있다")
    ap.add_argument("--gpus-per-learner", type=int, default=None,
                    help="기본값은 config의 SUPERDEX_GPUS_PER_LEARNER")
    ap.add_argument("--env-config", default=None,
                    help='환경 설정 JSON, 예: {\"place_jitter\": 0.02}')
    ap.add_argument("--run-name", default=None, help="산출물 폴더 이름")
    args = ap.parse_args()

    runners = args.num_env_runners if args.num_env_runners is not None else cfg.SUPERDEX_ENV_RUNNERS
    gpus = args.gpus_per_learner if args.gpus_per_learner is not None else cfg.SUPERDEX_GPUS_PER_LEARNER
    # num_learners=0이면 learner가 메인 프로세스에서 돌고 GPU 배정 인자가 의미를 잃는다.
    if args.num_learners == 0:
        gpus = 0

    import ray
    from ray.rllib.algorithms.ppo import PPOConfig
    from ray.tune.registry import register_env

    env_config = json.loads(args.env_config) if args.env_config else {}
    if args.env in OWN_ENVS:
        spec = OWN_ENVS[args.env]
        print(f"env       : {args.env} -> superdex/envs/{spec}  (우리 소유)")
        creator = lambda _cfg: make_own_env(spec, env_config)  # noqa: E731
    else:
        env_id = resolve_env_id(args.env)
        print(f"env       : {args.env} -> {env_id}")
        creator = lambda _cfg: make_superdex_env(env_id)  # noqa: E731
    if env_config:
        print(f"env_config: {env_config}")
    print(f"runners   : {runners}   learners: {args.num_learners}   gpu/learner: {gpus}")

    # 워커 프로세스에도 asset 경로를 넘긴다 — 안 넘기면 워커가 asset을 못 찾는다.
    ray.init(
        ignore_reinit_error=True,
        runtime_env={"env_vars": {"SUPERDEX_ASSETS_PATH": str(_assets)}},
    )
    register_env("superdex_env", creator)

    config = (
        PPOConfig()
        .environment(env="superdex_env")
        .env_runners(num_env_runners=runners)
        .learners(num_learners=args.num_learners, num_gpus_per_learner=gpus)
        .training(
            # 게이트 1은 ONNX 계약 검증이 목적이라 하이퍼파라미터를 튜닝하지 않는다.
            # 게이트 2에서 DG5FGraspEnv에 맞춰 다시 잡는다.
            train_batch_size_per_learner=4000,
            minibatch_size=256,
            num_epochs=10,
            lr=3e-4,
            gamma=0.99,
            lambda_=0.95,
        )
        .debugging(log_level="ERROR")
    )

    algo = config.build_algo()
    for i in range(args.iters):
        result = algo.train()
        env_runners = result.get("env_runners", {})
        ret = env_runners.get("episode_return_mean")
        steps = result.get("num_env_steps_sampled_lifetime")
        print(f"iter {i + 1:>3}/{args.iters}  return_mean="
              f"{'n/a' if ret is None else f'{ret:.2f}'}  env_steps={steps}")

    run_name = args.run_name or f"{args.env}_ppo"
    out = Path(cfg.SUPERDEX_RESULTS_DIR) / run_name
    out.mkdir(parents=True, exist_ok=True)
    saved = algo.save_to_path(str(out))
    print(f"\n체크포인트: {saved}")
    print("다음 단계: python superdex/scripts/export_onnx.py --checkpoint "
          f"{out.as_posix()}")

    algo.stop()
    ray.shutdown()


if __name__ == "__main__":
    main()
