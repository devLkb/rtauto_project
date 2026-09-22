# -*- coding: utf-8 -*-
"""물체의 위치·방향 → **물체 앞에 설 자리**(파지 직전 자세) + 안전 검사.

무엇을 하는가
-------------
`vision/d405/object_pose.py`가 잰 물체 하나(로봇 밑동 기준)를 받아서, 손을 **물체
바로 앞 어디에 어떤 방향으로 둘 것인가**를 정한다. 그 결과는
`contracts/grasp_prepose.py`의 `GraspPrePose` 한 개다 —
`arm/prepose_to_joints.py`가 그대로 받아 팔을 움직인다.

🛑 **잡지 않는다.** 이 파일이 내는 자리는 물체에서 **일부러 떨어진 곳**이다
(`PREGRASP_DISTANCE_M`, 기본 12 cm). 손은 벌린 채로 그 자리에 서서 멈춘다.
실제로 쥐는 것·들어올리는 것은 다음 단계 일이고 여기에 넣지 않는다
(2026-09-22 사용자 지시 — 11월 시연의 완료 지점이 여기다).

물체 중심으로 바로 보내지 않는 이유
-----------------------------------
물체 가운데로 손을 보내면 **손이 물체를 뚫고 들어가는 자세**가 나온다. 그래서
세 단계를 나눈다::

    물체 위치·방향
        ↓  ① 어느 쪽에서 다가갈지 정한다      (approach_dir)
        ↓  ② 그 방향으로 손을 돌린다           (palm_orientation)
        ↓  ③ 다가가는 방향의 반대로 물러난다   (PREGRASP_DISTANCE_M)
    물체 앞에 설 자리

손바닥 기준 축 — 이걸 틀리면 손이 옆으로 간다
---------------------------------------------
DG-5F 손바닥 좌표의 뜻은 다음과 같다(정본:
`superdex/scripts/geometric_pose_score.py` 머리말, URDF 실측에서 나온 것).

===========  ===================================================
손바닥 +Z     손가락이 뻗어 나가는 쪽 = **다가가는 방향**
손바닥 +X     손바닥이 바라보는 쪽 = **엄지와 네 손가락이 서로 마주 보며 무는 방향**
손바닥 +Y     엄지 ↔ 새끼 방향 = **네 손가락이 나란히 늘어선 쪽 = 손의 폭**
===========  ===================================================

⚠️ **+X와 +Y를 바꿔 잡으면 손이 90도 돌아간 채로 간다.** 2026-09-22 에 URDF로 직접
확인했다: 손을 절반쯤 오므리면 네 손가락 끝이 x=0.095 로 감겨 오는데 엄지는 x=0.026
에 머문다 — 즉 물체는 **X 방향으로 눌려 물린다.** Y는 네 손가락이 옆으로 늘어선
방향일 뿐 무는 방향이 아니다.

그래서 이 파일은 **손바닥 +Z를 다가가는 방향에 맞추고**, **손바닥 +Y를 물체의 가장
긴 축과 나란하게** 돌린다 — 그래야 네 손가락이 길쭉한 몸통을 따라 늘어서서 한꺼번에
감싼다(세워 둔 병을 옆에서 잡을 때 사람 손이 하는 것과 같다). 긴 축을 X(무는 방향)에
맞추면 기다란 몸통을 길이 방향으로 누르게 되어 미끄러진다.

어느 쪽에서 다가가는가 (물체별 상수 없이)
-----------------------------------------
물체 이름이나 물체별로 사람이 맞춘 값은 **쓰지 않는다**(CLAUDE.md 프로젝트 목적 —
범용 파지). 오직 "가장 긴 축이 위쪽과 몇 도 기울었나" 하나로 가른다.

- **서 있음** (기운 각도가 작다 — 세워 둔 컵·병): 로봇 쪽에서 **옆으로** 다가간다.
  세운 물체는 몸통을 옆에서 무는 것이 자연스럽다.
- **누워 있음 / 기울어짐**: **위에서 아래로** 다가간다.
- **방향을 모름** (원통·공처럼 돌려도 같은 모양): 옆에서 다가가되, 방향을 안 썼다고
  기록에 남긴다. 위치(XYZ)만으로 가는 것이 이 경우다.

안전 검사 — 여기 한 군데서만 한다
---------------------------------
비전이 한 번 크게 틀렸다고 팔이 날아가면 안 된다. 아래를 **자세를 만들기 전에**
전부 본다. 하나라도 걸리면 자세를 만들지 않고 **거절을 정식 결과로** 돌려준다
(`GraspPrePose.reject()`). 기준값은 전부 `config/rtauto_config.py`에서 온다(원칙 1).

1. 좌표에 숫자가 아닌 값(NaN/Inf)이 있는가
2. 좌표 기준이 로봇 밑동인가 (카메라 기준 값을 그대로 받으면 거절)
3. 거리값(점) 개수가 모자라지 않은가
4. 인식 확신이 기준 이상인가
5. 물체 크기가 손에 들어오는 범위인가
6. 목표가 **작업 공간 상자** 안인가 / 밑동에서 너무 멀거나 가깝지 않은가
7. 지금 손끝 위치에서 **한 번에 움직이는 거리**가 한계 안인가

🛑 이 파일은 **로봇을 움직이지 않는다.** 실물 이동 관문
(`arm/eye_in_hand.require_validated_mount_for_physical_move`)은 실제로 움직이는
쪽(`arm/approach_object.py`)이 통과한다.

돌려 보기
---------
터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python arm/pregrasp_planner.py --demo
    python -m unittest arm.tests.test_pregrasp_planner -v

터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python arm/pregrasp_planner.py --demo
    python -m unittest arm.tests.test_pregrasp_planner -v
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from config import rtauto_config as cfg  # noqa: E402
from contracts.grasp_prepose import (  # noqa: E402
    Decision,
    GraspPrePose,
    Source,
    hand_joint_names,
)
# 회전 → 쿼터니언 변환은 `arm/prepose_to_joints.py`가 이미 갖고 있다 — 다시 만들지
# 않는다(원칙 1).
from arm.prepose_to_joints import matrix_to_quat  # noqa: E402

from object_pose import (  # noqa: E402  (vision/d405/object_pose.py)
    FRAME_BASE,
    LYING,
    ObjectPose,
    STANDING,
    TILTED,
)

#: 로봇 밑동 기준에서 **위쪽**. UR 밑동은 Z가 위다.
UP_BASE = np.array([0.0, 0.0, 1.0])

#: 두 방향이 "거의 나란하다"고 볼 기준. 이보다 작으면 직각인 축을 못 만든다.
PARALLEL_EPS = 1e-3

#: 다가가는 방식 — 사람이 읽는 말 그대로.
APPROACH_SIDE = "옆에서"
APPROACH_TOP = "위에서"


class PreGraspPlanError(ValueError):
    """넣은 값 자체가 계획을 세울 수 있는 꼴이 아닐 때(코드 잘못). 물체가 부적합한
    경우는 예외가 아니라 **거절된 `GraspPrePose`** 로 돌려준다."""


# ---------------------------------------------------------------------------
# 안전 검사
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SafetyVerdict:
    """안전 검사 결과 하나. `ok`가 False면 `decision`·`reason`이 채워진다."""

    ok: bool
    decision: Optional[Decision] = None
    reason: str = ""
    #: 통과했더라도 사람에게 알릴 것이 있으면 여기에. 이동을 막지는 않는다.
    warnings: Tuple[str, ...] = ()


def _finite(vec) -> bool:
    return bool(np.all(np.isfinite(np.asarray(vec, dtype=float))))


def check_target(pose: ObjectPose,
                 current_tool0_xyz: Optional[Sequence[float]] = None) -> SafetyVerdict:
    """**이 물체로 팔을 보내도 되는가.** 하나라도 걸리면 거기서 멈춘다.

    `current_tool0_xyz`를 주면 "한 번에 움직이는 거리" 한계도 본다. 안 주면 그
    검사만 건너뛰고 나머지는 그대로 한다 — 검사를 조용히 통째로 끄지 않는다.
    """
    warnings = []

    if pose.frame != FRAME_BASE:
        return SafetyVerdict(
            False, Decision.REJECT_NO_TARGET,
            "좌표 기준이 '{}'다 — 로봇 밑동('{}') 기준이어야 한다. 카메라 기준 값을 "
            "그대로 보내면 팔이 엉뚱한 곳으로 간다.".format(pose.frame, FRAME_BASE))

    pos = np.asarray(pose.position, dtype=float)
    if not _finite(pos) or not _finite(pose.extents) or not _finite(pose.axes):
        return SafetyVerdict(
            False, Decision.REJECT_LOW_DEPTH,
            "물체 좌표나 크기에 숫자가 아닌 값(NaN/Inf)이 있다 — 거리값이 깨졌다는 "
            "뜻이라 움직이지 않는다.")

    if pose.n_points < cfg.MIN_OBJECT_POINTS:
        return SafetyVerdict(
            False, Decision.REJECT_LOW_DEPTH,
            "거리값이 {}개뿐이다 — 최소 {}개는 있어야 위치를 믿는다. 흰 종이컵처럼 "
            "무늬가 없거나 반짝이는 물체에서 잘 난다.".format(
                pose.n_points, cfg.MIN_OBJECT_POINTS))

    if pose.confidence < cfg.MIN_DETECT_CONFIDENCE:
        return SafetyVerdict(
            False, Decision.REJECT_LOW_CONFIDENCE,
            "인식 확신이 {:.0%}로 기준 {:.0%}에 못 미친다.".format(
                pose.confidence, cfg.MIN_DETECT_CONFIDENCE))

    biggest = pose.max_size_m
    if biggest > cfg.OBJECT_MAX_SIZE_M:
        return SafetyVerdict(
            False, Decision.REJECT_OUT_OF_RANGE,
            "가장 긴 변이 {:.1f} cm다 — 손에 들어가는 한계 {:.1f} cm를 넘는다.".format(
                biggest * 100, cfg.OBJECT_MAX_SIZE_M * 100))
    if biggest < cfg.OBJECT_MIN_SIZE_M:
        return SafetyVerdict(
            False, Decision.REJECT_OUT_OF_RANGE,
            "가장 긴 변이 {:.1f} cm뿐이다 — 최소 {:.1f} cm보다 작으면 손끝 한두 개만 "
            "닿는다.".format(biggest * 100, cfg.OBJECT_MIN_SIZE_M * 100))

    lo = np.asarray(cfg.WORKSPACE_MIN_M, dtype=float)
    hi = np.asarray(cfg.WORKSPACE_MAX_M, dtype=float)
    if np.any(pos < lo) or np.any(pos > hi):
        return SafetyVerdict(
            False, Decision.REJECT_OUT_OF_RANGE,
            "물체가 작업 공간 상자 밖이다 — 위치 ({:+.3f}, {:+.3f}, {:+.3f}) m, "
            "허용 {} ~ {} m.".format(pos[0], pos[1], pos[2], tuple(lo), tuple(hi)))

    radius = float(np.linalg.norm(pos))
    if radius > cfg.WORKSPACE_MAX_RADIUS_M:
        return SafetyVerdict(
            False, Decision.REJECT_UNREACHABLE,
            "밑동에서 {:.2f} m 떨어져 있다 — 팔이 닿는 한계 {:.2f} m를 넘는다.".format(
                radius, cfg.WORKSPACE_MAX_RADIUS_M))
    if radius < cfg.WORKSPACE_MIN_RADIUS_M:
        return SafetyVerdict(
            False, Decision.REJECT_UNREACHABLE,
            "밑동에서 {:.2f} m밖에 안 된다 — {:.2f} m보다 가까우면 팔이 자기 몸과 "
            "부딪힌다.".format(radius, cfg.WORKSPACE_MIN_RADIUS_M))

    if current_tool0_xyz is not None:
        now = np.asarray(current_tool0_xyz, dtype=float)
        if not _finite(now):
            return SafetyVerdict(
                False, Decision.REJECT_NO_TARGET,
                "지금 팔 끝 위치에 숫자가 아닌 값이 있다 — 팔 상태를 못 믿어 "
                "움직이지 않는다.")
        step = float(np.linalg.norm(pos - now))
        if step > cfg.MAX_STEP_M:
            return SafetyVerdict(
                False, Decision.REJECT_OUT_OF_RANGE,
                "지금 손끝에서 {:.2f} m 떨어진 곳이다 — 한 번에 움직여도 되는 거리 "
                "{:.2f} m를 넘는다. 비전이 크게 틀렸을 수 있어 움직이지 않는다.".format(
                    step, cfg.MAX_STEP_M))
    else:
        warnings.append(
            "지금 팔 끝 위치를 안 줘서 '한 번에 움직이는 거리' 검사를 건너뛰었다.")

    if pose.estimated:
        warnings.append(
            "거리값이 모자라 테두리로 크기를 어림잡은 물체다 — 위치가 덜 정확할 수 있다.")
    if not pose.orientation_valid:
        warnings.append(
            "방향을 하나로 정할 수 없는 물체다 — 위치(XYZ)만 써서 옆에서 다가간다.")

    return SafetyVerdict(True, warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# 다가가는 방향과 손 방향 정하기
# ---------------------------------------------------------------------------
def _unit(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise PreGraspPlanError("길이가 0인 방향은 쓸 수 없다.")
    return v / n


def approach_direction(pose: ObjectPose) -> Tuple[np.ndarray, str, str]:
    """**어느 쪽에서 다가갈 것인가.** 물체 이름은 보지 않는다.

    돌려주는 것: `(방향 (3,) 길이 1, 방식 이름, 왜 그렇게 정했는지 한 줄)`.
    방향은 "손이 나아가는 쪽"이다 — 위에서 아래로 가면 (0, 0, -1)이다.
    """
    posture = pose.posture(UP_BASE)
    horizontal = np.array([pose.position[0], pose.position[1], 0.0])

    if posture in (LYING, TILTED):
        return (
            np.array([0.0, 0.0, -1.0]), APPROACH_TOP,
            "물체가 {}(가장 긴 축이 위쪽과 {:.0f}도) — 위에서 아래로 다가간다.".format(
                posture, pose.tilt_deg(UP_BASE)))

    if float(np.linalg.norm(horizontal)) < PARALLEL_EPS:
        return (
            np.array([0.0, 0.0, -1.0]), APPROACH_TOP,
            "물체가 밑동 바로 위라 옆이라는 방향이 없다 — 위에서 아래로 다가간다.")

    if posture == STANDING:
        why = "물체가 서 있다(가장 긴 축이 위쪽과 {:.0f}도) — 로봇 쪽에서 옆으로 다가간다.".format(
            pose.tilt_deg(UP_BASE))
    else:   # UNKNOWN_POSTURE
        why = ("돌려도 같은 모양이라 방향을 못 정했다 — 위치만 보고 로봇 쪽에서 옆으로 "
               "다가간다.")
    return _unit(horizontal), APPROACH_SIDE, why


def _perpendicular_part(vec, axis) -> np.ndarray:
    """`vec`에서 `axis` 방향 성분을 뺀 나머지 — `axis`와 직각인 부분만 남긴다."""
    v = np.asarray(vec, dtype=float)
    a = np.asarray(axis, dtype=float)
    return v - float(np.dot(v, a)) * a


def palm_rotation(approach_dir, long_axis, orientation_valid: bool) -> np.ndarray:
    """다가가는 방향과 물체의 긴 축으로 **손의 회전 3x3**을 만든다.

    열이 손바닥 축이다: `[X(무는 방향), Y(손의 폭), Z(다가가는 방향)]`.
    **Y를 물체의 긴 축과 나란하게** 놓아 네 손가락이 몸통을 따라 늘어서게 한다
    (머리말의 축 표 참고 — 이걸 반대로 잡으면 손이 90도 돌아간다).

    긴 축이 다가가는 방향과 거의 나란하면(예: 세운 물체를 바로 위에서 내려다봄)
    긴 축을 Y에 맞출 방법이 없다 — 그때는 어느 쪽으로 돌려도 같으므로 위쪽을
    기준으로 아무 직각 방향이나 고른다.
    """
    z_axis = _unit(approach_dir)

    reference = np.asarray(long_axis, dtype=float) if orientation_valid else UP_BASE
    y_axis = _perpendicular_part(reference, z_axis)
    if float(np.linalg.norm(y_axis)) < PARALLEL_EPS:
        y_axis = _perpendicular_part(UP_BASE, z_axis)
        if float(np.linalg.norm(y_axis)) < PARALLEL_EPS:
            y_axis = _perpendicular_part(np.array([1.0, 0.0, 0.0]), z_axis)
    y_axis = _unit(y_axis)
    x_axis = _unit(np.cross(y_axis, z_axis))
    return np.column_stack([x_axis, y_axis, z_axis])


# ---------------------------------------------------------------------------
# 결과
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreGraspPlan:
    """계획 하나. `prepose`가 팔 쪽으로 넘어가는 값이고, 나머지는 **사람이 보는 값**이다.

    `contracts/grasp_prepose.py`는 일부러 최소한만 싣는다(계약이 커지면 두 방식이
    같은 자리에 못 꽂힌다). 그래서 "실제로 쥐려면 어디까지 더 들어가야 하나" 같은
    설명용 값은 계약에 넣지 않고 여기에 둔다.
    """

    prepose: GraspPrePose
    #: 물체를 실제로 쥘 자리(손바닥 기준점) — **이번 단계에서는 여기로 가지 않는다.**
    grasp_palm_position: Optional[Tuple[float, float, float]] = None
    #: 다가가는 방식("옆에서"/"위에서")과 그 이유.
    approach_style: str = ""
    approach_why: str = ""
    #: 물체가 놓인 모습(서 있음/누워 있음/…).
    posture: str = ""
    #: 안전 검사가 통과하면서 남긴 알림들.
    warnings: Tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.prepose.accepted

    def describe(self) -> str:
        p = self.prepose
        if not p.accepted:
            return "거절({}) — {}".format(p.decision.value, p.reason)
        pos = p.palm_position
        grasp = self.grasp_palm_position or (float("nan"),) * 3
        lines = [
            "받아들임 — {} 다가간다 ({})".format(self.approach_style, self.approach_why),
            "  물체가 놓인 모습 : {}".format(self.posture),
            "  물체 앞에 설 자리 : ({:+.4f}, {:+.4f}, {:+.4f}) m  ← 팔이 실제로 가는 곳".format(*pos),
            "  실제로 쥘 자리    : ({:+.4f}, {:+.4f}, {:+.4f}) m  ← 이번엔 여기로 안 간다".format(*grasp),
            "  다가가는 방향     : ({:+.3f}, {:+.3f}, {:+.3f})".format(*p.approach_dir),
            "  마지막 직선 구간  : {:.3f} m".format(p.standoff),
            "  확신              : {:.0%}".format(p.confidence),
        ]
        lines += ["  ⚠️ " + w for w in self.warnings]
        return "\n".join(lines)


def _reject(decision: Decision, reason: str, stamp_capture: float,
            warnings=()) -> PreGraspPlan:
    return PreGraspPlan(
        prepose=GraspPrePose.reject(
            stamp_capture=stamp_capture, stamp_emit=time.time(),
            source=Source.GEOMETRIC, decision=decision, reason=reason),
        warnings=tuple(warnings))


def plan_pregrasp(pose: ObjectPose,
                  stamp_capture: Optional[float] = None,
                  current_tool0_xyz: Optional[Sequence[float]] = None,
                  pregrasp_distance_m: Optional[float] = None,
                  approach_clearance_m: Optional[float] = None,
                  urdf_path: Optional[str] = None) -> PreGraspPlan:
    """물체 하나 → **물체 앞에 설 자리**. 못 가겠으면 거절을 돌려준다.

    `stamp_capture`를 안 주면 지금 시각을 쓴다 — **실물에서는 반드시 사진을 찍은
    시각을 넣어라.** 그 값으로 `ArmMover.move_to()`가 "관측이 너무 오래됐다"를
    판정한다(`MAX_POSE_AGE_SEC`).
    """
    stamp_capture = time.time() if stamp_capture is None else float(stamp_capture)
    distance = (cfg.PREGRASP_DISTANCE_M if pregrasp_distance_m is None
                else float(pregrasp_distance_m))
    clearance = (cfg.APPROACH_CLEARANCE_M if approach_clearance_m is None
                 else float(approach_clearance_m))
    if distance < 0 or clearance < 0:
        raise PreGraspPlanError("떨어지는 거리와 마지막 직선 구간은 0 이상이어야 한다.")

    verdict = check_target(pose, current_tool0_xyz)
    if not verdict.ok:
        return _reject(verdict.decision, verdict.reason, stamp_capture, verdict.warnings)

    direction, style, why = approach_direction(pose)
    rot = palm_rotation(direction, pose.long_axis, pose.orientation_valid)

    # 물체 가운데가 **손이 감싸는 자리**에 오도록 손바닥 원점을 뒤로 뺀다.
    grasp_center_palm = np.asarray(cfg.DG5F_GRASP_CENTER_PALM_M, dtype=float)
    object_center = np.asarray(pose.position, dtype=float)
    grasp_palm = object_center - rot @ grasp_center_palm

    # 거기서 다가가는 방향의 **반대로** 물러난 자리가 "물체 앞에 설 자리"다.
    pregrasp_palm = grasp_palm - direction * distance

    if not (_finite(grasp_palm) and _finite(pregrasp_palm)):
        return _reject(Decision.REJECT_NO_TARGET,
                       "계산 결과에 숫자가 아닌 값이 나왔다.", stamp_capture,
                       verdict.warnings)

    # 설 자리 자체도 작업 공간 안이어야 한다 — 물체는 안이어도 뒤로 물러난 자리가
    # 밖일 수 있다(벽 쪽 물체 등).
    lo = np.asarray(cfg.WORKSPACE_MIN_M, dtype=float)
    hi = np.asarray(cfg.WORKSPACE_MAX_M, dtype=float)
    if np.any(pregrasp_palm < lo) or np.any(pregrasp_palm > hi):
        return _reject(
            Decision.REJECT_OUT_OF_RANGE,
            "물체는 작업 공간 안이지만, {:.0f} cm 물러난 '설 자리' "
            "({:+.3f}, {:+.3f}, {:+.3f}) m가 작업 공간 밖이다.".format(
                distance * 100, *pregrasp_palm),
            stamp_capture, verdict.warnings)

    names = hand_joint_names(urdf_path)
    prepose = GraspPrePose.accept(
        stamp_capture=stamp_capture,
        stamp_emit=time.time(),
        source=Source.GEOMETRIC,
        palm_position=tuple(pregrasp_palm),
        palm_orientation=matrix_to_quat(rot),
        approach_dir=tuple(_unit(direction)),
        standoff=clearance,
        # 손은 **벌린 채로** 간다. URDF의 0도가 벌린 자세다(잡지 않는다).
        hand_joint_target=tuple(0.0 for _ in names),
        confidence=float(pose.confidence),
        joint_names=names,
        urdf_path=urdf_path,
    )
    return PreGraspPlan(
        prepose=prepose,
        grasp_palm_position=tuple(float(v) for v in grasp_palm),
        approach_style=style,
        approach_why=why,
        posture=pose.posture(UP_BASE),
        warnings=verdict.warnings,
    )


# ---------------------------------------------------------------------------
# 명령줄 — 카메라도 팔도 없이 계산만 확인
# ---------------------------------------------------------------------------
def _demo_object(kind: str) -> ObjectPose:
    """연습용 물체. **실측값이 아니라 계산을 눈으로 보려고 만든 가짜다.**"""
    from object_pose import estimate_pose

    rng = np.random.default_rng(0)
    if kind == "lying":
        size, center = np.array([0.14, 0.05, 0.05]), np.array([0.45, 0.10, 0.20])
    else:
        size, center = np.array([0.05, 0.05, 0.14]), np.array([0.45, 0.10, 0.20])
    pts = center + (rng.random((400, 3)) - 0.5) * size
    return estimate_pose(pts, frame=FRAME_BASE, label="demo_" + kind, confidence=0.9)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="물체 위치·방향 → 물체 앞에 설 자리 (계산만, 팔을 안 움직인다)")
    ap.add_argument("--demo", action="store_true",
                    help="가짜 물체 두 개(세운 것·누운 것)로 계산 결과를 보여 준다")
    args = ap.parse_args(argv)
    if not args.demo:
        print(__doc__)
        return 2

    print("=== 물체 앞에 설 자리 계산 (가짜 물체, 팔 없음) ===\n")
    print("설정값: 떨어지는 거리 {:.0f} cm / 마지막 직선 구간 {:.0f} cm\n".format(
        cfg.PREGRASP_DISTANCE_M * 100, cfg.APPROACH_CLEARANCE_M * 100))
    for kind in ("standing", "lying"):
        obj = _demo_object(kind)
        print(obj.describe(UP_BASE))
        print(plan_pregrasp(obj).describe())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
