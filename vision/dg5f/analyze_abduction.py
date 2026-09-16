# -*- coding: utf-8 -*-
"""벌림(손가락이 옆으로 벌어진 각도) 계산 방식 비교 — 실제 손 녹화 기록으로 판정한다.

무엇을 답하나:
  ① 새 계산식이 **굽힘에 덜 끌려다니는가** — 새끼만 굽혔다 펴는 녹화에서 좌우값이
     얼마나 움직이는지 본다. 작을수록 좋다(이상적으로는 0).
  ② 새 계산식이 **벌림은 제대로 잡는가** — 새끼만 벌렸다 오므리는 녹화에서 값이
     충분히 크게 움직이는지 본다. 클수록 좋다.
  ③ 그래서 **로봇에 허용할 범위를 얼마로 잡아야 하는가** — 실제 사람 값 분포에서 제안한다.

가상 손으로 하는 검증은 tests/test_abduction.py가 이미 한다(정답을 아는 대신 실제 손의
버릇·카메라 노이즈는 못 담는다). 이 스크립트는 그 반대 — 정답은 모르지만 **진짜 손**이다.

녹화 방법 (터미널, 리포 루트, venv 활성화 상태):
    python vision/dg5f/probe_landmarks.py spread   # 손 편 채로 새끼만 벌렸다 오므리기 (20초)
    python vision/dg5f/probe_landmarks.py bend     # 새끼만 굽혔다 폈다 (20초, 벌리지 말 것)
  둘 다 logs/lmprobe_<라벨>_<시각>.csv 로 저장된다(미리보기 창에서 q로 종료).

분석:
    python vision/dg5f/analyze_abduction.py                 # logs/에서 라벨별 최신 파일 자동
    python vision/dg5f/analyze_abduction.py 파일1.csv 파일2.csv
"""
import glob
import math
import os
import sys

import numpy as np
import pandas as pd

import dg5f_angles as A
from dg5f_paths import LOG_DIR

FINGERS = [("검지", A.INDEX), ("약지", A.RING), ("새끼", A.PINKY)]
LABELS = ("spread", "bend")


def load(path):
    df = pd.read_csv(path)
    df = df[df["detected"] == 1]
    lm = df[[f"lm{i}_{a}" for i in range(21) for a in "xyz"]].to_numpy()
    return lm.reshape(len(df), 21, 3)


def series(frames, fn):
    return np.array([math.degrees(fn(f)) for f in frames], dtype=float)


def span(vals):
    """실제로 움직인 폭(끝단 노이즈를 빼려고 p2~p98로 본다)."""
    return float(np.percentile(vals, 98) - np.percentile(vals, 2))


def corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def pick_latest():
    found = {}
    for label in LABELS:
        hits = sorted(glob.glob(os.path.join(LOG_DIR, f"lmprobe_{label}_*.csv")))
        if hits:
            found[label] = hits[-1]
    return found


def report(label, path):
    frames = load(path)
    print(f"\n── {label} 녹화: {os.path.basename(path)} ({len(frames)}프레임) ──")
    if len(frames) < 30:
        print("   프레임이 너무 적다 — 최소 20초는 녹화할 것.")
        return
    for name, finger in FINGERS:
        old = series(frames, lambda f: A._abduction_planar(f, finger))
        new = series(frames, lambda f: A._abduction_lateral(f, finger))
        bend = series(frames, lambda f: A._bend_mcp(f, finger))
        print(f"  {name}: 좌우값이 움직인 폭 — 옛 방식 {span(old):6.1f}°  새 방식 {span(new):6.1f}°"
              f"   |  굽힘과 같이 움직인 정도 — 옛 {corr(old, bend):+.2f}  새 {corr(new, bend):+.2f}")


def recommend(path):
    """벌림 녹화에서 '사람이 실제로 내는 값' 분포 → 로봇 허용 범위 제안."""
    frames = load(path)
    print("\n── 로봇에 허용할 범위 제안 (벌림 녹화 기준) ──")
    print("   사람 값의 p2~p98을 담되, 실물 기구 한계를 넘지 않게 자른 값이다.")
    for name, finger in FINGERS:
        new = series(frames, lambda f: A._abduction_lateral(f, finger))
        lo, hi = np.percentile(new, 2), np.percentile(new, 98)
        ch = {"검지": "index_abd", "약지": "ring_abd", "새끼": "pinky_lat"}[name]
        cur = next((c for c in A.DG5F_CHANNELS if c[0] == ch), None)
        urdf = A.URDF_LIMITS_DEG.get(ch)
        print(f"  {name}({ch}): 사람 {lo:+6.1f}° ~ {hi:+6.1f}°  "
              f"| 지금 허용 {cur[3]:+.0f}° ~ {cur[4]:+.0f}°  | 기구 한계(좌수 URDF) {urdf}")


def main(argv):
    paths = argv or []
    if not paths:
        found = pick_latest()
        if not found:
            print("[오류] logs/에 lmprobe_spread_*.csv / lmprobe_bend_*.csv 가 없습니다.\n"
                  "       먼저 녹화하세요 (이 파일 맨 위 설명 참고):\n"
                  "         python vision/dg5f/probe_landmarks.py spread\n"
                  "         python vision/dg5f/probe_landmarks.py bend")
            return 1
        paths = list(found.values())

    spread_path = None
    for p in paths:
        label = next((l for l in LABELS if f"lmprobe_{l}_" in os.path.basename(p)), "?")
        report(label, p)
        if label == "spread":
            spread_path = p

    print("\n[읽는 법] '굽힘과 같이 움직인 정도'가 0에 가까울수록 좋다 — 굽히기만 했는데 "
          "좌우값이 따라 움직이면 로봇 손가락이 엉뚱하게 옆으로 흔들린다.")
    print("          bend 녹화에서 '좌우값이 움직인 폭'은 작을수록, spread 녹화에서는 "
          "클수록 좋은 계산식이다.")
    if spread_path:
        recommend(spread_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
