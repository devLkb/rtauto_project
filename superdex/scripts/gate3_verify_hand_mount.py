# -*- coding: utf-8 -*-
"""게이트 3 마무리 — 손 장착 회전(`SUPERDEX_HAND_MOUNT_QUAT`)이 맞는가.

이 항목은 게이트 3의 다른 판정으로는 **절대 걸리지 않는다.** 손이 플랜지 축으로 180°
돌아가 붙어도 자기접촉은 0이고, 관절 한계는 그대로이고, 시뮬도 안정적이다. 그런데
파지 정책 입장에서는 완전히 다른 로봇이다.

"눈으로 보라"고 미뤄 뒀던 항목인데, **눈으로도 잘 안 걸린다** — 오른손이 180° 돌아가
붙어도 여전히 오른손으로 보인다. 그래서 수치로 판정한다.

## 판정 방법 — 정본과 대조한다

우리에게는 이미 **손 장착의 정본**이 있다: 결합 URDF(`ur16e_dg5f_<hand>.urdf`)의
`tool0_to_dg_mount` 조인트다(parent `tool0`, origin identity). 이 URDF 는 SuperDex
도입 전부터 이 프로젝트의 로봇 정의였다.

그래서 **같은 것을 두 경로로 만들어 손 자세를 비교**한다:

| | 팔 | 손 | 장착 |
|---|---|---|---|
| A 결합 bot | Studio 에서 구운 asset | **공식 Tesollo baked asset** | `SUPERDEX_HAND_MOUNT_QUAT` |
| B 결합 URDF (정본) | 우리 URDF | 우리 DG5F 메시 | `tool0_to_dg_mount` (identity) |

두 경로에서 **`tool0` 좌표계로 표현한 손바닥·엄지끝·검지끝의 위치와 손바닥 축**이 같으면
장착 회전이 정본과 일치하는 것이다. 180° 오차가 있으면 축 부호가 뒤집혀 바로 드러난다.

> 두 손은 서로 다른 파일(공식 baked asset vs 우리 URDF 메시)이므로 완전히 같을 이유는
> 없다. 실제로 일치한다면 두 모델이 같은 원본에서 나왔다는 교차 검증도 된다.

## 실행

터미널 1 (PowerShell, 리포 루트, **superdex/.venv 활성화 필수**):

```powershell
superdex/.venv/Scripts/Activate.ps1
python -u superdex/scripts/gate3_verify_hand_mount.py
```

bash (Linux/WSL2, 리포 루트):

```bash
source superdex/.venv/bin/activate
python -u superdex/scripts/gate3_verify_hand_mount.py
```

출력 마지막 `=== 손 장착 회전:` 줄이 결론이다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtauto_config as cfg  # noqa: E402  (경로·로봇 구성의 유일한 출처 — 원칙 1)

# 선행 검증 2 가 asset 경로 환경변수 설정과 superdex import 를 해 준다.
import gate3_verify_combined_urdf as g3urdf  # noqa: E402,F401

import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402

# 비교할 링크. 결합 bot 은 `dg5f_link_*`, 결합 URDF 는 `<접두사>dg_*` 를 쓴다
# (접두사는 손 방향에 따라 rl_/ll_ — cfg.dg5f_link_prefix()).
#   palm  : 손바닥. 장착 지점 바로 다음이라 회전 오차가 그대로 드러난다
#   thumb : 1번 손가락 끝. 180° 오차에 가장 민감하다
#   index : 2번 손가락 끝
_PROBE_LINKS = ("palm", "1_tip", "2_tip")


def _quat_to_R(q) -> np.ndarray:
    x, y, z, w = (float(v) for v in q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def hand_pose_in_tool0(prefab, suffixes: dict[str, str]) -> dict[str, np.ndarray]:
    """베이스를 용접한 홈 자세에서 `tool0` 좌표계로 표현한 손 기하."""
    prefab.joints[0].type = physics.ArticulatedJointType.HARD
    scene = physics.create_scene("hand_mount_cmp")
    ctx = robotics.create_context()
    bot = robotics.create_bot(scene, prefab, ctx)
    actor = bot.get_articulated_actor()

    names = [prefab.links[i].name for i in range(len(prefab.links))]
    tf = physics.DynamicArrayTransformRT(len(names))
    actor.get_articulated_link_transforms(tf)

    def find(suffix: str) -> int:
        idx = next((i for i, n in enumerate(names) if n.endswith(suffix)), None)
        if idx is None:
            sys.exit(f"링크를 찾지 못했다: *{suffix}\n실제 링크: {names}")
        return idx

    i_tool0 = find("tool0")
    R0 = _quat_to_R(tf[i_tool0].rotation)
    t0 = np.array([float(v) for v in tf[i_tool0].translation])

    out: dict[str, np.ndarray] = {}
    for key, suffix in suffixes.items():
        i = find(suffix)
        R = _quat_to_R(tf[i].rotation)
        t = np.array([float(v) for v in tf[i].translation])
        out[f"{key}_pos"] = R0.T @ (t - t0)
        if key == "palm":
            # 손바닥 좌표축을 tool0 기준으로. 180° 오차는 여기서 부호로 드러난다.
            out["palm_axis_x"] = R0.T @ R[:, 0]
            out["palm_axis_z"] = R0.T @ R[:, 2]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="손 장착 회전 판정")
    ap.add_argument("--tol", type=float, default=1e-3,
                    help="위치[m]·축 성분의 허용 오차")
    args = ap.parse_args()

    combo = cfg.SUPERDEX_OUR_ASSETS_DIR / cfg.superdex_combo_asset()
    urdf = (
        REPO_ROOT / "urdf" / f"{cfg.UR_TYPE}_dg5f_{cfg.DG5F_HAND}_build"
        / f"{cfg.UR_TYPE}_dg5f_{cfg.DG5F_HAND}.urdf"
    )
    for p in (combo, urdf):
        if not p.is_file():
            sys.exit(f"파일이 없다: {p}")

    print(f"A 결합 bot  : {combo.name}   (구운 팔 + 공식 손)")
    print(f"B 결합 URDF : {urdf.name}   (정본 마운트 tool0_to_dg_mount)")
    print(f"현재 장착 회전 (x,y,z,w) = {cfg.SUPERDEX_HAND_MOUNT_QUAT}")
    print()

    physics.initialize(num_worker_threads=0)
    prefix = cfg.dg5f_link_prefix()  # 'rl_' / 'll_'
    A = hand_pose_in_tool0(
        robotics.load_bot_prefab_from_file(str(combo)),
        {"palm": "dg5f_link_palm", "thumb": "dg5f_link_1_tip",
         "index": "dg5f_link_2_tip"},
    )
    B = hand_pose_in_tool0(
        robotics.load_bot_prefab_from_urdf_file(str(urdf)),
        {"palm": f"{prefix}dg_palm", "thumb": f"{prefix}dg_1_tip",
         "index": f"{prefix}dg_2_tip"},
    )

    keys = ["palm_pos", "thumb_pos", "index_pos", "palm_axis_x", "palm_axis_z"]
    worst = 0.0
    print(f"{'항목':<12} {'A 결합 bot':<26} {'B 정본 URDF':<26} 차이")
    for k in keys:
        d = float(np.abs(A[k] - B[k]).max())
        worst = max(worst, d)
        print(f"{k:<12} {str(np.round(A[k], 4).tolist()):<26} "
              f"{str(np.round(B[k], 4).tolist()):<26} {d:.2e}")

    print()
    print("=" * 72)
    if worst <= args.tol:
        print(f"=== 손 장착 회전: 통과 — 정본과 일치 (최대 차이 {worst:.2e}) ===")
        print("    SUPERDEX_HAND_MOUNT_QUAT 가 결합 URDF 의 tool0_to_dg_mount 와 같은")
        print("    자세로 손을 붙인다. 눈이 아니라 수치로 확인된 값이다.")
        return
    print(f"=== 손 장착 회전: 불일치 (최대 차이 {worst:.2e}) ===")
    print("    SUPERDEX_HAND_MOUNT_QUAT 를 고쳐야 한다. 축 부호가 뒤집혀 있으면")
    print("    플랜지 축 180° 오차다 — .env 의 RTAUTO_SUPERDEX_HAND_MOUNT_QUAT 로 준다.")
    sys.exit(1)


if __name__ == "__main__":
    main()
