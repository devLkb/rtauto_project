# -*- coding: utf-8 -*-
"""ur16e_dg5f_right.urdf -> ur16e_dg5f_right.mjcf.xml (순수 기구학, patch_mjcf.py 이전 단계).

MuJoCo는 DAE 시각 메시를 지원하지 않는다(로드맵 Phase 0 참고). 실측 결과: URDF의
<visual><mesh filename="*.dae"> 는 컴파일 시 경고 없이 그냥 누락되고, 남는 건 STL
collision geom뿐이라 뷰어에 뜨는 모양이 실제 로봇과 다르게 보인다(관절 기구학은
정확해도 형태가 뭉툭한 충돌 헐로만 보임).

그래서 canonical `ur16e_dg5f_right.urdf`는 그대로 두고(Unity 등 DAE를 읽는
소비자를 위해), 컴파일 직전에 메모리 상에서만 <visual> 메시를 매칭되는 충돌용
STL로 바꿔 치환한다(로드맵이 명시한 옵션 ② — 별도 시각 변환 없이 기존 STL 재사용).

사용: python compile_mjcf.py   (이 폴더에서)
출력: ur16e_dg5f_right.mjcf.xml
"""
from pathlib import Path

import lxml.etree as ET
import mujoco

BUILD_DIR = Path(__file__).resolve().parent
URDF_PATH = BUILD_DIR / "ur16e_dg5f_right.urdf"
OUT_PATH = BUILD_DIR / "ur16e_dg5f_right.mjcf.xml"


def use_collision_mesh_for_visual(root) -> int:
    n = 0
    for link in root.findall("link"):
        for visual in link.findall("visual"):
            mesh = visual.find("geometry/mesh")
            if mesh is None:
                continue
            fn = mesh.get("filename")
            if not fn or not fn.lower().endswith(".dae"):
                continue
            if "/visual/" in fn:
                candidate = fn.replace("/visual/", "/collision/")[:-4] + ".stl"
            else:
                candidate = fn[:-4] + "_c.STL"
            if not (BUILD_DIR / candidate).is_file():
                raise FileNotFoundError(f"대응하는 충돌 STL을 못 찾음: {fn} -> {candidate}")
            mesh.set("filename", candidate)
            n += 1
    return n


def main():
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(str(URDF_PATH), parser)
    root = tree.getroot()

    n = use_collision_mesh_for_visual(root)
    print(f"[mesh] MuJoCo 컴파일용 시각 메시 대체(dae -> collision stl): {n}개")

    # 상대 메시 경로가 원본 URDF와 같은 폴더 기준으로 풀려야 하므로, 같은 폴더에
    # 임시 파일로 써서 from_xml_path로 컴파일한다(from_xml_string은 기준 폴더가 없다).
    tmp_path = BUILD_DIR / "_tmp_mujoco_visual.urdf"
    tree.write(str(tmp_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
    try:
        model = mujoco.MjModel.from_xml_path(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    mujoco.mj_saveLastXML(str(OUT_PATH), model)
    print(f"[출력] {OUT_PATH}")


if __name__ == "__main__":
    main()
