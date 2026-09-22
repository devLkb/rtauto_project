# -*- coding: utf-8 -*-
"""물체 하나의 **위치와 방향**을 점 덩어리에서 잰다 (11월 시연 경로 단계 B·C).

무엇을 하는가
-------------
`yolo_assist.py`가 잘라낸 물체 하나(`ObjectCloud` — 그 물체에 속한 점들)를 받아서
두 가지를 낸다.

1. **위치** — 점들의 가운데. 다만 평균이 아니라 **중앙값 + 튀는 값 버리기**로 낸다.
   반짝이는 물체는 엉뚱한 곳에 점이 몇 개 튀는데, 평균은 그 몇 개에 통째로 끌려간다.
2. **방향** — 점들이 가장 길게 퍼진 쪽이 어디인가(세 방향). 이것으로 물체가
   **서 있는지 / 누워 있는지 / 기울어졌는지**를 가른다.

왜 따로 뺐나
------------
`yolo_assist.py`는 **카메라를 열고 화면을 그리는** 일까지 같이 한다. 이 파일은
카메라도 화면도 모른다 — **숫자만 받아 숫자만 낸다.** 그래서 카메라 없이 시험할 수
있고(`vision/d405/tests/test_object_pose.py`), 팔 쪽에서 그대로 가져다 쓸 수 있다.

좌표 기준을 스스로 지킨다
-------------------------
`ObjectPose.frame`이 그 값이 **어느 기준**인지 들고 다닌다. 카메라 기준 값을 로봇
기준인 척 쓰는 것이 이 파이프라인에서 가장 조용히 틀리는 자리라, 기준을 바꾸는 일은
`transformed()` 하나만 할 수 있게 했다.

    카메라 기준 --(arm/eye_in_hand.py)--> 로봇 밑동 기준

방향 추정의 한계 — 미리 적어 둔다
---------------------------------
🛑 **원통·공처럼 돌려도 같은 모양인 물체는 방향이 하나로 정해지지 않는다.**
페트병을 세워 두면 "긴 축은 위쪽"까지는 맞지만, 그 축을 중심으로 몇 도 돌아가 있는지는
점만 봐서는 알 수 없다(어느 각도에서 봐도 같은 모양이므로). 이럴 때 이 파일은
`orientation_valid=False`로 **모른다고 말한다** — 아는 척하지 않는다. 쓰는 쪽
(`arm/pregrasp_planner.py`)은 그때 방향을 안 쓰는 쪽으로 물러선다.

판정 기준은 `config/rtauto_config.py`의 `OBJECT_AXIS_RATIO_MIN`이다(원칙 1).

돌려 보기
---------
터미널 1 (bash, 리포 루트) — 시험만:

    source vision/.vision/bin/activate
    python -m unittest vision.d405.tests.test_object_pose -v

터미널 1 (PowerShell, 리포 루트) — 시험만:

    vision/.vision/Scripts/Activate.ps1
    python -m unittest vision.d405.tests.test_object_pose -v
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (모든 한계값의 유일한 출처 — 원칙 1)

#: 좌표 기준 이름. `contracts/grasp_prepose.py`의 `FRAME_BASE`와 같은 뜻이다.
FRAME_CAMERA = "camera"
FRAME_BASE = "base"

#: 튀는 값을 버릴 때 쓰는 기준. 가운데에서 **중앙값 절대편차(MAD)의 몇 배**까지
#: 남길 것인가. 3배는 흔히 쓰는 값이고, 정규분포라면 약 99 %가 남는다.
OUTLIER_MAD_SCALE = 3.0

#: MAD가 0이 되는 경우(점이 다 같은 자리)를 위한 최소값 [m]. 0으로 나누지 않으려는 것.
MIN_MAD_M = 1e-4

#: 방향을 계산하려면 최소한 있어야 하는 점 개수. 3점 이하로는 퍼짐을 못 잰다.
MIN_POINTS_FOR_AXES = 8


class ObjectPoseError(ValueError):
    """넣은 값이 방향·위치를 잴 수 있는 꼴이 아닐 때."""


# ---------------------------------------------------------------------------
# 1. 위치 — 튀는 값에 안 끌려가게
# ---------------------------------------------------------------------------
def _as_points(points) -> np.ndarray:
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ObjectPoseError(
            "점 덩어리는 (N, 3) 꼴이어야 한다 (받은 모양 {}).".format(pts.shape))
    return pts


def valid_points(points) -> np.ndarray:
    """**쓸 수 있는 점만** 남긴다 — 숫자가 아닌 값(NaN/Inf)과 거리 0을 버린다.

    거리값이 0인 화소는 "잼"이 아니라 **"못 쟀다"** 는 뜻이다(RealSense 규약).
    이걸 그대로 계산에 넣으면 물체가 카메라 렌즈에 붙어 있는 것처럼 나온다.
    """
    pts = _as_points(points)
    ok = np.isfinite(pts).all(axis=1) & (pts[:, 2] > 0.0)
    return pts[ok]


def robust_center(points) -> Tuple[np.ndarray, np.ndarray]:
    """가운데를 **중앙값으로** 내고, 거기서 너무 먼 점은 버린 뒤 다시 낸다.

    돌려주는 것: `(가운데 (3,), 남긴 점들 (M, 3))`.

    왜 평균이 아닌가
    ----------------
    반짝이는 물체·유리에서는 거리값이 엉뚱하게 튄 점이 몇 개씩 섞인다. 100개 중
    3개가 1 m 뒤에 찍히면 평균은 3 cm 뒤로 밀린다 — 그만큼 팔이 헛짚는다.
    중앙값은 그 3개에 끌려가지 않는다.
    """
    pts = valid_points(points)
    if len(pts) == 0:
        raise ObjectPoseError("쓸 수 있는 점이 하나도 없다(전부 NaN이거나 거리 0).")

    med = np.median(pts, axis=0)
    dist = np.linalg.norm(pts - med, axis=1)
    mad = float(np.median(dist))
    keep = dist <= max(mad, MIN_MAD_M) * OUTLIER_MAD_SCALE
    if keep.sum() < max(1, MIN_POINTS_FOR_AXES // 2):
        keep = np.ones(len(pts), dtype=bool)   # 너무 많이 버리면 그냥 다 쓴다
    kept = pts[keep]
    return np.median(kept, axis=0), kept


# ---------------------------------------------------------------------------
# 2. 방향 — 가장 길게 퍼진 쪽 찾기 (주성분 분석)
# ---------------------------------------------------------------------------
def principal_axes(points) -> Tuple[np.ndarray, np.ndarray]:
    """점들이 **어느 쪽으로 얼마나 길게 퍼졌는지** 낸다.

    돌려주는 것: `(축 3개 (3, 3) — 열이 하나의 축, 퍼진 길이 (3,) [m])`.
    긴 쪽부터 순서대로 나온다. `축[:, 0]`이 가장 긴 방향이다.

    퍼진 길이는 **그 축에 점들을 비춰 봤을 때의 양끝 거리**다(표준편차가 아니다) —
    사람이 "이 물체는 12 cm 짜리" 라고 말할 때의 그 길이와 같은 뜻이라 읽기 쉽다.

    ⚠️ 카메라는 **물체의 한쪽 면만 본다.** 뒤쪽은 점이 없으므로 "앞뒤 두께"는 늘
    실제보다 얇게 나온다. 위치·긴 축 방향에는 큰 영향이 없지만, 두께 자체를
    물체 크기로 믿으면 안 된다.
    """
    pts = _as_points(points)
    if len(pts) < MIN_POINTS_FOR_AXES:
        raise ObjectPoseError(
            "방향을 재려면 점이 최소 {}개는 있어야 한다 (받은 개수 {}).".format(
                MIN_POINTS_FOR_AXES, len(pts)))

    centered = pts - pts.mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    if not np.isfinite(cov).all():
        raise ObjectPoseError("퍼짐 계산에 숫자가 아닌 값이 나왔다.")
    # eigh는 대칭행렬 전용이고 **오름차순**으로 돌려준다 — 뒤집어서 긴 쪽부터 놓는다.
    _, vecs = np.linalg.eigh(cov)
    vecs = vecs[:, ::-1]

    projected = centered @ vecs                      # (N, 3) 각 축에 비춘 값
    extents = projected.max(axis=0) - projected.min(axis=0)
    order = np.argsort(-extents)                     # 양끝 거리 기준으로 다시 정렬
    vecs, extents = vecs[:, order], extents[order]

    # 오른손 좌표계로 맞춘다 — 뒤집힌 채로 쓰면 회전이 거울상이 된다.
    if np.linalg.det(vecs) < 0:
        vecs[:, 2] = -vecs[:, 2]
    return vecs, extents


# ---------------------------------------------------------------------------
# 3. 결과 자료구조
# ---------------------------------------------------------------------------
#: 물체가 놓인 모습. 사람이 읽는 말 그대로 쓴다(원칙 4).
STANDING = "서 있음"
LYING = "누워 있음"
TILTED = "기울어짐"
UNKNOWN_POSTURE = "모름"


@dataclass(frozen=True)
class ObjectPose:
    """물체 하나의 위치·방향. **어느 기준의 좌표인지 스스로 들고 다닌다.**"""

    #: 좌표 기준 — `FRAME_CAMERA` 또는 `FRAME_BASE`.
    frame: str
    #: 가운데 위치 (x, y, z) [m].
    position: Tuple[float, float, float]
    #: 축 3개. **열이 하나의 축**이고 긴 쪽부터다. `axes[:, 0]`이 가장 긴 방향.
    axes: np.ndarray
    #: 각 축으로 퍼진 길이 [m]. 같은 순서.
    extents: Tuple[float, float, float]
    #: 위치·방향을 내는 데 실제로 쓴 점 개수.
    n_points: int
    #: 방향을 믿어도 되는가. 원통·공처럼 돌려도 같은 모양이면 False.
    orientation_valid: bool
    #: 왜 못 믿는지 / 참고할 점 한 줄.
    note: str = ""
    #: 인식한 이름과 확신(0~1). YOLO가 준 값 그대로 — 이름이 틀려도 테두리는 맞을 수 있다.
    label: str = ""
    confidence: float = 0.0
    #: 거리값이 모자라 **테두리로 크기를 어림잡은** 물체인가(`ObjectCloud.estimated`).
    estimated: bool = False

    # -- 읽기 쉬운 파생값 ------------------------------------------------
    @property
    def long_axis(self) -> np.ndarray:
        """가장 긴 방향 (3,), 길이 1."""
        return np.asarray(self.axes, dtype=float)[:, 0]

    @property
    def max_size_m(self) -> float:
        return float(max(self.extents))

    @property
    def min_size_m(self) -> float:
        return float(min(self.extents))

    def _up(self, up: Optional[Sequence[float]]) -> np.ndarray:
        """어느 쪽이 **위쪽**인가. 안 주면 좌표 기준에서 알아낸다.

        🛑 **카메라 기준에서는 위쪽을 알 수 없다** (2026-09-22 실물 D405로 발견한
        진짜 버그). 카메라 좌표는 Z가 **앞쪽(거리)** 이고 Y가 아래쪽이다. 그런데
        로봇 밑동 기준의 위쪽인 (0, 0, 1)을 그대로 갖다 쓰면, **똑바로 서 있는 병이
        "누워 있음"으로 판정된다** — 실제로 그렇게 나왔다(기운 각도 81도).

        카메라가 얼마나 기울어져 있는지는 팔 자세 + 손목 카메라 장착값을 알아야
        나온다. 그러니 카메라 기준 물체에는 **조용히 틀린 답을 내는 대신 막는다.**
        먼저 `transformed()` 로 로봇 밑동 기준으로 옮긴 뒤에 물어야 한다.
        """
        if up is None:
            if self.frame != FRAME_BASE:
                raise ObjectPoseError(
                    "'{}' 기준 물체에는 위아래를 판정할 수 없다 — 카메라 좌표는 Z가 "
                    "앞쪽(거리)이라 로봇 기준의 위쪽과 다르다. 먼저 transformed()로 "
                    "'{}' 기준으로 옮기거나, up= 으로 위쪽을 직접 알려 줄 것.".format(
                        self.frame, FRAME_BASE))
            up = (0.0, 0.0, 1.0)
        up_v = np.asarray(up, dtype=float)
        norm = float(np.linalg.norm(up_v))
        if norm < 1e-12:
            raise ObjectPoseError("위쪽 방향의 길이가 0이다.")
        return up_v / norm

    def tilt_deg(self, up: Optional[Sequence[float]] = None) -> float:
        """가장 긴 축이 **위쪽과 이루는 각도** [도]. 0도면 곧게 서 있는 것.

        축은 방향의 앞뒤 구분이 없으므로(긴 축은 위아래 어느 쪽을 가리켜도 같은 축)
        0~90도 사이로 접어서 돌려준다. `up`을 안 주면 좌표 기준에서 알아낸다 —
        카메라 기준이면 막는다(`_up()` 설명 참고).
        """
        cos = abs(float(np.dot(self.long_axis, self._up(up))))
        return math.degrees(math.acos(min(1.0, max(0.0, cos))))

    def posture(self, up: Optional[Sequence[float]] = None) -> str:
        """서 있음 / 누워 있음 / 기울어짐 / 모름. 기준 각도는 설정에서 온다."""
        if not self.orientation_valid:
            return UNKNOWN_POSTURE
        tilt = self.tilt_deg(up)
        if tilt <= cfg.OBJECT_STANDING_MAX_TILT_DEG:
            return STANDING
        if tilt >= cfg.OBJECT_LYING_MAX_TILT_DEG:
            return LYING
        return TILTED

    # -- 기준 바꾸기 ------------------------------------------------------
    def transformed(self, transform: np.ndarray, frame: str) -> "ObjectPose":
        """4x4 변환을 먹여 **다른 좌표 기준의 같은 물체**로 바꾼다.

        위치는 옮기고 회전시키고, 축은 회전만 시킨다. 이 함수 말고는 `frame`을
        바꾸는 길이 없다 — 카메라 기준 좌표가 로봇 기준인 척 흘러다니지 않게.
        """
        mat = np.asarray(transform, dtype=float)
        if mat.shape != (4, 4):
            raise ObjectPoseError("변환은 4x4여야 한다 (받은 모양 {}).".format(mat.shape))
        rot, trans = mat[:3, :3], mat[:3, 3]
        pos = rot @ np.asarray(self.position, dtype=float) + trans
        axes = rot @ np.asarray(self.axes, dtype=float)
        return ObjectPose(
            frame=frame,
            position=tuple(float(v) for v in pos),
            axes=axes,
            extents=self.extents,
            n_points=self.n_points,
            orientation_valid=self.orientation_valid,
            note=self.note,
            label=self.label,
            confidence=self.confidence,
            estimated=self.estimated,
        )

    def describe(self, up: Optional[Sequence[float]] = None) -> str:
        """사람이 읽을 한 줄. 위아래를 판정할 수 없는 기준이면 그 자리를 비운다."""
        try:
            posture = "{} (기운 각도 {:.0f}도)".format(self.posture(up), self.tilt_deg(up))
        except ObjectPoseError:
            posture = "놓인 모습은 아직 모름(카메라 기준이라 위쪽을 알 수 없다)"
        return (
            "[{}] {} 확신 {:.0%} | 위치({}) ({:+.3f}, {:+.3f}, {:+.3f}) m | "
            "크기 {:.1f}x{:.1f}x{:.1f} cm | {} | 점 {}개{}"
        ).format(
            self.label or "이름없음",
            "테두리로 어림잡음" if self.estimated else "거리값으로 쟀음",
            self.confidence,
            self.frame,
            self.position[0], self.position[1], self.position[2],
            self.extents[0] * 100, self.extents[1] * 100, self.extents[2] * 100,
            posture,
            self.n_points,
            " | " + self.note if self.note else "",
        )


# ---------------------------------------------------------------------------
# 4. 입구 — 점 덩어리 하나 → ObjectPose
# ---------------------------------------------------------------------------
def estimate_pose(points,
                  frame: str = FRAME_CAMERA,
                  label: str = "",
                  confidence: float = 0.0,
                  estimated: bool = False,
                  axis_ratio_min: Optional[float] = None) -> ObjectPose:
    """점 덩어리 하나 → `ObjectPose`. **한 줄로 쓰는 입구.**

    `axis_ratio_min`을 안 주면 설정값(`OBJECT_AXIS_RATIO_MIN`)을 쓴다.
    """
    if frame not in (FRAME_CAMERA, FRAME_BASE):
        raise ObjectPoseError(
            "좌표 기준은 '{}' 또는 '{}'여야 한다 (받은 값 {!r}).".format(
                FRAME_CAMERA, FRAME_BASE, frame))
    ratio_min = cfg.OBJECT_AXIS_RATIO_MIN if axis_ratio_min is None else float(axis_ratio_min)

    center, kept = robust_center(points)

    notes = []
    if len(kept) < MIN_POINTS_FOR_AXES:
        # 점이 너무 적으면 방향은 포기하고 위치만 낸다 — 아는 척하지 않는다.
        return ObjectPose(
            frame=frame,
            position=tuple(float(v) for v in center),
            axes=np.eye(3),
            extents=(0.0, 0.0, 0.0),
            n_points=int(len(kept)),
            orientation_valid=False,
            note="점이 {}개뿐이라 방향을 재지 못했다(최소 {}개 필요) — 위치만 쓴다.".format(
                len(kept), MIN_POINTS_FOR_AXES),
            label=label, confidence=float(confidence), estimated=bool(estimated))

    axes, extents = principal_axes(kept)

    # 가장 긴 축과 두 번째 축의 길이가 비슷하면 "어느 쪽이 긴 쪽"이 정해지지 않는다.
    second = float(extents[1])
    ratio = float(extents[0]) / second if second > 1e-9 else float("inf")
    orientation_valid = ratio >= ratio_min
    if not orientation_valid:
        notes.append(
            "가장 긴 축({:.1f} cm)과 두 번째 축({:.1f} cm)의 길이 비가 {:.2f}로 "
            "{:.2f}에 못 미친다 — 돌려도 같은 모양이라 방향을 하나로 정할 수 없다.".format(
                extents[0] * 100, extents[1] * 100, ratio, ratio_min))
    if estimated:
        notes.append("거리값이 모자라 테두리로 어림잡은 물체라 크기를 덜 믿어야 한다.")

    return ObjectPose(
        frame=frame,
        position=tuple(float(v) for v in center),
        axes=axes,
        extents=tuple(float(v) for v in extents),
        n_points=int(len(kept)),
        orientation_valid=orientation_valid,
        note=" / ".join(notes),
        label=label, confidence=float(confidence), estimated=bool(estimated))


def from_object_cloud(obj, frame: str = FRAME_CAMERA) -> ObjectPose:
    """`yolo_assist.py`/`segment_objects.py`가 낸 `ObjectCloud` 하나 → `ObjectPose`.

    `ObjectCloud.source`는 `"YOLO:cup 89%"` 또는 `"모양"` 꼴이라, 거기서 이름과
    확신을 갈라낸다. **이름이 틀려도 테두리는 맞을 수 있으므로**(2026-09-18 실측:
    캔이 `bottle`로 불렸지만 테두리는 정확) 이름은 사람이 보는 용도로만 쓴다.
    """
    label, conf = _split_source(getattr(obj, "source", ""))
    return estimate_pose(obj.points, frame=frame, label=label, confidence=conf,
                         estimated=bool(getattr(obj, "estimated", False)))


def _split_source(source: str) -> Tuple[str, float]:
    """`"YOLO:cup 89%"` → `("cup", 0.89)`. YOLO가 아니면 확신 0으로 본다."""
    text = str(source or "")
    if not text.startswith("YOLO:"):
        return text, 0.0
    body = text[len("YOLO:"):].strip()
    name, _, pct = body.rpartition(" ")
    try:
        conf = float(pct.rstrip("%")) / 100.0
    except ValueError:
        return body, 0.0
    return name.strip() or body, conf
