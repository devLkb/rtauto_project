#!/usr/bin/env bash
# URSim(UR16e 가상 컨트롤박스) 도커 컨테이너 실행 — Linux/macOS.
# RTDE(30001-30004)를 게시해야 arm/ur_rtde_bridge.py가 접속할 수 있다(공식 이미지 기본
# 예시는 5900/6080만 게시해 RTDE가 막힌다). 근거: docs/SIM2REAL_ROADMAP.md §9 "URSim 선행 개발 경로".
#
# 펜던트 화면(웹): http://localhost:6080/vnc.html
# ⚠️ 공식 문서 경고 — 포트를 게시하면 시뮬 로봇이 LAN에 노출된다. 방화벽 확인할 것.
#
# 실행 후 arm/ur_rtde_bridge.py --ip 로 접속(기본 .env RTAUTO_UR_IP=127.0.0.1이 이 컨테이너를 가리킴).
set -euo pipefail

docker run --rm -it \
  -e ROBOT_MODEL=UR16 \
  -p 5900:5900 \
  -p 6080:6080 \
  -p 29999:29999 \
  -p 30001-30004:30001-30004 \
  universalrobots/ursim_e-series
