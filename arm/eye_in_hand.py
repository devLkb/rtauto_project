# -*- coding: utf-8 -*-
"""카메라가 본 것을 **로봇 좌표로 옮긴다** (D-6).

왜 이게 없으면 아무것도 안 되나
-------------------------------
손목 카메라는 **"내 앞 20 cm 에 물체가 있다"** 까지만 안다. 그런데 팔한테 보내야 하는
것은 **"로봇 바닥 기준으로 어디"** 다. 이 둘을 잇는 것이 두 가지다:

1. **카메라가 팔 끝의 어디에 어떤 방향으로 붙었나** — 한 번 재면 안 변한다(고정 장착)
2. **지금 팔 끝이 어디에 있나** — 팔이 매 순간 알려 준다

    로봇 기준 물체 위치  =  (지금 팔 끝 자세)  x  (카메라 장착 자세)  x  (카메라가 본 위치)
    P_base              =   T_base_tool       x   T_tool_camera    x   P_camera

- `P_camera`     : `depth_to_points_cam()` — D405 깊이 사진에서 뽑은 점(카메라 기준, m)
- `T_tool_camera`: `CameraMount.matrix()` — **파일 `config/d405_tool_camera.json`** 이 정본
  (2026-09-23 전에는 `.env` 의 `RTAUTO_D405_MOUNT_*` 였다)
- `T_base_tool`  : `pose_to_matrix(tool0_pose_from_joints(q6))` — 팔 관절각에서 **매번** 계산
  (`read_tool0_pose()` 가 팔에서 읽어 온다)
- `P_base`       : `points_to_base()` / 세 단계를 다 보려면 `points_camera_tcp_base()`

🛑 CALIBRATION_REQUIRED — 아직 안 쟀다
--------------------------------------
2026-09-23 현재 장착값 파일의 `status` 는 `CALIBRATION_REQUIRED` 이고 값은 **자리 표시용**
(회전 없음·이동 없음)이다. 이 상태로도 배관은 돌지만(원칙 2 — 새 머신에서 설치 직후
바로 실행 가능해야 한다) **결과를 믿으면 안 된다.** `--check` 가 이 상태를 눈에 띄게
알려 주고, `points_to_base()` 는 경고를 함께 돌려주며, **실물 자동 이동은 막힌다**
(`require_validated_mount_for_physical_move()`). 남의 로봇·다른 카메라의 장착값을
실측값처럼 넣지 않는다.

재는 법(요약): 체커보드 같은 표식을 책상에 고정해 두고, 팔을 **여러 자세로** 옮기며
그때마다 ① 팔이 알려 주는 팔 끝 자세와 ② 카메라가 본 표식 위치를 함께 기록한 뒤,
둘이 아귀가 맞는 장착값을 푼다. 자세가 많을수록·서로 다를수록 정확해진다.
자세한 절차는 카메라가 도착한 뒤 `docs/FESTA_PREGRASP_PLAN.md` Q2 에서 확정한다.

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트) — 지금 설정값 확인:

    vision/.vision/Scripts/Activate.ps1
    python arm/eye_in_hand.py --check

터미널 1 (PowerShell, 리포 루트) — 가짜 팔(URSim)에 붙여 실제 변환까지:

    vision/.vision/Scripts/Activate.ps1
    python arm/eye_in_hand.py --check --ip

시험: `python -m unittest arm.tests.test_eye_in_hand -v`
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config"))
# tool0_pose_from_joints()가 arm.prepose_to_joints를 "arm 패키지" 경로로 지역
# 임포트한다(원칙 1 — URDF 기구학 정본을 여기서 다시 만들지 않는다) — 그러려면
# 리포 루트 자체가 sys.path에 있어야 한다(위 config/ 추가와는 별개).
sys.path.insert(0, str(REPO_ROOT))

import rtauto_config as cfg  # noqa: E402  (장착값의 유일한 출처 — 원칙 1)


def rpy_to_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """roll-pitch-yaw(도) → 3x3 회전. 축 순서는 **Z(yaw) → Y(pitch) → X(roll)** 이다.

    ⚠️ 순서를 바꾸면 **같은 숫자가 다른 방향을 뜻한다.** 장착값을 재는 쪽과 쓰는 쪽이
    같은 순서를 써야 하므로 여기 한 군데에만 적어 두고 다른 곳은 이 함수를 부른다.
    """
    r, p, y = (math.radians(v) for v in (roll_deg, pitch_deg, yaw_deg))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def rotvec_to_matrix(rotvec: Sequence[float]) -> np.ndarray:
    """회전벡터(길이=각도 라디안) → 3x3. UR 이 팔 끝 자세를 이 형식으로 알려 준다."""
    v = np.asarray(rotvec, dtype=float)
    theta = float(np.linalg.norm(v))
    if theta < 1e-12:
        return np.eye(3)
    k = v / theta
    kx, ky, kz = k
    K = np.array([[0.0, -kz, ky], [kz, 0.0, -kx], [-ky, kx, 0.0]])
    return np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * (K @ K)


def quat_to_matrix(quat_xyzw: Sequence[float]) -> np.ndarray:
    """쿼터니언 (x, y, z, w) → 3x3. **순서가 x, y, z, w 다**(ROS 와 같다, w 가 맨 뒤).

    길이가 1 에서 조금(0.1 % 이내) 벗어나면 맞춰 쓰고, 그보다 많이 벗어나면 **옮겨 적다
    틀린 값**으로 보고 멈춘다.
    """
    q = np.asarray(quat_xyzw, dtype=float).reshape(-1)
    if q.shape != (4,):
        raise ValueError("쿼터니언은 숫자 4개(x, y, z, w)여야 한다 (지금 {}개)".format(q.size))
    n = float(np.linalg.norm(q))
    if abs(n - 1.0) > 1e-3:
        raise ValueError("쿼터니언 길이가 1이 아니다({:.6f}) — 옮겨 적다 틀렸을 수 있다".format(n))
    x, y, z, w = q / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def matrix_to_rpy_deg(r: np.ndarray) -> Tuple[float, float, float]:
    """3x3 → (roll, pitch, yaw) 도. `rpy_to_matrix()` 의 역 — 화면 표시용."""
    r = np.asarray(r, dtype=float)
    pitch = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    if abs(r[2, 0]) < 1.0 - 1e-9:
        roll = math.atan2(r[2, 1], r[2, 2])
        yaw = math.atan2(r[1, 0], r[0, 0])
    else:  # pitch ±90도 — roll 과 yaw 가 구분되지 않으므로 roll 을 0 으로 둔다
        roll = 0.0
        yaw = math.atan2(-r[0, 1], r[1, 1])
    return tuple(math.degrees(v) for v in (roll, pitch, yaw))


def pose_to_matrix(pose6: Sequence[float]) -> np.ndarray:
    """UR 의 팔 끝 자세 6칸 (x, y, z, rx, ry, rz) → 4x4."""
    out = np.eye(4)
    out[:3, :3] = rotvec_to_matrix(pose6[3:6])
    out[:3, 3] = np.asarray(pose6[:3], dtype=float)
    return out


#: `CameraMount.parent_link`으로 지금 계산이 지원하는 값. `camera_to_base()`가
#: tool0 자세를 직접 요구하므로(아래 함수 docstring 참고) 다른 링크는 아직 지원하지
#: 않는다 — 조용히 틀리느니 명시적으로 거절한다(2026-09-21 코드 리뷰).
SUPPORTED_MOUNT_PARENTS = ("tool0",)

#: 장착값 파일의 `status` 로 쓸 수 있는 값 — 뒤로 갈수록 믿을 만하다.
#: - CALIBRATION_REQUIRED: 아직 안 쟀다(자리 표시용 값). 좌표 계산은 되지만 믿으면 안 된다
#: - MEASURED  : 자로 재거나 도면에서 읽었다. 좌표는 쓸 만하지만 실물 자동 이동은 아직 막힌다
#: - VALIDATED : 실물 손-눈 맞추기(BACKLOG D-7)로 검증을 끝냈다. **사람이 직접** 적는다
MOUNT_STATUS_REQUIRED = "CALIBRATION_REQUIRED"
MOUNT_STATUS_MEASURED = "MEASURED"
MOUNT_STATUS_VALIDATED = "VALIDATED"
MOUNT_STATUSES = (MOUNT_STATUS_REQUIRED, MOUNT_STATUS_MEASURED, MOUNT_STATUS_VALIDATED)


class MountConfigError(ValueError):
    """장착값 파일이 틀렸거나 앞뒤가 안 맞을 때 — 조용히 넘어가지 않고 여기서 멈춘다."""


def mount_file_path() -> Path:
    """장착값 파일 경로 (`RTAUTO_D405_TOOL_CAMERA_FILE`, 리포 상대 또는 절대)."""
    path = Path(cfg.D405_TOOL_CAMERA_FILE)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class CameraMount:
    """카메라가 팔 끝의 어디에 어떤 방향으로 붙었나.

    `measured` 가 False 면 **아직 안 잰 값**이다(파일 status `CALIBRATION_REQUIRED`)
    — 돌아는 가지만 믿으면 안 된다.

    🛑 **`measured`와 `validated`는 다른 질문이다** (P1-5, 2026-09-21 코드 리뷰).
    `measured`(status `MEASURED`)는 "사람이 값을 재서 넣었다"일 뿐이다 — 자를 잘못
    읽어도 그렇게 된다. `validated`(status `VALIDATED`)는 "hand-eye 검증(Q2/Q3)을
    실물로 실제로 끝내고 사람이 직접 파일에 적었다"는 뜻이다. **좌표 계산·시각화는 `measured`만 있어도
    동작하지만, 실물 자동 이동은 `validated`가 있어야만 연다**
    (`require_validated_mount_for_physical_move` 참고).
    """

    parent_link: str
    xyz_m: Tuple[float, float, float]
    rpy_deg: Tuple[float, float, float]
    measured: bool
    validated: bool = False
    #: 파일에 쿼터니언으로 적었으면 그 값 (x, y, z, w). 있으면 `rpy_deg` 대신 이것을 쓴다
    #: (`rpy_deg` 는 표시용으로 이 값에서 계산해 채운다).
    quat_xyzw: Optional[Tuple[float, float, float, float]] = None
    source: str = ""
    measured_on: Optional[str] = None
    file_path: Optional[str] = None

    def __post_init__(self):
        # "검증됐다" 인데 "쟀다" 가 아니면 앞뒤가 안 맞는다 — 관문을 잘못 여는 조합을 막는다.
        if self.validated and not self.measured:
            raise MountConfigError("validated=True 인데 measured=False — 앞뒤가 안 맞는다")

    @property
    def status(self) -> str:
        if self.validated:
            return MOUNT_STATUS_VALIDATED
        return MOUNT_STATUS_MEASURED if self.measured else MOUNT_STATUS_REQUIRED

    @classmethod
    def from_config(cls, path: Optional[Path] = None) -> "CameraMount":
        """장착값 파일(`config/d405_tool_camera.json`)을 읽고 **앞뒤가 맞는지 검사한다.**

        틀리면 `MountConfigError` 로 멈춘다 — 틀린 장착값으로 조용히 계산하느니 멈추는 게 낫다.
        """
        legacy = cfg.legacy_d405_mount_env_keys_set()
        if legacy:
            raise MountConfigError(
                "옛 장착값 .env 키가 남아 있다: {}. 2026-09-23 부터 장착값은 파일 {} 하나에만 "
                "적는다 — .env(또는 환경변수)에서 이 줄들을 지우고 값은 파일로 옮길 것."
                .format(", ".join(legacy), mount_file_path()))
        path = Path(path) if path is not None else mount_file_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise MountConfigError(
                "장착값 파일이 없다: {} — 리포에 들어 있어야 하는 파일이다(git 으로 되살릴 것). "
                "경로를 바꿨다면 RTAUTO_D405_TOOL_CAMERA_FILE 을 확인.".format(path)) from None
        except json.JSONDecodeError as exc:
            raise MountConfigError("{}: JSON 형식이 틀렸다 — {}".format(path, exc)) from None
        return cls.from_dict(data, file_path=str(path))

    @classmethod
    def from_dict(cls, data: dict, file_path: Optional[str] = None) -> "CameraMount":
        where = file_path or "장착값"

        def bad(msg):
            return MountConfigError("{}: {}".format(where, msg))

        def num(v):
            # true/false 가 1/0 으로, "0.03" 같은 글자가 숫자로 조용히 바뀌지 않게 막는다.
            # NaN/Infinity(JSON 이 받아 준다)는 좌표 전체를 망가뜨리므로 여기서 멈춘다.
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise bad("숫자가 아니거나 유한하지 않다: {!r}".format(v))
            return float(v)

        if not isinstance(data, dict):
            raise bad("맨 바깥은 {...} 객체여야 한다")
        status = data.get("status")
        if status not in MOUNT_STATUSES:
            raise bad("status 는 {} 중 하나여야 한다 (지금 {!r})".format(
                "/".join(MOUNT_STATUSES), status))
        try:
            t = data["translation_m"]
            xyz = (num(t["x"]), num(t["y"]), num(t["z"]))
            rot = data["rotation"]
            kind = rot["type"]
            if kind == "rpy_deg":
                quat = None
                rpy = (num(rot["roll"]), num(rot["pitch"]), num(rot["yaw"]))
            elif kind == "quaternion":
                quat = (num(rot["x"]), num(rot["y"]), num(rot["z"]), num(rot["w"]))
                try:
                    rpy = matrix_to_rpy_deg(quat_to_matrix(quat))
                except ValueError as exc:
                    raise bad(str(exc)) from None
            else:
                raise bad("rotation.type 은 rpy_deg 또는 quaternion (지금 {!r})".format(kind))
        except (KeyError, TypeError) as exc:
            raise bad("항목이 빠졌거나 숫자가 아니다: {}".format(exc)) from None

        parent = data.get("parent_frame")
        if parent not in SUPPORTED_MOUNT_PARENTS:
            raise bad("parent_frame 은 {} 중 하나여야 한다 (지금 {!r})".format(
                ", ".join(SUPPORTED_MOUNT_PARENTS), parent))
        mount = cls(parent_link=parent, xyz_m=xyz, rpy_deg=rpy,
                    measured=status != MOUNT_STATUS_REQUIRED,
                    validated=status == MOUNT_STATUS_VALIDATED,
                    quat_xyzw=quat, source=str(data.get("source") or ""),
                    measured_on=data.get("measured_on"), file_path=file_path)

        if status != MOUNT_STATUS_REQUIRED:
            # "쟀다" 고 적었으면 그 증거가 있어야 한다.
            # ① 회전도 이동도 없는 장착은 현실에 없다 — 카메라가 팔 끝 원점에 부피 없이
            #    붙을 수는 없다. 자리 표시용 값을 그대로 둔 채 status 만 바꾼 것으로 본다.
            if np.allclose(mount.matrix(), np.eye(4), atol=1e-9):
                raise bad("status 가 {} 인데 값이 자리 표시용(회전·이동 없음) 그대로다".format(status))
            # ② 출처·날짜 — 남의 로봇 값이나 어림값이 실측값처럼 섞이는 것을 막는다.
            if not mount.source or mount.source.upper().startswith("PLACEHOLDER"):
                raise bad("status 가 {} 이면 source 에 값의 출처를 적어야 한다".format(status))
            try:
                datetime.date.fromisoformat(mount.measured_on)
            except (TypeError, ValueError):
                raise bad("status 가 {} 이면 measured_on 에 잰 날짜를 2026-09-23 형식으로 "
                          "적어야 한다 (지금 {!r})".format(status, mount.measured_on)) from None
            # ③ 손목 브라켓 위 카메라가 팔 끝에서 이보다 멀 수는 없다 — 단위(mm/m) 착오 등.
            offset = float(np.linalg.norm(xyz))
            if offset > cfg.D405_MOUNT_MAX_OFFSET_M:
                raise bad("카메라가 팔 끝에서 {:.3f} m 떨어졌다고 적혀 있다 — 상한 {:.2f} m "
                          "(RTAUTO_D405_MOUNT_MAX_OFFSET_M). 단위(mm↔m)를 확인.".format(
                              offset, cfg.D405_MOUNT_MAX_OFFSET_M))
        return mount

    def rotation_matrix(self) -> np.ndarray:
        if self.quat_xyzw is not None:
            return quat_to_matrix(self.quat_xyzw)
        return rpy_to_matrix(*self.rpy_deg)

    def matrix(self) -> np.ndarray:
        """팔 끝(tool0) 기준 카메라 자세 4x4 = T_tool_camera."""
        out = np.eye(4)
        out[:3, :3] = self.rotation_matrix()
        out[:3, 3] = np.asarray(self.xyz_m, dtype=float)
        return out

    def warning(self) -> Optional[str]:
        if self.measured:
            return None
        return ("🛑 CALIBRATION_REQUIRED — 손목 카메라 장착값을 **아직 안 쟀다**(자리 표시용 "
                "값). 계산은 돌지만 결과는 실제와 다르다. 브라켓을 달고 잰 뒤 {} 의 "
                "translation_m / rotation / status / source / measured_on 을 채울 것."
                .format(self.file_path or "config/d405_tool_camera.json"))


class MountNotValidatedError(RuntimeError):
    """손목 카메라 장착값이 실물로 검증되지 않은 채로 자동 이동에 쓰이려 할 때."""


def require_validated_mount_for_physical_move(
    mount: Optional[CameraMount] = None,
    ip: Optional[str] = None,
    allow_unvalidated_on_sim: bool = False,
) -> CameraMount:
    """**실물 자동 이동** 경로가 D405 좌표를 쓰기 전 반드시 통과해야 하는 관문
    (P1-5, 2026-09-21 코드 리뷰).

    좌표 계산·시각화·디버깅(`--check`, 시험)에서는 미검증 mount도 허용한다 —
    `camera_to_base()`/`points_to_base()`는 그대로 쓰면 된다. 하지만 **로봇을
    실제로 움직이는 경로**(D405 → GraspPrePose → `ArmMover.move_to()`, 아직 구현
    전)는 이 함수를 먼저 불러야 한다. `mount.validated`가 아니면 조용히 넘어가지
    않고 예외를 낸다 — hand-eye 검증(BACKLOG Q2/Q3)이 끝나 사람이 장착값 파일
    (`config/d405_tool_camera.json`)의 `status` 를 `VALIDATED` 로 직접 바꾸기 전까지는
    실물 자동 이동을 열지 않는다는 정책을 코드로 강제한다.

    **가짜 팔에서의 예외** (2026-09-22 사용자 결정): `allow_unvalidated_on_sim=True`
    이고 `ip`가 config의 `UR_SIM_IPS`(기본 127.0.0.1/localhost)에 있으면 통과시킨다.
    가짜 팔에는 부딪힐 물건도 다칠 사람도 없으므로, 장착값을 재기 전에 움직임
    경로를 확인하는 것이 막는 것보다 낫다. **둘 중 하나라도 빠지면 막는다** —
    모르는 주소는 실물로 본다.
    """
    mount = mount or CameraMount.from_config()
    if not mount.validated:
        # 🛑 **가짜 팔(URSim)에서만 열리는 예외** (2026-09-22 사용자 결정).
        # 장착값을 아직 안 쟀을 때 실물은 그대로 막되, 가짜 팔에서는 움직임 경로
        # (moveJ → moveL → 도착 확인)를 확인할 수 있어야 하기 때문이다. 열리려면
        # **두 가지가 동시에** 성립해야 한다:
        #   ① 사람이 명시적으로 허용을 켰다(allow_unvalidated_on_sim)
        #   ② 그 주소가 가짜 팔이다(config의 UR_SIM_IPS)
        # 둘 중 하나라도 빠지면 예전처럼 막는다 — 특히 ②가 없으면 이 예외는
        # 실물에서 아무 의미가 없다(모르는 주소는 실물로 본다).
        if allow_unvalidated_on_sim and cfg.is_sim_arm(ip):
            return mount
        raise MountNotValidatedError(
            "손목 카메라 장착값이 아직 실물로 검증되지 않았다"
            "(status {}) — 실물 자동 이동에는 쓸 수 없다. "
            "hand-eye 검증(BACKLOG Q2/Q3, docs/FESTA_PREGRASP_PLAN.md §7-2) 후 "
            "사람이 직접 {} 의 status 를 VALIDATED 로 바꿔야 한다. ".format(
                mount.status, mount.file_path or "config/d405_tool_camera.json") +
            "좌표 계산·시각화만 필요하면 "
            "camera_to_base()/points_to_base()를 그대로 쓸 것 — 이 함수는 실물 "
            "이동 경로 전용이다."
            + ("\n\n(허용을 켰지만 주소 '{}'가 가짜 팔 목록(RTAUTO_UR_SIM_IPS)에 "
               "없다 — 모르는 주소는 실물로 보고 막는다.)".format(ip)
               if allow_unvalidated_on_sim else "")
        )
    return mount


def camera_to_base(tool0_pose6: Sequence[float],
                   mount: Optional[CameraMount] = None) -> np.ndarray:
    """**카메라 기준 → 로봇 바닥 기준** 변환 4x4.

    `tool0_pose6` 는 **tool0** 자세(x, y, z, rx, ry, rz)여야 한다 — `mount.parent_link`
    가 `"tool0"` 이기 때문이다(장착값을 그 기준으로 쟀다는 뜻).

    🛑 **`RTDEReceiveInterface.getActualTCPPose()`를 그대로 넣지 마라 (2026-09-21
    코드 리뷰로 발견한 실제 버그).** 그 값은 tool0가 아니라 **컨트롤러에 지금 설정된
    활성 TCP**(DG5F 손끝 TCP 등일 수 있다) 자세다. 둘이 다르면 카메라 좌표가 활성
    TCP 오프셋만큼 조용히 어긋난다. 관절각(`getActualQ()`)에서 직접 계산하려면
    `tool0_pose_from_joints()`를 쓴다 — 활성 TCP 설정이 뭐든 상관없다.
    """
    mount = mount or CameraMount.from_config()
    if mount.parent_link not in SUPPORTED_MOUNT_PARENTS:
        raise ValueError(
            "카메라 장착 기준 링크 '{}'는 아직 지원하지 않는다(지원: {}) — "
            "장착값 파일의 parent_frame을 확인하라. 조용히 틀린 계산을 하느니 "
            "여기서 멈춘다.".format(mount.parent_link, ", ".join(SUPPORTED_MOUNT_PARENTS))
        )
    return pose_to_matrix(tool0_pose6) @ mount.matrix()


def points_to_base(points_cam, tool0_pose6, mount=None):
    """카메라가 본 점들(카메라 기준, m)을 **로봇 바닥 기준**으로 옮긴다.

    `tool0_pose6` 에 대한 주의사항은 `camera_to_base()` 참고 — 활성 TCP 자세를
    그대로 넣으면 안 된다.

    돌려주는 것: `(옮긴 점들, 경고 문구 또는 None)`. 경고를 **일부러 함께 돌려준다** —
    안 잰 장착값으로 나온 좌표가 조용히 쓰이면 안 되기 때문이다.
    """
    mount = mount or CameraMount.from_config()
    pts = np.asarray(points_cam, dtype=float).reshape(-1, 3)
    t = camera_to_base(tool0_pose6, mount)
    moved = pts @ t[:3, :3].T + t[:3, 3]
    return moved, mount.warning()


def points_to_tcp(points_cam, mount=None):
    """카메라가 본 점들을 **팔 끝(tool0) 기준**으로만 옮긴다 — 중간 단계.

    `points_to_base()`가 한 번에 하는 일의 **앞쪽 절반**이다. 왜 따로 뺐나:
    좌표가 틀렸을 때 **어느 단계에서 틀렸는지** 봐야 고칠 수 있기 때문이다
    (카메라 장착값이 틀린 것인지, 팔 자세가 틀린 것인지).
    """
    mount = mount or CameraMount.from_config()
    pts = np.asarray(points_cam, dtype=float).reshape(-1, 3)
    t = mount.matrix()
    return pts @ t[:3, :3].T + t[:3, 3]


def points_camera_tcp_base(points_cam, tool0_pose6, mount=None):
    """카메라 기준 점들을 **세 단계 전부** 돌려준다 — 로그로 확인하려는 것.

    돌려주는 것: `(카메라 기준, 팔 끝 기준, 로봇 밑동 기준, 경고 또는 None)`.

    화면에 이렇게 찍으라고 만든 것이다::

        Camera XYZ : [...]
        TCP XYZ    : [...]
        Base XYZ   : [...]

    한 함수 안에서 뒤섞어 계산하면 틀렸을 때 어디가 틀렸는지 알 수 없다.
    `tool0_pose6`에 대한 주의사항은 `camera_to_base()` 참고 — 활성 TCP 자세를
    그대로 넣으면 안 된다.
    """
    mount = mount or CameraMount.from_config()
    pts = np.asarray(points_cam, dtype=float).reshape(-1, 3)
    in_tcp = points_to_tcp(pts, mount)
    in_base, warn = points_to_base(pts, tool0_pose6, mount)
    return pts, in_tcp, in_base, warn


def tool0_pose_from_joints(q6: Sequence[float]) -> Tuple[float, float, float, float, float, float]:
    """팔 관절각(rad) 6개로 **tool0** 자세를 직접 계산한다 — 활성 TCP 설정과 무관하다.

    `RTDEReceiveInterface.getActualTCPPose()`는 컨트롤러에 지금 설정된 활성 TCP
    기준이라 카메라 장착값(tool0 기준)과 섞어 쓰면 안 된다(위 `camera_to_base()`
    경고 참고). 관절각에서 직접 순기구학으로 계산하면 활성 TCP가 뭐든 상관없다 —
    URDF가 좌표계의 유일한 정본이라는 이 리포의 원칙과도 맞는다.

    `getActualQ()`만 있으면 되고 컨트롤 연결(Remote Control)은 필요 없다.
    """
    # arm.prepose_to_joints가 URDF 기구학의 정본을 이미 갖고 있다 — 여기서 다시
    # 만들지 않는다(원칙 1). 무거운 top-level 의존을 피하려고 지역 임포트로 둔다.
    from arm.prepose_to_joints import RobotChain, baselink_transform_to_ur_pose

    chain = RobotChain()
    pose = baselink_transform_to_ur_pose(chain.forward_kinematics(q6), chain)
    return tuple(float(v) for v in pose)


def read_tool0_pose(ip: str):
    """팔에서 지금 관절각을 읽어 **T_base_tool 의 재료**(tool0 자세 6칸)를 돌려준다.

    돌려주는 것: `(tool0 자세, 관절각 6개, 컨트롤러 활성 TCP 자세 — 참고용)`.
    읽기 연결(`rtde_receive`)만 쓰므로 Remote Control 이 아니어도 된다. 팔이 움직이면
    값이 바뀌므로 **카메라 사진을 찍은 그 순간마다** 다시 부른다.
    """
    import rtde_receive  # 팔 없이 도는 시험이 ur_rtde 없이도 돌게 지역 임포트

    recv = rtde_receive.RTDEReceiveInterface(ip)
    try:
        active_tcp_pose = list(recv.getActualTCPPose())
        q6 = list(recv.getActualQ())
    finally:
        recv.disconnect()
    return tool0_pose_from_joints(q6), q6, active_tcp_pose


def intrinsics(width: int, height: int):
    """초점거리·중심 (fx, fy, cx, cy). 설정에 실측값이 있으면 그것을, 없으면 시야각에서 계산.

    ⚠️ 시야각에서 계산한 값은 **제조사 공개 사양 기준**이라 개체 차이가 안 들어 있다.
    실물에서는 RealSense SDK 가 알려 주는 값을 `.env` 에 넣어 쓴다.

    ⚠️ 실측값은 **잰 해상도**(`D405_CALIB_WIDTH/HEIGHT`)에서만 맞으므로, 다른 크기로
    물어보면 **그 비율만큼 환산해서** 돌려준다.
    """
    if cfg.D405_FX > 0 and cfg.D405_FY > 0:
        # ⚠️ **잰 해상도에서만 맞는 값이다.** 다른 크기로 물어보면 그 비율만큼 환산한다 —
        #    안 그러면 640x480 으로 물었는데 1280x720 값이 그대로 나가 **2배 틀린다**
        #    (2026-09-18 에 시험이 잡은 버그). 사진을 그냥 줄인 경우 이 환산이 맞다.
        sx = width / float(cfg.D405_CALIB_WIDTH)
        sy = height / float(cfg.D405_CALIB_HEIGHT)
        cx = cfg.D405_CX * sx if cfg.D405_CX > 0 else width / 2.0
        cy = cfg.D405_CY * sy if cfg.D405_CY > 0 else height / 2.0
        return cfg.D405_FX * sx, cfg.D405_FY * sy, cx, cy, True
    fx = width / (2.0 * math.tan(math.radians(cfg.D405_FOV_H_DEG) / 2.0))
    fy = height / (2.0 * math.tan(math.radians(cfg.D405_FOV_V_DEG) / 2.0))
    return fx, fy, width / 2.0, height / 2.0, False


def depth_to_points_cam(depth_m, width=None, height=None, near=None, far=None):
    """깊이 사진 → **카메라 기준** 점 덩어리(m).

    너무 가깝거나 먼 화소는 버린다(`D405_NEAR_M` ~ `D405_FAR_M`) — D405 가 그 밖에서는
    못 재기 때문이다.
    """
    depth = np.asarray(depth_m, dtype=float)
    if depth.ndim != 2:
        raise ValueError("깊이 사진은 2차원이어야 한다 (지금 {})".format(depth.shape))
    h, w = depth.shape
    if width and height and (w, h) != (width, height):
        raise ValueError("사진 크기가 안 맞는다: {}x{} vs {}x{}".format(w, h, width, height))
    fx, fy, cx, cy, _ = intrinsics(w, h)
    near = cfg.D405_NEAR_M if near is None else near
    far = cfg.D405_FAR_M if far is None else far

    ys, xs = np.nonzero(np.isfinite(depth) & (depth >= near) & (depth <= far))
    z = depth[ys, xs]
    return np.stack([(xs - cx) * z / fx, (ys - cy) * z / fy, z], axis=1)


def _check(ip: Optional[str]) -> int:
    mount = CameraMount.from_config()
    print("=== 손목 카메라 장착값 (D-6) ===")
    print("파일      : {}".format(mount.file_path))
    print("상태      : {}{}".format(mount.status, "" if mount.measured else "  ← 아직 안 쟀다"))
    print("출처      : {}  (잰 날짜: {})".format(mount.source or "-", mount.measured_on or "-"))
    print("붙은 링크 : {}".format(mount.parent_link))
    print("위치      : ({:+.4f}, {:+.4f}, {:+.4f}) m".format(*mount.xyz_m))
    print("방향      : ({:+.2f}, {:+.2f}, {:+.2f}) 도 (Z→Y→X 순서)".format(*mount.rpy_deg))
    if mount.quat_xyzw is not None:
        print("            (파일에는 쿼터니언 x,y,z,w = {:+.5f}, {:+.5f}, {:+.5f}, {:+.5f})".format(
            *mount.quat_xyzw))
    fx, fy, cx, cy, real = intrinsics(cfg.D405_SYNTH_WIDTH, cfg.D405_SYNTH_HEIGHT)
    print("카메라 내부: fx {:.1f} fy {:.1f} cx {:.1f} cy {:.1f}  ({})".format(
        fx, fy, cx, cy, "실측값" if real else "시야각에서 계산 — 제조사 사양"))
    print()

    warn = mount.warning()
    if warn:
        print(warn)
        print()
    else:
        print("장착값이 채워져 있다.")
        print()

    if mount.validated:
        print("✅ 실물로 검증됨(status VALIDATED) — 실물 자동 이동에 쓸 수 있다.")
    else:
        print("🛑 실물로 아직 검증 안 됨(status {}) — 실물 자동 이동은 막힌다. "
              "hand-eye 검증(BACKLOG Q2/Q3) 후 사람이 직접 파일의 status 를 "
              "VALIDATED 로 바꿔야 한다.".format(mount.status))
    print()

    if ip is None:
        print("팔에 붙여 확인하려면 --ip 를 준다 (가짜 팔 URSim 도 된다).")
        return 0

    target = cfg.resolve_ur_ip(ip)
    print("팔에 연결: {}".format(target))
    try:
        tool0_pose, _q6, active_tcp_pose = read_tool0_pose(target)
    except ImportError:
        print("ur_rtde 가 없다 — `pip install ur_rtde` 후 다시.")
        return 2
    print("지금 팔 끝(tool0) 자세      : ({:+.4f}, {:+.4f}, {:+.4f}) m — 카메라 계산은 이 값을 쓴다".format(
        *tool0_pose[:3]))
    print("지금 컨트롤러 활성 TCP 자세 : ({:+.4f}, {:+.4f}, {:+.4f}) m — getActualTCPPose(), 참고용".format(
        *active_tcp_pose[:3]))
    gap_mm = math.dist(tool0_pose[:3], active_tcp_pose[:3]) * 1000.0
    if gap_mm > 1.0:
        print("  ⚠️ 활성 TCP가 tool0에서 {:.1f} mm 떨어져 있다 — 컨트롤러에 손끝 TCP가 "
              "따로 설정돼 있다는 뜻이다(정상일 수 있다, DG5F 등). 카메라 계산에는 "
              "위 tool0 자세만 쓴다.".format(gap_mm))

    # 카메라 바로 앞 10 cm 에 점이 하나 있다고 치고 로봇 좌표로 옮겨 본다
    moved, _ = points_to_base([[0.0, 0.0, 0.10]], tool0_pose, mount)
    print("카메라 앞 10 cm 의 점 → 로봇 기준 ({:+.4f}, {:+.4f}, {:+.4f}) m".format(
        *moved[0]))
    if not mount.measured:
        print("  ⚠️ CALIBRATION_REQUIRED — 장착값이 자리 표시용이라 이 좌표는 "
              "**팔 끝(tool0) 원점 바로 앞**을 가리킬 뿐이다.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="손목 카메라 장착값 확인·변환 (D-6)")
    ap.add_argument("--check", action="store_true", help="지금 설정값을 보여 준다")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="팔 IP. 값 없이 주면 .env 의 RTAUTO_UR_IP (기본 URSim)")
    args = ap.parse_args()
    if not args.check and args.ip is None:
        print(__doc__)
        return 2
    return _check(args.ip)


if __name__ == "__main__":
    raise SystemExit(main())
