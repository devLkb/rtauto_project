# CLAUDE.md

이 파일은 이 리포에서 작업하는 모든 Claude 세션이 따라야 하는 프로젝트 최상위 지침이다.
세부 아키텍처·진행상황·의사결정 근거는 [`docs/SIM2REAL_ROADMAP.md`](docs/SIM2REAL_ROADMAP.md)가
정본이다 — 이 파일과 로드맵 문서가 상충하면 로드맵 문서 쪽이 더 최신 사실을 담고 있을 가능성이
높으니 먼저 확인하고, 확인 후에는 이 파일도 함께 갱신한다.

## 프로젝트 목적

반도체 웨이퍼 캐리어(**FOUP**)의 **Pick & Place**를 자율 수행하는 모바일 매니퓰레이터를
만든다. 최종 목표는 **디지털 트윈** — 시뮬레이션과 실물이 같은 모델·같은 설정 체계를
공유해 서로를 검증하는 상태.

## 하드웨어 스펙 (확정)

| 구성요소 | 모델 | 비고 |
|---|---|---|
| 로봇팔 | **UR16e** | 가반 16 kg, 리치 900 mm |
| 그리퍼 | **DG-5F-M-R** (Tesollo, 오른손) | SDK 모델 코드 `5f_right` |
| 이동 베이스 | **엔스퀘어(Nsquare) AMR** | 모델·상세 스펙 미확보 — 확보되면 로드맵 갱신 |

스펙은 변동 가능하다고 통보받은 상태다. 로봇 치수·워크스페이스 상수는 **컴파일 상수로
굳히지 말고** 런타임 파라미터/설정으로 뺀다.

## 동작 원칙 — 순차 동작, 모바일 매니퓰레이션 아님

**이동 → 정지 → 로봇팔 → 그리퍼.** 주행 중 파지는 범위 밖이다. 매니퓰레이션은 항상
베이스가 정지한 상태에서만 일어나므로, 정책·관찰 설계는 "고정된 로봇 베이스 프레임"을
전제해도 된다.

## 파이프라인

```text
sim { Unity (ML-Agents 학습, 물리=Unity 자체 엔진/PhysX) }
  -> real (UR16e RTDE + DG-5F-M-R dgsdk + 엔스퀘어 AMR, ROS2 + Nav2 오케스트레이션)

ROS2 통합: Unity <-> ROS-TCP-Connector/Endpoint (Unity-Robotics-Hub) <-> ROS2(WSL2/Docker)
  매니퓰레이션 정책 검증 + Nav2 주행 공용 — 별도 Gazebo 단계 없음
```

> ⚠️ **MuJoCo 폐기 (2026-08-26).** 물리 엔진으로 MuJoCo를 도입하는 방안(2026-08-25
> 확정·검증됨)은 **파이프라인 통합 및 후속 유지보수 어려움을 이유로 폐기**됐다.
> `urdf/ur16e_dg5f_right_build/*.mjcf.xml`, `patch_mjcf.py` 등 이미 만들어진 MuJoCo
> 산출물은 삭제하지 말고 그대로 두되(과거 이력), 새 작업의 기준으로 삼지 않는다.

> ⚠️ **Gazebo 검증 단계 폐기 (2026-08-26, MuJoCo 폐기와 같은 날 추가 결정).** v3에서
> 도입했던 "Unity 다음의 Gazebo 범용 검증 단계"는 하루 만에 다시 폐기됐다. 대신 Unity가
> [Unity-Robotics-Hub](https://github.com/Unity-Technologies/Unity-Robotics-Hub)의
> ROS-TCP-Connector/Endpoint로 **ROS2와 직접 통신**하고, 이 경로로 매니퓰레이션
> 정책·Nav2 주행 검증을 모두 수행한다. `docs/SIM2REAL_ROADMAP.md`는 v4(2026-08-26)에서
> 이 결정을 반영했다 — 상세 구성(설치·토폴로지·ROS2 버전 호환 리스크)은 로드맵 §9
> 참고. ROS_IP·TCP 포트는 원칙 1에 따라 `config/rtauto_config.py`로 뺄 것.
- **물리·학습은 Unity 자체 엔진**(PhysX)으로 되돌아간다. Unity가 물리와 ML-Agents 에이전트
  로직을 모두 소유한다.
- **1차 목표**: Unity 경로로 sim2real 파이프라인을 완전히 뚫는 것. 그 뒤 **모방학습으로
  초기 데이터를 확보**해 강화학습/정책 개선의 시작점으로 쓴다.
- **GPU 워크스테이션(Isaac Sim/Lab 가능 사양)을 제공받으면**: sim 단계의 Unity를
  **Isaac Sim/Isaac Lab으로 교체**한다. real 연동 구조는 이 교체와 무관하게 유지되는 것을
  전제로 설계할 것 — Unity 전용 코드(ML-Agents 브리지, C# 보상 스펙 등)는 나중에 이식
  대상이 된다는 점을 염두에 두고 결합도를 낮게 유지한다.

## 원칙 1 — 하드코딩 절대 금지

경로·IP·포트·사용자명 등 머신마다 달라지는 값은 **어떤 코드에도 리터럴로 넣지 않는다.**
반드시 [`config/rtauto_config.py`](config/rtauto_config.py) + 리포 루트 `.env`(git 비추적,
`.env.example` 복사) 조합을 거친다. 우선순위: 환경변수 > `.env` > 코드 기본값.

- 새 포트/경로가 필요하면 `config/rtauto_config.py`에 추가하고 다른 파일은 그걸 import한다.
  숫자·경로를 두 번째 파일에 다시 타이핑하지 않는다.
- 관절 오프셋·클램프 같은 **물리/캘리브레이션 상수**는 하드코딩과 다르다 — 정당한 데이터지만,
  여러 스크립트에 중복시키지 말고 하나의 정본 파일(예: `Dg5fGraspLiftSpec.cs`)에 모은다.
- 기존 코드를 손댈 때 하드코딩된 값을 발견하면, 요청받은 작업과 무관해도 버그로 보고 고친다.
- 이 리포는 과거 5인 팀 체제에서 하드코딩이 광범위하게 퍼졌던 이력이 있다(`C:\Users\...`
  경로, 포트 충돌 등). 1인 체제로 바뀐 지금도 원칙을 완화하지 않는다.

## 원칙 2 — 새 머신 부트스트랩 보장

**다른 컴퓨터에서 Unity + Python 3.10.11 + 필요 라이브러리 설치가 끝나는 즉시** 강화학습을
새로 시작하거나 이어서 시작할 수 있어야 한다. 이것이 모든 설계 결정의 조건이다.

- 새로 시작: 설치 완료 → 바로 학습 실행 가능해야 한다. 문서화되지 않은 수동 단계가 있으면
  버그로 취급한다.
- 이어서 시작: 체크포인트 등 추가로 필요한 파일 조건이 있다면, "그 조건 자체를 문서와
  스크립트에 명시"하는 것까지가 완료 조건이다 — 파일이 있다고 가정하고 넘어가지 않는다.
- Python 버전은 **3.10.11 고정**(ML-Agents가 3.10.x 전용, 패치버전은 무관하나 3.10.12부터
  Windows installer가 배포되지 않아 — 3.10부터는 보안 패치 전용 단계라 소스만 배포 —
  installer가 있는 마지막 3.10 패치인 3.10.11로 고정, 2026-08-26 확인·정정). 비전(mediapipe)과
  ML-Agents는 버전 조합이 맞으면 venv 하나를 공유한다 — 근거와 정확한 버전 표는
  [`docs/PYTHON_ENV_SETUP.md`](docs/PYTHON_ENV_SETUP.md) 참고.
- 환경 셋업 절차 자체를 변경했으면 `docs/PYTHON_ENV_SETUP.md`를 그 자리에서 함께 갱신한다.

## 리포 구조

| 경로 | 내용 |
|---|---|
| `unity/` | Unity 프로젝트 (Assets + Packages + ProjectSettings) |
| `urdf/` | 로봇 URDF 원본·결합 빌더(`build_arm_hand.py`), MJCF 변환 산출물 |
| `vision/dg5f/` | DG5F 텔레옵 파이프라인 (보정→트래킹→UDP 송신) |
| `vision/zed_object_detection/` | 3D 비전(ZED) 객체 검출 |
| `tools/urdf_hand_import/` | URDF→Unity 임포트/물리검증/구동준비 범용 스크립트 |
| `training/` | ML-Agents 학습 설정·스크립트·평가 도구 |
| `config/rtauto_config.py` | 경로/IP/포트/하드웨어 구성의 유일한 정본 |
| `docs/` | 로드맵, 정책 계약, 작업 이력 — `SIM2REAL_ROADMAP.md`가 최상위 정본 |

## 우선 참고 문서

1. [`docs/SIM2REAL_ROADMAP.md`](docs/SIM2REAL_ROADMAP.md) — 아키텍처 확정 사항, Phase별 계획, 리스크. **가장 먼저 확인.**
2. [`README.md`](README.md) — 환경 셋업, 텔레옵 실행법 (하드웨어 전환 반영해 최신화 필요할 수 있음 — 착수 전 UR16e/오른손 기준으로 맞는지 확인)
3. [`training/README.md`](training/README.md) — 학습·평가 명령
4. [`config/rtauto_config.py`](config/rtauto_config.py) — 모든 IP/포트/경로 설정의 출처
