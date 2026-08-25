# DG5FGraspReadyReach 인수인계 (2026-07-21)

> **빠른 시연 경로:** 새 `37/6` 정책 대신 기존 `DG5FGrasp` `57/7` 모델을
> 유지하면서 바닥 안전 제한과 closure 무시 handoff를 적용하는 절차는
> [DG5F_GRASP_57X7_FLOOR_SAFE_DEMO.md](DG5F_GRASP_57X7_FLOOR_SAFE_DEMO.md)를 따른다.

## 구현 완료

- Behavior/spec `DG5FGraspReadyReach` / `2.0.0`, observation/action `37/6`
- RL은 팔 6축만 제어하고 DG5F 손 20관절은 prefab의 열린 target으로 유지
- 공 10 cm 위 waypoint를 먼저 통과한 뒤 수평 거리 5 cm 안에서 하강
- root base를 제외한 움직이는 robot collider의 패널 접촉은 즉시 실패
- 조기 하강/바닥 쓸기 trajectory는 `PrematureDescent` 실패
- 거리 1 cm, 속도 0.05 m/s, palm 15°, 상부 45° cone을 0.25초 유지하면 팔 latch
- 배포 모드의 latch는 `ReleaseArmLock()` 호출 전까지 유지
- 20개 병렬 영역, kinematic solid target, fresh PPO와 500-seed 평가 계약 반영
- 이전 PointReach checkpoint 변환 및 curriculum 파일 제거

## 검증 완료

- Unity EditMode: **13/13 pass**
- Unity PlayMode: **7/7 pass**
- 활성 ReadyReach Python 계약/평가기: **14/14 pass**
- 전체 `training/tests`: **27/27 pass**
- Linux player 빌드 성공:
  `training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64`
- built-player 512-step smoke 성공
  - Unity communicator 1.5.0 연결
  - brain `DG5FGraspReadyReach` 연결
  - ONNX export 성공
  - 결과: `training/results/dg5f-grasp-ready-reach-smoke-512/`
- shell syntax, Python compile, C# compile 및 diff whitespace 검사 수행

## VDI에서 남은 필수 작업

현재 로컬 Python 환경은 CPU 전용이므로 본학습은 CUDA가 설치된 VDI에서 수행한다.
먼저 VDI checkout과 player가 현재 계약인지 확인한다.

```bash
cd /path/to/KDT_1_AX_rtauto
source vision/.vision/bin/activate
pip check
python - <<'PY'
import torch
assert torch.cuda.is_available(), "CUDA-enabled PyTorch is required"
print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY
test -x training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64
python -m unittest discover -s training/tests -p 'test_*.py'
```

1. VDI에서 새 run ID로 최대 5M-step PPO 본학습
   ```bash
   RUN_ID=dg5f-grasp-ready-reach-5m \
   ENV_PATH="$PWD/training/builds/DG5FGraspReadyReach/DG5FGraspReadyReach.x86_64" \
   TORCH_DEVICE=cuda TIME_SCALE=10 \
   training/scripts/train_dg5f_grasp_point_reach.sh
   ```
2. 별도 VDI 셸에서 TensorBoard를 실행하고 `Reach/LockSuccess`, palm 정렬,
   최소 Transit clearance, 패널 접촉과 조기 하강 실패를 모니터링한다.
   ```bash
   tensorboard --logdir training/results --port 6006
   ```
3. 학습 완료 후 500개 미학습 seed 평가를 실행해 성공률 90%와 안전 위반 0건을
   확인한다.
   ```bash
   DG5F_RUN_ID=dg5f-grasp-ready-reach-5m \
   DG5F_EVAL_EPISODES=500 DG5F_EVAL_BASE_SEED=500000 \
   training/scripts/run_dg5f_grasp_point_reach_evaluation.sh
   ```
   승인 증거는 `evaluation.csv`, `evaluation.csv.approved.json`, canonical ONNX를
   같은 run 디렉터리에 함께 보존한다.
4. 승인된 팔 정책 뒤에만 MediaPipe 20관절 → DG5F 손 target adapter를 연결한다.
   MediaPipe 파지 중에는 팔 latch를 유지하고 상위 상태 기계만 잠금을 해제한다.

## 알려진 비차단 사항

- Unity Editor가 URDF/Assimp probe에서 시스템의 unversioned `libdl.so`를 찾지 못하는
  기존 경고가 있다. 새 Linux player 빌더는 player Plugins에 shim을 복사하며 실제
  512-step player smoke는 정상 통과했다.
- player 종료 시 ML-Agents timer JSON 저장 경고가 1회 있으나 checkpoint와 ONNX export는
  성공했다. 성능 승인과 무관하지만 필요하면 ML-Agents timer 경로 처리를 별도로 조사한다.
- 5M 학습 수렴과 500-seed 성공률은 아직 수행하지 않았으므로 모델 성능 승인 상태는 아니다.

## 2026-07-22 후속 작업

- 사용자가 5M PPO 본학습을 VDI에서 별도 수행하기로 결정했다.
- 과거 V2 보존 런처가 참조하지만 누락되어 있던
  `training/scripts/bootstrap_v1_to_joint26.py`를 저장소 이력의 검증본으로 복원했다.
- 전체 Python 회귀 테스트 **27/27**, Unity EditMode **13/13**, PlayMode **7/7**을
  현재 작업 트리에서 재검증했다.
- 정책 승인 전이므로 MediaPipe target adapter는 아직 연결하지 않는다.

## 범위 밖/보존

- MediaPipe runtime 연동은 이번 변경에 포함하지 않았다.
- 기존 Grasp prefab/model의 로컬 변경은 이번 작업과 무관하므로 수정하거나 되돌리지 않았다.
