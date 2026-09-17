# -*- coding: utf-8 -*-
"""짝짓기 — 점 덩어리와 "좋은 자세" 를 한 줄로 묶는다 (D-4 의 재료 만들기).

무엇을 만드는가
---------------
예측기(D-4)를 가르치려면 `입력 -> 정답` 짝이 있어야 한다.

- **입력**: 카메라가 본 점 덩어리 (D-3 이 만든다)
- **정답**: 그 물체에서 잡히는 자세들 (D-2 채점표가 준다)

지금까지 이 둘은 **따로 놀고 있었다.** 이 스크립트가 같은 장면에서 둘을 뽑아 묶는다.

⚠️ 예측기에 넣으면 안 되는 것
------------------------------
[`docs/FESTA_PREGRASP_PLAN.md`](../../docs/FESTA_PREGRASP_PLAN.md) **§7-3**:
예측기는 **점 덩어리만** 봐야 한다. 시뮬레이터만 아는 값(손가락 몇 개 닿았나, 얼마나
미끄러졌나, 물체가 정확히 어디 있나)은 **정답지를 만드는 데만** 쓰고 입력에 넣지 않는다.

그래서 이 파일이 저장하는 것도 **입력 쪽은 점 좌표뿐**이다. 확인하는 시험이
`superdex/scripts/test_pose_dataset.py` 에 있다.

좌표 기준 — 둘을 같은 자리에서 재는 것이 핵심
----------------------------------------------
점 덩어리와 자세를 **같은 좌표 기준**으로 적지 않으면 짝이 어긋난다. 여기서는 둘 다
**물체 기준**으로 적는다:

- 점 덩어리: 물체의 원점·방향을 기준으로 한 점들
- 자세: 물체 기준으로 **손바닥이 어디에 어떤 방향으로** 있어야 하는가

이렇게 하면 물체를 어디에 놓든 같은 정답이 된다. 그리고 **관계는 설정값에서 다시
계산하지 않고 시뮬레이터에서 직접 읽는다** — 설정값에서 되짚으면 좌표 기준을 헷갈릴
여지가 생기는데, 시뮬레이터가 실제로 놓은 결과를 읽으면 그럴 일이 없다.

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/build_pose_dataset.py --table superdex/results/pose_score_first.json

결과는 `superdex/results/pose_dataset_<시각>.npz`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402

from pose_score_sweep import OBJECTS  # noqa: E402  (물체 목록의 정본은 그쪽 하나)
from synth_pointcloud import (  # noqa: E402
    depth_to_points, look_at, quat_to_matrix, render_depth, surface_triangles,
)

RESULTS_DIR = REPO_ROOT / "superdex" / "results"


def _transform_matrix(transform):
    """physics 의 TransformRT → 4x4."""
    out = np.eye(4)
    out[:3, :3] = quat_to_matrix(transform.rotation)
    out[:3, 3] = np.asarray(transform.translation, dtype=np.float64)
    return out


def _invert(mat):
    out = np.eye(4)
    out[:3, :3] = mat[:3, :3].T
    out[:3, 3] = -mat[:3, :3].T @ mat[:3, 3]
    return out


def _matrix_to_quat(rot):
    """3x3 → 쿼터니언 (x, y, z, w). physics 표기와 같은 순서."""
    trace = float(np.trace(rot))
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (rot[2, 1] - rot[1, 2]) / s
        y = (rot[0, 2] - rot[2, 0]) / s
        z = (rot[1, 0] - rot[0, 1]) / s
    else:
        i = int(np.argmax(np.diag(rot)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + rot[i, i] - rot[j, j] - rot[k, k]) * 2
        q = [0.0, 0.0, 0.0]
        q[i] = 0.25 * s
        q[j] = (rot[j, i] + rot[i, j]) / s
        q[k] = (rot[k, i] + rot[i, k]) / s
        w = (rot[k, j] - rot[j, k]) / s
        x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    return np.array([x / n, y / n, z / n, w / n])


def viewpoints(count):
    """물체를 둘러싼 카메라 자리들. 물체 기준 단위벡터로.

    실제 카메라는 손목에 달려 팔 자세에 따라 여기저기서 본다. 한 방향에서만 배우면
    그 방향에서만 쓸 수 있으므로 여러 방향을 만든다.
    """
    out = []
    golden = math.pi * (3.0 - math.sqrt(5.0))   # 고르게 흩뿌리기
    for i in range(count):
        z = 1.0 - (2.0 * i + 1.0) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden * i
        out.append((r * math.cos(theta), r * math.sin(theta), z))
    return np.asarray(out, dtype=np.float64)


def cloud_in_object_frame(env, view_dir, standoff, width, height, fov):
    """카메라를 `view_dir` 쪽에 두고 본 **물체 점만**, 물체 기준 좌표로."""
    t_world_obj = _transform_matrix(env.block.get_root_transform())
    center = env._object_position()
    cam_pos = center + np.asarray(view_dir, dtype=np.float64) * standoff
    cam_rot = look_at(cam_pos, center)

    got = surface_triangles(env.block, env.block.get_root_transform())
    if got is None:
        return np.zeros((0, 3), dtype=np.float32)
    verts, tris = got
    labels = np.full(len(tris), "object", dtype=object)
    depth, who = render_depth(verts, tris, labels, cam_rot, cam_pos, width, height, fov)
    pts_world, _ = depth_to_points(depth, who, cam_rot, cam_pos, fov)
    if len(pts_world) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    inv = _invert(t_world_obj)
    pts_obj = pts_world @ inv[:3, :3].T + inv[:3, 3]
    return pts_obj.astype(np.float32)


def palm_pose_in_object_frame(env):
    """지금 놓인 상태에서 **물체 기준 손바닥 자세**. 시뮬레이터에서 직접 읽는다."""
    tf = env._link_positions()
    t_world_palm = _transform_matrix(tf[env.palm_idx])
    t_world_obj = _transform_matrix(env.block.get_root_transform())
    t_obj_palm = _invert(t_world_obj) @ t_world_palm
    return t_obj_palm[:3, 3], _matrix_to_quat(t_obj_palm[:3, :3])


def main() -> int:
    ap = argparse.ArgumentParser(description="점 덩어리 + 좋은 자세 짝짓기 (D-4 재료)")
    ap.add_argument("--table", required=True, help="D-2 가 만든 채점표 json")
    ap.add_argument("--views", type=int, default=12, help="물체당 카메라 방향 수")
    ap.add_argument("--standoff", type=float, default=0.18, help="카메라 거리(m)")
    ap.add_argument("--good-rate", type=float, default=0.99,
                    help="이 이상이면 '좋은 자세' 로 본다")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    table = json.loads(Path(args.table).read_text(encoding="utf-8"))
    rows = table.get("rows", [])
    if not rows:
        print("빈 채점표다: {}".format(args.table))
        return 2

    by_object = {}
    for r in rows:
        by_object.setdefault(r["object"], []).append(r)

    width, height = cfg.D405_SYNTH_WIDTH, cfg.D405_SYNTH_HEIGHT
    fov = cfg.D405_FOV_H_DEG
    dirs = viewpoints(args.views)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / "pose_dataset_{}.npz".format(time.strftime("%Y%m%d_%H%M%S")))

    print("=== 짝짓기 (D-4 재료) ===")
    print("채점표   : {} (물체 {}종)".format(args.table, len(by_object)))
    print("카메라   : 방향 {}개, 거리 {:.2f} m, 시야 {:.0f}도, {}x{}".format(
        len(dirs), args.standoff, fov, width, height))
    print("좋은 자세 기준: 성공률 {:.0%} 이상".format(args.good_rate))
    print()

    from dg5f_grasp_env import Dg5fGraspEnv

    clouds, cloud_start, cloud_object = [], [0], []
    pose_pos, pose_quat, pose_rate, pose_object = [], [], [], []

    for name, obj_rows in by_object.items():
        prefab, actor, ref = OBJECTS[name]
        config = {"object_prefab": prefab, "object_ref": ref, "place_jitter": 0.0}
        if actor:
            config["object_actor"] = actor
        env = Dg5fGraspEnv(config)
        try:
            # --- 정답: 좋은 자세들을 물체 기준으로 ---------------------------
            good = 0
            for r in obj_rows:
                env.place = np.asarray(r["place"], dtype=float)
                env.place_rot = np.asarray(r["place_rot"], dtype=float)
                env.reset(seed=1234)
                pos, quat = palm_pose_in_object_frame(env)
                pose_pos.append(pos)
                pose_quat.append(quat)
                pose_rate.append(float(r["rate"]))
                pose_object.append(name)
                good += int(r["rate"] >= args.good_rate)

            # --- 입력: 여러 방향에서 본 점 덩어리 ----------------------------
            env.place = np.asarray(obj_rows[0]["place"], dtype=float)
            env.place_rot = np.asarray(obj_rows[0]["place_rot"], dtype=float)
            env.reset(seed=1234)
            sizes = []
            for d in dirs:
                pts = cloud_in_object_frame(env, d, args.standoff, width, height, fov)
                clouds.append(pts)
                cloud_start.append(cloud_start[-1] + len(pts))
                cloud_object.append(name)
                sizes.append(len(pts))
            print("  [{}] 자세 {}개(좋은 것 {}개) / 점 덩어리 {}장, 점 {}~{}개".format(
                name, len(obj_rows), good, len(dirs),
                min(sizes) if sizes else 0, max(sizes) if sizes else 0), flush=True)
        finally:
            env.close()
            try:
                import superdex.physics as physics
                physics.destroy_scene(env.scene)
            except Exception:
                pass

    all_points = (np.concatenate(clouds) if clouds
                  else np.zeros((0, 3), dtype=np.float32))
    np.savez_compressed(
        out_path,
        points=all_points,
        cloud_start=np.asarray(cloud_start, dtype=np.int64),
        cloud_object=np.asarray(cloud_object),
        pose_pos=np.asarray(pose_pos, dtype=np.float32),
        pose_quat=np.asarray(pose_quat, dtype=np.float32),
        pose_rate=np.asarray(pose_rate, dtype=np.float32),
        pose_object=np.asarray(pose_object),
        frame=np.asarray("object"),
        made_from=np.asarray(str(args.table)),
    )

    print()
    print("=" * 60)
    print("점 덩어리 {}장 (점 {}개), 자세 {}개".format(
        len(cloud_object), len(all_points), len(pose_object)))
    good_total = int((np.asarray(pose_rate) >= args.good_rate).sum())
    print("그중 좋은 자세 {}개 ({:.0f}%)".format(
        good_total, 100.0 * good_total / max(1, len(pose_rate))))
    print("좌표 기준: 물체 기준 (점 덩어리·자세 둘 다)")
    print("저장: {}".format(out_path))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
