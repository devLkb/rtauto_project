# -*- coding: utf-8 -*-
"""MediaPipe 랜드마크 원본(21×3) 덤프 프로브 — 손바닥 접힘(5_1 프록시) 검증용.

왜 별도 스크립트인가 (2026-07-18):
  vision_dg5f 로그는 계산된 각도·벡터만 남기고 랜드마크 원본을 버린다. 그래서
  "MediaPipe가 손바닥 5점(0,5,9,13,17)의 접힘/함몰을 실제로 출력하는가"를 기존
  로그로는 검증할 수 없다. 라이브 노드를 건드리지 않고(포트·필터 무영향) 같은
  카메라·MediaPipe 설정으로 랜드마크만 통째로 기록한다.

카메라·모델 설정은 vision_node_dg5f.py와 **동일하게 유지**할 것 — 노이즈 특성이
같아야 여기서 잰 SNR이 라이브 파이프라인에 그대로 적용된다.

사용: python probe_landmarks.py <라벨>   (종료: 미리보기 창에서 q)
  권장 세션 3종(각 20초 이상):
    still     — 손바닥 펴고 카메라 향해 정지 (노이즈 바닥 측정)
    cup       — 평평한 손 ↔ 컵핑(새끼쪽 손바닥 접기) 반복 (신호 측정)
    pinkybend — 손바닥 평평하게 둔 채 새끼만 굽혔다 폈다 (crosstalk 측정)
  분석: python analyze_lmprobe.py [파일들...]  (인자 없으면 최신 세트 자동)

──────────────── 기록 열 (2026-07-28 확장) ────────────────
  t_unix, detected,
  lm0_x..lm20_z   (63)  이미지 랜드마크 — **정규화 원값 그대로**(보정 안 함)
  frame_w, frame_h      그 프레임 실제 크기
  wl0_x..wl20_z   (63)  world 랜드마크(multi_hand_world_landmarks, 미터·손 중심 좌표)

왜 원값을 그대로 남기나:
  라이브 경로(dg5f_angles.landmarks_to_xyz)는 2026-07-28부터 종횡비 등방 보정
  (x, y·H/W, z)을 적용한다. 하지만 **녹화는 보정 전 원값 + 프레임 크기**를 남겨야
  오프라인에서 보정 유무·다른 보정식을 모두 사후 재평가할 수 있다.
  → 이 CSV로 각도를 계산할 땐 y에 frame_h/frame_w를 직접 곱하거나,
    landmarks_to_xyz와 같은 규칙을 적용할 것. 안 하면 라이브와 다른 좌표계가 된다.

왜 world까지 남기나 (2026-07-28):
  MCP 굽힘이 이미지 랜드마크로는 측정 한계에 걸린다. 손바닥을 카메라 정면으로 두면
  MCP 굽힘은 광축(깊이) 방향 운동이고 MediaPipe의 이미지 z가 이를 못 잡는다 —
  실측으로 검지 MCP가 세 가지 계산방식(옛 _bend / 평면투영 _bend_mcp / 평면이탈각)
  **모두 0.58 rad(33°)에서 막혔다**(07-27 녹화 좌·우 각 1200여 프레임).
  world 랜드마크는 미터 단위 3D라 깊이를 더 잘 담을 수 있고 종횡비 왜곡도 없다.
  같은 녹화에 둘을 함께 남겨 두면 오프라인에서 공정 비교가 된다.
  ※ 이 스크립트는 기록만 한다 — 어느 소스를 쓸지는 dg5f_angles가 결정한다.

MCP·자세 비교용 권장 세션(2026-07-28):
    tabletop_front — 손바닥 카메라 정면. ㄱ자(첫 마디만 90°) 검지→중지→약지→새끼
    tabletop_45    — 위와 같은 동작을 손을 카메라에 45° 기울여서
  두 세션을 같은 동작으로 찍어 두면 [이미지 / 이미지+종횡비 / world] × [정면 / 45°]
  전 조합을 재녹화 없이 오프라인 비교할 수 있다.
"""
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp

from dg5f_paths import unique_log_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import VISION_CAMERA_INDEX

# vision_node_dg5f.py와 동일 출처(config/rtauto_config.py + .env) — 카메라가 여러 대라
# 엉뚱한 게 잡히면 여기가 아니라 .env의 RTAUTO_VISION_CAMERA_INDEX를 바꿀 것.
CAM_INDEX = VISION_CAMERA_INDEX
# FRAME_W/FRAME_H는 2026-07-28에 삭제 — cap.set()을 안 쓰므로 쓸 데가 없고,
# 실제 크기는 frame.shape에서 읽어 CSV(frame_w/frame_h)에 그대로 기록한다.


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "free"
    hands = mp.solutions.hands.Hands(
        model_complexity=1, max_num_hands=1,
        min_detection_confidence=0.6, min_tracking_confidence=0.6)

    # ⚠️ cap.set() 을 추가하지 말 것 (2026-07-28 제거). 이 웹캠 + Windows MSMF 실측:
    #    W/H/FPS set 하나당 3.7~3.9초가 붙어 '열기+첫프레임'이 5.11초 → 16.73초가 됐다.
    #    그런데 결과는 넣든 안 넣든 640x480 @30fps / read 33ms로 **완전히 동일**했다
    #    (FOURCC는 MSMF가 아예 무시하고 False를 반환한다 — 0초, 효과도 0).
    #    카메라 기본값이 이미 640x480@30이라 순수 손해였다. vision_node_dg5f.py·
    #    dg5f_teleop_gui.py는 07-27에 같은 이유로 이미 제거된 상태다.
    #    실제 해상도는 frame.shape에서 읽어 쓴다(종횡비 보정도 그 값을 쓴다).
    cap = cv2.VideoCapture(CAM_INDEX)

    log_path = unique_log_path(f"lmprobe_{label}")
    log_f = open(log_path, "w", encoding="utf-8")
    # ⚠️ 열은 **뒤에만 추가**한다 — analyze_lmprobe.py가 이름으로 읽으므로(df[[f"lm{i}_{a}"]])
    #   뒤에 붙이면 옛 로그도 그대로 열리고 새 로그도 옛 분석기로 열린다.
    log_f.write(",".join(["t_unix", "detected"]
                         + [f"lm{i}_{a}" for i in range(21) for a in "xyz"]
                         + ["frame_w", "frame_h"]
                         + [f"wl{i}_{a}" for i in range(21) for a in "xyz"]) + "\n")
    zeros63 = ["0"] * 63

    print(f"[시작] 랜드마크 프로브 (label={label}) → {log_path} (종료: q)")
    t0 = time.time()
    n_frames = n_det = n_world = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.flip(frame, 1)  # vision_node와 동일 (거울 모드)
        res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        now = time.time()
        n_frames += 1
        h, w = frame.shape[0], frame.shape[1]
        if res.multi_hand_landmarks:
            n_det += 1
            hl = res.multi_hand_landmarks[0]
            mp.solutions.drawing_utils.draw_landmarks(
                frame, hl, mp.solutions.hands.HAND_CONNECTIONS)
            # 이미지 랜드마크: 정규화 원값 그대로(보정은 오프라인/라이브 쪽에서) + 프레임 크기
            coords = [f"{v:.6f}" for lm in hl.landmark for v in (lm.x, lm.y, lm.z)]
            # world 랜드마크: 미터·손 중심 좌표. 이미지 검출이 있어도 없을 수 있어 방어적으로 처리.
            if res.multi_hand_world_landmarks:
                n_world += 1
                wl = res.multi_hand_world_landmarks[0]
                wcoords = [f"{v:.6f}" for lm in wl.landmark for v in (lm.x, lm.y, lm.z)]
            else:
                wcoords = zeros63
            log_f.write(f"{now:.3f},1," + ",".join(coords)
                        + f",{w},{h}," + ",".join(wcoords) + "\n")
        else:
            # 미검출 프레임도 남긴다 — 검출률 자체가 "얼마나 민감하게 잡는가"의 일부
            log_f.write(f"{now:.3f},0," + ",".join(zeros63)
                        + f",{w},{h}," + ",".join(zeros63) + "\n")

        cv2.putText(frame, f"{label}  {now - t0:5.1f}s  det {n_det}/{n_frames}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("lmprobe (q to quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    log_f.close()
    print(f"[종료] {n_det}/{n_frames} 프레임 검출 (world {n_world}), 로그: {log_path}")


if __name__ == "__main__":
    main()
