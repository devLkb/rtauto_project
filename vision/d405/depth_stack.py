# -*- coding: utf-8 -*-
"""**여러 장을 합쳐 거리값이 나온 화소를 모은다** — 없는 값은 지어내지 않는다.

왜 필요한가
-----------
흰 종이컵처럼 무늬가 없는 면은 거리가 **나오다 말다 한다.** 한 장만 찍으면 컵 자리가
거의 비어 있어 점 덩어리를 못 만든다(2026-09-18 실측: 불 껐을 때 값 있는 화소 14 %).

그런데 **깜빡이는 자리가 매번 다르다.** 그래서 같은 자리를 여러 장 찍어 모으면, 어느
한 장에서라도 값이 나온 화소를 건질 수 있다.

🛑 **구멍 메우기(hole filling)와 다르다.** 구멍 메우기는 **옆 화소를 보고 없는 값을
   지어낸다.** 여기서는 **실제로 카메라가 그 화소에서 읽은 값만** 쓴다. 한 번도 안 읽힌
   화소는 끝까지 0 으로 남는다. (구멍 메우기를 쓰지 않는 이유는
   `d405_stream.py` 의 설명 참고 — 없는 면을 있다고 보고 손을 갖다 대게 된다)

⚠️ **카메라가 움직이면 쓰면 안 된다.** 같은 화소가 같은 지점을 가리킨다는 전제이기
   때문이다. 우리 동작 원칙이 **"이동 → 정지 → 팔"** 이라 파지 직전에는 항상 멈춰
   있으므로, 바로 그 자리에서 쓰라고 만든 것이다.

쓰는 법 (다른 코드에서)::

    from depth_stack import stack
    got, intr = stream.frames(count=5, warmup=0)
    merged, stats = stack([d for d, _ in got])
    print(stats["message"])
"""
from __future__ import annotations

import warnings

import numpy as np

#: 몇 장을 합칠지 기본값. 30장/초이므로 5장은 **0.17초**다 — 사람이 못 느낀다.
#: 더 늘려도 좋아지는 폭은 줄어든다(같은 자리가 계속 안 나오면 끝까지 안 나온다).
DEFAULT_FRAMES = 5

#: 몇 번은 나와야 그 값을 믿을지. 1이면 한 번이라도 나온 값을 전부 쓴다(가장 많이 건진다).
#: 2 이상으로 올리면 **한 번만 반짝한 값**을 버려 더 깨끗해지지만 건지는 양은 줄어든다.
DEFAULT_MIN_HITS = 1


def stack(depths, min_hits=DEFAULT_MIN_HITS):
    """거리 사진 여러 장을 **한 장으로 합친다**.

    각 화소마다 **값이 나온 장면들의 중앙값**을 쓴다. 중앙값이라 한 장에서 튄 값에
    흔들리지 않는다. 한 번도 안 나온 화소는 0(=모름)으로 남는다.

    돌려주는 것: `(합친 거리 사진, 설명 숫자들)`

    설명 숫자들:

    ==================  ===============================================
    `frames`             합친 장면 수
    `single_valid`       **첫 장면**에서 값이 있던 화소 비율
    `after_valid`        합친 뒤 값이 있는 화소 비율
    `gain`               늘어난 화소 수
    `message`            사람이 읽을 한 줄
    ==================  ===============================================
    """
    if not len(depths):
        raise ValueError("합칠 거리 사진이 없다")

    arr = np.stack([np.asarray(d, dtype=np.float32) for d in depths], axis=0)
    if arr.ndim != 3:
        raise ValueError("거리 사진은 (세로, 가로) 여야 한다: {}".format(arr.shape[1:]))

    valid = arr > 0
    hits = valid.sum(axis=0)

    # 중앙값은 "값이 있는 것들끼리" 내야 한다 → 없는 자리를 NaN 으로 바꿔 무시시킨다.
    # 한 번도 안 나온 화소는 전부 NaN 이라 경고가 뜨는데, 그건 **정상**이므로 덮는다.
    masked = np.where(valid, arr, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        merged = np.nanmedian(masked, axis=0)
    merged = np.nan_to_num(merged, nan=0.0).astype(np.float32)
    merged[hits < int(min_hits)] = 0.0

    total = float(merged.size)
    single = float(valid[0].sum()) / total
    after = float((merged > 0).sum()) / total
    stats = {
        "frames": int(arr.shape[0]),
        "single_valid": single,
        "after_valid": after,
        "gain": int((merged > 0).sum() - valid[0].sum()),
        "min_hits": int(min_hits),
    }
    stats["message"] = (
        "{}장 합침 — 값 있는 화소 {:.0%} → {:.0%} (+{}개). "
        "실제로 읽힌 값만 쓴다(지어낸 값 없음)".format(
            stats["frames"], single, after, stats["gain"]))
    return merged, stats
