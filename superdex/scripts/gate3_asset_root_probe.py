# -*- coding: utf-8 -*-
"""게이트 3 / U7 판정 — 결합 `.superdex_bot` 이 **다른 asset 트리**를 참조할 수 있는가.

U7 은 "우리가 만든 UR16e asset 을 어디에 두는가"다. 걸림돌은 하나다:

  공식 Tesollo DG5F asset 은 **재배포 제한이 있어 우리 저장소에 커밋할 수 없다**(U4).
  그런데 결합 bot 은 팔(`base`)과 손(`AttachBot.path`)을 둘 다 참조해야 한다.

`docs/SUPERDEX_POC_PLAN.md` §5 게이트 3-4 가 후보 3개를 적어 뒀고, 그중 3번
("SuperDex 가 다중 asset 검색 경로를 지원하는가 — 지원하면 가장 깔끔하다")을
**추측하지 않고 여기서 직접 로드해 판정한다.** Studio bake(사람 조작) 전에 답이 나와야
asset 을 어디에 구울지 정할 수 있다.

판정 대상은 우리 UR16e asset 이 아니라 **공식 fr3 + dg5f_short_right 조합**이다 —
우리 팔 asset 은 아직 없고, 물어보는 것은 "참조 방식이 성립하는가"이지 특정 로봇이
아니기 때문이다. 여기서 통과한 참조 방식을 그대로 UR16e 결합에 쓴다.

## 참조 방식과 실측 결과 (2026-09-09)

| 케이스 | 표기 | 결과 |
|---|---|---|
| A 대조군    | 공식 조합 asset 을 그대로 로드    | **통과** (links=38) — 로더·환경 정상 |
| B `//` 교차 | 우리 루트에서 `//arms/fr3/...`  | 실패 — `//` 는 자기 루트를 벗어나지 못한다 |
| C 절대경로  | `D:/.../fr3.superdex_bot`      | 실패 — *"Absolute bot paths are not allowed"* |
| D 상대경로  | `../../../project_superdex/...`| 실패 — *"Bot path ascends beyond the permitted ... '..'"* |
| **E `@tag/`**   | `@superdex/arms/fr3/...`   | **통과** (links=38) |
| **E2 `@tag/`**  | 태그 대상을 상대경로로        | **통과** (links=38) |

**C 의 거부 메시지가 답을 알려줬다** — *"use `//`, `@tag/`, or a file-relative path"*.
`@tag/` 는 원래 계획에 없던 네 번째 표기이고, `.superdex_root` 가 빈 마커가 아니라
**`{"@tag": "경로"}` JSON 사전**임을 뜻한다(네이티브 문자열:
*"Failed to deserialize .superdex_root JSON (expected object of @tag : path)"*).
태그 대상 폴더에도 마커가 있어야 한다 — 공식 `assets/bots/` 에 있다.

**결론: U7 후보 3번(다중 검색 경로)이 지원된다.** 공식 asset 을 한 바이트도 복사하지
않고 우리 리포에 팔 asset 과 결합 파일만 둔다. 배선은
`superdex/scripts/gate3_setup_asset_root.py` 가 만든다.

> ⚠️ 케이스 D 는 **드라이브가 다르면 물어볼 수 없는 질문**이 된다(Windows 에서 상대경로가
> 존재하지 않는다). 그래서 임시 루트를 리포와 같은 드라이브에 만든다 — 기본 임시폴더가
> `C:` 이고 asset 이 `D:` 이면 계산 자체가 불가능하다.

실행 (터미널 1, PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/gate3_asset_root_probe.py

출력 마지막의 `=== U7 판정:` 줄이 결론이다. 임시 트리는 종료 시 지운다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
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

# 태그 이름. 네이티브 검증 규칙: `@` + 영문자/숫자/밑줄만.
TAG = "@superdex"

import superdex.robotics as robotics  # noqa: E402
from superdex.physics.paths import resolve_asset  # noqa: E402


def official_combo_asset() -> str:
    """대조군으로 쓸 공식 fr3 + DG5F 조합 asset의 assets/ 상대경로.

    ⚠️ **동봉 조합 샘플은 손 변형을 다 갖고 있지 않다** (실측 2026-09-09):
    `bots/hands/` 에는 dg5f_long·dg5f_short 가 모두 있지만 `bots/arm_hand_combos/` 에는
    `fr3_dg5f_short` 뿐이다. 우리 설정(`DG5F_SHORT=False` → long)을 그대로 대입하면
    없는 파일을 찾는다. 그래서 **설정값을 우선 시도하고, 없으면 존재하는 조합을 집는다** —
    이 스크립트가 묻는 것은 "참조 표기가 성립하는가"이지 어느 손 변형인가가 아니다.

    조합 asset 경로 형식(실측):
    `bots/arm_hand_combos/fr3_<variant>/<hand>/fr3_<variant>_<hand>.superdex_bot`
    """
    _, _, variant, hand, _ = cfg.superdex_hand_asset().split("/")
    combos = _assets / "bots" / "arm_hand_combos"

    def rel(v: str) -> str:
        return f"bots/arm_hand_combos/fr3_{v}/{hand}/fr3_{v}_{hand}.superdex_bot"

    if (_assets / rel(variant)).is_file():
        return rel(variant)
    for other in sorted(p.name.removeprefix("fr3_") for p in combos.glob("fr3_dg5f_*")):
        if (_assets / rel(other)).is_file():
            print(
                f"[대조군] 설정 변형 {variant} 의 조합 샘플이 없어 {other} 로 대체한다 "
                f"(참조 표기 판정에는 영향 없다)."
            )
            return rel(other)
    sys.exit(
        f"공식 fr3+DG5F 조합 샘플을 찾지 못했다: {combos}\n"
        f"asset 트리가 온전한지 확인하라 (docs/SUPERDEX_POC_PLAN.md §11 0-5)."
    )


def load(path: Path) -> tuple[bool, str]:
    """로드해 보고 (성공여부, 요약) 을 돌려준다. 예외는 삼키고 종류만 남긴다."""
    try:
        prefab = robotics.load_bot_prefab_from_file(str(path))
    except Exception as exc:  # 바인딩이 superdex.physics.Error 를 던진다
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
    n_links = len(prefab.links) if hasattr(prefab, "links") else -1
    n_joints = len(prefab.joints) if hasattr(prefab, "joints") else -1
    if n_links <= 0:
        # 문서상 "default-constructed on failure" — 조용한 실패를 성공으로 세지 않는다.
        return False, f"빈 prefab (links={n_links}) — 조용한 실패"
    return True, f"links={n_links} joints={n_joints}"


def write_combo(dest: Path, base_ref: str, hand_ref: str, attach_from: dict) -> Path:
    """공식 조합과 같은 형식의 결합 파일을 참조 표기만 바꿔 쓴다."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "base": base_ref,
        "name": dest.stem,
        "modifications": [
            {
                "AttachBot": {
                    "enabled": True,
                    "joint": {
                        "name": "dg5f_to_fr3",
                        "type": "Hard",
                        "parentLinkFromJoint": attach_from,
                    },
                    "name": "dg5f",
                    "parentLinkName": "fr3_link8",
                    "path": hand_ref,
                }
            }
        ],
    }
    dest.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return dest


def main() -> None:
    official = resolve_asset(official_combo_asset())
    src = json.loads(official.read_text(encoding="utf-8"))
    attach = src["modifications"][0]["AttachBot"]
    attach_from = attach["joint"].get("parentLinkFromJoint", {})
    base_ref_official = src["base"]          # "//arms/fr3/fr3.superdex_bot"
    hand_ref_official = attach["path"]       # "//hands/dg5f_short/right/..."

    print(f"assets root   : {_assets}")
    print(f"공식 조합     : {official}")
    print(f"  base        : {base_ref_official}")
    print(f"  attach path : {hand_ref_official}")
    print()

    # `//` 표기를 절대경로로 푼다 — assets/bots/ 의 .superdex_root 가 `//` 의 기준이다.
    bots_root = _assets / "bots"
    base_abs = bots_root / base_ref_official.removeprefix("//")
    hand_abs = bots_root / hand_ref_official.removeprefix("//")
    for p in (base_abs, hand_abs):
        if not p.is_file():
            sys.exit(f"참조 원본이 없다: {p}\n공식 asset 트리가 온전한지 확인하라.")

    results: dict[str, tuple[bool, str]] = {}
    # 임시 루트를 **리포와 같은 드라이브**에 만든다. 기본 임시폴더(C:)를 쓰면 asset 트리가
    # 다른 드라이브(D:)일 때 케이스 D의 상대경로 계산이 Windows에서 불가능해진다.
    tmp = Path(tempfile.mkdtemp(prefix="rtauto_u7_", dir=str(REPO_ROOT.parent)))
    try:
        # 우리 리포를 흉내 낸 별도 asset 루트. 공식 asset 은 여기에 **없다**.
        our_bots = tmp / "assets" / "bots"
        our_bots.mkdir(parents=True)
        (our_bots / ".superdex_root").write_text("", encoding="utf-8")

        # A — 대조군.
        results["A 대조군 (공식 조합 그대로)"] = load(official)

        # B — 우리 루트에서 `//` 로 공식 트리를 가리켜 본다.
        b = write_combo(
            our_bots / "arm_hand_combos" / "probe_b" / "probe_b.superdex_bot",
            base_ref_official,
            hand_ref_official,
            attach_from,
        )
        results["B `//` 교차 트리"] = load(b)

        # C — 절대경로.
        c = write_combo(
            our_bots / "arm_hand_combos" / "probe_c" / "probe_c.superdex_bot",
            base_abs.as_posix(),
            hand_abs.as_posix(),
            attach_from,
        )
        results["C 절대경로"] = load(c)

        # D — 결합 파일 위치 기준 상대경로.
        d_dir = our_bots / "arm_hand_combos" / "probe_d"
        d_dir.mkdir(parents=True, exist_ok=True)
        try:
            rel_base = os.path.relpath(base_abs, d_dir).replace("\\", "/")
            rel_hand = os.path.relpath(hand_abs, d_dir).replace("\\", "/")
        except ValueError as exc:
            # Windows에서 드라이브가 다르면 상대경로가 존재하지 않는다 — 케이스 D는
            # 이 머신에서 물어볼 수 없는 질문이 된다. 실패로 세면 오판이다.
            results["D 파일기준 상대경로"] = (False, f"판정 불가 — {exc}")
        else:
            d = write_combo(
                d_dir / "probe_d.superdex_bot", rel_base, rel_hand, attach_from
            )
            results["D 파일기준 상대경로"] = load(d)

        # E — `@tag/` 표기. 케이스 C의 거부 메시지("use //, @tag/, or a file-relative
        # path")가 알려준 네 번째 표기다. 네이티브 문자열에 따르면 `.superdex_root` 는
        # 빈 마커가 아니라 **`@tag : 경로` JSON 사전**일 수 있다
        # ("expected object of @tag : path"). 태그 대상에도 마커가 있어야 한다.
        e_root = tmp / "tagged" / "bots"
        e_root.mkdir(parents=True)
        (e_root / ".superdex_root").write_text(
            json.dumps({TAG: str(bots_root)}), encoding="utf-8"
        )
        tagged_base = f"{TAG}/" + base_ref_official.removeprefix("//")
        tagged_hand = f"{TAG}/" + hand_ref_official.removeprefix("//")
        e = write_combo(
            e_root / "arm_hand_combos" / "probe_e" / "probe_e.superdex_bot",
            tagged_base,
            tagged_hand,
            attach_from,
        )
        results["E `@tag/` 교차 트리"] = load(e)

        # E2 — 같은 태그를 **상대경로**로 적어 본다. 통과하면 `.superdex_root` 를
        # 커밋할 수 있을지 판단할 재료가 된다(절대경로면 머신마다 달라 생성해야 한다).
        e2_root = tmp / "tagged_rel" / "bots"
        e2_root.mkdir(parents=True)
        try:
            rel_target = os.path.relpath(bots_root, e2_root).replace("\\", "/")
        except ValueError as exc:
            results["E2 `@tag/` 상대 대상"] = (False, f"판정 불가 — {exc}")
        else:
            (e2_root / ".superdex_root").write_text(
                json.dumps({TAG: rel_target}), encoding="utf-8"
            )
            e2 = write_combo(
                e2_root / "arm_hand_combos" / "probe_e2" / "probe_e2.superdex_bot",
                tagged_base,
                tagged_hand,
                attach_from,
            )
            results["E2 `@tag/` 상대 대상"] = load(e2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 72)
    for name, (ok, detail) in results.items():
        print(f"{'통과' if ok else '실패'}  {name:<28} {detail}")
    print("=" * 72)

    if not results["A 대조군 (공식 조합 그대로)"][0]:
        print("=== U7 판정: 판정 불가 — 대조군이 실패했다. 환경 문제부터 해결하라. ===")
        sys.exit(2)

    cross_ok = [k for k in results if k.startswith(("B ", "C ", "D ", "E")) and results[k][0]]
    if cross_ok:
        print(
            "=== U7 판정: 교차 트리 참조 가능 → 공식 asset 복사 불필요 ===\n"
            f"    통과한 표기: {', '.join(cross_ok)}\n"
            "    우리 리포에 UR16e asset + 결합 파일만 두고, 손 참조는\n"
            "    config/rtauto_config.py 에서 생성한다(경로 리터럴 금지 — 원칙 1)."
        )
    else:
        print(
            "=== U7 판정: 교차 트리 참조 불가 → 후보 1번 확정 ===\n"
            "    우리 리포(superdex/assets/bots/)를 asset 루트로 삼고,\n"
            "    공식 hands/·sensors/ 는 .gitignore + 복사 스크립트로 채운다."
        )


if __name__ == "__main__":
    main()
