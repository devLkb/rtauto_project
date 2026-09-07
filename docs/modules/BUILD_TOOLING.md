# 설정 · 빌드 · 주변 도구 모듈 설명

로봇을 직접 움직이지는 않지만, **나머지 전부가 딛고 서 있는 바닥**에 해당하는 코드들.

## 1. 설정 정본 — `config/rtauto_config.py`

이 저장소에서 가장 중요한 규칙 하나: **경로·IP·포트를 코드에 리터럴로 적지 않는다**(CLAUDE.md 원칙 1).
모든 값은 이 파일 하나를 거친다.

우선순위: **환경변수 > 리포 루트 `.env` > `.env.example` > 코드 기본값**

`.env.example`까지 읽는 덕분에 새 PC에서 `cp .env.example .env` 없이도 공유 기본값으로 바로 돈다.

### 여기 들어 있는 값들

| 분류 | 예시 키 |
|---|---|
| 포트 | `PORT_DG5F_SIM`(5006, Unity 손 트윈) · `PORT_ZED_TARGET`(5007) · `PORT_DG5F_BRIDGE`(5008, 실물 손) · `PORT_UR_ARM_BRIDGE`(5009, Unity→팔) · `PORT_UR_ARM_SIM`(5010, 팔→Unity) · `PORT_MLAGENTS_BASE`(5100) |
| IP | `UNITY_IP` · `DG5F_IP` · `UR_IP`(기본 127.0.0.1 = 로컬 URSim) |
| 경로 | `PYTHON_EXE` · `UNITY_PROJECT` · `UNITY_CLI` · `DG5F_DLL` · `UR_DESCRIPTION` · `TRAINING_RESULTS_DIR` |
| 하드웨어 | `UR_TYPE`(ur16e) · `DG5F_HAND`(right) · 속도 상한 `UR_MAX_DEG_PER_SEC` / `DG5F_MAX_DEG_PER_SEC` |
| 카메라 | `VISION_CAMERA_INDEX/WIDTH/HEIGHT/FPS/BACKEND`, 체스보드 규격 `CALIB_BOARD_*` |
| 학습 | `TRAIN_AREAS`(40) · `TRAIN_NUM_ENVS` · 플레이어 출력 경로/이름 |

> PyInstaller로 얼린 exe에서는 `__file__`이 임시 폴더를 가리키므로, 그 경우 **exe가 놓인 폴더**를
> 기준으로 삼는다. Unity `RtautoConfig.cs`도 빌드된 exe 옆에서 `.env`를 찾는 같은 관례를 따른다.

**같은 값을 읽는 형제 파일**: `unity/Assets/Scripts/RtautoConfig.cs` (C#은 파이썬을 import할 수 없어
동일 우선순위로 `.env`를 직접 파싱한다). 이게 없으면 `.env`에서 포트를 바꿨을 때 파이썬은 새 포트로 쏘고
Unity는 옛 포트에서 기다리는 **에러 없는 조용한 실패**가 난다.

## 2. 로봇 모델 만들기 — `urdf/`

| 파일 | 하는 일 |
|---|---|
| `urdf/build_arm_hand.py` | **UR 팔 + DG5F 손을 하나의 URDF로 결합**한다. 기종(`--ur-type`)과 좌우(`--hand`)가 파라미터. UR tool0에 `dg_mount`를 고정 연결하고, mesh 경로를 상대경로로 통일하고, 메시 실파일도 출력 폴더로 복사한다(빌드 폴더 자체가 임포트 소스) |
| `urdf/ur16e_dg5f_right_build/` | 위 스크립트의 산출물 — **현재 쓰는 결합 URDF + 메시** |
| `urdf/dg5f/` | 손 단독 URDF 4종(오른/왼 × 일반/숏) + 메시 |

- 링크 접두사가 손마다 다르다: 왼손 `ll_`, 오른손 `rl_`. 관절 이름 매칭 코드가 이 규칙에 의존한다.
- DG5F는 mimic 관절이 없다 — 20관절 전부 독립.
- UR description은 외부 공개 레포라 저장소에 포함하지 않는다. 경로는 `.env`의 `RTAUTO_UR_DESCRIPTION`.

## 3. URDF → Unity 임포트 — `tools/urdf_hand_import/`

URDF를 Unity에 넣으면 그냥은 못 쓴다. 그 격차를 메우는 4단계 도구다.

| 파일 | 단계 | 하는 일 |
|---|---|---|
| `import_hand.py` | ① 임포트 | URDF·메시를 Unity `Assets/Robots/`로 복사하고 경로를 패치한 뒤, unity-cli로 URDF-Importer 실행 → 결과 감사 → 프리팹 저장 |
| `phys_compare.py` | ② 검증 | Unity에 들어간 물리값을 URDF 원본과 **전수 대조**(질량·무게중심·관성·리밋·토크). 좌표계 변환까지 반영. PhysX 최소 관성 클램프처럼 알려진 정상 편차는 WARN으로 구분 |
| `setup_drive.py` | ③ 구동 준비 | 임포트 직후엔 모터가 꺼져 있다(stiffness=0). 드라이브 게인 설정 + 중력 끄기 + 루트 고정 + 자기충돌 무시·초기 포즈 동기화 컴포넌트 부착. **멱등**(재실행 안전) |
| `probe_test.py` | ④ 움직임 검증 | 모든 관절에 사각파를 넣어 추종 오차·잔여 진동·리밋 침범을 자동 판정. 합격선: 정착오차 ≤1.0°, 잔여진동 ≤0.5°, 리밋 침범 0건 |

> `setup_drive.py`의 주석에 중요한 트레이드오프가 적혀 있다: `forceLimit`을 URDF의 실제 토크값으로 두면
> 작은 오차에도 토크가 포화돼 **뱅뱅 진동**이 난다. 그래서 사실상 무제한으로 올리고 **하드웨어 토크 상한
> 재현을 포기**했다. 실물 이관 때 다시 봐야 할 지점.

## 4. 기타 도구

| 파일 | 하는 일 |
|---|---|
| `build-support/linux/libdl.so.2` | Linux headless 플레이어 빌드 후처리에 쓰는 벤더링된 라이브러리. Windows/macOS에서 Linux 빌드를 만들 수 있게 한다 |
| `tools/unity_firewall_toggle.ps1` / `.bat` | Unity Editor의 공용 프로필 인바운드 방화벽 규칙을 허용↔차단 토글. 다른 PC에서 UDP를 받아야 할 때만 잠깐 열고 닫는 용도(관리자 권한 자동 승격) |
| `tools/plot_grasp_lift_*.py` | 학습 곡선 그래프 렌더링 → [RL_TRAINING.md](RL_TRAINING.md) 참고 |
| `.gitattributes` | 저장소 줄바꿈을 LF로 고정. 없으면 Windows에서 커밋한 `.sh`가 Linux에서 `bad interpreter: /bin/bash^M`으로 죽는다 |
| `requirements-mlagents.txt` / `requirements-vision.txt` | 의존성. 버전 조합 근거는 [`docs/PYTHON_ENV_SETUP.md`](../PYTHON_ENV_SETUP.md) |
