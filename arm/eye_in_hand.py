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


@dataclass(frozen=True)
class CameraMount:
    """카메라가 팔 끝의 어디에 어떤 방향으로 붙었나.

    `measured` 가 False 면 **아직 안 잰 값**이다 — 돌아는 가지만 믿으면 안 된다.
    """

    parent_link: str
    xyz_m: Tuple[float, float, float]
    rpy_deg: Tuple[float, float, float]
    measured: bool

    @classmethod
    def from_config(cls) -> "CameraMount":
        return cls(parent_link=cfg.D405_MOUNT_PARENT,
                   xyz_m=tuple(cfg.D405_MOUNT_XYZ_M),
                   rpy_deg=tuple(cfg.D405_MOUNT_RPY_DEG),
                   measured=cfg.d405_mount_measured())

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


def camera_to_base(tcp_pose6: Sequence[float],
                   mount: Optional[CameraMount] = None) -> np.ndarray:
    """**카메라 기준 → 로봇 바닥 기준** 변환 4x4.

    `tcp_pose6` 는 팔이 알려 주는 지금 팔 끝 자세 (x, y, z, rx, ry, rz).
    """
    mount = mount or CameraMount.from_config()
    return pose_to_matrix(tcp_pose6) @ mount.matrix()


def points_to_base(points_cam, tcp_pose6, mount=None):
    """카메라가 본 점들(카메라 기준, m)을 **로봇 바닥 기준**으로 옮긴다.

    돌려주는 것: `(옮긴 점들, 경고 문구 또는 None)`. 경고를 **일부러 함께 돌려준다** —
    안 잰 장착값으로 나온 좌표가 조용히 쓰이면 안 되기 때문이다.
    """
    mount = mount or CameraMount.from_config()
    pts = np.asarray(points_cam, dtype=float).reshape(-1, 3)
    t = camera_to_base(tcp_pose6, mount)
    moved = pts @ t[:3, :3].T + t[:3, 3]
    return moved, mount.warning()


def intrinsics(width: int, height: int):
    """초점거리·중심 (fx, fy, cx, cy). 설정에 실측값이 있으면 그것을, 없으면 시야각에서 계산.

    ⚠️ 시야각에서 계산한 값은 **제조사 공개 사양 기준**이라 개체 차이가 안 들어 있다.
    실물에서는 RealSense SDK 가 알려 주는 값을 `.env` 에 넣어 쓴다.
    """
    if cfg.D405_FX > 0 and cfg.D405_FY > 0:
        cx = cfg.D405_CX if cfg.D405_CX > 0 else width / 2.0
        cy = cfg.D405_CY if cfg.D405_CY > 0 else height / 2.0
        return cfg.D405_FX, cfg.D405_FY, cx, cy, True
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
        pose = list(recv.getActualTCPPose())
    finally:
        recv.disconnect()
    print("지금 팔 끝 자세: ({:+.4f}, {:+.4f}, {:+.4f}) m".format(*pose[:3]))

    # 카메라 바로 앞 10 cm 에 점이 하나 있다고 치고 로봇 좌표로 옮겨 본다
    moved, _ = points_to_base([[0.0, 0.0, 0.10]], pose, mount)
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
