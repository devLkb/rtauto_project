# -*- coding: utf-8 -*-
"""접촉 판단 규칙 시험 — **손 없이** 돈다.

무엇을 확인하나
---------------
실물이 없어도 "이 규칙이 말이 되는가" 는 확인할 수 있다. 특히 가장 위험한 오판:

- **시킨 각도까지 다 가서 멈춘 관절을 접촉으로 세지 않는가** (안 잡고도 잡았다고 하는 것)
- 전류가 순간적으로 튄 것을 접촉으로 세지 않는가
- 기준표에 없는 각도에서 아무렇게나 판단하지 않는가

돌리는 법 — `arm/tests/` 와 같은 방식이다(이 리포는 pytest 를 안 쓴다).

터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python -m unittest hand.tests.test_grasp_contact -v

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python -m unittest hand.tests.test_grasp_contact -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import unittest

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hand"))
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402
from grasp_contact import (  # noqa: E402
    BASELINE_MAX_DEG, N_JOINTS, BaselineMissing, ContactDetector, CurrentBaseline,
    JointReading,
)
from grasp_sequence import GraspSequence, HandFrame, Phase  # noqa: E402

#: 시험용 무부하 전류 — 관절마다 다르게 둔다(현실이 그렇다). 흔들림도 함께.
IDLE_MA = 40.0
SPREAD_MA = 5.0


def make_baseline(spread=SPREAD_MA, idle=IDLE_MA, samples=50):
    """모든 각도 칸이 채워진 기준표를 만든다."""
    rng = np.random.default_rng(0)
    angles, currents = [], []
    for _ in range(samples):
        for a in np.arange(-120.0, 121.0, 5.0):
            angles.append(np.full(N_JOINTS, a))
            currents.append(idle + rng.normal(0.0, spread, N_JOINTS))
    return CurrentBaseline.from_samples(angles, currents, note="시험용")


def reading(angle=0.0, target=0.0, current=IDLE_MA, vel=0.0):
    return JointReading(angle_deg=angle, target_deg=target,
                        current_ma=current, velocity_rpm=vel)


class ContactRuleTests(unittest.TestCase):
    """접촉 판단 규칙 — 손 없이 숫자만 넣어 본다."""

    # ---------------------------------------------------------------- 기준표
    def test_기준표가_없으면_시작을_거부한다(self):
        """짐작한 숫자로 실물을 조이느니 안 도는 게 낫다."""
        with self.assertRaises(BaselineMissing) as e:
            CurrentBaseline.load(REPO_ROOT / "config" / "없는파일_dg5f_baseline.json")
        self.assertIn("measure_baseline.py", str(e.exception))


    def test_재본적_없는_각도는_판단하지_않는다(self):
        """표본이 모자란 칸에서 양옆 값을 빌려 쓰면 조용히 틀린다."""
        b = CurrentBaseline.empty()
        assert b.threshold_ma(0, 0.0) is None


    def test_기준은_관절마다_각도마다_따로다(self):
        """무부하 전류는 자세에 따라 달라지므로 숫자 하나로 못 박으면 안 된다."""
        rng = np.random.default_rng(1)
        angles, currents = [], []
        for _ in range(60):
            for a in np.arange(-120.0, 121.0, 5.0):
                angles.append(np.full(N_JOINTS, a))
                # 관절 0은 각도가 커질수록 전류가 는다(중력 부하를 흉내)
                c = np.full(N_JOINTS, IDLE_MA) + rng.normal(0, 2.0, N_JOINTS)
                c[0] += abs(a) * 1.5
                currents.append(c)
        b = CurrentBaseline.from_samples(angles, currents)
        낮은각 = b.threshold_ma(0, 0.0)
        높은각 = b.threshold_ma(0, 100.0)
        assert 높은각 > 낮은각 + 100, (낮은각, 높은각)


    # ------------------------------------------------------- 가장 중요한 오판
    def test_시킨각도에_도달해_멈춘_관절은_접촉이_아니다(self):
        """멈춰 있고 오차도 없는 것은 접촉의 **반대**다. 이걸 세면 빈손도 성공이 된다."""
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=3)
        # 전류만 높게 줘도(마찰 등) 오차가 없으면 접촉이 아니어야 한다
        rs = [reading(angle=10.0, target=10.0, current=IDLE_MA + 500, vel=0.0)
              for _ in range(N_JOINTS)]
        for _ in range(10):
            state = det.update(rs)
        assert state.n_fingers == 0
        assert "도달" in state.per_joint[0].reason


    def test_막혀서_멈춘_관절은_접촉이다(self):
        """갈 길이 남았는데 안 가고 있고 힘은 쓰는 중 = 뭔가에 막혔다."""
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=3)
        rs = [reading(angle=10.0, target=30.0, current=IDLE_MA + 500, vel=0.0)
              for _ in range(N_JOINTS)]
        for _ in range(5):
            state = det.update(rs)
        assert state.n_fingers == 5


    def test_전류가_안_올라가면_접촉이_아니다(self):
        """오차가 있고 멈춰 있어도 힘을 안 쓰고 있으면 막힌 게 아니다(명령이 안 갔거나 등)."""
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=3)
        rs = [reading(angle=10.0, target=30.0, current=IDLE_MA, vel=0.0)
              for _ in range(N_JOINTS)]
        for _ in range(10):
            state = det.update(rs)
        assert state.n_fingers == 0


    def test_아직_움직이는_중이면_접촉이_아니다(self):
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=3)
        rs = [reading(angle=10.0, target=30.0, current=IDLE_MA + 500, vel=20.0)
              for _ in range(N_JOINTS)]
        for _ in range(10):
            state = det.update(rs)
        assert state.n_fingers == 0


    # ---------------------------------------------------------- 지속 시간 조건
    def test_한_번_튄_것은_접촉이_아니다(self):
        """전류는 방향이 바뀔 때도 튄다. 연속으로 유지돼야 믿는다."""
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=5)
        좋은 = [reading(angle=10.0, target=30.0, current=IDLE_MA + 500, vel=0.0)] * N_JOINTS
        보통 = [reading(angle=10.0, target=30.0, current=IDLE_MA, vel=15.0)] * N_JOINTS
        for _ in range(3):                    # hold_ticks 보다 짧게
            det.update(좋은)
        state = det.update(보통)              # 끊긴다
        assert state.n_fingers == 0
        for _ in range(5):
            state = det.update(좋은)
        assert state.n_fingers == 5


    def test_한번_닿으면_유지된다(self):
        """잡은 뒤 조이기를 멈추면 전류가 내려간다 — 그때 '놓쳤다'로 되돌아가면 안 된다."""
        det = ContactDetector(make_baseline(), min_fingers=1, hold_ticks=3)
        좋은 = [reading(angle=10.0, target=30.0, current=IDLE_MA + 500, vel=0.0)] * N_JOINTS
        쉬는 = [reading(angle=10.0, target=10.0, current=IDLE_MA, vel=0.0)] * N_JOINTS
        for _ in range(5):
            det.update(좋은)
        state = det.update(쉬는)
        assert state.n_fingers == 5
        det.reset()
        state = det.update(쉬는)
        assert state.n_fingers == 0


    def test_손가락_수로_센다_관절_수가_아니라(self):
        """한 손가락의 관절 4개가 다 닿아도 손가락은 1개다."""
        det = ContactDetector(make_baseline(), min_fingers=2, hold_ticks=2)
        rs = [reading(angle=10.0, target=10.0, current=IDLE_MA, vel=0.0)
              for _ in range(N_JOINTS)]
        for j in range(4):                      # 엄지 관절만 전부 접촉
            rs[j] = reading(angle=10.0, target=30.0, current=IDLE_MA + 500, vel=0.0)
        for _ in range(5):
            state = det.update(rs)
        assert state.n_fingers == 1
        assert not state.enough




# ----------------------------------------------------------------- 순서도

class FakeHand:
    """가짜 손. `contact_at_deg` 각도에 물체가 있어 더 못 들어간다.

    전류를 **위치 오차가 아니라 "물체를 누르고 있는가"** 로 만든다. 실제 손이 그렇기
    때문이다 — 목표를 그 자리에 세워 둬도 물체를 쥐고 있으면 전류는 계속 나온다.
    (처음엔 위치 오차로 만들었다가, 그 탓에 "잡고 있는데 전류가 기준값" 이라는
    현실에 없는 상태가 만들어져 시험이 헛돌았다.)
    """

    #: 물체를 1도 더 파고들려 할 때마다 늘어나는 전류(mA). 대략적인 흉내다.
    MA_PER_DEG = 200.0

    def __init__(self, contact_at_deg=None, start=0.0, stuck_current=IDLE_MA + 500):
        self.angle = np.full(N_JOINTS, float(start))
        self.target = self.angle.copy()
        self.contact_at = contact_at_deg
        self.stuck_current = stuck_current
        self.t = 0.0
        self.sent = []

    def servo(self, target_deg20):
        self.target = np.asarray(target_deg20, dtype=float)
        self.sent.append(self.target.copy())
        limit = self.contact_at if self.contact_at is not None else np.inf
        self.angle = np.minimum(self.target, limit)

    def read(self):
        self.t += 0.005
        # 목표가 물체 너머를 가리키는 만큼이 "누르는 힘" 이다
        if self.contact_at is None:
            press = np.zeros(N_JOINTS)
        else:
            press = np.maximum(0.0, self.target - self.contact_at)
        current = IDLE_MA + np.minimum(press * self.MA_PER_DEG, self.stuck_current)
        return HandFrame(angle_deg=self.angle.copy(), current_ma=current,
                         velocity_rpm=np.zeros(N_JOINTS),
                         temperature_c=np.full(N_JOINTS, 30.0), stamp=self.t)


class FakeArm:
    def __init__(self, force_before=10.0, force_after=14.0):
        self.lifted = None
        self._f = [force_before, force_after]

    def lift(self, h, v):
        self.lifted = (h, v)

    def tcp_force(self):
        return self._f.pop(0) if len(self._f) > 1 else self._f[0]



class SequenceTests(unittest.TestCase):
    """잡기 한 판의 순서도 — 가짜 손·가짜 팔로 돌린다."""

    def test_물체를_잡으면_성공으로_끝난다(self):
        hand = FakeHand(contact_at_deg=20.0)
        arm = FakeArm()
        seq = GraspSequence(hand, arm, baseline=make_baseline())
        rep = seq.run(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0), step_deg=2.0)
        assert rep.phase is Phase.SUCCESS, (rep.phase, rep.reason, rep.log)
        assert rep.fingers_touching == 5
        assert arm.lifted == (cfg.GRASP_LIFT_HEIGHT_M, cfg.GRASP_LIFT_SPEED_MPS)


    def test_빈손으로_끝까지_오므리면_실패로_끝난다(self):
        """아무것도 없으면 손이 끝까지 닫힌다 — 이걸 성공이라 하면 안 된다."""
        hand = FakeHand(contact_at_deg=None)
        seq = GraspSequence(hand, None, baseline=make_baseline())
        rep = seq.run(np.zeros(N_JOINTS), np.full(N_JOINTS, 30.0), step_deg=5.0)
        assert rep.phase is Phase.FAILED_NO_CONTACT
        assert rep.fingers_touching == 0


    def test_닿은_관절은_더_밀지_않는다(self):
        """계속 밀면 물체가 찌그러지거나 밀려난다."""
        hand = FakeHand(contact_at_deg=20.0)
        seq = GraspSequence(hand, None, baseline=make_baseline())
        seq.run(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0), step_deg=2.0, hold_bias_deg=0.5)
        마지막목표 = hand.sent[-1]
        assert np.all(마지막목표 <= 20.0 + 0.5 + 1e-6), 마지막목표


    def test_들다가_놓치면_실패로_잡아낸다(self):
        """물체가 빠지면 손가락이 빈 공간으로 더 들어간다."""
        hand = FakeHand(contact_at_deg=20.0)
        seq = GraspSequence(hand, None, baseline=make_baseline())
        state, err = seq.close_until_contact(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0),
                                             step_deg=2.0)
        assert err is None
        hold = hand.read()
        hand.contact_at = None                       # 들다가 물체가 빠졌다
        rep = seq.lift_and_verify(hold)
        # 집어보기에서 손가락이 쑥 들어가야 놓친 것을 알아챈다
        assert rep.phase is Phase.FAILED_SLIPPED, (rep.reason, rep.closed_further_deg)
        assert rep.closed_further_deg >= cfg.GRASP_SLIP_CLOSE_DEG


    def test_잡고_있으면_집어봐도_안_움직인다(self):
        """물체가 버티고 있으면 더 조여도 손가락이 못 들어간다 — 이게 '잡혔다'의 증거다."""
        hand = FakeHand(contact_at_deg=20.0)
        seq = GraspSequence(hand, None, baseline=make_baseline())
        state, err = seq.close_until_contact(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0),
                                             step_deg=2.0)
        assert err is None
        rep = seq.lift_and_verify(hand.read())
        assert rep.phase is Phase.SUCCESS, (rep.reason, rep.closed_further_deg)
        assert rep.closed_further_deg < cfg.GRASP_SLIP_CLOSE_DEG


    def test_너무_뜨거우면_중단한다(self):
        hand = FakeHand(contact_at_deg=20.0)
        real_read = hand.read

        def hot_read():
            f = real_read()
            f.temperature_c = np.full(N_JOINTS, cfg.DG5F_TEMP_LIMIT_C + 5)
            return f

        hand.read = hot_read
        seq = GraspSequence(hand, None, baseline=make_baseline())
        rep = seq.run(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0), step_deg=2.0)
        assert rep.phase is Phase.ABORTED
        assert "도를 넘었다" in rep.reason


    def test_손이_오류를_보고하면_중단한다(self):
        hand = FakeHand(contact_at_deg=20.0)
        real_read = hand.read

        def bad_read():
            f = real_read()
            f.error_code = 7
            return f

        hand.read = bad_read
        seq = GraspSequence(hand, None, baseline=make_baseline())
        rep = seq.run(np.zeros(N_JOINTS), np.full(N_JOINTS, 60.0), step_deg=2.0)
        assert rep.phase is Phase.ABORTED
        assert "오류" in rep.reason


if __name__ == "__main__":
    unittest.main()
