# -*- coding: utf-8 -*-
"""파지 직전 자세 → 팔 관절 각도 계산 시험.

돌리는 법 (리포 루트에서, numpy 가 있는 가상환경으로):
    python -m unittest arm.tests.test_prepose_to_joints -v

**팔에 연결하지 않는다.** 가짜 팔(URSim)도 실물도 없이 도는 시험이다 — 여기서 확인하는
것은 좌표 계산이지 통신이 아니다.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arm.prepose_to_joints import (  # noqa: E402
    ARM_JOINT_COUNT,
    ArmKinematicsError,
    ArmMover,
    RobotChain,
    UR_BASE_LINK,
    UR_TCP_LINK,
    URDF_BASE_LINK,
    _matrix_to_quat,
    invert_transform,
    make_transform,
    matrix_to_rotvec,
    palm_link_name,
    palm_pose_to_ur_tcp_pose,
    quat_to_matrix,
    rpy_to_matrix,
    ur_tcp_pose_to_palm_transform,
)
from contracts.grasp_prepose import (  # noqa: E402
    Decision,
    GraspPrePose,
    Source,
    hand_joint_names,
)


class TestRotationHelpers(unittest.TestCase):
    def test_rotvec_round_trip(self):
        for rpy in [(0.3, -0.7, 1.1), (0.0, 0.0, 0.0), (0.0, 0.0, math.pi)]:
            rot = rpy_to_matrix(*rpy)
            vec = matrix_to_rotvec(rot)
            angle = float(np.linalg.norm(vec))
            if angle < 1e-12:
                back = np.eye(3)
            else:
                axis = vec / angle
                skew = np.array([[0, -axis[2], axis[1]],
                                 [axis[2], 0, -axis[0]],
                                 [-axis[1], axis[0], 0]])
                back = np.eye(3) + math.sin(angle) * skew + (1 - math.cos(angle)) * (skew @ skew)
            np.testing.assert_allclose(back, rot, atol=1e-9)

    def test_quat_round_trip(self):
        rot = rpy_to_matrix(0.2, 0.9, -1.3)
        np.testing.assert_allclose(quat_to_matrix(_matrix_to_quat(rot)), rot, atol=1e-12)

    def test_invert_transform(self):
        mat = make_transform(rpy_to_matrix(0.1, 0.2, 0.3), (0.4, -0.5, 0.6))
        np.testing.assert_allclose(invert_transform(mat) @ mat, np.eye(4), atol=1e-12)


class TestRobotChain(unittest.TestCase):
    """좌표 관계의 정본은 URDF 하나다 — 코드에 숫자를 적지 않았는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def test_six_arm_joints_in_order(self):
        names = self.chain.arm_joint_names()
        self.assertEqual(len(names), ARM_JOINT_COUNT)
        self.assertEqual(names[0], "shoulder_pan_joint")
        self.assertEqual(names[-1], "wrist_3_joint")

    def test_ur_base_is_baselink_turned_half_around(self):
        """UR 컨트롤러 밑동은 URDF 밑동을 Z축으로 180° 돌린 것이다.

        이걸 놓치면 팔이 정확히 반대편으로 간다. 값을 코드에 적지 않고 URDF 에서
        읽는지 여기서 확인한다.
        """
        mat = self.chain.fixed_transform(URDF_BASE_LINK, UR_BASE_LINK)
        np.testing.assert_allclose(mat[:3, 3], np.zeros(3), atol=1e-12)
        np.testing.assert_allclose(
            mat[:3, :3], rpy_to_matrix(0.0, 0.0, math.pi), atol=1e-12
        )

    def test_palm_sits_ahead_of_the_flange(self):
        mat = self.chain.fixed_transform(UR_TCP_LINK, palm_link_name())
        distance = float(np.linalg.norm(mat[:3, 3]))
        self.assertGreater(distance, 0.0)
        self.assertLess(distance, 0.30, "손바닥이 접시에서 30 cm 넘게 떨어져 있다 — URDF 확인")

    def test_fixed_transform_refuses_a_movable_joint(self):
        with self.assertRaises(ArmKinematicsError) as ctx:
            self.chain.fixed_transform(URDF_BASE_LINK, UR_TCP_LINK)
        self.assertIn("움직이는 관절", str(ctx.exception))

    def test_forward_kinematics_needs_six_angles(self):
        with self.assertRaises(ArmKinematicsError):
            self.chain.forward_kinematics([0.0, 0.0, 0.0])

    def test_forward_kinematics_moves_the_flange(self):
        home = self.chain.forward_kinematics([0.0] * ARM_JOINT_COUNT)
        turned = self.chain.forward_kinematics([math.pi / 2] + [0.0] * 5)
        self.assertGreater(float(np.linalg.norm(home[:3, 3] - turned[:3, 3])), 0.1)

    def test_missing_urdf_says_where_to_look(self):
        with self.assertRaises(ArmKinematicsError) as ctx:
            RobotChain(urdf_path="없는파일.urdf")
        self.assertIn("ARM_HAND_URDF", str(ctx.exception))


class TestPoseConversion(unittest.TestCase):
    """손바닥 자세 ↔ UR 좌표. 여기가 틀리면 팔이 조용히 엉뚱한 곳으로 간다."""

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def _palm_from_home(self, q6):
        t_flange = self.chain.forward_kinematics(q6)
        t_palm = t_flange @ self.chain.fixed_transform(UR_TCP_LINK, palm_link_name())
        return t_palm

    def test_round_trip_returns_the_same_palm_pose(self):
        for q6 in (
            [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0],
            [0.3, -1.2, 0.9, -0.8, -1.5, 0.4],
        ):
            t_palm = self._palm_from_home(q6)
            tcp = palm_pose_to_ur_tcp_pose(
                t_palm[:3, 3], _matrix_to_quat(t_palm[:3, :3]), self.chain
            )
            back = ur_tcp_pose_to_palm_transform(tcp, self.chain)
            np.testing.assert_allclose(back, t_palm, atol=1e-9)

    def test_ur_frame_flips_x_and_y(self):
        """UR 밑동은 180° 돌아가 있으므로 x·y 부호가 뒤집혀야 한다."""
        t_palm = self._palm_from_home(
            [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0]
        )
        tcp = palm_pose_to_ur_tcp_pose(
            t_palm[:3, 3], _matrix_to_quat(t_palm[:3, :3]), self.chain
        )
        self.assertAlmostEqual(tcp[0], -t_palm[0, 3], places=9)
        self.assertAlmostEqual(tcp[1], -t_palm[1, 3], places=9)


def _accepted_pose(chain):
    q6 = [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0]
    t_palm = chain.forward_kinematics(q6) @ chain.fixed_transform(
        UR_TCP_LINK, palm_link_name()
    )
    return GraspPrePose.accept(
        stamp_capture=1.0,
        stamp_emit=1.0,
        source=Source.GEOMETRIC,
        palm_position=tuple(t_palm[:3, 3]),
        palm_orientation=_matrix_to_quat(t_palm[:3, :3]),
        approach_dir=(0.0, 0.0, -1.0),
        standoff=0.08,
        hand_joint_target=tuple(0.0 for _ in hand_joint_names()),
        confidence=1.0,
    )


class TestArmMoverWithoutRobot(unittest.TestCase):
    """팔이 없어도 '움직이기 전에 거절한다'가 도는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def test_refuses_a_rejected_pose_without_connecting(self):
        pose = GraspPrePose.reject(
            stamp_capture=1.0,
            stamp_emit=1.0,
            source=Source.LEARNED,
            decision=Decision.REJECT_OUT_OF_RANGE,
            reason="손이 벌어지는 범위를 넘는다",
        )
        result = ArmMover(ip=None, chain=self.chain).plan(pose)
        self.assertFalse(result.moved)
        self.assertIn("움직이지 않는다", result.reason)
        self.assertIsNone(result.joints)

    def test_dry_run_computes_the_pose_but_does_not_move(self):
        result = ArmMover(ip=None, chain=self.chain).plan(_accepted_pose(self.chain))
        self.assertFalse(result.moved)
        self.assertIn("연습 모드", result.reason)
        self.assertIsNotNone(result.tcp_pose)
        self.assertEqual(len(result.tcp_pose), 6)
        self.assertIsNone(result.joints)

    def test_move_to_without_connection_does_not_move(self):
        result = ArmMover(ip=None, chain=self.chain).move_to(_accepted_pose(self.chain))
        self.assertFalse(result.moved)


if __name__ == "__main__":
    unittest.main()
