# -*- coding: utf-8 -*-
# 디지털 트윈 시연 런처 — 웹캠 텔레옵(vision_node_dg5f.exe) + Unity 데모(KDT_robot_AI.exe)를
# 한 번에 띄운다. 다른 PC에 배포할 때는 이 스크립트를 아래 구조로 같은 폴더에 넣을 것:
#
#   <배포 폴더>\
#     RunDemo.ps1                          (이 파일)
#     vision_node_dg5f\vision_node_dg5f.exe   (build_demo_exe.ps1 산출물 — 폴더째 복사)
#     KDT_robot_AI.exe                        (Unity Build 산출물)
#     KDT_robot_AI_Data\...                   (Unity Build 산출물, exe와 같은 폴더)
#
# Unity Build Settings에서 Product Name을 바꿨다면 아래 $unityExe 값도 맞춰 바꿀 것
# (ProjectSettings/ProjectSettings.asset의 productName이 정본).

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

$visionExe = Join-Path $here "vision_node_dg5f\vision_node_dg5f.exe"
$unityExe = Join-Path $here "KDT_robot_AI.exe"

if (-not (Test-Path $visionExe)) {
    Write-Warning "웹캠 트래킹 exe를 못 찾음: $visionExe — 텔레옵 없이 Unity만 띄운다(손이 안 움직임)."
    $visionExe = $null
}
if (-not (Test-Path $unityExe)) {
    throw "Unity 데모 exe를 못 찾음: $unityExe — 파일명이 다르면 이 스크립트의 `$unityExe`를 수정할 것."
}

if ($visionExe) {
    Write-Host "[RunDemo] 웹캠 손 트래킹 시작 (오른손 모델)..."
    Start-Process -FilePath $visionExe -ArgumentList "right"
    Start-Sleep -Seconds 2   # 웹캠 초기화 + UDP 첫 패킷 여유
}

Write-Host "[RunDemo] Unity 데모 시작..."
Start-Process -FilePath $unityExe
