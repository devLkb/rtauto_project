# -*- coding: utf-8 -*-
"""게이트 3 배선 — 우리 asset 루트를 만들고 UR16e+DG5F 결합 파일을 쓴다.

U7 이 실측으로 확정됐다(2026-09-09, `gate3_asset_root_probe.py`): 결합 `.superdex_bot` 은
`.superdex_root` 에 정의한 **`@tag/`** 로 다른 asset 트리를 참조할 수 있다. 그래서
**공식 Tesollo asset 을 한 바이트도 복사하지 않고** 우리 리포에 팔 asset 과 결합 파일만
둔다. 재배포 제한(U4)과 원칙 2(새 머신 부트스트랩)를 동시에 만족한다.

이 스크립트가 만드는 것:

| 산출물 | git | 왜 |
|---|---|---|
| `superdex/assets/bots/.superdex_root` | **비추적** | 공식 클론 위치를 담아 머신마다 다르다 → 생성물 |
| `superdex/assets/bots/arm_hand_combos/.../<ur>_<variant>_<hand>.superdex_bot` | **커밋** | 머신 의존 값이 없다(`//arms/...` + `@superdex/hands/...`) |

**새 머신에서는 이 스크립트를 한 번 돌려야 한다** — `.superdex_root` 가 없으면 결합
파일이 손을 찾지 못한다(원칙 2).

## 아직 사람이 해야 하는 일 — Studio SDF bake

팔 asset(`bots/arms/<ur>/<ur>.superdex_bot`)은 **여기서 만들 수 없다.** 확인한 사실:

- SDF bake 를 하는 `mochi_mesh` 네이티브 확장은 **Studio 앱 안에만 있고 파이썬 패키지로
  배포되지 않는다** (`superdex.physics.mesh` import 가 `NativeModuleNotFoundError`).
- `superdex_mesh_cli.exe` 는 Studio 가 쓰는 **바이너리 프레임 프로토콜 헬퍼**이지 사용자
  CLI 가 아니다 (`--help` 에 `malformed request frame` 을 뱉는다).
- robotics 바인딩에 prefab **저장 API 가 없다** — `load_bot_prefab_from_file` /
  `load_bot_prefab_from_urdf_file` 둘뿐이다.

즉 GUI 조작이 불가피하다. 절차는 `docs/SUPERDEX_POC_PLAN.md` §5 게이트 3-2 를 따른다.
bake 가 끝나면 산출물을 이 스크립트가 알려주는 경로에 넣고 `--verify` 를 다시 돌린다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate3_setup_asset_root.py
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate3_setup_asset_root.py
```

기본 동작이 곧 검증이다 — 배선을 쓰고, 팔 asset 이 있으면 결합 bot 을 실제로 로드해
보고, 없으면 **대역(공식 fr3 팔)으로 배선 자체가 성립하는지**까지 확인한 뒤 사람이 할
일을 정확히 알려준다. 파일을 건드리지 않고 상태만 보려면 `--verify-only`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·asset 위치의 유일한 출처 — 원칙 1)

_assets = cfg.superdex_assets_path()
if _assets is None:
    sys.exit(
        "RTAUTO_SUPERDEX_REPO(또는 RTAUTO_SUPERDEX_ASSETS)가 .env에 없다.\n"
        "docs/SUPERDEX_POC_PLAN.md §11 0-5 참고."
    )
os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))

import superdex.robotics as robotics  # noqa: E402

OFFICIAL_BOTS = _assets / "bots"


def write_root_marker(our_bots: Path) -> Path:
    """`.superdex_root` 에 공식 트리를 가리키는 태그를 심는다.

    대상 폴더에도 `.superdex_root` 가 있어야 태그가 성립한다(네이티브 검증:
    "Tag '%s' ... targets '%s' which has no '%s' marker").
    """
    if not (OFFICIAL_BOTS / ".superdex_root").is_file():
        sys.exit(
            f"공식 asset 트리에 루트 마커가 없다: {OFFICIAL_BOTS / '.superdex_root'}\n"
            f"클론이 온전한지 확인하라 (docs/SUPERDEX_POC_PLAN.md §11 0-5)."
        )
    our_bots.mkdir(parents=True, exist_ok=True)
    marker = our_bots / ".superdex_root"
    marker.write_text(
        json.dumps({cfg.SUPERDEX_OFFICIAL_TAG: str(OFFICIAL_BOTS)}, indent=2),
        encoding="utf-8",
    )
    return marker


def write_combo(our_bots: Path) -> Path:
    """팔+손 결합 파일. 공식 조합 asset과 같은 형식이고 머신 의존 값이 없다."""
    dest = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_combo_asset()
    dest.parent.mkdir(parents=True, exist_ok=True)
    qx, qy, qz, qw = cfg.SUPERDEX_HAND_MOUNT_QUAT
    doc = {
        "base": cfg.superdex_arm_asset_ref(),
        "name": dest.stem,
        "modifications": [
            {
                "AttachBot": {
                    "enabled": True,
                    # 조인트 이름은 우리 결합 URDF의 `tool0_to_dg_mount` 와 맞춘다.
                    "joint": {
                        "name": "tool0_to_dg_mount",
                        "type": "Hard",
                        "parentLinkFromJoint": {"rotation": [qx, qy, qz, qw]},
                    },
                    "name": f"dg5f_{cfg.DG5F_HAND}",
                    # 게이트 3 선행 검증에서 `tool0` 링크 생존을 확인했다(2026-09-08).
                    # Studio bake 후에도 남아 있는지 --verify 가 다시 본다.
                    "parentLinkName": "tool0",
                    "path": cfg.superdex_hand_asset_tagged_ref(),
                }
            }
        ],
    }
    dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return dest


def load(path: Path) -> tuple[bool, str]:
    try:
        prefab = robotics.load_bot_prefab_from_file(str(path))
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    links = list(getattr(prefab, "links", []))
    joints = list(getattr(prefab, "joints", []))
    if not links:
        return False, "빈 prefab — 조용한 실패"
    return True, f"links={len(links)} joints={len(joints)}"


def standin_check(our_bots: Path, combo: Path) -> tuple[bool, str]:
    """팔 asset 이 아직 없을 때, **배선 자체**가 성립하는지 대역으로 확인한다.

    우리 결합 파일의 `base` 만 공식 fr3 팔로 바꿔 로드한다. 통과하면 남은 실패 원인은
    태그·경로·형식이 아니라 **팔 asset 부재 하나뿐**임이 확정된다.
    """
    doc = json.loads(combo.read_text(encoding="utf-8"))
    doc["base"] = f"{cfg.SUPERDEX_OFFICIAL_TAG}/arms/fr3/fr3.superdex_bot"
    doc["name"] = "standin_wiring_check"
    # parentLinkName 은 fr3 링크로 바꿔야 한다 — 대역이 묻는 것은 참조 해석이지
    # UR16e 의 링크 이름이 아니다.
    doc["modifications"][0]["AttachBot"]["parentLinkName"] = "fr3_link8"
    probe = combo.parent / "_standin_wiring_check.superdex_bot"
    probe.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    try:
        return load(probe)
    finally:
        probe.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="게이트 3 asset 루트 배선과 검증")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="파일을 쓰지 않고 현재 상태만 검사한다",
    )
    args = ap.parse_args()

    our_bots = cfg.superdex_our_bots_root()
    combo = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_combo_asset()
    arm = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_arm_asset()

    print(f"공식 asset 트리 : {OFFICIAL_BOTS}")
    print(f"우리 asset 루트 : {our_bots}")
    print(f"태그            : {cfg.SUPERDEX_OFFICIAL_TAG} -> {OFFICIAL_BOTS}")
    print()

    if args.verify_only:
        marker = our_bots / ".superdex_root"
        if not marker.is_file():
            sys.exit(
                f"루트 마커가 없다: {marker}\n"
                f"--verify-only 없이 한 번 돌려 배선을 만들어라."
            )
        if not combo.is_file():
            sys.exit(f"결합 파일이 없다: {combo}\n--verify-only 없이 한 번 돌려라.")
    else:
        marker = write_root_marker(our_bots)
        combo = write_combo(our_bots)
        print(f"[생성] {marker.relative_to(REPO_ROOT)}  (git 비추적 — 머신마다 다르다)")
        print(f"[생성] {combo.relative_to(REPO_ROOT)}  (커밋 대상)")
        print(f"       base = {cfg.superdex_arm_asset_ref()}")
        print(f"       hand = {cfg.superdex_hand_asset_tagged_ref()}")
        print(f"       mount quat (x,y,z,w) = {cfg.SUPERDEX_HAND_MOUNT_QUAT}  ← 미확정")
        print()

    if arm.is_file():
        ok, detail = load(combo)
        print("=" * 72)
        print(f"{'통과' if ok else '실패'}  결합 bot 로드  {detail}")
        print("=" * 72)
        if ok:
            print("=== 게이트 3 배선: 통과 — 결합 bot 이 로드된다 ===")
            print("    다음: 관절 한계·자기충돌 검증 (docs/SUPERDEX_POC_PLAN.md §5 게이트 3 판정)")
        else:
            print("=== 게이트 3 배선: 실패 — 위 에러를 먼저 해소하라 ===")
            sys.exit(1)
        return

    ok, detail = standin_check(our_bots, combo)
    print("=" * 72)
    print(f"{'통과' if ok else '실패'}  대역 배선 확인 (공식 fr3 팔로 대체)  {detail}")
    print("=" * 72)
    if not ok:
        print(
            "=== 배선 자체가 깨졌다 ===\n"
            "    팔 asset 부재와 무관한 문제다. 태그·경로·JSON 형식을 확인하라.\n"
            f"    판정 근거 스크립트: superdex/scripts/gate3_asset_root_probe.py"
        )
        sys.exit(1)

    print(
        "=== 배선 통과. 남은 것은 팔 asset 하나뿐이다 (사람이 Studio 에서 만든다) ===\n"
        f"    넣을 위치 : {arm}\n"
        f"    입력 URDF : {REPO_ROOT / 'urdf' / (cfg.UR_TYPE + '_dg5f_' + cfg.DG5F_HAND + '_build') / (cfg.UR_TYPE + '_arm_only.urdf')}\n"
        "    절차      : docs/SUPERDEX_POC_PLAN.md §5 게이트 3-2 (Studio import -> remesh\n"
        "                -> watertight -> SDF bake). 공식 bots/arms/fr3/ 와 같은 구조로\n"
        "                (.superdex_bot + collision/ + render/) 굽는다.\n"
        "    끝난 뒤   : python -u superdex/scripts/gate3_setup_asset_root.py --verify-only"
    )


if __name__ == "__main__":
    main()
