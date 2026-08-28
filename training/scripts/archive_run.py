#!/usr/bin/env python3
"""끝난 학습 런을 failure/ 또는 legacy/로 격리하고 근거를 문서로 남긴다.

왜 필요한가: 실패한 정책을 `training/results/` 안에 계속 쌓아두면 (a) 어느
체크포인트가 살아있는 기준선인지 사람이 매번 다시 판단해야 하고, (b) `--resume`
이나 `--initialize-from`이 죽은 런을 가리키는 사고가 난다. 격리 자체보다
**왜 실패했는지를 런 옆에 남기는 것**이 이 스크립트의 핵심이다.

    python training/scripts/archive_run.py --run-id pnp_v4_headless \
        --to failure --reason "G2 접촉 게이트 실패: 80만 스텝 ContactCount 0.0"

디렉터리 규칙과 경로 정본은 config/rtauto_config.py (TRAINING_RESULTS_DIR /
TRAINING_FAILURE_DIR / TRAINING_LEGACY_DIR). 판정 이력의 정본은
docs/TRAINING_RUN_LEDGER.md — 이 스크립트가 붙여넣을 표 행을 출력한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.rtauto_config import (  # noqa: E402
    TRAINING_FAILURE_DIR,
    TRAINING_LEGACY_DIR,
    TRAINING_RESULTS_DIR,
)

from tensorboard.backend.event_processing.event_accumulator import (  # noqa: E402
    EventAccumulator,
)

DESTINATIONS = {"failure": TRAINING_FAILURE_DIR, "legacy": TRAINING_LEGACY_DIR}
SUMMARY_NAME = "RUN.md"


def find_event_directories(run_directory: Path) -> list[Path]:
    """런 안에서 tfevents를 담고 있는 behavior 디렉터리들."""
    directories = {
        path.parent
        for path in run_directory.rglob("events.out.tfevents.*")
        # 이미 격리된 런을 다시 훑지 않도록 목적지 디렉터리는 건너뛴다.
        if path.is_file()
    }
    return sorted(directories)


def final_scalars(directory: Path) -> tuple[int, dict[str, float]]:
    """behavior 디렉터리의 마지막 스텝과 태그별 마지막 값."""
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

    step = max((max(values) for values in merged.values() if values), default=0)
    latest = {tag: values[max(values)] for tag, values in merged.items() if values}
    return step, latest


def write_summary(
    destination: Path, run_id: str, source: Path, reason: str, verdict: str
) -> Path:
    lines = [
        f"# {run_id} — {verdict}",
        "",
        f"- 격리 일자: `{dt.date.today().isoformat()}`",
        f"- 원래 위치: `{source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source}`",
        f"- 격리 위치: `{destination.relative_to(REPO_ROOT) if destination.is_relative_to(REPO_ROOT) else destination}`",
        "",
        "## 판정 근거",
        "",
        reason,
        "",
    ]

    for event_directory in find_event_directories(destination):
        step, latest = final_scalars(event_directory)
        label = event_directory.relative_to(destination)
        lines += [
            f"## 최종 지표 — `{label}` (step {step:,})",
            "",
            "| 태그 | 마지막 값 |",
            "|---|---|",
        ]
        for tag, value in sorted(latest.items()):
            lines.append(f"| `{tag}` | {value:.5f} |")
        lines.append("")

    configuration = destination / "configuration.yaml"
    if configuration.is_file():
        lines += [
            "## 설정",
            "",
            f"실행에 쓰인 설정 전문은 이 폴더의 `{configuration.name}`에 그대로 보존돼 있다.",
            "",
        ]

    summary = destination / SUMMARY_NAME
    summary.write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="옮길 런 디렉터리 이름")
    parser.add_argument(
        "--to", required=True, choices=sorted(DESTINATIONS), help="격리 대상 구분"
    )
    parser.add_argument(
        "--reason", required=True, help="판정 근거 (게이트 이름·관측값까지 구체적으로)"
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=TRAINING_RESULTS_DIR,
        help="런 디렉터리의 현재 부모. 기본값은 TRAINING_RESULTS_DIR",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="옮기지 않고 무엇을 할지만 출력"
    )
    arguments = parser.parse_args()

    source = arguments.source_dir / arguments.run_id
    if not source.is_dir():
        parser.error(f"런 디렉터리가 없다: {source}")

    destination_root = DESTINATIONS[arguments.to]
    destination = destination_root / arguments.run_id
    if destination.exists():
        parser.error(f"격리 위치에 같은 이름이 이미 있다: {destination}")

    verdict = "실패 격리" if arguments.to == "failure" else "레거시 보존"
    if arguments.dry_run:
        print(f"[dry-run] {source} -> {destination} ({verdict})")
        return 0

    destination_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    summary = write_summary(destination, arguments.run_id, source, arguments.reason, verdict)

    print(f"옮김: {source} -> {destination}")
    print(f"요약 작성: {summary}")
    print("\ndocs/TRAINING_RUN_LEDGER.md에 붙여넣을 행:")
    print(
        f"| `{arguments.run_id}` | {dt.date.today().isoformat()} | {verdict} | "
        f"`{destination.relative_to(REPO_ROOT)}` | {arguments.reason.splitlines()[0]} |"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
