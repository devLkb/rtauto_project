# -*- coding: utf-8 -*-
# URSim(UR16e 가상 컨트롤박스) 도커 컨테이너 실행 — Windows.
# RTDE(30001-30004)를 게시해야 arm/ur_rtde_bridge.py·arm/prepose_to_joints.py가 접속할 수
# 있다(공식 이미지 기본 예시는 5900/6080만 게시해 RTDE가 막힌다).
# 근거: docs/SIM2REAL_ROADMAP.md §9 "URSim 선행 개발 경로".
#
# 펜던트 화면(웹): http://localhost:6080/vnc.html
# ⚠️ 공식 문서 경고 — 포트를 게시하면 시뮬 로봇이 LAN에 노출된다. 방화벽 확인할 것.
#
# 쓰는 법
#   ./arm/run_ursim.ps1            # 이 터미널을 붙잡고 실행. Ctrl+C 로 끈다
#   ./arm/run_ursim.ps1 -Detach    # 뒤에서 돌린다. 사람이 없는 자동 실행·스크립트용
#   ./arm/run_ursim.ps1 -Stop      # -Detach 로 띄운 것을 끈다
#
# ⚠️ -Detach 가 필요한 이유: `docker run -it` 는 사람이 붙은 터미널이 있어야 하고,
#    없으면 "cannot attach stdin to a TTY-enabled container" 로 죽는다.

param(
    [switch]$Detach,
    [switch]$Stop,
    [string]$Name = "ursim"
)

$ErrorActionPreference = "Stop"

if ($Stop) {
    docker rm -f $Name
    exit $LASTEXITCODE
}

# 포트·모델은 여기 한 곳에만 적는다 — 붙었을 때와 뒤에서 돌 때가 갈라지면 안 된다.
$runArgs = @(
    "--name", $Name,
    "--rm",
    "-e", "ROBOT_MODEL=UR16",
    "-p", "5900:5900",
    "-p", "6080:6080",
    "-p", "29999:29999",
    "-p", "30001-30004:30001-30004"
)

if ($Detach) {
    docker run -d @runArgs universalrobots/ursim_e-series
    Write-Host "뒤에서 띄웠다. 끌 때: ./arm/run_ursim.ps1 -Stop"
    Write-Host "펜던트 화면: http://localhost:6080/vnc.html"
} else {
    docker run -it @runArgs universalrobots/ursim_e-series
}
