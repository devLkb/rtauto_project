# -*- coding: utf-8 -*-
"""UR 팔 + Tesollo DG5F 손 → 단일 결합 URDF 빌드 (기종·좌우 파라미터화).

기존 `ur5e_svh_build/convert_ur.py`(xacro→flat URDF)와
`ur5e_dg5f_build/merge_dg5f.py`(결합)를 하나로 합치고, 거기에 박혀 있던
특정 개발자 PC 경로와 ur5e·왼손 고정을 전부 제거한 버전이다.

규칙(기존 스크립트에서 계승):
- UR tool0 --(fixed, identity)--> <접두사>dg_mount 연결 (DG5F가 플랜지 마운트를 자체 보유)
- mesh 경로 통일 — Unity import_hand.py가 URDF 기준 상대경로로 해석한다:
    UR  : package://ur_description/meshes/...   -> meshes/ur/...
    DG5F: package://meshes/<변형>/...           -> meshes/<변형>/...
- 메시 실파일도 출력 폴더 아래로 복사 (빌드 폴더 자체가 임포트 소스)
- DG5F는 mimic 없음(20관절 독립)

⚠️ 링크 접두사는 손에 따라 다르다(URDF 실측): 왼손 `ll_`, 오른손 `rl_`.

사용:
  python build_arm_hand.py                          # config 기본값(UR_TYPE/DG5F_HAND)
  python build_arm_hand.py --ur-type ur5e --hand left
  python build_arm_hand.py --ur-description D:/src/Universal_Robots_ROS2_Description

UR description은 저장소에 포함하지 않는 외부 공개 레포다. 경로는
`.env`의 `RTAUTO_UR_DESCRIPTION` 또는 `--ur-description`으로 준다.
"""
import argparse
import shutil
import sys
import types
from pathlib import Path

import lxml.etree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import rtauto_config as cfg

URDF_ROOT = Path(__file__).resolve().parent


def flatten_ur(ur_share: Path, ur_type: str, out_path: Path) -> Path:
    """UR xacro → flat URDF. ROS 없이 돌리기 위해 ament_index_python을 가짜로 주입한다."""
    class PackageNotFoundError(KeyError):
        pass

    def get_package_share_directory(name):
        if name == "ur_description":
            return str(ur_share)
        raise PackageNotFoundError(name)

    ament = types.ModuleType("ament_index_python")
    ament_pkgs = types.ModuleType("ament_index_python.packages")
    ament_pkgs.get_package_share_directory = get_package_share_directory
    ament_pkgs.PackageNotFoundError = PackageNotFoundError
    ament.packages = ament_pkgs
    sys.modules["ament_index_python"] = ament
    sys.modules["ament_index_python.packages"] = ament_pkgs

    import xacro  # noqa: PLC0415 — 가짜 모듈 주입 뒤에 임포트해야 한다

    xacro_file = ur_share / "urdf" / "ur.urdf.xacro"
    if not xacro_file.is_file():
        raise FileNotFoundError(f"UR xacro 없음: {xacro_file}")
    doc = xacro.process_file(str(xacro_file), mappings={
        "ur_type": ur_type,
        "name": ur_type,
        "force_abs_paths": "false",
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc.toprettyxml(indent="  "), encoding="utf-8")
    print(f"[UR] {ur_type} flat URDF → {out_path}")
    return out_path


def rewrite_mesh(root, prefix_from: str, prefix_to: str) -> int:
    n = 0
    for mesh in root.iter("mesh"):
        fn = mesh.get("filename")
        if fn and fn.startswith(prefix_from):
            mesh.set("filename", prefix_to + fn[len(prefix_from):])
            n += 1
    return n


def copy_meshes(pairs, build_dir: Path) -> int:
    copied = 0
    for src_root, dst_sub in pairs:
        if not src_root.is_dir():
            raise FileNotFoundError(f"메시 폴더 없음: {src_root}")
        for src in src_root.rglob("*"):
            if not src.is_file():
                continue
            dst = build_dir / dst_sub / src.relative_to(src_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
                copied += 1
    return copied


def merge(ur_urdf: Path, dg_urdf: Path, ur_meshes: Path, dg_meshes: Path,
          variant: str, prefix: str, ur_type: str, out_path: Path):
    parser = ET.XMLParser(remove_blank_text=True)
    ur_root = ET.parse(str(ur_urdf), parser).getroot()
    dg_root = ET.parse(str(dg_urdf), parser).getroot()

    n_ur = rewrite_mesh(ur_root, "package://ur_description/meshes/", "meshes/ur/")
    n_dg = rewrite_mesh(dg_root, f"package://meshes/{variant}/", f"meshes/{variant}/")
    print(f"[mesh] 경로 패치: UR {n_ur}개, DG5F {n_dg}개")

    build_dir = out_path.parent
    # ⚠️ UR 메시는 해당 기종만 (전체 복사 시 ur3~ur30 전 기종 72MB가 딸려온다)
    copied = copy_meshes([
        (ur_meshes / ur_type, f"meshes/ur/{ur_type}"),
        (dg_meshes, f"meshes/{variant}"),
    ], build_dir)
    print(f"[mesh] 복사: 신규 {copied}개")

    robot_name = f"{ur_type}_{variant}"
    new_root = ET.Element("robot", name=robot_name)
    seen_materials = set()

    def append_children(src):
        for child in src:
            if child.tag == "material":
                nm = child.get("name")
                if nm in seen_materials:
                    continue
                seen_materials.add(nm)
            new_root.append(child)

    append_children(ur_root)   # world ~ tool0
    append_children(dg_root)   # <prefix>dg_mount ~ <prefix>dg_5_tip

    mount_link = f"{prefix}dg_mount"
    conn = ET.SubElement(new_root, "joint", name="tool0_to_dg_mount", type="fixed")
    ET.SubElement(conn, "parent", link="tool0")
    ET.SubElement(conn, "child", link=mount_link)
    ET.SubElement(conn, "origin", xyz="0 0 0", rpy="0 0 0")

    ET.ElementTree(new_root).write(
        str(out_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
    return new_root, robot_name, mount_link


def verify(new_root, robot_name: str, prefix: str) -> bool:
    links = [l.get("name") for l in new_root.findall("link")]
    joints = new_root.findall("joint")
    rev = [j for j in joints if j.get("type") == "revolute"]
    print(f"robot name: {robot_name}")
    print(f"links: {len(links)} | joints: {len(joints)} (revolute {len(rev)})")

    ok = True
    dup = {n for n in links if links.count(n) > 1}
    print("중복 링크명:", sorted(dup) if dup else "NONE")
    ok &= not dup

    edges = {}
    for j in joints:
        edges.setdefault(j.find("parent").get("link"), []).append(j.find("child").get("link"))
    reached, stack = set(), ["world"]
    while stack:
        n = stack.pop()
        if n in reached:
            continue
        reached.add(n)
        stack.extend(edges.get(n, []))
    unreached = set(links) - reached
    print(f"world에서 도달: {len(reached & set(links))} / {len(links)}",
          "| 미도달:", sorted(unreached) if unreached else "NONE")
    ok &= not unreached

    for tip in [f"{prefix}dg_{i}_tip" for i in range(1, 6)]:
        hit = tip in reached
        print(f"  {tip}: {'OK' if hit else 'NOT reached'}")
        ok &= hit

    # inertial 없는 링크 — Unity 임포터 기본값(1kg/(1,1,1)) 함정이고, MuJoCo는
    # 관절 달린 질량 0 바디를 거부한다. 둘 다 후처리로 메워야 한다(WORKLOG §12·§22).
    no_inertial = [l.get("name") for l in new_root.findall("link")
                   if l.find("inertial") is None]
    print("inertial 없는 링크(임포트/MJCF 변환 후 관성 보정 필요):", no_inertial)
    return ok


def main():
    ap = argparse.ArgumentParser(description="UR 팔 + DG5F 손 결합 URDF 빌드")
    ap.add_argument("--ur-type", default=cfg.UR_TYPE,
                    help=f"UR 기종 (기본 {cfg.UR_TYPE}, .env RTAUTO_UR_TYPE)")
    ap.add_argument("--hand", default=cfg.DG5F_HAND, choices=["left", "right"],
                    help=f"DG5F 좌우 (기본 {cfg.DG5F_HAND}, .env RTAUTO_DG5F_HAND)")
    ap.add_argument("--short", action="store_true", default=cfg.DG5F_SHORT,
                    help="DG5F short 변형 사용 (.env RTAUTO_DG5F_SHORT=1)")
    ap.add_argument("--ur-description", default=cfg.UR_DESCRIPTION,
                    help="Universal_Robots_ROS2_Description 루트 (.env RTAUTO_UR_DESCRIPTION)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="출력 폴더 (기본 urdf/<ur_type>_<변형>_build)")
    args = ap.parse_args()

    if not args.ur_description:
        ap.error("--ur-description 이 필요합니다 "
                 "(또는 레포 루트 .env에 RTAUTO_UR_DESCRIPTION 설정). "
                 "Universal_Robots_ROS2_Description 공개 레포를 체크아웃한 폴더.")
    ur_share = Path(args.ur_description)
    if not (ur_share / "urdf").is_dir() or not (ur_share / "meshes").is_dir():
        ap.error(f"UR description 폴더가 아닌 것 같습니다(urdf/·meshes/ 없음): {ur_share}")

    variant = f"dg5f_{args.hand}" + ("_short" if args.short else "")
    prefix = "ll_" if args.hand == "left" else "rl_"
    dg_urdf = URDF_ROOT / "dg5f" / f"{variant}.urdf"
    dg_meshes = URDF_ROOT / "dg5f" / "meshes" / variant
    if not dg_urdf.is_file():
        ap.error(f"DG5F URDF 없음: {dg_urdf}")

    out_dir = args.out_dir or (URDF_ROOT / f"{args.ur_type}_{variant}_build")
    out_dir.mkdir(parents=True, exist_ok=True)

    ur_urdf = flatten_ur(ur_share, args.ur_type, out_dir / f"{args.ur_type}_raw.urdf")
    out_path = out_dir / f"{args.ur_type}_{variant}.urdf"
    new_root, robot_name, mount_link = merge(
        ur_urdf, dg_urdf, ur_share / "meshes", dg_meshes,
        variant, prefix, args.ur_type, out_path)
    print(f"[연결] tool0 --(fixed, identity)--> {mount_link}")
    print(f"[출력] {out_path}")

    print("\n=== 검증 ===")
    sys.exit(0 if verify(new_root, robot_name, prefix) else 1)


if __name__ == "__main__":
    main()
