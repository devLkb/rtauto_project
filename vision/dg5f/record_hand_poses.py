# -*- coding: utf-8 -*-
"""자세를 **하나씩 안내하며** 손 관절 점(MediaPipe 랜드마크)을 기록한다 — 엄지·중지 조정용.

왜 만들었나 (2026-09-23)
------------------------
Unity 화면에서 ① 손을 쫙 펴도 로봇 엄지가 손바닥 앞으로 나오고 ② 중지가 좌우로 안
움직였다. 엄지를 고치려면 "엄지를 옆에 붙였을 때 / 옆으로 벌렸을 때 / 손바닥 앞으로
가져왔을 때" 값이 **실제로 어떻게 다른지** 사용자 손으로 재야 한다. 옛 녹화 도구
(`probe_landmarks.py`)는 한 번에 한 동작만 찍어서 자세 이름이 없다. 이 도구는 자세를
차례로 안내하고, **줄마다 자세 이름(pose)을 붙여** 한 파일에 남긴다.

돌리는 법
---------
터미널 1 (PowerShell, 브랜치 폴더 `KDT_1_AX_rtauto-teleop`, 녹화)::

    D:/workspace/KDT_1_AX_rtauto/vision/.vision/Scripts/Activate.ps1
    python vision/dg5f/record_hand_poses.py

터미널 1 (bash, 같은 폴더)::

    source ../KDT_1_AX_rtauto/vision/.vision/Scripts/activate
    python vision/dg5f/record_hand_poses.py

- **오른손**을 카메라에 손바닥이 보이게 든다(평소 텔레옵할 때와 같은 자세·거리).
- 터미널에 다음 자세가 한국어로 나오고, 카메라 창에는 영어 이름과 남은 초가 보인다.
  `GET READY` 동안 자세를 잡고, `REC` 동안 **자세를 유지한 채 손을 조금씩 돌리고
  기울인다**(손 방향이 바뀌어도 값이 버티는지 보려는 것).
- 창에서 `s` = 지금 자세 건너뛰기, `q` = 그만두기(그때까지 찍은 것은 저장된다).
- 끝나면 `vision/dg5f/logs/handposes_<날짜_시각>.csv` 가 생긴다. 이 파일을 알려 주면 된다.

기록 열은 `probe_landmarks.py` 와 같고(이미지 점 63 + 화면 크기 + world 점 63),
맨 뒤에 `pose` 한 열이 붙는다. 준비 시간(`GET READY`) 줄은 pose=`-` 로 남긴다.
"""
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp

from dg5f_paths import unique_log_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (  # noqa: E402
    VISION_CAMERA_INDEX, VISION_CAMERA_WIDTH, VISION_CAMERA_HEIGHT,
    VISION_CAMERA_FPS, VISION_CAMERA_BACKEND, VISION_CAMERA_FOURCC,
    VISION_CAMERA_MIN_FPS,
)

import camera_caps  # noqa: E402

#: (영어 이름 — 화면·파일용, 한국어 안내 — 터미널용). 순서대로 안내한다.
POSES = [
    ("flat", "손을 쫙 펴고 엄지를 검지 옆에 나란히 붙인다 (손바닥과 같은 평면)"),
    ("spread", "손을 편 채 엄지만 옆으로 최대한 벌린다 (L자)"),
    ("oppose", "엄지 끝을 새끼손가락 뿌리(손바닥 아래 새끼 쪽)에 댄다"),
    ("pinch", "엄지 끝과 검지 끝을 맞댄다 (집게, 나머지 손가락은 편 채)"),
    ("thumb_front", "손은 편 채 엄지만 손바닥 앞(카메라 쪽)으로 세운다 — 검지 쪽 위에 뜨게"),
    ("fist", "주먹을 쥔다 (엄지는 검지·중지 위를 감싼다)"),
    ("fingers_together", "손을 편 채 네 손가락을 서로 딱 붙인다"),
    ("fingers_spread", "손을 편 채 네 손가락을 서로 최대한 벌린다"),
    ("middle_to_index", "손을 편 채 중지만 검지 쪽으로 기울인다 (약지와 벌어지게)"),
    ("middle_to_ring", "손을 편 채 중지만 약지 쪽으로 기울인다 (검지와 벌어지게)"),
]
READY_SEC = 3.0
RECORD_SEC = 8.0
PREP_LABEL = "-"


def _header():
    return ",".join(["t_unix", "detected"]
                    + [f"lm{i}_{a}" for i in range(21) for a in "xyz"]
                    + ["frame_w", "frame_h"]
                    + [f"wl{i}_{a}" for i in range(21) for a in "xyz"]
                    + ["pose"]) + "\n"


def main():
    hands = mp.solutions.hands.Hands(      # vision_node_dg5f.py 와 같은 설정
        model_complexity=1, max_num_hands=1,
        min_detection_confidence=0.6, min_tracking_confidence=0.6)
    cap, cam_fmt = camera_caps.open_camera(
        VISION_CAMERA_INDEX, backend_name=VISION_CAMERA_BACKEND,
        width=VISION_CAMERA_WIDTH, height=VISION_CAMERA_HEIGHT,
        fps=VISION_CAMERA_FPS, fourcc=VISION_CAMERA_FOURCC,
        min_fps=VISION_CAMERA_MIN_FPS)
    if cap is None:
        print(f"[오류] 카메라 {VISION_CAMERA_INDEX} 열기 실패 — 리포 루트 .env 의 "
              "RTAUTO_VISION_CAMERA_INDEX 를 0, 1, 2 순으로 바꿔 볼 것.")
        return 1
    print(f"[카메라] {cam_fmt.text} (카메라 {cam_fmt.index}번)")

    log_path = unique_log_path("handposes")
    zeros63 = ["0"] * 63
    counts = {}
    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(_header())
        quit_all = False
        for n, (pose, text) in enumerate(POSES, 1):
            print(f"\n[{n}/{len(POSES)}] {text}")
            print(f"        준비 {READY_SEC:.0f}초 → 기록 {RECORD_SEC:.0f}초 "
                  "(기록 중엔 자세를 유지한 채 손을 조금씩 돌리고 기울일 것)")
            t_start = time.time()
            n_det = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    continue
                frame = cv2.flip(frame, 1)   # vision_node 와 같은 거울 모드
                res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                now = time.time()
                el = now - t_start
                if el >= READY_SEC + RECORD_SEC:
                    break
                recording = el >= READY_SEC
                label = pose if recording else PREP_LABEL
                h, w = frame.shape[0], frame.shape[1]
                if res.multi_hand_landmarks:
                    hl = res.multi_hand_landmarks[0]
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame, hl, mp.solutions.hands.HAND_CONNECTIONS)
                    coords = [f"{v:.6f}" for lm in hl.landmark for v in (lm.x, lm.y, lm.z)]
                    if res.multi_hand_world_landmarks:
                        wl = res.multi_hand_world_landmarks[0]
                        wcoords = [f"{v:.6f}" for lm in wl.landmark for v in (lm.x, lm.y, lm.z)]
                    else:
                        wcoords = zeros63
                    log_f.write(f"{now:.3f},1," + ",".join(coords) + f",{w},{h},"
                                + ",".join(wcoords) + f",{label}\n")
                    if recording:
                        n_det += 1
                else:
                    log_f.write(f"{now:.3f},0," + ",".join(zeros63) + f",{w},{h},"
                                + ",".join(zeros63) + f",{label}\n")

                if recording:
                    msg, color = f"REC {pose}  {READY_SEC + RECORD_SEC - el:4.1f}s", (0, 0, 255)
                else:
                    msg, color = f"GET READY: {pose}  {READY_SEC - el:3.1f}s", (0, 200, 255)
                cv2.putText(frame, f"[{n}/{len(POSES)}] {msg}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                cv2.putText(frame, "s: skip   q: quit", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.imshow("record_hand_poses", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("s"):
                    print("        → 건너뜀")
                    break
                if key == ord("q"):
                    quit_all = True
                    break
            counts[pose] = n_det
            print(f"        손이 잡힌 장면 {n_det}개")
            if quit_all:
                print("[중단] q — 여기까지 저장한다.")
                break

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[끝] 저장: {log_path}")
    weak = [p for p, c in counts.items() if c < 60]
    if weak:
        print(f"⚠️ 손이 잡힌 장면이 60개보다 적은 자세: {', '.join(weak)} — "
              "손이 화면에 다 들어오게 하고 다시 찍는 것이 좋다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
