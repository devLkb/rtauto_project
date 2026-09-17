# -*- coding: utf-8 -*-
"""점 덩어리 합성 — 카메라가 볼 법한 점만 만들어 낸다 (D-3).

무엇을 만드는가
---------------
시뮬레이터 안의 물체·손 표면에서, **한 위치의 카메라에서 실제로 보이는 점만** 골라
3차원 점 덩어리를 만든다. 실제 3D 카메라(D405)가 내놓는 것과 같은 성격이어야 한다:

- **뒷면은 안 보인다** — 물체 반대편 표면은 빠진다
- **가린 것은 안 보인다** — 손가락이 앞을 막으면 그 뒤는 빠진다
- **한쪽에서만 본다** — 물체 전체 모양이 아니라 보이는 조각만 나온다

왜 필요한가
-----------
"보이는 모양 → 좋은 자세" 를 배우려면(D-4), 배울 때 쓰는 입력이 **실제 카메라가 주는
것과 닮아야** 한다. 물체의 완전한 모양을 넣고 배우면, 실물에서 반쪽만 보이는 순간
못 쓰게 된다.

[`docs/FESTA_PREGRASP_PLAN.md`](../../docs/FESTA_PREGRASP_PLAN.md) §9 가 이걸 **이 길의
최대 미검증 항목**으로 적어 뒀다 — 표면 메시가 나온다는 것까지만 확인됐고, 실제로
"카메라가 볼 법한" 점이 나오는지는 아무도 안 해 봤다.

어떻게 만드는가
---------------
깊이 렌더러(그림을 그려 주는 부품)가 이 물리 엔진에는 없다. 대신 **직접 그린다**:

1. 물체·손의 표면 삼각형을 세계 좌표로 옮긴다
2. 카메라 눈에서 본 좌표로 바꾸고, 사진 격자에 삼각형을 칠한다
3. 한 칸에 여러 개가 겹치면 **가장 가까운 것만 남긴다** (뒷면·가린 것이 자동으로 빠진다)
4. 남은 격자 칸을 다시 3차원 점으로 되돌린다

3번이 핵심이다 — 이 한 줄이 "뒷면 빼기" 와 "가림" 을 한꺼번에 해결한다.

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/synth_pointcloud.py

`--save-npz <파일>` 로 점 덩어리를 저장하고, `--preview <파일.png>` 로 그림을 남긴다.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))

import rtauto_config as cfg  # noqa: E402  (환경이 asset 경로를 여기서 읽고, 카메라 값도 여기서 온다)

#: 카메라 값은 **전부 config 에서 온다**(원칙 1). 여기에 숫자를 적지 않는다.
#: ⚠️ 그 값들은 아직 **제조사 사양이고 실측이 아니다** — 카메라가 도착하면 재서 고친다.
NEAR_M = cfg.D405_NEAR_M
FAR_M = cfg.D405_FAR_M


# ---------------------------------------------------------------------------
# 작은 회전 도구
# ---------------------------------------------------------------------------
def quat_to_matrix(quat):
    """쿼터니언 (x, y, z, w) → 3x3 회전. physics 쪽 표기와 같은 순서다."""
    x, y, z, w = (float(v) for v in quat)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def look_at(eye, target, up=(0.0, 0.0, 1.0)):
    """카메라를 `eye` 에 두고 `target` 을 보게 하는 회전(3x3).

    카메라 좌표 규약: **z 가 보는 방향**, x 가 오른쪽, y 가 아래. 흔한 사진 규약이다.
    """
    eye = np.asarray(eye, dtype=np.float64)
    forward = np.asarray(target, dtype=np.float64) - eye
    n = np.linalg.norm(forward)
    if n < 1e-9:
        raise ValueError("카메라 자리와 보는 곳이 같다 — 방향을 정할 수 없다")
    forward = forward / n
    up = np.asarray(up, dtype=np.float64)
    if abs(float(np.dot(up, forward))) > 0.999:      # 위쪽과 보는 방향이 나란하면
        up = np.array([0.0, 1.0, 0.0])               # 다른 위쪽을 쓴다
    right = np.cross(forward, up)
    right = right / np.linalg.norm(right)
    down = np.cross(forward, right)
    return np.stack([right, down, forward], axis=0)  # world -> camera


# ---------------------------------------------------------------------------
# 표면 모으기
# ---------------------------------------------------------------------------
def surface_triangles(actor, transform):
    """actor 하나의 표면 삼각형을 **세계 좌표**로. 못 읽으면 None."""
    try:
        mesh = actor.get_surface_mesh()
    except Exception:
        return None
    verts = np.asarray(mesh.coordinates, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(mesh.connectivity, dtype=np.int64).reshape(-1, 3)
    if len(verts) == 0 or len(tris) == 0:
        return None
    rot = quat_to_matrix(transform.rotation)
    pos = np.asarray(transform.translation, dtype=np.float64)
    return (verts @ rot.T + pos), tris


def scene_triangles(env, include_hand=True):
    """환경에서 물체(+손끝) 표면을 모아 `(정점, 삼각형, 이름표)` 로.

    이름표는 그 삼각형이 무엇의 표면인지 — 나중에 "물체 점만" 골라내는 데 쓴다.
    """
    chunks = []
    got = surface_triangles(env.block, env.block.get_root_transform())
    if got is not None:
        chunks.append(("object", got[0], got[1]))
    if include_hand:
        tf = env._link_positions()
        for k, actor in enumerate(env.tip_actors):
            got = surface_triangles(actor, tf[env.tip_idx[k]])
            if got is not None:
                chunks.append(("tip{}".format(k), got[0], got[1]))

    verts, tris, labels = [], [], []
    offset = 0
    for name, v, t in chunks:
        verts.append(v)
        tris.append(t + offset)
        labels.append(np.full(len(t), name, dtype=object))
        offset += len(v)
    if not verts:
        raise RuntimeError("표면을 하나도 못 읽었다")
    return np.concatenate(verts), np.concatenate(tris), np.concatenate(labels)


# ---------------------------------------------------------------------------
# 직접 그리기 (깊이 사진 만들기)
# ---------------------------------------------------------------------------
def render_depth(verts_world, tris, labels, cam_rot, cam_pos, width, height, fov_deg):
    """삼각형들을 카메라에서 본 깊이 사진으로. 겹치면 가까운 것만 남는다.

    돌려주는 것: `(깊이[h,w], 이름표[h,w])`. 아무것도 없는 칸은 깊이가 `inf`.
    """
    cam = (verts_world - cam_pos) @ cam_rot.T        # 세계 -> 카메라
    fx = fy = 0.5 * width / math.tan(math.radians(fov_deg) * 0.5)
    cx, cy = width * 0.5, height * 0.5

    depth = np.full((height, width), np.inf, dtype=np.float64)
    who = np.full((height, width), None, dtype=object)

    z = cam[:, 2]
    # 카메라 뒤나 범위 밖의 점이 낀 삼각형은 통째로 버린다(첫 판이라 자르기는 생략).
    ok_v = (z > NEAR_M) & (z < FAR_M)
    u = np.where(ok_v, cam[:, 0] / np.where(z == 0, 1e-9, z) * fx + cx, -1e9)
    v = np.where(ok_v, cam[:, 1] / np.where(z == 0, 1e-9, z) * fy + cy, -1e9)

    for tri, label in zip(tris, labels):
        if not (ok_v[tri[0]] and ok_v[tri[1]] and ok_v[tri[2]]):
            continue
        tu, tv, tz = u[tri], v[tri], z[tri]
        u0, u1 = int(max(0, math.floor(tu.min()))), int(min(width - 1, math.ceil(tu.max())))
        v0, v1 = int(max(0, math.floor(tv.min()))), int(min(height - 1, math.ceil(tv.max())))
        if u0 > u1 or v0 > v1:
            continue
        area = ((tu[1] - tu[0]) * (tv[2] - tv[0]) - (tu[2] - tu[0]) * (tv[1] - tv[0]))
        if abs(area) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(u0, u1 + 1) + 0.5, np.arange(v0, v1 + 1) + 0.5)
        # 무게중심 좌표로 삼각형 안인지 본다
        w0 = ((tu[1] - gx) * (tv[2] - gy) - (tu[2] - gx) * (tv[1] - gy)) / area
        w1 = ((tu[2] - gx) * (tv[0] - gy) - (tu[0] - gx) * (tv[2] - gy)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * tz[0] + w1 * tz[1] + w2 * tz[2]
        sub_d = depth[v0:v1 + 1, u0:u1 + 1]
        nearer = inside & (zz < sub_d)
        if not nearer.any():
            continue
        sub_d[nearer] = zz[nearer]
        who[v0:v1 + 1, u0:u1 + 1][nearer] = label
    return depth, who


def depth_to_points(depth, who, cam_rot, cam_pos, fov_deg, to_world=True):
    """깊이 사진을 다시 3차원 점으로. `to_world` 면 세계 좌표로 돌려준다."""
    height, width = depth.shape
    fx = fy = 0.5 * width / math.tan(math.radians(fov_deg) * 0.5)
    cx, cy = width * 0.5, height * 0.5
    vs, us = np.nonzero(np.isfinite(depth))
    if len(us) == 0:
        return np.zeros((0, 3)), np.array([], dtype=object)
    z = depth[vs, us]
    x = (us + 0.5 - cx) / fx * z
    y = (vs + 0.5 - cy) / fy * z
    pts_cam = np.stack([x, y, z], axis=1)
    labels = who[vs, us]
    if not to_world:
        return pts_cam, labels
    return pts_cam @ cam_rot + cam_pos, labels


# ---------------------------------------------------------------------------
# 명령줄
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="점 덩어리 합성 — 카메라가 볼 법한 점만 (D-3)")
    ap.add_argument("--object", default="prefabs/box_and_blocks/block_red.mochi_prefab")
    ap.add_argument("--object-actor", default=None)
    ap.add_argument("--object-ref", default="com")
    ap.add_argument("--width", type=int, default=cfg.D405_SYNTH_WIDTH)
    ap.add_argument("--height", type=int, default=cfg.D405_SYNTH_HEIGHT)
    ap.add_argument("--fov", type=float, default=cfg.D405_FOV_H_DEG,
                    help="가로 시야각(도). 기본값은 D405 제조사 사양 — 실측 아님")
    ap.add_argument("--standoff", type=float, default=0.18,
                    help="카메라를 물체에서 얼마나 떨어뜨릴지(m)")
    ap.add_argument("--no-hand", action="store_true", help="손을 빼고 물체만 본다")
    ap.add_argument("--save-npz", default=None)
    ap.add_argument("--preview", default=None, help="깊이 사진을 png 로 저장")
    args = ap.parse_args()

    from dg5f_grasp_env import Dg5fGraspEnv

    config = {"object_prefab": args.object, "object_ref": args.object_ref,
              "place_jitter": 0.0}
    if args.object_actor:
        config["object_actor"] = args.object_actor
    env = Dg5fGraspEnv(config)
    try:
        env.reset(seed=1)
        verts, tris, labels = scene_triangles(env, include_hand=not args.no_hand)
        target = env._object_position()

        # 카메라는 손 쪽에서 물체를 본다(eye-in-hand 를 흉내낸다).
        tf = env._link_positions()
        palm = np.asarray(tf[env.palm_idx].translation, dtype=np.float64)
        direction = target - palm
        n = float(np.linalg.norm(direction))
        direction = direction / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        cam_pos = target - direction * args.standoff
        cam_rot = look_at(cam_pos, target)

        print("=== 점 덩어리 합성 (D-3) ===")
        print("물체            : {}{}".format(args.object,
              " [{}]".format(args.object_actor) if args.object_actor else ""))
        print("표면 삼각형     : {}개 (정점 {}개)".format(len(tris), len(verts)))
        print("카메라          : {} 에서 {} 쪽, 거리 {:.2f} m, 시야 {:.0f}도".format(
            np.round(cam_pos, 3), np.round(target, 3), args.standoff, args.fov))
        print("사진 크기       : {}x{}".format(args.width, args.height))
        print("거리 범위       : {:.2f} ~ {:.2f} m".format(NEAR_M, FAR_M))
        print("⚠️ 카메라 값은 제조사 사양이고 **실측이 아니다** — 도착하면 재서 고칠 것")
        print()

        depth, who = render_depth(verts, tris, labels, cam_rot, cam_pos,
                                  args.width, args.height, args.fov)
        pts, plabels = depth_to_points(depth, who, cam_rot, cam_pos, args.fov)

        filled = int(np.isfinite(depth).sum())
        obj_pts = pts[plabels == "object"] if len(pts) else pts
        print("찍힌 칸         : {} / {} ({:.1f}%)".format(
            filled, depth.size, 100.0 * filled / depth.size))
        print("나온 점         : {}개  (그중 물체 {}개, 손 {}개)".format(
            len(pts), len(obj_pts), len(pts) - len(obj_pts)))
        if len(obj_pts):
            print("물체 점 거리    : {:.3f} ~ {:.3f} m".format(
                float(np.linalg.norm(obj_pts - cam_pos, axis=1).min()),
                float(np.linalg.norm(obj_pts - cam_pos, axis=1).max())))
        print()

        # --- 진짜 "보이는 것만" 인지 확인 -----------------------------------
        print("진짜 한쪽에서만 본 것인가")
        print("-" * 52)
        all_obj = verts[:0]
        got = surface_triangles(env.block, env.block.get_root_transform())
        if got is not None:
            all_obj = got[0]
        if len(all_obj) and len(obj_pts):
            # 물체 중심에서 카메라 쪽을 앞면, 반대를 뒷면으로 본다
            to_cam = cam_pos - target
            to_cam = to_cam / np.linalg.norm(to_cam)
            front_all = float(np.mean((all_obj - target) @ to_cam > 0))
            front_seen = float(np.mean((obj_pts - target) @ to_cam > 0))
            print("  물체 표면 전체 중 카메라 쪽 : {:.0f}%".format(front_all * 100))
            print("  나온 점 중 카메라 쪽        : {:.0f}%".format(front_seen * 100))
            ok = front_seen > 0.9
            print("  판정: {}".format(
                "앞면만 나왔다 — 카메라처럼 동작한다" if ok
                else "⚠️ 뒷면이 섞였다 — 가림 판정이 안 먹었다"))
        print()

        if args.save_npz:
            np.savez(args.save_npz, points=pts,
                     labels=np.array([str(x) for x in plabels]),
                     camera_pos=cam_pos, camera_rot=cam_rot, depth=depth)
            print("점 덩어리 저장: {}".format(args.save_npz))
        if args.preview:
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                # superdex/.venv 에는 그림 라이브러리가 없다(학습용이라 일부러 가볍다).
                # 점 덩어리는 이미 저장됐으므로 그림만 건너뛴다.
                print("그림을 못 그렸다 — 이 가상환경에 matplotlib 이 없다.")
                print("  --save-npz 로 저장한 뒤 다른 환경에서 그리면 된다:")
                print("  vision/.vision/Scripts/python.exe 로 npz 를 읽어 그린다")
                return 0
            shown = np.where(np.isfinite(depth), depth, np.nan)
            plt.figure(figsize=(6, 4.5))
            plt.imshow(shown, cmap="viridis")
            plt.colorbar(label="거리 (m)")
            plt.title("카메라가 본 깊이 ({} points)".format(len(pts)))
            plt.tight_layout()
            plt.savefig(args.preview, dpi=110)
            print("그림 저장: {}".format(args.preview))
        return 0
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())
