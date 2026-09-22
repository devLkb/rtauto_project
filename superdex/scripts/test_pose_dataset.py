# -*- coding: utf-8 -*-
"""짝지은 데이터 판정 — 특히 **예측기 입력에 시뮬레이터만 아는 값이 안 섞였는지**.

왜 이 시험이 따로 있는가
------------------------
[`docs/FESTA_PREGRASP_PLAN.md`](../../docs/FESTA_PREGRASP_PLAN.md) **§7-3**:
예측기는 **점 덩어리만** 봐야 한다. 시뮬레이터만 아는 값(손가락 몇 개 닿았나, 얼마나
미끄러졌나, 물체가 세계 어디에 있나, 물체 이름)을 입력에 섞으면 **시뮬에서는 잘 되는데
실물에서 못 쓰게 된다.** 그것도 조용히 틀리는 종류다.

사람이 눈으로 확인하는 것에 기대지 않으려고 시험으로 만들었다. 이 시험이 하는 일은
"입력으로 쓸 수 있는 것" 과 "정답 만드는 데만 쓰는 것" 이 파일 안에서 갈려 있는지 보는 것이다.

돌리는 법 (리포 루트, superdex/.venv):

    python superdex/scripts/test_pose_dataset.py superdex/results/pose_dataset_<시각>.npz
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# 정본은 dataset_contract.py 하나 — 여기서 다시 목록을 만들면 train_pose_predictor.py의
# load_pairs()와 조용히 어긋날 수 있다(P1-6/P1-7, 2026-09-21 코드 리뷰).
from dataset_contract import (  # noqa: E402
    CANDIDATE_INPUT, DEPLOYABLE_FRAMES, LABEL_ONLY, LEAKY_FRAMES, OBSERVATION_INPUT,
    check_frame,
)

#: 예측기 입력으로 **써도 되는** 칸 — 관측(카메라가 본 것) + 채점할 후보 자세.
#: ⚠️ pose_pos/pose_quat는 예전에 LABEL_ONLY였다 — **틀렸다**(P1-7). 지금 예측기
#: (`train_pose_predictor._features()`)는 이 둘을 실제로 입력에 쓴다. 지금 모델은
#: "점 구름 → 자세" 생성기가 아니라 "(점 구름, 후보 자세) → 점수" 채점기다.
INPUT_ALLOWED = OBSERVATION_INPUT | CANDIDATE_INPUT

_fail = 0


def check(label, value, ok, expect):
    global _fail
    if not ok:
        _fail += 1
    print("  {}  {:44s} {}   (기대 {})".format(
        "통과" if ok else "실패", label, value, expect))


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    data = np.load(path, allow_pickle=True)
    keys = set(data.files)

    print("=== 짝지은 데이터 판정 ===")
    print("파일: {}".format(path))
    print()

    # --- 1. 입력과 정답이 갈려 있는가 (§7-3) ------------------------------
    print("1. 예측기 입력에 시뮬레이터만 아는 값이 안 섞였는가 (§7-3)")
    unknown = keys - INPUT_ALLOWED - LABEL_ONLY
    check("모르는 칸이 없다", sorted(unknown) if unknown else "없음",
          not unknown, "전부 입력용 또는 정답용으로 분류됨")
    check("관측 입력 칸(카메라가 본 것)", sorted(keys & OBSERVATION_INPUT),
          (keys & OBSERVATION_INPUT) == OBSERVATION_INPUT, sorted(OBSERVATION_INPUT))
    check("후보 자세 입력 칸(채점 대상)", sorted(keys & CANDIDATE_INPUT),
          (keys & CANDIDATE_INPUT) == CANDIDATE_INPUT, sorted(CANDIDATE_INPUT))
    # 점 좌표에 물체 이름·성공률 같은 것이 숫자로 숨어들지 않았는지 — 모양으로 본다
    pts = data["points"]
    check("점은 좌표 3개짜리뿐", "{}".format(pts.shape),
          pts.ndim == 2 and pts.shape[1] == 3, "(N, 3)")
    print()

    # --- 2. 점 덩어리가 쓸 만한가 -----------------------------------------
    print("2. 점 덩어리")
    start = data["cloud_start"]
    sizes = np.diff(start)
    check("점 덩어리 장수", len(sizes), len(sizes) > 0, "> 0")
    check("빈 장이 없다", "가장 작은 장 {}점".format(int(sizes.min()) if len(sizes) else 0),
          len(sizes) > 0 and sizes.min() > 0, "> 0점")
    check("점 개수 합이 맞는다", "{} vs {}".format(int(start[-1]), len(pts)),
          int(start[-1]) == len(pts), "같아야 함")
    check("좌표가 유한하다", "NaN/무한 {}개".format(int((~np.isfinite(pts)).sum())),
          bool(np.isfinite(pts).all()), "0개")
    span = float(np.linalg.norm(pts.max(0) - pts.min(0))) if len(pts) else 0.0
    check("물체 크기가 그럴듯한가", "{:.3f} m".format(span),
          0.005 < span < 0.5, "0.005 ~ 0.5 m")
    print()

    # --- 3. 자세(정답)가 쓸 만한가 ----------------------------------------
    print("3. 자세(정답)")
    quat = data["pose_quat"]
    norms = np.linalg.norm(quat, axis=1)
    check("자세 개수", len(quat), len(quat) > 0, "> 0")
    check("방향 길이가 1", "최대 오차 {:.2e}".format(float(np.abs(norms - 1).max())),
          float(np.abs(norms - 1).max()) < 1e-5, "< 1e-5")
    rate = data["pose_rate"]
    check("성공률이 0~1", "{:.2f} ~ {:.2f}".format(float(rate.min()), float(rate.max())),
          bool((rate >= 0).all() and (rate <= 1).all()), "0 ~ 1")
    good = int((rate >= 0.99).sum())
    check("좋은 자세가 있다", "{}개 ({:.0f}%)".format(good, 100.0 * good / max(1, len(rate))),
          good > 0, "> 0개")
    print()

    # --- 4. 가르칠 거리가 있는가 ------------------------------------------
    print("4. 가르칠 거리가 있는가 (물체마다 좋은 자세가 다른가)")
    pose_obj = data["pose_object"]
    names = list(dict.fromkeys(pose_obj.tolist()))
    good_sets = {}
    for name in names:
        sel = (pose_obj == name) & (rate >= 0.99)
        good_sets[name] = {(tuple(np.round(p, 5)), tuple(np.round(q, 5)))
                           for p, q in zip(data["pose_pos"][sel], quat[sel])}
    check("물체 수", len(names), len(names) >= 2, ">= 2종")
    if len(names) >= 2:
        pairs = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                uni = len(good_sets[a] | good_sets[b])
                pairs.append(100.0 * len(good_sets[a] & good_sets[b]) / max(1, uni))
        avg = sum(pairs) / len(pairs)
        check("물체끼리 좋은 자세 겹침", "평균 {:.0f}%".format(avg),
              avg < 90, "< 90% (다 같으면 배울 게 없다)")
    print()

    # --- 5. 좌표 기준이 "실물 D405로도 낼 수 있는" 것인가 -------------------
    # 🛑 2026-09-21 코드 리뷰로 발견: 이 검사가 예전엔 정반대였다 — `frame == "object"`
    #    (물체 기준)이면 **통과**로 쳤다. 그런데 "물체 기준"은 시뮬레이터가 아는
    #    물체의 정답 위치(`env.block.get_root_transform()`)가 있어야만 계산할 수
    #    있다. 실물 D405는 바로 그 정답 위치를 몰라서 이 문제를 푸는 것이므로,
    #    "물체 기준"으로 맞춘 입력은 정답을 미리 알고 문제를 푼 것과 같다
    #    (sim-to-real 입력 누수). 입력 배열에 물체 이름이 안 보인다고 해서 안전한 게
    #    아니다 — 좌표값 자체가 이미 정답으로 정렬돼 있으면 그것도 누수다.
    #    카메라가 스스로 아는 기준(camera)이나 로봇 밑동 기준(base)만 실물에서도
    #    똑같이 만들 수 있다. 설계 원칙: docs/FESTA_PREGRASP_PLAN.md 재검토 필요.
    print("5. 좌표 기준 — 실물 D405 추론 때도 똑같이 만들 수 있는가")
    frame = str(data["frame"]) if "frame" in keys else "(없음)"
    check("좌표 기준이 시뮬레이터 정답 없이도 나오는가", frame,
          frame in DEPLOYABLE_FRAMES,
          "camera 또는 base — 'object'는 실물 추론 때 못 만든다(정답을 몰라서 풀려는 "
          "문제이므로 순환)")
    if frame in LEAKY_FRAMES:
        print("     ⚠️ 이 데이터셋은 물체의 '정답' 자세(시뮬레이터만 아는 값)로 점 구름과")
        print("        자세를 맞춰 정렬했다 — 실물 D405 추론 때는 그 정답을 몰라서 같은")
        print("        방식으로 입력을 못 만든다. build_pose_dataset.py의 좌표 기준을")
        print("        camera 또는 base로 다시 설계해야 한다(2026-09-21 코드 리뷰,")
        print("        재설계는 아직 안 됨 — 이 시험이 그걸 넘어가지 못하게 막는다).")

    print()
    print("=" * 62)
    print("모두 통과" if _fail == 0 else "실패 {}건".format(_fail))
    print("=" * 62)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
