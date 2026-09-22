# -*- coding: utf-8 -*-
"""파지 직전 자세 — 주고받는 값의 정본.

무엇인가
--------
3D 카메라가 본 것을 가지고 "손을 어디에, 어떤 방향으로, 손가락을 어떤 모양으로 두고
멈출 것인가"를 정한 결과다. 이 값을 만드는 쪽(자세를 정하는 부품)과 쓰는 쪽(관절 각도를
계산해 팔을 움직이는 부품)이 **같은 자료구조를 주고받는다.**

왜 하나로 못 박는가
-------------------
자세를 정하는 방법이 두 가지이기 때문이다.

  1. 계산 방식  — 보이는 점 덩어리의 크기·방향을 재서 규칙대로 계산한다.
  2. 학습한 예측기 — 가상 세계에서 수없이 잡아 본 결과로 배운다.

둘을 **같은 자리에 꽂았다 뺐다** 하려면 주고받는 값이 같아야 한다. 그래서 이 파일이
있고, 두 방식 중 무엇이 만들었는지는 `source` 한 칸으로 구분한다.

설계 문서: `docs/FESTA_PREGRASP_PLAN.md` §6.
관찰·행동 계약의 상위 정본: `docs/RL_POLICY_REDESIGN.md` §4-1·§4-2.

정본이 어디에 있는가 (원칙 1)
-----------------------------
- **손 관절 이름과 그 순서** → 팔+손 결합 URDF. 이 파일이 읽는다. 관절 이름 목록을
  여기에 베껴 적지 않는다.
- **URDF 경로** → `config/rtauto_config.py`의 `ARM_HAND_URDF`.

단위와 기준 (섞이면 조용히 틀린다)
----------------------------------
- 길이: **m**.  각도: **rad**.  시각: **초**(`time.time()` 기준).
- 좌표 기준: **로봇 베이스**(`FRAME_BASE`). 카메라 기준 좌표를 그대로 싣지 않는다.
- 회전: 쿼터니언 **(w, x, y, z)** 순서, 길이 1.

"거절"은 곁다리가 아니다
------------------------
자세를 정할 수 없으면 **정식 결과로 거절을 내보낸다.** 거절일 때는 자세 칸이 전부
비어 있다 — 실수로 쓰이는 것을 막기 위해서다. "모르면 멈춘다"는 이 시스템의 합격
기준 중 하나다.
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import rtauto_config as cfg  # noqa: E402


SCHEMA_VERSION = 1

#: 좌표 기준 이름. 로봇 베이스 고정 — 베이스가 멈춘 상태에서만 매니퓰레이션한다는
#: 프로젝트 동작 원칙(CLAUDE.md "순차 동작")에 맞춘 것이다.
FRAME_BASE = "base"

#: DG-5F-M 오른손의 관절 개수. URDF에서 읽은 값과 다르면 `hand_joint_names()`가 막는다.
HAND_JOINT_COUNT = 20

#: URDF에서 손 관절을 고르는 이름 접두사. 값 자체가 아니라 **URDF의 작명 사실**이다 —
#: 팔은 `shoulder_*`/`elbow_*`/`wrist_*`, 손은 `rj_dg_*`.
HAND_JOINT_PREFIX = "rj_dg_"

#: 단위 벡터·쿼터니언 길이를 확인할 때 허용하는 오차.
UNIT_TOLERANCE = 1e-6

_JOINT_RE = re.compile(r'<joint\s[^>]*name="([^"]+)"[^>]*type="([^"]+)"', re.S)
_MOVABLE_TYPES = ("revolute", "continuous", "prismatic")

_hand_joint_names_cache: dict = {}


class GraspPrePoseError(ValueError):
    """주고받는 값이 계약을 어겼을 때 나는 오류."""


class Source(str, Enum):
    """이 자세를 누가 만들었는가. 두 방식을 비교하려면 반드시 필요하다."""

    GEOMETRIC = "geometric"  # 보이는 모양을 재서 규칙대로 계산
    LEARNED = "learned"      # 가상 세계에서 잡아 본 결과로 배운 예측기


class Decision(str, Enum):
    """결과. 거절이면 자세 칸은 전부 비어 있어야 한다."""

    ACCEPT = "accept"
    #: 물체를 못 찾음
    REJECT_NO_TARGET = "reject_no_target"
    #: 손 벌림 폭·크기 등 검증된 작업 범위 밖
    REJECT_OUT_OF_RANGE = "reject_out_of_range"
    #: 깊이(거리) 값이 너무 비거나 튐 — 투명·반짝이는 물체에서 잘 난다
    REJECT_LOW_DEPTH = "reject_low_depth"
    #: 팔이 그 자세까지 닿지 못함
    REJECT_UNREACHABLE = "reject_unreachable"
    #: 자세는 냈지만 확신이 모자람
    REJECT_LOW_CONFIDENCE = "reject_low_confidence"


def _urdf_path(urdf_path: Optional[str] = None) -> Path:
    return Path(urdf_path or cfg.ARM_HAND_URDF)


def hand_joint_names(urdf_path: Optional[str] = None) -> Tuple[str, ...]:
    """손 관절 20개의 이름을 **URDF 순서 그대로** 돌려준다.

    이 순서가 곧 `hand_joint_target`/`hand_joint_valid` 배열의 순서다.
    목록을 코드에 베껴 적지 않는 이유는 URDF가 바뀌면 조용히 어긋나기 때문이다.
    """
    path = _urdf_path(urdf_path)
    key = str(path)
    cached = _hand_joint_names_cache.get(key)
    if cached is not None:
        return cached

    if not path.is_file():
        raise GraspPrePoseError(
            "팔+손 결합 URDF를 찾지 못했다: {}\n"
            "config/rtauto_config.py의 ARM_HAND_URDF(또는 .env의 "
            "RTAUTO_ARM_HAND_URDF)를 확인하라.".format(path)
        )

    text = path.read_text(encoding="utf-8")
    names = [
        name
        for name, jtype in _JOINT_RE.findall(text)
        if jtype in _MOVABLE_TYPES and name.startswith(HAND_JOINT_PREFIX)
    ]
    if len(names) != HAND_JOINT_COUNT:
        raise GraspPrePoseError(
            "URDF에서 찾은 손 관절이 {}개다 — {}개여야 한다.\n"
            "  URDF: {}\n"
            "  고른 기준: 이름이 '{}'로 시작하는 움직이는 관절\n"
            "  찾은 것: {}".format(
                len(names), HAND_JOINT_COUNT, path, HAND_JOINT_PREFIX, names
            )
        )
    result = tuple(names)
    _hand_joint_names_cache[key] = result
    return result


def _norm(vec: Sequence[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in vec))


@dataclass(frozen=True)
class GraspPrePose:
    """파지 직전 자세 하나. `accept()` 또는 `reject()`로 만든다."""

    # --- 언제·어디 기준 -------------------------------------------------
    #: 관측 화면을 찍은 시각(초). 팔 자세를 되짚을 때 이 시각의 관절값을 쓴다.
    stamp_capture: float
    #: 이 결과를 내보낸 시각(초).
    stamp_emit: float
    #: 좌표 기준. 지금은 로봇 베이스 하나뿐이다.
    frame: str = FRAME_BASE

    # --- 누가 만들었나 ---------------------------------------------------
    source: Source = Source.GEOMETRIC

    # --- 판정 -------------------------------------------------------------
    decision: Decision = Decision.ACCEPT
    #: 0~1. 높을수록 확신이 크다.
    confidence: float = 0.0
    #: 거절이면 왜 거절했는지 사람이 읽을 한 줄. 거절일 때는 비워 두면 안 된다.
    reason: str = ""

    # --- 손바닥 자세 (거절이면 전부 None) ---------------------------------
    #: 손바닥 중심 위치 (x, y, z) m.
    palm_position: Optional[Tuple[float, float, float]] = None
    #: 손바닥 방향 (w, x, y, z), 길이 1.
    palm_orientation: Optional[Tuple[float, float, float, float]] = None
    #: 마지막 구간에서 다가갈 방향 (x, y, z), 길이 1.
    approach_dir: Optional[Tuple[float, float, float]] = None
    #: 접근을 시작할 지점에서 손바닥까지 남은 거리 m. 0 이상.
    standoff: Optional[float] = None

    # --- 손 모양 (거절이면 빈 배열) ---------------------------------------
    #: 관절 이름. URDF 순서 그대로.
    hand_joint_names: Tuple[str, ...] = ()
    #: 관절 목표각 rad. `hand_joint_names`와 같은 길이·같은 순서.
    hand_joint_target: Tuple[float, ...] = ()
    #: 그 관절 값을 믿어도 되는지. 같은 길이.
    hand_joint_valid: Tuple[bool, ...] = ()

    # --- 참고값 -----------------------------------------------------------
    #: 손이 얼마나 벌어져 있는지 m. **사람이 읽기 위한 값이고 제어에 쓰지 않는다** —
    #: 쓰면 손 모양의 정본이 둘이 된다.
    opening_width: Optional[float] = None

    schema_version: int = field(default=SCHEMA_VERSION)

    # ------------------------------------------------------------------
    # 만들기
    # ------------------------------------------------------------------
    @classmethod
    def accept(
        cls,
        stamp_capture: float,
        stamp_emit: float,
        source: Source,
        palm_position: Sequence[float],
        palm_orientation: Sequence[float],
        approach_dir: Sequence[float],
        standoff: float,
        hand_joint_target: Sequence[float],
        hand_joint_valid: Optional[Sequence[bool]] = None,
        confidence: float = 1.0,
        opening_width: Optional[float] = None,
        joint_names: Optional[Sequence[str]] = None,
        frame: str = FRAME_BASE,
        urdf_path: Optional[str] = None,
    ) -> "GraspPrePose":
        """자세를 정했을 때. 관절 이름을 안 주면 URDF에서 읽어 채운다."""
        names = tuple(joint_names) if joint_names is not None else hand_joint_names(urdf_path)
        valid = (
            tuple(bool(v) for v in hand_joint_valid)
            if hand_joint_valid is not None
            else tuple(True for _ in names)
        )
        obj = cls(
            stamp_capture=float(stamp_capture),
            stamp_emit=float(stamp_emit),
            frame=frame,
            source=Source(source),
            decision=Decision.ACCEPT,
            confidence=float(confidence),
            reason="",
            palm_position=tuple(float(v) for v in palm_position),  # type: ignore[arg-type]
            palm_orientation=tuple(float(v) for v in palm_orientation),  # type: ignore[arg-type]
            approach_dir=tuple(float(v) for v in approach_dir),  # type: ignore[arg-type]
            standoff=float(standoff),
            hand_joint_names=names,
            hand_joint_target=tuple(float(v) for v in hand_joint_target),
            hand_joint_valid=valid,
            opening_width=None if opening_width is None else float(opening_width),
        )
        obj.validate()
        return obj

    @classmethod
    def reject(
        cls,
        stamp_capture: float,
        stamp_emit: float,
        source: Source,
        decision: Decision,
        reason: str,
        confidence: float = 0.0,
        frame: str = FRAME_BASE,
    ) -> "GraspPrePose":
        """자세를 정할 수 없을 때. 자세 칸은 비운 채로 나간다."""
        obj = cls(
            stamp_capture=float(stamp_capture),
            stamp_emit=float(stamp_emit),
            frame=frame,
            source=Source(source),
            decision=Decision(decision),
            confidence=float(confidence),
            reason=reason,
        )
        obj.validate()
        return obj

    # ------------------------------------------------------------------
    # 검사
    # ------------------------------------------------------------------
    @property
    def accepted(self) -> bool:
        return self.decision is Decision.ACCEPT

    def validate(self, urdf_path: Optional[str] = None) -> "GraspPrePose":
        """계약을 어겼으면 `GraspPrePoseError`. 통과하면 자기 자신을 돌려준다."""
        if self.schema_version != SCHEMA_VERSION:
            raise GraspPrePoseError(
                "schema_version이 {}다 — 이 코드는 {}만 읽는다.".format(
                    self.schema_version, SCHEMA_VERSION
                )
            )
        if self.frame != FRAME_BASE:
            raise GraspPrePoseError(
                "frame은 '{}'여야 한다 (받은 값 {!r}). 카메라 기준 좌표를 그대로 "
                "실어 보내면 안 된다.".format(FRAME_BASE, self.frame)
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise GraspPrePoseError(
                "confidence는 0~1이어야 한다 (받은 값 {}).".format(self.confidence)
            )
        # ⚠️ NaN/Inf 는 비교식(<, >)을 전부 통과시킨다 — `NaN < x`와 `x < NaN`이 둘 다
        # False라서, 아래 순서 비교(stamp_emit < stamp_capture)만으로는 NaN이 섞인
        # 시각을 못 걸러낸다(2026-09-21 코드 리뷰로 발견). 나이 계산(실제 이동 직전
        # 거부, arm/prepose_to_joints.py의 MAX_POSE_AGE_SEC)이 이 값을 그대로 빼서
        # 쓰므로, 여기서 먼저 유한한 숫자인지 확인한다.
        if not math.isfinite(self.stamp_capture):
            raise GraspPrePoseError(
                "stamp_capture가 숫자가 아니다(NaN/Inf 등, 받은 값 {}).".format(
                    self.stamp_capture
                )
            )
        if not math.isfinite(self.stamp_emit):
            raise GraspPrePoseError(
                "stamp_emit이 숫자가 아니다(NaN/Inf 등, 받은 값 {}).".format(
                    self.stamp_emit
                )
            )
        if self.stamp_emit < self.stamp_capture:
            raise GraspPrePoseError(
                "내보낸 시각이 찍은 시각보다 빠르다 "
                "(찍은 {}, 내보낸 {}).".format(self.stamp_capture, self.stamp_emit)
            )

        if not self.accepted:
            self._validate_rejected()
            return self

        self._validate_accepted(urdf_path)
        return self

    def _validate_rejected(self) -> None:
        if not self.reason.strip():
            raise GraspPrePoseError(
                "거절({})인데 reason이 비어 있다. 왜 거절했는지 한 줄은 적어야 "
                "이어받는 사람이 고칠 수 있다.".format(self.decision.value)
            )
        leftovers = [
            name
            for name, value in (
                ("palm_position", self.palm_position),
                ("palm_orientation", self.palm_orientation),
                ("approach_dir", self.approach_dir),
                ("standoff", self.standoff),
                ("opening_width", self.opening_width),
            )
            if value is not None
        ]
        leftovers += [
            name
            for name, seq in (
                ("hand_joint_names", self.hand_joint_names),
                ("hand_joint_target", self.hand_joint_target),
                ("hand_joint_valid", self.hand_joint_valid),
            )
            if len(seq) > 0
        ]
        if leftovers:
            raise GraspPrePoseError(
                "거절인데 자세 값이 남아 있다: {}. 거절은 자세 칸을 전부 비워야 "
                "실수로 쓰이지 않는다.".format(", ".join(leftovers))
            )

    def _validate_accepted(self, urdf_path: Optional[str]) -> None:
        for name, value, length in (
            ("palm_position", self.palm_position, 3),
            ("palm_orientation", self.palm_orientation, 4),
            ("approach_dir", self.approach_dir, 3),
        ):
            if value is None:
                raise GraspPrePoseError("받아들임인데 {}가 비어 있다.".format(name))
            if len(value) != length:
                raise GraspPrePoseError(
                    "{}는 숫자 {}개여야 한다 (받은 개수 {}).".format(
                        name, length, len(value)
                    )
                )
            if any(not math.isfinite(v) for v in value):
                raise GraspPrePoseError("{}에 숫자가 아닌 값이 있다.".format(name))

        for name, value in (
            ("palm_orientation", self.palm_orientation),
            ("approach_dir", self.approach_dir),
        ):
            norm = _norm(value)  # type: ignore[arg-type]
            if abs(norm - 1.0) > UNIT_TOLERANCE:
                raise GraspPrePoseError(
                    "{}의 길이가 1이 아니다 (길이 {:.9f}). 회전과 방향은 길이 1로 "
                    "맞춰서 넣는다.".format(name, norm)
                )

        if self.standoff is None or not math.isfinite(self.standoff) or self.standoff < 0.0:
            raise GraspPrePoseError(
                "standoff는 0 이상의 거리(m)여야 한다 (받은 값 {}).".format(self.standoff)
            )

        expected = hand_joint_names(urdf_path)
        if tuple(self.hand_joint_names) != expected:
            raise GraspPrePoseError(
                "손 관절 이름·순서가 URDF와 다르다.\n"
                "  URDF: {}\n"
                "  받은 값: {}".format(list(expected), list(self.hand_joint_names))
            )
        for name, seq in (
            ("hand_joint_target", self.hand_joint_target),
            ("hand_joint_valid", self.hand_joint_valid),
        ):
            if len(seq) != len(expected):
                raise GraspPrePoseError(
                    "{}의 개수가 {}다 — 관절 이름과 같은 {}개여야 한다.".format(
                        name, len(seq), len(expected)
                    )
                )
        if any(not math.isfinite(v) for v in self.hand_joint_target):
            raise GraspPrePoseError("hand_joint_target에 숫자가 아닌 값이 있다.")
        if not any(self.hand_joint_valid):
            raise GraspPrePoseError(
                "받아들임인데 믿을 수 있는 관절이 하나도 없다(hand_joint_valid가 전부 "
                "거짓). 이럴 거면 거절로 내보내야 한다."
            )
        if self.opening_width is not None and (
            not math.isfinite(self.opening_width) or self.opening_width < 0.0
        ):
            raise GraspPrePoseError(
                "opening_width는 0 이상의 거리(m)여야 한다 "
                "(받은 값 {}).".format(self.opening_width)
            )

    # ------------------------------------------------------------------
    # 파일로 주고받기
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "stamp_capture": self.stamp_capture,
            "stamp_emit": self.stamp_emit,
            "frame": self.frame,
            "source": self.source.value,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "palm_position": list(self.palm_position) if self.palm_position else None,
            "palm_orientation": (
                list(self.palm_orientation) if self.palm_orientation else None
            ),
            "approach_dir": list(self.approach_dir) if self.approach_dir else None,
            "standoff": self.standoff,
            "hand_joint_names": list(self.hand_joint_names),
            "hand_joint_target": list(self.hand_joint_target),
            "hand_joint_valid": [bool(v) for v in self.hand_joint_valid],
            "opening_width": self.opening_width,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraspPrePose":
        def _tup(key):
            value = data.get(key)
            return None if value is None else tuple(float(v) for v in value)

        obj = cls(
            stamp_capture=float(data["stamp_capture"]),
            stamp_emit=float(data["stamp_emit"]),
            frame=data.get("frame", FRAME_BASE),
            source=Source(data["source"]),
            decision=Decision(data["decision"]),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", ""),
            palm_position=_tup("palm_position"),
            palm_orientation=_tup("palm_orientation"),
            approach_dir=_tup("approach_dir"),
            standoff=(
                None if data.get("standoff") is None else float(data["standoff"])
            ),
            hand_joint_names=tuple(data.get("hand_joint_names", ())),
            hand_joint_target=tuple(
                float(v) for v in data.get("hand_joint_target", ())
            ),
            hand_joint_valid=tuple(bool(v) for v in data.get("hand_joint_valid", ())),
            opening_width=(
                None
                if data.get("opening_width") is None
                else float(data["opening_width"])
            ),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )
        obj.validate()
        return obj

    def to_json(self, **kwargs) -> str:
        kwargs.setdefault("ensure_ascii", False)
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> "GraspPrePose":
        return cls.from_dict(json.loads(text))
