# -*- coding: utf-8 -*-
"""웹캠 N대 extrinsic 캘리브레이션 — 같은 순간 같은 체스보드를 모든 카메라가 보는 상태에서
카메라별 자세(R,t)를 구해 "하나의 3D 좌표계(보드 좌표계)"로 묶는다.

다중뷰 3D 삼각측량의 2단계 — calibrate_intrinsics.py로 카메라별 intrinsics(K, dist)를
먼저 구해 둘 것. 이 단계는 intrinsics를 그대로 쓰고 각 카메라의 solvePnP로 "보드 →
카메라" 변환만 추가로 구한다.

원리: 카메라 3대가 정확히 같은 촬영 순간 같은 물리적 보드를 봤다면, 그 순간 보드의 3D
코너 좌표(보드 좌표계, Z=0 평면)는 세 카메라 모두에게 동일하다. 각 카메라에서
solvePnP(objectPoints, imagePoints_i, K_i, dist_i) → (R_i, t_i)를 구하면, 이 R_i,t_i들은
전부 "같은 보드 좌표계" 기준이므로 자동으로 서로 정합된 공통 좌표계가 된다 — 별도의
번들 조정(bundle adjustment) 없이도 충분하다(카메라가 흔들리지 않고, 캡처 시점에 세
카메라가 모두 같은 프레임의 같은 보드를 봤다는 전제 하에).

사용법:
  python calibrate_extrinsics.py
  보드를 모든 카메라가 동시에 보게 들고 있다가 스페이스바로 동시 캡처(여러 번 캡처해
  평균) → q로 종료 → config.CALIB_DIR/extrinsics.json 저장.

⚠️ 캡처하는 동안 보드도 카메라도 움직이면 안 된다(그 순간의 상대 자세를 구하는 것이므로).
   여러 장 캡처하는 건 노이즈를 평균으로 줄이기 위함이지, 보드를 옮겨 다니며 찍는 게
   아니다(intrinsic 캘리브레이션과 반대).
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (
    CALIB_BOARD_COLS, CALIB_BOARD_ROWS, CALIB_SQUARE_SIZE_MM, CALIB_DIR,
    VISION_CAMERA_INDICES,
)
from camera_calibration import (
    chessboard_object_points, find_board_corners, load_all_intrinsics, save_extrinsics,
)
from multi_camera_capture import MultiCameraCapture

CALIB_MIN_CAPTURES = 5


def _average_rt(rt_list):
    """여러 번 캡처한 (R,t)를 평균 — 회전은 회전행렬 평균(SVD 재직교화), 이동은 산술평균.

    단순 산술평균한 R은 직교행렬이 아니게 되므로, 평균 후 SVD로 가장 가까운 회전행렬에
    투영한다(Rotation averaging의 표준적인 근사 — 캡처 간 자세 차이가 작다는 전제에서 충분).
    """
    R_mean = np.mean([R for R, _ in rt_list], axis=0)
    U, _, Vt = np.linalg.svd(R_mean)
    R_avg = U @ Vt
    if np.linalg.det(R_avg) < 0:  # 반사(reflection) 방지
        U[:, -1] *= -1
        R_avg = U @ Vt
    t_avg = np.mean([t for _, t in rt_list], axis=0)
    return R_avg, t_avg


def main():
    # ⚠️ 카메라를 순차로(하나씩) 갖추는 게 정상 흐름이다 — 3대를 설정해뒀어도 아직 일부만
    # intrinsics가 있으면 "없는 것만 빼고" 있는 것들로 진행한다. 하나라도 없다고 전체를
    # 중단하면 카메라 2대만 있는 동안은 이 스크립트를 아예 못 쓰게 된다.
    intrinsics = load_all_intrinsics(CALIB_DIR, VISION_CAMERA_INDICES)
    missing = [idx for idx in VISION_CAMERA_INDICES if idx not in intrinsics]
    if missing:
        print(f"[경고] 카메라 {missing}의 intrinsics가 없어 이번 extrinsic 캘리브레이션에서 "
              f"제외합니다 (먼저 calibrate_intrinsics.py <인덱스>로 구해두면 포함됩니다). "
              f"지금은 {list(intrinsics.keys())}로 진행합니다.")
    if len(intrinsics) < 2:
        print("[오류] intrinsics가 있는 카메라가 2대 미만입니다 — extrinsic 캘리브레이션(삼각측량용 "
              "카메라 자세 정합)은 최소 2대 동시 촬영이 필요합니다.")
        return

    objp = chessboard_object_points(CALIB_BOARD_COLS, CALIB_BOARD_ROWS, CALIB_SQUARE_SIZE_MM)
    print(f"[calib_extrinsics] 대상 카메라: {list(intrinsics.keys())} "
          f"보드={CALIB_BOARD_COLS}x{CALIB_BOARD_ROWS} 칸={CALIB_SQUARE_SIZE_MM}mm")

    mgr = MultiCameraCapture(indices=list(intrinsics.keys()))
    opened = mgr.open_all()
    failed = [idx for idx, ok in opened.items() if not ok]
    opened_ok = [idx for idx, ok in opened.items() if ok]
    if failed:
        print(f"[경고] 카메라 {failed} 열기 실패: {[mgr.streams[i].error for i in failed]}")
    if len(opened_ok) < 2:
        print(f"[오류] 실제로 열린 카메라가 {len(opened_ok)}대({opened_ok})뿐입니다 — "
              "extrinsic 캘리브레이션에는 동시에 열리는 카메라가 2대 이상 필요합니다.")
        mgr.stop_all()
        return
    print(f"[calib_extrinsics] 실제 진행: {opened_ok} ({len(opened_ok)}대)")
    mgr.start_all()

    captures = {idx: [] for idx in mgr.streams if mgr.streams[idx].opened}
    print("[안내] 보드를 모든 카메라가 동시에 보이게 고정하고, 전부 초록 코너가 뜨면 "
          f"스페이스바로 캡처. 최소 {CALIB_MIN_CAPTURES}회 이상 캡처 후 q로 종료.")
    try:
        while True:
            frames = mgr.read_all()
            corners_by_idx = {}
            display_frames = {}
            for idx, frame in frames.items():
                if frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                corners = find_board_corners(gray, CALIB_BOARD_COLS, CALIB_BOARD_ROWS)
                corners_by_idx[idx] = corners
                disp = frame.copy()
                if corners is not None:
                    cv2.drawChessboardCorners(disp, (CALIB_BOARD_COLS, CALIB_BOARD_ROWS),
                                              corners, True)
                display_frames[idx] = disp
                cv2.imshow(f"cam{idx}", disp)

            all_seen = (len(display_frames) == len(captures)
                        and all(corners_by_idx.get(idx) is not None for idx in captures))
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                if all_seen:
                    for idx in captures:
                        captures[idx].append(corners_by_idx[idx])
                    n = len(next(iter(captures.values())))
                    print(f"[capture] 전체 카메라 동시 캡처 {n}회")
                else:
                    missing_now = [idx for idx in captures if corners_by_idx.get(idx) is None]
                    print(f"[스킵] 카메라 {missing_now}에서 보드를 못 봤습니다 — 다시 맞춰서 시도")
            elif key == ord("q"):
                break
    finally:
        mgr.stop_all()
        cv2.destroyAllWindows()

    n_captures = len(next(iter(captures.values()))) if captures else 0
    if n_captures < CALIB_MIN_CAPTURES:
        print(f"[오류] 동시 캡처 {n_captures}회 — 최소 {CALIB_MIN_CAPTURES}회 필요. 다시 실행하세요.")
        return

    cameras = {}
    for idx, corner_list in captures.items():
        K, dist = intrinsics[idx]["camera_matrix"], intrinsics[idx]["dist_coeffs"]
        rt_list = []
        for corners in corner_list:
            ok, rvec, tvec = cv2.solvePnP(objp, corners, K, dist)
            if not ok:
                continue
            R, _ = cv2.Rodrigues(rvec)
            rt_list.append((R, tvec.reshape(3)))
        if not rt_list:
            print(f"[오류] 카메라 {idx}: solvePnP가 전부 실패했습니다.")
            return
        cameras[idx] = _average_rt(rt_list)
        print(f"[calib_extrinsics] 카메라 {idx}: t(mm)={cameras[idx][1]}")

    path = save_extrinsics(CALIB_DIR, cameras, CALIB_SQUARE_SIZE_MM)
    print(f"[저장] {path}")


if __name__ == "__main__":
    main()
