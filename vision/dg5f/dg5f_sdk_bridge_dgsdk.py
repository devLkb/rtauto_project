# -*- coding: utf-8 -*-
"""DG-5F 실물 SDK 브리지 — 벤더 공식 파이썬 래퍼(dgsdk) 버전.

🛑 **미검증 — 드라이런(`--ip` 생략)까지만 확인됐다. 실물로 재검증되지 않았다
(2026-09-14 작성 시점, 그리퍼가 UR16e 팔에 물려 있어 배선을 풀 수 없는 상태).**
현재 실물 구동에 쓰는 정본은 `dg5f_sdk_bridge.py`(직접 ctypes 바인딩)다 — 그쪽이
2026-08-31 실물 실측으로 검증된 경로이며, 이 파일은 폐기하지 않는다.

왜 이 파일이 존재하나 (기술부채 정리, docs/docs2/TESOLLO_SDK_기술부채_조사.md 부채①):
  기존 dg5f_sdk_bridge.py는 벤더 DLL(DGSDK.dll)을 ctypes로 직접 재바인딩했다 — 벤더가
  같이 제공한 공식 파이썬 패키지(`dg_python` = `dgsdk`, vision/dg5f/vendor/dgsdk-python/)를
  쓰지 않은 상태였다. 이 파일은 그 공식 래퍼로 SDK 호출부만 교체한 버전이다.
  관절 대응·클램프·미러·슬루 리밋 등 우리가 실측으로 확정한 안전 로직은 전부
  dg5f_sdk_bridge.py에서 그대로 가져와 재사용한다(정본 하나 원칙, import로 공유).

실물 재검증 전까지 반드시 확인해야 할 것 (교체 검토 시 나온 리스크, 미해결):
  1. 콜백 등록 없이 connect_to_gripper()를 부르면 dg5f_sdk_bridge.py가 실측한 것과 같은
     "access violation" 크래시가 재현되는지 — 이 파일은 안전하게 콜백을 먼저 등록하지만
     실물로 확인된 적은 없다.
  2. 연결마다 PID 게인을 넣지 않으면 전 관절이 무반응이라는 실측 사실이 이 경로에서도
     동일한지.
  3. DLL 버전 — vendor 패키지 동봉 DGSDK.dll과 이 리포 .env(RTAUTO_DG5F_DLL)가 실제로
     가리키던 DLL은 **MD5 동일 확인됨(2026-09-14, 둘 다 GetLibraryVersion=[2,0,0])**이라
     이 항목의 위험은 낮다 — 그러나 다른 머신에서 다른 DLL을 쓰게 되면 재확인 필요.

사용 (전부 드라이런 전용으로 취급할 것):
  python dg5f_sdk_bridge_dgsdk.py                # 드라이런 — 수신값만 출력, DGSDK 호출 없음
  python dg5f_sdk_bridge_dgsdk.py --ip <IP> --i-know-this-is-unverified
      실물 연결을 시도하려면 --i-know-this-is-unverified를 반드시 함께 줘야 한다 — 위 3가지
      미검증 리스크를 인지했다는 의도적 확인 절차. 그리퍼 배선을 풀 수 있게 된 뒤,
      dg5f_readback_bridge.py의 --jog/--track과 동일한 절차로 재검증한 다음에만 이 게이트를
      정식으로 없앨 것.

CLI 인자·패킷 계약·안전장치는 dg5f_sdk_bridge.py와 동일하게 맞췄다 — 그쪽 문서(모듈 상단
주석, docs/modules/REAL_BRIDGES.md §2)를 함께 참고.
"""
import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(_HERE / "vendor" / "dgsdk-python" / "src"))

from config.rtauto_config import (
    PORT_DG5F_BRIDGE, DG5F_DGSDK_LIB_DIR, DG5F_MAX_DEG_PER_SEC,
    UNITY_IP, PORT_DG5F_SIM, DG5F_IP, resolve_gripper_ip,
)
# 정본 공유 — 관절 대응·클램프·미러·CLI 도구(--jog/--track 요약)는 여기서 가져다 쓴다.
from dg5f_sdk_bridge import (
    N_JOINTS, MIN_PACKET_BYTES, CONTROL_MAGIC, CHANNEL_NAMES, JOINT_CLAMP,
    to_sdk_frame, from_sdk_frame, run_jog, summarize_track,
)

from dgsdk import (
    DGSDK, GripperSystemSetting, GripperSetting, ControlMode, CommunicationMode,
    DGModel, DGResult,
)

DEFAULT_LIB_DIR = DG5F_DGSDK_LIB_DIR or str(_HERE / "vendor" / "dgsdk-python" / "libs")

MODELS = {
    "5f_left": DGModel.DG_5F_LEFT, "5f_right": DGModel.DG_5F_RIGHT,
    "5f_s_left": DGModel.DG_5F_S_LEFT, "5f_s_right": DGModel.DG_5F_S_RIGHT,
    "5f_s15_left": DGModel.DG_5F_S15_LEFT, "5f_s15_right": DGModel.DG_5F_S15_RIGHT,
}
# dg5f_sdk_bridge.py의 DEVELOPER_MODE_RECEIVED_DATA_TYPE_* 와 동일한 값(JOINT/CURRENT/MODULE_ERROR_CODE)
RECEIVED_DATA_TYPE = [1, 2, 7, 0, 0, 0, 0, 0]


class Dg5fSdkOfficial:
    """공식 dgsdk 래퍼를 dg5f_sdk_bridge.Dg5fSdk와 같은 인터페이스로 감싼다.

    run_jog()/메인 루프가 기대하는 메서드(connect/servo/read/read_diag/close)만
    맞추면 되므로, 그쪽 함수들은 수정 없이 그대로 재사용된다.
    """

    def __init__(self, lib_dir):
        self.sdk = DGSDK(lib_dir=lib_dir)
        version = self.sdk.get_library_version()
        print(f"[dgsdk] 공식 래퍼 로드 완료 — DGSDK.dll/so 버전 {version}")

    def _check(self, name, result):
        if result != DGResult.NONE:
            raise RuntimeError(f"{name} 실패 — {DGResult(result).name}")

    def connect(self, ip, port, model_code, control_mode=ControlMode.DEVELOPER,
                set_gains=True, gain_p=2.0, gain_d=5.0, gain_i=0.05, gain_ilimit=0.1):
        sys_set = GripperSystemSetting.create(
            ip=ip, port=port, control_mode=control_mode,
            communication_mode=CommunicationMode.ETHERNET,
            read_timeout=60000, slave_id=1, baudrate=115200, comport="COM1")
        self._check("set_gripper_system", self.sdk.set_gripper_system(sys_set))

        # dg5f_sdk_bridge.py의 2026-08-31 실측 경고와 동일 순서: 콜백은 반드시
        # connect_to_gripper() 이전에 등록한다(등록 안 하면 access violation — 원본 코드 실측,
        # 이 래퍼 경로에서는 아직 재검증되지 않았다).
        self.sdk.on_connected(lambda: None)
        self.sdk.on_disconnected(lambda: None)
        self.sdk.on_gripper_data(lambda data: None)
        self.sdk.on_communication_period(lambda period: None)
        self.sdk.on_fingertip_sensor(lambda data: None)
        self.sdk.on_gpio(lambda data: None)

        self._check("connect_to_gripper", self.sdk.connect_to_gripper())

        opt = GripperSetting.create(
            model=model_code, joint_count=N_JOINTS, finger_count=5,
            moving_inpose=0.4, received_data_type=RECEIVED_DATA_TYPE)
        self._check("set_gripper_option", self.sdk.set_gripper_option(opt))

        if set_gains:
            # dg5f_sdk_bridge.py 실측 경고: 게인을 안 넣으면 전 관절이 무반응이었다.
            self.sdk.set_joint_gain_pid_all_equal(gain_p, gain_d, gain_i, gain_ilimit)
            print(f"[게인] P={gain_p} D={gain_d} I={gain_i} iLimit={gain_ilimit}")
        self._check("system_start", self.sdk.system_start())

    def servo(self, deg20):
        return int(self.sdk.move_servo_joint(list(deg20)))

    def read(self):
        try:
            data = self.sdk.get_gripper_data()
        except RuntimeError:
            return None
        joints = list(data.joint)
        return None if all(v == 0.0 for v in joints) else joints

    def read_diag(self):
        try:
            data = self.sdk.get_gripper_data()
        except RuntimeError:
            return None, None, None
        return list(data.joint), list(data.current), int(data.moduleErrorCode)

    def close(self):
        try:
            self.sdk.system_stop()
        finally:
            self.sdk.disconnect_to_gripper()

    def manual_teach_mode(self, is_on):
        return int(self.sdk.manual_teach_mode(1 if is_on else 0))

    def set_low_pass_filter(self, is_used, alpha):
        return int(self.sdk.set_low_pass_filter(is_used, alpha))


def main():
    ap = argparse.ArgumentParser(
        description="DG-5F 실물 SDK 브리지 (공식 dgsdk 래퍼 — 미검증, 드라이런 전용 취급)")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="그리퍼 IP. 생략하면 드라이런. --ip만 주면 .env의 RTAUTO_DG5F_IP 사용"
                         + (f" (현재 {DG5F_IP})" if DG5F_IP else " (현재 비어 있음)"))
    ap.add_argument("--i-know-this-is-unverified", dest="ack_unverified", action="store_true",
                    help="실물 연결(--ip)에 필수. 이 브리지는 아직 실물로 재검증되지 않았음을 "
                         "인지했다는 명시적 동의 — 파일 상단 docstring의 미검증 리스크 3가지를 "
                         "읽고 넘길 것")
    ap.add_argument("--port", type=int, default=502, help="그리퍼 Modbus TCP 포트 (기본 502)")
    ap.add_argument("--model", default="5f_right", choices=sorted(MODELS),
                    help="실물 모델 (기본 5f_right — 하드웨어 확정: DG-5F-M-R)")
    ap.add_argument("--listen", type=int, default=PORT_DG5F_BRIDGE,
                    help=f"UDP 수신 포트 (기본 {PORT_DG5F_BRIDGE})")
    ap.add_argument("--lib-dir", default=DEFAULT_LIB_DIR,
                    help=f"DGSDK.dll/libDGSDK.so가 있는 디렉터리 (기본 {DEFAULT_LIB_DIR})")
    ap.add_argument("--hz", type=float, default=50.0, help="실물 송신 상한 Hz (기본 50)")
    ap.add_argument("--max-deg-per-sec", type=float, default=DG5F_MAX_DEG_PER_SEC,
                    help=f"관절 각속도 상한[deg/s] (기본 {DG5F_MAX_DEG_PER_SEC:g})")
    ap.add_argument("--max-step", type=float, default=None,
                    help="틱당 관절 최대 변화량[deg] 직접 지정 (기본: 각속도 상한/--hz 자동환산)")
    ap.add_argument("--lpf", type=float, default=0.3, help="SDK 내장 저역필터 alpha (0=사용 안 함)")
    ap.add_argument("--unmirror", action="store_true",
                    help="왼손 스트림을 오른손 실물 규약으로 부호 변환")
    ap.add_argument("--no-set-gains", dest="set_gains", action="store_false",
                    help="PID 게인을 넣지 않는다(실험용, 실물이 안 움직일 수 있음)")
    ap.set_defaults(set_gains=True)
    ap.add_argument("--gain-p", type=float, default=2.0, help="P 게인 (기본 2.0)")
    ap.add_argument("--gain-d", type=float, default=5.0, help="D 게인")
    ap.add_argument("--gain-i", type=float, default=0.05, help="I 게인")
    ap.add_argument("--gain-ilimit", type=float, default=0.1, help="I 적분 한계")
    ap.add_argument("--echo-to-unity", action="store_true",
                    help="실물 실제각을 Unity Dg5fReceiver로 되돌려 보낸다")
    ap.add_argument("--echo-ip", default=UNITY_IP, help="--echo-to-unity 대상 IP")
    ap.add_argument("--echo-port", type=int, default=PORT_DG5F_SIM,
                    help=f"--echo-to-unity 대상 포트 (기본 {PORT_DG5F_SIM})")
    ap.add_argument("--track", default=None, metavar="CSV", help="명령 vs 실제 추종 기록")
    ap.add_argument("--track-channels", default="0,1", help="--track 실시간 표시 채널")
    ap.add_argument("--jog", default=None, metavar="IDX:DEG", help="관절 하나만 단독 구동+전류 확인")
    ap.add_argument("--jog-hold", type=float, default=1.5, help="--jog 목표 도달 후 유지 시간(초)")
    ap.add_argument("--pose", default=None,
                    help="검증용 1회 포즈: 'idx:deg[,idx:deg...]' 나머지 0으로 MoveServoJoint 후 종료")
    args = ap.parse_args()

    try:
        args.ip = resolve_gripper_ip(args.ip)
    except ValueError as e:
        print(f"[오류] {e}")
        return

    if args.ip is not None and not args.ack_unverified:
        print("[오류] 이 브리지는 아직 실물로 재검증되지 않았다 (파일 상단 docstring 참고).")
        print("       실물 연결을 정말 시도하려면 --i-know-this-is-unverified를 함께 주세요.")
        print("       드라이런만 원하면 --ip 없이 실행하세요.")
        return

    if args.max_step is None:
        args.max_step = args.max_deg_per_sec / max(1e-6, args.hz)
    print(f"[슬루] 각속도 상한 {args.max_deg_per_sec:g} deg/s @ {args.hz:g} Hz "
          f"→ 틱당 {args.max_step:.2f}°")

    dry = args.ip is None

    import socket
    import struct

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", args.listen))
    except OSError as e:
        sock.close()
        print(f"[오류] UDP :{args.listen} 바인드 실패 — {e}")
        return
    sock.settimeout(0.2)

    sdk = None
    if not dry:
        sdk = Dg5fSdkOfficial(args.lib_dir)
        print(f"[연결] {args.ip}:{args.port} model={args.model} DEVELOPER 모드 (공식 dgsdk 래퍼)")
        sdk.connect(args.ip, args.port, MODELS[args.model],
                    set_gains=args.set_gains, gain_p=args.gain_p, gain_d=args.gain_d,
                    gain_i=args.gain_i, gain_ilimit=args.gain_ilimit)
        if args.lpf > 0:
            sdk.set_low_pass_filter(1, args.lpf)
        print("[연결] SystemStart 완료")

        if args.jog is not None:
            run_jog(sdk, args)
            sdk.close()
            sock.close()
            return

        if args.pose is not None:
            target = [0.0] * N_JOINTS
            for item in args.pose.split(","):
                i, d = item.split(":")
                target[int(i)] = float(d)
            print(f"[pose] MoveServoJoint {target}")
            sdk.servo(target)
            time.sleep(1.0)
            sdk.close()
            sock.close()
            return

    print(f"[수신] UDP :{args.listen} 대기 — vision_node_dg5f.py [left|right] --bridge 로 송신"
          + (" (드라이런: 실물 송신 없음)" if dry else ""))

    period = 1.0 / args.hz
    last_sent_t = 0.0
    last_cmd = None
    if not dry:
        for _ in range(50):
            last_cmd = sdk.read()
            if last_cmd is not None:
                break
            time.sleep(period)
        if last_cmd is None:
            print("[슬루] ⚠️ 실물 현재 자세를 읽지 못했습니다 — 첫 명령이 속도 제한 없이 나갑니다.")
        else:
            print(f"[슬루] 실물 현재 자세를 기준점으로 잡았습니다 "
                  f"(엄지 {last_cmd[0]:.1f}/{last_cmd[1]:.1f}°).")
    last_print = 0.0
    stale_warned = False
    teach_on = False

    if args.echo_to_unity and args.echo_port == args.listen:
        print(f"[오류] --echo-port({args.echo_port})가 수신 포트와 같습니다.")
        return

    track_f = None
    track_ch = []
    track_t0 = None
    if args.track:
        track_path = Path(args.track)
        track_path.parent.mkdir(parents=True, exist_ok=True)
        track_f = open(track_path, "w", encoding="utf-8")
        track_f.write("t_sec," + ",".join(f"cmd_{n}" for n in CHANNEL_NAMES)
                      + "," + ",".join(f"act_{n}" for n in CHANNEL_NAMES) + "\n")
        try:
            track_ch = [int(x) for x in args.track_channels.split(",") if x.strip() != ""]
        except ValueError:
            track_ch = [0, 1]
        print(f"[track] 기록 시작: {track_path}")

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                stale_warned = False
            except socket.timeout:
                if not stale_warned and last_cmd is not None:
                    print("[hold] 패킷 끊김 — 마지막 자세 유지")
                    stale_warned = True
                continue

            if data.startswith(CONTROL_MAGIC):
                if dry or len(data) < len(CONTROL_MAGIC) + 1:
                    continue
                want_teach = data[len(CONTROL_MAGIC)] == 1
                if want_teach != teach_on:
                    r = sdk.manual_teach_mode(want_teach)
                    if r == 0:
                        teach_on = want_teach
                        print(f"[모드] {'real→sim (교시 ON)' if want_teach else 'sim→real (교시 OFF)'}")
                        if not want_teach:
                            cur = sdk.read()
                            if cur is not None:
                                last_cmd = list(cur)
                    else:
                        print(f"[모드] manual_teach_mode 실패 DG_RESULT={r}")
                continue

            if len(data) < MIN_PACKET_BYTES:
                continue
            if teach_on:
                continue
            ours = struct.unpack_from(f"<{N_JOINTS}f", data)
            target = to_sdk_frame(ours, args.unmirror)

            now = time.time()
            if now - last_sent_t < period:
                continue
            if last_cmd is not None and args.max_step > 0:
                step = args.max_step
                target = [p + min(step, max(-step, t - p))
                          for p, t in zip(last_cmd, target)]
            last_cmd = target
            last_sent_t = now

            if dry:
                if now - last_print >= 0.5:
                    print("[dry]", " ".join(f"{v:6.1f}" for v in target))
                    last_print = now
            else:
                res = sdk.servo(target)
                if res != 0 and now - last_print >= 0.5:
                    print(f"[경고] MoveServoJoint DG_RESULT={res}")
                    last_print = now

            actual = None
            if (track_f is not None or args.echo_to_unity) and not dry:
                actual = sdk.read()

            if args.echo_to_unity and actual is not None:
                echo = from_sdk_frame(actual)
                sock.sendto(struct.pack(f"<{N_JOINTS}f", *echo), (args.echo_ip, args.echo_port))

            if track_f is not None:
                if track_t0 is None:
                    track_t0 = now
                rel = now - track_t0
                act_cols = (",".join(f"{v:.2f}" for v in actual) if actual
                            else ",".join([""] * N_JOINTS))
                track_f.write(f"{rel:.3f}," + ",".join(f"{v:.2f}" for v in target)
                              + "," + act_cols + "\n")
                if now - last_print >= 0.25:
                    parts = []
                    for i in track_ch:
                        if 0 <= i < N_JOINTS:
                            a = f"{actual[i]:6.1f}" if actual else "   ---"
                            parts.append(f"[{i}]{CHANNEL_NAMES[i]:<10} 명령{target[i]:6.1f} 실제{a}")
                    print(f"[track {rel:5.2f}s] " + "  |  ".join(parts))
                    last_print = now
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        if track_f is not None:
            track_f.close()
            summarize_track(args.track)
        if sdk is not None and teach_on:
            sdk.manual_teach_mode(0)
            print("[모드] 교시 모드 해제")
        if sdk is not None:
            sdk.close()
            print("[종료] SystemStop + Disconnect 완료")


if __name__ == "__main__":
    main()
