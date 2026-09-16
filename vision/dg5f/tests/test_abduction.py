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


def make_hand(abduction_deg=0.0, flexion_deg=0.0, finger=A.PINKY, seed=None, noise=0.0):
    """정답을 아는 가상 손의 21개 점을 만든다.

    손 좌표계: 앞(+y) · 옆(+x) · 손바닥 법선(+z). 지정한 손가락만 벌림/굽힘을 주고
    나머지는 쭉 편 상태로 둔다. noise는 랜드마크에 섞을 흔들림(손 길이 대비 비율) —
    MediaPipe는 깊이(z)가 특히 부정확하므로 z에 3배로 준다.
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
        for k in range(1, 4):                    # PIP·DIP·TIP을 같은 방향으로 이어 붙인다
            lm[f[k]] = lm[f[0]] + d * PHALANX * k

    if noise:
        rng = np.random.default_rng(seed)
        sigma = noise * HAND_LEN
        lm = lm + rng.normal(0.0, sigma, lm.shape) * np.array([1.0, 1.0, 3.0])
    return lm


def deg_new(lm, finger=A.PINKY):
    return math.degrees(A._abduction_lateral(lm, finger))


def deg_old(lm, finger=A.PINKY):
    return math.degrees(A._abduction_planar(lm, finger))


class AbductionTest(unittest.TestCase):
    def test_straight_finger_reads_the_true_angle(self):
        """쭉 편 손가락: 넣은 벌림각이 그대로 나와야 한다."""
        for truth in (-30.0, -15.0, 0.0, 10.0, 25.0, 40.0):
            lm = make_hand(abduction_deg=truth, flexion_deg=0.0)
            self.assertAlmostEqual(deg_new(lm), truth, delta=1.0, msg=f"벌림 {truth}°")

    def test_new_and_old_agree_when_straight(self):
        """부호 규약이 바뀌지 않았는지 — 손가락을 편 상태에서는 두 방식이 같아야 한다."""
        for truth in (-25.0, -10.0, 10.0, 25.0):
            lm = make_hand(abduction_deg=truth, flexion_deg=0.0)
            self.assertAlmostEqual(deg_new(lm), deg_old(lm), delta=1.0,
                                   msg=f"벌림 {truth}°에서 새 방식과 옛 방식이 어긋남")

    def test_bending_does_not_make_the_new_formula_jumpy(self):
        """핵심 검증 — **굽힐수록 값이 불안정해지는가**.

        벌림은 0으로 고정하고 굽힘만 바꿔 가며, 같은 크기의 랜드마크 흔들림을 준다.
          · 옛 방식: 굽힐수록 손바닥 평면 그림자가 짧아져 같은 흔들림이 큰 각도로 증폭된다
                     → 많이 굽힌 구간의 흔들림 폭이 조금 굽힌 구간보다 훨씬 커야 한다.
          · 새 방식: 옆 성분만 보므로 굽힘과 거의 무관 → 흔들림이 훨씬 덜 커져야 한다.
        이게 실물에서 "새끼를 굽히기만 해도 좌우값이 움직이는" 증상의 원인이다.

        실측(이 테스트, 흔들림 0.4% 기준): 조금 굽힘 → 많이 굽힘
          옛 방식  1.10° → 10.52°  (9.5배 악화)
          새 방식  1.08° →  2.77°  (2.6배)
        ⚠️ 새 방식이 0배가 아닌 이유: '옆 방향' 축 자체를 손바닥 점들로 추정하는데, 그 점들의
           깊이(z)가 부정확해 축이 조금 기울고, 기운 축에는 손가락의 굽힘 성분이 조금 샌다.
           손바닥 5점 평면맞춤으로 바꿔 봐도 2.4배로 거의 그대로였다(코드 복잡도만 늘어 채택
           안 함). 남은 2.6배는 **치우침이 아니라 흔들림**이라 One Euro 필터가 상당히 걷어낸다.
        """
        def spread(method, flexions):
            vals = []
            for i, flex in enumerate(flexions):
                for k in range(40):
                    lm = make_hand(abduction_deg=0.0, flexion_deg=float(flex),
                                   seed=10_000 * flex + k, noise=0.004)
                    vals.append(method(lm))
            return float(np.std(vals))

        low, high = (0, 10, 20), (60, 70, 80)
        new_low, new_high = spread(deg_new, low), spread(deg_new, high)
        old_low, old_high = spread(deg_old, low), spread(deg_old, high)

        # 옛 방식은 많이 굽힌 구간에서 9.5배 나빠졌다(1.10° → 10.52°) — 재현 확인용.
        self.assertGreater(old_high, old_low * 5.0,
                           f"옛 방식이 굽힘에서 크게 나빠지는 현상이 재현되지 않음: "
                           f"조금굽힘 {old_low:.1f}° → 많이굽힘 {old_high:.1f}°")
        # 새 방식은 2.6배에서 멈춘다(1.08° → 2.77°). 0배가 아닌 이유는 아래 ⚠️ 참고.
        self.assertLess(new_high, new_low * 4.0,
                        f"새 방식이 기대보다 많이 나빠졌다: 조금굽힘 {new_low:.1f}° → "
                        f"많이굽힘 {new_high:.1f}°")
        self.assertLess(new_high, old_high * 0.4,
                        f"많이 굽힌 구간에서 새 방식이 최소 2.5배는 안정적이어야 한다: "
                        f"새 {new_high:.1f}° vs 옛 {old_high:.1f}°")

    def test_curling_shrinks_the_reading_instead_of_exploding(self):
        """벌린 채로 굽히면: 값이 **작아지기만** 하고 넣은 값을 넘지 않는다(문서화된 성질)."""
        truth = 30.0
        vals = [deg_new(make_hand(abduction_deg=truth, flexion_deg=float(f)))
                for f in range(0, 91, 10)]
        self.assertAlmostEqual(vals[0], truth, delta=1.0)
        for a, b in zip(vals, vals[1:]):
            self.assertLessEqual(b, a + 1e-6, f"굽힐수록 커지면 안 된다: {vals}")
        self.assertLessEqual(max(vals), truth + 1.0)
        self.assertLess(abs(vals[-1]), 2.0, "다 굽히면 0으로 수렴해야 한다")

    def test_middle_finger_is_always_zero(self):
        """중지는 자기 자신이 기준이라 항상 0 — 옛 방식과 같은 규약."""
        lm = make_hand(abduction_deg=20.0, flexion_deg=40.0, finger=A.MIDDLE)
        self.assertAlmostEqual(deg_new(lm, A.MIDDLE), 0.0, delta=1e-6)

    def test_every_finger_uses_the_same_rule(self):
        """검지·약지·새끼 모두 같은 식으로 계산된다(새끼만 특별 취급하지 않는다)."""
        for finger in (A.INDEX, A.RING, A.PINKY):
            lm = make_hand(abduction_deg=20.0, flexion_deg=0.0, finger=finger)
            self.assertAlmostEqual(deg_new(lm, finger), 20.0, delta=1.0,
                                   msg=f"손가락 {finger[0]}")

    def test_method_switch_selects_the_formula(self):
        """ABDUCTION_METHOD로 옛 방식을 다시 켤 수 있다(비교·재현용)."""
        lm = make_hand(abduction_deg=20.0, flexion_deg=60.0)
        original = A.ABDUCTION_METHOD
        try:
            A.ABDUCTION_METHOD = "planar"
            self.assertAlmostEqual(math.degrees(A._abduction(lm, A.PINKY)), deg_old(lm),
                                   delta=1e-9)
            A.ABDUCTION_METHOD = "lateral"
            self.assertAlmostEqual(math.degrees(A._abduction(lm, A.PINKY)), deg_new(lm),
                                   delta=1e-9)
        finally:
            A.ABDUCTION_METHOD = original


if __name__ == "__main__":
    unittest.main()
