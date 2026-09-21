# -*- coding: utf-8 -*-
"""파지 직전 자세 → 팔 관절 각도 계산 시험.

돌리는 법 (리포 루트에서, numpy 가 있는 가상환경으로):
    python -m unittest arm.tests.test_prepose_to_joints -v

**팔에 연결하지 않는다.** 가짜 팔(URSim)도 실물도 없이 도는 시험이다 — 여기서 확인하는
것은 좌표 계산이지 통신이 아니다.
"""
import dataclasses
import math
import sys
import time
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
    tool0_pose_to_active_tcp_pose,
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

    def test_ur_tool_frame_is_tool0_not_flange(self):
        """UR 컨트롤러가 말하는 손끝은 `tool0` 이다 — `flange` 가 아니다.

        2026-09-17 실측: 가짜 팔(URSim)에 물어 보니 `flange` 로 잡았을 때 위치는
        0.0000 mm 로 맞는데 **방향이 120° 어긋났고**, `tool0` 으로 바꾸니 위치·방향이
        모두 0 이 됐다. 이 시험은 그 실측을 붙잡아 두는 것이다 — 되돌리면 팔이
        손목만 돌아간 채로 간다.
        """
        self.assertEqual(UR_TCP_LINK, "tool0")

    def test_flange_and_tool0_are_the_same_spot_turned_120_degrees(self):
        """둘은 같은 자리인데 축만 돌아가 있다 — 그래서 헷갈리면 조용히 틀린다."""
        mat = self.chain.fixed_transform("flange", "tool0")
        np.testing.assert_allclose(mat[:3, 3], np.zeros(3), atol=1e-12)
        angle = math.degrees(float(np.linalg.norm(matrix_to_rotvec(mat[:3, :3]))))
        self.assertAlmostEqual(angle, 120.0, places=6)

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


class _FakeControl:
    """RTDEControlInterface 흉내 — 실물/URSim 없이 `ArmMover.plan()`의 IK 호출부를 시험한다.

    `isPoseWithinSafetyLimits`/`getInverseKinematicsHasSolution`/`getInverseKinematics`에
    **실제로 넘어온 pose**를 그대로 기록해 둔다 — "tool0 자세를 그대로 넘기는지"
    "활성 TCP 자세로 변환해서 넘기는지"를 이 기록으로 구분한다(2026-09-21 코드 리뷰).
    """

    def __init__(self, tcp_offset6, ik_joints=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
                movej_ok=True, movel_ok=True):
        self.tcp_offset6 = list(tcp_offset6)
        self._ik_joints = list(ik_joints)
        self.seen_poses = []          # plan()이 안전검사/IK에 넘긴 pose들
        self.calls = []               # move_to()가 실제로 부른 이동 명령 순서
        #: ur_rtde의 moveJ/moveL은 bool을 돌려준다(2026-09-21 확인, 1.6.5) — 그 반환값을
        #: 흉내 낸다. False로 두면 "로봇이 명령을 거부/중단"한 상황을 재현한다.
        self.movej_ok = movej_ok
        self.movel_ok = movel_ok

    def getTCPOffset(self):
        return list(self.tcp_offset6)

    def isPoseWithinSafetyLimits(self, pose):
        self.seen_poses.append(list(pose))
        return True

    def getInverseKinematicsHasSolution(self, pose):
        self.seen_poses.append(list(pose))
        return True

    def getInverseKinematics(self, pose, q_near=None):
        self.seen_poses.append(list(pose))
        return list(self._ik_joints)

    def isJointsWithinSafetyLimits(self, joints):
        return True

    def moveJ(self, joints, speed, acceleration):
        self.calls.append(("moveJ", list(joints), speed, acceleration))
        return self.movej_ok

    def moveL(self, pose, speed, acceleration):
        self.calls.append(("moveL", list(pose), speed, acceleration))
        return self.movel_ok

    def stopJ(self, acceleration):
        self.calls.append(("stopJ", acceleration))
        return True


class _FakeReceive:
    """기본 q6은 `_FakeControl`의 기본 `ik_joints`와 **똑같다** — "실제로 정확히
    도착했다"가 기본 시나리오가 되게 해서, 도착 오차 시험이 아닌 다른 시험들이
    엉뚱하게 도착 오차 때문에 실패하지 않게 한다(2026-09-21). 도착 오차를 직접
    시험할 때만 다른 q6을 넣는다."""

    def __init__(self, q6=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6)):
        self._q6 = list(q6)

    def getActualQ(self):
        return list(self._q6)


class TestArmMoverActiveTcpOffset(unittest.TestCase):
    """P1-2 — plan()이 tool0 자세가 아니라 **활성 TCP 자세**를 IK/안전검사에 넘기는지.

    UR 컨트롤러의 isPoseWithinSafetyLimits/getInverseKinematics*는 tool0가 아니라
    컨트롤러에 설정된 활성 TCP 기준으로 좌표를 해석한다(2026-09-21 코드 리뷰로 발견).
    여기서는 실물 연결 없이 가짜 RTDE 인터페이스로 그 경계를 확인한다.
    """

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def _plan_with_offset(self, tcp_offset6):
        pose = _accepted_pose(self.chain)
        mover = ArmMover(ip="fake", chain=self.chain)
        control = _FakeControl(tcp_offset6)
        mover._control = control
        mover._receive = _FakeReceive()
        result = mover.plan(pose)
        return result, control

    def test_active_tcp_equals_tool0(self):
        """활성 TCP 오프셋이 항등(0,0,0,0,0,0)이면 IK에 넘어간 최종 pose == tool0 pose.

        plan()이 접근 시작 지점(pre-approach)도 같이 푸므로 `seen_poses`의 앞 절반은
        pre-approach, 뒤 절반은 최종 자세다(P1-4) — 여기서는 최종 자세 쪽만 본다.
        """
        result, control = self._plan_with_offset([0, 0, 0, 0, 0, 0])
        # plan()은 계산만 한다 — feasible이 계획 성공 신호다. moved(=arrived)는
        # 실제로 움직인 적이 없으므로 여기서는 항상 False다(P1-2).
        self.assertTrue(result.feasible, result.reason)
        self.assertFalse(result.moved, "plan()이 실제로 움직인 것처럼 moved=True를 냈다")
        for seen in control.seen_poses[-3:]:
            np.testing.assert_allclose(seen, result.tcp_pose, atol=1e-9)

    def test_active_tcp_has_translation_offset(self):
        """활성 TCP가 tool0에서 x로 3cm 떨어져 있으면, IK에 넘어간 최종 pose는 tool0
        pose가 아니라 그만큼 변환된 값이어야 한다 — 그대로 넘기면(버그) 팔이 3cm 어긋난다."""
        offset = [0.03, 0.0, 0.0, 0.0, 0.0, 0.0]
        result, control = self._plan_with_offset(offset)
        self.assertTrue(result.feasible, result.reason)
        expected = tool0_pose_to_active_tcp_pose(result.tcp_pose, offset)
        for seen in control.seen_poses[-3:]:
            np.testing.assert_allclose(seen, expected, atol=1e-9)
            # 버그였다면(tool0 자세를 그대로 넘겼다면) 이 차이가 0이었을 것이다.
            self.assertGreater(float(np.linalg.norm(np.array(seen[:3]) - np.array(result.tcp_pose[:3]))),
                               0.02)

    def test_active_tcp_has_rotation_offset(self):
        """활성 TCP가 tool0에서 Z로 90도 돌아가 있으면 그만큼 반영돼야 한다(최종 자세)."""
        offset = [0.0, 0.0, 0.0, 0.0, 0.0, math.pi / 2]
        result, control = self._plan_with_offset(offset)
        self.assertTrue(result.feasible, result.reason)
        expected = tool0_pose_to_active_tcp_pose(result.tcp_pose, offset)
        for seen in control.seen_poses[-3:]:
            np.testing.assert_allclose(seen, expected, atol=1e-9)
            self.assertGreater(float(np.linalg.norm(np.array(seen[3:]) - np.array(result.tcp_pose[3:]))),
                               0.1)

    def test_pre_approach_waypoint_is_computed_and_checked(self):
        """P1-4 — approach_dir/standoff로 계산한 접근 시작 지점이 실제로 안전검사·IK를
        거쳐 pre_joints로 나오고, 최종 위치와 표준 8cm(계약의 standoff)만큼 떨어진다."""
        result, control = self._plan_with_offset([0, 0, 0, 0, 0, 0])
        self.assertTrue(result.feasible, result.reason)
        self.assertIsNotNone(result.pre_tcp_pose)
        self.assertIsNotNone(result.pre_joints)
        self.assertIsNotNone(result.active_tcp_pose)
        gap = float(np.linalg.norm(
            np.array(result.tcp_pose[:3]) - np.array(result.pre_tcp_pose[:3])))
        self.assertAlmostEqual(gap, 0.08, places=6)  # _accepted_pose의 standoff
        # pre-approach 쪽도 안전검사/IK를 실제로 거쳤어야 한다(앞 3개 기록).
        self.assertEqual(len(control.seen_poses), 6)

    def test_reported_tcp_pose_stays_tool0_regardless_of_active_tcp(self):
        """MoveResult.tcp_pose는 (활성 TCP가 뭐든) 항상 같은 tool0 자세를 보고해야
        한다 — 사람이 읽는 값의 의미가 활성 TCP 설정에 따라 바뀌면 안 된다."""
        result_a, _ = self._plan_with_offset([0, 0, 0, 0, 0, 0])
        result_b, _ = self._plan_with_offset([0.05, -0.02, 0.01, 0.1, -0.2, 0.3])
        np.testing.assert_allclose(result_a.tcp_pose, result_b.tcp_pose, atol=1e-9)

    def test_move_to_goes_pre_approach_then_linear_final(self):
        """P1-4/P1-1 — move_to()가 moveJ(접근 시작) → moveL(최종, 직선) 순서로 불러야
        한다. 끝점만 안전하다고 중간 경로가 안전한 게 아니므로, 마지막 구간은
        approach_dir을 따라 직선(moveL)으로 짧게 가야 한다.

        ⚠️ **정상 완료된 blocking 이동 뒤에는 stopJ()를 따로 부르지 않는다**
        (2026-09-21 재검토) — moveJ/moveL이 기본값(asynchronous=False)이라 이미
        완료될 때까지 블로킹하므로, 그 뒤에 다시 정지 명령을 보내는 것은 불필요한
        중복이다. stopJ는 실패·예외로 중단된 경로에서만 부른다."""
        pose = dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=time.time(), stamp_emit=time.time()
        )
        mover = ArmMover(ip="fake", chain=self.chain)
        control = _FakeControl([0, 0, 0, 0, 0, 0])
        mover._control = control
        mover._receive = _FakeReceive()  # 기본값 = _ik_joints와 같음 → 도착 오차 0

        result = mover.move_to(pose)
        self.assertTrue(result.moved, result.reason)
        self.assertTrue(result.feasible)
        self.assertTrue(result.executed)
        self.assertTrue(result.arrived)
        self.assertEqual([c[0] for c in control.calls], ["moveJ", "moveL"])
        moveJ_joints = control.calls[0][1]
        moveL_pose = control.calls[1][1]
        np.testing.assert_allclose(moveJ_joints, result.pre_joints, atol=1e-9)
        np.testing.assert_allclose(moveL_pose, result.active_tcp_pose, atol=1e-9)
        # moveL은 관절 속도(rad/s)가 아니라 선속도(m/s)를 써야 한다 — 단위를 섞으면 안 된다.
        self.assertLess(control.calls[1][2], 1.0)

    def test_refuses_to_move_if_tcp_offset_cannot_be_read(self):
        """활성 TCP 오프셋을 못 읽으면 확실하지 않은 채로 움직이지 않는다(fail-closed)."""
        pose = _accepted_pose(self.chain)
        mover = ArmMover(ip="fake", chain=self.chain)

        class _BrokenControl(_FakeControl):
            def getTCPOffset(self):
                raise RuntimeError("RTDE 연결 끊김")

        mover._control = _BrokenControl([0, 0, 0, 0, 0, 0])
        mover._receive = _FakeReceive()
        result = mover.plan(pose)
        self.assertFalse(result.moved)
        self.assertFalse(result.feasible)
        self.assertIn("활성 TCP", result.reason)


class TestMoveToExecutionAndArrival(unittest.TestCase):
    """P1-1/P1-2 — moveJ/moveL의 bool 반환값을 실제로 확인하고, 실행 뒤 실제 도착까지
    확인해야 성공(`moved`/`arrived`)으로 본다.

    ur_rtde 1.6.5에서 `moveJ`/`moveL`은 둘 다 bool을 돌려준다(2026-09-21 확인,
    `help(rtde_control.RTDEControlInterface.moveJ)`). 반환값을 버리면 로봇이 명령을
    거부해도 성공처럼 보인다 — 이 클래스가 그 다섯 경우를 전부 확인한다.
    """

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def _fresh_pose(self):
        return dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=time.time(), stamp_emit=time.time()
        )

    def _mover(self, control):
        mover = ArmMover(ip="fake", chain=self.chain)
        mover._control = control
        mover._receive = _FakeReceive()  # 기본값 = ik_joints와 같음 → 도착 오차 0
        return mover

    def test_pre_approach_and_final_both_succeed_is_arrived(self):
        control = _FakeControl([0, 0, 0, 0, 0, 0])
        result = self._mover(control).move_to(self._fresh_pose())
        self.assertTrue(result.executed, result.reason)
        self.assertTrue(result.arrived, result.reason)
        self.assertTrue(result.moved, result.reason)
        self.assertEqual([c[0] for c in control.calls], ["moveJ", "moveL"])

    def test_pre_approach_movej_fails_moveL_is_never_called(self):
        control = _FakeControl([0, 0, 0, 0, 0, 0], movej_ok=False)
        result = self._mover(control).move_to(self._fresh_pose())
        self.assertFalse(result.executed)
        self.assertFalse(result.arrived)
        self.assertFalse(result.moved, result.reason)
        self.assertIn("moveJ", result.reason)
        call_names = [c[0] for c in control.calls]
        self.assertIn("moveJ", call_names)
        self.assertNotIn("moveL", call_names,
                         "moveJ가 실패했는데 moveL을 계속 실행했다")

    def test_movej_succeeds_but_movel_fails_is_not_moved(self):
        control = _FakeControl([0, 0, 0, 0, 0, 0], movel_ok=False)
        result = self._mover(control).move_to(self._fresh_pose())
        self.assertFalse(result.executed)
        self.assertFalse(result.arrived)
        self.assertFalse(result.moved, result.reason)
        self.assertIn("moveL", result.reason)
        self.assertEqual([c[0] for c in control.calls], ["moveJ", "moveL", "stopJ"],
                         "moveL 실패 뒤에는 stopJ로 적극적으로 멈춰야 한다")

    def test_commands_succeed_but_arrival_error_exceeds_tolerance_is_not_moved(self):
        control = _FakeControl([0, 0, 0, 0, 0, 0])
        # 목표(ik_joints)는 (0.1,...,0.6) rad인데, 실제로는 10도(약 0.17 rad)
        # 어긋난 곳에서 멈췄다고 흉내낸다 — 허용치(기본 1도)를 넘는다.
        off_target = [v + math.radians(10) for v in control._ik_joints]
        mover = ArmMover(ip="fake", chain=self.chain)
        mover._control = control
        mover._receive = _FakeReceive(q6=off_target)

        result = mover.move_to(self._fresh_pose())
        self.assertTrue(result.executed, "명령 자체는 성공했어야 한다")
        self.assertFalse(result.arrived)
        self.assertFalse(result.moved, result.reason)
        self.assertIsNotNone(result.arrival_error_deg)
        self.assertGreater(result.arrival_error_deg, 1.0)
        self.assertIn("오차", result.reason)

    def test_arrival_error_within_tolerance_is_moved(self):
        control = _FakeControl([0, 0, 0, 0, 0, 0])
        # 허용치(기본 1도) 훨씬 안쪽인 0.05도만 어긋나게 흉내낸다.
        near_target = [v + math.radians(0.05) for v in control._ik_joints]
        mover = ArmMover(ip="fake", chain=self.chain)
        mover._control = control
        mover._receive = _FakeReceive(q6=near_target)

        result = mover.move_to(self._fresh_pose())
        self.assertTrue(result.arrived, result.reason)
        self.assertTrue(result.moved, result.reason)
        self.assertLess(result.arrival_error_deg, 1.0)

    def test_rtde_exception_during_move_is_not_moved(self):
        class _ExplodingControl(_FakeControl):
            def moveL(self, pose, speed, acceleration):
                raise RuntimeError("RTDE 연결이 도중에 끊겼다")

        control = _ExplodingControl([0, 0, 0, 0, 0, 0])
        result = self._mover(control).move_to(self._fresh_pose())
        self.assertFalse(result.executed)
        self.assertFalse(result.moved, result.reason)
        self.assertIn("예외", result.reason)
        # 예외가 나면 즉시 stopJ로 멈춰야 한다 — 조용히 죽어서 팔이 멈추는지도
        # 모르는 상태로 남으면 안 된다.
        self.assertIn("stopJ", [c[0] for c in control.calls])


class TestMoveToAgeGate(unittest.TestCase):
    """P4/P2-1 — move_to()가 오래된 관측과 미래 시각 관측을 둘 다 거절하는지.

    `plan()`은 나이를 안 본다(분석·재현을 방해하지 않으려고) — `move_to()`에서만
    강제한다. 여기서는 실제로 움직이려는 시도 자체가 막히는지 확인한다.
    """

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()

    def _mover(self):
        mover = ArmMover(ip="fake", chain=self.chain)
        mover._control = _FakeControl([0, 0, 0, 0, 0, 0])
        mover._receive = _FakeReceive()
        return mover

    def test_stale_pose_is_refused(self):
        pose = dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=time.time() - 10.0
        )
        result = self._mover().move_to(pose, max_age_sec=2.0)
        self.assertFalse(result.moved)
        self.assertIn("오래됐다", result.reason)

    def test_future_pose_is_refused(self):
        """시계가 안 맞거나 조작된 미래 시각도 '믿을 수 없는 관측'으로 거절한다."""
        pose = dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=time.time() + 5.0
        )
        result = self._mover().move_to(pose, max_age_sec=2.0)
        self.assertFalse(result.moved)
        self.assertIn("미래", result.reason)

    def test_slightly_future_pose_within_clock_skew_is_accepted(self):
        """같은 PC 안의 시계 오차 수준(작은 값)까지는 거절하지 않는다."""
        future_capture = time.time() + 0.05
        pose = dataclasses.replace(
            _accepted_pose(self.chain),
            stamp_capture=future_capture, stamp_emit=future_capture + 0.001,
        )
        result = self._mover().move_to(pose, max_age_sec=2.0)
        self.assertTrue(result.moved, result.reason)

    def test_fresh_pose_is_accepted(self):
        pose = dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=time.time(), stamp_emit=time.time()
        )
        result = self._mover().move_to(pose, max_age_sec=2.0)
        self.assertTrue(result.moved, result.reason)

    def test_plan_ignores_age_entirely(self):
        """plan()은 아무리 오래된 자세여도 계산은 그대로 해 준다 — 분석·재현용.
        (plan()은 실제로 움직이지 않으므로 moved는 항상 False, feasible이 성공 신호다)"""
        pose = dataclasses.replace(
            _accepted_pose(self.chain), stamp_capture=1.0, stamp_emit=1.0
        )
        result = self._mover().plan(pose)
        self.assertTrue(result.feasible, result.reason)
        self.assertFalse(result.moved)


if __name__ == "__main__":
    unittest.main()
