"""[대체됨 → urdf/build_arm_hand.py] UR5e xacro -> flat URDF (ROS 없이 Windows에서).

⚠️ UR_SHARE/OUT이 존재하지 않는 개발자 PC 경로를 가리켜 실행 불가다. 같은 기법
   (가짜 ament_index_python 주입)을 기종 파라미터화해 `build_arm_hand.py`가 계승했다.
가짜 ament_index_python 모듈로 $(find ur_description)를 실제 폴더로 해석시킨다.
"""
import sys
import types
import os

# UR 공식 레포 루트 (urdf/, meshes/, config/ 가 바로 안에 있음)
UR_SHARE = r"C:/Users/dltmd/Desktop/KDT/Universal_Robots_ROS2_Description-rolling"
OUT = r"C:/Users/dltmd/Desktop/KDT/ur5e_svh_build/ur5e_raw.urdf"

# --- 가짜 ament_index_python 주입 ---
class PackageNotFoundError(KeyError):
    pass

def get_package_share_directory(name):
    if name == "ur_description":
        return UR_SHARE
    raise PackageNotFoundError(name)

ament = types.ModuleType("ament_index_python")
ament_pkgs = types.ModuleType("ament_index_python.packages")
ament_pkgs.get_package_share_directory = get_package_share_directory
ament_pkgs.PackageNotFoundError = PackageNotFoundError
ament.packages = ament_pkgs
sys.modules["ament_index_python"] = ament
sys.modules["ament_index_python.packages"] = ament_pkgs

import xacro  # noqa: E402

xacro_file = os.path.join(UR_SHARE, "urdf", "ur.urdf.xacro")
mappings = {
    "ur_type": "ur5e",
    "name": "ur5e",
    "force_abs_paths": "false",
}

doc = xacro.process_file(xacro_file, mappings=mappings)
xml = doc.toprettyxml(indent="  ")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(xml)

# 간단 검증
import re
meshes = re.findall(r'filename="([^"]+)"', xml)
pkg_meshes = [m for m in meshes if m.startswith("package://ur_description/meshes/ur5e/")]
print("OUTPUT:", OUT)
print("total mesh refs:", len(meshes), "| package://ur_description/meshes/ur5e refs:", len(pkg_meshes))
print("sample mesh paths:")
for m in meshes[:4]:
    print("  ", m)
