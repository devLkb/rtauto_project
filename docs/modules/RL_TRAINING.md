# 강화학습(RL) 모듈 설명

"로봇이 스스로 물체를 잡아 드는 정책"을 만드는 부분. 두 덩어리로 나뉜다.

- **Unity 쪽(`unity/Assets/MLAgents/**`)** — 과제 정의. 무엇을 보고(관찰), 무엇을 움직이고(행동),
  무엇을 잘하면 점수를 주는지(보상).
- **파이썬 쪽(`training/**`)** — 학습을 돌리고, 결과를 읽고, 실패한 런을 격리한다.

실행 절차는 [`training/README.md`](../../training/README.md)가 정본이다. 이 문서는 "각 파일이 왜 있나"만 다룬다.

## 0. 큰 그림

```text
 Unity 학습 씬(로봇 40개 병렬)  ←→  mlagents-learn (PPO)  →  .onnx 정책 파일
   Dg5fPicknPlaceAgent가                  ↑                        ↓
   관찰 57개를 만들고 행동 7개를          training/config/*.yaml    Unity 데모 씬에 넣으면
   받아 관절에 씀                          (하이퍼파라미터)          자동으로 물체를 잡음
```

**behavior 이름**이 이 세계의 식별자다. 지금 살아있는 건 두 개:

| behavior | 하드웨어 | 위치 | 상태 |
|---|---|---|---|
| `DG5FPicknPlace` | UR16e + DG-5F-M-R **오른손** (확정 스펙) | `MLAgents/picknplace/` | **현역** |
| `DG5FGraspLift` | UR5e + 왼손 | `MLAgents/GraspLift/` | 검증된 기준선, 구세대 |

picknplace는 GraspLift를 확정 하드웨어로 **거의 그대로 이식**한 것이다. 그래서 파일 이름만 다르고
내용이 쌍둥이인 것들이 많다. 새 작업은 picknplace 쪽에서 한다.

## 1. 과제 정의 — 핵심 2개 파일

### `Runtime/Dg5fPicknPlaceSpec.cs` — 과제 계약서 (약 48KB)

숫자와 규칙만 모아둔 정적 클래스. **이 파일이 "무엇이 성공인가"의 정본**이다.

- 정책 모양: 관찰 57개 / 행동 7개(팔 6축 + 손 개폐 1축). 이 모양을 GraspLift와 똑같이 유지한
  이유는 이미 학습된 정책 가중치를 `--initialize-from`으로 물려받기 위해서다.
- 물체 규격: 큐브 0.035 × 0.12 m, 밀도 1800, 무게중심 높이 비율 등.
- 파지 성공 조건(기하학적): 접촉점 3개 이상 + 마주보는 접촉각 90° + 중심에서 5cm 이내를
  0.3초 유지 → 파지 확정 보상.
- 들어올리기 성공 조건: 0.10 m 상승을 0.5초 유지 → 성공 보상.
- 각종 페널티: 행동 급변, 손이 바닥을 긁음, 물체 기울어짐(topple), 자세 불량 등.
- `Set*Parameter` 계열 — 커리큘럼(난이도 점진 상승)에서 YAML이 값을 갈아끼울 수 있게 하는 통로.

### `Runtime/Dg5fPicknPlaceAgent.cs` — 에이전트 본체 (약 52KB)

ML-Agents의 `Agent`를 상속한 컴포넌트. 매 스텝 하는 일:
1. 관찰 수집 — 관절각, 손·물체 상대 위치, 접촉 상태 등 57개 값을 만든다.
2. 행동 적용 — 정책이 준 7개 값을 팔 6관절 + 손 개폐 비율로 바꿔 `xDrive.target`에 쓴다.
   손가락 20관절은 "펴진 자세 ↔ 검증된 주먹 자세" 사이를 스칼라 하나로 보간한다.
3. 보상 계산 및 에피소드 종료 판정.

> **학습 씬에서 xDrive에 쓰는 것은 이 컴포넌트뿐**이라는 게 설계 규칙이다. 다른 구동자
> (텔레옵 수신, 주먹 버튼)가 동시에 쓰면 결과가 실행 순서에 따라 달라진다.

### 접촉 센서 4종 — 에이전트에 "무엇이 닿았는지" 알려주는 부품

| 파일 | 감지 대상 |
|---|---|
| `PicknPlaceObjectContactSensor.cs` | 손끝 5개 + 손바닥이 **물체**에 닿았는가 (파지 판정의 입력) |
| `PicknPlaceSurfaceContactSensor.cs` | **팔**이 바닥에 닿았는가 (안전 실패). 손가락은 일부러 제외 — 바닥의 물체를 잡으려면 닿을 수밖에 없다 |
| `PicknPlaceHandSurfaceSensor.cs` | 손이 바닥을 긁고 있는가 (실패가 아니라 감점 요소) |
| `PicknPlaceSelfCollisionSensor.cs` | 로봇이 자기 몸에 닿았는가. 물리 충돌을 다시 켜면 진동이 생기므로, **트리거 전용 그림자 콜라이더**로 겹침만 감지한다 |

## 2. 학습 실행 (`training/scripts/`)

| 파일 | 하는 일 |
|---|---|
| `train_picknplace.py` | **학습 런처.** `mlagents-learn`을 직접 치지 않는 이유는 플레이어 경로·포트·병렬 수가 머신마다 다르고 그 정본이 `.env`이기 때문. 기본은 headless 병렬 학습, `--editor`로 에디터 붙이기 |
| `mlagents_learn_compat.py` | ML-Agents 1.x가 요구하는 **구버전 ONNX 내보내기 경로**를 강제하는 래퍼. 최신 PyTorch의 기본 exporter를 쓰면 학습 끝에 모델 저장이 실패한다 |
| `validate_unity_environment.py` | 학습 시작 전에 빌드된 플레이어가 멀쩡한지(해시·구성) 검사 |

## 3. 학습 감시·판정 (`training/scripts/`)

학습은 몇 시간씩 걸리므로 "지금 잘 되고 있나"를 사람이 눈으로 판단하지 않게 만드는 도구들이다.

| 파일 | 하는 일 |
|---|---|
| `picknplace_monitor.py` | **현역 모니터.** `PicknPlace/*` 지표를 읽어 진행 상황 출력. `--gate`를 주면 과거 실패 양상에서 역산한 기준에 걸릴 때 종료코드 1을 내 런을 중단시킨다 |
| `grasp_metrics.py`, `show_dg5f_metrics.py`, `dg5f_status.py` | 이전 세대 behavior(`Reach/*`, `Grasp/*` 태그)용 모니터. **picknplace에는 쓸 수 없다** |
| `archive_run.py` | 끝난 런을 `failure/`·`legacy/`로 격리하고 실패 이유를 문서로 남긴다. 죽은 체크포인트를 `--resume`이 가리키는 사고를 막는 게 목적 |
| `tools/plot_grasp_lift_curves.py`, `tools/plot_grasp_lift_slides.py` | TensorBoard 로그를 발표용 그래프 PNG로 렌더링 |

## 4. 정책 이어받기 (transfer)

처음부터 학습하지 않고 이미 학습된 가중치를 씨앗으로 쓰는 스크립트들.

| 파일 | 하는 일 |
|---|---|
| `prepare_dg5f_grasp_lift_transfer.py` | 기존 체크포인트를 **새 behavior 이름 아래로 복사**해 `--initialize-from` 소스로 만든다(가중치는 바이트 단위 그대로) |
| `bootstrap_v1_to_joint26.py` | 구버전 정책(57관찰/7행동)을 확장된 관절 규격으로 늘린다 |
| `prepare_hold_curriculum_init.py` | 커리큘럼 전환용으로 새로 추가된 관찰 슬롯의 노이즈를 낮춘 체크포인트를 만든다 |

## 5. 설정 파일 (`training/config/*.yaml`)

PPO 하이퍼파라미터 + 커리큘럼. 파일 이름이 곧 실험 이름이다.

- `dg5f_picknplace.yaml` — **현역 학습 설정.** 주석에 왜 이 값인지(측정된 처리량 수치 포함)가 적혀 있다.
- `dg5f_grasp_lift*.yaml` — GraspLift 계열. `t1/t2/t3/t4_topdown*`는 보상 계수 스윕 실험,
  `s1~s4`는 자세·긁힘·행동률 페널티 스윕, `*_eval_*`은 평가 전용(학습 없이 성능 측정).

## 6. 테스트 (`training/tests/`, Unity `Tests/`)

| 위치 | 하는 일 |
|---|---|
| `MLAgents/picknplace/Tests/EditMode/Dg5fPicknPlaceSpecTests.cs` | 보상·성공 판정 로직의 단위 테스트(로봇 없이 순수 계산 검증) |
| `MLAgents/picknplace/Tests/PlayMode/PicknPlaceSceneTests.cs` | 생성된 학습 씬이 계약대로인지(오브젝트 구성·물리) 검증 |
| `MLAgents/GraspLift/Tests/PlayMode/GraspLiftSceneTests.cs` | 위와 같고, 추가로 **물리적 실현 가능성 프로브** — "닫힌 손이 이 블록을 들고 버틸 수 있는가"를 직접 확인한다. PPO는 물리적으로 불가능한 파지를 학습할 수 없으므로 이 질문을 학습 곡선으로 추측하지 않는다 |
| `MLAgents/GraspLift/Tests/PlayMode/GraspLiftHandGeometryProbe.cs` | 합격/불합격이 아니라 **측정 도구**. 손을 닫았을 때 손끝이 실제로 어디 가는지 재서 블록 크기를 URDF 계산이 아닌 시뮬 실측으로 정한다 |
| `training/tests/test_*.py` | 파이썬 스크립트와 과거 behavior 계약의 회귀 테스트 |
