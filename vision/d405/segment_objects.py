# -*- coding: utf-8 -*-
"""점 덩어리에서 **물체만 남긴다** — 책상과 배경을 뺀다.

왜 필요한가
-----------
카메라가 한 번에 주는 점이 **60만 개**인데 대부분 책상·벽·모니터다. 우리가 자세를
정할 때 보는 것은 **물체 하나**뿐이다. 그래서 물체만 잘라내야 한다.

`docs/EXTERNAL_GRASP_POLICY_SURVEY.md` 가 "🟡 없음 — 만들어야 한다" 로 지목한 부분이다.

왜 YOLO 를 안 쓰나
------------------
YOLO 같은 것은 **미리 배운 종류**만 찾는다. 우리 목적은 **처음 보는 물체**를 잡는
것이라 정면으로 어긋난다(`CLAUDE.md` 프로젝트 목적).

대신 **생김새만 보고** 나눈다. 물체는 책상 위에 놓여 있으므로:

1. 가장 넓은 **평평한 면**(책상)을 찾는다
2. 그 면과 그 아래를 버린다
3. 남은 점들을 **서로 붙어 있는 덩어리**로 묶는다 → 덩어리 하나가 물체 하나

배운 것이 하나도 없으므로 **처음 보는 물체에도 그대로 된다.**

어떻게 평평한 면을 찾나
-----------------------
점 3개를 아무거나 뽑아 면을 만들고, 그 면에 가까운 점이 몇 개인지 센다. 이걸 여러 번
반복해 **가장 많은 점이 붙은 면**을 고른다. 책상은 화면에서 가장 넓으므로 이게 책상이다.

⚠️ **책상이 안 보이면 이 방법이 틀린 면을 고른다** — 벽이나 물체 자체의 평평한 면을
   책상으로 착각할 수 있다. 그래서 `plane_ok()` 로 **"고른 면이 정말 바닥 같은가"** 를
   확인하고, 아니면 평면 빼기를 건너뛴다(조용히 틀리지 않게).

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트) — **눈으로 보기**:

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/segment_objects.py --live

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python vision/d405/segment_objects.py --live

한 장만 찍어 파일로 남기기:

    python vision/d405/segment_objects.py --save
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 면에서 이만큼(m) 안쪽이면 "그 면 위의 점" 으로 본다. 깊이 흔들림(파지 거리에서
#: 0.4 mm 수준)보다 넉넉히 크게 잡아야 책상이 깨끗이 빠진다.
PLANE_TOL_M = 0.008

#: 평평한 면 찾기를 몇 번 시도하나. 많을수록 정확하지만 느리다.
PLANE_TRIES = 200

#: 이 비율보다 적은 점이 붙은 면은 "책상" 으로 안 본다 — 책상이 안 보이는 장면에서
#: 엉뚱한 면을 빼지 않으려는 장치다.
PLANE_MIN_FRAC = 0.15

#: 덩어리로 묶을 때 쓰는 격자 칸 크기(m). 이 정도 안에 붙어 있으면 같은 물체로 본다.
#: 작으면 물체 하나가 여러 개로 쪼개지고, 크면 옆 물체와 붙는다.
CLUSTER_CELL_M = 0.012

#: 다시 쪼갤 때 칸을 얼마씩 줄일지, 그리고 어디까지 줄일지.
#: ⚠️ **왜 다시 쪼개나 (2026-09-18, 사용자가 화면에서 발견).**
#: *"큰 종이컵, 작은 종이컵이 나란히 있으면 둘을 한 물체로 식별한다"*
#: 칸을 처음부터 작게 잡으면 컵 하나가 여러 조각으로 부서진다. 그래서 **일단 크게 묶고,
#: 손보다 큰 덩어리만 더 촘촘한 칸으로 다시 묶어 본다.** 가는 다리부터 먼저 끊어지므로
#: **붙은 것만 갈라지고 멀쩡한 물체는 안 부서진다.**
#: (책상이 거의 안 보여 못 빼는 탓에 남은 드문 점이 물체 사이를 다리처럼 잇는다 —
#:  그 다리가 바로 이 방법으로 끊긴다)
SPLIT_SHRINK = 0.6
SPLIT_MIN_CELL_M = 0.004

#: 이보다 큰 덩어리는 **쪼개기를 시도한다**. 기준은 "손에 들어가는 크기" 여야 한다 —
#: 처음에 물체 목록에서 걸러내는 한계(MAX_SIZE_M = 30 cm)로 잡았더니 25 cm 짜리 뭉치가
#: 그대로 남았다(2026-09-18). 잡을 수 있는 크기를 넘으면 붙은 것으로 의심하는 게 맞다.
#: 값의 근거는 `GRASPABLE_MAX_M` 과 같다(손보다 큰 것).
SPLIT_ABOVE_M = 0.16

#: 이보다 점이 적은 덩어리는 버린다(잡음).
MIN_POINTS = 120

#: 물체로 볼 크기 범위(m). 손이 잡을 수 있는 것만 남긴다 —
#: 근거: superdex/scripts/survey_object_assets.py 의 크기 기준(최소변 4 cm ~ 최대변 16 cm).
#: 여기서는 카메라가 한쪽만 보므로 조금 느슨하게 잡는다.
MIN_SIZE_M = 0.02
MAX_SIZE_M = 0.30


@dataclass
class ObjectCloud:
    """잘라낸 물체 하나."""
    points: np.ndarray          # (N, 3) 카메라 기준 좌표(m)
    center: np.ndarray          # (3,) 가운데
    size: np.ndarray            # (3,) 가로·세로·깊이 크기
    n_points: int
    track_id: int = -1          # 장면이 바뀌어도 **같은 물체면 같은 번호** (Tracker 가 매긴다)
    seen_frames: int = 0        # 몇 장면 연속으로 보였나 — 클수록 믿을 만하다
    source: str = "모양"        # 어디서 나왔나 — "모양" / "YOLO:cup 89%"
    #: ⚠️ **크기를 재지 못하고 추정한 것인가.** 흰 종이컵처럼 거리값이 몇 개밖에 안 나오면
    #:    점으로 크기를 잴 수 없어 **테두리와 거리 하나로 계산**한다(`yolo_assist.py`).
    #:    잡으러 갈지 정할 때 이 표시를 보고 **덜 믿어야 한다.**
    estimated: bool = False
    why: str = ""               # 추정이라면 왜 그랬는지 한 줄
    #: 이 덩어리가 **원래 점 목록의 몇 번째 줄들**이었나. 값으로 되찾으면 어긋나므로
    #: 번호를 그대로 들고 다닌다(`_raw_clusters` 주석 참고).
    index: Optional[np.ndarray] = None

    @property
    def max_side_m(self) -> float:
        return float(self.size.max())

    @property
    def distance_m(self) -> float:
        return float(self.center[2])


def fit_plane(points, tries=PLANE_TRIES, tol=PLANE_TOL_M, seed=0):
    """가장 많은 점이 붙어 있는 **평평한 면**을 찾는다.

    돌려주는 것: `(법선 3개, 상수, 그 면에 붙은 점 표시)`.
    면 위의 점은 `법선·점 + 상수 ≈ 0` 을 만족한다.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return None, None, np.zeros(len(pts), dtype=bool)
    rng = np.random.default_rng(seed)
    best_n, best_d, best_in = None, None, np.zeros(len(pts), dtype=bool)
    # 속도를 위해 일부만 보고 면을 찾는다 — 면을 정하는 데는 이걸로 충분하다
    sample = pts if len(pts) <= 20000 else pts[rng.choice(len(pts), 20000, replace=False)]
    for _ in range(tries):
        idx = rng.choice(len(sample), 3, replace=False)
        a, b, c = sample[idx]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        d = -float(n @ a)
        inliers = np.abs(sample @ n + d) < tol
        if best_in is None or inliers.sum() > best_in.sum():
            best_n, best_d, best_in = n, d, inliers
    if best_n is None:
        return None, None, np.zeros(len(pts), dtype=bool)
    # 정한 면으로 **전체 점**을 다시 판정한다
    return best_n, best_d, np.abs(pts @ best_n + best_d) < tol


def plane_ok(points, inliers, min_frac=PLANE_MIN_FRAC):
    """찾은 면을 **책상으로 믿어도 되나**.

    붙은 점이 너무 적으면 책상이 아니라 우연히 맞은 면일 수 있다. 그때는 빼지 않는다 —
    물체를 통째로 지워 버리는 것보다 배경이 남는 편이 낫다.

    🛑 **미해결 — 이 검사는 "화면을 넓게 채우는 평면인가"만 본다 (2026-09-21 코드
    리뷰로 확인, 의도적으로 아직 안 고침).** 벽·모니터 화면·상자 옆면도 화면을 넓게
    채우면 이 검사를 통과해 "책상"으로 오인될 수 있다. 진짜로 필요한 확인
    — "그 평면이 바닥에 가깝고 수평인가", "작업 영역 안인가" — 은 **로봇 밑동(base)
    좌표**에서만 뜻이 있는데, 그러려면 손목 카메라 장착값 실측(D-7, 아직 장비 대기
    ⏸)이 먼저 끝나야 한다. D-7이 끝나지 않은 지금 base-frame 가정을 여기 박아 넣으면
    "확실하지 않은 것을 확실한 것처럼 계산하는" 실수가 된다 — 그래서 지금은 손대지
    않는다. D-7이 끝나면 `arm/eye_in_hand.py`의 `camera_to_base()`로 평면 법선과
    중심점을 base 좌표로 옮긴 뒤, 다음을 추가할 것: (1) 법선이 "위쪽"에 가까운가
    (2) 높이가 작업대로 알려진 범위 안인가 (3) 중심점이 작업 영역 안인가. 그 전까지는
    지금처럼 "확실하지 않으면 지우지 않는다"가 맞는 방향이다.
    """
    return len(points) > 0 and float(inliers.mean()) >= min_frac


def remove_plane(points, colors=None):
    """책상 면과 **그 뒤쪽(카메라에서 먼 쪽)** 을 뺀다.

    면만 빼면 책상 아래·뒤의 점이 남는다. 물체는 책상보다 **카메라에 가까운 쪽**에
    있으므로, 카메라 쪽에 있는 점만 남긴다.

    ⚠️ **카메라 쪽을 어떻게 정하는가 (2026-09-21 코드 리뷰로 수정).** 예전에는 "점이 더
    많이 붙은 쪽"을 카메라 쪽으로 가정했다 — 하지만 `fit_plane()`이 뽑는 법선(`n`)의
    방향은 임의라서(3점을 어떤 순서로 뽑았느냐에 따라 뒤집힐 수 있다), "점이 많은 쪽 =
    카메라 쪽"이라는 보장이 없다. 예를 들어 물체가 책상보다 화면을 더 많이 채우면
    점 개수만으로는 반대쪽(책상 아래·뒤)을 카메라 쪽으로 잘못 고를 수 있다.

    이 점 구름은 **카메라 기준 좌표계**다(`_to_points()`가 그렇게 만든다) — 즉 카메라
    원점은 언제나 `(0, 0, 0)`이다. 평면 방정식 `n·p + d = 0`에 원점을 넣으면 가리키는
    값은 그냥 `d`이므로, **카메라 쪽은 부호가 `d`와 같은 쪽**이다(점 개수와 무관하게
    법선 방향만으로 정해지는 사실이다). 팔목에 달린 카메라(eye-in-hand)가 움직여도
    "카메라 원점 = (0,0,0)"이라는 좌표계 정의 자체가 매 프레임 다시 성립하므로 이
    판정은 그대로 쓸 수 있다.
    """
    pts = np.asarray(points, dtype=np.float64)
    n, d, inl = fit_plane(pts)
    if n is None or not plane_ok(pts, inl):
        # 책상은 매끈한 단색이라 무늬가 없어 **거의 안 잡힌다**(2026-09-18 실측).
        # 그래서 이 갈래로 빠지는 일이 흔하다. 물체를 통째로 지우는 것보다 낫지만,
        # 남은 드문 점이 물체 사이를 잇는 다리가 되므로 cluster() 가 다시 쪼갠다.
        return pts, colors, None, "평평한 면을 못 찾았다(책상이 거의 안 보임) — 배경을 둔다"

    signed = pts @ n + d
    # 카메라 원점(0,0,0)에서의 부호 = d 그 자체. 그 부호와 같은 쪽이 카메라 쪽이다.
    camera_side = signed > PLANE_TOL_M if d > 0 else signed < -PLANE_TOL_M
    keep = camera_side
    note = "평평한 면 제거 — 붙은 점 {:.0%}, 남긴 점 {:.0%}".format(
        float(inl.mean()), float(keep.mean()))
    return pts[keep], (colors[keep] if colors is not None else None), (n, d), note


def _raw_clusters(points, cell, min_points):
    """칸 격자로 한 번 묶는다. 크기 판정 없이 **점 번호 묶음**만 돌려준다.

    ⚠️ 점 자체가 아니라 **번호(index)** 를 돌려준다. 값을 돌려주면 "이 점이 원래 몇 번째
       줄이었나" 를 나중에 값 비교로 되찾아야 하는데, float32/float64 를 오가면서 값이
       미세하게 달라져 **하나도 못 찾는 일**이 실제로 있었다(2026-09-18).
    """
    from scipy import ndimage

    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < min_points:
        return []
    lo = pts.min(axis=0)
    idx = np.floor((pts - lo) / cell).astype(np.int64)
    shape = idx.max(axis=0) + 1
    if np.prod(shape.astype(np.float64)) > 4e7:      # 너무 크면 칸을 키운다
        return _raw_clusters(points, cell * 2, min_points)

    grid = np.zeros(shape, dtype=bool)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    labels, n = ndimage.label(grid, structure=np.ones((3, 3, 3), dtype=int))
    per_point = labels[idx[:, 0], idx[:, 1], idx[:, 2]]
    out = []
    for k in range(1, n + 1):
        sel = per_point == k
        if int(sel.sum()) >= min_points:
            out.append(np.flatnonzero(sel))
    return out


def _split_if_too_big(pts, idx, cell, min_points, depth=0):
    """손보다 큰 묶음이면 **더 촘촘한 칸으로 다시 묶어 본다.**

    쪼개지면 쪼갠 것을 쓰고, 더 못 쪼개면 그대로 둔다(억지로 자르지 않는다).
    `idx` 는 `pts` 안에서의 점 번호이고, 돌려주는 것도 같은 기준의 번호다.
    """
    chunk = pts[idx]
    size = chunk.max(axis=0) - chunk.min(axis=0)
    if float(size.max()) <= SPLIT_ABOVE_M or cell <= SPLIT_MIN_CELL_M or depth >= 6:
        return [idx]
    smaller = cell * SPLIT_SHRINK
    pieces = [idx[p] for p in _raw_clusters(chunk, smaller, min_points)]
    if len(pieces) <= 1:
        # 더 촘촘하게 해도 안 갈라진다 — 진짜 하나로 이어진 것이다
        return [idx] if not pieces else _split_if_too_big(
            pts, pieces[0], smaller, min_points, depth + 1)
    out = []
    for p in pieces:
        out.extend(_split_if_too_big(pts, p, smaller, min_points, depth + 1))
    return out


def cluster(points, cell=CLUSTER_CELL_M, min_points=MIN_POINTS):
    """서로 붙어 있는 점들을 **덩어리**로 묶는다.

    칸 격자에 점을 넣고, 붙어 있는 칸끼리 이어 붙인다. 학습이 필요 없고 빠르다.
    그다음 **손보다 큰 덩어리만 더 촘촘한 칸으로 다시 쪼갠다**(위 SPLIT_* 주석 참고).
    """
    pts = np.asarray(points, dtype=np.float64)
    out = []
    for chunk_idx in _raw_clusters(pts, cell, min_points):
        for idx in _split_if_too_big(pts, chunk_idx, cell, min_points):
            if len(idx) < min_points:
                continue
            piece = pts[idx]
            size = piece.max(axis=0) - piece.min(axis=0)
            if not (MIN_SIZE_M <= float(size.max()) <= MAX_SIZE_M):
                continue
            out.append(ObjectCloud(points=piece.astype(np.float32),
                                   center=piece.mean(axis=0), size=size,
                                   n_points=len(piece), index=idx))
    out.sort(key=lambda o: -o.n_points)
    return out


def find_objects(points, colors=None, near=None, far=None):
    """점 덩어리 → **물체 목록**. 한 줄로 쓰는 입구.

    돌려주는 것: `(물체 목록, 남은 점, 설명 문구)`
    """
    pts = np.asarray(points, dtype=np.float64)
    near = cfg.D405_NEAR_M if near is None else near
    far = cfg.D405_FAR_M if far is None else far
    sel = (pts[:, 2] >= near) & (pts[:, 2] <= far)
    pts, colors = pts[sel], (colors[sel] if colors is not None else None)
    if len(pts) == 0:
        return [], pts, "그 거리 범위({:.2f}~{:.2f} m) 안에 점이 없다".format(near, far)

    rest, rest_c, plane, note = remove_plane(pts, colors)
    objs = cluster(rest)
    return objs, rest, "{} / 덩어리 {}개".format(note, len(objs))


#: 장면이 바뀔 때 "같은 물체" 로 볼 최대 이동 거리(m). 물체는 가만히 있고 카메라만
#: 조금 흔들리므로 이 정도면 충분하다. 크게 잡으면 옆 물체와 헷갈린다.
TRACK_MAX_MOVE_M = 0.05

#: 이 장면 수만큼 안 보이면 그 번호를 버린다. 깊이가 깜빡이므로 한두 장면 빠지는 것은
#: 흔하다 — 바로 버리면 번호가 계속 바뀐다.
TRACK_KEEP_MISSING = 8


class Tracker:
    """**같은 물체에 같은 번호**를 계속 준다.

    왜 필요한가
    -----------
    덩어리 묶기는 장면마다 처음부터 다시 한다. 그래서 번호가 매번 뒤바뀌어 **화면 색이
    깜빡거리고**, 더 중요하게는 "아까 그 물체" 를 못 알아본다. 우리 방식이
    **"보고 → 정하고 → 가고 → 다시 보기"** 이므로, 다시 봤을 때 같은 물체인지 알아야 한다.

    방법은 단순하다: 지난 장면의 물체 가운데와 **가장 가까운 것**에 같은 번호를 준다.
    물체는 가만히 있고 카메라만 조금 흔들리므로 이것으로 충분하다.
    """

    def __init__(self, max_move=TRACK_MAX_MOVE_M, keep_missing=TRACK_KEEP_MISSING):
        self.max_move = float(max_move)
        self.keep_missing = int(keep_missing)
        self._next_id = 1
        self._tracks = {}          # id -> [가운데, 안 보인 장면 수, 본 장면 수]

    def reset(self):
        """**관측 세션을 새로 시작한다** — 이전 물체와의 번호 이어붙이기를 끊는다.

        왜 필요한가 (eye-in-hand, D-7 손눈보정 전까지의 임시 정책)
        -----------------------------------------------------------
        `Tracker` 는 **카메라 기준 좌표**의 이동 거리로 같은 물체를 판단한다
        (`TRACK_MAX_MOVE_M`). 그런데 eye-in-hand 는 "물체는 그대로, 카메라가
        움직인다" — 팔이 10 cm 이동하면 카메라 기준으로는 물체가 10 cm 움직인
        것처럼 보여 **`TRACK_MAX_MOVE_M` 을 가볍게 넘는다.** 이 상태로 계속
        `update()` 를 부르면 같은 물체에 새 번호를 주거나(가벼운 문제), 이동
        도중 우연히 가까운 다른 물체와 번호를 잘못 이어 붙일 수 있다(더 나쁜
        문제) — 카메라 기준 좌표만으로는 둘을 구분할 수 없다.

        D-7(손목 카메라 위치 맞추기)이 끝나 물체 중심을 로봇 밑동(base) 좌표로
        옮길 수 있게 되면 이동 중에도 번호를 이어 줄 수 있지만, 그 전까지는
        **"관측 세션" 단위로 번호를 다시 매기는 것**이 유일하게 안전한 정책이다
        (`docs/FESTA_PREGRASP_PLAN.md` §1 "보고 → 정하고 → 가고 → 다시 보기").

        쓰는 법::

            팔 이동 시작 → tracker.reset()
            팔 정지 → (새 관측 시작) → tracker.update(objs)

        `_next_id` 는 이어서 늘어난다(번호를 재사용하지 않는다) — 화면에 "3번"이
        두 번 다른 물체를 가리키며 나타나는 혼란을 막기 위함이다.
        """
        self._tracks = {}

    def update(self, objs: List[ObjectCloud]) -> List[ObjectCloud]:
        used = set()
        for o in objs:
            best, best_d = None, self.max_move
            for tid, (center, _missing, _seen) in self._tracks.items():
                if tid in used:
                    continue
                d = float(np.linalg.norm(o.center - center))
                if d < best_d:
                    best, best_d = tid, d
            if best is None:
                best = self._next_id
                self._next_id += 1
                self._tracks[best] = [o.center.copy(), 0, 0]
            used.add(best)
            seen = self._tracks[best][2] + 1
            self._tracks[best] = [o.center.copy(), 0, seen]
            o.track_id = best
            o.seen_frames = seen

        for tid in list(self._tracks):
            if tid in used:
                continue
            self._tracks[tid][1] += 1
            if self._tracks[tid][1] > self.keep_missing:
                del self._tracks[tid]
        return objs


def describe(objs: List[ObjectCloud]) -> str:
    if not objs:
        return "물체를 못 찾았다"
    lines = []
    for i, o in enumerate(objs[:6]):
        lines.append("  {}번 [{:4s}] 점 {:6d}개  거리 {:.3f} m  크기 {:.1f}x{:.1f}x{:.1f} cm".format(
            o.track_id if o.track_id > 0 else i + 1, size_verdict(o)[1],
            o.n_points, o.distance_m, *(o.size * 100)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 눈으로 보기 (원칙 6)
# --------------------------------------------------------------------------
def _to_points(depth_m, intr, color_img=None):
    ys, xs = np.nonzero(depth_m > 0)
    z = depth_m[ys, xs]
    pts = np.stack([(xs - intr.ppx) * z / intr.fx,
                    (ys - intr.ppy) * z / intr.fy, z], axis=1)
    cols = None
    if color_img is not None and color_img.shape[:2] == depth_m.shape:
        cols = color_img[ys, xs]
    return pts, cols, (ys, xs)


#: 손이 잡을 수 있는 크기(m). `superdex/scripts/survey_object_assets.py` 의 실측 기준
#: (최소변 4 cm ~ 최대변 16 cm)에서 왔다. 한쪽만 보이므로 아래쪽은 조금 느슨하게 본다.
GRASPABLE_MIN_M = 0.03
GRASPABLE_MAX_M = 0.16


def is_grasp_candidate(obj: "ObjectCloud") -> bool:
    """이 물체를 **실제로 잡으러 갈 후보**로 믿어도 되나.

    2026-09-21 사용자 결정: "모양"(geometry) 안전망은 **화면에는 계속 보여주되**,
    **잡으러 가는 후보 선정에서는 YOLO 가 확실히 인식한 것만 믿는다.**

    왜 이렇게 나눴나
    -----------------
    "모양" 경로는 YOLO 가 모르는(또는 이번처럼 각도 때문에 놓친) 물체도 어떻게든
    화면에 보여주는 **안전망**이다(`CLAUDE.md` 프로젝트 목적 — "처음 보는 물체도
    잡는다"). 이걸 완전히 꺼 버리면 학습된 12종 밖의 물체가 **화면에서 통째로
    사라진다** — 그건 이 프로젝트의 핵심 목표를 포기하는 것과 같다.

    그런데 "모양" 경로는 이름도 크기 상식도 없이 **순수하게 가까이 붙은 점끼리만
    묶는다.** 반사되는 병처럼 거리값이 군데군데 끊기는 물체를 여러 조각으로
    쪼개거나(2026-09-21, 페트병 실측으로 재현), 책상 위 다른 물건·배경 일부를
    같이 집어 올 수 있다 — **보여주는 용도로는 괜찮지만, 팔을 실제로 보낼
    근거로는 아직 약하다.**

    그래서 절충: **화면·로그에는 둘 다 계속 뜨지만**, 나중에 "어느 물체로 팔을
    보낼지" 고르는 단계에서는 이 함수가 `True` 인 것만 후보로 쓴다.

    ⚠️ 아직 이 함수를 실제로 호출해 팔을 보내는 코드는 없다(D-7 손눈보정 전까지는
    관측과 팔 이동이 안 엮여 있다) — 지금은 **판정 기준만** 마련해 둔 것이다.
    """
    return obj.source.startswith("YOLO:")


def size_verdict(obj: "ObjectCloud"):
    """덩어리 크기가 **손에 들어가나**. `(색 BGR, 한 글자 표시)`.

    색에 뜻을 준다 — 잘라낸 덩어리가 진짜 잡을 만한 물체인지 한눈에 보이게.
    (전에는 발견 순서대로 색을 돌려 썼는데, 그건 아무 뜻이 없었다)
    """
    big = obj.max_side_m
    if big > GRASPABLE_MAX_M:
        return (0, 0, 255), "큼"          # 빨강 — 손보다 크다
    if big < GRASPABLE_MIN_M:
        return (255, 128, 0), "작음"      # 파랑 — 지문 1~2개만 닿는다
    return (0, 255, 0), "잡을만"          # 초록 — 손에 들어간다


def main() -> int:
    ap = argparse.ArgumentParser(description="책상·배경을 빼고 물체만 남긴다")
    ap.add_argument("--live", action="store_true", help="실시간 창으로 본다")
    ap.add_argument("--save", action="store_true", help="한 장 찍어 사진·점으로 남긴다")
    ap.add_argument("--near", type=float, default=None)
    ap.add_argument("--far", type=float, default=None)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--cloud", default=None, help="카메라 대신 저장해 둔 npz 로 시험")
    args = ap.parse_args()

    near = cfg.D405_NEAR_M if args.near is None else args.near
    far = cfg.D405_FAR_M if args.far is None else args.far

    # --- 저장된 점으로 시험 (카메라 없이) ---------------------------------
    if args.cloud:
        data = np.load(args.cloud, allow_pickle=True)
        pts = data["points"].astype(np.float64)
        objs, rest, note = find_objects(pts, near=near, far=far)
        print("=== 물체 잘라내기 (저장된 점) ===")
        print("파일: {}  점 {}개".format(args.cloud, len(pts)))
        print(note)
        print(describe(objs))
        return 0

    if not (args.live or args.save):
        print(__doc__)
        return 2

    import cv2
    from view_d405 import colorize, put_lines
    from d405_stream import open_depth

    print("=== 물체 잘라내기 ===")
    print("책상(평평한 면)을 찾아 빼고, 남은 점을 덩어리로 묶는다.")
    print("배운 것이 없으므로 **처음 보는 물체에도 된다.**")
    print("키: q 끝내기 / s 사진 저장")
    print()

    stream = open_depth(args.width, args.height, color=True)
    tracker = Tracker()
    # 창 제목은 영어로 — OpenCV 가 한글 제목을 깨뜨린다(`yolo_assist.py` 주석 참고)
    win = "D405 - segment  (left: photo / right: objects)"
    try:
        while True:
            got, intr = stream.frames(count=1, warmup=0)
            if not got:
                continue
            depth_m, color = got[0]
            pts, cols, (ys, xs) = _to_points(depth_m, intr, None)
            objs, rest, note = find_objects(pts, near=near, far=far)
            objs = tracker.update(objs)      # 같은 물체는 같은 번호 -> 색이 안 바뀐다

            # 찾은 물체를 화면에 칠한다 — 어느 점이 어느 물체인지 보이게
            paint = colorize(depth_m, near, far)
            if objs:
                # 색은 **번호**로 고른다(점 개수 순이 아니라) — 그래야 안 깜빡인다
                for oi, o in enumerate(objs[:8]):
                    px = np.round(o.points[:, 0] * intr.fx / o.points[:, 2] + intr.ppx)
                    py = np.round(o.points[:, 1] * intr.fy / o.points[:, 2] + intr.ppy)
                    ok = ((px >= 0) & (px < depth_m.shape[1])
                          & (py >= 0) & (py < depth_m.shape[0]))
                    paint[py[ok].astype(int), px[ok].astype(int)] = size_verdict(o)[0]

            view_c = cv2.resize(color, (640, 480)) if color is not None else np.zeros(
                (480, 640, 3), np.uint8)
            view_o = cv2.resize(paint, (640, 480), interpolation=cv2.INTER_NEAREST)
            view_c = put_lines(view_c, ["색 사진"])
            n_ok = sum(1 for o in objs if size_verdict(o)[1] == "잡을만")
            lines = ["찾은 덩어리 {}개 — 그중 **잡을만한 크기 {}개**".format(len(objs), n_ok),
                     "초록=잡을만(3~16cm) / 빨강=손보다 큼 / 파랑=너무 작음",
                     note]
            for i, o in enumerate(objs[:4]):
                lines.append("  {}번 [{}] {:.1f}x{:.1f}x{:.1f} cm  거리 {:.2f} m  연속 {}장면".format(
                    o.track_id, size_verdict(o)[1], *(o.size * 100),
                    o.distance_m, o.seen_frames))
            view_o = put_lines(view_o, lines)
            both = np.hstack([view_c, view_o])

            if args.save:
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "segment_{}.png".format(stamp)), both)
                np.savez_compressed(
                    RESULTS_DIR / "segment_{}.npz".format(stamp),
                    **{"obj{}".format(i): o.points for i, o in enumerate(objs)})
                print(note)
                print(describe(objs))
                print("저장: {}".format(RESULTS_DIR / "segment_{}.png".format(stamp)))
                break

            cv2.imshow(win, both)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "segment_{}.png".format(stamp)), both)
                print("사진 저장 / " + note)
                print(describe(objs))
    finally:
        stream.close()
        try:
            import cv2 as _c
            _c.destroyAllWindows()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
