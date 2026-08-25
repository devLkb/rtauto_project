# -*- coding: utf-8 -*-
"""DG5F 텔레오퍼레이션 GUI — 웹캠+MediaPipe로 손을 20관절 각도[deg]로 만들어 UDP로 쏘되,
송신 대상(IP/포트)·모드·보정값(사람 범위)·관절 제한(로봇 범위)·관절 각도(수동)를
**실행 중에 UI로 바꿔** 볼 수 있는 컨트롤 패널.  (headless 버전=vision_node_dg5f.py)

이 파일이 exe 타깃(1단계). 계산 로직은 dg5f_angles를 그대로 재사용 —
  raw = compute_raw(landmarks)            # 사람 관절 프록시(rad)
  mapped = map_to_dg5f(raw, hand, mode)   # 로봇 관절각(deg)  ← UDP로 나가는 값
UI에서 바꾼 값은 dg5f_angles의 모듈 전역(DG5F_CHANNELS / RATIO_LIMIT / 엄지 상수)에
**라이브로 반영**된다(map_to_dg5f가 호출 시점에 그 전역을 읽으므로 재시작 불필요).

패킷은 vision_node와 동일한 v6 <72f>:
  [0..19] 관절각[deg] / [20..22] 엄지 tip / [23] 핀치 / [24] 끝거리비
  / [25..36] 손가락 리치 / [37..51] 손목→끝 / [52..71] 라디안 원값(디버그)
→ Unity Dg5fReceiver(sim)와 dg5f_sdk_bridge(real) 둘 다 그대로 받는다.

────────────────────────── 스레드 구조 (2026-07-27 성능 개편) ──────────────────────────
예전엔 tick() 하나가 Tk 메인 스레드에서 cap.read()(33ms 블로킹) + MediaPipe(10ms) +
PhotoImage 생성(5~13ms)을 다 하고 그 위에 after(20)을 더 얹었다. 그동안 Tk 이벤트 루프가
멈춰서 슬라이더를 드래그하면 콜백이 프레임 뒤에 줄줄이 큐잉됐다(체감 19.5fps).
지금은 3분할 — 각 단계는 '최신 1개만 유지하는' 슬롯으로 연결되고, 밀린 프레임은 버린다:

  [캡처 스레드]  cap.read() 반복        → frame_slot  ─┐
  [처리 스레드]  MediaPipe·매핑·필터·UDP송신          ─┤ 둘 다 UI를 막지 않음
  [메인(Tk)]     결과를 PhotoImage.paste + 판독 갱신  ←┘  프레임당 ~2ms

핵심 규칙 3개:
  1. tk 변수(StringVar 등)는 **메인 스레드만** 만진다(Tcl 인터프리터가 스레드 안전하지 않음).
     워커는 _sync_settings()가 만들어 원자적으로 갈아끼우는 불변 _Settings 스냅샷만 읽는다.
  2. cv2 / mediapipe 임포트는 워커 스레드에서 한다(합쳐 ~4.5초. 최상단에서 하면
     그만큼 창이 안 뜬다). 준비되면 모듈 전역 cv2 / mp 에 채워진다.
  3. cap.set() 은 **쓰지 않는다** — 실측 근거는 _capture_loop 주석 참조.
  4. 송신 경로(sendto)에는 **점4자리 IP만** 넘긴다. 검증은 _sync_settings에서 inet_pton으로
     끝내둔다 — 그러지 않으면 IP를 타이핑하는 중간 문자열('1','19','192','192.')이 전부
     DNS 조회로 들어가 한 번 입력에 10.8초를 멈춘다(실측 근거는 _sync_settings 주석).

────────────────────────── 레이아웃/스크롤 (2026-07-30) ──────────────────────────
  [영상(고정)] [컨트롤 패널 ①~⑥ (Canvas 안, 세로·가로 스크롤)] [수직바]
                                   [수평바]
  [────────────────── 상태바(고정) ──────────────────]
스크롤은 **오른쪽 패널에만** 건다. 전체를 한 Canvas에 넣으면 ⑤·⑥을 보러 내려간 순간
미리보기가 화면 밖으로 나가서 '손을 보며 값을 맞추는' 일 자체가 불가능해진다.
영상 열은 VIDEO_COL_W로 자리를 예약한다 — 창 크기를 잡는 시점엔 영상 라벨이 아직
안내문 크기(≈107px)라, 예약이 없으면 첫 프레임에 라벨이 496px로 커지면서 패널을
창 밖으로 밀어낸다(그 상태가 "오른쪽 UI가 잘린다" = 07-30에 실제로 고친 증상).

────────────────────────── 로그 (2026-07-28 추가) ──────────────────────────
⑤ 체크박스를 켜면 logs/teleop_<초단위>.csv 에 **한 프레임 = 한 행**으로 파이프라인 4개 층을
전부 남긴다(랜드마크 → 사람각 → 로봇각 → UDP 송신값). 상세는 _TeleopLogger 참조.

실행:  <vision venv python> dg5f_teleop_gui.py
"""
import os

# ⚠️ 이 두 줄은 **어떤 import보다 먼저** 와야 한다(matplotlib은 임포트 시점에 백엔드를 정한다).
# mediapipe.solutions.drawing_utils가 모듈 레벨에서 `import matplotlib.pyplot`을 하는데,
# 리눅스 matplotlib의 기본 백엔드는 **TkAgg**다. 우리는 mediapipe를 **워커 스레드**에서
# 임포트하므로(_process_loop) 그 순간 tkinter/backend_tkagg가 워커에서 로드되며 X 연결을
# 건드리고, 메인 스레드의 Tk와 부딪혀 프로세스가 통째로 죽는다(리눅스 실측):
#     [xcb] Unknown sequence number while appending request
#     [xcb] You called XInitThreads, this is not your fault
#     python: xcb_io.c:157: append_pending_request:
#             Assertion `!xcb_xlib_unknown_seq_number' failed.  → Aborted (core dumped)
# Agg(비GUI)로 고정하면 워커에서 tkinter가 **아예 임포트되지 않는다**(실측: TkAgg일 때
# `tkinter in sys.modules`=True → Agg에선 False). 이 GUI는 pyplot을 쓰지 않으니 손실 없음.
# 윈도우에서는 TkAgg여도 죽지 않아 07-30까지 드러나지 않았다.
os.environ.setdefault("MPLBACKEND", "Agg")   # 필요하면 셸에서 MPLBACKEND로 덮어쓸 수 있다

import collections
import json
import socket
import struct
import sys
import threading
import time

import numpy as np
from PIL import Image, ImageTk

import tkinter as tk
from tkinter import ttk, filedialog, font as tkfont, messagebox

from one_euro_filter import OneEuroFilter
from dg5f_paths import unique_log_path
import dg5f_angles as A

# cv2(0.6s) + mediapipe(3.9s) = 창이 뜨기까지의 대기시간. 워커 스레드가 임포트해서
# 여기에 채운다 → 창은 ~1.2초에 뜨고, 그 뒤 백그라운드로 모델이 준비된다.
# ⚠️ 모듈 최상단으로 되돌리지 말 것(그러면 B/C 개편 효과가 통째로 사라진다).
cv2 = None
mp = None

# ------------------------- 기본 설정 (vision_node와 동일 값) -------------------------
CAM_INDEX = 0
CAM_BACKEND = None          # None=OpenCV 기본(Windows=MSMF, 실측 640x480@30 그대로 나옴).
                            # ⚠️ cv2.CAP_DSHOW는 open이 1.2초로 빠르지만 이 웹캠에서
                            #    read()가 504ms(2fps)로 붕괴한다 — 바꾸려면 반드시 재측정.
# exe로 패키징돼 배포되는 독립 실행형 도구라 config/rtauto_config.py(레포 상대 import)에는
# 일부러 의존하지 않는다 — 대신 같은 환경변수 이름을 직접 읽어 값 하나로 통일한다.
# (env var 없으면 아래 기본값. 시작 시 값일 뿐이며 GUI에서 언제든 바꿀 수 있다.)
DEF_SIM_IP = os.environ.get("RTAUTO_UNITY_IP", "127.0.0.1")               # Unity 트윈
DEF_SIM_PORT = int(os.environ.get("RTAUTO_PORT_DG5F_SIM", "5006"))
DEF_REAL_IP = os.environ.get("RTAUTO_UNITY_IP", "127.0.0.1")              # 실물 SDK 브리지
DEF_REAL_PORT = int(os.environ.get("RTAUTO_PORT_DG5F_BRIDGE", "5008"))    # 구 5007 — ZED와 포트 충돌해 변경(config/rtauto_config.py 참조)
SEND_HZ_CAP = 60
FILTER_FREQ, FILTER_MIN_CUTOFF, FILTER_BETA = 30.0, 0.6, 0.0005
TIP_MIN_CUTOFF, TIP_BETA = 0.15, 0.5

DISPLAY_W = 480             # 미리보기 표시 폭(카메라 원본 640 → 세로는 비율 유지).
                            # 640으로 그리면 Tk 전송이 프레임당 7.7ms, 480이면 1.7ms.
                            # 각도 계산은 항상 원본 프레임으로 하므로 전송값과 무관.
DISPLAY_H = DISPLAY_W * 3 // 4   # 4:3 웹캠 기준 표시 높이 — 영상 자리 예약용(초기 창 크기 계산).
VIDEO_PAD = 6               # 미리보기 라벨 내부 여백. ⚠️ 크게 주지 말 것 — 라벨 폭은
                            # 이미지폭+2*VIDEO_PAD+4(테두리)라서, 여백을 키우면 프레임이
                            # 도착한 순간 영상 열이 예약폭(VIDEO_COL_W)을 넘어 컨트롤 패널을
                            # 창 밖으로 밀어낸다(2026-07-30에 padding=40으로 실제 발생:
                            # 라벨 175→564px, 우측 패널이 58px 잘려 가로 스크롤 없이는 안 보였음).
VIDEO_COL_W = DISPLAY_W + 2 * VIDEO_PAD + 4       # 영상 열에 예약하는 폭(=라벨 최종 폭)
UI_HZ = 30                  # UI 리프레시 상한 (카메라 30fps보다 높일 이유 없음)
READOUT_HZ = 10             # ④ 판독 + 상태바 갱신 주기(문자열 포맷 아끼기)
UI_PERIOD_MS = 1000.0 / UI_HZ

N = 20
CH = A.CHANNEL_NAMES                       # 20 채널 이름
JOINT_ID = [f"{i // 4 + 1}_{i % 4 + 1}" for i in range(N)]   # 1_1 .. 5_4

# MediaPipe Hands 모델 정확도(0=경량/빠름, 1=정확/느림).
# ★2026-07-27: 0 → 1. **반드시 probe_landmarks.py·calibrate_dg5f.py·vision_node_dg5f.py와 같아야 한다.**
#   여기만 0이었던 탓에 보정·프로브 녹화(전부 complexity=1)로 뽑은 상수가 라이브와 안 맞았다.
#   실측 차이(같은 사람·같은 자세, 엄지끝↔소지MCP 거리):
#     펴짐    complexity=1: 1.019/1.058  vs  complexity=0: 1.054/1.012   (거의 동일)
#     완전대향 complexity=1: 0.227/0.247  vs  complexity=0: 0.512/0.476   (**2배 차이**)
#   → 경량 모델은 엄지를 손바닥 안쪽까지 깊게 넣지 못한다. 그 결과 THUMB_OPP_D_FULL=0.25가
#     라이브에서 도달 불가가 되어 대향 풀스케일 도달률 0.0%, 명령이 64~68°에서 멈췄다.
#     오른손이 특히 심했던 건 거리 상단이 max 2.006까지 튀어(왼손 1.312) 사각지대가 넓었기 때문.
#   ⚠️ 속도가 문제되면 0으로 내려도 되지만, **그 경우 그 모델로 전부 재보정**해야 한다
#     (보정 파일과 THUMB_OPP_D_* 둘 다). 모델만 바꾸고 상수를 두면 오늘 같은 증상이 재발한다.
MP_MODEL_COMPLEXITY = 1


def _base_dir():
    """exe(frozen)면 실행파일 폴더, 아니면 스크립트 폴더 — 프리셋 저장/로드 기준."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


PRESET_PATH = os.path.join(_base_dir(), "dg5f_gui_preset.json")


# landmarks_to_xyz는 dg5f_angles가 소유한다(2026-07-28 통합) — 종횡비 등방 보정 포함.
#   ⚠️ 여기에 사본을 되살리지 말 것. 보정(calibrate)과 라이브가 다른 좌표계를 쓰게 된다
#   (한 곳만 값이 달라 어긋났던 07-27 MP_MODEL_COMPLEXITY 사고와 같은 구조).


# ------------------------- dg5f_angles 전역에 라이브 반영하는 헬퍼 -------------------------
# 이 함수들은 메인(UI) 스레드에서만 호출된다. 처리 스레드는 같은 전역을 읽지만,
# 갱신 단위가 '리스트 원소 하나에 튜플 하나를 대입'(GIL 하에서 원자적)이라 찢어진 값이
# 나올 수는 없다 — 최악의 경우 슬라이더를 놓은 그 한 프레임이 옛 값으로 나갈 뿐이다.
def _ch_idx(ch):
    return CH.index(ch)


def get_human_range(ch):
    _n, hmn, hmx, _dmn, _dmx, _g = A.DG5F_CHANNELS[_ch_idx(ch)]
    return hmn, hmx


def set_human_range(ch, lo, hi):
    i = _ch_idx(ch)
    n, _hmn, _hmx, dmn, dmx, g = A.DG5F_CHANNELS[i]
    A.DG5F_CHANNELS[i] = (n, lo, hi, dmn, dmx, g)   # map_to_dg5f가 이 리스트를 라이브로 읽음


def get_robot_range(ch):
    """현재 매핑이 참고하는 로봇 [lo,hi](deg). ratio 우선순위(RATIO_LIMIT)를 먼저 보여준다."""
    if ch in A.RATIO_LIMIT:
        return A.RATIO_LIMIT[ch]
    _n, _hmn, _hmx, dmn, dmx, _g = A.DG5F_CHANNELS[_ch_idx(ch)]
    return dmn, dmx


def set_robot_range(ch, lo, hi):
    """로봇 범위를 direct(DG5F_CHANNELS dmin/dmax)·ratio(RATIO_LIMIT) 양쪽에 함께 기록 →
    모드 전환해도 일관. 특수 엄지 채널(cmc/opp)은 전용 상수까지 갱신."""
    i = _ch_idx(ch)
    n, hmn, hmx, _dmn, _dmx, g = A.DG5F_CHANNELS[i]
    A.DG5F_CHANNELS[i] = (n, hmn, hmx, lo, hi, g)   # direct clamp + ratio 폴백
    A.RATIO_LIMIT[ch] = (lo, hi)                    # ratio 최우선
    if ch == "thumb_cmc":                           # |abd|→[fold,spread] 선형(direct/ratio 공통)
        A.THUMB_CMC_FOLD_DEG = lo
        A.THUMB_CMC_SPREAD_DEG = hi
    elif ch == "thumb_opp":                         # 단방향 대향 최대각(ratio 전용 상수)
        A.THUMB_OPP_RATIO_MAX_DEG = hi


# ------------------------- 스레드 간 핸드오프 -------------------------
class _LatestSlot:
    """최신 1개만 유지하는 스레드 간 슬롯. 소비자가 느리면 **오래된 것을 버린다** —
    텔레오퍼레이션에서 밀린 프레임은 가치가 없고(지연만 늘고), 큐로 쌓으면 지연이 무한정
    자란다. 생산자는 절대 블로킹되지 않는다."""

    def __init__(self):
        self._cv = threading.Condition()
        self._item = None
        self._seq = 0

    def put(self, item):
        with self._cv:
            self._item = item
            self._seq += 1
            self._cv.notify_all()

    def wait_new(self, seq, timeout=None):
        """seq 이후의 새 아이템을 기다려 (새 seq, item)을 준다. 타임아웃이면 (seq, None)."""
        with self._cv:
            if self._seq == seq:
                self._cv.wait(timeout)
            if self._seq == seq:
                return seq, None
            return self._seq, self._item

    def peek(self):
        """대기 없이 현재 (seq, item). UI 스레드용 — 절대 블로킹되면 안 된다."""
        with self._cv:
            return self._seq, self._item


class _Settings:
    """처리 스레드가 읽는 설정 스냅샷(불변). tk 변수를 워커에서 직접 .get() 하면
    Tcl 인터프리터를 메인 스레드 밖에서 건드리게 되므로, 평범한 파이썬 값으로 복사해 넘긴다.
    교체는 참조 하나를 대입하는 것으로만 한다(원자적 → 락 불필요)."""
    __slots__ = ("hand", "mapmode", "overrides", "targets")

    def __init__(self, hand, mapmode, overrides, targets):
        self.hand = hand
        self.mapmode = mapmode
        self.overrides = overrides   # {ch_idx: deg} — 워커는 읽기만
        self.targets = targets       # ((ip, port), ...) 파싱 완료 → 송신 경로에서 int() 안 함


class _Result:
    """처리 스레드 → UI 스레드로 넘기는 한 프레임분 결과."""
    __slots__ = ("disp", "detected", "raw", "mapped", "sent")

    def __init__(self, disp, detected, raw, mapped, sent):
        self.disp = disp             # numpy RGB (표시용 축소 프레임, 랜드마크 그려진 상태)
        self.detected = detected
        self.raw = raw               # 20ch 사람 프록시(rad)
        self.mapped = mapped         # 20ch 로봇 각(deg, 필터 전)
        self.sent = sent             # 20ch 필터 후(= 실제 UDP 전송값) / None


class _TeleopLogger:
    """텔레옵 파이프라인 전 구간을 한 CSV에 남기는 로거 (2026-07-28 신설).

    왜 만들었나:
      이 GUI에는 신설(07-23) 이래 로깅이 **아예 없었다**. 그래서 라이브 세션을 사후 분석하려면
      Unity가 받은 rx/act(unity_dg5f_*.csv)만 봐야 했는데, 거기서 이상이 보여도 원인이
      ①랜드마크 노이즈인지 ②프록시 수식인지 ③매핑 상수인지 가릴 수가 없다. 실제로 07-28
      벌림 crosstalk 분석(5_2가 굽힘과 r=0.95)에서 여기서 막혀 결론을 못 냈다.
      → 같은 프레임의 네 층을 한 행에 남겨 층간 책임을 가른다.

    열 구성 (한 행 = 처리 스레드 한 프레임):
      t_unix,detected,hand,mapmode,tx        메타. t_unix는 UTC 초 — Unity 로거와 같은 시계라
                                             unity_dg5f_*.csv / rad_dg5f_*.csv 와 그대로 조인된다.
      lm0_x..lm20_z   (63)  ① MediaPipe 랜드마크 원값(이미지 정규화 좌표, 미검출이면 공란)
      raw_<채널>      (20)  ② 사람 관절 프록시[rad] — A.compute_raw 출력
      mapped_<채널>   (20)  ③ 로봇 관절각[deg] — A.map_to_dg5f 출력(오버라이드·필터 **전**)
      sent_<채널>     (20)  ④ 실제 패킷에 실린 값 — 오버라이드 적용 + OneEuro 필터 **후**
      ※ tx=1은 이 프레임에 sendto가 실제로 나갔다는 뜻. SEND_HZ_CAP(60Hz) 때문에 값은
        준비됐어도 송신은 걸러질 수 있어 sent_*와 별도 열로 둔다.
      ※ 미검출 프레임의 raw_*는 occlusion hold로 **실제 사용된** 직전 값이다(공란 아님).
        그 프레임이 hold인지는 detected=0으로 구분한다.

    스레드 규칙:
      처리 스레드는 deque.append만 한다(포맷·디스크 접촉 없음). 포맷과 flush는 쓰기 전담
      스레드가 맡는다 — 07-27 성능 개편의 "워커는 UI/디스크에 막히지 않는다"를 깨지 않기 위함.
      백로그가 MAX_BACKLOG를 넘으면 **오래된 행부터 버린다**. 로그 때문에 텔레옵이 느려지는
      것보다 로그에 구멍이 나는 편이 낫다(_LatestSlot과 같은 철학). 버린 수는 UI에 표시한다.
      두 스레드가 같은 deque에 popleft를 하지만 append/popleft는 GIL 하에서 원자적이라
      깨지지 않는다 — 경합해도 '어느 행이 버려지는가'만 달라진다.

    파일 경로는 dg5f_paths.unique_log_path가 소유(초 단위 + 중복 시 접미사, 덮어쓰기 불가).
    켜고 끌 때마다 새 파일이 열린다 — 껐다 켜서 앞 세션을 덮는 사고를 원천 차단.

    용량: 30fps × 123열 ≈ 1.2KB/행 → 분당 약 2MB. 길게 켜두고 돌릴 때 참고.
    """

    MAX_BACKLOG = 600      # ≈20초분(30fps). 넘으면 오래된 행부터 폐기.
    FLUSH_EVERY = 100

    def __init__(self):
        self.active = False
        self.path = None
        self.count = 0
        self.dropped = 0
        self._q = collections.deque()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._th = None

    def start(self):
        """새 CSV를 열고 쓰기 스레드를 띄운다. 실패는 OSError로 올린다(호출자가 UI에 알림)."""
        if self.active:
            return self.path
        path = unique_log_path("teleop")        # 디렉터리 생성·중복 회피·자리 선점까지 끝냄
        f = open(path, "w", encoding="utf-8", newline="")
        f.write(",".join(
            ["t_unix", "detected", "hand", "mapmode", "tx"]
            + [f"lm{i}_{a}" for i in range(21) for a in "xyz"]
            + [f"raw_{n}" for n in CH]
            + [f"mapped_{n}" for n in CH]
            + [f"sent_{n}" for n in CH]) + "\n")
        self.path, self.count, self.dropped = path, 0, 0
        self._q.clear()
        self._stop.clear()
        self._wake.clear()
        self._th = threading.Thread(target=self._writer, args=(f,), name="dg5f-log", daemon=True)
        self.active = True                      # log()가 큐에 넣기 시작하는 시점 = 스레드 뜬 뒤
        self._th.start()
        return path

    def log(self, t, detected, hand, mapmode, tx, xyz, raw, mapped, sent):
        """처리 스레드 전용. 절대 블로킹하지 않는다."""
        if not self.active:
            return
        q = self._q
        if len(q) >= self.MAX_BACKLOG:
            try:
                q.popleft()
                self.dropped += 1
            except IndexError:                  # 쓰기 스레드가 먼저 비웠다 — 버릴 게 없으니 그냥 넣는다
                pass
        q.append((t, detected, hand, mapmode, tx, xyz, raw, mapped, sent))
        self._wake.set()

    def stop(self):
        if not self.active:
            return
        self.active = False                     # 새 행 유입 차단 → 남은 큐만 비우면 끝
        self._stop.set()
        self._wake.set()
        if self._th is not None:
            self._th.join(timeout=2.0)          # 파일 close는 쓰기 스레드가 finally에서 한다
            self._th = None

    def _writer(self, f):
        try:
            while True:
                if not self._q:
                    if self._stop.is_set():
                        break
                    self._wake.wait(0.2)
                    self._wake.clear()
                    continue
                try:
                    rec = self._q.popleft()
                except IndexError:              # 처리 스레드의 오버플로 폐기와 경합 — 무해
                    continue
                f.write(self._fmt(rec))
                self.count += 1
                if self.count % self.FLUSH_EVERY == 0:
                    f.flush()
        finally:
            try:
                f.flush()
            finally:
                f.close()

    @staticmethod
    def _fmt(rec):
        t, detected, hand, mapmode, tx, xyz, raw, mapped, sent = rec
        cols = [f"{t:.3f}", "1" if detected else "0", hand, mapmode, "1" if tx else "0"]
        # 미검출 프레임엔 랜드마크가 없다 → 공란(분석 시 NaN). 0으로 채우면 원점에 손이
        # 있었던 것처럼 보여 통계가 오염된다.
        cols += [""] * 63 if xyz is None else [f"{v:.5f}" for v in xyz.reshape(-1)]
        cols += [""] * N if raw is None else [f"{v:.5f}" for v in raw]
        cols += [""] * N if mapped is None else [f"{v:.3f}" for v in mapped]
        cols += [""] * N if sent is None else [f"{v:.3f}" for v in sent]
        return ",".join(cols) + "\n"


class TeleopGUI:
    def __init__(self, root):
        self.root = root
        root.title("DG5F 텔레오퍼레이션 컨트롤")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---- 상태 ----
        self.hand = tk.StringVar(value="right")
        self.mapmode = tk.StringVar(value="ratio")
        self.cam_index = tk.IntVar(value=CAM_INDEX)
        self.sel_ch = tk.StringVar(value=CH[0])
        self.overrides = {}          # {ch_idx: deg}  수동 오버라이드 활성 채널
        self.ov_enabled = tk.BooleanVar(value=False)
        self._loading = False        # 슬라이더 프로그램 세팅 중 콜백 억제
        self._ov_rev = 0             # overrides 변경 감지용(스냅샷 재생성 트리거)

        # ---- 처리 스레드 소유 상태 (UI 스레드에서 만지지 말 것) ----
        self.last_vals = None        # occlusion hold (52ch)
        self.last_raw = [0.0] * N
        self.last_mapped = [0.0] * N
        self.pinch_on = False
        self._filter_freq = FILTER_FREQ
        self._tx_ok = False          # 이 프레임에 sendto가 실제로 나갔나(SEND_HZ_CAP에 걸리면 False)

        # ---- 로거 (메인이 켜고 끄고, 처리 스레드가 넣고, 전용 스레드가 쓴다) ----
        self.logger = _TeleopLogger()

        # ---- 스레드 공용(원자적 대입만) ----
        self.pkt_count = 0
        self.cam_status = "카메라 준비 중…"
        self.cam_fps = 0.0
        self.proc_fps = 0.0
        self.ui_fps = 0.0

        # ---- 필터 (처리 스레드 전용) ----
        self.filters = {n: OneEuroFilter(FILTER_FREQ, FILTER_MIN_CUTOFF, FILTER_BETA) for n in CH}
        self.tip_filters = [OneEuroFilter(FILTER_FREQ, TIP_MIN_CUTOFF, TIP_BETA) for _ in range(3)]
        self.ftip_filters = [OneEuroFilter(FILTER_FREQ, TIP_MIN_CUTOFF, TIP_BETA)
                             for _ in range(3 * len(A.TIP_FINGERS))]
        self.wtip_filters = [OneEuroFilter(FILTER_FREQ, TIP_MIN_CUTOFF, TIP_BETA)
                             for _ in range(3 * len(A.WRIST_TIP_FINGERS))]
        self.pinch_filter = OneEuroFilter(FILTER_FREQ, FILTER_MIN_CUTOFF, 0.001)

        # ---- 네트워크 ----
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_send = 0.0

        # ---- 스레드 배관 ----
        self._stop = threading.Event()
        self._ev_cv2 = threading.Event()     # cv2 임포트 완료 신호(캡처→처리)
        self.frame_slot = _LatestSlot()      # 캡처 → 처리
        self.result_slot = _LatestSlot()     # 처리 → UI
        self._settings = _Settings("right", "ratio", {}, ())
        self._settings_key = None
        self._bad_targets = []               # 입력 중/무효인 송신 대상(상태바 경고용)
        self._cam_req = 1                    # 재연결 요청 카운터(메인 스레드가 증가)
        self._cam_req_index = CAM_INDEX
        self._shown_seq = 0
        self._photo = None
        self._last_result = None
        self._last_new_t = time.perf_counter()   # 마지막 새 프레임 시각(정지 감지용)
        self._slow_t = 0.0
        self._ui_t, self._ui_n = time.perf_counter(), 0

        # ① 창을 먼저 띄운다 — 무거운 임포트/카메라 오픈은 전부 워커 뒤로.
        self._build_ui()
        self._load_channel_into_sliders(CH[0])
        self._sync_settings()

        self._th_cap = threading.Thread(target=self._capture_loop, name="dg5f-capture", daemon=True)
        self._th_proc = threading.Thread(target=self._process_loop, name="dg5f-process", daemon=True)
        self._th_cap.start()
        self._th_proc.start()
        self.root.after(1, self._ui_tick)

    # ============================ UI 구성 ============================
    def _build_ui(self):
        root = self.root

        # ---- 레이아웃 ----
        #   row0: [영상(고정)] [컨트롤 캔버스(스크롤)] [수직 스크롤바]
        #   row1:              [수평 스크롤바]
        #   row2: 상태바(전 폭)
        # 컨트롤 패널(①~⑥)이 노트북 화면 높이보다 길어서 아래쪽(⑤ 로그·⑥ 프리셋)이 잘린다.
        # **스크롤은 오른쪽 패널에만** 건다 — 영상까지 같이 스크롤되면 슬라이더를 만지려고
        # 내려간 순간 미리보기가 화면 밖으로 사라져서, 손을 보면서 값을 맞출 수가 없다
        # (텔레옵에서 그건 기능 상실이다). ttk.Frame은 스크롤을 못 하므로 패널만
        # Canvas + create_window에 담는다.
        root.columnconfigure(1, weight=1)        # 창을 넓히면 영상이 아니라 패널 쪽이 늘어난다
        root.rowconfigure(0, weight=1)

        # ---- 좌: 영상 (스크롤 밖 = 항상 같은 자리) ----
        # 영상 자리를 미리 480x360으로 예약한다(열/행 minsize). 그러지 않으면 창을 띄우는
        # 순간(=첫 프레임 전)의 라벨 크기는 안내문뿐이라 초기 창이 그 크기로 잡히고,
        # 프레임이 도착해 라벨이 커지는 순간 컨트롤 패널이 오른쪽으로 밀려 **잘린다**.
        # 예약폭은 라벨의 최종 폭(VIDEO_COL_W)과 정확히 같게 맞춘다 — 라벨이 예약폭보다
        # 커지면 예약이 무의미해지므로 padding은 VIDEO_PAD로만 준다.
        self.video = ttk.Label(root, text="카메라 준비 중…\n(모델 로딩 ~4초)",
                               anchor="center", padding=VIDEO_PAD, foreground="#888")
        self.video.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(6, 8), pady=(6, 0))
        root.columnconfigure(0, minsize=VIDEO_COL_W + 14)
        root.rowconfigure(0, minsize=DISPLAY_H + 2 * VIDEO_PAD + 4)

        # ---- 우: 컨트롤 (스크롤 안) ----
        outer = tk.Canvas(root, highlightthickness=0, borderwidth=0)
        outer.grid(row=0, column=1, sticky="nsew")
        vbar = ttk.Scrollbar(root, orient="vertical", command=outer.yview)
        vbar.grid(row=0, column=2, sticky="ns")
        hbar = ttk.Scrollbar(root, orient="horizontal", command=outer.xview)
        hbar.grid(row=1, column=1, sticky="ew")
        # increment을 주지 않으면 휠 한 칸이 '창 높이의 1/10'로 튄다 → 20px 단위로 고정.
        outer.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set,
                        yscrollincrement=20, xscrollincrement=20)
        self._canvas = outer

        main = ttk.Frame(outer, padding=(0, 6, 6, 6))
        self._main = main
        self._main_item = outer.create_window((0, 0), window=main, anchor="nw")
        # 내용 크기가 바뀌면(채널 전환으로 라벨 길이가 변하는 등) 스크롤 범위를 다시 잡는다.
        main.bind("<Configure>", self._on_content_configure)
        outer.bind("<Configure>", self._on_canvas_configure)
        # 휠: 포커스와 무관하게 창 어디서든(영상 위에서도) 패널이 굴러가게. 단 휠로 값이
        # 바뀌는 위젯(콤보·스핀박스) 위에서는 이중 동작이 되지 않게 넘긴다.
        # ⚠️ X11(리눅스)은 휠을 <MouseWheel>로 주지 않고 <Button-4/5>로 준다 —
        #    <MouseWheel>만 걸면 리눅스에서 휠 스크롤이 통째로 죽는다(방향 판정은 _wheel_dir).
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(seq, self._on_wheel)
        for seq in ("<Shift-MouseWheel>", "<Shift-Button-4>", "<Shift-Button-5>"):
            root.bind_all(seq, self._on_wheel_x)
        for k in ("<Prior>", "<Next>", "<Home>", "<End>"):
            root.bind_all(k, self._on_page)
        self._vbar, self._hbar = vbar, hbar

        ctrl = ttk.Frame(main)
        ctrl.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)         # 창을 넓히면 ①~⑥ 프레임도 같이 넓어진다
                                                 # (안 주면 패널 오른쪽에 빈 띠만 생긴다)

        # (1) 연결 대상
        f = ttk.LabelFrame(ctrl, text="① 송신 대상 (IP·포트)", padding=6)
        f.grid(row=0, column=0, sticky="ew", pady=3)
        self.sim_on = tk.BooleanVar(value=True)
        self.real_on = tk.BooleanVar(value=False)
        self.sim_ip = tk.StringVar(value=DEF_SIM_IP)
        self.sim_port = tk.StringVar(value=str(DEF_SIM_PORT))
        self.real_ip = tk.StringVar(value=DEF_REAL_IP)
        self.real_port = tk.StringVar(value=str(DEF_REAL_PORT))
        ttk.Checkbutton(f, text="Sim (Unity)", variable=self.sim_on).grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.sim_ip, width=15).grid(row=0, column=1)
        ttk.Entry(f, textvariable=self.sim_port, width=6).grid(row=0, column=2)
        ttk.Checkbutton(f, text="Real (로봇/브리지)", variable=self.real_on).grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.real_ip, width=15).grid(row=1, column=1)
        ttk.Entry(f, textvariable=self.real_port, width=6).grid(row=1, column=2)
        ttk.Label(f, text="※ 다른 PC로 쏘려면 그 PC의 LAN IP 입력 (같은 WiFi, 방화벽 UDP 허용)",
                  foreground="#666").grid(row=2, column=0, columnspan=3, sticky="w", pady=(3, 0))

        # (2) 모드
        f = ttk.LabelFrame(ctrl, text="② 모드", padding=6)
        f.grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Label(f, text="손:").grid(row=0, column=0)
        ttk.Radiobutton(f, text="right", value="right", variable=self.hand).grid(row=0, column=1)
        ttk.Radiobutton(f, text="left", value="left", variable=self.hand).grid(row=0, column=2)
        ttk.Label(f, text="매핑:").grid(row=0, column=3, padx=(10, 0))
        ttk.Radiobutton(f, text="direct", value="direct", variable=self.mapmode).grid(row=0, column=4)
        ttk.Radiobutton(f, text="ratio", value="ratio", variable=self.mapmode).grid(row=0, column=5)
        ttk.Label(f, text="cam#").grid(row=1, column=0, pady=(4, 0))
        ttk.Spinbox(f, from_=0, to=8, width=4, textvariable=self.cam_index).grid(row=1, column=1, pady=(4, 0))
        ttk.Button(f, text="카메라 재연결", command=self._request_camera).grid(row=1, column=2, columnspan=2, pady=(4, 0))

        # (3) 채널 파라미터 편집
        f = ttk.LabelFrame(ctrl, text="③ 채널별 파라미터 (라이브)", padding=6)
        f.grid(row=2, column=0, sticky="ew", pady=3)
        ttk.Label(f, text="채널:").grid(row=0, column=0, sticky="w")
        self.ch_combo = ttk.Combobox(f, textvariable=self.sel_ch, width=22, state="readonly",
                                     values=[f"{JOINT_ID[i]}  {CH[i]}" for i in range(N)])
        self.ch_combo.current(0)
        self.ch_combo.grid(row=0, column=1, columnspan=3, sticky="w")
        self.ch_combo.bind("<<ComboboxSelected>>", self._on_channel_change)

        self.s_hmin = self._mk_scale(f, 1, "사람 min (rad)", -1.8, 1.8, 0.01, self._on_human)
        self.s_hmax = self._mk_scale(f, 2, "사람 max (rad)", -1.8, 1.8, 0.01, self._on_human)
        self.s_rlo = self._mk_scale(f, 3, "로봇 lo (deg)", -160, 160, 1, self._on_robot)
        self.s_rhi = self._mk_scale(f, 4, "로봇 hi (deg)", -160, 160, 1, self._on_robot)

        ov = ttk.Frame(f)
        ov.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(ov, text="수동 오버라이드 (손 무시하고 이 각도로 송신)",
                        variable=self.ov_enabled, command=self._on_override_toggle).pack(anchor="w")
        self.s_manual = self._mk_scale(f, 6, "수동 각도 (deg)", -160, 160, 1, self._on_manual)

        ttk.Label(f, text="※ '로봇 lo/hi'는 direct=clamp범위·ratio=정규화범위 양쪽에 반영. "
                          "엄지 1_1은 lo=접힘/hi=벌림, 1_2는 hi=대향최대(음수). "
                          "1_1 값은 항상 왼손 기준 — right 모드에선 자동 반전돼 적용된다.",
                  foreground="#666", wraplength=340).grid(row=7, column=0, columnspan=4, sticky="w", pady=(3, 0))

        # (4) 라이브 판독
        f = ttk.LabelFrame(ctrl, text="④ 선택 채널 실시간 값", padding=6)
        f.grid(row=3, column=0, sticky="ew", pady=3)
        self._mono = self._mono_font()            # Font 객체는 참조를 잡아둬야 GC되지 않는다
        self.lbl_read = ttk.Label(f, text="-", font=self._mono)
        self.lbl_read.pack(anchor="w")

        # (5) 로그 기록
        f = ttk.LabelFrame(ctrl, text="⑤ 로그 기록 (CSV)", padding=6)
        f.grid(row=4, column=0, sticky="ew", pady=3)
        self.log_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="랜드마크 → 사람각 → 로봇각 → 송신값 전 구간 기록",
                        variable=self.log_on,
                        command=self._on_log_toggle).grid(row=0, column=0, sticky="w")
        self.lbl_log = ttk.Label(f, text="꺼짐 — 켜면 logs/teleop_<시각>.csv 새로 생성",
                                 foreground="#666", wraplength=340)
        self.lbl_log.grid(row=1, column=0, sticky="w")
        ttk.Label(f, text="※ 껐다 켜면 항상 새 파일(덮어쓰기 없음). 약 2MB/분. "
                          "t_unix가 Unity 로그와 같은 시계라 그대로 대조 가능.",
                  foreground="#666", wraplength=340).grid(row=2, column=0, sticky="w", pady=(3, 0))

        # (6) 프리셋 저장/불러오기
        f = ttk.Frame(ctrl)
        f.grid(row=5, column=0, sticky="ew", pady=3)
        ttk.Button(f, text="프리셋 저장", command=self.save_preset).pack(side="left", padx=2)
        ttk.Button(f, text="프리셋 불러오기", command=self.load_preset).pack(side="left", padx=2)
        ttk.Button(f, text="채널 리셋", command=self.reset_channel).pack(side="left", padx=2)

        # 상태바 — 스크롤 밖(항상 보이는 자리)에 고정
        self.status = ttk.Label(root, text="", anchor="w", relief="sunken")
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew")

    # ---- 스크롤 배관 ----
    # 휠을 캔버스 스크롤로 쓰지 않고 그냥 넘길 위젯 = **자기 클래스에 <MouseWheel> 바인딩이
    # 있는 것들만**. bind_all("all" 태그)은 클래스 바인딩보다 **뒤에** 실행되므로, 여기서
    # "break"를 해도 값 변경은 이미 일어난 뒤다 → 넘기는 게 아니라 '이중 동작을 피한다'는 뜻.
    # 실측(Tk 8.6): TCombobox·TSpinbox·Listbox만 휠 바인딩이 있고 Scale/TScale은 없다.
    # ③이 슬라이더로 가득해서 예전엔 그 위에서 휠이 완전히 죽어 ⑤·⑥까지 내려갈 수가 없었다.
    _NO_WHEEL = ("TCombobox", "TSpinbox", "Listbox", "Text", "Treeview")

    def _on_content_configure(self, _e=None):
        box = self._canvas.bbox("all")
        if box is not None:                      # 위젯이 아직 없으면(초기 1프레임) bbox=None
            self._canvas.configure(scrollregion=box)

    def _on_canvas_configure(self, e):
        # 창이 내용보다 넓어지면 내부 프레임도 같이 늘려 준다(오른쪽에 빈 띠가 생기지 않게).
        inner = self._canvas.nametowidget(self._canvas.itemcget(self._main_item, "window"))
        self._canvas.itemconfigure(self._main_item, width=max(e.width, inner.winfo_reqwidth()))

    @staticmethod
    def _wheel_dir(e):
        """휠 이벤트 → -1(위로)/+1(아래로). 플랫폼 3종의 차이를 여기서 흡수한다:
             Windows : <MouseWheel>, delta = ±120
             macOS   : <MouseWheel>, delta = ±1 (트랙패드는 더 큰 값)
             X11     : <Button-4>(위)/<Button-5>(아래), **delta = 0**
           → X11에서 delta 부호만 보면 0 > 0 이 False라서 항상 아래로만 굴러간다."""
        if getattr(e, "num", None) in (4, 5):
            return -1 if e.num == 4 else 1
        return -1 if e.delta > 0 else 1

    def _on_wheel(self, e):
        if e.widget.winfo_class() in self._NO_WHEEL:
            return
        self._canvas.yview_scroll(3 * self._wheel_dir(e), "units")
        return "break"

    def _on_wheel_x(self, e):
        if e.widget.winfo_class() in self._NO_WHEEL:
            return
        self._canvas.xview_scroll(3 * self._wheel_dir(e), "units")
        return "break"

    def _on_page(self, e):
        """PgUp/PgDn/Home/End — 휠이나 스크롤바를 안 쓰고도 아래쪽(⑤·⑥)에 닿게.
        텍스트를 입력하는 중(Entry/Spinbox)에는 캐럿 이동을 방해하지 않게 넘긴다."""
        if e.widget.winfo_class() in ("TEntry", "Entry", "TSpinbox", "Spinbox", "Text"):
            return
        if e.keysym == "Prior":
            self._canvas.yview_scroll(-1, "pages")
        elif e.keysym == "Next":
            self._canvas.yview_scroll(1, "pages")
        elif e.keysym == "Home":
            self._canvas.yview_moveto(0.0)
        else:                                    # End
            self._canvas.yview_moveto(1.0)
        return "break"

    @staticmethod
    def _mono_font(size=10):
        """④ 판독용 고정폭 글꼴. 자릿수를 맞춘 포맷('{:+7.1f}')이라 비례 글꼴이면 숫자가
        흔들려 읽기 어렵다. "Consolas"는 **윈도우 전용**이므로(리눅스/맥엔 없어 비례 글꼴로
        대체됨) 설치된 것 중 앞선 것을 고르고, 하나도 없으면 Tk가 플랫폼별로 정의해 둔
        TkFixedFont(고정폭 보장)로 떨어진다."""
        have = set(tkfont.families())
        for fam in ("Consolas",              # Windows
                    "Menlo", "SF Mono",      # macOS
                    "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono",  # Linux
                    "Courier New"):          # 3종 공통 폴백
            if fam in have:
                return tkfont.Font(family=fam, size=size)
        fnt = tkfont.nametofont("TkFixedFont").copy()
        fnt.configure(size=size)
        return fnt

    def _mk_scale(self, parent, row, label, lo, hi, res, cmd):
        ttk.Label(parent, text=label, width=16).grid(row=row, column=0, sticky="w")
        var = tk.DoubleVar()
        s = tk.Scale(parent, from_=lo, to=hi, resolution=res, orient="horizontal",
                     length=260, variable=var, command=lambda _v: cmd())
        s.grid(row=row, column=1, columnspan=3, sticky="w")
        s.var = var
        return s

    # ============================ 채널 편집 콜백 ============================
    def _cur_ch(self):
        return CH[self.ch_combo.current()]

    def _on_channel_change(self, _e=None):
        self._load_channel_into_sliders(self._cur_ch())

    def _load_channel_into_sliders(self, ch):
        self._loading = True
        hmn, hmx = get_human_range(ch)
        rlo, rhi = get_robot_range(ch)
        self.s_hmin.set(round(hmn, 3))
        self.s_hmax.set(round(hmx, 3))
        self.s_rlo.set(round(rlo, 1))
        self.s_rhi.set(round(rhi, 1))
        i = _ch_idx(ch)
        self.ov_enabled.set(i in self.overrides)
        self.s_manual.set(self.overrides.get(i, 0.0))
        self._loading = False

    def _on_human(self):
        if self._loading:
            return
        set_human_range(self._cur_ch(), self.s_hmin.var.get(), self.s_hmax.var.get())

    def _on_robot(self):
        if self._loading:
            return
        set_robot_range(self._cur_ch(), self.s_rlo.var.get(), self.s_rhi.var.get())

    def _on_override_toggle(self):
        i = _ch_idx(self._cur_ch())
        if self.ov_enabled.get():
            self.overrides[i] = self.s_manual.var.get()
        else:
            self.overrides.pop(i, None)
        self._ov_rev += 1          # 다음 _sync_settings에서 워커 스냅샷 갱신

    def _on_manual(self):
        if self._loading:
            return
        if self.ov_enabled.get():
            self.overrides[_ch_idx(self._cur_ch())] = self.s_manual.var.get()
            self._ov_rev += 1

    def reset_channel(self):
        """선택 채널을 dg5f_angles 원본 기본값으로 되돌린다(모듈 재로딩 없이 근사 복원은 어려워 안내만)."""
        messagebox.showinfo("채널 리셋",
                            "원본 기본값 복원은 프리셋 불러오기로 하거나 프로그램을 재시작하세요.\n"
                            "(현재 세션에서 바꾼 값만 프리셋에 저장됩니다.)")

    def _on_log_toggle(self):
        """메인 스레드 전용. 켜면 새 파일, 끄면 남은 큐를 비우고 닫는다."""
        if self.log_on.get():
            try:
                path = self.logger.start()
            except OSError as e:
                self.log_on.set(False)
                self.lbl_log.configure(text=f"로그 파일 열기 실패: {e}")
                messagebox.showerror("로그", f"로그 파일을 열 수 없습니다:\n{e}")
                return
            self.lbl_log.configure(text=f"기록 중 → {path}")
        else:
            self.logger.stop()
            self.lbl_log.configure(
                text=f"중지 — {self.logger.count}행 저장됨: {self.logger.path}")

    def _request_camera(self):
        """카메라 (재)연결 요청만 걸고 즉시 리턴 — 오픈은 캡처 스레드가 한다.
        (예전엔 이 버튼이 UI 스레드에서 VideoCapture를 열어 6~25초 프리즈였다.)"""
        self._cam_req_index = self.cam_index.get()
        self._cam_req += 1
        self.cam_status = f"cam{self._cam_req_index} 재연결 요청…"

    # ============================ 캡처 스레드 ============================
    def _capture_loop(self):
        global cv2
        import cv2 as _cv2                      # 0.6초 — UI 밖에서
        cv2 = _cv2
        self._ev_cv2.set()

        cap = None
        req = 0
        fail = 0
        t_fps, n_fps = time.perf_counter(), 0
        while not self._stop.is_set():
            if req != self._cam_req or cap is None:
                req = self._cam_req
                if cap is not None:
                    cap.release()
                    cap = None
                idx = self._cam_req_index
                self.cam_status = f"cam{idx} 여는 중…"
                t0 = time.perf_counter()
                # ⚠️ cap.set() 절대 추가하지 말 것. 2026-07-27 실측(4회 반복):
                #    FOURCC/W/H/FPS 4개를 넣으면 6.3~18.9초를 먹는데(set 하나당 2~4.3초)
                #    read 지연·해상도·fps는 넣든 안 넣든 33ms / 640x480 / 30fps로 동일했다.
                #    MSMF는 set(FOURCC, MJPG)에 False를 반환(무시)한다. 즉 순수 손해.
                #    프레임 지연도 전용 캡처 스레드가 계속 비워주므로 버퍼가 쌓이지 않는다.
                cap = (cv2.VideoCapture(idx) if CAM_BACKEND is None
                       else cv2.VideoCapture(idx, CAM_BACKEND))
                if not cap.isOpened():
                    self.cam_status = f"cam{idx} 열기 실패 — cam# 확인"
                    self.cam_fps = 0.0           # 실패 중에 옛 fps를 계속 보여주면 안 된다
                    cap.release()
                    cap = None
                    self._stop.wait(1.5)         # 실패 폭주 방지
                    continue
                self.cam_status = f"cam{idx} 연결 ({time.perf_counter() - t0:.1f}s)"
                fail = 0

            ok, frame = cap.read()
            if not ok:
                fail += 1
                if fail > 30:                    # ~1초간 계속 실패 → 재오픈
                    self.cam_status = "프레임 끊김 — 재연결 중…"
                    self.cam_fps = 0.0
                    cap.release()
                    cap = None
                    fail = 0
                else:
                    self._stop.wait(0.01)
                continue
            fail = 0
            self.frame_slot.put(frame)

            n_fps += 1
            t = time.perf_counter()
            if t - t_fps >= 1.0:
                self.cam_fps = n_fps / (t - t_fps)
                t_fps, n_fps = t, 0

        if cap is not None:
            cap.release()

    # ============================ 처리 스레드 ============================
    def _process_loop(self):
        global mp
        import mediapipe as _mp                 # 3.9초 — 창이 뜬 뒤 백그라운드에서
        mp = _mp
        hands = mp.solutions.hands.Hands(
            model_complexity=MP_MODEL_COMPLEXITY, max_num_hands=1,
            min_detection_confidence=0.6, min_tracking_confidence=0.6)
        draw_landmarks = mp.solutions.drawing_utils.draw_landmarks
        connections = mp.solutions.hands.HAND_CONNECTIONS
        self._ev_cv2.wait()                     # flip/cvtColor/resize에 cv2 필요

        seq = 0
        t_prev = None
        t_fps, n_fps = time.perf_counter(), 0
        while not self._stop.is_set():
            seq, frame = self.frame_slot.wait_new(seq, timeout=0.3)
            if frame is None:                   # 프레임이 안 온다(카메라 실패/재연결 중)
                self.proc_fps = 0.0             # 상태바가 옛 fps로 거짓말하지 않게
                t_prev = None                   # 끊긴 구간의 dt로 필터 주파수를 오염시키지 않기
                continue
            st = self._settings                 # 참조 한 번만 읽어 프레임 내내 일관되게 사용

            frame = cv2.flip(frame, 1)          # 거울 모드(보기 편의, 각도 계산 무관)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = hands.process(rgb)
            detected = bool(res.multi_hand_landmarks)

            # G: 필터 주파수를 실제 처리 주기에 맞춘다. 고정 30Hz로 두면 루프가 19fps일 때
            #    OneEuroFilter의 dx 추정이 틀려 추종 지연이 실제보다 커진다.
            t_now = time.perf_counter()
            if t_prev is not None:
                dt = t_now - t_prev
                if dt > 0:
                    f = min(max(1.0 / dt, 5.0), 120.0)      # 순간 튐 방어
                    self._filter_freq += 0.2 * (f - self._filter_freq)
            t_prev = t_now

            sent = None
            xyz = None                          # 로그용 — 미검출 프레임은 랜드마크가 없다
            mapped = None
            self._tx_ok = False                 # _send_packet이 실제로 보내면 True로 바꾼다
            if detected:
                lms = res.multi_hand_landmarks[0]
                draw_landmarks(frame, lms, connections)
                xyz = A.landmarks_to_xyz(lms, rgb.shape)   # rgb = 표시용 축소 전 원본
                raw = A.compute_raw(xyz)
                mapped = list(A.map_to_dg5f(raw, st.hand, st.mapmode))
                self.last_raw = list(raw)
                self.last_mapped = mapped       # 오버라이드·필터 전 값(_pack_and_send는 사본을 쓴다)
                sent = self._pack_and_send(mapped, raw, xyz, st)
            elif st.overrides:
                # 손 없어도 오버라이드가 있으면 중립(0)에 오버라이드만 얹어 송신(장비 단독 테스트)
                mapped = [0.0] * N
                sent = self._pack_and_send(mapped, self.last_raw, None, st)
            elif self.last_vals is not None:
                self._send_packet(self.last_vals + self.last_raw, st)   # occlusion hold
                sent = self.last_vals[:N]

            # 로그: 위 분기가 실제로 쓴 값을 그대로 남긴다(raw는 hold 시 직전 값 = 실사용값).
            # time.time()은 UTC 초 — Unity 로거와 같은 시계라야 사후 조인이 된다.
            self.logger.log(time.time(), detected, st.hand, st.mapmode, self._tx_ok,
                            xyz, self.last_raw, mapped, sent)

            # 표시용 축소는 여기서(워커) 한다 — UI 스레드는 paste만.
            # 랜드마크가 그려진 BGR을 먼저 줄이고 그 다음 색변환(작은 쪽이 싸다).
            h, w = frame.shape[:2]
            if w > DISPLAY_W:
                frame = cv2.resize(frame, (DISPLAY_W, max(1, round(h * DISPLAY_W / w))))
            disp = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.result_slot.put(_Result(disp, detected, self.last_raw, self.last_mapped, sent))

            n_fps += 1
            if t_now - t_fps >= 1.0:
                self.proc_fps = n_fps / (t_now - t_fps)
                t_fps, n_fps = t_now, 0

        hands.close()

    def _pack_and_send(self, mapped, raw, xyz, st):
        """처리 스레드 전용. 반환값 = 필터 후 20채널(= 실제 UDP로 나간 값)."""
        mapped = list(mapped)
        for i, deg in st.overrides.items():      # 수동 오버라이드 적용
            mapped[i] = deg
        fr = self._filter_freq
        vals_ang = [self.filters[n](v, fr) for n, v in zip(CH, mapped)]

        if xyz is not None:
            tip, pinch_d = A.compute_thumb_tip(xyz)
            self.pinch_on = (pinch_d < A.PINCH_OFF) if self.pinch_on else (pinch_d < A.PINCH_ON)
            ftips = A.compute_finger_tips(xyz)
            wtips = A.compute_wrist_tip_vectors(xyz)
            tip_f = [f(v, fr) for f, v in zip(self.tip_filters, tip)]
            ftips_f = [f(v, fr) for f, v in zip(self.ftip_filters, ftips)]
            wtips_f = [f(v, fr) for f, v in zip(self.wtip_filters, wtips)]
            vals = (vals_ang + tip_f + [1.0 if self.pinch_on else 0.0]
                    + [self.pinch_filter(pinch_d, fr)] + ftips_f + wtips_f)
        else:
            # 손 없는 오버라이드 송신 — 각도만 채우고 나머지는 0
            vals = vals_ang + [0.0] * 32

        self.last_vals = vals
        self._send_packet(vals + list(raw), st)
        return vals_ang

    def _send_packet(self, payload72, st):
        now = time.time()
        if now - self.last_send < 1.0 / SEND_HZ_CAP:
            return
        self.last_send = now
        try:
            pkt = struct.pack(A.PACKET_FMT, *payload72)
        except struct.error:
            return
        for ip, port in st.targets:              # 파싱은 _sync_settings에서 이미 끝냈다
            try:
                self.sock.sendto(pkt, (ip, port))
                self.pkt_count += 1
                self._tx_ok = True               # 로그 tx 열 — 이 프레임 값이 실제로 나갔다
            except OSError:
                pass

    # ============================ UI 루프 (메인 스레드) ============================
    def _sync_settings(self):
        """tk 변수를 읽어 워커용 불변 스냅샷으로 교체. **메인 스레드에서만** 호출.
        바뀐 게 없으면 아무것도 안 한다(30Hz로 돌아도 공짜)."""
        key = (self.hand.get(), self.mapmode.get(),
               self.sim_on.get(), self.sim_ip.get(), self.sim_port.get(),
               self.real_on.get(), self.real_ip.get(), self.real_port.get(),
               self._ov_rev)
        if key == self._settings_key:
            return
        self._settings_key = key

        targets = []
        bad = []
        for label, on, ip, port in (("sim", key[2], key[3], key[4]),
                                    ("real", key[5], key[6], key[7])):
            if not on:
                continue
            ip = ip.strip()
            try:
                p = int(port)
                if not 0 < p < 65536:
                    raise ValueError
            except ValueError:                   # 포트 입력 중(빈칸 등)
                bad.append(f"{label} 포트?")
                continue
            # ⚠️ 여기서 반드시 걸러야 한다. 점4자리가 아닌 문자열을 sendto에 넘기면 Windows가
            #    호스트명으로 보고 DNS 조회를 시도하며 **2.7초 블로킹**한다(2026-07-27 실측).
            #    IP를 한 글자씩 입력하면 '1','19','192','192.' 넷이 전부 조회로 들어가
            #    한 번 입력에 누적 10.8초 동안 송신 스레드가 멈췄다 → 미리보기가 얼어붙음.
            #    inet_pton 검사는 1~3us. 엄격 검사(inet_aton은 '192'를 0.0.0.192로 통과시켜
            #    엉뚱한 곳으로 쏘므로 쓰지 말 것).
            try:
                socket.inet_pton(socket.AF_INET, ip)
            except OSError:
                bad.append(f"{label} IP?")       # 입력 완료 전까지 송신 보류(오발신 방지)
                continue
            targets.append((ip, p))
        self._bad_targets = bad
        self._settings = _Settings(key[0], key[1], dict(self.overrides), tuple(targets))

    def _ui_tick(self):
        t0 = time.perf_counter()
        self._sync_settings()

        seq, r = self.result_slot.peek()          # 절대 블로킹 없음
        if r is not None and seq != self._shown_seq:
            self._shown_seq = seq
            self._last_result = r
            self._last_new_t = time.perf_counter()
            self._blit(r.disp)
            self._ui_n += 1

        now = time.perf_counter()
        if now - self._slow_t >= 1.0 / READOUT_HZ:    # F: 판독/상태바는 10Hz면 충분
            self._slow_t = now
            self._update_readout()
            self._update_status()
        if now - self._ui_t >= 1.0:
            self.ui_fps = self._ui_n / (now - self._ui_t)
            self._ui_t, self._ui_n = now, 0

        # D: 고정 20ms를 덧붙이지 않고 '남은 시간'만 쉰다.
        left = UI_PERIOD_MS - (time.perf_counter() - t0) * 1000.0
        self.root.after(max(1, int(left)), self._ui_tick)

    def _blit(self, rgb):
        """numpy(RGB) → Tk 라벨. 매 프레임 PhotoImage를 새로 만들면 4~13ms + Tk 이미지
        객체 churn이라, 크기가 같으면 paste로 픽셀만 갈아끼운다(480x360에서 ~1.7ms)."""
        img = Image.fromarray(rgb)
        if self._photo is None or (self._photo.width(), self._photo.height()) != img.size:
            self._photo = ImageTk.PhotoImage(img)
            self.video.configure(image=self._photo, text="")
            self.video.image = self._photo       # GC 방지
        else:
            self._photo.paste(img)

    def _update_readout(self):
        i = self.ch_combo.current()
        ch = CH[i]
        r = self._last_result
        if r is None:
            self.lbl_read.configure(text=f"{JOINT_ID[i]} {ch}\n(대기 중…)")
            return
        raw = r.raw[i]
        mapped = r.mapped[i]
        sent = float("nan") if r.sent is None else r.sent[i]
        ov = f"  [OVERRIDE {self.overrides[i]:+.0f}]" if i in self.overrides else ""
        self.lbl_read.configure(
            text=f"{JOINT_ID[i]} {ch}\n"
                 f"raw   = {raw:+.4f} rad ({np.degrees(raw):+7.1f} deg)\n"
                 f"mapped= {mapped:+7.1f} deg{ov}\n"
                 f"sent  = {sent:+7.1f} deg  (필터후=UDP)")

    def _update_status(self):
        tgt = []
        if self.sim_on.get():
            tgt.append(f"sim {self.sim_ip.get()}:{self.sim_port.get()}")
        if self.real_on.get():
            tgt.append(f"real {self.real_ip.get()}:{self.real_port.get()}")
        if self._bad_targets:
            tgt.append("⚠ " + "/".join(self._bad_targets) + " 확인 — 송신 보류")
        r = self._last_result
        stall = time.perf_counter() - self._last_new_t
        if r is None:
            state = self.cam_status
        elif stall > 1.5:
            # 처리 스레드가 어딘가에 막혔다는 신호. 이 표시가 보이면 미리보기가 멈춘 게
            # UI 탓이 아니라 캡처/처리 쪽이 막힌 것 — 원인 좁히기에 쓴다.
            state = f"영상 정지 {stall:.0f}s — {self.cam_status}"
        else:
            state = "손 인식" if r.detected else "미검출(hold)"
        if self.logger.active:
            drop = f", 유실 {self.logger.dropped}" if self.logger.dropped else ""
            self.lbl_log.configure(
                text=f"기록 중 {self.logger.count}행{drop} → {os.path.basename(self.logger.path)}")
        self.status.configure(
            text=f"{state} | cam {self.cam_fps:4.1f} / proc {self.proc_fps:4.1f} / ui {self.ui_fps:4.1f} fps | "
                 f"filt {self._filter_freq:4.1f}Hz | pkt {self.pkt_count} | "
                 f"mode={self.mapmode.get()}/{self.hand.get()} | "
                 f"→ {', '.join(tgt) or '(대상 없음)'}")

    # ============================ 프리셋 ============================
    def _collect(self):
        return {
            "hand": self.hand.get(), "mapmode": self.mapmode.get(),
            "sim": [self.sim_on.get(), self.sim_ip.get(), self.sim_port.get()],
            "real": [self.real_on.get(), self.real_ip.get(), self.real_port.get()],
            "human_ranges": {ch: get_human_range(ch) for ch in CH},
            "robot_ranges": {ch: get_robot_range(ch) for ch in CH},
            "overrides": {CH[i]: v for i, v in self.overrides.items()},
        }

    def save_preset(self):
        path = filedialog.asksaveasfilename(initialfile=os.path.basename(PRESET_PATH),
                                            initialdir=_base_dir(), defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(self._collect(), fp, ensure_ascii=False, indent=2)
        messagebox.showinfo("저장", f"프리셋 저장됨:\n{path}")

    def load_preset(self):
        path = filedialog.askopenfilename(initialdir=_base_dir(), filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, encoding="utf-8") as fp:
            d = json.load(fp)
        self.hand.set(d.get("hand", "right"))
        self.mapmode.set(d.get("mapmode", "ratio"))
        for key, on_v, ip_v, port_v in (("sim", self.sim_on, self.sim_ip, self.sim_port),
                                        ("real", self.real_on, self.real_ip, self.real_port)):
            if key in d:
                on, ip, port = d[key]
                on_v.set(on); ip_v.set(ip); port_v.set(str(port))
        for ch, (lo, hi) in d.get("human_ranges", {}).items():
            if ch in CH:
                set_human_range(ch, lo, hi)
        for ch, (lo, hi) in d.get("robot_ranges", {}).items():
            if ch in CH:
                set_robot_range(ch, lo, hi)
        self.overrides = {_ch_idx(ch): v for ch, v in d.get("overrides", {}).items() if ch in CH}
        self._ov_rev += 1
        self._load_channel_into_sliders(self._cur_ch())
        self._sync_settings()
        messagebox.showinfo("불러오기", f"프리셋 적용됨:\n{path}")

    # ============================ 종료 ============================
    def on_close(self):
        self._stop.set()
        for th in (self._th_cap, self._th_proc):
            # 무거운 임포트/카메라 오픈 중이면 안 끝날 수 있다 → daemon이라 프로세스 종료를 막지 않음
            if th.is_alive():
                th.join(timeout=1.5)
        # 처리 스레드를 먼저 세운 뒤 로거를 닫아야 남은 큐가 유실 없이 파일로 나간다.
        self.logger.stop()
        try:
            self.sock.close()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    gui = TeleopGUI(root)
    # Canvas는 내용 크기를 따라가지 않으므로(기본 378x265) 초기 창 크기를 직접 잡는다.
    # 내용 전체가 들어가되 화면(작업표시줄 감안)을 넘지 않게 — 넘치는 만큼은 스크롤로 본다.
    # ⚠️ '영상 자리'는 예약값(VIDEO_COL_W/DISPLAY_H)으로 계산한다. 이 시점의 영상 라벨은
    #    아직 안내문 크기(≈175px)뿐이므로 실측으로 잡으면 첫 프레임에 창이 모자라진다.
    root.update_idletasks()
    chrome_w = gui._vbar.winfo_reqwidth() + 2                     # 수직 스크롤바
    chrome_h = gui._hbar.winfo_reqheight() + gui.status.winfo_reqheight() + 2
    need_w = VIDEO_COL_W + 14 + gui._main.winfo_reqwidth() + chrome_w
    need_h = max(gui._main.winfo_reqheight(), DISPLAY_H + 2 * VIDEO_PAD + 4) + chrome_h
    w = min(need_w, int(root.winfo_screenwidth() * 0.95))
    h = min(need_h, int(root.winfo_screenheight() * 0.90))
    root.geometry(f"{w}x{h}")
    # 최소 크기: 영상 + 패널이 최소한 절반은 보이게(더 좁히면 패널은 가로 스크롤로 본다).
    root.minsize(VIDEO_COL_W + 220, 360)
    root.mainloop()


if __name__ == "__main__":
    main()
