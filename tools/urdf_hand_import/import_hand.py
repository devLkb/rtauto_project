# -*- coding: utf-8 -*-
"""URDF 로봇핸드 → Unity 임포트 파이프라인 (범용).

절차 (SVH·DG5F에서 검증된 순서 그대로):
  1. URDF + 메시를 Unity 프로젝트 Assets/Robots/<이름>/ 으로 복사,
     mesh filename의 package:// 경로를 URDF 기준 상대경로로 패치
  2. unity-cli exec 로 URDF-Importer 실행 (Y축 + vHACD)
  3. 임포트 결과 감사: 바디/revolute 수, 임포터 기본값 관성(mass=1, I=(1,1,1)) 링크
  4. (--verify) URDF 원본 vs Unity 물리값 전수 대조 (질량/CoM/관성/리밋/effort)
  5. (--prefab) Assets/Robots/Prefabs/<이름>.prefab 저장
  6. (--remove-instance) 씬에서 인스턴스 제거 (프리팹만 남김)

사용 예:
  python import_hand.py C:/path/to/hand.urdf --prefab
  python import_hand.py a.urdf b.urdf c.urdf --prefab --remove-instance
"""
import argparse
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_PROJECT, UNITY_CLI

# 머신마다 다른 경로라 기본값을 박아두지 않는다 — .env(RTAUTO_UNITY_PROJECT/RTAUTO_UNITY_CLI)로
# 설정하거나 --project/--cli 로 직접 넘길 것. 둘 다 없으면 main()에서 명확히 에러를 낸다.
DEFAULT_PROJECT = Path(UNITY_PROJECT) if UNITY_PROJECT else None
DEFAULT_CLI = Path(UNITY_CLI) if UNITY_CLI else None
EXEC_TIMEOUT = 600  # vHACD 포함 임포트 최대 대기(초)

# ⚠️ unity-cli exec 스니펫 제약(실측): using 지시문 불가(전부 풀네임),
#    $"" 문자열 보간 불가, 마지막에 return 필수. ImportSettings 필드명은 chosenAxis.
IMPORT_SNIPPET = """
UnityEditor.AssetDatabase.Refresh(UnityEditor.ImportAssetOptions.ForceSynchronousImport);
Unity.Robotics.UrdfImporter.ImportSettings settings = new Unity.Robotics.UrdfImporter.ImportSettings();
settings.chosenAxis = Unity.Robotics.UrdfImporter.ImportSettings.axisType.yAxis;
settings.convexMethod = Unity.Robotics.UrdfImporter.ImportSettings.convexDecomposer.@CONVEX@;
System.Collections.Generic.IEnumerator<UnityEngine.GameObject> it =
    Unity.Robotics.UrdfImporter.UrdfRobotExtensions.Create("@URDF@", settings, false, false);
while (it.MoveNext()) {}
UnityEngine.GameObject robot = it.Current;
if (robot == null) robot = UnityEngine.GameObject.Find("@NAME@");
if (robot == null) return "FAIL: robot GameObject not found after import";
UnityEngine.ArticulationBody[] bodies = robot.GetComponentsInChildren<UnityEngine.ArticulationBody>();
int rev = 0; int bad = 0;
foreach (UnityEngine.ArticulationBody b in bodies) {
  if (b.jointType == UnityEngine.ArticulationJointType.RevoluteJoint) rev++;
  UnityEngine.Vector3 t = b.inertiaTensor;
  if (b.mass == 1f || (t.x == 1f && t.y == 1f && t.z == 1f)) bad++;
}
string prefabMsg = "skipped";
if (@PREFAB@) {
  if (!UnityEditor.AssetDatabase.IsValidFolder("Assets/Robots/Prefabs"))
    UnityEditor.AssetDatabase.CreateFolder("Assets/Robots", "Prefabs");
  UnityEditor.PrefabUtility.SaveAsPrefabAsset(robot, "Assets/Robots/Prefabs/@NAME@.prefab");
  prefabMsg = "Assets/Robots/Prefabs/@NAME@.prefab";
}
if (@REMOVE@) { UnityEngine.Object.DestroyImmediate(robot); }
return "OK bodies=" + bodies.Length + " revolute=" + rev + " badInertia=" + bad + " prefab=" + prefabMsg;
"""


def parse_robot(urdf_path: Path):
    """URDF에서 로봇 이름과 mesh filename 목록을 얻는다."""
    root = ET.parse(urdf_path).getroot()
    name = root.get("name")
    meshes = sorted({m.get("filename") for m in root.iter("mesh") if m.get("filename")})
    return name, meshes


def resolve_mesh(filename: str, urdf_dir: Path):
    """mesh filename → (실제 파일 경로, 복사 후 상대경로). 실패 시 (None, None).

    package://a/b.stl 은 ① a/b.stl ② b.stl(첫 세그먼트가 ROS 패키지명인 경우) 순으로
    URDF 폴더 기준 탐색, 그래도 없으면 파일명으로 재귀 검색.
    """
    candidates = []
    if filename.startswith("package://"):
        rest = filename[len("package://"):]
        candidates.append(rest)
        if "/" in rest:
            candidates.append(rest.split("/", 1)[1])
    elif filename.startswith("file://"):
        candidates.append(filename[len("file://"):])
    else:
        candidates.append(filename)
    for c in candidates:
        p = urdf_dir / c
        if p.is_file():
            return p, Path(c).as_posix()
    hits = [h for h in urdf_dir.rglob(Path(filename).name) if h.is_file()]
    if hits:
        rel = hits[0].relative_to(urdf_dir).as_posix()
        return hits[0], rel
    return None, None


def prepare(urdf_path: Path, project: Path, name: str):
    """Assets/Robots/<name>/ 에 URDF+메시 복사, 경로 패치. 프로젝트 내 URDF 상대경로 반환."""
    urdf_dir = urdf_path.parent
    dest_root = project / "Assets" / "Robots" / name
    content = urdf_path.read_text(encoding="utf-8")
    _, mesh_files = parse_robot(urdf_path)

    missing, copied = [], 0
    for fn in mesh_files:
        src, rel = resolve_mesh(fn, urdf_dir)
        if src is None:
            missing.append(fn)
            continue
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
            copied += 1
        content = content.replace('"' + fn + '"', '"' + rel + '"')
    if missing:
        raise FileNotFoundError("메시 파일을 찾지 못함:\n  " + "\n  ".join(missing))

    dest_urdf = dest_root / (name + ".urdf")
    dest_root.mkdir(parents=True, exist_ok=True)
    dest_urdf.write_text(content, encoding="utf-8")
    print(f"  [준비] {dest_root} — 메시 {len(mesh_files)}개(신규복사 {copied}), URDF 경로 패치 완료")
    return f"Assets/Robots/{name}/{name}.urdf"


def unity_exec(cli: Path, code: str, retries: int = 4, extra=()) -> str:
    """C# 스니펫을 unity-cli exec 로 실행. 하트비트 순단('no Unity instances')은 재시도
    (Play 진입 직후 특히 잦음 — 2초 간격 재시도)."""
    import time
    last = ""
    for i in range(retries + 1):
        if i:
            time.sleep(2)
        r = subprocess.run([str(cli), "exec", *extra], input=code.encode("utf-8"),
                           capture_output=True, timeout=EXEC_TIMEOUT)
        out = r.stdout.decode("utf-8", "replace").strip()
        err = r.stderr.decode("utf-8", "replace").strip()
        if r.returncode == 0:
            return out
        last = err or out
        if "no Unity instances" not in last:
            break
    raise RuntimeError(f"unity-cli exec 실패: {last}")


def import_one(urdf_path: Path, args) -> bool:
    name, _ = parse_robot(urdf_path)
    if args.name:
        name = args.name
    print(f"[{name}] {urdf_path}")

    rel_urdf = prepare(urdf_path, args.project, name)

    code = (IMPORT_SNIPPET
            .replace("@URDF@", rel_urdf)
            .replace("@NAME@", name)
            .replace("@CONVEX@", "unity" if args.no_vhacd else "vHACD")
            .replace("@PREFAB@", "true" if args.prefab else "false")
            .replace("@REMOVE@", "true" if args.remove_instance else "false"))
    result = unity_exec(args.cli, code)
    print(f"  [임포트] {result}")
    ok = result.startswith("OK") and "badInertia=0" in result
    if not ok:
        print("  ⚠️ 임포트 결과 확인 필요 (badInertia>0 이면 SVH 진동 사태 패턴 — WORKLOG §12 참고)")

    if args.verify:
        if args.remove_instance:
            print("  [검증] --remove-instance 와 --verify 는 함께 못 씀 (인스턴스가 씬에 있어야 대조 가능) — 건너뜀")
        else:
            import phys_compare
            ok = phys_compare.verify(urdf_path, name, args.project, args.cli) and ok
    return ok


def main():
    ap = argparse.ArgumentParser(description="URDF 핸드 → Unity 임포트 파이프라인")
    ap.add_argument("urdf", nargs="+", type=Path, help="URDF 파일 경로 (여러 개 가능)")
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="Unity 프로젝트 루트")
    ap.add_argument("--cli", type=Path, default=DEFAULT_CLI, help="unity-cli 실행파일")
    ap.add_argument("--name", help="Assets/Robots 폴더·프리팹 이름 강제 지정 (기본: URDF robot name, 단일 파일일 때만)")
    ap.add_argument("--prefab", action="store_true", help="Assets/Robots/Prefabs/<이름>.prefab 저장")
    ap.add_argument("--remove-instance", action="store_true", help="임포트 후 씬 인스턴스 제거 (프리팹만 남김)")
    ap.add_argument("--verify", action="store_true", help="URDF 원본 vs Unity 물리값 전수 대조 (numpy 필요)")
    ap.add_argument("--no-vhacd", action="store_true", help="콜리전 분해를 vHACD 대신 unity 기본으로")
    args = ap.parse_args()

    if args.name and len(args.urdf) > 1:
        ap.error("--name 은 URDF 1개일 때만 사용")
    if args.project is None:
        ap.error("--project 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_PROJECT 설정)")
    if args.cli is None:
        ap.error("--cli 가 필요합니다 (또는 레포 루트 .env에 RTAUTO_UNITY_CLI 설정)")

    results = {}
    for u in args.urdf:
        if not u.is_file():
            print(f"[에러] 파일 없음: {u}")
            results[str(u)] = False
            continue
        try:
            results[str(u)] = import_one(u.resolve(), args)
        except Exception as e:  # noqa: BLE001 — 파일별 실패를 모아서 보고
            print(f"  [에러] {e}")
            results[str(u)] = False

    print("\n=== 요약 ===")
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
