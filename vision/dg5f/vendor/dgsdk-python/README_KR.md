# DGSDK

Delto Gripper SDK의 공식 Python 래퍼입니다.

> 🌏 English documentation: [README.md](./README.md)

운영체제(Linux/Windows)에 맞는 공유 라이브러리를 자동으로 로드하여
Python에서 Tesollo Delto Gripper를 제어할 수 있습니다.

## 호환성

| 항목 | 내용 |
|------|------|
| 번들 DGSDK 바이너리 | **2.0.0** |
| 지원 그리퍼 | 펌웨어 3.0 이상의 출시 모델 |
| 미지원 | 레거시 **DG-3F-B** (DGSDK 2.0.0+ 미지원) |
| 아키텍처 | **x86_64 (x64) 전용** — ARM / 32-bit은 경고 후 미지원 |
| OS | Linux (`libDGSDK.so`), Windows (`DGSDK.dll`) |

런타임에 라이브러리 버전 확인:

```python
from dgsdk import DGSDK

print(DGSDK().get_library_version())  # -> [2, 0, 0]
```

## 설치

로컬 배포 방식입니다. 저장소를 클론한 뒤 `uv`로 의존성을 설치하세요.

```bash
git clone <repo-url> dgsdk-python
cd dgsdk-python
uv sync
```

`uv sync`는 `pyproject.toml` / `uv.lock`을 읽어 `.venv`를 생성하고
패키지를 editable 모드로 설치합니다. 예제는 `uv run`으로 실행합니다.

```bash
uv run python examples/basic_connection.py
```

## 빠른 시작

```python
from dgsdk import (
    DGSDK, GripperSystemSetting, GripperSetting,
    ControlMode, CommunicationMode, DGModel, DGGraspMode,
)

gripper = DGSDK()
print("lib version:", gripper.get_library_version())

# 1. 시스템 설정
system_setting = GripperSystemSetting.create(
    ip="169.254.186.72",
    port=502,
    control_mode=ControlMode.OPERATOR,
    communication_mode=CommunicationMode.ETHERNET,
    read_timeout=1000,
    slave_id=1,
    baudrate=115200,
)
gripper.set_gripper_system(system_setting)

# 2. 그리퍼 연결
gripper.connect_to_gripper()

# 3. 그리퍼 옵션 설정 (모델, 조인트/핑거 수)
gripper_setting = GripperSetting.create(
    model=DGModel.DG_3F_M,  # DG_3F_B는 DGSDK 2.0.0에서 미지원
    joint_count=12,
    finger_count=3,
)
gripper.set_gripper_option(gripper_setting)

# 4. 시스템 시작
gripper.system_start()

# 전체 조인트 이동
gripper.move_joint_all([0.0, ,0.0, 70.0, 30.0] * 3)

# 파지
gripper.set_grasp_data(
    DGGraspMode._3F_3FINGER,
    grasp_force=10.0, grasp_option=0, smooth_grasping=1,
)
gripper.grasp(1)  # 1 = 파지, 0 = 릴리스

# 연결 종료
gripper.system_stop()
gripper.disconnect_to_gripper()
```

### 연결 시퀀스 (중요!)

```
1. set_gripper_system()   → 시스템 설정 (IP, 포트, 통신모드)
2. connect_to_gripper()   → 그리퍼 연결
3. set_gripper_option()   → 그리퍼 옵션 (모델, 조인트 수)
4. system_start()         → 시스템 시작 (데이터 수신/제어 가능)
```

**반드시 이 순서를 지켜야 합니다.**

### Context Manager 사용

```python
from dgsdk import DGSDK, GripperSystemSetting, GripperSetting, DGModel

with DGSDK() as gripper:
    gripper.set_gripper_system(
        GripperSystemSetting.create(ip="169.254.186.72", port=502)
    )
    gripper.connect_to_gripper()
    gripper.set_gripper_option(
        GripperSetting.create(DGModel.DG_3F_M, joint_count=12, finger_count=3)
    )
    gripper.system_start()
    gripper.move_joint_all([0.0, 0.0, 45.0, 30.0] * 3)
    # 종료 시 system_stop() 및 disconnect_to_gripper() 자동 호출
```

## API 개요

### 시스템 함수

| 함수 | 설명 |
|------|------|
| `get_library_version()` | 로드된 DGSDK의 `[major, minor, patch]` 반환 |
| `set_gripper_system(setting)` | 통신 설정 |
| `set_gripper_option(setting)` | 그리퍼 모델/옵션 설정 |
| `connect_to_gripper()` / `disconnect_to_gripper()` | 연결 / 해제 |
| `system_start()` / `system_stop()` | 데이터 수신 및 제어 시작/정지 |
| `set_ip(ip, port)` | 런타임 중 IP/포트 변경 |

### 모션 함수

| 함수 | 설명 |
|------|------|
| `move_joint(target, joint_number)` | 단일 조인트 이동 |
| `move_joint_all(targets)` | 모든 조인트 이동 |
| `move_joint_finger(targets, finger_number)` | 단일 핑거 조인트 이동 |
| `move_servo_joint(targets)` | 실시간 서보 이동 (DEVELOPER 모드 전용) |
| `grasp(is_grasp)` | 파지 동작 — `1` 파지, `0` 릴리스 |
| `manual_teach_mode(is_on)` | 수동 티칭 모드 on/off |
| `set_joint_encoder_zero()` | 현재 조인트 위치를 엔코더 영점으로 설정 |

### 설정 함수

| 함수 | 설명 |
|------|------|
| `set_grasp_data(mode, force, option, smooth)` | 파지 파라미터 설정 |
| `set_grasp_force(force)` | 파지 힘만 변경 |
| `set_joint_gain_pid_all(p, d, i, limit)` | 모든 조인트 PID 게인 설정 |
| `set_motion_time_all(times)` | 조인트별 동작 시간 설정 |
| `set_gpio_output(gpio, output_number)` | 단일 GPIO 출력 설정 (`gpio` = 출력값, `output_number` = 핀 번호) |
| `set_gpio_output_all(output)` | 전체 GPIO 출력 설정 (리스트) |

### 데이터 함수

| 함수 | 설명 |
|------|------|
| `get_gripper_data()` | 최신 그리퍼 상태 (조인트/전류/TCP/에러 코드 등) |
| `get_current_tcp_pose()` | 현재 TCP 좌표 |
| `get_communication_period()` | 통신 주기 (Hz) |
| `get_fingertip_sensor_data()` | 핑거팁 센서 (FT + 촉각) 데이터 |
| `get_gpio_data()` | GPIO 상태 |

### 콜백

```python
def on_data(data):
    print(f"joint={list(data.joint)} err={data.moduleErrorCode}")

gripper.on_gripper_data(on_data)
gripper.on_connected(lambda: print("Connected"))
gripper.on_disconnected(lambda: print("Disconnected"))
```

## 지원 모델

| 모델 | 설명 | 비고 |
|------|------|------|
| `DG_1F_M` | 1핑거 | |
| `DG_2F_M` | 2핑거 | |
| `DG_3F_B` | 3핑거 | **레거시 — DGSDK 2.0.0+ 미지원** |
| `DG_3F_M` | 3핑거| |
| `DG_4F_M` | 4핑거 | |
| `DG_5F_LEFT` / `DG_5F_RIGHT` | 5핑거 | |
| `DG_5F_S_LEFT` / `DG_5F_S_RIGHT` | 5핑거 (S) | |
| `DG_5F_S15_LEFT` / `DG_5F_S15_RIGHT` | 5핑거 (S15) | |

## 파지 모드

### 3F 모델

- `DGGraspMode._3F_3FINGER` — 3핑거 파지
- `DGGraspMode._3F_2FINGER_1_AND_2` — 2핑거 파지 (1, 2번)
- `DGGraspMode._3F_3FINGER_PARALLEL` — 3핑거 평행 파지
- `DGGraspMode._3F_3FINGER_ENVELOP` — 3핑거 감싸기 파지

### 5F 모델

- `DGGraspMode._5F_5FINGER` — 5핑거 파지
- `DGGraspMode._5F_3FINGER` — 3핑거 파지
- `DGGraspMode._5F_5FINGER_PARALLEL` — 5핑거 평행 파지

## 프로젝트 구조

```
dgsdk/
├── pyproject.toml
├── README.md           # English
├── README_KR.md        # 한국어 (현재 파일)
├── libs/
│   ├── DGSDK.dll       # Windows (x64)
│   ├── libDGSDK.so     # Linux (x64)
│   ├── DGSDK.h
│   └── DGDataTypes.h
├── src/
│   └── dgsdk/
│       ├── __init__.py
│       ├── wrapper.py  # DGSDK 클래스
│       └── types.py    # 구조체, Enum 정의
├── examples/
│   ├── basic_connection.py    # 최소 연결/읽기/이동
│   ├── callbacks_streaming.py # 콜백 기반 데이터 스트리밍
│   ├── grasp_cycle.py         # 파지 → 유지 → 릴리스
│   └── joint_movement.py      # 단일/핑거/전체 조인트 이동
└── tests/
    └── test_dgsdk.py
```

## 지원 플랫폼

- ✅ Linux x86_64 (`libDGSDK.so`)
- ✅ Windows x86_64 (`DGSDK.dll`)
- ⚠️ ARM / 32-bit — 미지원 (`RuntimeWarning` 발생)
- ❌ macOS — 미지원

## 요구사항

- Python 3.8+
- `cffi >= 1.15.0`

## 라이센스

BSD 3-Clause License — [LICENSE](./LICENSE) 참조.

## 링크
- [Delto Gripper (Tesollo)](https://www.tesollo.com)
