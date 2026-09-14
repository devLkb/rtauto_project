# -*- coding: utf-8 -*-
"""공식 asset 트리의 파지 대상 후보를 전수 조사한다 — 크기·질량·손 적합성.

**왜 필요한가.** 프로젝트 최종 목적이 범용 파지로 바뀐 뒤(로드맵 v17) 성공 조건이
"학습하지 않은 물체로 넘어가는 것"이 됐다. 그런데 게이트 4 에서 쓴 물체는 4종뿐이고
그중 손 크기에 맞는 것은 `duck_lamp`·`paper_cup` 둘이었다 — **물체 확보 자체가 작업**이라고
인수인계에 적힌 이유다. 무엇이 있는지부터 수치로 알아야 한다.

**어떻게 재는가.** 프리팹 JSON 이 참조하는 **충돌 메시(`.mochi.h5`)를 직접 읽어**
AABB 를 구하고(없으면 렌더 메시 .glb), 질량은 프리팹의 `mass` 필드를 읽는다. 물리
초기화가 필요 없어 빠르다.

> 정정 (2026-09-11): 예전 이 자리에 "rigid actor 는 런타임에서 AABB 를 못 읽는다"고
> 적었는데 **틀렸다** — `actor.get_aabb_local()` 과 `get_rigid_center_of_mass_local()` 이
> 런타임에서 그대로 읽힌다(block_red·paper_cup·shape_box 조각 실측). 파일에서 읽는
> 방식을 유지하는 이유는 속도다(물리 초기화 불필요).

**손 적합성 판정.** DG-5F-M 이 3지 이상으로 감쌀 수 있는 크기인지를 기준으로 나눈다.
기준은 **오라클 스윕 실측**이다(`object_oracle_sweep.py`, 2026-09-14) — 최대변 4.0 cm 인
shape_box 도형 12종이 전부 잡혔고(8~10/10 시드), 최대변 2.5 cm 블록은 6/10 으로 경계였다.

> 갱신 (2026-09-14): 예전 기준은 **최소변 4.5 cm** 였는데 실측이 뒤집었다 — `rectangle`
> 은 최소변 **2.7 cm** 인데 9/10 으로 잡힌다. 얇아도 다른 축이 4 cm 면 3지가 닿기
> 때문이다. 그래서 판정을 **최대변** 기준으로 바꾸고, 최소변에는 실측 하한 2.7 cm 만 건다.

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

# 판정 기준은 **최대변**이다 (2026-09-14 오라클 스윕 실측으로 교체).
#   최대변 < 2.5 cm  : 불가 — 이 크기는 지문이 1~2개만 닿는다
#   2.5 ~ 4.0 cm     : **미검증** — 2.5 는 6/10(경계), 4.0 은 전부 성립. 사이는 안 쟀다
#   >= 4.0 cm        : 적합 — shape_box 도형 12종이 8~10/10 으로 잡혔다
# 최소변에는 실측 하한만 건다: rectangle 은 최소변 2.7 cm 인데 9/10 으로 잡힌다.
# ⚠️ 예전 기준(최소변 4.5 cm)을 그대로 두면 그 12종이 전부 "미검증"으로 남아 실측과
# 어긋난다. 4.5 는 지문 거리 실측에서 온 추정값이었고, 이제 직접 잰 값이 있다.
KNOWN_FAIL_M = 0.025
MIN_SIDE_OK_M = 0.027
MIN_GRASPABLE_M = 0.040
# 지문 두께보다 얇은 것은 3지 접촉을 만들 수 없다고 본다. ⚠️ 이 값만은 **실측이 아니라
# 추정**이다(chain 0.2 cm, 9-hole peg 0.6 cm 를 미검증 목록에서 걸러내기 위한 것).
# 판정 사유 문자열에도 "추정"이라고 적어 실측 근거와 섞이지 않게 한다.
THIN_FAIL_M = 0.010

# `object_oracle_sweep.py` (2026-09-14) 로 **실제로 재 본** 물체. 크기 기준만 통과한 것과
# 반드시 구분해 표시한다 — 임계값을 실측에 맞춰 낮추면 **재보지도 않은 물체가 조용히
# "적합"으로 승격**된다. 실제로 9홀 페그 보드(12.5×12.5×4.0 cm)가 그렇게 올라왔다.
MEASURED = dict(
    {n: "실측 8~10/10 시드" for n in (
        "cross", "triangle", "square", "trapezoid", "rectangle", "pentagon",
        "parallelogram", "octagon", "hexagon", "ellipse", "diamond", "star")},
    DuckLamp="실측 10/10 시드 (대조군)",
    Block_red="실측 6/10 시드 — 경계, 배치에 민감",
)
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
    # ⚠️ 임계값이 **실측값과 같은 숫자**이므로 비교에 여유(0.1 mm)를 준다. 충돌 메시의
    # AABB 는 4.0 cm 를 3.99998 로 주기도 해서, 여유가 없으면 실측으로 잡힌 도형
    # (cross·rectangle·parallelogram·octagon)이 그대로 "미검증"으로 샌다. 실제로 샜다.
    eps = 1e-4
    if hi > MAX_GRASPABLE_M:
        return "✗", f"최대변 {hi*100:.1f}cm > {MAX_GRASPABLE_M*100:.0f}cm (손보다 크다)"
    if hi <= KNOWN_FAIL_M + eps:
        return "✗", f"최대변 {hi*100:.1f}cm <= {KNOWN_FAIL_M*100:.1f}cm (지문이 1~2개만 닿는다)"
    if lo < THIN_FAIL_M:
        return "✗", f"최소변 {lo*100:.1f}cm < {THIN_FAIL_M*100:.1f}cm (지문보다 얇다 — **추정**, 미실측)"
    if hi < MIN_GRASPABLE_M - eps:
        return "?", f"최대변 {hi*100:.1f}cm — **미검증 구간** (2.5~4.0cm, 실험 필요)"
    if lo < MIN_SIDE_OK_M - eps:
        return "?", f"최소변 {lo*100:.1f}cm < 실측 하한 {MIN_SIDE_OK_M*100:.1f}cm — **미검증**"
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
                if name in MEASURED:
                    why = f"{why} · **{MEASURED[name]}**"
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
    n_measured = sum(1 for f in d_fit if any(f" :: {n} (" in f for n in MEASURED))
    print(f"크기 기준을 통과한 **서로 다른 형상은 {len(d_fit)}종**이다 "
          "(복제 인스턴스를 접으면 수가 크게 줄어든다 — paper_cup 11개는 모두 같은 컵이다).")
    print(f"그중 **실제로 잡아 본 것은 {n_measured}종**이고, 나머지 {len(d_fit) - n_measured}종은 "
          "**크기 기준만 통과**했다 — 미실측이다.")
    print("⚠️ 이 둘을 섞어 세지 마라. 임계값은 실측에서 왔지만, 임계값 통과가 실측은 아니다.")
    print("\n이 표의 크기 임계값은 **2026-09-14 오라클 스윕 실측**에서 왔다 —")
    print("shape_box 도형 12종이 8~10/10 시드로 잡혔다 (superdex/scripts/object_oracle_sweep.py).")
    if d_unk:
        print(f"\n**미검증 구간에 {len(d_unk)}종**이 남아 있다. 크기가 애매할 뿐 불가가 아니다 —")
        print("잡히는 쪽으로 아는 것은 최대변 4.0 cm(도형 12종)이고, 어려운 쪽으로 아는 것은")
        print("최대변 2.5 cm(block_red, 배치를 넓혀도 6/10)이다. 그 사이는 아직 아무도 안 쟀다.")
        print("\n👉 재려면: object_oracle_sweep.py 에 대상을 추가해 같은 방식으로 돌린다.")
    if len(d_fit) < 5:
        print("\n적합 형상이 5종 미만이면 외부 물체 셋(YCB 등) 도입을 검토한다 —")
        print("인수인계의 '물체 다양성 확보' 항목이 여기서 막힌다.")


if __name__ == "__main__":
    main()
