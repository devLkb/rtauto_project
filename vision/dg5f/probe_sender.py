# -*- coding: utf-8 -*-
"""웹캠 없이 DG5F 텔레옵 배선을 결정적으로 검증하는 프로브 송신기.

지정한 포즈의 20채널 패킷을 50Hz로 송신한다. Unity Play 중에 실행해
xDrive.target이 기대값으로 들어가는지 확인하는 용도 (SVH 프로브 패킷 검증 패턴).

사용:
  python probe_sender.py fist          # 주먹 (오른손 모델)
  python probe_sender.py open          # 펴기
  python probe_sender.py cycle         # 주먹↔펴기 2초 주기 반복
  python probe_sender.py oktip         # v2 핀치 스냅 검증 (엄지 IK → 검지 끝 1.2cm)
  python probe_sender.py tipfar        # v3 리치 복원 검증 (핀치 해제, 펴짐 75% 목표)
  python probe_sender.py tipmax        # 펴짐 100% → 목표가 정확히 robotThumbMaxReach
  python probe_sender.py tipover       # |n|=1.4 위반 패킷 → Unity 안전망 클램프 검증
  python probe_sender.py idxmax        # v4 검지 IK: 펴짐 100% 손가락 방향 → 검지 완전 폄
  python probe_sender.py idxfar        # v4 검지 IK: 펴짐 75%
  python probe_sender.py idxabd        # v4 검지 IK: 측면 성분 큰 목표 → 벌림(2_1) 구동 검증
  python probe_sender.py idxcurl       # v4 검지 IK: 법선(손바닥) 쪽 → 굽힘
  python probe_sender.py okboth        # v4 핀치+검지 IK 동시 (정적) → 두 손끝 접촉 거리 검증
  python probe_sender.py okmove        # okboth 동적판: 검지 목표 45°↔60° 왕복 → 관통 재현(정적으론 재현 불가)
  python probe_sender.py fist left     # 왼손 모델용 (미러 채널 부호 반전)
  (Ctrl+C 종료)

⚠️ 리치벡터(tip*/idx*)는 해부학 좌표계 값이라 **좌우 미러 대상이 아니다** — mirror_left는
   관절각 20채널에만 적용한다(해부학 프레임이 좌우 대칭 정의라 좌/우 불변, §20-2).
"""
import math
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_IP, PORT_DG5F_SIM

from dg5f_angles import CHANNEL_NAMES, LEFT_MIRROR_CHANNELS

UNITY_PORT = PORT_DG5F_SIM

#         엄지: cmc opp  mcp ip | 검지: abd mcp pip dip | 중지 | 약지 | 새끼: cmc lat mcp pip
# (오른손 관절공간 기준 — left는 mirror_left가 변환. 새끼 slot17=5_2 측면은 항상 0)
OPEN = [0.0, 0.0, 0.0, 0.0,   0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0,   0.0, 0.0, 0.0, 0.0,   0.0, 0.0, 0.0, 0.0]
FIST = [40.0, -80.0, 60.0, 60.0,   0.0, 100.0, 80.0, 70.0,
        0.0, 100.0, 80.0, 70.0,    0.0, 95.0, 80.0, 70.0,   0.0, 0.0, 80.0, 70.0]
OK = [0.0, -80.0, 40.0, 30.0,   0.0, 62.0, 52.0, 38.0,
      0.0, 0.0, 0.0, 0.0,       0.0, 0.0, 0.0, 0.0,   0.0, 0.0, 0.0, 0.0]

# --- v4 검지 IK 프로브 ---
# 엄지 주차 자세(리치3 + 핀치0 + 끝거리0.8) = tipfar와 동일 — 검지 검증 중 엄지를 안정시킨다.
THUMB_PARK = [0.25, 0.55, 0.45, 0.0, 0.8]
# 검지 리치벡터 (해부학 축 ex=손바닥법선 / ey=측면(+가 검지쪽) / ez=손가락방향).
# 크기 = 펴짐 비율(직진도) 0~1 — Unity가 가상앵커 + 방향 × 비율 × 그 방향 최대도달로 복원.
#
# ⚠️ 값을 **지어내지 말 것**. 전부 합성 손 포즈(test_v4_tips.make_hand)에서 뽑아 옮긴 것.
#    2026-07-16 두 번 데임: ①임의값으로 만들었더니 도달 불가 목표 ②합성 손의 굽힘 회전축을
#    아무렇게나 잡아 ex가 음수(손등 쪽)로 나옴. **굽힘은 ex가 양수**(손바닥 쪽)다 —
#    로봇 검지 FK 실측(Unity, 2026-07-16): 굽힘 30°→ex=+0.644 / 60°→ex=+0.624.
#    로봇 2_2 리밋이 [0,115°] 굽힘 전용이라 ex 음수 목표는 영원히 도달 못 하고 damper가
#    최선 자세에 정지 → IK 결함으로 오독하기 쉽다(실제로 오독할 뻔했음).
IDX_MODES = {
    "idxmax":  [0.000, 0.000, 1.000],   # 굽힘0 벌림0     |n|=1.00 → 검지 완전 폄
    "idxfar":  [0.805, 0.000, 0.465],   # 굽힘30°         |n|=0.93
    "idxabd":  [0.000, 0.342, 0.940],   # 벌림20° 굽힘0   |n|=1.00 → 벌림 2_1 구동 검증
    "idxcurl": [0.589, 0.000, -0.340],  # 굽힘60°         |n|=0.68 → 깊은 굽힘
    "idxgrip": [0.848, 0.051, 0.141],   # 벌림20°+굽힘40° |n|=0.86 → 복합(파지 근사)
}


def mirror_left(vals):
    return [-v if n in LEFT_MIRROR_CHANNELS else v
            for v, n in zip(vals, CHANNEL_NAMES)]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    hand = sys.argv[2].lower() if len(sys.argv) > 2 else "right"
    fist = mirror_left(FIST) if hand == "left" else FIST
    open_ = mirror_left(OPEN) if hand == "left" else OPEN
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[probe_sender] mode={mode} hand={hand} → {UNITY_IP}:{UNITY_PORT} (Ctrl+C 종료)")
    t0 = time.time()
    try:
        while True:
            if mode == "fist":
                vals = fist
            elif mode == "open":
                vals = open_
            elif mode == "ok":
                vals = mirror_left(OK) if hand == "left" else OK
            elif mode == "oktip":
                # v2 핀치 스냅 검증: 검지만 OK 컬, 핀치 플래그 1 → 엄지 IK가 검지 끝으로
                # tip 3개 = 체인 정규화 리치벡터(2026-07-14 의미 변경, 핀치 우선이라 무시됨)
                base = mirror_left(OK) if hand == "left" else OK
                vals = base + [0.25, 0.55, 0.45, 1.0]
            elif mode == "tipfar":
                # v3 리치 복원 검증(§26 방향별 도달): 핀치 해제(끝거리비 0.8).
                # 리치 크기 |(0.25,0.55,0.45)|≈0.75 = "펴짐 비율 75%" →
                # 로봇 엄지 끝이 가상앵커에서 0.75×(그 방향 테이블 최대도달) 지점에 수렴해야 함
                base = mirror_left(OPEN) if hand == "left" else OPEN
                vals = base + [0.25, 0.55, 0.45, 0.0, 0.8]
            elif mode == "tipmax":
                # 펴짐 100%: |(0.30,0.36,0.88)|≈1.00 → 목표가 그 방향 작업공간 경계에
                # 찍히고 로봇 엄지가 그 방향으로 완전히 뻗어야 함(§26 완료기준:
                # 사람 100% 폄 = 로봇 100% 폄. 시각 확인: 노란공이 완전 폄 팁 위치와 일치)
                base = mirror_left(OPEN) if hand == "left" else OPEN
                vals = base + [0.30, 0.36, 0.88, 0.0, 0.8]
            elif mode == "tipover":
                # 계약 위반 패킷(|n|=1.4>1, 구버전 송신기/오보정 상황 재현) —
                # Python은 송신 전 클램프하므로 정상 경로에선 안 나옴. Unity 쪽
                # 비율 1.0 재클램프 안전망이 경계 위로 깎는지 검증용(tipmax와 같은 지점).
                base = mirror_left(OPEN) if hand == "left" else OPEN
                vals = base + [0.42, 0.50, 1.21, 0.0, 0.8]
            elif mode == "okboth":
                # v4 핀치 + 검지 IK 동시 — **엄지·검지 IK가 서로 관통하는지** 검증.
                # 기존 oktip은 v2(24f)라 검지 IK가 데이터를 못 받아 각도 구동으로 폴백 →
                # 이 상황을 재현 못 한다(2026-07-16 라이브에서 사용자가 발견한 증상).
                # 엄지 리치는 핀치(pinch_w=1)가 덮으므로 값 자체는 무의미 — pinch_d만 임계 아래로.
                base = mirror_left(OK) if hand == "left" else OK
                vals = (base + [0.25, 0.55, 0.45, 1.0, 0.15]
                        + [0.766, 0.000, -0.135] + [0.0] * 9)   # 검지 굽힘 50°(OK 사인 근사)
            elif mode == "okmove":
                # okboth의 **동적** 판. 검지 목표를 굽힘 45°↔60° 사이로 0.5Hz 왕복시켜
                # 검지에 상시 잔여오차를 만든다 — 라이브에서만 나타나던 관통을 재현하는 유일한 방법.
                # 정적 프로브(okboth)는 검지가 목표에 도착해버려(err 0.04cm) 재현 불가.
                base = mirror_left(OK) if hand == "left" else OK
                w = 0.5 * (1.0 + math.sin(2.0 * math.pi * 0.5 * (time.time() - t0)))
                a = IDX_MODES["idxfar"]           # 굽힘 30° 부근
                b = IDX_MODES["idxcurl"]          # 굽힘 60°
                idx = [a[k] + (b[k] - a[k]) * w for k in range(3)]
                vals = base + [0.25, 0.55, 0.45, 1.0, 0.15] + idx + [0.0] * 9
            elif mode in IDX_MODES:
                # v4 검지 IK 프로브 — 패킷 37f: 각도20 + 엄지리치3 + 핀치1 + 끝거리1 + 손가락리치12.
                # 엄지는 tipfar 자세로 고정해 간섭·시각 혼동을 막는다(0,0,0을 주면 목표가
                # 앵커로 붕괴해 엄지가 오므라듦 — 테이블 홀필 주석의 그 상황).
                # 중지/약지/새끼는 0: IK 컴포넌트가 없어 수신기에 담기기만 하고 무시된다.
                base = mirror_left(OPEN) if hand == "left" else OPEN
                vals = base + THUMB_PARK + IDX_MODES[mode] + [0.0] * 9
            else:  # cycle
                vals = fist if int((time.time() - t0) / 2.0) % 2 == 0 else open_
            fmt = "<%df" % len(vals)
            sock.sendto(struct.pack(fmt, *vals), (UNITY_IP, UNITY_PORT))
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
