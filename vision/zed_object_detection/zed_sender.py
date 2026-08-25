"""
ZED 2i로 물체를 감지하고 3D 좌표를 UDP로 Unity에 전송하는 스크립트.

2D 물체 감지는 YOLO(ultralytics, COCO 사전학습)로 하고, 그 결과를
ZED SDK의 Custom Object Detection에 넣어서 3D 좌표/트래킹을 얻는다.
ZED 내장 감지 모델(MULTI_CLASS_BOX_ACCURATE)은 사람/차량/가방/동물/전자기기/
과일채소/스포츠용품 클래스만 있어서 텀블러, 음료수 같은 물체를 잡지 못한다.
COCO 클래스에는 cup/bottle이 포함돼 있어 YOLO 쪽이 더 잘 잡는다.

사전 설치:
    pip install pyzed ultralytics

실행 전 확인:
    - UNITY_IP: Unity가 돌아가는 PC의 IP (같은 PC면 "127.0.0.1")
    - UNITY_PORT: Unity 쪽 리시버가 열어둔 포트와 동일해야 함

전송 프로토콜: unity/Assets/Scripts/CameraTargetReceiver.cs가 받는 포맷과 동일하게
float32 little-endian 3개, `struct.pack('<3f', x, y, z)`로 매 프레임 최대 1개 좌표만
보낸다(트래킹 중인 오브젝트가 여러 개면 카메라에서 가장 가까운 것 하나를 선택).
커스텀 모델이 타겟 오브젝트 한 클래스만 학습돼 있어 다중 라벨 구분은 필요 없다.
"""

import csv
import os
import socket
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyzed.sl as sl
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_IP, PORT_ZED_TARGET  # .env의 RTAUTO_UNITY_IP로 오버라이드

UNITY_PORT = PORT_ZED_TARGET
SEND_INTERVAL_SEC = 0.05  # 초당 약 20회 전송

# unity/Logs/ — Dg5fJointLogger 등 Unity 쪽 CSV 로그와 같은 폴더. 타임스탬프는 t_unix(초, UTC)로
# 맞춰서 CameraTargetReceiver의 수신 로그와 나중에 시간/값으로 대조할 수 있게 한다.
LOG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "unity", "Logs")
)


def open_log_file(prefix):
    """Logs/<prefix>_<yyyymmdd_HHMMSS>.csv를 겹치지 않게 연다 (Dg5fLogFile.cs와 동일한 규칙:
    같은 초에 두 번 실행돼도 접미사로 갈라져 절대 덮어쓰지 않음)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    n = 1
    while True:
        name = f"{prefix}_{stamp}.csv" if n == 1 else f"{prefix}_{stamp}_{n}.csv"
        path = os.path.join(LOG_DIR, name)
        try:
            # "x" = 이미 있으면 FileExistsError — 덮어쓰기가 불가능하게 강제
            return open(path, "x", newline="", encoding="utf-8"), path
        except FileExistsError:
            n += 1

CAMERA_WINDOW = "ZED Camera"
COORDS_WINDOW = "Object Coordinates"

YOLO_WEIGHTS = "yolov8m.pt"  # COCO 사전학습 (80개 일반 사물 클래스), 처음 실행 시 자동 다운로드됨
YOLO_IMG_SIZE = 640
YOLO_CONF_THRES = 0.5


def xywh_to_corners(xywh):
    x_min = max(0, xywh[0] - 0.5 * xywh[2])
    x_max = xywh[0] + 0.5 * xywh[2]
    y_min = max(0, xywh[1] - 0.5 * xywh[3])
    y_max = xywh[1] + 0.5 * xywh[3]
    return np.array([[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]])


def detections_to_custom_box(boxes):
    output = []
    for det in boxes:
        obj = sl.CustomBoxObjectData()
        obj.bounding_box_2d = xywh_to_corners(det.xywh[0])
        obj.label = int(det.cls.item())
        obj.probability = det.conf.item()
        obj.is_grounded = False
        output.append(obj)
    return output


def main():
    print("YOLO 모델 로딩 중...")
    model = YOLO(YOLO_WEIGHTS)
    class_names = model.names  # {class_id: name}

    zed = sl.Camera()

    init_params = sl.InitParameters()
    init_params.camera_resolution = sl.RESOLUTION.HD720
    init_params.depth_mode = sl.DEPTH_MODE.PERFORMANCE
    init_params.coordinate_units = sl.UNIT.METER
    # Unity(왼손 좌표계, Y-up)와 동일한 좌표계로 바로 받기
    init_params.coordinate_system = sl.COORDINATE_SYSTEM.LEFT_HANDED_Y_UP

    status = zed.open(init_params)
    if status != sl.ERROR_CODE.SUCCESS:
        print(f"카메라 열기 실패: {status}")
        return

    zed.enable_positional_tracking(sl.PositionalTrackingParameters())

    obj_param = sl.ObjectDetectionParameters()
    obj_param.detection_model = sl.OBJECT_DETECTION_MODEL.CUSTOM_BOX_OBJECTS
    obj_param.enable_tracking = True
    err = zed.enable_object_detection(obj_param)
    if err != sl.ERROR_CODE.SUCCESS:
        print(f"Object Detection 활성화 실패: {err}")
        zed.close()
        return

    obj_runtime_param = sl.CustomObjectDetectionRuntimeParameters()
    obj_runtime_param.object_detection_properties.detection_confidence_threshold = 40
    objects = sl.Objects()
    image_zed = sl.Mat()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    cv2.namedWindow(CAMERA_WINDOW)
    cv2.namedWindow(COORDS_WINDOW)

    log_file, log_path = open_log_file("zed_camera_sent")
    log_writer = csv.writer(log_file)
    log_writer.writerow(
        ["t_unix", "num_detections", "detections", "sent_label", "sent_x", "sent_y", "sent_z", "sent_distance"]
    )
    print(f"전송 시작: {UNITY_IP}:{UNITY_PORT} (카메라 창에서 q 또는 ESC로 종료)")
    print(f"로그 기록 시작: {log_path}")

    try:
        last_sent = 0.0
        while True:
            if zed.grab() != sl.ERROR_CODE.SUCCESS:
                continue

            zed.retrieve_image(image_zed, sl.VIEW.LEFT)
            frame_rgb = cv2.cvtColor(image_zed.get_data(), cv2.COLOR_BGRA2RGB)

            results = model.predict(
                frame_rgb, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF_THRES, verbose=False
            )[0].cpu().numpy()

            zed.ingest_custom_box_objects(detections_to_custom_box(results.boxes))
            zed.retrieve_custom_objects(objects, obj_runtime_param)

            frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            detections = []
            for obj in objects.object_list:
                if obj.tracking_state != sl.OBJECT_TRACKING_STATE.OK:
                    continue
                x, y, z = obj.position
                label = class_names.get(obj.raw_label, str(obj.raw_label))
                detections.append(
                    {
                        "id": int(obj.id),
                        "label": label,
                        "x": float(x),
                        "y": float(y),
                        "z": float(z),
                        "confidence": float(getattr(obj, "confidence", 0.0)),
                        "distance": float((x * x + y * y + z * z) ** 0.5),
                    }
                )

                corners = np.array(obj.bounding_box_2d, dtype=np.int32)
                if corners.shape[0] >= 4:
                    cv2.polylines(frame, [corners], isClosed=True, color=(0, 255, 0), thickness=2)
                    top_left = corners[0]
                    cv2.putText(
                        frame,
                        f"{label} #{obj.id} z={z:.2f}m",
                        (int(top_left[0]), max(int(top_left[1]) - 8, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )

            coord_img = np.zeros((max(len(detections), 1) * 30 + 20, 420, 3), dtype=np.uint8)
            for i, d in enumerate(detections):
                line = f"#{d['id']} {d['label']}: x={d['x']:.2f} y={d['y']:.2f} z={d['z']:.2f}"
                cv2.putText(
                    coord_img,
                    line,
                    (10, 25 + i * 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )

            cv2.imshow(CAMERA_WINDOW, frame)
            cv2.imshow(COORDS_WINDOW, coord_img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

            now = time.time()
            if now - last_sent < SEND_INTERVAL_SEC:
                continue
            last_sent = now

            if detections:
                # 카메라(원점)로부터 가장 가까운 물체 하나만 골라 전송한다 — 여러 개 감지돼도
                # Unity 쪽 CameraTargetReceiver는 좌표 하나만 받는 구조라서.
                nearest = min(detections, key=lambda d: d["distance"])
                payload = struct.pack("<3f", nearest["x"], nearest["y"], nearest["z"])
                sock.sendto(payload, (UNITY_IP, UNITY_PORT))

                detections_str = ";".join(
                    f"{d['label']}:{d['x']:.6f}:{d['y']:.6f}:{d['z']:.6f}:{d['distance']:.6f}"
                    for d in detections
                )
                log_writer.writerow(
                    [
                        f"{now:.3f}",
                        len(detections),
                        detections_str,
                        nearest["label"],
                        f"{nearest['x']:.6f}",
                        f"{nearest['y']:.6f}",
                        f"{nearest['z']:.6f}",
                        f"{nearest['distance']:.6f}",
                    ]
                )
                log_file.flush()

                summary = ", ".join(
                    f"{d['label']}(x={d['x']:.2f}, y={d['y']:.2f}, z={d['z']:.2f}, "
                    f"dist={d['distance']:.2f})"
                    for d in detections
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] {len(detections)}개 감지, "
                    f"전송(최근접)={nearest['label']}(x={nearest['x']:.2f}, "
                    f"y={nearest['y']:.2f}, z={nearest['z']:.2f}, "
                    f"dist={nearest['distance']:.2f}): {summary}"
                )

    except KeyboardInterrupt:
        print("종료합니다.")
    finally:
        cv2.destroyAllWindows()
        zed.disable_object_detection()
        zed.disable_positional_tracking()
        zed.close()
        sock.close()
        log_file.close()


if __name__ == "__main__":
    main()
