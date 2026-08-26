# Archived training scripts

여기 5개 `.sh`는 전용 GPU Linux 학습서버(`/workspace/KDT_1_AX_rtauto`,
`/root/venvs/ax310`, `training/builds/*.x86_64`, `tmux`/`xvfb-run`/`nvidia-smi`/
`/proc` 기반 PID 추적) 전제로 작성됐다. 그 서버는 폐지됐고
(`training/README.md`의 과거 주석 참고), 지금은 로컬 Windows 단독
머신(RTX 2080)뿐이다 — `docs/SIM2REAL_ROADMAP.md`가 "1인 풀타임·로컬 단독
머신(RTX 2080, Windows) 체제"로 확정해뒀다.

Windows/Git Bash에서 이 스크립트들이 실패하는 구체적 이유:

- `VENV/bin/python` — Linux venv 레이아웃. Windows venv는 `Scripts/`.
- `ENV_PATH` 기본값이 `.x86_64`(Linux ELF) — Windows에서 실행 자체가 불가능.
- `setsid`, `kill -TERM -- "-$pid"`(음수 PID = process group), `/proc/[0-9]*`,
  `tmux`, `xvfb-run`, `nvidia-smi` — 전부 Linux 전용.

옮긴 파일과 대체 경로:

| 파일 | 역할 | 지금은 |
|---|---|---|
| `dg5f.sh` | 구 GPU 서버의 v1–v4 학습 단계 tmux 오케스트레이션 | 죽음. 대상 config(`dg5f_grasp.yaml`/`v3`/`v4`)도 이미 없다 |
| `grasp.sh` | 구 GPU 서버에서 TensorBoard scalar 확인 | 죽음. `training/scripts/grasp_metrics.py`를 로컬 venv로 직접 실행하면 대체된다 |
| `train_dg5f_grasp.sh` | `mlagents-learn` 래퍼(Xvfb/CUDA 검사 포함) | `training/README.md`의 Windows 수동 절차(`mlagents-learn config.yaml --run-id=...`를 Unity Editor에 붙여 실행)로 대체됨 |
| `train_dg5f_grasp_lift.sh` | 위 wrapper의 GraspLift 특화판(`--transfer`) | 동일. `--transfer` 준비(`prepare_dg5f_grasp_lift_transfer.py`)는 지금 수동으로 먼저 돌려야 한다 — 이걸 감싸는 Windows 스크립트는 아직 없다 |
| `evaluate_dg5f_grasp_lift_topdown.sh` | 체크포인트 복사 → bounded inference → 지표 비교 자동화 | **Windows 대체 경로 없음.** 재현하려면 `training/results/<RUN_ID>`를 수동 복사하고 `mlagents-learn <config> --run-id=<복사한 ID> --resume --inference`를 직접 실행한 뒤 `training/scripts/grasp_metrics.py`로 비교해야 한다 |

이 스크립트들이 참조하던 `training/config/dg5f_grasp_lift_t1_topdown150.yaml` 등
config 파일 자체는 `training/config/`에 그대로 남아 있다 — 실험 기록으로서
`docs/DG5F_GRASP_LIFT.md`의 config 표가 여전히 유효하기 때문이다. 죽은 건
그 config를 자동으로 돌리던 bash 레이어뿐이다.
