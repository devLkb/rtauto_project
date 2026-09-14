#!/usr/bin/env python3
"""
DGSDK joint-level movement example

Demonstrates:
  - move_joint(target, joint_number)       : single joint
  - move_joint_finger(targets, finger_num) : finger sub-group
  - move_joint_all(targets)                : every joint
  - set_motion_time_all_equal(ms)          : speed tuning

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

MOTION_TIME_MS = 500  # default per-segment travel time


def wait_for_arrival(gripper, timeout=1.0):
    """Poll until targetArrived or timeout"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = gripper.get_gripper_data()
        if data.targetArrived == 1:
            return True
        time.sleep(0.05)
    return False


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
                ip=GRIPPER_IP,
                port=GRIPPER_PORT,
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
        # NOTE: DG_3F_B is not supported by DGSDK 2.0.0.
        # =====================================================
        result = gripper.set_gripper_option(
            GripperSetting.create(
                model=MODEL,
                joint_count=JOINT_COUNT,
                finger_count=FINGER_COUNT,
            )
        )
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
        # Motion sequence
        # =====================================================
        gripper.set_motion_time_all_equal(MOTION_TIME_MS)

        # 1) home: all joints to 0
        print("\n[1] home")
        gripper.move_joint_all([0.0] * JOINT_COUNT)
        wait_for_arrival(gripper)

        # 2) move one joint
        print("[2] single joint: joint #4 = 30deg")
        gripper.move_joint(30.0, joint_number=4)
        wait_for_arrival(gripper)

        # 3) move one finger's joints
        print("[3] finger #2 sub-group: [0, 0, 40, 40]")
        gripper.move_joint_finger([0.0, 0.0, 40.0, 40.0], finger_number=2)
        wait_for_arrival(gripper)

        # 4) move all joints
        print("[4] all joints")
        target = [0.0, 30.0, 20.0, 10.0] * FINGER_COUNT  # repeat per-finger pattern
        gripper.move_joint_all(target)
        wait_for_arrival(gripper)

        # 5) speed tuning + return home
        print("[5] fast home (50 ms)")
        gripper.set_motion_time_all_equal(50)
        gripper.move_joint_all([0.0] * JOINT_COUNT)
        wait_for_arrival(gripper)

        # 6) read final state
        data = gripper.get_gripper_data()
        print("\nfinal joints:", [f"{v:.1f}" for v in list(data.joint[:JOINT_COUNT])])

    except Exception as e:
        print(f"\nerror: {e}")

    finally:
        # =====================================================
        # Teardown
        # =====================================================
        print("\nclosing...")
        gripper.system_stop()
        time.sleep(0.3)
        gripper.disconnect_to_gripper()
        print("[OK] closed")


if __name__ == "__main__":
    main()
