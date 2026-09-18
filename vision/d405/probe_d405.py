# -*- coding: utf-8 -*-
"""D405 를 **실제로 재서** 짐작값을 바꾼다 (계획서 Q1).

왜 지금 할 수 있나
------------------
카메라는 **USB 로 PC 에 직접** 붙는다. 못 온 것은 팔·그리퍼를 묶을 **랜 스위치**이고,
그건 카메라와 상관없다. 손목에 달지 않아도 **카메라 자체의 성질**은 다 잴 수 있다.

무엇을 바꾸나 — 지금 설정값은 전부 짐작이다
--------------------------------------------
`config/rtauto_config.py` 의 D405 값들은 **제조사 공개 사양**이고 "실측 아님" 이라고
적혀 있다. 이 스크립트가 그걸 실제 숫자로 바꾼다.

=====================  ==========================  =====================
설정 키                 지금 (제조사 사양)            이 스크립트가 재는 것
=====================  ==========================  =====================
`D405_FOV_H_DEG`        87                          실제 시야각(가로)
`D405_FOV_V_DEG`        58                          실제 시야각(세로)
`D405_NEAR_M`           0.07                        실제로 값이 나오기 시작하는 거리
`D405_FAR_M`            0.50                        값이 쓸 만한 거리의 상한
`D405_FX/FY/CX/CY`      0 (시야각에서 계산)           **이 개체의** 초점거리·중심
=====================  ==========================  =====================

시야각과 초점거리는 같은 것을 다르게 적은 값이다. **카메라가 알려 주는 초점거리가
정본**이고, 시야각은 거기서 계산해 적는다 — 개체마다 다르기 때문이다.

무엇을 하나
-----------
1. `--info`   : 카메라가 알려 주는 초점거리·중심·시야각을 읽어 출력한다 (물체 필요 없음)
2. `--depth`  : 지금 보이는 장면의 깊이 품질을 잰다 — 몇 %의 화소에 값이 있나,
                거리가 얼마나 흔들리나. **물체를 놓고 거리를 바꿔 가며** 여러 번 돌린다
3. `--cloud`  : 점 덩어리를 뽑아 파일로 남긴다. 시뮬레이터가 만든 것과 견주기 위한 것
4. `--env`    : 위에서 잰 값을 `.env` 에 넣을 형태로 출력한다

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/probe_d405.py --info

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python vision/d405/probe_d405.py --info

깊이 품질을 잴 때 (물체를 카메라 앞 10 cm 에 놓고):

    python vision/d405/probe_d405.py --depth --note "종이컵 10cm"

⚠️ 카메라를 손목에 달지 않은 상태로도 위는 전부 된다. **달아야만 되는 것**은
   "카메라가 팔 끝 어디에 붙었나"(`D405_MOUNT_*`, BACKLOG D-6/D-7)뿐이다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 맞춰 볼 해상도 후보. D405 는 깊이 1280x720 까지 된다. 앞에서부터 되는 것을 쓴다.
PREFERRED = ((1280, 720, 30), (848, 480, 30), (640, 480, 30))

#: 값을 재기 전에 버리는 장면 수. 자동 노출이 자리 잡을 시간을 준다.
WARMUP_FRAMES = 30


def open_pipe(rs, width=None, height=None, fps=30):
    """깊이 스트림을 연다. 원하는 크기가 안 되면 되는 것으로 내려간다."""
    tries = [(width, height, fps)] if width else list(PREFERRED)
    last = None
    for w, h, f in tries:
        pipe = rs.pipeline()
        cfgs = rs.config()
        cfgs.enable_stream(rs.stream.depth, w, h, rs.format.z16, f)
        try:
            profile = pipe.start(cfgs)
            return pipe, profile, (w, h, f)
        except Exception as e:      # 이 크기를 이 카메라가 안 하면 다음 후보로
            last = e
            try:
                pipe.stop()
            except Exception:
                pass
    raise RuntimeError("깊이 스트림을 열지 못했다: {}".format(last))


def read_intrinsics(rs, profile):
    """카메라가 알려 주는 초점거리·중심. **이것이 정본이다** — 개체마다 다르다."""
    stream = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    i = stream.get_intrinsics()
    fov_h = 2.0 * math.degrees(math.atan2(i.width / 2.0, i.fx))
    fov_v = 2.0 * math.degrees(math.atan2(i.height / 2.0, i.fy))
    return dict(width=i.width, height=i.height, fx=i.fx, fy=i.fy, ppx=i.ppx, ppy=i.ppy,
                model=str(i.model), coeffs=list(i.coeffs), fov_h_deg=fov_h, fov_v_deg=fov_v)


def grab_depth(rs, pipe, frames=WARMUP_FRAMES + 10, keep=10):
    """장면을 여러 장 받아 **뒤쪽 몇 장**만 쓴다 (앞은 자동 조정 중이라 버린다)."""
    out = []
    for i in range(frames):
        fs = pipe.wait_for_frames()
        d = fs.get_depth_frame()
        if not d:
            continue
        if i >= frames - keep:
            out.append(np.asanyarray(d.get_data()))
    return np.stack(out) if out else None


def depth_report(stack, scale, near, far, note=""):
    """깊이 품질 — **값이 있는 화소 비율**과 **같은 자리가 얼마나 흔들리는가**."""
    d = stack.astype(np.float64) * scale          # z16 원값 -> m
    valid = d > 0
    frac = float(valid.mean())

    # 같은 화소를 여러 장에 걸쳐 본 흔들림(표준편차). 값이 늘 있는 화소만.
    always = valid.all(axis=0)
    jitter_mm = float("nan")
    if always.any():
        jitter_mm = float(np.median(d[:, always].std(axis=0)) * 1000.0)

    mid = d[:, always] if always.any() else d[valid][None, :]
    dist = float(np.median(mid)) if mid.size else float("nan")
    in_band = float(((d >= near) & (d <= far)).mean())

    return dict(note=note, valid_frac=frac, in_band_frac=in_band,
                median_dist_m=dist, jitter_mm=jitter_mm,
                min_m=float(d[valid].min()) if valid.any() else float("nan"),
                max_m=float(d[valid].max()) if valid.any() else float("nan"))


def to_points(depth_m, intr):
    """깊이 사진 → 카메라 기준 점 덩어리(m)."""
    h, w = depth_m.shape
    ys, xs = np.nonzero(depth_m > 0)
    z = depth_m[ys, xs]
    return np.stack([(xs - intr["ppx"]) * z / intr["fx"],
                     (ys - intr["ppy"]) * z / intr["fy"], z], axis=1)


def main() -> int:
    ap = argparse.ArgumentParser(description="D405 실측 (계획서 Q1)")
    ap.add_argument("--info", action="store_true", help="초점거리·중심·시야각을 읽는다")
    ap.add_argument("--depth", action="store_true", help="깊이 품질을 잰다")
    ap.add_argument("--cloud", action="store_true", help="점 덩어리를 파일로 남긴다")
    ap.add_argument("--env", action="store_true", help=".env 에 넣을 형태로 출력")
    ap.add_argument("--note", default="", help="지금 무엇을 찍고 있는지 (기록용)")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not (args.info or args.depth or args.cloud or args.env):
        print(__doc__)
        return 2

    try:
        import pyrealsense2 as rs
    except ImportError:
        print("pyrealsense2 가 없다 — `pip install pyrealsense2` 후 다시.")
        return 2

    devs = list(rs.context().query_devices())
    if not devs:
        print("카메라가 안 보인다. USB 를 다시 꽂고, 다른 프로그램(RealSense Viewer 등)이")
        print("카메라를 쥐고 있지 않은지 확인할 것.")
        return 2
    dev = devs[0]
    print("=== D405 실측 ===")
    print("장치   : {} / 시리얼 {} / 펌웨어 {}".format(
        dev.get_info(rs.camera_info.name),
        dev.get_info(rs.camera_info.serial_number),
        dev.get_info(rs.camera_info.firmware_version)))

    pipe, profile, mode = open_pipe(rs, args.width, args.height)
    try:
        intr = read_intrinsics(rs, profile)
        scale = profile.get_device().first_depth_sensor().get_depth_scale()
        print("해상도 : {}x{} @ {}Hz   (깊이 단위 {:.6f} m)".format(*mode, scale))
        print()

        print("--- 카메라가 알려 주는 값 (**이것이 정본**) ---")
        print("  초점거리 fx {:.2f}  fy {:.2f}".format(intr["fx"], intr["fy"]))
        print("  화면 중심 cx {:.2f}  cy {:.2f}".format(intr["ppx"], intr["ppy"]))
        print("  시야각   가로 {:.2f}도  세로 {:.2f}도".format(
            intr["fov_h_deg"], intr["fov_v_deg"]))
        print("  왜곡 모델 {}  계수 {}".format(
            intr["model"], [round(c, 5) for c in intr["coeffs"]]))
        print()
        print("--- 지금 설정값과 비교 (제조사 사양) ---")
        for label, got, have in (
                ("가로 시야각(도)", intr["fov_h_deg"], cfg.D405_FOV_H_DEG),
                ("세로 시야각(도)", intr["fov_v_deg"], cfg.D405_FOV_V_DEG)):
            diff = got - have
            mark = "차이 없음" if abs(diff) < 0.5 else "**{:+.1f} 차이**".format(diff)
            print("  {:<16s} 실측 {:6.2f}  설정 {:6.2f}   {}".format(label, got, have, mark))
        print()

        result = {"made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "serial": dev.get_info(rs.camera_info.serial_number),
                  "mode": list(mode), "depth_scale": scale, "intrinsics": intr}

        if args.depth or args.cloud:
            print("--- 깊이 재는 중 (약 1.5초) ---")
            stack = grab_depth(rs, pipe)
            if stack is None:
                print("깊이 장면을 못 받았다.")
                return 2
            rep = depth_report(stack, scale, cfg.D405_NEAR_M, cfg.D405_FAR_M, args.note)
            result["depth"] = rep
            print("  적은 것 : {}".format(args.note or "(없음)"))
            print("  값이 있는 화소      : {:.1%}".format(rep["valid_frac"]))
            print("  설정한 거리 범위 안  : {:.1%}  ({:.2f}~{:.2f} m 기준)".format(
                rep["in_band_frac"], cfg.D405_NEAR_M, cfg.D405_FAR_M))
            print("  가운데 거리(중앙값)  : {:.3f} m".format(rep["median_dist_m"]))
            print("  같은 자리 흔들림     : {:.2f} mm".format(rep["jitter_mm"]))
            print("  보이는 거리 범위     : {:.3f} ~ {:.3f} m".format(
                rep["min_m"], rep["max_m"]))
            print()

            if args.cloud:
                depth_m = stack[-1].astype(np.float64) * scale
                pts = to_points(depth_m, intr)
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stem = args.out or "cloud_{}".format(time.strftime("%Y%m%d_%H%M%S"))
                path = RESULTS_DIR / "{}.npz".format(stem)
                np.savez_compressed(path, points=pts.astype(np.float32),
                                    note=np.asarray(args.note),
                                    intrinsics=np.asarray(json.dumps(intr)))
                print("  점 {}개 저장: {}".format(len(pts), path))
                near_far = pts[(pts[:, 2] >= cfg.D405_NEAR_M) & (pts[:, 2] <= cfg.D405_FAR_M)]
                print("  그중 설정 거리 범위 안: {}개".format(len(near_far)))
                print()

        if args.env:
            print("--- .env 에 넣을 것 (이 개체의 실측값) ---")
            print("RTAUTO_D405_FX={:.3f}".format(intr["fx"]))
            print("RTAUTO_D405_FY={:.3f}".format(intr["fy"]))
            print("RTAUTO_D405_CX={:.3f}".format(intr["ppx"]))
            print("RTAUTO_D405_CY={:.3f}".format(intr["ppy"]))
            print("RTAUTO_D405_FOV_H_DEG={:.2f}".format(intr["fov_h_deg"]))
            print("RTAUTO_D405_FOV_V_DEG={:.2f}".format(intr["fov_v_deg"]))
            print()
            print("⚠️ 초점거리·중심은 **해상도마다 다르다**({}x{} 기준). 다른 해상도를".format(
                intr["width"], intr["height"]))
            print("   쓸 거면 그 해상도로 다시 재라.")
            print()

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        log = RESULTS_DIR / "probe_{}.json".format(time.strftime("%Y%m%d_%H%M%S"))
        log.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("기록: {}".format(log))
    finally:
        pipe.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
