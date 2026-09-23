# -*- coding: utf-8 -*-
"""MediaPipe 손 관절 점 + D405 깊이 → 관절마다 **실제 입체 위치(미터)** (2026-09-23 시험).

왜: 웹캠 한 대로는 "엄지가 손바닥 앞으로 얼마나 나왔나"(앞뒤)를 사진 한 장으로 추측해야 해서
집게를 정면으로 보여 줘야 했다. D405 는 화소마다 거리를 재므로, MediaPipe 가 찾은 관절 위치의
거리를 그대로 읽으면 앞뒤를 추측이 아니라 **잰다.**

🛑 시험 결과 (2026-09-23): **텔레옵에는 쓰지 않는다 — 웹캠 방식보다 못했다.**
  D405 녹화(정면 10자세·옆 6자세, 손 21~33 cm, 관절 깊이 97~99% 읽음)를 `analyze_hand_poses.py`로
  비교한 "가르는 힘"(사진 점 / 이 파일의 입체 점): 정면 붙이기 vs 엄지 앞으로 3.40 / 1.42,
  옆 붙이기 vs 집게 10.90 / 1.50, 옆 붙이기 vs 앞으로 4.68 / 1.00. 나아진 것은 정면 집게의
  엄지끝~검지끝 거리뿐(1.71 / 4.76). 추정 원인: 관절 점이 손가락 가장자리에 찍혀 배경·옆 손가락
  깊이가 섞이고, 엄지가 앞으로 나오면 다른 관절을 가린다. 다시 시도하려면 이 원인부터 풀 것
  (예: 관절 점이 아니라 손가락 뼈 선을 따라 깊이 읽기). 기록: claudeDocs/daily/2026-09-23.md.

무엇을 하나 (카메라 없이 시험할 수 있게 계산만 여기 둔다 — 여는 것은 `record_hand_poses.py`):
  관절 점(사진 위 비율 좌표) → 화소 위치 → 그 주변 작은 창의 깊이 중앙값 → 핀홀 역투영.

주의:
- **거울 모드.** 텔레옵은 사진을 좌우로 뒤집어 MediaPipe 에 넣는다(`cv2.flip(frame, 1)`).
  깊이도 **똑같이 뒤집어야** 같은 화소가 같은 점이 된다. 뒤집은 사진의 광학 중심은
  cx' = (가로 - 1) - cx 다 — `mirror=True` 로 넘기면 여기서 처리한다.
- **손가락끼리 가림.** 손끝이 다른 손가락 뒤에 있으면 그 화소의 거리는 앞 손가락의 거리다.
  여기서는 창 안의 값 중 **가장 가까운 무리**를 쓰는 대신 단순 중앙값을 쓰고, 손목에서 너무
  먼(손 크기보다 큰 앞뒤 차이) 값은 버린다 — 어느 쪽이 나은지는 녹화로 판단한다.
- 못 읽은 관절은 NaN 이다. 채워 넣지 않는다(지어낸 값 금지).
"""
import numpy as np

#: 깊이를 읽을 창의 반지름(화소). 848x480 에서 손끝 한 마디가 대략 10~20 화소라 2(=5x5)로 둔다.
DEFAULT_RADIUS_PX = 2

#: 손목 깊이와 이만큼(m) 넘게 차이 나면 그 관절 깊이는 버린다 — 손 뒤 배경/책상을 읽은 것.
#: 손 길이(손목→중지끝) 약 0.18 m 보다 넉넉히.
MAX_DEPTH_FROM_WRIST_M = 0.20


def sample_depth(depth_m, u, v, radius=DEFAULT_RADIUS_PX, near=0.0, far=np.inf):
    """(u, v) 화소 주변 (2r+1)^2 창의 **유효한 깊이 중앙값**(m). 하나도 없으면 NaN."""
    h, w = depth_m.shape
    ui, vi = int(round(u)), int(round(v))
    if not (0 <= ui < w and 0 <= vi < h):
        return float("nan")
    win = depth_m[max(0, vi - radius):vi + radius + 1, max(0, ui - radius):ui + radius + 1]
    vals = win[np.isfinite(win) & (win > near) & (win < far)]
    return float(np.median(vals)) if vals.size else float("nan")


def landmarks_3d(lm_norm, depth_m, fx, fy, cx, cy, mirror=False, near=0.0, far=np.inf,
                 radius=DEFAULT_RADIUS_PX, max_from_wrist=MAX_DEPTH_FROM_WRIST_M):
    """관절 점(21x2 이상, MediaPipe 비율 좌표 x·y) → (21x3 카메라 기준 미터, 읽었는가 21개).

    `fx, fy, cx, cy` 는 **뒤집기 전** 카메라 값(RealSense 가 알려 주는 그대로). `mirror=True` 면
    사진·깊이를 좌우로 뒤집은 것으로 보고 중심을 맞춘다. 좌표 방향은 x 오른쪽, y 아래, z 앞(멀어짐)
    — MediaPipe 사진 좌표와 같은 방향이라 각도 계산(dg5f_angles)이 그대로 받는다.
    """
    lm = np.asarray(lm_norm, dtype=float)
    h, w = depth_m.shape
    cxm = (w - 1) - cx if mirror else cx
    u = lm[:, 0] * w
    v = lm[:, 1] * h
    z = np.array([sample_depth(depth_m, ui, vi, radius, near, far) for ui, vi in zip(u, v)])
    if np.isfinite(z[0]) and max_from_wrist is not None:
        z[np.abs(z - z[0]) > max_from_wrist] = np.nan
    pts = np.stack([(u - cxm) * z / fx, (v - cy) * z / fy, z], axis=1)
    return pts, np.isfinite(z)
