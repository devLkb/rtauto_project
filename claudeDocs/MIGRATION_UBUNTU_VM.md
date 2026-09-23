# 개발 환경 이사 — Windows PC → VMware Ubuntu 24.04 LTS (2026-09-23)

## 왜, 그리고 무엇을 어디서 하나

이 Windows PC 에서 AI 에이전트가 자꾸 멈춰서(그중 하나는 OMC 훅 멈춤 — 2026-09-23 고침,
[daily/2026-09-23.md](daily/2026-09-23.md)) **개발은 VMware 안 Ubuntu 24.04 LTS 로 옮긴다.**
사용자 결정(2026-09-23):

| 어디서 | 무엇을 |
|---|---|
| **Ubuntu 가상 머신** | 코드 짜기, 시험(unittest), 문서, git |
| **이 Windows PC** | **장비·자원이 필요한 확인** — D405·웹캠, DG-5F 실물, UR16e 실물, 그래픽카드가 필요한 것, Unity 를 무겁게 쓰는 것 |

⚠️ **"가상 머신에서 확인함" 은 "확인함" 이 아니다.** 장비·그래픽이 걸린 것은 Windows 에서 다시
본다. 기록(daily)에는 **어느 컴퓨터에서 돌렸는지**를 함께 적는다(원칙 5).

---

## 1. 옮길 것 (git 에 없는 파일)

Windows 에서 묶어 둔 파일: **`D:\workspace\cobo_sight_migration_20260923.zip`** (82 MB).
USB·공유 폴더로 가상 머신에 넘긴다. ⚠️ `.env` 가 들어 있다 — 인터넷에 올리지 않는다.

| zip 안 | 풀 곳 (Ubuntu) | 비고 |
|---|---|---|
| `repo/.env` | 리포 루트 `.env` | **경로 값을 리눅스 경로로 고친다**(아래 3단계) |
| `repo/superdex/results/` | `superdex/results/` | 채점표·학습 체크포인트·B-8 검사 결과. 다시 만들기 어렵다 |
| `repo/superdex/policies/` | `superdex/policies/` | ONNX 정책 |
| `repo/training/results/` | `training/results/` | Unity 학습 결과 |
| `repo/unity/Assets/Policies/` (+ `.meta`) | 같은 자리 | Unity 쪽 정책 |
| `repo/vision/dg5f/logs/` | 같은 자리 | 2026-09-23 손 자세 녹화(웹캠·D405) 포함 |
| `claude_memory/` | `~/.claude/projects/<새 프로젝트 키>/memory/` | Claude 기억. 새 키는 리포 경로로 정해진다(예: `-home-<사용자>-workspace-KDT_1_AX_rtauto`). **첫 세션을 한 번 연 뒤** 생긴 폴더 이름을 보고 넣는다 |

**옮기지 않는 것** (새로 만든다): `training/builds/`(Unity 빌드), `superdex/assets/bots/.superdex_root`
(설치 스크립트가 만든다), `vision/dg5f/camera_caps_cache.json`(카메라가 바뀐다), 각 가상환경(`.venv`, `.vision`).

---

## 2. 설치 순서 (Ubuntu 가상 머신, 터미널 1 — bash, 홈 폴더)

1. git·기본 도구: `sudo apt update && sudo apt install -y git git-lfs build-essential`
2. 리포 받기: `git clone https://github.com/devLkb/rtauto_project.git ~/workspace/KDT_1_AX_rtauto`
3. **Python 3.10 (공용 가상환경용)** — ⚠️ Ubuntu 24.04 기본 저장소에는 3.10 이 없다. 먼저 저장소를 추가한다
   (2026-09-23 기준 **이 순서는 아직 24.04 에서 직접 돌려 보지 않았다**):

   ```bash
   sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update
   ```

   그다음은 [`docs/PYTHON_ENV_SETUP.md`](../docs/PYTHON_ENV_SETUP.md) §1~§3 을 그대로 따른다(Linux 블록).
4. **Python 3.12 (SuperDex 전용)** — 24.04 에는 기본으로 있다. `docs/PYTHON_ENV_SETUP.md` 부록 A-1~A-6
   (2026-09-10 Ubuntu 24.04.4 에서 검증된 순서). A-5 에서 SuperDex 공식 asset 을 clone 하고
   `python -u superdex/scripts/gate3_setup_asset_root.py` 로 `.superdex_root` 를 만든다.
   **그래픽카드가 없으니 A-5 의 "CUDA 없는 머신" 안내를 따른다.**
5. zip 을 풀고 1절 표대로 넣는다.
6. `.env` 고치기 — `D:/...` 나 `C:\...` 처럼 Windows 경로가 들어간 줄을 찾아 리눅스 경로로 바꾼다:
   `grep -nE '[A-Za-z]:[\\/]' .env`
7. 확인 — 둘 다 통과하면 개발 준비 끝:

   ```bash
   source vision/.vision/bin/activate && python -m unittest discover -s vision/dg5f/tests && python -m unittest arm.tests.test_eye_in_hand arm.tests.test_pregrasp_planner arm.tests.test_prepose_to_joints arm.tests.test_target_selection
   ```

   ```bash
   source superdex/.venv/bin/activate && python -u superdex/scripts/gate3_setup_asset_root.py --verify-only
   ```

   2026-09-23 Windows 기준 통과 개수: `vision/dg5f/tests` 102개, arm 시험 146개(4묶음).
8. Claude Code 설치 후 **`~/.claude/settings.json` 의 `env` 에 `OMC_SKIP_HOOKS` 를 넣지 않는다** —
   이 설정이 Windows 에서 멈춤의 원인이었다(기억 `reference_omc_skip_hooks_hang.md`).

---

## 3. 가상 머신에서 조심할 것

| 무엇 | 왜 | 어떻게 |
|---|---|---|
| D405·웹캠 | 가상 머신으로 USB 를 넘겨야 한다. D405 는 USB 3 필요 | 되도록 **Windows 에서** 쓴다(역할 표). 꼭 써야 하면 VMware 설정의 USB 컨트롤러를 USB 3.1 로 |
| UR16e·DG-5F 실물 | 로봇 쪽 랜 어댑터에 붙어야 한다 | **Windows 에서** 한다. URSim(도커) 은 가상 머신에서도 된다 |
| DG-5F 실물 제어 | 검증된 브리지 `vision/dg5f/dg5f_sdk_bridge.py` 는 **Windows 전용 DLL** 을 쓴다. 리눅스용 `dg5f_sdk_bridge_dgsdk.py` 는 "실물 미검증" | 실물 손은 Windows 에서 |
| 그래픽 | VMware 는 그래픽카드를 제대로 못 넘긴다 | Unity 무거운 작업·학습 속도 확인은 Windows 에서 |

---

## 4. 이사 시점에 하던 일

- **B-8 (파지 판정 재설계)** 1~3단계가 남았다 — 시작 겹침 검사 넣기, 판정을 "모든 부위 97 N 이하 +
  들어 올린 뒤 유지" 로 바꾸기, 채점표 다시 만들기. 근거: [BACKLOG.md](BACKLOG.md) B-8,
  [daily/2026-09-23.md](daily/2026-09-23.md) "B-8". 이 작업은 **그래픽카드 없이 가상 머신에서 할 수 있다**
  (SuperDex 는 CPU 로 돈다 — 속도는 가상 머신에서 다시 재 볼 것).
