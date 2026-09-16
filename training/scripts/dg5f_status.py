#!/usr/bin/env python3
"""Print the latest ML-Agents scalar values for a DG5F run."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# V2 hand-first 판정 기준: 100k step까지 curriculum이 첫 lesson(stage 1)에
# 머물러 있으면 즉시 중단한다 (docs/archives/V2_TRAINING_FAILURE_ANALYSIS_20260717.md §5).
STAGE_ONE_GATE_STEPS = 100_000
CURRICULUM_PARAMETER = "joint26_stage"


DISPLAY_TAGS = (
    ("Environment/Cumulative Reward", "환경/누적 보상"),
    ("Environment/Episode Length", "환경/에피소드 길이"),
    ("Grasp/Success", "파지/성공률"),
    ("Grasp/MaxContactHoldSeconds", "파지/최대 연속 접촉 시간(초)"),
    ("Grasp/ThumbContactReached", "파지/엄지 접촉 도달률"),
    ("Grasp/OpposingContactReached", "파지/맞은편 손가락 접촉 도달률"),
    ("Grasp/DualContactReached", "파지/엄지·맞은편 동시 접촉 도달률"),
    ("Reach/Success", "도달/성공률"),
    ("Reach/FirstSuccessSeconds", "도달/최초 성공 시간(초)"),
    ("Reach/FinalDistanceMeters", "도달/종료 거리(m)"),
    ("Reach/BestDistanceMeters", "도달/최소 거리(m)"),
    ("Failure/Timeout", "실패/시간 초과율"),
    ("Failure/PostReachTimeout", "실패/도달 후 파지 시간 초과율"),
    ("Failure/BallOutOfBounds", "실패/공 이탈률"),
    ("Failure/NonFinitePhysics", "실패/비유한 물리 발생률"),
    ("Policy/Entropy", "정책/행동 다양성(높을수록 탐색적)"),
    ("Policy/Extrinsic Value Estimate", "정책/예상 미래 누적 보상"),
)

LABEL_DISPLAY_WIDTH = 50


def terminal_width(text: str) -> int:
    """Return monospace terminal columns, accounting for wide Korean glyphs."""
    width = 0
    for character in text:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def pad_terminal(text: str, width: int) -> str:
    return text + " " * max(0, width - terminal_width(text))


def lesson_number(run_dir: Path) -> int | None:
    status_path = run_dir / "run_logs" / "training_status.json"
    if not status_path.is_file():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        return int(status[CURRICULUM_PARAMETER]["lesson_num"])
    except (ValueError, KeyError, TypeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    event_files = sorted(args.run_dir.glob("*/events.out.tfevents.*"))
    if not event_files:
        print(f"아직 지표 event 파일이 없습니다 ({args.run_dir})")
        return 0

    latest: dict[str, object] = {}
    for event_file in event_files:
        accumulator = EventAccumulator(
            str(event_file), size_guidance={"scalars": 0}
        )
        try:
            accumulator.Reload()
        except Exception:
            continue
        for tag in accumulator.Tags().get("scalars", []):
            values = accumulator.Scalars(tag)
            if values and (
                tag not in latest or values[-1].wall_time > latest[tag].wall_time
            ):
                latest[tag] = values[-1]

    if not latest:
        print("아직 기록된 scalar 지표가 없습니다")
        return 0

    max_step = max(value.step for value in latest.values())
    print(f"최신 지표 스텝: {max_step:,}")
    lesson = lesson_number(args.run_dir)
    if lesson is not None:
        print(f"curriculum lesson({CURRICULUM_PARAMETER}): {lesson}")
        if lesson == 0 and max_step >= STAGE_ONE_GATE_STEPS:
            print(
                f"[GATE 위반] {STAGE_ONE_GATE_STEPS:,} step이 지나도록 stage 1"
                " (lesson 0)에 머물러 있습니다. 판정 기준상 즉시 중단 대상입니다"
                " (dg5f v2 stop)."
            )
    for tag, korean_label in DISPLAY_TAGS:
        if tag in latest:
            value = latest[tag]
            formatted_value = f"{value.value:.6g}"
            print(
                f"  {pad_terminal(korean_label, LABEL_DISPLAY_WIDTH)} "
                f"스텝={value.step:>8,}  값={formatted_value:>10}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
