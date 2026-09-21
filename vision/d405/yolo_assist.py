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

쓰는 모델 — **YOLOE** (글자로 찾을 것을 정한다)
------------------------------------------------
`vision/d405/weights/yoloe26-n-seg-ready.pt` (11.5 MB).

YOLOE 는 **"cup", "can" 같은 글자로 무엇을 찾을지** 알려 주는 방식이다. 정해진 80종에
묶이지 않으므로 **우리 목적("처음 보는 물체")에 더 맞는다.** 새 물체가 생기면
`PROMPT_WORDS` 에 한 줄 넣고 `make_ready.py` 를 다시 돌리면 끝이다.

⚠️ **이름이 맞는지는 중요하지 않다 — 테두리가 목적이다.** 실제로 캔이 `bottle` 로
   불렸지만(77 %) 테두리는 정확했다(2026-09-18 실측). 우리는 점 덩어리를 잘라내려는
   것이지 이름표를 붙이려는 게 아니다.

여기까지 온 과정 (전부 같은 사진으로 견줬다)
--------------------------------------------

=====================  ==========  ==========  ==========  ============
같은 사진               ZED 모델     YOLO11n     YOLO11s     **YOLOE26-n**
=====================  ==========  ==========  ==========  ============
흰 컵                    10 %        92 %        89 %        **89 %**
캔                      못 찾음      못 찾음      못 찾음      **77 %**
마우스                   못 찾음      83 %        91 %        **90 %**
테두리                   없음         있음         있음         **있음**
CPU 한 장                 —          41 ms       76 ms       **43 ms**
=====================  ==========  ==========  ==========  ============

- **ZED 모델은 버렸다.** 확신 5 % 까지 낮춰도 거의 못 찾았다. 원인은 더 파지 않았다
  (공식 모델이 훨씬 잘하므로 파 볼 값어치가 없다).
- **COCO 계열(YOLO11)은 캔을 원천적으로 못 찾는다** — `can` 이라는 종류가 아예 없다.
- **l(큰 것)은 안 쓴다.** CPU 228 ms 로 5 배 느린데 결과가 같았다.
  시연장엔 노트북만 가져가므로 n 이 맞다.

⚠️ **242 MB 를 시연 노트북에 안 들이려고 "구워" 둔다.** YOLOE 는 글자를 이해하려고
   별도 모델(`mobileclip2_b.ts`, 242 MB)이 필요한데, 그 일은 **미리 한 번만** 하면 된다.
   `make_ready.py` 가 결과를 모델에 구워 11.5 MB 파일 하나로 만든다.

**흰 종이컵 문제 — 거리값이 몇 개 없어도 물체를 낸다** (2026-09-18)
------------------------------------------------------------------
YOLO 는 "여기 컵이 있다" 를 정확히 말하는데, **흰 종이컵은 무늬가 없어 거리값이 거의
안 나온다.** D405 에는 무늬를 쏘는 장치가 없고, 렌즈에 적외선을 막는 필터가 들어 있어
**적외선 무늬 장치를 사도 안 통한다**(제조사 답변). 그래서 코드 쪽에서 세 가지를 했다.

1. **좌표 환산을 고쳤다.** 깊이 사진은 줄이기 때문에 색 사진의 **절반 크기**인데
   (640x480 → 320x240) 그 화소 번호를 환산 없이 테두리에 대고 있었다. 화면 가운데
   있는 컵이 **통째로 버려지고 있었다** — 컵이 안 잡히던 이유의 큰 몫이다.
2. **여러 장을 합친다** (`--frames`, `depth_stack.py`). 깜빡이는 자리가 매번 달라서,
   여러 장에서 **한 번이라도 읽힌 값**을 모으면 건지는 양이 늘어난다.
   구멍 메우기와 달리 **없는 값을 지어내지 않는다.**
3. **그래도 모자라면 테두리로 계산한다** (`estimate_from_mask`). 거리값이 6개만 있어도
   그것으로 거리를 정하고, 가로·세로는 **테두리 화소 수 × 거리 ÷ 초점거리**로 낸다.
   이런 물체는 `estimated=True` 로 표시되고 화면에 **노란 네모 + "추정"** 으로 그려진다 —
   잡으러 갈지 정할 때 **덜 믿어야 한다.**

⚠️ 그래도 **조명은 여전히 성능을 좌우한다**(값 있는 화소 14 % → 45 %). 위 셋은
   "어두워도 된다" 는 뜻이 아니라 **값이 듬성듬성해도 버티게** 만든 것이다.

`person` 이 쓸모 있다
---------------------
사람 팔이 물체로 잡히던 문제(25 cm 짜리 덩어리)를 **걸러낼 수 있다.**
`NOT_OBJECT` 에 사람·책상·의자·모니터를 넣어 잡으러 가지 않게 했다.

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

import depth_stack  # noqa: E402

RESULTS_DIR = REPO_ROOT / "vision" / "d405" / "results"

#: 얼마나 확신해야 믿을지. 낮추면 헛것을 찾고, 높이면 진짜를 놓친다.
#: ⚠️ 이 모델의 성적을 우리가 모르므로 **잠정값**이다 — 돌려 보고 맞출 것.
YOLO_CONF = 0.35

#: 잡으러 가면 안 되는 것들. 사람은 물체가 아니고, 책상·의자·모니터는 손에 안 들어온다.
NOT_OBJECT = ("person", "dining table", "chair", "couch", "bed", "tv", "refrigerator")

#: 찾을 것들. **글자로 적으면 그대로 찾는다**(YOLOE) — 종류가 80개로 묶여 있지 않다.
#: 우리 목적이 "처음 보는 물체" 라 이쪽이 더 맞는다. 새 물체가 생기면 여기 한 줄 추가하고
#: `make_ready.py` 를 다시 돌리면 된다.
#:
#: ⚠️ **이름이 맞는지는 중요하지 않다.** 우리가 쓰는 것은 **테두리**다 — 실제로 캔이
#:    `bottle` 로 불렸지만(77 %) 테두리는 정확했다(2026-09-18 실측). 이름이 아니라
#:    잘라내기가 목적이다.
#: 🛑 **2026-09-21 사용자 결정 — "처음 보는 물체 일반화"는 이 목록을 무한히 늘리라는
#:    뜻이 아니다.** 진짜 미지의(이름조차 없는) 형상까지 잡는 것은 **페스타(2026-11-13)
#:    이후 별도 과제**다. 지금은 **전시에서 실제로 나올 법한 "상식적인 범위"의 물건을
#:    확실히 인식**하는 것이 목표라서, 그 범위 안에서 목록을 채운다
#:    (`ai_festa_plan.md` §8-2 참고). 공구는 이 상식적 범위에 들어간다고 보고 추가함.
PROMPT_WORDS = ("cup", "paper cup", "bottle", "can", "box", "computer mouse",
                "keyboard", "pen", "cell phone", "book", "bowl", "person",
                "screwdriver", "wrench", "hammer", "pliers", "tape measure", "scissors")

#: 기본 가중치. **찾을 말이 이미 구워진** 파일을 쓴다.
#: ⚠️ 구워 두는 이유: YOLOE 는 글자를 이해하려고 별도 모델(`mobileclip2_b.ts`, **242 MB**)
#:    을 받는데, **미리 한 번만** 하면 되고 그 결과를 모델에 구워 두면 시연 노트북에서는
#:    그 242 MB 가 필요 없다. 시연장엔 노트북과 로봇만 가져가므로 이게 중요하다.
#:    만드는 법: `python vision/d405/make_ready.py`
DEFAULT_WEIGHTS = "yoloe26-n-seg-ready.pt"

#: 구운 파일이 없을 때 물러설 곳. 이건 COCO 80종 고정이라 **캔을 못 찾는다.**
FALLBACK_WEIGHTS = "yolo11n-seg.pt"


def model_path():
    """가중치 파일 자리. 설정으로 바꿀 수 있게 해 둔다(원칙 1)."""
    override = getattr(cfg, "YOLO_WEIGHTS", "")
    if override:
        p = Path(override)
        return p if p.is_absolute() else (REPO_ROOT / p)
    here = REPO_ROOT / "vision" / "d405" / "weights"
    if (here / DEFAULT_WEIGHTS).exists():
        return here / DEFAULT_WEIGHTS
    if (here / FALLBACK_WEIGHTS).exists():
        return here / FALLBACK_WEIGHTS
    return Path(FALLBACK_WEIGHTS)            # 없으면 자동 내려받기(COCO 80종)


@dataclass
class Detection:
    """YOLO 가 찾은 것 하나."""
    name: str
    conf: float
    box: tuple                      # (x1, y1, x2, y2) 화면 좌표
    mask: Optional[np.ndarray] = None   # 물체 모양 그대로 (있으면 박스 대신 이걸 쓴다)

    @property
    def is_object(self) -> bool:
        return self.name not in NOT_OBJECT

    def contains(self, px, py, shape):
        """**색 사진 좌표** `(px, py)` 들이 이 물체 안에 드는가.

        **테두리(mask)가 있으면 그것을 쓰고**, 없을 때만 네모 박스로 물러선다.
        박스는 물체 뒤의 배경까지 긁어오므로 테두리 쪽이 훨씬 깨끗하다.

        🛑 **깊이 사진의 화소 번호를 그대로 넣으면 안 된다.** 깊이 사진은 줄이기 때문에
           색 사진의 절반 크기다(640x480 → 320x240). 환산은 `split_by_boxes` 가 한다.
        """
        x1, y1, x2, y2 = self.box
        in_box = (px >= x1) & (px <= x2) & (py >= y1) & (py <= y2)
        if self.mask is None:
            return in_box
        h, w = self.mask.shape
        ix = np.clip(np.round(px * (w / shape[1])).astype(int), 0, w - 1)
        iy = np.clip(np.round(py * (h / shape[0])).astype(int), 0, h - 1)
        return in_box & (self.mask[iy, ix] > 0.5)


class Detector:
    """YOLO 를 감싼다. 없으면 **조용히 꺼진 채로 동작한다** — 모양 쪽은 계속 돈다."""

    def __init__(self, path=None, conf=YOLO_CONF):
        self.conf = float(conf)
        self.model = None
        self.why = ""
        p = Path(path) if path else model_path()
        self.path = p
        try:
            # 구운 YOLOE 파일은 YOLOE 로 열어야 찾을 말이 살아난다
            if "yoloe" in p.name.lower():
                from ultralytics import YOLOE as _M
            else:
                from ultralytics import YOLO as _M
            self.model = _M(str(p))
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
        masks = None
        if getattr(res, "masks", None) is not None:
            masks = res.masks.data.cpu().numpy()      # (물체수, 높이, 너비)
        out = []
        for i, b in enumerate(res.boxes):
            xy = [float(v) for v in b.xyxy[0].tolist()]
            out.append(Detection(name=str(self.names[int(b.cls[0])]),
                                 conf=float(b.conf[0]), box=tuple(xy),
                                 mask=(masks[i] if masks is not None and i < len(masks)
                                       else None)))
        return out


#: 덩어리로 묶으려면 점이 이만큼은 있어야 한다.
CLUSTER_MIN_POINTS = 120

#: 덩어리를 못 만들 때, 거리값이 이만큼이라도 있으면 **테두리로 크기를 계산**한다.
#: ⚠️ 이게 **흰 종이컵 대책**이다 — YOLO 는 "여기 컵이 있다" 를 정확히 말하는데
#:    무늬가 없어 거리값이 몇 개밖에 안 나온다(2026-09-18). 그 몇 개로 거리를 정하고,
#:    가로·세로는 **테두리 화소 수**에서 계산한다. 값을 지어내는 것이 아니라
#:    **실제로 읽힌 거리 + 실제로 본 테두리**만 쓴다.
FEW_POINTS_MIN = 6

#: 추정할 때 "이 물체" 로 볼 거리 폭(m). 가장 가까운 값에서 이만큼 안쪽만 쓴다 —
#: 테두리가 가장자리에서 물고 온 **뒤 배경**을 빼려는 것.
#: 조각을 도로 합칠 때도 같은 폭을 쓴다(`_merge_pieces`).
ESTIMATE_BAND_M = 0.05

#: 점 덩어리가 테두리의 **가로 폭을 이 비율만큼은 덮어야** 크기를 믿는다.
#: 못 덮으면 테두리 쪽 계산으로 넘긴다.
#:
#: ⚠️ **왜 가로만 보나.** 카메라가 물체를 위에서 비스듬히 내려다보면 컵의 **아랫부분은
#:    거리값이 안 나온다** — 세로는 원래 덜 덮이는 게 정상이라 기준으로 쓸 수 없다.
#:    반면 가로(폭)는 손을 얼마나 벌릴지와 직결되고, 위에서 봐도 테두리 전체가 보인다.
#:
#: 이 장치가 필요한 이유(2026-09-18 실측): 뒤쪽에 반쯤 가린 작은 종이컵이
#: **3.2 cm** 로 나왔다 — 실제 7 cm. 거리값이 숭숭 뚫려 조각난 것 중 한 조각만
#: 쓰고 있었다.
MASK_COVER_MIN = 0.6

#: 추정 물체의 앞뒤 두께를 최소 이만큼으로 본다(m). 한 면만 보이므로 0 이 나올 수 있는데,
#: 0 이면 크기 판정이 이상해진다.
ESTIMATE_MIN_DEPTH_M = 0.005


def _mask_extent(d, shape):
    """테두리(없으면 박스)가 **색 사진 좌표**에서 차지하는 범위.

    돌려주는 것: `(가로 화소수, 세로 화소수, 가운데 u, 가운데 v)`
    """
    if d.mask is not None:
        ys, xs = np.nonzero(d.mask > 0.5)
        if len(xs):
            h, w = d.mask.shape
            sx, sy = shape[1] / float(w), shape[0] / float(h)
            return (float(xs.max() - xs.min() + 1) * sx,
                    float(ys.max() - ys.min() + 1) * sy,
                    float(xs.mean() + 0.5) * sx, float(ys.mean() + 0.5) * sy)
    x1, y1, x2, y2 = d.box
    return (float(x2 - x1), float(y2 - y1), (x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _merge_pieces(pieces, inside):
    """**같은 물체의 조각들을 도로 합친다.**

    거리값이 숭숭 뚫린 물체는 덩어리 묶기에서 여러 조각으로 부서진다. 전에는 그중
    **카메라에 가장 가까운 한 조각**만 썼는데, 그러면 크기가 실제보다 훨씬 작게 나온다
    (2026-09-18 실측: 7 cm 짜리 종이컵이 3.2 cm).

    **YOLO 가 이미 "여기까지가 한 물체" 라고 말해 줬으므로**, 가장 가까운 조각에서
    `ESTIMATE_BAND_M` 안쪽에 있는 조각은 전부 같은 물체로 본다. 그보다 뒤에 있는 것은
    배경이므로 계속 버린다.
    """
    from segment_objects import ObjectCloud

    near = min(pieces, key=lambda p: p.distance_m)
    idx = np.unique(np.concatenate(
        [p.index for p in pieces
         if p.distance_m <= near.distance_m + ESTIMATE_BAND_M]))
    pts = inside[idx]
    return ObjectCloud(points=pts.astype(np.float32), center=pts.mean(axis=0),
                       size=pts.max(axis=0) - pts.min(axis=0),
                       n_points=len(idx), index=idx)


def _covers_enough(o, d, intr, shape, depth_shape, need=MASK_COVER_MIN):
    """점 덩어리가 **테두리의 가로 폭을 충분히 덮었나.** 못 덮었으면 크기를 못 믿는다."""
    if intr is None:
        return True
    u_px, _, _, _ = _mask_extent(d, shape)
    mask_w = u_px / (shape[1] / float(depth_shape[1]))      # 깊이 사진 화소 기준
    if mask_w <= 0:
        return True
    seen_w = o.size[0] * float(intr.fx) / max(float(o.center[2]), 1e-6)
    return seen_w >= need * mask_w


def estimate_from_mask(d, inside, intr, shape, depth_shape):
    """**거리값이 몇 개 없을 때** 테두리와 그 몇 개로 물체 하나를 만든다.

    - **거리**: 있는 값 중 앞쪽 무리의 중앙값 (뒤 배경은 뺀다)
    - **가로·세로**: 테두리가 차지한 화소 수 × 거리 ÷ 초점거리 — 학교에서 배우는 닮은꼴이다
    - **앞뒤 두께**: 한 면만 보이므로 잰 값의 폭. 사실상 모른다고 봐야 한다

    돌려주는 것: `ObjectCloud`(`estimated=True` 로 표시된다). 못 하면 `None`.
    """
    from segment_objects import ObjectCloud

    if len(inside) < FEW_POINTS_MIN or intr is None:
        return None

    z = inside[:, 2]
    band = z <= float(np.percentile(z, 10)) + ESTIMATE_BAND_M
    if int(band.sum()) < FEW_POINTS_MIN:
        band = np.ones(len(z), dtype=bool)
    zz = z[band]
    z_med = float(np.median(zz))

    u_px, v_px, uc, vc = _mask_extent(d, shape)
    sx, sy = shape[1] / float(depth_shape[1]), shape[0] / float(depth_shape[0])
    w_m = (u_px / sx) * z_med / float(intr.fx)
    h_m = (v_px / sy) * z_med / float(intr.fy)
    cx = (uc / sx - float(intr.ppx)) * z_med / float(intr.fx)
    cy = (vc / sy - float(intr.ppy)) * z_med / float(intr.fy)
    d_m = max(float(zz.max() - zz.min()), ESTIMATE_MIN_DEPTH_M)

    n = int(band.sum())
    return ObjectCloud(
        points=inside[band].astype(np.float32),
        center=np.array([cx, cy, z_med], dtype=np.float64),
        size=np.array([w_m, h_m, d_m], dtype=np.float64),
        n_points=n, estimated=True, index=np.flatnonzero(band),
        why="거리값 {}개뿐 — 테두리로 가로·세로를 계산했다(앞뒤 두께는 모른다)".format(n))


def split_by_boxes(points, pixel_xy, dets, shape, depth_shape=None, intr=None,
                   min_points=CLUSTER_MIN_POINTS, near=None, far=None):
    """**YOLO 가 찾은 것들의 점을 따로 떼어낸다.**

    테두리(mask)가 있으면 그것으로, 없으면 네모 박스로 가른다.

    ==============  =====================================================
    `points`         3D 점 (N, 3)
    `pixel_xy`       그 점들의 **깊이 사진** 화소 번호 `(x들, y들)`
    `dets`           YOLO 가 찾은 것들
    `shape`          **색 사진** 크기 `(세로, 가로)` — 박스·테두리가 사는 좌표
    `depth_shape`    **깊이 사진** 크기 `(세로, 가로)`. 안 주면 색 사진과 같다고 본다
    `intr`           깊이 사진 기준 초점거리·중심. 있으면 **듬성듬성해도 추정**한다
    `near`/`far`     D405 가 믿을 수 있는 거리 범위(m). 안 주면 설정값(`D405_NEAR_M`/
                     `D405_FAR_M`) 을 쓴다
    ==============  =====================================================

    돌려주는 것: `(박스별 물체 목록, 어느 박스에도 안 든 점)`

    같은 점이 두 박스에 겹쳐 들면 **확신이 높은 쪽**에 준다 — 나란히 놓인 컵처럼
    박스가 조금 겹칠 때 점이 양쪽에 중복되지 않게 한다.

    🛑 **좌표계가 둘이다.** 깊이 사진은 줄이기 때문에 색 사진의 절반 크기인데
       (640x480 → 320x240), 전에는 깊이 화소 번호를 **환산 없이** 테두리에 대고 있었다.
       그러면 화면 가운데 있는 컵의 점이 테두리 밖으로 밀려나 **통째로 버려진다**
       (2026-09-18 발견). 여기서 한 번에 환산한다.

    🛑 **믿을 수 없는 거리도 제일 먼저 뺀다** (2026-09-21 코드 리뷰로 발견).
       `find_objects()`(모양 전용 경로)는 `near`/`far` 밖의 점을 맨 처음에 버리는데,
       이 함수는 그 검사가 없었다 — YOLO 박스/테두리 안에 렌즈 코앞 반사 같은 잡음이
       섞이면, `_merge_pieces()`가 "가장 가까운 조각"을 고르는 로직 때문에 **그 잡음이
       진짜 물체 대신 뽑히고 진짜 물체는 통째로 사라질 수 있었다**(재현·확인함).
       그래서 여기서도 클러스터링 전에 먼저 범위를 벗어난 점을 뺀다.
    """
    from segment_objects import cluster

    near = cfg.D405_NEAR_M if near is None else near
    far = cfg.D405_FAR_M if far is None else far

    pts = np.asarray(points, dtype=np.float64)
    depth_shape = tuple(shape) if depth_shape is None else tuple(depth_shape)
    sx = shape[1] / float(depth_shape[1])
    sy = shape[0] / float(depth_shape[0])
    px = np.asarray(pixel_xy[0], dtype=float) * sx      # 색 사진 좌표로 환산
    py = np.asarray(pixel_xy[1], dtype=float) * sy

    # 믿을 수 없는 거리(너무 가깝거나 먼)는 클러스터링에 들어가기 전에 뺀다 —
    # find_objects()(모양 전용 경로)와 같은 순서.
    in_range = (pts[:, 2] >= near) & (pts[:, 2] <= far)
    pts, px, py = pts[in_range], px[in_range], py[in_range]

    owner = np.full(len(pts), -1, dtype=np.int64)
    best_conf = np.zeros(len(pts))

    order = sorted(range(len(dets)), key=lambda i: dets[i].conf)   # 낮은 것부터, 높은 것이 덮어씀
    for i in order:
        d = dets[i]
        if not d.is_object:
            continue
        inside = d.contains(px, py, shape)
        take = inside & (d.conf >= best_conf)
        owner[take] = i
        best_conf[take] = d.conf

    objs, used = [], np.zeros(len(pts), dtype=bool)
    for i, d in enumerate(dets):
        if not d.is_object:
            continue
        sel = owner == i
        idx_in = np.flatnonzero(sel)
        if len(idx_in) == 0:
            continue
        inside = pts[sel]

        # 🛑 **소유(ownership)와 계측(measurement)은 다른 질문이다** (2026-09-21,
        #    바깥 조언자 진단 — `claudeDocs/daily/2026-09-18.md` 세션 18 §B).
        #    이 마스크 안의 점은 **전부 이 YOLO 물체가 소유한다** — 그중 몇 개만
        #    크기·중심 계산에 실제로 썼는지와는 무관하다. 예전에는 "계산에 안 쓴 점"을
        #    바로 아래 `used[idx_in[o.index]]`처럼 **계산에 쓴 점만** 소비 처리했다.
        #    그러면 계산에 안 쓴 나머지가 "주인 없는 점"으로 되돌아가 `pts[~used]`를
        #    거쳐 모양(geometry) 쪽으로 넘어갔고, 같은 물체가 **또 하나 생겼다**
        #    ("크기 계산에 안 썼다" 와 "다른 물체의 점이다" 가 같은 뜻으로 처리되던
        #    버그). 그래서 소유는 여기서 **먼저, 무조건** 확정하고, 계측은 아래에서
        #    별도로(신뢰도 높은 subset만) 계산한다.
        #
        #    🛑 **마스크 바깥 점까지 소유하는 것은 아니다** — `sel = owner == i` 가
        #    이미 마스크(또는 박스) 안으로 한정했고, 다른 detection이 더 높은 확신으로
        #    같은 점을 먼저 차지했으면 `owner` 배정 단계에서 이미 걸러졌다.
        used[idx_in] = True

        # ⚠️ **네모 박스는 그 방향의 배경까지 전부 긁어온다.** 처음엔 박스 안의 점을
        #    통째로 한 물체로 썼더니 텀블러가 **324x344x598 cm** 로 나왔다(2026-09-18) —
        #    뒤의 벽·모니터가 같이 들어온 것이다. 테두리(mask)를 쓰면서 대부분 해결됐지만,
        #    테두리도 가장자리에서 배경을 조금 물고 온다. 그래서 여기서 **모양으로 한 번
        #    더 나누고, 앞쪽 조각들만** 쓴다 —
        #    물체가 배경보다 앞에 있다는 것은 항상 참이다.
        pieces = cluster(inside) if len(idx_in) >= min_points else []
        o = _merge_pieces(pieces, inside) if pieces else None

        # 점이 테두리의 가로 폭을 충분히 못 덮으면 **크기를 점으로 재지 않는다.**
        # (거리값이 숭숭 뚫린 흰 물체가 여기로 온다)
        if o is None or not _covers_enough(o, d, intr, shape, depth_shape):
            guess = estimate_from_mask(d, inside, intr, shape, depth_shape)
            if guess is not None:
                o = guess
        if o is None:
            # 이 detection이 소유한 점은 (위에서 이미) 계속 소유한 채로 남는다 —
            # 계측에 실패했다고 해서 모양 쪽에 다시 넘기지 않는다.
            continue
        o.source = "YOLO:{} {:.0%}".format(d.name, d.conf)      # 어디서 나왔는지 남긴다
        objs.append(o)

    # 사람으로 잡힌 박스 안의 점은 **버린다** — 잡으러 가면 안 된다
    for d in dets:
        if d.is_object:
            continue
        used |= d.contains(px, py, shape)

    return objs, pts[~used]


def find_objects_hybrid(points, pixel_xy, color_bgr, detector, near=None, far=None,
                        depth_shape=None, intr=None, dets=None):
    """**YOLO 로 먼저 가르고, 남은 곳은 모양으로 나눈다.**

    `depth_shape` 와 `intr` 를 주면 **거리값이 듬성듬성한 물체도** 위치·크기를 낸다.
    `dets` 를 미리 주면 YOLO 를 **다시 돌리지 않는다**(화면에도 그려야 하므로 한 번만 돈다).

    돌려주는 것: `(물체 목록, 설명 문구, YOLO 가 찾은 것들)`
    """
    from segment_objects import find_objects

    if dets is None:
        dets = detector.detect(color_bgr) if (detector and detector.ready) else []
    boxed, rest = split_by_boxes(points, pixel_xy, dets, color_bgr.shape[:2],
                                 depth_shape=depth_shape, intr=intr,
                                 near=near, far=far)

    shape_objs, _, note = find_objects(rest, near=near, far=far)

    objs = boxed + shape_objs
    objs.sort(key=lambda o: -o.n_points)
    found = ", ".join("{} {:.0%}".format(d.name, d.conf) for d in dets) or "없음"
    guess = sum(1 for o in objs if o.estimated)
    extra = " / 거리값이 모자라 추정한 것 {}개".format(guess) if guess else ""
    return objs, "YOLO: {} / 모양으로 추가 {}개 ({}){}".format(
        found, len(shape_objs), note, extra), dets


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
    ap.add_argument("--frames", type=int, default=None,
                    help="거리 사진 몇 장을 합칠지. **흰 종이컵처럼 값이 깜빡이는 물체**를 "
                         "건지는 수단이다(지어내지 않는다). 기본: 한 장 찍기는 {}장, "
                         "실시간은 1장".format(depth_stack.DEFAULT_FRAMES))
    args = ap.parse_args()

    if not (args.live or args.save):
        print(__doc__)
        return 2

    import cv2
    from d405_stream import open_depth
    from segment_objects import Tracker, size_verdict, is_grasp_candidate
    from view_d405 import colorize, put_labels, put_lines

    n_frames = args.frames
    if n_frames is None:
        n_frames = depth_stack.DEFAULT_FRAMES if args.save else 1
    n_frames = max(1, int(n_frames))

    near = cfg.D405_NEAR_M if args.near is None else args.near
    far = cfg.D405_FAR_M if args.far is None else args.far

    det = Detector(args.weights, args.conf)
    print("=== YOLO + 모양 ===")
    if det.ready:
        print("모델: {}".format(det.path.name))
        print("찾는 것 {} 종 — {}".format(len(det.names), ", ".join(det.names.values())))
        print("확신 기준 {:.0%} 이상만 믿는다 (잠정값 — 이 모델 성적을 우리가 모른다)".format(
            args.conf))
    else:
        print("⚠️ YOLO 를 못 쓴다 ({}) — **모양으로 나누기만 돈다**".format(det.why))
    print("🛑 YOLO 로 갈아타는 것이 아니다. 배운 9종 밖은 모양 쪽이 계속 답을 낸다.")
    if n_frames > 1:
        print("거리 사진 {}장을 합친다 — 깜빡이는 화소를 건진다(없는 값은 안 지어낸다). "
              "⚠️ 카메라가 멈춰 있을 때만 맞다.".format(n_frames))
    print("키: q 끝내기 / s 사진 저장")
    print()

    stream = open_depth(args.width, args.height, color=True)
    tracker = Tracker()
    # ⚠️ 창 제목은 **영어로 적는다.** OpenCV 가 윈도우 창 제목에 한글을 못 넣어
    #    "모양" 같은 글자로 깨져 나온다(2026-09-18 사용자 화면에서 확인).
    #    설명은 그림 안에 한글로 적으므로 제목은 창을 구분하는 용도만 한다.
    win = "D405 - YOLO + shape  (left: photo / right: objects)"
    try:
        while True:
            got, intr = stream.frames(count=n_frames, warmup=0)
            if not got:
                continue
            depth_m, color = got[-1]
            if color is None:
                continue
            # ⚠️ **`--live` 기본은 1장, `--save` 기본은 5장이다** — 지금까지 화면으로
            #    평가한 대부분은 `--live`(1장)였고, 여러 장 합치기의 효과를 실제로 본
            #    적이 없었다(2026-09-18 세션 18, 바깥 조언자 지적). 몇 장을 합치는지가
            #    화면에 안 보이면 이 사실을 매번 잊는다 — 그래서 **장 수를 항상 표시**한다.
            if len(got) > 1:
                depth_m, st = depth_stack.stack([d for d, _ in got])
                stack_note = st["message"]
            else:
                single_valid = float((depth_m > 0).mean())
                stack_note = "1장만 사용 — 값 있는 화소 {:.0%} (여러 장 합치려면 --frames 5)".format(
                    single_valid)
            pts, pix = _to_points(depth_m, intr)
            objs, note, dets = find_objects_hybrid(
                pts, pix, color, det, near, far,
                depth_shape=depth_m.shape, intr=intr)
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
            for d in dets:
                x1, y1, x2, y2 = d.box
                col = (0, 200, 255) if d.is_object else (80, 80, 80)
                cv2.rectangle(view_c, (int(x1 * sx), int(y1 * sy)),
                              (int(x2 * sx), int(y2 * sy)), col, 2)
                cv2.putText(view_c, "{} {:.0%}".format(d.name, d.conf),
                            (int(x1 * sx), max(12, int(y1 * sy) - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)

            view_o = cv2.resize(paint, (640, 480), interpolation=cv2.INTER_NEAREST)

            # **덩어리마다 번호를 찍는다.** 목록에는 "99번" 이라고 나오는데 그림의 어느
            # 덩어리가 99번인지 알 수가 없었다(2026-09-18 사용자 지적). 같은 번호를
            # **왼쪽 사진에도** 찍어 실제 물건과 맞춰 볼 수 있게 한다(원칙 6).
            #
            # 추정으로 낸 물체는 점이 몇 개 없어 화면에 거의 안 보이므로 **노란 네모**까지
            # 그린다.
            vx, vy = 640 / depth_m.shape[1], 480 / depth_m.shape[0]
            tags = []
            for o in objs[:10]:                      # 색칠한 것과 같은 범위
                z = max(float(o.center[2]), 1e-6)
                cu = (o.center[0] * intr.fx / z + intr.ppx) * vx
                cv_ = (o.center[1] * intr.fy / z + intr.ppy) * vy
                # 번호는 **흰색**으로 쓴다. 덩어리 색(초록/빨강/파랑)과 같은 색으로 쓰면
                # 그 위에서 안 읽힌다 — 크기 판정은 덩어리 색이 이미 말해 준다.
                #
                # ⚠️ **소유(누가 찾았나)와 후보(잡으러 갈 만한가)는 다른 질문이다**
                #    (2026-09-21 사용자 결정). "모양"(geometry) 안전망은 화면에 계속
                #    보여주되, 아직 잡으러 가는 후보로는 **믿지 않는다** — 그래서
                #    회색으로 흐리게 표시해 "참고용" 임을 구분한다. `estimated` 는
                #    YOLO 경로에서만 나오므로(거리값이 모자라 테두리로 추정한 경우)
                #    이 구분과 겹치지 않는다.
                if not is_grasp_candidate(o):
                    col = (150, 150, 150)            # 회색 — 참고용, 후보 아님
                elif o.estimated:
                    col = (0, 255, 255)              # 노랑 — 거리값이 모자라 추정한 것
                    hw = (o.size[0] / 2) * intr.fx / z * vx
                    hh = (o.size[1] / 2) * intr.fy / z * vy
                    cv2.rectangle(view_o, (int(cu - hw), int(cv_ - hh)),
                                  (int(cu + hw), int(cv_ + hh)), col, 2)
                else:
                    col = (255, 255, 255)
                tags.append((cu, cv_, "{}번{}{}".format(
                    o.track_id, " 추정" if o.estimated else "",
                    " 참고" if not is_grasp_candidate(o) else ""), col))
            view_o = put_labels(view_o, tags)
            view_c = put_labels(view_c, tags)

            n_ok = sum(1 for o in objs if size_verdict(o)[1] == "잡을만")
            n_cand = sum(1 for o in objs if is_grasp_candidate(o))
            lines = ["찾은 덩어리 {}개 — 잡을만한 크기 {}개 / 잡으러 갈 후보(YOLO 인식) {}개"
                     .format(len(objs), n_ok, n_cand),
                     "초록=잡을만 / 빨강=큼 / 파랑=작음 / 노란 네모=거리값이 모자라 추정 / "
                     "회색 번호=모양으로만 잡힘(참고용, 후보 아님)",
                     note]
            if stack_note:
                lines.append(stack_note)
            for o in objs[:6]:
                lines.append("  {}번 [{}] {:.1f}x{:.1f}x{:.1f} cm  {}{}{}".format(
                    o.track_id, size_verdict(o)[1], *(o.size * 100), o.source,
                    "  ← 추정" if o.estimated else "",
                    "  ⚠️ 참고용(후보 아님)" if not is_grasp_candidate(o) else ""))
            view_o = put_lines(view_o, lines)
            both = np.hstack([view_c, view_o])

            if args.save:
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(RESULTS_DIR / "yolo_{}.png".format(stamp)), both)
                if stack_note:
                    print(stack_note)
                print(note)
                print("잡으러 갈 후보(YOLO 인식) {}개 / 화면 참고용(모양) {}개".format(
                    n_cand, len(objs) - n_cand))
                for o in objs[:8]:
                    print("  {}번 [{}] {:.1f}x{:.1f}x{:.1f} cm  거리 {:.2f} m  {}{}".format(
                        o.track_id, size_verdict(o)[1], *(o.size * 100),
                        o.distance_m, o.source,
                        "  ⚠️ 참고용(후보 아님)" if not is_grasp_candidate(o) else ""))
                    if o.estimated:
                        print("        ⚠️ {}".format(o.why))
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
