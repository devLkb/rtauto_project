# -*- coding: utf-8 -*-
"""`arm/target_selection.py` 시험 — 여러 물체 중 어느 것으로 갈지 (BACKLOG A-9).

무엇을 확인하나
---------------
1. **거절되면 다음** — 1등이 거절되면 2등을 시도하고, 전부 거절되면 이유를 다 남기는가
2. **흔들리지 않기** — 거리가 비슷한 두 물체 사이를 장면마다 오가지 않는가
3. **같은 물체 알아보기** — 실제 `Tracker` 로 번호가 이어지고, 팔이 움직이면 끊기는가
4. **이어 붙이기** — `approach_object.run_once()` 가 실제로 2등으로 넘어가는가

돌리는 법 (리포 루트)::

    source vision/.vision/bin/activate          # bash
    vision/.vision/Scripts/Activate.ps1         # PowerShell
    python -m unittest arm.tests.test_target_selection -v
"""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from arm.target_selection import Candidate, TargetPicker, choose, rank  # noqa: E402
from segment_objects import ObjectCloud, Tracker  # noqa: E402

MARGIN = 0.03


def cand(z, label="cup", conf=0.9, tid=-1, x=0.0):
    pose = SimpleNamespace(position=(x, 0.0, z), label=label, confidence=conf)
    return Candidate(pose, None, tid)


def cloud(x, z):
    c = np.array([x, 0.0, z])
    return ObjectCloud(points=np.zeros((1, 3)) + c, center=c,
                       size=np.array([0.06, 0.06, 0.12]), n_points=500,
                       source="YOLO:cup 90%")


class TestRank(unittest.TestCase):
    def test_처음엔_가장_가까운_것부터(self):
        ordered, why = rank([cand(0.30), cand(0.22), cand(0.26)], None, MARGIN)
        self.assertEqual([c.distance_m for c in ordered], [0.22, 0.26, 0.30])
        self.assertIn("가장 가깝다", why)

    def test_차이가_기준보다_작으면_아까_것을_유지(self):
        # 2026-09-22 실측과 같은 상황: 종이컵 0.24 m, 주스병 0.22 m — 2 cm 차이
        cup, bottle = cand(0.24, "cup", tid=1), cand(0.22, "bottle", tid=2)
        ordered, why = rank([cup, bottle], previous_track_id=1, switch_margin_m=MARGIN)
        self.assertIs(ordered[0], cup)
        self.assertIn("계속 따라간다", why)

    def test_차이가_기준보다_크면_바꾼다(self):
        cup, bottle = cand(0.30, "cup", tid=1), cand(0.22, "bottle", tid=2)
        ordered, why = rank([cup, bottle], previous_track_id=1, switch_margin_m=MARGIN)
        self.assertIs(ordered[0], bottle)
        self.assertIn("바꿨다", why)

    def test_아까_것이_안_보이면_가장_가까운_것(self):
        ordered, why = rank([cand(0.25, tid=3), cand(0.21, tid=4)], 1, MARGIN)
        self.assertEqual(ordered[0].track_id, 4)
        self.assertIn("안 보여서", why)


class TestChoose(unittest.TestCase):
    def test_1등이_거절되면_2등으로_넘어간다(self):
        near, far = cand(0.20, "bottle", tid=1), cand(0.25, "cup", tid=2)
        sel = choose([near, far], "가깝다",
                     lambda c: (False, "작업 공간 밖") if c is near else (True, ""))
        self.assertIs(sel.chosen, far)
        self.assertEqual(len(sel.rejected), 1)
        self.assertEqual(sel.rejected[0].reason, "작업 공간 밖")
        self.assertIn("2번째 후보", sel.why)

    def test_전부_거절되면_아무것도_안_고르고_이유를_다_남긴다(self):
        a, b = cand(0.20), cand(0.25)
        sel = choose([a, b], "가깝다", lambda c: (False, "닿지 않는다"))
        self.assertIsNone(sel.chosen)
        self.assertEqual([x.reason for x in sel.rejected], ["닿지 않는다"] * 2)

    def test_통과한_뒤의_후보는_시도하지_않는다(self):
        calls = []
        a, b, c = cand(0.20), cand(0.25), cand(0.30)
        sel = choose([a, b, c], "가깝다", lambda x: (calls.append(x) or True, ""))
        self.assertEqual(calls, [a])
        self.assertEqual(sel.untried, (b, c))
        self.assertEqual(sel.others, (b, c))

    def test_검사_없이는_1등을_고르고_그렇다고_말한다(self):
        sel = choose([cand(0.20), cand(0.25)], "가깝다", None)
        self.assertEqual(sel.chosen.distance_m, 0.20)
        self.assertIn("확인 안 함", sel.why)

    def test_후보가_없으면_None(self):
        self.assertIsNone(choose([], "", None).chosen)


class TestPickerWithRealTracker(unittest.TestCase):
    """실제 `segment_objects.Tracker` 를 붙여 여러 장면을 흘려 본다."""

    def _scene(self, picker, clouds, evaluate=None):
        picker.track(clouds)
        cands = [Candidate(SimpleNamespace(position=tuple(c.center), label="cup",
                                           confidence=0.9), c, c.track_id) for c in clouds]
        return picker.pick(cands, evaluate)

    def test_거리가_비슷한_두_물체_사이를_오가지_않는다(self):
        picker = TargetPicker(Tracker(), switch_margin_m=MARGIN)
        # 거리 흔들림 때문에 장면마다 1등이 뒤바뀌는 상황을 흉내낸다
        scenes = [(0.240, 0.235), (0.232, 0.241), (0.243, 0.231), (0.236, 0.239)]
        chosen_ids = []
        for za, zb in scenes:
            sel = self._scene(picker, [cloud(-0.05, za), cloud(0.05, zb)])
            chosen_ids.append(sel.chosen.track_id)
        self.assertEqual(len(set(chosen_ids)), 1, chosen_ids)

    def test_같은_물체는_장면이_바뀌어도_같은_번호(self):
        picker = TargetPicker(Tracker(), switch_margin_m=MARGIN)
        first = self._scene(picker, [cloud(0.0, 0.25)])
        again = self._scene(picker, [cloud(0.004, 0.252)])     # 수 mm 흔들림
        self.assertEqual(first.chosen.track_id, again.chosen.track_id)

    def test_팔이_움직이면_아까_것을_잊는다(self):
        picker = TargetPicker(Tracker(), switch_margin_m=MARGIN)
        self._scene(picker, [cloud(-0.05, 0.24), cloud(0.05, 0.22)])
        self.assertIsNotNone(picker.last_track_id)
        picker.arm_moved()
        self.assertIsNone(picker.last_track_id)
        sel = self._scene(picker, [cloud(-0.05, 0.24), cloud(0.05, 0.22)])
        self.assertAlmostEqual(sel.chosen.distance_m, 0.22)
        self.assertIn("가장 가깝다", sel.why)

    def test_거절된_것은_따라가지_않는다(self):
        picker = TargetPicker(Tracker(), switch_margin_m=MARGIN)
        # 1장면: 가까운 쪽(x=+0.05)이 거절돼 먼 쪽을 고른다
        reject_near = lambda c: (c.cloud.center[0] < 0, "작업 공간 밖")
        sel = self._scene(picker, [cloud(-0.05, 0.24), cloud(0.05, 0.22)], reject_near)
        self.assertLess(sel.chosen.cloud.center[0], 0)
        # 2장면: 여전히 먼 쪽을 유지하고, 가까운 쪽을 다시 시도하지 않는다
        tried = []
        sel = self._scene(picker, [cloud(-0.05, 0.24), cloud(0.05, 0.22)],
                          lambda c: (tried.append(c) or True, ""))
        self.assertLess(sel.chosen.cloud.center[0], 0)
        self.assertEqual(len(tried), 1)


class TestHoldWhenMissing(unittest.TestCase):
    """아까 고른 물체가 **잠깐 안 보일 때** 다른 물체로 갈아타지 않는가.

    2026-09-23 실물 D405 `--watch` 에서 확신 40 % 안팎의 컵이 한두 장면씩 인식에서
    빠졌고, 빠질 때마다 대상이 바뀌었다 — 그 상황을 그대로 옮겼다.
    """

    def _pick(self, picker, cands):
        return picker.pick(cands, lambda c: (True, ""))

    def test_한두_장면_빠져도_갈아타지_않고_돌아오면_다시_그것(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=3)
        a, b = cand(0.22, tid=1), cand(0.26, tid=2)
        self.assertEqual(self._pick(picker, [a, b]).chosen.track_id, 1)
        for _ in range(2):                          # #1 이 두 장면 안 보인다
            sel = self._pick(picker, [b])
            self.assertIsNone(sel.chosen)
            self.assertIn("기다린다", sel.why)
            self.assertEqual(sel.untried, (b,))
        self.assertEqual(self._pick(picker, [a, b]).chosen.track_id, 1)

    def test_오래_안_보이면_포기하고_새로_고른다(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=2)
        a, b = cand(0.22, tid=1), cand(0.26, tid=2)
        self._pick(picker, [a, b])
        self.assertIsNone(self._pick(picker, [b]).chosen)
        self.assertIsNone(self._pick(picker, [b]).chosen)
        sel = self._pick(picker, [b])               # 3번째 — 기다리는 한도(2)를 넘었다
        self.assertEqual(sel.chosen.track_id, 2)
        self.assertIn("#1 이 이번엔 안 보여서", sel.why)

    def test_기다리는_횟수는_다시_보이면_처음부터(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=2)
        a, b = cand(0.22, tid=1), cand(0.26, tid=2)
        self._pick(picker, [a, b])
        self._pick(picker, [b])
        self._pick(picker, [a, b])                  # 돌아왔다 — 세던 것을 지운다
        self.assertIsNone(self._pick(picker, [b]).chosen)
        self.assertIsNone(self._pick(picker, [b]).chosen)

    def test_0이면_기다리지_않는다(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=0)
        a, b = cand(0.22, tid=1), cand(0.26, tid=2)
        self._pick(picker, [a, b])
        self.assertEqual(self._pick(picker, [b]).chosen.track_id, 2)

    def test_팔이_움직인_뒤에는_기다리지_않는다(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=3)
        a, b = cand(0.22, tid=1), cand(0.26, tid=2)
        self._pick(picker, [a, b])
        picker.arm_moved()
        self.assertEqual(self._pick(picker, [b]).chosen.track_id, 2)


class FakePlan:
    """`PreGraspPlan` 흉내 — 설 자리 계산이 받아들였는지와 이름만 있다."""

    def __init__(self, ok, label):
        self.accepted, self.label = ok, label
        self.prepose = SimpleNamespace(label=label)

    def describe(self):
        return "받아들임" if self.accepted else "거절(out) — 작업 공간 밖"


class FakeChecked:
    """`MoveResult` 흉내."""

    def __init__(self, feasible=True, executed=False, arrived=False):
        self.feasible, self.executed, self.arrived = feasible, executed, arrived
        self.joints = self.pre_joints = None

    def describe(self):
        return "갈 수 있다" if self.feasible else "IK 해 없음"


class FakeMover:
    """팔 흉내. `bad_labels` 에 든 물체는 관절각이 안 풀린다."""

    can_command = True

    def __init__(self, bad_labels=(), move_result=None):
        self.bad_labels = set(bad_labels)
        self.move_result = move_result or FakeChecked(executed=True, arrived=True)
        self.planned, self.moved = [], []

    def plan(self, prepose):
        self.planned.append(prepose.label)
        return FakeChecked(feasible=prepose.label not in self.bad_labels)

    def move_to(self, prepose):
        self.moved.append(prepose.label)
        return self.move_result


class TestRunOnce(unittest.TestCase):
    """`approach_object.run_once()` 에 규칙이 제대로 이어졌는지.

    카메라·팔·설 자리 계산은 가짜로 바꾸고, 좌표 옮기기(`to_base`)는 진짜를 쓴다.
    """

    def setUp(self):
        from object_pose import FRAME_CAMERA, estimate_pose

        rng = np.random.default_rng(0)

        def pose_at(z, label):
            pts = np.array([0.0, 0.0, z]) + (rng.random((300, 3)) - 0.5) * 0.06
            return estimate_pose(pts, frame=FRAME_CAMERA, label=label, confidence=0.9)

        self.near = Candidate(pose_at(0.22, "bottle"), None, 1)
        self.far = Candidate(pose_at(0.26, "cup"), None, 2)

    def _run(self, cands, picker, *, reject=(), mover=None, move=False, answer="y",
             pose_json=None):
        from arm import approach_object as ao

        planned = []

        def fake_plan(pose_base, **_kw):
            planned.append(pose_base.label)
            return FakePlan(pose_base.label not in reject, pose_base.label)

        args = argparse.Namespace(fake_object=None, frames=1, near=0.1, far=0.5,
                                  target=None, ip="", show=False, watch=False,
                                  pose_json=pose_json, move=move, yes=False)
        with mock.patch.object(ao, "observe",
                               return_value=ao.Observation(0.0, candidates=tuple(cands))), \
             mock.patch.object(ao, "read_tool0_pose",
                               return_value=([0.4, 0.0, 0.4, 0.0, 0.0, 0.0], [0.0] * 6)), \
             mock.patch.object(ao, "plan_pregrasp", side_effect=fake_plan), \
             mock.patch("builtins.input", return_value=answer), \
             mock.patch("builtins.print"):
            out, plan = ao.run_once(None, None, args, mover=mover, picker=picker)
        return out, plan, planned

    def test_1등이_설_자리에서_거절되면_2등으로_계획한다(self):
        out, plan, planned = self._run([self.near, self.far], TargetPicker(),
                                       reject={"bottle"})
        self.assertEqual(planned, ["bottle", "cup"])
        self.assertEqual(plan.label, "cup")
        self.assertIs(out.selection.chosen, self.far)
        self.assertEqual(out.target.label, "cup")

    def test_1등이_관절각에서_거절되면_2등으로_넘어가_그쪽으로_간다(self):
        mover = FakeMover(bad_labels={"bottle"})
        out, plan, _ = self._run([self.near, self.far], TargetPicker(), mover=mover,
                                 move=True)
        self.assertEqual(mover.planned, ["bottle", "cup"])
        self.assertEqual(mover.moved, ["cup"])          # 거절된 병으로는 절대 안 간다
        self.assertIn("관절 각도", out.selection.rejected[0].reason)

    def test_전부_관절각에서_거절되면_받아들임_계획을_돌려주지_않는다(self):
        import os
        import tempfile

        mover = FakeMover(bad_labels={"bottle", "cup"})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pose.json")
            out, plan, _ = self._run([self.near, self.far], TargetPicker(), mover=mover,
                                     move=True, pose_json=path)
            self.assertFalse(os.path.exists(path))
        self.assertIsNone(plan)
        self.assertIsNone(out.selection.chosen)
        self.assertEqual(mover.moved, [])

    def test_이동이_중간에_실패해도_번호를_버린다(self):
        picker = TargetPicker()
        mover = FakeMover(move_result=FakeChecked(executed=False, arrived=False))
        self._run([self.near, self.far], picker, mover=mover, move=True)
        self.assertEqual(mover.moved, ["bottle"])
        # 고를 때 #1 을 기억했지만, 이동을 시도했으니(결과가 실패여도) 잊어야 한다
        self.assertIsNone(picker.last_track_id)

    def test_이동_중_예외가_나도_번호를_버린다(self):
        picker = TargetPicker()
        mover = FakeMover()
        mover.move_to = mock.Mock(side_effect=RuntimeError("RTDE 끊김"))
        with self.assertRaises(RuntimeError):
            self._run([self.near, self.far], picker, mover=mover, move=True)
        self.assertIsNone(picker.last_track_id)

    def test_사람이_취소한_물체는_다음_장면에서_다시_안_고른다(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN)
        mover = FakeMover()
        self._run([self.near, self.far], picker, mover=mover, move=True, answer="n")
        self.assertEqual(mover.moved, [])
        out, _plan, _ = self._run([self.near, self.far], picker, mover=mover,
                                  move=True, answer="n")
        self.assertIs(out.selection.chosen, self.far)
        self.assertIn("취소", out.selection.rejected[0].reason)

    def test_아무것도_안_보인_장면도_기다린_횟수로_센다(self):
        picker = TargetPicker(None, switch_margin_m=MARGIN, hold_missing_frames=1)
        self._run([self.near, self.far], picker)            # #1(병)을 고른다
        self.assertEqual(picker.last_track_id, 1)
        out, _p, _ = self._run([], picker)                  # 아무것도 안 보임 — 1/1
        self.assertIn("기다린다", out.selection.why)
        out, _p, _ = self._run([self.far], picker)          # 한도를 넘었다 — 포기
        self.assertIs(out.selection.chosen, self.far)


if __name__ == "__main__":
    unittest.main()
