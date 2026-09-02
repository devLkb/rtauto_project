# -*- coding: utf-8 -*-
"""카메라 N대 + MediaPipe → 삼각측량된 (21,3) 3D 손 랜드마크.

역할 분담:
  - multi_camera_capture.py   : 카메라 N대에서 최신 프레임 가져오기
  - (이 파일)                  : 카메라별 프레임에 MediaPipe 돌려 픽셀좌표 얻기 → 삼각측량
  - camera_calibration.py     : intrinsics/extrinsics 로드 + 실제 DLT 삼각측량 수학
  - dg5f_angles.compute_raw() : 결과 (21,3) xyz를 그대로 받아 관절각 계산 (수정 불필요 —
                                 각도 계산은 회전/이동/균일 스케일에 불변이라 진짜 3D
                                 좌표든 단안 추정 좌표든 인터페이스가 같다)

이 모듈은 함수만 제공한다(단독 실행 진입점 없음) — 실제 vision_node에 연결하는 건
카메라 실물로 intrinsics/extrinsics를 실측하고 삼각측량된 각도가 실제 손 움직임과
맞는지 확인한 뒤에 할 일이다(축 부호가 뒤집히는 사고가 이 리포에 실제로 있었다 —
vision_node_dg5f.py의 ANGLE_Z_FLIP 관련 이력 참고). 여기 정확도 검증은
tests/test_camera_calibration.py의 합성 카메라 3대 시나리오로 대신한다.

⚠️ 나중에 이 함수를 실시간 vision_node에 연결할 때 지킬 것 — 프레임을 뒤집지 말 것:
  vision_node_dg5f.py는 사람이 보기 편하라고 `cv2.flip(frame, 1)`(거울 모드)을 미리보기용
  으로 적용한다. calibrate_intrinsics.py/calibrate_extrinsics.py는 원본(뒤집지 않은) 프레임
  으로 캘리브레이션했으므로, 여기 넘기는 MediaPipe 결과도 반드시 **원본 프레임**을 처리한
  것이어야 한다. 뒤집은 프레임으로 MediaPipe를 돌리면 픽셀좌표계가 캘리브레이션 때와
  좌우 반전돼 삼각측량이 조용히 완전히 틀린 3D 좌표를 낸다(에러 없이 그럴듯한 값처럼
  보일 수 있어 더 위험함) — 거울모드가 필요하면 MediaPipe 처리 후 "표시용 복사본"만
  뒤집을 것.
"""
import numpy as np


def hand_landmarks_to_pixels(hand_landmarks, width, height):
    """MediaPipe Hands 결과 1개 손 → (21,2) 픽셀좌표 ndarray. undistort_normalize 입력용."""
    return np.array([[lm.x * width, lm.y * height] for lm in hand_landmarks.landmark],
                     dtype=np.float64)


def triangulate_hands(per_camera_results, rig, min_views=2):
    """카메라별 MediaPipe 결과 → 삼각측량된 (21,3) xyz(보드 좌표계, mm), 또는 None.

    per_camera_results: {index: (mediapipe.Hands 결과 또는 None, width, height)}
        결과의 multi_hand_landmarks가 비어 있으면 그 카메라는 이번 프레임에 미검출로
        취급한다(occlusion 등). width/height는 그 카메라 그 프레임의 실제 해상도 —
        vision_node_dg5f.py처럼 frame.shape에서 매 프레임 읽은 값을 넘길 것(고정값 가정 금지).
    rig: camera_calibration.build_camera_rig() 결과.
    """
    from camera_calibration import triangulate_landmark_set  # 순환 임포트 회피용 지연 임포트

    per_camera_pixels = {}
    for idx, (result, width, height) in per_camera_results.items():
        if result is not None and result.multi_hand_landmarks:
            per_camera_pixels[idx] = hand_landmarks_to_pixels(
                result.multi_hand_landmarks[0], width, height)
        else:
            per_camera_pixels[idx] = None
    return triangulate_landmark_set(per_camera_pixels, rig, min_views=min_views)
