# DG5FGraspReadyReach 학습 실행 가이드

`DG5FGraspReadyReach` 2.0.0을 checkpoint 없이 학습하고 500개 seed로 평가하는 절차다.
정확한 정책 상수는 [`AGENT_SPEC.md`](AGENT_SPEC.md)를 우선한다.

## 1. 환경 확인

```bash
cd <repo-root>   # 과거 전용 학습서버(/home/lkb/...) 경로였음 — 서버 폐지, 지금은 로컬 1대뿐이라 저장소 루트로 이동
source vision/.vision/bin/activate
pip check
mlagents-learn --help >/dev/null
python - <<'PY'
import torch
assert torch.cuda.is_available(), "CUDA-enabled PyTorch is required"
print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY
test -x training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64
python -m unittest discover -s training/tests -p 'test_*.py'
```

기준은 Unity 6000.4.0f1과 `mlagents/mlagents_envs==1.2.0.dev0`이다.

## 2. Scene과 player

Unity에서 다음을 실행한다.

1. **Tools > ML-Agents > Build DG5F GraspPoint Reach Scene**
2. Reach EditMode/PlayMode tests
3. **Tools > ML-Agents > Build DG5F Grasp Ready Reach Linux Player**

산출물:

- scene: `Assets/MLAgents/Reach/DG5F_GraspPointReachTraining.unity`
- prefab: `Assets/MLAgents/Reach/TrainingArea.prefab`
- player: `training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64`
- 20개 영역, Behavior `DG5FGraspReadyReach`, observation/action `37/6`

## 3. 512-step communicator smoke

```bash
ENV_PATH="$PWD/training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64" \
training/scripts/smoke_dg5f_grasp_point_reach.sh
```

trainer 연결, `37/6` shape, 정확한 `max_steps: 512`, checkpoint/ONNX export와 정상 종료를
확인한다. smoke reward나 성공률은 수렴 근거가 아니다.

## 4. 5M fresh PPO

```bash
RUN_ID=dg5f-grasp-ready-reach-5m \
ENV_PATH="$PWD/training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64" \
TORCH_DEVICE=cuda TIME_SCALE=10 \
training/scripts/train_dg5f_grasp_point_reach.sh
```

- 새 run ID로 시작한다.
- `--initialize-from`과 과거 checkpoint는 사용하지 않는다.
- 같은 실험을 중단 후 이어갈 때만 동일 ID와 `--resume`을 사용한다.
- 기본 max steps는 5,000,000이다.
- DISPLAY가 없으면 launcher가 Xvfb를 사용한다.

TensorBoard에서는 reward뿐 아니라 `Reach/LockSuccess`, 최종 거리, 완료 시간, palm 정렬,
최소 Transit clearance, `Failure/UnsafeSurfaceContact`, `Failure/PrematureDescent`를 본다.

```bash
tensorboard --logdir training/results --port 6006
```

## 5. 500-seed 평가

최신 player와 평가할 run의 ONNX/checkpoint를 준비한다.

```bash
DG5F_RUN_ID=dg5f-grasp-ready-reach-5m \
DG5F_EVAL_EPISODES=500 DG5F_EVAL_BASE_SEED=500000 \
training/scripts/run_dg5f_grasp_point_reach_evaluation.sh
```

validator는 다음을 모두 확인한다.

- 정확히 500개 고유 episode/seed와 성공률 90% 이상
- 성공 거리 `<=0.01 m`, 속도 `<=0.05 m/s`, hold `>=0.25 s`
- palm alignment `>=cos(15°)`, upper-cone alignment `>=cos(45°)`
- Transit 최소 clearance `>=0.10 m`
- 패널 접촉, 조기 하강, 비유한 물리, workspace 실패 0건

여러 모델이 통과하면 평균 최종 오차, median 완료 시간, p95 완료 시간 순으로 선택한다.
wrapper는 CSV와 canonical ONNX hash를 승인 JSON에 기록한다.

## 6. 문제 해결

- **Behavior/shape 불일치**: scene을 재생성하고 `DG5FGraspReadyReach`, `37`, `6`을 확인한다.
- **player 없음**: 새 player 경로와 실행 권한을 확인한다.
- **기존 RUN_ID**: 새 실험은 새 ID, 재개만 `--resume`을 사용한다.
- **성공 없음**: waypoint 진입, clearance, palm forward, target 높이와 관절 clamp를 먼저
  PlayMode에서 확인한다. 이전 모델 bootstrap으로 우회하지 않는다.
- **접촉 실패 급증**: safety sensor를 끄지 말고 초기 자세와 waypoint trajectory를 점검한다.
