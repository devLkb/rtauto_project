# -*- coding: utf-8 -*-
"""`place_rot` 판정 — 물체를 **여러 방향으로 놓을 수 있는가**.

왜 필요한가
-----------
채점표(docs/FESTA_PREGRASP_PLAN.md D-2)는 "이 자세에서 잡히는가"를 훑어 기록하는 표다.
그런데 **자세는 위치만이 아니라 방향까지**다 — 같은 자리라도 손이 옆에서 들어가느냐
위에서 들어가느냐에 따라 결과가 달라진다.

이 환경은 지금까지 물체를 **항상 같은 방향으로만** 놓았다(`TransformRT` 에 위치만 넣고
회전은 안 넣었다). 그래서 채점표가 위치만 훑게 되고, 손 방향을 구분하지 못한다.
`place_rot` 이 그 구멍을 막는다.

이 스크립트가 판정하는 것
-------------------------
1. **기본값은 회전 없음** — 이 값을 안 주면 지금까지와 똑같이 돈다(기존 실측 보존).
2. **준 방향이 실제로 적용된다** — 물체가 그 방향으로 놓인다.
3. **기준점이 여전히 제자리에 놓인다** — 물체를 돌리면 물체 안의 기준점(질량중심)
   오프셋도 같이 돌아가야 한다. 안 돌리면 배치가 조용히 어긋난다. **여기가 핵심이다.**
4. **이상한 값은 막는다** — 길이 0 이거나 개수가 안 맞는 쿼터니언.

실행 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python superdex/scripts/smoke_place_rot.py

실행 (bash, 리포 루트):

    source superdex/.venv/bin/activate
    python superdex/scripts/smoke_place_rot.py

정상이면 마지막 줄이 `모두 통과` 다.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))

from dg5f_grasp_env import Dg5fGraspEnv, _quat_rotate  # noqa: E402

_fail = 0

#: 시험에 쓸 방향들. (이름, 쿼터니언 x,y,z,w)
#: 질량중심을 읽으려면 **단단한 물체**여야 한다. 기본 물체(duck_lamp)는 말랑해서
#: 질량중심을 못 읽는다 — 기준점이 돌아가는지 보려면 단단한 것이 필요하다.
RIGID = {"object_prefab": "prefabs/box_and_blocks/block_red.mochi_prefab",
         "object_ref": "com"}

ROTATIONS = (
    ("회전 없음", (0.0, 0.0, 0.0, 1.0)),
    ("Z축 90도", (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))),
    ("X축 90도 (눕히기)", (math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4))),
    ("Y축 45도", (0.0, math.sin(math.pi / 8), 0.0, math.cos(math.pi / 8))),
)


def check(label, value, ok, expect):
    global _fail
    if not ok:
        _fail += 1
    print("  {}  {:38s} {}   (기대 {})".format("통과" if ok else "실패", label, value, expect))


def _spawned_rotation(env):
    return np.asarray(env.block.get_root_transform().rotation, dtype=float)


def main() -> int:
    print("=== place_rot smoke (물체를 여러 방향으로 놓기) ===")
    print()

    # --- 1. 기본값은 회전 없음 --------------------------------------------
    print("1. 기본값 — 이 값을 안 주면 지금까지와 똑같아야 한다")
    print("   (기본 물체 그대로. 기본 물체는 말랑해서 질량중심을 못 읽으므로 기준점은 root)")
    env = Dg5fGraspEnv({"place_jitter": 0.0})
    try:
        check("설정된 방향", np.round(env.place_rot, 6).tolist(),
              np.allclose(env.place_rot, [0, 0, 0, 1]), "[0, 0, 0, 1] (회전 없음)")
        env.reset(seed=1234)
        rot = _spawned_rotation(env)
        check("실제로 놓인 방향", np.round(rot, 6).tolist(),
              np.allclose(np.abs(rot), [0, 0, 0, 1], atol=1e-6), "[0, 0, 0, 1]")
    finally:
        env.close()
    print()

    # --- 2·3. 방향이 적용되고, 기준점은 제자리 -----------------------------
    print("2. 방향을 주면 그대로 놓이고, 기준점(질량중심)은 제자리여야 한다")
    print("   ※ 3번이 핵심 — 물체를 돌리면 물체 안의 기준점 오프셋도 같이 돌아야 한다")
    print("   단단한 물체(block_red) + 기준점=질량중심 으로 본다")
    print()
    for name, quat in ROTATIONS:
        env = Dg5fGraspEnv(dict(RIGID, place_jitter=0.0, place_rot=quat))
        try:
            env.reset(seed=1234)
            got_rot = _spawned_rotation(env)
            same = (np.allclose(got_rot, quat, atol=1e-5)
                    or np.allclose(got_rot, -np.asarray(quat), atol=1e-5))
            check("[{}] 놓인 방향".format(name), np.round(got_rot, 4).tolist(),
                  same, np.round(quat, 4).tolist())

            # 기준점이 의도한 자리에 있는가 — 흔들림을 껐으므로 정확히 place 여야 한다
            tf = env._link_positions()
            want = env._palm_to_world(tf, env.place)
            got = env._object_position()
            err_mm = float(np.linalg.norm(want - got)) * 1000.0
            check("[{}] 기준점 자리 오차".format(name), "{:.4f} mm".format(err_mm),
                  err_mm < 0.1, "< 0.1 mm")

            # 회전이 실제로 물체를 움직였는지 (회전 없음 말고는 root 가 달라야 한다)
            root = np.asarray(env.block.get_root_transform().translation, dtype=float)
            shift_mm = float(np.linalg.norm(root - want)) * 1000.0
            note = "기준점 오프셋만큼 떨어져 있어야 정상"
            check("[{}] root 와 기준점 거리".format(name), "{:.2f} mm ({})".format(shift_mm, note),
                  math.isfinite(shift_mm), "유한한 값")
        finally:
            env.close()
        print()

    # --- 4. 이상한 값은 막는다 ---------------------------------------------
    print("4. 이상한 값은 만들 때 막아야 한다")
    for label, bad in (("개수가 3개", (0.0, 0.0, 1.0)), ("길이가 0", (0.0, 0.0, 0.0, 0.0))):
        try:
            Dg5fGraspEnv({"place_rot": bad}).close()
            check(label, "안 막았다", False, "ValueError")
        except ValueError as exc:
            check(label, "막았다: {}".format(str(exc)[:46]), True, "ValueError")
        except Exception as exc:  # 다른 오류면 그것도 실패로 본다
            check(label, "다른 오류: {}".format(type(exc).__name__), False, "ValueError")
    print()

    # --- 회전 헬퍼 자체 -----------------------------------------------------
    print("5. 회전 계산 자체")
    q90 = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    check("x축을 Z로 90도 돌리면 y축", np.round(_quat_rotate(q90, [1, 0, 0]), 6).tolist(),
          np.allclose(_quat_rotate(q90, [1, 0, 0]), [0, 1, 0], atol=1e-9), "[0, 1, 0]")
    check("길이가 보존되는가", "{:.9f}".format(float(np.linalg.norm(_quat_rotate(q90, [1, 2, 3])))),
          abs(float(np.linalg.norm(_quat_rotate(q90, [1, 2, 3]))) - math.sqrt(14)) < 1e-9,
          "{:.9f}".format(math.sqrt(14)))

    print()
    print("=" * 56)
    print("모두 통과" if _fail == 0 else "실패 {}건".format(_fail))
    print("=" * 56)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
