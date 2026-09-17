# contracts/ — 부품끼리 주고받는 값의 정본

여기 있는 파일은 **여러 부품이 주고받는 값의 모양**을 한 곳에 못 박아 둔 것이다.
같은 값을 두 파일에 다시 적으면 곧 서로 어긋나므로, 그런 값은 전부 여기 모은다(원칙 1).

## 왜 필요한가

자세를 정하는 방법이 두 가지다.

1. **계산 방식** — 보이는 점 덩어리의 크기·방향을 재서 규칙대로 계산한다.
2. **학습한 예측기** — 가상 세계에서 수없이 잡아 본 결과로 배운다.

둘을 **같은 자리에 꽂았다 뺐다** 하려면 주고받는 값이 같아야 한다. 그래서 값의 모양을
먼저 못 박고, 그 뒤에 무엇이 들어가든 나머지를 다시 만들지 않는다.

## 들어 있는 것

| 파일 | 무엇 |
|---|---|
| [`grasp_prepose.py`](grasp_prepose.py) | **파지 직전 자세** — 손을 어디에, 어떤 방향으로, 손가락을 어떤 모양으로 두고 멈출 것인가 |
| [`tests/`](tests/) | 위 계약을 어기면 바로 막히는지 확인하는 시험 |

설계 근거: [`../docs/FESTA_PREGRASP_PLAN.md`](../docs/FESTA_PREGRASP_PLAN.md) §6.
상위 정본: [`../docs/RL_POLICY_REDESIGN.md`](../docs/RL_POLICY_REDESIGN.md) §4-1·§4-2.

## 파지 직전 자세 — 꼭 알아야 할 네 가지

### 1. 단위와 기준이 정해져 있다

- 길이는 **m**, 각도는 **rad**, 시각은 **초**.
- 좌표는 **로봇 베이스 기준**. 카메라가 본 좌표를 그대로 실어 보내면 막힌다.
- 회전은 쿼터니언 **(w, x, y, z)** 순서에 길이 1.

섞이면 조용히 틀리기 때문에 `validate()`가 전부 검사한다.

### 2. 손 관절 이름의 정본은 URDF 하나다

손 관절 20개의 **이름과 순서**는 팔+손 결합 URDF에서 읽는다. 목록을 코드에 베껴 적지
않는다 — 베껴 적으면 URDF가 바뀌었을 때 조용히 어긋난다.

URDF 경로는 `config/rtauto_config.py`의 `ARM_HAND_URDF`에서 온다(`.env`로 바꿀 수 있다).

### 3. "거절"이 곁다리가 아니라 정식 결과다

자세를 정할 수 없으면 **거절을 내보낸다.** 거절일 때는 자세 칸이 **전부 비어 있어야**
한다 — 비워 두지 않으면 누군가 실수로 그 자세로 팔을 움직인다.

| 거절 이유 | 언제 |
|---|---|
| `reject_no_target` | 물체를 못 찾음 |
| `reject_out_of_range` | 손이 벌어지는 범위·검증된 크기 범위 밖 |
| `reject_low_depth` | 거리 값이 비거나 튐 (투명·반짝이는 물체에서 잘 난다) |
| `reject_unreachable` | 팔이 그 자세까지 못 닿음 |
| `reject_low_confidence` | 자세는 냈지만 확신이 모자람 |

거절에는 **왜 거절했는지 한 줄**을 반드시 적어야 한다. 비우면 막힌다.

### 4. 손 벌림 폭은 참고값이고 제어에 쓰지 않는다

`opening_width`는 사람이 읽기 좋으라고 넣은 값이다. **손 모양의 정본은 관절 목표각
20개**이고, 벌림 폭으로 제어하면 정본이 둘이 된다.

## 써 보기

```python
from contracts.grasp_prepose import GraspPrePose, Source, Decision

# 자세를 정했을 때 — 관절 이름은 URDF에서 알아서 채워진다
pose = GraspPrePose.accept(
    stamp_capture=t_shot, stamp_emit=t_now,
    source=Source.LEARNED,
    palm_position=(0.45, -0.10, 0.32),
    palm_orientation=(1.0, 0.0, 0.0, 0.0),
    approach_dir=(0.0, 0.0, -1.0),
    standoff=0.08,
    hand_joint_target=target_20,
    confidence=0.91,
)

# 정할 수 없을 때
pose = GraspPrePose.reject(
    stamp_capture=t_shot, stamp_emit=t_now,
    source=Source.LEARNED,
    decision=Decision.REJECT_OUT_OF_RANGE,
    reason="보이는 폭 0.14 m — 손이 벌어지는 범위를 넘는다",
)

if pose.accepted:
    move_arm_to(pose)   # 관절 각도는 여기서 계산한다
else:
    stop_and_report(pose.reason)
```

파일로 주고받을 때는 `to_json()` / `from_json()`을 쓴다. 읽어 들일 때도 검사가 돌아서
망가진 값이 조용히 통과하지 않는다.

## 시험 돌리는 법

표준 라이브러리만 쓰므로 **어느 가상환경에서든** 그대로 돈다.

터미널 1 (PowerShell, 리포 루트):

```powershell
python -m unittest contracts.tests.test_grasp_prepose_contract -v
```

터미널 1 (bash, 리포 루트):

```bash
python -m unittest contracts.tests.test_grasp_prepose_contract -v
```

`superdex/` 쪽(파이썬 3.12)에서 확인하려면 그 가상환경의 파이썬으로 같은 명령을 돌린다.

정상이면 마지막 줄에 `OK`가 나온다. 2026-09-17 기준 **23개 전부 통과**했고,
파이썬 3.10.11 / 3.12.0 / 3.14.7 세 곳에서 확인했다.
