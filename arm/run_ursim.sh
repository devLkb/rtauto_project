#!/usr/bin/env bash
# URSim(UR16e 가상 컨트롤박스) 도커 컨테이너 실행 — Linux/macOS.
# RTDE(30001-30004)를 게시해야 arm/ur_rtde_bridge.py·arm/prepose_to_joints.py가 접속할 수
# 있다(공식 이미지 기본 예시는 5900/6080만 게시해 RTDE가 막힌다).
# 근거: docs/SIM2REAL_ROADMAP.md §9 "URSim 선행 개발 경로".
#
# 🛑 이미지 버전을 반드시 5.25.2로 고정한다(태그 없이 받으면 :latest가 따라와 실물
#    UR16e 버전(PolyScope 5.25.2, docs/SIM2REAL_ROADMAP.md §4)과 어긋난다). 2026-09-21
#    코드 리뷰 3차 URSim 실측 중 :latest(5.26.0)로 실제로 겪은 문제 — ur_rtde 1.6.5로
#    RTDEControlInterface 연결이 "Failed to start RTDE data synchronization, before
#    timeout"으로 계속 실패했다(읽기 전용 RTDEReceiveInterface는 됐다 — 명령 연결만
#    깨졌다). 5.25.2로 다시 띄우니 바로 됐다 — 컨트롤러·클라이언트 라이브러리 버전
#    호환성 문제였다.
#
# 펜던트 화면(웹): http://localhost:6080/vnc.html
# ⚠️ 공식 문서 경고 — 포트를 게시하면 시뮬 로봇이 LAN에 노출된다. 방화벽 확인할 것.
#
# 쓰는 법
#   ./arm/run_ursim.sh            # 이 터미널을 붙잡고 실행. Ctrl+C 로 끈다
#   ./arm/run_ursim.sh --detach   # 뒤에서 돌린다. 사람이 없는 자동 실행·스크립트용
#   ./arm/run_ursim.sh --stop     # --detach 로 띄운 것을 끈다
#
# ⚠️ --detach 가 필요한 이유: `docker run -it` 는 사람이 붙은 터미널이 있어야 하고,
#    없으면 "the input device is not a TTY" 로 죽는다.
set -euo pipefail

NAME="${URSIM_NAME:-ursim}"
MODE="attach"
case "${1:-}" in
  --detach|-d) MODE="detach" ;;
  --stop)      MODE="stop" ;;
  "")          ;;
  *) echo "모르는 선택지: $1 (쓸 수 있는 것: --detach, --stop)" >&2; exit 2 ;;
esac

if [ "$MODE" = "stop" ]; then
  docker rm -f "$NAME"
  exit $?
fi

# 포트·모델은 여기 한 곳에만 적는다 — 붙었을 때와 뒤에서 돌 때가 갈라지면 안 된다.
RUN_ARGS=(
  --name "$NAME"
  --rm
  -e ROBOT_MODEL=UR16
  -p 5900:5900
  -p 6080:6080
  -p 29999:29999
  -p 30001-30004:30001-30004
)

if [ "$MODE" = "detach" ]; then
  docker run -d "${RUN_ARGS[@]}" universalrobots/ursim_e-series:5.25.2
  echo "뒤에서 띄웠다. 끌 때: ./arm/run_ursim.sh --stop"
  echo "펜던트 화면: http://localhost:6080/vnc.html"
else
  docker run -it "${RUN_ARGS[@]}" universalrobots/ursim_e-series:5.25.2
fi
