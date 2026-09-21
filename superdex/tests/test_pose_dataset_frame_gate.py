# -*- coding: utf-8 -*-
"""`superdex/scripts/test_pose_dataset.py`의 좌표 기준 검사 회귀 시험.

무엇을 확인하나
---------------
2026-09-21 코드 리뷰(P1-3)로 발견한 문제: `build_pose_dataset.py`가 물체 기준
(`frame="object"`)으로 점 구름과 자세를 맞춰 정렬하는데, 이 기준은 **시뮬레이터가
아는 물체의 정답 위치**(`env.block.get_root_transform()`)가 있어야만 계산할 수
있다. 실물 D405는 그 정답을 몰라서 이 문제를 풀려는 것이므로 순환이다
(sim-to-real 입력 누수). 그런데 검사 시험(`test_pose_dataset.py`)이 오히려
`frame == "object"` 를 요구하고 있었다 — 누수를 잡기는커녕 통과시키고 있었다.

이 시험은 그 경계가 **지금은 맞게 뒤집혀 있는지**를 확인한다:
- `frame="object"` 인 데이터셋은 실패해야 한다(순환이므로).
- `frame="camera"` 인 데이터셋은 통과해야 한다(카메라가 스스로 아는 기준).

⚠️ 이 시험은 `build_pose_dataset.py`(데이터 생성기)를 아직 안 고쳤다는 것과는
별개다 — 생성기가 여전히 `frame="object"`로 저장한다면, 그 산출물은 이 시험을
통과하지 못한다(의도된 동작). 생성기를 camera/base 기준으로 다시 설계하는 것은
이번 리뷰의 다음 단계다(시뮬레이터 실행이 필요해 이번엔 안 함).

돌리는 법 (리포 루트, superdex/.venv):

    superdex/.venv/Scripts/Activate.ps1
    python -m unittest superdex.tests.test_pose_dataset_frame_gate -v
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = REPO_ROOT / "superdex" / "scripts" / "test_pose_dataset.py"

# `superdex/scripts/test_pose_dataset.py` 는 패키지가 아니라 CLI 스크립트라
# 일반적인 import 경로가 없다 — 파일 경로로 직접 불러온다.
_spec = importlib.util.spec_from_file_location("_pose_dataset_check", _SCRIPT_PATH)
_pose_dataset_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pose_dataset_check)


def _write_minimal_dataset(path: Path, frame: str) -> None:
    """검사 1~4는 전부 통과하도록 채운, 좌표 기준만 다른 최소 데이터셋."""
    points = np.random.default_rng(0).normal(size=(40, 3)).astype(np.float32) * 0.02
    cloud_start = np.array([0, 20, 40], dtype=np.int64)
    cloud_object = np.array(["a", "b"], dtype=object)
    # 좋은 자세(짝수 인덱스)를 물체마다 다른 위치로 둔다 — 검사 4("물체끼리 겹침")가
    # 우연히 실패하지 않게(이 시험이 확인하려는 것은 검사 5뿐이다).
    pose_pos = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                         [0.05, 0.0, 0.0], [0.05, 0.0, 0.0]], dtype=np.float32)
    pose_quat = np.tile(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32), (4, 1))
    pose_rate = np.array([1.0, 0.0, 1.0, 0.0], dtype=np.float32)
    pose_tilt = np.array([1.0, 999.0, 2.0, 999.0], dtype=np.float32)
    pose_object = np.array(["a", "a", "b", "b"], dtype=object)
    np.savez_compressed(
        path,
        points=points,
        cloud_start=cloud_start,
        cloud_object=cloud_object,
        pose_pos=pose_pos,
        pose_quat=pose_quat,
        pose_rate=pose_rate,
        pose_tilt=pose_tilt,
        pose_object=pose_object,
        frame=np.asarray(frame),
        made_from=np.asarray("test"),
    )


class TestFrameGate(unittest.TestCase):
    def test_object_frame_dataset_is_rejected(self):
        """시뮬레이터 정답으로 정렬한 데이터셋(frame='object')은 실패해야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leaky.npz"
            _write_minimal_dataset(path, frame="object")
            rc = _pose_dataset_check.main(["test_pose_dataset.py", str(path)])
        self.assertEqual(rc, 1, "물체 기준(frame='object')인데도 통과했다 — 누수를 못 잡는다")

    def test_camera_frame_dataset_is_accepted(self):
        """카메라가 스스로 아는 기준(frame='camera')은 통과해야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.npz"
            _write_minimal_dataset(path, frame="camera")
            rc = _pose_dataset_check.main(["test_pose_dataset.py", str(path)])
        self.assertEqual(rc, 0, "실물에서도 낼 수 있는 기준(camera)인데 실패했다")

    def test_missing_frame_metadata_is_rejected(self):
        """좌표 기준 자체를 안 적어 둔 데이터셋도 믿을 수 없으므로 실패해야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_frame.npz"
            _write_minimal_dataset(path, frame="camera")
            # frame 칸을 지운 새 파일로 다시 저장
            data = dict(np.load(path, allow_pickle=True))
            del data["frame"]
            np.savez_compressed(path, **data)
            rc = _pose_dataset_check.main(["test_pose_dataset.py", str(path)])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
