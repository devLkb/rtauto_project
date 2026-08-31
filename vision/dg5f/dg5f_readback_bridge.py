# -*- coding: utf-8 -*-
"""실물 DG-5F 상태 판독 브리지 — 실물 그리퍼가 **누구에 의해 움직이든**(테솔로 공식
DGManager, DGSDKSample, 수기 조그 등) 그 실제 관절각을 읽어 Unity 트윈에 반사한다.

dg5f_sdk_bridge.py(명령 방향: Unity/webcam → 실물)와 반대 방향이다:
  이 스크립트 → SDK 연결 → GetReceivedGripperData() 폴링 → UDP:PORT_DG5F_SIM(기본 5006)
  → Unity Dg5fReceiver/Dg5fHandDriver (수신기는 출처를 안 가리므로 Unity 쪽 코드 변경 불필요)

SDK 근거 (DGSDK.h/DGDataTypes.h, dg_python-main 공식 래퍼, 매뉴얼 9.2/10.1절 대조, 2026-08-31 확인):
  GetReceivedGripperData(ReceivedGripperData*) — joint[20]이 MoveServoJoint와 동일한
  20채널[deg] 규약. 이 함수 자체는 이 저장소에서 처음 바인딩한다(기존 dg5f_sdk_bridge.py는
  MoveServoJoint 등 9개 함수만 바인딩, 읽기 계열은 미사용 — docs2/TESOLLO_SDK_기술부채_조사.md
  부채③ 참고).
  ⚠️ **DEVELOPER 모드 필수** — 매뉴얼 9.2절 enum DEVELOPER_MODE_COMMAND가 "그리퍼 사용자
  (OPERATOR) 모드 미지원 명령어" 목록 1번으로 GET_DATA(설정된 데이터 수신)를 명시한다.
  즉 OPERATOR 모드로는 애초에 이 읽기 자체가 불가능 — control-mode는 항상 developer.

⚠️ 실물 테스트 전 확인되지 않은 것 (로컬 오프라인 네트워크에서 실측 필요):
  **동시 접속 가능 여부** — DGManager(또는 다른 SDK 클라이언트)가 이미 그리퍼에 붙어 있는
  상태에서, 이 스크립트가 별도 프로세스로 같은 그리퍼(Modbus TCP :502)에 **두 번째 연결**을
  여는 것을 그리퍼 펌웨어가 허용하는지 미확인. 게다가 이 스크립트는 DEVELOPER 모드로 붙어야
  해서, DGManager가 OPERATOR 모드로 물려 있다면 컨트롤 모드 자체가 전역 상태일 경우
  충돌 가능성도 있음(둘 다 미확인). 안 되면 먼저 DGManager를 끄고 이 스크립트 단독으로
  읽기가 되는지 확인한 뒤, DGManager를 같이 켜서 재시도할 것 — 이 스크립트는 실물에
  아무것도 쓰지 않는(읽기 전용) 안전한 편이라, 실패해도 하드웨어 손상 위험은 없다.

2026-08-31 실물 1차 테스트에서 "access violation writing 0x0"으로 죽었던 원인은 매뉴얼
10.1 ConnectToGripper 예제가 명시한 콜백 등록(InitializedCallback)을 안 해서였다 —
dg5f_sdk_bridge.py의 Dg5fSdk.connect()에 콜백 등록을 추가해 고쳤다(그 파일 주석 참고).

사용:
  python dg5f_readback_bridge.py --fake
      # 하드웨어 없이 가짜 스윕 패턴을 Unity로 송신 — UDP 수신 경로만 먼저 검증
  python dg5f_readback_bridge.py --ip 169.254.186.72
      # 실물 연결, DGManager 등으로 움직인 실제 관절각을 Unity로 중계
  종료: Ctrl+C (SystemStop + Disconnect 자동, --fake는 소켓만 정리)
"""
import argparse
import ctypes
import json
import math
import socket
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import UNITY_IP, PORT_DG5F_SIM, DG5F_GRASP_POSE_FILE

from dg5f_sdk_bridge import (
    Dg5fSdk, MODELS, DG_RESULT_NONE, DEFAULT_DLL,
    CONTROL_MODE_DEVELOPER, N_JOINTS, ReceivedGripperData,
    CHANNEL_NAMES, from_sdk_frame,
)

CONTROL_MODE_OPERATOR = 0


def bind_readback(dll):
    dll.GetReceivedGripperData.argtypes = [ctypes.POINTER(ReceivedGripperData)]
    dll.GetReceivedGripperData.restype = ctypes.c_int
    # ManualTeachMode(int isOn) — DGSDK.h Motion Functions:
    #   "Manual teaching mode allows a human to set the gripper pose and teach all joints directly"
    # 그리퍼가 클라이언트 1개만 허용해(2026-08-31 실측) DGManager와 동시 접속이 불가능하므로,
    # 이 스크립트가 연결을 독점한 채로 손을 움직일 수단이 필요하다 — 그게 이 모드다.
    dll.ManualTeachMode.argtypes = [ctypes.c_int]
    dll.ManualTeachMode.restype = ctypes.c_int


def main():
    ap = argparse.ArgumentParser(description="DG-5F 실물 상태 판독 → Unity 트윈 반사")
    ap.add_argument("--ip", default=None, help="그리퍼 IP — 생략 시 --fake만 가능")
    ap.add_argument("--port", type=int, default=502, help="그리퍼 Modbus TCP 포트 (기본 502)")
    ap.add_argument("--model", default="5f_right", choices=sorted(MODELS))
    ap.add_argument("--dll", default=DEFAULT_DLL, help="DGSDK.dll 경로")
    ap.add_argument("--send-ip", default=UNITY_IP, help="Unity가 도는 PC IP (기본 config UNITY_IP)")
    ap.add_argument("--send-port", type=int, default=PORT_DG5F_SIM,
                     help=f"Unity Dg5fReceiver 포트 (기본 {PORT_DG5F_SIM})")
    ap.add_argument("--hz", type=float, default=30.0, help="폴링/송신 Hz (기본 30)")
    ap.add_argument("--control-mode", choices=["developer", "operator"], default="developer",
                     help="기본 developer — GetReceivedGripperData(읽기)는 매뉴얼상 OPERATOR "
                          "모드에서 지원 안 됨(9.2절 DEVELOPER_MODE_COMMAND 참고). operator는 "
                          "동작 확인용으로만 남겨둠 — 정상적으로는 안 될 가능성이 높음")
    ap.add_argument("--teach", action="store_true",
                     help="수동 교시 모드(ManualTeachMode) — 관절 힘을 풀어 사람이 손으로 직접 "
                          "손가락을 접었다 펼 수 있게 한다. 그리퍼가 클라이언트 1개만 허용해 "
                          "DGManager와 동시 접속이 안 되므로, 이 스크립트가 연결을 쥔 채로 손을 "
                          "움직이려면 이 모드가 필요하다. 종료(Ctrl+C) 시 자동 해제. "
                          "⚠️ 켜는 순간 힘이 풀려 손가락이 중력으로 처질 수 있음 — 물건을 쥔 "
                          "상태에서는 켜지 말 것")
    ap.add_argument("--rest", action="store_true",
                     help="영점 확인 모드 — 손을 쫙 편 상태로 두고 실행하면 20채널 전체를 "
                          "일정 시간 평균내어 채널명과 함께 표로 출력하고 종료한다. 우리 규약은 "
                          "'편 상태 = 0'이므로, 여기서 0에서 많이 벗어난 채널이 곧 영점 오차다.")
    ap.add_argument("--rest-sec", type=float, default=2.0,
                     help="--rest에서 평균낼 시간(초) (기본 2.0)")
    ap.add_argument("--capture-pose", nargs="?", const=DG5F_GRASP_POSE_FILE, default=None,
                     metavar="JSON",
                     help="지금 실물 손이 잡고 있는 자세를 캡처해 JSON으로 저장하고 종료한다. "
                          "사람이 손을 원하는 파지 자세로 만들어 놓고(필요하면 --teach) 실행하면, "
                          f"Unity의 '파지하기' 버튼이 그대로 재생한다. 경로 생략 시 "
                          f"{DG5F_GRASP_POSE_FILE}")
    ap.add_argument("--pose-name", default="grasp",
                     help="--capture-pose로 저장할 자세 이름(파일에 기록, 예: grasp_papercup)")
    ap.add_argument("--probe", action="store_true",
                     help="관절 대응 검증 모드 — 시작 시 현재 자세를 기준(baseline)으로 잡고, "
                          "이후 기준 대비 가장 많이 변한 채널을 실시간 표시한다. --teach와 같이 켜고 "
                          "손가락 관절을 하나씩만 움직여, 우리가 가정한 채널 이름과 실제 관절이 "
                          "일치하는지 확인할 때 쓴다(실물에 명령을 보내지 않으므로 안전).")
    ap.add_argument("--probe-top", type=int, default=3,
                     help="--probe에서 표시할 상위 변화 채널 수 (기본 3)")
    ap.add_argument("--fake", action="store_true",
                     help="하드웨어 없이 가짜 스윕 패턴 송신 — UDP 경로/Unity 수신만 검증")
    args = ap.parse_args()

    if args.fake:
        run_fake(args)
        return
    if args.ip is None:
        print("[오류] --ip 없이는 --fake만 가능합니다 (예: python dg5f_readback_bridge.py --fake)")
        return
    run_real(args)


def run_fake(args):
    """실물 없이 20채널을 0~일부 굽힘값으로 스윕 — Unity 수신 경로만 검증."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.hz
    t0 = time.time()
    print(f"[가짜 모드] {args.send_ip}:{args.send_port}로 스윕 패턴 송신 (Ctrl+C 종료)")
    try:
        while True:
            t = time.time() - t0
            sweep = 40.0 * (0.5 - 0.5 * math.cos(t))  # 0→80° 왕복
            vals = [sweep if i not in (0,) else 0.0 for i in range(N_JOINTS)]
            sock.sendto(struct.pack(f"<{N_JOINTS}f", *vals), (args.send_ip, args.send_port))
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")


def _sample_mean(sdk, args, seconds, label):
    """실물 관절각을 seconds 동안 평균낸다(우리 규약). 빈 프레임은 버린다."""
    data = ReceivedGripperData()
    period = 1.0 / args.hz
    n = max(1, int(seconds * args.hz))
    print(f"[{label}] {seconds:.1f}초 동안 {n}회 샘플링 — 손을 움직이지 마세요…")
    samples, skipped = [], 0
    while len(samples) < n:
        if sdk.dll.GetReceivedGripperData(ctypes.byref(data)) == DG_RESULT_NONE:
            frame = from_sdk_frame(data.joint)
            # 연결 직후 첫 프레임은 데이터 도착 전이라 전부 0이다 — 평균을 오염시키므로 버린다.
            if all(v == 0.0 for v in frame):
                skipped += 1
                time.sleep(period)
                continue
            samples.append(frame)
        time.sleep(period)
    if skipped:
        print(f"[{label}] (데이터 도착 전 빈 프레임 {skipped}개 제외)")
    return [sum(s[i] for s in samples) / len(samples) for i in range(N_JOINTS)], samples


def run_capture_pose(sdk, args):
    """지금 실물이 잡고 있는 자세를 JSON으로 저장 — Unity '파지하기' 버튼이 읽는다."""
    mean, samples = _sample_mean(sdk, args, args.rest_sec, "capture")
    spread = [max(s[i] for s in samples) - min(s[i] for s in samples) for i in range(N_JOINTS)]

    print(f"\n{'idx':>3}  {'채널':<12} {'각도[deg]':>10} {'흔들림':>8}")
    print("-" * 40)
    for i in range(N_JOINTS):
        warn = "  ← 불안정" if spread[i] > 3.0 else ""
        print(f"{i:>3}  {CHANNEL_NAMES[i]:<12} {mean[i]:>10.2f} {spread[i]:>8.2f}{warn}")
    print("-" * 40)

    path = Path(args.capture_pose)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent.parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": args.pose_name,
        "hand": args.model,
        "captured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "real DG-5F readback (dg5f_readback_bridge.py --capture-pose)",
        "convention": "our channel order/sign (URDF·Unity 기준, deg) — 실물 SDK 규약과의 "
                      "부호 차이는 from_sdk_frame으로 이미 변환됨",
        "channels": list(CHANNEL_NAMES),
        "deg": [round(v, 2) for v in mean],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[capture] 저장 완료: {path}")
    print("[capture] Unity에서 Play 후 '파지하기' 버튼을 누르면 이 자세로 갑니다. "
          "다른 물체용 자세가 필요하면 --pose-name과 경로를 바꿔 여러 개 떠두면 됩니다.")


def run_rest(sdk, args):
    """손을 편 상태(우리 규약상 전 채널 0)로 두고 20채널 평균을 재 영점 오차를 본다."""
    data = ReceivedGripperData()
    period = 1.0 / args.hz
    n = max(1, int(args.rest_sec * args.hz))
    print(f"[rest] {args.rest_sec:.1f}초 동안 {n}회 샘플링 — 손을 움직이지 마세요…")
    samples = []
    skipped = 0
    while len(samples) < n:
        if sdk.dll.GetReceivedGripperData(ctypes.byref(data)) == DG_RESULT_NONE:
            frame = from_sdk_frame(data.joint)   # 표의 채널명이 우리 규약이므로 값도 우리 규약으로
            # 첫 폴링은 그리퍼 데이터가 도착하기 전이라 구조체가 통째로 0으로 나온다
            # (실행 로그 첫 줄이 늘 "0.0 0.0 0.0 0.0"인 이유). 그대로 평균에 넣으면 0쪽으로
            # 편향되므로 버린다. 실제로 전 관절이 정확히 0.000인 자세는 사실상 없다.
            if all(v == 0.0 for v in frame):
                skipped += 1
                time.sleep(period)
                continue
            samples.append(frame)
        time.sleep(period)
    if skipped:
        print(f"[rest] (데이터 도착 전 빈 프레임 {skipped}개 제외)")

    print(f"\n{'idx':>3}  {'채널':<12} {'평균[deg]':>10} {'최소':>7} {'최대':>7}  판정")
    print("-" * 58)
    offsets = []
    for i in range(N_JOINTS):
        col = [s[i] for s in samples]
        mean = sum(col) / len(col)
        offsets.append(mean)
        lo, hi = min(col), max(col)
        # 편 상태에서 0에서 얼마나 벗어났나 — 5° 넘으면 눈에 띄는 영점 오차로 본다.
        mark = "OK" if abs(mean) <= 5.0 else ("확인" if abs(mean) <= 15.0 else "★큼")
        print(f"{i:>3}  {CHANNEL_NAMES[i]:<12} {mean:>10.2f} {lo:>7.1f} {hi:>7.1f}  {mark}")

    worst = max(range(N_JOINTS), key=lambda i: abs(offsets[i]))
    print("-" * 58)
    print(f"[rest] 최대 이탈: [{worst}] {CHANNEL_NAMES[worst]} = {offsets[worst]:+.2f}°")
    print("[rest] 판정 기준: 우리 규약은 '편 상태 = 0'이다. 어떤 채널이 수십 도(예 ±90) 어긋나 "
          "있으면 그건 영점이 아니라 **매핑이 틀렸다**는 신호다.")
    if not args.teach:
        # ★이 구분이 중요하다(2026-08-31). 서보가 켜져 명령각을 유지 중이면, 그 명령이 0인 한
        #   readback의 잔차는 '영점 오차'가 아니라 '서보 정상추종오차'다. 둘은 원인이 달라
        #   전자는 캘리브레이션으로 빼야 하지만 후자는 빼면 안 된다(오차를 영점에 굳혀버린다).
        #   명령도 0이고 읽기도 0이라 순환적이라, 이 모드만으로는 영점을 독립 검증할 수 없다.
        print("[rest] ⚠️ 지금은 서보가 켜진 상태다 — SDK가 이미 어떤 포즈(대개 전 관절 0)를 "
              "명령해 유지 중이라면, 위 잔차는 영점 오차가 아니라 **서보 추종오차**일 수 있다. "
              "그 값을 JOINT_OFFSET_DEG에 넣으면 추종오차를 영점으로 굳히는 셈이라 오히려 나쁘다.")
        print("[rest] → 영점을 독립적으로 보려면 서보 명령을 빼고 재실행할 것: "
              "`--rest --teach` (힘을 풀고 손으로 곧게 편 뒤 측정)")
    else:
        print("[rest] 교시 모드(서보 명령 없음)에서 측정했으므로, 위 값은 추종오차가 아닌 "
              "실제 영점 오차로 볼 수 있다.")
    print("[rest] 참고 — 그대로 쓰려면 dg5f_sdk_bridge.py의 JOINT_OFFSET_DEG에 넣는다:")
    print("JOINT_OFFSET_DEG = [" + ", ".join(f"{v:.1f}" for v in offsets) + "]")
    print("[rest] 다만 전부 작으면(≈5° 이내) 실용상 0으로 두는 편이 낫다 — "
          "한 번 관측으로 과적합하지 말 것.")


def run_real(args):
    dll_path = str(Path(args.dll).resolve())
    if not Path(dll_path).exists():
        print(f"[오류] DLL 없음: {dll_path}")
        return

    sdk = Dg5fSdk(dll_path)
    bind_readback(sdk.dll)

    control_mode = CONTROL_MODE_DEVELOPER if args.control_mode == "developer" else CONTROL_MODE_OPERATOR
    print(f"[연결 시도] {args.ip}:{args.port} model={args.model} control_mode={args.control_mode} "
          "— DGManager가 이미 붙어 있다면 여기서 실패/타임아웃 가능(동시접속 미검증, 상단 docstring 참고)")
    try:
        # set_gains=False — 이 스크립트는 관절을 구동하지 않으므로(읽기 전용) 게인이 필요 없고,
        # 그리퍼 상태에 불필요한 쓰기를 하지 않는다. 반대로 **구동하는** dg5f_sdk_bridge.py는
        # 반드시 게인을 넣어야 한다 — 안 넣으면 전 관절이 움직이지 않는다(2026-08-31 실측).
        # SetGripperOption(receivedDataType=JOINT)은 GetReceivedGripperData가 값을 채우는 데
        # 필요해 보여 그대로 호출한다(connect() 내부).
        sdk.connect(args.ip, args.port, MODELS[args.model],
                    control_mode=control_mode, set_gains=False)
    except Exception as e:
        print(f"[연결 실패] {e}")
        print("[안내] DGManager를 켠 채로 실패했다면 DGManager를 끄고 이 스크립트 단독으로 "
              "먼저 연결되는지 확인할 것 (동시접속 미지원 가능성 — 상단 docstring 참고).")
        return
    print("[연결] 성공 — 읽기 전용 폴링 시작 (이 스크립트는 MoveServoJoint를 호출하지 않음)")

    teach_on = False
    if args.teach:
        res = sdk.dll.ManualTeachMode(1)
        if res == DG_RESULT_NONE:
            teach_on = True
            print("[교시] 수동 교시 모드 ON — 손으로 직접 손가락을 움직이세요. "
                  "Ctrl+C로 종료하면 자동 해제됩니다.")
        else:
            print(f"[경고] ManualTeachMode(1) 실패 DG_RESULT={res} — 교시 모드 없이 계속합니다"
                  "(손을 움직일 수단이 없으면 값이 고정으로 보일 수 있음).")

    if args.capture_pose or args.rest:
        (run_capture_pose if args.capture_pose else run_rest)(sdk, args)
        if teach_on:
            sdk.dll.ManualTeachMode(0)
            print("[교시] 수동 교시 모드 OFF")
        sdk.close()
        print("[종료] SystemStop + Disconnect 완료")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = ReceivedGripperData()
    period = 1.0 / args.hz
    last_print = 0.0
    baseline = None
    baseline_samples = []
    BASELINE_N = 15          # 약 0.5초(30Hz) 평균 — 노이즈 억제
    if args.probe:
        print("[probe] 기준 자세를 잡는 중… 손을 움직이지 말고 잠시 기다리세요.")
    try:
        while True:
            res = sdk.dll.GetReceivedGripperData(ctypes.byref(data))
            if res == DG_RESULT_NONE:
                # 실물 SDK 규약 → 우리(URDF/Unity) 규약. 순서는 같지만 부호가 다른 채널이
                # 있다(thumb_opp) — 변환을 빼면 Unity 리밋에서 잘려 트윈만 안 움직인다.
                joints = from_sdk_frame(data.joint)
                sock.sendto(struct.pack(f"<{N_JOINTS}f", *joints), (args.send_ip, args.send_port))
                now = time.time()

                if args.probe and baseline is None:
                    baseline_samples.append(joints)
                    if len(baseline_samples) >= BASELINE_N:
                        baseline = [sum(s[i] for s in baseline_samples) / len(baseline_samples)
                                    for i in range(N_JOINTS)]
                        print("[probe] 기준 확보 완료. 이제 관절을 **하나씩만** 움직여 보세요 — "
                              "가장 많이 변한 채널이 그 관절의 인덱스입니다.")
                elif args.probe:
                    if now - last_print >= 0.3:
                        deltas = [(abs(joints[i] - baseline[i]), i) for i in range(N_JOINTS)]
                        deltas.sort(reverse=True)
                        parts = []
                        for mag, i in deltas[:args.probe_top]:
                            d = joints[i] - baseline[i]
                            parts.append(f"[{i:2d}] {CHANNEL_NAMES[i]:<11} {d:+7.1f}°")
                        print("[probe] " + "  |  ".join(parts))
                        last_print = now
                elif now - last_print >= 0.5:
                    print("[readback]", " ".join(f"{v:5.1f}" for v in joints[:4]), "...")
                    last_print = now
            else:
                print(f"[경고] GetReceivedGripperData DG_RESULT={res}")
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        if teach_on:
            # 교시 모드를 켠 채로 끊으면 그리퍼가 힘 풀린 상태로 남을 수 있다 — 반드시 해제.
            r = sdk.dll.ManualTeachMode(0)
            print("[교시] 수동 교시 모드 OFF" + ("" if r == DG_RESULT_NONE else f" (DG_RESULT={r})"))
        sdk.close()
        print("[종료] SystemStop + Disconnect 완료")


if __name__ == "__main__":
    main()
