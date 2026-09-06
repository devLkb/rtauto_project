# 2026-07-21 작업 기록 (ksj)

새 PC(`C:\Users\tjrwn`)에 `KDT_1_AX_rtauto` 저장소를 처음 세팅하고, 팀 강화학습 작업과는
별개로 맡은 "카메라 입력 → 타겟 오브젝트 배치" 파트를 구현·검증·커밋한 하루 기록.

## 1. 저장소 클론 및 로컬 환경 세팅

- `https://github.com/devLkb/KDT_1_AX_rtauto`를 `C:\Users\tjrwn\KDT_1_AX`로 clone
  (같은 이름의 기존 로컬 작업 폴더 `KDT_1_AX_rtauto`는 커밋 안 된 변경사항이 있어 건드리지
  않고 별도 폴더로 새로 받음)
- Python 3.10 venv(`vision/.vision`) 생성, `requirements-mlagents.txt` /
  `requirements-vision.txt` 설치
  - `torch==2.1.1+cpu`는 PyPI가 아니라 PyTorch 전용 인덱스
    (`https://download.pytorch.org/whl/cpu`)에 있어서 별도 설치 필요했음
  - `pip check`, `mlagents-learn --help` 통과 확인
- `tools/urdf_hand_import/import_hand.py`, `vision/dg5f/analyze_teleop.py`의
  하드코딩된 개발 PC 경로(`C:\Users\dltmd\...`)를 이 PC 기준(`C:\Users\tjrwn\KDT_1_AX\...`)으로 수정
- Unity 6000.4.0f1로 `unity/` 프로젝트를 batchmode로 열어 Library 생성, 컴파일 에러 없음 확인

## 2. 텔레옵 파이프라인 동작 확인

- `unity-cli`(에디터 HTTP 컨트롤 도구)를 이용해 `DG5F_Import.unity` 씬을 열고 Play
- 웹캠 없이 배선만 검증하는 `vision/dg5f/probe_sender.py`로 fist/open 포즈를 UDP 송신
  → `Dg5fHandDriver`가 받아 손가락 관절(xDrive.target)에 정확히 반영되는 것을 스크린샷 +
  수치(예: index MCP/PIP/DIP = 100.0/80.0/70.0)로 확인
- 한글 출력이 `UnicodeEncodeError`(cp949)를 내는 이슈 발견 → `PYTHONUTF8=1` 환경변수로 회피

## 3. "Play 눌러도 팔이 안 움직이는" 문제 진단

- 원인 두 가지를 코드/설정 확인으로 특정:
  1. Behavior Parameters에 학습된 모델이 연결되어 있지 않음 (5M 본학습 전이라 당연)
  2. 수동 조작(Heuristic)의 키보드 입력 코드가 `#if ENABLE_LEGACY_INPUT_MANAGER`로 막혀
     있는데, 프로젝트는 New Input System 전용(`activeInputHandler: 1`)이라 항상 무반응
- 카카오톡으로 받은 `DG5FGrasp.onnx`(관측 57 / 액션 7, `Grasp` 비헤이비어용)를 처음엔
  잘못 `Reach`(관측 26 / 액션 6) prefab에 연결해 `IndexOutOfRangeException` 발생 →
  이름·관측·액션 수를 대조해 원인 파악 후 올바른 `Grasp/TrainingArea.prefab`에 연결
- `DG5F_GraspTraining.unity`(20개 병렬 학습 영역)에서 Play → 3초 간격 스크린샷 두 장 비교로
  20개 에이전트의 팔이 실제로 다른 자세로 움직이는 것을 확인 (추론 정상 동작)

## 4. Reach 학습 스모크 테스트

- `training/scripts/generate_grasp_point_reach_smoke_config.py`로 512-step 스모크 설정 생성
- Linux 전용(tmux/Xvfb 전제) 공식 런처 대신 `mlagents-learn`을 이 PC에서 직접
  `--torch-device cpu --time-scale 10`으로 실행
- `DG5F_GraspPointReachTraining.unity`에서 Play → 트레이너와 정상 연결, 512 스텝 학습 완료,
  체크포인트·ONNX export 확인, 에러 0건
- timers.json 프로파일링 결과 정책 신경망 연산은 무시할 수준이고 병목은 Unity-Python 통신이라
  이 네트워크 규모에서는 GPU(MX450, VRAM 2GB) 전환의 이득이 불확실하다고 판단
- 5M 본학습은 팀원이 별도로 진행 중임을 확인하고 이 PC에서는 진행하지 않음

## 5. 카메라 타겟 배치 스크립트 (오늘의 본 작업)

담당 파트: 3D 카메라로부터 받은 위치 좌표를, 로봇팔(`robotBase`)을 원점으로 하는 로컬
좌표계에서 타겟 오브젝트(빨간 공)에 반영하는 스크립트.

- `unity/Assets/Scripts/CameraTargetReceiver.cs` 신규 작성
  - `vision/dg5f/Dg5fReceiver.cs`와 동일한 UDP 백그라운드 스레드 수신 패턴 (포트 5007,
    SVH 5005·DG5F 손 5006과 안 겹침)
  - 패킷: float32 `'<3f'` = (x, y, z)
  - `inputIsCameraSpace=false`(기존 동작): 수신 좌표가 이미 robotBase 로컬 좌표
  - `inputIsCameraSpace=true`(추가 기능): 수신 좌표를 카메라 자체 좌표계 값으로 해석,
    `cameraTransform`(실측 카메라 위치/방향으로 캘리브레이션할 Transform) 기준으로
    월드 좌표를 구한 뒤 다시 robotBase 기준으로 변환. `cameraAxisSign`(기본 `(1,-1,1)`)으로
    OpenCV/RealSense류(Y-down) → Unity(Y-up) 축 관례 차이 보정
  - `clampToWorkspace`로 평면 반경을 `[0.20, 0.85]m`로 안전 클램프 (카메라 오검출 대비,
    기존 RL 워크스페이스 범위와 동일값)
- 검증: Play 모드에서 임시 오브젝트로 두 경로 모두 테스트
  - robotBase-local 직접 입력: `(0.30, 0.05, 0.20)` 전송 → `target.position`과 기대 월드
    좌표 오차 0
  - 카메라-공간 입력: 임의 위치·회전(로봇팔과 무관한 지점, 15°/40° 회전)의 테스트 카메라로
    `(0.40, 0.10, 0.60)` 전송 → 오차 0으로 일치
- `DG5F_GraspPointReachTraining.unity` 씬의 `DG5F_GraspPointReachArea_00` 인스턴스 하나에만
  부착·와이어링 (공유 prefab이나 나머지 19개 병렬 학습 영역에는 영향 없음 — UDP 포트는
  프로세스당 1회만 bind 가능해서 prefab에 넣으면 20개가 동시에 같은 포트를 두고 충돌하기 때문)

### 사고 처리: 팀원 커밋 실수로 덮어쓸 뻔한 것 복구

`Grasp/Models/DG5FGrasp.onnx`가 사실 같은 날 팀원(devlkb)이 이미 커밋해 둔 파일이었는데,
카카오톡으로 받은 사본을 옮기는 과정에서 실수로 덮어썼던 것을 뒤늦게 발견. git hash 비교로
확인 후 `git restore --source=HEAD`로 원본 onnx·meta 파일과 삭제됐던 관련 meta 2개
(`DG5FGraspPointReach.onnx.meta`, `DG5FStableGrasp.onnx.meta`)를 복구했고, 잘못 바뀐
`Grasp/TrainingArea.prefab`의 모델 참조·관절 anchor 값도 원본과 완전히 동일하게 되돌림.
최종 커밋에는 이 사고의 흔적이 남지 않도록 확인 후 진행.

## 커밋

- `e603d21` — `Add CameraTargetReceiver for UDP-driven target placement`
  (`unity/Assets/Scripts/CameraTargetReceiver.cs` 신규 +
  `DG5F_GraspPointReachTraining.unity` 인스턴스 와이어링)

## 남은 것 / 다음에 할 일

- 실제 카메라 연동 시 `cameraTransform`을 실측 캘리브레이션 값으로 교체, `inputIsCameraSpace=true`로 전환
- `cameraAxisSign`을 실제 사용하는 카메라 SDK 좌표 관례에 맞게 검증
- 팀원 5M 본학습 결과 나오면 `Reach` 씬에도 실제 모델 연결해서 카메라 입력 + RL 정책 통합 테스트
