# DG5F V2 실패 학습 분석 (2026-07-17)

## 목적

V2에서 중단한 세 실험의 문제를 구분해 기록하고, hand-first
`dg5f_v2_joint26_handfirst_lr5e5_gpu_fixed`를 새로 시작한 근거를
남긴다.

## 1. Closure V2의 구조적 한계

- 보존 run: `dg5f_v2_closure_failed_343k`
- 최종 step: `343180`
- 계약: observation 57개, continuous action 7개
- 손 제어: 팔 6축과 손 전체 closure 1축

Closure 방식은 손가락 20관절을 하나의 값으로 `OPEN -> FIST` 보간했다.
따라서 엄지와 맞은편 손가락의 위치와 접촉 시점을 각각 수정할 수 없었다.
공의 위치·자세가 달라져도 모든 손가락이 고정된 비율로 함께 움직이므로,
파지에 필요한 엄지와 맞은편 손가락의 동시 접촉을 안정적으로 학습하기
어려웠다.

이 문제는 학습률 조정만으로 해결할 수 없는 **행동 공간의 구조적
제약**이다. 해당 run은 비교 자료로만 보존하며 재개하거나 V3 전이
원본으로 사용하지 않는다.

## 2. Joint26 learning-rate 1e-4 pilot 문제

- 보존 run: `dg5f_v2_joint26_gpu_fixed`
- 최종 step: `253740`
- 계약: `DG5FGraspJoint`, observation 116개, continuous action 26개
- 학습률: `1e-4`, linear schedule
- 초기화: 검증된 `dg5f_v1_joint26_bootstrap`, global step 0
- 종료 방식: 정상 중단 후 최종 checkpoint와 ONNX 저장

이 run은 실행 장애로 중단한 것이 아니다. NaN, 비유한 물리,
ML-Agents 통신 오류는 발생하지 않았으며 팔과 손 20관절도 정상
구동됐다. 문제는 **팔 도달은 개선되는 반면 손 접촉과 파지는
퇴보하는 학습 추세**였다.

### 중단 판단에 사용한 지표

TensorBoard summary를 step 구간별로 평균한 근사값이다.

| 지표 | 0..100k | 100k..200k | 최근 20k |
|---|---:|---:|---:|
| 도달 성공률 | 39.9% | 56.4% | 62.6% |
| 파지 성공률 | 52.7% | 43.5% | 36.2% |
| 엄지·맞은편 동시 접촉률 | 69.8% | 46.1% | 37.5% |
| 시간 초과율 | 9.2% | 41.0% | 55.6% |
| 공 이탈률 | 38.1% | 15.6% | 8.2% |
| 비유한 물리 발생률 | 0% | 0% | 0% |

해석은 다음과 같다.

1. 공 이탈이 줄고 도달 성공률이 증가했으므로 팔의 접근 능력은
   개선되고 있었다.
2. 동시에 파지 성공률과 동시 접촉률이 지속적으로 하락했다.
3. 공에 접근한 뒤 파지를 완성하지 못한 채 episode가 끝나는 비율이
   늘면서 시간 초과율이 크게 상승했다.
4. 원래 승인 조건인 `Reach/Success >= 80%`에도 도달하지 못했고,
   접촉률 증가 조건은 반대로 악화됐다.
5. 중단 시점은 curriculum 첫 단계인 보조된 near-ball/pre-grasp
   구간이었다. 따라서 다음 단계로 진행시키는 것보다 재시작하는 편이
   안전하다고 판단했다.

### 원인 판단

확정된 사실은 정책 갱신 이후 팔 성능과 손 성능의 추세가 갈라졌다는
것이다. 코드·물리·통신 장애는 확인되지 않았다.

`1e-4` 학습률이 V1에서 이식한 팔 정책과 새로 추가한 20개 손 행동을
함께 최적화하기에는 커서, 손 접촉 정책이 불안정하게 갱신됐을 가능성이
높다고 판단했다. 이는 지표에 근거한 원인 가설이며 단일 실험만으로
학습률이 유일한 원인이라고 확정한 것은 아니다.

## 3. Joint26 learning-rate 5e-5 pilot 문제

- 보존 run: `dg5f_v2_joint26_lr5e5_gpu_fixed`
- 최종 step: `215202`
- 최종 checkpoint SHA-256:
  `8ed86d272f56d4341034af802fca2ce53605de14a96ee5db8baa30d046423057`
- 최종 ONNX SHA-256:
  `ec8a84a2f59cfcf81446b7bf3d20185967147c55b5345b845bdf95f5a56d547e`
- archive SHA-256:
  `dc0c4b5920dea2c499adb7e666ae741098b9220067f1c96415b77bfceefa9822`

이 run은 동일한 팔·손 동시 학습 구조에서 학습률만 `5e-5`로 낮췄다.
정상 중단으로 최종 checkpoint와 ONNX를 저장했지만 200k 이후에도 첫
lesson에 머물렀다. 최신 완료 summary인 step 215000에서 reward는
`1.3623`, 파지·동시접촉·도달은 각각 `0.333333`, 일반 timeout과 공
이탈도 각각 `0.333333`, 비유한 물리는 `0`이었다.

학습률 인하만으로 팔 도달과 손 파지의 경쟁 및 20초 timeout이 만드는
긴 실패 표본 편향을 해소하지 못했다고 판단했다. 이 run도 재개하거나
V3 전이 원본으로 사용하지 않는다.

## 3.5. Hand-first 첫 시도(stale build) 실패 — 2026-07-18 추가

- 보존 run: `dg5f_v2_joint26_handfirst_lr5e5_gpu_fixed` (417k step)
- 상세: `training/archives/V2_HANDFIRST_STALEBUILD_FAILED.md`

이 run은 hand-first 설계 자체를 검증하지 못했다. `Player-0.log`가
증명하듯 hand-first 로직이 없는 옛 `DG5FGraspJoint26` 빌드
(2026-07-17 08:09, C# 수정 09:55 이전)로 실행됐다. 따라서 팔 고정과
5초 timeout이 적용되지 않았고(도달 최초 성공 시간 평균 6.29초,
episode 길이 최대 ~198 decision ≈ 20초), 옛 20초 arm+hand 환경이
그대로 재실행돼 lesson 0에 고착된 채 수동적 timeout 정책으로
붕괴했다(Timeout 0.9%→98.3%, Grasp 63.6%→1.7%).

추가로 콘솔의 "Mean Reward 3.017 (std 0.000)"은 `summary_freq: 200`이
~80 agent 규모 대비 너무 작아 생긴 단일 episode 표본이었다. 실제
200-episode 평균 reward 피크는 ~1.76으로 threshold 2.2에 미달했다.

재발 방지 조치: (1) `train_dg5f_grasp.sh`에 빌드-소스 신선도 가드,
(2) `summary_freq` 20000으로 상향, (3) DLL hot-swap으로
`DG5FGraspJoint26HandFirst` 빌드 생성(에디터 라이선스 부재 우회),
(4) 대체 run `dg5f_v2_joint26_handfirst2_lr5e5_gpu_fixed`.

## 3.6. Hand-first 2차 시도(자유낙하) gate 중단 — 2026-07-18 추가

- 보존 run: `dg5f_v2_joint26_handfirst2_lr5e5_gpu_fixed` (107,787 step)
- 상세: `training/archives/V2_HANDFIRST2_GATE_STOPPED.md`

올바른 hand-first 빌드로 실행된 첫 run. 100k까지 lesson 0이어서 gate
기준대로 중단했다. 파지 성공이 약 3,200 episode 동안 0회였는데, 원인은
학습이 아니라 역학이다: 공이 스폰 후 0.04초 만에 자유낙하해 0.2~0.4초에
반쯤 열린 손을 통과하는데, stage 1 손가락 제한 1°/decision으로는 그
사이 2~4°밖에 못 닫는다. 성공이 물리적으로 도달 불가였다.

수정: stage 1에서 공을 엄지·맞은편 동시 접촉 달성(또는 최대 2.5초)까지
kinematic으로 고정한 뒤 release하고, release 시점에 dual-contact hold
시계를 리셋해 성공은 여전히 중력 하 0.5초 유지를 요구한다. stage 1 손
delta는 `Dg5fGraspSpec.StageOneHandDeltaDegPerDecision = 2°`로 상향
(scene에 직렬화된 필드 값 1은 더 이상 사용하지 않음).

## 4. Hand-first 조치

- 새 run: `dg5f_v2_joint26_handfirst3_lr5e5_gpu_fixed`
- 검증된 `dg5f_v1_joint26_bootstrap`에서 optimizer 없이 step 0 시작
- stage 1 팔 target 고정, 손 20관절만 독립 학습
- stage 1 접근 reward 0, timeout 5초
- stage 2/3은 기존 20초 timeout 및 도달 후 5초 파지 timeout
- curriculum은 최근 200 episode 평균 reward 기준:
  stage 1 `> 2.2`, stage 2 `> 1.8`
- 정책 shape, 성공 `+2`, 공 이탈/비유한 물리 `-1`, checkpoint 100k,
  최대 2M step 유지
- V3 전이 원본은 hand-first run만 허용

> 2026-07-18 후속 상태: 위 run은 player/result 교체 중 839,959 step에서
> 중단되어 보존 전용으로 전환했다. 현재 `dg5f v2`는 StableGrasp 3.0.0
> player의 새 `dg5f_v2_stablegrasp_v3_lr5e5_gpu_fixed` run을 가리키며,
> 검증된 V1 joint26 bootstrap에서 step 0으로 시작한다.

## 5. 이후 판정 기준

- 100k 전에 stage 2 전환
- 전환 직전 20k:
  `Reach >= 80%`, `Grasp >= 80%`, `DualContact >= 85%`,
  `Timeout <= 15%`
- 100k까지 stage 1이면 즉시 중단하고 단순 학습률 변경으로 재시도하지
  않음
- 500k 전에 stage 3 전환, 전환 직전
  `Reach >= 80%`, `Grasp >= 70%`, `DualContact >= 75%`,
  `Timeout <= 25%`
- NaN, 비유한 물리, reset 및 communicator 오류 0

최종 승인은 curriculum 3단계에서 unseen seed 200회 deterministic
평가로 수행하며, `Grasp/Success >= 80%`, `Reach/Success >= 80%`,
모든 성공 episode의 연속 접촉 `>= 0.5초`를 요구한다.

## 지표가 0, 1, 0.xx로 크게 변하는 이유

성공률 지표는 해당 summary 구간에서 종료된 episode들의 평균이다.
초기 학습처럼 표본 수가 적으면 1회 성공 여부가 값에 큰 영향을 준다.
예를 들어 3개 episode 중 2개 성공이면 `0.6667`, 1개 중 1개 성공이면
`1.0`이다. 따라서 초반 단일 표시값은 성능 확정값이 아니며, 충분한
episode가 포함된 step 구간 평균과 장기 추세를 함께 확인해야 한다.
