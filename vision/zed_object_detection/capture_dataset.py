"""
YOLO 파인튜닝용 학습 이미지를 ZED 카메라로 촬영하는 스크립트.

실행:
    python capture_dataset.py

조작:
    s : 현재 화면을 이미지로 저장
    q / ESC : 종료

물건을 여러 각도/거리/배경/조명에서 최소 100장 이상 찍는 것을 권장.
(물건 없는 배경 사진도 10~20장 섞어두면 오탐지 방지에 도움됨)
"""

import time
from pathlib import Path

import cv2
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # vision/ — cv_window(X 로 창 닫기)
import cv_window  # noqa: E402
import pyzed.sl as sl

OUTPUT_DIR = Path(__file__).parent / "dataset" / "raw_images"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    zed = sl.Camera()
    init_params = sl.InitParameters()
    init_params.camera_resolution = sl.RESOLUTION.HD720
    status = zed.open(init_params)
    if status != sl.ERROR_CODE.SUCCESS:
        print(f"카메라 열기 실패: {status}")
        return

    image_zed = sl.Mat()
    cv2.namedWindow("Capture (s: 저장, q/ESC: 종료)")

    saved = 0
    print(f"저장 위치: {OUTPUT_DIR}")
    print("s: 저장 / q 또는 ESC: 종료")

    try:
        while True:
            if zed.grab() != sl.ERROR_CODE.SUCCESS:
                continue

            zed.retrieve_image(image_zed, sl.VIEW.LEFT)
            frame = cv2.cvtColor(image_zed.get_data(), cv2.COLOR_BGRA2BGR)

            preview = frame.copy()
            cv2.putText(
                preview,
                f"saved: {saved}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Capture (s: 저장, q/ESC: 종료)", preview)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27 or cv_window.closed("Capture (s: 저장, q/ESC: 종료)"):
                break
            if key == ord("s"):
                filename = OUTPUT_DIR / f"img_{int(time.time() * 1000)}.jpg"
                cv2.imwrite(str(filename), frame)
                saved += 1
                print(f"저장됨 ({saved}): {filename.name}")

    finally:
        cv2.destroyAllWindows()
        zed.close()
        print(f"총 {saved}장 저장 완료: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
