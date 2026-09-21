# -*- coding: utf-8 -*-
"""D-4 데이터셋(`build_pose_dataset.py`가 만드는 `.npz`)이 지켜야 하는 계약 — 정본 하나
(P1-6/P1-7, 2026-09-21 코드 리뷰로 신설).

왜 따로 뺐나
-----------
`test_pose_dataset.py`(검사 스크립트)와 `train_pose_predictor.py`(실제로 학습하는 쪽)가
**같은 목록을 각자 따로 들고 있으면 조용히 어긋난다.** 실제로 있었던 문제:

1. 좌표 기준(`frame`) — 검사 스크립트만 `frame="object"`(시뮬레이터 정답이 있어야만
   나오는 값, 실물에서 재현 불가능)를 거절하고, `train_pose_predictor.load_pairs()`는
   `frame`을 아예 안 봐서 검사를 건너뛴 예전 데이터셋을 그대로 학습할 수 있었다(P1-6).
2. 입력 분류(`pose_pos`/`pose_quat`) — 검사 스크립트는 이 둘을 "정답 전용"으로
   분류했지만, `train_pose_predictor._features()`는 실제로 이 둘을 **모델 입력**으로
   쓴다 — 지금 예측기는 "점 구름 → 자세"가 아니라 "(점 구름, 후보 자세) → 점수"
   모델이기 때문이다(P1-7). 문서·검사가 실제 동작과 다르면 다음 사람이 잘못 믿는다.

정본은 이 파일 하나다. 새 필드가 생기면 여기만 고친다.
"""
from __future__ import annotations

#: 시뮬레이터의 물체 정답 위치(`env.block.get_root_transform()`)가 있어야만 만들 수
#: 있는 좌표 기준 — 실물 D405는 그 정답을 몰라서(그게 풀려는 문제) 재현 불가능하다.
LEAKY_FRAMES = frozenset({"object"})

#: 카메라·로봇이 **스스로 아는** 기준만 실물에서도 똑같이 만들 수 있다.
DEPLOYABLE_FRAMES = frozenset({"camera", "base"})

#: 카메라(또는 D405)가 본 것 그대로 — 시뮬레이터 정답 없이 실물에서도 낼 수 있는 값.
OBSERVATION_INPUT = frozenset({"points", "cloud_start"})

#: **채점할 자세 후보** — 지금 예측기는 "점 구름 → 자세를 직접 생성"하는 게 아니라
#: "(점 구름, 후보 자세) → 이 후보가 좋은가 점수"를 매기는 모델이다(P1-7). 후보 자세도
#: 모델 입력이다. ⚠️ 이 후보를 **실물 D405에서도 똑같이 만들 수 있어야** 한다 — 시뮬레이터
#: object-frame 정답으로 후보를 만들면(D-2 채점표가 지금 하는 방식) 후보 자체가 leakage다.
#: 실물에서도 쓸 수 있는 최소 후보 생성기는 `candidate_pose_generator.py`에 있다(P1-8,
#: 2026-09-21 — 점 구름만 보고 만든다, 물체 이름/시뮬레이터 정답 없이). 아직 인터페이스와
#: 시험용 최소 구현뿐이고, D-2 채점표를 대체해 실제 학습 데이터를 만드는 배관은 안 됐다.
#:
#: 🛑 **카메라 시점별로 후보를 다시 계산하려면(D-4 재설계, P1-9) `pose_quat`을 그대로
#: 모델 입력에 쓰는 지금 방식(`train_pose_predictor._features()`의 pose_f)도 같이
#: 손봐야 한다** — 그 값은 손바닥 기준 상대값이 아니라 **절대** 방향이라, 같은 물리적
#: 자세라도 어느 카메라 시점에서 봤느냐에 따라 달라진다(회귀 시험으로 확인함:
#: `superdex/tests/test_camera_frame_transform.py`의
#: `test_pose_feature_is_NOT_frame_invariant_known_gap_for_camera_frame_redesign`).
#: 점 구름 특징(cloud_f)은 시점이 바뀌어도 그대로다 — 같은 시험의 나머지 케이스들.
CANDIDATE_INPUT = frozenset({"pose_pos", "pose_quat"})

#: 정답을 만들거나 사람이 읽는 데만 쓴다 — **모델 입력에 넣으면 안 된다.**
LABEL_ONLY = frozenset({
    "pose_rate", "pose_tilt", "pose_object", "cloud_object", "frame", "made_from",
})


class DatasetContractError(ValueError):
    """데이터셋이 이 계약을 어겼을 때."""


def check_frame(frame) -> str:
    """좌표 기준 문자열 하나를 검사한다. 어기면 `DatasetContractError`.

    `test_pose_dataset.py`(검사 스크립트)와 `train_pose_predictor.load_pairs()`
    (실제 학습 진입점) **둘 다** 이 함수를 불러야 한다 — 하나만 부르면 그 경로로는
    새는 게 그대로다(P1-6).
    """
    frame = str(frame)
    if frame not in DEPLOYABLE_FRAMES:
        reason = (
            "시뮬레이터 정답 위치가 있어야만 나오는 기준이라 실물 D405에서 "
            "재현할 수 없다(순환 — 그 정답을 모르는 게 풀려는 문제다)."
            if frame in LEAKY_FRAMES else
            "알 수 없는 좌표 기준이다."
        )
        raise DatasetContractError(
            "데이터셋의 frame='{}'은(는) 허용되지 않는다 — {} "
            "허용되는 값: {}. build_pose_dataset.py의 좌표 기준을 camera 또는 "
            "base로 다시 설계할 것.".format(frame, reason, sorted(DEPLOYABLE_FRAMES))
        )
    return frame
