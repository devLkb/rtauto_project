# -*- coding: utf-8 -*-
"""벌림(손가락이 옆으로 벌어진 각도) 계산 검증 — 카메라도 손도 필요 없다.

왜 이 테스트가 있나 (2026-09-16):
  실측에서 **새끼손가락을 벌려도 그리퍼가 따라오지 않는** 문제를 파고들다가, 벌림 계산에
  굽힘이 크게 섞여 있다는 걸 찾았다(새끼 좌우값 vs 새끼 굽힘 상관 −0.77, 사람 폭 102°가
  로봇 허용 폭 24°를 4배 초과 → 78.5%가 잘림).

어떻게 검증하나:
  **정답을 아는 가상의 손**을 수학으로 만든다. "벌림 20°, 굽힘 50°" 같은 값을 넣어 21개
  점의 좌표를 직접 계산하고, 그 점들을 계산식에 넣어 원래 넣은 값이 나오는지 본다.
  실제 손으로는 "지금 정확히 몇 도 벌렸는지"를 알 수 없으므로 이런 검증이 불가능하다.

여기서 확인하는 것:
  ① 쭉 편 손가락에서는 새 방식과 옛 방식이 같은 값을 준다(부호·크기 규약이 안 바뀌었다)
  ② 굽히기만 하고 벌리지는 않았을 때, 새 방식은 0 근처를 지키고 옛 방식은 크게 요동친다
  ③ 벌린 채로 굽히면 새 방식의 값은 **작아질 뿐 폭주하지 않는다**(문서화된 성질)
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dg5f_angles as A

HAND_LEN = 8.0        # 손목→중지 MCP 거리(cm 정도로 생각하면 된다)
PHALANX = 4.0         # 첫 마디 길이
MCP_X = {5: 1.5, 9: 0.5, 13: -0.5, 17: -1.5}   # 검지·중지·약지·새끼 MCP의 좌우 위치


def make_hand(abduction_deg=0.0, flexion_deg=0.0, finger=A.PINKY, seed=None, noise=0.0,
              bend_lateral_deg=0.0):
    """정답을 아는 가상 손의 21개 점을 만든다.

    손 좌표계: 앞(+y) · 옆(+x) · 손바닥 법선(+z). 지정한 손가락만 벌림/굽힘을 주고
    나머지는 쭉 편 상태로 둔다. noise는 랜드마크에 섞을 흔들림(손 길이 대비 비율) —
    MediaPipe는 깊이(z)가 특히 부정확하므로 z에 3배로 준다.

    bend_lateral_deg은 **실제 손의 성질**을 흉내 낸다: MCP 관절의 회전축이 손 축과 정확히
    직각이 아니라서, 손가락을 굽히면 첫 마디가 옆으로도 따라 눕는다(굽힘각의 sin에 비례).
    실측으로 새끼는 −38.3°, 약지는 −16.8°였다(dg5f_angles.ABD_BEND_SIN_DEG).
    """
    lm = np.zeros((21, 3), dtype=float)
    lm[A.WRIST] = (0.0, 0.0, 0.0)
    for idx, x in MCP_X.items():
        lm[idx] = (x, HAND_LEN, 0.0)
    lm[A.THUMB[0]] = (3.0, 2.0, 0.0)             # 엄지는 이 계산에 쓰이지 않는다

    # 손의 앞/옆 방향 — _hand_lateral_axis가 쓰는 것과 같은 정의로 직접 만든다.
    palm_n = np.array([0.0, 0.0, 1.0])
    fwd = lm[A.MIDDLE[0]] - lm[A.WRIST]
    fwd /= np.linalg.norm(fwd)
    lat = np.cross(palm_n, fwd)
    lat /= np.linalg.norm(lat)

    for f in (A.INDEX, A.MIDDLE, A.RING, A.PINKY):
        a = math.radians(abduction_deg) if f is finger else 0.0
        fl = math.radians(flexion_deg) if f is finger else 0.0
        # 벌림 = 손바닥 평면 안에서 옆으로 돌리기, 굽힘 = 그 방향에서 손바닥 쪽으로 눕히기
        d = math.cos(fl) * (math.cos(a) * fwd + math.sin(a) * lat) - math.sin(fl) * palm_n
        if f is finger and bend_lateral_deg:
            # 굽힘에 비례해 손가락을 옆으로 더 눕힌다. 굽힌 깊이는 그대로 두고 **옆으로 기운
            # 각도만** 바꾸는 방식이라, 계산식이 읽는 값이 정확히 (원래값 + 계수×sin굽힘)이 된다.
            d /= np.linalg.norm(d)
            side = math.asin(float(np.clip(np.dot(d, lat), -1.0, 1.0)))
            plane = d - np.dot(d, lat) * lat
            n_plane = np.linalg.norm(plane)
            if n_plane > 1e-9:
                tilted = side + math.radians(bend_lateral_deg) * math.sin(fl)
                d = math.sin(tilted) * lat + math.cos(tilted) * (plane / n_plane)
        for k in range(1, 4):                    # PIP·DIP·TIP을 같은 방향으로 이어 붙인다
            lm[f[k]] = lm[f[0]] + d * PHALANX * k

    if noise:
        rng = np.random.default_rng(seed)
        sigma = noise * HAND_LEN
        lm = lm + rng.normal(0.0, sigma, lm.shape) * np.array([1.0, 1.0, 3.0])
    return lm


# 굽힘 보정계수가 0인 손가락 = 계산식 자체만 시험할 때 쓴다(보정이 섞이지 않는다).
PLAIN = A.INDEX


def deg_new(lm, finger=A.PINKY):
    return math.degrees(A._abduction_lateral(lm, finger))


def deg_old(lm, finger=A.PINKY):
    return math.degrees(A._abduction_planar(lm, finger))


class AbductionTest(unittest.TestCase):
    def test_straight_finger_reads_the_true_angle(self):
        """쭉 편 손가락: 넣은 벌림각이 그대로 나와야 한다."""
        for truth in (-30.0, -15.0, 0.0, 10.0, 25.0, 40.0):
            lm = make_hand(abduction_deg=truth, flexion_deg=0.0, finger=PLAIN)
            self.assertAlmostEqual(deg_new(lm, PLAIN), truth, delta=2.0, msg=f"벌림 {truth}°")

    def test_new_and_old_agree_when_straight(self):
        """부호 규약이 바뀌지 않았는지 — 손가락을 편 상태에서는 두 방식이 같아야 한다."""
        for truth in (-25.0, -10.0, 10.0, 25.0):
            lm = make_hand(abduction_deg=truth, flexion_deg=0.0, finger=PLAIN)
            self.assertAlmostEqual(deg_new(lm, PLAIN), deg_old(lm, PLAIN), delta=2.0,
                                   msg=f"벌림 {truth}°에서 새 방식과 옛 방식이 어긋남")

    def test_bending_does_not_make_the_new_formula_jumpy(self):
        """**굽힐수록 값이 불안정해지는가** — 옛 방식이 무너지는 지점.

        벌림은 0으로 고정하고 굽힘만 바꿔 가며 같은 크기의 랜드마크 흔들림을 준다.
        옛 방식은 굽힐수록 손바닥 평면 그림자가 짧아져 같은 흔들림이 큰 각도로 증폭된다.
        새 방식은 옆 성분만 보므로 훨씬 덜 커져야 한다. (굽힘 보정이 섞이지 않도록
        계수가 0인 검지로 시험한다 — 계산식 자체의 성질을 보는 것이다.)
        """
        def spread(method, flexions):
            vals = []
            for flex in flexions:
                for k in range(40):
                    lm = make_hand(abduction_deg=0.0, flexion_deg=float(flex), finger=PLAIN,
                                   seed=10_000 * flex + k, noise=0.004)
                    vals.append(method(lm, PLAIN))
            return float(np.std(vals))

        low, high = (0, 10, 20), (60, 70, 80)
        new_low, new_high = spread(deg_new, low), spread(deg_new, high)
        old_low, old_high = spread(deg_old, low), spread(deg_old, high)

        self.assertGreater(old_high, old_low * 3.0,
                           f"옛 방식이 굽힘에서 크게 나빠지는 현상이 재현되지 않음: "
                           f"조금굽힘 {old_low:.1f}° → 많이굽힘 {old_high:.1f}°")
        self.assertLess(new_high, old_high * 0.6,
                        f"많이 굽힌 구간에서 새 방식이 더 안정적이어야 한다: "
                        f"새 {new_high:.1f}° vs 옛 {old_high:.1f}°")

    def test_curling_shrinks_the_reading_instead_of_exploding(self):
        """벌린 채로 굽히면: 값이 **작아지기만** 하고 넣은 값을 넘지 않는다.

        (굽힘 보정이 0인 검지 기준 = 계산식 자체의 성질. 실제 새끼·약지는 굽힐 때 옆으로
        눕는 성질이 있어 보정이 더해지며, 그건 아래 test_bend_lateral_*이 따로 본다.)
        """
        truth = 30.0
        vals = [deg_new(make_hand(abduction_deg=truth, flexion_deg=float(f), finger=PLAIN), PLAIN)
                for f in range(0, 91, 10)]
        self.assertAlmostEqual(vals[0], truth, delta=2.0)
        for a, b in zip(vals, vals[1:]):
            self.assertLessEqual(b, a + 1e-6, f"굽힐수록 커지면 안 된다: {vals}")
        self.assertLessEqual(max(vals), truth + 2.0)
        # 다 굽히면 0 근처로 모인다. 정확히 0이 아닌 이유: 0도의 기준이 '손 앞방향'인데
        # 손가락은 손목에서 약간 비스듬히 뻗어 있어(검지 ≈7°) 그만큼이 남는다.
        self.assertLess(abs(vals[-1]), 9.0, f"다 굽히면 0 근처로 모여야 한다: {vals[-1]:.1f}°")

    def test_bend_lateral_coupling_is_removed(self):
        """**굽히면 옆으로 눕는 손가락**을 만들어, 굽힘 보정이 그걸 걷어내는지 본다.

        실제 손에서 새끼는 굽힐 때 옆으로 눕는다(실측 계수 −38.3°). 보정이 없으면 벌리지
        않았는데도 로봇 새끼가 옆으로 크게 흔들린다 — 이것이 2026-07-20에 벌림 범위를
        ±12°로 좁혀 놨던 이유이고, 그 좁은 범위가 다시 "벌려도 안 움직인다"를 만들었다.
        """
        k = A.ABD_BEND_SIN_DEG["pinky"]
        self.assertNotEqual(k, 0.0, "새끼는 굽힘 보정계수가 있어야 한다")
        fixed, plain = [], []
        for flex in range(0, 91, 10):
            lm = make_hand(abduction_deg=0.0, flexion_deg=float(flex), finger=A.PINKY,
                           bend_lateral_deg=k)
            fixed.append(deg_new(lm, A.PINKY))                     # 보정 포함(현재 계산식)
            plain.append(deg_new(lm, PLAIN))                       # 같은 손의 검지(계수 0)
        swing = lambda v: max(v) - min(v)
        # 보정이 없다면 새끼 값이 |k|·sin(굽힘)만큼 끌려간다 — 그걸 되돌려 확인한다.
        without = [f - math.degrees(math.radians(k) * math.sin(math.radians(fl)))
                   for f, fl in zip(fixed, range(0, 91, 10))]
        self.assertGreater(swing(without), 25.0,
                           f"시험용 손이 굽힘에 따라 옆으로 눕지 않았다: {without}")
        # 실측: 끌림 53.2° → 14.9°(72% 제거). 완전히 0이 되지 않는 이유는 보정이 쓰는
        # 굽힘각 자체가 옆으로 누운 손가락에서 조금 달라지기 때문이다(실제 손에서도 마찬가지).
        self.assertLess(swing(fixed), swing(without) * 0.35,
                        f"굽힘 보정이 끌림을 충분히 걷어내지 못했다 — 보정 전 "
                        f"{swing(without):.1f}° 보정 후 {swing(fixed):.1f}°")
        self.assertLess(swing(plain), 12.0, "보정계수가 0인 손가락은 원래대로 조용해야 한다")

    def test_middle_channel_stays_zero_on_the_robot(self):
        """중지 벌림은 로봇으로 **0만 나간다** — 계산식이 아니라 채널 설정(gated)이 보장한다.

        옛 계산식에서는 "중지 기준 상대 벌림"이라 중지가 정의상 0이었다. 새 계산식은
        손가락마다 자기 축으로 재므로 중지에도 값이 생기는데, 아무도 요청하지 않은 움직임을
        만들지 않으려고 채널을 gated로 두어 예전 결과(0)를 유지한다.
        """
        row = next(c for c in A.DG5F_CHANNELS if c[0] == "middle_abd")
        self.assertTrue(row[5], "middle_abd는 gated여야 한다")
        raw = [0.0] * len(A.CHANNEL_NAMES)
        raw[A.CHANNEL_NAMES.index("middle_abd")] = math.radians(20.0)
        out = A.map_to_dg5f(raw, hand="right", mode="direct")
        self.assertEqual(out[A.CHANNEL_NAMES.index("middle_abd")], A.GATED_NEUTRAL_DEG)

    def test_every_finger_uses_the_same_rule(self):
        """새끼만 특별 취급하지 않는다 — 같은 함수, 같은 축 정의, 손가락별 계수만 다르다."""
        for finger in (A.INDEX, A.MIDDLE, A.RING, A.PINKY):
            lm = make_hand(abduction_deg=20.0, flexion_deg=0.0, finger=finger)
            # 굽힘 0에서는 보정항(sin 0)이 사라지므로 어느 손가락이든 넣은 값이 나와야 한다
            self.assertAlmostEqual(deg_new(lm, finger), 20.0, delta=2.5,
                                   msg=f"손가락 {finger[0]}")

    def test_bent_finger_stops_commanding_spread(self):
        """**주먹 검증** — 손가락을 굽힐수록 벌림 명령이 0으로 줄어야 한다.

        굽힌 상태에서 벌림 명령이 남아 있으면 로봇 손가락이 **옆으로 벌어진 채 접힌다**.
        2026-09-16에 실제로 그렇게 됐다(주먹 구간 평균 +15.6°) — 벌림 범위를 넓힌 직후의
        부작용이었고, 이 처리로 +5.2°까지 줄였다.
        """
        def command(spread_deg, bend_deg):
            raw = [0.0] * len(A.CHANNEL_NAMES)
            raw[A.CHANNEL_NAMES.index("pinky_lat")] = math.radians(spread_deg)
            raw[A.CHANNEL_NAMES.index("pinky_mcp")] = math.radians(bend_deg)
            return A.map_to_dg5f(raw, hand="right", mode="direct")[
                A.CHANNEL_NAMES.index("pinky_lat")]

        self.assertAlmostEqual(command(30.0, 0.0), 30.0, delta=0.5)      # 편 손: 그대로
        self.assertAlmostEqual(command(30.0, 45.0), 15.0, delta=0.5)     # 반쯤 굽힘: 절반
        self.assertAlmostEqual(command(30.0, 90.0), 0.0, delta=0.5)      # 다 굽힘: 0
        self.assertAlmostEqual(command(30.0, 120.0), 0.0, delta=0.5)     # 더 굽혀도 0 아래로 안 감

        original = A.ABD_BEND_FADE_DEG
        try:
            A.ABD_BEND_FADE_DEG = 0.0                                    # 0 이하 = 이 처리 끄기
            self.assertAlmostEqual(command(30.0, 90.0), 30.0, delta=0.5)
        finally:
            A.ABD_BEND_FADE_DEG = original

    def test_fade_uses_each_fingers_own_bend(self):
        """벌림 채널마다 **자기 손가락의** 굽힘을 본다 — 남의 손가락을 보면 안 된다."""
        for abd, mcp in A.ABD_FADE_SOURCE.items():
            self.assertEqual(abd.split("_")[0], mcp.split("_")[0], f"{abd} ↔ {mcp}")
            self.assertIn(abd, A.CHANNEL_NAMES)
            self.assertIn(mcp, A.CHANNEL_NAMES)

    def test_method_switch_selects_the_formula(self):
        """ABDUCTION_METHOD로 옛 방식을 다시 켤 수 있다(비교·재현용)."""
        lm = make_hand(abduction_deg=20.0, flexion_deg=60.0, finger=PLAIN)
        original = A.ABDUCTION_METHOD
        try:
            A.ABDUCTION_METHOD = "planar"
            self.assertAlmostEqual(math.degrees(A._abduction(lm, PLAIN)), deg_old(lm, PLAIN),
                                   delta=1e-9)
            A.ABDUCTION_METHOD = "lateral"
            self.assertAlmostEqual(math.degrees(A._abduction(lm, PLAIN)), deg_new(lm, PLAIN),
                                   delta=1e-9)
        finally:
            A.ABDUCTION_METHOD = original


if __name__ == "__main__":
    unittest.main()
