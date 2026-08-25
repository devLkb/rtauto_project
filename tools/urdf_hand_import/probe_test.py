# -*- coding: utf-8 -*-
"""움직임 검증 프로브 (범용): 전 revolute 관절에 사각파 명령 → 추종·진동·리밋 자동 판정.

동작:
  1. Play 진입 → 각 관절을 자기 가동범위의 fracB(기본 15%) ↔ fracA(기본 80%) 로
     사각파 왕복 (기본 8페이즈 = 4사이클, 페이즈당 1.5s)
  2. 에디터 업데이트마다 명령(cmd)/실측(act) 각도를 CSV 기록
  3. pandas 분석 → 관절별 정착오차 / 정상상태 잔여진동(p2p) / 리밋 침범 판정

합격 기준 (SVH 진동 디버깅에서 확립한 지표):
  - 정착오차(페이즈 끝 0.3s 평균 |act-cmd|) ≤ 1.0°
  - 정상상태 잔여진동(페이즈 끝 0.5s act p2p) ≤ 0.5°
  - 리밋 침범(가동범위 ±0.5° 밖) 0건   (--urdf 지정 시)

사용 예:
  python probe_test.py dg5f_right --urdf C:/path/dg5f_right.urdf
  python probe_test.py my_hand --phases 4 --frac-a 0.6   # 짧고 얕게
"""
import argparse
import math
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import import_hand  # DEFAULT_PROJECT, DEFAULT_CLI 재사용

PROBE_SNIPPET = """
UnityEngine.GameObject robot = UnityEngine.GameObject.Find("@NAME@");
if (robot == null) return "FAIL: @NAME@ not in scene";
if (!UnityEditor.EditorApplication.isPlaying) return "FAIL: not in Play mode";
System.Collections.Generic.List<UnityEngine.ArticulationBody> joints = new System.Collections.Generic.List<UnityEngine.ArticulationBody>();
foreach (UnityEngine.ArticulationBody b in robot.GetComponentsInChildren<UnityEngine.ArticulationBody>()) {
  if (b.jointType == UnityEngine.ArticulationJointType.RevoluteJoint) joints.Add(b);
}
if (joints.Count == 0) return "FAIL: no revolute joints";
System.Text.StringBuilder log = new System.Text.StringBuilder();
System.Text.StringBuilder hdr = new System.Text.StringBuilder("t");
foreach (UnityEngine.ArticulationBody b in joints) { hdr.Append("," + b.name + "_cmd," + b.name + "_act"); }
log.AppendLine(hdr.ToString());
double t0 = UnityEditor.EditorApplication.timeSinceStartup;
float settle = @SETTLE@f; float phaseDur = @PHASE@f; int phases = @NPHASES@;
float fracA = @FRACA@f; float fracB = @FRACB@f;
string outPath = System.IO.Path.Combine(UnityEngine.Application.dataPath, "../Logs/@OUT@");
UnityEditor.EditorApplication.CallbackFunction cb = null;
cb = () => {
  double t = UnityEditor.EditorApplication.timeSinceStartup - t0;
  float frac = fracB;
  if (t > settle) {
    int p = (int)((t - settle) / phaseDur);
    if (p >= phases) {
      System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(outPath));
      System.IO.File.WriteAllText(outPath, log.ToString());
      UnityEditor.EditorApplication.update -= cb;
      UnityEngine.Debug.Log("[probe] done -> " + outPath);
      return;
    }
    frac = (p % 2 == 0) ? fracA : fracB;
  }
  System.Text.StringBuilder line = new System.Text.StringBuilder(t.ToString("F3"));
  foreach (UnityEngine.ArticulationBody b in joints) {
    UnityEngine.ArticulationDrive d = b.xDrive;
    float target = d.lowerLimit + frac * (d.upperLimit - d.lowerLimit);
    d.target = target; b.xDrive = d;
    float act = b.jointPosition[0] * UnityEngine.Mathf.Rad2Deg;
    line.Append("," + target.ToString("F3") + "," + act.ToString("F3"));
  }
  log.AppendLine(line.ToString());
};
UnityEditor.EditorApplication.update += cb;
return "probe started: joints=" + joints.Count + ", duration=" + (settle + phases * phaseDur).ToString("F1") + "s";
"""

SETTLE_WIN = 0.3   # 정착오차 측정 구간(페이즈 끝, 초)
P2P_WIN = 0.5      # 잔여진동 측정 구간(페이즈 끝, 초)
SETTLE_TOL = 1.0   # deg
P2P_TOL = 0.5      # deg
LIMIT_MARGIN = 0.5 # deg


def cli_run(cli, *args_, timeout=120):
    r = subprocess.run([str(cli)] + list(args_), capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def urdf_limits(urdf_path):
    """child link 이름 → (lower deg, upper deg)"""
    root = ET.parse(urdf_path).getroot()
    out = {}
    for j in root.findall("joint"):
        if j.get("type") != "revolute":
            continue
        lim = j.find("limit")
        out[j.find("child").get("link")] = (
            math.degrees(float(lim.get("lower"))), math.degrees(float(lim.get("upper"))))
    return out


def analyze(csv_path, settle, phase_dur, phases, limits):
    import pandas as pd
    df = pd.read_csv(csv_path)
    joints = [c[:-4] for c in df.columns if c.endswith("_cmd")]
    report, fails = [], []
    for j in joints:
        act = df[j + "_act"]
        worst_settle, worst_p2p = 0.0, 0.0
        for p in range(phases):
            t_end = settle + (p + 1) * phase_dur
            w1 = df[(df.t > t_end - SETTLE_WIN) & (df.t <= t_end)]
            w2 = df[(df.t > t_end - P2P_WIN) & (df.t <= t_end)]
            if len(w1) < 3:
                continue
            worst_settle = max(worst_settle, float((w1[j + "_act"] - w1[j + "_cmd"]).abs().mean()))
            worst_p2p = max(worst_p2p, float(w2[j + "_act"].max() - w2[j + "_act"].min()))
        viol = 0
        if limits and j in limits:
            lo, up = limits[j]
            viol = int(((act < lo - LIMIT_MARGIN) | (act > up + LIMIT_MARGIN)).sum())
        ok = worst_settle <= SETTLE_TOL and worst_p2p <= P2P_TOL and viol == 0
        report.append((j, worst_settle, worst_p2p, viol, ok))
        if not ok:
            fails.append(j)

    print(f"\n{'관절':24s} {'정착오차°':>9s} {'잔여진동°':>9s} {'리밋침범':>7s}  판정")
    for j, se, pp, v, ok in report:
        print(f"{j:24s} {se:9.3f} {pp:9.3f} {v:7d}  {'PASS' if ok else '❌FAIL'}")
    n_ok = sum(1 for r in report if r[4])
    print(f"\n샘플 {len(df)}행({df.t.max():.1f}s) | 관절 {n_ok}/{len(report)} 합격"
          f" | 기준: 정착≤{SETTLE_TOL}° 진동≤{P2P_TOL}° 침범=0")
    return not fails


def main():
    ap = argparse.ArgumentParser(description="관절 구동 프로브 테스트")
    ap.add_argument("name", help="씬의 로봇 GameObject 이름")
    ap.add_argument("--urdf", type=Path, help="리밋 침범 검사용 URDF (권장)")
    ap.add_argument("--project", type=Path, default=import_hand.DEFAULT_PROJECT)
    ap.add_argument("--cli", type=Path, default=import_hand.DEFAULT_CLI)
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--phase-dur", type=float, default=1.5)
    ap.add_argument("--phases", type=int, default=8)
    ap.add_argument("--frac-a", type=float, default=0.8)
    ap.add_argument("--frac-b", type=float, default=0.15)
    ap.add_argument("--keep-play", action="store_true", help="테스트 후 Play 유지 (추가 관찰용)")
    args = ap.parse_args()
    if args.project is None:
        ap.error("--project 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_PROJECT 설정)")
    if args.cli is None:
        ap.error("--cli 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_CLI 설정)")

    out_name = f"probe_{args.name}.csv"
    csv_path = args.project / "Logs" / out_name
    if csv_path.exists():
        csv_path.unlink()

    print("[1/4] Play 진입...")
    rc, out = cli_run(args.cli, "editor", "play", "--wait", timeout=180)
    if rc != 0:
        sys.exit(f"Play 실패: {out}")

    print("[2/4] 프로브 시작...")
    code = (PROBE_SNIPPET
            .replace("@NAME@", args.name).replace("@OUT@", out_name)
            .replace("@SETTLE@", str(args.settle)).replace("@PHASE@", str(args.phase_dur))
            .replace("@NPHASES@", str(args.phases))
            .replace("@FRACA@", str(args.frac_a)).replace("@FRACB@", str(args.frac_b)))
    try:
        out = import_hand.unity_exec(args.cli, code, extra=("--allow-async",))
    except RuntimeError as e:
        cli_run(args.cli, "editor", "stop", "--wait")
        sys.exit(f"프로브 시작 실패: {e}")
    print("   ", out)
    if out.startswith("FAIL"):
        cli_run(args.cli, "editor", "stop", "--wait")
        sys.exit(f"프로브 시작 실패: {out}")

    duration = args.settle + args.phases * args.phase_dur
    print(f"[3/4] 완료 대기 (~{duration:.0f}s)...")
    deadline = time.time() + duration + 30
    while time.time() < deadline and not csv_path.exists():
        time.sleep(1)
    if not args.keep_play:
        cli_run(args.cli, "editor", "stop", "--wait", timeout=180)
    if not csv_path.exists():
        sys.exit("CSV가 생성되지 않음 — Unity 콘솔 확인 필요")

    print(f"[4/4] 분석: {csv_path}")
    limits = urdf_limits(args.urdf) if args.urdf else None
    if not args.urdf:
        print("    (참고: --urdf 미지정이라 리밋 침범 검사 생략)")
    ok = analyze(csv_path, args.settle, args.phase_dur, args.phases, limits)
    print("\n" + ("✅ 전체 PASS — 구동 검증 완료" if ok else "❌ FAIL 항목 있음 — 게인/관성/충돌 점검 필요"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
