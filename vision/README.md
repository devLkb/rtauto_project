# `vision/` — 카메라 입력과 손 텔레옵

웹캠으로 **사람의 손을 보고 로봇 손 20관절 각도를 만들어 내보내는** 코드가 모여 있다.
"사람이 로봇을 원격 조작하는 경로"이며, 스스로 물체를 찾아 잡는 강화학습 정책과는 **완전히
독립**이다. 웹캠이 켜져 있다고 RL의 물체 위치 관찰이 카메라에서 공급되지 않는다.

## 목차

1. [폴더 구조와 상태](#1-폴더-구조와-상태)
2. [텔레옵 데이터 흐름](#2-텔레옵-데이터-흐름)
3. [`dg5f/` — 현역 손 텔레옵 파이프라인](#3-dg5f--현역-손-텔레옵-파이프라인)
4. [`zed_object_detection/` — 폐기](#4-zed_object_detection--폐기)
5. [의존성 파일 두 개](#5-의존성-파일-두-개)
6. [따라 하기: 웹캠으로 Unity 손 움직이기](#6-따라-하기-웹캠으로-unity-손-움직이기)
7. [증상별 확인 순서](#7-증상별-확인-순서)
8. [관련 문서](#8-관련-문서)

## 1. 폴더 구조와 상태

```text
vision/
├── dg5f/                                   ★ 현역 — 손 텔레옵 + 다중 카메라 캘리브레이션
│   ├── README.md                              파일별·채널별 상세(정본)
│   ├── CALIBRATION_GUIDE.md                   보정 시 취할 손 동작 체크리스트
│   └── tests/                                 캘리브레이션 수학 단위 테스트
├── zed_object_detection/                   ⛔ 폐기 — DEPRECATED.md 참고
├── requirements-vision-mlagents.constraints.txt   비전+ML-Agents 공용 venv 제약(사람이 관리)
└── requirements-vision-mlagents.resolved.txt      검증 시점의 pip freeze 전체 스냅샷
```

가상환경은 관례상 `vision/.vision/`에 만든다(git 비추적). **비전과 ML-Agents는 venv 하나를
공유한다** — 버전 조합의 근거는 [`docs/PYTHON_ENV_SETUP.md`](../docs/PYTHON_ENV_SETUP.md).

## 2. 텔레옵 데이터 흐름

```text
웹캠 프레임
  → MediaPipe Hands (손 랜드마크 21점)
  → dg5f_angles.compute_raw()      동작 신호 20채널 (대부분 rad, thumb_opp만 거리 기반)
  → dg5f_angles.map_to_dg5f()      로봇 20관절각[deg] + 로봇 리밋 clamp
  → One Euro 필터                   떨림 제거 (채널마다 독립 인스턴스)
  → struct.pack("<72f") → UDP ─┬─ 5006 → Unity Dg5fReceiver          (시뮬 손)
                               └─ 5008 → dg5f_sdk_bridge.py → 실물 DG-5F  (--bridge)
```

- 포트는 기본값이며 정본은 [`config/rtauto_config.py`](../config/README.md)의
  `PORT_DG5F_SIM`(5006) / `PORT_DG5F_BRIDGE`(5008)다.
- ⚠️ **웹캠 송신과 실물 손 피드백(echo)은 같은 UDP 5006을 쓴다.** 동시에 켜면 Unity가 받는
  값이 섞인다. 실물 실제각을 볼 때는 웹캠 송신을 멈춘다.
- ⚠️ 기본 진입점은 손이 한 번 검출된 뒤 가려지면 **마지막 유효 명령을 계속 송신**한다.
  Unity의 UDP 수신 표시만으로 "지금 손이 보이고 있다"고 판단하면 안 된다.
- `--bridge`는 **송신 대상을 추가할 뿐 브리지 프로세스를 실행하지 않는다.**

## 3. `dg5f/` — 현역 손 텔레옵 파이프라인

파일별 상세는 [`vision/dg5f/README.md`](dg5f/README.md)가 정본이다. 아래는 역할 지도다.

### 3-1. 진입점 2개 (같은 계산, 다른 껍데기)

| 파일 | 성격 |
|---|---|
| `vision_node_dg5f.py` | **기본 진입점.** 미리보기 창 + UDP 송신. 현재 exe 빌드 대상 |
| `dg5f_teleop_gui.py` | **GUI 제어 패널.** 송신 대상 IP/포트·매핑 모드·보정값·관절 제한을 **실행 중에** 바꿀 수 있다. 캡처 / 처리 / Tk 화면 3스레드 구조이며, 각 단계는 "최신 1개만 유지하는 슬롯"으로 연결돼 밀린 프레임을 버린다 |

`vision_node_dg5f.py`는 argparse를 쓰지 않고 `sys.argv`를 직접 본다 — **인자 형식이 고정**이다.

```text
python vision/dg5f/vision_node_dg5f.py [right|left] [--bridge] [--map=direct|ratio]
```

### 3-2. 계산 엔진

| 파일 | 역할 |
|---|---|
| `dg5f_angles.py` | **핵심.** 랜드마크 → 동작 신호 → 로봇 관절각. 채널 테이블·보정 로드·엄지 리타게팅. `CHANNEL_NAMES`가 20채널 순서의 정본 |
| `one_euro_filter.py` | 적응형 저역통과 필터. 느리면 부드럽게, 빠르면 반응성 유지 |
| `joint_ranges.py` | 사람/로봇 가동범위 대조표(참고용). 매핑 구현의 정본은 `dg5f_angles.py` |
| `dg5f_paths.py` | 로그·보정 파일 경로 규칙의 단일 출처. 실행마다 새 로그 파일 보장(덮어쓰기 방지) |
| `calibrate_dg5f.py` | 본인 손의 가동범위·엄지 직진도를 `dg5f_calibration.json`에 저장 |

### 3-3. 실물 브리지 3종 (같은 폴더에 있지만 성격이 다르다)

| 파일 | 성격 |
|---|---|
| `dg5f_sdk_bridge.py` | **현재 구동 경로.** UDP 5008 → DGSDK.dll → 실물 20모터 |
| `dg5f_readback_bridge.py` | 읽기 전용 실험 + **자세 캡처**(`--capture-pose`) |
| `dg5f_modbus_readback.py` | 실패로 결론난 Modbus 조사 기록 |

⚠️ **DG-5F는 프로토콜·제어모드와 무관하게 TCP 세션을 전체에서 1개만 받는다**(2026-08-31 실측).
DGManager를 켜둔 채로는 SDK도 Modbus도 붙지 않는다. 상세와 교시 중 피드백 제한은
[`docs/modules/REAL_BRIDGES.md`](../docs/modules/REAL_BRIDGES.md).

### 3-4. 검증·분석 도구 — 눈으로 판단하지 않기 위한 장치

| 파일 | 무엇을 판정하나 |
|---|---|
| `probe_sender.py` | **웹캠 없이** 정해진 포즈를 50Hz로 송신. "안 움직인다"의 원인이 비전인지 수신/구동인지 한 번에 가른다 |
| `analyze_teleop.py` | 사람 손 로그 ↔ Unity 관절 로그 시간 정렬 후 4항목 판정(전송 무결성 / 리밋 초과 / 물리 추종 / 동작 재현 상관) |
| `probe_landmarks.py` · `analyze_lmprobe.py` | 랜드마크 원본 덤프 + 후보 지표의 신호/잡음비 분석 |
| `analyze_thumbik.py` | 엄지 IK 오차를 "축 부호 / 오프셋 / 물리 추종 실패 / 작업공간 밖"으로 계층 분리 |

`analyze_teleop.py` 합격선: 상관 `CORR_PASS 0.90`(0.70 미만 FAIL), 추종 `TRACK_RMS_TOL 3.0°`,
송신값 대비 `FOLLOW_RMS_TOL 10.0°`.

### 3-5. 다중 카메라 3D 삼각측량 (별도 경로)

카메라 1대 MediaPipe는 깊이 추정이 부정확하다. 그걸 개선하려는 실험 경로이며,
**현재 라이브 텔레옵은 여전히 카메라 1대를 쓴다.**

```text
calibrate_intrinsics.py → calibrate_extrinsics.py → multiview_landmarks.py
                          └ camera_calibration.py (저장/로드 + DLT 삼각측량)
                          └ multi_camera_capture.py (카메라 N대 전용 스레드 구동)
```

⚠️ 이 경로에 **프레임 좌우 반전을 넣으면 안 된다** — 캘리브레이션을 원본 프레임으로 했다.

### 3-6. 배포 스크립트

| 파일 | 역할 |
|---|---|
| `build_demo_exe.ps1` | `vision_node_dg5f.py`를 PyInstaller로 패키징 |
| `RunDemo.ps1` | 배포 폴더에서 텔레옵 exe + Unity 빌드를 한 번에 실행 |

빌드 성공이 새 PC 실행 성공을 보장하지 않는다. **설정 파일 탐색 위치가 Python exe와 Unity
플레이어에서 다르다** — [`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) 참고.

## 4. `zed_object_detection/` — 폐기

⛔ **사용하지 않는다.** 새 작업의 출발점으로 삼지 말 것. 자세한 이유는
[`vision/zed_object_detection/DEPRECATED.md`](zed_object_detection/DEPRECATED.md).

핵심만 옮기면:

- ZED 2i 스테레오 카메라로 물체 3D 좌표를 뽑아 Unity로 UDP 송신하려던 경로였다.
- **수신 측이 이미 없다.** `zed_sender.py`가 보낸다고 적힌 Unity `CameraTargetReceiver.cs`가
  저장소에 존재하지 않는다. 실행해도 받는 쪽이 없다.
- `PORT_ZED_TARGET`(5007)은 이 경로 전용이라 현재 쓰이지 않는다. **다른 용도로 재사용 금지**
  (과거 이 포트 충돌로 DG5F 브리지를 5008로 옮긴 이력이 있다).
- 물체 인식이 다시 필요해지면 하드웨어·라이브러리 선택부터 새로 정한다.

## 5. 의존성 파일 두 개

| 파일 | 성격 | 언제 고치나 |
|---|---|---|
| `requirements-vision-mlagents.constraints.txt` | **사람이 관리하는 제약**(53줄). 왜 이 버전인지 주석이 붙어 있다 | 의존성을 의도적으로 바꿀 때 |
| `requirements-vision-mlagents.resolved.txt` | 검증 시점의 `pip freeze` 전체 스냅샷(71줄) | 재검증 후 갱신 |

Python은 **3.10.11 고정**이다. ML-Agents가 3.10.x 전용이고, 3.10.12부터는 Windows installer가
배포되지 않아(보안 패치 전용 단계라 소스만 배포) installer가 있는 마지막 패치로 고정했다.
전체 근거와 설치 절차는 [`docs/PYTHON_ENV_SETUP.md`](../docs/PYTHON_ENV_SETUP.md)가 정본이다.

리포 루트의 `requirements-vision.txt` / `requirements-mlagents.txt`는 역할별 설치 목록이고,
이 폴더의 두 파일은 **둘을 한 venv에 함께 넣었을 때 실제로 통과한 조합**을 기록한 것이다.

## 6. 따라 하기: 웹캠으로 Unity 손 움직이기

> 순서가 중요하다. **UDP를 바인드하는 쪽(Unity)을 먼저 띄운다.** 반대로 하면 비전이 보내는
> 초기 패킷이 버려지고, 포트 점유 에러를 늦게 보게 된다.

**1) Unity** — 데모 씬 `unity/Assets/Scenes/Pipeline_Demo_GraspLift.unity`를 Project 창에서
더블클릭해 열고, 에디터 상단 중앙의 ▶(Play)를 누른다. Console 창(`Window > General > Console`)에
아래 로그가 보여야 한다.

```text
[Dg5fHandDriver] 관절 매핑 20/20, 포트 5006 수신 대기
```

**2) 터미널 1 (bash 또는 PowerShell, 리포 루트, DG5F 텔레옵 송신)**

```bash
source vision/.vision/bin/activate
python vision/dg5f/vision_node_dg5f.py
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python vision/dg5f/vision_node_dg5f.py
```

- 미리보기 창이 뜨고 손 위에 랜드마크가 그려지면 정상이다. 이 터미널은 **띄워 둔 채로** 둔다.
- 종료는 창에 포커스를 두고 `q` 또는 터미널에서 `Ctrl+C`.
- 오른손이 기본이다. 왼손은 `python vision/dg5f/vision_node_dg5f.py left`.

**3) 손이 안 움직이면 — 웹캠을 빼고 확인한다 (터미널 2, 리포 루트)**

```bash
source vision/.vision/bin/activate
python vision/dg5f/probe_sender.py fist
```

이걸로 Unity 손이 주먹을 쥐면 **비전 계산 쪽 문제**이고, 이것도 안 움직이면 **수신/구동 쪽 문제**다.

**4) 최초 1회 보정 (선택)**

```bash
source vision/.vision/bin/activate
python vision/dg5f/calibrate_dg5f.py
```

취할 손 동작은 [`vision/dg5f/CALIBRATION_GUIDE.md`](dg5f/CALIBRATION_GUIDE.md)에 체크리스트로 있다.
보정 파일이 없어도 기본값으로 동작한다.

## 7. 증상별 확인 순서

문제는 아래 순서로 좁힌다. 순서를 건너뛰면 엉뚱한 곳을 고치게 된다.

1. **카메라가 열리는가** — 미리보기 창이 뜨는지. `.env`의 `RTAUTO_VISION_CAMERA_INDEX` 확인
2. **손이 검출되는가** — 미리보기에 랜드마크가 그려지는지
3. **UDP를 보내는가** — 송신 로그 / `probe_sender.py`로 대체 확인
4. **Unity가 받는가** — Console의 수신 포트·매핑 로그, 두 프로그램의 IP·포트 대조
5. **손 제어권이 웹캠에 있는가** — 주먹 버튼을 누른 뒤에는 **웹캠 복귀 버튼**
   (`Dg5fFistButton.ReleaseHandToTracking()`)을 눌러야 웹캠 패킷이 다시 손을 움직인다

수신은 되는데 주먹 버튼 이후 안 움직이면 **재보정보다 5번을 먼저 확인한다.**

## 8. 관련 문서

- [`vision/dg5f/README.md`](dg5f/README.md) — 채널·매핑·패킷의 정본
- [`vision/dg5f/CALIBRATION_GUIDE.md`](dg5f/CALIBRATION_GUIDE.md) — 보정 절차
- [`docs/modules/VISION_TELEOP.md`](../docs/modules/VISION_TELEOP.md) — 비전 모듈 전체 설명
- [`docs/modules/REAL_BRIDGES.md`](../docs/modules/REAL_BRIDGES.md) — 손 SDK 브리지와 실물 제한
- [`docs/PYTHON_ENV_SETUP.md`](../docs/PYTHON_ENV_SETUP.md) — venv 구성(Windows/Linux)

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- vision/README.md`
- **갱신 대상**: `vision/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/VISION_TELEOP.md`, `vision/dg5f/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

