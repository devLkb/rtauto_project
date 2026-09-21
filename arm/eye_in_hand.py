# -*- coding: utf-8 -*-
"""카메라가 본 것을 **로봇 좌표로 옮긴다** (D-6).

왜 이게 없으면 아무것도 안 되나
-------------------------------
손목 카메라는 **"내 앞 20 cm 에 물체가 있다"** 까지만 안다. 그런데 팔한테 보내야 하는
것은 **"로봇 바닥 기준으로 어디"** 다. 이 둘을 잇는 것이 두 가지다:

1. **카메라가 팔 끝의 어디에 어떤 방향으로 붙었나** — 한 번 재면 안 변한다(고정 장착)
2. **지금 팔 끝이 어디에 있나** — 팔이 매 순간 알려 준다

    로봇 기준 물체 위치  =  (지금 팔 끝 자세)  x  (카메라 장착 자세)  x  (카메라가 본 위치)

1번이 `config/rtauto_config.py` 의 `D405_MOUNT_*` 다. **2026-09-18 까지 이 항목이 리포에
아예 없었다** — `docs/EXTERNAL_GRASP_POLICY_SURVEY.md` §9 가 "이게 먼저다" 라고 지목한
것이 이것이다.

🛑 아직 안 쟀다
---------------
기본값은 전부 0이고, 그것은 **"아직 안 쟀다"** 는 뜻이다. 0인 채로도 배관은 돌지만
(원칙 2 — 새 머신에서 설치 직후 바로 실행 가능해야 한다) **결과를 믿으면 안 된다.**
`--check` 가 이 상태를 눈에 띄게 알려 주고, `points_to_base()` 는 경고를 함께 돌려준다.

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


@dataclass(frozen=True)
class CameraMount:
    """카메라가 팔 끝의 어디에 어떤 방향으로 붙었나.

    `measured` 가 False 면 **아직 안 잰 값**이다 — 돌아는 가지만 믿으면 안 된다.

    🛑 **`measured`와 `validated`는 다른 질문이다** (P1-5, 2026-09-21 코드 리뷰).
    `measured`는 "0이 아닌 값이 들어있다"만 본다 — 사람이 어림값을 넣어도 True가
    된다. `validated`는 "hand-eye 검증(Q2/Q3)을 실물로 실제로 끝내고 사람이 직접
    `.env`에서 1로 바꿨다"는 뜻이다. **좌표 계산·시각화는 `measured`만 있어도
    동작하지만, 실물 자동 이동은 `validated`가 있어야만 연다**
    (`require_validated_mount_for_physical_move` 참고).
    """

    parent_link: str
    xyz_m: Tuple[float, float, float]
    rpy_deg: Tuple[float, float, float]
    measured: bool
    validated: bool = False

    @classmethod
    def from_config(cls) -> "CameraMount":
        return cls(parent_link=cfg.D405_MOUNT_PARENT,
                   xyz_m=tuple(cfg.D405_MOUNT_XYZ_M),
                   rpy_deg=tuple(cfg.D405_MOUNT_RPY_DEG),
                   measured=cfg.d405_mount_measured(),
                   validated=cfg.d405_mount_validated())

    def matrix(self) -> np.ndarray:
        """팔 끝 기준 카메라 자세 4x4."""
        out = np.eye(4)
        out[:3, :3] = rpy_to_matrix(*self.rpy_deg)
        out[:3, 3] = np.asarray(self.xyz_m, dtype=float)
        return out

    def warning(self) -> Optional[str]:
        if self.measured:
            return None
        return ("🛑 손목 카메라 장착값을 **아직 안 쟀다**(전부 0). 계산은 돌지만 "
                "결과는 실제와 다르다. .env 의 RTAUTO_D405_MOUNT_XYZ_M / "
                "RTAUTO_D405_MOUNT_RPY_DEG 를 실측값으로 채울 것.")


class MountNotValidatedError(RuntimeError):
    """손목 카메라 장착값이 실물로 검증되지 않은 채로 자동 이동에 쓰이려 할 때."""


def require_validated_mount_for_physical_move(
    mount: Optional[CameraMount] = None,
) -> CameraMount:
    """**실물 자동 이동** 경로가 D405 좌표를 쓰기 전 반드시 통과해야 하는 관문
    (P1-5, 2026-09-21 코드 리뷰).

    좌표 계산·시각화·디버깅(`--check`, 시험)에서는 미검증 mount도 허용한다 —
    `camera_to_base()`/`points_to_base()`는 그대로 쓰면 된다. 하지만 **로봇을
    실제로 움직이는 경로**(D405 → GraspPrePose → `ArmMover.move_to()`, 아직 구현
    전)는 이 함수를 먼저 불러야 한다. `mount.validated`가 아니면 조용히 넘어가지
    않고 예외를 낸다 — hand-eye 검증(BACKLOG Q2/Q3)이 끝나 사람이 `.env`의
    `RTAUTO_D405_MOUNT_VALIDATED=1`로 직접 바꾸기 전까지는 실물 자동 이동을 열지
    않는다는 정책을 코드로 강제한다.
    """
    mount = mount or CameraMount.from_config()
    if not mount.validated:
        raise MountNotValidatedError(
            "손목 카메라 장착값이 아직 실물로 검증되지 않았다"
            "(RTAUTO_D405_MOUNT_VALIDATED=0) — 실물 자동 이동에는 쓸 수 없다. "
            "hand-eye 검증(BACKLOG Q2/Q3, docs/FESTA_PREGRASP_PLAN.md §7-2) 후 "
            "사람이 직접 .env에서 1로 바꿔야 한다. 좌표 계산·시각화만 필요하면 "
            "camera_to_base()/points_to_base()를 그대로 쓸 것 — 이 함수는 실물 "
            "이동 경로 전용이다."
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
            "RTAUTO_D405_MOUNT_PARENT를 확인하라. 조용히 틀린 계산을 하느니 "
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
    print("붙은 링크 : {}".format(mount.parent_link))
    print("위치      : ({:+.4f}, {:+.4f}, {:+.4f}) m".format(*mount.xyz_m))
    print("방향      : ({:+.2f}, {:+.2f}, {:+.2f}) 도 (Z→Y→X 순서)".format(*mount.rpy_deg))
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
        print("✅ 실물로 검증됨(RTAUTO_D405_MOUNT_VALIDATED=1) — 실물 자동 이동에 쓸 수 있다.")
    else:
        print("🛑 실물로 아직 검증 안 됨(RTAUTO_D405_MOUNT_VALIDATED=0) — 값이 채워져 "
              "있어도 실물 자동 이동에는 못 쓴다. hand-eye 검증(BACKLOG Q2/Q3) 후 "
              "사람이 직접 1로 바꿔야 한다.")
    print()

    if ip is None:
        print("팔에 붙여 확인하려면 --ip 를 준다 (가짜 팔 URSim 도 된다).")
        return 0

    try:
        import rtde_receive
    except ImportError:
        print("ur_rtde 가 없다 — `pip install ur_rtde` 후 다시.")
        return 2

    target = cfg.resolve_ur_ip(ip)
    print("팔에 연결: {}".format(target))
    recv = rtde_receive.RTDEReceiveInterface(target)
    try:
        active_tcp_pose = list(recv.getActualTCPPose())
        q6 = list(recv.getActualQ())
    finally:
        recv.disconnect()
    tool0_pose = tool0_pose_from_joints(q6)
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
        print("  ⚠️ 장착값이 0이라 이 좌표는 **팔 끝 바로 앞**을 가리킬 뿐이다.")
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
