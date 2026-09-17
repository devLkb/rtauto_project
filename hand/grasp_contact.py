# -*- coding: utf-8 -*-
"""손끝 센서 없이 "닿았다" 를 알아내기 — 판단 부분만 따로 떼어낸 것.

왜 이 파일이 있는가
-------------------
우리 손(DG-5F-M-R)에는 **손끝 힘·촉감 센서가 없다.** 그래서 "물체에 닿았다" 를 직접
읽을 수 없고, 관절마다 들어오는 세 가지 숫자로 **추정**해야 한다:

==================  ====================================  ==============
들어오는 것          닿으면 어떻게 되나                      단위
==================  ====================================  ==============
모터 전류            막히면 **올라간다**                     mA
시킨 각도 − 실제 각도  막히면 **벌어진다**                     도(deg)
관절 속도            막히면 **0에 가까워진다**                rpm
==================  ====================================  ==============

(단위 근거: `vision/dg5f/vendor/dgsdk-python/libs/DGDataTypes.h` 의
`ReceivedGripperData` 주석 — joint=degree, current=mA, velocity=rpm, temperature=°C)

가장 중요한 한 가지 — **"멈췄다" 만으로는 절대 안 된다**
--------------------------------------------------------
시킨 각도까지 **다 가서** 멈춘 관절도 속도가 0이고 전류도 낮다. 이걸 접촉으로 세면
아무것도 안 잡고도 "잡았다" 가 나온다. 그래서 **"시킨 데까지 못 갔다"(각도 오차)** 는
빼도 되는 조건이 아니라 **반드시 있어야 하는 조건**이다.

정리하면 접촉은 이렇게 생겼다:

    아직 갈 길이 남았는데(각도 오차 있음)  +  안 가고 있고(속도 ≈ 0)  +  힘은 쓰고 있다(전류 ↑)

기준값을 숫자 하나로 못 박지 않는 이유
--------------------------------------
무부하 전류는 **관절마다 다르고, 같은 관절이라도 각도마다 다르다**(중력·마찰·기구
간섭). "전류 200 mA 넘으면 접촉" 같은 상수 하나를 쓰면 엄지에서는 늘 켜지고 새끼에서는
절대 안 켜진다. 그래서:

1. `hand/measure_baseline.py` 로 **아무것도 안 잡은 채** 같은 속도로 쥐었다 폈다 하며
   관절별·각도구간별 전류의 **평균과 흔들림**을 잰다 → `config/dg5f_current_baseline.json`
2. 여기서는 **"그 기준에서 흔들림의 몇 배만큼 올라갔나"** 로만 판단한다.

⚠️ **기준표가 없으면 이 파일은 일부러 실패한다.** 짐작한 숫자로 실물을 조이는 것보다
   안 도는 편이 낫다.

이 파일에 하드웨어가 안 들어오는 이유
--------------------------------------
판단 규칙이 맞는지는 **손 없이도** 시험할 수 있어야 한다. 그래서 이 파일은 숫자를
받아 판정만 하고, 통신은 `hand/grasp_sequence.py` 가 맡는다. 시험은
`hand/tests/test_grasp_contact.py`.

설계 정본: [`docs/GRASP_CONTACT_DETECTION.md`](../docs/GRASP_CONTACT_DETECTION.md)
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (모든 기준값의 출처 — 원칙 1)

#: 관절 수. 손가락 5개 × 관절 4개.
N_JOINTS = 20

#: 손가락 하나가 쓰는 관절 번호. `vision/dg5f/dg5f_sdk_bridge.py` 의 채널 순서와 같다
#: (Motor N ↔ 채널 N-1, 하드웨어 설명서 §3.3.1).
FINGER_JOINTS = tuple(tuple(range(f * 4, f * 4 + 4)) for f in range(5))

#: 기준표를 만들 때 각도를 몇 도 단위로 나눠 담는가. 좁히면 정확하지만 재는 시간이 늘고
#: 구간마다 표본이 모자라진다.
BASELINE_BIN_DEG = 10.0

#: 기준표가 담고 있어야 하는 각도 범위(도). 이 밖은 "재 본 적 없음" 으로 처리한다.
BASELINE_MIN_DEG = -120.0
BASELINE_MAX_DEG = 120.0


class BaselineMissing(RuntimeError):
    """무부하 전류 기준표가 없거나 모자라다 — 접촉 감지를 시작하면 안 된다."""


def _bin_index(angle_deg: float) -> int:
    """각도를 기준표의 칸 번호로. 범위를 벗어나면 가장 가까운 칸으로 붙인다."""
    clamped = min(BASELINE_MAX_DEG, max(BASELINE_MIN_DEG, float(angle_deg)))
    return int((clamped - BASELINE_MIN_DEG) // BASELINE_BIN_DEG)


def _bin_count() -> int:
    return int((BASELINE_MAX_DEG - BASELINE_MIN_DEG) // BASELINE_BIN_DEG) + 1


@dataclass
class CurrentBaseline:
    """아무것도 안 잡았을 때의 전류 — 관절별·각도구간별 평균과 흔들림.

    `mean[j][b]` / `spread[j][b]` 는 관절 `j`, 각도구간 `b` 의 무부하 전류 평균(mA)과
    흔들림(mA). 재 본 적 없는 칸은 `count[j][b] == 0` 이고, 그런 칸은 **양옆에서 빌려
    쓰지 않는다** — 없는 것을 있는 척하면 조용히 틀린다.
    """

    mean: np.ndarray       # (20, bins) mA
    spread: np.ndarray     # (20, bins) mA
    count: np.ndarray      # (20, bins) 표본 수
    made_at: str = ""
    note: str = ""

    #: 한 칸을 믿으려면 최소 몇 번 재야 하는가.
    MIN_SAMPLES = 20

    @classmethod
    def empty(cls) -> "CurrentBaseline":
        bins = _bin_count()
        return cls(mean=np.zeros((N_JOINTS, bins)),
                   spread=np.zeros((N_JOINTS, bins)),
                   count=np.zeros((N_JOINTS, bins), dtype=np.int64))

    # --- 만들기 ---------------------------------------------------------
    @classmethod
    def from_samples(cls, angles_deg, currents_ma, made_at="", note=""):
        """잰 것들로 표를 만든다.

        `angles_deg`, `currents_ma` 는 각각 (표본수, 20) 모양이다.
        """
        angles = np.asarray(angles_deg, dtype=float).reshape(-1, N_JOINTS)
        currents = np.asarray(currents_ma, dtype=float).reshape(-1, N_JOINTS)
        if len(angles) != len(currents):
            raise ValueError("각도와 전류의 표본 수가 다르다")
        out = cls.empty()
        bins = _bin_count()
        for j in range(N_JOINTS):
            idx = np.asarray([_bin_index(a) for a in angles[:, j]], dtype=int)
            for b in range(bins):
                sel = currents[idx == b, j]
                out.count[j, b] = len(sel)
                if len(sel) == 0:
                    continue
                out.mean[j, b] = float(np.mean(sel))
                # 흔들림은 표준편차. 표본이 하나뿐이면 0이 되는데, 그런 칸은
                # count 로 걸러지므로 여기서 따로 손대지 않는다.
                out.spread[j, b] = float(np.std(sel))
        out.made_at = made_at
        out.note = note
        return out

    # --- 저장·읽기 ------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "made_at": self.made_at,
            "note": self.note,
            "bin_deg": BASELINE_BIN_DEG,
            "min_deg": BASELINE_MIN_DEG,
            "max_deg": BASELINE_MAX_DEG,
            "unit": {"angle": "deg", "current": "mA"},
            "mean": self.mean.tolist(),
            "spread": self.spread.tolist(),
            "count": self.count.tolist(),
        }

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, path=None) -> "CurrentBaseline":
        """기준표를 읽는다. 없으면 **왜 없는지와 어떻게 만드는지**를 알려주고 실패한다."""
        path = Path(path) if path else (REPO_ROOT / cfg.DG5F_BASELINE_FILE)
        if not path.exists():
            raise BaselineMissing(
                "무부하 전류 기준표가 없다: {}\n"
                "  이 표가 없으면 '전류가 평소보다 올라갔다' 를 판단할 수 없다.\n"
                "  만드는 법 (터미널 1, PowerShell, 리포 루트):\n"
                "      .vision/Scripts/Activate.ps1\n"
                "      python hand/measure_baseline.py\n"
                "  손에 아무것도 쥐어 주지 말고, 손 앞을 비워 둔 채로 돌려야 한다.".format(path))
        raw = json.loads(path.read_text(encoding="utf-8"))
        if abs(float(raw.get("bin_deg", 0)) - BASELINE_BIN_DEG) > 1e-9:
            raise BaselineMissing(
                "기준표의 각도 칸 크기가 지금 코드와 다르다 ({} vs {}) — 다시 재라: {}".format(
                    raw.get("bin_deg"), BASELINE_BIN_DEG, path))
        return cls(mean=np.asarray(raw["mean"], dtype=float),
                   spread=np.asarray(raw["spread"], dtype=float),
                   count=np.asarray(raw["count"], dtype=np.int64),
                   made_at=str(raw.get("made_at", "")),
                   note=str(raw.get("note", "")))

    # --- 쓰기 -----------------------------------------------------------
    def threshold_ma(self, joint: int, angle_deg: float):
        """이 관절이 이 각도에서 **접촉으로 볼 전류(mA)**. 못 재 본 칸이면 None.

        기준 = 무부하 평균 + (흔들림 × 배수), 단 최소 바닥값 이상.
        """
        b = _bin_index(angle_deg)
        if self.count[joint, b] < self.MIN_SAMPLES:
            return None
        rise = max(cfg.DG5F_CONTACT_CURRENT_SIGMA * float(self.spread[joint, b]),
                   cfg.DG5F_CONTACT_CURRENT_FLOOR_MA)
        return float(self.mean[joint, b]) + rise

    def coverage(self, joints=None):
        """쓸 만한 칸이 전체의 몇 퍼센트인가. 재기가 충분했는지 보는 용도."""
        rows = range(N_JOINTS) if joints is None else joints
        cnt = self.count[list(rows)]
        return float((cnt >= self.MIN_SAMPLES).sum()) / float(cnt.size)


@dataclass
class JointReading:
    """한 순간 한 관절의 상태."""
    angle_deg: float
    target_deg: float
    current_ma: float
    velocity_rpm: float


@dataclass
class JointVerdict:
    """한 관절에 대한 판정과 **그 이유**. 왜 그렇게 봤는지 남겨야 나중에 고칠 수 있다."""
    contact: bool
    ticks: int
    current_ma: float
    threshold_ma: Optional[float]
    pos_err_deg: float
    velocity_rpm: float
    reason: str


@dataclass
class ContactState:
    """손 전체 판정."""
    per_joint: List[JointVerdict]
    fingers_touching: List[int] = field(default_factory=list)
    enough: bool = False
    over_current: List[int] = field(default_factory=list)
    unmeasured: List[int] = field(default_factory=list)

    @property
    def n_fingers(self) -> int:
        return len(self.fingers_touching)


class ContactDetector:
    """관절 상태를 계속 받아 "어느 손가락이 닿았나" 를 알려준다.

    한 번 넘었다고 바로 믿지 않는다 — **연속으로 몇 번** 조건을 만족해야 확정한다
    (`DG5F_CONTACT_HOLD_TICKS`). 전류는 물체에 닿는 순간뿐 아니라 방향이 바뀔 때도
    튀기 때문이다.

    한 번 닿았다고 본 관절은 **그 상태를 유지한다**(`latch`). 잡은 뒤 조이기를 멈추면
    전류가 다시 내려가는데, 그때 "안 닿았다" 로 되돌아가면 잡고 있는데도 놓쳤다고
    판단해 버린다. 되돌리는 것은 `reset()` 으로 명시적으로만 한다.
    """

    def __init__(self, baseline: CurrentBaseline, min_fingers=None, hold_ticks=None):
        self.baseline = baseline
        self.min_fingers = int(cfg.DG5F_CONTACT_MIN_FINGERS
                               if min_fingers is None else min_fingers)
        self.hold_ticks = int(cfg.DG5F_CONTACT_HOLD_TICKS
                              if hold_ticks is None else hold_ticks)
        self._ticks = [0] * N_JOINTS
        self._latched = [False] * N_JOINTS

    def reset(self) -> None:
        self._ticks = [0] * N_JOINTS
        self._latched = [False] * N_JOINTS

    def update(self, readings: Sequence[JointReading]) -> ContactState:
        """상태 한 묶음을 넣고 판정을 받는다."""
        if len(readings) != N_JOINTS:
            raise ValueError("관절 {}개가 와야 하는데 {}개가 왔다".format(
                N_JOINTS, len(readings)))

        verdicts: List[JointVerdict] = []
        unmeasured: List[int] = []
        over: List[int] = []

        for j, r in enumerate(readings):
            thr = self.baseline.threshold_ma(j, r.angle_deg)
            err = float(r.target_deg) - float(r.angle_deg)
            pushing = abs(err) >= cfg.DG5F_CONTACT_POS_ERR_DEG
            still = abs(float(r.velocity_rpm)) <= cfg.DG5F_CONTACT_VEL_RPM
            loaded = thr is not None and float(r.current_ma) >= thr

            if abs(float(r.current_ma)) >= cfg.DG5F_CURRENT_LIMIT_MA:
                over.append(j)

            if thr is None:
                unmeasured.append(j)
                reason = "이 각도({:.0f}도)는 기준표에 없다 — 판단 못 함".format(r.angle_deg)
                self._ticks[j] = 0
            elif loaded and pushing and still:
                self._ticks[j] += 1
                reason = "전류 {:.0f}≥{:.0f} mA, 오차 {:.1f}도, 속도 {:.1f} rpm".format(
                    r.current_ma, thr, err, r.velocity_rpm)
            else:
                self._ticks[j] = 0
                missing = []
                if not loaded:
                    missing.append("전류 안 올라감({:.0f}<{:.0f})".format(r.current_ma, thr))
                if not pushing:
                    # 시킨 데까지 다 갔다 = 막힌 게 아니다. 가장 흔한 오판 원인.
                    missing.append("시킨 각도에 도달함(오차 {:.1f}도)".format(err))
                if not still:
                    missing.append("아직 움직임({:.1f} rpm)".format(r.velocity_rpm))
                reason = " / ".join(missing)

            if self._ticks[j] >= self.hold_ticks:
                self._latched[j] = True

            verdicts.append(JointVerdict(
                contact=self._latched[j], ticks=self._ticks[j],
                current_ma=float(r.current_ma), threshold_ma=thr,
                pos_err_deg=err, velocity_rpm=float(r.velocity_rpm), reason=reason))

        fingers = [f for f, joints in enumerate(FINGER_JOINTS)
                   if any(verdicts[j].contact for j in joints)]
        return ContactState(per_joint=verdicts, fingers_touching=fingers,
                            enough=len(fingers) >= self.min_fingers,
                            over_current=over, unmeasured=unmeasured)


def describe(state: ContactState) -> str:
    """사람이 읽을 한 줄 요약."""
    names = ("엄지", "검지", "중지", "약지", "새끼")
    touched = ", ".join(names[f] for f in state.fingers_touching) or "없음"
    tail = ""
    if state.over_current:
        tail += "  ⚠️ 전류 한계 초과 관절 {}".format(state.over_current)
    if state.unmeasured:
        tail += "  ⚠️ 기준표에 없는 각도의 관절 {}개".format(len(state.unmeasured))
    return "닿은 손가락 {}개 ({}){}".format(state.n_fingers, touched, tail)
