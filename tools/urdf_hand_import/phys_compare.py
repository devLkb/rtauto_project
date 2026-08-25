# -*- coding: utf-8 -*-
"""Unity에 임포트된 로봇 vs URDF 원본 물리값 전수 대조.

비교 항목:
  질량 / 무게중심(URDF (x,y,z) → Unity (-y,z,x) 변환) / 관성(행렬 고유값 vs Unity 주관성값)
  / revolute 리밋(rad→deg, 임포터 부호반전 허용) / effort→forceLimit

알려진 정상 편차:
  - PhysX 최소 관성 클램프: URDF 관성이 1e-6 미만이면 Unity가 (1e-6,1e-6,1e-6)으로
    올림 → WARN 처리 (안전한 방향, DG5F 팁 5개에서 실측)

단독 실행:
  python phys_compare.py <urdf경로> [--name 로봇이름] — 해당 로봇 인스턴스가 씬에 있어야 함
"""
import argparse
import csv
import io
import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

MASS_TOL = 1e-3      # kg
COM_TOL = 1e-4       # m
INERTIA_RTOL = 0.02  # 상대 2%
LIM_TOL = 0.1        # deg
PHYSX_MIN_INERTIA = 1e-6

DUMP_SNIPPET = """
UnityEngine.GameObject robot = UnityEngine.GameObject.Find("@NAME@");
if (robot == null) return "FAIL: @NAME@ not in scene";
System.Text.StringBuilder sb = new System.Text.StringBuilder();
sb.AppendLine("name,mass,comX,comY,comZ,itX,itY,itZ,jointType,lowerDeg,upperDeg,forceLimit");
foreach (UnityEngine.ArticulationBody b in robot.GetComponentsInChildren<UnityEngine.ArticulationBody>()) {
  UnityEngine.Vector3 com = b.centerOfMass;
  UnityEngine.Vector3 it = b.inertiaTensor;
  UnityEngine.ArticulationDrive d = b.xDrive;
  sb.AppendLine(b.name + "," + b.mass.ToString("F6")
    + "," + com.x.ToString("F6") + "," + com.y.ToString("F6") + "," + com.z.ToString("F6")
    + "," + it.x.ToString("E6") + "," + it.y.ToString("E6") + "," + it.z.ToString("E6")
    + "," + b.jointType + "," + d.lowerLimit.ToString("F4") + "," + d.upperLimit.ToString("F4")
    + "," + d.forceLimit.ToString("F4"));
}
return sb.ToString();
"""


def parse_urdf(urdf_path: Path):
    import numpy as np
    root = ET.parse(urdf_path).getroot()
    links, joints = {}, {}
    for link in root.findall("link"):
        inertial = link.find("inertial")
        if inertial is None:
            continue
        mass = float(inertial.find("mass").get("value"))
        o = inertial.find("origin")
        xyz = [float(v) for v in (o.get("xyz") if o is not None else "0 0 0").split()]
        i = inertial.find("inertia")
        ixx, ixy, ixz = float(i.get("ixx")), float(i.get("ixy")), float(i.get("ixz"))
        iyy, iyz, izz = float(i.get("iyy")), float(i.get("iyz")), float(i.get("izz"))
        M = np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]])
        links[link.get("name")] = dict(
            mass=mass,
            com=(-xyz[1], xyz[2], xyz[0]),  # URDF (x,y,z) → Unity (-y,z,x)
            eig=np.sort(np.linalg.eigvalsh(M)))
    for j in root.findall("joint"):
        if j.get("type") != "revolute":
            continue
        lim = j.find("limit")
        joints[j.find("child").get("link")] = dict(
            lower=math.degrees(float(lim.get("lower"))),
            upper=math.degrees(float(lim.get("upper"))),
            effort=float(lim.get("effort")))
    return links, joints


def verify(urdf_path: Path, name: str, project: Path, cli: Path) -> bool:
    """URDF vs 씬 인스턴스 대조. project 인자는 시그니처 통일용(현재 미사용)."""
    import numpy as np
    r = subprocess.run([str(cli), "exec"],
                       input=DUMP_SNIPPET.replace("@NAME@", name).encode("utf-8"),
                       capture_output=True, timeout=120)
    out = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode != 0 or out.startswith("FAIL"):
        print(f"  [검증] 덤프 실패: {out or r.stderr.decode('utf-8', 'replace')}")
        return False

    rows = list(csv.DictReader(io.StringIO(out)))
    links, joints = parse_urdf(urdf_path)
    fails, warns = [], []

    for row in rows:
        n = row["name"]
        u = links.get(n)
        if u is None:
            warns.append(f"{n}: URDF에 inertial 없음 (임포터 추정값 사용)")
            continue
        if abs(float(row["mass"]) - u["mass"]) > MASS_TOL:
            fails.append(f"{n}: 질량 unity={row['mass']} urdf={u['mass']}")
        com = np.array([float(row["comX"]), float(row["comY"]), float(row["comZ"])])
        d = float(np.linalg.norm(com - np.array(u["com"])))
        if d > COM_TOL:
            fails.append(f"{n}: CoM {d*1000:.2f}mm 어긋남")
        it = np.sort([float(row["itX"]), float(row["itY"]), float(row["itZ"])])
        rel = np.abs(it - u["eig"]) / np.maximum(u["eig"], 1e-12)
        if rel.max() > INERTIA_RTOL:
            clamped = (np.allclose(it, PHYSX_MIN_INERTIA, rtol=1e-3)
                       and u["eig"].max() < PHYSX_MIN_INERTIA)
            if clamped:
                warns.append(f"{n}: 관성 PhysX 최소값(1e-6) 클램프 (urdf max={u['eig'].max():.2e}) — 무해")
            else:
                fails.append(f"{n}: 관성 고유값 불일치 unity={it} urdf={u['eig']}")
        uj = joints.get(n)
        if row["jointType"] == "RevoluteJoint" and uj is not None:
            lo, up = float(row["lowerDeg"]), float(row["upperDeg"])
            same = abs(lo - uj["lower"]) < LIM_TOL and abs(up - uj["upper"]) < LIM_TOL
            flip = abs(lo + uj["upper"]) < LIM_TOL and abs(up + uj["lower"]) < LIM_TOL
            if not (same or flip):
                fails.append(f"{n}: 리밋 unity=({lo},{up}) urdf=({uj['lower']:.2f},{uj['upper']:.2f})")
            fl = float(row["forceLimit"])
            if fl < 1e30 and abs(fl - uj["effort"]) > 0.01:
                fails.append(f"{n}: forceLimit={fl} vs effort={uj['effort']}")
        elif row["jointType"] == "RevoluteJoint" and uj is None:
            fails.append(f"{n}: Unity revolute인데 URDF revolute 아님")
        elif row["jointType"] != "RevoluteJoint" and uj is not None:
            fails.append(f"{n}: URDF revolute인데 Unity {row['jointType']}")

    for w in warns:
        print(f"  [검증] WARN {w}")
    for f in fails:
        print(f"  [검증] FAIL {f}")
    print(f"  [검증] 바디 {len(rows)}개 대조 → {'전 항목 통과' if not fails else str(len(fails)) + '건 불일치'}"
          + (f" (경고 {len(warns)}건)" if warns else ""))
    return not fails


def main():
    import import_hand
    ap = argparse.ArgumentParser(description="URDF vs Unity 물리값 대조 (로봇이 씬에 있어야 함)")
    ap.add_argument("urdf", type=Path)
    ap.add_argument("--name", help="씬의 로봇 GameObject 이름 (기본: URDF robot name)")
    ap.add_argument("--project", type=Path, default=import_hand.DEFAULT_PROJECT)
    ap.add_argument("--cli", type=Path, default=import_hand.DEFAULT_CLI)
    args = ap.parse_args()
    if args.project is None:
        ap.error("--project 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_PROJECT 설정)")
    if args.cli is None:
        ap.error("--cli 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_CLI 설정)")
    name = args.name or ET.parse(args.urdf).getroot().get("name")
    ok = verify(args.urdf.resolve(), name, args.project, args.cli)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
