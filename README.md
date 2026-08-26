# KDT_1_AX_rtauto — UR5e GraspPoint 강화학습 + DG5F 텔레옵

3D 목표 좌표를 바탕으로 UR5e 팔의 `GraspPoint`를 빠르고 정확하게 이동시키고, 도달 후
Tesollo DG5F 손은 MediaPipe 텔레옵으로 조작하는 디지털 트윈 프로젝트다.

```text
3D 카메라 목표 좌표(후속 입력 경계)
  -> DG5FGraspPointReach 강화학습으로 팔 이동
  -> vision/dg5f 원격조작으로 손 조작
```

현재 강화학습 범위는 가운데 팔 이동 단계다. 학습 환경에서는 랜덤 목표가 카메라 입력을
대신하며, 카메라 수신 코드는 아직 포함하지 않는다. 개발 이력과 의사결정은
`docs/WORKLOG.md`에 보존한다.

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
- 씬: `Assets/Scenes/DG5F_Import.unity` (메인 — DG5F 왼손 인스턴스 배치됨)
  ※ SVH 관련 코드·씬(SampleScene, unity_pkg)은 DG5F 전환에 따라 제거됨(2026-07-13).
  UR 팔 결합 시 `urdf/build_arm_hand.py`(기종·좌우 파라미터화)와 `Assets/Scripts/ArmTargetIK.cs`
  (팔 IK, WORKLOG §15·§18)를 재사용해 새로 구성.
- 프리팹: `Assets/Robots/Prefabs/dg5f_*.prefab` 4변형 — 구동 준비(게인/중력off/자기충돌무시/
  수신기/IK/로거) 완료 상태. 씬에 끌어놓으면 됨. 변형 교체는 메뉴 **Tools/DG5F**.
- ML-Agents 학습 환경: `Assets/MLAgents/Reach/`.
  현재 구현은 단일 `DG5FGraspPointReach` 정책이며 checkpoint 전이 없이 처음부터 학습한다.
  Unity·강화학습을 처음 접하면 `docs/ML_AGENTS_LEARNING_FLOW.md`부터 읽는다.
  정확한 Agent 계약은 `docs/AGENT_SPEC.md`, 설계 근거는 `docs/ML_AGENTS_DESIGN.md`,
  빌드·smoke·본학습 실행법은 `docs/ML_AGENTS_TRAINING_GUIDE.md` 참고.

### 2. Python — **3.10.12 권장, 비전+ML-Agents 공용 가상환경 1개**

버전 선택 근거(2026-07-14 `vision/.vision`에서 검증):
- **ML-Agents(mlagents)는 Python 3.10.x 전용** → 3.10.12 기준으로 통일
- 기존 판단은 `mediapipe 0.10.14`(protobuf 4.x 계열) 때문에 ML-Agents(protobuf 3.x)와
  가상환경을 분리해야 한다는 것이었으나, **`mediapipe==0.10.11`로 낮추면 `protobuf==3.20.3`에서
  동작**해 ML-Agents와 같은 venv에 공존 가능하다.
- 현재 검증된 핵심 버전: `mediapipe==0.10.11`, `protobuf==3.20.3`, `numpy==1.23.5`,
  `opencv-contrib-python==4.8.1.78`, `mlagents/mlagents_envs==1.2.0.dev0`.
- **torch**: 전용 학습 서버(VDI)가 없어져 이제 본학습도 이 로컬 GPU에서 돌리므로
  `torch==2.1.1+cpu`가 아니라 **드라이버 CUDA 버전에 맞는 CUDA 빌드**를 설치한다
  (`nvidia-smi`로 CUDA 버전 확인 후 고르기 — 예: CUDA 12.3 드라이버 → `cu121` 휠).

```bash
# 비전(텔레옵) + ML-Agents 공용 venv (리포 현재 검증 경로)
python3.10 -m venv vision/.vision
source vision/.vision/bin/activate      # Windows: vision\.vision\Scripts\activate

# torch는 CUDA 빌드를 먼저 설치(버전은 vision/requirements-vision-mlagents.constraints.txt와
# 반드시 맞출 것 — 다르면 아래 설치에서 재다운로드/버전충돌 발생)
pip install torch==2.1.1+cu121 --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements-mlagents.txt
pip install -r requirements-vision.txt

# 전체 고정 버전 재현/감사가 필요할 때
pip install -r vision/requirements-vision-mlagents.resolved.txt
```

`mlagents/mlagents_envs==1.2.0.dev0`은 `requirements-mlagents.txt`에 Release 23 커밋으로 고정했다.
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

## 텔레옵 실행 (왼손 모델 기준)

```bash
cd vision/dg5f
python calibrate_dg5f.py          # 최초 1회 보정 — CALIBRATION_GUIDE.md의 동작 수행
# Unity에서 Play ▶ (씬에 dg5f_left 인스턴스)
python vision_node_dg5f.py left   # 오른손 모델이면 인자 생략
```
- 프로토콜/채널 순서/좌표계 계약은 `vision/dg5f/README.md` 참고 (v2: 관절각 20 + 엄지끝 위치 + 핀치)
- 웹캠 없이 배선 검증: `python probe_sender.py fist left` / `ok left` / `oktip left`
- 추종 정량 분석: `python analyze_teleop.py latest latest --hand left`
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

- Behavior: `DG5FGraspPointReach`
- observation 26개, UR5e continuous action 6개
- 손가락 20관절은 정책에서 제외하고 별도 텔레옵으로 제어
- 빨간 목표: 패널 기준 반경 0.20~0.85 m와 전 방향 360°를 각각 균등 생성
- 성공: GraspPoint 거리 1 cm 이내와 속도 0.05 m/s 이하를 0.25초 유지
- episode 제한: 20 simulation seconds

이전 move→grasp→lift 단계형 정책과 손 20관절 checkpoint 전이는 폐기됐다.
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
