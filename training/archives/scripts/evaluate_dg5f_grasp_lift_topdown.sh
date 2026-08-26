#!/usr/bin/env bash
# Copy a completed top-down fine-tune and evaluate the copy with --inference.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${VENV:-${VIRTUAL_ENV:-$ROOT/vision/.vision}}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/training/results}"
ENV_PATH="${ENV_PATH:-$ROOT/training/builds/DG5FGraspLift/DG5FGraspLift.x86_64}"
TIME_SCALE="${TIME_SCALE:-20}"
TORCH_DEVICE="${TORCH_DEVICE:-cpu}"
NUM_ENVS="${NUM_ENVS:-1}"
BASE_PORT="${BASE_PORT:-5005}"
# max_steps does NOT bound --inference in this ML-Agents version. Bound each
# resumed inference session ourselves by observed environment steps and time.
INFERENCE_STEP_BUDGET="${INFERENCE_STEP_BUDGET:-200000}"
INFERENCE_TIMEOUT_SECONDS="${INFERENCE_TIMEOUT_SECONDS:-1800}"
INFERENCE_POLL_SECONDS="${INFERENCE_POLL_SECONDS:-5}"
INFERENCE_TERM_GRACE_SECONDS="${INFERENCE_TERM_GRACE_SECONDS:-30}"

SOURCE_RUN_ID="${1:-}"
EVAL_SET="${2:-both}"
active_inference_pid=""
active_inference_log=""

cleanup() {
  if [[ -n "$active_inference_pid" ]] && kill -0 "$active_inference_pid" 2>/dev/null; then
    kill -TERM -- "-$active_inference_pid" 2>/dev/null || true
    wait "$active_inference_pid" 2>/dev/null || true
  fi
  [[ -z "$active_inference_log" ]] || rm -f -- "$active_inference_log"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

usage() {
  echo "usage: $0 RUN_ID [nominal|com050|both]" >&2
  echo "  RUN_ID must be one of:" >&2
  echo "    dg5f_grasp_lift_t1_topdown150" >&2
  echo "    dg5f_grasp_lift_t2_topdown300" >&2
  echo "    dg5f_grasp_lift_t3_topdown225" >&2
  echo "    dg5f_grasp_lift_t4_topdown150_long" >&2
}

if [[ -z "$SOURCE_RUN_ID" ]]; then
  usage
  exit 2
fi

case "$SOURCE_RUN_ID" in
  dg5f_grasp_lift_t1_topdown150)
    nominal_run_id="dg5f_grasp_lift_eval_t1_topdown150"
    nominal_config="$ROOT/training/config/dg5f_grasp_lift_eval_t1_topdown150.yaml"
    com050_run_id="dg5f_grasp_lift_eval_t1_com050"
    com050_config="$ROOT/training/config/dg5f_grasp_lift_eval_t1_com050.yaml"
    ;;
  dg5f_grasp_lift_t2_topdown300)
    nominal_run_id="dg5f_grasp_lift_eval_t2_topdown300"
    nominal_config="$ROOT/training/config/dg5f_grasp_lift_eval_t2_topdown300.yaml"
    com050_run_id="dg5f_grasp_lift_eval_t2_com050"
    com050_config="$ROOT/training/config/dg5f_grasp_lift_eval_t2_com050.yaml"
    ;;
  dg5f_grasp_lift_t3_topdown225)
    nominal_run_id="dg5f_grasp_lift_eval_t3_topdown225"
    nominal_config="$ROOT/training/config/dg5f_grasp_lift_eval_t3_topdown225.yaml"
    com050_run_id="dg5f_grasp_lift_eval_t3_com050"
    com050_config="$ROOT/training/config/dg5f_grasp_lift_eval_t3_com050.yaml"
    ;;
  dg5f_grasp_lift_t4_topdown150_long)
    nominal_run_id="dg5f_grasp_lift_eval_t4_topdown150_long"
    nominal_config="$ROOT/training/config/dg5f_grasp_lift_eval_t4_topdown150_long.yaml"
    com050_run_id="dg5f_grasp_lift_eval_t4_com050"
    com050_config="$ROOT/training/config/dg5f_grasp_lift_eval_t4_com050.yaml"
    ;;
  *)
    echo "[ERROR] unsupported training RUN_ID: $SOURCE_RUN_ID" >&2
    usage
    exit 2
    ;;
esac

case "$EVAL_SET" in
  nominal)
    eval_run_ids=("$nominal_run_id")
    eval_configs=("$nominal_config")
    eval_coms=("0.20")
    ;;
  com050)
    eval_run_ids=("$com050_run_id")
    eval_configs=("$com050_config")
    eval_coms=("0.50")
    ;;
  both)
    eval_run_ids=("$nominal_run_id" "$com050_run_id")
    eval_configs=("$nominal_config" "$com050_config")
    eval_coms=("0.20" "0.50")
    ;;
  *)
    echo "[ERROR] evaluation set must be nominal, com050, or both: $EVAL_SET" >&2
    usage
    exit 2
    ;;
esac

source_dir="$RESULTS_DIR/$SOURCE_RUN_ID"
checkpoint="$source_dir/DG5FGraspLift/checkpoint.pt"
[[ -f "$checkpoint" ]] || {
  echo "[ERROR] trained checkpoint not found: $checkpoint" >&2
  exit 2
}

# Preflight every destination before making any copy, so `both` cannot partially
# start merely because its second destination already exists.
for eval_run_id in "${eval_run_ids[@]}"; do
  eval_dir="$RESULTS_DIR/$eval_run_id"
  [[ ! -e "$eval_dir" ]] || {
    echo "[ERROR] evaluation directory already exists; refusing to clobber: $eval_dir" >&2
    exit 2
  }
done

PYTHON="$VENV/bin/python"
METRICS="$ROOT/training/scripts/grasp_metrics.py"
[[ -x "$PYTHON" ]] || {
  echo "[ERROR] Python environment not found: $PYTHON" >&2
  exit 2
}
[[ -f "$METRICS" ]] || {
  echo "[ERROR] metric tool not found: $METRICS" >&2
  exit 2
}
[[ "$BASE_PORT" =~ ^[0-9]+$ ]] || {
  echo "[ERROR] BASE_PORT must be an integer: $BASE_PORT" >&2
  exit 2
}
for variable_name in \
  INFERENCE_STEP_BUDGET \
  INFERENCE_TIMEOUT_SECONDS \
  INFERENCE_POLL_SECONDS \
  INFERENCE_TERM_GRACE_SECONDS; do
  value="${!variable_name}"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || {
    echo "[ERROR] $variable_name must be a positive integer: $value" >&2
    exit 2
  }
done

latest_matching_step() {
  local pattern="$1"
  local log_path="$2"

  sed -nE "s/.*${pattern}.*/\\1/p" "$log_path" 2>/dev/null | tail -n 1
}

stop_inference_group() {
  local pid="$1"
  local waited=0

  kill -TERM -- "-$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && (( waited < INFERENCE_TERM_GRACE_SECONDS )); do
    sleep 1
    ((waited += 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "[WARN] inference process group $pid ignored SIGTERM; sending SIGKILL" >&2
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

run_bounded_inference() {
  local eval_run_id="$1"
  local config="$2"
  local started_at="$SECONDS"
  local resume_step=""
  local latest_step=""
  local target_step=""
  local elapsed
  local exit_status

  active_inference_log="$(mktemp "${TMPDIR:-/tmp}/dg5f-grasp-lift-eval.XXXXXX.log")"
  echo "[Bound] step_budget=$INFERENCE_STEP_BUDGET timeout=${INFERENCE_TIMEOUT_SECONDS}s"

  RUN_ID="$eval_run_id" \
  CONFIG="$config" \
  RESULTS_DIR="$RESULTS_DIR" \
  ENV_PATH="$ENV_PATH" \
  VENV="$VENV" \
  TIME_SCALE="$TIME_SCALE" \
  TORCH_DEVICE="$TORCH_DEVICE" \
  NUM_ENVS="$NUM_ENVS" \
    setsid "$ROOT/training/scripts/train_dg5f_grasp_lift.sh" resume --inference \
      --base-port "$BASE_PORT" > >(tee "$active_inference_log") 2>&1 &
  active_inference_pid="$!"

  while kill -0 "$active_inference_pid" 2>/dev/null; do
    if [[ -z "$resume_step" ]]; then
      resume_step="$(
        latest_matching_step 'Resuming training from step ([0-9]+)' "$active_inference_log"
      )"
      if [[ -n "$resume_step" ]]; then
        target_step=$((resume_step + INFERENCE_STEP_BUDGET))
        echo "[Bound] resume_step=$resume_step target_step=$target_step"
      fi
    fi

    latest_step="$(
      latest_matching_step 'DG5FGraspLift[.] Step: ([0-9]+)' "$active_inference_log"
    )"
    if [[ -n "$target_step" && -n "$latest_step" ]] && (( latest_step >= target_step )); then
      echo "[Bound] reached step $latest_step (target $target_step); stopping process group $active_inference_pid"
      stop_inference_group "$active_inference_pid"
      active_inference_pid=""
      rm -f -- "$active_inference_log"
      active_inference_log=""
      return 0
    fi

    elapsed=$((SECONDS - started_at))
    if (( elapsed >= INFERENCE_TIMEOUT_SECONDS )); then
      echo "[ERROR] inference timed out after ${elapsed}s at step ${latest_step:-unknown}; target=${target_step:-unknown}" >&2
      stop_inference_group "$active_inference_pid"
      active_inference_pid=""
      rm -f -- "$active_inference_log"
      active_inference_log=""
      return 1
    fi
    sleep "$INFERENCE_POLL_SECONDS"
  done

  if wait "$active_inference_pid"; then
    exit_status=0
  else
    exit_status="$?"
  fi
  active_inference_pid=""
  echo "[ERROR] inference exited early with status $exit_status at step ${latest_step:-unknown}; target=${target_step:-unknown}" >&2
  rm -f -- "$active_inference_log"
  active_inference_log=""
  return 1
}

print_metrics() {
  local eval_run_id="$1"
  local com_fraction="$2"
  local output

  echo
  echo "=== Comparison: $eval_run_id (COM $com_fraction) ==="
  if [[ "$com_fraction" == "0.20" ]]; then
    echo "Deployed baseline: Success=0.9975, GraspPostureAngleDegrees=67.1,"
    echo "  HandSurfaceContactSeconds=1.05, BestLiftHeight=0.146"
  else
    echo "Uniform-COM deployed baseline: Success=0.9924"
  fi
  echo "Evaluation latest scalars:"
  output="$("$PYTHON" "$METRICS" --root "$ROOT" --all "$eval_run_id")"
  awk '
    /GraspLift\/(GraspPostureAngleDegrees|HandSurfaceContactSeconds|Success|BestLiftHeight|TopDownAngleDegrees)/ {
      print "  " $0
      found = 1
    }
    END {
      if (!found) {
        print "  [WARN] requested GraspLift scalar tags were not found"
      }
    }
  ' <<<"$output"
}

for index in "${!eval_run_ids[@]}"; do
  eval_run_id="${eval_run_ids[$index]}"
  config="${eval_configs[$index]}"
  com_fraction="${eval_coms[$index]}"
  eval_dir="$RESULTS_DIR/$eval_run_id"

  echo "[Copy] $source_dir -> $eval_dir"
  cp -a -- "$source_dir" "$eval_dir"

  echo "[Inference] run=$eval_run_id config=$config base_port=$BASE_PORT"
  run_bounded_inference "$eval_run_id" "$config"

  print_metrics "$eval_run_id" "$com_fraction"
done
