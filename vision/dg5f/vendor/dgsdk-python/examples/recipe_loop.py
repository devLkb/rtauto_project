#!/usr/bin/env python3
"""
DGSDK interactive recipe + grasp loop example

Connection sequence:
1. set_gripper_system()   - system setting
2. connect_to_gripper()   - connect to gripper
3. set_gripper_option()   - gripper option
4. system_start()         - start system
5. interactive REPL: load pose / grasp recipes from keyboard

Commands:
  p <n>    : load pose recipe n  (waits for targetArrived)
  g <n>    : load grasp recipe n + grasp
  r        : release
  s        : show state (joint, targetArrived)
  h        : help
  q        : quit

NOTE: DGSDK 2.0.0 does NOT support the legacy DG-3F-B model.
NOTE: Recipes must be programmed on the gripper beforehand (UI / SetBootRecipe).
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

def wait_for_arrival(gripper, timeout=3.0):
    """Poll until targetArrived or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = gripper.get_gripper_data()
        if data.targetArrived == 1:
            return True
        time.sleep(0.05)
    return False


def print_help():
    print("\ncommands:")
    print("  p <n>  load pose recipe n")
    print("  g <n>  load grasp recipe n + grasp")
    print("  r      release")
    print("  s      show state")
    print("  h      help")
    print("  q      quit\n")


def handle(gripper, line: str) -> bool:
    """Dispatch one user command. Return False to exit the loop."""
    parts = line.strip().split()
    if not parts:
        return True
    cmd = parts[0].lower()

    if cmd == "q":
        return False

    if cmd == "h":
        print_help()
        return True

    if cmd == "s":
        d = gripper.get_gripper_data()
        joints     = " ".join(f"{v:7.2f}" for v in d.joint[:JOINT_COUNT])
        currents   = " ".join(f"{v:4d}"   for v in d.current[:JOINT_COUNT])
        velocities = " ".join(f"{v:4d}"   for v in d.velocity[:JOINT_COUNT])
        temps      = " ".join(f"{v:5.1f}" for v in d.temperature[:JOINT_COUNT])
        print( "  --- gripper state ---")
        print(f"  joint[deg]    : {joints}")
        print(f"  current[mA]   : {currents}")
        print(f"  velocity[rpm] : {velocities}")
        print(f"  temperature[C]: {temps}")
        print(f"  moving={d.moving}  targetArrived={d.targetArrived}  "
              f"productID={hex(d.productID)}  fw={hex(d.firmwareVersion)}  "
              f"err={d.moduleErrorCode}  ctrlPeriod={d.controlPeriod}")
        return True

    if cmd == "r":
        # Release: grasp(0) opens the fingers
        rc = gripper.grasp(0)
        print(f"  release: {DGResult(rc).name}")
        return True

    if cmd in ("p", "g"):
        if len(parts) < 2:
            print("  usage: p <n>  or  g <n>")
            return True
        try:
            n = int(parts[1])
        except ValueError:
            print(f"  invalid number: {parts[1]}")
            return True

        if cmd == "p":
            # Pose recipe: load + wait until targetArrived
            rc = gripper.load_recipe_pose(n)
            print(f"  load_recipe_pose({n}): {DGResult(rc).name}")
            if rc == DGResult.NONE:
                arrived = wait_for_arrival(gripper)
                print(f"  arrived: {arrived}")
        else:
            # Grasp recipe: load grasp parameters, then trigger grasp(1)
            rc = gripper.load_recipe_grasp(n)
            print(f"  load_recipe_grasp({n}): {DGResult(rc).name}")
            if rc == DGResult.NONE:
                rc2 = gripper.grasp(1)
                print(f"  grasp(1): {DGResult(rc2).name}")
        return True

    print(f"  unknown command: {cmd!r}  (h = help)")
    return True


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
        recv_types = [
            ReceivedDataType.JOINT,
            ReceivedDataType.CURRENT,
            ReceivedDataType.TEMPERATURE,
            ReceivedDataType.VELOCITY,
            ReceivedDataType.MODULE_ERROR_CODE,
            ReceivedDataType.CONTROL_PERIOD,
            0, 0,
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
        # REPL loop
        # =====================================================
        print_help()
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            try:
                if not handle(gripper, line):
                    break
            except KeyboardInterrupt:
                break

    except KeyboardInterrupt:
        print("\ninterrupted")
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
