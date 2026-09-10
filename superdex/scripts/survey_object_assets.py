# -*- coding: utf-8 -*-
"""공식 asset 트리의 파지 대상 후보를 전수 조사한다 — 크기·질량·손 적합성.

**왜 필요한가.** 프로젝트 최종 목적이 범용 파지로 바뀐 뒤(로드맵 v17) 성공 조건이
"학습하지 않은 물체로 넘어가는 것"이 됐다. 그런데 게이트 4 에서 쓴 물체는 4종뿐이고
그중 손 크기에 맞는 것은 `duck_lamp`·`paper_cup` 둘이었다 — **물체 확보 자체가 작업**이라고
인수인계에 적힌 이유다. 무엇이 있는지부터 수치로 알아야 한다.

**어떻게 재는가.** rigid actor 는 local node 좌표 컴포넌트를 주지 않아(실측 확인)
런타임에서 AABB 를 못 읽는다. 그래서 프리팹 JSON 이 참조하는 **렌더 메시(.glb)를
직접 로드**해 AABB 를 구하고, 질량은 프리팹의 `mass` 필드를 읽는다. 물리 초기화가
필요 없어 빠르다.

**손 적합성 판정.** DG-5F-M 이 3지 이상으로 감쌀 수 있는 크기인지를 기준으로 나눈다.
근거는 게이트 2 실측이다 — 2.5 cm 블록은 지문이 1~2개만 닿아 **3지 접촉이 기하적으로
성립하지 않았고**, 11.9 cm duck_lamp 에서는 성립했다. 그 사이를 가르는 값으로
완전 폐쇄 시 지문 거리 실측(`[3.4, 4.0, 3.4, 2.3, 5.2] cm`)에서 온 최소 개구폭을 쓴다.

실행 (bash, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/survey_object_assets.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
import rtauto_config as cfg  # noqa: E402

# ⚠️ **실측으로 아는 것은 두 점뿐이다** — 2.5 cm 블록은 3지 접촉이 기하적으로 성립하지
# 않았고(게이트 2), 9.3 cm paper_cup 과 11.9 cm duck_lamp 은 성립했다. 그 사이는
# **아무도 측정하지 않았다.** 그래서 하나의 임계값으로 자르지 않고 **경계 구간**을 둔다.
#   < 2.5 cm  : 불가 (실측 근거 있음)
#   2.5~4.5cm : **미검증** — 실험해야 안다. 여기를 "불가"로 단정하면 shape_box 의
#               12가지 도형을 근거 없이 버리게 된다.
#   >= 4.5 cm : 적합 (실측 근거 있음)
# 4.5 는 완전 폐쇄 시 지문 거리 실측 [3.4, 4.0, 3.4, 2.3, 5.2] cm 에서 온 보수적 하한이다.
KNOWN_FAIL_M = 0.025
MIN_GRASPABLE_M = 0.045
# 상한은 손이 감쌀 수 있는 폭. duck_lamp 최대변 11.9 cm 가 성립한 최대 실측치다.
MAX_GRASPABLE_M = 0.16
# UR16e 가반 16 kg 이지만 게이트 4 에서 마찰 한계가 1.2 kg 부근이었다(쿨롱 한계).
MAX_MASS_KG = 1.2


def load_actor_aabb(prefab_dir: Path, actor: dict):
    """actor 의 AABB [m]. 실패하면 None.

    **충돌 메시(`shape`, `.mochi.h5`)를 우선한다** — rigid·soft 가 같은 형식이라 균일하게
    잴 수 있고, 무엇보다 **물리가 실제로 쓰는 기하**다. 렌더 메시(`renderModel`, .glb)는
    soft actor 에 아예 없어서(duck_lamp 실측) 그것만 보면 주력 물체를 통째로 놓친다.
    `scale` 필드가 있으면 곱한다 — 없다고 가정하면 크기를 잘못 읽는다.
    """
    scale = np.asarray(actor.get("scale", [1.0, 1.0, 1.0]), dtype=float)

    shape = actor.get("shape")
    if shape:
        h5path = (prefab_dir / shape).resolve()
        if h5path.is_file():
            try:
                import h5py
                with h5py.File(h5path, "r") as f:
                    v = np.asarray(f["mesh/coordinates"][:], dtype=float)
                if v.size:
                    return (v.max(0) - v.min(0)) * scale
            except Exception:
                pass

    render = actor.get("renderModel")
    if render:
        gpath = (prefab_dir / render).resolve()
        if gpath.is_file():
            try:
                import trimesh
                m = trimesh.load(str(gpath), force="mesh")
                if m is not None and getattr(m, "bounds", None) is not None:
                    return np.asarray(m.bounds[1] - m.bounds[0], dtype=float) * scale
            except Exception:
                pass
    return None


def verdict(extent, mass):
    """손 적합성. (판정, 사유)"""
    if extent is None:
        return "!", "**측정 실패** — 메시를 읽지 못했다 (분류 불가)"
    lo, hi = float(np.min(extent)), float(np.max(extent))
    if hi > MAX_GRASPABLE_M:
        return "✗", f"최대변 {hi*100:.1f}cm > {MAX_GRASPABLE_M*100:.0f}cm (손보다 크다)"
    if lo <= KNOWN_FAIL_M + 1e-4:   # 부동소수점 여유 — 2.5cm 블록이 경계로 새지 않게
        return "✗", f"최소변 {lo*100:.1f}cm <= {KNOWN_FAIL_M*100:.1f}cm (3지 접촉 불가 — 실측 근거)"
    if lo < MIN_GRASPABLE_M:
        return "?", f"최소변 {lo*100:.1f}cm — **미검증 구간** (2.5~4.5cm, 실험 필요)"
    if mass is not None and mass > MAX_MASS_KG:
        return "△", f"{mass*1000:.0f}g > {MAX_MASS_KG*1000:.0f}g (마찰 한계 초과 가능)"
    return "✓", "적합"


def main():
    ap = argparse.ArgumentParser(description="공식 asset 물체 전수 조사")
    ap.add_argument("--assets", default=None, help="asset 트리 (기본: config 의 값)")
    args = ap.parse_args()

    root = Path(args.assets) if args.assets else cfg.superdex_assets_path()
    if root is None or not Path(root).is_dir():
        sys.exit("asset 트리를 찾지 못했다 — .env 의 RTAUTO_SUPERDEX_REPO 를 확인하라.")
    prefabs = sorted((Path(root) / "prefabs").rglob("*.mochi_prefab"))
    if not prefabs:
        sys.exit(f"프리팹이 없다: {root}/prefabs")

    print(f"asset 트리 : {root}")
    print(f"적합 기준  : 최소변 >= {MIN_GRASPABLE_M*100:.1f}cm, 최대변 <= {MAX_GRASPABLE_M*100:.0f}cm, "
          f"질량 <= {MAX_MASS_KG*1000:.0f}g\n")
    header = f"{'':2s} {'프리팹':46s} {'rigid':>5s} {'크기 (cm)':>22s} {'질량':>9s}  사유"
    print(header)
    print("-" * len(header))

    fits, unknown, failed = [], [], []
    for pf in prefabs:
        spec = json.loads(pf.read_text())
        actors = spec.get("actors", {})
        rel = str(pf.relative_to(Path(root)))
        total = sum(len(v) for v in actors.values())
        kinds = "+".join(f"{k}{len(v)}" for k, v in actors.items()) or "없음"
        print(f"\n■ {rel}   (actor {total}개: {kinds})")
        if not total:
            print("   actor 가 없다 — 설정 전용 프리팹이다.")
            continue

        # ⚠️ actor 종류를 rigid 로 한정하면 안 된다. 게이트 2~4 의 주력 물체
        # duck_lamp 은 **soft(변형체)** 라 rigid 만 보면 통째로 놓친다.
        # 조립 프리팹(shape_box 12조각 등)은 대표 1개가 아니라 **전부** 잰다 —
        # 조각마다 형상이 달라 물체 다양성의 후보가 되기 때문이다.
        for kind, lst in actors.items():
            for a in lst:
                name = a.get("name", "?")
                mass = a.get("mass")
                extent = load_actor_aabb(pf.parent, a)
                v, why = verdict(extent, mass)
                size = ("×".join(f"{x*100:.1f}" for x in extent)
                        if extent is not None else "—")
                ms = f"{mass*1000:.0f} g" if mass is not None else "—"
                print(f"   {v:2s} [{kind:5s}] {name:22s} {size:>20s} {ms:>9s}  {why}")
                key = (tuple(np.round(extent, 4)) if extent is not None else None)
                if v == "✓":
                    fits.append((f"{rel} :: {name} ({kind})", key))
                elif v == "?":
                    unknown.append((f"{rel} :: {name} ({kind})", key))
                elif v == "!":
                    failed.append(f"{rel} :: {name} ({kind})")

    def distinct(items):
        """AABB 가 같은 것은 같은 형상으로 본다 — 복제본이 개수를 부풀리지 않게."""
        seen, out = set(), []
        for label, key in items:
            if key in seen:
                continue
            seen.add(key)
            out.append(label)
        return out

    d_fit, d_unk = distinct(fits), distinct(unknown)
    print(f"\n{'='*80}")
    print(f"적합       : 인스턴스 {len(fits):3d}개 -> **서로 다른 형상 {len(d_fit)}종**")
    for f in d_fit:
        print(f"  ✓ {f}")
    print(f"\n미검증 구간 : 인스턴스 {len(unknown):3d}개 -> **서로 다른 형상 {len(d_unk)}종**")
    for f in d_unk:
        print(f"  ? {f}")

    if failed:
        print(f"\n측정 실패 : {len(failed)}개 — 분류에서 제외했다 (판정이 아니다)")
        for f in failed:
            print(f"  ! {f}")

    print(f"\n{'='*80}\n결론\n{'='*80}")
    print(f"학습에 바로 쓸 수 있는 **서로 다른 형상은 {len(d_fit)}종**이다 "
          "(복제 인스턴스를 접으면 수가 크게 줄어든다 — paper_cup 11개는 모두 같은 컵이다).")
    if d_unk:
        print(f"\n다만 **미검증 구간에 {len(d_unk)}종**이 있다. 특히 shape_box 의 도형들은")
        print("서로 형상이 다르고 크기가 고른(3.8~5.0 cm) 집합이라, 잡히기만 하면")
        print("**물체 다양성 문제를 크게 덜어 준다.** 지금은 크기가 애매할 뿐 불가가 아니다 —")
        print("2.5 cm(실패)와 9.3 cm(성공) 사이는 아무도 측정하지 않았다.")
        print("\n👉 다음 실험: 이 도형들에 오라클/스크립트 파지를 돌려 실제 성립 여부를 본다")
        print("   (superdex/scripts/gate2_oracle_search.py 의 방식). 싸고 결정적이다.")
    if len(d_fit) < 5:
        print("\n그래도 부족하면 외부 물체 셋(YCB 등) 도입을 검토한다 —")
        print("인수인계의 '물체 다양성 확보' 항목이 여기서 막힌다.")


if __name__ == "__main__":
    main()
