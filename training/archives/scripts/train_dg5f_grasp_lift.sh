#!/usr/bin/env bash
# DG5F Grasp + Lift (behavior DG5FGraspLift, 57 obs / 7 actions).
#
#   start                    fresh PPO run
#   start --transfer         seed the run from the 599887-step pre-grasp reach
#                            checkpoint (same 57/7 shape) via --initialize-from
#   resume                   resume an interrupted run of the same RUN_ID
#
# Environment:
#   RUN_ID     default dg5f_grasp_lift_5m
#   CONFIG     default training/config/dg5f_grasp_lift.yaml
#   ENV_PATH   default training/builds/DG5FGraspLift/DG5FGraspLift.x86_64
#   NUM_ENVS / TIME_SCALE / TORCH_DEVICE forwarded to train_dg5f_grasp.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${VENV:-${VIRTUAL_ENV:-$ROOT/vision/.vision}}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/training/results}"
RUN_ID="${RUN_ID:-dg5f_grasp_lift_5m}"
CONFIG="${CONFIG:-$ROOT/training/config/dg5f_grasp_lift.yaml}"
ENV_PATH="${ENV_PATH:-$ROOT/training/builds/DG5FGraspLift/DG5FGraspLift.x86_64}"
TORCH_DEVICE="${TORCH_DEVICE:-cpu}"

# Best available pre-grasp policy: the v4 top-down angle run at ~1.9M steps
# (25.3 deg mean approach angle, 69% pre-grasp success — docs/DG5F_PREGRASP_ANGLE_RESULT.md).
SOURCE_RUN_ID="${DG5F_GRASPLIFT_SOURCE_RUN_ID:-dg5f_grasp_lift_transfer_source_topdown_v4}"
SOURCE_CHECKPOINT="${DG5F_GRASPLIFT_SOURCE_CHECKPOINT:-$ROOT/training/results/dg5f_grasp_topdown_angle_v4_cpu_2m_20260725/DG5FGrasp/DG5FGrasp-1899942.pt}"

MODE="${1:-start}"
shift || true

extra_args=()
case "$MODE" in
  start)
    [[ ! -e "$RESULTS_DIR/$RUN_ID" ]] || {
      echo "[ERROR] run already exists; pick a new RUN_ID or use resume: $RUN_ID" >&2
      exit 2
    }
    if [[ "${1:-}" == "--transfer" ]]; then
      shift
      "$VENV/bin/python" \
        "$ROOT/training/scripts/prepare_dg5f_grasp_lift_transfer.py" \
        --source "$SOURCE_CHECKPOINT" \
        --results-dir "$RESULTS_DIR" \
        --source-run-id "$SOURCE_RUN_ID"
      extra_args+=(--initialize-from "$SOURCE_RUN_ID")
    fi
    ;;
  resume)
    [[ -f "$RESULTS_DIR/$RUN_ID/DG5FGraspLift/checkpoint.pt" ]] || {
      echo "[ERROR] no checkpoint to resume: $RESULTS_DIR/$RUN_ID/DG5FGraspLift/checkpoint.pt" >&2
      exit 2
    }
    extra_args+=(--resume)
    ;;
  *)
    echo "usage: $0 [start [--transfer] | resume]" >&2
    exit 2
    ;;
esac

# The freshness guard in train_dg5f_grasp.sh only knows the legacy Grasp runtime
# DLL layout, so check the GraspLift sources against this player explicitly.
grasplift_dll="$(dirname "$ENV_PATH")/DG5FGraspLift_Data/Managed/KDT.GraspLiftTraining.dll"
grasplift_src="$ROOT/unity/Assets/MLAgents/GraspLift/Runtime"
if [[ "${DG5F_SKIP_BUILD_FRESHNESS:-0}" != 1 && -f "$grasplift_dll" && -d "$grasplift_src" ]]; then
  newest="$(find "$grasplift_src" -name '*.cs' -newer "$grasplift_dll" -print -quit)"
  if [[ -n "$newest" ]]; then
    echo "[ERROR] the Unity player is older than the GraspLift runtime sources." >&2
    echo "        player DLL : $grasplift_dll" >&2
    echo "        newer source: $newest" >&2
    echo "        Rebuild via Tools > ML-Agents > Build DG5F Grasp Lift Linux Player." >&2
    exit 2
  fi
fi

export CONFIG RESULTS_DIR RUN_ID ENV_PATH VENV TORCH_DEVICE
DG5F_SKIP_BUILD_FRESHNESS=1 exec "$ROOT/training/scripts/train_dg5f_grasp.sh" \
  "${extra_args[@]}" "$@"
