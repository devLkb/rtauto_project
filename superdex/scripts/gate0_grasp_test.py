# -*- coding: utf-8 -*-
"""게이트 0-8 — DG5F 스크립트 파지 테스트 (headless, 학습 없음).

docs/SUPERDEX_POC_PLAN.md §5 게이트 0의 판정 스크립트다. 목적은 단 하나:
**SuperDex 접촉 물리가 DG5F로 물체를 안정적으로 붙잡는가**를 학습 없이 확인하고,
접촉이 있는 상태의 steps/sec를 재는 것.

판정 방식 — 파지 중심을 먼저 실측하고, 중력을 뒤집어 떼어내 본다:
  A) probe  : 블록 없이 손가락을 접어, **닫힌 자세의 지문 5개 중심**을 파지 중심으로 잡는다
  B) reset  : 열린 자세로 되돌린다
  C) spawn  : 파지 중심에 블록을 놓는다 (떨어뜨리지 않는다 — 배치 오차·낙하 동역학 제거)
  D) close  : 손가락을 접어 블록을 감싼다
  E) invert : **중력을 +Z로 뒤집어** 블록을 손에서 떼어내는 1g를 건다
  F) hold   : 유지. 블록이 파지 중심 근처에 남고 손과 접촉이 살아 있으면 성공

⚠️ 손을 "손바닥 위로" 두고 떨어뜨리는 방식은 쓰지 않는다. asset 기본 방향은
**손가락 +Z(위), 손바닥 +X**라서(실측) 수평 손바닥이 없고, 블록이 손을 지나쳐 바닥까지
떨어진다. A~C가 그 기하 의존을 없앤다.

⚠️ 동적 물체는 surface mesh가 있어야 한다 — primitive box/sphere로는 rigid actor를
만들 수 없다(실측). 그래서 동봉 task prefab(Box and Blocks Test의 블록)을 쓴다.

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/gate0_grasp_test.py
    python superdex/scripts/gate0_grasp_test.py --close-frac 0.75
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·asset 위치의 유일한 출처 — 원칙 1)

_assets = cfg.superdex_assets_path()
if _assets is None:
    sys.exit("RTAUTO_SUPERDEX_REPO가 .env에 없다 — docs/SUPERDEX_POC_PLAN.md §11 0-5 참고.")
os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))

import numpy as np  # noqa: E402
import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402
from superdex.physics.paths import get_assets_root, resolve_asset  # noqa: E402

# 파지 대상. Box and Blocks Test의 블록 — 표준 벤치마크 자산이라 자체 제작 메시보다
# 판정 근거가 명확하다.
BLOCK_PREFAB = "prefabs/box_and_blocks/block_red.mochi_prefab"

PALM_LINK = "dg5f_link_palm"
TIP_LINKS = tuple(f"dg5f_link_{f}_tip" for f in "12345")

# 굽힘 관절 = 각 손가락의 2·3·4번째 (관절 _1은 벌림/회전이라 파지 자세에서 건드리지 않는다).
FLEX_SUFFIXES = ("_2", "_3", "_4")


def main() -> None:
    ap = argparse.ArgumentParser(description="DG5F 스크립트 파지 테스트")
    ap.add_argument("--close-frac", type=float, default=0.6,
                    help="굽힘 관절을 가동범위의 몇 배까지 접을지 (0~1)")
    ap.add_argument("--place", type=str, default="0.03,0.0,0.04",
                    help="손바닥 링크 좌표계에서의 블록 배치 오프셋 x,y,z [m]")
    ap.add_argument("--max-frac", type=float, default=0.95,
                    help="접촉을 찾으며 닫을 때의 최대 폐쇄율")
    ap.add_argument("--grip-margin", type=float, default=0.10,
                    help="접촉이 잡힌 뒤 파지력을 만들기 위해 추가로 조이는 폐쇄율")
    ap.add_argument("--hold-radius", type=float, default=0.05,
                    help="파지 중심에서 이 거리[m] 안에 남아 있으면 붙잡은 것으로 본다")
    ap.add_argument("--stiffness", type=float, default=1.0e3)
    ap.add_argument("--damping", type=float, default=1.0e2)
    args = ap.parse_args()

    dt = 1.0 / cfg.SUPERDEX_SIM_HZ
    hz = cfg.SUPERDEX_SIM_HZ

    physics.initialize(num_worker_threads=0)
    scene = physics.create_scene("Gate0 Grasp Test")
    scene.set_gravity([0, 0, -9.81])

    # 바닥판은 static이라 implicit plane으로 문제없다. 떨어뜨린 블록이 무한히 날아가지
    # 않게 두는 안전망 — 정상 경로에서는 닿지 않는다.
    ground = physics.create_plane_shape(normal=[0, 0, 1], distance=0)
    scene.create_rigid_actor(name="ground", shape=ground, is_static=True)

    # --- 손 ---------------------------------------------------------------------
    prefab = robotics.load_bot_prefab_from_file(str(resolve_asset(cfg.superdex_hand_asset())))

    # world_joint의 기본 타입은 FREE라 손이 자유부양한다(실측). HARD로 바꿔 손목을
    # world에 용접한다 — PoC의 "손목 고정"이 이것이고, 그 결과 DOF가 정확히 20이 된다.
    prefab.joints[0].type = physics.ArticulatedJointType.HARD
    prefab.world_from_root = physics.TransformRT(
        rotation=[0.0, 0.0, 0.0, 1.0], translation=[0.0, 0.0, 0.4]
    )

    ctx = robotics.create_context()
    bot = robotics.create_bot(scene, prefab, ctx)
    actor = bot.get_articulated_actor()
    num_dofs = actor.get_num_dofs()

    names = [prefab.links[i].name for i in range(len(prefab.links))]
    link_tf = physics.DynamicArrayTransformRT(len(names))
    palm_idx = names.index(PALM_LINK)
    tip_idx = [names.index(n) for n in TIP_LINKS]

    def link_pos(idx):
        actor.get_articulated_link_transforms(link_tf)
        return np.asarray(link_tf[idx].translation, dtype=float)

    def grasp_center():
        actor.get_articulated_link_transforms(link_tf)
        pts = [np.asarray(link_tf[i].translation, dtype=float) for i in tip_idx]
        pts.append(np.asarray(link_tf[palm_idx].translation, dtype=float))
        return np.mean(pts, axis=0)

    def palm_to_world(offset):
        """손바닥 링크 좌표계의 오프셋을 world 좌표로. 배치를 손 자세와 무관하게 적기 위한 것.

        실측 기하: 손바닥 기준으로 손가락은 +Z로 뻗고 손바닥면은 +X를 본다. 따라서
        "손바닥 앞 포켓"은 +X 쪽, 손가락 밑동 높이는 +Z 쪽 작은 값이다.
        """
        actor.get_articulated_link_transforms(link_tf)
        local = physics.TransformRT()
        local.translation = [float(v) for v in offset]
        return np.asarray((link_tf[palm_idx] * local).translation, dtype=float)

    # 관절 이름 -> DOF 인덱스. root가 HARD라 root DOF가 0개이므로 REVOLUTE 순서가 곧 DOF 순서.
    name_to_dof, dof = {}, 0
    for i in range(len(prefab.joints)):
        j = prefab.joints[i]
        if j.type == physics.ArticulatedJointType.REVOLUTE:
            name_to_dof[j.name] = dof
            dof += 1
    assert num_dofs == dof, f"DOF 불일치: actor {num_dofs} vs revolute {dof}"
    print(f"hand: {prefab.name}  dofs={num_dofs} (손목 용접, root dofs="
          f"{actor.get_articulated_shape_info().dof_info[0].get_size()})")

    # 열린 자세 = asset 기본 자세. full = 굽힘 관절을 가동범위 끝까지 접은 자세.
    # 임의 폐쇄율 f의 자세 = open + (full - open) * f. 폐쇄율을 하나의 스칼라로 다루려고
    # full을 정본으로 두고 보간한다.
    open_arr = physics.DynamicArrayReal(num_dofs)
    actor.get_articulated_pose(open_arr)
    open_pose = np.array([float(v) for v in open_arr], dtype=np.float64)
    closed_pose_full = open_pose.copy()
    n_flex = 0
    for i in range(len(prefab.joints)):
        j = prefab.joints[i]
        if j.type != physics.ArticulatedJointType.REVOLUTE or not j.name.endswith(FLEX_SUFFIXES):
            continue
        ax = [round(float(v), 0) for v in j.axis]
        k = ax.index(1.0) if 1.0 in ax else (ax.index(-1.0) if -1.0 in ax else 0)
        lo, hi = float(j.min_limit[k]), float(j.max_limit[k])
        # 굽힘은 max_limit 방향이다(실측: _2/_3/_4의 min은 0, max는 90~115도).
        closed_pose_full[name_to_dof[j.name]] = hi if abs(hi) >= abs(lo) else lo
        n_flex += 1
    print(f"굽힘 DOF {n_flex}개. 폐쇄율 f 자세 = open + (full-open)*f")

    def pose_at(frac):
        return open_pose + (closed_pose_full - open_pose) * float(frac)

    closed_pose = pose_at(args.close_frac)

    # 액추에이터: Mochi의 암시적 관절 자세 컨트롤러. BASIC_*_PD와 달리 중력 항이 있어
    # 링크 중력을 끄지 않아도 자세를 유지한다 — 중력을 뒤집는 판정에서 중요하다.
    tracking = physics.PoseTrackingParams(stiffness=args.stiffness, damping=args.damping)
    pose_ctrl = bot.create_controller("MOCHI_ARTICULATED_POSE")
    pose_ctrl.set_params(
        robotics.ControllerMochiArticulatedPoseParams(
            pose_controller_params=physics.PoseControllerParams(
                joint_tracking=physics.DynamicArrayPoseTrackingParams([tracking])
            )
        )
    )
    pose_ctrl.initialize(True)

    def drive(target, steps):
        arr = physics.DynamicArrayReal(np.asarray(target, dtype=np.float64).tolist())
        for _ in range(steps):
            actor.set_articulated_target_pose(arr)
            scene.step(dt)

    def ramp(a, b, steps):
        for s in range(steps):
            t = a + (b - a) * ((s + 1) / steps)
            actor.set_articulated_target_pose(
                physics.DynamicArrayReal(t.tolist())
            )
            scene.step(dt)

    # === A) probe — 블록 없이 닫아서 파지 중심을 실측 ===========================
    print(f"\n[A] probe: 블록 없이 닫아 파지 중심 측정")
    print(f"    open  palm={link_pos(palm_idx).round(4).tolist()}  "
          f"center={grasp_center().round(4).tolist()}")
    ramp(open_pose, closed_pose, int(0.5 * hz))
    drive(closed_pose, int(0.5 * hz))
    center = grasp_center()
    print(f"    closed center = {center.round(4).tolist()}  <- 여기에 블록을 둔다")

    # === B) reset — 열린 자세로 되돌린다 =======================================
    print(f"[B] reset: 열린 자세 복귀")
    ramp(closed_pose, open_pose, int(0.5 * hz))
    drive(open_pose, int(0.5 * hz))

    # === C) spawn — 손바닥 앞 포켓에 블록 배치 =================================
    # 지문 중심(center)에 두면 f=0.30에서 닿았다가 더 조일 때 밖으로 밀려났다(실측).
    # 5지 파워 그립은 물체가 손바닥 쪽에 있어야 성립하므로, 배치를 손바닥 좌표계
    # 오프셋으로 준다. 기본값은 손바닥 앞(+X) 3 cm, 손가락 밑동 쪽(+Z) 4 cm.
    place = [float(v) for v in args.place.split(",")]
    spawn = palm_to_world(place)
    print(f"[C] spawn @ palm+{place} (world {spawn.round(4).tolist()}) "
          f"— 참고: 지문 중심은 {center.round(4).tolist()}")
    physics.prefab.add_to_scene(
        prefab_path=str(resolve_asset(BLOCK_PREFAB)),
        root_path=str(get_assets_root()),
        scene=scene,
        params=physics.prefab.PrefabParams(name="block",
                                           translation=[float(v) for v in spawn]),
    )
    found = []
    scene.for_each_actor(lambda a: found.append(a))
    block = next((a for a in found
                  if a.get_name().startswith("block") and not a.is_static()), None)
    if block is None:
        sys.exit(f"블록 actor를 못 찾았다: {[a.get_name() for a in found]}")
    print(f"    actor={block.get_name()}  mass={block.get_mass():.4f} kg")

    # 접촉점 조회는 스텝 **전에** CONTACT_POINTS 쿼리를 등록해야 결과가 나온다.
    contacts_ok = True
    try:
        block.register_query(physics.QueryType.CONTACT_POINTS)
    except Exception as exc:
        contacts_ok = False
        print(f"    (접촉점 쿼리 등록 실패: {type(exc).__name__} — 접촉 수는 생략한다)")

    def n_contacts():
        if not contacts_ok:
            return -1
        try:
            return len(block.get_contact_points_world())
        except Exception:
            return -1

    def report(tag):
        bt = np.asarray(block.get_root_transform().translation, dtype=float)
        c = grasp_center()
        v = float(np.linalg.norm(np.asarray(block.get_linear_velocity(), dtype=float)))
        print(f"    {tag:<22} block={bt.round(4).tolist()}  "
              f"|block-center|={np.linalg.norm(bt - c):.4f}  |v|={v:.3f}  "
              f"contacts={n_contacts()}")
        return bt, c

    t0 = time.perf_counter()
    n_steps = 0

    # 닫는 동안은 중력을 0으로 둔다. 손가락이 닫히는 데 1.25초가 걸리고, 그 사이 블록이
    # 자유낙하하면(0.5*g*t^2 ≈ 7.7 m) 파지 자체가 성립하지 않는다 — 실측으로 확인했다.
    # 파지 강도 판정은 아래 [E]에서 중력을 켜서 한다.
    scene.set_gravity([0, 0, 0])
    drive(open_pose, int(0.25 * hz)); n_steps += int(0.25 * hz)
    report("spawn 후 정착(0g)")

    # === D) close — 접촉이 생길 때까지 닫는다 =================================
    # 고정된 close_frac으로 한 번에 닫으면 손가락 케이지가 블록보다 커서 닿지도 않는다
    # (close_frac=0.6에서 contacts=0으로 실측). 그래서 조금씩 닫으며 접촉을 감시하고,
    # 접촉이 잡히면 grip_margin만큼 더 조여 파지력을 만든다 — 정책이 학습할 행동의
    # 스크립트 버전이다.
    print(f"[D] close until contact (0g, max {args.max_frac:.0%})")
    aabb = block.get_aabb_world()
    try:
        ext = np.asarray(aabb.max, dtype=float) - np.asarray(aabb.min, dtype=float)
        print(f"    block AABB 크기 = {ext.round(4).tolist()} m")
    except Exception:
        pass

    grip_frac = None
    prev = open_pose.copy()
    for frac in np.arange(0.10, args.max_frac + 1e-9, 0.02):
        tgt = pose_at(frac)
        k = max(1, int(0.05 * hz))
        ramp(prev, tgt, k); n_steps += k
        prev = tgt
        nc = n_contacts()
        if nc > 0:
            grip_frac = float(frac)
            print(f"    f={frac:.2f} 에서 접촉 {nc}점 — grip margin "
                  f"+{args.grip_margin:.2f} 만큼 더 조인다")
            break
    if grip_frac is None:
        print(f"    ⚠️ f={args.max_frac:.2f} 까지 닫아도 접촉이 안 생겼다 — "
              f"블록 배치나 폐쇄 범위를 다시 봐야 한다")
        grip_frac = args.max_frac

    grip = pose_at(min(1.0, grip_frac + args.grip_margin))
    k = int(0.4 * hz)
    ramp(prev, grip, k); n_steps += k
    closed_pose = grip  # 이후 hold 구간은 이 자세를 유지한다
    print(f"    최종 파지 폐쇄율 f={min(1.0, grip_frac + args.grip_margin):.2f}")
    k = int(0.5 * hz)
    drive(closed_pose, k); n_steps += k
    report("닫은 직후")

    # === E/F) 양방향 1g 로 떼어내기 ===========================================
    # 먼저 정상 중력(-Z)에서 0.5초씩 2회 — 아래로 떨어뜨리는 1g.
    # 그 다음 중력을 반전(+Z)해 위로 뽑아내는 1g. 손목이 용접돼 있으므로 손을 움직이지
    # 않고도 양방향 파지 강도를 볼 수 있다.
    print(f"[E] gravity -Z (아래로 떼어내는 1g)")
    scene.set_gravity([0, 0, -9.81])
    for i in range(2):
        k = int(0.5 * hz)
        drive(closed_pose, k); n_steps += k
        report(f"-Z hold {0.5 * (i + 1):.1f}s")

    print(f"[F] gravity +Z (위로 뽑아내는 1g)")
    scene.set_gravity([0, 0, +9.81])
    for i in range(2):
        k = int(0.5 * hz)
        drive(closed_pose, k); n_steps += k
        report(f"+Z hold {0.5 * (i + 1):.1f}s")

    elapsed = time.perf_counter() - t0
    sps = n_steps / elapsed

    # === 판정 =================================================================
    bt = np.asarray(block.get_root_transform().translation, dtype=float)
    center = grasp_center()
    dist = float(np.linalg.norm(bt - center))
    nc = n_contacts()
    held = dist < args.hold_radius and (nc != 0)

    print("\n=== 판정 ===")
    print(f"최종 |block - 파지중심| : {dist:.4f} m  (기준 < {args.hold_radius})")
    print(f"최종 접촉점 수          : {nc}  (-1 = 측정 불가)")
    print(f"파지 유지               : {'성공' if held else '실패 (놓쳤다)'}")
    print(f"접촉 포함 throughput    : {sps:.1f} steps/s (realtime {sps * dt:.2f}x)")
    print(f"집계 추정               : {sps * cfg.SUPERDEX_ENV_RUNNERS:.0f} steps/s "
          f"({cfg.SUPERDEX_ENV_RUNNERS} runner)")
    print("\n이 숫자를 docs/SUPERDEX_POC_PLAN.md §10 진행 기록에 남긴다.")

    robotics.destroy_bot(scene, bot)
    physics.shutdown()
    sys.exit(0 if held else 2)


if __name__ == "__main__":
    main()
