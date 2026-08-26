# -*- coding: utf-8 -*-
"""
Dg5fThumbIK 디버그 CSV 분석 — "노랑·빨강은 일치하는데 초록(로봇 실측)만 먼" 문제를 계층 분리.

사용:
  python analyze_thumbik.py            # 최신 thumbik_*.csv 자동
  python analyze_thumbik.py latest
  python analyze_thumbik.py <경로.csv>

로그 폴더: 환경변수 DG5F_UNITY_LOGS (기본: Unity 프로젝트 Logs/)

판정 로직:
  - corr(n_축, ach_축) < 0        → 그 축 부호 반전 (좌우 미러/축 정의 불일치)
  - corr 높은데 bias(ach−n) 큼    → 상수 오프셋 (베이스/프레임 원점 문제)
  - err_red 큰데 stall_scale 바닥 → 도달 불가 목표에서 stall damper가 정지시킨 것
  - |tgt−act| 큼                  → IK는 명령을 냈는데 물리가 못 따라감 (드라이브/충돌)
  - |tgt−act| 작고 err_red 큼     → 관절은 명령대로인데 손끝이 목표 밖
                                     = 그 목표가 관절 리밋/작업공간 밖 (IK 기하 문제)
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import DG5F_UNITY_LOGS

# 머신마다 다른 경로라 기본값을 박아두지 않는다 — .env에 DG5F_UNITY_LOGS 설정할 것.
DEFAULT_LOG_DIR = DG5F_UNITY_LOGS


def find_csv(arg):
    if arg and arg != "latest":
        return arg
    if not DEFAULT_LOG_DIR:
        sys.exit("[오류] 로그 폴더가 필요합니다 (레포 루트 .env에 DG5F_UNITY_LOGS 설정)")
    files = sorted(glob.glob(os.path.join(DEFAULT_LOG_DIR, "thumbik_*.csv")),
                   key=os.path.getmtime)
    if not files:
        sys.exit(f"[오류] {DEFAULT_LOG_DIR} 에 thumbik_*.csv 없음")
    return files[-1]


def main():
    path = find_csv(sys.argv[1] if len(sys.argv) > 1 else None)
    df = pd.read_csv(path)
    dur = df.t_unix.iloc[-1] - df.t_unix.iloc[0]
    print(f"파일: {path}")
    print(f"샘플 {len(df)}개 / {dur:.1f}s ({len(df) / max(dur, 1e-9):.0f}Hz)\n")

    # ── 1. 목표 거리 요약 (cm) ─────────────────────────────────────────
    print("── 1. 손끝-목표 거리 (cm) ──")
    for col, label in [("err_red", "빨강(CCD 목표)↔초록(실측)"),
                       ("err_yel", "노랑(UDP 복원)↔초록(실측)")]:
        e = df[col] * 100
        print(f"  {label}: 평균 {e.mean():.2f} / 중앙 {e.median():.2f}"
              f" / p95 {e.quantile(0.95):.2f} / 최대 {e.max():.2f}")

    # ── 2. 축별 비교: UDP 비율(n) vs 로봇 달성 비율(ach) ──────────────
    print("\n── 2. 축별 UDP 명령 비율 vs 로봇 달성 비율 ──")
    print("  (같은 좌표계·스케일 — corr<0=부호반전, corr 높고 bias 크면 오프셋)")
    verdicts = []
    for ax in "xyz":
        n, a = df[f"n_{ax}"], df[f"ach_{ax}"]
        moved = n.std() > 0.02  # 입력이 거의 안 움직인 축은 corr 무의미
        corr = n.corr(a) if moved else float("nan")
        bias = (a - n).mean()
        print(f"  {ax}: corr={corr: .3f}  bias(ach-n)={bias:+.3f}"
              f"  n범위[{n.min():.2f},{n.max():.2f}]"
              f"  ach범위[{a.min():.2f},{a.max():.2f}]"
              f"{'' if moved else '  (입력 정지 — corr 판정 제외)'}")
        if moved and corr < -0.3:
            verdicts.append(f"❌ {ax}축 부호 반전 의심 (corr={corr:.2f})")
        elif moved and corr < 0.5:
            verdicts.append(f"⚠️ {ax}축 추종 불량 (corr={corr:.2f})")
        if abs(bias) > 0.15:
            verdicts.append(f"⚠️ {ax}축 상수 편차 {bias:+.2f} (프레임/오프셋 의심)")

    # ── 3. stall damper 상태 ──────────────────────────────────────────
    print("\n── 3. stall damper ──")
    ss = df.stall_scale
    frac_low = (ss < 0.5).mean() * 100
    print(f"  stall_scale: 평균 {ss.mean():.2f} / 최소 {ss.min():.2f}"
          f" / 0.5 미만 시간 {frac_low:.0f}%")
    err_when_low = df.loc[ss < 0.5, "err_red"] * 100
    if len(err_when_low):
        print(f"  damper 감쇠 중 평균 오차 {err_when_low.mean():.2f}cm"
              " — 크면 '도달 불가 목표에서 포기하고 정지' 패턴")
        if err_when_low.mean() > 1.5:
            verdicts.append("⚠️ stall damper가 큰 오차 상태에서 정지시킴"
                            " → 목표가 작업공간/리밋 밖일 가능성")

    # ── 4. 관절 명령 vs 실측 ──────────────────────────────────────────
    print("\n── 4. 엄지 관절 |tgt−act| (deg) ──")
    joint_ok = True
    for j in range(1, 5):
        d = (df[f"tgt_1_{j}"] - df[f"act_1_{j}"]).abs()
        print(f"  1_{j}: 평균 {d.mean():.2f} / 최대 {d.max():.2f}"
              f"   tgt범위[{df[f'tgt_1_{j}'].min():.1f},{df[f'tgt_1_{j}'].max():.1f}]")
        if d.mean() > 5:
            joint_ok = False
            verdicts.append(f"⚠️ 관절 1_{j} 물리 추종 불량 (평균 {d.mean():.1f}°)")
    if joint_ok and (df.err_red * 100).mean() > 1.5:
        verdicts.append("⚠️ 관절은 명령대로인데 손끝은 목표 밖"
                        " → IK가 낼 수 있는 명령의 한계(리밋/기하) — 목표 자체 재검토")

    # ── 5. 핀치 ────────────────────────────────────────────────────────
    pw = df.pinch_w
    print(f"\n── 5. 핀치 — pinch_w 평균 {pw.mean():.2f}, 1.0 근접 시간 {(pw > 0.9).mean() * 100:.0f}%")

    print("\n══ 종합 판정 ══")
    if verdicts:
        for v in dict.fromkeys(verdicts):
            print("  " + v)
    else:
        print("  특이사항 없음 — 전 축 추종 정상 범위")


if __name__ == "__main__":
    main()
