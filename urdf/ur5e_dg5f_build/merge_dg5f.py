# -*- coding: utf-8 -*-
"""[대체됨 → urdf/build_arm_hand.py] UR5e(flat) + DG5F left -> ur5e_dg5f_left.urdf 결합.

⚠️ 이 스크립트는 실행 불가 상태다: UR_MESHES가 존재하지 않는 개발자 PC 경로를
   가리키고, ur5e·왼손이 하드코딩돼 있다. 하드웨어가 UR16e + 오른손(DG-5F-M-R)으로
   확정되면서 기종·좌우를 파라미터로 받는 `urdf/build_arm_hand.py`로 대체했다.
   이 파일은 UR5e+왼손 자산이 어떻게 만들어졌는지의 이력으로만 남긴다.

ur5e_svh_build/merge.py 계승 (SVH 자리에 DG5F). 규칙:
- UR tool0 --(fixed)--> ll_dg_mount 연결 (identity — DG5F 마운트가 플랜지 장착용)
- mesh 경로 통일 (Unity import_hand.py가 URDF 기준 상대경로로 해석):
    UR  : package://ur_description/meshes/... -> meshes/ur/...
    DG5F: package://meshes/dg5f_left/...      -> meshes/dg5f_left/...
- 메시 실파일도 이 폴더의 meshes/ 아래로 복사 (빌드 폴더 자체가 임포트 소스)
- DG5F는 mimic 없음(20관절 독립) — SVH 대비 mimic 처리 불필요
- robot name = ur5e_dg5f_left

사용: python merge_dg5f.py   (이 폴더에서)
"""
import shutil
from pathlib import Path

import lxml.etree as ET

BUILD = Path(__file__).resolve().parent
REPO = BUILD.parent            # KDT_1_AX_rtauto/urdf
UR = REPO / "ur5e_svh_build" / "ur5e_raw.urdf"
DG = REPO / "dg5f" / "dg5f_left.urdf"
DG_MESHES = REPO / "dg5f" / "meshes" / "dg5f_left"
UR_MESHES = Path(r"C:/Users/dltmd/Desktop/KDT/Universal_Robots_ROS2_Description-rolling/meshes")
OUT = BUILD / "ur5e_dg5f_left.urdf"

parser = ET.XMLParser(remove_blank_text=True)
ur_root = ET.parse(str(UR), parser).getroot()
dg_root = ET.parse(str(DG), parser).getroot()


def rewrite_mesh(root, prefix_from, prefix_to):
    n = 0
    for mesh in root.iter("mesh"):
        fn = mesh.get("filename")
        if fn and fn.startswith(prefix_from):
            mesh.set("filename", prefix_to + fn[len(prefix_from):])
            n += 1
    return n


# 1) mesh 경로 통일
n_ur = rewrite_mesh(ur_root, "package://ur_description/meshes/", "meshes/ur/")
n_dg = rewrite_mesh(dg_root, "package://meshes/dg5f_left/", "meshes/dg5f_left/")
print(f"mesh 경로 패치: UR {n_ur}개, DG5F {n_dg}개")

# 2) 메시 실파일 복사 (빌드 폴더가 자족적이도록)
copied = 0
# ⚠️ UR 메시는 ur5e만 (전체 복사 시 ur3~ur30 전 기종 72MB가 딸려옴)
for src_root, dst_sub in ((UR_MESHES / "ur5e", "meshes/ur/ur5e"), (DG_MESHES, "meshes/dg5f_left")):
    for src in src_root.rglob("*"):
        if not src.is_file():
            continue
        dst = BUILD / dst_sub / src.relative_to(src_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
            copied += 1
print(f"메시 복사: 신규 {copied}개")

# 3) 새 robot 루트 구성 (material 이름 중복 제거)
new_root = ET.Element("robot", name="ur5e_dg5f_left")
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
append_children(dg_root)   # ll_dg_mount ~ ll_dg_5_tip

# 4) tool0 -> ll_dg_mount 연결 (fixed, identity)
conn = ET.SubElement(new_root, "joint", name="tool0_to_dg_mount", type="fixed")
ET.SubElement(conn, "parent", link="tool0")
ET.SubElement(conn, "child", link="ll_dg_mount")
ET.SubElement(conn, "origin", xyz="0 0 0", rpy="0 0 0")

# 5) 저장
tree = ET.ElementTree(new_root)
tree.write(str(OUT), pretty_print=True, xml_declaration=True, encoding="utf-8")

# ---------------- 검증 ----------------
links = [l.get("name") for l in new_root.findall("link")]
joints = new_root.findall("joint")
rev = [j for j in joints if j.get("type") == "revolute"]
print("robot name:", new_root.get("name"))
print("links:", len(links), "| joints:", len(joints), f"(revolute {len(rev)})")

dup = {n for n in links if links.count(n) > 1}
print("중복 링크명:", sorted(dup) if dup else "NONE")

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
print("world에서 도달:", len(reached & set(links)), "/", len(links),
      "| 미도달:", sorted(unreached) if unreached else "NONE")
for tip in [f"ll_dg_{i}_tip" for i in range(1, 6)]:
    print(f"  {tip}: {'OK' if tip in reached else 'NOT reached'}")

# 링크에 inertial 없는 것(임포터 기본값 1kg/(1,1,1) 함정 §12) 목록
no_inertial = [l.get("name") for l in new_root.findall("link") if l.find("inertial") is None]
print("inertial 없는 링크(임포트 후 관성 수정 필요):", no_inertial)

# 메시 참조가 전부 빌드 폴더에 실재하는지
missing = [m.get("filename") for m in new_root.iter("mesh")
           if not (BUILD / m.get("filename")).is_file()]
print("실재하지 않는 메시 참조:", missing if missing else "NONE")
print("OUTPUT:", OUT)
