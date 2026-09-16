import json
import math
import os
import numpy as np

from dg5f_paths import CALIB_PATH

# --- MediaPipe landmark 인덱스 ---
WRIST = 0                 # 손목
THUMB = [1, 2, 3, 4]      # 엄지 CMC, MCP, IP, TIP
INDEX = [5, 6, 7, 8]      # 검지 MCP, PIP, DIP, TIP
MIDDLE = [9, 10, 11, 12]  # 중지 MCP, PIP, DIP, TIP
RING = [13, 14, 15, 16]   # 약지 MCP, PIP, DIP, TIP
PINKY = [17, 18, 19, 20]  # 소지 MCP, PIP, DIP, TIP

# ── 랜드마크 → 좌표배열 (등방 보정 포함) ─────────────────────────────────────
# ★2026-07-28 신설. 그 전엔 calibrate/vision_node/teleop_gui가 **각자 같은 함수를 복사**해
#   갖고 있었다(MP_MODEL_COMPLEXITY가 한 곳만 달라 보정과 라이브가 어긋났던 07-27 사고와 같은
#   구조). 한 곳으로 모아 사본이 갈라질 수 없게 한다.
#
# 무엇을 고치나 — **종횡비 왜곡**:
#   MediaPipe 이미지 랜드마크는 x=px/W, y=py/H 로 **축마다 다른 값으로 정규화**된다.
#   640x480이면 y축만 4/3배 늘어난 비등방 좌표계라, 여기서 잰 모든 각도가 왜곡된다.
#   등방 좌표 = (x·W, y·H, z·W).  전체 배율은 각도에 무영향이므로 W로 나눠 (x, y·H/W, z)만 쓴다.
#   (z는 MediaPipe 문서상 "x와 대략 같은 스케일" = 폭 정규화 → x와 같이 두면 된다)
#
# 실측 효과(07-27 녹화 좌/우 각 1200여 프레임, p2~p98 폭):
#   MCP  +21~30%   벌림 +18~32%   thumb_cmc +10~13%   (과소 판독이 줄어 이득/노이즈증폭 완화)
#   PIP  −5~15%    (153~168°까지 나오던 과다 판독이 줄어드는 방향)
#   index_mcp 실측 최대 0.578 → 0.711 rad
#
# ⚠️ world 랜드마크(multi_hand_world_landmarks)에는 **적용하면 안 된다** — 그쪽은 미터 단위
#   손 중심 좌표라 애초에 이 왜곡이 없다. 그 경우 frame_shape=None 으로 부를 것.
# ⚠️ 프록시 값이 20%대로 바뀌므로 **이 변경 이후 재보정 필수**. 거리 기반 상수
#   (THUMB_OPP_D_OPEN/D_FULL)도 함께 재산출했다 — 해당 상수 주석 참조.
LM_ASPECT_FIX = True    # False로 두면 옛 동작(비등방 정규화 좌표 그대로). A/B 비교용.


def landmarks_to_xyz(hand_landmarks, frame_shape):
    """MediaPipe 랜드마크 → (21,3) ndarray.

    frame_shape: 그 랜드마크를 뽑은 프레임의 `.shape` (h, w, ...).
        이미지 랜드마크면 반드시 넘길 것 — 등방 보정에 쓴다.
        world 랜드마크면 **None**(보정 대상 아님).
    ⚠️ 기본값을 두지 않는 건 일부러다. 빼먹으면 조용히 옛 좌표계로 돌아가 보정과 라이브가
       어긋나므로, 호출부가 매번 명시하게 해서 그 사고를 막는다.
    """
    pts = np.zeros((21, 3), dtype=np.float64)
    for i, lm in enumerate(hand_landmarks.landmark):
        pts[i] = (lm.x, lm.y, lm.z)
    if LM_ASPECT_FIX and frame_shape is not None:
        h, w = float(frame_shape[0]), float(frame_shape[1])
        if w > 0.0:
            pts[:, 1] *= h / w
    return pts


# _angle(a, b, c): 점 b를 꼭짓점으로 하는 두 벡터(b→a, b→c) 사이 각(rad)을 구하는 함수
def _angle(a, b, c):
    # 점 b를 꼭짓점으로 하는 두 벡터 만들기
    v1, v2 = np.asarray(a) - np.asarray(b), np.asarray(c) - np.asarray(b)
    # 미디어파이프에서 랜드마크는 a[x,y,z] 처럼 리스트로 받기때문에 np.asarray()로 NumPy 배열로 변환처리 후
    # 벡터 연산(빼기, 내적, 길이 계산 등)을 하여 점 b를 꼭짓점으로 하는 두 벡터를 구함.

    # 구한 두 벡터의 길이를 계산
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    # np.linalg.norm(): 벡터의 크기(길이)를 구하는 함수, 길이 = √(x² + y² + z²) 이용

    # 벡터의 길이가 0(또는 거의 0)인 경우 예외 처리
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0

    # cosθ에서 각도 추출
    return float(np.arccos(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)))
    # np.dot(v1, v2) / (n1 * n2): 벡터의 내적 공식 이용하여 cosθ 값 구하기
    # |a|*|b|*cosθ = a⋅b
    # cosθ = a⋅b/|a|*|b|
    # np.clip(): cosθ 값은 -1~1 사이로 나와야하지만 컴퓨터 부동소수점 연산 오차로 범위를 벗어날 수 있으므로, -1~1 범위로 제한 처리
    # np.arccos(): 코사인(cos) 값으로부터 실제 각도(θ)를 구하는 함수

# _bend(): 손가락 관절의 굽힘각(Flexion)을 계산하는 함수
def _bend(lm, i, j, k):
    return math.pi - _angle(lm[i], lm[j], lm[k])
    # - lm : MediaPipe의 21개 랜드마크 좌표
    # - i : 이전 관절
    # - j : 현재 관절(굽힘을 계산할 관절)
    # - k : 다음 관절
    # 위에서 구현한 _angle() 함수에 미디어파이프 전체 랜드마크 좌표에서 자신이 구할 관절의 내부 각도를 구하고
    # math.pi(180°) 에서 구한 관절 내부 각도를 빼서 손가락 관절을 완전히 폈을때 기준 얼만큼 굽혔는지 그 각도를 구함.
    #
    # ⚠️ 이 각은 **부호 없는 3D 각**이라 굽힘 평면 밖 성분(좌우 벌림)도 그대로 섞여 들어온다.
    #   MCP 굽힘(_bend(lm, WRIST, X[0], X[1]))은 손목→MCP가 손바닥에 고정된 반면 MCP→PIP는
    #   굽힘과 벌림 양쪽으로 움직이므로, 손가락을 옆으로 θ 돌리면 굽힘도 θ만큼 늘어난다.
    #   → MCP는 _bend_mcp()(평면 투영판)를 쓴다. 아래 주석 참조.
    #   PIP/DIP·엄지 MCP/IP는 두 벡터가 모두 그 손가락 안에 있어 벌림에 함께 회전 → 각이 불변.
    #   그래서 그쪽은 이 함수를 그대로 쓴다(투영하면 오히려 정보를 깎는다).


# MCP 굽힘 전용: 굽힘 평면에 투영해 좌우 벌림 성분을 제거한다 (2026-07-28 신설).
#
# 왜 (실측 근거):
#   사용자 보고 — "손을 선서하듯 쭉 펴서 **모으면** 로봇 검지가 앞으로 굽는다"(좌·우 양손).
#   07-28 라이브 3개 런(rad_dg5f 14:10/14:12/14:14, 편 손 1495프레임)에서 그대로 재현:
#     펴고 벌림 → 사람 index_mcp  8.2° / 로봇 2_2 25.5°
#     펴고 모음 → 사람 index_mcp 18.5° / 로봇 2_2 49.2°   (모으기만 했는데 +10.4° / +23.7°)
#   검지가 최악인 이유: 손목→검지MCP 축이 네 손가락 중 가장 비스듬하고 벌림 가동범위도 가장 크다.
#
# 방법: 그 손가락의 '측면축' lat = palm_n × (손목→MCP) 성분을 두 벡터에서 빼고 각을 잰다.
#   _abduction()이 palm_n(법선) 성분을 빼서 손바닥 평면만 남기는 것과 정확히 대칭 —
#   이쪽은 측면 성분을 빼서 굽힘 평면만 남긴다.
#
# 07-27 녹화 랜드마크(lmprobe 좌/우 각 1200여 프레임) 시뮬레이션 결과:
#   index  벌림상관 0.74→0.45(우) / 0.69→0.24(좌),  편손 rest 10.2°→7.1° / 10.1°→6.7°
#   middle 편손 rest 7.4°→4.1° / 6.5°→2.5°     pinky 편손 rest 13.6°→7.1° / 13.2°→4.7°
#   (약지·새끼의 '벌림상관'은 오히려 올라가는데, 그쪽 _abduction 자체가 굽힘 오염이 심해서
#    (5_2 vs 5_3 r=0.95) 굽힘이 깨끗해질수록 상관이 커지는 착시다. _abduction 수정은 별건.)
#
# ⚠️ 프록시 정의가 바뀌므로 **이 변경 이후로 재보정해야 한다**(사람 min/max가 달라진다).
#   BEND_MCP_PLANAR=False로 즉시 옛 동작으로 되돌릴 수 있다(A/B 비교용).
BEND_MCP_PLANAR = True


def _bend_mcp(lm, finger):
    """finger = INDEX/MIDDLE/RING/PINKY. 손목→MCP 기준 MCP 굽힘각(rad), 굽힘 평면 투영."""
    if not BEND_MCP_PLANAR:
        return _bend(lm, WRIST, finger[0], finger[1])

    lm = np.asarray(lm)
    palm_n = np.cross(lm[INDEX[0]] - lm[WRIST], lm[PINKY[0]] - lm[WRIST])
    npn = np.linalg.norm(palm_n)
    axis = lm[finger[0]] - lm[WRIST]            # 손목→MCP (이 손가락의 MCP 축)
    na = np.linalg.norm(axis)
    if npn < 1e-9 or na < 1e-9:                 # 손이 정면에서 뭉개진 프레임 — 옛 방식으로 폴백
        return _bend(lm, WRIST, finger[0], finger[1])

    lat = np.cross(palm_n / npn, axis / na)     # 굽힘 평면의 법선(= 좌우 벌림 축)
    nl = np.linalg.norm(lat)
    if nl < 1e-9:
        return _bend(lm, WRIST, finger[0], finger[1])
    lat /= nl

    a = lm[WRIST] - lm[finger[0]]               # MCP→손목
    b = lm[finger[1]] - lm[finger[0]]           # MCP→PIP
    a = a - lat * np.dot(a, lat)                # 측면(벌림) 성분 제거 → 굽힘 평면 성분만 남김
    b = b - lat * np.dot(b, lat)
    n1, n2 = np.linalg.norm(a), np.linalg.norm(b)
    if n1 < 1e-6 or n2 < 1e-6:
        return _bend(lm, WRIST, finger[0], finger[1])
    return math.pi - float(np.arccos(np.clip(np.dot(a, b) / (n1 * n2), -1.0, 1.0)))


# ─────────────────────── 벌림(옆으로 벌어짐) 계산 방식 ───────────────────────
# "lateral"(기본, 2026-09-16 신설): 손가락 첫 마디가 **자기 굽힘 평면에서 옆으로 얼마나
#   벗어났는지**를 잰다. 굽힘은 그 평면 안에서 일어나므로 원리상 섞이지 않는다.
#   축은 `_bend_mcp`가 굽힘을 뽑을 때 쓰는 것과 **같은 축**을 쓴다(한 관절을 굽힘/벌림
#   두 성분으로 가르는 같은 기준 — 두 함수가 서로의 짝이 된다).
#   0도는 옛 방식과 같게 맞춘다: **손 앞방향(중지와 나란함) = 0**.
# "planar"(옛 방식): 손가락 방향을 손바닥 평면에 눌러 붙인 뒤 중지와의 각도를 잰다.
#   굽히면 눌러 붙인 그림자가 짧아져 각도가 폭주한다.
#
# 실측 비교 (2026-09-16, 실제 손 녹화 2개. 재현: analyze_abduction.py):
#   녹화 ① 손 편 채로 새끼만 벌렸다 오므리기(704프레임) — 여기서 값이 **크게** 움직여야 좋다
#   녹화 ② 새끼(+약지)만 굽혔다 펴기(608프레임)     — 여기서 값이 **안** 움직여야 좋다
#     옛 방식            벌림 42.5° / 굽힘 76.7°  → 신호대오염 0.55
#     굽힘평면 축        벌림 41.0° / 굽힘 43.4°  → 1.13 (아래 굽힘 보정 전)
#     + 굽힘 보정        벌림 43.4° / 굽힘 26.0°  → **1.67**  ← 채택
ABDUCTION_METHOD = "lateral"

# 굽힘이 벌림에 남기는 **체계적인** 끌림을 빼는 계수(deg). 축을 바꿔도 남는 성분이 있는데,
# 이는 잡음이 아니라 손 구조 때문이다 — MCP 관절의 회전축이 손 축과 정확히 직각이 아니라서,
# 손가락을 굽히면 첫 마디가 실제로 옆으로 따라 눕는다. 굽힘각의 sin에 비례한다:
#     보정된 벌림 = 잰 벌림 − (계수) × sin(굽힘각)
# 계수는 녹화 ②에서 최소제곱으로 구했다. 앞 절반으로 구해 뒤 절반에 적용해도 결과가
# 거의 같아(26.7° vs 25.1°) 한 번의 녹화에 과하게 맞춘 값이 아님을 확인했다.
#
# ⚠️ 검지·중지가 0인 이유: 녹화 ②에서 그 두 손가락은 거의 굽히지 않아(굽힘 폭 10° 미만)
#   계수를 믿을 만하게 잴 수 없었다. 억지로 맞추면 오히려 해롭다(중지는 +48°라는 말도 안
#   되는 값이 나왔다). 그 손가락들을 크게 굽힌 녹화를 얻으면 같은 방법으로 채우면 된다:
#     python vision/dg5f/probe_landmarks.py bend   → analyze_abduction.py
ABD_BEND_SIN_DEG = {
    "index": 0.0,     # 미측정(위 ⚠️ 참고)
    "middle": 0.0,    # 미측정
    "ring": -16.8,    # 녹화 ②에서 굽힘 폭 43.7°로 측정 — 신호대오염 0.47 → 0.64
    "pinky": -38.3,   # 녹화 ②에서 굽힘 폭 71.1°로 측정 — 신호대오염 0.94 → 1.67
}

# 랜드마크 번호 → 손가락 이름(위 표를 찾을 때 쓴다). finger[0]이 그 손가락의 MCP 번호다.
_FINGER_NAME = {INDEX[0]: "index", MIDDLE[0]: "middle", RING[0]: "ring", PINKY[0]: "pinky"}


def _finger_frame(lm, finger):
    """(옆 방향 축, 손 앞 방향) 단위벡터. 못 구하면 (None, None).

    옆 방향 축은 `_bend_mcp`가 쓰는 것과 **같은 정의**다(손바닥 법선 × 손목→MCP).
    손 앞 방향은 손목→중지 MCP를 손바닥 평면에 투영한 것 — 0도의 기준이 된다.
    """
    palm_n = np.cross(lm[INDEX[0]] - lm[WRIST], lm[PINKY[0]] - lm[WRIST])
    n = np.linalg.norm(palm_n)
    if n < 1e-9:
        return None, None
    palm_n /= n
    axis = lm[finger[0]] - lm[WRIST]              # 손목→MCP = 이 손가락이 뻗은 방향
    na = np.linalg.norm(axis)
    if na < 1e-9:
        return None, None
    lat = np.cross(palm_n, axis / na)
    nl = np.linalg.norm(lat)
    if nl < 1e-9:
        return None, None
    fwd = lm[MIDDLE[0]] - lm[WRIST]
    fwd = fwd - palm_n * np.dot(fwd, palm_n)
    nf = np.linalg.norm(fwd)
    if nf < 1e-9:
        return None, None
    return lat / nl, fwd / nf


def _lateral_tilt(vec, lat):
    """벡터가 옆 방향으로 얼마나 기울었는지(rad). |성분|≤1이라 폭주하지 않는다."""
    n = np.linalg.norm(vec)
    if n < 1e-9:
        return 0.0
    return math.asin(float(np.clip(np.dot(vec / n, lat), -1.0, 1.0)))


def _abduction_lateral(lm, finger):
    """벌림각(rad). 굽힘이 섞이지 않는다(위 ABDUCTION_METHOD 설명 참고)."""
    lm = np.asarray(lm)
    lat, fwd = _finger_frame(lm, finger)
    if lat is None:
        return 0.0
    # 0도 = 손 앞방향(중지와 나란함). 옛 방식과 같은 기준이라 로봇 쪽 규약이 그대로 맞는다.
    ang = _lateral_tilt(lm[finger[1]] - lm[finger[0]], lat) - _lateral_tilt(fwd, lat)
    coeff = ABD_BEND_SIN_DEG.get(_FINGER_NAME.get(finger[0]), 0.0)
    if coeff:
        ang -= math.radians(coeff) * math.sin(_bend_mcp(lm, finger))
    return ang


def _abduction(lm, finger):
    """벌림각(rad). 실제 계산은 ABDUCTION_METHOD가 고른 방식이 한다."""
    if ABDUCTION_METHOD == "lateral":
        return _abduction_lateral(lm, finger)
    return _abduction_planar(lm, finger)


# _abduction_planar(): 옛 방식 — 중지의 근위지골(9→10) 방향을 기준으로 손가락이 얼마나 좌우로
# 벌어졌는지 계산한다. 비교·재현용으로 남겨 둔다(analyze_abduction.py가 두 방식을 대조한다).
def _abduction_planar(lm, finger):
    lm = np.asarray(lm)           # 랜드마크 리스트를 NumPy 배열로 변환처리

    # 손바닥 평면의 법선 벡터 구하는 처리
    palm_n = np.cross(            # np.cross(): 두 벡터의 외적 계산 함수로 손바닥 평면의 법선 벡터 구하기
        lm[INDEX[0]] - lm[WRIST], # 손목→검지 MCP 벡터 구하기
        lm[PINKY[0]] - lm[WRIST]  # 손목→소지 MCP 벡터 구하기
      )

    # 손바닥 법선 벡터(palm_n)의 길이 구하기 처리
    # np.linalg.norm(): 벡터의 크기(길이)를 구하는 함수, 길이 = √(x² + y² + z²) 이용
    n = np.linalg.norm(palm_n)

    # 벡터의 길이가 0(또는 거의 0)인 경우 예외 처리
    if n < 1e-9:
        return 0.0

    palm_n /= n                                  # 법선벡터 정규화(벡터길이를 1로 정규화)
    ref = lm[MIDDLE[1]] - lm[MIDDLE[0]]          # 중지 근위지골(9→10 벡터)
    v = lm[finger[1]] - lm[finger[0]]            # 대상 근위지골(대상 손가락 mcp→pip 벡터)
    
    # 중지 근위지골(9→10)벡터에서 손바닥 평면 방향 벡터 성분만 남기도록 처리
    ref -= palm_n * np.dot(ref, palm_n)          # np.dot(ref, palm_n): 중지 방향 벡터(ref)에서 손바닥 법선 방향 성분만을 남기도록 내적
                                                 # palm_n * np.dot(ref, palm_n): 내적연산으로 구한 법선 방향 벡터성분을 법선 벡터와 곱해 벡터로 만들고
                                                 # 그 값을 중지 방향 벡터(ref)에서 벡터 연산(빼기)하여 손바닥 평면 방향 벡터 성분만을 남기도록 처리.
    
    # 대상 손가락 mcp→pip 벡터에서 손바닥 평면 방향 성분만 남기도록 처리                                             
    v -= palm_n * np.dot(v, palm_n)              # 위와 근위지골(9→10)벡터와 동일하게 처리
    
    # _angle() 함수로
    ang = _angle(
        ref + lm[finger[0]],    # ref + lm[finger[0]]: 대상손가락의 mcp에서 9→10벡터의 손바닥 평면 성분벡터만큼 이동한 좌표
        lm[finger[0]],          # lm[finger[0]]      : 대상손가락의 mcp 좌표
        v + lm[finger[0]]       # v + lm[finger[0]]  : 대상손가락의 mcp에 대상 손가락 mcp→pip 벡터의 손바닥 평면 성분벡터만큼 이동한 좌표
    ) 
    
    # 중지를 기준으로 대상 손가락이 검지 쪽으로 벌어졌는지, 새끼 쪽으로 벌어졌는지를 판별
    side = np.dot(np.cross(ref, v), palm_n)
    # np.cross(ref, v): 9→10벡터에서 손바닥 평면 방향 성분만 남긴 벡터와 대상 손가락 mcp→pip 벡터에서 손바닥 평면 방향 성분만 남긴 벡터를 외적한 결과. 
    #                   두 벡터가 같은 평면(손바닥 평면)에 있으므로 결과는 palm_n 축과 나란함
    # np.dot(np.cross(ref, v), palm_n) : 위 외적 결과와 손바닥 평면 법선 벡터를 내적하여 palm_n(법선) 방향 성분의 크기만 스칼라로 남김.
    #                                    이렇게 구한 스칼라의 부호로 +면 손등 방향, -면 손바닥 방향인지 확인
    #                                    오른손 법칙에 따라 위 결과가 +면 시계방향, -면 반시계방향으로 측정한 각도
    
    # 위에서 구한 side로 최종 ang이 어느쪽으로 벌어진 것인지 부호를 결정.
    return ang if side >= 0 else -ang
    
# _thumb_abduction(): 엄지 CMC의 벌림(abduction)각을 구하는 함수.
#   엄지 근위 마디(1→2) 벡터를 손바닥 평면에 투영한 뒤,
#   손 축(손목→검지 MCP, 0→5)의 평면 투영과 이루는 각을 잰다.
#   TIP(4번)을 쓰지 않으므로 MCP·IP 굽힘이 값에 섞이지 않는다.
def _thumb_abduction(lm):
    lm = np.asarray(lm)

    # 손바닥 평면 법선 (기존 _thumb_elevation과 동일)
    n = np.cross(lm[INDEX[0]] - lm[WRIST],
                 lm[PINKY[0]] - lm[WRIST])
    nn = np.linalg.norm(n)
    if nn < 1e-9:
        return 0.0
    n /= nn

    ref = lm[INDEX[0]] - lm[WRIST]     # 손 축 벡터 (0→5)
    v   = lm[THUMB[1]] - lm[THUMB[0]]  # 엄지 근위 마디 벡터 (1→2) ← TIP 아님!

    # 두 벡터 모두 손바닥 평면에 투영 (법선 성분 제거 — _abduction과 동일 처리)
    ref = ref - n * np.dot(ref, n)
    v   = v   - n * np.dot(v, n)

    nr, nv = np.linalg.norm(ref), np.linalg.norm(v)
    if nr < 1e-9 or nv < 1e-9:
        return 0.0

    # 평면 위 두 벡터 사이 각 (크기)
    ang = float(np.arccos(np.clip(np.dot(ref / nr, v / nv), -1.0, 1.0)))

    # 부호 판정 (_abduction과 동일한 방식): 외적을 법선에 투영해 방향 결정
    side = np.dot(np.cross(ref, v), n)
    return ang if side >= 0 else -ang

# _thumb_elevation(): 엄지 손가락이 손바닥 평면으로부터 얼만큼 각도로 들려 있는지 각도를 구하는 함수
def _thumb_elevation(lm):
    lm = np.asarray(lm)    # 랜드마크 리스트를 NumPy 배열로 변환처리
    
    # 손목→중지mcp 벡터와 손목→새끼 mcp 벡터의 외적을 구해 손바닥 평면의 법선 벡터 구하기
    n = np.cross(
        lm[INDEX[0]] - lm[WRIST],    # 0→5 백터
        lm[PINKY[0]] - lm[WRIST]     # 0→17 벡터
    )
    
    # 손바닥 법선 벡터의 길이 구하기
    nn = np.linalg.norm(n)
    
    # 벡터의 길이가 0(또는 거의 0)인 경우 예외 처리
    if nn < 1e-9:
        return 0.0
    n /= nn                            # 법선벡터 정규화(벡터길이를 1로 정규화)
    
    v = lm[THUMB[1]] - lm[THUMB[0]]    # 엄지 방향 벡터(1→2 벡터)
    vn = np.linalg.norm(v)             # 엄지 방향 벡터의 길이 구하기
    
    # 벡터의 길이가 0(또는 거의 0)인 경우 예외 처리
    if vn < 1e-9:
        return 0.0
    v /= vn                            # 엄지 방향 벡터 정규화(벡터길이를 1로 정규화)
        
    # 엄지 손가락이 손바닥 평면으로부터 얼만큼 각도로 들려 있는지 각도 계산
    return float(np.arcsin(np.clip(np.dot(v, n), -1.0, 1.0)))
    # np.dot(v, n): 정규화된 엄지벡터와 정규화된 손바닥 법선 벡터를 내적하여 두 벡터 사이 각도의 cosθ을 구함.
    #               cos θ = cos(90° − φ) = sin φ 이므로 dot(v, n) = cos θ = sin φ 
    # np.clip(): cosθ 값은 -1~1 사이로 나와야하지만 컴퓨터 부동소수점 연산 오차로 범위를 벗어날 수 있으므로, -1~1 범위로 제한 처리
    # np.arcsin(): sin값을 값으로부터 실제 각도(φ)를 구하는 함수


# _thumb_opposition(): 엄지 '대향(opposition)' 정도 — 엄지끝이 손바닥을 가로질러 새끼 뿌리로
#   얼마나 다가왔는지. **각도가 아니라 거리(손 크기로 정규화)** 를 돌려준다. 대향할수록 작아진다.
#     반환값 = ‖랜드마크4(엄지끝) − 랜드마크17(소지 MCP)‖ / ‖랜드마크9(중지 MCP) − 랜드마크0(손목)‖
#   ★2026-07-27 두 번째 교체 — '평면 밖 각도' 방식을 완전히 버린 이유(원본 랜드마크 실측):
#     ① 각도 방식(arcsin(dot(v,n)/‖v‖), v=엄지 CMC1→MCP2)이 재는 마디는 **거의 손바닥 평면에 누워
#        있다**. 실측 평균 기울기 0.84~2.04°인데 잡음이 0.92~2.28° — 신호대잡음 1:1~1:2.7.
#        그래서 손을 오므리면 **부호가 19~37% 확률로 뒤집힌다**(lmprobe cup/pinkybend 실측).
#     ② 매핑이 max(0,·) 정류라 음수는 전부 0 → **파지 자세에서 엄지 명령이 죽는다**
#        (라이브 실측: 깊은 파지 구간의 55~80% 프레임이 음수, corr(엄지MCP굽힘, 대향)=−0.92~−0.97).
#     ③ 엄지가 실제로 뒤로 가는 건 **아니다** — MCP(2)점의 평면 밖 위치는 3개 녹화 전부
#        +0.098~+0.124로 **음수 프레임 0.0%**. 즉 z가 죽은 것도, 엄지가 뒤로 넘어간 것도 아니고
#        '거의 0인 기울기'를 재던 게 문제였다.
#   ★거리 방식의 이점:
#     • x·y가 지배 → MediaPipe z 품질(파지 시 가림)에 둔감
#     • **부호가 없다** → 정류가 신호를 잘라먹는 일이 원천적으로 불가능
#     • **좌우 불변** → THUMB_OPP_SIGN / THUMB_OPP_HAND_SIGN 같은 손별 부호 표가 불필요해짐
#     • 실측 신호대잡음: 현재식 3.9~9.1 → 거리식 3.8~29.8, 집기동작 상관 +0.25 → +0.91(cup)
#   ⚠️ 대향 없이 엄지를 굽히기만 해도 거리가 줄어 1_3/1_4(엄지 MCP·IP 굽힘)와 신호가 일부 겹친다.
#      파지에선 둘이 함께 일어나 실용상 문제는 작지만, "엄지만 접었는데 대향까지 들어감"이 보이면
#      엄지끝(4) 대신 IP(3)를 쓰거나 굽힘 성분을 빼는 보정이 필요하다.
def _thumb_opposition(lm):
    lm = np.asarray(lm)
    hand_len = float(np.linalg.norm(lm[MIDDLE[0]] - lm[WRIST]))   # 손 크기 = 카메라 거리 보정
    if hand_len < 1e-9:
        return THUMB_OPP_D_OPEN                                    # 판정 불가 → '펴진 상태'로
    return float(np.linalg.norm(lm[THUMB[3]] - lm[PINKY[0]])) / hand_len


def _thumb_opp_amount(d):
    """대향 프록시(거리) → 0(펴짐) ~ 1(완전대향) 비율. 거리는 대향할수록 '작아지므로' 반전한다."""
    span = THUMB_OPP_D_OPEN - THUMB_OPP_D_FULL
    if span < 1e-9:
        return 0.0
    return min(1.0, max(0.0, (THUMB_OPP_D_OPEN - d) / span))


# ── 엄지 평면 벌림(1_1) ↔ 대향(1_2) crosstalk 게이트 (기본 OFF) ─────────────────
# 배경(2026-07-21 로그 실측): _thumb_abduction(1_1)이 _thumb_opposition(1_2)과 상관 +0.98 —
#   둘이 같은 엄지 중수골(1→2) 벡터의 두 구면각(평면내 방위각=벌림/접힘, 평면밖 들림=대향)이라
#   엄지 CMC 안장관절에서 자연스럽게 함께 움직인다. 단일 뼈 벡터라 완전 분리는 원래 불가.
# ★ 사용자 요구(2026-07-21): 엄지는 대향+벌림/접힘이 '섞여서' 움직여야 하는 경우가 많다 →
#   두 프록시를 인위적으로 디커플링/게이팅하지 말고 그대로 내보내 1_1·1_2가 함께 움직이게 한다.
#   따라서 아래 게이트는 기본 OFF. (fold 중 1_1을 죽이던 이전 "옆벌림만" 처방은 이 요구와 상충.)
# THUMB_ABD_OPP_GATE=True로 켜면: 대향(opp)이 깊어질수록 벌림(1_1)을 감쇠(fold 중 1_1→중립).
#   실험용 — 특정 태스크에서 벌림 crosstalk가 방해될 때만.
THUMB_ABD_OPP_GATE = False   # 기본 OFF = 대향/벌림 혼합 허용(사용자 요구)
# ⚠️ 2026-07-27: 대향 프록시가 '각도(rad)'에서 **거리(손크기 정규화)** 로 바뀌었다.
#   게이트 임계값도 그에 맞춰 대향량(0=펴짐 ~ 1=완전대향) 기준으로 재정의했다.
OPP_GATE_LO = 0.30   # (게이트 ON일 때) 이 대향량 이하: 벌림 그대로 통과
OPP_GATE_HI = 0.70   # (게이트 ON일 때) 이 대향량 이상: 벌림 완전 차단


def _opp_gate(opp_d):
    """대향이 깊을수록 0에 가까운 게이트값[0,1]. 인자는 _thumb_opposition의 **거리** 프록시."""
    t = _thumb_opp_amount(opp_d)
    if t <= OPP_GATE_LO:
        return 1.0
    if t >= OPP_GATE_HI:
        return 0.0
    return (OPP_GATE_HI - t) / (OPP_GATE_HI - OPP_GATE_LO)


# _palm_fold():
def _palm_fold(lm):
    lm = np.asarray(lm)    # 랜드마크 리스트를 NumPy 배열로 변환처리

    # 요측(엄지쪽) 손바닥 평면의 법선 벡터 — 비교적 손바닥 접힘 운동에 안 딸려가는 검지·중지로 기준면을 만든다
    n_rad = np.cross(                  # np.cross(): 두 벡터의 외적으로 요측 평면 법선 구하기
	      lm[INDEX[0]] - lm[MIDDLE[0]],  # 중지 MCP→검지 MCP 벡터(9→5 벡터)
	      lm[MIDDLE[0]] - lm[WRIST]      # 손목→중지 MCP 벡터(0→9 벡터)
    )
    
    # 척측(새끼쪽) 손바닥 평면의 법선 벡터 — 비교적 손바닥 접힘 운동에 딸려가는 약지·새끼 MCP로 만든다
    n_uln = np.cross(
	      lm[RING[0]] - lm[WRIST],       # 손목→약지 MCP 벡터(0→13 벡터)
	      lm[PINKY[0]] - lm[WRIST]       # 손목→소지 MCP 벡터(0→17 벡터)
    )
      
    # 두 손바닥 평면이 접히는 경첩(힌지)축 벡터 구하기. 손목→약지 MCP 벡터(0→13 벡터)
    hinge = lm[RING[0]] - lm[WRIST]

    # 세 벡터의 길이를 구해 하나라도 0(또는 거의 0)이면 예외 처리
    nr, nu, nh = np.linalg.norm(n_rad), np.linalg.norm(n_uln), np.linalg.norm(hinge)
    if nr < 1e-9 or nu < 1e-9 or nh < 1e-9:
        return 0.0
    
    # 전부 단위벡터로 정규화
    n_rad, n_uln, hinge = n_rad / nr, n_uln / nu, hinge / nh

    # 두 법선 사이의 '부호 있는' 각도를 힌지축 기준으로 구하기
    x = float(np.dot(n_rad, n_uln))                    # x: 두 손바닥 평면이 접힌 각도의 cos 성분
    y = float(np.dot(np.cross(n_rad, n_uln), hinge))   # y: 두 손바닥 평면의 법선벡터의 외적을 계산하여 두 손바닥 평면의 법선벡터로 이루어진
                                                       # 평면의 법선벡터(np.cross(a, b)=|a|·|b|·sin θ)를 구하고, 
                                                       # np.cross() 벡터와 힌지축 벡터는 서로 동일한 축에 놓인 두 벡터이므로
                                                       # 내적 연산을 통해 부호를 결정하여 최종 성분을 sin 구함.

    # np.arctan2(y, x): (y, x)로부터 각도(θ)를 구하는 함수 — 단순 arctan과 달리 접힘/폄 방향(부호)까지 포함된 결과를 얻을 수 있음.
    return float(np.arctan2(y, x))


# DIP(원위 관절) 굽힘을 PIP에서 유도하는 결합계수 (2026-07-21, 격리 디버깅 결과 대응).
#   왜: DIP는 _bend(PIP→DIP→TIP)로 재는데 DIP·TIP의 z(깊이)가 MediaPipe에서 부실해 노이즈 큼
#       (사용자 관찰: 2_4·3_4·4_4 "z로 잘 추정 못함"). 해부학적으로 DIP 굴곡은 신전건 메커니즘상
#       PIP에 종속(사람도 DIP만 독립으로 못 굽힘)이라 측정 대신 PIP에서 유도하는 게 표준·강건.
#   값: DIP≈0.66~0.75×PIP(해부학). 보정파일 middle/ring 비율도 ~0.75. 튜닝: 원위가 덜/더 굽으면 ↕.
DIP_PIP_COUPLING = 0.75


def compute_raw(lm):
    # 엄지 벌림/접힘(1_1)과 대향(1_2)은 안장관절서 자연히 섞여 움직임 → 두 프록시를 독립적으로
    #   그대로 내보내 로봇 1_1·1_2가 함께(복합) 움직이게 한다(사용자 요구). 게이트는 기본 OFF.
    _opp_thumb = _thumb_opposition(lm)
    _abd_thumb = _thumb_abduction(lm)
    if THUMB_ABD_OPP_GATE:                             # (기본 False) 켜면 fold 중 벌림 감쇠 — 실험용
        _abd_thumb *= _opp_gate(_opp_thumb)
    return [
        # 엄지
        _abd_thumb,                                    # thumb_cmc(1_1): 엄지 손바닥평면 안 운동 = 벌림(검지와 수직)↔접힘(손가락과 평행). 프록시=cmc→mcp 벡터와 0→5 벡터의 손바닥평면 성분 사이각. FK: 로봇 1_1 −77°=평행(접음)/+22°=수직(벌림)
        _opp_thumb,                                    # thumb_opp(1_2): 엄지 평면 밖 대향각(손바닥서 떠서 가로질러 넘어옴). 옛 _thumb_elevation(들림각)은 손축 희석으로 과소평가라 교체(2026-07-21)
        _bend(lm, THUMB[0], THUMB[1], THUMB[2]),       # thumb_mcp(2번) 관절의 각도
        _bend(lm, THUMB[1], THUMB[2], THUMB[3]),       # thumb_ip(3번) 관절의 각도
        # 검지
        _abduction(lm, INDEX),                         # 중지의 근위지골(9→10) 방향을 기준으로 검지가 얼마나 좌우로 벌어졌는지 각도
        _bend_mcp(lm, INDEX),                          # index_mcp(5번) 관절의 각도 (굽힘평면 투영)
        _bend(lm, INDEX[0], INDEX[1], INDEX[2]),       # index_pip(6번) 관절의 각도
        DIP_PIP_COUPLING * _bend(lm, INDEX[0], INDEX[1], INDEX[2]),   # index_dip(7번): PIP에서 유도(측정 z 부실). =k×PIP
        # 중지
        _abduction(lm, MIDDLE),                        # middle_abd — 값은 계산하되 채널이 gated라 0으로 나간다(표 주석 참고)
        _bend_mcp(lm, MIDDLE),                         # middle_mcp(9번) 관절의 각도 (굽힘평면 투영)
        _bend(lm, MIDDLE[0], MIDDLE[1], MIDDLE[2]),    # middle_pip(10번) 관절의 각도
        DIP_PIP_COUPLING * _bend(lm, MIDDLE[0], MIDDLE[1], MIDDLE[2]),  # middle_dip(11번): PIP에서 유도. =k×PIP
        # 약지
        _abduction(lm, RING),                          # ring_abd — 중지(9→10) 기준 약지 벌림각
        _bend_mcp(lm, RING),                           # ring_mcp(13번) 관절의 각도 (굽힘평면 투영)
        _bend(lm, RING[0], RING[1], RING[2]),          # ring_pip(14번) 관절의 각도
        DIP_PIP_COUPLING * _bend(lm, RING[0], RING[1], RING[2]),       # ring_dip(15번): PIP에서 유도. =k×PIP
        # 새끼
        _palm_fold(lm),                                # pinky_cmc → 손바닥접기 각도, 5_1 대응용
        _abduction(lm, PINKY),                         # pinky_lat → 중지의 근위지골(9→10) 방향을 기준으로 새끼가 얼마나 좌우로 벌어졌는지 각도, 5_2 대응용
        _bend_mcp(lm, PINKY),                          # pinky_mcp(17번) 관절의 각도, 5_3 대응용 (굽힘평면 투영)
        (1.0 + DIP_PIP_COUPLING) * _bend(lm, PINKY[0], PINKY[1], PINKY[2]),  # pinky 원위(5_4): 로봇은 원위관절 1개뿐 → 사람 PIP+DIP 합을 PIP에서 유도((1+k)×PIP). 옛 (PIP+측정DIP)/2는 DIP z부실로 과소(사용자: "덜 움직임")
    ]

# 채널 테이블:
GATED_NEUTRAL_DEG = 0.0

# 왼손 모델용 부호 반전 채널
#   ★thumb_cmc 제외(2026-07-21): 1_1은 이제 |abd|→로봇[접힘,벌림] 양방향 선형매핑으로 왼손모델
#     각을 '직접' 산출하므로 여기서 또 반전하면 안 됨(FK가 왼손 URDF 기준이었음). 우수 모델은
#     THUMB_CMC_FOLD_DEG/SPREAD_DEG 부호를 뒤집어 대응(주석 참고).
LEFT_MIRROR_CHANNELS = {
    "thumb_opp", "thumb_mcp", "thumb_ip",
    "index_abd", "middle_abd", "ring_abd",
    "pinky_cmc", "pinky_lat",
}

# 우수(right) 모델에서만 부호를 뒤집는 채널 (2026-07-27 추가)
#   thumb_cmc(1_1)는 LEFT_MIRROR_CHANNELS에 없다(|abd|→[FOLD,SPREAD] 직접 산출). 그런데 그
#   FOLD/SPREAD·RATIO_LIMIT 값이 **왼손 URDF 기준**이라 우수 URDF에선 그대로 쓰면 안 된다:
#   좌수 1_1 리밋 [-77,+22] ↔ 우수 [-22,+77] (Y축 거울).
#   실측(로그 rad_dg5f_20260727_143610, 우수 로봇 라이브): 뒤집기 전 명령 -65.0..-4.8 →
#   **82.1%가 하한(-22°) 밖으로 잘려** 가동폭이 좌수 65° → 우수 24°로 붕괴(로봇 -22에 42.8% 포화).
#   뒤집으면 명령 +4.8..+65.0, 리밋 이탈 0.0%.
#   ★한 곳(끝단 부호 반전)에서 처리하는 근거: direct는 deg=FOLD+t·(SPREAD−FOLD), ratio는
#     deg=rmin+t·(rmax−rmin)로 **두 끝점에 대해 선형**이므로 −deg는 두 끝점을 모두 반전한 것과
#     완전히 동일하다. 그래서 상수를 손대지 않고 direct/ratio 양쪽이 함께 맞는다.
#   ⚠️ 따라서 GUI의 1_1 '로봇 lo/hi' 슬라이더는 **항상 왼손 기준값**이고, right 모드에서는
#     자동 반전돼 로봇에 적용된다(프리셋도 왼손 기준으로 저장됨).
RIGHT_MIRROR_CHANNELS = {"thumb_cmc"}

# 벌림(좌우) 채널 — 사람 벌림각(rad)을 로봇 벌림각(deg)으로 **1:1 직접 매핑**(로봇 범위로 clamp).
#   percentile min/max 정규화를 쓰면 안 되는 이유(2026-07-20 실측): 보정 세션에서 벌림을 조금만 해도
#   사람 범위가 좁게 잡혀(예 index 양수쪽 hmax=0.096rad=5.5°) 로봇 dmax=20°까지 ~3.6배 증폭 →
#   "사람보다 훨씬 많이 벌어짐". 로봇 벌림 가동범위(±20~30°)가 사람 손가락 벌림 범위(±20~25°)와
#   비슷해 1:1이 자연스럽다. raw=0(중지와 평행=모음)→0°는 자동으로 성립(부호 있는 각이라).
#   ABD_GAIN을 키우면 더 과장, 줄이면 더 절제 — 라이브 체감으로 미세조정.
# thumb_cmc는 0을 사이에 두지 않는 벌림(hmin/hmax 둘 다 음수)이라 여기서 제외 — 기존 선형 유지.
ABDUCTION_CHANNELS = {"index_abd", "middle_abd", "ring_abd", "pinky_lat"}
ABD_GAIN = 1.0  # 로봇도 = 사람 벌림각(deg) × 이 값. 1.0 = 1:1(증폭 없음).

# ── 엄지 대향(thumb_opp, 1_2) 거리 프록시 상수 ────────────────────────────────
# 프록시 = ‖엄지끝(4) − 소지MCP(17)‖ / ‖중지MCP(9) − 손목(0)‖  (_thumb_opposition 참조)
#   D_OPEN = 손을 쫙 폈을 때(엄지도 옆으로 벌림)의 거리 — 여기서 대향량 0
#   D_FULL = 엄지끝을 새끼 뿌리에 최대한 붙였을 때의 거리 — 여기서 대향량 1(로봇 최대 대향)
# ★좌우 공통이다 — 거리는 거울상에 불변이라 손별 상수가 원리적으로 불필요하다.
#   (그래서 옛 THUMB_OPP_SIGN / THUMB_OPP_HAND_SIGN 부호 표를 통째로 제거했다.)
# ★확정값(2026-07-27 lmprobe_grasp_left/right 실측, 각 ~1200프레임 · 펴기/완전대향/집게파지 3자세):
#     펴짐 중앙값     왼 1.019 / 오 1.058  → D_OPEN은 **작은 쪽**(1.02)으로: 양손 다 rest 누출 0
#     완전대향 중앙값  왼 0.227 / 오 0.247  → D_FULL은 **큰 쪽**(0.25)으로: 양손 다 풀스케일 도달
#   좌우 차이가 펴짐 3.7% / 대향 8%로 작아 **손별 상수 불필요**가 실측으로 확인됐다.
#   집게 파지(엄지-검지) 자세는 거리 0.68~0.69 → 대향량 0.43 → 로봇 ≈41°. 죽지 않고 제대로 반응.
#   랜드마크쌍 선택 근거(4개 후보 비교): 4↔17이 span 0.62~0.67·신호대잡음 7.4~11.0으로 최고.
#     (3↔17은 span 0.40, 2↔17은 0.22로 좁고, 4↔13은 좌우 일치는 좋으나 span·SNR이 낮음)
# ★2026-07-28 종횡비 등방 보정(landmarks_to_xyz)에 맞춰 재산출:
#   이 프록시는 **방향이 다른 두 거리의 비**(엄지끝→소지MCP / 중지MCP→손목)라 비등방 보정이
#   상쇄되지 않고 값이 통째로 커진다. 같은 07-27 녹화로 보정 전/후 배율을 재보니 분포 전 구간
#   (p2~p99)에서 **1.22~1.32로 일정** → 위 실측 튜닝값의 의도를 그대로 살려 배율만 곱했다.
#     D_OPEN 1.02 × 1.30(펴짐측 배율) = 1.33      D_FULL 0.25 × 1.25(대향측 배율) = 0.31
#   ⚠️ LM_ASPECT_FIX=False로 되돌릴 땐 이 두 값도 1.02 / 0.25로 함께 되돌릴 것.
# 튜닝: 중립에서 엄지가 미리 들어가 있으면 D_OPEN↓, 끝까지 대향이 안 되면 D_FULL↑.
THUMB_OPP_D_OPEN = 1.33     # 펴진 상태 거리(큼)   — 옛 비등방 좌표 기준 1.02
THUMB_OPP_D_FULL = 0.31     # 완전대향 거리(작음) — 옛 비등방 좌표 기준 0.25

# direct 모드에서 대향량(0~1)을 로봇 각도로 바꿀 때의 최대각[deg]. 로봇 clamp는 -155(URDF 전 범위).
#   ratio 모드는 이 값을 쓰지 않는다(THUMB_OPP_RATIO_MAX_DEG가 담당).
THUMB_OPP_GAIN = 95.0



# 엄지 손바닥평면 벌림/접힘(thumb_cmc, 1_1): |abd| → 로봇 [접힘, 벌림] 양방향 선형매핑.
#   ★왜 부호/미러가 아니라 크기 매핑인가(2026-07-21 실데이터 진단):
#     _thumb_abduction 실측값은 파이프라인상 '항상 음수'(보정 -1.4~-30°, lmprobe -7.6~-22°)이고,
#     벌림(엄지-검지 수직)=|각| 큼 / 접힘(엄지 손가락과 평행)=|각| 작음(≈0). 즉 두 동작이 부호가
#     아니라 '크기'로 구분된다. 게다가 이 프록시 부호는 손 방향·거울상에 불변(검증) → 부호 뒤집기는
#     방향 교정이 아니라 채널을 죽일 뿐. 그래서 |abd|를 로봇 양방향각에 직접 선형매핑한다.
#   FK(왼손 URDF): 로봇 1_1 −77°=평행(접음) / +22°=수직(벌림) / 0=중립. LEFT_MIRROR 제외(직접 산출).
#   튜닝: 벌림이 부족/과하면 SPREAD_DEG, 접힘이 부족/과하면 FOLD_DEG. 사람 |abd| 범위가 다르면 H_*.
#   ⚠️우수(right) 모델은 FOLD_DEG/SPREAD_DEG 부호를 뒤집을 것(왼손 기준 값임).
THUMB_CMC_FOLD_DEG   = -65.0   # 사람이 엄지 완전히 접었을 때(손가락과 평행) 로봇 1_1 목표각
THUMB_CMC_SPREAD_DEG = 22.0    # 사람이 엄지 완전히 벌렸을 때(검지와 수직) 로봇 1_1 목표각
THUMB_CMC_H_FOLD     = 0.03    # 접힘일 때 사람 |abd|(rad, 작음). 이 값→FOLD_DEG
THUMB_CMC_H_SPREAD   = 0.52    # 벌림일 때 사람 |abd|(rad, 큼).   이 값→SPREAD_DEG

DG5F_CHANNELS = [
    # name          hmin   hmax    dg_min  dg_max  gated
    # ★2026-07-21: map_to_dg5f 전 채널 1:1 전환. dg_min/dg_max = 로봇 clamp 경계(가동범위).
    #   hmin/hmax는 매핑에서 미사용(보정 로드가 덮어써도 무해) — 기록/스키마용으로만 남김.
    #   굽힘 채널 dg_max = 로봇 관절 최대각(사람이 더 굽히면 여기서 포화).
    # thumb_cmc(1_1): 2026-07-21 |abd|→로봇[접힘,벌림] 양방향 선형매핑(THUMB_CMC_* 상수·분기 참조).
    #   dmin/dmax(0,65)·hmin/hmax는 이 채널에선 미사용(분기가 자체 [FOLD_DEG,SPREAD_DEG]로 클램프).
    #   실사용 범위 = [THUMB_CMC_FOLD_DEG, THUMB_CMC_SPREAD_DEG] = 기본 [-65, +22]°(왼손).
    ("thumb_cmc",  -0.52, -0.03,    0.0,   65.0,  False),
    # thumb_opp(1_2, 대향): ⚠️ hmin/hmax(0.15,0.85)는 **미사용**이다. 이 채널만 프록시 단위가
    #   각도(rad)가 아니라 '거리'라서 보정 파일 값이 의미 없고, 매핑은 THUMB_OPP_D_OPEN/D_FULL이 담당.
    #   (보정 로드가 이 자리를 덮어써도 무해 — 두 특수분기 어디서도 읽지 않는다.)
    #   dmax -75→-155(2026-07-21) — 로봇 clamp가 -75(≈손바닥 법선)에서
    #   잘려 사람처럼 손바닥 안쪽까지 못 접혔음. URDF 한계 155°까지 열어 깊은 대향 허용(GAIN 1.5와 함께).
    #   dmin=0(평면). 신 프록시 _thumb_opposition + THUMB_OPP_GAIN로 이 범위를 채운다.
    ("thumb_opp",   0.15,  0.85,    0.0, -155.0,  False),
    ("thumb_mcp",   0.05,  0.90,    0.0,   80.0,  False),
    ("thumb_ip",    0.05,  1.20,    0.0,   80.0,  False),
    ("index_abd",  -0.30,  0.30,  -25.0,   20.0,  False),
    ("index_mcp",   0.05,  1.20,    0.0,  110.0,  False),
    ("index_pip",   0.10,  1.80,    0.0,   85.0,  False),
    ("index_dip",   0.05,  1.20,    0.0,   80.0,  False),
    # middle_abd(3_1): 2026-09-16부터 gated(항상 0). 옛 계산식에서는 "중지 기준 상대 벌림"이라
    #   중지 자신은 정의상 0이었다. 새 계산식은 손가락마다 자기 축으로 재므로 중지도 값이
    #   생기는데(실측: 손 편 상태 폭 3.9°, 손 오므릴 때 14.4°), 아무도 요청하지 않은 움직임을
    #   새로 만들 이유가 없어 예전 결과(0)를 유지한다. 중지 벌림을 살리고 싶으면 True→False만
    #   바꾸면 된다 — 계산은 이미 나와 있다.
    ("middle_abd", -0.30,  0.30,  -20.0,   20.0,  True),
    ("middle_mcp",  0.05,  1.20,    0.0,  110.0,  False),
    ("middle_pip",  0.10,  1.80,    0.0,   85.0,  False),
    ("middle_dip",  0.05,  1.20,    0.0,   80.0,  False),
    ("ring_abd",   -0.30,  0.30,  -12.0,   28.0,  False),
    ("ring_mcp",    0.05,  1.20,    0.0,  105.0,  False),
    ("ring_pip",    0.10,  1.80,    0.0,   85.0,  False),
    ("ring_dip",    0.05,  1.20,    0.0,   80.0,  False),
    # pinky_cmc(5_1, 손바닥 접기): 2026-07-20 게이트(사용자 요청) — 앞굽힘을 가장 크게 망치는 오염원.
    #   프록시 raw는 컵핑(22°)>굽힘오염(7.7°)로 신호가 있으나, 사람범위 6.9°→로봇 50°로 7.2배 증폭돼
    #   굽힘만 해도 로봇 5_1이 40° 스윙 + 정지 노이즈 14°도 증폭. SNR 나빠 유지가치 낮음.
    #   컵핑을 조금 살리려면 gated False + dg (50,0)→(12,0)으로 '아주 적게 제한'이 대안(주석 참고).
    ("pinky_cmc",   0.09,  0.21,   50.0,    0.0,  True),
    # pinky_lat(5_2): 2026-09-16 ±12° → (-15, 50)으로 확대. **"벌려도 안 움직인다"의 직접 원인**이
    #   이 ±12°였다 — 사람 새끼의 좌우 폭이 그보다 훨씬 커서 보정 기록의 78.5%가 잘려 나갔고,
    #   라이브 기록에서는 34%가 정확히 +12.0°에 붙어 있었다(중앙값 +10.3°). 손을 가만히 둬도
    #   이미 한계값이라 더 벌려도 로봇이 반응할 수 없었다.
    #   ±12°로 좁혀 뒀던 이유(2026-07-20)는 굽힘이 이 값에 섞여 들어와서였는데, 그 원인을
    #   계산식 쪽에서 고쳤다(ABDUCTION_METHOD="lateral" + 굽힘 보정 — 실측 오염 76.7°→26.0°,
    #   굽힘 상관 -0.94→+0.04). 그래서 이제 넓혀도 손가락이 엉뚱하게 흔들리지 않는다.
    #   상한 50°: 실측 사람 벌림 p98이 +48.8°(2026-09-16 녹화). 기구 한계는 +90°라 여유가 있다.
    #   하한 -15°: 기구 한계 그대로(실물 Motor 18 = -15°~+90°, DG5F_JOINT_RANGES.md §2).
    ("pinky_lat",  -0.30,  0.30,  -15.0,   50.0,  False),
    ("pinky_mcp",   0.05,  1.20,    0.0,   85.0,  False),
    ("pinky_pip",   0.10,  1.80,    0.0,   80.0,  False),
]

CHANNEL_NAMES = [c[0] for c in DG5F_CHANNELS]

# ── 비율(0~1) 매핑 모드용 로봇 관절 URDF 기구 리밋[deg] ────────────────────────
#   출처: joint_ranges.py SPEC의 URDF <limit> 열(이번 세션 왼손 미러 URDF 기준).
#   ★2026-07-21 사용자 요청: map_to_dg5f(mode="ratio")가 이 범위를 로봇 [min,max]로 써서
#     사람각을 [사람min,사람max]→[0,1]→[로봇min,로봇max]로 정규화 매핑한다(아래 _map_ratio).
#   ⚠️ 기구 리밋은 실제 사용범위(DG5F_CHANNELS dg_min/dg_max)보다 넓다(pip/dip ±90 등).
#     → 비율이 안 쓰는 극단 영역까지 분산돼 같은 사람동작에도 로봇 움직임이 작아진다(사용자 인지·선택).
#     또 굽힘 관절 리밋 하한이 −90(과신전 여유)이라 사람 rest(≈사람min)가 로봇 −90 근처로 갈 수 있음.
#     rest 포즈가 뒤로 젖혀 보이면 RATIO_ROBOT_RANGE를 "use"로 바꿔 재평가할 것(한 줄).
#   ⚠️⚠️ 좌표계 함정(2026-07-28): 이 표는 **좌수** URDF다. 그런데 _map_ratio가 만드는 값은
#     LEFT_MIRROR_CHANNELS에 대해 함수 끝에서 hand=="left"일 때 부호 반전되므로, 반전 전 단계는
#     **우수 좌표계**다. 따라서 LEFT_MIRROR 채널에 이 표를 경계로 쓰면 양손 모두 거울상으로
#     어긋난다. 그런 채널은 RATIO_LIMIT에 우수 기준 값을 명시해 폴백을 끊는다(벌림 3채널이 그 예).
#     이 표 자체는 '좌수 URDF의 사실'이므로 값을 고치지 말 것 — joint_ranges.py SPEC과 짝이다.
URDF_LIMITS_DEG = {
    "thumb_cmc": (-77.0,  22.0), "thumb_opp": (0.0, 155.0),
    "thumb_mcp": (-90.0,  90.0), "thumb_ip":  (-90.0, 90.0),
    "index_abd": (-20.0,  31.0), "index_mcp": (0.0, 115.0),
    "index_pip": (-90.0,  90.0), "index_dip": (-90.0, 90.0),
    "middle_abd": (-25.0, 25.0), "middle_mcp": (0.0, 115.0),
    "middle_pip": (-90.0, 90.0), "middle_dip": (-90.0, 90.0),
    "ring_abd": (-32.0,  15.0),  "ring_mcp":  (0.0, 110.0),
    "ring_pip": (-90.0,  90.0),  "ring_dip":  (-90.0, 90.0),
    "pinky_cmc": (-60.0,  0.0),  "pinky_lat": (-90.0, 15.0),
    "pinky_mcp": (-90.0,  90.0), "pinky_pip": (-90.0, 90.0),
}

# 비율 모드가 로봇 [min,max]로 무엇을 쓸지: "urdf"=기구 리밋(사용자 선택) / "use"=DG5F_CHANNELS 사용범위.
RATIO_ROBOT_RANGE = "urdf"

# ── 비율 모드 채널별 로봇 출력 한계[deg] (URDF/use 대신 이 값을 최우선 사용) ─────────────
#   2026-07-22 라이브 관절디버깅 피드백 반영. URDF 리밋(±90 등)이면 사람보다 과하게 움직이거나
#   (특히 굽힘 관절) 사람이 못 하는 뒤꺾임(과신전, rmin=−90)까지 나온다. → 사람 실제 ROM으로 조인다.
#   여기 '없는' 채널은 URDF 리밋(RATIO_ROBOT_RANGE)로 폴백한다. (rmin,rmax) 의미는 채널별 주석 참조.
#   ⚠️ 폴백은 LEFT_MIRROR_CHANNELS 채널에 쓰면 안 된다 — URDF_LIMITS_DEG가 좌수 표라 좌표계가
#     어긋난다(2026-07-28 벌림 3채널 사고, 아래 벌림 블록 주석 참조). 그런 채널은 여기 명시할 것.
#   ⚠️ 첫 튜닝값 — 라이브 보고 이 숫자만 조정하면 됨.
RATIO_LIMIT = {
    # ── 엄지 ──
    # thumb_cmc(1_1): rmin=접힘(fold,−)/rmax=벌림(spread,+). 접힘 OK(−65 유지), 벌림 과함 +22→+10.
    "thumb_cmc": (-65.0, 10.0),
    # thumb_mcp(1_3)/thumb_ip(1_4): 안쪽 굽힘만 사람스러움 → URDF −90(과신전) 제거, 0(1자)..80.
    "thumb_mcp": (0.0, 80.0),
    "thumb_ip":  (0.0, 80.0),
    # (thumb_opp 1_2는 단방향 특수분기 → THUMB_OPP_RATIO_MAX_DEG로 따로 제한)
    # ── 손가락 굽힘(mcp/pip/dip): ★공통 — 사람은 뒤로 못 꺾음 → rmin=0(과신전 금지). rmax=사람 굽힘 한계 ──
    # 검지: 2_2 굽힘 잘 되나 약간 과함 → rmax 110→95. 2_3/2_4는 URDF −90이라 손 펴면 뒤로 꺾이던 것 제거.
    "index_mcp": (0.0, 95.0), "index_pip": (0.0, 85.0), "index_dip": (0.0, 80.0),
    # 중지·약지·새끼도 동일한 뒤꺾임 문제라 예방적으로 rmin=0 적용(rmax=각 손가락 사람 굽힘 한계).
    "middle_mcp": (0.0, 95.0),  "middle_pip": (0.0, 85.0), "middle_dip": (0.0, 80.0),
    "ring_mcp":   (0.0, 105.0), "ring_pip":   (0.0, 85.0), "ring_dip":   (0.0, 80.0),
    "pinky_mcp":  (0.0, 85.0),  "pinky_pip":  (0.0, 80.0),
    # ── 벌림(abduction) ★2026-07-28 추가 (그 전엔 일부러 비워 URDF 폴백을 썼는데, 그게 버그였다) ──
    #   무엇이 틀렸나: URDF_LIMITS_DEG는 **좌수** URDF 표다. 그런데 이 채널들은 LEFT_MIRROR_CHANNELS
    #   소속이라 값이 함수 끝에서 hand=="left"일 때만 부호 반전된다 — 즉 반전 '전' 단계의 값은
    #   **우수 좌표계**여야 한다. 좌수 경계를 그대로 물린 탓에 **양손 모두** 명령 가능범위가
    #   구동 중인 로봇 가동범위의 정확히 거울상이 됐다:
    #       hand=right(반전 없음) → [-20,+31] 인데 우수 로봇은 [-31,+20]
    #       hand=left (반전됨)    → [-31,+20] 인데 좌수 로봇은 [-20,+31]
    #   같은 LEFT_MIRROR인 thumb_opp(−95..0)·thumb_mcp/ip(0..80)는 이미 우수 기준이라 멀쩡했고,
    #   벌림 셋만 좌수 표를 물고 있었다. (direct 모드는 DG5F_CHANNELS use범위가 양손 다 들어맞아 무사)
    #   실측 근거(unity_dg5f 4개 런, 07-28): 한쪽 끝에 붙어 있던 시간 2_1 5.1%/4_1 3.5%/5_2 20.1%,
    #   반대쪽으로는 각각 11°/17°/75°를 한 번도 못 씀. 5_2는 vis_rad→joint_rad 상관이 0.33까지 붕괴.
    #   방향(부호)은 건드리지 않는다 — vis_rad(사람 프록시)가 좌/우 손에서 부호 불변임을 4개 런에서
    #   확인했고(index −5~−7°, ring +3.6~+5.7°로 일관), 따라서 끝단 반전이 곧 로봇 거울 대응이라 정상.
    #   ⚠️ 여기 값은 **우수 URDF 기준**으로 적을 것(좌수 표의 negate&swap). 좌수 값을 적으면 원위치.
    "index_abd": (-31.0, 20.0),   # 우수 URDF 그대로 (좌수 -20..31 의 negate&swap)
    "ring_abd":  (-15.0, 32.0),   # 우수 URDF 그대로 (좌수 -32..15)
    # pinky_lat(5_2): 우수 URDF는 (-15,+90)이지만 편측 90°는 사람 새끼 벌림의 5배다
    #   (실측 피크가 리밋 대비 5.2~5.8배). 사람 ROM으로 조인다 — 첫 튜닝값, 라이브 보고 조정.
    "pinky_lat": (-15.0, 25.0),
    # middle_abd(3_1)는 기준 손가락이라 항상 0 + 리밋이 대칭(±25) → 폴백이어도 무해해서 그대로 둔다.
    # pinky_cmc(5_1)는 gated(항상 0). 게이트를 풀면 여기에 우수 기준 (0,60)을 넣을 것.
}

# thumb_opp(1_2) 비율 모드 손바닥쪽(대향) 최대각[deg]. 부호는 direct와 동일(−, left-mirror가 +로).
#   URDF −155면 엄지가 새끼 손바닥에 닿을 만큼 과회전 → 사람 대향 한계로 축소(−95).
#   더 깊게 대향하려면 크기↑(예 −110), 덜이면 크기↓(예 −80).
#   ※ 손등쪽(음의 대향)은 MediaPipe z가 부실해 신뢰 불가 → rest(0)로 고정(로봇 관절도 대개 단방향).
THUMB_OPP_RATIO_MAX_DEG = -95.0


def _robot_range(name, dmin, dmax):
    """비율 모드용 로봇 [min,max](deg). 채널별 한계(RATIO_LIMIT) 최우선 →
    없으면 RATIO_ROBOT_RANGE에 따라 URDF 리밋 또는 DG5F 사용범위."""
    if name in RATIO_LIMIT:
        return RATIO_LIMIT[name]
    if RATIO_ROBOT_RANGE == "urdf" and name in URDF_LIMITS_DEG:
        return URDF_LIMITS_DEG[name]
    return dmin, dmax


def _map_ratio(raw, hand):
    """사람 관절 프록시(rad) → DG5F 로봇 관절각(deg). **비율(0~1) 정규화 매핑**(2026-07-21 신규 모드).
    채널마다 t = clamp01((v − 사람min)/(사람max − 사람min)) 로 사람각을 0~1 비율로 바꾸고,
    로봇각 = 로봇min + t·(로봇max − 로봇min) 로 로봇 범위에 그대로 실어보낸다(사람비율=로봇비율).
      • 사람 min/max = DG5F_CHANNELS의 hmin/hmax(= calibration.json human_ranges, 실행 시 로드).
      • 로봇 min/max = _robot_range() (기본 URDF 기구 리밋, RATIO_ROBOT_RANGE로 전환).
    ⚠️ 정규화라 보정 신선도에 민감: 보정 때 관절을 끝까지 안 움직였거나(폭 좁음) 프록시 정의가
       보정 이후 바뀐 채널(2026-07-21 thumb_cmc/thumb_opp)은 t가 빗나갈 수 있음 → 재보정 권장.
       폭 0(예 middle_abd)은 t=0(로봇min 고정)으로 처리(0나누기 방지)."""
    out = []
    for v, (name, hmin, hmax, dmin, dmax, gated) in zip(raw, DG5F_CHANNELS):
        if gated:
            out.append(GATED_NEUTRAL_DEG)
            continue
        if name == "thumb_cmc":
            # ★thumb_cmc(1_1)는 부호가 아니라 |abd| '크기'로 접힘/벌림을 구분한다(direct 모드와
            #   동일 원리 — _thumb_abduction 원값은 항상 음수, 작은|v|=접힘·큰|v|=벌림). 균일 비율식을
            #   그대로 쓰면 v가 hmin(큰 음수)일수록 t=0→rmin이 돼 '벌림→접힘'으로 안/바깥이 뒤집힌다.
            #   → |v|를 사람 [|min|,|max|] 비율로 바꿔 로봇 [접힘(rmin), 벌림(rmax)]에 실어 방향을 맞춘다.
            rmin, rmax = _robot_range(name, dmin, dmax)   # URDF (-77접힘, +22벌림)
            a_lo, a_hi = min(abs(hmin), abs(hmax)), max(abs(hmin), abs(hmax))
            aspan = a_hi - a_lo
            t = (abs(v) - a_lo) / aspan if aspan > 1e-9 else 0.0
            t = min(1.0, max(0.0, t))
            deg = rmin + t * (rmax - rmin)
        elif name == "thumb_opp":
            # ★thumb_opp(1_2)는 단방향 동작(펴짐→대향)이고, 프록시가 **거리**라 균일 비율식을 못 쓴다.
            #   _thumb_opp_amount가 [D_OPEN, D_FULL] 거리를 0~1 대향량으로 뒤집어 준다(대향할수록 거리↓).
            #   부호가 없는 양이므로 손별 부호 표(옛 THUMB_OPP_HAND_SIGN)가 필요 없다 —
            #   로봇 좌우 방향은 아래 left-mirror가 담당한다.
            deg = _thumb_opp_amount(v) * THUMB_OPP_RATIO_MAX_DEG   # 0(펴짐) .. MAX(−95, 완전대향)
        elif name in ABDUCTION_CHANNELS:
            # ★벌림은 0중심 양방향 신호(v=0=중립=손가락 평행). 균일 비율식은 중립을 0°로 안 보내
            #   (예 pinky_lat v=0→+41.6°) rest에서 손가락이 옆으로 휘어버림 → 0을 중심으로 각 방향을
            #   독립 선형매핑해 v=0→0°를 보장한다. 방향(부호)은 균일식과 동일 → 방향감 불변, 오프셋만 제거.
            rmin, rmax = _robot_range(name, dmin, dmax)
            if v >= 0:
                t = v / hmax if hmax > 1e-9 else 0.0      # 0..1 (v: 0..사람 양(+)쪽 최대)
                deg = min(1.0, t) * rmax
            else:
                t = v / hmin if hmin < -1e-9 else 0.0     # 0..1 (v: 0..사람 음(−)쪽 최대)
                deg = min(1.0, t) * rmin
        else:
            rmin, rmax = _robot_range(name, dmin, dmax)
            span = hmax - hmin
            t = (v - hmin) / span if abs(span) > 1e-9 else 0.0
            t = min(1.0, max(0.0, t))                     # 사람 비율 [0,1]
            deg = rmin + t * (rmax - rmin)                # 로봇 비율 → 로봇각
            deg = min(max(rmin, rmax), max(min(rmin, rmax), deg))  # 안전 clamp
        if hand == "left" and name in LEFT_MIRROR_CHANNELS:
            deg = -deg
        elif hand == "right" and name in RIGHT_MIRROR_CHANNELS:
            deg = -deg          # 왼손 기준 FOLD/SPREAD·RATIO_LIMIT → 우수 URDF 부호로
        out.append(deg)
    return out


def map_to_dg5f(raw, hand="right", mode="direct"):
    """사람 관절 프록시(rad) → DG5F 로봇 관절각(deg).
    mode="direct"(기본): **전 채널 1:1 직접매핑**(2026-07-21). 사람 관절각을 그대로 로봇각으로
      보내고 로봇 가동범위[dmin,dmax]로만 clamp. 사람이 로봇 한계보다 크게 움직이면 포화.
      옛 percentile 선형이 만들던 증폭(예 index_mcp 4.8×)을 근본 제거. hmin/hmax 미사용.
    mode="ratio": **비율(0~1) 정규화 매핑**. [사람min,사람max]→[0,1]→[로봇min,로봇max](_map_ratio 참조).
      사람/로봇 범위를 각각 0~1 비율로 바꿔 사람비율을 로봇비율로 그대로 옮긴다."""
    if mode == "ratio":
        return _map_ratio(raw, hand)
    out = []
    for v, (name, _hmin, _hmax, dmin, dmax, gated) in zip(raw, DG5F_CHANNELS):
        if gated:
            out.append(GATED_NEUTRAL_DEG)
            continue
        if name in ABDUCTION_CHANNELS:
            # 벌림 1:1: 사람 벌림각(rad)→deg × ABD_GAIN, [dmin,dmax] clamp. raw=0→0°(중립) 자동 성립.
            # middle_abd는 기준(중지 자기 자신)이라 v≈0 → deg≈0 (0나누기 없음 — 1:1은 나눗셈 안 함).
            deg = math.degrees(v) * ABD_GAIN
            deg = min(dmax, max(dmin, deg))
        elif name == "thumb_opp":
            # 대향량(0~1, 거리 프록시) × 최대각 → 로봇 깊이각. dmin=0/dmax=-155 부호 맞춰 음수.
            #   direct라도 프록시가 각도가 아니라 거리라 '1:1'이 성립하지 않는다 → GAIN이 스케일 담당.
            deg = -_thumb_opp_amount(v) * THUMB_OPP_GAIN
            deg = max(dmax, min(dmin, deg))
        elif name == "thumb_cmc":
            # 벌림/접힘: |abd|(벌림 크기, 방향·거울 불변)를 [H_FOLD,H_SPREAD]→[FOLD_DEG,SPREAD_DEG] 선형.
            #   작은 |abd|(접힘)→FOLD_DEG(−), 큰 |abd|(벌림)→SPREAD_DEG(+). 왼손 각 직접 산출(미러 제외).
            span = THUMB_CMC_H_SPREAD - THUMB_CMC_H_FOLD
            t = (abs(v) - THUMB_CMC_H_FOLD) / span if span > 1e-9 else 0.0
            t = min(1.0, max(0.0, t))
            deg = THUMB_CMC_FOLD_DEG + t * (THUMB_CMC_SPREAD_DEG - THUMB_CMC_FOLD_DEG)
        else:
            # 굽힘(flexion) 1:1: 사람 관절각(_bend는 항상 ≥0, rad)→deg 그대로, [0,dmax(로봇최대)] clamp.
            # 사람이 로봇 기구한계보다 더 굽히면 한계각에서 포화(사용범위 내내 1:1, 끝에서만 어긋남).
            deg = math.degrees(v)
            deg = min(dmax, max(dmin, deg))
        if hand == "left" and name in LEFT_MIRROR_CHANNELS:
            deg = -deg
        elif hand == "right" and name in RIGHT_MIRROR_CHANNELS:
            deg = -deg          # 왼손 기준 FOLD/SPREAD·RATIO_LIMIT → 우수 URDF 부호로
        out.append(deg)
    return out

# 엄지 손끝 위치 리타게팅
PINCH_ON, PINCH_OFF = 0.30, 0.42

# 사람 엄지 직진도 상한
DEFAULT_THUMB_STRAIGHT = 0.97
CALIB_VERSION = 3  # v3: thumb_straight_ratio(직진도). v2 thumb_reach_ratio(직선/손길이)는 폐기.
_thumb_straight_calib = None

# 손가락(검지~새끼) 직진도 상한
DEFAULT_FINGER_STRAIGHT = 0.98

# 리치벡터를 싣는 손가락(패킷 [25..36] 순서 고정) — 엄지는 [20..22]에 따로 있어 제외.
TIP_FINGERS = [("index", INDEX), ("middle", MIDDLE), ("ring", RING), ("pinky", PINKY)]
# v5 새 방식(로봇 관점 IK)용: 손목→끝 벡터를 싣는 5손가락 (엄지 포함, 엄지부터).
WRIST_TIP_FINGERS = [("thumb", THUMB), ("index", INDEX), ("middle", MIDDLE),
                     ("ring", RING), ("pinky", PINKY)]

# =========================================================================
# 패킷 레이아웃 (Unity Dg5fReceiver와 계약 — 수신기는 **길이로** 버전 판별)
#   v1 <20f>: [0..19] 관절각[deg]
#   v2 <24f>: + [20..22] 엄지 리치벡터, [23] 핀치 플래그
#   v3 <25f>: + [24] 엄지-검지 끝거리비
#   v4 <37f>: + [25..36] 검지/중지/약지/새끼 리치벡터 (각 3, TIP_FINGERS 순서)
#   v5 <52f>: + [37..51] 손목→끝 벡터 5개 (엄지·검지·중지·약지·새끼, WRIST_TIP_FINGERS 순서,
#             각 3 = 해부학 프레임 성분 ÷ 손길이) — 새 방식(로봇 관점 IK, ikMode=RobotRootTipVector)
#   v6 <72f>: + [52..71] compute_raw()의 20채널 **라디안 원값**(매핑·필터 전, 프록시 출력 그대로) —
#             디버그용. Unity가 비전 라디안 vs 로봇 관절 라디안을 직접 비교/로깅하는 데 씀.
# ⚠️ 수신기 판별이 `>=`라 상위 버전을 하위 Unity에 쏴도 앞부분만 읽고 뒤는 무시된다(양방향 호환).
#    v6를 v5까지 아는 Unity에 쏴도 라디안 필드만 무시, 나머지 동작 불변.
# =========================================================================
PACKET_FMT = "<72f"
PACKET_LEN = 72


def _anat_frame(lm):
    wrist, mid_mcp = lm[WRIST], lm[MIDDLE[0]]
    hand_len = float(np.linalg.norm(mid_mcp - wrist))
    if hand_len < 1e-6:
        return None
    ez = (mid_mcp - wrist) / hand_len
    ey_raw = lm[INDEX[0]] - lm[PINKY[0]]
    ex = np.cross(ey_raw, ez)
    ex /= max(np.linalg.norm(ex), 1e-9)
    ey = np.cross(ez, ex)
    return ex, ey, ez, hand_len


def _reach_vector(lm, chain_idx, cap, ex, ey, ez):
    d = lm[chain_idx[3]] - lm[chain_idx[0]]
    straight = float(np.linalg.norm(d))
    chain = float(np.linalg.norm(lm[chain_idx[1]] - lm[chain_idx[0]])
                  + np.linalg.norm(lm[chain_idx[2]] - lm[chain_idx[1]])
                  + np.linalg.norm(lm[chain_idx[3]] - lm[chain_idx[2]]))
    if straight < 1e-9 or chain < 1e-9:
        return (0.0, 0.0, 0.0)
    m = min(1.0, straight / (chain * cap))
    u = d / straight
    return (m * float(np.dot(u, ex)), m * float(np.dot(u, ey)), m * float(np.dot(u, ez)))


def compute_thumb_tip(lm):
    lm = np.asarray(lm)
    frame = _anat_frame(lm)
    if frame is None:
        return (0.0, 0.0, 0.0), 0.0
    ex, ey, ez, hand_len = frame
    cap = _thumb_straight_calib if _thumb_straight_calib is not None else DEFAULT_THUMB_STRAIGHT
    tip = _reach_vector(lm, THUMB, cap, ex, ey, ez)
    pinch_d = float(np.linalg.norm(lm[THUMB[3]] - lm[INDEX[3]]) / hand_len)
    return tip, pinch_d


def compute_finger_tips(lm):
    lm = np.asarray(lm)
    frame = _anat_frame(lm)
    if frame is None:
        return [0.0] * 12
    ex, ey, ez, _ = frame
    out = []
    for _name, idx in TIP_FINGERS:
        out.extend(_reach_vector(lm, idx, DEFAULT_FINGER_STRAIGHT, ex, ey, ez))
    return out


def compute_wrist_tip_vectors(lm):
    lm = np.asarray(lm)
    frame = _anat_frame(lm)
    if frame is None:
        return [0.0] * (3 * len(WRIST_TIP_FINGERS))
    ex, ey, ez, hand_len = frame
    wrist = lm[WRIST]
    out = []
    for _name, idx in WRIST_TIP_FINGERS:
        v = lm[idx[3]] - wrist                       # idx[3] = 끝 landmark
        out.extend([float(np.dot(v, ex)) / hand_len,
                    float(np.dot(v, ey)) / hand_len,
                    float(np.dot(v, ez)) / hand_len])
    return out


# --- 보정 파일 자동 로드 (calibrate_raw.py 방식과 동일 스키마) ---
_CALIB_PATH = CALIB_PATH


def _load_calibration():
    global DG5F_CHANNELS, _thumb_straight_calib
    if not os.path.exists(_CALIB_PATH):
        return False
    try:
        with open(_CALIB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        hr = data.get("human_ranges", {})
    except Exception as e:
        print(f"[dg5f_angles] 보정 파일 읽기 실패({e}) — 기본값 사용")
        return False
    ver = int(data.get("version", 1))
    ts = data.get("thumb_straight_ratio")
    if ver >= CALIB_VERSION and ts:
        _thumb_straight_calib = float(ts)
        print(f"[dg5f_angles] 엄지 직진도 상한 보정값 사용: {_thumb_straight_calib:.3f}")
    else:
        print(f"[dg5f_angles] 엄지 직진도 상한 = 기본값 {DEFAULT_THUMB_STRAIGHT} "
              f"(보정 파일 v{ver}, thumb_straight_ratio 없음 — 무보정 동작 정상. "
              "더 정밀히 맞추려면 calibrate_dg5f.py 재실행). human_ranges는 그대로 사용.")
    # 보정 범위 폭이 0이면 기본값 유지 — map_to_dg5f가 폭 0이면 t=0(dg_min 고정)이 되는 함정.
    # 예: middle_abd는 기준(중지)과 자기 자신 비교라 정의상 항상 0 → 보정이 (0,0)을 저장함
    # (2026-07-20 실보정에서 발각: 중지 3_1이 -20°로 상시 누움).
    def _rng(n, hmin, hmax):
        if n in hr:
            lo, hi = float(hr[n]["min"]), float(hr[n]["max"])
            if hi - lo > 1e-6:
                return lo, hi
            print(f"[dg5f_angles] {n}: 보정 범위 폭 0 — 기본값({hmin}, {hmax}) 유지")
        return hmin, hmax

    DG5F_CHANNELS = [
        (n, *_rng(n, hmin, hmax), dmin, dmax, g)
        for (n, hmin, hmax, dmin, dmax, g) in DG5F_CHANNELS]
    return True


if _load_calibration():
    print(f"[dg5f_angles] 보정값 로드됨: {_CALIB_PATH}")
