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
    ARM_HAND_URDF,
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
# 팔로 보내기
# ---------------------------------------------------------------------------
@dataclass
class MoveResult:
    """움직였는지, 안 움직였으면 왜 안 움직였는지."""

    moved: bool
    reason: str
    tcp_pose: Optional[Tuple[float, ...]] = None
    joints: Optional[Tuple[float, ...]] = None

    def describe(self) -> str:
        head = "이동함" if self.moved else "움직이지 않음"
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
    def plan(self, pose: GraspPrePose) -> MoveResult:
        """움직이지는 않고, 갈 수 있는지와 관절 각도만 정한다."""
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
        if not self.can_command:
            if self.can_read:
                return MoveResult(
                    False,
                    "팔에 명령을 보낼 수 없다 — 펜던트에서 원격 조작(Remote Control)을 "
                    "켜야 한다. UR 좌표 계산까지만 했다. ({})".format(
                        self.control_error or "이유 미상"
                    ),
                    tcp_pose=tuple(tcp_pose),
                )
            return MoveResult(
                False,
                "연습 모드 — 팔에 연결하지 않았다. UR 좌표 계산까지만 했다.",
                tcp_pose=tuple(tcp_pose),
            )

        if not self._control.isPoseWithinSafetyLimits(list(tcp_pose)):
            return MoveResult(
                False, "그 자세는 팔의 안전 범위 밖이다.", tcp_pose=tuple(tcp_pose)
            )
        if not self._control.getInverseKinematicsHasSolution(list(tcp_pose)):
            return MoveResult(
                False, "팔이 그 자세까지 닿지 못한다.", tcp_pose=tuple(tcp_pose)
            )

        q_near = self._receive.getActualQ() if self._receive is not None else None
        joints = (
            self._control.getInverseKinematics(list(tcp_pose), q_near)
            if q_near
            else self._control.getInverseKinematics(list(tcp_pose))
        )
        if not joints or len(joints) != ARM_JOINT_COUNT:
            return MoveResult(
                False, "관절 각도를 풀지 못했다.", tcp_pose=tuple(tcp_pose)
            )
        if not self._control.isJointsWithinSafetyLimits(list(joints)):
            return MoveResult(
                False,
                "풀린 관절 각도가 안전 범위 밖이다.",
                tcp_pose=tuple(tcp_pose),
                joints=tuple(joints),
            )
        return MoveResult(
            True,
            "갈 수 있다.",
            tcp_pose=tuple(tcp_pose),
            joints=tuple(joints),
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
        ours = transform_to_pose6(
            pose6_to_transform(ours_flange) @ pose6_to_transform(offset)
        )
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

    def move_to(self, pose: GraspPrePose, acceleration: float = 0.5) -> MoveResult:
        """계산한 자세로 움직이고 **멈춘다.** 갈 수 없으면 움직이기 전에 거절한다."""
        plan = self.plan(pose)
        if not plan.moved or plan.joints is None:
            return plan
        self._control.moveJ(list(plan.joints), self.speed, acceleration)
        self._control.stopJ(acceleration)
        return MoveResult(
            True, "자세까지 이동하고 멈췄다.", plan.tcp_pose, plan.joints
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

    if result.tcp_pose is not None:
        print("UR 좌표 자세  : {} (앞 3개 m, 뒤 3개 회전벡터)".format(_fmt(result.tcp_pose)))
    if result.joints is not None:
        print("팔 관절 목표  : {} rad".format(_fmt(result.joints)))
        print("              : {} deg".format(_fmt([math.degrees(v) for v in result.joints], 2)))
    print("결과          : {}".format(result.describe()))
    return 0 if (result.moved or ip is None or args.plan_only) else 1


if __name__ == "__main__":
    raise SystemExit(main())
