# -*- coding: utf-8 -*-
"""텔레옵 추종 검증: 사람 손 로그(vision) ↔ Unity 관절 로그를 시간 정렬해 채널별 대조.

무엇을 검증하나 (채널별):
  ① 전송:   vision filt(송신값) ↔ unity rx(수신값) 일치 — 프로토콜/순서 무결성
  ② 클램프: 송신값이 URDF 리밋 밖인 비율 — 보정 범위가 로봇 범위를 초과하는지
  ③ 추종:   unity tgt ↔ act — 로봇이 명령을 물리로 따라가는지 (RMS)
  ④ 동작 재현: 사람 각도(raw) ↔ 로봇 실측(act) 최적지연 상관 — "손을 그대로 따라가는가"

사용:
  python analyze_teleop.py <vision_csv> <unity_csv> [--hand left] [--channels thumb pinky]
  python analyze_teleop.py --unity-only <unity_csv>          # 웹캠 없이 rx/tgt/act만
  파일명 대신 'latest' 를 주면 각 위치의 최신 파일 자동 선택.

판정 기준:
  상관 ≥0.90 PASS / 0.70~0.90 WARN / <0.70 FAIL,  추종 RMS ≤3°, 잔여오차 RMS ≤10°
"""
import argparse
import glob
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import DG5F_UNITY_LOGS, DG5F_URDF_DIR

from dg5f_angles import CHANNEL_NAMES, DG5F_CHANNELS

# 비전 로그(vision_dg5f_*.csv)는 스크립트 위치 기준 logs/ 하위
VISION_LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# 머신마다 다른 경로라 기본값을 박아두지 않는다 — .env(DG5F_UNITY_LOGS/DG5F_URDF_DIR)로
# 설정하거나 --logs-dir/--urdf-dir 로 직접 넘길 것. 둘 다 없으면 main()에서 명확히 에러를 낸다.
UNITY_LOGS = DG5F_UNITY_LOGS
URDF_DIR = DG5F_URDF_DIR
JOINT_KEYS = [f"{f}_{j}" for f in range(1, 6) for j in range(1, 5)]  # 채널 순서와 동일

CORR_PASS, CORR_WARN = 0.90, 0.70
TRACK_RMS_TOL = 3.0    # tgt vs act (deg)
FOLLOW_RMS_TOL = 10.0  # sent(clamp) vs act (deg)


def latest(pattern):
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not files:
        sys.exit(f"파일 없음: {pattern}")
    return files[-1]


def urdf_limits(hand):
    root = ET.parse(os.path.join(URDF_DIR, f"dg5f_{hand}.urdf")).getroot()
    out = {}
    for j in root.findall("joint"):
        if j.get("type") != "revolute":
            continue
        key = j.get("name").split("_dg_")[1]
        lim = j.find("limit")
        out[key] = (math.degrees(float(lim.get("lower"))),
                    math.degrees(float(lim.get("upper"))))
    return out


def best_lag_corr(t_a, a, t_b, b, max_lag=0.6, fs=50.0):
    """b(로봇)가 a(사람)를 따르는 최적 지연·상관. 공통 시간창을 fs로 리샘플."""
    lo, hi = max(t_a.min(), t_b.min()), min(t_a.max(), t_b.max())
    if hi - lo < 2.0:
        return np.nan, np.nan
    grid = np.arange(lo, hi, 1.0 / fs)
    ai = np.interp(grid, t_a, a)
    bi = np.interp(grid, t_b, b)
    if ai.std() < 1e-3 or bi.std() < 1e-3:
        return np.nan, np.nan
    lags = np.arange(0, int(max_lag * fs) + 1)  # 로봇은 뒤처지기만 한다고 가정
    best = (-2.0, 0)
    for L in lags:
        aa = ai[: len(ai) - L] if L else ai
        bb = bi[L:] if L else bi
        c = np.corrcoef(aa, bb)[0, 1]
        if c > best[0]:
            best = (c, L)
    return best[0], best[1] * 1000.0 / fs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vision", nargs="?", help="vision_dg5f_*.csv 또는 latest")
    ap.add_argument("unity", nargs="?", help="unity_dg5f_*.csv 또는 latest")
    ap.add_argument("--unity-only", metavar="UNITY_CSV", help="비전 로그 없이 unity 로그만")
    ap.add_argument("--hand", default="left", choices=["left", "right"])
    ap.add_argument("--channels", nargs="*", help="이름 부분일치 필터 (예: thumb pinky)")
    ap.add_argument("--logs-dir", default=None, help="Unity Logs 폴더 (기본: 상수/환경변수)")
    ap.add_argument("--urdf-dir", default=None, help="dg5f URDF 폴더 (기본: 상수/환경변수)")
    args = ap.parse_args()
    global UNITY_LOGS, URDF_DIR
    if args.logs_dir:
        UNITY_LOGS = args.logs_dir
    if args.urdf_dir:
        URDF_DIR = args.urdf_dir
    if not URDF_DIR:
        ap.error("--urdf-dir 가 필요합니다 (또는 레포 루트 .env에 DG5F_URDF_DIR 설정)")
    needs_unity_logs = args.unity_only == "latest" or args.unity == "latest"
    if needs_unity_logs and not UNITY_LOGS:
        ap.error("--logs-dir 가 필요합니다 (또는 레포 루트 .env에 DG5F_UNITY_LOGS 설정)")

    lim = urdf_limits(args.hand)
    gated = {c[0] for c in DG5F_CHANNELS if c[5]}

    if args.unity_only:
        upath = (latest(os.path.join(UNITY_LOGS, "unity_dg5f_*.csv"))
                 if args.unity_only == "latest" else args.unity_only)
        u = pd.read_csv(upath)
        print(f"[unity-only] {os.path.basename(upath)} — {len(u)}행 {u.t_unix.max()-u.t_unix.min():.1f}s")
        print(f"{'채널':10s} {'rx↔act상관':>9s} {'지연ms':>6s} {'tgt↔act RMS°':>12s}  판정")
        tu = u.t_unix.values
        for name, key in zip(CHANNEL_NAMES, JOINT_KEYS):
            if args.channels and not any(c in name for c in args.channels):
                continue
            rx, tgt, act = u[f"rx_{key}"].values, u[f"tgt_{key}"].values, u[f"act_{key}"].values
            lo_d, hi_d = lim[key]
            rx_cl = np.clip(np.nan_to_num(rx), lo_d, hi_d)
            corr, lag = best_lag_corr(tu, rx_cl, tu, act)
            r2 = float(np.sqrt(np.mean((tgt - act) ** 2)))
            if np.isnan(corr):
                verdict = "─ 무동작"
            else:
                verdict = "PASS" if corr >= CORR_PASS and r2 < TRACK_RMS_TOL else "❌확인"
            print(f"{name:10s} {corr:9.2f} {lag:6.0f} {r2:12.2f}  {verdict}")
        return

    vpath = (latest(os.path.join(VISION_LOGS, "vision_dg5f_*.csv"))
             if args.vision == "latest" else args.vision)
    upath = (latest(os.path.join(UNITY_LOGS, "unity_dg5f_*.csv"))
             if args.unity == "latest" else args.unity)
    v = pd.read_csv(vpath)
    u = pd.read_csv(upath)

    # 공통 시간창으로 절단
    lo, hi = max(v.t_unix.min(), u.t_unix.min()), min(v.t_unix.max(), u.t_unix.max())
    v = v[(v.t_unix >= lo) & (v.t_unix <= hi)]
    u = u[(u.t_unix >= lo) & (u.t_unix <= hi)]
    print(f"vision: {os.path.basename(vpath)} {len(v)}행 | unity: {os.path.basename(upath)} {len(u)}행 | 겹침 {hi-lo:.1f}s")
    if hi - lo < 3:
        sys.exit("두 로그의 시간이 안 겹칩니다 — 같은 세션의 파일인지 확인하세요.")

    print(f"\n{'채널':10s} {'①전송RMS°':>9s} {'②클램프%':>8s} {'③추종RMS°':>9s} {'④상관':>6s} {'지연ms':>6s} {'잔여RMS°':>8s}  판정")
    fails, warns = [], []
    for name, key in zip(CHANNEL_NAMES, JOINT_KEYS):
        if args.channels and not any(c in name for c in args.channels):
            continue
        if name in gated:
            continue  # 게이트 채널은 항상 상수 — 검증 무의미
        sent = v[f"filt_{name}"].values
        tv = v.t_unix.values
        rx = np.interp(tv, u.t_unix.values, u[f"rx_{key}"].values)
        tgt = u[f"tgt_{key}"].values
        act = u[f"act_{key}"].values
        tu = u.t_unix.values
        lo_d, hi_d = lim[key]

        transport = float(np.sqrt(np.nanmean((sent - rx) ** 2)))
        clamp_pct = float(((sent < lo_d) | (sent > hi_d)).mean() * 100)
        track = float(np.sqrt(np.mean((tgt - act) ** 2)))
        corr, lag = best_lag_corr(tv, np.clip(sent, lo_d, hi_d), tu, act)
        # 잔여오차: 최적지연 보정 후 clamp(sent) vs act
        if not np.isnan(corr):
            grid = np.arange(max(tv.min(), tu.min()), min(tv.max(), tu.max()), 0.02)
            si = np.interp(grid - lag / 1000.0, tv, np.clip(sent, lo_d, hi_d))
            aiv = np.interp(grid, tu, act)
            resid = float(np.sqrt(np.mean((si - aiv) ** 2)))
        else:
            resid = np.nan

        if np.isnan(corr):
            verdict = "─ 무동작"
        elif corr >= CORR_PASS and resid <= FOLLOW_RMS_TOL and track <= TRACK_RMS_TOL:
            verdict = "PASS"
        elif corr >= CORR_WARN:
            verdict = "⚠WARN"
            warns.append(name)
        else:
            verdict = "❌FAIL"
            fails.append(name)
        print(f"{name:10s} {transport:9.2f} {clamp_pct:8.1f} {track:9.2f} {corr:6.2f} {lag:6.0f} {resid:8.2f}  {verdict}")

    print("""
해석 가이드:
  ①전송 크면 → 프로토콜/순서 문제(코드).  ②클램프 크면 → 보정 범위가 로봇 리밋 초과(재보정/트림).
  ③추종 크면 → 물리/게인 문제.  ④상관 낮으면 → 매핑 자체가 사람 동작을 못 따름(프록시/방향).""")
    if fails:
        print("FAIL:", ", ".join(fails))
    if warns:
        print("WARN:", ", ".join(warns))
    if not fails and not warns:
        print("✅ 분석한 전 채널 PASS")


if __name__ == "__main__":
    main()
