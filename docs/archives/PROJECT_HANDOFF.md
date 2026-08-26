# SVH 5지 핸드 실시간 손 모방 — 프로젝트 인수인계 문서

작성일: 2026-07-02 · 진행 상태 갱신: 2026-07-13
목적: 이 문서 하나만 보고 다른 환경(Claude Code + unity-cli)에서 작업을 이어받을 수 있도록,
지금까지 한 것 / 겪은 문제와 해결 / 남은 단계와 각 단계의 상세 작업 지침을 기록.

> ⚠️ **최신 현황은 [WORKLOG.md](WORKLOG.md)가 기준** (특히 §17 현재 상태 스냅샷).
> 이 문서의 단계별 상세 지침(§6)은 여전히 유효하나, §1 진행 상태 외 세부 수치(보정값 등)는
> 07-02 시점 기록이라 낡았을 수 있음.

---

## 0. 프로젝트 개요

### 최종 목표
정밀 제조용 SCHUNK SVH(Servo-electric 5-Finger Gripping Hand)를 사람 손 움직임으로
**실시간 모방(teleoperation)** 시킨다.

### 핵심 하드웨어: SVH
- 인간형 5지 핸드. **9개 구동기(DoF)** 로 15개 손가락 관절을 커플링 구동.
- ROS1/ROS2 드라이버 공식 제공 (SCHUNK GitHub). joint_trajectory_controller로 9개 관절 동기 제어.
- MuJoCo 기반 시뮬레이션 환경 포함.
- 9개 채널(이 프로젝트에서 정의한 매핑 기준):
  1. thumb_flexion (엄지 굽힘)
  2. thumb_opposition (엄지 대향)
  3. index_flexion (검지 굽힘)
  4. middle_flexion (중지 굽힘)
  5. ring_flexion (약지 굽힘)
  6. pinky_flexion (새끼 굽힘)
  7. finger_spread (손가락 벌림)
  8. index_middle_couple (검지+중지 커플링)
  9. ring_pinky_couple (약지+새끼 커플링)
  ※ 위 9개 순서는 SVH ROS 드라이버의 실제 joint 순서에 맞춰 2단계에서 재확인/재정렬 필요.

### 핵심 설계 원칙 (중요)
- **좌표가 아니라 "관절 각도"를 전송한다.** 사람 손과 로봇 손은 크기·위치가 다르므로
  좌표를 직접 보내면 안 됨. 관절 각도는 크기·위치·카메라 거리에 무관 → retargeting이 자연스러움.
- 사람 손 각도 범위(human_min~max)를 0~1로 정규화 → SVH 관절 범위(svh_min~max)로 재매핑(비율 매핑).
- 비전 프로세스(Python)와 소비자(유니티/ROS)를 **분리**하고, 사이에는 무거운 영상이 아니라
  **float 9개(관절 각도)만 UDP로 전송**. 부하 거의 0. 나중에 비전을 다른 기기로 빼도 IP만 변경.

### 정확도에 대한 합의된 한계
- 단일 카메라(z 부정확) → 각도 경향은 나오나 정밀도 한계. 파이프라인 검증용.
- 정밀 모방에는 카메라 2대(스테레오) 삼각측량 필요. 단, 뒷단(각도·필터·전송)은 그대로 재사용.
- 최종 정밀도가 정말 중요하면 데이터글러브(Manus/CyberGlove)가 occlusion 없어 더 안정적 — 대안으로만 언급.

---

## 1. 현재까지 완료 상태 (전체 5단계 중)

- **0단계 (준비) — 완료**
- **1단계 (뒷단 파이프라인 검증, 단일 카메라) — 완료**
- **2단계 (SVH 실제 관절 범위 채우기) — 완료 (07-02)**: dex-urdf `schunk_svh_hand_right.urdf`
  `<limit>` 값으로 채움. 채널 순서 = SVH ROS 드라이버 JTC/SVHChannel enum 순서로 확정.
  thmOpp 역방향은 07-08 라이브 로그로 확정 → svh_min/max 스왑 적용.
- **3단계 (시뮬 검증) — 완료 (07-02~07-08, MuJoCo 대신 Unity 경로 B)**: UR5e+SVH 결합 URDF를
  Unity ArticulationBody로 구동, SvhReceiver/SvhHandDriver로 UDP 9각도 주입, 라이브 미러링 동작.
  Unity 물리 진동 사건(07-02~07-08)은 임포터 기본값 관성 수정으로 종결 — WORKLOG §12, §16 필독.
- 4단계 (안전장치 추가) — **일부**: occlusion hold ✅ / rate limit·One Euro 튜닝·spread 게이팅 미완.
- (5단계) 스테레오 카메라 2대 확장 — 미착수. 정밀도 필요 시(팔 텔레옵 도입 시 사실상 필수).
- (6단계) 실물 SVH 연동 — 미착수.
- **(신규 트랙) Unity ML-Agents 모방학습/강화학습** — 선행 조건·로드맵: [ML_AGENTS_ROADMAP.md](ML_AGENTS_ROADMAP.md)
- **(신규) 팔 타겟 추종 IK** — RobotArm 패키지 CCD IK를 `ArmTargetIK.cs`로 이식(WORKLOG §15).
  **07-13 안정화 완료**: 출렁임 원인 2건 해결(손목 forceLimit 28→150 포화 제거 + 순차 CCD),
  가속 램프·도달 히스테리시스·범위 밖 타겟 처리로 부드러운 뻗기, GraspPoint를 반그립 실측
  파지 중심으로 이설(WORKLOG §18~§18-3). 남은 것: 자세(orientation) 제어 — 위치만 추종 중이라
  손바닥 접근 방향이 임의, 실제 파지엔 자세 제어 추가 필요.
- **(신규) GitHub 공개** — https://github.com/tmdrb0130/kdt-ai (vision/unity/urdf_build/docs).
  원본 개발은 로컬 Unity 프로젝트에서 하고 수정분을 리포에 커밋·푸시로 동기화.

---

## 2. 개발 환경

- OS: Windows. 작업 폴더: `C:\Users\dltmd\Desktop\KDT\svh\`
- Python 3.10.12 공용 venv(`vision/.vision`) 권장 — 비전(텔레옵)과 ML-Agents를 한 환경에서 사용.
- **중요 버전 고정(2026-07-14 검증)**: `mediapipe==0.10.11`, `protobuf==3.20.3`, `numpy==1.23.5`,
  `opencv-contrib-python==4.8.1.78`. 과거 `mediapipe==0.10.14` 기준으로는 protobuf 4.x 충돌 때문에
  venv 분리가 필요하다고 보았으나, 0.10.11로 낮추면 ML-Agents와 공존 가능.
- 이어서 할 환경: Claude Code + unity-cli (유니티를 CLI 환경에서 직접 조작 가능)
  - 이미 검증한 것: dex-urdf / UR ROS2 description zip에서 3D 모델 추출,
    핸드+로봇암 결합, 관절값 주입해 조작까지 성공.
  - 참고 저장소:
    - https://github.com/dexsuite/dex-urdf (여러 로봇 손 URDF 모음)
    - https://github.com/UniversalRobots/Universal_Robots_ROS2_Description (UR 암)
    - https://github.com/youngwoocho02/unity-cli (유니티 CLI 제어)
    - SVH 공식 드라이버: https://github.com/SCHUNK-SE-Co-KG/schunk_svh_ros_driver
      (ROS1/ROS2, URDF + MuJoCo 시뮬 포함)

---

## 3. 파일 구성 (현재)

작업 폴더에 있는 파일:

| 파일 | 역할 | 상태 |
|------|------|------|
| `svh_angles.py` | landmark 21점 → SVH 9채널 각도 변환 + 비율 매핑 + calibration.json 자동 로드 | 완성, human값 보정됨 / **svh_min·max는 placeholder(2단계 대상)** |
| `one_euro_filter.py` | One Euro Filter (관절 떨림 억제). 9채널 각각 적용 | 완성 |
| `calibrate_raw.py` | 웹캠으로 손 각도 raw값 관측 → calibration.json 자동 저장 | 완성 |
| `calibration.json` | 사람 손 각도 범위(human_min/max). calibrate_raw가 생성, svh_angles가 로드 | 생성됨(사용자 손 기준) |
| `vision_node.py` | 메인 루프: 캡처→MediaPipe→(삼각측량)→각도→필터→UDP 전송 | 완성, 현재 STEREO=False |
| `udp_test_receiver.py` | 유니티 없이 UDP 전송 확인용 수신기 | 완성(테스트용) |
| `SvhReceiver.cs` | 유니티에서 UDP 9각도 수신하는 C# 스크립트 | 완성(미연동) |
| `angles_log.csv` | calibrate_raw의 프레임별 로그 | 자동 생성 |

### 데이터 흐름
```
웹캠 → MediaPipe Hands(21 landmark) → svh_angles.compute_svh_angles(raw 각도 9개)
     → svh_angles.map_to_svh(사람범위→0~1→SVH범위, clamp) → One Euro 필터(9채널)
     → struct.pack('<9f') → UDP(127.0.0.1:5005) → 수신측(유니티 SvhReceiver / ROS 브리지)
```

### UDP 패킷 포맷 (계약)
- float32 × 9, little-endian, 총 36바이트.
- Python: `struct.pack('<9f', *svh)` / C#: `BitConverter.ToSingle` ×9.
- 순서 = svh_angles.CHANNEL_NAMES 순서 (위 9개 채널 순서).

---

## 4. 각도 계산 방식 (svh_angles.py 요지)

- landmark 인덱스: 0=손목, 1-4=엄지, 5-8=검지, 9-12=중지, 13-16=약지, 17-20=새끼.
- `_angle(a,b,c)`: b를 꼭짓점으로 한 두 벡터 사이 각도(rad).
- 굽힘(_flexion): MCP각 + PIP각 합. 편 상태 ≈ 0, 주먹 ≈ 3.x rad.
- 엄지 대향(_thumb_opposition): 검지MCP–손목–엄지끝 각.
- 벌림(_spread): 검지MCP–손목–새끼MCP 각.
- 커플링 채널: 관련 손가락 굽힘의 평균.
- **map_to_svh**: 각 채널 `t=(v-hmin)/(hmax-hmin)` clamp[0,1] → `smin + t*(smax-smin)`.

### 현재 보정값 (calibration.json, 사람 손 기준 / 사용자 실측)
thumb_flexion 0.134–1.592, thumb_opposition 0.207–0.906, index_flexion 0.189–3.028,
middle_flexion 0.148–3.143, ring_flexion 0.126–3.25, pinky_flexion 0.186–3.247,
finger_spread 0.558–1.101, index_middle_couple 0.169–3.084, ring_pinky_couple 0.171–3.245.
- 검증 결과: 손 펴면 굽힘 0~5%, 주먹 쥐면 99~100% 로 정상 매핑 확인.
- 주의: finger_spread min(0.558)이 다소 높음 → 손가락 완전히 붙이는 동작 포함해 재보정하면 개선.
- 주의: thumb_opposition은 편 자세에서 값이 높게 나옴 → 방향(부호) 뒤집힘 여부는 시각화로 확인 필요.

---

## 5. 겪은 문제와 해결 (트러블슈팅 기록)

1. **`AttributeError: module 'mediapipe' has no attribute 'solutions'`**
   - 원인: `pip install mediapipe`가 최신 0.10.35 설치. 이 휠에는 `python/solutions` 폴더가
     없고 `tasks`/`modules`만 있음 → 구 `mp.solutions.hands` API 제거됨.
   - 확인법: `python -c "import mediapipe as mp,os;print(os.listdir(os.path.dirname(mp.__file__)))"`
     → `python` 폴더 없으면 구 API 불가.
   - 해결(현재 권장): `pip install -r requirements-vision.txt` 또는
     `pip install -r vision/requirements-vision-mlagents.resolved.txt`
   - 검증: `python -c "import mediapipe as mp; print(mp.__version__, mp.solutions.hands)"` →
     `0.10.11`과 hands 모듈이 출력되면 OK.
   - ML-Agents와 같은 venv를 유지하려면 `protobuf==3.20.3`을 고정한다.
   - 잔여 경고(무시 가능): protobuf `GetPrototype deprecated`, TFLite XNNPACK INFO,
     inference_feedback_manager WARNING.

2. **수동으로 svh_angles.py의 human 범위를 고쳐야 하는 번거로움**
   - 해결: calibrate_raw.py가 종료 시 `calibration.json` 자동 저장(마진 ±0.05 적용),
     svh_angles.py가 import 시 자동 로드해 human_min/max만 덮어씀. 소스코드는 직접 수정 안 함.
     (svh_min/max는 건드리지 않음 — URDF 값이라 별도 관리)

3. **q로 종료가 안 되던 것**
   - OpenCV 영상 창(콘솔 아님)을 클릭 후 q. 한/영 입력 상태면 영문으로.

4. **udp_test_receiver.py가 Ctrl+C로 안 꺼짐**
   - 원인: recvfrom blocking 중 Windows에서 인터럽트 지연.
   - 해결: 창을 X로 닫거나, 개선하려면 `sock.settimeout(0.5)` + try/except.

5. **화면 좌우 반전(거울) 혼란**
   - calibrate_raw는 flip 적용, vision_node는 미적용이라 손 방향이 반대로 보였음.
   - 해결: vision_node의 **단일 카메라 분기에만** `cv2.flip(frameL,1)` 추가.
   - 중요: **STEREO=True(카메라 2대)에서는 flip 금지** — 삼각측량 좌표가 꼬임.
   - 각도 계산은 flip과 무관(상대 각도라 불변). 표시 편의일 뿐.

6. **로그 끝에 값이 한 줄로 고정 반복**
   - 손이 프레임에서 벗어나 인식 끊김 → occlusion hold(마지막 유효값 유지)가 작동한 정상 동작.

---

## 6. 남은 단계 상세 지침

### ▶ 2단계: SVH 실제 관절 범위(svh_min/svh_max) 채우기  ← 지금 할 차례
**목표**: svh_angles.py의 SVH_CHANNELS 각 채널 뒤 두 값(svh_min, svh_max)을
SVH의 실제 관절 가동 범위(rad)로 교체. 현재는 placeholder(예: 0.0~1.33).

**작업 방법**:
1. SVH URDF 확보. 소스 우선순위:
   - SCHUNK 공식 드라이버 저장소의 `schunk_svh_description`(URDF/xacro) 안 `<joint>`의 `<limit lower= upper=>`.
   - 또는 dex-urdf에 SVH가 포함돼 있으면 그 URDF의 joint limit.
2. URDF의 9개 구동 joint를 식별하고, 각 joint의 lower/upper(rad)를 읽는다.
   - 커플링/미미크(mimic) joint 주의: SVH는 일부 관절이 mimic으로 종속됨.
     실제 "구동되는" joint만 9개로 골라야 함.
3. svh_angles.py의 SVH_CHANNELS에서 각 채널 이름 ↔ URDF joint 이름 대응을 확정하고,
   (svh_min, svh_max)를 URDF lower/upper로 교체.
   - **채널 순서를 ROS 드라이버 joint_trajectory_controller의 joint 순서와 반드시 일치**시킬 것.
     (전송 순서가 어긋나면 엉뚱한 관절이 움직임)
4. 방향(부호) 확인: URDF에서 굽힘의 +방향이 사람 손 굽힘 증가와 같은 방향인지.
   반대면 매핑에서 (svh_min, svh_max)를 서로 바꾸면 됨.

**산출물**: svh_min/max가 실제값으로 채워진 svh_angles.py.
**주의**: 이 값이 맞기 전에는 절대 실물 SVH로 명령 보내지 말 것.

### ▶ 3단계: MuJoCo(또는 unity-cli) 시뮬 검증
**목표**: UDP로 나오는 9각도를 시뮬 SVH 모델에 연결해 가상 손이 내 손을 따라 움직이는지 확인.
**두 경로**:
- (A) SVH ROS 드라이버 포함 MuJoCo 시뮬에 연결.
- (B) **현 사용자 환경 권장**: unity-cli + dex-urdf에서 SVH(또는 유사 핸드) 3D 모델을 로드하고,
  SvhReceiver.cs(UDP 수신)로 받은 9각도를 각 joint에 주입. 이미 핸드+암 결합/관절 주입 경험 있음.
**확인 포인트**:
- 굽힘 방향 부호가 맞는가(손 굽히면 로봇도 굽히는가).
- thumb_opposition, finger_spread 방향이 자연스러운가.
- 튀는 값/떨림 없는가(One Euro 파라미터 조정: min_cutoff, beta).
- occlusion 시 hold가 자연스러운가.
**산출물**: 시뮬에서 손 모방이 자연스럽게 재현됨. 매핑/부호/필터 최종 확정.

### ▶ 4단계: 안전장치 추가 (실물 전 필수)
- **rate limit**: 프레임 간 각도 변화량 상한. 예) |Δangle| ≤ MAX_STEP(관절별) per frame로 clamp.
  급격한 비전 노이즈가 모터 급명령이 되는 것 방지.
- **범위 clamp**: 이미 map_to_svh에서 SVH 범위로 clamp 중. 유지.
- **occlusion hold**: 이미 vision_node에 구현(last_valid 유지). 유지.
- (권장) 워치독: 일정 시간 유효 landmark 없으면 안전자세로 서서히 복귀.
**산출물**: vision_node(또는 브리지)에 rate limit 등 추가.

### ▶ 5단계: 스테레오 카메라 2대 확장 (정밀도 필요 시)
- 카메라 2대를 **하나의 단단한 바(리그)** 에 고정(상대 위치 불변). 삼각대 2개 지양.
- baseline(카메라 간격) ≈ 손까지 거리의 1/10~1/3. 손 40~50cm면 10~20cm 권장. 광축 평행 또는 약한 수렴.
- 체커보드(인쇄 또는 화면 표시)로 `cv2.calibrateCamera`(각각) + `cv2.stereoCalibrate` →
  `stereo_calib.npz`(mtxL,distL,mtxR,distR,R,T) 저장.
  - 대안: 체커보드 없이 손 landmark를 대응점으로 하는 자동 캘리브(정확도↓, 스케일 모호. 각도만 필요하면 실용적).
- vision_node.py에서 `STEREO=True`, `CAM_LEFT/RIGHT` 설정. flip은 반드시 제거.
- **뒷단(각도·필터·UDP·시뮬·안전장치)은 그대로 재사용.** 입력만 단일→삼각측량 3D로 교체.

### ▶ 6단계: 실물 SVH 연동
- MuJoCo/시뮬에서 충분히 안정적일 때만.
- 9각도를 SVH ROS 드라이버의 joint_trajectory_controller 액션서버로 전송하는 브리지 작성.
- 처음엔 느린 속도·좁은 범위로 시작, 점진적으로 확대.

---

## 7. 재현/실행 방법 (현재 1단계까지)

```powershell
# 최초 1회 설치(비전 + ML-Agents 공용 venv)
py -3.10 -m venv vision\.vision
vision\.vision\Scripts\Activate.ps1
pip install -r requirements-mlagents.txt
pip install -r requirements-vision.txt

cd "C:\Users\dltmd\Desktop\KDT\svh"

# (재)보정: 손 펴기/주먹/벌리기/엄지대향 반복 후 영상창에서 q
python calibrate_raw.py       # -> calibration.json 자동 생성

# 전송 확인 (창 2개)
python udp_test_receiver.py    # 창 A (먼저)
python vision_node.py          # 창 B  (STEREO=False, 127.0.0.1:5005)
```

CAM 인덱스가 안 맞으면 vision_node/calibrate_raw의 CAM 값 0→1→2 시도.

---

## 8. 다음 액션 (이 문서를 받은 시점에서)
1. SVH URDF 확보 → 9개 구동 joint의 lower/upper(rad) 추출.
2. svh_angles.py의 SVH_CHANNELS svh_min/max 교체 + 채널↔joint 순서 일치.
3. unity-cli 환경에서 SVH(또는 dex-urdf 핸드) 로드 → SvhReceiver로 9각도 주입 → 손 모방 시각 검증.
4. 부호/떨림/occlusion 확인 후 4단계 안전장치(rate limit) 추가.
```
