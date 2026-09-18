# -*- coding: utf-8 -*-
"""**찾을 말을 모델에 구워 넣는다** — 시연 노트북에서 242 MB 를 안 받게.

왜 필요한가
-----------
YOLOE 는 "cup", "can" 같은 **글자로 무엇을 찾을지** 알려 주는 방식이다. 그런데 글자를
이해하려면 별도 모델(`mobileclip2_b.ts`, **242 MB**)이 필요하다.

그 일은 **미리 한 번만** 하면 된다. 결과를 모델 파일에 구워 두면 쓸 때는 글자 모델이
필요 없다. **시연장엔 노트북과 로봇만 가져가므로** 이게 중요하다.

돌리는 법 (인터넷이 되는 개발 PC 에서 한 번만)
----------------------------------------------
터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/make_ready.py

찾을 물체를 바꾸려면 `yolo_assist.py` 의 `PROMPT_WORDS` 를 고치고 다시 돌린다.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from yolo_assist import DEFAULT_WEIGHTS, PROMPT_WORDS  # noqa: E402

BASE = "yoloe26-n-seg.pt"          # 글자를 받아들이는 원본


def main() -> int:
    from ultralytics import YOLOE

    here = REPO_ROOT / "vision" / "d405" / "weights"
    here.mkdir(parents=True, exist_ok=True)
    src = here / BASE
    if not src.exists():
        print("원본이 없다: {}".format(src))
        print("huggingface 에서 받을 것: openvision/yoloe26-n-seg 의 model.pt")
        return 2

    words = list(PROMPT_WORDS)
    print("찾을 말 {}개를 구워 넣는다: {}".format(len(words), ", ".join(words)))
    print("(이때만 글자 모델 242 MB 가 필요하다 — 인터넷이 있어야 한다)")
    m = YOLOE(str(src))
    m.set_classes(words, m.get_text_pe(words))
    out = here / DEFAULT_WEIGHTS
    m.save(str(out))
    print()
    print("저장: {}  ({:.1f} MB)".format(out, out.stat().st_size / 1e6))
    print("이제 시연 노트북에는 **이 파일만** 있으면 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
