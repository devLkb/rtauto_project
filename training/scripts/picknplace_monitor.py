#!/usr/bin/env python3
"""DG5FPicknPlace(grasp+lift) 학습 런의 상태를 읽고 건강도를 판정한다.

`training/scripts/grasp_metrics.py`·`show_dg5f_metrics.py`는 폐기된 behavior의
`Reach/*`·`Grasp/*` 태그에 묶여 있어 이 behavior에는 쓸 수 없다 —
`Dg5fPicknPlaceAgent.RecordOutcome`이 쓰는 태그는 `PicknPlace/*`다.

두 가지 용도:

1. 진행 상황 출력 (기본)
       python training/scripts/picknplace_monitor.py --run-id <RUN_ID>
2. 게이트 판정 — 실패 게이트에 걸리면 종료코드 1
       python training/scripts/picknplace_monitor.py --run-id <RUN_ID> --gate

게이트는 이 behavior가 실제로 빠졌던 실패 양상에서 역산한 것이다(근거는
docs/TRAINING_RUN_LEDGER.md). 목적은 "몇 시간을 더 태울지"를 사람이 매번
눈으로 판단하지 않게 만드는 것 — 걸리면 런을 중단하고 failure로 격리한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.rtauto_config import TRAINING_RESULTS_DIR  # noqa: E402

from tensorboard.backend.event_processing.event_accumulator import (  # noqa: E402
    EventAccumulator,
)

BEHAVIOR = "DG5FPicknPlace"

# (표시명, 태그, 배율, 단위). Dg5fPicknPlaceAgent.RecordOutcome이 쓰는 태그와 1:1.
METRICS = (
    ("누적 보상", "Environment/Cumulative Reward", 1.0, ""),
    ("에피소드 길이", "Environment/Episode Length", 1.0, " step"),
    ("성공률", "PicknPlace/Success", 100.0, "%"),
    ("파지 확정률", "PicknPlace/GraspConfirmed", 100.0, "%"),
    ("접촉 손가락 수", "PicknPlace/ContactCount", 1.0, " 개"),
    ("종료 거리", "PicknPlace/FinalDistanceMeters", 100.0, " cm"),
    ("최고 리프트 높이", "PicknPlace/BestLiftHeight", 100.0, " cm"),
    ("최종 리프트 높이", "PicknPlace/FinalLiftHeight", 100.0, " cm"),
    ("리프트 유지 시간", "PicknPlace/LiftHoldSeconds", 1.0, " s"),
    ("손바닥-물체 정렬 최대", "PicknPlace/MaxPalmFacingAlignment", 1.0, ""),
    ("하향 파지각", "PicknPlace/TopDownAngleDegrees", 1.0, " °"),
    ("엄지 하향각", "PicknPlace/ThumbDownAngleDegrees", 1.0, " °"),
    ("물체 최대 기울기", "PicknPlace/MaxObjectTiltDegrees", 1.0, " °"),
    ("손-바닥 접촉 시간", "PicknPlace/HandSurfaceContactSeconds", 1.0, " s"),
    ("팔 액션 변화율", "PicknPlace/MeanArmActionRate", 1.0, ""),
    ("완료 시간", "PicknPlace/CompletionSeconds", 1.0, " s"),
    ("커리큘럼 단계", "Curriculum/GraspStage", 1.0, ""),
    ("정책 엔트로피", "Policy/Entropy", 1.0, ""),
    ("가치 추정", "Policy/Extrinsic Value Estimate", 1.0, ""),
)

FAILURE_TAG_PREFIX = "Failure/"


@dataclass(frozen=True)
class Gate:
    """단계 게이트. `at_step`을 넘겼는데 조건을 못 채우면 실패로 본다."""

    name: str
    at_step: int
    tag: str
    minimum: float
    why: str


# 임계값 근거는 docs/TRAINING_RUN_LEDGER.md의 "게이트 근거" 절.
GATES = (
    Gate(
        "G1 접근",
        300_000,
        "PicknPlace/MaxPalmFacingAlignment",
        0.0,
        "손바닥이 물체를 한 번도 향하지 않으면 DirectionalApproachPotential이"
        " 영원히 0이라 접근 그래디언트 자체가 없다 — 정지 정책 데드락.",
    ),
    Gate(
        "G2 접촉",
        800_000,
        "PicknPlace/ContactCount",
        0.20,
        "80만 스텝까지 큐브를 평균 0.2개 손가락도 못 건드리면 파지 학습은 시작조차 못 한 것.",
    ),
    Gate(
        "G3 파지",
        2_000_000,
        "PicknPlace/GraspConfirmed",
        0.05,
        "접촉은 하는데 200만 스텝까지 파지 확정이 5% 미만이면 파지 계약(대향각/케이지)이"
        " 이 손·큐브 조합에서 성립하지 않는다는 신호.",
    ),
    Gate(
        "G4 성공",
        4_000_000,
        "PicknPlace/Success",
        0.10,
        "400만 스텝에서 리프트 성공률 10% 미만이면 남은 100만 스텝으로 뒤집히지 않는다.",
    ),
)


def load_scalars(directory: Path) -> dict[str, list[tuple[int, float]]]:
    """런 디렉터리의 tfevents 파일들을 스텝 기준으로 병합한다.

    --resume으로 이어붙인 런은 events 파일이 여러 개 생기고 스텝 구간이 겹친다.
    mtime 오름차순으로 읽어 나중 파일이 같은 스텝을 덮어쓰게 한다.
    """
    merged: dict[str, dict[int, float]] = {}
    files = sorted(
        directory.glob("events.out.tfevents.*"), key=lambda path: path.stat().st_mtime
    )
    for path in files:
        accumulator = EventAccumulator(str(path), size_guidance={"scalars": 0})
        accumulator.Reload()
        for tag in accumulator.Tags().get("scalars", []):
            values = merged.setdefault(tag, {})
            for event in accumulator.Scalars(tag):
                values[event.step] = event.value
    return {tag: sorted(values.items()) for tag, values in merged.items()}


def window_mean(points: list[tuple[int, float]], count: int) -> float | None:
    if not points:
        return None
    window = points[-count:] if count > 0 else points
    return sum(value for _, value in window) / len(window)


def best_so_far(points: list[tuple[int, float]]) -> float | None:
    if not points:
        return None
    return max(value for _, value in points)


def latest_step(scalars: dict[str, list[tuple[int, float]]]) -> int:
    steps = [points[-1][0] for points in scalars.values() if points]
    return max(steps) if steps else 0


def format_value(value: float | None, scale: float, unit: str) -> str:
    if value is None:
        return "-"
    return f"{value * scale:.3f}{unit}"


def report(scalars: dict[str, list[tuple[int, float]]], window: int) -> None:
    step = latest_step(scalars)
    print(f"최신 스텝: {step:,}")
    print(f"{'지표':<24}{'최근 평균':>16}{'직전 구간':>16}{'변화':>12}")
    print("-" * 68)
    for label, tag, scale, unit in METRICS:
        points = scalars.get(tag, [])
        recent = window_mean(points, window)
        earlier = window_mean(points[:-window], window) if len(points) > window else None
        delta = (
            f"{(recent - earlier) * scale:+.3f}"
            if recent is not None and earlier is not None
            else "-"
        )
        print(
            f"{label:<24}{format_value(recent, scale, unit):>16}"
            f"{format_value(earlier, scale, unit):>16}{delta:>12}"
        )

    failures = {
        tag: window_mean(points, window)
        for tag, points in scalars.items()
        if tag.startswith(FAILURE_TAG_PREFIX)
    }
    if failures:
        print("\n실패 사유 (요약 구간당 건수, Sum 집계):")
        for tag, value in sorted(failures.items(), key=lambda item: -(item[1] or 0)):
            print(f"  {tag[len(FAILURE_TAG_PREFIX):]:<24}{value:.1f}")


def evaluate_gates(
    scalars: dict[str, list[tuple[int, float]]],
) -> list[tuple[Gate, str, float | None]]:
    """각 게이트를 (게이트, 판정, 관측값)으로 돌려준다. 판정: PASS/FAIL/PENDING."""
    step = latest_step(scalars)
    results = []
    for gate in GATES:
        points = scalars.get(gate.tag, [])
        # 게이트는 "한 번이라도 넘겼는가"로 본다. 학습 중 일시적 후퇴로
        # 이미 통과한 단계가 실패로 뒤집히면 오탐이 된다.
        observed = best_so_far(points)
        if observed is not None and observed > gate.minimum:
            results.append((gate, "PASS", observed))
        elif step < gate.at_step:
            results.append((gate, "PENDING", observed))
        else:
            results.append((gate, "FAIL", observed))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="mlagents-learn --run-id 값")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=TRAINING_RESULTS_DIR,
        help="런 디렉터리의 부모. 기본값은 config/rtauto_config.py의 TRAINING_RESULTS_DIR",
    )
    parser.add_argument(
        "--window", type=int, default=10, help="평균을 낼 최근 요약 구간 수 (기본 10)"
    )
    parser.add_argument("--gate", action="store_true", help="게이트 판정만 하고 종료코드로 알린다")
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON 출력")
    arguments = parser.parse_args()

    directory = arguments.results_dir / arguments.run_id / BEHAVIOR
    if not directory.is_dir():
        parser.error(f"런 디렉터리가 없다: {directory}")

    scalars = load_scalars(directory)
    if not scalars:
        parser.error(f"tfevents 스칼라를 하나도 못 읽었다: {directory}")

    gates = evaluate_gates(scalars)
    failed = [item for item in gates if item[1] == "FAIL"]

    if arguments.json:
        print(
            json.dumps(
                {
                    "run_id": arguments.run_id,
                    "step": latest_step(scalars),
                    "metrics": {
                        tag: window_mean(scalars.get(tag, []), arguments.window)
                        for _, tag, _, _ in METRICS
                    },
                    "gates": [
                        {"name": gate.name, "verdict": verdict, "observed": observed}
                        for gate, verdict, observed in gates
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if not arguments.gate:
            report(scalars, arguments.window)
            print()
        print("게이트:")
        for gate, verdict, observed in gates:
            shown = "-" if observed is None else f"{observed:.4f}"
            print(
                f"  [{verdict:<7}] {gate.name} @ {gate.at_step:,} step"
                f" — {gate.tag} 관측 최대 {shown} (> {gate.minimum} 필요)"
            )
            if verdict == "FAIL":
                print(f"            근거: {gate.why}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
