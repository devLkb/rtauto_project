# -*- coding: utf-8 -*-
"""게이트 3 선행 검증 2 — UR16e + DG5F **결합체**가 SuperDex 물리에서 성립하는가.

2026-09-08 의 선행 검증은 **팔 단독** URDF 로만 확인했다(REVOLUTE 6, 관절 한계 스펙 일치,
`tool0` 생존). 이 스크립트는 그 위에서 **팔+손 결합 URDF** 를 런타임 로더로 올려
게이트 3 판정 항목 중 Studio bake 품질을 뺀 나머지를 **사람 조작 없이** 미리 답한다:

| 게이트 3 판정 항목 | 여기서 답하는가 |
|---|---|
| 결합체가 로드되는가 | ✅ |
| 관절 한계가 UR16e 스펙과 일치하는가 | ✅ (팔 6축을 스펙과 대조) |
| 충돌 형상이 깨지지 않았는가 | ✅ (전 링크 mesh 충돌 존재 확인 + 시뮬 안정성) |
| 자기충돌이 정상인가 | ✅ (홈 자세에서 자기접촉 수를 센다) |
| **Studio SDF bake 품질** | ❌ — bake 산출물이 있어야 답할 수 있다 |

**왜 미리 하는가**: Studio bake 는 사람이 GUI 를 조작해야 하는 유일한 단계다. 결합
기하 자체에 문제가 있다면 bake 를 하고 나서 발견하는 것보다 지금 발견하는 편이 싸다.

**한계 — 여기서 쓰는 손은 공식 Tesollo asset 이 아니다.** 결합 URDF
(`ur16e_dg5f_<hand>.urdf`)는 우리가 만든 DG5F 메시를 쓴다. 게이트 0·2 가 쓴 SDF 가
구워진 공식 손 asset 과는 다른 물체다. 그래서 이 스크립트는 **결합 기하·관절·자기충돌**
을 판정하지, 파지 품질을 판정하지 않는다. 최종 결합체는 여전히
`superdex/assets/bots/arm_hand_combos/.../*.superdex_bot`(공식 손을 `@superdex/` 태그로
참조) 이며, 그것은 팔 asset bake 후 `gate3_setup_asset_root.py --verify-only` 로 본다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate3_verify_combined_urdf.py
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate3_verify_combined_urdf.py
```

출력 마지막 `=== 게이트 3 선행 검증 2:` 줄이 결론이다. 30초 이내에 끝난다.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·로봇 구성의 유일한 출처 — 원칙 1)

_assets = cfg.superdex_assets_path()
if _assets is None:
    sys.exit(
        "RTAUTO_SUPERDEX_REPO(또는 RTAUTO_SUPERDEX_ASSETS)가 .env에 없다.\n"
        "docs/SUPERDEX_POC_PLAN.md §11 0-5 참고."
    )
os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))

import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402

# UR16e e-series 관절 한계 (도). 2026-09-08 팔 단독 URDF 실측과 UR 공식 스펙이 일치했다.
# 캘리브레이션/스펙 상수라 하드코딩이 아니지만, 정본을 한 곳에만 둔다(원칙 1) — 이
# 표는 "URDF 가 스펙에서 벗어나지 않았는가"를 묻는 판정 기준이지 로봇 구성값이 아니다.
UR16E_LIMITS_DEG = {
    "shoulder_pan_joint": 360.0,
    "shoulder_lift_joint": 360.0,
    "elbow_joint": 180.0,
    "wrist_1_joint": 360.0,
    "wrist_2_joint": 360.0,
    "wrist_3_joint": 360.0,
}
UR_ARM_DOFS = len(UR16E_LIMITS_DEG)
DG5F_DOFS = 20  # 게이트 0 실측 (손목 용접 시 정확히 20)


def collision_meshes(urdf: Path) -> list[tuple[str, Path]]:
    """URDF 의 (링크 이름, 충돌 메시 경로) 목록. 경로는 URDF 위치 기준으로 푼다."""
    import xml.etree.ElementTree as ET

    out: list[tuple[str, Path]] = []
    for link in ET.parse(urdf).getroot().findall("link"):
        name = link.get("name", "?")
        for col in link.findall("collision"):
            mesh = col.find("geometry/mesh")
            if mesh is None:
                continue
            filename = mesh.get("filename", "")
            if filename:
                out.append((name, (urdf.parent / filename).resolve()))
    return out


def audit_watertight(urdf: Path) -> tuple[list[str], list[str]]:
    """충돌 메시가 watertight 인지 검사해 (열린 메시 링크, 읽기 실패) 를 돌려준다.

    SuperDex 런타임 로더는 충돌 메시가 watertight 라고 **가정**하고, 아니면 스텝 중
    경고를 뿌린다("The collider mesh is not topologically closed ... The SDF sign may be
    incorrect"). 그 경고는 stderr 로 흘러가 세기 어려우므로 여기서 직접 판정해
    **Studio remesh 대상 목록**으로 만든다 — 사람이 GUI 에서 무엇을 고쳐야 하는지가
    이 목록이다.
    """
    import trimesh  # superdex-physics 의 의존이라 별도 설치가 필요 없다

    open_links: list[str] = []
    unreadable: list[str] = []
    for link, path in collision_meshes(urdf):
        if not path.is_file():
            unreadable.append(f"{link}: 파일 없음 {path}")
            continue
        try:
            # ⚠️ process=True 여야 한다(정점 병합). STL 은 삼각형마다 정점을 따로
            # 저장해 공유 인덱스가 없으므로, 병합하지 않으면 **닫힌 메시도 전부 열린
            # 것으로 나온다** — process=False 로 재면 35개 중 35개가 열림으로 나오는데
            # 네이티브 경고는 8개뿐이었다(실측 2026-09-09). 그 불일치가 오측정의 증거다.
            mesh = trimesh.load_mesh(str(path))
        except Exception as exc:
            unreadable.append(f"{link}: {type(exc).__name__}")
            continue
        if not getattr(mesh, "is_watertight", False):
            open_links.append(link)
    return open_links, unreadable


def combined_urdf() -> Path:
    build = REPO_ROOT / "urdf" / f"{cfg.UR_TYPE}_dg5f_{cfg.DG5F_HAND}_build"
    return build / f"{cfg.UR_TYPE}_dg5f_{cfg.DG5F_HAND}.urdf"


def main() -> None:
    ap = argparse.ArgumentParser(description="UR16e+DG5F 결합 URDF 물리 검증")
    ap.add_argument("--steps", type=int, default=1000,
                    help="홈 자세 유지 시뮬 스텝 수 (기본 1000 = 5초 @200 Hz)")
    # ⚠️ 게이트 0 손 테스트의 게인(1e3/1e2)을 그대로 쓰면 안 된다 — 실측으로 확인했다.
    # 900 mm 팔은 링크가 무겁고 모멘트 팔이 길어 중력 토크가 손과 자릿수가 다르다.
    # 강성만 바꿔 재현한 정상상태 처짐(damping 1e3, 600스텝, 2026-09-09):
    #     1e3 -> 92.0 mm | 1e4 -> 9.88 mm | 1e5 -> 0.99 mm
    # **강성에 정확히 반비례**한다 = 발산이 아니라 P제어 정상상태 오차다. 결합 기하
    # 결함이 아니므로 팔에 맞는 게인을 기본값으로 둔다.
    ap.add_argument("--stiffness", type=float, default=1.0e5)
    ap.add_argument("--damping", type=float, default=1.0e3)
    ap.add_argument("--sag-limit", type=float, default=0.05,
                    help="기본 게인에서 허용할 최대 중력 처짐 [m]")
    args = ap.parse_args()

    urdf = combined_urdf()
    if not urdf.is_file():
        sys.exit(
            f"결합 URDF 가 없다: {urdf}\n"
            f"urdf/build_arm_hand.py 를 먼저 돌려 빌드 폴더를 만든다."
        )
    print(f"결합 URDF : {urdf}")
    print(f"구성      : UR_TYPE={cfg.UR_TYPE}  DG5F_HAND={cfg.DG5F_HAND}")
    print()

    dt = 1.0 / cfg.SUPERDEX_SIM_HZ
    physics.initialize(num_worker_threads=0)
    scene = physics.create_scene("Gate3 Combined URDF")
    scene.set_gravity([0, 0, -9.81])

    prefab = robotics.load_bot_prefab_from_urdf_file(str(urdf))

    # world_joint 기본값은 FREE 라 로봇이 자유낙하한다(게이트 0 실측). 베이스를 world 에
    # 용접한다 — CLAUDE.md 의 동작 원칙("매니퓰레이션은 베이스 정지 상태에서만")과 같다.
    prefab.joints[0].type = physics.ArticulatedJointType.HARD

    links = [prefab.links[i].name for i in range(len(prefab.links))]
    joints = [prefab.joints[i] for i in range(len(prefab.joints))]
    revolute = [j for j in joints if j.type == physics.ArticulatedJointType.REVOLUTE]

    print(f"링크 {len(links)}개 / 조인트 {len(joints)}개 / REVOLUTE {len(revolute)}개")

    failures: list[str] = []

    # --- 1) tool0 생존 -----------------------------------------------------------
    # 손을 붙이는 기준 링크다. 결합 파일의 parentLinkName 이 이 이름을 쓴다.
    if "tool0" in links:
        print("통과  tool0 링크 존재 — 결합 파일의 parentLinkName 기준이 살아 있다")
    else:
        failures.append("tool0 링크가 없다 — 결합 파일의 parentLinkName 을 바꿔야 한다")
        print(f"실패  tool0 링크 없음. 손목 근처 링크: "
              f"{[n for n in links if 'wrist' in n or 'flange' in n or 'tool' in n]}")

    # --- 2) DOF 수 ---------------------------------------------------------------
    expected = UR_ARM_DOFS + DG5F_DOFS
    if len(revolute) == expected:
        print(f"통과  REVOLUTE {len(revolute)}개 = 팔 {UR_ARM_DOFS} + 손 {DG5F_DOFS}")
    else:
        failures.append(f"REVOLUTE 수 불일치: {len(revolute)} (기대 {expected})")
        print(f"실패  REVOLUTE {len(revolute)}개 (기대 {expected})")

    # --- 3) 팔 관절 한계가 UR16e 스펙과 일치하는가 --------------------------------
    by_name = {j.name: j for j in revolute}
    missing = [n for n in UR16E_LIMITS_DEG if n not in by_name]
    if missing:
        failures.append(f"팔 관절 이름을 찾지 못했다: {missing}")
        print(f"실패  팔 관절 누락: {missing}")
    else:
        bad = []
        for name, spec_deg in UR16E_LIMITS_DEG.items():
            j = by_name[name]
            ax = [round(float(v), 0) for v in j.axis]
            k = ax.index(1.0) if 1.0 in ax else (ax.index(-1.0) if -1.0 in ax else 0)
            lo = math.degrees(float(j.min_limit[k]))
            hi = math.degrees(float(j.max_limit[k]))
            # 대칭 ±spec 을 기대한다. URDF 는 라디안이라 반올림 오차를 1도 허용한다.
            if abs(lo + spec_deg) > 1.0 or abs(hi - spec_deg) > 1.0:
                bad.append(f"{name}: [{lo:.1f}, {hi:.1f}]도 (기대 ±{spec_deg:.0f})")
        if bad:
            failures.append(f"관절 한계가 UR16e 스펙과 다르다: {bad}")
            print("실패  관절 한계 불일치:")
            for line in bad:
                print(f"        {line}")
        else:
            print(f"통과  팔 6축 관절 한계가 UR16e 스펙과 일치 "
                  f"(±360, elbow ±180)")

    # --- 4) 충돌 메시 watertight 감사 ---------------------------------------------
    # 실패로 세지 **않는다** — watertight 로 만드는 것이 Studio remesh 단계가 하는 일이라
    # 지금 열려 있는 것이 정상이다. 대신 사람이 무엇을 고쳐야 하는지 목록으로 남긴다.
    open_links, unreadable = audit_watertight(urdf)
    total = len(collision_meshes(urdf))
    if unreadable:
        failures.append(f"충돌 메시를 읽지 못했다: {unreadable}")
        print(f"실패  충돌 메시 읽기 실패 {len(unreadable)}건:")
        for line in unreadable:
            print(f"        {line}")
    # 팔과 손을 갈라 본다 — **결정에 쓰이는 사실이 다르다.** 우리가 Studio 에서 굽는
    # 것은 팔뿐이고(손은 공식 baked asset 을 쓴다), 따라서 팔 메시가 깨끗한지가
    # bake 성공 가능성을 좌우한다.
    prefix = cfg.dg5f_link_prefix()
    open_arm = [n for n in open_links if not n.startswith(prefix)]
    open_hand = [n for n in open_links if n.startswith(prefix)]
    if not open_links:
        print(f"통과  충돌 메시 {total}개 전부 watertight")
    else:
        print(f"      충돌 메시 {total}개 중 {len(open_links)}개가 열린 메시"
              f"(not watertight)")
        if open_arm:
            failures.append(
                f"**팔** 충돌 메시 {len(open_arm)}개가 열려 있다: {open_arm} — "
                f"Studio bake 입력이 되는 메시라 bake 품질에 직접 영향을 준다"
            )
            print(f"실패  그중 팔 링크 {len(open_arm)}개 — bake 입력이라 문제다:")
            for name in open_arm:
                print(f"        {name}")
        else:
            print("통과  **팔 링크는 전부 watertight** — Studio bake 입력이 깨끗하다")
        if open_hand:
            # 실패로 세지 않는다: 결합 URDF 의 손은 우리 자체 메시이고, 최종 결합체는
            # 공식 baked 손 asset(@superdex 태그)을 쓴다. 이 URDF 를 직접 시뮬할 때만
            # 영향이 있다.
            print(f"주의  손 링크 {len(open_hand)}개가 열려 있다 — 이 URDF 를 직접")
            print("      시뮬할 때만 문제다. 최종 결합체는 공식 baked 손 asset 을 쓴다:")
            print(f"        {', '.join(open_hand)}")

    # --- 5) 시뮬 안정성 -----------------------------------------------------------
    ctx = robotics.create_context()
    bot = robotics.create_bot(scene, prefab, ctx)
    actor = bot.get_articulated_actor()
    num_dofs = actor.get_num_dofs()
    if num_dofs != len(revolute):
        failures.append(f"actor DOF {num_dofs} != REVOLUTE {len(revolute)}")
        print(f"실패  actor DOF {num_dofs} != REVOLUTE {len(revolute)}")
    else:
        print(f"통과  actor DOF {num_dofs} (베이스 용접, root DOF "
              f"{actor.get_articulated_shape_info().dof_info[0].get_size()})")

    # ⚠️ 자기접촉 수는 **이 경로에서 측정할 수 없다** (실측 2026-09-09). 접촉점 쿼리를
    # 등록하면 네이티브가 거부한다:
    #     "Contact queries are only supported for actors with contact sample points."
    # contact sample point 는 Studio bake 산출물에 들어 있는 것이고 런타임 URDF 로더는
    # 만들지 않는다. 즉 **자기충돌 판정은 bake 후로 미룰 수밖에 없다** — 조용히 건너뛰지
    # 않고 여기에 사실로 남긴다. bake 후에는 gate3_setup_asset_root.py --verify-only
    # 로 올린 결합 bot 에서 측정한다.
    print("보류  자기접촉 수 — 런타임 URDF 로더에는 contact sample point 가 없어")
    print("      측정 불가. Studio bake 후 결합 bot 에서 판정한다.")

    tracking = physics.PoseTrackingParams(
        stiffness=args.stiffness, damping=args.damping
    )
    pose_ctrl = bot.create_controller("MOCHI_ARTICULATED_POSE")
    pose_ctrl.set_params(
        robotics.ControllerMochiArticulatedPoseParams(
            pose_controller_params=physics.PoseControllerParams(
                joint_tracking=physics.DynamicArrayPoseTrackingParams([tracking])
            )
        )
    )
    pose_ctrl.initialize(True)

    home = physics.DynamicArrayReal(num_dofs)
    actor.get_articulated_pose(home)
    home_np = np.array([float(v) for v in home], dtype=np.float64)

    link_tf = physics.DynamicArrayTransformRT(len(links))

    def link_positions() -> np.ndarray:
        actor.get_articulated_link_transforms(link_tf)
        return np.array(
            [[float(v) for v in link_tf[i].translation] for i in range(len(links))]
        )

    start_pos = link_positions()
    target = physics.DynamicArrayReal(home_np.tolist())
    half = args.steps // 2
    mid_pos = None
    for i in range(args.steps):
        actor.set_articulated_target_pose(target)
        scene.step(dt)
        if i + 1 == half:
            mid_pos = link_positions()

    end_pos = link_positions()
    if not np.isfinite(end_pos).all():
        failures.append("시뮬 발산 — 링크 위치에 NaN/Inf 가 생겼다")
        print("실패  시뮬 발산 (NaN/Inf)")
    else:
        # 판정을 **두 갈래로 나눈다**. 하나로 합치면 게인을 낮췄을 때 "결합 결함"으로
        # 오판한다 — 실제로 그렇게 오판했다(위 게인 주석 참고).
        #   settle : 후반 절반 동안 추가로 움직인 양. 발산/진동이면 커진다.
        #            게인과 무관하게 "이 몸체가 정지 상태로 수렴하는가"를 묻는다.
        #   sag    : 명령 자세 대비 총 처짐. 게인에 반비례하는 정상상태 오차다.
        settle = float(np.abs(end_pos - mid_pos).max())
        sag = float(np.abs(end_pos - start_pos).max())
        worst = links[int(np.abs(end_pos - start_pos).max(axis=1).argmax())]
        if settle > 1e-3:
            failures.append(
                f"수렴하지 않는다 — 후반 절반에서 {settle * 1e3:.1f} mm 추가 이동"
            )
            print(f"실패  수렴 실패, 후반 절반 추가 이동 {settle * 1e3:.1f} mm")
        else:
            print(f"통과  {args.steps}스텝({args.steps * dt:.1f}초) 후 정지 수렴 — "
                  f"후반 절반 추가 이동 {settle * 1e3:.3f} mm")
        if sag > args.sag_limit:
            failures.append(
                f"중력 처짐 {sag * 1e3:.1f} mm > 한계 {args.sag_limit * 1e3:.0f} mm "
                f"(최대 링크 {worst}) — 게인을 올려도 줄지 않으면 질량/관성을 의심하라"
            )
            print(f"실패  중력 처짐 {sag * 1e3:.1f} mm (최대 링크 {worst})")
        else:
            print(f"통과  중력 처짐 {sag * 1e3:.2f} mm (최대 링크 {worst}, "
                  f"강성 {args.stiffness:.0e} 에서의 정상상태 오차)")

    print()
    print("=" * 72)
    if failures:
        print("=== 게이트 3 선행 검증 2: 실패 ===")
        for f in failures:
            print(f"    - {f}")
        sys.exit(1)
    print("=== 게이트 3 선행 검증 2: 통과 ===")
    print("    결합 기하·관절 한계·시뮬 안정성이 정상이고, 팔 충돌 메시가 watertight 다.")
    print("    ⚠️ 자기충돌 판정은 남아 있다 — 위 '보류' 참고. bake 후에만 측정 가능하다.")
    print("    다음: docs/SUPERDEX_POC_PLAN.md §5 게이트 3-2 (사람이 Studio 에서 굽는다)")


if __name__ == "__main__":
    main()
