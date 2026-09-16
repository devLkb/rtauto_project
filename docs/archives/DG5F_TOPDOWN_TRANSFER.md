# DG5F top-down palm transfer

이 경로는 기존 `DG5FGrasp` 57 observations / 7 continuous actions 계약을
바꾸지 않고, 물체 위에서 `graspPoint.forward`가 `-robotBase.up`을 향하도록
599887-step 정책을 재학습한다.

## 런타임 계약

- hold stage 1..5의 하향 허용각은 각각 80°, 60°, 45°, 30°, 15°다.
- hold 시간/위치 허용오차는 각각 0.25 s/3 cm, 0.5 s/2.5 cm,
  1 s/2 cm, 2 s/1.5 cm, 3 s/1 cm다.
- 각 stage의 하향 정렬 보상 진입각은 100°, 85°, 65°, 50°, 35°다.
  물체에서 15 cm 이내이고 물체 위에 있을 때 진입각에서 목표각까지의
  정규화된 각도 진행률을 제곱한 potential이 최대 `+0.25`가 된다.
  episode에서 새 최고 potential을 달성한 차이만 지급하므로 정지 누적과
  자세 왕복 보상 파밍을 막는다.
- 10 cm 아래로 내려갈 때는 물체 수평 5 cm column 안에 있어야 하며 현재
  stage의 하향각도 만족해야 한다. 전자는 `PrematureDescent`, 후자는
  `MisalignedDescent`로 종료된다.
- hold/성공/arm lock은 표면거리, palm-facing, top-down alignment, hold
  anchor를 모두 만족해야 한다.
- spawn은 로봇 로컬 `+Z=front`, `+X=right`이며 uniform 360° 50%,
  front ±45° 25%, right ±45° 25%다.

## 원본 checkpoint

저장소와 다운로드 위치에서 확인된 실제 파일 SHA-256은 다음과 같다.

```text
38340bbbe20a994f6ea5db2792bb5f2b29eb51024c3667782f1ead17873d2cd1
```

초기 계획에 적힌 `38340bbabe...`와 한 글자가 다르지만, 로컬의 독립된 네
복사본이 모두 위의 `38340bbbe...`로 일치한다. 준비 도구는 실제 파일 hash,
global step 599887, policy/critic 57→256×3, 7 actions, optimizer state를
검증한다. 그 후 아래 위치로 바이트 그대로 복사하고 provenance를 남긴다.

```text
training/results/dg5f_topdown_transfer_source_599887/
  DG5FGrasp/checkpoint.pt
  provenance.json
```

`prepare_hold_curriculum_init.py`는 이 경로에서 사용하지 않는다. CPU-only
호스트에서는 launcher가 파일을 변경하지 않고 역직렬화 시 CUDA storage만
CPU로 매핑한다.

## CPU headless 학습

512-step smoke:

```bash
VENV="$PWD/vision/.vision" \
ENV_PATH="$PWD/training/builds/DG5FGraspTopDownTransfer/DG5FGrasp.x86_64" \
TORCH_DEVICE=cpu UNITY_DISPLAY_MODE=nographics TIME_SCALE=20 \
training/scripts/smoke_dg5f_grasp_topdown_transfer.sh
```

본 학습:

```bash
VENV="$PWD/vision/.vision" \
ENV_PATH="$PWD/training/builds/DG5FGraspTopDownTransfer/DG5FGrasp.x86_64" \
RUN_ID=dg5f_grasp_topdown_transfer_cpu_1m_20260724 \
TORCH_DEVICE=cpu UNITY_DISPLAY_MODE=nographics TIME_SCALE=20 \
training/scripts/train_dg5f_grasp_topdown_transfer.sh start
```

중단된 **동일한 새 transfer run만** `resume`할 수 있다. immutable source
run이나 과거 run을 resume하거나 덮어쓰지 않는다.

TensorBoard:

```bash
vision/.vision/bin/tensorboard \
  --logdir training/results --host 127.0.0.1 --port 6006
```

브라우저에서 <http://127.0.0.1:6006/>을 연다. 주요 scalar는
`Reach/Success`, `Reach/FinalTopDownAngleDegrees`,
`Reach/FinalSurfaceClearanceMeters`, `Reach/BestHoldSeconds`,
`Failure/MisalignedDescent`, `Failure/PrematureDescent`,
`Failure/UnsafeSurfaceContact`, `Curriculum/HoldStage`다.

## 100k checkpoint 승인

동일한 500개 seed로 원본과 후보 CSV를 만든 뒤 다음 validator를 실행한다.

```bash
vision/.vision/bin/python training/scripts/evaluate_dg5f_topdown.py \
  baseline.csv candidate.csv \
  --checkpoint training/results/RUN/DG5FGrasp/DG5FGrasp-STEP.pt \
  --approved-dir training/approved/dg5f-topdown
```

validator는 방향별 125개 seed, front/right/전체 90%, 모든 방향 85%, 성공
시 15°/3 cm/3 s/1 cm, 안전 실패 0건, left/back distance/hold 성공률
5%p 이내 회귀를 검사한다. 최초 통과 후보가 이미 있으면 덮어쓰지 않는다.
실패 시 기존 배포 ONNX를 유지한다.

## Stage 2 고정 전이학습

Stage 1 run이 각도 목표를 학습했지만 reward 기반 lesson gate를 통과하지
못하면 완료된 checkpoint를 덮어쓰지 않고 Stage 2 고정 run을 시작한다.

```bash
RUN_ID=dg5f_grasp_topdown_stage2_cpu_1m_20260724 \
TORCH_DEVICE=cpu \
UNITY_DISPLAY_MODE=nographics \
TIME_SCALE=20 \
training/scripts/train_dg5f_grasp_topdown_stage2_transfer.sh start
```

이 run은 `dg5f_grasp_topdown_curriculum_v2_cpu_1m_20260724`의 최종
`checkpoint.pt`에서 policy, critic, optimizer를 초기화하고 학습 step과
linear learning-rate schedule을 0부터 다시 시작한다. `hold_stage=2`를
고정해 전체 예산을 60°/0.5 s/2.5 cm 조건에 사용한다.
