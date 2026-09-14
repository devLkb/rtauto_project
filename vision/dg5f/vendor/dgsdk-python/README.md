# DGSDK

Official Python wrapper for the Delto Gripper SDK.

> 🇰🇷 한국어 문서는 [README_KR.md](./README_KR.md)를 참고하세요.

It automatically loads the right shared library for your OS (Linux / Windows)
so you can drive a Tesollo Delto Gripper from Python.

## Compatibility

| Item | Version |
|------|---------|
| Bundled DGSDK binary | **2.0.0** |
| Supported grippers | Firmware 3.0+ released models |
| Excluded | Legacy **DG-3F-B** (not supported by DGSDK 2.0.0+) |
| Architecture | **x86_64 (x64) only** — ARM / 32-bit emits a warning and is not supported |
| OS | Linux (`libDGSDK.so`), Windows (`DGSDK.dll`) |

Check the shipped lib version at runtime:

```python
from dgsdk import DGSDK

print(DGSDK().get_library_version())  # -> [2, 0, 0]
```

## Install

Distributed locally — clone the repo and let `uv` resolve everything.

```bash
cd dgsdk-python
uv sync
```

`uv sync` reads `pyproject.toml` / `uv.lock`, creates a `.venv`, and installs
the package in editable mode. Run examples with `uv run`:

```bash
uv run python examples/basic_connection.py
```

## Quick Start

```python
from dgsdk import (
    DGSDK, GripperSystemSetting, GripperSetting,
    ControlMode, CommunicationMode, DGModel, DGGraspMode,
)

gripper = DGSDK()
print("lib version:", gripper.get_library_version())

# 1. System setting
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

# 2. Connect
gripper.connect_to_gripper()

# 3. Gripper option (model, joint/finger count)
gripper_setting = GripperSetting.create(
    model=DGModel.DG_3F_M,  # DG_3F_B is NOT supported by DGSDK 2.0.0
    joint_count=12,
    finger_count=3,
)
gripper.set_gripper_option(gripper_setting)

# 4. Start system
gripper.system_start()

# Move all joints
gripper.move_joint_all([0.0, 0.0, 70.0, 30.0] * 3)

# Grasp
gripper.set_grasp_data(
    DGGraspMode._3F_3FINGER,
    grasp_force=10.0, grasp_option=0, smooth_grasping=0,
)
gripper.grasp(1)  # 1 = grasp, 0 = release

# Teardown
gripper.system_stop()
gripper.disconnect_to_gripper()
```

### Connection sequence (required order)

```
1. set_gripper_system()   → system settings (IP, port, comm mode)
2. connect_to_gripper()   → open connection
3. set_gripper_option()   → gripper option (model, joint count)
4. system_start()         → start system (data RX / control enabled)
```

You **must** follow this order.

### Context manager

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
    # system_stop() + disconnect_to_gripper() are called automatically on exit
```

## API Overview

### System

| Method | Description |
|--------|-------------|
| `get_library_version()` | Return `[major, minor, patch]` of the loaded DGSDK |
| `set_gripper_system(setting)` | Configure communication |
| `set_gripper_option(setting)` | Configure gripper model / options |
| `connect_to_gripper()` / `disconnect_to_gripper()` | Open / close the connection |
| `system_start()` / `system_stop()` | Start / stop data RX and control |
| `set_ip(ip, port)` | Change gripper IP/port at runtime |

### Motion

| Method | Description |
|--------|-------------|
| `move_joint(target, joint_number)` | Move one joint |
| `move_joint_all(targets)` | Move all joints |
| `move_joint_finger(targets, finger_number)` | Move one finger's joints |
| `move_servo_joint(targets)` | Real-time servo move (DEVELOPER mode) |
| `grasp(is_grasp)` | Grasp motion — `1` grasp, `0` release |
| `manual_teach_mode(is_on)` | Enable/disable manual teach mode |
| `set_joint_encoder_zero()` | Set current joint position as encoder zero |

### Configuration

| Method | Description |
|--------|-------------|
| `set_grasp_data(mode, force, option, smooth)` | Set grasp parameters |
| `set_grasp_force(force)` | Update grasp force only |
| `set_joint_gain_pid_all(p, d, i, limit)` | Set PID gains for all joints |
| `set_motion_time_all(times)` | Set per-joint motion times |
| `set_gpio_output(gpio, output_number)` | Set one GPIO output (`gpio` = value, `output_number` = pin index) |
| `set_gpio_output_all(output)` | Set all GPIO outputs (list) |

### Data

| Method | Description |
|--------|-------------|
| `get_gripper_data()` | Latest gripper state (joint, current, TCP, errors, ...) |
| `get_current_tcp_pose()` | Current TCP coordinates |
| `get_communication_period()` | Communication cycle (Hz) |
| `get_fingertip_sensor_data()` | Fingertip sensor (FT + tactile) data |
| `get_gpio_data()` | GPIO state |

### Callbacks

```python
def on_data(data):
    print(f"joint={list(data.joint)} err={data.moduleErrorCode}")

gripper.on_gripper_data(on_data)
gripper.on_connected(lambda: print("Connected"))
gripper.on_disconnected(lambda: print("Disconnected"))
```

## Supported Models

| Model | Description | Notes |
|-------|-------------|-------|
| `DG_1F_M` | 1 finger | |
| `DG_2F_M` | 2 finger | |
| `DG_3F_B` | 3 finger (Basic) | **Legacy — NOT supported by DGSDK 2.0.0+** |
| `DG_3F_M` | 3 finger (Multi) | |
| `DG_4F_M` | 4 finger | |
| `DG_5F_LEFT` / `DG_5F_RIGHT` | 5 finger | |
| `DG_5F_S_LEFT` / `DG_5F_S_RIGHT` | 5 finger (S) | |
| `DG_5F_S15_LEFT` / `DG_5F_S15_RIGHT` | 5 finger (S15) | |

## Grasp Modes

### 3F

- `DGGraspMode._3F_3FINGER` — 3-finger grasp
- `DGGraspMode._3F_2FINGER_1_AND_2` — 2-finger grasp (fingers 1, 2)
- `DGGraspMode._3F_3FINGER_PARALLEL` — 3-finger parallel grasp
- `DGGraspMode._3F_3FINGER_ENVELOP` — 3-finger envelop grasp

### 5F

- `DGGraspMode._5F_5FINGER` — 5-finger grasp
- `DGGraspMode._5F_3FINGER` — 3-finger grasp
- `DGGraspMode._5F_5FINGER_PARALLEL` — 5-finger parallel grasp

## Project Layout

```
dgsdk/
├── pyproject.toml
├── README.md           # English (this file)
├── README_KR.md        # Korean
├── libs/
│   ├── DGSDK.dll       # Windows (x64)
│   ├── libDGSDK.so     # Linux (x64)
│   ├── DGSDK.h
│   └── DGDataTypes.h
├── src/
│   └── dgsdk/
│       ├── __init__.py
│       ├── wrapper.py  # DGSDK class
│       └── types.py    # Structures and enums
├── examples/
│   ├── basic_connection.py   # minimal connect / read / move
│   ├── callbacks_streaming.py # event-driven data streaming
│   ├── grasp_cycle.py        # full grasp → hold → release
│   └── joint_movement.py     # per-joint / per-finger / all movement
└── tests/
    └── test_dgsdk.py
```

## Supported Platforms

- ✅ Linux x86_64 (`libDGSDK.so`)
- ✅ Windows x86_64 (`DGSDK.dll`)
- ⚠️ ARM / 32-bit — not supported (loads with a `RuntimeWarning`)
- ❌ macOS — not supported

## Requirements

- Python 3.8+
- `cffi >= 1.15.0`

## License

BSD 3-Clause License — see [LICENSE](./LICENSE).

## Links

- [Delto Gripper (Tesollo)](https://www.tesollo.com)
