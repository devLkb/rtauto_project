"""
간단한 로컬 라벨링 도구. Roboflow 같은 웹사이트 없이 물건을 클릭하면 자동으로
윤곽을 잡아 박스를 그리고, 이름을 타이핑하면 YOLO 학습용 라벨 파일이 만들어진다.

실행:
    python label_tool.py

조작 (이미지 한 장씩 진행):
    클릭(마우스 짧게 클릭) : 그 위치 물체를 자동 인식해서 윤곽선+박스 표시
    드래그              : 자동 인식이 안 맞을 때 수동으로 박스 직접 그리기
    (박스 생긴 후) 타이핑으로 물건 이름 입력 -> Enter로 확정
                        (영문/숫자만 지원, 한글 입력 안 됨)
                      ESC : 지금 그린 박스만 취소 (이름 입력 중일 때)
    z                 : 마지막으로 확정된 박스 삭제
    c                 : 지금 이미지의 박스 전부 지우고 다시 그리기
    s                 : 지금까지 그린 박스(들)로 저장하고 다음 이미지로
                        (박스가 하나도 없으면 "물건 없음"으로 저장됨)
    q                 : 중단 (지금까지 진행한 건 저장됨, 다시 실행하면 이어서 진행)
"""

from pathlib import Path

import cv2
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # vision/ — cv_window(X 로 창 닫기)
import cv_window  # noqa: E402
import numpy as np
import torch
import yaml
from ultralytics import FastSAM

BASE_DIR = Path(__file__).parent / "dataset"
RAW_IMAGES_DIR = BASE_DIR / "raw_images"
IMAGES_OUT_DIR = BASE_DIR / "images" / "train"
LABELS_OUT_DIR = BASE_DIR / "labels" / "train"
DATA_YAML_PATH = BASE_DIR / "data.yaml"

WINDOW_NAME = "Label (click: auto, drag: manual box, z: undo, c: clear, s: save+next, q: quit)"
CLICK_MAX_DIST = 6  # 이보다 적게 움직이면 드래그가 아니라 클릭으로 간주

boxes = []  # list of {"rect": (x0,y0,x1,y1), "label": str, "polygon": np.ndarray|None}
drag_start = None
drag_current = None
pending_rect = None  # 박스는 그렸지만 아직 이름 입력 중인 상태
pending_polygon = None
text_buffer = ""
current_img = None

sam_model = None
class_to_id = {}


def get_sam_model():
    global sam_model
    if sam_model is None:
        print("세그멘테이션 모델 로딩 중 (최초 1회, 자동 다운로드될 수 있음)...")
        sam_model = FastSAM("FastSAM-s.pt")
    return sam_model


def segment_at_point(img, x, y):
    model = get_sam_model()
    device = 0 if torch.cuda.is_available() else "cpu"
    results = model(img, points=[[x, y]], labels=[1], device=device, verbose=False)
    if not results or results[0].masks is None or len(results[0].masks.xy) == 0:
        return None, None
    polygon = np.array(results[0].masks.xy[0])
    if len(polygon) < 3:
        return None, None
    x0, y0, bw, bh = cv2.boundingRect(polygon.astype(np.int32))
    return (x0, y0, x0 + bw, y0 + bh), polygon


def on_mouse(event, x, y, flags, param):
    global drag_start, drag_current, pending_rect, pending_polygon
    if pending_rect is not None:
        return  # 이름 입력 중에는 새 클릭/드래그 무시
    if event == cv2.EVENT_LBUTTONDOWN:
        drag_start = (x, y)
        drag_current = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and drag_start is not None:
        drag_current = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and drag_start is not None:
        x0, y0 = drag_start
        x1, y1 = x, y
        dist = max(abs(x1 - x0), abs(y1 - y0))
        if dist <= CLICK_MAX_DIST:
            rect, polygon = segment_at_point(current_img, x, y)
            if rect is not None:
                pending_rect = rect
                pending_polygon = polygon
            else:
                print("해당 위치에서 물체를 못 찾았습니다. 드래그로 직접 박스를 그려주세요.")
        else:
            pending_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            pending_polygon = None
        drag_start = None
        drag_current = None


def load_existing_classes():
    if DATA_YAML_PATH.exists():
        data = yaml.safe_load(DATA_YAML_PATH.read_text())
        for idx, name in (data.get("names") or {}).items():
            class_to_id[name] = int(idx)


def get_class_id(name):
    if name not in class_to_id:
        class_to_id[name] = len(class_to_id)
    return class_to_id[name]


def write_yolo_label(label_path, img_w, img_h):
    lines = []
    for b in boxes:
        x0, y0, x1, y1 = b["rect"]
        cls_id = get_class_id(b["label"])
        cx = (x0 + x1) / 2 / img_w
        cy = (y0 + y1) / 2 / img_h
        w = (x1 - x0) / img_w
        h = (y1 - y0) / img_h
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    label_path.write_text("\n".join(lines))


def write_data_yaml():
    names_sorted = sorted(class_to_id.items(), key=lambda kv: kv[1])
    names_block = "\n".join(f"  {idx}: {name}" for name, idx in names_sorted)
    DATA_YAML_PATH.write_text(
        f"path: {BASE_DIR.resolve()}\n"
        f"train: images/train\n"
        f"val: images/train\n"
        f"names:\n"
        f"{names_block}\n"
    )


def main():
    global boxes, pending_rect, pending_polygon, text_buffer, current_img

    IMAGES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    load_existing_classes()

    all_images = sorted(RAW_IMAGES_DIR.glob("*.jpg"))
    remaining = [p for p in all_images if not (LABELS_OUT_DIR / f"{p.stem}.txt").exists()]

    if not remaining:
        print("라벨링할 새 이미지가 없습니다 (전부 완료됨).")
        write_data_yaml()
        return

    print(f"전체 {len(all_images)}장 중 {len(remaining)}장 남음")

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    stopped = False
    for img_path in remaining:
        boxes = []
        pending_rect = None
        pending_polygon = None
        text_buffer = ""
        img = cv2.imread(str(img_path))
        current_img = img
        h, w = img.shape[:2]

        while True:
            preview = img.copy()
            for b in boxes:
                x0, y0, x1, y1 = b["rect"]
                if b.get("polygon") is not None:
                    cv2.polylines(preview, [b["polygon"].astype(np.int32)], True, (0, 255, 0), 2)
                else:
                    cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 255, 0), 2)
                cv2.putText(
                    preview, b["label"], (x0, max(y0 - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                )
            if drag_start is not None and drag_current is not None:
                cv2.rectangle(preview, drag_start, drag_current, (0, 200, 255), 2)
            if pending_rect is not None:
                x0, y0, x1, y1 = pending_rect
                if pending_polygon is not None:
                    cv2.polylines(preview, [pending_polygon.astype(np.int32)], True, (255, 0, 255), 2)
                else:
                    cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 200, 255), 2)
                cv2.putText(
                    preview, f"이름 입력 후 Enter: {text_buffer}_", (x0, max(y0 - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2,
                )

            status = f"{img_path.name}  boxes:{len(boxes)}"
            if pending_rect is None:
                status += "  (drag:box  z:undo  c:clear  s:save+next  q:quit)"
            cv2.putText(preview, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(WINDOW_NAME, preview)

            key = cv2.waitKey(20) & 0xFF
            if cv_window.closed(WINDOW_NAME):   # 창 X — q 와 같게 끝낸다
                stopped = True
                break
            if key == 255:  # 키 입력 없음
                continue

            if pending_rect is not None:
                if key == 13:  # Enter
                    label = text_buffer.strip()
                    if label:
                        boxes.append({"rect": pending_rect, "label": label, "polygon": pending_polygon})
                    pending_rect = None
                    pending_polygon = None
                    text_buffer = ""
                elif key == 27:  # ESC: 이 박스만 취소
                    pending_rect = None
                    pending_polygon = None
                    text_buffer = ""
                elif key == 8:  # Backspace
                    text_buffer = text_buffer[:-1]
                elif 32 <= key < 127:
                    text_buffer += chr(key)
                continue

            if key == ord("z") and boxes:
                boxes.pop()
            elif key == ord("c"):
                boxes = []
            elif key == ord("s"):
                out_img_path = IMAGES_OUT_DIR / img_path.name
                cv2.imwrite(str(out_img_path), img)
                write_yolo_label(LABELS_OUT_DIR / f"{img_path.stem}.txt", w, h)
                break
            elif key == ord("q"):
                stopped = True
                break

        if stopped:
            break

    cv2.destroyAllWindows()
    write_data_yaml()

    done = len(list(LABELS_OUT_DIR.glob("*.txt")))
    print(f"라벨링 완료: {done}/{len(all_images)}장")
    print(f"data.yaml 생성됨: {DATA_YAML_PATH}")
    print(f"클래스: {sorted(class_to_id.items(), key=lambda kv: kv[1])}")


if __name__ == "__main__":
    main()
