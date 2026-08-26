#!/usr/bin/env bash
set -euo pipefail

ROOT="${DG5F_ROOT:-/workspace/KDT_1_AX_rtauto}"
VENV="${DG5F_VENV:-/root/venvs/ax310}"
METRICS="$ROOT/training/scripts/grasp_metrics.py"

usage() {
  cat <<'EOF'
사용법: grasp <명령>

  log [RUN_ID]   실행 중인 최신 학습의 TensorBoard scalar와 자동 분석 출력
  logs [RUN_ID]  log와 동일
  help           도움말

옵션 예:
  grasp log
  grasp log dg5f_ready_reach_scratch_gpu_20260722
  grasp log --window 50 --all
EOF
}

case "${1:-help}" in
  log|logs)
    shift
    [[ -x "$VENV/bin/python" ]] || {
      echo "[ERROR] ML-Agents Python 환경이 없습니다: $VENV/bin/python" >&2
      exit 2
    }
    exec "$VENV/bin/python" "$METRICS" --root "$ROOT" "$@"
    ;;
  help|-h|--help) usage ;;
  *)
    echo "[ERROR] 알 수 없는 명령: $1" >&2
    usage >&2
    exit 2
    ;;
esac
