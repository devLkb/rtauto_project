# -*- coding: utf-8 -*-
"""게이트 3 판정 — **실제 결합 bot**(구운 팔 + 공식 손)이 판정 기준을 만족하는가.

`docs/SUPERDEX_POC_PLAN.md` §5 게이트 3의 판정 문장은 이것이다:

> 결합 bot이 로드되고, 관절 한계가 UR16e 스펙과 일치하며, 충돌 형상이 깨지지 않았고
> 자기충돌이 정상인가.

선행 검증 2(`gate3_verify_combined_urdf.py`)가 **URDF 를 런타임 로더로** 올려 이 중
셋을 미리 답했지만, **자기충돌은 답할 수 없었다** — 접촉점 쿼리에 contact sample point
가 필요한데 런타임 URDF 로더는 만들지 않는다. 그 샘플점은 Studio bake 산출물에 들어
있으므로, **bake 가 끝난 지금에야** 마지막 항목을 답할 수 있다.

선행 검증 2와의 차이:

| | 선행 검증 2 (URDF) | **이 스크립트 (결합 bot)** |
|---|---|---|
| 팔 | 우리 URDF, SDF 즉석 생성 | **Studio 에서 구운 asset** |
| 손 | 우리 자체 DG5F 메시 | **공식 Tesollo baked asset** (`@superdex/` 태그) |
| 자기충돌 | 측정 불가 | **측정한다** |

즉 이것이 게이트 3의 **본 판정**이고, 선행 검증 2는 bake 전에 값싸게 돌린 예행이었다.

UR16e 관절 한계 기준표와 시뮬 게인 근거는 선행 검증 2에서 **가져다 쓴다** — 같은
사실을 두 곳에 타이핑하지 않는다(원칙 1).

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate3_verify_combined_bot.py
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate3_verify_combined_bot.py
```

먼저 `gate3_setup_asset_root.py` 로 배선이 만들어져 있어야 하고, 팔 asset 이
Studio bake 로 준비돼 있어야 한다(§5 게이트 3-2). 출력 마지막
`=== 게이트 3 판정:` 줄이 결론이다.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtauto_config as cfg  # noqa: E402  (경로·로봇 구성의 유일한 출처 — 원칙 1)

# 선행 검증 2 가 asset 경로 환경변수 설정과 superdex import 까지 해 준다.
# 기준표(UR16e 관절 한계, 손 DOF)도 그쪽이 정본이다.
from gate3_verify_combined_urdf import (  # noqa: E402
    DG5F_DOFS,
    UR16E_LIMITS_DEG,
    UR_ARM_DOFS,
)

import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="결합 bot 게이트 3 본 판정")
    ap.add_argument("--steps", type=int, default=1000,
                    help="홈 자세 유지 시뮬 스텝 수 (기본 1000 = 5초 @200 Hz)")
    # 선행 검증 2 와 같은 이유로 팔에 맞는 게인이다(손 기준 1e3 을 쓰면 9 cm 처진다).
    ap.add_argument("--stiffness", type=float, default=1.0e5)
    ap.add_argument("--damping", type=float, default=1.0e3)
    ap.add_argument("--sag-limit", type=float, default=0.05,
                    help="기본 게인에서 허용할 최대 중력 처짐 [m]")
    # 계측기 자기검사용 자세. 팔꿈치를 크게 접으면 팔뚝이 위팔에 닿는다(실측:
    # 170도/-20도에서 접촉 8704점, wrist_2/wrist_3 vs upper_arm).
    ap.add_argument("--fold-elbow-deg", type=float, default=170.0)
    ap.add_argument("--fold-lift-deg", type=float, default=-20.0)
    args = ap.parse_args()

    combo = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_combo_asset()
    arm = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_arm_asset()
    if not arm.is_file():
        sys.exit(
            f"팔 asset 이 없다: {arm}\n"
            f"Studio bake 가 먼저다 — docs/SUPERDEX_POC_PLAN.md §5 게이트 3-2."
        )
    if not combo.is_file():
        sys.exit(
            f"결합 파일이 없다: {combo}\n"
            f"python -u superdex/scripts/gate3_setup_asset_root.py 를 먼저 돌려라."
        )

    print(f"결합 bot : {combo}")
    print(f"팔 asset : {arm}")
    print(f"손 참조  : {cfg.superdex_hand_asset_tagged_ref()}")
    print(f"장착 회전: {cfg.SUPERDEX_HAND_MOUNT_QUAT}  (x,y,z,w)")
    print()

    dt = 1.0 / cfg.SUPERDEX_SIM_HZ
    physics.initialize(num_worker_threads=0)
    scene = physics.create_scene("Gate3 Combined Bot")
    scene.set_gravity([0, 0, -9.81])

    prefab = robotics.load_bot_prefab_from_file(str(combo))
    links = [prefab.links[i].name for i in range(len(prefab.links))]
    joints = [prefab.joints[i] for i in range(len(prefab.joints))]
    revolute = [j for j in joints if j.type == physics.ArticulatedJointType.REVOLUTE]
    print(f"링크 {len(links)}개 / 조인트 {len(joints)}개 / REVOLUTE {len(revolute)}개")

    failures: list[str] = []

    # --- 1) tool0 생존 -----------------------------------------------------------
    # 결합이 성립한 것 자체가 방증이지만(AttachBot 의 parentLinkName 이 tool0 다),
    # bake 가 fixed joint 를 접었는지 이름으로 직접 확인한다.
    if any(n.endswith("tool0") for n in links):
        print("통과  tool0 링크가 bake 후에도 살아 있다")
    else:
        failures.append("tool0 링크가 없다")
        print(f"실패  tool0 없음. 손목 근처: "
              f"{[n for n in links if 'wrist' in n or 'flange' in n or 'tool' in n]}")

    # --- 2) DOF 수 ---------------------------------------------------------------
    expected = UR_ARM_DOFS + DG5F_DOFS
    if len(revolute) == expected:
        print(f"통과  REVOLUTE {len(revolute)}개 = 팔 {UR_ARM_DOFS} + 손 {DG5F_DOFS}")
    else:
        failures.append(f"REVOLUTE 수 불일치: {len(revolute)} (기대 {expected})")
        print(f"실패  REVOLUTE {len(revolute)}개 (기대 {expected})")

    # --- 3) 팔 관절 한계 ----------------------------------------------------------
    # 결합 bot 의 링크·조인트 이름에는 AttachBot 이 붙인 접두사가 있을 수 있으므로
    # 이름 끝으로 찾는다.
    by_name = {}
    for j in revolute:
        for spec_name in UR16E_LIMITS_DEG:
            if j.name == spec_name or j.name.endswith("/" + spec_name):
                by_name[spec_name] = j
    missing = [n for n in UR16E_LIMITS_DEG if n not in by_name]
    if missing:
        failures.append(f"팔 관절을 찾지 못했다: {missing}")
        print(f"실패  팔 관절 누락: {missing}")
        print(f"        (실제 REVOLUTE 이름 일부: {[j.name for j in revolute[:8]]})")
    else:
        bad = []
        for name, spec_deg in UR16E_LIMITS_DEG.items():
            j = by_name[name]
            ax = [round(float(v), 0) for v in j.axis]
            k = ax.index(1.0) if 1.0 in ax else (ax.index(-1.0) if -1.0 in ax else 0)
            lo = math.degrees(float(j.min_limit[k]))
            hi = math.degrees(float(j.max_limit[k]))
            if abs(lo + spec_deg) > 1.0 or abs(hi - spec_deg) > 1.0:
                bad.append(f"{name}: [{lo:.1f}, {hi:.1f}]도 (기대 ±{spec_deg:.0f})")
        if bad:
            failures.append(f"관절 한계가 UR16e 스펙과 다르다: {bad}")
            print("실패  관절 한계 불일치:")
            for line in bad:
                print(f"        {line}")
        else:
            print("통과  팔 6축 관절 한계가 UR16e 스펙과 일치 (±360, elbow ±180)")

    # --- 4) 생성 + DOF ------------------------------------------------------------
    ctx = robotics.create_context()
    bot = robotics.create_bot(scene, prefab, ctx)
    actor = bot.get_articulated_actor()
    num_dofs = actor.get_num_dofs()
    if num_dofs == len(revolute):
        print(f"통과  actor DOF {num_dofs} (root DOF "
              f"{actor.get_articulated_shape_info().dof_info[0].get_size()})")
    else:
        failures.append(f"actor DOF {num_dofs} != REVOLUTE {len(revolute)}")
        print(f"실패  actor DOF {num_dofs} != REVOLUTE {len(revolute)}")

    # --- 5) 자기충돌 준비 — **bake 후에야 물어볼 수 있는 항목** ---------------------
    # ⚠️ 쿼리는 **링크 actor 마다** 걸어야 한다. articulated actor 전체에 걸면
    # "Contact queries are only supported for actors with contact sample points" 로
    # 거부된다(실측 2026-09-09 — 처음에 이렇게 걸어 오판했다). 접촉 샘플점은 충돌
    # 형상을 가진 링크에만 있으므로, 형상이 없는 프레임 링크(tool0·flange·ft_frame 등)와
    # 집합 actor 는 지원하지 않는 것이 정상이다.
    # 등록은 스텝 **전에** 해야 결과가 나온다(게이트 0 실측 함정).
    scene_actors: list = []
    scene.for_each_actor(lambda a: scene_actors.append(a))
    contact_actors = [
        a for a in scene_actors
        if a.is_query_supported(physics.QueryType.CONTACT_POINTS)
    ]
    for a in contact_actors:
        a.register_query(physics.QueryType.CONTACT_POINTS)
    print(f"      접촉 쿼리 등록 {len(contact_actors)}/{len(scene_actors)} actor "
          f"(나머지는 충돌 형상이 없는 프레임 링크)")

    def count_contacts() -> dict[str, int]:
        hits = {}
        for a in contact_actors:
            k = len(a.get_contact_points_world())
            if k:
                hits[a.get_name().split("/")[-1]] = k
        return hits

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
    target = physics.DynamicArrayReal([float(v) for v in home])

    link_tf = physics.DynamicArrayTransformRT(len(links))

    def link_positions() -> np.ndarray:
        actor.get_articulated_link_transforms(link_tf)
        return np.array(
            [[float(v) for v in link_tf[i].translation] for i in range(len(links))]
        )

    start_pos = link_positions()
    half = args.steps // 2
    mid_pos = None
    worst_hits: dict[str, int] = {}
    for i in range(args.steps):
        actor.set_articulated_target_pose(target)
        scene.step(dt)
        hits = count_contacts()
        if sum(hits.values()) > sum(worst_hits.values()):
            worst_hits = hits
        if i + 1 == half:
            mid_pos = link_positions()
    end_pos = link_positions()

    # 홈 자세는 팔을 편 자세다. 팔·손이 서로 파고들면 접촉이 잡힌다.
    home_contacts = sum(worst_hits.values())
    if home_contacts == 0:
        print("통과  홈 자세 자기접촉 0 — 팔과 손의 충돌 형상이 겹치지 않는다")
    else:
        failures.append(
            f"홈 자세에서 자기접촉 {home_contacts}점 {worst_hits} — 손 장착 위치/회전"
            f"(SUPERDEX_HAND_MOUNT_QUAT) 또는 충돌 형상을 확인하라"
        )
        print(f"실패  홈 자세 자기접촉 {home_contacts}점 {worst_hits}")

    # --- 6) 안정성 ----------------------------------------------------------------
    if not np.isfinite(end_pos).all():
        failures.append("시뮬 발산 — 링크 위치에 NaN/Inf")
        print("실패  시뮬 발산 (NaN/Inf)")
    else:
        settle = float(np.abs(end_pos - mid_pos).max())
        sag = float(np.abs(end_pos - start_pos).max())
        worst = links[int(np.abs(end_pos - start_pos).max(axis=1).argmax())]
        if settle > 1e-3:
            failures.append(f"수렴하지 않는다 — 후반 절반 {settle * 1e3:.1f} mm 추가 이동")
            print(f"실패  수렴 실패, 후반 절반 추가 이동 {settle * 1e3:.1f} mm")
        else:
            print(f"통과  {args.steps}스텝({args.steps * dt:.1f}초) 후 정지 수렴 — "
                  f"후반 절반 추가 이동 {settle * 1e3:.3f} mm")
        if sag > args.sag_limit:
            failures.append(f"중력 처짐 {sag * 1e3:.1f} mm (최대 링크 {worst})")
            print(f"실패  중력 처짐 {sag * 1e3:.1f} mm (최대 링크 {worst})")
        else:
            print(f"통과  중력 처짐 {sag * 1e3:.2f} mm (최대 링크 {worst}, "
                  f"강성 {args.stiffness:.0e} 에서의 정상상태 오차)")

    # --- 7) 계측기 자기검사 — "접촉 0" 이 진짜 0 인지 확인한다 -----------------------
    # 쿼리가 조용히 비어 있어도 위 5번은 "통과"로 보인다. 그래서 **일부러 충돌시켜**
    # 접촉이 잡히는지 확인한다. 여기서 0 이 나오면 5번의 0 은 근거가 없는 것이다.
    if home_contacts == 0:
        jn = [j.name for j in revolute]

        def dof_of(spec: str) -> int | None:
            for i, name in enumerate(jn):
                if name == spec or name.endswith("/" + spec):
                    return i
            return None

        i_elbow, i_lift = dof_of("elbow_joint"), dof_of("shoulder_lift_joint")
        if i_elbow is None or i_lift is None:
            failures.append("자기검사를 못 했다 — elbow/shoulder_lift DOF 를 못 찾았다")
            print("실패  자기검사 불가 (관절 인덱스를 못 찾음)")
        else:
            fold = np.array([float(v) for v in home], dtype=np.float64)
            fold[i_elbow] = math.radians(args.fold_elbow_deg)
            fold[i_lift] = math.radians(args.fold_lift_deg)
            fold_tgt = physics.DynamicArrayReal(fold.tolist())
            for _ in range(args.steps):
                actor.set_articulated_target_pose(fold_tgt)
                scene.step(dt)
            fold_hits = count_contacts()
            n_fold = sum(fold_hits.values())
            if n_fold > 0:
                print(f"통과  자기검사 — elbow {args.fold_elbow_deg:.0f}도로 접으니 "
                      f"접촉 {n_fold}점 {fold_hits}")
                print("      즉 위의 '홈 자세 자기접촉 0' 은 측정된 0 이다")
            else:
                failures.append(
                    "자기검사 실패 — 일부러 접었는데도 접촉이 0 이다. "
                    "위의 '자기접촉 0' 은 근거가 없다"
                )
                print(f"실패  자기검사 — 접어도 접촉 0. 앞의 0 을 신뢰할 수 없다")

    print()
    print("=" * 72)
    if failures:
        print("=== 게이트 3 판정: 실패 ===")
        for f in failures:
            print(f"    - {f}")
        sys.exit(1)
    print("=== 게이트 3 판정: 통과 ===")
    print("    구운 UR16e 팔 + 공식 DG5F 손 결합체가 로드·구동되고, 관절 한계가")
    print("    UR16e 스펙과 일치하며, 자기충돌이 없고, 시뮬이 안정적이다.")
    print("    ⚠️ 손 방향(엄지 위치)은 수치가 아니라 눈으로 볼 항목이다 — Studio 에서")
    print("       결합 bot 을 열어 확인하고 SUPERDEX_HAND_MOUNT_QUAT 를 확정하라.")


if __name__ == "__main__":
    main()
