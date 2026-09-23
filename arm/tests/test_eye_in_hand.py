# -*- coding: utf-8 -*-
"""손목 카메라 좌표 옮기기 시험 — **카메라도 팔도 없이** 돈다.

여기서 확인하는 것은 **계산**이지 통신이 아니다. 특히:

- 팔이 움직이면 같은 "카메라가 본 점" 이 로봇 기준으로 **따라 움직이는가**
- 장착값이 0일 때 **"안 쟀다" 고 분명히 말하는가** (조용히 틀린 좌표를 내놓지 않기)
- 회전 순서를 바꿔 적어도 되는가 (안 된다 — 같은 숫자가 다른 방향을 뜻한다)

돌리는 법 (리포 루트, numpy 가 있는 가상환경으로):

    python -m unittest arm.tests.test_eye_in_hand -v
"""
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arm.eye_in_hand import (  # noqa: E402
    MOUNT_STATUS_REQUIRED, CameraMount, MountConfigError, MountNotValidatedError,
    camera_to_base, depth_to_points_cam, intrinsics, matrix_to_rpy_deg,
    points_camera_tcp_base, points_to_base, pose_to_matrix, quat_to_matrix,
    require_validated_mount_for_physical_move, rotvec_to_matrix, rpy_to_matrix,
    tool0_pose_from_joints,
)
from arm.prepose_to_joints import (  # noqa: E402
    RobotChain, baselink_transform_to_ur_pose, tool0_pose_to_active_tcp_pose,
)


def mount(xyz=(0.0, 0.0, 0.0), rpy=(0.0, 0.0, 0.0), measured=True, validated=False):
    return CameraMount("tool0", tuple(xyz), tuple(rpy), measured, validated)


class RotationTests(unittest.TestCase):
    def test_돌리지_않으면_그대로다(self):
        np.testing.assert_allclose(rpy_to_matrix(0, 0, 0), np.eye(3), atol=1e-12)
        np.testing.assert_allclose(rotvec_to_matrix([0, 0, 0]), np.eye(3), atol=1e-12)

    def test_회전은_길이를_바꾸지_않는다(self):
        for rpy in [(10, 20, 30), (-90, 45, 180), (5, -175, 60)]:
            r = rpy_to_matrix(*rpy)
            np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-10)
            self.assertAlmostEqual(float(np.linalg.det(r)), 1.0, places=10)

    def test_z축_90도는_x를_y로_보낸다(self):
        """방향 규약을 못 박아 둔다 — 나중에 누가 순서를 바꾸면 여기서 걸린다."""
        got = rpy_to_matrix(0, 0, 90) @ np.array([1.0, 0.0, 0.0])
        np.testing.assert_allclose(got, [0.0, 1.0, 0.0], atol=1e-12)

    def test_회전_순서를_바꾸면_다른_방향이_된다(self):
        """같은 숫자라도 순서가 다르면 다른 방향이다 — 그래서 한 군데에만 적어 둔다."""
        a = rpy_to_matrix(30, 40, 50)
        b = rpy_to_matrix(50, 40, 30)
        self.assertGreater(float(np.abs(a - b).max()), 0.1)

    def test_회전벡터도_길이를_안_바꾼다(self):
        r = rotvec_to_matrix([0.3, -1.2, 0.7])
        np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-10)


class TransformTests(unittest.TestCase):
    def test_팔이_움직이면_본_점도_따라_움직인다(self):
        """팔을 x 로 10 cm 옮기면, 같은 화면의 점도 로봇 기준으로 10 cm 옮겨져야 한다."""
        m = mount(xyz=(0.05, 0.0, 0.02))
        p0, _ = points_to_base([[0, 0, 0.2]], [0.3, 0.0, 0.4, 0, 0, 0], m)
        p1, _ = points_to_base([[0, 0, 0.2]], [0.4, 0.0, 0.4, 0, 0, 0], m)
        np.testing.assert_allclose(p1[0] - p0[0], [0.1, 0.0, 0.0], atol=1e-12)

    def test_장착_위치가_그대로_더해진다(self):
        """팔 끝이 원점에 있고 안 돌아 있으면, 결과 = 장착 위치 + 본 위치."""
        m = mount(xyz=(0.01, -0.02, 0.03))
        got, _ = points_to_base([[0.0, 0.0, 0.2]], [0, 0, 0, 0, 0, 0], m)
        np.testing.assert_allclose(got[0], [0.01, -0.02, 0.23], atol=1e-12)

    def test_팔이_돌면_본_방향도_같이_돈다(self):
        """팔 끝을 Z 로 90도 돌리면 카메라 앞(+Z)은 그대로지만 옆(+X)은 +Y 가 된다."""
        m = mount()
        pose = [0, 0, 0, 0, 0, math.pi / 2]        # Z 축 90도
        got, _ = points_to_base([[0.1, 0.0, 0.0]], pose, m)
        np.testing.assert_allclose(got[0], [0.0, 0.1, 0.0], atol=1e-9)

    def test_변환은_거리를_보존한다(self):
        """옮기고 돌리기만 하므로 점끼리의 거리는 안 변한다 — 크기가 틀어지면 버그다."""
        m = mount(xyz=(0.04, 0.01, -0.02), rpy=(15, -30, 60))
        pts = np.array([[0.0, 0.0, 0.15], [0.03, -0.02, 0.18], [-0.05, 0.04, 0.22]])
        moved, _ = points_to_base(pts, [0.2, -0.3, 0.5, 0.4, -0.2, 1.1], m)
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertAlmostEqual(float(np.linalg.norm(pts[i] - pts[j])),
                                       float(np.linalg.norm(moved[i] - moved[j])),
                                       places=10)

    def test_4x4_가_올바른_형태다(self):
        t = camera_to_base([0.1, 0.2, 0.3, 0.1, 0.2, 0.3], mount(xyz=(0.01, 0, 0)))
        self.assertEqual(t.shape, (4, 4))
        np.testing.assert_allclose(t[3], [0, 0, 0, 1], atol=1e-12)


class UnmeasuredTests(unittest.TestCase):
    def test_안_쟀으면_경고를_돌려준다(self):
        """조용히 틀린 좌표를 내놓지 않는 것이 이 시험의 목적이다."""
        _, warn = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], mount(measured=False))
        self.assertIsNotNone(warn)
        self.assertIn("아직 안 쟀다", warn)

    def test_쟀으면_경고가_없다(self):
        _, warn = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0],
                                 mount(xyz=(0.05, 0, 0)))
        self.assertIsNone(warn)

    def test_안_쟀어도_계산은_돌아간다(self):
        """원칙 2 — 새 머신에서 설치 직후 바로 실행은 돼야 한다(값을 믿는 것과 별개)."""
        got, _ = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], mount(measured=False))
        self.assertEqual(got.shape, (1, 3))
        self.assertTrue(np.isfinite(got).all())


class PhysicalMoveValidationGateTests(unittest.TestCase):
    """P1-5 — "값이 들어있다"(measured)와 "실물로 검증했다"(validated)는 다르다.

    좌표 계산·시각화(`points_to_base()`/`camera_to_base()`)는 미검증 mount도 그대로
    허용해야 한다(원칙 2, 기존 개발 흐름을 안 깬다) — 실물 자동 이동 관문
    (`require_validated_mount_for_physical_move()`)만 막는다.
    """

    def test_measured_but_not_validated_is_rejected_for_physical_move(self):
        """장착값을 채워 넣었어도(measured=True) 실물로 검증(validated) 안 했으면 거절."""
        m = mount(xyz=(0.05, 0, 0), measured=True, validated=False)
        with self.assertRaises(MountNotValidatedError) as ctx:
            require_validated_mount_for_physical_move(m)
        self.assertIn("검증", str(ctx.exception))

    def test_unmeasured_is_also_rejected_for_physical_move(self):
        m = mount(measured=False, validated=False)
        with self.assertRaises(MountNotValidatedError):
            require_validated_mount_for_physical_move(m)

    def test_validated_mount_passes_the_gate(self):
        """사람이 실물 검증 후 .env에서 직접 1로 바꾼 상태를 흉내낸다."""
        m = mount(xyz=(0.05, 0, 0), measured=True, validated=True)
        got = require_validated_mount_for_physical_move(m)
        self.assertIs(got, m)

    # -- 가짜 팔(URSim) 예외 — 2026-09-22 사용자 결정 --------------------
    # 장착값을 아직 안 쟀을 때도 **가짜 팔에서는** 움직임 경로를 확인할 수 있어야
    # 한다. 다만 그 예외가 실물로 새면 안 되므로, 아래 네 시험이 경계를 못박는다.

    def test_sim_arm_with_explicit_opt_in_passes(self):
        """가짜 팔 주소 + 사람이 명시적으로 켬 → 통과."""
        m = mount(measured=False, validated=False)
        got = require_validated_mount_for_physical_move(
            m, ip="127.0.0.1", allow_unvalidated_on_sim=True)
        self.assertIs(got, m)

    def test_sim_arm_without_opt_in_is_still_rejected(self):
        """주소가 가짜 팔이어도 **사람이 안 켰으면** 막는다 — 기본은 막는 쪽이다."""
        m = mount(measured=False, validated=False)
        with self.assertRaises(MountNotValidatedError):
            require_validated_mount_for_physical_move(m, ip="127.0.0.1")

    def test_real_arm_with_opt_in_is_still_rejected(self):
        """🛑 **가장 중요한 시험** — 허용을 켜도 실물 주소면 막아야 한다."""
        m = mount(measured=False, validated=False)
        with self.assertRaises(MountNotValidatedError) as ctx:
            require_validated_mount_for_physical_move(
                m, ip="192.168.0.11", allow_unvalidated_on_sim=True)
        self.assertIn("가짜 팔 목록", str(ctx.exception))

    def test_unknown_address_is_treated_as_real(self):
        """주소를 모르면(None) 실물로 본다 — 모를 때 여는 쪽으로 기울면 안 된다."""
        m = mount(measured=False, validated=False)
        with self.assertRaises(MountNotValidatedError):
            require_validated_mount_for_physical_move(
                m, ip=None, allow_unvalidated_on_sim=True)

    def test_calc_and_viz_are_unaffected_by_validated_flag(self):
        """실물 이동 관문과 무관하게, 좌표 계산 자체는 검증 여부를 안 본다."""
        unvalidated = mount(xyz=(0.05, 0, 0), validated=False)
        validated = mount(xyz=(0.05, 0, 0), validated=True)
        p1, w1 = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], unvalidated)
        p2, w2 = points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], validated)
        np.testing.assert_allclose(p1, p2)
        self.assertIsNone(w1)  # measured=True(기본)라 경고 없음 — validated와 무관
        self.assertIsNone(w2)

    def test_config_default_is_not_validated(self):
        """리포에 든 장착값 파일은 반드시 미검증이다 — 설치만 하고 실물 이동이 열리면 안 된다."""
        m = CameraMount.from_config()
        self.assertFalse(m.validated)
        self.assertEqual(m.status, MOUNT_STATUS_REQUIRED)
        with self.assertRaises(MountNotValidatedError):
            require_validated_mount_for_physical_move(m, ip="192.168.0.10")


class ActiveTcpVsTool0Tests(unittest.TestCase):
    """P1-1 — `getActualTCPPose()`(활성 TCP)를 tool0 자세로 착각하면 안 된다.

    카메라 장착값은 tool0 기준인데, 컨트롤러가 주는 "TCP 자세"는 활성 TCP(DG5F
    손끝 TCP 등으로 바뀌어 있을 수 있다) 기준이다. `tool0_pose_from_joints()`가
    관절각에서 직접 계산해 이 문제를 피하는지 확인한다(2026-09-21 코드 리뷰).
    """

    @classmethod
    def setUpClass(cls):
        cls.chain = RobotChain()
        cls.q6 = [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0]

    def _reference_tool0_pose(self):
        """RobotChain으로 직접 계산한 tool0 자세 — 시험의 기준값."""
        return baselink_transform_to_ur_pose(
            self.chain.forward_kinematics(self.q6), self.chain
        )

    def test_active_tcp_equals_tool0(self):
        """활성 TCP 오프셋이 항등이면 tool0_pose_from_joints()가 기준값과 같다."""
        got = tool0_pose_from_joints(self.q6)
        np.testing.assert_allclose(got, self._reference_tool0_pose(), atol=1e-9)

    def test_active_tcp_translation_offset_would_have_mismatched(self):
        """활성 TCP가 tool0에서 5cm 떨어져 있을 때, (버그였다면) 그 활성 TCP 자세를
        그대로 카메라 계산에 넣었을 결과가 tool0 기준 결과와 **눈에 띄게 다름**을
        확인한다 — 이 차이가 실물에서 카메라 좌표가 어긋나는 크기다."""
        tcp_offset = [0.05, 0.0, 0.0, 0.0, 0.0, 0.0]
        tool0_pose = tool0_pose_from_joints(self.q6)
        buggy_active_tcp_pose = tool0_pose_to_active_tcp_pose(tool0_pose, tcp_offset)

        m = mount()
        correct, _ = points_to_base([[0, 0, 0.2]], tool0_pose, m)
        buggy, _ = points_to_base([[0, 0, 0.2]], buggy_active_tcp_pose, m)
        self.assertGreater(float(np.linalg.norm(correct[0] - buggy[0])), 0.04)

    def test_active_tcp_rotation_offset_would_have_mismatched(self):
        """활성 TCP가 tool0에서 Z로 30도 돌아가 있을 때도 마찬가지로 결과가 갈린다."""
        tcp_offset = [0.0, 0.0, 0.0, 0.0, 0.0, math.radians(30)]
        tool0_pose = tool0_pose_from_joints(self.q6)
        buggy_active_tcp_pose = tool0_pose_to_active_tcp_pose(tool0_pose, tcp_offset)

        m = mount(xyz=(0.0, 0.0, 0.05))  # 회전 차이가 점 위치에 드러나려면 오프셋이 필요
        correct, _ = points_to_base([[0.1, 0.0, 0.2]], tool0_pose, m)
        buggy, _ = points_to_base([[0.1, 0.0, 0.2]], buggy_active_tcp_pose, m)
        self.assertGreater(float(np.linalg.norm(correct[0] - buggy[0])), 0.01)

    def test_camera_pose_is_unaffected_by_active_tcp_setting(self):
        """같은 관절각이면, 컨트롤러의 활성 TCP 설정이 뭐든 카메라가 본 점의 로봇
        기준 좌표는 **똑같아야 한다** — tool0_pose_from_joints()는 애초에 활성 TCP를
        입력으로 받지 않으므로 이 성질이 저절로 성립한다."""
        pose_no_offset_config = tool0_pose_from_joints(self.q6)
        pose_with_offset_config = tool0_pose_from_joints(self.q6)  # 활성 TCP와 무관
        np.testing.assert_allclose(pose_no_offset_config, pose_with_offset_config, atol=1e-12)

        m = mount(xyz=(0.03, -0.01, 0.02), rpy=(5, -10, 15))
        p1, _ = points_to_base([[0, 0, 0.2]], pose_no_offset_config, m)
        p2, _ = points_to_base([[0, 0, 0.2]], pose_with_offset_config, m)
        np.testing.assert_allclose(p1, p2, atol=1e-12)

    def test_unsupported_parent_link_is_rejected_explicitly(self):
        """flange는 tool0와 위치는 같지만 축이 120도 다르다 — 지원하지 않는 장착
        기준이면 조용히 계산하지 않고 명시적으로 거절해야 한다."""
        bad_mount = CameraMount("flange", (0, 0, 0), (0, 0, 0), True)
        with self.assertRaises(ValueError):
            camera_to_base([0, 0, 0, 0, 0, 0], bad_mount)
        with self.assertRaises(ValueError):
            points_to_base([[0, 0, 0.2]], [0, 0, 0, 0, 0, 0], bad_mount)


class DepthTests(unittest.TestCase):
    def test_깊이에서_점이_나온다(self):
        depth = np.full((8, 10), 0.2)
        pts = depth_to_points_cam(depth)
        self.assertEqual(len(pts), 80)
        np.testing.assert_allclose(pts[:, 2], 0.2)

    def test_너무_가깝거나_먼_화소는_버린다(self):
        """D405 가 못 재는 거리의 값을 그대로 쓰면 없는 물체를 만들어 낸다."""
        depth = np.array([[0.01, 0.2], [5.0, np.nan]])
        pts = depth_to_points_cam(depth)
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(float(pts[0, 2]), 0.2)

    def test_화면_가운데_점은_정면에_있다(self):
        depth = np.full((10, 10), 0.3)
        pts = depth_to_points_cam(depth)
        fx, fy, cx, cy, _ = intrinsics(10, 10)
        # 중심은 화면 안에 있어야 한다(실측값이든 계산값이든)
        self.assertTrue(0 <= cx <= 10, cx)
        self.assertLess(float(np.abs(pts[:, 0]).min()), 1e-9 + 0.3 * 0.5 / fx)

    def test_실측값은_해상도에_맞춰_환산된다(self):
        """⚠️ 잰 해상도의 값을 그대로 쓰면 **2배 틀린다** — 2026-09-18 에 시험이 잡았다."""
        import rtauto_config as c
        if not (c.D405_FX > 0 and c.D405_FY > 0):
            self.skipTest("실측값이 .env 에 없다 — 환산할 것이 없다")
        fx_big, _, cx_big, _, real = intrinsics(c.D405_CALIB_WIDTH, c.D405_CALIB_HEIGHT)
        fx_half, _, cx_half, _, _ = intrinsics(c.D405_CALIB_WIDTH // 2,
                                               c.D405_CALIB_HEIGHT // 2)
        self.assertTrue(real)
        self.assertAlmostEqual(fx_big, c.D405_FX, places=6)
        self.assertAlmostEqual(fx_half, c.D405_FX / 2, places=6)   # 절반이어야 한다
        self.assertAlmostEqual(cx_half, c.D405_CX / 2, places=6)
        # 중심은 늘 화면 안에 있어야 한다
        self.assertTrue(0 <= cx_half <= c.D405_CALIB_WIDTH // 2)

    def test_사진이_2차원이_아니면_거부한다(self):
        with self.assertRaises(ValueError):
            depth_to_points_cam(np.zeros((4, 4, 3)))


def _file_dict(status="MEASURED", xyz=(0.03, 0.0, 0.05), rotation=None,
               source="시험용 가짜 값", measured_on="2026-09-23"):
    """시험용 장착값 파일 내용. **실측값이 아니다** — 읽기·검사 규칙만 확인한다."""
    return {
        "status": status, "parent_frame": "tool0",
        "translation_m": dict(zip("xyz", xyz)),
        "rotation": rotation or {"type": "rpy_deg", "roll": 0.0, "pitch": 0.0, "yaw": 90.0},
        "source": source, "measured_on": measured_on,
    }


class MountFileTests(unittest.TestCase):
    """장착값 파일(`config/d405_tool_camera.json`) 읽기와 검사 (2026-09-23)."""

    def test_리포의_파일은_자리표시용이다(self):
        m = CameraMount.from_config()
        self.assertEqual(m.status, MOUNT_STATUS_REQUIRED)
        self.assertFalse(m.measured)
        np.testing.assert_allclose(m.matrix(), np.eye(4))
        self.assertIsNotNone(m.warning())
        self.assertIn("CALIBRATION_REQUIRED", m.warning())

    def test_파일에서_읽어도_경로가_돈다(self):
        m = CameraMount.from_config()
        _, _, in_base, warn = points_camera_tcp_base(
            [[0.0, 0.0, 0.2]], [0.4, 0.1, 0.3, 0.0, 0.0, 0.0], m)
        np.testing.assert_allclose(in_base[0], [0.4, 0.1, 0.5], atol=1e-12)
        self.assertIsNotNone(warn)

    def test_쿼터니언과_rpy가_같은_회전이면_같은_결과다(self):
        """z축 90도 = 쿼터니언 (0, 0, sin45, cos45)."""
        h = math.sqrt(0.5)
        a = CameraMount.from_dict(_file_dict())
        b = CameraMount.from_dict(_file_dict(rotation={
            "type": "quaternion", "x": 0.0, "y": 0.0, "z": h, "w": h}))
        np.testing.assert_allclose(a.matrix(), b.matrix(), atol=1e-12)
        np.testing.assert_allclose(b.rpy_deg, (0.0, 0.0, 90.0), atol=1e-9)

    def test_쿼터니언_rpy_왕복(self):
        for rpy in [(10, 20, 30), (-90, 45, 170), (5, -60, -120), (30, 90, 10), (0, -90, 45)]:
            r = rpy_to_matrix(*rpy)
            np.testing.assert_allclose(rpy_to_matrix(*matrix_to_rpy_deg(r)), r, atol=1e-10)

    def test_길이가_1이_아닌_쿼터니언은_거부한다(self):
        with self.assertRaises(ValueError):
            quat_to_matrix([0.0, 0.0, 0.5, 0.5])
        with self.assertRaises(MountConfigError):
            CameraMount.from_dict(_file_dict(rotation={
                "type": "quaternion", "x": 0.0, "y": 0.0, "z": 0.5, "w": 0.5}))

    def test_쟀다고_해놓고_자리표시용_값이면_거부한다(self):
        for status in ("MEASURED", "VALIDATED"):
            with self.assertRaises(MountConfigError):
                CameraMount.from_dict(_file_dict(
                    status=status, xyz=(0.0, 0.0, 0.0),
                    rotation={"type": "rpy_deg", "roll": 0, "pitch": 0, "yaw": 0}))

    def test_쟀다고_해놓고_출처나_날짜가_없으면_거부한다(self):
        for bad in (dict(source=""), dict(source="PLACEHOLDER x"), dict(measured_on=None)):
            with self.assertRaises(MountConfigError):
                CameraMount.from_dict(_file_dict(**bad))

    def test_모르는_status_나_회전_형식은_거부한다(self):
        with self.assertRaises(MountConfigError):
            CameraMount.from_dict(_file_dict(status="DONE"))
        with self.assertRaises(MountConfigError):
            CameraMount.from_dict(_file_dict(rotation={"type": "euler"}))
        d = _file_dict()
        del d["translation_m"]
        with self.assertRaises(MountConfigError):
            CameraMount.from_dict(d)

    def test_NaN_무한대_참거짓_글자_숫자는_거부한다(self):
        """JSON 은 NaN/Infinity 를 받아 준다 — 그대로 두면 NaN 장착값이 관문을 통과했다(2026-09-23 리뷰)."""
        for v in (float("nan"), float("inf"), True, "0.03", None):
            with self.assertRaises(MountConfigError, msg=repr(v)):
                CameraMount.from_dict(_file_dict(status="VALIDATED", xyz=(v, 0.0, 0.05)))
        with self.assertRaises(MountConfigError):
            CameraMount.from_dict(_file_dict(rotation={
                "type": "rpy_deg", "roll": 0, "pitch": 0, "yaw": float("inf")}))

    def test_날짜_형식과_거리_상한을_본다(self):
        for bad_date in (True, 20260923, "어제"):
            with self.assertRaises(MountConfigError):
                CameraMount.from_dict(_file_dict(measured_on=bad_date))
        with self.assertRaises(MountConfigError):   # 30 mm 를 m 칸에 30 으로 적은 경우
            CameraMount.from_dict(_file_dict(xyz=(30.0, 0.0, 50.0)))

    def test_지원하지_않는_기준_링크는_읽을_때_거부한다(self):
        for parent in ("flange", None):
            d = _file_dict(status="VALIDATED")
            d["parent_frame"] = parent
            with self.assertRaises(MountConfigError):
                CameraMount.from_dict(d)

    def test_검증됐는데_안_쟀다는_조합은_만들_수_없다(self):
        with self.assertRaises(MountConfigError):
            CameraMount("tool0", (0, 0, 0), (0, 0, 0), False, True)

    def test_깨진_파일은_분명히_멈춘다(self):
        with tempfile.TemporaryDirectory() as d:
            for text in ('{"status": "MEASURED",}', "[]"):
                path = Path(d) / "mount.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(MountConfigError):
                    CameraMount.from_config(path)

    def test_MEASURED_는_좌표는_주지만_실물_이동은_막힌다(self):
        m = CameraMount.from_dict(_file_dict(status="MEASURED"))
        self.assertIsNone(m.warning())
        with self.assertRaises(MountNotValidatedError):
            require_validated_mount_for_physical_move(m, ip="192.168.0.10")

    def test_VALIDATED_만_실물_이동_관문을_통과한다(self):
        m = CameraMount.from_dict(_file_dict(status="VALIDATED"))
        self.assertIs(require_validated_mount_for_physical_move(m, ip="192.168.0.10"), m)

    def test_다른_파일_경로를_읽는다(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mount.json"
            path.write_text(json.dumps(_file_dict()), encoding="utf-8")
            m = CameraMount.from_config(path)
        self.assertEqual(m.status, "MEASURED")
        self.assertEqual(m.xyz_m, (0.03, 0.0, 0.05))

    def test_파일이_없으면_분명히_멈춘다(self):
        with self.assertRaises(MountConfigError):
            CameraMount.from_config(Path(tempfile.gettempdir()) / "없는_장착값_파일.json")

    def test_옛_env_키가_남아_있으면_멈춘다(self):
        """파일과 .env 두 곳에 값이 있으면 어느 쪽이 쓰였는지 모르게 된다."""
        with mock.patch.dict(os.environ, {"RTAUTO_D405_MOUNT_XYZ_M": "0.1,0,0"}):
            with self.assertRaises(MountConfigError):
                CameraMount.from_config()


class FrameChainTests(unittest.TestCase):
    """P_base = T_base_tool x T_tool_camera x P_camera 를 손으로 계산한 값과 맞춘다."""

    def test_세_단계가_손계산과_같다(self):
        # 카메라: tool0 에서 z 로 5 cm, z축 90도 돌아 붙었다고 **가정**(가짜 값)
        m = CameraMount.from_dict(_file_dict(xyz=(0.0, 0.0, 0.05)))
        # 팔 끝: 로봇 기준 (0.5, 0, 0.4), 회전 없음
        tool0 = [0.5, 0.0, 0.4, 0.0, 0.0, 0.0]
        p_cam = [[0.10, 0.0, 0.20]]   # 카메라 x 로 10 cm, 앞으로 20 cm
        _, in_tool, in_base, _ = points_camera_tcp_base(p_cam, tool0, m)
        # z축 90도: 카메라 x → tool0 y
        np.testing.assert_allclose(in_tool[0], [0.0, 0.10, 0.25], atol=1e-12)
        np.testing.assert_allclose(in_base[0], [0.5, 0.10, 0.65], atol=1e-12)
        # 4x4 곱으로 해도 같다
        t = pose_to_matrix(tool0) @ m.matrix()
        np.testing.assert_allclose(t @ np.array([0.10, 0.0, 0.20, 1.0]),
                                   [0.5, 0.10, 0.65, 1.0], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
