#!/usr/bin/env python3
"""
DGSDK fingertip sensor readout example

Streams Force/Torque + tactile summary for ~5 seconds at 20 Hz.

Connection sequence:
1. set_gripper_system()   - system setting
2. connect_to_gripper()   - connect to gripper
3. set_gripper_option()   - request FINGER_FT_SENSOR in receivedDataType
4. system_start()         - start system
5. get_fingertip_sensor_data() in a 20 Hz loop

NOTE: DGSDK 2.0.0 does NOT support the legacy DG-3F-B model.
NOTE: receivedDataType MUST include FINGER_FT_SENSOR or sensor frames stay empty.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dgsdk import (
    DGSDK,
    GripperSystemSetting,
    GripperSetting,
    ControlMode,
    CommunicationMode,
    DGModel,
    DGResult,
    DGSensorType,
    ReceivedDataType,
)

""" Enter Gripper Connection Details """
# Modify the settings to match the gripper you want to connect to.
# Please check the files under src/dgsdk/types.py
MODEL = DGModel.DG_5F_S_RIGHT
CONTROL_MODE = ControlMode.OPERATOR
GRIPPER_IP = "169.254.186.72"
GRIPPER_PORT = 502
JOINT_COUNT = 20
FINGER_COUNT = 5
""" -------------------------------- """

DURATION_S = 5.0
PERIOD_S = 0.05  # 20 Hz
AXES = ("Fx", "Fy", "Fz", "Tx", "Ty", "Tz")


def finger_ft(ft_flat, finger_idx):
    """Slice 6-axis FT for one finger"""
    base = finger_idx * 6
    return ft_flat[base:base + 6]


def finger_tactile(tac_flat, finger_idx):
    """Slice 18 tactile cells for one finger"""
    base = finger_idx * 18
    return tac_flat[base:base + 18]


def print_frame(data, first):
    """Render one frame, overwriting the previous block"""
    lines = []
    try:
        stype = DGSensorType(data.sensorType).name
    except ValueError:
        stype = f"UNKNOWN({data.sensorType})"
    lines.append(f"sensorType: {stype}")

    ft = list(data.forceTorque)
    tac = list(data.tactile)
    header = "finger | " + " ".join(f"{a:>8}" for a in AXES) + " | tactile min/avg/max"
    lines.append(header)
    for i in range(FINGER_COUNT):
        vals = finger_ft(ft, i)
        ft_str = " ".join(f"{v:+8.3f}" for v in vals)
        tcells = finger_tactile(tac, i)
        tmin, tmax = min(tcells), max(tcells)
        tavg = sum(tcells) / len(tcells)
        lines.append(f"  #{i+1}  | {ft_str} | {tmin:5d} / {tavg:7.1f} / {tmax:5d}")

    block = "\n".join(lines)
    if not first:
        # Move cursor up N lines and clear to end of screen.
        sys.stdout.write(f"\033[{len(lines)}A\033[J")
    sys.stdout.write(block + "\n")
    sys.stdout.flush()


def main():
    # Initialize gripper
    gripper = DGSDK()
    print("[OK] library loaded")

    # Show loaded lib version
    major, minor, patch = gripper.get_library_version()
    print(f"     DGSDK version: {major}.{minor}.{patch}")

    try:
        # =====================================================
        # 1. System setting
        # =====================================================
        result = gripper.set_gripper_system(
            GripperSystemSetting.create(
                ip=GRIPPER_IP, port=GRIPPER_PORT,
                control_mode=CONTROL_MODE,
                communication_mode=CommunicationMode.ETHERNET,
            )
        )
        print(f"1. system setting: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        # =====================================================
        # 1.5 Register callbacks (before connect)
        # =====================================================
        gripper.on_connected(lambda: print("   -> connected"))
        gripper.on_disconnected(lambda: print("   -> disconnected"))

        # =====================================================
        # 2. Connect
        # =====================================================
        print("2. connecting...", flush=True)
        result = gripper.connect_to_gripper()
        print(f"2. connect: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        # =====================================================
        # 3. Gripper option
        # NOTE: receivedDataType must include FINGER_FT_SENSOR.
        # NOTE: DG_3F_B is not supported by DGSDK 2.0.0.
        # =====================================================
        recv_types = [
            ReceivedDataType.JOINT,
            ReceivedDataType.CURRENT,
            ReceivedDataType.FINGER_FT_SENSOR,
            0, 0, 0, 0,
        ]
        result = gripper.set_gripper_option(
            GripperSetting.create(
                model=MODEL,
                joint_count=JOINT_COUNT,
                finger_count=FINGER_COUNT,
                received_data_type=recv_types,
            )
        )
        print(f"3. gripper option: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        # Option must settle before system_start() or it returns NOT_FOUND_MODEL.
        time.sleep(0.5)

        # =====================================================
        # 4. Start system
        # =====================================================
        result = gripper.system_start()
        print(f"4. system start: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        time.sleep(0.3)  # let first frames arrive
        print("\n[OK] connected")

        # =====================================================
        # Stream sensor frames
        # =====================================================
        print(f"\nstreaming {DURATION_S:.0f}s at {1/PERIOD_S:.0f} Hz\n")
        deadline = time.monotonic() + DURATION_S
        first = True
        while time.monotonic() < deadline:
            try:
                data = gripper.get_fingertip_sensor_data()
            except RuntimeError as e:
                print(f"read failed: {e}")
                break
            print_frame(data, first)
            first = False
            time.sleep(PERIOD_S)

    except Exception as e:
        print(f"\nerror: {e}")

    finally:
        # =====================================================
        # Teardown
        # =====================================================
        print("\nclosing...")
        gripper.system_stop()
        time.sleep(0.2)
        gripper.disconnect_to_gripper()
        print("[OK] closed")


if __name__ == "__main__":
    main()
