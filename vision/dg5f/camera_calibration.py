# -*- coding: utf-8 -*-
"""다중 웹캠 3D 캘리브레이션 공용 모듈 — intrinsics/extrinsics 저장·로드 + N-view 삼각측량.

목적: 웹캠 3대(또는 N대)의 영상을 **하나의 3D 좌표계**로 합쳐서, 카메라 1대짜리 MediaPipe
world landmark(깊이 추정이 부정확 — vision_node_dg5f.py의 USE_WORLD_LANDMARKS 관련 주석,
dg5f_angles.py의 MCP 굽힘 33° 클리핑 이력 참고)보다 정확한 3D 손 랜드마크를 얻는 것.

파이프라인:
  1) calibrate_intrinsics.py  — 카메라별로 체스보드를 여러 각도에서 찍어 렌즈 왜곡·초점거리(K, dist) 산출
  2) calibrate_extrinsics.py  — 같은 체스보드를 모든 카메라가 동시에 보는 상태에서 카메라별
                                  solvePnP → 보드 좌표계를 공통 원점으로 한 R,t(카메라 자세) 산출
  3) 이 모듈의 triangulate_landmark_set() — 카메라별 2D 랜드마크(픽셀) → undistort로 왜곡 제거
                                  → 이 모듈의 DLT 삼각측량으로 3D 좌표(보드 좌표계, mm) 복원

좌표계 규약: extrinsics의 (R, t)는 "보드 좌표계 → 카메라 좌표계" 변환이다
  (X_cam = R @ X_board + t) — cv2.solvePnP가 그대로 이 규약으로 반환한다.
  카메라 3대가 전부 같은 촬영 순간의 같은 보드를 기준으로 구해지므로, 그 R,t들이 자동으로
  "공통 3D 좌표계(보드 좌표계) 안에서 서로 다른 시점"이 된다 — 이게 곧 요청하신
  "3대를 하나의 3D 좌표계로 맞추는" 부분이다.

삼각측량된 (21,3) xyz는 실제 미터법 좌표라 dg5f_angles.compute_raw()에 그대로 넣을 수 있다
  — compute_raw는 벡터 사이 각도만 계산하므로 회전/이동/균일 스케일에 불변이다(단, MediaPipe
  단안 이미지 좌표의 비등방 왜곡을 보정하던 landmarks_to_xyz의 LM_ASPECT_FIX는 여기선
  필요 없다 — 애초에 진짜 3D라 그 왜곡 자체가 없다).
"""
import json
from pathlib import Path

import cv2
import numpy as np


def chessboard_object_points(cols, rows, square_size_mm):
    """체스보드 내부 코너의 보드 좌표계 3D 좌표 (cols*rows, 3), Z=0 평면, mm 단위."""
    objp = np.zeros((cols * rows, 3), dtype=np.float64)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_size_mm
    return objp


def find_board_corners(gray_frame, cols, rows):
    """체스보드 코너 검출 + 서브픽셀 정제. 못 찾으면 None.

    반환: (cols*rows, 1, 2) float32 픽셀 좌표 (cv2.findChessboardCorners 규약 그대로).
    """
    found, corners = cv2.findChessboardCorners(
        gray_frame, (cols, rows),
        cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    cv2.cornerSubPix(gray_frame, corners, (11, 11), (-1, -1), criteria)
    return corners


# ------------------------- intrinsics I/O -------------------------

def intrinsics_path(calib_dir, index):
    return Path(calib_dir) / f"intrinsics_cam{index}.json"


def save_intrinsics(calib_dir, index, camera_matrix, dist_coeffs, image_width, image_height):
    path = intrinsics_path(calib_dir, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "index": index,
        "image_width": image_width,
        "image_height": image_height,
        "camera_matrix": np.asarray(camera_matrix, dtype=np.float64).tolist(),
        "dist_coeffs": np.asarray(dist_coeffs, dtype=np.float64).reshape(-1).tolist(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_intrinsics(calib_dir, index):
    path = intrinsics_path(calib_dir, index)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "index": data["index"],
        "image_width": data["image_width"],
        "image_height": data["image_height"],
        "camera_matrix": np.array(data["camera_matrix"], dtype=np.float64),
        "dist_coeffs": np.array(data["dist_coeffs"], dtype=np.float64),
    }


def load_all_intrinsics(calib_dir, indices):
    """{index: intrinsics dict} — 파일 없는 인덱스는 결과에서 빠진다(호출부가 개수로 확인)."""
    out = {}
    for idx in indices:
        intr = load_intrinsics(calib_dir, idx)
        if intr is not None:
            out[idx] = intr
    return out


# ------------------------- extrinsics I/O -------------------------

def extrinsics_path(calib_dir):
    return Path(calib_dir) / "extrinsics.json"


def save_extrinsics(calib_dir, cameras, square_size_mm):
    """cameras: {index: (R (3,3), t (3,)/(3,1))} — 보드 좌표계 기준 카메라 자세."""
    path = extrinsics_path(calib_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "board_square_size_mm": square_size_mm,
        "cameras": {
            str(idx): {
                "R": np.asarray(R, dtype=np.float64).tolist(),
                "t": np.asarray(t, dtype=np.float64).reshape(-1).tolist(),
            }
            for idx, (R, t) in cameras.items()
        },
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_extrinsics(calib_dir):
    """반환: ({index: (R, t)}, board_square_size_mm) — 파일 없으면 ({}, None)."""
    path = extrinsics_path(calib_dir)
    if not path.is_file():
        return {}, None
    data = json.loads(path.read_text(encoding="utf-8"))
    cameras = {
        int(idx): (np.array(v["R"], dtype=np.float64), np.array(v["t"], dtype=np.float64))
        for idx, v in data["cameras"].items()
    }
    return cameras, data.get("board_square_size_mm")


# ------------------------- N-view 삼각측량 -------------------------

def build_camera_rig(intrinsics_by_idx, extrinsics_by_idx, verbose=True):
    """카메라별 (K, dist, R, t, P=[R|t]) 묶음 — 매 프레임 재계산 안 하도록 한 번만 구성.

    intrinsics는 있는데 extrinsics가 아직 없는 카메라(예: 3대 중 아직 extrinsic 캘리브레이션
    안 한 1대)는 조용히 빠진다 — 호출부(vision_node 등)가 "카메라가 줄어서 삼각측량 정확도가
    낮아진 채로 동작 중"이라는 걸 모르고 지나치면 안 되므로, 여기서 한 번(rig 구성 시점) 알린다.
    매 프레임 로그가 아니라 시작 시점 1회인 이유: 이 구성은 세션당 한 번만 호출되기 때문.
    """
    rig = {}
    dropped = []
    for idx, intr in intrinsics_by_idx.items():
        if idx not in extrinsics_by_idx:
            dropped.append(idx)
            continue
        R, t = extrinsics_by_idx[idx]
        rig[idx] = {
            "K": intr["camera_matrix"],
            "dist": intr["dist_coeffs"],
            "R": R,
            "t": np.asarray(t, dtype=np.float64).reshape(3),
            "P": np.hstack([R, np.asarray(t, dtype=np.float64).reshape(3, 1)]),
        }
    if verbose:
        if dropped:
            print(f"[camera_rig] extrinsics 없어 제외된 카메라: {dropped} "
                  f"(calibrate_extrinsics.py를 다시 실행하면 포함됩니다)")
        n = len(rig)
        if n < 2:
            print(f"[camera_rig] 활성 카메라 {sorted(rig.keys())} — {n}대뿐이라 삼각측량 불가"
                  "(2대 이상부터 동작).")
        else:
            print(f"[camera_rig] 활성 카메라 {sorted(rig.keys())} ({n}대)로 삼각측량 진행.")
    return rig


def undistort_normalize(pixel_xy, K, dist):
    """왜곡 있는 픽셀좌표 1점 → 왜곡 제거된 정규화 카메라좌표(x/z, y/z). K=단위행렬로 투영한 것과 동치."""
    pts = np.array([[[pixel_xy[0], pixel_xy[1]]]], dtype=np.float64)
    und = cv2.undistortPoints(pts, K, dist)
    return und[0, 0]


def triangulate_point(views):
    """views: [(P (3,4), (x_norm, y_norm)), ...] (>=2개) → 3D 점(3,), DLT(선형 최소제곱).

    P는 extrinsic-only(K 미포함) 투영행렬 — undistort_normalize로 K를 이미 제거했기 때문에
    여기서 다시 곱하면 안 된다. 2-view 전용 cv2.triangulatePoints 대신 SVD 기반 일반 DLT를
    직접 쓰는 이유: 카메라가 N>=2대로 늘어도(3대, 4대…) 코드 변경 없이 그대로 확장된다.
    """
    if len(views) < 2:
        return None
    rows = []
    for P, (x, y) in views:
        rows.append(x * P[2] - P[0])
        rows.append(y * P[2] - P[1])
    A = np.asarray(rows, dtype=np.float64)
    _, _, vt = np.linalg.svd(A)
    X = vt[-1]
    if abs(X[3]) < 1e-12:
        return None
    return (X[:3] / X[3])


def triangulate_landmark_set(per_camera_pixel_landmarks, rig, min_views=2):
    """per_camera_pixel_landmarks: {index: (N,2) 픽셀좌표 ndarray 또는 None(그 카메라는 미검출)}
    rig: build_camera_rig() 결과.

    반환: (N,3) xyz(보드 좌표계, mm) ndarray, 또는 유효 시점이 min_views 미만이면 None.
    개별 랜드마크 단위가 아니라 프레임 단위로 컷한다 — 카메라마다 검출 성공 시점이 달라
    특정 관절만 값이 들쭉날쭉하면 필터(One Euro)가 오히려 더 튄다(occlusion hold 정책과
    동일한 이유: 애매하게 섞느니 아예 갱신 안 하는 편이 안전).
    """
    active = [idx for idx, lm in per_camera_pixel_landmarks.items()
              if lm is not None and idx in rig]
    if len(active) < min_views:
        return None
    n_landmarks = per_camera_pixel_landmarks[active[0]].shape[0]
    out = np.zeros((n_landmarks, 3), dtype=np.float64)
    for li in range(n_landmarks):
        views = []
        for idx in active:
            xy = per_camera_pixel_landmarks[idx][li]
            norm = undistort_normalize(xy, rig[idx]["K"], rig[idx]["dist"])
            views.append((rig[idx]["P"], (norm[0], norm[1])))
        X = triangulate_point(views)
        if X is None:
            return None
        out[li] = X
    return out
