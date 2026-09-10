# -*- coding: utf-8 -*-
"""RLlib 체크포인트 -> 자기완결 ONNX 정책 (게이트 1).

**왜 RLModule만 뽑으면 안 되는가 (실측).**
RLlib 새 API 스택은 ONNX export를 지원하지 않고(ray#45526), 정책의 일부가 신경망
**바깥**의 커넥터에 산다. 이 체크포인트에서 실측한 구성:

    env_to_module : AddObservationsFromEpisodesToBatch, AddTimeDimToBatchAndZeroPad,
                    AddStatesFromEpisodesToBatch, BatchIndividualItems, NumpyToTensor
                    -> 관찰 정규화 **없음** (state.pkl 5바이트 = 빈 상태)
    module_to_env : GetActions, TensorToNumpy, UnBatchToIndividualItems,
                    RemoveSingleTsTimeRankFromBatch,
                    **NormalizeAndClipActions {normalize_actions: True}**,
                    ListifyDataForVectorEnv

즉 신경망은 **[-1,1] 정규화 공간**의 액션을 내고, 커넥터가 실제 액션 공간으로 되돌린다
(`unsquash_action`):

    a = low + (a_norm + 1.0) * (high - low) / 2.0 ;  a = clip(a, low, high)

RLModule만 ONNX로 내보내면 이 되돌림이 빠져 **조용히 잘못된 정책**이 배포된다.
cart_pole(Box(-3,3))이면 3배 작은 액션이고, DG5F 관절 지령이면 단위가 아예 틀린다.

그래서 이 스크립트는 **래퍼 nn.Module**을 내보낸다:

    raw_obs -> RLModule.forward_inference -> action_dist_inputs -> 평균(결정론적)
            -> unsquash(상수로 박힌 low/high) -> clip -> raw_action

정규화 통계나 스케일을 JSON으로 빼서 Unity C#과 ROS2 Python에 각각 구현하면 구현이
셋으로 갈라져 계약이 조용히 깨진다. ONNX 하나가 raw_obs -> raw_action 전체를 담게 한다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/export_onnx.py --checkpoint superdex/results/cart_pole_ppo
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (산출물 경로의 유일한 출처 — 원칙 1)

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

# 환경별 스펙 버전. 관찰·행동 계약이 바뀌면 여기서 올린다 — 소비자(Unity/ROS2)가 계약
# 불일치를 즉시 감지하기 위해 ONNX 메타데이터에 박는다. 스펙 정본은
# docs/RL_POLICY_REDESIGN.md 다.
SPEC_VERSIONS = {
    (4, 1): "gate1-cartpole-1",      # cart_pole 대리 환경 (게이트 1)
    (65, 20): "dg5f-grasp-1",        # DG5FGraspEnv: 관찰 65 / 행동 20 (게이트 2)
}


def load_spaces(ckpt: Path):
    """체크포인트에서 관찰·액션 공간을 읽는다 (환경을 만들지 않고).

    env_to_module 커넥터의 생성 인자 첫 항이 (obs_space, action_space)다 — 실측.
    """
    obj = pickle.load(open(ckpt / "env_runner" / "env_to_module_connector"
                           / "class_and_ctor_args.pkl", "rb"))
    obs_space, act_space = obj["ctor_args_and_kwargs"][0]
    return obs_space, act_space


def load_module(ckpt: Path):
    from ray.rllib.core.rl_module.multi_rl_module import MultiRLModule
    from ray.rllib.core.rl_module.rl_module import RLModule

    rl_dir = ckpt / "learner_group" / "learner" / "rl_module"
    try:
        multi = MultiRLModule.from_checkpoint(str(rl_dir))
        keys = list(multi.keys())
        print(f"MultiRLModule 로드, 모듈: {keys}")
        return multi[keys[0]]
    except Exception as exc:
        print(f"MultiRLModule 실패({type(exc).__name__}) — default_policy 직접 로드 시도")
        return RLModule.from_checkpoint(str(rl_dir / "default_policy"))


class DeterministicPolicy(nn.Module):
    """raw_obs -> raw_action. 커넥터가 하던 unsquash/clip을 그래프 안에 상수로 넣는다."""

    def __init__(self, module, low, high, act_dim):
        super().__init__()
        self.module = module
        self.act_dim = int(act_dim)
        # low/high를 버퍼로 등록 -> ONNX 그래프의 상수로 굳는다(외부 설정 파일 불필요).
        self.register_buffer("low", torch.as_tensor(low, dtype=torch.float32))
        self.register_buffer("high", torch.as_tensor(high, dtype=torch.float32))

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        out = self.module.forward_inference({"obs": obs})
        dist_inputs = out["action_dist_inputs"]
        # DiagGaussian: [mean, log_std] 연결. 결정론적 액션 = mean.
        mean = dist_inputs[..., : self.act_dim]
        a = self.low + (mean + 1.0) * (self.high - self.low) / 2.0
        return torch.clamp(a, self.low, self.high)


def rllib_reference_action(ckpt: Path, module, obs_batch, act_space):
    """RLlib 실제 경로(모듈 + module_to_env 커넥터)로 액션을 계산한다 — 정답값.

    래퍼가 커넥터를 정확히 복제했는지 증명하는 기준선이다.
    """
    from ray.rllib.utils.spaces.space_utils import unsquash_action

    with torch.no_grad():
        out = module.forward_inference({"obs": torch.as_tensor(obs_batch)})
    dist_inputs = out["action_dist_inputs"].cpu().numpy()
    act_dim = int(np.prod(act_space.shape))
    mean = dist_inputs[:, :act_dim]
    # NormalizeAndClipActions(normalize_actions=True)가 하는 일과 동일:
    return np.stack([unsquash_action(m, act_space) for m in mean])


def main() -> None:
    ap = argparse.ArgumentParser(description="RLlib 체크포인트 -> ONNX")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--out", default=None, help="기본값: config의 SUPERDEX_POLICY_DIR")
    ap.add_argument("--name", default=None, help="파일 이름 (기본: 체크포인트 폴더명)")
    ap.add_argument("--samples", type=int, default=32, help="파리티 fixture 샘플 수")
    ap.add_argument("--tol", type=float, default=1e-5, help="파리티 허용 오차")
    args = ap.parse_args()

    ckpt = Path(args.checkpoint)
    if not ckpt.is_absolute():
        ckpt = REPO_ROOT / ckpt
    if not ckpt.is_dir():
        sys.exit(f"체크포인트 폴더가 없다: {ckpt}")

    obs_space, act_space = load_spaces(ckpt)
    obs_dim = int(np.prod(obs_space.shape))
    act_dim = int(np.prod(act_space.shape))
    print(f"obs space : {obs_space}  -> dim {obs_dim}")
    print(f"act space : {act_space}  -> dim {act_dim}")
    print(f"unsquash  : a = low + (a_norm+1)*(high-low)/2, clip  "
          f"(low={act_space.low.tolist()}, high={act_space.high.tolist()})")

    spec_version = SPEC_VERSIONS.get((obs_dim, act_dim))
    if spec_version is None:
        sys.exit(
            f"관찰 {obs_dim} / 행동 {act_dim} 조합에 스펙 버전이 등록돼 있지 않다.\n"
            f"SPEC_VERSIONS 에 추가하고 docs/RL_POLICY_REDESIGN.md 를 함께 갱신할 것 "
            f"— 계약 변경을 버전 없이 내보내면 소비자가 불일치를 감지할 수 없다."
        )
    print(f"spec ver  : {spec_version}")

    module = load_module(ckpt)
    module.eval()

    policy = DeterministicPolicy(module, act_space.low, act_space.high, act_dim)
    policy.eval()

    out_dir = Path(args.out) if args.out else Path(cfg.SUPERDEX_POLICY_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or ckpt.name
    onnx_path = out_dir / f"{stem}.onnx"
    fixture_path = out_dir / f"{stem}.parity.json"

    # 재현 가능한 fixture — 3자 파리티 테스트가 같은 입력을 쓰게 한다.
    rng = np.random.default_rng(0)
    obs = rng.standard_normal((args.samples, obs_dim)).astype(np.float32)

    with torch.no_grad():
        torch_act = policy(torch.as_tensor(obs)).cpu().numpy()
    ref_act = rllib_reference_action(ckpt, module, obs, act_space)

    max_ref = float(np.max(np.abs(torch_act - ref_act)))
    print(f"\n[1] 래퍼 vs RLlib 커넥터 경로 : 최대 오차 {max_ref:.3e}")
    if max_ref > args.tol:
        sys.exit(f"래퍼가 RLlib 경로를 복제하지 못했다 (허용 {args.tol}). 중단한다.")

    torch.onnx.export(
        policy,
        (torch.as_tensor(obs[:1]),),
        str(onnx_path),
        input_names=["obs"],
        output_names=["action"],
        dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
        opset_version=17,
    )

    # 스펙 버전을 ONNX 메타데이터에 박는다 — 소비자가 계약 불일치를 즉시 감지하게.
    import onnx

    model = onnx.load(str(onnx_path))
    for k, v in {
        "policy_spec_version": spec_version,
        "obs_dim": str(obs_dim),
        "act_dim": str(act_dim),
        "action_low": json.dumps(act_space.low.tolist()),
        "action_high": json.dumps(act_space.high.tolist()),
        "contains_unsquash": "true",
        "deterministic": "true",
    }.items():
        e = model.metadata_props.add()
        e.key, e.value = k, v
    onnx.save(model, str(onnx_path))
    print(f"[2] ONNX 저장 : {onnx_path}  ({onnx_path.stat().st_size / 1024:.1f} KB)")

    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    ort_act = sess.run(["action"], {"obs": obs})[0]
    max_ort = float(np.max(np.abs(ort_act - ref_act)))
    print(f"[3] onnxruntime vs RLlib 경로 : 최대 오차 {max_ort:.3e}")

    fixture = {
        "policy_spec_version": spec_version,
        "checkpoint": str(ckpt.relative_to(REPO_ROOT)).replace("\\", "/"),
        "obs_dim": obs_dim,
        "act_dim": act_dim,
        "action_low": act_space.low.tolist(),
        "action_high": act_space.high.tolist(),
        "tolerance": args.tol,
        "obs": obs.tolist(),
        "expected_action": ref_act.tolist(),
    }
    fixture_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"[4] 파리티 fixture : {fixture_path}")

    ok = max_ref <= args.tol and max_ort <= args.tol
    print(f"\n=== 판정 === {'통과' if ok else '실패'}  (허용 오차 {args.tol})")
    print("남은 다리: Unity Inference Engine C# 에서 같은 fixture로 검증한다 —")
    print("  superdex/scripts/unity/PolicyParityCheck.cs")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
