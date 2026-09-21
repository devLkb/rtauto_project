# -*- coding: utf-8 -*-
"""파지 직전 자세 → 팔 관절 각도 → 팔 이동 (D-5).

무엇을 하는가
-------------
`contracts/grasp_prepose.py`가 내놓은 **파지 직전 자세**(손바닥을 어디에 어떤 방향으로
둘 것인가)를 받아서, 팔의 관절 6개를 몇 도로 꺾어야 하는지 계산하고, 거기까지 움직인 뒤
**멈춘다.** 잡지 않는다.

여기에는 학습이 없다. **어디로 갈지는 이미 정해져서 들어오고**, 이 파일은 거기까지 가는
관절 각도만 푼다. 자율성이 어디에 있는지는
[`docs/FESTA_PREGRASP_PLAN.md`](../docs/FESTA_PREGRASP_PLAN.md) §1 참고.

가장 조심할 것 — 좌표 기준이 세 개다
-------------------------------------
같은 손목 위치를 세 가지 다른 좌표로 부를 수 있고, 섞으면 **조용히 엉뚱한 곳으로 간다.**

| 이름 | 무엇 | 어디서 왔나 |
|---|---|---|
| `base_link` | URDF·Unity가 쓰는 로봇 밑동 | URDF |
| `base` | **UR 컨트롤러가 쓰는 밑동.** `base_link`를 Z축으로 180° 돌린 것 | URDF `base_link-base_fixed_joint` |
| `tool0` | **팔 끝. UR 컨트롤러가 말하는 손끝이 여기다** | URDF `flange-tool0` |
| `flange` | 같은 자리의 다른 이름. **축 방향이 `tool0` 과 120° 다르다** — 여기를 손끝으로 잡으면 위치는 맞는데 손목이 돌아간 채로 간다 | URDF `wrist_3-flange` |

**이 값들을 코드에 적지 않는다.** 전부 URDF에서 읽는다(원칙 1). 그래서 손이 바뀌거나
장착 위치가 바뀌어도 URDF만 고치면 된다.

⚠️ **`flange` 와 `tool0` 을 헷갈리면 120° 돌아간 채로 간다.** 2026-09-17 에 실제로 겪었고
`--check-frames` 로 잡았다. 좌표 쪽을 손대면 **움직이기 전에 반드시 `--check-frames` 를
돌려라.**

계약이 말하는 `frame="base"`는 **URDF의 `base_link`** 를 뜻한다.

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트):

    # 1) 연결 없이 계산만 — 자세가 UR 좌표로 어떻게 바뀌는지 확인
    python arm/prepose_to_joints.py --demo

    # 2) 좌표 기준이 맞는지 팔에게 직접 물어 확인 (움직이지 않는다). 이걸 먼저 한다
    python arm/prepose_to_joints.py --check-frames --ip

    # 3) 가짜 팔(URSim)에 실제로 보내기. 먼저 다른 터미널에서 arm/run_ursim.ps1 을 띄운다
    python arm/prepose_to_joints.py --demo --ip

    # 4) 파일로 받은 자세로
    python arm/prepose_to_joints.py --pose-json 자세.json --ip

`--ip` 를 값 없이 주면 `.env` 의 `RTAUTO_UR_IP`(기본 127.0.0.1 = 로컬 URSim)를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.rtauto_config import (  # noqa: E402
    APPROACH_SPEED_MPS,
    ARM_HAND_URDF,
    ARRIVAL_TOLERANCE_DEG,
    MAX_POSE_AGE_SEC,
    UR_MAX_DEG_PER_SEC,
    dg5f_link_prefix,
    resolve_ur_ip,
)
from contracts.grasp_prepose import (  # noqa: E402
    Decision,
    GraspPrePose,
    Source,
)

#: URDF 안에서 손바닥 링크의 이름 꼬리. 앞의 `rl_`/`ll_`(오른손/왼손)은
#: config의 `dg5f_link_prefix()`가 준다 — 여기에 손 방향을 적지 않는다.
PALM_LINK_SUFFIX = "dg_palm"

#: UR 컨트롤러가 밑동으로 삼는 링크와, 기본 손끝이 놓인 링크. URDF의 링크 이름이다.
#:
#: ⚠️ 손끝은 `flange`가 아니라 **`tool0`** 이다. URDF 에는 둘 다 있고 위치는 같지만
#: **축 방향이 120° 다르다**(x→y→z 로 한 칸씩 돌아가 있다). `flange` 로 잡으면 위치는
#: 맞는데 손목이 돌아간 채로 간다. 2026-09-17 `--check-frames` 로 실측해 잡은 것이고,
#: 그 실측이 이 값의 근거다 — 바꾸려면 다시 재고 바꿔라.
UR_BASE_LINK = "base"
UR_TCP_LINK = "tool0"
URDF_BASE_LINK = "base_link"

#: 팔 관절 6개의 이름. URDF에서 이 순서로 나오는 것을 `arm_joint_names()`가 확인한다.
ARM_JOINT_COUNT = 6

#: `ArmMover.move_to()`가 "관측 시각이 미래"로 볼 허용 오차[초](P2-1, 2026-09-21).
#: 카메라와 이 스크립트가 같은 PC의 같은 시계를 쓴다는 전제라 수 ms 수준이어야 정상이다
#: — 이보다 크게 미래인 stamp_capture는 시계가 안 맞거나 값을 믿을 수 없다는 뜻이다.
CLOCK_SKEW_TOLERANCE_SEC = 0.5

_JOINT_BLOCK_RE = re.compile(r"<joint\s[^>]*?name=\"([^\"]+)\"[^>]*?type=\"([^\"]+)\"(.*?)</joint>", re.S)
_ORIGIN_RE = re.compile(r"<origin([^>]*)/?>")
_PARENT_RE = re.compile(r"<parent\s+link=\"([^\"]+)\"")
_CHILD_RE = re.compile(r"<child\s+link=\"([^\"]+)\"")
_AXIS_RE = re.compile(r"<axis\s+xyz=\"([^\"]+)\"")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

_MOVABLE = ("revolute", "continuous", "prismatic")


class ArmKinematicsError(RuntimeError):
    """URDF를 못 읽었거나 좌표 계산이 성립하지 않을 때."""


# ---------------------------------------------------------------------------
# 작은 회전 도구들 — 외부 라이브러리 없이 numpy만 쓴다
# ---------------------------------------------------------------------------
def rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """URDF의 rpy(고정축 X→Y→Z 순서)를 3x3 회전으로."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=float)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=float)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def quat_to_matrix(quat: Sequence[float]) -> np.ndarray:
    """쿼터니언 (w, x, y, z) → 3x3 회전."""
    w, x, y, z = (float(v) for v in quat)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def matrix_to_rotvec(rot: np.ndarray) -> np.ndarray:
    """3x3 회전 → 회전벡터(축 × 각도). UR의 자세 표기가 이 형식이다."""
    cos_theta = (np.trace(rot) - 1.0) / 2.0
    cos_theta = max(-1.0, min(1.0, cos_theta))
    theta = math.acos(cos_theta)
    if theta < 1e-9:
        return np.zeros(3)
    if math.pi - theta < 1e-6:
        # 180° 근처에서는 위 식이 불안정해 대각 성분으로 축을 뽑는다.
        diag = np.clip((np.diag(rot) + 1.0) / 2.0, 0.0, None)
        axis = np.sqrt(diag)
        biggest = int(np.argmax(axis))
        for i in range(3):
            if i == biggest:
                continue
            if rot[biggest, i] + rot[i, biggest] < 0:
                axis[i] = -axis[i]
        if axis[biggest] < 0:
            axis = -axis
        return axis / np.linalg.norm(axis) * theta
    axis = np.array(
        [rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]]
    ) / (2.0 * math.sin(theta))
    return axis * theta


def make_transform(rot: np.ndarray, xyz: Sequence[float]) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = rot
    out[:3, 3] = np.asarray(xyz, dtype=float)
    return out


def invert_transform(mat: np.ndarray) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = mat[:3, :3].T
    out[:3, 3] = -mat[:3, :3].T @ mat[:3, 3]
    return out


# ---------------------------------------------------------------------------
# URDF 읽기 — 좌표 관계의 정본
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Joint:
    name: str
    jtype: str
    parent: str
    child: str
    origin: np.ndarray  # 부모 기준 자식 원점 (4x4)
    axis: Optional[np.ndarray]


class RobotChain:
    """URDF 하나에서 링크 사이 좌표 관계를 뽑아 주는 읽기 전용 도구."""

    def __init__(self, urdf_path: Optional[str] = None):
        self.path = Path(urdf_path or ARM_HAND_URDF)
        if not self.path.is_file():
            raise ArmKinematicsError(
                "팔+손 결합 URDF를 찾지 못했다: {}\n"
                "config/rtauto_config.py의 ARM_HAND_URDF(.env의 RTAUTO_ARM_HAND_URDF)를 "
                "확인하라.".format(self.path)
            )
        text = self.path.read_text(encoding="utf-8")
        self._by_child: Dict[str, _Joint] = {}
        self._ordered = []
        for name, jtype, body in _JOINT_BLOCK_RE.findall(text):
            parent = _PARENT_RE.search(body)
            child = _CHILD_RE.search(body)
            if not parent or not child:
                continue
            joint = _Joint(
                name=name,
                jtype=jtype,
                parent=parent.group(1),
                child=child.group(1),
                origin=self._parse_origin(body),
                axis=self._parse_axis(body),
            )
            self._by_child[joint.child] = joint
            self._ordered.append(joint)

    @staticmethod
    def _parse_origin(body: str) -> np.ndarray:
        match = _ORIGIN_RE.search(body)
        if not match:
            return np.eye(4)
        attrs = dict(_ATTR_RE.findall(match.group(1)))
        xyz = [float(v) for v in attrs.get("xyz", "0 0 0").split()]
        rpy = [float(v) for v in attrs.get("rpy", "0 0 0").split()]
        return make_transform(rpy_to_matrix(*rpy), xyz)

    @staticmethod
    def _parse_axis(body: str) -> Optional[np.ndarray]:
        match = _AXIS_RE.search(body)
        if not match:
            return None
        return np.array([float(v) for v in match.group(1).split()], dtype=float)

    # -- 링크 사이 관계 ---------------------------------------------------
    def path_to_root(self, link: str):
        """`link`에서 위(부모 쪽)로 올라가며 지나는 관절을 순서대로 준다."""
        seen = set()
        current = link
        while current in self._by_child:
            if current in seen:
                raise ArmKinematicsError("URDF 링크 관계가 고리를 이룬다: {}".format(current))
            seen.add(current)
            joint = self._by_child[current]
            yield joint
            current = joint.parent

    def fixed_transform(self, from_link: str, to_link: str) -> np.ndarray:
        """`to_link` 좌표를 `from_link` 좌표로 바꾸는 4x4. 사이에 움직이는 관절이 있으면 막는다."""
        mat = np.eye(4)
        for joint in self.path_to_root(to_link):
            if joint.jtype in _MOVABLE:
                raise ArmKinematicsError(
                    "{} 에서 {} 사이에 움직이는 관절 '{}'({})이 있다 — 고정 관계가 "
                    "아니다.".format(from_link, to_link, joint.name, joint.jtype)
                )
            mat = joint.origin @ mat
            if joint.parent == from_link:
                return mat
        raise ArmKinematicsError(
            "{} 에서 {} 로 가는 길을 URDF에서 못 찾았다.".format(from_link, to_link)
        )

    def arm_joints(self) -> Tuple[_Joint, ...]:
        """팔 관절 6개를 밑동에서 손목 순서로. URDF에 6개가 아니면 막는다."""
        joints = [j for j in self.path_to_root(UR_TCP_LINK) if j.jtype in _MOVABLE]
        joints.reverse()
        if len(joints) != ARM_JOINT_COUNT:
            raise ArmKinematicsError(
                "팔 관절이 {}개다 — {}개여야 한다. 찾은 것: {}".format(
                    len(joints), ARM_JOINT_COUNT, [j.name for j in joints]
                )
            )
        return tuple(joints)

    def arm_joint_names(self) -> Tuple[str, ...]:
        return tuple(j.name for j in self.arm_joints())

    def forward_kinematics(self, q6: Sequence[float]) -> np.ndarray:
        """팔 관절각(rad) 6개 → `base_link` 기준 `flange` 자세(4x4).

        UR 컨트롤러가 주는 값과 맞는지 대조하는 데 쓴다. 좌표 기준이 틀렸는지
        이걸로 잡는다.
        """
        q6 = [float(v) for v in q6]
        if len(q6) != ARM_JOINT_COUNT:
            raise ArmKinematicsError(
                "관절각이 {}개다 — {}개여야 한다.".format(len(q6), ARM_JOINT_COUNT)
            )
        joints = list(self.path_to_root(UR_TCP_LINK))
        joints.reverse()  # 밑동 → 손목 순서
        mat = np.eye(4)
        movable_index = 0
        for joint in joints:
            mat = mat @ joint.origin
            if joint.jtype in _MOVABLE:
                axis = joint.axis if joint.axis is not None else np.array([0.0, 0.0, 1.0])
                mat = mat @ make_transform(
                    _axis_angle_to_matrix(axis, q6[movable_index]), (0, 0, 0)
                )
                movable_index += 1
        return mat


    def frames_along_arm(self, q6: Sequence[float]):
        """팔 관절각(rad) 6개 → 밑동부터 손끝까지 각 마디의 자세를 순서대로.

        `[(링크이름, 4x4), ...]` 를 돌려준다. 팔을 화면에 그릴 때 쓴다
        (`arm/watch_arm.py`). `forward_kinematics` 와 같은 계산이고, 중간 것까지
        같이 내놓는 것만 다르다.
        """
        q6 = [float(v) for v in q6]
        if len(q6) != ARM_JOINT_COUNT:
            raise ArmKinematicsError(
                "관절각이 {}개다 — {}개여야 한다.".format(len(q6), ARM_JOINT_COUNT)
            )
        joints = list(self.path_to_root(UR_TCP_LINK))
        joints.reverse()
        out = [(URDF_BASE_LINK, np.eye(4))]
        mat = np.eye(4)
        movable_index = 0
        for joint in joints:
            mat = mat @ joint.origin
            if joint.jtype in _MOVABLE:
                axis = joint.axis if joint.axis is not None else np.array([0.0, 0.0, 1.0])
                mat = mat @ make_transform(
                    _axis_angle_to_matrix(axis, q6[movable_index]), (0, 0, 0)
                )
                movable_index += 1
            out.append((joint.child, mat.copy()))
        return out


def _axis_angle_to_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    norm = np.linalg.norm(axis)
    if norm < 1e-12:
        return np.eye(3)
    axis = axis / norm
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    skew = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    return np.eye(3) + sin_a * skew + (1 - cos_a) * (skew @ skew)


def palm_link_name() -> str:
    """손바닥 링크 이름. 오른손/왼손 구분은 config가 준다."""
    return dg5f_link_prefix() + PALM_LINK_SUFFIX


# ---------------------------------------------------------------------------
# 자세 바꾸기
# ---------------------------------------------------------------------------
def palm_pose_to_ur_tcp_pose(
    palm_position: Sequence[float],
    palm_orientation: Sequence[float],
    chain: Optional[RobotChain] = None,
) -> np.ndarray:
    """손바닥 자세(`base_link` 기준) → UR가 이해하는 TCP 자세 6개.

    돌려주는 것은 `[x, y, z, rx, ry, rz]` — 앞 셋은 m, 뒤 셋은 회전벡터.
    UR 컨트롤러의 밑동(`base`) 기준이다.
    """
    chain = chain or RobotChain()
    t_baselink_palm = make_transform(quat_to_matrix(palm_orientation), palm_position)
    t_tcp_palm = chain.fixed_transform(UR_TCP_LINK, palm_link_name())
    t_baselink_tcp = t_baselink_palm @ invert_transform(t_tcp_palm)
    return baselink_transform_to_ur_pose(t_baselink_tcp, chain)


def pose6_to_transform(pose6: Sequence[float]) -> np.ndarray:
    """UR 표기 `[x, y, z, rx, ry, rz]` → 4x4."""
    pose6 = np.asarray(pose6, dtype=float)
    rotvec = pose6[3:]
    angle = float(np.linalg.norm(rotvec))
    rot = np.eye(3) if angle < 1e-12 else _axis_angle_to_matrix(rotvec / angle, angle)
    return make_transform(rot, pose6[:3])


def transform_to_pose6(mat: np.ndarray) -> np.ndarray:
    """4x4 → UR 표기 `[x, y, z, rx, ry, rz]`."""
    return np.concatenate([mat[:3, 3], matrix_to_rotvec(mat[:3, :3])])


def baselink_transform_to_ur_pose(
    t_baselink_x: np.ndarray, chain: Optional[RobotChain] = None
) -> np.ndarray:
    """`base_link` 기준 자세(4x4) → UR 밑동 기준 자세 6개."""
    chain = chain or RobotChain()
    t_baselink_urbase = chain.fixed_transform(URDF_BASE_LINK, UR_BASE_LINK)
    return transform_to_pose6(invert_transform(t_baselink_urbase) @ t_baselink_x)


def ur_tcp_pose_to_palm_transform(
    tcp_pose: Sequence[float], chain: Optional[RobotChain] = None
) -> np.ndarray:
    """위의 반대 — UR TCP 자세 6개 → `base_link` 기준 손바닥 자세(4x4). 대조용."""
    chain = chain or RobotChain()
    t_baselink_urbase = chain.fixed_transform(URDF_BASE_LINK, UR_BASE_LINK)
    t_tcp_palm = chain.fixed_transform(UR_TCP_LINK, palm_link_name())
    return t_baselink_urbase @ pose6_to_transform(tcp_pose) @ t_tcp_palm


# ---------------------------------------------------------------------------
# tool0 자세 ↔ 컨트롤러의 "활성 TCP" 자세 (2026-09-21 코드 리뷰로 추가)
# ---------------------------------------------------------------------------
# ⚠️ **"TCP"라는 말이 이 파일 안에서도 두 가지 다른 뜻으로 쓰인다.** 위
# `palm_pose_to_ur_tcp_pose()`가 돌려주는 "TCP 자세"는 실제로는 **tool0** 자세다
# (`UR_TCP_LINK = "tool0"`). 그런데 `RTDEControlInterface`의 `isPoseWithinSafetyLimits`
# / `getInverseKinematics*` / `getActualTCPPose()`는 그 이름과 달리 **컨트롤러에 지금
# 설정된 활성 TCP**(펜던트·URCap이 `set_tcp()`로 바꿀 수 있다 — DG5F 손끝 TCP 등)
# 기준으로 좌표를 해석한다. 두 "TCP"가 같은 값이라는 보장이 없다 — 다르면 우리가
# tool0 기준으로 계산한 목표를 그대로 넘겼을 때 팔이 그 차이(TCP 오프셋)만큼
# 엉뚱한 곳으로 간다. 아래 두 함수가 그 경계를 명시적으로 나눈다.
def tool0_pose_to_active_tcp_pose(
    tool0_pose6: Sequence[float], tcp_offset6: Sequence[float]
) -> np.ndarray:
    """tool0 자세 → **컨트롤러의 활성 TCP** 자세.

    `tcp_offset6`은 `RTDEControlInterface.getTCPOffset()`가 주는 값이다 — tool0
    기준으로 본 활성 TCP의 자세다. 이 관계는 `ArmMover.check_frames()`가 이미
    `getActualTCPPose() ≈ tool0_pose @ getTCPOffset()`로 실측 검증해 둔 것과 같다.

    컨트롤러의 TCP 설정(펜던트·URCap이 잡아 둔 것)을 함부로 덮어쓰지 않고, 우리가
    원하는 tool0 목표를 **지금 설정된 활성 TCP 기준 목표로 변환**해서 IK/안전검사에
    넘기는 쪽을 쓴다 — 현장 TCP 설정을 그대로 보존하기 위해서다.
    """
    t_base_tool0 = pose6_to_transform(tool0_pose6)
    t_tool0_activetcp = pose6_to_transform(tcp_offset6)
    return transform_to_pose6(t_base_tool0 @ t_tool0_activetcp)


def active_tcp_pose_to_tool0_pose(
    active_tcp_pose6: Sequence[float], tcp_offset6: Sequence[float]
) -> np.ndarray:
    """위의 반대 — 활성 TCP 자세(`getActualTCPPose()` 등) → tool0 자세.

    `getActualTCPPose()`를 우리 좌표 계산의 기준점(예: 손목 카메라 장착 좌표)으로
    되짚어야 할 때 쓴다. **활성 TCP 자세를 tool0 자세인 것처럼 그대로 쓰면 안 된다**
    — `arm/eye_in_hand.py`가 이 문제를 겪었던 것과 같은 함정이다.
    """
    t_base_activetcp = pose6_to_transform(active_tcp_pose6)
    t_tool0_activetcp = pose6_to_transform(tcp_offset6)
    return transform_to_pose6(t_base_activetcp @ invert_transform(t_tool0_activetcp))


# ---------------------------------------------------------------------------
# 팔로 보내기
# ---------------------------------------------------------------------------
@dataclass
class MoveResult:
    """계획·실행·도착 세 단계 중 어디까지 갔는지 (P1-2, 2026-09-21 재설계).

    🛑 **왜 세 단계로 나눴나.** 예전에는 `moved` 하나가 "계산상 갈 수 있다"
    (`plan()`)와 "실제로 도착했다"(`move_to()`)를 동시에 나타냈다 — `plan()`이
    실제로는 팔을 전혀 안 움직이는데도 `moved=True`를 돌려줘서, "계획 성공"과
    "실제 도착"이 호출부에서 구분되지 않았다. `A-3`(BACKLOG)가 요구하는
    "명령 전송 완료가 아니라 실제 도착을 확인한 뒤 다음 단계로" 는 이 구분이
    없으면 지킬 수 없다.

    ==============  ===================================================
    `feasible`       계산상 갈 수 있는가(안전검사+IK 통과). `plan()`도 채운다 —
                     **실제로 움직였다는 뜻이 아니다.**
    `executed`       `move_to()`가 실제로 `moveJ`/`moveL` 명령을 로봇에 보냈고,
                     RTDE가 성공(bool True)을 돌려줬으며 예외가 없었는가.
    `arrived`        실행 뒤 `RTDEReceiveInterface`로 실제 관절각을 읽어 목표와
                     대조했을 때 허용 오차(`ARRIVAL_TOLERANCE_DEG`) 안인가.
                     **다음 단계로 넘어가도 되는지는 이 값 하나만 본다.**
    `moved`          호환용 별칭 — 항상 `arrived`와 같은 값이다(과거 코드가
                     `.moved`만 보던 자리를 더 엄격한 뜻으로 자동 승격시킨다).
    ==============  ===================================================
    """

    moved: bool
    reason: str
    feasible: bool = False
    executed: bool = False
    arrived: bool = False
    #: 실제 도착 오차[deg] — 관절마다의 최대 절대오차. 확인 안 했으면 None.
    arrival_error_deg: Optional[float] = None
    #: 최종 파지 직전 자세 — **tool0** 자세(사람이 읽는 값, 활성 TCP와 무관하다).
    tcp_pose: Optional[Tuple[float, ...]] = None
    #: 최종 자세의 관절각.
    joints: Optional[Tuple[float, ...]] = None
    #: 접근 시작 지점(pre-approach) — `GraspPrePose.approach_dir`/`standoff`로 계산한
    #: 중간 경유점의 tool0 자세(P1-4, 2026-09-21). 없으면(None) 중간 경유 없이
    #: 최종 자세로 바로 간다(예: approach_dir 계약이 없는 옛 자세).
    pre_tcp_pose: Optional[Tuple[float, ...]] = None
    #: 접근 시작 지점의 관절각.
    pre_joints: Optional[Tuple[float, ...]] = None
    #: 최종 자세의 **활성 TCP** 자세 — `move_to()`가 `moveL`에 그대로 넘기는 값
    #: (플랜 때 안전검사·IK에 실제로 쓴 값과 같아야 하므로 다시 계산하지 않는다).
    active_tcp_pose: Optional[Tuple[float, ...]] = None

    def describe(self) -> str:
        if self.arrived:
            head = "도착 확인됨"
        elif self.executed:
            head = "명령은 보냈지만 도착 미확인"
        elif self.feasible:
            head = "갈 수 있음(계산만, 실행 안 함)"
        else:
            head = "움직이지 않음"
        return "{} — {}".format(head, self.reason)


def _fmt(vec, digits=4):
    return "[" + ", ".join("{:.{}f}".format(float(v), digits) for v in vec) + "]"


class ArmMover:
    """파지 직전 자세를 받아 팔을 그 자세로 옮기고 멈춘다.

    `ip`가 없으면 **연결하지 않는다**(연습 모드). 좌표 계산까지만 하고 움직이지 않는다.
    """

    def __init__(self, ip: Optional[str] = None, chain: Optional[RobotChain] = None,
                 speed_deg_per_sec: Optional[float] = None):
        self.chain = chain or RobotChain()
        self.ip = ip
        self.speed = math.radians(
            UR_MAX_DEG_PER_SEC if speed_deg_per_sec is None else speed_deg_per_sec
        )
        self._control = None
        self._receive = None
        #: 명령 연결이 막혔을 때 그 이유. 막히지 않았으면 None.
        self.control_error: Optional[str] = None

    # -- 연결 -------------------------------------------------------------
    def connect(self):
        """팔에 붙는다. **읽기는 필수, 명령은 선택**이다.

        UR e-시리즈는 펜던트에서 원격 조작(Remote Control)을 켜야만 바깥에서 명령을
        보낼 수 있다. 그게 꺼져 있어도 **관절각을 읽는 것은 된다** — 좌표 기준 확인
        (`check_frames`)은 읽기만으로 성립하므로, 명령이 막혔다고 확인까지 막지 않는다.
        """
        if self.ip is None:
            return
        import rtde_control
        import rtde_receive

        self._receive = rtde_receive.RTDEReceiveInterface(self.ip)
        try:
            self._control = rtde_control.RTDEControlInterface(self.ip)
        except Exception as exc:
            self._control = None
            self.control_error = str(exc)

    def close(self):
        for obj in (self._control, self._receive):
            if obj is not None:
                try:
                    obj.disconnect()
                except Exception:
                    pass
        self._control = self._receive = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @property
    def can_read(self) -> bool:
        """관절각을 읽을 수 있는가. 좌표 확인에는 이것만 있으면 된다."""
        return self._receive is not None

    @property
    def can_command(self) -> bool:
        """팔에 명령을 보낼 수 있는가. 펜던트의 원격 조작이 켜져 있어야 한다."""
        return self._control is not None

    @property
    def connected(self) -> bool:
        return self.can_command

    # -- 본 일 -------------------------------------------------------------
    def _solve_joints(self, tool0_pose6, tcp_offset, q_near):
        """tool0 자세 하나 → (관절각 또는 None, 실패 이유 또는 None).

        활성 TCP 변환 → 안전검사 → IK → 관절 안전검사 순서로, `plan()`이 최종
        자세와 접근 시작 지점(pre-approach) 둘 다에 **같은 절차**로 쓴다(P1-4).
        """
        active_tcp_pose = tool0_pose_to_active_tcp_pose(tool0_pose6, tcp_offset)
        if not self._control.isPoseWithinSafetyLimits(list(active_tcp_pose)):
            return None, "그 자세는 팔의 안전 범위 밖이다."
        if not self._control.getInverseKinematicsHasSolution(list(active_tcp_pose)):
            return None, "팔이 그 자세까지 닿지 못한다."
        joints = (
            self._control.getInverseKinematics(list(active_tcp_pose), q_near)
            if q_near
            else self._control.getInverseKinematics(list(active_tcp_pose))
        )
        if not joints or len(joints) != ARM_JOINT_COUNT:
            return None, "관절 각도를 풀지 못했다."
        if not self._control.isJointsWithinSafetyLimits(list(joints)):
            return None, "풀린 관절 각도가 안전 범위 밖이다."
        return tuple(joints), None

    def plan(self, pose: GraspPrePose) -> MoveResult:
        """움직이지는 않고, 갈 수 있는지와 관절 각도만 정한다.

        `pose.approach_dir`/`pose.standoff`가 있으면(항상 있다 — 계약이 요구함,
        `contracts/grasp_prepose.py` 참고) **접근 시작 지점(pre-approach)** 도 같이
        계산·검사한다(P1-4, 2026-09-21). 최종 자세만 안전하다고 중간 경로까지
        안전한 것은 아니므로, 둘 다 각각 안전검사·IK를 통과해야 "갈 수 있다"가 된다.
        """
        pose.validate()
        if not pose.accepted:
            return MoveResult(
                False,
                "자세를 정하지 못한 결과({})라 움직이지 않는다: {}".format(
                    pose.decision.value, pose.reason
                ),
            )

        tcp_pose = palm_pose_to_ur_tcp_pose(
            pose.palm_position, pose.palm_orientation, self.chain
        )
        # ⚠️ tcp_pose는 **tool0** 자세다 — 아래 컨트롤러 호출들은 tool0가 아니라
        # 컨트롤러에 지금 설정된 **활성 TCP** 기준으로 좌표를 해석한다(2026-09-21
        # 코드 리뷰로 발견). 그대로 넘기면 활성 TCP != tool0 일 때 팔이 그 차이만큼
        # 엉뚱한 곳으로 간다 — _solve_joints()가 tool0_pose_to_active_tcp_pose()로 변환한다.

        # 접근 시작 지점 = 최종 손바닥 위치에서 접근 방향으로 standoff만큼 뒤로 뺀 곳.
        # (계약: approach_dir는 "마지막 구간에서 다가갈 방향" — 그 방향으로 이동해
        # 최종 위치에 도착하므로, 시작점은 그 방향의 반대로 물러난 자리다.)
        approach_dir = np.asarray(pose.approach_dir, dtype=float)
        pre_palm_position = (
            np.asarray(pose.palm_position, dtype=float) - approach_dir * pose.standoff
        )
        pre_tcp_pose = palm_pose_to_ur_tcp_pose(
            pre_palm_position, pose.palm_orientation, self.chain
        )

        if not self.can_command:
            if self.can_read:
                return MoveResult(
                    False,
                    "팔에 명령을 보낼 수 없다 — 펜던트에서 원격 조작(Remote Control)을 "
                    "켜야 한다. UR 좌표 계산까지만 했다. ({})".format(
                        self.control_error or "이유 미상"
                    ),
                    tcp_pose=tuple(tcp_pose),
                    pre_tcp_pose=tuple(pre_tcp_pose),
                )
            return MoveResult(
                False,
                "연습 모드 — 팔에 연결하지 않았다. UR 좌표 계산까지만 했다.",
                tcp_pose=tuple(tcp_pose),
                pre_tcp_pose=tuple(pre_tcp_pose),
            )

        # 컨트롤러의 활성 TCP 오프셋(펜던트·URCap이 설정한 것)을 읽어 우리 tool0
        # 목표를 그 기준 목표로 변환한다 — 컨트롤러의 TCP 설정 자체는 건드리지 않는다.
        try:
            tcp_offset = list(self._control.getTCPOffset())
        except Exception as exc:
            return MoveResult(
                False,
                "컨트롤러의 활성 TCP 설정을 읽지 못했다 — 확실하지 않으면 움직이지 "
                "않는다: {}".format(exc),
                tcp_pose=tuple(tcp_pose),
                pre_tcp_pose=tuple(pre_tcp_pose),
            )

        q_near = self._receive.getActualQ() if self._receive is not None else None

        pre_joints, pre_reason = self._solve_joints(pre_tcp_pose, tcp_offset, q_near)
        if pre_joints is None:
            return MoveResult(
                False,
                "접근 시작 지점(pre-approach)에 못 간다: {}".format(pre_reason),
                tcp_pose=tuple(tcp_pose),
                pre_tcp_pose=tuple(pre_tcp_pose),
            )

        # 최종 자세의 IK는 접근 시작 지점의 관절해를 기준점(q_near)으로 푼다 —
        # 로봇의 지금 실제 자세가 아니라 **다음에 실제로 지나갈 점**을 기준으로 풀어야
        # moveJ(접근 시작) → moveL(최종) 구간이 다른 팔꿈치 자세로 튀지 않는다.
        final_active_tcp_pose = tool0_pose_to_active_tcp_pose(tcp_pose, tcp_offset)
        final_joints, final_reason = self._solve_joints(tcp_pose, tcp_offset, pre_joints)
        if final_joints is None:
            return MoveResult(
                False,
                final_reason,
                tcp_pose=tuple(tcp_pose),
                pre_tcp_pose=tuple(pre_tcp_pose),
                pre_joints=tuple(pre_joints),
            )
        # ⚠️ feasible=True 일 뿐 moved(=arrived)는 여전히 False다 — plan()은 계산만
        # 하고 팔을 전혀 안 움직인다. 실제로 움직였는지는 move_to()만 안다(P1-2).
        return MoveResult(
            False,
            "갈 수 있다 — 접근 시작 지점을 거쳐 최종 자세까지 (계산만, 아직 안 움직였다).",
            feasible=True,
            tcp_pose=tuple(tcp_pose),
            joints=tuple(final_joints),
            pre_tcp_pose=tuple(pre_tcp_pose),
            pre_joints=tuple(pre_joints),
            active_tcp_pose=tuple(final_active_tcp_pose),
        )

    def check_frames(self) -> Tuple[bool, str]:
        """좌표 기준이 맞는지 팔에게 직접 물어 확인한다.

        지금 팔이 있는 관절각을 읽어, **우리가 URDF로 계산한 손끝 자세**와
        **컨트롤러가 말하는 손끝 자세**를 맞대어 본다. 두 값이 다르면 좌표 기준을
        잘못 잡은 것이고, 그대로 두면 팔이 조용히 엉뚱한 곳으로 간다.

        이 확인은 가짜 팔(URSim)로도 된다.
        """
        if not self.can_read:
            return False, "팔에 연결하지 않아 확인할 수 없다."
        q6 = self._receive.getActualQ()
        ours_flange = baselink_transform_to_ur_pose(
            self.chain.forward_kinematics(q6), self.chain
        )
        if self.can_command:
            offset = list(self._control.getTCPOffset())
            offset_note = "컨트롤러에서 읽음"
        else:
            # 원격 조작이 꺼져 있으면 손끝 오프셋을 물어볼 수 없다. 0으로 두고 그 사실을
            # 적는다 — 실제로 0이 아니면 아래 차이로 드러나므로 조용히 넘어가지 않는다.
            offset = [0.0] * 6
            offset_note = "못 읽어서 0으로 가정(원격 조작 꺼짐)"
        ours = tool0_pose_to_active_tcp_pose(ours_flange, offset)
        theirs = np.asarray(self._receive.getActualTCPPose(), dtype=float)

        pos_err_mm = float(np.linalg.norm(ours[:3] - theirs[:3])) * 1000.0
        rot_err_deg = math.degrees(
            float(
                np.linalg.norm(
                    matrix_to_rotvec(
                        pose6_to_transform(ours)[:3, :3].T
                        @ pose6_to_transform(theirs)[:3, :3]
                    )
                )
            )
        )
        ok = pos_err_mm < 1.0 and rot_err_deg < 0.1
        report = "\n".join(
            [
                "지금 관절각    : {} rad".format(_fmt(q6)),
                "손끝 오프셋    : {} ({})".format(_fmt(offset), offset_note),
                "손끝으로 삼은 링크: {}".format(UR_TCP_LINK),
                "우리 계산      : {}".format(_fmt(ours)),
                "컨트롤러 계산  : {}".format(_fmt(theirs)),
                "위치 차이      : {:.3f} mm".format(pos_err_mm),
                "방향 차이      : {:.4f} deg".format(rot_err_deg),
                "판정           : {}".format(
                    "좌표 기준이 맞다" if ok else "⚠️ 좌표 기준이 어긋난다 — 움직이지 마라"
                ),
            ]
        )
        return ok, report

    def move_to(self, pose: GraspPrePose, acceleration: float = 0.5,
                max_age_sec: Optional[float] = None,
                approach_speed_mps: Optional[float] = None) -> MoveResult:
        """계산한 자세로 움직이고 **멈춘다.** 갈 수 없거나 관측이 오래됐으면 움직이기 전에 거절한다.

        `max_age_sec`를 안 주면 `.env`의 `RTAUTO_MAX_POSE_AGE_SEC`(기본 2초)를 쓴다.
        **실제 이동 직전(여기)에서만 나이를 강제한다** — `plan()`은 계산만 하고 움직이지
        않으므로 저장된 자세 분석·재현 작업을 방해하지 않게 그대로 둔다(P4).

        `plan()`이 접근 시작 지점(pre-approach)을 찾아냈으면(P1-4) 거기까지 `moveJ`로
        먼저 간 뒤, **마지막 구간만 직선으로**(`moveL`, `approach_dir` 방향) 최종
        자세까지 간다 — 끝점만 안전하다고 중간 경로까지 안전한 것은 아니므로, 접근
        구간 자체를 짧고 예측 가능한 직선으로 만든다. 찾아내지 못했으면(과거 계약이
        없는 자세 등) 예전처럼 `moveJ`로 바로 간다.
        """
        age_limit = MAX_POSE_AGE_SEC if max_age_sec is None else max_age_sec
        age = time.time() - pose.stamp_capture
        if age > age_limit:
            return MoveResult(
                False,
                "관측이 너무 오래됐다({:.2f}초 지남, 허용 {:.2f}초) — 그 사이 물체가 "
                "옮겨갔을 수 있어 움직이지 않는다.".format(age, age_limit),
            )
        # ⚠️ stamp_capture가 **미래**(age가 크게 음수)여도 위 검사는 통과한다 — 시계가
        # 안 맞거나 값이 조작됐다는 뜻이므로 이것도 "믿을 수 없는 관측"이다(2026-09-21
        # 코드 리뷰). 같은 PC 안에서 나는 시각차라면 수 ms 수준이어야 정상이므로,
        # CLOCK_SKEW_TOLERANCE_SEC(여유 있게 0.5초)를 넘는 미래 시각은 거절한다.
        if age < -CLOCK_SKEW_TOLERANCE_SEC:
            return MoveResult(
                False,
                "관측 시각이 지금보다 {:.2f}초 미래다 — 시계가 안 맞거나 시각값을 "
                "믿을 수 없어 움직이지 않는다.".format(-age),
            )

        plan = self.plan(pose)
        if not plan.feasible or plan.joints is None:
            return plan

        # ⚠️ 이 밑부터는 **실제로 로봇에 명령을 보낸다.** moveJ/moveL은 둘 다 bool을
        # 돌려준다(ur_rtde 1.6.5 확인) — 반환값을 버리면 "명령이 거부됐는데도 성공한
        # 것처럼 보이는" 상태가 된다(2026-09-21 코드 리뷰로 발견). RTDE 예외도 마찬가지로
        # 성공으로 남으면 안 된다 — 전부 여기서 막는다.
        def _fail(reason: str) -> MoveResult:
            # 실행이 중간에 끊긴 상태다 — 적극적으로 감속 정지시킨다(정상 완료된
            # blocking move 뒤에는 이미 멈춰 있으므로 이 호출이 따로 필요 없다).
            try:
                self._control.stopJ(acceleration)
            except Exception:
                pass
            return MoveResult(
                False, reason, feasible=True, executed=False,
                tcp_pose=plan.tcp_pose, joints=plan.joints,
                pre_tcp_pose=plan.pre_tcp_pose, pre_joints=plan.pre_joints,
                active_tcp_pose=plan.active_tcp_pose,
            )

        try:
            if plan.pre_joints is not None and plan.active_tcp_pose is not None:
                speed_mps = (
                    APPROACH_SPEED_MPS if approach_speed_mps is None else approach_speed_mps
                )
                if not self._control.moveJ(list(plan.pre_joints), self.speed, acceleration):
                    return _fail("접근 시작 지점으로 가는 moveJ가 실패했다(로봇이 명령을 "
                                "거부했거나 중단됐다) — moveL은 시도하지 않았다.")
                if not self._control.moveL(list(plan.active_tcp_pose), speed_mps, acceleration):
                    return _fail("접근 시작 지점까지는 갔지만, 최종 자세로 가는 moveL이 "
                                "실패했다 — 팔이 접근 시작 지점 근처에 멈춰 있을 수 있다.")
                reason = "접근 시작 지점을 거쳐 최종 자세까지 명령을 보냈다."
            else:
                if not self._control.moveJ(list(plan.joints), self.speed, acceleration):
                    return _fail("최종 자세로 가는 moveJ가 실패했다.")
                reason = "최종 자세로 명령을 보냈다."
        except Exception as exc:
            return _fail("이동 중 RTDE 예외로 중단됐다: {}".format(exc))

        # 명령이 (거부 없이) 끝났다 — 이제 **실제로 거기 도착했는지** 관절각을 다시
        # 읽어 확인한다. "성공"은 이 확인을 통과해야만 붙는다(A-3, P1-2).
        try:
            actual_q = self._receive.getActualQ() if self._receive is not None else None
        except Exception:
            actual_q = None
        if actual_q is None:
            return MoveResult(
                False,
                "명령은 보냈지만 실제 관절각을 읽지 못해 도착을 확인할 수 없다.",
                feasible=True, executed=True,
                tcp_pose=plan.tcp_pose, joints=plan.joints,
                pre_tcp_pose=plan.pre_tcp_pose, pre_joints=plan.pre_joints,
                active_tcp_pose=plan.active_tcp_pose,
            )
        err_deg = max(
            abs(math.degrees(a) - math.degrees(t)) for a, t in zip(actual_q, plan.joints)
        )
        arrived = err_deg <= ARRIVAL_TOLERANCE_DEG
        return MoveResult(
            arrived,
            (reason + " 실제 도착 확인함(최대 관절 오차 {:.3f}°).".format(err_deg))
            if arrived else
            (reason + " 그러나 실제 도착 오차 {:.3f}°가 허용치 {:.3f}°를 넘는다 — "
             "성공으로 보지 않는다.".format(err_deg, ARRIVAL_TOLERANCE_DEG)),
            feasible=True, executed=True, arrived=arrived, arrival_error_deg=err_deg,
            tcp_pose=plan.tcp_pose, joints=plan.joints,
            pre_tcp_pose=plan.pre_tcp_pose, pre_joints=plan.pre_joints,
            active_tcp_pose=plan.active_tcp_pose,
        )


# ---------------------------------------------------------------------------
# 명령줄
# ---------------------------------------------------------------------------
def _demo_pose(chain: RobotChain) -> GraspPrePose:
    """연습용 자세 하나 — 팔을 곧게 편 자세에서 손바닥을 8 cm 뒤로 뺀 지점.

    URDF로 직접 계산하므로 좌표를 사람이 적어 넣지 않는다. 팔이 반드시 닿는 자세다.
    """
    q_home = [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0]
    t_baselink_flange = chain.forward_kinematics(q_home)
    t_flange_palm = chain.fixed_transform(UR_TCP_LINK, palm_link_name())
    t_baselink_palm = t_baselink_flange @ t_flange_palm
    rot = t_baselink_palm[:3, :3]
    quat = _matrix_to_quat(rot)
    names_len = 20
    return GraspPrePose.accept(
        stamp_capture=time.time(),
        stamp_emit=time.time(),
        source=Source.GEOMETRIC,
        palm_position=tuple(t_baselink_palm[:3, 3]),
        palm_orientation=quat,
        approach_dir=(0.0, 0.0, -1.0),
        standoff=0.08,
        hand_joint_target=tuple(0.0 for _ in range(names_len)),
        confidence=1.0,
        opening_width=0.085,
    )


def _matrix_to_quat(rot: np.ndarray) -> Tuple[float, float, float, float]:
    """3x3 회전 → 쿼터니언 (w, x, y, z), 길이 1."""
    trace = float(np.trace(rot))
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (rot[2, 1] - rot[1, 2]) / s
        y = (rot[0, 2] - rot[2, 0]) / s
        z = (rot[1, 0] - rot[0, 1]) / s
    else:
        i = int(np.argmax(np.diag(rot)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + rot[i, i] - rot[j, j] - rot[k, k]) * 2
        quat = [0.0, 0.0, 0.0]
        quat[i] = 0.25 * s
        quat[j] = (rot[j, i] + rot[i, j]) / s
        quat[k] = (rot[k, i] + rot[i, k]) / s
        w = (rot[k, j] - rot[j, k]) / s
        x, y, z = quat
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    return (w / norm, x / norm, y / norm, z / norm)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="파지 직전 자세를 받아 팔을 그 자세로 옮기고 멈춘다 (잡지는 않는다)."
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pose-json", help="contracts/grasp_prepose.py가 쓴 자세 파일")
    src.add_argument("--demo", action="store_true",
                     help="연습용 자세 하나를 URDF에서 만들어 쓴다 (반드시 닿는 자세)")
    src.add_argument("--check-frames", action="store_true",
                     help="움직이지 않고, 좌표 기준이 맞는지 팔에게 직접 물어 확인한다 "
                          "(--ip 필요. 가짜 팔로도 된다)")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="UR 컨트롤박스/URSim 주소. 아예 생략하면 연결하지 않고 계산만 한다. "
                         "값 없이 --ip 만 주면 .env 의 RTAUTO_UR_IP 를 쓴다")
    ap.add_argument("--speed-deg-per-sec", type=float, default=None,
                    help="관절 속도 상한(기본: .env 의 RTAUTO_UR_MAX_DEG_PER_SEC)")
    ap.add_argument("--plan-only", action="store_true",
                    help="연결은 하되 움직이지는 않는다 — 갈 수 있는지만 본다")
    args = ap.parse_args(argv)

    chain = RobotChain()
    print("URDF          : {}".format(chain.path))
    print("팔 관절 6개   : {}".format(", ".join(chain.arm_joint_names())))
    print("손바닥 링크   : {}".format(palm_link_name()))

    ip_early = None if args.ip is None else resolve_ur_ip(args.ip)
    if args.check_frames:
        if ip_early is None:
            print("--check-frames 는 팔에 연결해야 한다. --ip 를 같이 준다.")
            return 2
        mover = ArmMover(ip=ip_early, chain=chain)
        try:
            mover.connect()
        except Exception as exc:
            print("팔에 연결하지 못했다: {}".format(exc))
            print("  가짜 팔을 먼저 띄운다: arm/run_ursim.ps1 (또는 run_ursim.sh)")
            return 2
        try:
            ok, report = mover.check_frames()
        finally:
            mover.close()
        print(report)
        return 0 if ok else 1

    if args.demo:
        pose = _demo_pose(chain)
    else:
        pose = GraspPrePose.from_json(Path(args.pose_json).read_text(encoding="utf-8"))

    print("들어온 자세   : {}".format(pose.decision.value))
    if pose.accepted:
        print("  손바닥 위치 : {} m".format(_fmt(pose.palm_position)))
        print("  손바닥 방향 : {} (w,x,y,z)".format(_fmt(pose.palm_orientation)))

    ip = None if args.ip is None else resolve_ur_ip(args.ip)
    mover = ArmMover(ip=ip, chain=chain, speed_deg_per_sec=args.speed_deg_per_sec)
    try:
        mover.connect()
    except Exception as exc:  # 연결 실패는 흔하고, 원인을 그대로 보여주는 편이 낫다
        print("팔에 연결하지 못했다: {}".format(exc))
        print("  가짜 팔을 먼저 띄운다: arm/run_ursim.ps1 (또는 run_ursim.sh)")
        return 2

    try:
        result = mover.plan(pose) if (args.plan_only or ip is None) else mover.move_to(pose)
    finally:
        mover.close()

    if result.pre_tcp_pose is not None:
        print("접근 시작 지점: {} (앞 3개 m, 뒤 3개 회전벡터) — approach_dir/standoff로 계산".format(
            _fmt(result.pre_tcp_pose)))
    if result.tcp_pose is not None:
        print("UR 좌표 자세  : {} (앞 3개 m, 뒤 3개 회전벡터)".format(_fmt(result.tcp_pose)))
    if result.joints is not None:
        print("팔 관절 목표  : {} rad".format(_fmt(result.joints)))
        print("              : {} deg".format(_fmt([math.degrees(v) for v in result.joints], 2)))
    print("결과          : {}".format(result.describe()))
    # 세 모드가 "성공"의 뜻이 다르다(P1-2, 2026-09-21):
    #   ip 없음(순수 계산)  — 연결 자체가 없어 feasible을 못 정한다. 좌표가 나왔으면 성공.
    #   --plan-only        — 연결은 했지만 실행은 안 함. IK/안전검사 통과(feasible)가 성공.
    #   실제로 움직이려던 모드 — 명령만 보내고 끝나면 안 된다. 도착 확인(arrived)까지 성공.
    if ip is None:
        ok = result.tcp_pose is not None
    elif args.plan_only:
        ok = result.feasible
    else:
        ok = result.arrived
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
