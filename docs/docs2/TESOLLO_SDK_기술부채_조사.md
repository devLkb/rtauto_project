# Tesollo SDK vs. Unity+MediaPipe 텔레옵 — 기술부채 조사 보고

조사일 2026-07-29. 조사 대상: 회사 제공 자료
`~/Documents/카카오톡 받은 파일/회사에서 준 api 관련 자료 원본/`
(`DGSDK_ver_2_0_1.zip`, `DGSDKSample_ver_2_0_1`, `dg_python-main.zip`,
`Delto_Gripper_Manager_and_SDK_User_Manual_ver_2_0_0_KR.pdf`)
및 저장소 `vision/dg5f/`, `unity/Assets/Scripts/`.

---

## 0. 결론 요약

**"SDK를 안 쓰고 MediaPipe로 갈아탔다"는 전제는 사실이 아니다.** SDK는 이미 쓰이고
있고, MediaPipe는 SDK가 애초에 제공하지 않는 계층을 채운 것이다. 둘은 대체재가
아니라 **입력 계층 / 출력 계층**으로 직렬 연결돼 있다.

```
웹캠 → MediaPipe → 20채널 관절각 ─┬→ UDP:5006 → Unity 디지털 트윈 (RL 학습·검증)
   [입력: SDK에 없는 부분]        └→ UDP:5007 → dg5f_sdk_bridge.py → DGSDK → 실물 하드웨어
                                                  [출력: SDK가 담당]
```

실제 갚아야 할 부채는 "SDK 미사용"이 아니라 **"SDK를 비공식 경로로 얕게 썼고,
실물 검증을 아직 안 했다"**는 것이다. 항목은 4절.

---

## 1. Tesollo SDK가 실제로 제공하는 것

공식 Python 래퍼 `dg_python-main/src/dgsdk/wrapper.py`(51 KB)의 공개 메서드를
전수 분류한 결과, API는 다음 5종뿐이다.

| 분류 | 대표 함수 | 하는 일 |
|---|---|---|
| 시스템 | `set_gripper_system` `connect_to_gripper` `system_start/stop` | Modbus TCP 연결 수립 |
| 모션 | `move_joint_all` `move_servo_joint` `grasp` `manual_teach_mode` | **주어진 관절각/명령으로 하드웨어 구동** |
| 설정 | `set_joint_gain_pid_*` `set_motion_time_*` `set_grasp_force` | 게인·모션타임·파지력 |
| 데이터 | `get_gripper_data` `get_fingertip_sensor_data` `get_current_tcp_pose` | 상태·센서 읽기 |
| 콜백 | `on_gripper_data` `on_connected` | 이벤트 수신 |

**핵심: "무슨 각도를 보낼지 만들어 내는 기능은 SDK에 하나도 없다."** SDK는
`move_servo_joint([float]*20)`처럼 **이미 정해진 20개 각도를 받아 실물에 쓰는**
계층이다. 사람 손을 읽어 그 20개 값을 만드는 일 — 그게 이 프로젝트에서 MediaPipe가
하는 일이고, SDK의 범위 밖이다.

이는 제조사 자신의 텔레옵 레퍼런스에서도 확인된다. Tesollo가 공개한 DG-5F 텔레오퍼레이션
사례는 **MANUS Metagloves Pro / SenseGlove 데이터 글러브 + ROS2 패키지** 조합이다.
즉 SDK만으로 텔레옵이 성립하는 것이 아니라, **별도의 입력 하드웨어가 반드시 필요**하다.
우리는 그 데이터 글러브(수백만 원대)가 없었고, 웹캠+MediaPipe가 그 자리를 대체했다.

또한 SDK는 **시뮬레이터가 아니다.** 실물 그리퍼에 Modbus로 붙지 않으면 아무것도
하지 않는다. 이번 프로젝트 산출물의 본체인 강화학습(20대 병렬, 650만 스텝)은
Unity 물리 시뮬레이션 없이는 불가능하고, SDK로는 대체할 수 없다.

---

## 2. 저장소에서 SDK가 실제로 쓰이는 지점

| 위치 | 내용 |
|---|---|
| `vision/dg5f/dg5f_sdk_bridge.py` (276줄) | `DGSDK.dll`을 **ctypes로 직접 바인딩**. `SetGripperSystem → ConnectToGripper → SetGripperOption → SystemStart` 시퀀스 구현, `MoveServoJoint(float[20])`로 50 Hz 실시간 구동. 슬루 리밋(2°/틱), 저역필터, 드라이런 모드, 관절 대응 검증용 `--pose` 포함 |
| `vision/dg5f/vision_node_dg5f.py:99` | `--bridge` 옵션 시 같은 패킷을 Unity(5006)와 브리지(5007)에 **동시 송신** — 트윈과 실물 동시 구동 설계 |
| `unity/.../Dg5fFingerIKMode.cs` (`JointAnglesOnly` 모드) | IK를 끄고 패킷 관절각으로 20관절을 직접 구동. 주석에 **"실물 Tesollo SDK와 동일 인터페이스, 트윈/실물 비교용"** 명시 |

즉 20채널 관절각이라는 계약 자체가 **SDK의 `MAX_JOINT_COUNT=20`, 단위 degrees에
1:1로 맞춰 설계**돼 있다. 브리지 파일 헤더에 그 근거가 적혀 있다(2026-07-20 확인).

**설계 판단으로서는 방어 가능하다.** MediaPipe를 Unity 쪽에 넣지 않고 Python에서
각도까지 계산한 뒤 UDP로 뿌리는 구조라, 같은 스트림 하나로 트윈과 실물을 동시에
먹일 수 있다. SDK를 Unity에 직접 붙였다면(C# P/Invoke) 실물이 없는 개발·학습
환경에서 손 파이프라인 전체를 돌릴 수 없었을 것이다.

---

## 3. 왜 Unity였나 (기록상 근거)

1. **강화학습 환경이 필요했다.** ML-Agents 기반 파지 학습이 프로젝트 본체이며,
   20개 환경 병렬 학습·충돌 검증·물리 실험은 시뮬레이터 없이는 불가능하다.
   SDK에는 시뮬레이션 기능이 없다.
2. **실물 접근이 상시 가능하지 않았다.** 브리지가 아직 드라이런 상태인 것이 방증이다.
3. **UR5e 팔 + DG5F 손 결합 모델**이 필요했다. SDK는 손만 담당하고 팔은 범위 밖이다.
4. **디지털 트윈이 요구사항**이었다(README 첫 문장). 트윈은 정의상 시뮬레이터가 있어야 한다.

---

## 4. 실제 기술부채 (갚아야 할 것)

### 부채 ① 공식 Python 래퍼를 두고 ctypes를 직접 짰다 — **우선순위 높음**

회사가 준 `dg_python-main.zip`에는 **공식 Python 래퍼**(`src/dgsdk/wrapper.py`,
타입 정의, 예제 4종, 테스트 2종, `pyproject.toml`)가 들어 있다. 우리 브리지는
이것을 쓰지 않고 `DGDataTypes.h`를 보고 ctypes 구조체를 손으로 재작성했다.

구체적 손해:

- **유지보수 경로 이탈 (핵심).** 구조체 레이아웃이 SDK 2.0.1 → 이후 버전에서 바뀌면
  우리 ctypes 정의는 조용히 깨진다. 메모리 레이아웃 불일치는 예외를 던지지 않고
  **잘못된 값이 하드웨어로 나가는 형태로 나타난다.** 공식 래퍼를 쓰면 이 위험이
  제조사 쪽으로 넘어간다.
- **검증 자산을 버렸다.** 공식 패키지에는 예제 4종(`basic_connection`,
  `joint_movement`, `recipe_loop`, `sensor_readout`)과 테스트 2종이 들어 있다.
  우리 브리지는 이 중 어느 것도 재사용하지 않아, 연결 시퀀스가 맞는지 확인할
  독립적인 기준이 없다.
- **API 커버리지가 좁다.** 우리 ctypes 바인딩은 9개 함수만 선언했다. 공식 래퍼는
  100개 이상을 노출하며, 부채 ③에서 지적하는 센서·상태 읽기가 전부 여기 포함된다.

> **OS 참고**: 브리지 기본 경로는 `DGSDK.dll`(Windows)로 하드코딩돼 있다.
> **팀원 개발 환경이 모두 Windows이므로 이는 실질적 제약이 아니다.**
> 다만 공식 패키지에는 `libs/libDGSDK.so`(Linux x86_64)도 함께 있고 래퍼가 OS를
> 자동 판별하므로, 이관하면 리눅스 장비(현재 이 학습용 PC)에서도 그대로 돌아간다는
> 부수 이득이 있다. 이관의 주된 근거는 어디까지나 위 세 가지다.

**갚는 법**: `uv`/pip로 `dgsdk` 패키지를 vision venv에 설치하고,
`dg5f_sdk_bridge.py`의 `Dg5fSdk` 클래스(98~157줄)를 `from dgsdk import DGSDK`로
교체. UDP 수신·슬루 리밋·미러 변환 로직은 그대로 두면 되므로 실작업은 클래스
하나 치환 수준이다.

### 부채 ② 실물 관절 대응이 미검증 — **안전 이슈**

브리지 51~58줄의 `JOINT_ORDER`(항등), `JOINT_SIGN`(전부 +1), `JOINT_OFFSET_DEG`
(전부 0)는 전부 **가정값**이다. 코드 주석에 명시돼 있다:

> ⚠️ 첫 실물 구동 전 필수 확인 (모르면 움직이지 말 것)
> 우리 채널과 실물 관절 번호·방향·영점 대응은 **미검증**

관절 순서나 부호가 틀린 채로 `MoveServoJoint`를 보내면 손가락이 리밋 방향으로
꺾일 수 있다. 지금은 아무도 실물을 돌리지 않아 드러나지 않은 부채다.

**갚는 법**: `--pose 6:20` 형식으로 한 관절씩 소각도 주입하며 20채널 대응표를
확정하고, 결과를 이 문서에 표로 남긴다. `--max-step`은 작게 유지.

### 부채 ③ SDK가 주는 피드백을 하나도 안 쓴다 — **기능 손실**

현재 파이프라인은 완전 **개루프**다. 각도를 던지기만 하고 아무것도 읽지 않는다.
쓰지 않고 있는 SDK 기능:

| 미사용 기능 | 쓸 수 있었던 곳 |
|---|---|
| `get_fingertip_sensor_data()` — 핑거팁 FT·촉각 센서 | 파지 성공 판정. 지금 Unity 학습은 접촉을 물리 콜라이더로 판정하는데, 실물에서는 이 센서가 그 역할을 한다 |
| `get_gripper_data()` — 관절 실제값·전류·에러코드 | 명령 대비 추종 오차 측정(현재 `analyze_teleop.py`가 Unity 로그로만 하는 일) |
| `grasp()` — 내장 파지 알고리즘 | 형상 무관 파지. 우리는 이걸 강화학습으로 재발명한 셈 |
| `manual_teach_mode()` | 시연 데이터 수집 → 모방학습 |

특히 **`grasp()` 내장 알고리즘의 존재는 발표에서 나올 만한 질문**이다
("SDK에 파지 기능이 있는데 왜 학습했나"). 답: 내장 파지는 손 단독의 정형 파지이고,
이번 과제는 **UR5e 팔 접근 궤적까지 포함한 파지+들어올리기**라 손만으로는 성립하지
않는다. 다만 이 비교를 실측으로 해 본 적은 없다.

### 부채 ④ ROS2 경로 미검토

Tesollo는 ROS2 패키지를 제공하고, 자사 텔레옵 레퍼런스도 ROS2 기반이다. 우리는
UDP 자체 프로토콜을 만들었다. 프로젝트 범위(Unity 트윈 단독)에서는 UDP가 더 단순해
합리적이지만, 실물 통합 단계에서는 재검토 대상이다.

### 부채 ⑤ 문서화 누락

`dg5f_sdk_bridge.py`는 `docs/WORKLOG.md`에 항목이 없다(grep 결과 0건). SDK 연동
결정이 코드 주석에만 남아 있어, 이번처럼 "왜 SDK를 안 썼냐"는 질문이 반복해서
발생한다.

---

## 4.5. 학습한 정책을 SDK로 실물에서 돌릴 수 있나

배경: 기업 요구는 "비전으로 실시간 제어·구동하는 시뮬레이션"이었고, 프로젝트 주제가
AI인데 AI가 없다는 문제 때문에 강화학습을 추가했다. 그렇다면 그 학습 결과물을
SDK 경로로 실물에 태울 수 있는가.

**결론: 손 쪽은 형식이 이미 맞아 있어 그대로 나간다. 막히는 건 SDK가 아니라
① 관측 입력(비전)과 ② 팔 제어 경로다.**

### (1) 출력 — SDK로 나가는 길은 이미 열려 있다

정책 출력은 7개다: 팔 6관절 증분 + **손 닫힘 1개**.

- **손**: 닫힘 값 0~1 → `LeftFistDeg`로 20관절 각도 보간 → `move_servo_joint(float[20])`.
  **브리지가 지금 텔레옵 패킷으로 하고 있는 것과 완전히 같은 형식**이다. 관절각[deg]
  20채널이라는 계약을 처음부터 SDK 규격에 맞춰 잡아 둔 것이 여기서 값을 한다.
- 손가락 20개를 개별 출력하지 않고 **닫힘 스칼라 1개로 묶은 설계가 실물 이식에서
  유리**하다. 정책이 물리적으로 불가능한 손 모양을 만들 여지가 구조적으로 없다.
- **팔 6개는 SDK 범위 밖이다.** UR5e 컨트롤러(RTDE `servoJ` 등)가 따로 필요하며,
  저장소에 실물 팔 제어 코드는 없다(grep 확인).

### (2) 입력 — 여기가 진짜 벽

정책은 매 스텝 57개 관측을 요구한다. 실물에서 각각을 어디서 얻을 수 있는지:

| 관측 | 개수 | 실물 조달처 | 가능? |
|---|---:|---|:--:|
| 팔 관절 각도·속도 | 12 | UR5e 컨트롤러 | ✅ |
| 팔 명령각 | 6 | 우리가 보낸 값 | ✅ |
| 손 닫힘 | 1 | 우리가 보낸 값 | ✅ |
| 손끝 접촉 플래그 | 6 | **SDK `get_fingertip_sensor_data()`** | ✅ |
| 손끝 위치(블록 기준) | 15 | URDF 순기구학 + 블록 자세 | ⚠️ 블록 자세 필요 |
| **블록 상대위치·속도·각속도·상승높이** | **10** | **비전(3D 물체 자세 추정)** | ❌ **없음** |
| 과제 진행 상태 | 7 | 위 값들에서 계산 | ⚠️ 파생 |

**57개 중 약 10개가 비전 의존이고, 지금 저장소에 카메라 수신 코드가 없다**
(README에 "카메라 수신 코드는 아직 포함하지 않는다"고 명시).

여기서 구조적으로 주목할 점: **AI가 없다는 문제를 풀려고 넣은 강화학습이,
실물로 나가려면 기업이 원래 요구했던 바로 그 비전을 다시 요구한다.** 두 요구는
서로 다른 일이 아니라 같은 파이프라인의 앞뒤였다.

### (3) 실행 배선

배포 모델 `DG5FGraspLift.onnx`의 시그니처를 확인했다:

```
입력  obs_0                            [batch, 57]
출력  deterministic_continuous_actions [batch, 7]
```

표준 ONNX이므로 `onnxruntime`으로 Python에서 10 Hz 추론이 가능하다. Unity를
띄우지 않아도 된다.

```
비전(미구현) ─┐
UR5e 상태 ────┼→ 관측 57개 조립 → onnxruntime(ONNX) → 행동 7개
SDK 센서 ─────┘                                        ├→ 팔 6개 → UR5e RTDE (미구현)
                                                       └→ 손 1개 → 20각도 → SDK (구현됨)
```

### (4) 남는 sim-to-real 간극

- **관측 노이즈**: 시뮬은 물체 자세를 오차 0으로 준다. 실물 비전은 노이즈와 지연이
  있는데, **도메인 랜덤화를 하지 않았으므로 정책이 이에 강건한지는 미검증**이다.
- **물체 물성**: 학습은 밀도 1800 kg/m³, 무게중심을 아래로 낮춘 블록을 가정했다.
  균일 밀도에서 99.24%가 나온 것은 확인했지만, 실물 마찰 계수는 별개 문제다.
- **구동 특성**: Unity `xDrive` PD와 실물 조인트 PID 게인이 다르다.
- **안전**: 부채 ②(관절 대응 미검증)가 선행 조건이다.

### (5) 현실적인 단계

| 단계 | 내용 | 필요한 것 |
|---|---|---|
| **A** | 팔은 고정/수동, **손 닫힘만 정책으로 SDK 구동** | 부채 ②만 해결하면 됨 |
| **B** | 블록 자세를 비전 대신 **ArUco 마커나 고정 지그**로 공급 | 비전 파이프라인 없이 관측 채우기 |
| **C** | 실제 3D 비전 + UR5e RTDE까지 전체 통합 | 기업 원래 요구의 완성형 |

A는 지금 자산만으로 "학습한 정책이 실물 손을 움직인다"를 시연할 수 있는 최소
경로다. B는 비전 개발 없이 파지 전체를 실물에서 재현해 보는 우회로다.

---

## 5. 권고 순서

1. **문서 정정** — "SDK 미사용"이 아니라 "SDK는 출력 계층에서 사용 중, 입력 계층은
   MediaPipe"임을 README와 WORKLOG에 명시. (비용 거의 0, 오해 재발 차단)
2. **공식 `dgsdk` 패키지로 브리지 이관** — SDK 버전업에 안전해지고, 센서·상태
   API가 한꺼번에 열린다. (부수적으로 리눅스 장비에서도 실행 가능해진다)
3. **실물 관절 대응 검증** — 안전 이슈이므로 실물 구동 전 필수.
4. **핑거팁 센서 피드백 도입 검토** — 개루프 탈출. 학습 정책의 실물 이식 시 필요.

---

## 참고 자료

- [DG-5F | Humanoid Robotic Hand for Dexterous Manipulation (Tesollo)](https://en.tesollo.com/dg-5f/)
- [TESOLLO: Maximize Robot Dexterity with MANUS & Franka Robot Arm (MANUS use case)](https://www.manus-meta.com/use-cases/tesollo-maximize-robot-dexterity-with-manus-franka-robot-arm)
- [TESOLLO unveils dexterous robot hand for humanoids (The Robot Report)](https://www.therobotreport.com/tesollo-unveils-dexterous-robot-hand-for-humanoids/)
- 회사 제공: `Delto_Gripper_Manager_and_SDK_User_Manual_ver_2_0_0_KR.pdf`, `dg_python-main`, `DGSDKSample_ver_2_0_1`
