# DG5F Pre-Grasp 강화학습과 Teleoperation Handoff 설계

## 1. 목적

3D 비전 카메라가 전달한 물체 위치에 맞춰 강화학습 정책이 UR5e 팔을 사람이 파지하기 좋은 자세까지 이동시키고, 자세가 안정된 뒤 팔을 잠근 상태에서 MediaPipe 기반 DG5F 텔레오퍼레이션을 활성화한다.

강화학습 정책은 손가락을 직접 조작하지 않는다. 역할은 다음과 같이 분리한다.

- **3D 비전**: 파지할 물체와 목표 위치 결정
- **강화학습 정책**: 열린 손을 pre-grasp/handoff 자세까지 이동
- **Arm lock**: handoff 자세에서 팔 관절 고정
- **MediaPipe teleoperation**: 사람이 DG5F 손가락을 조작해 실제 파지

## 2. 런타임 제어 흐름

```text
WAIT_TARGET
    카메라 좌표 안정화 및 목표 확정
        ↓
ARM_REACH
    강화학습이 팔 관절만 제어
    DG5F 손가락은 열린 상태 유지
        ↓
ARM_LOCKED
    최종 자세 조건 만족
    현재 팔 관절 drive target 저장 및 유지
        ↓
TELEOP_GRASP
    MediaPipe 손가락 제어 활성화
    사람은 손가락만 조작
        ↓
RELEASE
    텔레오퍼레이션 비활성화
    손 열기 → 팔 잠금 해제 → 목표 초기화
        ↓
WAIT_TARGET
```

`GraspTeleoperationHandoff`의 현재 방식처럼 다음 조건을 모두 만족한 뒤에만 텔레오퍼레이션 writer를 활성화한다.

```text
agent.IsArmLocked && agent.IsExternalHandControl
```

### 관절 제어권

| 상태 | 팔 관절 writer | 손가락 관절 writer |
|---|---|---|
| `WAIT_TARGET` | 없음/초기 자세 유지 | Open-hand controller |
| `ARM_REACH` | 강화학습 Agent | Open-hand controller |
| `ARM_LOCKED` | Arm lock controller | Open-hand controller |
| `TELEOP_GRASP` | Arm lock controller | MediaPipe teleoperation |
| `RELEASE` | Arm lock 해제 후 Agent | Open-hand controller |

동일한 관절을 두 개 이상의 writer가 동시에 제어하면 안 된다.

## 3. 정책 입출력 호환성

기존 체크포인트를 추가 학습하기 위해 네트워크 규격을 유지한다.

```text
Observations: 57
Continuous actions: 7
```

- Action `0~5`: UR5e 팔 관절 delta
- Action `6`: 기존 모델 호환용으로 유지하되 현재 정책에서는 무시
- DG5F 손가락: action에 추가하지 않고 텔레오퍼레이션으로만 제어

탁자 위 물체에 수직 접근하는 범위에서는 목표 접근 방향을 `Vector3.down`으로 계산할 수 있으므로 observation/action 크기를 변경하지 않는다.

임의 형상이나 기울어진 물체를 다룰 경우에는 물체 중심 좌표만으로 원하는 손 방향을 결정할 수 없다. 이 경우 3D 비전 또는 grasp-pose estimator가 표면 normal, 물체 orientation, 크기 등을 제공해야 하며 observation 규격 변경 여부를 별도로 결정한다.

## 4. 파지 기준 Transform

위치 오차는 손목 원점이 아니라 손가락 사이에 정의한 **GraspPoint**를 기준으로 계산한다.

```text
p_object_top = 물체 상단 중심
p_pregrasp   = p_object_top + worldUp × 0.10~0.15 m
p_handoff    = p_object_top + worldUp × 0.03~0.06 m
```

`p_handoff`의 정확한 높이는 다음 요소를 반영해 조정한다.

- 물체 반지름/폭/높이
- 열린 손가락과 물체 사이의 여유
- GraspPoint와 손목 사이의 고정 offset
- 사람이 손가락을 닫을 때 필요한 공간

## 5. 단계별 정책

### Stage 1: Transit to Pre-Grasp

GraspPoint를 물체 상단 `10~15 cm` 위로 이동한다.

목표:

- pre-grasp 위치까지 안전하게 이동
- 바닥 및 물체와 조기 충돌 방지
- 관절 한계 회피
- 손가락 열린 상태 유지

수평 오차가 큰 상태에서 손이 안전 높이 아래로 내려가면 패널티를 준다.

```text
horizontalError > 0.03 m
&& verticalClearance < minimumTransitClearance
→ unsafe descent penalty
```

### Stage 2: Align Above Object

물체 위에서 GraspPoint 위치와 손 접근축을 정렬한다.

다음 조건을 만족하기 전에는 최종 하강을 허용하지 않는다.

```text
horizontalError < 0.02~0.03 m
approachAngleError < 15~20°
```

수직 접근을 기본으로 할 때 손의 접근축은 `Vector3.down`과 정렬한다. Unity 모델에서 실제 접근축이 local `forward`, `up`, `-up` 중 무엇인지는 Transform을 기준으로 확인해야 한다.

### Stage 3: Controlled Descent

정렬 상태를 유지하면서 handoff 위치까지 천천히 하강한다.

목표:

- 수평 오차 유지
- 손 방향 유지
- 말단 및 관절 속도 감소
- 바닥/물체 충돌 방지
- 편안한 elbow-up 관절 구성 유지

### Stage 4: Stable Handoff

위치만 가까운 것으로 성공 처리하지 않는다. 최종 위치, 방향, 속도, 관절 안전성과 유지시간을 모두 만족해야 한다.

초기 기준값:

| 항목 | 초기 기준 |
|---|---:|
| GraspPoint 위치 오차 | `< 0.015 m` |
| 수평 오차 | `< 0.01~0.02 m` |
| 접근 방향 오차 | `< 10~15°` |
| 말단 선속도 | `< 0.03 m/s` |
| 말단 각속도 | `< 5°/s` |
| 관절 한계 여유 | `약 10° 이상` |
| 안정 유지시간 | `0.25~0.5 s` |
| 충돌 | 없음 |

모든 조건을 유지시간 동안 만족했을 때만 `LockArmForTeleoperation()`을 실행한다.

## 6. 보상 설계

### 6.1 기본 원칙

“팔꿈치를 많이 굽히면 보상”처럼 관절 굽힘 자체를 직접 보상하지 않는다. 이 방식은 필요 이상으로 팔을 접거나 물체에 도달하지 않는 정책을 만들 수 있다.

보상 우선순위는 다음과 같다.

```text
위치 및 방향 달성
    >
안전한 접근과 안정성
    >
선호 관절 자세
```

### 6.2 진행량 기반 보상

목표 근처에서 시간을 끌며 보상을 누적하지 못하도록 절대 거리보다 이전 step 대비 개선량을 사용한다.

```text
positionProgress = previousDistance - currentDistance
angleProgress    = previousAngleError - currentAngleError
postureProgress  = previousPostureError - currentPostureError
```

stage별 reward의 기본 형태:

```text
reward =
    w_position × normalized(positionProgress)
  + w_angle    × normalized(angleProgress)
  + w_posture  × normalized(postureProgress)
  - timePenalty
  - actionPenalty
  - velocityPenalty
  - jointLimitPenalty
  - unsafeDescentPenalty
  - collisionPenalty
```

Potential-based shaping을 적용한다면 stage별 potential을 다음처럼 구성할 수 있다.

```text
Phi =
    w_position × exp(-(positionError / sigmaPosition)²)
  + w_angle    × exp(-(angleError / sigmaAngle)²)
  + w_posture  × exp(-(postureError / sigmaPosture)²)

shapingReward = gamma × Phi(nextState) - Phi(currentState)
```

### 6.3 초기 reward 크기

아래 값은 첫 학습을 위한 시작점이며 TensorBoard 결과에 따라 조정한다.

| 보상/패널티 | 초기 범위 |
|---|---:|
| 활성 waypoint 위치 진행 | `+0.2 ~ +0.3` |
| 손 접근 방향 정렬 진행 | `+0.1 ~ +0.2` |
| 선호 관절 자세 진행 | `+0.03 ~ +0.08` |
| pre-grasp 최초 도착 | `+0.2` |
| 정렬 stage 최초 완료 | `+0.2` |
| 최종 안정 handoff 성공 | `+1.0` |
| 시간 경과 | `-0.001 / step` |
| 큰 action/관절 진동 | `-0.005 ~ -0.02` |
| 관절 한계 접근 | `-0.05 ~ -0.2` |
| 잘못된 조기 하강 | `-0.1 ~ -0.3` |
| 바닥/물체 강한 충돌 | `-1.0` 및 episode 종료 |

stage 도착 보너스는 stage마다 한 번만 지급한다.

## 7. 편안한 팔 관절 자세

동일한 GraspPoint pose에도 여러 IK 해가 존재할 수 있으므로 목표 물체 위치마다 선호 관절 자세 `q_ref(target)`를 계산한다.

`q_ref`는 다음 조건을 만족하는 IK 해를 선택한다.

- elbow-up 구성
- 테이블 및 로봇 자체 충돌 없음
- 관절 한계에서 충분히 떨어짐
- 손 접근축이 목표 방향과 정렬
- 손목이 과도하게 꺾이지 않음
- 현재 관절 자세에서 불필요하게 큰 이동을 요구하지 않음
- singularity 근처를 피함

관절 자세 오차 예:

```text
postureError =
    mean(
        jointWeight[i]
        × (DeltaAngle(q[i], q_ref[i]) / jointRange[i])²
    )

postureScore = exp(-(postureError / sigmaPosture)²)
```

위치가 다른 모든 물체에 하나의 고정 관절 자세를 적용하면 안 된다. 목표 pose에 따라 생성한 `q_ref`를 사용하되, 관절 자세 보상의 전체 비중은 dense reward의 약 `10~20% 이하`로 유지한다.

손의 최종 방향은 orientation reward가 담당하고, 여러 IK 해 중 편안한 팔 구성 선택은 posture reward가 담당한다.

## 8. Handoff 성공 판정

```text
canHandoff =
    finalPositionReached
    && horizontalAlignmentReached
    && palmApproachAligned
    && endEffectorVelocityLow
    && jointVelocityLow
    && jointLimitsSafe
    && noCollision
    && stableForRequiredDuration
```

`canHandoff`가 참이면:

1. 현재 팔 관절 drive target 저장
2. RL action의 팔 적용 중단
3. 저장한 팔 자세를 매 physics step 유지
4. Open-hand writer 중단
5. MediaPipe 손가락 writer 활성화

Release 시에는 역순으로 처리한다.

1. MediaPipe 손가락 writer 비활성화
2. 손가락을 열린 상태로 복귀
3. 팔 잠금 해제
4. 현재 카메라 목표 폐기
5. 다음 목표 또는 episode 시작

## 9. 카메라 목표 안정화

카메라의 매 frame 좌표를 곧바로 목표 Transform에 적용하지 않는다. 물체가 흔들리면 팔이 목표 근처에서 진동하고 handoff 조건을 만족하지 못할 수 있다.

목표 확정 절차:

1. 동일한 object track ID 선택
2. confidence 기준 통과
3. 여러 frame 좌표 수집
4. 평균/저역통과 필터 적용
5. 위치 변화가 임계값 이하인지 확인
6. episode 목표 좌표로 latch
7. `ARM_REACH`부터 `RELEASE`까지 목표 고정
8. 다음 `WAIT_TARGET`에서만 새 목표 수락

카메라 좌표는 camera-to-robot extrinsic calibration을 적용해 로봇 base 좌표로 변환해야 한다.

## 10. Curriculum

### Curriculum 1: 기존 도달 능력 유지

- 기존 거리 도달 정책 복원
- pre-grasp 위치까지 이동
- 접근 방향 허용 오차 약 `30°`

### Curriculum 2: 안전한 수직 접근

- pre-grasp waypoint 적용
- 수평 오차가 작을 때만 하강
- 접근 방향 허용 오차 약 `20°`

### Curriculum 3: Handoff 자세

- 최종 handoff 높이 적용
- 접근 방향 허용 오차 약 `15°`
- 낮은 말단 속도와 관절 속도 요구

### Curriculum 4: 안정성 및 현실 오차

- 접근 방향 허용 오차 약 `10°`
- 안정 유지시간 강화
- 관절 한계와 posture 조건 강화
- 카메라 좌표 noise 및 calibration 오차 randomization
- 물체 크기와 위치 randomization

## 11. 학습과 배포 설정

### 학습

- `endEpisodeOnReach = true`
- 텔레오퍼레이션 드라이버 비활성화
- 성공 handoff pose에 도달하면 positive terminal reward
- 실패/강한 충돌/timeout 시 episode 종료

### 배포

- `endEpisodeOnReach = false`
- 성공 시 episode 종료 대신 팔 잠금
- 팔 잠금 이후에만 텔레오퍼레이션 활성화
- `ReleaseForNextTarget()` 이후 다음 목표 처리

## 12. 전이학습 요구사항

`DG5FGrasp-599887.onnx`는 inference용이므로 ONNX 파일만으로 PPO 학습을 이어갈 수 없다.

VDI 학습 환경에서 다음 자료를 확보해야 한다.

- 해당 ONNX를 생성한 PyTorch `.pt` 체크포인트
- ML-Agents run directory/checkpoint
- 학습 YAML
- Behavior Name
- Unity ML-Agents 및 Python package 버전

57 observations / 7 actions 규격을 유지하면 기존 팔 도달 능력을 불러와 새 pre-grasp reward와 curriculum으로 추가 학습할 수 있다.

## 13. 구현 대상

| 대상 | 변경 목적 |
|---|---|
| `Dg5fGraspAgent.cs` | stage 전환, reward 계산, 최종 handoff 판정 |
| `Dg5fGraspSpec.cs` | 위치·방향·속도·유지시간 기준 정의 |
| `GraspTeleoperationHandoff.cs` | 현재 arm-lock gating 유지, 실제 joint writer 연결 확인 |
| `CameraTargetReceiver.cs` | 카메라 좌표 변환, 안정화, 목표 latch |
| Live demo scene/builder | 카메라 → RL Agent → arm lock → teleoperation 연결 |
| Training YAML | curriculum parameter와 checkpoint fine-tuning 설정 |
| ZED sender | track ID, confidence 및 필요 시 물체 크기/방향 전달 |

`ksj` 브랜치 전체를 병합하지 않고 카메라 수신 및 ZED 연동 부분만 현재 `main` 구조에 맞게 이식한다. 텔레오퍼레이션은 `rhand`의 손가락 제어를 사용하되, 처음부터 활성화하지 않고 현재 `main`의 arm-lock handoff 뒤에만 활성화한다.

## 14. 검증 기준

- 카메라 좌표가 로봇 base 좌표로 정확하게 변환된다.
- episode 중 latch된 목표가 카메라 noise로 움직이지 않는다.
- 수평 정렬 전에는 최종 하강하지 않는다.
- GraspPoint가 물체의 파지 가능한 위치에 도달한다.
- 손 접근 방향이 설정한 허용 각도 안에 들어온다.
- handoff 전에는 MediaPipe가 손가락 관절을 쓰지 않는다.
- handoff 후에는 RL이 팔 관절을 쓰지 않는다.
- 텔레오퍼레이션 중 팔 관절과 말단 위치 drift가 허용 범위 안이다.
- 동일 관절에 여러 writer가 동시에 적용되지 않는다.
- release 후 손 열기, 팔 잠금 해제, 목표 초기화가 순서대로 실행된다.
- 기존 57/7 모델 체크포인트가 정상적으로 로드된다.

## 15. 결정 요약

1. 강화학습은 손가락을 제어하지 않는다.
2. 기존 57 observations / 7 actions 구조를 유지한다.
3. 손목이 아니라 GraspPoint를 목표 위치 기준으로 사용한다.
4. 물체 위 pre-grasp 이동, 정렬, 수직 하강, 안정 유지의 단계형 정책을 사용한다.
5. 관절 굽힘 자체가 아니라 target별 elbow-up IK 자세와의 오차를 작은 보조 보상으로 사용한다.
6. 위치, 방향, 속도, 관절 안전성, 유지시간을 모두 만족한 뒤 팔을 잠근다.
7. 팔이 잠긴 이후에만 MediaPipe 텔레오퍼레이션을 활성화한다.
8. 카메라 목표는 안정화 후 episode 동안 고정한다.
9. 실제 전이학습에는 ONNX가 아니라 기존 `.pt` 체크포인트가 필요하다.
