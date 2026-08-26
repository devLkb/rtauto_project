#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${VENV:-${VIRTUAL_ENV:-$ROOT/vision/.vision}}"
CONFIG="${CONFIG:-$ROOT/training/config/dg5f_grasp.yaml}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/training/results}"
RUN_ID="${RUN_ID:-dg5f_v1}"
ENV_PATH="${ENV_PATH:-}"
NUM_ENVS="${NUM_ENVS:-1}"
TIME_SCALE="${TIME_SCALE:-10}"
TORCH_DEVICE="${TORCH_DEVICE:-cuda}"
# Unity 6000.4.0f1의 Linux player는 -nographics에서 SDL video driver를
# null 포인터로 비교해 SIGSEGV가 난다. 화면 없는 서버에서는 Xvfb로 우회한다.
UNITY_DISPLAY_MODE="${UNITY_DISPLAY_MODE:-auto}"
XVFB_SCREEN="${XVFB_SCREEN:-640x480x24}"

if [[ ! -x "$VENV/bin/python" || ! -x "$VENV/bin/mlagents-learn" ]]; then
  echo "[ERROR] ML-Agents 가상환경을 찾을 수 없습니다: $VENV" >&2
  echo "        vision 명령으로 ax310을 활성화하거나 VENV=/root/venvs/ax310을 지정하세요." >&2
  exit 2
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "[ERROR] ML-Agents 설정 파일이 없습니다: $CONFIG" >&2
  exit 2
fi

echo "[Config] $CONFIG"
if [[ "$CONFIG" == /tmp/* ]]; then
  echo "[WARN] /tmp 설정을 사용 중입니다. 이전 smoke용 CONFIG 환경변수라면 'unset CONFIG' 하세요." >&2
fi
echo "[Train] Unity 물리 step 수집은 CPU에서 수행되며, CUDA 사용률은 PPO update 때 주로 상승합니다."

if [[ "$TORCH_DEVICE" == cuda* ]]; then
  "$VENV/bin/python" - <<'PY'
import sys
import torch

if not torch.cuda.is_available():
    sys.exit(
        "[ERROR] 현재 가상환경의 PyTorch가 CUDA를 사용할 수 없습니다. "
        "vision 명령으로 ax310을 활성화했는지 확인하세요."
    )
print(
    f"[GPU] torch={torch.__version__}, cuda={torch.version.cuda}, "
    f"device={torch.cuda.get_device_name(0)}"
)
PY
fi

args=(
  "$CONFIG"
  --run-id "$RUN_ID"
  --time-scale "$TIME_SCALE"
  --results-dir "$RESULTS_DIR"
  --torch-device "$TORCH_DEVICE"
)
launcher=()
if [[ -n "$ENV_PATH" ]]; then
  if [[ ! -x "$ENV_PATH" ]]; then
    echo "[ERROR] Unity 학습 player가 없거나 실행할 수 없습니다: $ENV_PATH" >&2
    exit 2
  fi
  # 외부 배포 패키지는 재현 가능한 timestamp를 사용하므로 소스/DLL mtime을
  # 비교할 수 없다. 패키지 manifest가 있으면 binary hash와 trainer 계약을
  # 검증하고, 저장소에서 만든 player만 아래 freshness 검사를 사용한다.
  environment_manifest="$(dirname "$ENV_PATH")/DG5F_ENVIRONMENT.json"
  if [[ ! -f "$environment_manifest"
        && "$ENV_PATH" == "$ROOT/training/builds/DG5FGraspV3/DG5FGrasp.x86_64" ]]; then
    environment_manifest="$ROOT/training/manifests/DG5FStableGrasp-v3.0.0.json"
  fi
  if [[ -f "$environment_manifest" ]]; then
    "$VENV/bin/python" "$ROOT/training/scripts/validate_unity_environment.py" \
      --env "$ENV_PATH" \
      --config "$CONFIG" \
      --manifest "$environment_manifest"
  elif [[ "${DG5F_SKIP_BUILD_FRESHNESS:-0}" != 1 ]]; then
    # 오래된 저장소 빌드로 학습하는 사고를 차단한다. Grasp 런타임 C# 소스가
    # KDT.GraspTraining.dll보다 새로우면 빌드(또는 DLL 교체)를 먼저 갱신한다.
    grasp_dll="$(dirname "$ENV_PATH")/DG5FGrasp_Data/Managed/KDT.GraspTraining.dll"
    grasp_src_dir="$ROOT/unity/Assets/MLAgents/Grasp/Runtime"
    if [[ -f "$grasp_dll" && -d "$grasp_src_dir" ]]; then
      newest_src="$(find "$grasp_src_dir" -name '*.cs' -not -path '*/.ipynb_checkpoints/*' \
        -newer "$grasp_dll" -print -quit)"
      if [[ -n "$newest_src" ]]; then
        echo "[ERROR] Unity 빌드가 Grasp 런타임 소스보다 오래됐습니다." >&2
        echo "        빌드 DLL : $grasp_dll" >&2
        echo "        새 소스  : $newest_src" >&2
        echo "        빌드를 갱신하거나 DG5F_SKIP_BUILD_FRESHNESS=1 로 명시적으로 무시하세요." >&2
        exit 2
      fi
    fi
  fi
  args+=(--env "$ENV_PATH" --num-envs "$NUM_ENVS")

  case "$UNITY_DISPLAY_MODE" in
    auto)
      if [[ -z "${DISPLAY:-}" ]]; then
        if ! command -v xvfb-run >/dev/null 2>&1; then
          echo "[ERROR] Unity 6000.4 Linux player 실행에 Xvfb가 필요합니다." >&2
          echo "        sudo apt-get install -y xvfb" >&2
          exit 2
        fi
        launcher=(xvfb-run -a -s "-screen 0 $XVFB_SCREEN")
        echo "[Unity] DISPLAY가 없어 Xvfb를 사용합니다 ($XVFB_SCREEN)."
      fi
      ;;
    xvfb)
      if ! command -v xvfb-run >/dev/null 2>&1; then
        echo "[ERROR] xvfb-run이 없습니다. sudo apt-get install -y xvfb" >&2
        exit 2
      fi
      launcher=(xvfb-run -a -s "-screen 0 $XVFB_SCREEN")
      ;;
    nographics)
      args+=(--no-graphics)
      ;;
    *)
      echo "[ERROR] UNITY_DISPLAY_MODE는 auto, xvfb, nographics 중 하나여야 합니다." >&2
      exit 2
      ;;
  esac
fi

exec "${launcher[@]}" "$VENV/bin/python" \
  "$ROOT/training/scripts/mlagents_learn_compat.py" "${args[@]}" "$@"
