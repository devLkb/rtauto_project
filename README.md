# KDT_1_AX_rtauto — UR16e + DG-5F-M-R 디지털 트윈

확정 하드웨어인 UR16e와 Tesollo DG-5F-M-R 오른손으로 파지·들어올리기를 검증하는
디지털 트윈 프로젝트다. 현재 시연 씬에서는 MediaPipe가 오른손 손가락을 구동하고,
사용자가 Unity 화면의 조이스틱과 높이 슬라이더로 팔을 직접 움직인다.

```text
Unity 수동 팔 IK (UR16e)
  + MediaPipe 오른손 관절 20채널
  -> UDP -> DG-5F-M-R 디지털 트윈
```

강화학습 환경은 동일 하드웨어의 12cm 블록 grasp+lift 태스크(obs 57 / act 7)를 제공한다.
현재 시연은 정책 없이 수동 팔 조작과 손 미러링을 우선한다. 최신 아키텍처와 결정은
`docs/SIM2REAL_ROADMAP.md`가 정본이다.

## 리포 구조

| 폴더 | 내용 |
|---|---|
| `unity/` | Unity 프로젝트 (Assets + Packages + ProjectSettings — Library는 열 때 자동 생성) |
| `vision/dg5f/` | **DG5F 텔레옵 파이프라인**: 보정→웹캠 트래킹→UDP 송신 + 검증/분석 도구 |
| `tools/urdf_hand_import/` | URDF→Unity 임포트/물리검증/구동준비/프로브 범용 스크립트 |
| `urdf/dg5f/` | Tesollo DG5F URDF+메시 원본 4변형 (검증 스크립트의 대조 기준) |
| `urdf/build_arm_hand.py` | UR 팔+DG5F 손 결합 URDF 빌더 (기종·좌우 파라미터화) |
| `docs/` | Agent 계약, ML-Agents 설계·학습 가이드, 전체 작업 이력 |
| `training/` | DG5FGraspPointReach PPO 설정, 학습·평가 도구 |

## 새 환경 셋업

### 1. Unity
- **Unity 6000.4.0f1** (다른 버전은 ArticulationBody 물리 재검증 필요)
- Unity Hub → Open → `unity/` 폴더 선택. 첫 오픈 시 Library 생성으로 수 분 소요.
- 렌더 파이프라인: Built-in (URP 아님 — 머티리얼 마젠타면 확인)
- 시연 씬: `Assets/Scenes/Pipeline_Demo_GraspLift.unity`
- 결합 프리팹: `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab`
- ML-Agents 학습 환경: `Assets/MLAgents/picknplace/` (`DG5FPicknPlace`라는 기존 이름을
  유지하지만 현재 태스크는 place가 제거된 grasp+lift다.)
- 학습 실행법은 `training/README.md`, 계약과 근거는 `docs/DG5F_PICKNPLACE.md` 참고.

### 2. Python — **3.10.11 권장, 비전+ML-Agents 공용 가상환경 1개**

설치 절차(Windows/Linux, 초보자 기준)는 [`docs/PYTHON_ENV_SETUP.md`](docs/PYTHON_ENV_SETUP.md)로
분리했다 — conda/pyenv 없이 `venv`만으로 진행한다. 아래는 버전 선택 근거와
검증된 패키지 조합만 요약.

버전 선택 근거:
- **ML-Agents(mlagents)는 Python 3.10.x 전용**이며 패치버전은 안 가린다
  (2026-07-14 `3.10.12`, `3.10.4` 모두 동작 확인). **3.10.11로 고정**한 이유는
  Windows용 설치 파일이 배포되는 마지막 3.10 패치가 3.10.11이기 때문
  (3.10.12부터는 "보안 패치만" 단계로 들어가 소스만 배포 — 2026-08-26 확인).
- 기존 판단은 `mediapipe 0.10.14`(protobuf 4.x 계열) 때문에 ML-Agents(protobuf 3.x)와
  가상환경을 분리해야 한다는 것이었으나, **`mediapipe==0.10.11`로 낮추면 `protobuf==3.20.3`에서
  동작**해 ML-Agents와 같은 venv에 공존 가능하다.
- 현재 검증된 핵심 버전: `mediapipe==0.10.11`, `protobuf==3.20.3`, `numpy==1.23.5`,
  `opencv-contrib-python==4.8.1.78`, `mlagents/mlagents_envs==1.2.0.dev0`.
- **torch**: 전용 학습 서버(VDI)가 없어져 이제 본학습도 이 로컬 GPU에서 돌리므로
  `torch==2.1.1+cpu`가 아니라 **드라이버 CUDA 버전에 맞는 CUDA 빌드**를 설치한다
  (`nvidia-smi`로 CUDA 버전 확인 후 고르기 — 예: 드라이버가 지원하는 최대 CUDA가
  12.3이면 그 이하인 `cu121` 휠로 충분. PyTorch는 CUDA 버전을 정확히 맞추는 게 아니라
  "드라이버가 지원하는 버전 이하"인 배포 휠 중에서 고르는 것).
- `mlagents/mlagents_envs==1.2.0.dev0`은 `requirements-mlagents.txt`에 Release 23 커밋으로
  고정했다. **GPU가 있는 머신에서 `torch_settings.device: cpu`로 학습 config를 돌리면
  안 됨** — 이 dev 빌드는 모듈 로드 시 GPU가 있으면 PyTorch 전역 기본 디바이스를
  cuda로 걸어두고, 이후 `device: cpu` 설정이 이걸 되돌리지 못하는 버그가 있어
  `cpu vs cuda:0` 텐서 불일치로 죽는다 (`mlagents/torch_utils/torch.py`
  `set_torch_config`). GPU 머신에서는 학습 config의 `torch_settings.device`를
  **`cuda`로 맞출 것** (`training/config/dg5f_grasp_lift.yaml` 참고).

설치 후 `pip check`와 `mlagents-learn --help`를 반드시 확인한다. 텔레옵 스크립트(`vision/`)도
같은 공용 venv에서 실행한다.

### 3. (선택) unity-cli — 에디터를 CLI로 제어 (임포트/프로브 자동화에 사용)
- https://github.com/akiojin/unity-cli 설치 후 Unity 프로젝트에 커넥터 패키지 추가.
- 없어도 텔레옵 자체는 동작 (Play는 에디터에서 직접).

### 4. 로컬 설정 (새 PC에서 1회)
머신마다 다른 경로/IP/포트는 코드에 하드코딩하지 않고 레포 루트 `.env`(git 비추적, `.env.example`
복사) 하나로 관리한다 — 값과 우선순위는 `config/rtauto_config.py` 참고.
- `RTAUTO_UNITY_PROJECT`, `RTAUTO_UNITY_CLI` — `tools/urdf_hand_import/import_hand.py`
  (및 이를 재사용하는 probe_test/phys_compare/setup_drive)의 Unity 프로젝트·unity-cli 경로.
  안 채우면 `--project`/`--cli`를 직접 넘겨야 하며, 둘 다 없으면 명확한 에러로 멈춘다.
- `RTAUTO_UNITY_IP`, `RTAUTO_PORT_*` — Unity ↔ Python vision 스크립트 UDP 통신. 이 PC에서
  Unity가 로컬로 돈다면 기본값 그대로 둬도 된다.
- `vision/dg5f/analyze_teleop.py`는 환경변수 `DG5F_UNITY_LOGS`, `DG5F_URDF_DIR` 또는
  `--logs-dir/--urdf-dir` 인자로 대체 가능

## 텔레옵 실행 (UR16e + 오른손 모델)

```bash
python vision/dg5f/calibrate_dg5f.py  # 새 사용자/카메라에서 최초 1회 보정
# Unity에서 Pipeline_Demo_GraspLift 씬 Play ▶ (수동 모드로 자동 시작)
python vision/dg5f/vision_node_dg5f.py right
```
- 프로토콜/채널 순서/좌표계 계약은 `vision/dg5f/README.md` 참고 (v2: 관절각 20 + 엄지끝 위치 + 핀치)
- 웹캠 없이 오른손 배선 검증: `python probe_sender.py fist right` / `open right`
- 추종 정량 분석: `python analyze_teleop.py latest latest --hand right`
  (Unity 쪽은 Dg5fJointLogger가 Play마다 자동 기록)

## 새 핸드 URDF 임포트 (범용 파이프라인)

```bash
cd tools/urdf_hand_import
python import_hand.py <hand.urdf> --prefab --verify   # 복사→패치→임포트→물리 전수대조→프리팹
python setup_drive.py <이름>                           # 구동 준비 일괄 (Controller 제거/게인/중력 등)
python probe_test.py <이름> --urdf <hand.urdf>         # 전 관절 사각파 구동 검증
```
자세한 절차·함정 목록은 `tools/urdf_hand_import/README.md`.

## 강화학습 계약

- Behavior: `DG5FPicknPlace` (레거시 이름, 현재 동작은 grasp+lift)
- observation 57개, continuous action 7개(UR16e 팔 6 + 손 closure 1)
- 모델: UR16e + DG-5F-M-R 오른손
- 대상: 0.035×0.12×0.035m 블록
- 성공: force-closure 파지를 확인하고 목표 높이까지 들어 올려 유지
학습·평가 명령은 [`training/README.md`](training/README.md)를 따른다.

## 현재 상태 / 알려진 이슈 (2026-07-20)

- ✅ DG5F 4변형 임포트·물리검증·구동검증 완료, 굽힘 텔레옵 전 채널 PASS(상관 1.00)
- ✅ 엄지 손끝 위치 리타게팅 v2 + 핀치 스냅 (OK 사인 접촉 프로브 검증 완료)
- ⚠️ **엄지 라이브 움직임이 부드럽지 않음** — 진행 중. 후보: 데드밴드 동결/재가동 경계,
  CCD 스텝 제한, 비전 깊이 노이즈. `docs/WORKLOG.md` §20-3 미해결 항목 참고.
- ✅ UR5e+DG5F 결합 및 GraspPoint 기준점 검증
- ✅ 단일 GraspPoint 팔 도달 환경 전환 및 512 max-step 통신 smoke
- ⏳ 5M 본학습과 미학습 고정 seed 500회 승인 평가
- ⬜ 벌림(n_1)·새끼접기(5_1) 채널 게이트 해제
