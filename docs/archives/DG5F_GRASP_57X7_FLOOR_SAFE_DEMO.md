# DG5F 57/7 바닥 안전 데모 경로

## 목적

시연 일정 때문에 새 `37/6` 정책을 처음부터 학습하지 않고, 기존
`DG5FGrasp` `57 observations / 7 continuous actions` 체크포인트를 그대로
초기화에 사용한다. 정책의 입출력 shape는 바꾸지 않으며 Unity 환경만 다음과
같이 동작한다.

- action `0..5`: 기존과 동일한 UR5e 팔 6축 target delta
- action `6`: 호환성 때문에 남겨 두지만 학습/배포 reach 구간에서는 무시
- 손 20관절: reach 중 열린 초기 target으로 계속 고정
- 바닥에서 10 cm 미만인 상태에서는 공과 수평 거리 5 cm 이내일 때만 하강 허용
- root base를 제외한 움직이는 robot collider가 패널에 닿으면 즉시 실패
- reach 성공 후 배포 모드에서는 팔 target을 latch하고 손 제어권을
  `Dg5fReceiver`, `Dg5fHandDriver`, `Dg5fFingerIK`에 넘김

따라서 기존 모델의 `57/7` 텐서 계약은 유지되며, closure 출력만 환경에서
소비하지 않는다. 텔레오퍼레이션이 시작된 뒤에는 정책이 팔이나 손 target을
다시 쓰지 않는다.

## VDI 미세조정

CUDA 환경과 새 Linux player를 사용하는 것을 전제로 한다.

```bash
cd /path/to/KDT_1_AX_rtauto
tar -xzf dg5f_v1_gpu_fixed_526647.tar.gz -C training/results

RUN_ID=dg5f_v1_floor_safe_demo \
ENV_PATH="$PWD/training/builds/DG5FGrasp/DG5FGrasp.x86_64" \
TORCH_DEVICE=cuda TIME_SCALE=20 \
training/scripts/train_dg5f_grasp_demo_floor.sh start
```

중단된 같은 run을 이어갈 때만 `resume`을 쓴다.

```bash
RUN_ID=dg5f_v1_floor_safe_demo \
ENV_PATH="$PWD/training/builds/DG5FGrasp/DG5FGrasp.x86_64" \
TORCH_DEVICE=cuda TIME_SCALE=20 \
training/scripts/train_dg5f_grasp_demo_floor.sh resume
```

`start`는 고정 원본 run `dg5f_v1_gpu_fixed`의 체크포인트가 없으면 실패하고,
`resume`은 대상 run의 체크포인트가 없으면 실패한다. 서로 바꾸어 사용하지 않는다.

TensorBoard에서는 최소한 다음 값을 확인한다.

- `Reach/Success`
- `Reach/FinalDistanceMeters`
- `Failure/UnsafeSurfaceContact`
- `Failure/PrematureDescent`

## 텔레오퍼레이션 통합

학습 scene은 `endEpisodeOnReach=true`이다. 실제 시연 scene의 agent에는 학습된
ONNX를 연결하고 다음처럼 설정한다.

1. `Dg5fGraspAgent.enablePolicyClosure = false`
2. `Dg5fGraspAgent.endEpisodeOnReach = false`
3. 같은 robot root의 `GraspTeleoperationHandoff.agent`에 해당 agent 연결
4. `teleoperationDrivers`에 `Dg5fReceiver`, `Dg5fHandDriver`, `Dg5fFingerIK` 연결

reach 성공 전에는 handoff가 이 driver들을 비활성화한다. 성공하면 팔을 현재
xDrive target에 고정하고 driver들을 활성화한다. 다음 target으로 넘어갈 때 상위
상태 머신이 `GraspTeleoperationHandoff.ReleaseForNextTarget()`을 호출하면 손 driver를
다시 끄고 새 episode를 시작한다.

## 현재 검증 범위

- Unity EditMode `10/10`, PlayMode `7/7`
- 기존 CUDA 체크포인트를 임시 CPU 매핑한 뒤 새 player에서 512-step
  `--initialize-from` smoke 및 ONNX export 성공
- Python training 계약 테스트와 전체 회귀 테스트 통과

이는 빠른 시연 경로 검증이다. VDI 수렴 결과와 실제 MediaPipe 입력을 포함한
end-to-end 시연은 별도로 확인해야 하며, `37/6` ReadyReach의 500-seed 안전 승인
절차를 대체하지 않는다.
