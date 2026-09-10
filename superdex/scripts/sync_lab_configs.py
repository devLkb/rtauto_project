# -*- coding: utf-8 -*-
"""SuperDex Lab의 누락된 JSON 설정 파일을 클론에서 설치본으로 복사한다.

**왜 필요한가 (SuperDex 1.0.0 패키징 버그).**
`superdex-lab==1.0.0` wheel에는 `.json` 파일이 **하나도 들어 있지 않다**(실측: 설치본
`superdex/lab` 트리의 json 개수 = 0). 그런데 Lab은 두 종류의 JSON을 모듈 파일 **옆에서**
찾는다:

  - `<env_module>.train.json`      학습 레시피. `train_samples.py`가 이걸로 학습 가능한
                                   환경을 discover한다 — 없으면 "No samples to train"
  - `<env_module>_<variant>.json`  gym config variant (예: `ant_env_no_contact.json`)

`load_env_config()`가 `inspect.getfile(env_cls)` 옆을 보기 때문에, 파일이 클론에만 있고
설치본에 없으면 **공식 RL 워크플로가 wheel만으로는 전혀 돌지 않는다.**

이 스크립트는 클론의 `superdex_lab/superdex/lab/**/*.json`을 설치본의 같은 상대 경로로
복사해 그 간극을 메운다. wheel 버전 핀은 그대로 유지한다(`pip install -e`로 소스 설치를
하지 않는 이유 — docs/SUPERDEX_POC_PLAN.md §9 R3).

상위 버전에서 패키징이 고쳐지면 이 스크립트는 no-op이 된다(복사할 것이 없거나 이미 동일).

실행 (터미널 1, PowerShell, 리포 루트, superdex/.venv 활성):
    python superdex/scripts/sync_lab_configs.py
    python superdex/scripts/sync_lab_configs.py --check   # 복사하지 않고 상태만 본다
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로의 유일한 출처 — 원칙 1)


def installed_lab_dir() -> Path:
    """설치된 superdex.lab 패키지 디렉터리."""
    import importlib.util

    spec = importlib.util.find_spec("superdex.lab")
    if spec is None or not spec.origin:
        sys.exit("superdex.lab 을 import할 수 없다 — superdex/.venv 가 활성인지 확인할 것.")
    return Path(spec.origin).parent


def clone_lab_dir() -> Path:
    """클론 안의 superdex/lab 소스 디렉터리."""
    repo = (cfg.SUPERDEX_REPO or "").strip()
    if not repo:
        sys.exit(
            "RTAUTO_SUPERDEX_REPO 가 .env에 없다 — docs/SUPERDEX_POC_PLAN.md §11 0-5 참고."
        )
    src = Path(repo) / "superdex_lab" / "superdex" / "lab"
    if not src.is_dir():
        sys.exit(f"클론에서 Lab 소스를 못 찾았다: {src}")
    return src


def main() -> None:
    ap = argparse.ArgumentParser(description="SuperDex Lab JSON 설정 동기화")
    ap.add_argument("--check", action="store_true", help="복사하지 않고 차이만 보고한다")
    args = ap.parse_args()

    src_root, dst_root = clone_lab_dir(), installed_lab_dir()
    print(f"클론  : {src_root}")
    print(f"설치본: {dst_root}")

    jsons = sorted(src_root.rglob("*.json"))
    if not jsons:
        print("클론에 json이 없다 — 이 버전은 패키징이 다를 수 있다. 확인 필요.")
        return

    copied = same = 0
    for src in jsons:
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
            same += 1
            continue
        if args.check:
            print(f"  [누락/차이] {rel}")
            copied += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  복사 {rel}")
        copied += 1

    print()
    verb = "복사 필요" if args.check else "복사됨"
    print(f"{verb}: {copied}개 / 이미 동일: {same}개 / 클론 총 json: {len(jsons)}개")
    if copied and not args.check:
        print("\n이제 학습 레시피가 discover된다. 확인:")
        print("  python superdex/scripts/sync_lab_configs.py --check")


if __name__ == "__main__":
    main()
