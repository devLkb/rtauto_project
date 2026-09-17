# -*- coding: utf-8 -*-
"""잡기 한 판의 순서도 — 닫고 → 닿았는지 보고 → 멈추고 → 들고 → 잡혔는지 확인.

무엇을 하는가
-------------
파지 직전 자세까지 가는 것은 `arm/prepose_to_joints.py` 가 한다. 이 파일은 **그 다음**,
실제로 손을 오므려 물체를 쥐고 잡혔는지 확인하는 부분이다.

::

    준비      손을 벌린 채 시작 자세로. 전류가 가라앉을 때까지 기다린다
      ↓
    닫는 중    관절 목표를 조금씩 오므린다. 닿은 관절은 **그 자리에 세워 둔다**
      ↓        (계속 밀면 물체가 찌그러지거나 밀려난다)
    쥐고 있음  손가락 N개가 닿으면 더 안 조인다
      ↓
    드는 중    팔을 천천히 조금 올린다
      ↓
    확인 중    손가락이 더 닫혔나 / 전류가 떨어졌나 / (있으면) 팔 힘센서·카메라
      ↓
    성공 또는 실패(→ 놓고 다시)

왜 "닿은 관절을 세워 두는가"
-----------------------------
위치로 명령하는 손이라, 닿은 뒤에도 목표를 계속 오므리면 제어기는 **차이를 메우려고
전류를 계속 올린다.** 종이컵 같은 것은 찌그러지고, 단단한 것은 손 밖으로 밀려난다.
그래서 닿았다고 판단한 관절은 목표를 **지금 각도 + 아주 조금**으로 바꿔 고정한다.

⚠️ 실물에서 아직 한 번도 안 돌려 봤다
--------------------------------------
2026-09-17 현재 **이 순서도는 실물 검증 0회**다. 기준값들도 전부 실측 전 잠정값이라
`config/dg5f_current_baseline.json`(→ `hand/measure_baseline.py`)이 없으면 시작 자체를
거부한다. 판단 규칙만 `hand/tests/test_grasp_contact.py` 로 시험해 뒀다.

손을 누가 쥐고 있나 — 먼저 정해야 하는 것
------------------------------------------
🛑 이 그리퍼는 **TCP 연결을 딱 하나만 받는다**(2026-08-31 실물 실측: 개발자모드 자체
프로토콜과 사용자모드 Modbus TCP **둘 다** 안 됐다 —
`vision/dg5f/dg5f_modbus_readback.py` 머리말). 로봇 티치펜던트의 URCap 이 손을 잡고
있으면 PC 는 전류를 못 읽는다. 그러니 **PC 가 손의 유일한 주인**이어야 한다:

- 손: PC ← DGSDK(개발자모드) → 그리퍼          ← 전류·각도·속도를 여기서 읽는다
- 팔: PC ← ur_rtde → UR16e 컨트롤박스           ← 팔만 담당

설계 정본: [`docs/GRASP_CONTACT_DETECTION.md`](../docs/GRASP_CONTACT_DETECTION.md)
"""
from __future__ import annotations

import enum
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "hand"))

import rtauto_config as cfg  # noqa: E402

from grasp_contact import (  # noqa: E402
    N_JOINTS, ContactDetector, ContactState, CurrentBaseline, JointReading, describe,
)


class Phase(enum.Enum):
    """지금 어느 단계인가."""
    READY = "준비"
    CLOSING = "닫는 중"
    HOLDING = "쥐고 있음"
    LIFTING = "드는 중"
    VERIFYING = "확인 중"
    SUCCESS = "성공"
    FAILED_NO_CONTACT = "실패 — 아무것도 안 잡혔다"
    FAILED_SLIPPED = "실패 — 들다가 놓쳤다"
    ABORTED = "중단"


@dataclass
class HandFrame:
    """손에서 한 번에 들어오는 상태 한 묶음."""
    angle_deg: np.ndarray       # (20,) 실제 각도
    current_ma: np.ndarray      # (20,) 모터 전류
    velocity_rpm: np.ndarray    # (20,) 관절 속도
    temperature_c: np.ndarray   # (20,) 온도
    error_code: int = 0
    stamp: float = 0.0


@dataclass
class GraspReport:
    """한 판의 결과. 왜 그렇게 끝났는지까지 남긴다."""
    phase: Phase
    reason: str = ""
    fingers_touching: int = 0
    close_seconds: float = 0.0
    hold_angle_deg: Optional[np.ndarray] = None
    lift_angle_deg: Optional[np.ndarray] = None
    closed_further_deg: float = float("nan")
    current_ratio: float = float("nan")
    ft_delta_n: float = float("nan")
    log: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.phase is Phase.SUCCESS


class GraspSequence:
    """잡기 한 판을 처음부터 끝까지 돌린다.

    손과 팔은 **바깥에서 넣어 준다** — 이 파일이 통신을 직접 하지 않으므로 가짜 손·가짜
    팔로도 돌려 볼 수 있다(시험에서 그렇게 쓴다).

    `hand` 에 필요한 것:
        ``read() -> HandFrame``           지금 상태
        ``servo(target_deg20)``           관절 목표 20개를 보낸다
    `arm` 에 필요한 것 (없어도 된다 — 없으면 들기·힘 확인을 건너뛴다):
        ``lift(height_m, speed_mps)``     TCP 를 위로 그만큼 올린다
        ``tcp_force() -> float``          지금 TCP 에 걸린 힘의 크기(N). 없으면 None
    """

    def __init__(self, hand, arm=None, baseline=None, detector=None, clock=time.monotonic):
        self.hand = hand
        self.arm = arm
        self.baseline = baseline if baseline is not None else CurrentBaseline.load()
        self.detector = detector or ContactDetector(self.baseline)
        self.clock = clock
        self.phase = Phase.READY
        self._log: List[str] = []
        self._close_dir = np.ones(N_JOINTS)
        self._last_target = np.zeros(N_JOINTS)

    # --- 기록 -----------------------------------------------------------
    def _say(self, text: str) -> None:
        self._log.append(text)

    # --- 안전 확인 -------------------------------------------------------
    def _check_frame(self, frame: HandFrame, last_stamp: float) -> Optional[str]:
        """이 상태값을 믿고 계속 가도 되는가. 문제가 있으면 이유를 돌려준다."""
        if frame.error_code:
            return "손이 오류를 보고했다 (코드 {})".format(frame.error_code)
        hot = np.flatnonzero(np.asarray(frame.temperature_c) >= cfg.DG5F_TEMP_LIMIT_C)
        if len(hot):
            return "관절 {}번이 {:.0f}도를 넘었다".format(
                hot.tolist(), cfg.DG5F_TEMP_LIMIT_C)
        over = np.flatnonzero(np.abs(np.asarray(frame.current_ma)) >= cfg.DG5F_CURRENT_LIMIT_MA)
        if len(over):
            return "관절 {}번의 전류가 한계({:.0f} mA)를 넘었다".format(
                over.tolist(), cfg.DG5F_CURRENT_LIMIT_MA)
        if frame.stamp and last_stamp and (frame.stamp - last_stamp) > cfg.DG5F_FRAME_TIMEOUT_S:
            return "{:.2f}초 동안 새 상태값이 안 왔다 — 통신이 끊긴 것으로 본다".format(
                frame.stamp - last_stamp)
        return None

    # --- 닫기 -----------------------------------------------------------
    def close_until_contact(self, start_deg, goal_deg, step_deg=1.0, hold_bias_deg=0.5):
        """`start_deg` 에서 `goal_deg` 쪽으로 조금씩 오므리며 닿는 관절을 찾는다.

        닿았다고 본 관절은 **그 자리(+아주 조금)** 로 목표를 바꿔 더 밀지 않는다.
        """
        start = np.asarray(start_deg, dtype=float).reshape(N_JOINTS)
        goal = np.asarray(goal_deg, dtype=float).reshape(N_JOINTS)
        target = start.copy()
        frozen = np.zeros(N_JOINTS, dtype=bool)
        self.detector.reset()
        # 확인 단계(집어보기)가 "어느 쪽이 조이는 방향인지" 를 알아야 한다
        self._close_dir = np.sign(goal - start)
        self._last_target = target.copy()

        t0 = self.clock()
        last_stamp = 0.0
        state: Optional[ContactState] = None
        self.phase = Phase.CLOSING

        while True:
            frame = self.hand.read()
            bad = self._check_frame(frame, last_stamp)
            if bad:
                self.phase = Phase.ABORTED
                self._say("중단: " + bad)
                return state, bad
            last_stamp = frame.stamp

            readings = [JointReading(angle_deg=float(frame.angle_deg[j]),
                                     target_deg=float(target[j]),
                                     current_ma=float(frame.current_ma[j]),
                                     velocity_rpm=float(frame.velocity_rpm[j]))
                        for j in range(N_JOINTS)]
            state = self.detector.update(readings)

            # 닿은 관절은 지금 각도에서 아주 조금만 더 간 자리에 세운다.
            for j, v in enumerate(state.per_joint):
                if v.contact and not frozen[j]:
                    direction = np.sign(goal[j] - start[j]) or 1.0
                    target[j] = float(frame.angle_deg[j]) + direction * hold_bias_deg
                    frozen[j] = True
                    self._say("관절 {}번 닿음 — {}".format(j, v.reason))
            self._last_target = target.copy()

            if state.enough:
                self.hand.servo(target.tolist())
                self.phase = Phase.HOLDING
                self._say("손가락 {}개가 닿아 조이기를 멈춘다".format(state.n_fingers))
                return state, None

            elapsed = self.clock() - t0
            if elapsed >= cfg.DG5F_CLOSE_TIMEOUT_S:
                self.phase = Phase.FAILED_NO_CONTACT
                msg = "{:.1f}초 동안 닿은 손가락이 {}개뿐이다 (필요 {}개)".format(
                    elapsed, state.n_fingers, self.detector.min_fingers)
                self._say(msg)
                return state, msg

            # 아직 안 닿은 관절만 목표를 한 칸 더 오므린다.
            moving = ~frozen
            step = np.sign(goal - target) * step_deg
            nxt = target + np.where(moving, step, 0.0)
            # 목표를 지나치지 않게 자른다
            target = np.where(goal >= start, np.minimum(nxt, goal), np.maximum(nxt, goal))
            self._last_target = target.copy()
            self.hand.servo(target.tolist())

            if bool(np.all(frozen | np.isclose(target, goal, atol=1e-6))) and not state.enough:
                self.phase = Phase.FAILED_NO_CONTACT
                msg = "끝까지 오므렸는데 닿은 손가락이 {}개뿐이다 (필요 {}개)".format(
                    state.n_fingers, self.detector.min_fingers)
                self._say(msg)
                return state, msg

    # --- 들어서 확인하기 -------------------------------------------------
    def lift_and_verify(self, hold_frame: HandFrame, probe_deg=None) -> GraspReport:
        """조금 들어올린 뒤 **아직 쥐고 있는지** 본다.

        세 가지를 본다. 손끝 센서가 없으니 하나만으로는 못 믿는다:

        1. **집어보기** — 일부러 조금 더 조여 본다.
           물체가 있으면 못 움직이고, 없으면 그만큼 들어간다
        2. **전류** — 무게를 들고 있으면 전류가 유지된다. 뚝 떨어지면 빈손이다
        3. **팔의 힘센서** — 무게만큼 힘이 는다.
           ⚠️ 잡음이 수 N 이라 **가벼운 물체(100 g ≈ 1 N)는 못 본다** — 그때는 1·2 만 쓴다

        ⚠️ **그냥 각도만 비교하면 안 되는 이유.** 닿은 관절은 목표를 그 자리에 세워 두므로
        물체가 빠져도 손가락이 0.5도쯤밖에 안 움직인다 — 놓친 걸 못 잡는다. 그래서
        가만히 보는 게 아니라 **조금 더 조여 보고** 움직이는지를 본다
        (`hand/tests/test_grasp_contact.py` 에서 이 구멍이 드러나 바꾼 설계다).
        """
        probe = float(cfg.GRASP_PROBE_DEG if probe_deg is None else probe_deg)
        report = GraspReport(phase=self.phase, log=list(self._log))
        report.hold_angle_deg = np.asarray(hold_frame.angle_deg, dtype=float).copy()
        hold_current = float(np.sum(np.abs(hold_frame.current_ma)))

        ft_before = None
        if self.arm is not None and hasattr(self.arm, "tcp_force"):
            ft_before = self.arm.tcp_force()

        if self.arm is not None:
            self.phase = Phase.LIFTING
            self.arm.lift(cfg.GRASP_LIFT_HEIGHT_M, cfg.GRASP_LIFT_SPEED_MPS)
        else:
            self._say("팔이 없어 들기를 건너뛴다 — 손가락 각도·전류만으로 확인한다")

        self.phase = Phase.VERIFYING

        # 1) 집어보기 — 쥐던 방향으로 조금 더 조여 본다
        before_probe = self.hand.read()
        squeeze_dir = np.sign(np.asarray(self._close_dir, dtype=float))
        probe_target = np.asarray(self._last_target, dtype=float) + squeeze_dir * probe
        self.hand.servo(probe_target.tolist())
        self._say("집어보기: {:.1f}도 더 조여 본다".format(probe))

        after = self.hand.read()
        report.lift_angle_deg = np.asarray(after.angle_deg, dtype=float).copy()
        moved = float(np.max(np.abs(report.lift_angle_deg
                                    - np.asarray(before_probe.angle_deg, dtype=float))))
        report.closed_further_deg = moved
        closed = moved

        # 조여 본 것은 되돌린다 — 확인하려다 물체를 찌그러뜨리지 않는다
        self.hand.servo(np.asarray(self._last_target, dtype=float).tolist())

        # 2) 전류가 유지되나
        after_current = float(np.sum(np.abs(after.current_ma)))
        ratio = after_current / hold_current if hold_current > 1e-6 else float("nan")
        report.current_ratio = ratio

        # 3) 팔의 힘
        if ft_before is not None and hasattr(self.arm, "tcp_force"):
            ft_after = self.arm.tcp_force()
            if ft_before is not None and ft_after is not None:
                report.ft_delta_n = float(abs(ft_after - ft_before))

        reasons = []
        if closed >= cfg.GRASP_SLIP_CLOSE_DEG:
            reasons.append("집어보니 손가락이 {:.1f}도 들어갔다 — 손이 비었다"
                           "(한계 {:.1f}도)".format(closed, cfg.GRASP_SLIP_CLOSE_DEG))
        if ratio == ratio and ratio < cfg.GRASP_SLIP_CURRENT_RATIO:
            reasons.append("전류가 잡은 직후의 {:.0%} 로 떨어졌다(한계 {:.0%})".format(
                ratio, cfg.GRASP_SLIP_CURRENT_RATIO))

        report.log = list(self._log)
        if reasons:
            self.phase = Phase.FAILED_SLIPPED
            report.phase = self.phase
            report.reason = " / ".join(reasons)
            return report

        self.phase = Phase.SUCCESS
        report.phase = self.phase
        note = "집어봐도 {:.1f}도만 움직임, 전류 {:.0%} 유지".format(closed, ratio)
        if report.ft_delta_n == report.ft_delta_n:
            enough = report.ft_delta_n >= cfg.GRASP_FT_MIN_DELTA_N
            note += ", 팔 힘 변화 {:.1f} N ({})".format(
                report.ft_delta_n,
                "무게가 잡힘" if enough else "가벼워서 힘으로는 판단 못 함")
        report.reason = note
        return report

    # --- 한 판 통째로 ----------------------------------------------------
    def run(self, start_deg, goal_deg, **kw) -> GraspReport:
        """준비 → 닫기 → 들기 → 확인까지 한 번에."""
        self._log = []
        state, err = self.close_until_contact(start_deg, goal_deg, **kw)
        if err is not None:
            return GraspReport(phase=self.phase, reason=err,
                               fingers_touching=state.n_fingers if state else 0,
                               log=list(self._log))
        self._say(describe(state))
        report = self.lift_and_verify(self.hand.read())
        report.fingers_touching = state.n_fingers
        return report
