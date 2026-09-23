# -*- coding: utf-8 -*-
"""**손목 카메라로 물체를 찾아 팔이 그 앞까지 스스로 간다** — 전체를 한 번에 돌리는 도구.

이 파일이 하는 일 (11월 시연의 한 줄 경로)
-------------------------------------------
::

    D405 손목 카메라로 사진 찍기
        ↓  ① 물체 찾기                    vision/d405/yolo_assist.py
        ↓  ② 거리값으로 위치·방향 재기      vision/d405/object_pose.py
        ↓  ③ 카메라 → 팔 끝 → 로봇 밑동     arm/eye_in_hand.py
        ↓  ④ 물체 앞에 설 자리 정하기       arm/pregrasp_planner.py
        ↓  ⑤ 관절 각도 풀고 움직이기        arm/prepose_to_joints.py
    물체 앞에 손을 벌린 채로 서서 멈춤

🛑 **잡지 않는다.** 물체 앞에 서는 데까지가 이번 목표다. 쥐기·들어올리기·옮기기는
다음 단계이고 여기에 없다.

이 파일 자체는 계산을 하나도 하지 않는다
-----------------------------------------
위 다섯 단계는 전부 각자의 파일에 있다. 여기는 **순서대로 부르고, 사람이 볼 수 있게
찍어 주고, 위험하면 멈추는** 일만 한다. 계산을 여기에 넣지 않는 이유는, 그러면
카메라 없이는 아무것도 시험할 수 없게 되기 때문이다.

안전 — 움직이기 전에 통과해야 하는 것
-------------------------------------
1. **손목 카메라 장착값 검증** (`--move` 일 때만). 아직 실물로 안 쟀으면 **안 움직인다**
   (`config/d405_tool_camera.json` 의 `status` 가 `VALIDATED` 가 되기 전까지).
   화면에 보여 주는 것은 그대로 된다.
2. **물체 쪽 검사** — `arm/pregrasp_planner.check_target()` 이 전부 본다
   (숫자가 아닌 값, 거리값 부족, 확신 부족, 크기, 작업 공간, 한 번에 움직이는 거리).
3. **사람 승인** — `--yes` 를 주지 않으면 매번 물어본다.
4. **관측 나이** — 사진을 찍고 나서 이동 직전까지 너무 오래 걸렸으면
   `ArmMover.move_to()` 가 스스로 거절한다(`RTAUTO_MAX_POSE_AGE_SEC`, 기본 10초).

돌리는 법
---------

**터미널 1 (bash, 리포 루트, 가짜 팔 URSim)** — 먼저 띄워 둔 채로 다음 터미널로 간다::

    bash arm/run_ursim.sh

**터미널 1 (PowerShell, 리포 루트, 가짜 팔 URSim)**::

    arm/run_ursim.ps1

**터미널 2 (bash, 리포 루트, 보기만 — 팔도 카메라 이동도 없다)**::

    source vision/.vision/bin/activate
    python arm/approach_object.py --look

**터미널 2 (PowerShell, 리포 루트, 보기만)**::

    vision/.vision/Scripts/Activate.ps1
    python arm/approach_object.py --look

`--look` 은 **카메라만** 쓴다. 팔에 연결하지 않으므로 팔 끝 자세를 모르고, 따라서
로봇 밑동 기준 좌표도 못 낸다 — 카메라 기준까지만 보여 준다.

**터미널 2 — 팔에 연결해서 로봇 좌표까지 (아직 안 움직인다)**::

    python arm/approach_object.py --plan --ip

**터미널 2 — 실제로 움직이기 (가짜 팔 URSim 에 먼저 할 것)**::

    python arm/approach_object.py --move --ip

`--ip` 를 값 없이 주면 `.env` 의 `RTAUTO_UR_IP`(기본 127.0.0.1 = 로컬 URSim)를 쓴다.
`--watch` 를 붙이면 **물체를 옮길 때마다 다시 찾아** 반복한다(시연 시나리오 7~9단계).

무엇이 보이면 정상인가
----------------------
::

    --- 1번째 ---
    고른 이유   : 앞의 1개가 거절돼서 2번째 후보로 넘어왔다(0.234 m)
    건너뜀      : #2 bottle 83% (0.220 m) — 거절(...) — 물체가 작업 공간 상자 밖이다 ...
    찾은 것     : #1 cup 확신 86%
    Camera XYZ  : (+0.0123, -0.0456, +0.2340) m
    TCP XYZ     : (+0.0123, -0.0456, +0.2340) m
    Base XYZ    : (+0.4512, +0.1008, +0.2010) m
    물체 모습   : 서 있음 (기운 각도 4도), 크기 7.2x7.0x11.8 cm
    설 자리     : (+0.3012, +0.0308, +0.1993) m
    → 팔 이동: 도착 확인됨 — ... (최대 관절 오차 0.412°)

물체를 못 찾았거나 안전 검사에 걸리면 **자세를 만들지 않고 이유를 찍는다.**
"팔이 안 움직였다"가 아니라 **왜 안 움직였는지**가 나와야 정상이다.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "vision" / "d405"))

from config import rtauto_config as cfg  # noqa: E402
from arm import eye_in_hand  # noqa: E402
from arm.pregrasp_planner import PreGraspPlan, UP_BASE, plan_pregrasp  # noqa: E402
from arm.target_selection import Candidate, Selection, TargetPicker  # noqa: E402

from object_pose import FRAME_BASE, FRAME_CAMERA, ObjectPose, from_object_cloud  # noqa: E402


@dataclass
class Observation:
    """한 번 본 결과. **카메라 기준**이다 — 아직 로봇 좌표가 아니다."""

    #: 사진을 찍은 시각(초). 이 값이 "관측이 오래됐나" 판정의 근거가 된다.
    stamp: float
    #: 고른 물체 하나(카메라 기준). 못 골랐으면 None. `run_once()` 가 고른 뒤 채운다.
    target: Optional[ObjectPose] = None
    #: 고른 것 말고 보인 후보들 — 사람이 "다른 걸 골랐어야 하나" 를 보려는 것.
    others: Tuple[ObjectPose, ...] = ()
    #: 카메라·인식 쪽에서 남긴 한 줄.
    note: str = ""
    #: 잡으러 갈 후보 전부(번호 포함). 여기서 `arm/target_selection.py` 규칙으로 고른다.
    candidates: Tuple[Candidate, ...] = ()
    #: 고른 결과 — 왜 골랐는지, 무엇을 왜 건너뛰었는지.
    selection: Optional[Selection] = None
    # --- 아래는 **화면에 그리기 위해서만** 들고 다닌다(--show). 계산에는 안 쓴다 ---
    #: 색 사진(BGR). 카메라를 안 썼으면 None.
    color: Optional[np.ndarray] = None
    #: 합친 거리 사진(m).
    depth_m: Optional[np.ndarray] = None
    #: 초점거리·중심(RealSense intrinsics).
    intr: Optional[object] = None
    #: YOLO 가 찾은 것 전부(중복 정리 뒤).
    dets: Tuple = ()
    #: 고른 물체의 점 덩어리 — 화면에서 **어느 것을 골랐는지** 표시하려고 들고 있다.
    target_cloud: Optional[object] = None


# ---------------------------------------------------------------------------
# ① · ② 보기 — 카메라가 있어야 한다
# ---------------------------------------------------------------------------
def observe(stream, detector, frames: int, near: float, far: float,
            want_name: Optional[str] = None,
            picker: Optional[TargetPicker] = None) -> Observation:
    """사진을 찍어 **잡으러 갈 후보를 전부** 모은다. 고르는 것은 `run_once()` 가 한다.

    카메라와 YOLO 는 바깥에서 열어 넘긴다. `--watch` 로 반복할 때 카메라를 매번 여닫으면
    준비 장면 때문에 느려지고, 시간 다듬기가 매번 처음부터 다시 차기 때문이다.

    후보: **YOLO 가 찾은 것만**(`is_grasp_candidate`). `want_name` 을 주면 그 이름이
    들어간 것만 본다 — 콤마로 여러 이름을 나열하면(예: "cup,bottle") **그중 하나라도
    들어간 것**을 후보로 본다. `picker` 를 주면 후보마다 번호를 붙인다(같은 물체 = 같은 번호).
    """
    import depth_stack
    from segment_objects import is_grasp_candidate
    from yolo_assist import _to_points, find_objects_hybrid

    stamp = time.time()
    got, intr = stream.frames(count=frames, warmup=0)
    if not got:
        return Observation(stamp, None, note="카메라에서 장면이 안 들어왔다.")
    depth_m, color = got[-1]
    if color is None:
        return Observation(stamp, None, note="색 사진이 안 들어왔다(색 스트림 확인).")
    if len(got) > 1:
        depth_m, st = depth_stack.stack([d for d, _ in got])
        note = st["message"]
    else:
        note = "1장만 사용 — 값 있는 화소 {:.0%}".format(float((depth_m > 0).mean()))

    pts, pix = _to_points(depth_m, intr)
    objs, found_note, dets = find_objects_hybrid(
        pts, pix, color, detector, near, far,
        depth_shape=depth_m.shape, intr=intr, geometry_fallback=False)
    note = found_note + " / " + note

    clouds = [o for o in objs if is_grasp_candidate(o)]
    if picker is not None:
        picker.track(clouds)      # 이름으로 거르기 전에 — 거른 것도 번호는 이어져야 한다
    # 점 덩어리를 같이 들고 다닌다 — 화면에 "어느 것을 골랐는지" 그리려면 필요하다.
    cands = [Candidate(from_object_cloud(o, frame=FRAME_CAMERA), o,
                       int(getattr(o, "track_id", -1)))
             for o in clouds]
    if want_name:
        # 콤마로 여러 이름을 주면 그중 하나라도 라벨에 들어가면 후보로 본다
        # (예: "cup,bottle" — 컵이든 병이든 둘 다 허용, 나머지는 제외).
        wanted = [w.strip().lower() for w in want_name.split(",") if w.strip()]
        cands = [c for c in cands if any(w in c.pose.label.lower() for w in wanted)]
    return Observation(stamp, note=note, candidates=tuple(cands),
                       color=color, depth_m=depth_m, intr=intr, dets=tuple(dets))


def observe_fake(position_cam, size_m=(0.06, 0.06, 0.13), label="fake_cup",
                 confidence=0.9, seed=0) -> Observation:
    """**카메라 없이** 가짜 물체를 하나 지어낸다 — 팔 쪽 절반만 확인할 때 쓴다.

    🛑 **이건 시험용이다. 실제로 본 것이 아니다.** 카메라가 아직 없거나 안 꽂혀
    있을 때, 그 뒤 단계(좌표 옮기기 → 설 자리 → 관절각 → 실제 이동)가 URSim 에서
    도는지 확인하려고 만들었다. 화면에도 `fake_` 로 표시되고, 실물 이동 관문
    (`require_validated_mount_for_physical_move`)은 이 경로에서도 그대로 걸린다 —
    가짜 물체로 실물을 움직일 수는 없다.

    `position_cam` 은 **카메라 기준** 위치 (x, y, z) m 다. 손목 카메라가 그 자리에
    물체를 봤다고 치는 것이다.
    """
    from object_pose import estimate_pose

    rng = np.random.default_rng(seed)
    pts = np.asarray(position_cam, dtype=float) + (
        rng.random((400, 3)) - 0.5) * np.asarray(size_m, dtype=float)
    pose = estimate_pose(pts, frame=FRAME_CAMERA, label=label, confidence=confidence)
    return Observation(time.time(), candidates=(Candidate(pose),),
                       note="🛑 가짜 물체다(--fake-object) — 카메라를 안 썼다.")


# ---------------------------------------------------------------------------
# ③ 카메라 → 팔 끝 → 로봇 밑동
# ---------------------------------------------------------------------------
def to_base(pose_cam: ObjectPose, tool0_pose6: Sequence[float],
            mount=None) -> Tuple[ObjectPose, np.ndarray, np.ndarray, Optional[str]]:
    """카메라 기준 물체 → **로봇 밑동 기준** 물체. 중간 단계도 같이 돌려준다.

    돌려주는 것: `(밑동 기준 물체, 팔 끝 기준 위치, 밑동 기준 위치, 경고 또는 None)`.
    세 단계를 따로 돌려주는 이유는 좌표가 틀렸을 때 **어디서 틀렸는지** 보기 위해서다.
    """
    mount = mount or eye_in_hand.CameraMount.from_config()
    _cam, in_tcp, in_base, warn = eye_in_hand.points_camera_tcp_base(
        [pose_cam.position], tool0_pose6, mount)
    transform = eye_in_hand.camera_to_base(tool0_pose6, mount)
    return pose_cam.transformed(transform, FRAME_BASE), in_tcp[0], in_base[0], warn


def read_tool0_pose(ip: str):
    """팔에서 **tool0 자세**를 읽는다. 관절각으로 직접 계산한다.

    🛑 `getActualTCPPose()` 를 쓰지 않는 이유는 `arm/eye_in_hand.camera_to_base()`
    설명 참고 — 그 값은 컨트롤러에 설정된 활성 TCP 기준이라 카메라 장착값과 섞이면
    조용히 어긋난다. 읽는 일 자체는 `eye_in_hand.read_tool0_pose()` 가 정본이다.
    """
    tool0_pose, q6, _active_tcp_pose = eye_in_hand.read_tool0_pose(ip)
    return tool0_pose, q6


# ---------------------------------------------------------------------------
# 사람이 보는 표
# ---------------------------------------------------------------------------
def _xyz(vec) -> str:
    return "({:+.4f}, {:+.4f}, {:+.4f}) m".format(*[float(v) for v in vec])


def report(obs: Observation,
           pose_base: Optional[ObjectPose] = None,
           in_tcp=None, in_base=None,
           plan: Optional[PreGraspPlan] = None,
           warn: Optional[str] = None) -> None:
    """단계마다의 값을 **전부** 찍는다. 한 줄이라도 빠지면 어디서 틀렸는지 못 찾는다."""
    print("카메라/인식 : {}".format(obs.note or "-"))
    sel = obs.selection
    if sel is not None:
        print("고른 이유   : {}".format(sel.why))
        for a in sel.rejected:
            print("건너뜀      : {} ({:.3f} m) — {}".format(
                a.candidate.name(), a.candidate.distance_m, a.reason.replace("\n", " / ")))
    if obs.target is None:
        if not obs.candidates:
            print("찾은 것     : 없음 — 물체를 못 찾았다(또는 잡을 후보가 아니었다).")
        elif sel is not None and sel.untried:
            print("같이 보인 것: {}".format(", ".join(c.name() for c in sel.untried)))
        return

    t = obs.target
    chosen = sel.chosen if sel is not None else None
    print("찾은 것     : {}{} 확신 {:.0%}{}".format(
        "#{} ".format(chosen.track_id) if chosen is not None and chosen.track_id > 0 else "",
        t.label or "이름없음", t.confidence,
        "  (거리값이 모자라 테두리로 어림잡음)" if t.estimated else ""))
    print("Camera XYZ  : {}".format(_xyz(t.position)))
    if in_tcp is not None:
        print("TCP XYZ     : {}".format(_xyz(in_tcp)))
    if in_base is not None:
        print("Base XYZ    : {}".format(_xyz(in_base)))
    shown = pose_base or t
    print("물체 크기   : {:.1f}x{:.1f}x{:.1f} cm, 점 {}개".format(
        shown.extents[0] * 100, shown.extents[1] * 100, shown.extents[2] * 100,
        shown.n_points))
    if pose_base is not None:
        # 🛑 **놓인 모습은 로봇 밑동 기준에서만 말할 수 있다.** 카메라 기준 좌표는
        #    Z가 앞쪽(거리)이라 "위쪽"이 다르다 — 2026-09-22 실물 D405 에서 똑바로
        #    서 있는 병이 "누워 있음(81도)"으로 나와 발견했다. 팔에 연결하지 않아
        #    밑동 기준 값이 없으면 **판정하지 않는다.**
        print("물체 모습   : {} (기운 각도 {:.0f}도)".format(
            pose_base.posture(UP_BASE), pose_base.tilt_deg(UP_BASE)))
    else:
        print("물체 모습   : 아직 모름 — 카메라 기준이라 어느 쪽이 위인지 알 수 없다"
              "(팔에 연결하면 나온다).")
    if not shown.orientation_valid:
        print("              ⚠️ 방향을 하나로 정할 수 없는 모양이다 — 위치만 쓴다.")
    if sel is not None and sel.untried:
        print("같이 보인 것: {}".format(", ".join(c.name() for c in sel.untried)))
    elif sel is None and obs.others:
        print("같이 보인 것: {}".format(", ".join(
            "{} {:.0%}".format(o.label or "이름없음", o.confidence) for o in obs.others)))
    if warn:
        print("장착값 경고 : {}".format(warn))
    if plan is not None:
        print(plan.describe())


# ---------------------------------------------------------------------------
# 카메라 관점으로 보기 (--show)
# ---------------------------------------------------------------------------
# 🛑 **왜 창을 따로 띄우지 않고 여기 넣었나.** D405 는 한 번에 **한 프로그램만** 열 수
#    있다. `vision/d405/yolo_assist.py --live` 를 옆 터미널에 같이 띄우면, 나중에 뜬
#    쪽이 카메라를 **하드웨어 재설정**해 버려서 먼저 뜬 쪽이 조용히 죽는다(2026-09-22
#    실측). 그래서 "보기"는 같은 프로그램 안에 있어야 한다.
#
# ⚠️ 창 **제목**만 영어로 쓴다 — OpenCV 가 창 제목에 한글을 못 넣어 깨진다. 그림 **안**의
#    글자는 `view_d405.put_lines/put_labels` 가 PIL 로 그리므로 한글이 제대로 나온다.
VIEW_WINDOW = "D405 view  (left: camera / right: distance)"


def _clip(text: str, n: int = 60) -> str:
    """화면 한 줄에 들어가게 자른다 — 전체 문장은 터미널에 찍힌다."""
    text = str(text).replace("\n", " / ")
    return text if len(text) <= n else text[:n - 1] + "…"


def draw_view(obs: "Observation", plan: Optional[PreGraspPlan],
              near: float, far: float):
    """지금 카메라가 보는 것을 **한 장으로** 그린다. 못 그리면 None.

    왼쪽은 색 사진 + YOLO 가 찾은 테두리, 오른쪽은 거리 사진이다.
    **고른 물체는 굵은 초록 테두리와 "← 이걸로 간다"** 로 다른 것과 구분한다 —
    여러 개가 보일 때 어느 것으로 가는지가 화면에서 바로 보여야 한다.
    """
    if obs.color is None or obs.depth_m is None or obs.intr is None:
        return None
    import cv2
    from view_d405 import colorize, put_labels, put_lines

    left = cv2.resize(obs.color, (640, 480))
    sx, sy = 640 / obs.color.shape[1], 480 / obs.color.shape[0]
    for d in obs.dets:
        x1, y1, x2, y2 = [int(v) for v in d.box]
        cv2.rectangle(left, (int(x1 * sx), int(y1 * sy)),
                      (int(x2 * sx), int(y2 * sy)), (0, 170, 255), 2)

    dw, dh = obs.depth_m.shape[1], obs.depth_m.shape[0]

    def _box(cloud):
        z = max(float(cloud.center[2]), 1e-6)
        u = (float(cloud.center[0]) * obs.intr.fx / z + obs.intr.ppx)
        v = (float(cloud.center[1]) * obs.intr.fy / z + obs.intr.ppy)
        half_w = int(float(cloud.size[0]) * obs.intr.fx / z * 0.5 * 640 / dw)
        half_h = int(float(cloud.size[1]) * obs.intr.fy / z * 0.5 * 480 / dh)
        return int(u * 640 / dw), int(v * 480 / dh), half_w, half_h

    labels = []
    sel = obs.selection
    if sel is not None:
        # 건너뛴 것은 빨강, 시도 안 한 것은 번호만 — 무엇을 왜 안 골랐는지 화면에서 보이게.
        for a in sel.rejected:
            if a.candidate.cloud is None:
                continue
            cu, cv_, hw, hh = _box(a.candidate.cloud)
            cv2.rectangle(left, (cu - hw, cv_ - hh), (cu + hw, cv_ + hh), (0, 0, 255), 2)
            labels.append((cu - hw, cv_ - hh - 22, a.candidate.name() + " 건너뜀", (0, 0, 255)))
        for c in sel.untried:
            if c.cloud is None:
                continue
            cu, cv_, hw, hh = _box(c.cloud)
            labels.append((cu - hw, cv_ - hh - 22, c.name(), (0, 170, 255)))
    if obs.target_cloud is not None:
        cu, cv_, half_w, half_h = _box(obs.target_cloud)
        cv2.rectangle(left, (cu - half_w, cv_ - half_h), (cu + half_w, cv_ + half_h),
                      (0, 255, 0), 3)
        cv2.circle(left, (cu, cv_), 6, (0, 0, 255), -1)
        tag = sel.chosen.name() + " " if sel is not None and sel.chosen is not None else ""
        labels.append((cu + half_w + 8, cv_, tag + "← 이걸로 간다", (0, 255, 0)))
    if labels:
        left = put_labels(left, labels, size=20)

    right = cv2.resize(colorize(obs.depth_m, near, far), (640, 480),
                       interpolation=cv2.INTER_NEAREST)

    lines = []
    t = obs.target
    if t is None:
        lines.append("고른 물체 없음 — " + (sel.why if sel is not None
                                           else "잡으러 갈 후보를 못 찾았다"))
    else:
        lines.append("고른 것: {} 거리 {:.3f} m".format(
            sel.chosen.name() if sel is not None and sel.chosen is not None
            else "{} {:.0%}".format(t.label or "이름없음", t.confidence), t.position[2]))
        lines.append("카메라 기준 ({:+.3f}, {:+.3f}, {:+.3f}) m / 크기 {:.1f}x{:.1f}x{:.1f} cm".format(
            *t.position, *[e * 100 for e in t.extents]))
        if sel is not None:
            lines.append("고른 이유: " + _clip(sel.why))
    if sel is not None:
        for a in sel.rejected:
            lines.append("건너뜀 {}: {}".format(a.candidate.name(), _clip(a.reason)))
    if plan is not None:
        lines.append(plan.prepose.reason if not plan.accepted
                     else "설 자리(로봇 기준) ({:+.3f}, {:+.3f}, {:+.3f}) m — {} 다가간다".format(
                         *plan.prepose.palm_position, plan.approach_style))
    left = put_lines(left, lines)

    return np.hstack([left, right])


def show_view(obs: "Observation", plan: Optional[PreGraspPlan],
              near: float, far: float, hold: bool) -> None:
    """창에 띄운다. `hold` 면 아무 키나 누를 때까지 기다린다(한 번만 돌릴 때)."""
    frame = draw_view(obs, plan, near, far)
    if frame is None:
        return
    import cv2
    cv2.imshow(VIEW_WINDOW, frame)
    cv2.waitKey(0 if hold else 1)


# ---------------------------------------------------------------------------
# 한 번 돌리기
# ---------------------------------------------------------------------------
def _show(args, obs, plan) -> None:
    """`--show` 일 때만 창을 갱신한다. 반복(--watch)이 아니면 키를 누를 때까지 기다린다."""
    if not getattr(args, "show", False):
        return
    if args.fake_object is not None:
        return          # 가짜 물체는 사진이 없다 — 보여 줄 것이 없다
    show_view(obs, plan, args.near, args.far, hold=not args.watch)


def _apply_selection(obs: Observation, sel: Selection) -> None:
    """고른 결과를 `obs` 의 표시용 칸에 옮겨 적는다."""
    obs.selection = sel
    obs.target = sel.chosen.pose if sel.chosen is not None else None
    obs.target_cloud = sel.chosen.cloud if sel.chosen is not None else None
    obs.others = tuple(c.pose for c in sel.others)


def run_once(stream, detector, args, mover=None,
             picker: Optional[TargetPicker] = None) -> Tuple[Observation, Optional[PreGraspPlan]]:
    """보기 → 고르기 → 좌표 옮기기 → 설 자리 정하기 → (원하면) 움직이기. **한 바퀴.**

    `picker` 는 `--watch` 동안 "아까 고른 물체" 를 기억한다. 안 주면 매번 새로 고른다.
    """
    picker = picker or TargetPicker()
    if args.fake_object is not None:
        obs = observe_fake(args.fake_object)
    else:
        obs = observe(stream, detector, args.frames, args.near, args.far, args.target,
                      picker=picker)
    if not obs.candidates:
        # 아무것도 안 보인 장면도 "아까 고른 것이 안 보였다" 로 센다 — 안 세면 물체를 치운
        # 뒤 새 물체가 나타날 때마다 기다리기가 처음부터 다시 시작된다.
        _apply_selection(obs, picker.pick(()))
        report(obs)
        _show(args, obs, None)
        return obs, None

    if args.ip is None:
        # 팔에 연결 안 함 — 팔 끝 자세를 모르니 로봇 좌표를 못 낸다. 아는 척하지 않는다.
        # 닿는지 검사할 방법도 없으므로 순서상 1등을 고르기만 한다.
        _apply_selection(obs, picker.pick(obs.candidates))
        report(obs)
        print("→ 팔에 연결하지 않아 로봇 밑동 기준 좌표를 못 낸다(--ip 를 줄 것). "
              "카메라 기준까지만 확인했다.")
        _show(args, obs, None)
        return obs, None

    tool0_pose, _q6 = read_tool0_pose(cfg.resolve_ur_ip(args.ip))
    can_solve = mover is not None and mover.can_command
    tried = {}

    def evaluate(cand: Candidate) -> Tuple[bool, str]:
        """이 후보로 **갈 수 있는가** — 안전 검사와 관절 각도 풀기까지. 움직이지는 않는다."""
        pose_base, in_tcp, in_base, warn = to_base(cand.pose, tool0_pose)
        plan = plan_pregrasp(pose_base, stamp_capture=obs.stamp,
                             current_tool0_xyz=tool0_pose[:3])
        # 🛑 설 자리가 계산상 나왔다고 팔이 거기 닿는다는 뜻은 아니다(안전 범위·IK 해
        # 존재·관절 한계). 그래서 **관절 각도를 실제로 풀어 본 뒤에** 고른다 — 못 풀리면
        # 다음 후보로 넘어간다.
        checked = mover.plan(plan.prepose) if plan.accepted and can_solve else None
        tried[id(cand)] = (pose_base, in_tcp, in_base, warn, plan, checked)
        if not plan.accepted:
            return False, plan.describe()
        if checked is not None and not checked.feasible:
            return False, "관절 각도가 안 풀린다 — " + checked.describe()
        return True, ""

    sel = picker.pick(obs.candidates, evaluate)
    _apply_selection(obs, sel)

    if sel.chosen is None:
        report(obs)
        _show(args, obs, None)
        first = tried.get(id(sel.attempts[0].candidate)) if sel.attempts else None
        first_plan = first[4] if first is not None else None
        # 🛑 1등이 **관절각에서** 거절됐으면 그 설 자리 계산은 "받아들임" 이다 — 그걸
        #    파일로 남기거나 돌려주면 거절 기록이 "갈 수 있다" 로 읽힌다. 설 자리 계산에서
        #    거절된 경우만 거절 기록으로 쓴다.
        if first_plan is not None and first_plan.accepted:
            first_plan = None
        if args.pose_json and first_plan is not None:
            Path(args.pose_json).write_text(first_plan.prepose.to_json(indent=2),
                                            encoding="utf-8")
            print("→ 1등 후보의 거절 기록을 파일로 저장했다: {}".format(args.pose_json))
        print("→ 움직이지 않는다.")
        return obs, first_plan

    pose_base, in_tcp, in_base, warn, plan, checked = tried[id(sel.chosen)]
    report(obs, pose_base, in_tcp, in_base, plan, warn)
    # 사람이 승인하기 **전에** 창을 갱신한다 — 무엇을 보고 고른 자리인지 눈으로
    # 확인한 뒤에 y/N 을 치게 하려는 것이다(원칙 6).
    _show(args, obs, plan)

    if args.pose_json:
        Path(args.pose_json).write_text(plan.prepose.to_json(indent=2), encoding="utf-8")
        print("→ 자세를 파일로 저장했다: {}".format(args.pose_json))

    if checked is None:
        print("→ 팔에 명령 연결이 없어 **관절 각도가 풀리는지는 확인 못 했다**.")
        return obs, plan

    print("→ 관절 각도: {}".format(checked.describe()))
    if checked.joints is not None:
        print("   최종 관절각[도] : " + ", ".join(
            "{:+.1f}".format(np.degrees(j)) for j in checked.joints))
    if checked.pre_joints is not None:
        print("   접근 시작 관절각: " + ", ".join(
            "{:+.1f}".format(np.degrees(j)) for j in checked.pre_joints))

    if not args.move:
        print("→ 계산까지만 했다(움직이려면 --move).")
        return obs, plan

    if not args.yes:
        answer = input("이 자리로 팔을 보낼까? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            # 다음 장면에서 같은 물체를 또 고르지 않게 한다(팔이 움직이기 전까지).
            picker.refuse(sel.chosen.track_id)
            print("→ 사람이 취소했다. 움직이지 않는다. 이 물체는 팔이 움직이기 전까지 "
                  "다시 고르지 않는다.")
            return obs, plan

    try:
        result = mover.move_to(plan.prepose)
    finally:
        # 🛑 `move_to()` 를 부른 순간부터 팔이 움직였을 수 있다 — 결과의 `executed` 는
        #    중간 실패(첫 이동 뒤 마지막 직선 구간 실패, 통신 끊김)에서 False 여도 팔은 이미
        #    움직인 상태다. 카메라 기준 번호를 계속 쓰면 엉뚱한 물체에 옛 번호가 붙는다
        #    (`arm/target_selection.py` 머리 설명). 번호를 버리는 비용은 작으니 무조건 버린다.
        picker.arm_moved()
    print("→ 팔 이동: {}".format(result.describe()))
    if result.arrived and stream is not None:
        stream.reset_temporal_history()   # 팔이 움직였으니 이전 위치의 다듬기 흔적을 버린다
    return obs, plan


# ---------------------------------------------------------------------------
# 명령줄
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="손목 카메라로 물체를 찾아 팔이 그 앞까지 간다 (잡지는 않는다)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--look", action="store_true",
                      help="카메라만 — 무엇이 보이는지 카메라 기준으로 찍는다")
    mode.add_argument("--plan", action="store_true",
                      help="팔에 연결해 로봇 좌표·설 자리까지 계산한다(안 움직인다)")
    mode.add_argument("--move", action="store_true",
                      help="실제로 그 자리까지 움직인다. 가짜 팔(URSim)에 먼저 할 것")
    ap.add_argument("--ip", nargs="?", const="", default=None,
                    help="팔 IP. 값 없이 주면 .env 의 RTAUTO_UR_IP (기본 URSim)")
    ap.add_argument("--target", default=None,
                    help="이 이름이 들어간 물체만 고른다(예: cup, 또는 콤마로 여러 개 "
                         "— cup,bottle). 기본은 후보 전부 중 가장 가까운 것")
    ap.add_argument("--watch", action="store_true",
                    help="계속 반복한다 — 물체를 옮기면 다시 찾아간다. Ctrl+C 로 끝낸다")
    ap.add_argument("--yes", action="store_true",
                    help="움직이기 전에 묻지 않는다. **무인 시연에서만** 쓸 것")
    ap.add_argument("--pose-json", default=None,
                    help="정한 자세를 이 파일로 저장한다(arm/prepose_to_joints.py 에 넘길 수 있다)")
    ap.add_argument("--frames", type=int, default=5,
                    help="거리 사진 몇 장을 합칠지. 흰 종이컵처럼 값이 깜빡이는 물체용")
    ap.add_argument("--conf", type=float, default=None, help="YOLO 확신 기준")
    ap.add_argument("--weights", default=None, help="YOLO 모델 파일")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--near", type=float, default=None)
    ap.add_argument("--far", type=float, default=None)
    ap.add_argument("--interval", type=float, default=1.0,
                    help="--watch 일 때 한 바퀴 사이에 쉬는 시간(초)")
    ap.add_argument("--show", action="store_true",
                    help="**카메라가 보는 것을 창으로 띄운다.** 왼쪽 색 사진(찾은 것 "
                         "테두리 + 고른 물체는 굵은 초록), 오른쪽 거리 사진. "
                         "⚠️ vision/d405/yolo_assist.py --live 를 따로 띄우면 안 된다 — "
                         "D405 는 한 번에 한 프로그램만 열 수 있어서 서로 죽인다")
    ap.add_argument("--unvalidated-mount-ok", action="store_true",
                    help="🛑 손목 카메라 장착값을 아직 안 쟀어도 **가짜 팔(URSim)에서는** "
                         "움직이게 한다. 실물 주소에서는 이 선택지를 줘도 막힌다"
                         "(가짜 팔 주소 목록: .env 의 RTAUTO_UR_SIM_IPS). 움직임 "
                         "경로를 미리 확인하는 용도이고, **나오는 좌표는 못 믿는다**")
    ap.add_argument("--fake-object", default=None, metavar="X,Y,Z",
                    help="🛑 **시험용.** 카메라를 안 쓰고 '카메라 앞 X,Y,Z m 에 물체가 "
                         "있다'고 치고 나머지 단계를 돌린다. 카메라가 없을 때 팔 쪽 "
                         "절반(좌표 옮기기 → 설 자리 → 관절각 → 이동)이 도는지 "
                         "확인하는 용도다. 예: --fake-object 0,0,0.25")
    args = ap.parse_args(argv)

    args.near = cfg.D405_NEAR_M if args.near is None else args.near
    args.far = cfg.D405_FAR_M if args.far is None else args.far
    args.frames = max(1, int(args.frames))
    if args.fake_object is not None:
        try:
            args.fake_object = tuple(float(v) for v in args.fake_object.split(","))
        except ValueError:
            args.fake_object = ()
        if len(args.fake_object) != 3:
            print("🛑 --fake-object 는 'X,Y,Z' 형식이어야 한다 (숫자 3개, 콤마로 구분).")
            return 2
    if (args.plan or args.move) and args.ip is None:
        args.ip = ""            # --plan/--move 는 팔이 있어야 한다 — 기본 IP 를 쓴다

    mount = eye_in_hand.CameraMount.from_config()
    print("=== 물체 앞까지 자율 접근 ===")
    print("손목 카메라 장착값: 위치 ({:+.4f}, {:+.4f}, {:+.4f}) m / 방향 "
          "({:+.2f}, {:+.2f}, {:+.2f}) 도".format(*mount.xyz_m, *mount.rpy_deg))
    if mount.warning():
        print(mount.warning())
    print("떨어져 설 거리 {:.0f} cm / 마지막 직선 구간 {:.0f} cm / 한 번에 움직이는 "
          "거리 한계 {:.0f} cm".format(cfg.PREGRASP_DISTANCE_M * 100,
                                        cfg.APPROACH_CLEARANCE_M * 100,
                                        cfg.MAX_STEP_M * 100))

    mover = None
    if args.plan or args.move:
        # 🛑 실물 자동 이동 관문 — 손목 카메라 장착값을 실물로 검증하기 전에는 열리지
        # 않는다. **`--plan` 에는 걸지 않는다** — 좌표 계산·관절각 풀기는 미검증
        # 장착값으로도 해도 되기 때문이다(막는 것은 "실제로 움직이는 것"뿐이다).
        if args.move:
            try:
                eye_in_hand.require_validated_mount_for_physical_move(
                    mount, ip=cfg.resolve_ur_ip(args.ip),
                    allow_unvalidated_on_sim=args.unvalidated_mount_ok)
            except eye_in_hand.MountNotValidatedError as exc:
                print("\n🛑 움직일 수 없다:\n{}".format(exc))
                print("\n지금 할 수 있는 것: --plan 으로 계산까지만 확인한다.")
                return 3
            if not mount.validated:
                print("\n" + "=" * 70)
                print("🛑 손목 카메라 장착값을 **아직 안 쟀는데 움직인다**"
                      " — 가짜 팔이라 허용했다(--unvalidated-mount-ok).")
                print("   화면에 나오는 로봇 기준 좌표는 **실제와 다르다.** 팔이 가는 "
                      "자리도 물체가 진짜 있는 곳이 아니다.")
                print("   여기서 확인하는 것은 좌표의 정확도가 아니라 **움직임 경로가 "
                      "도는가**뿐이다.")
                print("=" * 70 + "\n")
        from arm.prepose_to_joints import ArmMover

        mover = ArmMover(ip=cfg.resolve_ur_ip(args.ip))
        mover.connect()
        if not mover.can_command:
            print("\n🛑 팔에 명령을 보낼 수 없다 — 펜던트에서 전원 ON → 브레이크 해제 → "
                  "원격 조작(Remote Control) 까지 켤 것. ({})".format(
                      mover.control_error or "이유 미상"))
            if args.move:
                mover.close()
                return 4
            print("   (--plan 이라 계속 간다 — 관절 각도는 못 풀고 좌표까지만 나온다)")

    detector = None
    stream = None
    if args.fake_object is None:
        from d405_stream import open_depth
        from yolo_assist import Detector, YOLO_CONF

        detector = Detector(args.weights, args.conf if args.conf is not None else YOLO_CONF)
        if not detector.ready:
            print("\n🛑 YOLO 를 못 쓴다 ({}) — 물체를 하나도 못 찾는다.".format(detector.why))
            if mover is not None:
                mover.close()
            return 5
        print("YOLO 모델: {} / 확신 기준 {:.0%}".format(detector.path.name, detector.conf))
        print("대상 바꾸는 기준: 아까 고른 물체보다 {:.1f} cm 넘게 가까워야 바꾼다"
              "(RTAUTO_TARGET_SWITCH_MARGIN_M)".format(cfg.TARGET_SWITCH_MARGIN_M * 100))
        print()
        stream = open_depth(args.width, args.height, color=True)
    else:
        print("🛑 **카메라를 쓰지 않는다** — 카메라 앞 ({:+.3f}, {:+.3f}, {:+.3f}) m 에 "
              "물체가 있다고 치고 돈다(--fake-object). 이 좌표는 실제로 본 것이 "
              "아니다.".format(*args.fake_object))
        print()
    from segment_objects import Tracker

    tracker = Tracker()
    picker = TargetPicker(tracker)
    if picker.hold_missing_frames >= tracker.keep_missing:
        print("⚠️ RTAUTO_TARGET_HOLD_MISSING_FRAMES({}) 가 번호를 기억하는 장면 수({})보다 "
              "작지 않다 — 기다리는 동안 번호가 끊겨, 돌아온 물체를 다른 물체로 본다. "
              "{} 보다 작게 둘 것.".format(picker.hold_missing_frames, tracker.keep_missing,
                                          tracker.keep_missing))
    n = 0
    try:
        while True:
            n += 1
            print("--- {}번째 ---".format(n))
            run_once(stream, detector, args, mover, picker)
            print()
            if not args.watch:
                break
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        print("\n사람이 멈췄다(Ctrl+C).")
    finally:
        if args.show:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:
                pass
        if stream is not None:
            stream.close()
        if mover is not None:
            mover.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
