# -*- coding: utf-8 -*-
"""DG5F 비전 노드: 웹캠 → MediaPipe → 20관절 각도[deg] → One Euro → UDP.

svh/vision_node.py의 단일 카메라 경로를 DG5F 20채널용으로 개조.
  - 패킷(v3): float32 × 25, little-endian ('<25f')
    [0..19] DG5F 관절각[deg] / [20..22] 엄지끝 정규화좌표 / [23] 핀치 플래그
    / [24] 엄지-검지 끝거리 비율(연속) — Unity 핀치 연속 블렌딩용
  - 포트: 5006 (SVH 5005와 공존 — 동시 실행 가능)
  - 로그: 실행마다 새 CSV (logs/vision_dg5f_YYYYMMDD_HHMM.csv) — 덮어쓰기 함정 방지
  - occlusion 시 마지막 유효값 hold (SVH와 동일 정책)

사용: python vision_node_dg5f.py [left|right] [--map=direct|ratio] [--bridge]
      (기본 right·direct, 종료: 미리보기 창에서 q)
      왼손 모델 구동 시 'left' — 미러 채널 부호 반전 적용. 웹캠에도 왼손을 보여줄 것.
      --map=direct(기본): 사람 관절각을 로봇각으로 1:1 직접 전송(로봇 사용범위로 clamp).
      --map=ratio       : 사람각을 [사람min,사람max]→0~1 비율로 바꿔 [로봇min,로봇max]에 실어 전송
                          (로봇 범위=URDF 리밋, dg5f_angles.RATIO_ROBOT_RANGE로 전환). 정규화라
                          보정 신선도 민감 — 관절을 끝까지 안 움직인 보정이면 재보정 권장.
      --bridge: 같은 패킷을 실물 SDK 브리지(dg5f_sdk_bridge.py, 포트 BRIDGE_PORT)에도 동시 송신
                — Unity 트윈과 실물 그리퍼를 한 스트림으로 함께 구동.
"""
import os
import socket
import struct
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_IP, PORT_DG5F_SIM, PORT_DG5F_BRIDGE

from one_euro_filter import OneEuroFilter
from dg5f_angles import (compute_raw, map_to_dg5f, compute_thumb_tip, landmarks_to_xyz,
                         compute_finger_tips, compute_wrist_tip_vectors,
                         CHANNEL_NAMES, PINCH_ON, PINCH_OFF,
                         PACKET_FMT, TIP_FINGERS, WRIST_TIP_FINGERS)
from dg5f_paths import unique_log_path

# ------------------------- 설정 -------------------------
CAM_INDEX = 0                 # 프레임 크기는 카메라 기본값(640x480@30)을 그대로 쓴다 —
                              # 강제 설정 상수를 두지 않는 이유는 cap 생성부 주석 참조
UNITY_PORT = PORT_DG5F_SIM     # ⚠️ SVH(5005)와 다른 포트 — 공존용. 값은 config/rtauto_config.py 참조
BRIDGE_PORT = PORT_DG5F_BRIDGE  # --bridge 시 실물 SDK 브리지(dg5f_sdk_bridge.py)에도 같은 패킷 송신
SEND_HZ_CAP = 120
LOG_EVERY_SEC = 0.5
# 경로 규칙은 dg5f_paths가 소유 — 초 단위 + 중복 시 접미사라 덮어쓰기 불가
LOG_CSV = unique_log_path("vision_dg5f")
# One Euro: 값 단위가 deg(0~115)라 SVH(rad) 대비 beta를 1/57 스케일로 낮춤.
# min_cutoff 1.0→0.6 (2026-07-13 라이브: 엄지 대향 지터 1.1°/프레임 → 저속 지터 억제 강화)
FILTER_FREQ, FILTER_MIN_CUTOFF, FILTER_BETA = 30.0, 0.6, 0.0005
# 엄지 tip 위치(정규화 0~1) 전용 — §25-4(2026-07-15): 정지 중 노이즈가 초당 0.2유닛(2.6cm)
# 저속 드리프트라 min_cutoff 0.6Hz는 전부 통과(입력 2.6=필터후 2.6cm 실측), beta 0.001은
# 속도보상 무력. → min_cutoff 0.15(드리프트 차단) + beta 0.5(의도 동작 속도 1~3유닛/s에서
# 컷오프를 0.6~1.7Hz로 열어 지연 방지). 떨리면 min_cutoff↓, 굼뜨면 beta↑ 순으로 튜닝.
TIP_MIN_CUTOFF, TIP_BETA = 0.15, 0.5
# 각도(관절 프록시) 계산에 쓸 랜드마크 선택 (2026-07-21 실험):
#   True  = multi_hand_world_landmarks (미터단위 실제 3D, 깊이 정확) — MCP·엄지 대향의 깊이 오차 개선 목적
#   False = multi_hand_landmarks (이미지 정규화, z 부실) — 기존 동작
#   ⚠️ world 프레임은 이미지와 z/손대칭 방향이 다를 수 있어 벌림·엄지 들림의 '부호'가 뒤집힐 수 있음.
#      라이브에서 방향 반대면 ANGLE_Z_FLIP=True로 z축만 뒤집어 맞춘다(핀치·리치·그리기는 이미지 유지).
# 2026-07-22: True→False. 월드 landmark가 평평한 손가락을 z노이즈로 굽은 것처럼(15~27°) 잡아
#   ① 손 펴도 로봇 손가락이 굽어 있고(rest 오프셋) ② pip/dip 뒤꺾임·앞굽힘 부실이 생겼음.
#   보정(calibrate_dg5f.py)도 이미지 landmark 기준이라 False가 보정과 일치(재보정 불필요).
#   ⚠️ 엄지 대향(1_2) 깊이가 얕아지면 THUMB_OPP_RATIO_HI↓ / 방향 반대면 THUMB_OPP_SIGN 뒤집기.
USE_WORLD_LANDMARKS = False
ANGLE_Z_FLIP = False
# --------------------------------------------------------


# landmarks_to_xyz는 dg5f_angles가 소유한다(2026-07-28 통합) — 종횡비 등방 보정 포함.
#   ⚠️ 여기에 사본을 되살리지 말 것. 보정(calibrate)과 라이브가 다른 좌표계를 쓰게 된다
#   (한 곳만 값이 달라 어긋났던 07-27 MP_MODEL_COMPLEXITY 사고와 같은 구조).


def main():
    args = [a.lower() for a in sys.argv[1:]]
    to_bridge = "--bridge" in args
    # --map direct|ratio : 관절 매핑 방식 선택(기본 direct=1:1 직접, ratio=0~1 비율 정규화).
    #   ratio는 [사람min,사람max]→[0,1]→[로봇min,로봇max] 매핑(dg5f_angles.map_to_dg5f 참조).
    map_mode = "direct"
    for a in args:
        if a.startswith("--map="):
            map_mode = a.split("=", 1)[1]
    if map_mode not in ("direct", "ratio"):
        print(f"[오류] --map 은 direct/ratio 만 가능: {map_mode}")
        return
    pos = [a for a in args if not a.startswith("--")]
    hand = pos[0] if pos else "right"
    if hand not in ("right", "left"):
        print(f"[오류] 인자는 left/right만 가능: {hand}")
        return
    print(f"[vision_node] hand={hand}  map_mode={map_mode}"
          + (f"  robot_range={__import__('dg5f_angles').RATIO_ROBOT_RANGE}" if map_mode == "ratio" else ""))
    # 동일 패킷을 여러 수신자에 송신 — Unity 트윈은 항상, 실물 브리지는 --bridge 시에만
    targets = [(UNITY_IP, UNITY_PORT)]
    if to_bridge:
        targets.append((UNITY_IP, BRIDGE_PORT))
    hands = mp.solutions.hands.Hands(
        model_complexity=1, max_num_hands=1,
        min_detection_confidence=0.6, min_tracking_confidence=0.6)

    # ⚠️ cap.set() 을 추가하지 말 것. 2026-07-27 실측(4회 반복, 이 웹캠 + Windows MSMF):
    #    FOURCC/W/H/FPS 4개를 넣으면 시작에 6.3~18.9초가 붙는데(set 하나당 2~4.3초)
    #    read 지연·해상도·fps는 넣든 안 넣든 33ms / 640x480 / 30fps로 **완전히 동일**했다.
    #    카메라 기본값이 이미 640x480@30이고, MSMF는 set(FOURCC, MJPG)에 False를 반환(무시)한다.
    #    즉 순수 손해. 해상도를 정말 바꿔야 하면 그때 set 하나만 넣고 시작시간을 재볼 것.
    cap = cv2.VideoCapture(CAM_INDEX)

    filters = {n: OneEuroFilter(freq=FILTER_FREQ, min_cutoff=FILTER_MIN_CUTOFF,
                                beta=FILTER_BETA) for n in CHANNEL_NAMES}
    tip_filters = [OneEuroFilter(freq=FILTER_FREQ, min_cutoff=TIP_MIN_CUTOFF,
                                 beta=TIP_BETA) for _ in range(3)]
    # 손가락 리치벡터(v4 [25..36]) — 엄지 tip과 같은 노이즈 성격(정규화 위치)이라 §25-4
    # 튜닝값(TIP_MIN_CUTOFF/TIP_BETA)을 그대로 쓴다. 각도 채널 필터와 섞지 말 것(단위 다름).
    finger_tip_filters = [OneEuroFilter(freq=FILTER_FREQ, min_cutoff=TIP_MIN_CUTOFF,
                                        beta=TIP_BETA) for _ in range(3 * len(TIP_FINGERS))]
    # 손목→끝 벡터(v5 [37..51]) — 같은 정규화 위치 노이즈 성격이라 tip 튜닝값(§25-4) 재사용.
    wrist_tip_filters = [OneEuroFilter(freq=FILTER_FREQ, min_cutoff=TIP_MIN_CUTOFF,
                                       beta=TIP_BETA) for _ in range(3 * len(WRIST_TIP_FINGERS))]
    pinch_filter = OneEuroFilter(freq=FILTER_FREQ, min_cutoff=FILTER_MIN_CUTOFF,
                                 beta=0.001)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_send = last_log = 0.0
    last_valid = None
    last_raw = [0.0] * 20   # v6: 마지막 유효 20채널 라디안 원값(occlusion hold + 패킷 [52..71])
    pinch_on = False  # 핀치 히스테리시스 상태 (걸림 <PINCH_ON, 풀림 >PINCH_OFF)

    # unique_log_path가 logs/ 생성 + 중복 회피까지 끝냄 (덮어쓰기 구조적 불가)
    log_f = open(LOG_CSV, "w", encoding="utf-8")
    # 리치벡터·핀치도 기록 — 없으면 Unity 쪽 thumbik/fingerik CSV가 사라지는 순간 그 세션의
    # 손끝 분석이 영영 불가능해진다(2026-07-16 실제로 라이브 로그를 잃고 재분석 못 함).
    # 컬럼은 **뒤에만 추가** — analyze_teleop이 이름으로 읽어(v[f"filt_{name}"]) 위치 무관하지만
    # 앞에 끼우면 사람이 옛 로그와 눈으로 비교할 때 헷갈린다.
    tip_cols = [f"tip_{a}" for a in "xyz"] + ["pinch_on", "pinch_d"]
    for name, _ in TIP_FINGERS:
        tip_cols += [f"{name}_{a}" for a in "xyz"]
    for name, _ in WRIST_TIP_FINGERS:                        # v5 손목→끝 벡터
        tip_cols += [f"wt_{name}_{a}" for a in "xyz"]
    log_f.write(",".join(["t_unix", "detected"]
                         + [f"raw_{n}" for n in CHANNEL_NAMES]
                         + [f"filt_{n}" for n in CHANNEL_NAMES]
                         + tip_cols) + "\n")

    print(f"[시작] DG5F vision (hand={hand}) → "
          + ", ".join(f"{ip}:{port}" for ip, port in targets) + " (종료: q)")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.flip(frame, 1)  # 거울 모드(보기 편의, 각도 계산 무관)
        res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        now = time.time()
        mapped = None
        if res.multi_hand_landmarks:
            mp.solutions.drawing_utils.draw_landmarks(
                frame, res.multi_hand_landmarks[0],
                mp.solutions.hands.HAND_CONNECTIONS)
            xyz = landmarks_to_xyz(res.multi_hand_landmarks[0], frame.shape)
            # 각도 계산 전용 랜드마크: world면 깊이 정확(핀치·리치·그리기는 이미지 xyz 유지).
            xyz_ang = xyz
            if USE_WORLD_LANDMARKS and res.multi_hand_world_landmarks:
                # world는 미터 단위 손 중심 좌표 — 종횡비 왜곡이 없어 보정 대상이 아니다
                xyz_ang = landmarks_to_xyz(res.multi_hand_world_landmarks[0], None)
                if ANGLE_Z_FLIP:
                    xyz_ang = xyz_ang.copy(); xyz_ang[:, 2] *= -1.0
            raw = compute_raw(xyz_ang)                      # 라디안 원값(프록시 출력)
            mapped = map_to_dg5f(raw, hand, map_mode)       # deg (map_mode: direct 1:1 / ratio 0~1정규화)
            tip, pinch_d = compute_thumb_tip(xyz)           # v2: 엄지끝 위치(정규화)+끝거리
            if pinch_on:
                pinch_on = pinch_d < PINCH_OFF   # 풀림은 더 멀어져야 (히스테리시스)
            else:
                pinch_on = pinch_d < PINCH_ON
            ftips = compute_finger_tips(xyz)                 # v4: 손가락 리치벡터 4×3
            wtips = compute_wrist_tip_vectors(xyz)           # v5: 손목→끝 벡터 5×3
            tip_f = [f(v) for f, v in zip(tip_filters, tip)]
            ftips_f = [f(v) for f, v in zip(finger_tip_filters, ftips)]
            wtips_f = [f(v) for f, v in zip(wrist_tip_filters, wtips)]
            vals = ([filters[n](v) for n, v in zip(CHANNEL_NAMES, mapped)]
                    + tip_f + [1.0 if pinch_on else 0.0]
                    + [pinch_filter(pinch_d)]
                    + ftips_f + wtips_f)
            last_valid = vals
            last_raw = list(raw)    # v6: 라디안 원값 보존(패킷 [52..71], occlusion 시 hold)
        elif last_valid is not None:
            vals = last_valid                                # occlusion hold
        else:
            vals = None

        if vals is not None:
            r = mapped if mapped is not None else vals[:20]
            # 각도는 deg라 .3f로 충분, 리치벡터는 0~1 정규화라 .4f (Unity CSV의 F4와 맞춤)
            log_f.write(f"{now:.3f},{1 if mapped is not None else 0},"
                        + ",".join(f"{v:.3f}" for v in r) + ","
                        + ",".join(f"{v:.3f}" for v in vals[:20]) + ","
                        + ",".join(f"{v:.4f}" for v in vals[20:]) + "\n")
            if (now - last_send) >= (1.0 / SEND_HZ_CAP):
                # 패킷 = vals(52) + 라디안 원값(20) = 72 float (v6). CSV는 vals(52)만 그대로 기록.
                pkt = struct.pack(PACKET_FMT, *(vals + last_raw))
                for addr in targets:
                    sock.sendto(pkt, addr)
                last_send = now
                if now - last_log >= LOG_EVERY_SEC:
                    # |thumb|·|idx| = 펴짐 비율 — 쭉 폈을 때 1.0 근처여야 한다(§26 판정선).
                    # 못 미치면 해당 직진도 상한(DEFAULT_THUMB/FINGER_STRAIGHT)을 낮출 것.
                    print("[send]", " ".join(f"{v:5.1f}" for v in vals[:4]),
                          f"| tip ({vals[20]:.2f},{vals[21]:.2f},{vals[22]:.2f})"
                          f" pinch={vals[23]:.0f} d={vals[24]:.2f}"
                          f" | |thumb|={np.linalg.norm(vals[20:23]):.2f}"
                          f" |idx|={np.linalg.norm(vals[25:28]):.2f}")
                    # 20채널 전체 전 구간 추적(손가락별로 묶어 출력):
                    #   raw = 프록시 라디안 원값 / mapped = 매핑 degree(좌수 미러 포함) /
                    #   sent(filt) = One-Euro 필터 후 실제 UDP 전송값(= Unity 수신 rx와 같아야 함).
                    if mapped is not None:
                        for idx, lbl in enumerate(CHANNEL_NAMES):
                            print(f"[{idx//4+1}_{idx%4+1} {lbl:11s}] raw={raw[idx]:+.4f}rad "
                                  f"({np.degrees(raw[idx]):+6.1f}deg) → mapped {mapped[idx]:+6.1f}deg "
                                  f"→ sent(filt) {vals[idx]:+6.1f}deg")
                    last_log = now

        cv2.imshow("dg5f vision (q to quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    sock.close()
    log_f.close()
    print(f"[종료] 로그: {LOG_CSV}")


if __name__ == "__main__":
    main()
