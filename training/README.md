# DG5FGraspReadyReach training

## Linux 빌드 출력 설정

저장소 루트의 `.env.example`에 공유 기본값이 있다. 이를 `.env`로 복사하면
Unity Linux 빌드의 출력 폴더와 실행 파일명을 사용자별로 변경할 수 있다.

```bash
cp .env.example .env
```

상대 경로는 저장소 루트를 기준으로 해석한다. 적용 우선순위는
`프로세스 환경변수 > .env > .env.example`이며, `.env`는 Git에 포함되지 않는다.

현재 활성 학습 계약은 열린 DG5F 손을 공 위로 안전하게 이동하고 파지 준비 자세에서
팔을 고정하는 단일 정책이다.

- Behavior/spec: `DG5FGraspReadyReach` / `2.0.0`
- observations/actions: `37/6`
- policy 제어: UR5e 팔 6축
- 비-policy 상태: DG5F 손 20관절을 prefab의 열린 자세로 유지
- 접근: 공 10 cm 위 waypoint → 5 cm 수평 범위 안에서 하강
- 금지: root base 이외 로봇의 패널 접촉, 조기 하강, 바닥 쓸기
- 잠금: 1 cm, 0.05 m/s, palm 15°, 상부 45° cone을 0.25초 유지
- 학습: checkpoint/curriculum 없는 fresh PPO, 최대 5M steps

정확한 계약은 [`docs/AGENT_SPEC.md`](../docs/AGENT_SPEC.md), 실행 순서는
[`docs/ML_AGENTS_TRAINING_GUIDE.md`](../docs/ML_AGENTS_TRAINING_GUIDE.md)를 따른다.

## Active files

- PPO config: `config/dg5f_grasp_point_reach.yaml`
- trainer: `scripts/train_dg5f_grasp_point_reach.sh`
- 512-step smoke: `scripts/smoke_dg5f_grasp_point_reach.sh`
- deterministic evaluation: `scripts/run_dg5f_grasp_point_reach_evaluation.sh`
- CSV validator: `scripts/evaluate_dg5f_grasp_point_reach.py`
- Linux player: `builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64`

`builds/`, `results/`, `logs/`의 과거 Grasp/StableGrasp/PointReach 산출물은 새 Behavior와
호환되는 checkpoint가 아니다.

## Setup and tests

```bash
cd <repo-root>   # 과거 전용 학습서버(/home/lkb/...) 경로였음 — 서버 폐지, 지금은 로컬 1대뿐이라 저장소 루트로 이동
source vision/.vision/bin/activate
pip check
python -m unittest discover -s training/tests -p 'test_*grasp_point_reach*.py'
```

Unity 메뉴에서 다음을 순서대로 실행한다.

1. **Tools > ML-Agents > Build DG5F GraspPoint Reach Scene**
2. Reach EditMode/PlayMode tests
3. **Tools > ML-Agents > Build DG5F Grasp Ready Reach Linux Player**

## Smoke

```bash
ENV_PATH="$PWD/training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64" \
training/scripts/smoke_dg5f_grasp_point_reach.sh
```

smoke는 communicator와 37/6 shape 검증이며 수렴 증거가 아니다.

## 5M training

```bash
RUN_ID=dg5f-grasp-ready-reach-5m \
ENV_PATH="$PWD/training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64" \
TORCH_DEVICE=cuda TIME_SCALE=10 \
training/scripts/train_dg5f_grasp_point_reach.sh
```

새 실험에는 새 run ID를 사용한다. `--initialize-from`은 금지하며, `--resume`은 같은
실험을 중단 후 재개할 때만 사용한다.

## Approval evaluation

```bash
DG5F_RUN_ID=dg5f-grasp-ready-reach-5m \
DG5F_EVAL_EPISODES=500 DG5F_EVAL_BASE_SEED=500000 \
training/scripts/run_dg5f_grasp_point_reach_evaluation.sh
```

성공률 90% 이상과 모든 정밀 잠금 조건, 패널 접촉/조기 하강/clearance/물리/workspace
안전 조건을 validator가 함께 검사한다.

## DG5F Grasp + Lift (`DG5FGraspLift`)

파지 후 들어올리기까지 학습하는 새 behavior. 설계·보상·판정 근거는
[`docs/DG5F_GRASP_LIFT.md`](../docs/DG5F_GRASP_LIFT.md).

- Behavior/spec: `DG5FGraspLift` / `1.0.0`
- observations/actions: `57/7` (팔 6축 + 손 closure 1축)
- 대상: Cube 0.055 × 0.10 × 0.055 m, 0.12 kg
- config: `config/dg5f_grasp_lift.yaml`
- trainer: `scripts/train_dg5f_grasp_lift.sh`
- 전이 준비: `scripts/prepare_dg5f_grasp_lift_transfer.py`
- Linux player: `builds/DG5FGraspLift/DG5FGraspLift.x86_64`

```bash
source vision/.vision/bin/activate
RUN_ID=dg5f_grasp_lift_5m TIME_SCALE=20 TORCH_DEVICE=cpu \
  training/scripts/train_dg5f_grasp_lift.sh start --transfer
```
