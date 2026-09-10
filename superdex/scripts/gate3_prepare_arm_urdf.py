# -*- coding: utf-8 -*-
"""게이트 3 준비 — UR16e **팔 단독** URDF의 메시 경로를 SuperDex가 읽을 수 있게 바꾼다.

`urdf/ur16e_dg5f_right_build/` 에 이미 두 파일이 있다(실측):

| 파일 | 메시 참조 | 용도 |
|---|---|---|
| `ur16e_raw.urdf`        | `package://ur_description/meshes/...` | 팔 단독 — **팔 asset의 입력** |
| `ur16e_dg5f_right.urdf` | `meshes/ur/...` (상대경로)             | 팔+손 결합 (자체 DG5F) |

`package://` 는 ROS 패키지 URI라 SuperDex Studio가 해석하지 못한다. 결합 URDF를 만들 때
`build_arm_hand.py` 가 하는 리라이트와 **같은 함수를 재사용해** 팔 단독에도 적용한다
(같은 규칙을 두 번 구현하지 않는다 — 원칙 1).

충돌 형상은 13개 링크 전부 mesh(`.stl`)이므로 "primitive collision은 조용히 무시된다"는
SuperDex URDF 로더 제약에는 걸리지 않는다(게이트 3 절 참고).

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 또는 vision venv 아무거나):
    python superdex/scripts/gate3_prepare_arm_urdf.py

산출물: `urdf/ur16e_dg5f_right_build/ur16e_arm_only.urdf`
그 다음: SuperDex Studio에서 import -> remesh -> watertight -> SDF bake ->
`bots/arms/ur16e/ur16e.superdex_bot` (docs/SUPERDEX_POC_PLAN.md 게이트 3-2)
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "urdf"))

import rtauto_config as cfg  # noqa: E402  (경로·로봇 구성의 유일한 출처 — 원칙 1)
from build_arm_hand import rewrite_mesh  # noqa: E402  (리라이트 규칙 재사용)

BUILD_DIR = REPO_ROOT / "urdf" / f"{cfg.UR_TYPE}_dg5f_{cfg.DG5F_HAND}_build"


def main() -> None:
    ap = argparse.ArgumentParser(description="팔 단독 URDF 메시 경로 리라이트")
    ap.add_argument("--src", type=Path, default=BUILD_DIR / f"{cfg.UR_TYPE}_raw.urdf")
    ap.add_argument("--out", type=Path, default=BUILD_DIR / f"{cfg.UR_TYPE}_arm_only.urdf")
    args = ap.parse_args()

    if not args.src.is_file():
        sys.exit(
            f"입력 URDF가 없다: {args.src}\n"
            f"urdf/build_arm_hand.py 를 먼저 돌려 빌드 폴더를 만든다."
        )

    tree = ET.parse(args.src)
    root = tree.getroot()

    n = rewrite_mesh(root, "package://ur_description/meshes/", "meshes/ur/")

    # 남은 package:// 가 있으면 Studio에서 조용히 실패하므로 여기서 잡는다.
    leftover = sorted({
        m.get("filename") for m in root.iter("mesh")
        if (m.get("filename") or "").startswith("package://")
    })
    if leftover:
        sys.exit(
            "리라이트되지 않은 package:// 참조가 남았다 — 규칙을 추가해야 한다:\n  "
            + "\n  ".join(leftover)
        )

    links = len(list(root.iter("link")))
    joints = len(list(root.iter("joint")))
    collisions = [m.get("filename") for lk in root.iter("link")
                  for col in lk.iter("collision") for m in col.iter("mesh")]
    prim = [tag for lk in root.iter("link") for col in lk.iter("collision")
            for tag in ("box", "cylinder", "sphere") if col.find(tag) is not None]

    tree.write(args.out, encoding="utf-8", xml_declaration=True)

    print(f"입력   : {args.src.relative_to(REPO_ROOT).as_posix()}")
    print(f"산출물 : {args.out.relative_to(REPO_ROOT).as_posix()}")
    print(f"리라이트: {n}개 메시 경로  (package:// 잔여 0)")
    print(f"구조   : 링크 {links}개 / 조인트 {joints}개")
    print(f"충돌   : mesh {len(collisions)}개 / primitive {len(prim)}개"
          f"  {'(primitive 없음 — 로더 제약 회피)' if not prim else '(⚠️ primitive는 무시될 수 있다)'}")
    print("\n다음: SuperDex Studio에서 이 파일을 import -> remesh -> watertight -> SDF bake")
    print("      -> bots/arms/ur16e/ur16e.superdex_bot  (계획 문서 게이트 3-2)")


if __name__ == "__main__":
    main()
