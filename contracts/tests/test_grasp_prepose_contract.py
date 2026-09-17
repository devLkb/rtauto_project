# -*- coding: utf-8 -*-
"""파지 직전 자세 계약 시험.

돌리는 법 (리포 루트에서):
    python -m unittest contracts.tests.test_grasp_prepose_contract -v

파이썬 표준 라이브러리만 쓴다 — 3.10.11 쪽이든 superdex/.venv(3.12) 쪽이든 그냥 돈다.
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contracts.grasp_prepose import (  # noqa: E402
    Decision,
    GraspPrePose,
    GraspPrePoseError,
    HAND_JOINT_COUNT,
    HAND_JOINT_PREFIX,
    Source,
    hand_joint_names,
)


def _valid_kwargs(source=Source.GEOMETRIC, **overrides):
    """계약을 지키는 최소 입력 한 벌. 시험마다 여기서 한 칸씩 망가뜨려 본다."""
    names = hand_joint_names()
    kwargs = dict(
        stamp_capture=1000.0,
        stamp_emit=1000.05,
        source=source,
        palm_position=(0.45, -0.10, 0.32),
        palm_orientation=(1.0, 0.0, 0.0, 0.0),
        approach_dir=(0.0, 0.0, -1.0),
        standoff=0.08,
        hand_joint_target=tuple(0.1 * i for i in range(len(names))),
        confidence=0.9,
        opening_width=0.085,
    )
    kwargs.update(overrides)
    return kwargs


class TestHandJointNames(unittest.TestCase):
    """손 관절 이름의 정본은 URDF 하나다 — 코드에 베껴 적지 않는다."""

    def test_reads_twenty_joints_from_urdf(self):
        names = hand_joint_names()
        self.assertEqual(len(names), HAND_JOINT_COUNT)

    def test_all_names_are_hand_joints(self):
        for name in hand_joint_names():
            self.assertTrue(
                name.startswith(HAND_JOINT_PREFIX),
                "팔 관절이 섞여 들어왔다: {}".format(name),
            )

    def test_order_is_stable(self):
        self.assertEqual(hand_joint_names(), hand_joint_names())

    def test_missing_urdf_says_where_to_look(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            hand_joint_names(urdf_path="없는파일.urdf")
        self.assertIn("ARM_HAND_URDF", str(ctx.exception))


class TestAccept(unittest.TestCase):
    def test_builds_and_fills_joint_names_from_urdf(self):
        pose = GraspPrePose.accept(**_valid_kwargs())
        self.assertTrue(pose.accepted)
        self.assertEqual(pose.hand_joint_names, hand_joint_names())
        self.assertEqual(len(pose.hand_joint_target), HAND_JOINT_COUNT)
        self.assertEqual(len(pose.hand_joint_valid), HAND_JOINT_COUNT)
        self.assertTrue(all(pose.hand_joint_valid))

    def test_both_sources_fill_the_same_structure(self):
        """D-1 완료 조건 — 계산 방식과 학습한 예측기가 같은 자료구조를 채운다."""
        geometric = GraspPrePose.accept(**_valid_kwargs(source=Source.GEOMETRIC))
        learned = GraspPrePose.accept(**_valid_kwargs(source=Source.LEARNED))
        self.assertEqual(
            set(geometric.to_dict().keys()), set(learned.to_dict().keys())
        )
        self.assertEqual(geometric.hand_joint_names, learned.hand_joint_names)
        self.assertNotEqual(geometric.source, learned.source)

    def test_rejects_non_unit_orientation(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(**_valid_kwargs(palm_orientation=(1.0, 1.0, 0.0, 0.0)))
        self.assertIn("길이가 1이 아니다", str(ctx.exception))

    def test_rejects_non_unit_approach_dir(self):
        with self.assertRaises(GraspPrePoseError):
            GraspPrePose.accept(**_valid_kwargs(approach_dir=(0.0, 0.0, -2.0)))

    def test_rejects_negative_standoff(self):
        with self.assertRaises(GraspPrePoseError):
            GraspPrePose.accept(**_valid_kwargs(standoff=-0.01))

    def test_rejects_wrong_joint_count(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(**_valid_kwargs(hand_joint_target=(0.0, 0.1, 0.2)))
        self.assertIn("개수", str(ctx.exception))

    def test_rejects_joint_names_out_of_urdf_order(self):
        shuffled = list(hand_joint_names())
        shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(**_valid_kwargs(joint_names=shuffled))
        self.assertIn("URDF와 다르다", str(ctx.exception))

    def test_rejects_when_no_joint_is_trustworthy(self):
        names = hand_joint_names()
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(
                **_valid_kwargs(hand_joint_valid=[False] * len(names))
            )
        self.assertIn("거절로 내보내야", str(ctx.exception))

    def test_rejects_nan(self):
        names = hand_joint_names()
        bad = [0.0] * len(names)
        bad[3] = math.nan
        with self.assertRaises(GraspPrePoseError):
            GraspPrePose.accept(**_valid_kwargs(hand_joint_target=bad))

    def test_rejects_confidence_out_of_range(self):
        with self.assertRaises(GraspPrePoseError):
            GraspPrePose.accept(**_valid_kwargs(confidence=1.5))

    def test_rejects_emit_before_capture(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(**_valid_kwargs(stamp_capture=10.0, stamp_emit=9.0))
        self.assertIn("빠르다", str(ctx.exception))

    def test_rejects_non_base_frame(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.accept(**_valid_kwargs(frame="camera"))
        self.assertIn("카메라 기준 좌표", str(ctx.exception))


class TestReject(unittest.TestCase):
    """'모르면 멈춘다'가 정식 결과다."""

    def test_reject_is_a_first_class_result(self):
        pose = GraspPrePose.reject(
            stamp_capture=1.0,
            stamp_emit=1.01,
            source=Source.LEARNED,
            decision=Decision.REJECT_OUT_OF_RANGE,
            reason="보이는 폭 0.14 m — 손이 벌어지는 범위를 넘는다",
        )
        self.assertFalse(pose.accepted)
        self.assertIsNone(pose.palm_position)
        self.assertEqual(pose.hand_joint_target, ())

    def test_reject_needs_a_reason(self):
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.reject(
                stamp_capture=1.0,
                stamp_emit=1.0,
                source=Source.GEOMETRIC,
                decision=Decision.REJECT_LOW_DEPTH,
                reason="   ",
            )
        self.assertIn("reason이 비어 있다", str(ctx.exception))

    def test_reject_must_not_carry_a_pose(self):
        """거절인데 자세가 실려 있으면 누군가 실수로 그 자세로 팔을 움직인다."""
        pose = GraspPrePose(
            stamp_capture=1.0,
            stamp_emit=1.0,
            source=Source.GEOMETRIC,
            decision=Decision.REJECT_UNREACHABLE,
            reason="팔이 못 닿는다",
            palm_position=(0.4, 0.0, 0.3),
        )
        with self.assertRaises(GraspPrePoseError) as ctx:
            pose.validate()
        self.assertIn("palm_position", str(ctx.exception))

    def test_every_reject_reason_is_usable(self):
        for decision in Decision:
            if decision is Decision.ACCEPT:
                continue
            pose = GraspPrePose.reject(
                stamp_capture=0.0,
                stamp_emit=0.0,
                source=Source.GEOMETRIC,
                decision=decision,
                reason="시험",
            )
            self.assertFalse(pose.accepted)


class TestRoundTrip(unittest.TestCase):
    """파일로 주고받아도 값이 변하지 않아야 채점표를 쌓을 수 있다."""

    def test_accept_survives_json(self):
        pose = GraspPrePose.accept(**_valid_kwargs())
        self.assertEqual(GraspPrePose.from_json(pose.to_json()), pose)

    def test_reject_survives_json(self):
        pose = GraspPrePose.reject(
            stamp_capture=5.0,
            stamp_emit=5.2,
            source=Source.LEARNED,
            decision=Decision.REJECT_LOW_CONFIDENCE,
            reason="확신 0.2",
            confidence=0.2,
        )
        self.assertEqual(GraspPrePose.from_json(pose.to_json()), pose)

    def test_unknown_schema_version_is_refused(self):
        data = GraspPrePose.accept(**_valid_kwargs()).to_dict()
        data["schema_version"] = 99
        with self.assertRaises(GraspPrePoseError) as ctx:
            GraspPrePose.from_dict(data)
        self.assertIn("schema_version", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
