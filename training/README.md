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
- 전이 준비: `scripts/prepare_dg5f_grasp_lift_transfer.py`
- Linux player: `builds/DG5FGraspLift/DG5FGraspLift.x86_64`

> `scripts/train_dg5f_grasp_lift.sh`와 `scripts/evaluate_dg5f_grasp_lift_topdown.sh`는
> `training/archives/scripts/`로 옮겼다 — 전용 GPU Linux 학습서버(`/root/venvs/ax310`,
> `tmux`/`xvfb-run`/`setsid` 전제) 전용 스크립트였는데 그 서버가 폐지되고 지금은
> 로컬 Windows 단독 머신(RTX 2080)뿐이라 애초에 실행이 안 된다. 이유는
> `training/archives/scripts/README.md` 참고. `--transfer` 전이는 이제
> `prepare_dg5f_grasp_lift_transfer.py`를 직접 호출해 준비해야 한다.

Windows에서 빌드된 Linux 플레이어 없이 **Unity Editor에 직접 붙여서** 시작하는
방법(초보자 기준):

```cmd
vision\.vision\Scripts\activate
mlagents-learn training\config\dg5f_grasp_lift.yaml --run-id=<이름>
```

- 콘솔에 "Start training by pressing the Play button in the Unity Editor."가 뜨면
  Unity에서 `DG5FGraspLift` behavior가 들어있는 씬을 열고 ▶ Play.
- 기본 대기시간은 60초 — Unity 로딩이 오래 걸리면 `--timeout-wait=300`처럼 늘린다.
- 중단 후 이어서: 같은 `--run-id`에 `--resume` 추가.
- **GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 반드시 확인**
  (`cpu`로 두면 이 ml-agents dev 빌드의 전역 디바이스 버그로 죽음 — 근거는
  [`README.md`](../README.md) Python 절 참고).
- 모니터링: `tensorboard --logdir training/results` 실행 후 `http://localhost:6006/`.

## DG5F Grasp + Place 인프라, 현재는 Grasp + Lift (`DG5FPicknPlace`)

UR16e + DG-5F-M-R **오른손**으로 큐브를 바닥의 랜덤 위치에서 집어 들어올리는
behavior. GraspLift(UR5e + 왼손)의 검증된 접근·파지·리프트 보상/판정
아키텍처를 확정된 하드웨어(UR16e + 오른손)로 그대로 포팅한 것 — 동일한 12cm
사각기둥(0.035×0.12×0.035 m) 목표물, 동일한 커리큘럼 구조.

> 2026-08-26에 이 behavior는 잠깐 place(운반+배치) 단계까지 포함하는 진짜
> pick-and-place로 확장됐었다(플랫폼+마커 추가). 웨이퍼 스펙 도착 전 place
> 보상 셰이핑을 미리 연습해두려는 시도였는데, 하루 만에 되돌렸다 — 확정
> 하드웨어(UR16e+오른손) 위에서 grasp+lift부터 먼저 다지는 편이 지금 시점에
> 더 값지다고 판단해서다. place 설계 기록은
> [`docs/DG5F_PICKNPLACE.md`](../docs/DG5F_PICKNPLACE.md)와 git 이력에
> 남아있다.

- Behavior/spec: `DG5FPicknPlace` / `3.0.0`
- observations/actions: `57/7` (팔 6축 + 손 closure 1축) — GraspLift와 동일한
  슬롯 구성
- 대상: GraspLift 블록과 완전히 동일한 큐브(0.035×0.12×0.035 m) — 검증된
  파지 아퍼처를 그대로 재사용
- config: `config/dg5f_picknplace.yaml`
- Linux player: `builds/DG5FPicknPlace/DG5FPicknPlace.x86_64`

**사전 준비** (한 번만): Unity 메뉴에서 순서대로 실행.

1. **Tools > Robots > Create UR16e DG5F Right Prefab** — `UR16eDG5FRight_Preview.unity`의
   로봇을 `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab`로 저장 (씬 자체는 건드리지 않음).
2. **Tools > ML-Agents > Build DG5F PicknPlace Training Scene** — 위 prefab으로부터
   `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity`를 절차적으로 생성
   (20개 병렬 학습 영역). 이 씬은 빌드 산출물이므로 직접 편집하지 않고, 바뀔 때마다
   이 메뉴를 다시 실행한다.

Windows에서 Unity Editor에 직접 붙여서 시작하는 방법(위 GraspLift 절차와 동일 패턴):

```cmd
vision\.vision\Scripts\activate
mlagents-learn training\config\dg5f_picknplace.yaml --run-id=<이름>
```

- 콘솔에 "Start training by pressing the Play button in the Unity Editor."가 뜨면
  Unity에서 `DG5F_PicknPlaceTraining.unity`를 열고 ▶ Play.
- **GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 반드시 확인** (GraspLift와
  동일한 이유 — [`README.md`](../README.md) Python 절 참고).
- 모니터링: `tensorboard --logdir training/results` 실행 후 `http://localhost:6006/`.

> `docs/SIM2REAL_ROADMAP.md`의 "파지는 RL, 이송·배치는 결정적 플래너" 분업은
> **실제 FOUP 이송**(모바일 매니퓰레이터가 FOUP 자체를 옮기는 것)에 대한 결정이고
> 지금도 유효하다. 이 behavior는 그것과 다른 목적 — **place 보상 셰이핑 자체를
> 구조화하는 연습/기반 다지기**로, 작은 큐브를 고정 플랫폼 위 랜덤 지점에 놓는
> 순수 RL 태스크다.
