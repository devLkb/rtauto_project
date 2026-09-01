# -*- coding: utf-8 -*-
"""실물 DG-5F 상태 판독(사용자모드/Modbus TCP 경로) — DGManager가 이미 붙어 있어도 되는지
검증하는 두 번째 리더.

배경: dg5f_readback_bridge.py는 DGSDK 개발자모드로 붙는데, 그리퍼는 물리 스위치로
사용자모드/개발자모드 중 하나만 서비스한다(하드웨어 설명서 §4.2, "개발자 모드는 EtherNET
통신만 가능"). DGManager를 사용자모드(Modbus TCP)로 조종 중이면 개발자모드 프로토콜 자체가
응답하지 않아 dg5f_readback_bridge.py는 애초에 연결이 안 된다 — 지금까지 실패한 원인이 이거다.

이 스크립트는 DGSDK를 아예 쓰지 않고 표준 Modbus TCP(FC04 Read Input Register)로 직접
소켓을 열어 관절 현재값을 읽는다. Modbus TCP는 여러 마스터가 동시에 붙는 걸 전제로 한
프로토콜이라, DGManager(마스터 #1)가 붙어 있는 상태에서 이 스크립트(마스터 #2)가
동시에 연결되는지를 검증하려 만들었다.

⚠️ **결론: 동시 접속 불가 — 2026-08-31 실물 실측.** DGManager를 사용자모드로 연결해둔
채로 이 스크립트를 실행하면 `ModbusTcpClient.__init__`의 `sock.connect()` 단계에서
타임아웃이 난다(연결 거부가 아니라 타임아웃 — SYN에 응답이 없다는 뜻). 즉 프로토콜이
표준 Modbus TCP로 같아도 안 된다. dg5f_sdk_bridge.py/dg5f_readback_bridge.py(개발자모드)
쪽 실패와 합쳐서 보면, 이 그리퍼는 **프로토콜·제어모드와 무관하게 TCP 세션을 그리퍼
전체에서 1개만 받는다**는 것이 이제 두 가지 서로 다른 프로토콜 경로(개발자모드 자체
프로토콜 + 사용자모드 Modbus TCP) 모두에서 확인된 사실이다. DGManager와 별도 프로세스로
실물을 동시에 읽는 방법은 없다 — dg5f_sdk_bridge.py --echo-to-unity로 갈아타거나
(우리 쪽이 유일한 실물 클라이언트가 되어 조종+읽기+Unity 반사를 전부 겸함),
DGManager로 잡은 자세를 dg5f_readback_bridge.py --capture-pose로 스냅샷만 캡처하는
방법 중 하나를 택해야 한다.

레지스터 맵 근거([테솔로] Delto Gripper_Control_Manual_KR_v2_0_0.pdf §2.2.2 Input Register):
  Address 0: Product ID, 1: 펌웨어버전, 2: 관절 움직임 여부, 3: 타겟 도착여부,
             4: Blend 번호, 5: Blend 상태,
  Address 6..25: 모터 1..20 현재 위치값 (단위 0.1°, ×10 스케일, signed 16bit)
  → FC04로 시작주소 6, 개수 20을 한 번에 읽으면 우리 N_JOINTS(20)와 정확히 대응한다.
  Slave ID 기본 1 (DGSDK 쪽 connect()의 slaveID=1과 동일 — dg5f_sdk_bridge.py 참고).

Modbus 채널 순서(Motor N)는 dg5f_sdk_bridge.py가 하드웨어 설명서 §3.3.1로 이미 확정한
"Motor N ↔ 우리 채널 인덱스 N-1"과 같다. 그래서 부호/영점 변환도 그 파일의 from_sdk_frame을
그대로 재사용한다(정본 하나 원칙 — 표를 두 번 베끼지 않는다).

사용:
  python dg5f_modbus_readback.py --fake
      # 하드웨어 없이 가짜 스윕 패턴 송신 — UDP 수신 경로만 검증
  python dg5f_modbus_readback.py --ip
      # 실물 연결(사용자모드). IP는 .env의 RTAUTO_DG5F_IP에서 읽는다.
      # DGManager를 이미 켜둔 채로 시도해 동시접속 여부를 확인한다.
  종료: Ctrl+C
"""
import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_IP, PORT_DG5F_SIM, DG5F_IP, resolve_gripper_ip

from dg5f_sdk_bridge import N_JOINTS, CHANNEL_NAMES, from_sdk_frame

INPUT_REG_JOINT_START = 6   # Control Manual §2.2.2 — 모터1 현재위치값 주소
MODBUS_TCP_PORT_DEFAULT = 502


class ModbusTcpError(Exception):
    pass


class ModbusTcpClient:
    """FC04(Read Input Register)만 지원하는 최소 Modbus TCP 클라이언트.

    pymodbus 등 외부 의존성을 새로 추가하지 않으려고(원칙 2 — 새 머신 부트스트랩에
    패키지를 늘리지 않는다) MBAP 헤더 + PDU를 표준 라이브러리 socket/struct로 직접 짠다.
    """

    def __init__(self, ip, port, slave_id, timeout=1.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((ip, port))
        self.slave_id = slave_id
        self._txn = 0

    def read_input_registers(self, start_addr, count):
        self._txn = (self._txn + 1) & 0xFFFF
        pdu = struct.pack(">BHH", 0x04, start_addr, count)   # FC04 + 시작주소 + 개수
        mbap = struct.pack(">HHHB", self._txn, 0, len(pdu) + 1, self.slave_id)
        self.sock.sendall(mbap + pdu)

        header = self._recv_exact(7)
        txn, proto, length, unit = struct.unpack(">HHHB", header)
        if txn != self._txn:
            raise ModbusTcpError(f"트랜잭션ID 불일치 (보낸 {self._txn}, 받은 {txn})")
        body = self._recv_exact(length - 1)
        func = body[0]
        if func & 0x80:                          # 최상위 비트 = 예외 응답
            exc_code = body[1] if len(body) > 1 else -1
            raise ModbusTcpError(f"Modbus 예외 응답 func=0x{func:02X} code={exc_code}")
        if func != 0x04:
            raise ModbusTcpError(f"예상치 못한 함수코드 0x{func:02X}")
        byte_count = body[1]
        regs_raw = body[2:2 + byte_count]
        n = byte_count // 2
        return list(struct.unpack(f">{n}h", regs_raw))   # signed 16bit big-endian

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ModbusTcpError("연결이 끊겼습니다(recv 0바이트)")
            buf += chunk
        return buf

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def run_fake(args):
    """실물 없이 20채널을 스윕 — UDP 수신 경로만 검증 (dg5f_readback_bridge.py --fake와 동일 취지)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.hz
    t0 = time.time()
    print(f"[가짜 모드] {args.send_ip}:{args.send_port}로 스윕 패턴 송신 (Ctrl+C 종료)")
    try:
        while True:
            t = time.time() - t0
            sweep = 40.0 * (0.5 - 0.5 * math.cos(t))
            vals = [sweep if i not in (0,) else 0.0 for i in range(N_JOINTS)]
            sock.sendto(struct.pack(f"<{N_JOINTS}f", *vals), (args.send_ip, args.send_port))
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")


def run_real(args):
    print(f"[연결 시도] Modbus TCP {args.ip}:{args.port} slave={args.slave_id} "
          "— DGManager가 사용자모드로 이미 붙어 있어도 되는지 이 시도로 확인한다")
    try:
        client = ModbusTcpClient(args.ip, args.port, args.slave_id, timeout=args.timeout)
    except (OSError, socket.timeout) as e:
        print(f"[연결 실패] {e}")
        print("[안내] 이 실패가 '거부(Connection refused)'인지 '타임아웃'인지가 원인 분석의 "
              "핵심 단서다 — refused는 그 포트에 아무도 안 듣고 있다는 뜻(모드 스위치 확인), "
              "타임아웃은 접속은 받아주는데 응답이 없다는 뜻(동시접속 자체가 막혔을 가능성).")
        return
    print("[연결] TCP 소켓 성공 — FC04 폴링 시작")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.hz
    last_print = 0.0
    n_ok = 0
    n_fail = 0
    try:
        while True:
            try:
                raw = client.read_input_registers(INPUT_REG_JOINT_START, N_JOINTS)
                n_ok += 1
            except (ModbusTcpError, OSError, socket.timeout) as e:
                n_fail += 1
                now = time.time()
                if now - last_print >= 1.0:
                    print(f"[경고] 읽기 실패({n_fail}회째): {e}")
                    last_print = now
                time.sleep(period)
                continue

            sdk_deg = [v / 10.0 for v in raw]        # 레지스터 스케일 ×10 → deg
            joints = from_sdk_frame(sdk_deg)          # 실물 SDK 규약 → 우리(URDF/Unity) 규약
            sock.sendto(struct.pack(f"<{N_JOINTS}f", *joints), (args.send_ip, args.send_port))

            now = time.time()
            if now - last_print >= 0.5:
                print(f"[readback ok={n_ok} fail={n_fail}]",
                      " ".join(f"{v:5.1f}" for v in joints[:4]), "...")
                last_print = now
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        client.close()
        print(f"[종료] 소켓 닫음 (성공 {n_ok} / 실패 {n_fail})")


def main():
    ap = argparse.ArgumentParser(
        description="DG-5F 실물 상태 판독(Modbus TCP, 사용자모드 경로) → Unity 트윈 반사")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="그리퍼 IP. 아예 생략하면 --fake만 가능, 값 없이 --ip만 주면 "
                         ".env의 RTAUTO_DG5F_IP를 쓴다"
                         + (f" (현재 {DG5F_IP})" if DG5F_IP else " (현재 비어 있음)"))
    ap.add_argument("--port", type=int, default=MODBUS_TCP_PORT_DEFAULT,
                     help=f"Modbus TCP 포트 (기본 {MODBUS_TCP_PORT_DEFAULT})")
    ap.add_argument("--slave-id", type=int, default=1, help="Modbus Slave ID (기본 1)")
    ap.add_argument("--timeout", type=float, default=1.0, help="소켓 연결/읽기 타임아웃(초)")
    ap.add_argument("--send-ip", default=UNITY_IP, help="Unity가 도는 PC IP (기본 config UNITY_IP)")
    ap.add_argument("--send-port", type=int, default=PORT_DG5F_SIM,
                     help=f"Unity Dg5fReceiver 포트 (기본 {PORT_DG5F_SIM})")
    ap.add_argument("--hz", type=float, default=20.0,
                     help="폴링/송신 Hz (기본 20 — Modbus TCP는 요청-응답 왕복이 있어 "
                          "DGSDK 개발자모드보다 느리게 잡음)")
    ap.add_argument("--fake", action="store_true",
                     help="하드웨어 없이 가짜 스윕 패턴 송신 — UDP 경로/Unity 수신만 검증")
    args = ap.parse_args()

    try:
        args.ip = resolve_gripper_ip(args.ip)
    except ValueError as e:
        print(f"[오류] {e}")
        return

    if args.fake:
        run_fake(args)
        return
    if args.ip is None:
        print("[오류] --ip 없이는 --fake만 가능합니다 (예: python dg5f_modbus_readback.py --fake)")
        return
    run_real(args)


if __name__ == "__main__":
    main()
