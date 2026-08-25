# -*- coding: utf-8 -*-
"""URDF에서 나온 순수 기구학 MJCF(ur16e_dg5f_right.mjcf.xml)에 학습에 필요한 것을
덧붙인다: 위치 서보 액추에이터 26개, 손끝·팜 터치 센서, 바닥, 파지 대상 블록.

URDF에는 애초에 없는 정보(액추에이터 게인, 센서, 환경)라 손으로 추가하는 게
맞다 — Dg5fGraspLiftSpec.cs 문서화 원칙과 동일(로드맵 Phase 0 "URDF에 없어서
손으로 추가해야 하는 것" 참고).

사용: python patch_mjcf.py   (이 폴더에서, ur16e_dg5f_right.mjcf.xml 필요)
출력: ur16e_dg5f_right.sim.mjcf.xml (학습용 최종 모델)
"""
import lxml.etree as ET

SRC = "ur16e_dg5f_right.mjcf.xml"
OUT = "ur16e_dg5f_right.sim.mjcf.xml"

# 팔 6관절: Unity xDrive 게인(10000/200/100000, Dg5fGraspLiftSpec 주석 참고)을
# MuJoCo position actuator(kp)로 그대로 옮길 수 없다 — 단위계가 다르다
# (xDrive는 deg 기준 PD, MuJoCo actuator는 rad 기준 힘/토크). 우선 안정적으로
# 자세를 유지하는 보수적인 값에서 시작하고, 실측 후 튜닝한다.
ARM_JOINTS = ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
              "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"]
ARM_KP = 2000.0
ARM_KV = 200.0

# 손 20관절: 훨씬 작은 링크/토크 범위(effort limit 7.5 N·m)라 팔보다 낮은 게인.
HAND_JOINT_PREFIX = "rj_dg_"
HAND_KP = 20.0
HAND_KV = 2.0

# 손끝 5개 + 팜 — 실물 핑거팁 FT/촉각 센서(TESOLLO_SDK_기술부채_조사.md)에 대응.
# 좌표는 URDF에서 그대로 가져온 tip 지오멤 오프셋(각 손가락 마지막 링크 기준).
FINGERTIP_SITES = {
    "rl_dg_1_4": (0, 0.0363, 0),
    "rl_dg_2_4": (0, 0, 0.0255),
    "rl_dg_3_4": (0, 0, 0.0255),
    "rl_dg_4_4": (0, 0, 0.0255),
    "rl_dg_5_4": (0, 0, 0.0363),
}
PALM_BODY = "wrist_3_link"     # rl_dg_palm이 fixed-merge로 여기 흡수됨
PALM_SITE_POS = (0, 0, 0.09)   # rl_dg_palm_c geom 근방(대략치, 실측 후 조정)

BLOCK_WIDTH = 0.035   # Dg5fGraspLiftSpec.BlockWidth
BLOCK_HEIGHT = 0.12    # Dg5fGraspLiftSpec.BlockHeight
BLOCK_DENSITY = 1800   # Dg5fGraspLiftSpec.BlockDensity
BLOCK_COM_FRACTION = 0.20  # Dg5fGraspLiftSpec.BlockComHeightFraction


def add_actuators(root):
    actuator = ET.SubElement(root, "actuator")
    for name in ARM_JOINTS:
        ET.SubElement(actuator, "position", name=f"act_{name}", joint=name,
                      kp=str(ARM_KP), kv=str(ARM_KV))
    for jnt in root.iter("joint"):
        name = jnt.get("name")
        if name and name.startswith(HAND_JOINT_PREFIX):
            ET.SubElement(actuator, "position", name=f"act_{name}", joint=name,
                          kp=str(HAND_KP), kv=str(HAND_KV))


def add_sensors(root):
    sensor = ET.SubElement(root, "sensor")
    for body_name, pos in FINGERTIP_SITES.items():
        body = root.find(f".//body[@name='{body_name}']")
        if body is None:
            raise ValueError(f"body not found: {body_name}")
        site_name = f"site_{body_name}_tip"
        ET.SubElement(body, "site", name=site_name,
                      pos=" ".join(map(str, pos)), size="0.008", type="sphere")
        ET.SubElement(sensor, "touch", name=f"touch_{body_name}", site=site_name)

    palm_body = root.find(f".//body[@name='{PALM_BODY}']")
    if palm_body is None:
        raise ValueError(f"body not found: {PALM_BODY}")
    ET.SubElement(palm_body, "site", name="site_palm",
                  pos=" ".join(map(str, PALM_SITE_POS)), size="0.03 0.03 0.01",
                  type="box")
    ET.SubElement(sensor, "touch", name="touch_palm", site="site_palm")


def add_scene(root):
    worldbody = root.find("worldbody")
    ET.SubElement(worldbody, "light", pos="0 0 2", dir="0 0 -1", diffuse="0.8 0.8 0.8")
    ET.SubElement(worldbody, "geom", name="floor", type="plane", size="2 2 0.1",
                  rgba="0.6 0.6 0.6 1", contype="2", conaffinity="5")

    # 파지 대상 — Dg5fGraspLiftSpec 기본값과 동일 (12cm 블록, 무게중심 낮춤).
    # 스폰 위치는 팔 앞 임의 지점(실측/커리큘럼은 다음 단계에서).
    body = ET.SubElement(worldbody, "body", name="grasp_object", pos="0.5 0 0.06")
    ET.SubElement(body, "freejoint", name="grasp_object_free")
    ET.SubElement(body, "geom", name="grasp_object_geom", type="box",
                  size=f"{BLOCK_WIDTH/2} {BLOCK_WIDTH/2} {BLOCK_HEIGHT/2}",
                  density=str(BLOCK_DENSITY), rgba="0.8 0.2 0.2 1",
                  contype="4", conaffinity="3")
    com_z = (BLOCK_COM_FRACTION - 0.5) * BLOCK_HEIGHT
    ET.SubElement(body, "inertial",
                  pos=f"0 0 {com_z}",
                  mass=str(BLOCK_WIDTH * BLOCK_WIDTH * BLOCK_HEIGHT * BLOCK_DENSITY),
                  diaginertia="0.0001 0.0001 0.0001")  # 자리표시자 — 정밀값 다음 단계


def main():
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(SRC, parser)
    root = tree.getroot()

    compiler = root.find("compiler")
    compiler.set("autolimits", "true")

    # 자기충돌 무시 — Unity RobotSelfCollisionIgnore와 동치: 특정 쌍을 고르는 게 아니라
    # "로봇 전체가 자기 자신과는 충돌하지 않고 바닥·물체와는 충돌한다"를 콜리전
    # 그룹으로 구현한다(RobotSelfCollisionIgnore.cs 확인: 로봇 콜라이더 전 쌍에
    # Physics.IgnoreCollision을 걸 뿐, 특정 링크 쌍을 고르지 않는다).
    #   robot: contype=1 conaffinity=6(=floor|object) → 로봇끼리는 (1&6)=0 → 무충돌
    #   floor: contype=2 conaffinity=5(=robot|object)
    #   object: contype=4 conaffinity=3(=robot|floor)
    default = ET.SubElement(root, "default")
    ET.SubElement(default, "geom", contype="1", conaffinity="6")
    option = ET.SubElement(root, "option")
    option.set("timestep", "0.002")   # 500 Hz 물리, ML-Agents 10Hz 결정주기의 1/50
    # 손가락처럼 질량·관성이 아주 작은 링크에 position actuator를 걸면 고유진동수가
    # 커져 명시적(Euler) 적분기로는 실측 결과 DOF 발산이 났다(QACC NaN 경고).
    # implicitfast는 관절 댐핑/액추에이터 항을 암묵적으로 풀어 이런 뻣뻣한(stiff)
    # 계에서 kp를 낮추지 않고도 안정적으로 돈다 — MuJoCo가 이 상황의 표준 권장이다.
    option.set("integrator", "implicitfast")

    add_actuators(root)
    add_sensors(root)
    add_scene(root)

    tree.write(OUT, pretty_print=True, xml_declaration=True, encoding="utf-8")
    print(f"[출력] {OUT}")


if __name__ == "__main__":
    main()
