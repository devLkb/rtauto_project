# -*- coding: utf-8 -*-
"""팔이 지금 어떤 자세인지 창에 그려서 보여준다.

왜 필요한가
-----------
UR 로봇은 **원격 조작(Remote Control)을 켜야만** 바깥에서 명령을 받는다. 그런데 그걸
켜면 **펜던트 화면이 잠겨서 팔이 움직이는 것을 볼 수 없다.** 명령을 보내는 것과 눈으로
보는 것을 동시에 할 수 없는 셈이다.

이 창은 그 사이를 메운다 — **관절 각도를 읽는 것은 원격 조작 중에도 되므로**, 읽어서
따로 그린다. 실물 팔에도 그대로 쓸 수 있다.

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트, 팔 보기):

    python arm/watch_arm.py --ip

`--ip` 를 값 없이 주면 `.env` 의 `RTAUTO_UR_IP`(기본 127.0.0.1 = 로컬 가짜 팔)를 쓴다.
창이 하나 뜨고, 팔이 움직이면 그림도 같이 움직인다. 끌 때는 창을 닫거나 `Ctrl+C`.

**이 창은 보기만 한다. 팔에 아무 명령도 보내지 않는다.**

터미널 2 에서 `python arm/prepose_to_joints.py --demo --ip` 를 돌리면 이 창에서
팔이 움직이는 것이 보인다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.rtauto_config import resolve_ur_ip  # noqa: E402
from arm.prepose_to_joints import (  # noqa: E402
    ArmKinematicsError,
    RobotChain,
    UR_TCP_LINK,
    palm_link_name,
)

#: 그림에서 마디를 잇는 선으로 쓸 링크들. 중간에 자세만 바뀌고 자리가 같은 링크가
#: 여럿이라 그대로 다 이으면 점이 겹친다 — 자리가 실제로 움직이는 것만 고른다.
_MIN_SEGMENT_M = 1e-4


def _skeleton_points(chain: RobotChain, q6, include_palm: bool = True):
    """관절각 → 그릴 점들의 좌표 (밑동 → 손끝 → 손바닥)."""
    frames = chain.frames_along_arm(q6)
    points = []
    for _, mat in frames:
        xyz = mat[:3, 3]
        if not points or float(np.linalg.norm(xyz - points[-1])) > _MIN_SEGMENT_M:
            points.append(xyz)
    if include_palm:
        t_tcp = frames[-1][1]
        t_palm = t_tcp @ chain.fixed_transform(UR_TCP_LINK, palm_link_name())
        points.append(t_palm[:3, 3])
    return np.array(points)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="팔이 지금 어떤 자세인지 창에 그린다 (보기만 한다, 명령하지 않는다)."
    )
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="UR 컨트롤박스/URSim 주소. 값 없이 --ip 만 주면 .env 의 "
                         "RTAUTO_UR_IP 를 쓴다 (기본 127.0.0.1 = 로컬 가짜 팔)")
    ap.add_argument("--hz", type=float, default=20.0, help="화면을 새로 그리는 횟수(초당)")
    ap.add_argument("--reach", type=float, default=1.1,
                    help="그림에 보여줄 범위(m). UR16e 는 팔이 0.9 m 뻗는다")
    args = ap.parse_args(argv)

    if args.ip is None:
        print("팔 주소가 필요하다. 예: python arm/watch_arm.py --ip")
        return 2
    ip = resolve_ur_ip(args.ip)

    try:
        chain = RobotChain()
    except ArmKinematicsError as exc:
        print(exc)
        return 2

    import rtde_receive

    try:
        receive = rtde_receive.RTDEReceiveInterface(ip)
    except Exception as exc:
        print("팔에 연결하지 못했다: {}".format(exc))
        print("  가짜 팔을 먼저 띄운다: arm/run_ursim.ps1 -Detach (또는 run_ursim.sh --detach)")
        return 2

    import matplotlib.pyplot as plt

    print("팔 보기 창을 띄웠다 ({}). 창을 닫거나 Ctrl+C 로 끝낸다.".format(ip))
    print("이 창은 보기만 한다 — 팔에 명령을 보내지 않는다.")

    fig = plt.figure(figsize=(7, 6))
    fig.canvas.manager.set_window_title("UR16e + DG-5F — 지금 자세 ({})".format(ip))
    ax = fig.add_subplot(111, projection="3d")
    reach = float(args.reach)

    def draw(points, q6):
        ax.clear()
        ax.plot(points[:, 0], points[:, 1], points[:, 2],
                "-o", linewidth=4, markersize=6, color="#1f77b4")
        # 손바닥은 따로 크게 — 파지 직전 자세에서 중요한 건 여기다
        ax.scatter(points[-1, 0], points[-1, 1], points[-1, 2],
                   s=140, color="#d62728", depthshade=False, label="손바닥")
        ax.scatter([0], [0], [0], s=90, color="#2ca02c",
                   depthshade=False, label="로봇 밑동")
        # 바닥 격자
        grid = np.linspace(-reach, reach, 9)
        for g in grid:
            ax.plot([-reach, reach], [g, g], [0, 0], color="0.85", linewidth=0.6)
            ax.plot([g, g], [-reach, reach], [0, 0], color="0.85", linewidth=0.6)
        ax.set_xlim(-reach, reach)
        ax.set_ylim(-reach, reach)
        ax.set_zlim(0, 2 * reach)
        ax.set_box_aspect((1, 1, 1))
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_zlabel("z (m)")
        palm = points[-1]
        ax.set_title(
            "손바닥 위치  x={:.3f}  y={:.3f}  z={:.3f} (m)\n"
            "관절각  [{}] (도)".format(
                palm[0], palm[1], palm[2],
                ", ".join("{:.0f}".format(np.degrees(v)) for v in q6),
            ),
            fontsize=10,
        )
        ax.legend(loc="upper left", fontsize=9)

    try:
        plt.ion()
        plt.show()
        pause = max(1.0 / max(args.hz, 1.0), 0.01)
        while plt.fignum_exists(fig.number):
            q6 = receive.getActualQ()
            draw(_skeleton_points(chain, q6), q6)
            plt.pause(pause)
    except KeyboardInterrupt:
        print("\n끝냈다.")
    finally:
        try:
            receive.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
