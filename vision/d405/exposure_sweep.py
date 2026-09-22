# -*- coding: utf-8 -*-
"""D405 **노출(exposure) 훑기** — 흰 종이컵 문제가 빛 때문인지 무늬 때문인지 가른다.

왜 필요한가 (BACKLOG D-10)
--------------------------
흰 종이컵에서 거리값이 안 나오는 이유가 두 가지 후보로 갈려 있었다
(`claudeDocs/daily/2026-09-18.md` 세션 18, 바깥 조언자 진단):

    A. 빛/노출이 안 맞아서인가?
    B. 표면에 무늬가 없어 스테레오 매칭 자체가 어려운 것인가?

이 둘은 처방이 **정반대**다 — A 면 노출·조명을 조절하면 되고, B 면 노출을 아무리
바꿔도 그 자리는 계속 빈다(무늬 투사 같은 다른 수단이 필요하다). 지금까지 노출 설정을
**한 번도 코드에서 건드린 적이 없어서** 이 둘을 구분하지 못했다.

무엇을 하나
-----------
1. 게인을 고정하고(기본 16 — D405 가 허용하는 최솟값), 자동 노출을 끈다.
2. 노출을 여러 값으로 훑으며(기본 1000~30000 µs) 각 값마다:
   - 카메라가 자리 잡을 시간(SETTLE_FRAMES)을 버린다
   - **RAW**(다듬기 없음)와 **FILTERED**(d405_stream 의 기본 다듬기) 를 **나란히** 잰다
     — 둘을 섞으면 "카메라가 실제로 잰 것"과 "후처리가 만든 것"을 구분할 수 없다
     (2026-09-18 세션 18 조언자 지적)
   - 색 사진 + 좌우 원본(적외선) 영상을 저장한다 — 흰 컵이 **타서 뭉개졌는지**
     (포화) 아니면 **무늬가 원래 없는지**를 눈으로 봐야 갈린다
   - ROI(관심 영역)를 주면 그 안에서도 같은 통계를 낸다
3. 끝나면 원래 카메라 설정(자동 노출 등)을 되돌린다.
4. 전부 CSV 로 남는다 — `exposure_us,gain,frame_index,valid_depth_ratio,median_depth_m,
   depth_std_m,point_count,timestamp` (+ ROI 를 줬으면 `roi_*` 열도).

🛑 **범위 밖 노출값은 조용히 자르지 않는다.** 이 카메라가 실제로 허용하는
   최소/최대를 SDK 에서 읽어 먼저 보여주고, 범위 밖 값은 **건너뛰며 왜 건너뛰는지
   알린다** — clamp 해서 "요청한 값과 다른 값을 잰 줄 모르고 넘어가는 일"을 막는다.

돌리는 법 (터미널 1, PowerShell, 리포 루트)
--------------------------------------------

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/exposure_sweep.py --object "paper_cup"

특정 노출만, ROI 를 주고(색 사진 픽셀 기준, `x,y,w,h`):

    python vision/d405/exposure_sweep.py --exposures 2000,8000,30000 --roi 260,150,120,150

ROI 픽셀 좌표를 모르면 먼저 색 사진만 한 장 찍어서 확인한다:

    python vision/d405/exposure_sweep.py --preview-only
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402
import d405_stream  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results" / "exposure_sweep"

#: 계획서 기본값(D-10). 전부 D405 허용 범위(1~165000µs) 안이지만, 다른 개체는
#: 범위가 다를 수 있어 **실행 시 다시 확인한다**(clamp 하지 않고 알린다).
DEFAULT_EXPOSURES_US = (1000, 2000, 4000, 8000, 16000, 30000)

#: 게인 고정값. D405 의 게인 하한이 16 이라 그걸 기본으로 쓴다(계획서 지정값과 같다).
DEFAULT_GAIN = 16

#: 노출을 바꾼 뒤 자동 조정(있다면)과 센서 파이프라인이 자리 잡을 때까지 버리는 장면 수.
SETTLE_FRAMES = 20

#: 노출 하나당 실제로 재는 장면 수.
MEASURE_FRAMES = 10


def _die(msg):
    print("🛑 {}".format(msg))
    raise SystemExit(2)


def _parse_roi(text):
    """`--roi x,y,w,h` (색 사진 픽셀 기준) → `(x, y, w, h)` 또는 `None`."""
    if not text:
        return None
    try:
        x, y, w, h = (int(v) for v in text.split(","))
    except Exception:
        _die("--roi 는 'x,y,w,h' 형식이어야 한다 (정수 4개, 콤마로 구분): {!r}".format(text))
    if w <= 0 or h <= 0:
        _die("--roi 의 너비/높이는 0보다 커야 한다: {!r}".format(text))
    return x, y, w, h


def _scale_roi(roi, from_shape, to_shape):
    """ROI 를 **다른 해상도의 사진**으로 옮긴다 (예: 색 사진 → 줄인 깊이 사진).

    `from_shape`/`to_shape` 는 `(세로, 가로)`.
    """
    x, y, w, h = roi
    sy = to_shape[0] / float(from_shape[0])
    sx = to_shape[1] / float(from_shape[1])
    return (int(round(x * sx)), int(round(y * sy)),
            max(1, int(round(w * sx))), max(1, int(round(h * sy))))


def _roi_stats(depth_m, roi):
    """ROI 안의 값 있는 화소 비율 / 중앙값 / 흔들림(표준편차)."""
    x, y, w, h = roi
    H, W = depth_m.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return dict(valid_ratio=float("nan"), median_m=float("nan"), std_m=float("nan"),
                   point_count=0)
    patch = depth_m[y0:y1, x0:x1]
    valid = patch > 0
    n = int(valid.sum())
    return dict(
        valid_ratio=float(valid.mean()),
        median_m=float(np.median(patch[valid])) if n else float("nan"),
        std_m=float(np.std(patch[valid])) if n else float("nan"),
        point_count=n)


def _frame_stats(depth_m):
    valid = depth_m > 0
    n = int(valid.sum())
    return dict(
        valid_ratio=float(valid.mean()),
        median_m=float(np.median(depth_m[valid])) if n else float("nan"),
        std_m=float(np.std(depth_m[valid])) if n else float("nan"),
        point_count=n)


def read_exposure_gain_range(sensor, rs):
    """이 카메라가 **실제로** 허용하는 노출·게인 범위. 제조사 사양이 아니라 SDK 실측."""
    exp_r = sensor.get_option_range(rs.option.exposure)
    gain_r = sensor.get_option_range(rs.option.gain)
    return dict(exposure_min=exp_r.min, exposure_max=exp_r.max, exposure_step=exp_r.step,
               gain_min=gain_r.min, gain_max=gain_r.max, gain_step=gain_r.step)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="D405 노출 훑기 — 흰 물체 깊이 문제가 빛 때문인지 무늬 때문인지 가른다")
    ap.add_argument("--exposures", default=",".join(str(v) for v in DEFAULT_EXPOSURES_US),
                    help="훑을 노출값(µs), 콤마로 구분. 기본: {}".format(
                        ",".join(str(v) for v in DEFAULT_EXPOSURES_US)))
    ap.add_argument("--gain", type=float, default=DEFAULT_GAIN, help="고정할 게인")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--object", default="", help="지금 찍는 물체 이름 (기록용, 예: paper_cup)")
    ap.add_argument("--roi", default=None,
                    help="관심 영역 'x,y,w,h' — **색 사진 픽셀 기준**. 안 주면 화면 전체만 잰다")
    ap.add_argument("--frames", type=int, default=MEASURE_FRAMES,
                    help="노출 하나당 잴 장면 수 (기본 {})".format(MEASURE_FRAMES))
    ap.add_argument("--settle", type=int, default=SETTLE_FRAMES,
                    help="노출 바꾼 뒤 버릴 장면 수 (기본 {})".format(SETTLE_FRAMES))
    ap.add_argument("--out-dir", default=None, help="결과 저장 폴더 (기본: 자동 생성)")
    ap.add_argument("--preview-only", action="store_true",
                    help="노출을 안 건드리고 색 사진 한 장만 저장한다 — ROI 픽셀 좌표를 정할 때 씀")
    args = ap.parse_args()

    try:
        import pyrealsense2 as rs
    except ImportError:
        _die("pyrealsense2 가 없다 — `pip install pyrealsense2` 후 다시.")

    devs = list(rs.context().query_devices())
    if not devs:
        _die("카메라가 안 보인다. USB 를 다시 꽂고, 다른 프로그램이 쥐고 있지 않은지 볼 것.")

    roi_color = _parse_roi(args.roi)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_DIR / "{}_{}".format(args.object or "sweep", stamp))
    out_dir.mkdir(parents=True, exist_ok=True)

    pipe = rs.pipeline()
    conf = rs.config()
    conf.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, 30)
    conf.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, 30)
    have_ir = True
    try:
        conf.enable_stream(rs.stream.infrared, 1, args.width, args.height, rs.format.y8, 30)
        conf.enable_stream(rs.stream.infrared, 2, args.width, args.height, rs.format.y8, 30)
    except Exception as e:
        have_ir = False
        print("⚠️ 좌우 원본(적외선) 영상을 못 연다({}) — 색 사진과 깊이만 저장한다".format(e))

    profile = pipe.start(conf)
    depth_sensor = profile.get_device().first_depth_sensor()
    scale = depth_sensor.get_depth_scale()

    # --- 지금 이 카메라가 실제로 허용하는 범위 (제조사 사양이 아니라 SDK 실측) ------
    limits = read_exposure_gain_range(depth_sensor, rs)
    print("=== D405 노출 훑기 (D-10) ===")
    print("이 카메라의 실제 허용 범위 (SDK 에서 읽음, 사양이 아니다):")
    print("  노출(exposure) : {:.0f} ~ {:.0f} µs (단위 {:.0f})".format(
        limits["exposure_min"], limits["exposure_max"], limits["exposure_step"]))
    print("  게인(gain)     : {:.0f} ~ {:.0f} (단위 {:.0f})".format(
        limits["gain_min"], limits["gain_max"], limits["gain_step"]))
    print()

    # 자동 노출/화이트밸런스를 끄기 전에 원래 값을 기억해 뒀다가 끝나면 되돌린다.
    orig_auto_exp = depth_sensor.get_option(rs.option.enable_auto_exposure)
    orig_exposure = depth_sensor.get_option(rs.option.exposure)
    orig_gain = depth_sensor.get_option(rs.option.gain)

    def restore():
        try:
            depth_sensor.set_option(rs.option.enable_auto_exposure, orig_auto_exp)
            if orig_auto_exp == 0:
                depth_sensor.set_option(rs.option.exposure, orig_exposure)
                depth_sensor.set_option(rs.option.gain, orig_gain)
            print("카메라 설정을 원래대로 되돌렸다 (자동노출={}, 노출={:.0f}, 게인={:.0f})".format(
                bool(orig_auto_exp), orig_exposure, orig_gain))
        except Exception as e:
            print("⚠️ 설정 복원 실패({}) — 카메라를 다시 열면 초기화된다".format(e))

    try:
        if args.preview_only:
            for _ in range(args.settle):
                pipe.wait_for_frames()
            fs = pipe.wait_for_frames()
            color = np.asanyarray(fs.get_color_frame().get_data())
            import cv2
            path = out_dir / "preview_color.png"
            cv2.imwrite(str(path), color)
            print("미리보기 색 사진 저장: {}".format(path))
            print("이 사진에서 물체의 픽셀 좌표(x,y,w,h)를 읽어 --roi 로 넘겨라.")
            return 0

        exposures = []
        for tok in args.exposures.split(","):
            tok = tok.strip()
            if not tok:
                continue
            v = float(tok)
            if v < limits["exposure_min"] or v > limits["exposure_max"]:
                print("🛑 노출 {:.0f}µs 는 이 카메라의 허용 범위({:.0f}~{:.0f}) 밖이다 — "
                      "**건너뛴다**(조용히 자르지 않는다)".format(
                          v, limits["exposure_min"], limits["exposure_max"]))
                continue
            exposures.append(v)
        if not exposures:
            _die("잴 수 있는 노출값이 하나도 없다 — --exposures 를 허용 범위 안으로 다시 줄 것")

        if args.gain < limits["gain_min"] or args.gain > limits["gain_max"]:
            _die("게인 {} 는 이 카메라의 허용 범위({:.0f}~{:.0f}) 밖이다".format(
                args.gain, limits["gain_min"], limits["gain_max"]))

        # 자동 노출을 끈다 — **명시적으로**, 그리고 꺼졌는지 확인한다(계획서 요구사항).
        depth_sensor.set_option(rs.option.enable_auto_exposure, 0)
        if depth_sensor.get_option(rs.option.enable_auto_exposure) != 0:
            _die("자동 노출을 껐는데 SDK 가 여전히 켜져 있다고 답한다 — 노출값을 못 믿는다")
        depth_sensor.set_option(rs.option.gain, float(args.gain))

        rows = []
        for exp_us in exposures:
            depth_sensor.set_option(rs.option.exposure, float(exp_us))
            got_exp = depth_sensor.get_option(rs.option.exposure)
            if abs(got_exp - exp_us) > max(1.0, limits["exposure_step"]):
                print("⚠️ 노출 {:.0f}µs 를 요청했는데 카메라가 {:.0f}µs 로 받았다 "
                      "(가장 가까운 허용값으로 SDK 가 내부 반올림했을 수 있다)".format(
                          exp_us, got_exp))

            print("--- 노출 {:.0f} µs (게인 {:.0f} 고정) ---".format(got_exp, args.gain))

            filt = d405_stream.DepthFilters(rs, decimate=2, fill_holes=False)
            for _ in range(args.settle):
                pipe.wait_for_frames()

            color_saved = ir1_saved = ir2_saved = None
            for fi in range(args.frames):
                fs = pipe.wait_for_frames()
                d = fs.get_depth_frame()
                if not d:
                    continue
                raw_m = np.asanyarray(d.get_data()).astype(np.float32) * scale
                filtered_frame = filt.process(d)
                filt_m = np.asanyarray(filtered_frame.get_data()).astype(np.float32) * scale

                color = np.asanyarray(fs.get_color_frame().get_data())
                if color_saved is None:
                    color_saved = color.copy()
                if have_ir:
                    ir1 = fs.get_infrared_frame(1)
                    ir2 = fs.get_infrared_frame(2)
                    if ir1 and ir1_saved is None:
                        ir1_saved = np.asanyarray(ir1.get_data()).copy()
                    if ir2 and ir2_saved is None:
                        ir2_saved = np.asanyarray(ir2.get_data()).copy()

                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                for kind, depth_m in (("raw", raw_m), ("filtered", filt_m)):
                    st = _frame_stats(depth_m)
                    row = dict(
                        exposure_us=got_exp, gain=args.gain, kind=kind, frame_index=fi,
                        valid_depth_ratio=st["valid_ratio"], median_depth_m=st["median_m"],
                        depth_std_m=st["std_m"], point_count=st["point_count"],
                        timestamp=ts, object=args.object)
                    if roi_color is not None:
                        roi_here = _scale_roi(roi_color, color.shape[:2], depth_m.shape)
                        rst = _roi_stats(depth_m, roi_here)
                        row.update(roi_valid_depth_ratio=rst["valid_ratio"],
                                  roi_median_depth_m=rst["median_m"],
                                  roi_depth_std_m=rst["std_m"], roi_point_count=rst["point_count"])
                    rows.append(row)

            last = [r for r in rows if r["exposure_us"] == got_exp and r["kind"] == "filtered"][-1]
            print("  RAW      값있는 화소 {:.0%}".format(
                [r for r in rows if r["exposure_us"] == got_exp and r["kind"] == "raw"][-1][
                    "valid_depth_ratio"]))
            print("  FILTERED 값있는 화소 {:.0%}  중앙거리 {:.3f} m  흔들림 {:.4f} m".format(
                last["valid_depth_ratio"], last["median_depth_m"], last["depth_std_m"]))
            if roi_color is not None:
                print("  ROI(filtered) 값있는 화소 {:.0%}  중앙거리 {:.3f} m".format(
                    last.get("roi_valid_depth_ratio", float("nan")),
                    last.get("roi_median_depth_m", float("nan"))))

            import cv2
            tag = "{:06.0f}us".format(got_exp)
            if color_saved is not None:
                cv2.imwrite(str(out_dir / "{}_color.png".format(tag)), color_saved)
            if ir1_saved is not None:
                cv2.imwrite(str(out_dir / "{}_ir_left.png".format(tag)), ir1_saved)
            if ir2_saved is not None:
                cv2.imwrite(str(out_dir / "{}_ir_right.png".format(tag)), ir2_saved)
            from view_d405 import colorize
            cv2.imwrite(str(out_dir / "{}_depth_filtered.png".format(tag)),
                        colorize(filt_m, cfg.D405_NEAR_M, cfg.D405_FAR_M))
            cv2.imwrite(str(out_dir / "{}_depth_raw.png".format(tag)),
                        colorize(raw_m, cfg.D405_NEAR_M, cfg.D405_FAR_M))

        csv_path = out_dir / "exposure_sweep.csv"
        fieldnames = ["exposure_us", "gain", "kind", "frame_index", "valid_depth_ratio",
                     "median_depth_m", "depth_std_m", "point_count", "timestamp", "object"]
        if roi_color is not None:
            fieldnames += ["roi_valid_depth_ratio", "roi_median_depth_m", "roi_depth_std_m",
                          "roi_point_count"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print()
        print("CSV 저장: {}".format(csv_path))
        print("사진 저장 폴더: {}".format(out_dir))
        print()
        print("판단 기준: 노출을 바꿔도 늘 같은 자리가 비면(무늬가 없어서) → B.")
        print("           특정 노출에서 값이 뚜렷이 늘면(포화·너무 어두움) → A.")
        print("           **컵 부분의 좌우 원본 영상**(_ir_left/_ir_right.png)을 꼭 눈으로 볼 것 —")
        print("           화면 전체 밝기만으로는 컵이 타서 뭉개졌는지 알 수 없다(2026-09-18 교훈).")
        return 0
    finally:
        restore()
        pipe.stop()


if __name__ == "__main__":
    raise SystemExit(main())
