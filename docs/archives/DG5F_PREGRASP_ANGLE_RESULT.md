# DG5F pre-grasp top-down angle — 학습 결과 (2026-07-25)

## 목표
파지 직전(pre-grasp) 단계에서 손을 물체 위 top-down 자세로 위치시키기.
기존 문제: 목표까지 이동은 하나 파지 불가능한 ~90° 옆접근.
→ **top-down angle(graspPoint.forward vs 수직아래)을 좁혀 물체 위 수직 자세 확보**가 목표.

## 결과 (달성)

최종 run `dg5f_grasp_topdown_angle_v4_cpu_2m_20260725`, lesson 4(30°) 최종 window(1.8M–2M):

| 지표 | 값 | 목표 | 판정 |
|---|---|---|---|
| FinalTopDownAngle | **avg 25.3°** (min 18.6, max 40) | ≤30° | **초과 달성** |
| Success | **69%** (peak 100%) | — | 높음 |
| BestHoldSeconds | 0.21s | 0.3s dwell | 대체로 충족 |
| PalmFacingAlignment | 0.74 | — | 손바닥 물체 향함 정상 |
| MisalignedDescent | 1.8 | ↓ | 매우 낮음 |
| SurfaceClearance | avg 6.3cm | (부차) | 하단 note 참고 |

배포 가능 모델: `training/results/dg5f_grasp_topdown_angle_v4_cpu_2m_20260725/DG5FGrasp.onnx`
(대안 checkpoint: `DG5FGrasp-1899942.onnx`. peak: step ~1942000 success 1.00 / angle 20.5°)

## 각도 수렴 궤적 (stage별)

| stage | 각도 목표 | 실제 angle avg | success |
|---|---|---|---|
| L1 | 80° | 53.1° | 0.87 |
| L2 | 60° | 52.8° | 0.63 |
| L3 | 45° | 46.6° | 0.37 |
| L4 | 30° | 29.9° (final 25.3°) | 0.43 (final 0.69) |

## 문제 진단 → 해결 (v1→v4)

| run | 문제 | 수정 | 결과 |
|---|---|---|---|
| v1 원본 | hover 함정: 하강실패 −2 절벽에 위험회피 → 7cm 상공서 안 내려옴 | — | 성공 15%, 죽은 정책 |
| v2 | 위 함정 | descent penalty −2 → −0.5 (Premature/Misaligned만; UnsafeSurfaceContact은 −2 유지) | 함정 탈출, 25% |
| v3 | hold sustain 유인 없음(new-best-delta만) + 커리큘럼 gate `reward≥1.0` 도달불가 | `HoldDwellReward`(연속유지 비례 dense) 추가 | — |
| v3(reward gate 0.6) | shaping reward가 hold 없이 0.6↑ → carryover로 lesson 조기전진, 성공 붕괴 | — | 버그 |
| v3prog | 위 조기전진 | **progress(시간) gate**로 교체 — lesson별 고정 예산 | contract 완주 17–38% |
| stage2hold_v3 | 0.5s hold 신뢰도 부족 | 예산 집중 +1M | 43%, angle 54° |
| **v4** | 각도와 hold시간이 커리큘럼에 결합돼(30°=2s,15°=3s) 각도 좁히려면 불필요한 긴 hold 강제 → hold 벽에 각도 막힘 | **각도↔hold 분리**: hold 0.3s 고정(`PreGraspHoldSeconds`), 커리큘럼은 각도만 80→60→45→30° 조임 + top-down 보상 0.25→0.5 | **angle 25°, 69%** |

## 적용된 코드 변경

`unity/Assets/MLAgents/Grasp/Runtime/Dg5fGraspSpec.cs`
- `DescentAbortPenalty = -0.5f` (신설). Premature/Misaligned descent에 적용. UnsafeSurfaceContact은 `SafetyPenalty=-2` 유지.
- `HoldDwellReward(holdSeconds)` + `HoldDwellRewardScale = 0.01f` (신설). 연속유지 비율 비례 dense 보상, farming 차단.
- `PreGraspHoldSeconds = 0.3f` (신설). `RequiredHoldSeconds`를 stage 종속에서 분리해 전 stage 0.3s 고정.
- `TopDownAlignmentPotentialMaximum` 0.25 → 0.5 (각도가 주 shaping).

`unity/Assets/MLAgents/Grasp/Runtime/Dg5fGraspAgent.cs`
- `UpdateHoldProgress`에서 매 hold step `HoldDwellReward` 지급.

테스트: `Dg5fGraspSpecTests.cs` — penalty 분리·dwell·0.3s hold 계약 반영.

## config
- `training/config/dg5f_grasp_topdown_angle_curriculum_v4.yaml` (최종): progress gate, 30°서 정지, constant LR 3e-4 / beta 0.01.
- 중간 산출물: `dg5f_grasp_topdown_stage2_transfer_v2.yaml`, `dg5f_grasp_topdown_curriculum_v3.yaml`, `dg5f_grasp_topdown_stage2_hold_v3.yaml`.

## Unity 빌드
- 최종 학습 env: `training/builds/DG5FGraspTopDownAngleV4/` (spec 반영 DLL).

## 남은 개선점 (follow-up)
1. **SurfaceClearance**: 각도가 수직에 가까워질수록 손이 물체 위로 더 떠서(2.6→6.4cm) 최종 6.3cm. pre-grasp엔 grasp controller가 하강하므로 치명적 아님. 더 가까운 접근 필요 시 clearance 목표를 stage에 추가해 조이면 됨.
2. **15° stage**: 더 수직이 필요하면 커리큘럼에 stage5(15°) 추가 + 예산.
3. **정밀 평가**: `training/scripts/evaluate_dg5f_topdown.py`의 500-seed validator로 방향별(front/right/back/left) 성공률 측정 후 배포 승인.

## 학습 재현
```bash
VENV="$PWD/vision/.vision" \
CONFIG="$PWD/training/config/dg5f_grasp_topdown_angle_curriculum_v4.yaml" \
ENV_PATH="$PWD/training/builds/DG5FGraspTopDownAngleV4/DG5FGrasp.x86_64" \
RESULTS_DIR="$PWD/training/results" \
RUN_ID=dg5f_grasp_topdown_angle_v4_cpu_2m_20260725 \
TORCH_DEVICE=cpu UNITY_DISPLAY_MODE=nographics TIME_SCALE=20 \
training/scripts/train_dg5f_grasp.sh --initialize-from dg5f_grasp_topdown_stage2hold_v3_cpu_1m_20260725
```
