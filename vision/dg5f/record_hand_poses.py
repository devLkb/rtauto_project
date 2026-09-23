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
- `--set side` 를 붙이면 **손을 옆으로 돌린** 자세 6가지를 찍는다(정면 녹화로는 못 재는
  "옆을 보면 집게가 안 잡힌다" 를 재려는 것)::

      python vision/dg5f/record_hand_poses.py --set side

- `--camera d405` 를 붙이면 웹캠 대신 **D405** 로 찍는다(2026-09-23 시험). 관절마다 D405 가 잰
  입체 위치(`d3_*` 열, 미터)가 함께 남는다. D405 는 약 7~50 cm 에서 잘 재므로 **손을 카메라에서
  30~50 cm 안에** 든다::

      python vision/dg5f/record_hand_poses.py --camera d405
      python vision/dg5f/record_hand_poses.py --camera d405 --set side
- 터미널에 다음 자세가 한국어로 나오고, 카메라 창에는 영어 이름과 남은 초가 보인다.
  `GET READY` 동안 자세를 잡고, `REC` 동안 **자세를 유지한 채 손을 조금씩 돌리고
  기울인다**(손 방향이 바뀌어도 값이 버티는지 보려는 것).
- 창에서 `s` = 지금 자세 건너뛰기, `q` 또는 창의 X = 그만두기(그때까지 찍은 것은 저장된다).
- 끝나면 `vision/dg5f/logs/handposes_<날짜_시각>.csv` 가 생긴다. 이 파일을 알려 주면 된다.

기록 열은 `probe_landmarks.py` 와 같고(이미지 점 63 + 화면 크기 + world 점 63),
맨 뒤에 `pose` 한 열이 붙는다. 준비 시간(`GET READY`) 줄은 pose=`-` 로 남긴다.
"""
import sys
import time
from pathlib import Path

import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # vision/ — cv_window(X 로 창 닫기)
import cv_window  # noqa: E402
import mediapipe as mp

from dg5f_paths import unique_log_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (  # noqa: E402
    VISION_CAMERA_INDEX, VISION_CAMERA_WIDTH, VISION_CAMERA_HEIGHT,
    VISION_CAMERA_FPS, VISION_CAMERA_BACKEND, VISION_CAMERA_FOURCC,
    VISION_CAMERA_MIN_FPS, VISION_PREVIEW_WIDTH, D405_NEAR_M, D405_FAR_M,
)

import camera_caps  # noqa: E402
import depth_landmarks  # noqa: E402

#: (영어 이름 — 화면·파일용, 한국어 안내 — 터미널용). 순서대로 안내한다.
POSES = [
    ("flat", "손을 쫙 펴고 엄지를 검지 옆에 나란히 붙인다 (손바닥과 같은 평면)"),
    ("spread", "손을 편 채 엄지만 옆으로 최대한 벌린다 (L자)"),
    ("oppose", "엄지 끝을 새끼손가락 뿌리(손바닥 아래 새끼 쪽)에 댄다"),
    ("pinch", "엄지 끝과 검지 끝을 맞댄다 (집게, 나머지 손가락은 편 채)"),
    ("thumb_front", "손바닥을 카메라에 보여 준 채, 엄지 끝이 카메라를 가리키게 엄지만 앞으로 내민다 (옆에서 보면 엄지가 손바닥에서 수직으로 튀어나온 모양, 나머지 네 손가락은 편 채)"),
    ("fist", "주먹을 쥔다 (엄지는 검지·중지 위를 감싼다)"),
    ("fingers_together", "손을 편 채 네 손가락을 서로 딱 붙인다"),
    ("fingers_spread", "손을 편 채 네 손가락을 서로 최대한 벌린다"),
    ("middle_to_index", "손을 편 채 중지만 검지 쪽으로 기울인다 (약지와 벌어지게)"),
    ("middle_to_ring", "손을 편 채 중지만 약지 쪽으로 기울인다 (검지와 벌어지게)"),
]
#: `--set side` — 손을 **옆으로 돌린** 자세들(2026-09-23 추가). 사용자: "집게는 손을 정면으로
#: 보여 줘야 잡힌다". 정면 녹화(위 POSES)에는 옆을 본 장면이 거의 없어 이 실패를 잴 수 없었다.
#: 손날(새끼 쪽 옆면)이나 손등 쪽으로 반쯤 돌린 채 찍는다 — 이름 끝의 _side 로 정면 것과 구분한다.
SIDE_POSES = [
    ("flat_side", "손을 쫙 펴고 엄지를 검지 옆에 붙인 채, 손을 옆으로 돌린다 (손날이 카메라를 향할 만큼, 반쯤~거의 옆)"),
    ("spread_side", "엄지만 옆으로 벌린 채(L자), 손을 옆으로 돌린다"),
    ("pinch_side", "엄지 끝과 검지 끝을 맞댄 채(집게), 손을 옆으로 돌린다"),
    ("thumb_front_side", "엄지만 손바닥 앞으로 내민 채, 손을 옆으로 돌린다"),
    ("oppose_side", "엄지 끝을 새끼손가락 뿌리에 댄 채, 손을 옆으로 돌린다"),
    ("pinch_turn", "집게를 한 채로 손을 정면 → 옆 → 정면으로 천천히 돌린다 (8초 동안 반복)"),
]
POSE_SETS = {"front": POSES, "side": SIDE_POSES}

WINDOW_NAME = "record_hand_poses"
READY_SEC = 3.0
RECORD_SEC = 8.0
PREP_LABEL = "-"


def _header(with_depth=False):
    return ",".join(["t_unix", "detected"]
                    + [f"lm{i}_{a}" for i in range(21) for a in "xyz"]
                    + ["frame_w", "frame_h"]
                    + [f"wl{i}_{a}" for i in range(21) for a in "xyz"]
                    + ([f"d3{i}_{a}" for i in range(21) for a in "xyz"] if with_depth else [])
                    + ["pose"]) + "\n"


class WebcamSource:
    """평소 텔레옵과 같은 웹캠. 거울 모드로 뒤집은 사진을 준다."""

    def __init__(self):
        self.cap, fmt = camera_caps.open_camera(
            VISION_CAMERA_INDEX, backend_name=VISION_CAMERA_BACKEND,
            width=VISION_CAMERA_WIDTH, height=VISION_CAMERA_HEIGHT,
            fps=VISION_CAMERA_FPS, fourcc=VISION_CAMERA_FOURCC,
            min_fps=VISION_CAMERA_MIN_FPS)
        if self.cap is None:
            raise RuntimeError(f"카메라 {VISION_CAMERA_INDEX} 열기 실패 — 리포 루트 .env 의 "
                               "RTAUTO_VISION_CAMERA_INDEX 를 0, 1, 2 순으로 바꿔 볼 것.")
        self.size = (fmt.width, fmt.height)
        self.text = f"웹캠 {fmt.text} (카메라 {fmt.index}번)"

    def read(self):
        """(뒤집은 컬러, 뒤집은 깊이 또는 None, 초점·중심 또는 None). 실패하면 None."""
        ok, frame = self.cap.read()
        return (cv2.flip(frame, 1), None, None) if ok else None

    def close(self):
        self.cap.release()


class D405Source:
    """D405 컬러 + 컬러에 맞춘 깊이. 깊이를 줄이지 않는다(관절 화소와 1:1 로 맞아야 한다)."""

    def __init__(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "d405"))
        import d405_stream
        self.stream = d405_stream.open_depth(color=True, filters=False)
        (depth, color), intr = self._first(d405_stream.WARMUP_FRAMES)
        self.size = (color.shape[1], color.shape[0])
        self.text = "D405 {}x{} (깊이 {}x{})".format(*self.size, depth.shape[1], depth.shape[0])

    def _first(self, warmup):
        got, intr = self.stream.frames(count=1, warmup=warmup)
        self._intr = intr
        return got[-1], intr

    def read(self):
        got, intr = self.stream.frames(count=1, warmup=0)
        if not got or got[-1][1] is None:
            return None
        depth, color = got[-1]
        intr = intr or self._intr
        return (cv2.flip(color, 1), cv2.flip(depth, 1),
                (intr.fx, intr.fy, intr.ppx, intr.ppy))

    def close(self):
        self.stream.close()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="자세를 안내하며 손 관절 점을 기록")
    ap.add_argument("--set", choices=sorted(POSE_SETS), default="front",
                    help="front=정면 자세 10가지(기본) / side=손을 옆으로 돌린 자세 6가지")
    ap.add_argument("--camera", choices=("webcam", "d405"), default="webcam",
                    help="webcam=평소 텔레옵 웹캠(기본) / d405=D405 컬러+깊이(관절 입체 위치도 기록)")
    args = ap.parse_args()
    poses = POSE_SETS[args.set]
    hands = mp.solutions.hands.Hands(      # vision_node_dg5f.py 와 같은 설정
        model_complexity=1, max_num_hands=1,
        min_detection_confidence=0.6, min_tracking_confidence=0.6)
    try:
        src = D405Source() if args.camera == "d405" else WebcamSource()
    except Exception as e:                    # 카메라가 없거나 다른 프로그램이 쥐고 있음
        print(f"[오류] {e}")
        return 1
    with_depth = args.camera == "d405"
    print(f"[카메라] {src.text}")

    # 창은 화면에 맞는 크기로(RTAUTO_VISION_PREVIEW_WIDTH, 기본 1280) — 2560x1440 웹캠을
    # 원본 크기로 띄우면 모니터를 넘는다(2026-09-23 사용자: "창이 너무 크다"). 모서리를 끌어
    # 크기를 바꿀 수도 있다.
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(WINDOW_NAME, *camera_caps.preview_size(
        src.size[0], src.size[1], VISION_PREVIEW_WIDTH))

    log_path = unique_log_path("handposes_d405" if with_depth else "handposes")
    nan63 = ["nan"] * 63
    zeros63 = ["0"] * 63
    counts = {}
    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(_header(with_depth))
        quit_all = False
        for n, (pose, text) in enumerate(poses, 1):
            print(f"\n[{n}/{len(poses)}] {text}")
            print(f"        준비 {READY_SEC:.0f}초 → 기록 {RECORD_SEC:.0f}초 "
                  "(기록 중엔 자세를 유지한 채 손을 조금씩 돌리고 기울일 것)")
            t_start = time.time()
            n_det = 0
            n_depth = 0
            while True:
                got = src.read()
                if got is None:
                    continue
                frame, depth, intr = got      # 둘 다 이미 거울 모드로 뒤집혀 있다
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
                    dcoords = []
                    if with_depth:
                        pts3, ok3 = depth_landmarks.landmarks_3d(
                            [(lm.x, lm.y) for lm in hl.landmark], depth, *intr, mirror=True,
                            near=D405_NEAR_M, far=D405_FAR_M)
                        dcoords = [",".join(f"{v:.5f}" for v in p) for p in pts3]
                        if recording and ok3.all():
                            n_depth += 1
                    log_f.write(f"{now:.3f},1," + ",".join(coords) + f",{w},{h},"
                                + ",".join(wcoords)
                                + ("," + ",".join(dcoords) if with_depth else "")
                                + f",{label}\n")
                    if recording:
                        n_det += 1
                else:
                    log_f.write(f"{now:.3f},0," + ",".join(zeros63) + f",{w},{h},"
                                + ",".join(zeros63)
                                + ("," + ",".join(nan63) if with_depth else "")
                                + f",{label}\n")

                if recording:
                    msg, color = f"REC {pose}  {READY_SEC + RECORD_SEC - el:4.1f}s", (0, 0, 255)
                else:
                    msg, color = f"GET READY: {pose}  {READY_SEC - el:3.1f}s", (0, 200, 255)
                cv2.putText(frame, f"[{n}/{len(poses)}] {msg}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                cv2.putText(frame, "s: skip   q / X: quit", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.imshow(WINDOW_NAME, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("s"):
                    print("        → 건너뜀")
                    break
                if key == ord("q") or cv_window.closed(WINDOW_NAME):
                    quit_all = True
                    break
            counts[pose] = n_det
            print(f"        손이 잡힌 장면 {n_det}개"
                  + (f", 그중 21개 관절 깊이를 다 읽은 장면 {n_depth}개" if with_depth else ""))
            if quit_all:
                print("[중단] q — 여기까지 저장한다.")
                break

    src.close()
    cv2.destroyAllWindows()
    print(f"\n[끝] 저장: {log_path}")
    weak = [p for p, c in counts.items() if c < 60]
    if weak:
        print(f"⚠️ 손이 잡힌 장면이 60개보다 적은 자세: {', '.join(weak)} — "
              "손이 화면에 다 들어오게 하고 다시 찍는 것이 좋다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
