# 비전 · 텔레옵 모듈 설명

`vision/` 아래 코드. 크게 세 갈래다.

1. **DG5F 손 텔레옵** (`vision/dg5f/`) — 웹캠으로 사람 손을 보고 20관절 각도를 만들어 UDP로 쏜다. 이 저장소에서 가장 큰 파이썬 덩어리.
2. **다중 카메라 3D 캘리브레이션** (`vision/dg5f/` 안, 별도 진입점) — 웹캠 여러 대를 하나의 3D 좌표계로 묶는다.
3. ~~**ZED 객체 검출** (`vision/zed_object_detection/`)~~ — **폐기됨.** 아래 §4 참고.

실행 절차는 [`vision/dg5f/README.md`](../../vision/dg5f/README.md)와
[`CALIBRATION_GUIDE.md`](../../vision/dg5f/CALIBRATION_GUIDE.md)가 정본이다.

## 먼저 이해할 역할과 연결

텔레옵은 **사람의 동작으로 로봇을 원격 조작**하는 경로다. 입력은 웹캠 영상이고 출력은
로봇 손의 목표 관절각과 손끝 정보다. 사람 손의 특징점을 찾는 MediaPipe와, 그 특징점을 로봇 명령으로
바꾸는 계산은 Python에서 수행한다. Unity는 받은 명령을 화면 속 관절에 적용한다.

이 모듈은 물체를 스스로 찾아 잡는 RL 정책과 독립이다. 웹캠이 켜져 있다고 RL의 물체 위치 관찰이
카메라에서 공급되는 것은 아니다. 다중 카메라 경로도 현재 단일 웹캠 텔레옵에 자동으로 연결되지 않는다.

일반 시연은 비전 프로그램과 Unity 데모를 각각 실행하고, Unity에서 수동·웹캠 제어 상태를 사용한다.
미리보기에서 손이 검출되고 Unity의 수신 상태와 관절이 반응하면 경로를 확인할 수 있다.
실물 구동을 추가하려면 별도의 SDK 브리지와 장비 접속이 필요하다.
비전 프로그램의 `--bridge`는 **송신 대상을 추가할 뿐 브리지 프로세스를 실행하지 않는다.**

## 1. 손 텔레옵 파이프라인 — 흐름

```text
웹캠 프레임
  → MediaPipe Hands (손 랜드마크 21점)
  → dg5f_angles.compute_raw()      관절각·엄지 거리 등의 동작 신호 계산
  → dg5f_angles.map_to_dg5f()      로봇 20관절 각도(deg)로 변환 + 로봇 리밋 clamp
  → One Euro 필터                   떨림 제거
  → UDP 송신 ─┬─ 5006 → Unity Dg5fReceiver (시뮬 손)
              └─ 5008 → dg5f_sdk_bridge.py → 실물 DG-5F   (--bridge 옵션)
```

위 포트는 기본값이다. `vision_node_dg5f.py`는 Unity로 항상 송신하고 `--bridge`를 주면
손 브리지로도 같은 패킷을 보낸다. 현재 이 진입점은 두 대상에 `UNITY_IP`를 공유하므로,
Unity와 브리지가 다른 PC라면 별도 송신 대상 설정이 가능한 GUI 등의 경로를 확인해야 한다.
웹캠 송신과 실물 피드백은 같은 UDP 5006을 쓰므로 **동시에 켜면 수신값이 섞인다**.
실물 실제각을 확인할 때는 웹캠 송신을 멈춘다. [브리지의 현재 제한](REAL_BRIDGES.md)도 함께 확인한다.

기본 진입점은 손이 한 번 검출된 뒤 가려지면 **마지막 유효 명령을 계속 송신**한다.
따라서 Unity의 UDP 수신 표시만으로 현재 손이 보이고 있다고 판단하면 안 된다.
손 검출 상태는 비전 미리보기에서 따로 확인한다.
근거: [vision_node_dg5f.py의 last_valid 처리](../../vision/dg5f/vision_node_dg5f.py).

### 진입점 2개 (같은 계산, 다른 껍데기)

| 파일 | 성격 |
|---|---|
| `vision_node_dg5f.py` | **미리보기 창을 사용하는 기본 진입점.** 별도 제어 패널은 없지만 화면 없이 실행하는 headless 프로그램은 아님. 현재 exe 빌드 대상 |
| `dg5f_teleop_gui.py` | **GUI 컨트롤 패널.** 송신 대상 IP/포트, 매핑 모드, 사람 보정값, 관절 제한을 **실행 중에** 바꿔 볼 수 있다. 현재 제공된 exe 빌드 스크립트의 대상은 아님 |

`dg5f_teleop_gui.py`는 성능을 위해 3스레드로 나뉘어 있다 — 캡처 / 처리(MediaPipe·매핑·송신) / Tk 화면.
각 단계는 "최신 1개만 유지하는 슬롯"으로 연결되고 밀린 프레임은 버린다. 예전에 한 스레드에서 다 하다
슬라이더 조작이 프레임 뒤로 밀려 굳던 문제를 고친 구조다.

### 계산 엔진

| 파일 | 하는 일 |
|---|---|
| `dg5f_angles.py` | **핵심.** MediaPipe 특징점 → 동작 신호 → 로봇 20관절각 변환. 보정·기본 진입점·GUI가 공유한다 |
| `one_euro_filter.py` | 적응형 저역통과 필터. 느린 움직임에선 부드럽게, 빠른 움직임에선 반응성 유지. 관절 채널마다 독립 인스턴스 |
| `joint_ranges.py` | 사람과 로봇의 관절 가동범위 대조표. 매핑 구현의 정본은 `dg5f_angles.py`이며 전 채널이 동일한 1:1 변환은 아님 |
| `dg5f_paths.py` | 로그·보정 파일 경로 규칙의 단일 출처. 실행마다 새 로그 파일(초 단위 + 중복 시 접미사)을 보장해 덮어쓰기 사고를 막는다 |

### 패킷 계약 (버전이 붙어 있다)

float32 little-endian 배열이다. 숫자 하나가 4바이트이고, little-endian은 바이트 저장 순서다.
현재 Unity 수신기는 최소 20개 값을 읽고 패킷 길이에 따라 추가 필드를 읽는다.
SDK 브리지는 앞의 관절 20개를 사용한다. 새로운 수신기를 만들 때도 이 길이 규칙을 지켜야 한다.

| 인덱스 | 내용 |
|---|---|
| `[0..19]` | DG5F 20관절 각도[deg] — 엄지/검지/중지/약지/새끼 순, 손가락당 4관절 |
| `[20..22]` | 엄지 끝 정규화 좌표 |
| `[23]` | 핀치 플래그 |
| `[24]` | 엄지-검지 끝거리 비율(연속값) |
| `[25..36]` | 검지·중지·약지·새끼의 리치 벡터(엄지는 `[20..22]`) |
| `[37..51]` | 손목→손끝 벡터 5개 |
| `[52..71]` | `compute_raw`의 매핑 전 값(디버그). 대부분 rad 각도이나 엄지 대향 등 거리 기반 신호도 포함 |

관절 명령은 `[0..19]`의 deg 값이다. 뒤의 정규화 벡터는 로봇 치수에 맞춰 손끝 위치를 재구성할 때 쓰며,
그대로 실물 공간의 미터 좌표로 취급하지 않는다. Unity의 손가락 IK(손끝 목표에서 관절각을 계산하는 기능)가
활성일 때는 해당 손가락을 IK가 구동하고 일반 각도 구동은 비켜준다. [UNITY.md](UNITY.md) 참고.

### 보정 (캘리브레이션)

| 파일 | 하는 일 |
|---|---|
| `calibrate_dg5f.py` | 본인 손의 동작 범위와 보정값을 `dg5f_calibration.json`에 저장. 모든 실행의 필수 조건은 아니며, 사용하는 매핑과 손끝 계산에 따라 보정 영향이 다름 |

| 매핑·계산 | 실제 동작 | 보정의 영향 |
|---|---|---|
| `direct`(기본) | 일반 굽힘은 rad→deg 후 로봇 한계 제한. 벌림에는 게인, 엄지에는 별도 매핑·좌우 부호 규칙 사용 | 일반 채널의 사람 최소·최대 범위를 사용하지 않음 |
| `ratio` | 사람 가동범위의 비율을 로봇 가동범위로 옮김. 엄지·벌림에는 별도 분기 | 사람 가동범위 보정이 결과에 영향. 보정 당시 자세·계산 규약 확인 필요 |
| 엄지 손끝 계산 | 특징점에서 손끝 목표를 재구성 | 엄지 직진도 보정값 사용 가능 |

보정 파일이 없으면 기본값으로 동작한다. 기본 실행이 되는지 확인한 뒤, 사용할 모드에서 손의 중립·끝범위가
맞는지 확인하고 보정한다. 모든 어긋남을 재보정으로 해결할 수 있는 것은 아니다.
근거: [map_to_dg5f·보정 로드](../../vision/dg5f/dg5f_angles.py).

## 2. 검증·분석 도구

실물/시뮬이 "정말 손을 따라가고 있는가"를 로그로 판정하는 스크립트들. 눈으로 보고 판단하지 않기 위한 장치다.

| 파일 | 무엇을 판정하나 |
|---|---|
| `analyze_teleop.py` | 사람 손 로그 ↔ Unity 관절 로그를 시간 정렬해 4가지를 본다: ① 전송 무결성 ② 리밋 초과 비율 ③ 물리 추종 오차 ④ 사람 동작 재현 상관. 합격선까지 정해져 있다(상관 ≥0.90, 추종 RMS ≤3°) |
| `probe_sender.py` | **웹캠 없이** 정해진 포즈 패킷을 50Hz로 쏜다. 배선·매핑이 맞는지 결정적으로 확인하는 용도(`fist`, `open`, `oktip`, `idxabd` 등 시나리오별) |
| `probe_landmarks.py` | MediaPipe 랜드마크 원본을 통째로 CSV 기록. 계산된 각도만 남기는 라이브 로그로는 검증 불가능한 질문(“손바닥 접힘이 신호로 잡히나”)을 답하기 위해 |
| `analyze_lmprobe.py` | 위 로그를 분석 — 랜드마크 안정성과 후보 지표들의 신호/잡음비 |
| `analyze_thumbik.py` | Unity 엄지 IK 디버그 로그 분석. 오차를 "축 부호 문제 / 오프셋 문제 / 물리 추종 실패 / 작업공간 밖" 중 무엇인지 계층 분리해준다 |

문제는 순서대로 좁힌다. **카메라가 열리는가 → 손이 검출되는가 → UDP를 보내는가 → Unity가 받는가 →
현재 손 제어권이 웹캠에 있는가**를 확인한다. 수신은 되는데 주먹 버튼 이후 안 움직이면
재보정보다 Unity의 웹캠 복귀 버튼을 먼저 확인한다. 분석 로그의 Unity 실제각은 시뮬레이션 값이다.

## 3. 다중 카메라 3D 삼각측량

카메라 1대 MediaPipe는 **깊이 추정이 부정확**하다. 그걸 카메라 여러 대로 개선하려는 별도 경로다.
현재 손 텔레옵 라이브 경로는 여전히 카메라 1대를 쓰고, 이 모듈은 그것을 건드리지 않는다.

```text
1) calibrate_intrinsics.py   카메라마다 1회 — 렌즈 왜곡·초점거리(K, dist)
2) calibrate_extrinsics.py   모든 카메라가 같은 체스보드를 동시에 보는 상태에서 카메라 자세(R,t)
3) multiview_landmarks.py    카메라별 MediaPipe 픽셀좌표 → 삼각측량 → (21,3) 3D 랜드마크
   └ camera_calibration.py   저장/로드 + DLT 삼각측량 수학 (공용 모듈)
   └ multi_camera_capture.py 카메라 N대를 각각 전용 스레드로 구동(한 대가 느려도 나머지 유지)
```

- 좌표계 규약: `(R, t)`는 "보드 좌표계 → 카메라 좌표계". 세 카메라가 **같은 순간 같은 보드**를 봤다는
  전제 덕분에 별도 번들 조정 없이 공통 좌표계가 만들어진다.
- ⚠️ 실시간 경로에 연결할 때 **프레임을 좌우 반전하지 말 것** — 캘리브레이션은 원본 프레임으로 했다.
- 수학 구현은 `tests/test_camera_calibration.py`의 합성 카메라 3대 시나리오로 검증한다.
  이 테스트는 실제 카메라의 동기화·캘리브레이션 정확도를 보장하지 않는다. 보드 기준 3D 좌표를
  로봇에 적용하려면 보드/카메라 좌표계와 로봇 베이스 사이의 변환도 별도로 필요하다.

## 4. ZED 객체 검출 (`vision/zed_object_detection/`) — ⛔ 폐기, 사용하지 않는다

**이 폴더의 코드는 더 이상 사용하지 않는다.** 현재 파이프라인 어디에도 연결돼 있지 않고,
새 작업의 출발점으로 삼지 말 것. 남겨 둔 것은 과거 기록으로서일 뿐이다.

- 스테레오 카메라 ZED 2i로 물체 3D 좌표를 뽑아 Unity로 UDP 송신하려던 경로였다
  (`zed_sender.py` = YOLO 2D 검출 + ZED SDK 3D 트래킹, `capture_dataset.py`/`label_tool.py`/
  `train_custom_yolo.py` = 그 YOLO를 파인튜닝하기 위한 데이터셋 도구들).
- **수신 측이 이미 없다.** `zed_sender.py`가 보낸다고 적어 둔 Unity
  `Assets/Scripts/CameraTargetReceiver.cs`는 저장소에 존재하지 않는다. 즉 코드를 그대로 실행해도
  받는 쪽이 없다.
- `config/rtauto_config.py`의 `PORT_ZED_TARGET`(5007)도 이 경로 전용이라 현재 쓰이지 않는다.
  다만 과거에 포트 충돌 이력이 있으므로(구 5007 → DG5F 브리지가 5008로 이동) **다른 용도로 재사용하지 말 것.**
- 물체 위치 인식이 다시 필요해지면 하드웨어·라이브러리 선택부터 새로 정한다
  ([`SIM2REAL_ROADMAP.md`](../SIM2REAL_ROADMAP.md) 참고). 이 코드를 되살리는 것을 전제하지 않는다.

## 5. 배포용 스크립트

| 파일 | 하는 일 |
|---|---|
| `build_demo_exe.ps1` | `vision_node_dg5f.py`를 PyInstaller로 패키징. exe와 동봉 데이터·DLL 폴더를 함께 배포하며, 원본 저장소 밖에서 실행 검증 필요 |
| `RunDemo.ps1` | 배포 폴더에서 텔레옵 exe + Unity 빌드를 한 번에 띄우는 런처 |

배포 파일 구성은 `RunDemo.ps1` 상단에 있다. 빌드 성공이 새 PC 실행 성공을 보장하지 않으며,
설정 파일 위치는 [BUILD_TOOLING.md](BUILD_TOOLING.md)의 Python·Unity 차이를 따른다.

## 6. 코드 레벨 핵심 — 함수·상수·인자

### 6-1. 계산 파이프라인의 실제 함수 (`dg5f_angles.py`)

한 프레임이 처리되는 순서 그대로다. 새 진입점을 만들 때 이 순서를 그대로 재현해야 한다.

| 순서 | 함수 | 입출력 |
|---|---|---|
| ① | `landmarks_to_xyz(hand_landmarks, frame_shape)` | MediaPipe 결과 → 종횡비 등방 보정된 21×3 배열. **이 함수는 `dg5f_angles`가 소유한다** — 진입점에 사본을 만들면 보정과 라이브가 다른 좌표계를 쓰게 된다(2026-07-28 통합) |
| ② | `compute_raw(lm)` | → 20채널 "동작 신호" 리스트. 대부분 rad 각도지만 `thumb_opp`만 **거리 기반**이다 |
| ③ | `map_to_dg5f(raw, hand="right", mode="direct")` | → 로봇 20관절각[deg] + 로봇 리밋 clamp |
| ④ | `OneEuroFilter` 채널별 인스턴스 | 떨림 제거 |
| ⑤ | `compute_thumb_tip` / `compute_finger_tips` / `compute_wrist_tip_vectors` | 손끝·리치 벡터(정규화). Unity 손가락 IK의 입력 |
| ⑥ | `struct.pack(PACKET_FMT, ...)` → UDP | `PACKET_FMT = "<72f"`, `PACKET_LEN = 72` |

- 채널 이름 정본: `CHANNEL_NAMES` (= `DG5F_CHANNELS`의 첫 열). **Unity `Dg5fHandDriver.JointLabels`와
  같은 순서여야 한다** — 한쪽만 고치면 관절이 조용히 어긋난다.
- `DG5F_CHANNELS`의 각 행 = `(name, hmin, hmax, dg_min, dg_max, gated)`.
  `dg_min/dg_max`가 **로봇 clamp 경계**이고, `hmin/hmax`(사람 범위)는 `direct` 모드에선 미사용이다.
- 특수 분기 3개(일반 채널 규칙이 안 통하는 곳): `thumb_cmc`는 `THUMB_CMC_FOLD_DEG(-65°)`↔
  `THUMB_CMC_SPREAD_DEG(+22°)` 양방향 선형매핑, `thumb_opp`는 `THUMB_OPP_D_OPEN(1.33)`↔
  `THUMB_OPP_D_FULL(0.31)` 거리 기반 + `THUMB_OPP_GAIN(95.0)`, 벌림 채널
  (`ABDUCTION_CHANNELS`)은 `ABD_GAIN(1.0)` 게인.
- 좌우 손: `LEFT_MIRROR_CHANNELS` / `RIGHT_MIRROR_CHANNELS`가 부호를 뒤집을 채널을 정한다
  (오른손은 `thumb_cmc` 하나뿐).
- DIP는 측정하지 않고 PIP에서 유도한다: `DIP_PIP_COUPLING = 0.75`
  (새끼 원위는 로봇 관절이 1개뿐이라 `(1+k)×PIP`).

### 6-2. 진입점 실행 인자

`vision_node_dg5f.py`는 argparse를 쓰지 않고 `sys.argv`를 직접 본다 — 인자 형식이 고정이다.

```text
python vision/dg5f/vision_node_dg5f.py [right|left] [--bridge] [--map=direct|ratio]
```

| 인자 | 뜻 |
|---|---|
| 위치인자 `right`/`left` | 손 좌우 (기본 `right`) |
| `--bridge` | **UDP 5008로도 같은 패킷을 보낸다.** 브리지 프로세스를 실행하지는 않는다 |
| `--map=direct` (기본) / `--map=ratio` | 매핑 방식. `ratio`는 사람 가동범위 보정에 의존 |

주요 상수: `SEND_HZ_CAP = 120`, 창 `1280×720`,
MediaPipe `model_complexity=1, max_num_hands=1, min_detection/tracking_confidence=0.6`,
One Euro 각도 채널 `freq=30, min_cutoff=0.6, beta=0.0005` / 손끝 위치 채널 `min_cutoff=0.15, beta=0.5`.
`USE_WORLD_LANDMARKS = False`가 현재 값이다 — world 랜드마크는 평평한 손가락을 z노이즈로
15~27° 굽은 것처럼 잡았고, 보정 파일도 이미지 랜드마크 기준이라 False가 보정과 일치한다(2026-07-22).

### 6-3. 파일 경로·보정 파일

| 상수 | 값 | 소스 |
|---|---|---|
| `LOG_DIR` | `vision/dg5f/logs/` | `dg5f_paths.py` |
| `CALIB_PATH` | `vision/dg5f/dg5f_calibration.json` | `dg5f_paths.py` |
| `unique_log_path(prefix)` | `logs/<prefix>_<초타임스탬프>.csv`, 중복 시 접미사 | 덮어쓰기 방지 |
| `CALIB_VERSION` | 3 | v3 = `thumb_straight_ratio`. v2의 `thumb_reach_ratio`는 폐기 |

보정 파일이 없으면 `DEFAULT_THUMB_STRAIGHT(0.97)` · `DEFAULT_FINGER_STRAIGHT(0.98)` 기본값으로 동작한다.
`joint_ranges.py`는 `_LIVE` 플래그로 "지금 표에 보이는 사람 범위가 보정 파일에서 온 값인지"를 구분한다.

### 6-4. 웹캠 없이 배선을 검증하는 법 (`probe_sender.py`)

미리 정의된 20관절 자세를 50Hz로 UDP 5006에 쏜다. 카메라·MediaPipe·매핑을 전부 건너뛰므로
**"Unity가 안 움직인다"의 원인이 비전인지 수신/구동인지를 한 번에 가른다.**
내장 자세 상수: `OPEN`(전부 0) · `FIST` · `OK`(OK 사인) 등, 시나리오 키는 `IDX_MODES`.
왼손은 `mirror_left(vals)`로 부호를 뒤집는다.

### 6-5. 다중 카메라 모듈의 공용 함수 (`camera_calibration.py`)

| 함수 | 하는 일 |
|---|---|
| `chessboard_object_points(cols, rows, square_size_mm)` / `find_board_corners(gray, cols, rows)` | 보드 규격은 `.env`의 `RTAUTO_CALIB_BOARD_COLS/ROWS`(9×6)·`RTAUTO_CALIB_SQUARE_SIZE_MM`(25.0) |
| `save_intrinsics` / `load_intrinsics` / `load_all_intrinsics` | 카메라별 `K`·`dist`. 저장 위치는 `RTAUTO_CALIB_DIR`(기본 `vision/dg5f/camera_calib`) |
| `save_extrinsics` / `load_extrinsics` / `build_camera_rig(...)` | `(R, t)` = **보드 좌표계 → 카메라 좌표계** |
| `undistort_normalize(pixel_xy, K, dist)` → `triangulate_point(views)` → `triangulate_landmark_set(..., min_views=2)` | DLT 삼각측량. `min_views=2` 미만인 랜드마크는 버린다 |

라이브 쪽은 `multiview_landmarks.py`의 `hand_landmarks_to_pixels()` → `triangulate_hands(..., rig)`.
⚠️ 이 경로에 프레임 좌우 반전을 넣으면 안 된다 — 캘리브레이션을 원본 프레임으로 했다.

### 6-6. 분석 도구의 합격 기준 상수 (`analyze_teleop.py`)

`CORR_PASS = 0.90` / `CORR_WARN = 0.70` (사람 동작 재현 상관 — 0.70 미만이면 FAIL),
`TRACK_RMS_TOL = 3.0°` (Unity 목표각 vs 실측각 — 물리 추종),
`FOLLOW_RMS_TOL = 10.0°` (송신값 vs 실측각 — 클램프 포함 잔여오차).
시간 정렬은 `best_lag_corr(..., max_lag=0.6, fs=50.0)`로 ±0.6초 안에서 상관 최대 지연을 찾아 맞춘다.
채널 키는 `JOINT_KEYS = ["1_1", "1_2", ... "5_4"]`로 `CHANNEL_NAMES`와 같은 순서다.
