# -*- coding: utf-8 -*-
"""웹캠 1대 intrinsic 캘리브레이션 — 체스보드를 여러 각도에서 찍어 렌즈 왜곡·초점거리 산출.

다중뷰 3D 삼각측량(camera_calibration.py, calibrate_extrinsics.py)의 1단계. 카메라마다
한 번씩 실행 — 렌즈가 같은 모델이어도 개체마다 왜곡이 달라 공용 불가.

사용법:
  python calibrate_intrinsics.py <카메라 인덱스> [보드 col행수 row행수 칸mm]
  예) python calibrate_intrinsics.py 0
      python calibrate_intrinsics.py 1 --board=9x6 --square=25

  화면에 보드가 초록색으로 잡히면 스페이스바로 캡처. 최소 CALIB_MIN_FRAMES장 이상
  (보드를 화면 구석구석·기울여서·거리 다양하게) 모은 뒤 q로 종료하면 자동으로
  cv2.calibrateCamera 실행 → config.CALIB_DIR/intrinsics_cam<N>.json 저장.

⚠️ cap.set()의 대가는 카메라·백엔드마다 다르다는 게 이미 실측돼 있다(calibrate_dg5f.py
   주석 참고). 여기서도 강제하지 않고 카메라 기본 해상도를 그대로 쓴다.
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (
    CALIB_BOARD_COLS, CALIB_BOARD_ROWS, CALIB_SQUARE_SIZE_MM, CALIB_DIR,
)
from camera_calibration import chessboard_object_points, find_board_corners, save_intrinsics

CALIB_MIN_FRAMES = 12
WINDOW_NAME = "Intrinsic calibration (space=capture, q=finish)"


def _parse_args(argv):
    if not argv:
        print("[오류] 카메라 인덱스를 인자로 주세요. 예: python calibrate_intrinsics.py 0")
        return None
    try:
        index = int(argv[0])
    except ValueError:
        print(f"[오류] 카메라 인덱스는 정수여야 합니다: {argv[0]!r}")
        return None
    cols, rows, square = CALIB_BOARD_COLS, CALIB_BOARD_ROWS, CALIB_SQUARE_SIZE_MM
    for a in argv[1:]:
        if a.startswith("--board="):
            c, r = a.split("=", 1)[1].lower().split("x")
            cols, rows = int(c), int(r)
        elif a.startswith("--square="):
            square = float(a.split("=", 1)[1])
    return index, cols, rows, square


def main():
    parsed = _parse_args(sys.argv[1:])
    if parsed is None:
        return
    index, cols, rows, square_mm = parsed
    print(f"[calib_intrinsics] 카메라={index} 보드={cols}x{rows} 칸={square_mm}mm "
          f"(레포 루트 .env의 RTAUTO_CALIB_BOARD_*로 기본값 변경 가능)")

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f"[오류] 카메라 {index}를 열 수 없습니다.")
        return

    objp = chessboard_object_points(cols, rows, square_mm)
    object_points, image_points = [], []
    frame_size = None
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    print("[안내] 보드가 화면에 잡히면(초록 코너) 스페이스바로 캡처, 최소 "
          f"{CALIB_MIN_FRAMES}장 모은 뒤 q로 종료.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame_size = (frame.shape[1], frame.shape[0])
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners = find_board_corners(gray, cols, rows)
            display = frame.copy()
            if corners is not None:
                cv2.drawChessboardCorners(display, (cols, rows), corners, True)
            cv2.putText(display, f"captured: {len(object_points)}/{CALIB_MIN_FRAMES}+",
                        (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 0), 2, cv2.LINE_AA)
            cv2.imshow(WINDOW_NAME, display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" ") and corners is not None:
                object_points.append(objp)
                image_points.append(corners)
                print(f"[capture] {len(object_points)}장 캡처됨")
            elif key == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if len(object_points) < CALIB_MIN_FRAMES:
        print(f"[오류] 캡처 {len(object_points)}장 — 최소 {CALIB_MIN_FRAMES}장 필요. "
              "다시 실행해서 더 모으세요.")
        return

    print(f"[calib_intrinsics] cv2.calibrateCamera 실행 중 ({len(object_points)}장)...")
    rms, K, dist, _, _ = cv2.calibrateCamera(
        object_points, image_points, frame_size, None, None)
    print(f"[calib_intrinsics] 재투영 오차(RMS) = {rms:.4f}px "
          "(1px 안팎이면 양호, 2px 넘으면 캡처를 더 다양한 각도로 다시 모을 것)")

    path = save_intrinsics(CALIB_DIR, index, K, dist, frame_size[0], frame_size[1])
    print(f"[저장] {path}")


if __name__ == "__main__":
    main()
