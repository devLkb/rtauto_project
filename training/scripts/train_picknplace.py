#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DG5FPicknPlace(grasp + lift) 학습 런처.

`mlagents-learn`을 직접 치는 대신 이걸 쓰는 이유는 하나다: 플레이어 경로·포트·
병렬 수가 머신마다 다르고, 그 값들의 정본은 `config/rtauto_config.py` + `.env`이기
때문이다(CLAUDE.md 원칙 1). 명령줄에 경로와 포트를 손으로 적기 시작하면 새 PC에서
반드시 어긋난다.

기본 동작은 **headless 병렬 학습**이다 — 빌드된 Windows/Linux 플레이어를
`--num-envs`개 띄우고 `--no-graphics`로 렌더링을 끈다. Unity Editor에 붙이는
단일 환경 방식이 필요하면 `--editor`.

사용 예:
    python training/scripts/train_picknplace.py --run-id gl_20260830
    python training/scripts/train_picknplace.py --run-id gl_20260830 --resume
    python training/scripts/train_picknplace.py --run-id smoke --num-envs 2 --max-steps 20000
    python training/scripts/train_picknplace.py --run-id gl_editor --editor

`--` 뒤의 인자는 mlagents-learn으로 그대로 넘어간다.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "config"))
import rtauto_config as cfg  # noqa: E402

REPO_ROOT = cfg.REPO_ROOT
DEFAULT_CONFIG = REPO_ROOT / "training" / "config" / "dg5f_picknplace.yaml"
DEFAULT_RESULTS_DIR = REPO_ROOT / "training" / "results"
# mlagents-learn 대신 이 셔틀을 부른다 — 레거시 ONNX exporter 선택과 cuda 기본
# 디바이스의 스레드 전파를 담당한다. 자세한 이유는 파일 헤더 참고.
LEARN_ENTRYPOINT = REPO_ROOT / "training" / "scripts" / "mlagents_learn_compat.py"
# 40영역 x N 플레이어가 동시에 로봇을 로드하면 기본 60초 안에 첫 핸드셰이크가 안 온다.
DEFAULT_TIMEOUT_WAIT = 600


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="DG5FPicknPlace (grasp + lift) 학습 실행",
        epilog="`--` 뒤 인자는 mlagents-learn으로 그대로 전달된다.")
    parser.add_argument("--run-id", required=True,
                        help="mlagents-learn --run-id. 이어서 학습하려면 --resume와 같이 쓴다.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"트레이너 설정 yaml (기본 {DEFAULT_CONFIG.relative_to(REPO_ROOT)})")
    # 기본을 None으로 두고 나중에 채운다: --editor는 구조상 환경이 1개뿐이라,
    # .env의 병렬 수를 그대로 받으면 사용자가 아무 잘못도 안 했는데 에러가 난다.
    parser.add_argument("--num-envs", type=int, default=None,
                        help="병렬 플레이어 프로세스 수 "
                             f"(기본: .env의 RTAUTO_TRAIN_NUM_ENVS={cfg.TRAIN_NUM_ENVS}, "
                             "--editor면 1)")
    parser.add_argument("--base-port", type=int, default=cfg.PORT_MLAGENTS_BASE,
                        help="트레이너<->플레이어 gRPC 시작 포트 (기본: .env의 RTAUTO_PORT_MLAGENTS_BASE)")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--max-steps", type=int, default=None,
                        help="yaml의 max_steps를 덮어쓴 임시 설정으로 실행한다 (스모크 테스트용). "
                             "mlagents-learn에는 max_steps CLI 플래그가 없어서 파일을 만들어 넘긴다.")
    parser.add_argument("--editor", action="store_true",
                        help="빌드된 플레이어 대신 Unity Editor에 붙는다 (환경 1개, 렌더링 켜짐)")
    parser.add_argument("--graphics", action="store_true",
                        help="headless(--no-graphics)를 끈다. 화면으로 학습을 지켜보고 싶을 때만.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="같은 run-id의 기존 결과를 덮어쓴다")
    parser.add_argument("--timeout-wait", type=int, default=DEFAULT_TIMEOUT_WAIT)
    parser.add_argument("--keep-stale-players", action="store_true",
                        help="시작 전 남아있는 플레이어 프로세스를 정리하지 않는다")
    parser.add_argument("--dry-run", action="store_true",
                        help="실행할 명령만 출력하고 끝낸다")
    parser.add_argument("passthrough", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.num_envs is None:
        args.num_envs = 1 if args.editor else cfg.TRAIN_NUM_ENVS
    return args


def resolve_player():
    player = cfg.picknplace_player_path()
    if player is None:
        raise SystemExit(
            "플레이어 경로 설정이 비어있다. .env(.example)의 "
            "DG5F_PICKNPLACE_WINDOWS_BUILD_OUTPUT / _PLAYER_NAME"
            "(Linux는 DG5F_PICKNPLACE_BUILD_OUTPUT / _PLAYER_NAME)을 확인할 것.")
    if not player.is_file():
        raise SystemExit(
            f"빌드된 플레이어가 없다: {player}\n"
            "Unity에서 Tools > ML-Agents > Build DG5F PicknPlace "
            f"{'Windows' if sys.platform.startswith('win') else 'Linux'} Player 를 실행하거나,\n"
            "배치모드로: unity -quit -batchmode -projectPath unity -executeMethod "
            "KDT.PicknPlaceTraining.Editor.PicknPlaceTrainingBuild."
            f"Build{'Windows' if sys.platform.startswith('win') else 'Linux'}Player\n"
            "(--editor 로 Unity Editor에 직접 붙어 학습할 수도 있다 — 환경 1개.)")
    return player


def kill_stale_players(player):
    """이전 런이 남긴 플레이어 프로세스를 정리한다.

    ml-agents는 종료 시 "A SubprocessEnvManager worker did not shut down
    correctly"를 남기며 플레이어를 놓치는 일이 잦다. 살아남은 프로세스는 CPU를
    계속 먹어 다음 런의 처리량을 그대로 갉아먹고(--num-envs 벤치마크를 조용히
    왜곡한다), base_port를 물고 있으면 다음 런의 핸드셰이크까지 막는다.
    """
    name = player.name
    if sys.platform.startswith("win"):
        # tasklist는 일치하는 게 없어도 종료코드 0이라 출력에서 이름을 찾아야 한다.
        probe = ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"]
        kill = ["taskkill", "/IM", name, "/F"]
        found_by_name = True
    else:
        # pgrep은 반대로 출력이 PID 목록이라 이름이 안 나온다 — 종료코드로 판단한다.
        probe = ["pgrep", "-f", name]
        kill = ["pkill", "-f", name]
        found_by_name = False

    try:
        found = subprocess.run(probe, capture_output=True, text=True)
    except OSError:
        return
    running = name in (found.stdout or "") if found_by_name else found.returncode == 0
    if not running:
        return
    print(f"[train_picknplace] 이전 런의 {name} 프로세스가 남아있다 - 정리 후 시작한다.")
    subprocess.run(kill, capture_output=True)


def resolve_config(args):
    """실행에 쓸 트레이너 설정 경로. --max-steps가 있으면 오버라이드 사본을 만든다.

    mlagents-learn은 max_steps를 CLI로 받지 않는다(behaviors 아래 값이 유일한 출처).
    스모크 테스트마다 정식 설정을 편집했다 되돌리는 건 사고의 원천이라, 파생 파일을
    results 폴더에 남겨 어떤 값으로 돌렸는지도 함께 기록한다.
    """
    if args.max_steps is None:
        return args.config

    text = args.config.read_text(encoding="utf-8")
    patched, count = re.subn(r"^(\s*max_steps:\s*)\d+",
                             lambda m: f"{m.group(1)}{args.max_steps}",
                             text, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(
            f"{args.config}에서 max_steps를 정확히 하나 찾지 못했다 (발견 {count}개). "
            "--max-steps 없이 실행하거나 설정 파일을 확인할 것.")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    override = args.results_dir / f"{args.run_id}_config.yaml"
    override.write_text(patched, encoding="utf-8")
    print(f"[train_picknplace] max_steps={args.max_steps} 오버라이드 -> {override}")
    return override


def build_command(args):
    if not args.config.is_file():
        raise SystemExit(f"트레이너 설정이 없다: {args.config}")
    config_path = resolve_config(args)

    # -X utf8: ml-agents가 설정 yaml을 open()의 로케일 기본 인코딩으로 읽는다. 한국어
    # Windows(cp949)에서는 주석에 em-dash나 한글이 하나만 있어도 UnicodeDecodeError로
    # 죽는다 — 이 저장소 설정 파일들은 둘 다 쓴다. Python UTF-8 모드를 켜면 로케일과
    # 무관하게 UTF-8로 읽으므로, 어느 PC에서든 같은 파일이 그대로 돈다(원칙 2).
    command = [sys.executable, "-X", "utf8", str(LEARN_ENTRYPOINT), str(config_path),
               f"--run-id={args.run_id}",
               f"--results-dir={args.results_dir}",
               f"--timeout-wait={args.timeout_wait}"]

    if args.editor:
        if args.num_envs > 1:
            raise SystemExit(
                "--editor는 환경을 1개만 쓸 수 있다(Unity Editor 인스턴스 하나). "
                "병렬 학습은 빌드된 플레이어로만 가능하다 — --editor를 빼고 다시 실행할 것.")
    else:
        player = resolve_player()
        if not args.keep_stale_players:
            kill_stale_players(player)
        command.append(f"--env={player}")
        command.append(f"--num-envs={args.num_envs}")
        command.append(f"--base-port={args.base_port}")
        if not args.graphics:
            command.append("--no-graphics")

    if args.resume:
        command.append("--resume")
    if args.force:
        command.append("--force")

    extra = [a for a in args.passthrough if a != "--"]
    command.extend(extra)
    return command


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    command = build_command(args)

    total_agents = cfg.TRAIN_AREAS * (1 if args.editor else args.num_envs)
    print(f"[train_picknplace] 영역/환경={cfg.TRAIN_AREAS}, 환경={1 if args.editor else args.num_envs}, "
          f"총 에이전트~{total_agents}, headless={not (args.editor or args.graphics)}")
    print("[train_picknplace] " + " ".join(command))
    if args.dry_run:
        return 0

    args.results_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.call(command, cwd=str(REPO_ROOT), env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
