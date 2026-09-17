# -*- coding: utf-8 -*-
"""무부하 전류 기준표 만들기 — **아무것도 안 잡았을 때** 전류가 얼마나 나오는지 잰다.

왜 이걸 먼저 해야 하나
----------------------
손끝 센서가 없어서 "닿았다" 를 전류로 추정하는데, **"평소보다 높다" 를 말하려면 평소를
알아야 한다.** 그 평소가 이 표다.

그리고 평소는 **하나의 숫자가 아니다.** 관절마다 다르고(엄지 모터와 새끼 모터가 다르다),
같은 관절이라도 각도마다 다르다(중력·마찰·기구 간섭). 그래서 관절 20개 × 각도 구간마다
따로 잰다.

무엇을 하는가
-------------
1. 손을 **천천히 폈다 오므렸다** 여러 번 반복한다 (`--passes`)
2. 매 순간의 관절 각도와 전류를 모은다
3. 각도 구간별로 평균과 흔들림을 내어 `config/dg5f_current_baseline.json` 에 저장한다

🛑 돌리기 전에 반드시
---------------------
- **손 안과 손 주변을 비운다.** 뭔가에 닿은 채로 재면 그 힘이 "평소" 로 들어가 버려서,
  나중에 진짜로 닿았을 때 못 알아챈다.
- **손을 공중에 두고** 테이블·사람 손에 닿지 않게 한다.
- 로봇 티치펜던트의 URCap 이 손을 잡고 있으면 **PC 는 연결조차 안 된다** — 이 그리퍼는
  TCP 연결을 하나만 받는다(2026-08-31 실물 실측). URCap/DGManager 를 먼저 끊는다.

돌리는 법
---------
터미널 1 (PowerShell, 리포 루트) — 손 없이 배관만 확인:

    vision/.vision/Scripts/Activate.ps1
    python hand/measure_baseline.py --fake

터미널 1 (PowerShell, 리포 루트) — 실물:

    vision/.vision/Scripts/Activate.ps1
    python hand/measure_baseline.py --ip

터미널 1 (bash, 리포 루트):

    source vision/.vision/bin/activate
    python hand/measure_baseline.py --ip

`--ip` 를 값 없이 주면 `.env` 의 `RTAUTO_DG5F_IP` 를 쓴다(원칙 1).
끝나면 "쓸 만한 칸 몇 %" 가 나온다. 낮으면 `--passes` 를 늘려 다시 잰다.

⚠️ 실물 검증 0회
-----------------
2026-09-17 현재 이 스크립트는 **실물에서 한 번도 안 돌았다**(그리퍼를 PC 에 물릴 스위치와
랜 어댑터가 아직 도착하지 않았다). `--fake` 로 배관만 확인해 뒀다.
설계 정본: [`docs/GRASP_CONTACT_DETECTION.md`](../docs/GRASP_CONTACT_DETECTION.md)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "hand"))
sys.path.insert(0, str(REPO_ROOT / "vision" / "dg5f"))

import rtauto_config as cfg  # noqa: E402

from grasp_contact import (  # noqa: E402
    BASELINE_MAX_DEG, BASELINE_MIN_DEG, N_JOINTS, CurrentBaseline,
)

#: 재는 동안 관절을 움직일 범위(도). 실제로 쓸 범위를 다 덮어야 표에 빈칸이 안 생긴다.
#: ⚠️ 잠정값 — 실물 관절 한계를 확인하고 맞출 것(`vision/dg5f/joint_ranges.py`).
SWEEP_OPEN_DEG = 0.0
SWEEP_CLOSE_DEG = 60.0

#: 한 번 폈다 오므리는 데 걸리는 시간(초). 느릴수록 좋다 — 빠르면 가속 때문에 전류가
#: 부풀려져 "평소" 가 실제보다 높게 잡힌다.
SWEEP_SECONDS = 8.0

#: 상태를 읽는 주기(Hz).
READ_HZ = 50.0


class FakeHand:
    """손 없이 배관만 확인하는 가짜 손. 각도에 따라 전류가 조금씩 달라진다."""

    def __init__(self, seed=0):
        self.angle = np.zeros(N_JOINTS)
        self.rng = np.random.default_rng(seed)

    def servo(self, deg20):
        self.angle = np.asarray(deg20, dtype=float)

    def read_full(self):
        # 각도가 클수록 전류가 조금 는다 + 관절마다 다른 바탕값 + 잡음
        base = 30.0 + np.arange(N_JOINTS) * 2.0
        current = base + np.abs(self.angle) * 0.8 + self.rng.normal(0, 4.0, N_JOINTS)
        return self.angle.copy(), current, np.zeros(N_JOINTS), 0

    def close(self):
        pass


class RealHand:
    """실물 손. 기존 브리지(`vision/dg5f/dg5f_sdk_bridge_dgsdk.py`)를 그대로 쓴다.

    ⚠️ **속도(velocity)를 따로 요청해야 한다.** 기존 브리지는 받을 항목으로
    JOINT/CURRENT/MODULE_ERROR_CODE 만 켜 두어서(`RECEIVED_DATA_TYPE = [1, 2, 7, ...]`)
    속도가 0 으로만 들어온다. 접촉 판단이 "멈췄는가" 를 보므로 여기서는 VELOCITY(4)를
    켜서 연결한다.
    """

    def __init__(self, ip, port, model, lib_dir):
        from dg5f_sdk_bridge_dgsdk import Dg5fSdkOfficial, MODELS
        import dg5f_sdk_bridge_dgsdk as bridge

        # JOINT(1) + CURRENT(2) + VELOCITY(4) + MODULE_ERROR_CODE(7)
        bridge.RECEIVED_DATA_TYPE = [1, 2, 4, 7, 0, 0, 0, 0]
        self.sdk = Dg5fSdkOfficial(lib_dir)
        self.sdk.connect(ip=[int(v) for v in ip.split(".")], port=port,
                         model_code=MODELS[model])

    def servo(self, deg20):
        self.sdk.servo(list(deg20))

    def read_full(self):
        data = self.sdk.sdk.get_gripper_data()
        return (np.asarray(list(data.joint)[:N_JOINTS], dtype=float),
                np.asarray(list(data.current)[:N_JOINTS], dtype=float),
                np.asarray(list(data.velocity)[:N_JOINTS], dtype=float),
                int(data.moduleErrorCode))

    def close(self):
        self.sdk.close()


def sweep(hand, passes, open_deg, close_deg, seconds, hz, dwell=1.0):
    """폈다 오므렸다 하며 각도·전류를 모은다.

    양 끝에서 `dwell` 초 **머무른다.** 안 그러면 끝 각도 구간에 표본이 거의 안 쌓여
    "여기는 재 본 적 없음" 으로 남는다 — 그런데 끝 각도(다 오므린 자세)는 실제로 가장
    많이 쓰는 구간이다. 가짜 손으로 돌려 보다 발견했다.
    """
    angles, currents, vels = [], [], []
    dt = 1.0 / hz
    steps = max(2, int(seconds * hz))
    dwell_steps = max(1, int(dwell * hz))

    def sample(target):
        hand.servo(np.full(N_JOINTS, target))
        time.sleep(dt)
        a, c, v, err = hand.read_full()
        if err:
            raise RuntimeError("손이 오류를 보고했다 (코드 {}) — 중단한다".format(err))
        angles.append(a)
        currents.append(c)
        vels.append(v)

    for p in range(passes):
        for direction in (+1, -1):
            for i in range(steps):
                f = i / (steps - 1)
                if direction < 0:
                    f = 1.0 - f
                sample(open_deg + (close_deg - open_deg) * f)
            # 끝에서 잠깐 머문다 — 끝 구간 표본을 채운다
            end = close_deg if direction > 0 else open_deg
            for _ in range(dwell_steps):
                sample(end)
        print("  {}/{}번째 왕복 끝 — 표본 {}개".format(p + 1, passes, len(angles)), flush=True)
    return np.asarray(angles), np.asarray(currents), np.asarray(vels)


def main() -> int:
    ap = argparse.ArgumentParser(description="무부하 전류 기준표 만들기")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="그리퍼 IP. 값 없이 주면 .env 의 RTAUTO_DG5F_IP 를 쓴다")
    ap.add_argument("--fake", action="store_true", help="손 없이 배관만 확인")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--model", default="5f_right")
    ap.add_argument("--lib-dir", default=None)
    ap.add_argument("--passes", type=int, default=3, help="폈다 오므리기를 몇 번 반복할지")
    ap.add_argument("--open-deg", type=float, default=SWEEP_OPEN_DEG)
    ap.add_argument("--close-deg", type=float, default=SWEEP_CLOSE_DEG)
    ap.add_argument("--seconds", type=float, default=SWEEP_SECONDS,
                    help="한 방향에 걸리는 시간(초). 느릴수록 정확하다")
    ap.add_argument("--hz", type=float, default=READ_HZ)
    ap.add_argument("--dwell", type=float, default=1.0,
                    help="양 끝 각도에서 머무는 시간(초). 끝 구간 표본을 채운다")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not args.fake and args.ip is None:
        print("실물에 붙으려면 --ip 를, 배관만 확인하려면 --fake 를 준다.")
        return 2

    print("=== 무부하 전류 기준표 만들기 ===")
    print("🛑 손 안과 손 주변이 비어 있어야 한다. 뭔가에 닿은 채로 재면 그 힘이")
    print("   '평소' 로 들어가 버려 나중에 진짜 접촉을 못 알아챈다.")
    print("범위 {:.0f}~{:.0f}도, 한 방향 {:.0f}초, {}번 왕복, {:.0f}Hz".format(
        args.open_deg, args.close_deg, args.seconds, args.passes, args.hz))
    print()

    if args.fake:
        hand = FakeHand()
        print("[가짜 손] 배관만 확인한다 — 이 표를 실물에 쓰지 마라")
    else:
        ip = cfg.resolve_gripper_ip(args.ip)
        lib_dir = args.lib_dir or cfg.DG5F_DGSDK_LIB_DIR or str(
            REPO_ROOT / "vision" / "dg5f" / "vendor" / "dgsdk-python" / "libs")
        print("[실물] {}:{} 모델 {}".format(ip, args.port, args.model))
        hand = RealHand(ip, args.port, args.model, lib_dir)

    try:
        angles, currents, vels = sweep(hand, args.passes, args.open_deg,
                                       args.close_deg, args.seconds, args.hz,
                                       args.dwell)
    finally:
        hand.close()

    table = CurrentBaseline.from_samples(
        angles, currents,
        made_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        note=("가짜 손 — 실물에 쓰지 마라" if args.fake else
              "무부하 실측 ({:.0f}~{:.0f}도, {}왕복)".format(
                  args.open_deg, args.close_deg, args.passes)))

    out = Path(args.out) if args.out else (REPO_ROOT / cfg.DG5F_BASELINE_FILE)
    table.save(out)

    print()
    print("=" * 62)
    covered = table.coverage()
    print("표본 {}개, 쓸 만한 칸 {:.0%}".format(len(angles), covered))
    # 실제로 쓸 각도 범위만 따로 본다 — 안 쓸 각도가 비어 있는 건 문제가 아니다
    lo, hi = min(args.open_deg, args.close_deg), max(args.open_deg, args.close_deg)
    print("잰 범위({:.0f}~{:.0f}도) 안에서 못 채운 관절:".format(lo, hi))
    holes = 0
    for j in range(N_JOINTS):
        missing = [a for a in np.arange(lo, hi + 1, 10.0)
                   if table.threshold_ma(j, float(a)) is None]
        if missing:
            holes += 1
            print("  관절 {:2d}번 — {}도 구간이 비었다".format(
                j, ", ".join("{:.0f}".format(a) for a in missing)))
    if holes == 0:
        print("  없음 — 쓸 수 있다")
    else:
        print("  ⚠️ --passes 를 늘리거나 --seconds 를 키워 다시 재라")
    print("전류 평균 {:.0f} mA, 흔들림 {:.0f} mA (잰 칸만)".format(
        float(np.mean(currents)), float(np.std(currents))))
    if not args.fake and float(np.max(np.abs(vels))) < 1e-9:
        print("⚠️ 속도가 전부 0이다 — 받을 항목에 VELOCITY 가 안 켜졌을 수 있다")
    print("저장: {}".format(out))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
