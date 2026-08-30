#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DG5FPicknPlace 학습 런의 현재 상태를 한 화면으로 찍는다.

`show_dg5f_metrics.py`(폐기된 `Reach/*` behavior)와 `dg5f_status.py`(V2 joint26
커리큘럼)는 태그 이름이 이 behavior와 맞지 않는다 — 그 둘을 고치는 대신 여기에
DG5FPicknPlace 전용으로 따로 뒀다.

TensorBoard 웹 UI 없이 학습을 지켜보기 위한 것이므로 출력은 한 화면에 들어가야
한다: 최신값, 최근 구간의 추세, 그리고 목표(SUCCESS_TARGET) 대비 판정.

사용:
    python training/scripts/picknplace_status.py --run-id picknplace_gl_20260830
    python training/scripts/picknplace_status.py --run-id <이름> --window 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "config"))
import rtauto_config as cfg  # noqa: E402

DEFAULT_RESULTS_DIR = cfg.REPO_ROOT / "training" / "results"
BEHAVIOR = "DG5FPicknPlace"
SUCCESS_TAG = "PicknPlace/Success"
# 종료 기준. 90%로 시작했다가 2026-08-30에 99%로 상향됐다 — 레거시 GraspLift
# (UR5e+왼손) 베이스라인이 99.75%였으므로 이 과제 난이도에서 도달 가능한 수치다.
SUCCESS_TARGET = 0.99

# (태그, 표시명, 배율, 단위) — 배율은 사람이 읽기 좋은 단위로 바꾸기 위한 것.
TAGS = (
    (SUCCESS_TAG, "리프트 성공률", 100.0, "%"),
    ("PicknPlace/GraspConfirmed", "파지 확정률", 100.0, "%"),
    ("PicknPlace/BestLiftHeight", "최고 들어올린 높이", 100.0, "cm"),
    ("PicknPlace/ThumbBelowOtherTipsMeters", "엄지 깊이(0 이하 정상)", 100.0, "cm"),
    ("PicknPlace/ContactCount", "접촉 손가락 수", 1.0, ""),
    ("PicknPlace/HandSurfaceContactSeconds", "손-바닥 접촉", 1.0, "s"),
    ("PicknPlace/TopDownAngleDegrees", "손바닥 하향각", 1.0, "deg"),
    ("PicknPlace/ObjectTiltDegrees", "물체 기울기", 1.0, "deg"),
    ("Environment/Cumulative Reward", "누적 보상", 1.0, ""),
    ("Environment/Episode Length", "에피소드 길이", 1.0, "step"),
    ("Environment/Lesson Number/grasp_stage", "커리큘럼 lesson", 1.0, ""),
    ("Policy/Entropy", "엔트로피", 1.0, ""),
)


def load(run_directory: Path) -> EventAccumulator:
    behavior_directory = run_directory / BEHAVIOR
    if not behavior_directory.is_dir():
        raise SystemExit(
            f"런 디렉터리가 없다: {behavior_directory}\n"
            "--run-id 가 맞는지, 학습이 첫 summary를 쓸 만큼 진행됐는지 확인할 것.")
    accumulator = EventAccumulator(str(behavior_directory), size_guidance={"scalars": 0})
    accumulator.Reload()
    return accumulator


def series(accumulator: EventAccumulator, tag: str):
    try:
        return accumulator.Scalars(tag)
    except KeyError:
        return []


def main(argv=None):
    parser = argparse.ArgumentParser(description="DG5FPicknPlace 학습 상태")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--window", type=int, default=10,
                        help="추세를 볼 최근 summary 개수 (기본 10)")
    args = parser.parse_args(argv)

    accumulator = load(args.results_dir / args.run_id)

    steps = None
    print(f"run-id: {args.run_id}")
    for tag, label, scale, unit in TAGS:
        values = series(accumulator, tag)
        if not values:
            print(f"  {label:22s} (없음)")
            continue
        if steps is None:
            steps = values[-1].step
        recent = values[-args.window:]
        latest = values[-1].value * scale
        earlier = recent[0].value * scale
        best = max(v.value for v in values) * scale
        arrow = "→" if abs(latest - earlier) < 1e-9 else ("↑" if latest > earlier else "↓")
        print(f"  {label:22s} {latest:9.3f}{unit:4s} {arrow} "
              f"(최근{len(recent)}개 시작 {earlier:.3f}, 최고 {best:.3f})")

    success = series(accumulator, SUCCESS_TAG)
    print(f"\nstep: {steps:,}" if steps else "\nstep: ?")
    if success:
        recent = success[-args.window:]
        mean_recent = sum(v.value for v in recent) / len(recent)
        print(f"목표 {SUCCESS_TARGET:.0%} 대비: 최근{len(recent)}개 평균 "
              f"{mean_recent:.1%}, 최고 {max(v.value for v in success):.1%}")
        # 단발 스파이크로 조기 종료하지 않도록 최근 구간 평균으로 판정한다.
        print("판정: 목표 도달" if mean_recent >= SUCCESS_TARGET else "판정: 계속 학습")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
