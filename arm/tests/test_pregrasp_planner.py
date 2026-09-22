# -*- coding: utf-8 -*-
"""`arm/pregrasp_planner.py` 시험 — **카메라도 팔도 없이** 전부 돈다.

무엇을 확인하나
---------------
1. **안전장치** — 이상한 값이 들어오면 팔 명령이 만들어지지 **않는가**
2. **설 자리 계산** — 물체 위치 + 다가가는 방향 + 떨어질 거리에서 예상한 자리가 나오나
3. **손 방향** — 손이 물체의 긴 축을 따라 손가락을 늘어세우는 방향으로 돌아가나
4. **계약** — 나온 값이 `contracts/grasp_prepose.py` 검사를 통과하나

돌리는 법 (리포 루트)::

    source vision/.vision/bin/activate          # bash
    vision/.vision/Scripts/Activate.ps1         # PowerShell
    python -m unittest arm.tests.test_pregrasp_planner -v
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from config import rtauto_config as cfg  # noqa: E402
from contracts.grasp_prepose import Decision  # noqa: E402
from arm.pregrasp_planner import (  # noqa: E402
    APPROACH_SIDE,
    APPROACH_TOP,

    approach_direction,
    check_target,
    palm_rotation,
    plan_pregrasp,
)
from object_pose import FRAME_BASE, FRAME_CAMERA, ObjectPose  # noqa: E402


def make_pose(position=(0.45, 0.10, 0.20),
              axes=None,
              extents=(0.14, 0.06, 0.06),
              n_points=400,
              orientation_valid=True,
              confidence=0.9,
              frame=FRAME_BASE,
              estimated=False,
              label="cup") -> ObjectPose:
    """시험용 물체 하나를 **손으로 지어서** 만든다 — 점 뿌리기에 기대지 않는다.

    이렇게 하면 "긴 축이 정확히 위쪽" 같은 조건을 딱 맞춰 넣을 수 있어, 계산이 맞는지
    사람이 암산으로 대조할 수 있다.
    """
    return ObjectPose(
        frame=frame,
        position=tuple(float(v) for v in position),
        axes=np.eye(3) if axes is None else np.asarray(axes, dtype=float),
        extents=tuple(float(v) for v in extents),
        n_points=int(n_points),
        orientation_valid=orientation_valid,
        label=label,
        confidence=float(confidence),
        estimated=estimated,
    )


#: 긴 축이 **위쪽(Z)** 인 축 묶음 — 세워 둔 병·컵.
AXES_STANDING = np.column_stack([[0, 0, 1.0], [1.0, 0, 0], [0, 1.0, 0]])
#: 긴 축이 **X 방향** 인 축 묶음 — 옆으로 누운 물체.
AXES_LYING = np.column_stack([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])


class TestSafetyGate(unittest.TestCase):
    """🛑 **여기가 통과하면 안 되는 것들이다.** 하나라도 새면 팔이 엉뚱하게 움직인다."""

    def test_카메라_기준_좌표는_거절한다(self):
        verdict = check_target(make_pose(frame=FRAME_CAMERA))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.decision, Decision.REJECT_NO_TARGET)

    def test_숫자가_아닌_좌표는_거절한다(self):
        for bad in ((float("nan"), 0.1, 0.2), (0.4, float("inf"), 0.2)):
            with self.subTest(bad=bad):
                verdict = check_target(make_pose(position=bad))
                self.assertFalse(verdict.ok)
                self.assertEqual(verdict.decision, Decision.REJECT_LOW_DEPTH)

    def test_거리값이_모자라면_거절한다(self):
        verdict = check_target(make_pose(n_points=cfg.MIN_OBJECT_POINTS - 1))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.decision, Decision.REJECT_LOW_DEPTH)

    def test_확신이_모자라면_거절한다(self):
        verdict = check_target(make_pose(confidence=cfg.MIN_DETECT_CONFIDENCE - 0.01))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.decision, Decision.REJECT_LOW_CONFIDENCE)

    def test_손에_안_들어가는_크기는_거절한다(self):
        big = check_target(make_pose(extents=(cfg.OBJECT_MAX_SIZE_M + 0.05, 0.06, 0.06)))
        self.assertEqual(big.decision, Decision.REJECT_OUT_OF_RANGE)
        small = check_target(make_pose(extents=(0.005, 0.004, 0.004)))
        self.assertEqual(small.decision, Decision.REJECT_OUT_OF_RANGE)

    def test_작업_공간_밖이면_거절한다(self):
        far_side = cfg.WORKSPACE_MAX_M[0] + 0.5
        verdict = check_target(make_pose(position=(far_side, 0.0, 0.2)))
        self.assertFalse(verdict.ok)
        self.assertIn(verdict.decision,
                      (Decision.REJECT_OUT_OF_RANGE, Decision.REJECT_UNREACHABLE))

    def test_팔이_못_닿는_거리면_거절한다(self):
        r = cfg.WORKSPACE_MAX_RADIUS_M
        verdict = check_target(make_pose(position=(r * 0.75, r * 0.75, 0.2)))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.decision, Decision.REJECT_UNREACHABLE)

    def test_밑동에_너무_가까우면_거절한다(self):
        verdict = check_target(make_pose(position=(0.05, 0.0, 0.1)))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.decision, Decision.REJECT_UNREACHABLE)

    def test_한_번에_너무_멀리_가면_거절한다(self):
        """**비전이 한 번 크게 틀렸을 때 팔이 날아가는 것을 막는 장치다.**"""
        target = make_pose(position=(0.45, 0.10, 0.20))
        near_hand = (0.42, 0.10, 0.20)
        far_hand = (0.45 - cfg.MAX_STEP_M - 0.1, 0.10, 0.20)

        self.assertTrue(check_target(target, near_hand).ok)
        blocked = check_target(target, far_hand)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.decision, Decision.REJECT_OUT_OF_RANGE)

    def test_팔_위치에_숫자가_아닌_값이_오면_거절한다(self):
        verdict = check_target(make_pose(), (float("nan"), 0.0, 0.0))
        self.assertFalse(verdict.ok)

    def test_팔_위치를_안_주면_건너뛴_사실을_알린다(self):
        """조용히 검사를 빼먹지 않는다 — **건너뛰었다고 말한다.**"""
        verdict = check_target(make_pose())
        self.assertTrue(verdict.ok)
        self.assertTrue(any("건너뛰" in w for w in verdict.warnings))


class TestApproachDirection(unittest.TestCase):
    def test_세워진_물체는_옆에서_다가간다(self):
        pose = make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING)
        direction, style, _why = approach_direction(pose)
        self.assertEqual(style, APPROACH_SIDE)
        np.testing.assert_allclose(direction, [1.0, 0.0, 0.0], atol=1e-9)

    def test_누운_물체는_위에서_다가간다(self):
        pose = make_pose(position=(0.5, 0.0, 0.2), axes=AXES_LYING)
        direction, style, _why = approach_direction(pose)
        self.assertEqual(style, APPROACH_TOP)
        np.testing.assert_allclose(direction, [0.0, 0.0, -1.0], atol=1e-9)

    def test_방향을_모르면_옆에서_다가간다(self):
        pose = make_pose(position=(0.0, 0.5, 0.2), axes=AXES_STANDING,
                         orientation_valid=False)
        direction, style, why = approach_direction(pose)
        self.assertEqual(style, APPROACH_SIDE)
        np.testing.assert_allclose(direction, [0.0, 1.0, 0.0], atol=1e-9)
        self.assertIn("방향을 못 정했다", why)

    def test_밑동_바로_위면_위에서_다가간다(self):
        """옆이라는 방향 자체가 없는 자리 — 0으로 나누지 않고 위에서 내려온다."""
        pose = make_pose(position=(0.0, 0.0, 0.5), axes=AXES_STANDING)
        direction, style, _why = approach_direction(pose)
        self.assertEqual(style, APPROACH_TOP)
        np.testing.assert_allclose(direction, [0.0, 0.0, -1.0], atol=1e-9)


class TestPalmRotation(unittest.TestCase):
    """손바닥 축: X=무는 방향, Y=손의 폭(네 손가락이 늘어선 쪽), Z=다가가는 방향."""

    def test_손가락은_다가가는_방향으로_뻗는다(self):
        rot = palm_rotation([1.0, 0.0, 0.0], [0.0, 0.0, 1.0], True)
        np.testing.assert_allclose(rot[:, 2], [1.0, 0.0, 0.0], atol=1e-9)

    def test_손의_폭이_물체의_긴_축과_나란하다(self):
        """길쭉한 몸통을 네 손가락이 따라 늘어서서 감싸야 한다."""
        long_axis = np.array([0.0, 0.0, 1.0])       # 세워진 물체
        rot = palm_rotation([1.0, 0.0, 0.0], long_axis, True)
        self.assertAlmostEqual(abs(float(np.dot(rot[:, 1], long_axis))), 1.0, places=9)
        # 무는 방향(X)은 긴 축과 직각이어야 한다 — 길이 방향으로 누르면 미끄러진다
        self.assertAlmostEqual(float(np.dot(rot[:, 0], long_axis)), 0.0, places=9)

    def test_회전은_정규직교하고_오른손이다(self):
        for approach, axis in (([1.0, 0, 0], [0, 0, 1.0]),
                               ([0, 0, -1.0], [1.0, 0, 0]),
                               ([0.5, 0.5, -0.7071], [0.2, 0.9, 0.1])):
            with self.subTest(approach=approach):
                rot = palm_rotation(approach, axis, True)
                np.testing.assert_allclose(rot.T @ rot, np.eye(3), atol=1e-9)
                self.assertAlmostEqual(float(np.linalg.det(rot)), 1.0, places=9)

    def test_긴_축이_다가가는_방향과_나란해도_멈추지_않는다(self):
        """세운 물체를 **바로 위에서** 내려다보는 경우 — 특이점이지만 답은 내야 한다."""
        rot = palm_rotation([0.0, 0.0, -1.0], [0.0, 0.0, 1.0], True)
        np.testing.assert_allclose(rot.T @ rot, np.eye(3), atol=1e-9)

    def test_방향을_모르면_위쪽을_기준으로_돌린다(self):
        rot = palm_rotation([1.0, 0.0, 0.0], [0.7, 0.7, 0.0], False)
        np.testing.assert_allclose(abs(rot[:, 1]), [0.0, 0.0, 1.0], atol=1e-9)


class TestPlanPregrasp(unittest.TestCase):
    def test_물체에서_정해진_거리만큼_떨어진_자리가_나온다(self):
        """**이 시험이 '물체를 뚫고 들어가지 않는다'를 지킨다.**"""
        pose = make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING)
        plan = plan_pregrasp(pose, current_tool0_xyz=(0.45, 0.0, 0.25))

        self.assertTrue(plan.accepted, plan.describe())
        grasp = np.asarray(plan.grasp_palm_position)
        stand = np.asarray(plan.prepose.palm_position)
        direction = np.asarray(plan.prepose.approach_dir)

        # 설 자리 = 쥘 자리 - 다가가는 방향 x 떨어질 거리
        np.testing.assert_allclose(
            stand, grasp - direction * cfg.PREGRASP_DISTANCE_M, atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.norm(grasp - stand)),
                               cfg.PREGRASP_DISTANCE_M, places=9)
        # 설 자리는 물체보다 **로봇 쪽**에 있어야 한다(옆에서 다가가므로 x 가 더 작다)
        self.assertLess(stand[0], pose.position[0])

    def test_떨어질_거리를_바꾸면_그대로_반영된다(self):
        pose = make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING)
        plan = plan_pregrasp(pose, pregrasp_distance_m=0.30,
                             current_tool0_xyz=(0.5, 0.0, 0.2))
        grasp = np.asarray(plan.grasp_palm_position)
        stand = np.asarray(plan.prepose.palm_position)
        self.assertAlmostEqual(float(np.linalg.norm(grasp - stand)), 0.30, places=9)

    def test_물체_가운데가_손이_감싸는_자리에_온다(self):
        """쥘 자리는 손바닥 원점이 아니라 **손이 물체를 감싸는 자리** 기준이다."""
        pose = make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING)
        plan = plan_pregrasp(pose, current_tool0_xyz=(0.5, 0.0, 0.2))

        rot = palm_rotation(plan.prepose.approach_dir, pose.long_axis, True)
        grasp_center = rot @ np.asarray(cfg.DG5F_GRASP_CENTER_PALM_M)
        recovered = np.asarray(plan.grasp_palm_position) + grasp_center
        np.testing.assert_allclose(recovered, pose.position, atol=1e-9)

    def test_계약_검사를_통과한다(self):
        plan = plan_pregrasp(make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING),
                             current_tool0_xyz=(0.5, 0.0, 0.2))
        plan.prepose.validate()                  # 어기면 예외가 난다
        self.assertAlmostEqual(
            float(np.linalg.norm(plan.prepose.palm_orientation)), 1.0, places=9)
        self.assertAlmostEqual(
            float(np.linalg.norm(plan.prepose.approach_dir)), 1.0, places=9)
        self.assertEqual(plan.prepose.standoff, cfg.APPROACH_CLEARANCE_M)
        # 손은 벌린 채로 간다 — 잡지 않는다
        self.assertEqual(len(plan.prepose.hand_joint_target), 20)
        self.assertTrue(all(v == 0.0 for v in plan.prepose.hand_joint_target))
        self.assertTrue(all(plan.prepose.hand_joint_valid))

    def test_파일로_주고받아도_같다(self):
        plan = plan_pregrasp(make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING),
                             current_tool0_xyz=(0.5, 0.0, 0.2))
        from contracts.grasp_prepose import GraspPrePose

        again = GraspPrePose.from_json(plan.prepose.to_json())
        np.testing.assert_allclose(again.palm_position, plan.prepose.palm_position)
        np.testing.assert_allclose(again.approach_dir, plan.prepose.approach_dir)

    def test_거절이면_자세_칸이_비어_있다(self):
        """🛑 거절이 **자세를 들고 다니면** 실수로 쓰인다."""
        plan = plan_pregrasp(make_pose(confidence=0.0))
        self.assertFalse(plan.accepted)
        self.assertEqual(plan.prepose.decision, Decision.REJECT_LOW_CONFIDENCE)
        self.assertIsNone(plan.prepose.palm_position)
        self.assertIsNone(plan.prepose.approach_dir)
        self.assertIsNone(plan.grasp_palm_position)
        self.assertTrue(plan.prepose.reason.strip())

    def test_사진_찍은_시각이_그대로_실린다(self):
        """이 값으로 `ArmMover.move_to()` 가 '관측이 오래됐다'를 판정한다."""
        stamp = time.time() - 1.0
        plan = plan_pregrasp(make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING),
                             stamp_capture=stamp, current_tool0_xyz=(0.5, 0.0, 0.2))
        self.assertAlmostEqual(plan.prepose.stamp_capture, stamp, places=6)
        self.assertGreaterEqual(plan.prepose.stamp_emit, stamp)

    def test_오래된_관측이면_팔이_안_움직인다(self):
        """계획은 세워지되, **실제 이동 직전에** 나이로 막히는지 확인한다."""
        from arm.prepose_to_joints import ArmMover

        old = time.time() - (cfg.MAX_POSE_AGE_SEC + 5.0)
        plan = plan_pregrasp(make_pose(position=(0.5, 0.0, 0.2), axes=AXES_STANDING),
                             stamp_capture=old, current_tool0_xyz=(0.5, 0.0, 0.2))
        self.assertTrue(plan.accepted)

        result = ArmMover().move_to(plan.prepose)    # 연습 모드(팔 연결 없음)
        self.assertFalse(result.moved)
        self.assertIn("오래됐다", result.reason)

    def test_설_자리가_작업_공간_밖이면_거절한다(self):
        """물체는 안이어도 **뒤로 물러난 자리**가 밖일 수 있다."""
        # 누운 물체는 위에서 다가가므로 설 자리가 물체보다 **더 높다.** 물체 자체는
        # 상자 안이고 팔이 닿는 거리 안이지만, 30 cm 위로 물러난 자리는 상자 위로
        # 빠져나간다.
        target_z = cfg.WORKSPACE_MAX_M[2] - 0.20
        pose = make_pose(position=(0.0, 0.40, target_z), axes=AXES_LYING)
        self.assertTrue(check_target(pose).ok, "물체 자체는 통과해야 한다")
        plan = plan_pregrasp(pose, pregrasp_distance_m=0.30,
                             current_tool0_xyz=(0.0, 0.40, target_z))
        self.assertFalse(plan.accepted)
        self.assertEqual(plan.prepose.decision, Decision.REJECT_OUT_OF_RANGE)
        self.assertIn("설 자리", plan.prepose.reason)

    def test_방향을_모르는_물체도_위치만으로_간다(self):
        pose = make_pose(position=(0.5, 0.0, 0.2), extents=(0.08, 0.08, 0.08),
                         orientation_valid=False)
        plan = plan_pregrasp(pose, current_tool0_xyz=(0.5, 0.0, 0.2))
        self.assertTrue(plan.accepted, plan.describe())
        self.assertEqual(plan.approach_style, APPROACH_SIDE)
        self.assertTrue(any("방향" in w for w in plan.warnings))


class TestWholeChainWithoutHardware(unittest.TestCase):
    """**카메라도 팔도 없이 경로 전체가 실제로 이어지는지** 확인한다.

    각 부품의 시험이 다 통과해도 **부품끼리 안 맞으면** 시연 날 처음 알게 된다.
    그래서 이 시험은 다섯 단계를 실제로 순서대로 부른다::

        점 덩어리 → 물체 위치·방향 → (카메라→팔 끝→밑동) → 설 자리 → UR 좌표

    팔 연결이 필요한 부분(관절각 풀기)은 여기서 하지 않는다 — 그건 URSim 으로
    확인한다(`arm/approach_object.py --plan --ip`).
    """

    def test_카메라_점_덩어리가_UR_좌표까지_이어진다(self):
        from arm import eye_in_hand
        from arm.approach_object import to_base
        from arm.prepose_to_joints import RobotChain, palm_pose_to_ur_tcp_pose
        from object_pose import estimate_pose

        # 손목 카메라가 팔 끝에서 (5 cm 앞, 3 cm 위)에 붙어 있다고 치고 — 실측값이
        # 아니라 **경로가 이어지는지** 보려는 가짜 값이다.
        mount = eye_in_hand.CameraMount(
            parent_link="tool0", xyz_m=(0.05, 0.0, 0.03), rpy_deg=(0.0, 0.0, 0.0),
            measured=True, validated=False)
        chain = RobotChain()
        q6 = [0.0, -np.pi / 2, np.pi / 2, -np.pi / 2, -np.pi / 2, 0.0]
        tool0 = eye_in_hand.tool0_pose_from_joints(q6)

        # 카메라 앞 25 cm 에 세워 둔 컵 크기의 물체
        rng = np.random.default_rng(0)
        pts = np.array([0.0, 0.0, 0.25]) + (rng.random((400, 3)) - 0.5) * np.array(
            [0.06, 0.06, 0.13])
        cam_pose = estimate_pose(pts, frame=FRAME_CAMERA, label="cup", confidence=0.86)
        self.assertEqual(cam_pose.frame, FRAME_CAMERA)

        base_pose, in_tcp, in_base, _warn = to_base(cam_pose, tool0, mount)
        self.assertEqual(base_pose.frame, FRAME_BASE)

        # 팔 끝 기준 = 카메라 기준 + 장착 위치 (돌림이 없으므로 더하기만 하면 된다)
        np.testing.assert_allclose(
            in_tcp, np.asarray(cam_pose.position) + np.array([0.05, 0.0, 0.03]),
            atol=1e-9)
        # 밑동 기준 좌표는 `ObjectPose.transformed()` 가 낸 값과 같아야 한다 —
        # 두 길로 계산한 값이 어긋나면 어느 쪽을 믿어야 할지 알 수 없다
        np.testing.assert_allclose(base_pose.position, in_base, atol=1e-9)

        plan = plan_pregrasp(base_pose, current_tool0_xyz=tool0[:3])
        self.assertTrue(plan.accepted, plan.describe())

        # 마지막으로 UR 이 이해하는 좌표까지 간다(URDF 기구학을 실제로 탄다)
        tcp_pose = palm_pose_to_ur_tcp_pose(
            plan.prepose.palm_position, plan.prepose.palm_orientation, chain)
        self.assertEqual(len(tcp_pose), 6)
        self.assertTrue(np.all(np.isfinite(tcp_pose)))


if __name__ == "__main__":
    unittest.main()
