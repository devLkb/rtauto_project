# ML-Agents 학습 (DG5FGraspLift / DG5FPicknPlace)

현재 살아있는 behavior는 두 개다. 아래 각 절을 참고한다.

| Behavior | 하드웨어 | obs/act | config |
|---|---|---|---|
| [`DG5FGraspLift`](#dg5f-grasp--lift-dg5fgrasplift) | UR5e + 왼손 (레거시, 검증된 기준선) | 57/7 | `config/dg5f_grasp_lift.yaml` |
| [`DG5FPicknPlace`](#dg5f-grasp--place-인프라-현재는-grasp--lift-dg5fpicknplace) | **UR16e + DG-5F-M-R 오른손 (확정 스펙)** | 57/7 | `config/dg5f_picknplace.yaml` |

> 이전의 `DG5FGraspReadyReach`(37/6, UR5e 팔 단독 reach) 절은 삭제했다. 그 전용
> config·셸 스크립트(`train/smoke/run_*_grasp_point_reach.*`)는 저장소에 더 이상
> 존재하지 않아 문서만 남으면 새 PC에서 그대로 따라 하다 막힌다. 관련 테스트는
> `training/tests/`에 남아있고 설계 기록은 git 이력에 있다.

## 새 PC에서 시작하기

Python 가상환경 설치는 [`docs/PYTHON_ENV_SETUP.md`](../docs/PYTHON_ENV_SETUP.md)가
정본이다 (Windows/Linux 양쪽). 아래는 그게 끝난 뒤의 학습 실행 절차다.

**1) 가상환경 활성화** — 활성화 스크립트 경로가 OS마다 다르다.

```powershell
.\vision\.vision\Scripts\Activate.ps1
```

```bash
source vision/.vision/bin/activate
```

**2) 로컬 설정 1회** — 저장소 루트의 `.env.example`을 `.env`로 복사한다. Unity Linux
빌드의 출력 폴더·실행 파일명과 Python 쪽 IP/포트/카메라를 모두 이 파일 하나로 관리한다.

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

상대 경로는 저장소 루트를 기준으로 해석한다. 적용 우선순위는
`프로세스 환경변수 > .env > 코드 기본값`이며, `.env`는 Git에 포함되지 않는다.
값의 정본은 [`config/rtauto_config.py`](../config/rtauto_config.py)다.

**3) 확인**

```bash
pip check
python -m unittest discover -s training/tests -p 'test_validate_unity_environment.py'
```

`Ran 4 tests ... OK`가 나오면 설치가 정상이다. 이 모듈이 현재 저장소 상태에서
100% 통과하는 유일한 테스트 모듈이라 설치 확인용으로 쓴다.

> ⚠️ `python -m unittest discover -s training/tests -p 'test_*.py'`로 전체를 돌리면
> 22개 중 15개가 `FileNotFoundError`로 실패한다. **새 PC 설치가 잘못된 게 아니다** —
> 폐기된 behavior(ReadyReach, grasp v2/v3, surface-hold 커리큘럼)의 테스트가
> 이미 삭제된 config·스크립트·`.cs`를 계속 읽고 있어서다. 이 잔재는 별도로 정리해야
> 한다. `test_bootstrap_v1_to_joint26`도 5개 중 4개만 통과한다(나머지 1개가
> 삭제된 `dg5f_grasp_v2_handfirst_lr5e5.yaml`을 참조).

**4) 학습 실행** — Unity Editor에 직접 붙이는 방식이 가장 간단하며 빌드된 플레이어가
필요 없다. behavior별 명령은 아래 각 절에 있다.

> **GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 반드시 확인.** `cpu`로
> 두면 이 ml-agents dev 빌드의 전역 디바이스 버그로 죽는다 — 근거는 루트
> [`README.md`](../README.md)의 Python 절 참고.

`builds/`, `results/`, `logs/`의 과거 Grasp/StableGrasp/PointReach 산출물은 현재
Behavior와 호환되는 checkpoint가 아니다.

## DG5F Grasp + Lift (`DG5FGraspLift`)

파지 후 들어올리기까지 학습하는 새 behavior. 설계·보상·판정 근거는
[`docs/DG5F_GRASP_LIFT.md`](../docs/DG5F_GRASP_LIFT.md).

- Behavior/spec: `DG5FGraspLift` / `1.0.0`
- observations/actions: `57/7` (팔 6축 + 손 closure 1축)
- 대상: Cube 0.055 × 0.10 × 0.055 m, 0.12 kg
- config: `config/dg5f_grasp_lift.yaml`
- 전이 준비: `scripts/prepare_dg5f_grasp_lift_transfer.py`
- Linux player: `builds/DG5FGraspLift/DG5FGraspLift.x86_64`

> `scripts/train_dg5f_grasp_lift.sh`와 `scripts/evaluate_dg5f_grasp_lift_topdown.sh`는
> `training/archives/scripts/`로 옮겼다 — 전용 GPU Linux 학습서버(`/root/venvs/ax310`,
> `tmux`/`xvfb-run`/`setsid` 전제) 전용 스크립트였는데 그 서버가 폐지되고 지금은
> 로컬 Windows 단독 머신(RTX 2080)뿐이라 애초에 실행이 안 된다. 이유는
> `training/archives/scripts/README.md` 참고. `--transfer` 전이는 이제
> `prepare_dg5f_grasp_lift_transfer.py`를 직접 호출해 준비해야 한다.

빌드된 플레이어 없이 **Unity Editor에 직접 붙여서** 시작하는 방법(초보자 기준,
Windows/Linux 공통):

```powershell
.\vision\.vision\Scripts\Activate.ps1
mlagents-learn training/config/dg5f_grasp_lift.yaml --run-id=<이름>
```

```bash
source vision/.vision/bin/activate
mlagents-learn training/config/dg5f_grasp_lift.yaml --run-id=<이름>
```

- 콘솔에 "Start training by pressing the Play button in the Unity Editor."가 뜨면
  Unity에서 `DG5FGraspLift` behavior가 들어있는 씬을 열고 ▶ Play.
- 기본 대기시간은 60초 — Unity 로딩이 오래 걸리면 `--timeout-wait=300`처럼 늘린다.
- 중단 후 이어서: 같은 `--run-id`에 `--resume` 추가.
- **GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 반드시 확인**
  (`cpu`로 두면 이 ml-agents dev 빌드의 전역 디바이스 버그로 죽음 — 근거는
  [`README.md`](../README.md) Python 절 참고).
- 모니터링: `tensorboard --logdir training/results` 실행 후 `http://localhost:6006/`.

## DG5F Grasp + Place 인프라, 현재는 Grasp + Lift (`DG5FPicknPlace`)

UR16e + DG-5F-M-R **오른손**으로 큐브를 바닥의 랜덤 위치에서 집어 들어올리는
behavior. GraspLift(UR5e + 왼손)의 검증된 접근·파지·리프트 보상/판정
아키텍처를 확정된 하드웨어(UR16e + 오른손)로 그대로 포팅한 것 — 동일한 12cm
사각기둥(0.035×0.12×0.035 m) 목표물, 동일한 커리큘럼 구조.

> 2026-08-26에 이 behavior는 잠깐 place(운반+배치) 단계까지 포함하는 진짜
> pick-and-place로 확장됐었다(플랫폼+마커 추가). 웨이퍼 스펙 도착 전 place
> 보상 셰이핑을 미리 연습해두려는 시도였는데, 하루 만에 되돌렸다 — 확정
> 하드웨어(UR16e+오른손) 위에서 grasp+lift부터 먼저 다지는 편이 지금 시점에
> 더 값지다고 판단해서다. place 설계 기록은
> [`docs/DG5F_PICKNPLACE.md`](../docs/DG5F_PICKNPLACE.md)와 git 이력에
> 남아있다.

- Behavior/spec: `DG5FPicknPlace` / `3.0.0`
- observations/actions: `57/7` (팔 6축 + 손 closure 1축) — GraspLift와 동일한
  슬롯 구성
- 대상: GraspLift 블록과 완전히 동일한 큐브(0.035×0.12×0.035 m) — 검증된
  파지 아퍼처를 그대로 재사용
- config: `config/dg5f_picknplace.yaml`
- Linux player: `builds/DG5FPicknPlace/DG5FPicknPlace.x86_64`

**사전 준비** (한 번만): Unity 메뉴에서 순서대로 실행.

1. **Tools > Robots > Create UR16e DG5F Right Prefab** — `UR16eDG5FRight_Preview.unity`의
   로봇을 `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab`로 저장 (씬 자체는 건드리지 않음).
2. **Tools > ML-Agents > Build DG5F PicknPlace Training Scene** — 위 prefab으로부터
   `Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity`를 절차적으로 생성
   (40개 병렬 학습 영역). 이 씬은 빌드 산출물이므로 직접 편집하지 않고, 바뀔 때마다
   이 메뉴를 다시 실행한다.
3. **Tools > ML-Agents > Build PicknPlace Pipeline Demo Scene** — 위 학습 씬의
   `DG5F_PicknPlaceTrainingArea_00`을 하나 복제해 `Assets/Scenes/Pipeline_Demo_GraspLift.unity`로
   저장한다(이 씬도 빌드 산출물 — 직접 편집 금지). 좌상단 "제어 모드" 버튼으로
   **자동**(`Dg5fPicknPlaceAgent` 정책이 ONNX로 파지+리프트 수행)과 **수동**(사람이
   조종) 두 모드를 전환한다:
   - 자동: `Assets/MLAgents/picknplace/Models/DG5FPicknPlace.onnx`가 학습 완료 후
     같은 경로에 채워지면 `DG5F_PicknPlaceTraining.unity`의 BehaviorParameters에
     이미 연결돼 있으므로(`PicknPlaceTrainingSceneBuilder`가 매 빌드마다 다시 읽는다)
     이 메뉴를 재실행만 하면 데모 씬에도 반영된다. 모델이 없으면 자동 모드는 대기(정지) 상태.
   - 수동: 캠 앞에서 손을 움직이면 미디어파이프가 20관절 각도를 뽑아 UDP(포트는
     `config/rtauto_config.py`의 `PORT_DG5F_SIM`, 기본 5006)로 쏘고 `Dg5fHandDriver`가
     그리퍼에 그대로 주입한다 — 팔은 화면 조이스틱+높이 슬라이더(`ArmTargetIK` 기반
     `PicknPlaceTeleopNudge`)로 조종. 손 트래킹 실행:
     ```powershell
     .\vision\.vision\Scripts\Activate.ps1
     python vision/dg5f/vision_node_dg5f.py
     ```

     ```bash
     source vision/.vision/bin/activate
     python vision/dg5f/vision_node_dg5f.py
     ```
     (오른손 모델 기준 — 인자 없이 실행. 최초 1회 `python calibrate_dg5f.py` 보정 필요,
     `vision/dg5f/CALIBRATION_GUIDE.md` 참고.)

Unity Editor에 직접 붙여서 시작하는 방법(위 GraspLift 절차와 동일 패턴):

```powershell
.\vision\.vision\Scripts\Activate.ps1
mlagents-learn training/config/dg5f_picknplace.yaml --run-id=<이름>
```

```bash
source vision/.vision/bin/activate
mlagents-learn training/config/dg5f_picknplace.yaml --run-id=<이름>
```

- 콘솔에 "Start training by pressing the Play button in the Unity Editor."가 뜨면
  Unity에서 `DG5F_PicknPlaceTraining.unity`를 열고 ▶ Play.
- **GPU 머신은 config의 `torch_settings.device`가 `cuda`인지 반드시 확인** (GraspLift와
  동일한 이유 — [`README.md`](../README.md) Python 절 참고).
- 모니터링: `tensorboard --logdir training/results` 실행 후 `http://localhost:6006/`.

> `docs/SIM2REAL_ROADMAP.md`의 "파지는 RL, 이송·배치는 결정적 플래너" 분업은
> **실제 FOUP 이송**(모바일 매니퓰레이터가 FOUP 자체를 옮기는 것)에 대한 결정이고
> 지금도 유효하다. 이 behavior는 그것과 다른 목적 — **place 보상 셰이핑 자체를
> 구조화하는 연습/기반 다지기**로, 작은 큐브를 고정 플랫폼 위 랜덤 지점에 놓는
> 순수 RL 태스크다.
