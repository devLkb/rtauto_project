# -*- coding: utf-8 -*-
# 웹캠 텔레옵 데모(vision_node_dg5f.py)를 "설치 없이 실행 가능한" exe로 패키징한다.
# Unity Standalone 빌드와 짝지어 dist/에 함께 넣으면, 다른 PC에는 웹캠만 있으면
# Python/venv 설치 없이 시연이 가능하다. (원칙 2 — 새 머신 부트스트랩 보장)
#
# 전제: 이 스크립트는 docs/PYTHON_ENV_SETUP.md대로 만든 비전+ML-Agents 공용
# venv(Python 3.10.11)를 활성화한 상태에서 실행한다 — mediapipe 등 실제 런타임
# 의존성이 설치돼 있어야 PyInstaller가 무엇을 담을지 알 수 있다.
#
# 사용법:
#   .\venv310\Scripts\Activate.ps1
#   .\vision\dg5f\build_demo_exe.ps1
# 결과: vision\dg5f\dist\vision_node_dg5f\vision_node_dg5f.exe (+ 동봉 DLL/데이터 폴더째)

$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $here "..\..")

$pyVersion = (python --version) 2>&1
if ($pyVersion -notmatch "3\.10\.") {
    Write-Warning "현재 Python이 3.10.x가 아님 ($pyVersion). docs/PYTHON_ENV_SETUP.md의 venv를 먼저 활성화했는지 확인할 것."
}

python -m pip show pyinstaller > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[build_demo_exe] pyinstaller 미설치 — 설치한다."
    python -m pip install pyinstaller
}

Push-Location $repoRoot
try {
    # --onedir: mediapipe의 큰 모델/네이티브 바이너리를 --onefile로 묶으면 매 실행마다
    # 임시폴더에 재압축 해제되어 느리고 종종 깨진다 — 폴더째 배포가 더 안정적이다.
    # --paths $repoRoot: vision_node_dg5f.py의 `from config.rtauto_config import ...`가
    #   레포 루트를 최상위 패키지 경로로 삼으므로, PyInstaller의 정적 분석에도 알려줘야 한다.
    # --collect-all mediapipe: mediapipe는 모델 파일(.tflite/.binarypb)과 네이티브 확장을
    #   같이 들고 다니는데, PyInstaller 기본 분석은 이걸 못 찾는다 — 통째로 수집.
    python -m PyInstaller `
        --name vision_node_dg5f `
        --onedir `
        --noconfirm `
        --distpath (Join-Path $here "dist") `
        --workpath (Join-Path $here "build") `
        --paths "$repoRoot" `
        --collect-all mediapipe `
        --collect-all cv2 `
        (Join-Path $here "vision_node_dg5f.py")
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "[build_demo_exe] 완료: vision/dg5f/dist/vision_node_dg5f/vision_node_dg5f.exe"
Write-Host "[build_demo_exe] 필수 검증: 이 폴더를 실제로 옮겨서(원본 레포 밖) exe를 실행해보고"
Write-Host "  웹캠이 뜨고 관절각이 콘솔에 찍히는지 확인할 것 — PyInstaller의 mediapipe 번들링은"
Write-Host "  버전마다 깨지는 사례가 흔해 빌드 성공 != 실행 성공이다."
