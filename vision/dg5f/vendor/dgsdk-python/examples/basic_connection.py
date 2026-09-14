#!/usr/bin/env python3
"""
DGSDK basic connection example

Connection sequence:
1. set_gripper_system()   - system setting
2. connect_to_gripper()   - connect to gripper
3. set_gripper_option()   - gripper option
4. system_start()         - start system

NOTE: DGSDK 2.0.0 does NOT support the legacy DG-3F-B model.
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
        system_setting = GripperSystemSetting.create(
            ip=GRIPPER_IP,
            port=GRIPPER_PORT,
            control_mode=CONTROL_MODE,
            communication_mode=CommunicationMode.ETHERNET,
            read_timeout=1000,
            slave_id=1,
            baudrate=115200,
        )

        result = gripper.set_gripper_system(system_setting)
        print(f"1. system setting: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        # =====================================================
        # 1.5 Register callbacks (before connect)
        # =====================================================
        connected = False

        def on_connected():
            nonlocal connected
            connected = True
            print("   -> connected callback")

        gripper.on_connected(on_connected)
        gripper.on_disconnected(
            lambda: print("   -> disconnected callback")
        )

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
        # NOTE: DG_3F_B is not supported by DGSDK 2.0.0.
        # =====================================================
        recv_types = [
            ReceivedDataType.JOINT,
            ReceivedDataType.CURRENT,
            ReceivedDataType.TEMPERATURE,
            ReceivedDataType.VELOCITY,
            0, 0, 0,
        ]
        
        gripper_setting = GripperSetting.create(
            model=MODEL,
            joint_count=JOINT_COUNT,
            finger_count=FINGER_COUNT,
            moving_inpose=0.5,
            received_data_type = recv_types,
        )

        result = gripper.set_gripper_option(gripper_setting)
        print(f"3. gripper option: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        time.sleep(0.01)  # wait for settings to apply

        # =====================================================
        # 4. Start system
        # =====================================================
        result = gripper.system_start()
        print(f"4. system start: {result.name}")

        if result != DGResult.NONE:
            print(f"   error: {result.name}")
            return

        print("\n[OK] connected")

        # =====================================================
        # Read data
        # =====================================================
        time.sleep(0.5)

        try:
            data = gripper.get_gripper_data()
            print("\ngripper data:")
            print(f"  Joint:        {list(data.joint[:JOINT_COUNT])}")
            print(f"  Current:      {list(data.current[:JOINT_COUNT])}")
            print(f"  Moving:       {data.moving}")
            print(f"  Product ID:   {hex(data.productID)}")
            print(f"  Module Error: {data.moduleErrorCode}")
        except RuntimeError as e:
            print(f"  read failed: {e}")

        # =====================================================
        # Move joints
        # =====================================================
        print("\nmoving joints...")
        target = [0.0] * JOINT_COUNT
        # target[11] = 45.0  # move joint #12 to 45deg
        result = gripper.move_joint_all(target)
        print(f"  result: {result.name}")

        time.sleep(2.0)

    except Exception as e:
        print(f"\nerror: {e}")

    finally:
        # =====================================================
        # Teardown
        # =====================================================
        print("\nclosing...")
        gripper.system_stop()
        time.sleep(0.5)
        gripper.disconnect_to_gripper()
        print("[OK] closed")


if __name__ == "__main__":
    main()
