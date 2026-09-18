# -*- coding: utf-8 -*-
"""**배운 물체는 YOLO 로 가르고, 못 찾은 곳은 모양으로 나눈다** — 둘을 같이 쓴다.

왜 둘을 같이 쓰나
-----------------
`segment_objects.py` 는 **모양만 보고** 나눈다. 처음 보는 물체에도 되는 것이 장점인데,
**붙어 있으면 못 가른다** — 사용자가 화면에서 찾았다(2026-09-18):

    *"큰 종이컵, 작은 종이컵이 나란히 있으면 둘을 한 물체로 식별한다"*

YOLO 는 그 반대다. **붙어 있어도 하나씩 가르지만 배운 종류만** 찾는다.
그래서 서로의 약점을 정확히 메운다:

======================  ==========================  ==========================
                        모양으로 나누기               YOLO
======================  ==========================  ==========================
처음 보는 물체           ✅ 된다                      ❌ 못 찾는다
붙어 있는 물체 가르기     ❌ 못 가른다                 ✅ 가른다
======================  ==========================  ==========================

🛑 **YOLO 로 갈아타는 것이 아니다.** `CLAUDE.md` 프로젝트 목적은 **처음 보는 물체**를
잡는 것이다. YOLO 만 쓰면 배운 9종 밖에서는 아무것도 못 한다. 그래서 **YOLO 는 도우미**고,
못 찾았을 때는 모양으로 나누는 쪽이 계속 답을 낸다.

쓰는 모델
---------
`vision/zed_object_detection/weights/dg5f_target_objects_yolov8s.pt` (9종):

    tumbler · plastic cup · phone · can · box · mouse · laptop · bracelet · human

⚠️ **이 모델을 누가 언제 무엇으로 학습시켰는지 기록이 없다.** 얼마나 잘 맞히는지 우리는
   모른다 — 돌려 보고 판단할 것. 그래서 화면에 **확신 정도**를 같이 찍는다.

⚠️ ZED 폴더 자체는 폐기됐다(`vision/zed_object_detection/DEPRECATED.md`) — 받는 쪽
   Unity 코드가 없어졌기 때문이다. **가중치 파일만 가져다 쓴다.** 그 폴더의 파이프라인을
   되살리는 것이 아니다.

`human` 이 쓸모 있다
--------------------
사람 팔이 물체로 잡히던 문제(25 cm 짜리 덩어리)를 **걸러낼 수 있다.**

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트):

    vision/.vision/Scripts/Activate.ps1
    python vision/d405/yolo_assist.py --live

한 장만 찍어 보기:

    python vision/d405/yolo_assist.py --save
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

import rtauto_config as cfg  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 얼마나 확신해야 믿을지. 낮추면 헛것을 찾고, 높이면 진짜를 놓친다.
#: ⚠️ 이 모델의 성적을 우리가 모르므로 **잠정값**이다 — 돌려 보고 맞출 것.
YOLO_CONF = 0.35

#: 사람은 물체가 아니다 — 잡으러 가면 안 된다.
NOT_OBJECT = ("human",)


def model_path():
    """가중치 파일 자리. 설정으로 바꿀 수 있게 해 둔다(원칙 1)."""
    override = getattr(cfg, "YOLO_WEIGHTS", "")
    if override:
        p = Path(override)
        return p if p.is_absolute() else (REPO_ROOT / p)
    return REPO_ROOT / "vision" / "zed_object_detection" / "weights" / \
        "dg5f_target_objects_yolov8s.pt"


@dataclass
class Detection:
    """YOLO 가 찾은 것 하나."""
    name: str
    conf: float
    box: tuple          # (x1, y1, x2, y2) 화면 좌표

    @property
    def is_object(self) -> bool:
        return self.name not in NOT_OBJECT


class Detector:
    """YOLO 를 감싼다. 없으면 **조용히 꺼진 채로 동작한다** — 모양 쪽은 계속 돈다."""

    def __init__(self, path=None, conf=YOLO_CONF):
        self.conf = float(conf)
        self.model = None
        self.why = ""
        p = Path(path) if path else model_path()
        if not p.exists():
            self.why = "가중치 파일이 없다: {}".format(p)
            return
        try:
            from ultralytics import YOLO
            self.model = YOLO(str(p))
            self.names = self.model.names
        except Exception as e:                       # 없어도 전체가 멈추면 안 된다
            self.why = "YOLO 를 못 불러왔다: {}".format(e)

    @property
    def ready(self) -> bool:
        return self.model is not None

    def detect(self, bgr) -> List[Detection]:
        if not self.ready:
            return []
        res = self.model.predict(bgr, conf=self.conf, verbose=False)[0]
        out = []
        for b in res.boxes:
            xy = [float(v) for v in b.xyxy[0].tolist()]
            out.append(Detection(name=str(self.names[int(b.cls[0])]),
                                 conf=float(b.conf[0]), box=tuple(xy)))
        return out


def split_by_boxes(points, pixel_xy, dets, min_points=120):
    """**박스 안의 점들을 따로 떼어낸다.**

    돌려주는 것: `(박스별 물체 목록, 어느 박스에도 안 든 점)`

    같은 점이 두 박스에 겹쳐 들면 **확신이 높은 쪽**에 준다 — 나란히 놓인 컵처럼
    박스가 조금 겹칠 때 점이 양쪽에 중복되지 않게 한다.
    """
    from segment_objects import ObjectCloud, cluster

    pts = np.asarray(points, dtype=np.float64)
    px, py = np.asarray(pixel_xy[0], dtype=float), np.asarray(pixel_xy[1], dtype=float)
    owner = np.full(len(pts), -1, dtype=np.int64)
    best_conf = np.zeros(len(pts))

    order = sorted(range(len(dets)), key=lambda i: dets[i].conf)   # 낮은 것부터, 높은 것이 덮어씀
    for i in order:
        d = dets[i]
        if not d.is_object:
            continue
        x1, y1, x2, y2 = d.box
        inside = (px >= x1) & (px <= x2) & (py >= y1) & (py <= y2)
        take = inside & (d.conf >= best_conf)
        owner[take] = i
        best_conf[take] = d.conf

    objs, used = [], np.zeros(len(pts), dtype=bool)
    for i, d in enumerate(dets):
        if not d.is_object:
            continue
        sel = owner == i
        if int(sel.sum()) < min_points:
            continue
        inside = pts[sel]

        # ⚠️ **박스는 평면(2D)이라 그 방향의 배경까지 전부 긁어온다.**
        #    처음엔 박스 안의 점을 통째로 한 물체로 썼더니 텀블러 크기가
        #    324x344x598 cm 로 나왔다(2026-09-18) — 뒤의 벽·모니터가 같이 들어온 것이다.
        #    그래서 박스 안에서 **모양으로 한 번 더 나누고, 카메라에 가장 가까운
        #    덩어리**만 쓴다. 물체가 배경보다 앞에 있다는 것은 항상 참이다.
        pieces = cluster(inside)
        if not pieces:
            continue
        near_piece = min(pieces, key=lambda o: o.distance_m)
        o = ObjectCloud(points=near_piece.points, center=near_piece.center,
                        size=near_piece.size, n_points=near_piece.n_points)
        o.source = "YOLO:{} {:.0%}".format(d.name, d.conf)      # 어디서 나왔는지 남긴다
        objs.append(o)
        # 박스 안 전체가 아니라 **쓴 점만** 소비 처리한다 — 나머지는 모양 쪽이 다시 본다
        taken = np.zeros(len(pts), dtype=bool)
        idx_in = np.flatnonzero(sel)
        # near_piece 의 점이 inside 의 어느 줄인지 되찾는다(좌표로 맞춘다)
        keep = np.isin(inside.view([('', inside.dtype)] * 3).ravel(),
                       near_piece.points.astype(inside.dtype).view(
                           [('', inside.dtype)] * 3).ravel())
        taken[idx_in[keep]] = True
        used |= taken

    # 사람으로 잡힌 박스 안의 점은 **버린다** — 잡으러 가면 안 된다
    for d in dets:
        if d.is_object:
            continue
        x1, y1, x2, y2 = d.box
        used |= (px >= x1) & (px <= x2) & (py >= y1) & (py <= y2)

    return objs, pts[~used]


def find_objects_hybrid(points, pixel_xy, color_bgr, detector, near=None, far=None):
    """**YOLO 로 먼저 가르고, 남은 곳은 모양으로 나눈다.**

    돌려주는 것: `(물체 목록, 설명 문구)`
    """
    from segment_objects import find_objects

    dets = detector.detect(color_bgr) if (detector and detector.ready) else []
    boxed, rest = split_by_boxes(points, pixel_xy, dets)

    shape_objs, _, note = find_objects(rest, near=near, far=far)
    for o in shape_objs:
        o.source = "모양"

    objs = boxed + shape_objs
    objs.sort(key=lambda o: -o.n_points)
    found = ", ".join("{} {:.0%}".format(d.name, d.conf) for d in dets) or "없음"
    return objs, "YOLO: {} / 모양으로 추가 {}개 ({})".format(found, len(shape_objs), note)


# --------------------------------------------------------------------------
def _to_points(depth_m, intr):
    ys, xs = np.nonzero(depth_m > 0)
    z = depth_m[ys, xs]
    pts = np.stack([(xs - intr.ppx) * z / intr.fx,
                    (ys - intr.ppy) * z / intr.fy, z], axis=1)
    return pts, (xs.astype(float), ys.astype(float))


def main() -> int:
    ap = argparse.ArgumentParser(description="YOLO + 모양, 둘을 같이 써서 물체 나누기")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--conf", type=float, default=YOLO_CONF)
    ap.add_argument("--weights", default=None)
    ap.add_argument("--near", type=float, default=None)
    ap.add_argument("--far", type=float, default=None)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    if not (args.live or args.save):
        print(__doc__)
        return 2

    import cv2
    from d405_stream import open_depth
    from segment_objects import Tracker, size_verdict
    from view_d405 import colorize, put_lines

    near = cfg.D405_NEAR_M if args.near is None else args.near
    far = cfg.D405_FAR_M if args.far is None else args.far

    det = Detector(args.weights, args.conf)
    print("=== YOLO + 모양 ===")
    if det.ready:
        print("YOLO: {} 종 — {}".format(len(det.names), ", ".join(det.names.values())))
        print("확신 기준 {:.0%} 이상만 믿는다 (잠정값 — 이 모델 성적을 우리가 모른다)".format(
            args.conf))
    else:
        print("⚠️ YOLO 를 못 쓴다 ({}) — **모양으로 나누기만 돈다**".format(det.why))
    print("🛑 YOLO 로 갈아타는 것이 아니다. 배운 9종 밖은 모양 쪽이 계속 답을 낸다.")
    print("키: q 끝내기 / s 사진 저장")
    print()

    stream = open_depth(args.width, args.height, color=True)
    tracker = Tracker()
    win = "YOLO + 모양  (왼쪽: 색 사진+박스   오른쪽: 나눈 결과)"
    try:
        while True:
            got, intr = stream.frames(count=1, warmup=0)
            if not got:
                continue
            depth_m, color = got[0]
            if color is None:
                continue
            pts, pix = _to_points(depth_m, intr)
            objs, note = find_objects_hybrid(pts, pix, color, det, near, far)
            objs = tracker.update(objs)

            paint = colorize(depth_m, near, far)
            for o in objs[:10]:
                z = np.maximum(o.points[:, 2], 1e-6)
                bx = np.round(o.points[:, 0] * intr.fx / z + intr.ppx)
                by = np.round(o.points[:, 1] * intr.fy / z + intr.ppy)
                ok = ((bx >= 0) & (bx < depth_m.shape[1])
                      & (by >= 0) & (by < depth_m.shape[0]))
                paint[by[ok].astype(int), bx[ok].astype(int)] = size_verdict(o)[0]

            view_c = cv2.resize(color, (640, 480))
            sx, sy = 640 / color.shape[1], 480 / color.shape[0]
            for d in det.detect(color) if det.ready else []:
                x1, y1, x2, y2 = d.box
                col = (0, 200, 255) if d.is_object else (80, 80, 80)
                cv2.rectangle(view_c, (int(x1 * sx), int(y1 * sy)),
                              (int(x2 * sx), int(y2 * sy)), col, 2)
                cv2.putText(view_c, "{} {:.0%}".format(d.name, d.conf),
                            (int(x1 * sx), max(12, int(y1 * sy) - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)

            view_o = cv2.resize(paint, (640, 480), interpolation=cv2.INTER_NEAREST)
            n_ok = sum(1 for o in objs if size_verdict(o)[1] == "잡을만")
            lines = ["찾은 덩어리 {}개 — 잡을만한 크기 {}개".format(len(objs), n_ok),
                     "초록=잡을만 / 빨강=큼 / 파랑=작음", note]
            for o in objs[:4]:
                lines.append("  {}번 [{}] {:.1f}x{:.1f}x{:.1f} cm  {}".format(
                    o.track_id, size_verdict(o)[1], *(o.size * 100),
                    getattr(o, "source", "?")))
            view_o = put_lines(view_o, lines)
            both = np.hstack([view_c, view_o])

            if args.save:
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "yolo_{}.png".format(stamp)), both)
                print(note)
                for o in objs[:8]:
                    print("  {}번 [{}] {:.1f}x{:.1f}x{:.1f} cm  거리 {:.2f} m  {}".format(
                        o.track_id, size_verdict(o)[1], *(o.size * 100),
                        o.distance_m, getattr(o, "source", "?")))
                print("저장: {}".format(RESULTS_DIR / "yolo_{}.png".format(stamp)))
                break

            cv2.imshow(win, both)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "yolo_{}.png".format(stamp)), both)
                print("사진 저장 / " + note)
    finally:
        stream.close()
        try:
            import cv2 as _c
            _c.destroyAllWindows()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
