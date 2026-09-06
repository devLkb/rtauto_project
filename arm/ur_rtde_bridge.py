# -*- coding: utf-8 -*-
"""URSim/실물 UR16e RTDE 브리지 — Unity(UrArmSender.cs)가 UDP로 보내는 6축 관절각 목표를
ur_rtde로 URSim(또는 실물)에 servoJ 명령하고, 실제 관절각을 읽어 Unity(UrArmReceiver.cs)로
되돌려 보낸다(디지털 트윈 왕복). vision/dg5f/dg5f_sdk_bridge.py와 같은 구조를 팔에 적용한 것.

구조:
  Unity UrArmSender.cs → UDP(config.PORT_UR_ARM_BRIDGE, 기본 5009) → 이 브리지
     → ur_rtde RTDEControlInterface.servoJ() → URSim/실물 UR16e
  이 브리지 --echo-to-unity → UDP(config.PORT_UR_ARM_SIM, 기본 5010) → Unity UrArmReceiver (트윈)

패킷 계약: float32 little-endian x 6, 관절각[deg], 순서 = UR q 순서
  [shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]
  (Dg5fPicknPlaceSpec.ArmLinks와 같은 순서 — shoulder_link/upper_arm_link/forearm_link/
   wrist_1_link/wrist_2_link/wrist_3_link)

RTDE는 라디안 단위다. deg<->rad 변환은 이 스크립트가 경계에서 전담하고, 그 외 코드/패킷은
전부 deg(우리 규약)만 다룬다.

사용:
  python arm/ur_rtde_bridge.py                  # 드라이런 — RTDE 연결 안 함, 수신값만 출력(패킷 경로 검증)
  python arm/ur_rtde_bridge.py --ip             # 연결 — IP는 .env의 RTAUTO_UR_IP (기본 127.0.0.1=URSim 로컬)
  python arm/ur_rtde_bridge.py --ip <IP> --echo-to-unity

실행 순서는 상관없다 — 브리지와 펜던트(Remote Control 전환·전원 투입) 중 무엇을 먼저 해도
된다. 펜던트에서 Local↔Remote를 전환하면 ur_rtde가 로봇에 올려둔 컨트롤 스크립트가 죽는데,
그때 **Unity→로봇 방향만 조용히 멈추고** 읽기(--echo-to-unity)는 계속 살아 있어서
"URSim→Unity는 되는데 반대만 안 된다"로 보인다(2026-09-04 실제 증상). 이 브리지는 그 상태를
감지해 CONTROL_RETRY_SEC마다 스스로 다시 붙으므로 재시작할 필요가 없다 — control_ready() 참고.

URSim 실행 방법·RTDE 활성화(Remote Control 모드) 여부는 docs/SIM2REAL_ROADMAP.md
§4 "UR16e 소프트웨어 버전"·§9 "URSim 선행 개발 경로" 참고.
종료: Ctrl+C (RTDE 연결 정리 자동)
"""
import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.rtauto_config import (
    PORT_UR_ARM_BRIDGE, PORT_UR_ARM_SIM, UNITY_IP, UR_MAX_DEG_PER_SEC, resolve_ur_ip,
)

N_JOINTS = 6
MIN_PACKET_BYTES = 4 * N_JOINTS
JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3"]


def deg_to_rad(deg6):
    return [math.radians(d) for d in deg6]


def rad_to_deg(rad6):
    return [math.degrees(r) for r in rad6]


# 제어 링크가 끊겼을 때 재접속을 다시 시도하기까지의 간격[s]. 매 틱 시도하면 실패
# 예외 생성 비용이 루프를 잡아먹고, 너무 길면 펜던트에서 Remote Control로 바꾼 뒤
# 손이 멈칫하는 시간이 길어진다.
CONTROL_RETRY_SEC = 2.0


def connect_control(rtde_control_mod, ip, announce=True):
    """RTDE **Control** 접속 시도 — 실패해도 예외를 밖으로 내보내지 않고 None을 돌려준다.

    로봇이 Remote Control 모드가 아니거나 전원/브레이크가 아직이면 ur_rtde가 컨트롤
    스크립트를 못 올려 여기서 실패한다. 그때 프로세스를 죽이면 "펜던트를 먼저 맞춰놓고
    브리지를 나중에 띄운다"는 **실행 순서 의존**이 생긴다(2026-09-04에 실제로 이 순서를
    어겨서 Unity→로봇 방향만 조용히 죽었다). 그래서 실패를 정상 상태의 하나로 취급하고
    루프에서 계속 재시도한다 — 읽기(RTDE Receive)는 모드와 무관하게 살아 있으므로
    그동안에도 Unity 트윈(echo)은 정상 동작한다.

    `announce=False`는 주기적 재시도용이다 — 2초마다 같은 예외 메시지를 찍으면 콘솔이
    도배돼 정작 중요한 로그가 묻힌다. 사람이 볼 안내는 control_ready()가 한 번만 찍는다.
    """
    try:
        return rtde_control_mod.RTDEControlInterface(ip)
    except Exception as e:
        if announce:
            print(f"[제어] 접속 실패 — {e}")
        return None


def control_alive(rtde_c):
    """제어 링크가 명령을 받을 수 있는 상태인가.

    `isProgramRunning()`이 핵심 판정이다 — 컨트롤 스크립트가 죽으면 소켓은 붙어 있어도
    (`isConnected()`는 True) 명령만 조용히 안 먹기 때문이다. 다만 이 메서드가 없는
    ur_rtde 버전을 만나면 **없다는 이유로 "죽음"으로 오판해 2초마다 재접속을 반복하며
    멀쩡한 연결을 망가뜨린다.** 그래서 있으면 쓰고 없으면 isConnected()까지만 본다
    (requirements-vision.txt는 1.6.5 고정이라 정상 경로에서는 둘 다 있다).
    """
    if rtde_c is None or not rtde_c.isConnected():
        return False
    probe = getattr(rtde_c, "isProgramRunning", None)
    return True if probe is None else bool(probe())


def main():
    ap = argparse.ArgumentParser(description="UR16e RTDE 브리지 (URSim/실물)")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="UR 컨트롤박스/URSim IP. 아예 생략하면 드라이런(수신값 출력만), 값 없이 "
                         "--ip만 주면 .env의 RTAUTO_UR_IP를 쓴다 (기본 127.0.0.1=URSim 로컬)")
    ap.add_argument("--listen", type=int, default=PORT_UR_ARM_BRIDGE,
                    help=f"UDP 수신 포트 (Unity UrArmSender와 동일해야 함, 기본 {PORT_UR_ARM_BRIDGE})")
    ap.add_argument("--hz", type=float, default=10.0,
                    help="servoJ 송신 상한 Hz (기본 10 — docs/SIM2REAL_ROADMAP.md §5-5 계획값)")
    ap.add_argument("--max-deg-per-sec", type=float, default=UR_MAX_DEG_PER_SEC,
                    help=f"관절 각속도 상한[deg/s] — 정본은 .env의 RTAUTO_UR_MAX_DEG_PER_SEC "
                         f"(현재 {UR_MAX_DEG_PER_SEC:g}, 미검증 보수값)")
    ap.add_argument("--max-step", type=float, default=None,
                    help="틱당 관절 최대 변화량[deg] 직접 지정 — 주면 --max-deg-per-sec를 무시")
    ap.add_argument("--lookahead-time", type=float, default=0.1,
                    help="servoJ lookahead_time[s] (기본 0.1, ur_rtde 권장 범위 0.03~0.2)")
    ap.add_argument("--gain", type=float, default=300.0,
                    help="servoJ 서보 게인 (기본 300, ur_rtde 권장 범위 100~2000)")
    ap.add_argument("--echo-to-unity", action="store_true",
                    help="실제 관절각(getActualQ)을 읽어 Unity UrArmReceiver(포트 PORT_UR_ARM_SIM)로 "
                         "되돌려 보낸다 — 'Unity 명령 → URSim → 다시 Unity' 왕복 트윈 확인용")
    ap.add_argument("--echo-ip", default=UNITY_IP, help="--echo-to-unity 대상 IP")
    ap.add_argument("--echo-port", type=int, default=PORT_UR_ARM_SIM,
                    help=f"--echo-to-unity 대상 포트 (기본 {PORT_UR_ARM_SIM})")
    args = ap.parse_args()

    args.ip = resolve_ur_ip(args.ip)
    dry = args.ip is None

    if args.max_step is None:
        args.max_step = args.max_deg_per_sec / max(1e-6, args.hz)
    print(f"[슬루] 각속도 상한 {args.max_deg_per_sec:g} deg/s @ {args.hz:g} Hz "
          f"→ 틱당 {args.max_step:.2f}°")

    # UDP 수신 소켓을 RTDE 연결보다 먼저 잡는다 — dg5f_sdk_bridge.py와 같은 이유
    # (실패는 로봇을 건드리기 전에 나야 한다).
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", args.listen))
    except OSError as e:
        sock.close()
        print(f"[오류] UDP :{args.listen} 바인드 실패 — {e}")
        print("       같은 포트를 듣는 브리지가 이미 떠 있을 가능성이 높다.")
        return
    # 타임아웃을 --hz 절반 이하로 잡는다 — 이 값이 곧 idle 상태(Unity 명령 없음, 펜던트
    # 조그만 있는 상태)에서 echo_if_due()가 실제로 체크되는 주기라, --hz보다 크면
    # echo가 목표 Hz를 못 따라간다.
    sock.settimeout(min(0.2, 1.0 / args.hz / 2))

    rtde_c = rtde_r = rtde_control_mod = None
    if not dry:
        try:
            import rtde_control
            import rtde_receive
        except ImportError:
            print("[오류] ur_rtde 패키지가 없습니다 — `pip install ur_rtde` 후 다시 실행하세요.")
            sock.close()
            return
        rtde_control_mod = rtde_control
        print(f"[연결] {args.ip} RTDE 접속 시도 "
              "(URSim이면 도커 컨테이너가 떠 있어야 함 — docs/SIM2REAL_ROADMAP.md §4 참고)")
        # 읽기와 제어를 분리해서 붙인다. 읽기는 Remote Control 여부와 무관하게 붙지만
        # 제어는 모드·전원 상태를 탄다 — 제어 실패로 프로세스를 죽이지 않는 이유는
        # connect_control() 독스트링 참고(순서 의존 제거).
        rtde_r = rtde_receive.RTDEReceiveInterface(args.ip)
        rtde_c = connect_control(rtde_control_mod, args.ip)
        print("[연결] RTDE 읽기 접속 완료 / 제어 "
              + ("접속 완료" if rtde_c is not None
                 else f"대기 — {CONTROL_RETRY_SEC:g}초마다 자동 재시도합니다. "
                      "펜던트를 Remote Control로 바꾸면 브리지 재시작 없이 붙습니다."))

    print(f"[수신] UDP :{args.listen} 대기 — Unity UrArmSender 송신 필요"
          + (" (드라이런: RTDE 송신 없음)" if dry else ""))
    if args.echo_to_unity and not dry:
        print(f"[echo] 실제 관절각을 {args.hz:g} Hz로 Unity({args.echo_ip}:{args.echo_port})에 "
              "계속 보냅니다 — Unity가 명령을 안 보내도(펜던트로 직접 조그해도) 동작합니다.")

    period = 1.0 / args.hz
    last_sent_t = 0.0
    last_echo_t = 0.0
    # 슬루 리밋 기준점 — 반드시 로봇의 현재 자세로 시작한다(dg5f_sdk_bridge.py와 동일한 이유:
    # 아니면 연결 즉시 첫 목표로 서보 최고속 점프한다).
    last_cmd = None
    if not dry:
        q = rtde_r.getActualQ()
        last_cmd = rad_to_deg(q)
        print(f"[슬루] 현재 자세를 기준점으로 잡았습니다: "
              + ", ".join(f"{n}={d:.1f}°" for n, d in zip(JOINT_NAMES, last_cmd)))
    last_print = 0.0
    stale_warned = False
    # 제어 링크 상태 래치 — 끊김/복구를 각각 한 번만 알린다(매 틱 찍으면 콘솔 도배).
    control_down_warned = False
    last_control_try = 0.0
    # servoJ가 False를 돌려줬을 때 세운다. isConnected()/isProgramRunning()이 아직 True라고
    # 우겨도 재접속을 밀어붙이기 위한 것 — 그게 없으면 "붙어는 있는데 명령만 안 먹는" 상태에
    # 갇힌다.
    force_control_reconnect = False
    # "패킷 끊김"은 **소켓 타임아웃 1회**가 아니라 **마지막 수신 이후 경과 시간**으로 판정한다.
    # 타임아웃으로 판정하면, 송신 주기(Unity 10 Hz = 0.1 s)보다 소켓 타임아웃이 짧은 순간
    # 정상 송신 중에도 패킷 사이 간격마다 타임아웃이 나서 경고가 끝없이 찍힌다
    # (2026-09-04 실제 증상: "[hold] 패킷 끊김"이 계속 출력됨). 한 번도 받은 적이 없으면
    # 아예 경고하지 않는다 — URSim→Unity 단방향으로 쓸 때는 Unity가 원래 안 보내므로
    # "끊김"이 아니라 정상 상태다.
    STALE_AFTER_SEC = 1.0
    last_rx_t = None

    def echo_if_due(now):
        # echo는 Unity로부터의 수신 여부와 무관하게 독립된 타이머로 돈다 — 그래야 펜던트로
        # 직접 조그하거나(Unity가 명령을 안 보내는 상태) URScript 프로그램이 움직여도
        # Unity 트윈이 따라온다. Unity 명령 처리 루프(위 period)와 같은 Hz를 공유한다.
        nonlocal last_echo_t
        if not (args.echo_to_unity and not dry):
            return
        if now - last_echo_t < period:
            return
        last_echo_t = now
        actual = rad_to_deg(rtde_r.getActualQ())
        sock.sendto(struct.pack(f"<{N_JOINTS}f", *actual), (args.echo_ip, args.echo_port))

    def control_ready(now):
        """제어 링크가 살아 있으면 True. 죽어 있으면 조용히 재접속을 시도한다.

        **이 함수가 브리지의 실행 순서 의존을 없앤다.** ur_rtde의 제어 경로는 로봇에
        올려둔 컨트롤 스크립트 위에서 도는데, 펜던트에서 Local↔Remote를 전환하면 그
        스크립트가 죽는다. 사람이 브리지를 띄운 뒤에 모드를 바꾸는 건 자연스러운 순서라
        (실제로 2026-09-04에 그렇게 해서 막혔다), 그걸 "사용자가 지켜야 할 순서"로
        떠넘기지 않고 여기서 복구한다. 읽기(echo)는 이 함수와 무관하게 계속 돈다.
        """
        nonlocal rtde_c, last_control_try, control_down_warned, last_cmd
        nonlocal force_control_reconnect
        try:
            if not force_control_reconnect and control_alive(rtde_c):
                if control_down_warned:
                    print("[제어] 복구됨 — Unity→로봇 명령을 다시 받습니다")
                    control_down_warned = False
                return True
        except Exception:
            pass    # 죽은 링크에 상태를 묻다 난 예외는 "죽었다"와 같은 뜻이다

        if not control_down_warned:
            print(f"[제어] 로봇이 명령을 받지 않는 상태입니다 — 펜던트가 Remote Control인지, "
                  f"전원이 켜지고 브레이크가 풀렸는지 확인하세요. "
                  f"{CONTROL_RETRY_SEC:g}초마다 자동 재접속합니다(브리지 재시작 불필요).")
            control_down_warned = True

        if now - last_control_try < CONTROL_RETRY_SEC:
            return False
        last_control_try = now
        if rtde_c is not None:
            try:
                rtde_c.disconnect()
            except Exception:
                pass
        rtde_c = connect_control(rtde_control_mod, args.ip, announce=False)
        force_control_reconnect = False
        if rtde_c is None:
            return False
        # 재접속 성공 — 슬루 기준점을 로봇의 **현재** 자세로 다시 잡는다. 끊겨 있는 동안
        # 펜던트로 움직였을 수 있어서, 낡은 last_cmd로 이어가면 재개 순간 그 차이만큼
        # 튄다(연결 직후 기준점을 잡는 위 초기화와 같은 이유).
        last_cmd = rad_to_deg(rtde_r.getActualQ())
        return True

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                last_rx_t = time.time()
                if stale_warned:
                    print("[recv] Unity 패킷 재개")
                    stale_warned = False
            except socket.timeout:
                now = time.time()
                echo_if_due(now)
                if (not stale_warned and last_rx_t is not None
                        and now - last_rx_t > STALE_AFTER_SEC):
                    print(f"[hold] Unity 패킷이 {STALE_AFTER_SEC:g}초 이상 끊김 — 마지막 자세 유지")
                    stale_warned = True
                continue
            except ConnectionResetError:
                # Windows 전용 함정(WinError 10054) — 이 소켓으로 echo(sendto)를 보냈는데
                # 상대(Unity)가 그 포트를 안 듣고 있으면 ICMP "포트 도달불가"가 돌아오고,
                # 같은 소켓의 **다음 recvfrom()**이 이 예외를 던진다. UDP는 원래
                # 비연결형이라 이런 게 없어야 정상인데 Windows 소켓 스택의 특이 동작이다
                # (표준 파이썬 socket.ioctl로는 끌 수 없는 SIO_UDP_CONNRESET 관련 — ctypes로
                # WSAIoctl을 직접 불러야 하나, 그러기보다 여기서 무시하고 계속하는 쪽이
                # 훨씬 간단하고 안전하다). Linux에는 없는 문제라 실제로 겪기 전까지 안 보인다.
                continue

            if len(data) < MIN_PACKET_BYTES:
                echo_if_due(time.time())
                continue
            target = list(struct.unpack_from(f"<{N_JOINTS}f", data))

            now = time.time()
            if now - last_sent_t < period:
                echo_if_due(now)
                continue
            if not dry and not control_ready(now):
                # 제어 링크가 죽어 있으면 명령 경로 전체를 건너뛴다. 슬루 기준점(last_cmd)도
                # 진행시키지 않는다 — 못 보낸 명령만큼 기준점만 앞서가면 복구 순간 그 차이가
                # 한꺼번에 나간다. 복구 시점의 기준점은 control_ready()가 실제 자세로 다시 잡는다.
                last_sent_t = now
                echo_if_due(now)
                continue
            if last_cmd is not None and args.max_step > 0:
                step = args.max_step
                target = [p + min(step, max(-step, t - p))
                          for p, t in zip(last_cmd, target)]
            last_cmd = target
            last_sent_t = now

            if dry:
                if now - last_print >= 0.5:
                    print("[dry]", " ".join(f"{v:7.1f}" for v in target))
                    last_print = now
            else:
                # ⚠️ servoJ는 성공/실패를 bool로 돌려준다. 반환값을 버리면 로봇이 명령을
                # 거부해도 화면에 아무것도 안 뜨고 **"에러 없이 조용히 안 움직인다"**가 된다
                # (2026-09-04에 실제로 이 증상으로 원인 추적이 길어졌다). 거부는 링크가
                # 방금 죽었다는 뜻이므로 재접속을 강제하고, 안내는 control_ready()가 맡는다.
                # 링크가 명령 도중에 끊기면 False가 아니라 예외로 튀기도 한다 — 그걸
                # 흘려보내면 브리지가 통째로 죽어서 자가복구의 의미가 없어진다.
                try:
                    accepted = rtde_c.servoJ(deg_to_rad(target), 0.0, 0.0, period,
                                             args.lookahead_time, args.gain)
                except Exception as e:
                    print(f"[제어] servoJ 예외 — 재접속합니다 ({e})")
                    accepted = False
                if not accepted:
                    force_control_reconnect = True

            echo_if_due(now)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        sock.close()
        if rtde_c is not None:
            # 링크가 이미 죽은 채로 종료할 수 있다(모드 전환/전원 차단 등) — 그때 정리
            # 호출이 예외를 던지면 "[종료] 정리 완료"까지 못 가고 트레이스백만 남는다.
            try:
                rtde_c.servoStop()
                rtde_c.stopScript()
            except Exception as e:
                print(f"[종료] 제어 링크 정리 생략 — 이미 끊긴 상태 ({e})")
        print("[종료] 정리 완료")


if __name__ == "__main__":
    main()
