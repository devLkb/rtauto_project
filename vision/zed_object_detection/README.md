# ZED 3D Vision → Unity Object Coordinate Bridge

ZED 2i 카메라를 "눈"으로 써서 물체를 감지하고, 3D 좌표(x, y, z)를 UDP로 Unity에 전송하는 파이프라인.
Unity 쪽에서 그 좌표를 받아 로봇팔이 물체까지의 거리를 인식하고 집을 수 있도록 하는 것이 최종 목표이며,
이 폴더는 그중 "카메라로 물체를 인식하고 좌표를 뽑아 보내는" 부분을 담당한다.

## 사전 설치

1. **ZED SDK** 설치 (NVIDIA GPU + CUDA 필요): https://www.stereolabs.com/developers/release/
   - CUDA Toolkit(그래픽카드 드라이버 포함)을 먼저 설치해야 ZED SDK가 인식함
2. **pyzed** 설치 — pip으로 바로 안 되고, ZED SDK 설치 폴더의 스크립트로 설치:
   ```
   pip install requests
   python "C:\Program Files (x86)\ZED SDK\get_python_api.py"
   ```
3. **CUDA 지원 PyTorch** 설치 (기본 `pip install torch`는 CPU 전용이라 GPU 가속 안 됨):
   ```
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   ```
4. 나머지 패키지:
   ```
   pip install -r requirements.txt
   ```

## 스크립트 구성

| 파일 | 역할 |
|---|---|
| `zed_sender.py` | ZED 카메라로 물체 감지(YOLO) → 3D 좌표 계산 → UDP로 Unity에 전송. 카메라 화면(외곽선 표시)과 좌표 목록 창도 띄움 |
| `capture_dataset.py` | 커스텀 물체 인식 모델 학습용 사진을 ZED 카메라로 촬영 |
| `label_tool.py` | 촬영한 사진에 클릭 한 번으로 자동 윤곽 인식(FastSAM) 또는 수동 드래그로 박스를 그리고 이름을 입력해 라벨링 |
| `train_custom_yolo.py` | 라벨링한 데이터로 YOLO를 파인튜닝 |

## 실행

```
python zed_sender.py
```

기본은 COCO 사전학습 모델(`yolov8m.pt`, 처음 실행 시 자동 다운로드)을 써서 사람/컵/병/노트북 등
일반적인 사물을 인식한다. `zed_sender.py` 상단의 `YOLO_WEIGHTS`를 바꾸면 아래 커스텀 모델도 쓸 수 있다.

## UDP 포트

- Unity 쪽 수신 스크립트: `unity/Assets/Scripts/CameraTargetReceiver.cs` (이 저장소의 `unity/Assets/Scripts/`에 있음).
  이전에 있던 `ObjectCoordinateReceiver.cs`(로그만 찍는 미완성 스텁)는 삭제됐다 — CameraTargetReceiver가
  그 역할(좌표를 실제로 오브젝트에 반영)까지 포함해서 대체한다.
- 포트 **5007** 사용 — 5005(SVH 핸드), 5006(`Dg5fReceiver`, 손가락 관절 각도), 5008(DG5F 실물 SDK 브리지)과
  겹치지 않게 고정한 값이니 다른 용도로 바꾸지 말 것. 값의 유일한 출처는 `config/rtauto_config.py`
  (`PORT_ZED_TARGET`) — 바꿔야 하면 거기서 바꾸고 여기 숫자는 그대로 참고용으로만 둔다.
- 전송 포맷: `struct.pack('<3f', x, y, z)` — float32 little-endian 3개(감지된 물체 중 신뢰도가 가장
  높은 것 하나만). 예전엔 JSON으로 여러 물체를 보냈으나, `CameraTargetReceiver`가 애초에 단일 좌표
  바이너리 패킷만 받도록 짜여 있어서 그쪽에 맞춰 변경했다.
- **좌표계 캘리브레이션 아직 안 됨**: `CameraTargetReceiver.inputIsCameraSpace`가 현재 `false`라, ZED가
  보낸 좌표를 그대로 로봇팔 베이스 기준 로컬 좌표로 취급한다. 카메라가 로봇 베이스 원점에 정확히
  겹쳐 있지 않다면 실제 위치와 다르게 잡힌다. 실제 설치 위치/방향이 정해지면
  `inputIsCameraSpace=true` + `cameraTransform`(실측 캘리브레이션 Transform)으로 전환해야 한다.

## 커스텀 학습 모델 (`weights/dg5f_target_objects_yolov8s.pt`)

`capture_dataset.py`로 찍은 사진 71장(텀블러, 플라스틱컵, 폰, 캔, 박스, 마우스, 노트북,
팔찌, 사람)으로 `yolov8s.pt`를 파인튜닝한 결과물이다.

**주의**: 데이터가 71장뿐이고 학습(train)/검증(val)을 같은 이미지로 설정해서 만든 모델이라,
보고된 mAP(0.98 이상)는 실제 일반화 성능이 아니라 "학습한 사진을 다시 맞춘" 수치에 가깝다.
실제로 이 모델은 학습에 쓴 71장 밖의 환경에서는 인식률이 떨어지는 것을 확인했다.
실전에 쓰려면 더 많고 다양한 사진(다른 배경/조명/각도, 최소 150장 이상, 학습/검증 분리)으로
`capture_dataset.py` → `label_tool.py` → `train_custom_yolo.py`를 다시 돌려서 재학습할 것을 권장한다.
