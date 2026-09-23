# -*- coding: utf-8 -*-
"""**여러 물체가 보일 때 어느 것으로 갈지** 고르는 규칙 (BACKLOG A-9).

`arm/approach_object.py` 가 부른다. 카메라·팔 없이 시험할 수 있게 계산만 여기 둔다
(`arm/tests/test_target_selection.py`).

규칙 네 가지 (+ 사람이 취소한 물체는 다시 안 고른다)
----------------------------------------------------
1. **순서** — 카메라에서 가까운 것부터. 다만 **아까 고른 물체가 아직 보이면 그것을
   먼저** 둔다. 다른 물체가 `RTAUTO_TARGET_SWITCH_MARGIN_M`(기본 3 cm)보다 더 가까워야
   바꾼다. 거리가 비슷한 두 물체 사이를 장면마다 오가지 않게 하려는 것이다.
2. **거절되면 다음** — 1등이 안전 검사나 관절각 풀기에서 거절되면 2등, 3등 순서로
   시도한다. 전부 거절되면 아무것도 고르지 않고, 각각의 거절 이유를 돌려준다.
3. **같은 물체 알아보기** — `vision/d405/segment_objects.Tracker` 가 물체마다 번호를
   붙인다. 장면이 바뀌어도 같은 물체면 같은 번호다.
4. **잠깐 안 보여도 갈아타지 않기** — 아까 고른 물체가 안 보이면
   `RTAUTO_TARGET_HOLD_MISSING_FRAMES`(기본 3) 장면까지는 **아무것도 고르지 않고
   기다린다.** 2026-09-23 실물 D405 에서 확신 40 % 안팎의 컵이 한두 장면씩 인식에서
   빠졌다 돌아왔는데, 빠질 때마다 대상이 바뀌었다. 그 뒤에도 안 보이면 포기하고 새로 고른다.

🛑 팔이 움직이면 번호를 버린다 (`TargetPicker.arm_moved()`)
----------------------------------------------------------
번호는 **카메라 기준 좌표**로 붙인다. 손목 카메라는 팔과 같이 움직이므로, 팔이 10 cm
가면 가만히 있는 물체도 카메라에는 10 cm 움직인 것처럼 보인다. 그러면 엉뚱한 물체에
같은 번호가 붙을 수 있다. 로봇 밑동 기준으로 번호를 붙이면 이 문제가 없지만, 그러려면
손목 카메라 장착값(D-7)을 재야 한다. 그 전까지는 팔이 움직일 때마다 번호를 새로 매긴다
(`segment_objects.Tracker.reset()` 설명과 같은 규칙).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import rtauto_config as cfg  # noqa: E402


@dataclass(frozen=True)
class Candidate:
    """잡으러 갈 후보 하나. `pose` 는 **카메라 기준** `ObjectPose` 다."""

    pose: object
    #: 화면에 테두리를 그리려고 들고 다니는 점 덩어리(`ObjectCloud`). 없으면 None.
    cloud: object = None
    #: `Tracker` 가 붙인 번호. 번호를 안 붙였으면 -1.
    track_id: int = -1

    @property
    def distance_m(self) -> float:
        return float(self.pose.position[2])

    def name(self) -> str:
        """사람이 보는 이름 — `#3 cup 93%`."""
        tag = "#{} ".format(self.track_id) if self.track_id > 0 else ""
        return "{}{} {:.0%}".format(tag, self.pose.label or "이름없음",
                                   float(self.pose.confidence))


@dataclass(frozen=True)
class Attempt:
    """후보 하나를 시도한 결과."""

    candidate: Candidate
    ok: bool
    #: 거절됐으면 그 이유. 받아들였으면 빈 문자열.
    reason: str = ""


@dataclass(frozen=True)
class Selection:
    """고른 결과. `chosen` 이 None 이면 아무것도 못 골랐다."""

    chosen: Optional[Candidate]
    #: 왜 이 물체인가(또는 왜 아무것도 못 골랐나) — 사람이 읽는 한 줄.
    why: str
    #: 시도한 순서대로. 골랐으면 마지막 것이 `chosen` 이다.
    attempts: Tuple[Attempt, ...] = ()
    #: 시도하지 않은 나머지 후보(고른 뒤 남은 것).
    untried: Tuple[Candidate, ...] = ()

    @property
    def rejected(self) -> Tuple[Attempt, ...]:
        return tuple(a for a in self.attempts if not a.ok)

    @property
    def others(self) -> Tuple[Candidate, ...]:
        """고른 것을 뺀 나머지 전부 — 화면에 "같이 보인 것" 으로 띄운다."""
        return tuple(a.candidate for a in self.rejected) + self.untried


def rank(candidates: Sequence[Candidate],
         previous_track_id: Optional[int] = None,
         switch_margin_m: Optional[float] = None) -> Tuple[Tuple[Candidate, ...], str]:
    """후보를 **시도할 순서**로 늘어놓고, 1등이 왜 1등인지 한 줄을 돌려준다."""
    margin = cfg.TARGET_SWITCH_MARGIN_M if switch_margin_m is None else float(switch_margin_m)
    ordered = sorted(candidates, key=lambda c: c.distance_m)
    if not ordered:
        return (), "후보 없음"

    nearest = ordered[0]
    prev = None
    if previous_track_id is not None and previous_track_id > 0:
        prev = next((c for c in ordered if c.track_id == previous_track_id), None)

    if prev is None:
        why = "카메라에서 가장 가깝다({:.3f} m)".format(nearest.distance_m)
        if previous_track_id is not None and previous_track_id > 0:
            why = "아까 고른 #{} 이 이번엔 안 보여서, {}".format(previous_track_id, why)
        return tuple(ordered), why

    if prev is nearest:
        return tuple(ordered), "아까 고른 물체이고 지금도 가장 가깝다({:.3f} m)".format(
            prev.distance_m)

    gain = prev.distance_m - nearest.distance_m
    if gain > margin:
        return tuple(ordered), (
            "{} 이 아까 고른 #{} 보다 {:.1f} cm 더 가까워서 바꿨다(바꾸는 기준 {:.1f} cm)".format(
                nearest.name(), prev.track_id, gain * 100, margin * 100))
    rest = [c for c in ordered if c is not prev]
    return (prev, *rest), (
        "아까 고른 물체를 계속 따라간다 — {} 이 {:.1f} cm 더 가깝지만 바꾸는 기준"
        "({:.1f} cm)보다 작다".format(nearest.name(), gain * 100, margin * 100))


def choose(ordered: Sequence[Candidate], rank_why: str,
           evaluate: Optional[Callable[[Candidate], Tuple[bool, str]]] = None) -> Selection:
    """순서대로 `evaluate` 에 넣어 보고, **처음으로 통과한 것**을 고른다.

    `evaluate` 가 None 이면 검사 없이 1등을 고른다 — 팔에 연결하지 않아 "갈 수 있는지"
    를 확인할 방법이 없을 때(`--look`)다.
    """
    ordered = tuple(ordered)
    if not ordered:
        return Selection(None, "잡으러 갈 후보를 못 찾았다")
    if evaluate is None:
        return Selection(ordered[0], rank_why + " (팔에 연결 안 해 닿는지는 확인 안 함)",
                         (Attempt(ordered[0], True),), ordered[1:])

    attempts = []
    for i, cand in enumerate(ordered):
        ok, reason = evaluate(cand)
        attempts.append(Attempt(cand, bool(ok), "" if ok else str(reason)))
        if ok:
            if i == 0:
                why = rank_why
            else:
                why = "앞의 {}개가 거절돼서 {}번째 후보로 넘어왔다({:.3f} m)".format(
                    i, i + 1, cand.distance_m)
            return Selection(cand, why, tuple(attempts), ordered[i + 1:])
    return Selection(None, "후보 {}개가 전부 거절됐다".format(len(ordered)), tuple(attempts))


class TargetPicker:
    """`--watch` 로 반복하는 동안 **아까 고른 물체**와 번호를 기억한다.

    `tracker` 는 `segment_objects.Tracker` 처럼 `update(clouds)`·`reset()` 을 가진 것.
    None 이면 번호를 안 붙인다(그러면 "아까 그 물체" 도 못 알아본다).
    """

    def __init__(self, tracker=None, switch_margin_m: Optional[float] = None,
                 hold_missing_frames: Optional[int] = None):
        self.tracker = tracker
        self.switch_margin_m = switch_margin_m
        self.hold_missing_frames = (cfg.TARGET_HOLD_MISSING_FRAMES if hold_missing_frames is None
                                    else int(hold_missing_frames))
        self.last_track_id: Optional[int] = None
        self._missing = 0
        #: 사람이 "여기로 보내지 마" 라고 취소한 물체 번호. 팔이 움직이면 비운다.
        self._refused = set()

    def track(self, clouds: Sequence[object]) -> None:
        """이번 장면의 점 덩어리들에 번호를 붙인다(`cloud.track_id` 가 채워진다).

        아무것도 안 보인 장면에도 부른다 — 그래야 `Tracker` 가 "안 보인 장면 수" 를 센다.
        """
        if self.tracker is not None:
            self.tracker.update(list(clouds))

    def refuse(self, track_id: int) -> None:
        """사람이 이 물체로 가는 것을 취소했다 — 팔이 움직이기 전까지 다시 고르지 않는다."""
        if track_id is not None and track_id > 0:
            self._refused.add(int(track_id))
            if self.last_track_id == track_id:
                self.last_track_id = None
                self._missing = 0

    def pick(self, candidates: Sequence[Candidate],
             evaluate: Optional[Callable[[Candidate], Tuple[bool, str]]] = None) -> Selection:
        if self._refused:
            inner = evaluate

            def evaluate(c: Candidate) -> Tuple[bool, str]:
                if c.track_id in self._refused:
                    return False, "사람이 이 물체로 가는 것을 취소했다"
                return inner(c) if inner is not None else (True, "")
        prev = self.last_track_id
        if prev is not None and not any(c.track_id == prev for c in candidates):
            # 아까 고른 물체가 안 보인다. 인식이 한 장면 깜빡인 것일 수 있으므로 바로
            # 갈아타지 않는다 — 무인 반복이면 깜빡임 한 번에 팔이 다른 물체로 가 버린다.
            self._missing += 1
            if self._missing <= self.hold_missing_frames:
                return Selection(None, (
                    "아까 고른 #{} 이 이번 장면에 안 보인다({}/{}) — 잠깐 가려졌을 수 있어 "
                    "다른 물체로 바꾸지 않고 기다린다").format(
                        prev, self._missing, self.hold_missing_frames),
                    untried=tuple(sorted(candidates, key=lambda c: c.distance_m)))
            self.last_track_id = None       # 충분히 기다렸다 — 포기하고 새로 고른다
        self._missing = 0
        ordered, why = rank(candidates, prev, self.switch_margin_m)
        sel = choose(ordered, why, evaluate)
        if sel.chosen is not None and sel.chosen.track_id > 0:
            self.last_track_id = sel.chosen.track_id
        return sel

    def arm_moved(self) -> None:
        """팔이 움직였다 — 카메라 기준 번호가 더는 이어지지 않는다(파일 머리 설명)."""
        if self.tracker is not None:
            self.tracker.reset()
        self.last_track_id = None
        self._missing = 0
        self._refused.clear()     # 번호가 새로 매겨지므로 옛 번호로 막아 둔 것도 뜻을 잃는다
