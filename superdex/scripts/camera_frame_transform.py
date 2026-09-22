# -*- coding: utf-8 -*-
"""자세 하나를 다른 좌표 기준으로 옮기는 순수 계산 (D-4 재설계, P1-9).

왜 필요한가
-----------
`build_pose_dataset.py`(P1-6/P1-7 리뷰로 발견, 아직 안 고침 — 그 파일 docstring
참고)는 지금 **물체 기준 점 구름 여러 장**과 **물체 기준 자세 여러 개**를 각각
따로 모은 뒤, `train_pose_predictor.load_pairs()`가 "같은 물체면 아무 점 구름과나
아무 자세나 짝짓는다"(cross-product). 카메라 기준(`frame="camera"`)으로 다시
설계하면 이 cross-product 구조를 그대로 쓸 수 없다 — **카메라 시점마다 좌표
기준이 다르므로**, 시점 A에서 찍은 점 구름에 시점 B 기준으로 적어 둔 자세를
그대로 짝지으면 자세가 엉뚱한 곳을 가리킨다. 시점마다 그 시점의 카메라 기준으로
**다시 계산한** 자세가 있어야 한다.

이 파일은 그 "다시 계산" 부분 — 자세 하나를 한 좌표 기준에서 다른 좌표 기준으로
옮기는 순수 기하 계산 — 만 떼어 놓았다. 시뮬레이터 없이 합성 변환으로 시험할 수
있다(아래 `superdex/tests/test_camera_frame_transform.py`).

🛑 **범위 — 아직 안 된 것.** `build_pose_dataset.py`의 실제 촬영 루프를 이 함수로
다시 엮는 것은 시뮬레이터 실행이 필요해 이번 리뷰에서는 하지 않았다(선례:
`test_pose_dataset.py` §5 재설계도 같은 이유로 미룸). 엮는 법은 아래
`object_pose_to_camera_frame()`의 사용 예 docstring 그대로다 —
`build_pose_dataset.py`의 `viewpoints()`가 이미 각 시점의 카메라 위치/방향
(`cam_pos`, `cam_rot`, `synth_pointcloud.look_at()`로 계산)을 알고 있으므로, 시점마다
`palm_pose_in_object_frame()`이 돌려주는 (하나뿐인, 시점과 무관한) 물체 기준 자세를
그 시점의 `t_world_cam`으로 이 함수를 불러 시점별 카메라 기준 자세로 바꾸고, 점
구름과 같은 배열 인덱스로 저장하면 된다.

**시뮬레이터의 정답 위치를 여기서 쓰는 것이 왜 괜찮은가.** 이 변환은 **데이터셋을
만들 때(학습용 정답을 계산할 때)만** 쓴다 — 물체의 진짜 위치(`t_world_obj`)와
카메라를 어디에 두기로 했는지(`t_world_cam`, 우리가 직접 정한 값)를 시뮬레이터가
안다고 해서, 나온 결과(카메라 기준 자세 하나의 숫자 6~7개)가 실물에서 못 만드는
값이 되는 것은 아니다 — 실물에서는 이 자세를 물체 정답 위치에서 계산하는 게 아니라
`candidate_pose_generator.generate_candidates()`(P1-8)처럼 점 구름만 보고 **새로**
만든다. §7-3이 막는 것은 "입력에 정답이 섞이는 것"이지 "정답을 어떻게 계산해서
저장했는가"가 아니다.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from geometric_pose_score import _quat_to_matrix as quat_to_matrix  # noqa: E402
from candidate_pose_generator import matrix_to_quat  # noqa: E402


def pose_to_matrix(pos, quat) -> np.ndarray:
    """자세(위치 + 쿼터니언 (x,y,z,w)) → 4x4 동차행렬."""
    mat = np.eye(4)
    mat[:3, :3] = quat_to_matrix(quat)
    mat[:3, 3] = np.asarray(pos, dtype=np.float64)
    return mat


def matrix_to_pose(mat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """4x4 동차행렬 → (위치, 쿼터니언 (x,y,z,w))."""
    return mat[:3, 3].copy(), matrix_to_quat(mat[:3, :3])


def invert_transform(mat: np.ndarray) -> np.ndarray:
    """강체 변환(4x4)의 역행렬 — 회전 전치 + 평행이동 재계산(일반 역행렬보다 안정적)."""
    out = np.eye(4)
    out[:3, :3] = mat[:3, :3].T
    out[:3, 3] = -mat[:3, :3].T @ mat[:3, 3]
    return out


def transform_pose(t_target_source: np.ndarray, pos, quat) -> Tuple[np.ndarray, np.ndarray]:
    """`source` 기준으로 적힌 자세(`pos`/`quat`)를 `target` 기준으로 옮긴다.

    `t_target_source`는 "source 기준 점을 target 기준으로 바꾸는" 4x4 변환
    (즉 `p_target = t_target_source @ p_source`, 동차좌표)이다.
    """
    mat_target = t_target_source @ pose_to_matrix(pos, quat)
    return matrix_to_pose(mat_target)


def transform_points(t_target_source: np.ndarray, points: np.ndarray) -> np.ndarray:
    """점 구름(`N, 3`)을 `source` 기준에서 `target` 기준으로 옮긴다."""
    points = np.asarray(points, dtype=np.float64)
    if len(points) == 0:
        return points.copy()
    rot = t_target_source[:3, :3]
    trans = t_target_source[:3, 3]
    return points @ rot.T + trans


def object_pose_to_camera_frame(pos_obj, quat_obj, t_world_obj: np.ndarray, t_world_cam: np.ndarray):
    """물체 기준 자세 하나를 **그 카메라 시점 기준**으로 옮긴다.

    `t_world_obj`/`t_world_cam`은 데이터셋을 만들 때 시뮬레이터가 아는 값을 써도
    된다(위 모듈 docstring 참고) — 결과로 나온 카메라 기준 자세 자체는 실물에서도
    같은 방식(점 구름 기준)으로 표현 가능한 값이다.
    """
    t_cam_world = invert_transform(t_world_cam)
    t_cam_obj = t_cam_world @ t_world_obj
    return transform_pose(t_cam_obj, pos_obj, quat_obj)
