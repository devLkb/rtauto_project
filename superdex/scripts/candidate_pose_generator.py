# -*- coding: utf-8 -*-
"""점 구름 하나에서 채점할 손 자세 후보를 **계산으로만** 만든다 (D-4, P1-8).

왜 필요한가
-----------
지금 있는 두 채점기(`geometric_pose_score.py`, `train_pose_predictor.py`)는 둘 다
"이미 있는 자세 후보 중에 뭐가 좋은지" 만 판단한다 — **후보 자체를 만드는 쪽은
없다.** 지금까지 후보는 `build_pose_dataset.py`가 시뮬레이터 안에서 물체 기준
(`frame="object"`)으로 흩뿌려 만들었는데, 이건 시뮬레이터가 아는 물체의 정답
위치가 있어야만 가능하다 — **실물 D405에는 그 정답이 없다.**

그래서 "점 구름 → 채점할 후보 자세 목록"을 실물에서도 똑같이 돌아가는 계산만으로
만드는 함수가 따로 필요하다. 이 파일이 그 최소 구현이다.

**이 파일이 절대 하지 않는 것**
- 물체 이름/식별을 쓰지 않는다 — 함수 인자에 아예 없다(CLAUDE.md "범용 파지":
  물체별 상수 금지).
- 시뮬레이터만 아는 값(물체의 정답 위치 등)을 쓰지 않는다 — 들어오는 점 구름
  하나의 평균·크기만 본다.
- 학습한 채점기를 쓰지 않는다 — 순수 기하 계산이라 `geometric_pose_score.py`와
  같은 성격으로, 학습한 쪽과 **독립적으로** 비교 가능하다.
- 좌표 기준을 바꾸지 않는다 — 넣은 점 구름이 camera 기준이면 나오는 후보도
  camera 기준이다(P1-9와 같은 원칙 — 관측과 후보가 항상 같은 기준이어야 한다).

**이 파일이 아직 하지 않는 것 (범위 밖, 다음 단계)**
- camera 기준일 때 "위(하늘)가 어느 쪽인지"는 호출하는 쪽이 넣어 줘야 한다
  (`up_axis`). 카메라가 얼마나 기울어져 있는지는 아직 실물 손눈보정(D-7,
  `config/d405_tool_camera.json`의 status VALIDATED)이 끝나야 정확히 알 수 있다 —
  그 전까지 camera 기준 점 구름에 이 함수를 실물로 쓰면 up_axis를 잘못 넣어
  후보가 옆이나 아래에서도 나올 수 있다. base 기준 점 구름(로봇 밑동 기준, up
  이 항상 (0,0,1))에는 이 문제가 없다.
- `arm/prepose_to_joints.py`가 쓰는 `GraspPrePose`(approach_dir/standoff가 있는
  실제 이동 계약)로 변환하는 코드는 아직 없다 — 이 파일은 SuperDex 쪽 채점
  파이프라인(`pose_pos`/`pose_quat` 배열)까지만 만든다. 실물 팔로 보내려면
  다음 단계에서 이 출력을 `GraspPrePose.accept()`에 맞게 변환하는 코드가 필요하다.

실행 (리포 루트, superdex/.venv)
--------------------------------

    superdex/.venv/Scripts/Activate.ps1
    python -m superdex.tests.test_candidate_pose_generator  # 또는 unittest로
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from geometric_pose_score import GRASP_CENTER_PALM  # noqa: E402


def _orthonormal_basis(z_axis: np.ndarray, reference: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """z_axis(단위벡터) 하나로 나머지 x/y축까지 채운 정규직교 기저를 만든다."""
    z_axis = z_axis / np.linalg.norm(z_axis)
    ref = reference
    if abs(float(np.dot(z_axis, ref))) > 0.99:
        # z_axis가 참고축과 거의 나란하면(특이점) 다른 참고축으로 바꾼다.
        ref = np.array([1.0, 0.0, 0.0]) if abs(z_axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x_axis = np.cross(ref, z_axis)
    x_axis = x_axis / np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    return x_axis, y_axis, z_axis


def matrix_to_quat(rot: np.ndarray) -> np.ndarray:
    """3x3 회전행렬 → 쿼터니언 (x, y, z, w). `geometric_pose_score._quat_to_matrix`와
    서로 역함수가 되도록 같은 (x, y, z, w) 규약을 쓴다."""
    m = rot
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return np.array([x, y, z, w], dtype=np.float64)


def _hemisphere_directions(n: int, up_axis: np.ndarray) -> np.ndarray:
    """`up_axis` 쪽 반구에만 고르게 퍼진 단위벡터 n개 (황금각 나선, 결정적)."""
    if n <= 0:
        return np.zeros((0, 3), dtype=np.float64)
    up = up_axis / np.linalg.norm(up_axis)
    bx, by, bz = _orthonormal_basis(up, reference=np.array([0.0, 0.0, 1.0]))
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    dirs = np.zeros((n, 3), dtype=np.float64)
    for i in range(n):
        # z in (0, 1] — up_axis와의 내적이 항상 양수(엄격한 반구, 바닥/옆에서
        # 접근하는 후보가 안 나온다).
        z = 1.0 - (i + 0.5) / n
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden_angle * i
        local = np.array([radius * math.cos(theta), radius * math.sin(theta), z])
        dirs[i] = local[0] * bx + local[1] * by + local[2] * bz
    return dirs


def generate_candidates(
    points: np.ndarray,
    n_directions: int = 12,
    up_axis: Sequence[float] = (0.0, 0.0, 1.0),
    standoff: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """점 구름 하나에서 채점할 손 자세 후보 `n_directions`개를 계산으로만 만든다.

    Parameters
    ----------
    points : (N, 3) 배열
        점 구름 — camera 기준이든 base 기준이든(`dataset_contract.DEPLOYABLE_FRAMES`)
        상관없다. 나오는 `pose_pos`/`pose_quat`도 **같은 기준**이다.
    n_directions : 몇 방향에서 접근하는 후보를 만들지.
    up_axis : 그 점 구름의 좌표 기준에서 "위(하늘 방향)"를 가리키는 단위벡터.
        base 기준이면 보통 기본값 (0, 0, 1) 그대로 쓴다. camera 기준일 때는
        호출하는 쪽이 카메라 기울기를 반영해 넣어야 한다(위 docstring 참고,
        아직 실물 손눈보정 전이라 기본값을 그대로 믿으면 안 된다).
    standoff : 손바닥과 점 구름 중심 사이 거리(m). None이면
        `geometric_pose_score.GRASP_CENTER_PALM`(실측값)의 원점 거리 +
        점 구름 반지름으로 계산한다.

    Returns
    -------
    pose_pos : (K, 3) float64 — 후보 손바닥 위치, 입력 `points`와 같은 좌표 기준.
    pose_quat : (K, 4) float64 — 후보 손바닥 방향 (x, y, z, w). 손바닥 z축(손가락이
        뻗는 방향)이 점 구름 중심을 향한다.

    점 구름이 비어 있으면(`len(points) == 0`) 빈 배열 두 개를 돌려준다 — 채점할
    후보가 없다는 뜻이지, 오류가 아니다(호출하는 쪽이 "후보 0개"를 스스로 판단).
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 4), dtype=np.float64)

    centroid = points.mean(axis=0)
    obj_radius = float(np.max(np.linalg.norm(points - centroid, axis=1)))

    if standoff is None:
        standoff = float(np.linalg.norm(GRASP_CENTER_PALM)) + obj_radius

    up = np.asarray(up_axis, dtype=np.float64)
    dirs = _hemisphere_directions(n_directions, up)  # 손바닥 -> 중심으로의 반대 방향

    pose_pos = centroid[None, :] + dirs * standoff
    pose_quat = np.zeros((len(dirs), 4), dtype=np.float64)
    for i, d in enumerate(dirs):
        forward = -d  # 손바닥 z축(손가락 뻗는 방향)은 물체 쪽을 향한다.
        bx, by, bz = _orthonormal_basis(forward, reference=up)
        rot = np.stack([bx, by, bz], axis=1)  # 열이 손바닥의 x/y/z축(세계 기준)
        pose_quat[i] = matrix_to_quat(rot)

    return pose_pos, pose_quat
