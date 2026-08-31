# 학습 런 원장 (DG5FPicknPlace / 과거 behavior)

학습 런 하나하나의 **판정**과 **격리 위치**의 정본. 산출물(체크포인트·ONNX·
tfevents)은 용량 때문에 git에 넣지 않는다(`.gitignore`의 `training/results/`) —
그래서 "무엇이 있었고 왜 버렸는가"는 이 문서에만 남는다. 런을 옮길 때마다
여기 표에 한 줄을 추가한다.

## 디렉터리 규칙

경로 정본은 [`config/rtauto_config.py`](../config/rtauto_config.py)의
`TRAINING_RESULTS_DIR`이고, 나머지 둘은 거기서 파생된다.

| 위치 | 뜻 |
|---|---|
| `training/results/<run-id>` | 진행 중이거나 아직 판정하지 않은 런 |
| `training/results/failure/<run-id>` | 실패로 판정해 격리한 런. **재개·전이 금지** |
| `training/results/legacy/<run-id>` | 과거 behavior의 런. 참고 보존용, 재개 대상 아님 |

옮기는 것은 손으로 하지 않고
[`training/scripts/archive_run.py`](../training/scripts/archive_run.py)로 한다 —
옮기면서 런 폴더 안에 `RUN.md`(최종 지표 표 + 판정 근거)를 같이 남기기 때문이다.
사람이 판정 근거를 커밋 메시지에만 적어두면 그 폴더만 따로 넘겨받은 사람이
이유를 알 수 없다.

```powershell
python training/scripts/archive_run.py --run-id <RUN_ID> --to failure `
    --reason "G2 접촉 게이트 실패: 80만 스텝 ContactCount 0.00"
```

```bash
python training/scripts/archive_run.py --run-id <RUN_ID> --to failure \
    --reason "G2 접촉 게이트 실패: 80만 스텝 ContactCount 0.00"
```

> **격리 대상이 아닌 것 — 배포된 정책.**
> `unity/Assets/MLAgents/GraspLift/Models/DG5FGraspLift.onnx`와
> `unity/Assets/MLAgents/GraspLift/`의 씬·스크립트는 지금도 쓸 수 있는 검증된
> 자산이라 그대로 둔다(`.gitignore`가 이 ONNX만 예외로 추적한다). 아래 표의
> legacy 항목은 그 ONNX를 만든 런이 아니라 그 뒤에 돌린 스모크 런들이다.

## 게이트 근거

[`training/scripts/picknplace_monitor.py`](../training/scripts/picknplace_monitor.py)의
`GATES`가 코드 정본이고, 각 임계값이 왜 그 값인지는 여기 남긴다. 전부 이
behavior가 **실제로 빠졌던** 실패 양상에서 역산했다 — 일반론이 아니다.

| 게이트 | 시점 | 조건 | 왜 |
|---|---|---|---|
| G1 접근 | 300k step | `PicknPlace/MaxPalmFacingAlignment` > 0 | `DirectionalApproachPotential`은 `IsPalmFacingObject`(정렬 > 0)일 때만 값을 준다. 이 게이트가 한 번도 안 열리면 접근 보상 자체가 상수 0이라 그래디언트가 없다. 2026-08-27 진단 주석이 기록한 정지 정책 데드락이 정확히 이 상태다. |
| G2 접촉 | 800k step | `PicknPlace/ContactCount` > 0.2 | 접근이 되면 접촉은 따라온다. 80만 스텝까지 평균 0.2개 손가락도 못 닿으면 접근 자체가 안 되고 있는 것. |
| G3 파지 | 2M step | `PicknPlace/GraspConfirmed` > 0.05 | 접촉은 하는데 파지 확정이 5% 미만이면 파지 계약(3접촉 + 대향각 90° + 케이지 5cm)이 이 손·큐브 조합에서 성립하지 않는다는 뜻 — 학습률이 아니라 계약을 고쳐야 한다. |
| G4 성공 | 4M step | `PicknPlace/Success` > 0.10 | `max_steps`가 5M이다. 400만에서 10% 미만이면 남은 100만으로 뒤집히지 않는다. |

게이트는 **"한 번이라도 넘겼는가"**로 판정한다. 학습 중 일시적 후퇴로 이미
통과한 단계가 실패로 뒤집히면 오탐이 되기 때문이다.

## 알려진 실패 양상 (behavior 수명 전체)

코드 주석에 흩어져 있던 측정 기록을 한자리에 모은 것. 새 런이 같은 증상을
보이면 여기부터 확인한다.

1. **홈 포즈 바닥 접촉** (2026-08-27, 첫 headless 런) — UR16e 프리팹이 URDF
   임포트 직후 포즈 그대로 저장돼 있어 손이 에피소드 1스텝부터 끝까지 바닥
   패널에 놓여 있었다. `Dg5fPicknPlaceSpec.HomeArmDeg` 도입으로 해결
   (실측 FK로 검증: 패널에서 0.32 m, 손바닥이 수직에서 30.1°).
2. **스폰 방위 균일분포** (2026-08-27, v3) — 큐브의 절반이 홈 포즈가 바라보지
   않는 방향에 떨어져 `IsPalmFacingObject` 게이트가 열리지 않았다. 60만 스텝
   동안 `FinalDistanceMeters` 완전 평탄. `SpawnAzimuthRadians`의 전방/우측
   섹터 편향(GraspLift에서 이미 검증된 방식)으로 해결.
3. **엄지 하향 페널티 과대** (2026-08-28 확인) — `ThumbDownPenaltyScale`
   기본값 -0.10은 에피소드당 최대 -20.0인데, 태스크가 줄 수 있는 최대 양의
   보상 총합은 약 +12.2다. 셰이핑 항 하나가 태스크 보상 전체를 압도하면
   "가만히 있기"와 "안전 페널티(-2.0)로 자진 종료하기"가 최적 정책이 된다.
   `thumb_down_penalty_scale: -0.01`로 상한을 -2.0(종료 페널티와 같은 자릿수)
   으로 낮춰 대응했다.
   **2026-08-30 정정**: 가중치가 아니라 **판정 자체가 틀렸다.** 기구학을 실측하니
   (`Tools > ML-Agents > Diagnose PicknPlace Thumb Orientation`) 그 각도는 팔 자세를
   고정한 채 grip closure만 0→0.75로 바꿔도 71.5°→6.8°로 흔들렸고, 엄지 근위마디
   각도는 30.0°로 고정이었다 — 엄지 방향이 아니라 **손을 얼마나 쥐었는지**를 재고
   있었다. -0.01로 낮추면 증상은 가려지지만 "파지에 벌점을 주는 신호"는 그대로 남는다.
   판정을 "엄지 끝이 나머지 손끝보다 아래로 내려온 깊이"로 교체하고 -0.05로 되돌렸다.
4. **쥔 뒤 자세 무비용** (2026-08-30 실측) — `IsToppled`는 파지 확정 시 판정을
   멈추고 `IsLiftSuccessful`은 자세를 보지 않아, 큐브를 40° 꺾어 들어도 똑바로 든
   것과 점수가 같았다. 실제로 평균 기울기가 27°→29°로 오르는 중이었다.
   `lift_tilt_penalty_scale`(쥔 뒤 기울기 등급 벌점, 10° 이하 무료)로 대응 —
   27.5°→15.3°로 내려갔고 성공률은 오히려 98→99%로 올랐다.
   남은 15°의 원인은 솔버 정확도가 아니라 손이 계속 거는 일정한 파지 비대칭
   토크(약 52 mN·m)임을 무게중심 스윕으로 확정했다(docs/DG5F_PICKNPLACE.md).

## 런 원장

| run-id | 판정 일자 | 판정 | 위치 | 근거 |
|---|---|---|---|---|
| `test` | 2026-08-28 | 레거시 보존 | `training/results/legacy/test` | DG5FGraspLift(UR5e+왼손) 스모크 런, 12,040 step |
| `test1` | 2026-08-28 | 레거시 보존 | `training/results/legacy/test1` | DG5FGraspLift 스모크 런, 0 step (즉시 중단) |
| `test2` | 2026-08-28 | 레거시 보존 | `training/results/legacy/test2` | DG5FGraspLift 스모크 런, 32,080 step |
| `picknplace_gl_20260830` | 2026-08-30 | **성공 · 배포** | `training/results/picknplace_gl_20260830` | DG5FPicknPlace grasp+lift 20M step 완주. 최종 커리큘럼 단계(`lift_10cm_target`, 11.005M step 이후)에서 성공률 **99.21%**(최근 100 summary), 파지 확정 99.97%, 물체 기울기 15.3°, 엄지 깊이 -4.2 cm. ONNX를 `unity/Assets/MLAgents/picknplace/Models/DG5FPicknPlace.onnx`로 배포. 7.2M step에서 `lift_tilt_penalty_scale` 도입 후 `--resume`으로 이어붙였다(그 시점 이전/이후로 보상이 다르다). |
| `eval_com020` / `eval_com050` | 2026-08-30 | 진단용 | `training/results/eval_com*` | 위 정책의 잔여 기울기 원인 판별용 추론 런(학습 아님). 복원팔 7.6→4.0 cm에서 기울기 15.2→31.2°, 균형 외란토크 51.6/53.8 mN·m로 4% 이내 일치. 부수로 도메인 랜덤화 공백 확인(COM 0.50에서 성공률 99.7→96.6%). |
