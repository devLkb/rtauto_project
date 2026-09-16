# 실물 하드웨어 브리지 모듈 설명

> 실물 그리퍼 관절이 **각각 몇 도까지 움직이는지**와 **어느 쪽이 플러스인지**는
> [`DG5F_JOINT_RANGES.md`](DG5F_JOINT_RANGES.md)에 제조사 설명서 기준으로 정리돼 있다.

**브리지**는 Unity 나 비전 프로그램이 "이 관절을 이만큼 움직여라"라고 한 것을 **장비가 알아듣는
말로 바꿔 전달하는 파이썬 프로그램**이다. 통역이라고 보면 된다.

반대 방향도 한다. 장비에서 "지금 실제로 이 각도에 있다"를 읽어 Unity 로 보내면, 화면 속 로봇이
실물을 그대로 따라 움직인다. 이렇게 **실물과 똑같이 움직이는 화면 속 로봇**을 디지털 트윈이라고 부른다.

브리지는 통역만 한다 — **물체를 알아보거나 어떻게 잡을지 정하지는 않는다.**

## 먼저 확인할 입력·출력과 현재 범위

| 대상 | 입력 | 장비로 보내는 것 | Unity로 돌려주는 것 |
|---|---|---|---|
| 팔 브리지 | Unity의 팔 6관절 목표각 | RTDE `servoJ` 명령 | `--echo-to-unity` 사용 시 실제 6관절각. 입력이 없어도 주기적으로 읽음 |
| 손 SDK 브리지 | Unity 또는 비전의 손 20관절 목표각 | DGSDK의 서보 명령 | `--echo-to-unity` 사용 시 **관절 명령 처리 뒤에만** 실제각을 읽음 |

아래는 연결 구조다. **손의 역방향 피드백에는 현재 구현 제한이 있으므로 §2를 먼저 확인한다.**

```text
Unity ──UDP(관절각[deg])──> 브리지(파이썬) ──장비 SDK/프로토콜──> 실물
Unity <──UDP(실제 관절각)── 브리지 --echo-to-unity  <──상태 읽기──┘
```

- 브리지가 주고받는 각도는 **도(°)** 단위다. 팔 쪽 장비는 라디안이라는 다른 단위를 쓰는데,
  **그 변환은 브리지가 혼자 책임진다.** 다만 비전 계산 내부와 Unity 관절의 현재값에도 라디안이
  섞여 있어서 **저장소 전체가 도(°)인 것은 아니다** — 값을 옮길 때 단위를 확인한다.
- Unity UI는 자신이 관리하는 구동 방향을 전환한다. 외부 웹캠 송신까지 막지는 않으며,
  웹캠과 손 피드백을 동시에 UDP 5006으로 보내면 Unity에서 입력이 섞인다.
- **브리지를 켜는 것과 장비에 실제로 연결되는 것은 다른 일이다.** 두 브리지 모두 `--ip` 를
  빼고 실행하면 **연습 모드**로 돈다 — 장비에 붙지 않고 받은 값을 화면에 찍기만 한다.
  `--ip` 를 값 없이 주면 `.env` 에 적힌 장비 주소를 쓴다. 실물에 붙이기 전에
  [설정 문서](BUILD_TOOLING.md)에서 **장비 주소와 브리지를 돌리는 PC 주소를 헷갈리지 않게** 확인한다.

## 1. 팔 — `arm/ur_rtde_bridge.py`

UR16e(또는 URSim 가상 컨트롤박스)와 붙는 브리지.

```text
Unity UrArmSender.cs ──UDP 5009──> 이 브리지 ──ur_rtde servoJ()──> URSim / 실물 UR16e
Unity UrArmReceiver.cs <──UDP 5010── 이 브리지(--echo-to-unity) <──RTDE getActualQ()──┘
```

- 패킷: float32 × 6, 관절각[deg]. 순서는 `[shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]`.
- 옵션 없이 실행하면 **연습 모드** — 로봇에 붙지 않고 받은 값만 화면에 찍는다(연결이 제대로
  됐는지 확인하는 용도).
- 펜던트에서 Local↔Remote를 전환하면 로봇에 올려둔 제어 스크립트가 종료될 수 있는데,
  그때 **Unity→로봇 방향만 조용히 멈추고 읽기는 계속 살아 있어서** "URSim→Unity는 되는데 반대만 안 된다"로
  보인다. 브리지는 제어 명령 실패를 감지해 재접속을 시도한다. 로봇의 Remote 설정·접속 가능한
  네트워크가 전제이며, 모든 연결 장애가 자동 복구된다는 보장은 아니다.

**관련 파일**

| 파일 | 하는 일 |
|---|---|
| `arm/run_ursim.sh` / `run_ursim.ps1` | 팔 시뮬레이터(URSim)를 띄운다. **30001~30004번 포트를 반드시 열어야 한다** — 제조사 공식 예시는 5900·6080 만 열어서, 그대로 따라 하면 브리지가 붙지 못한다. 실제 로봇에 달린 조작기 화면은 웹브라우저에서 `http://localhost:6080/vnc.html` 로 본다 |
| `unity/Assets/Scripts/UrArmBridgeLauncher.cs` | Unity 에서 **버튼 하나로** 이 브리지를 켜고 끈다. 터미널을 따로 열고 가상환경을 켜는 수고를 없앤다. ▶(Play) 를 멈추면 **반드시 같이 종료시킨다** — 살아남으면 포트를 붙잡고 있고, 더 나쁘게는 **로봇에 계속 명령을 보낸다** |

## 2. 손 — Tesollo DG-5F 브리지 3종

실시간 구동은 `dg5f_sdk_bridge.py`, 자세 캡처·별도 읽기 실험은 `dg5f_readback_bridge.py`를 사용한다.
`dg5f_modbus_readback.py`는 과거 통신 조사 기록이다.

> 🛑 **`vision/dg5f/dg5f_sdk_bridge_dgsdk.py` (2026-09-14 추가, 미검증) — 아래
> `dg5f_sdk_bridge.py`를 대체하는 코드가 아니다.** 벤더가 `DGSDK.dll`과 함께 제공한
> 공식 파이썬 래퍼(`dgsdk`, `vision/dg5f/vendor/dgsdk-python/`로 vendor 커밋)로 SDK
> 호출부만 바꾼 버전이며, 관절 대응·클램프·미러·슬루 리밋은 `dg5f_sdk_bridge.py`에서
> import해 그대로 공유한다(정본 하나 원칙). **그리퍼가 UR16e 팔에 물려 있어 배선을
> 풀 수 없는 동안 작성됐다 — 드라이런(`--ip` 생략)까지만 확인됐고 실물 재검증은
> 안 됐다.** 실물 연결에는 `--i-know-this-is-unverified` 플래그가 필수(안전 게이트).
> 배선을 풀 수 있게 되면 `--jog`/`--track`으로 재검증한 뒤에만 정식 구동 경로로
> 승격할지 판단한다. 그 전까지 실물 구동의 정본은 여전히 아래 `dg5f_sdk_bridge.py`다.
> 교체 검토 배경은 `docs/docs2/TESOLLO_SDK_기술부채_조사.md` 부채①.

### `vision/dg5f/dg5f_sdk_bridge.py` — 현재 구동 경로

```text
vision_node_dg5f.py --bridge ──UDP 5008──> 이 브리지 ──DGSDK.dll(ctypes)──> 실물 DG-5F
                 관절 명령 처리 뒤에만 --echo-to-unity ──UDP 5006──> Unity 트윈
```

- 받은 숫자 중 앞의 20개(관절 각도, 도 단위)를 **그대로 실물 모터 20개에 넘긴다.** 장비 쪽도
  20개·도 단위라 중간에 바꿀 게 없다.
- SDK 호출 순서: `SetGripperSystem → ConnectToGripper → SetGripperOption → SystemStart`,
  실시간 구동은 `MoveServoJoint(float[20])` (DEVELOPER 모드 전용).
- 옵션 없이 실행하면 **연습 모드**(장비 라이브러리를 아예 부르지 않고 받은 값만 화면에 찍는다).
- **관절을 어떻게 짝지을지는 2026-08-31 에 실물로 재서 확정했다** — 순서는 1번이 1번으로
  그대로, 방향 뒤집힘 없음, 더하거나 빼는 값 없음. 다만 **채널마다 실제로 움직일 수 있는 범위를
  넘지 못하게 잘라 낸다.**
- 실물로 나가는 명령에는 **각도 한계와 속도 한계가 걸린다.** Unity 안에도 따로 한계가 있지만,
  **그건 실물에서 확인한 것을 대신하지 못한다.**

### 알려진 제한 — 손 real→sim은 현재 완료된 기능으로 취급하지 않는다

2026-09-07 코드 대조 기준이다. Unity 에서 "실물 → 화면" 방향을 고르면 브리지가 손에게
**교시 모드**를 요청한다. 교시 모드는 **손의 힘을 빼서 사람이 손으로 직접 자세를 잡게 하는 기능**이다.
🛑 **물건을 쥔 상태에서 이걸 켜면 놓친다.**

문제는 여기다. 지금 브리지는 교시 중일 때 들어온 각도 명령을 건너뛰고, 명령이 없으면 곧바로
다시 기다리러 돌아간다. **실제 각도를 읽어서 Unity 로 보내는 부분이 그 뒤에 있어서, 교시 중에는
아예 실행되지 않는다.**

그래서 **`--echo-to-unity` 만 붙이면 교시 중에도 화면이 실물을 따라오리라 기대하면 안 된다.**
반대 방향("화면 → 실물")으로 들어가기 전에 자세를 맞추는 단계도, 되돌아오는 값을 못 받으면
**시간만 기다리다 그냥 진행해 버릴 수 있다.**

화면의 방향 표시만 보고 "맞춰졌다"고 판단하지 말고 **브리지가 찍는 글을 같이 본다.**
이 제한은 문서를 고치다 **발견해서 적어 둔 것**이고, 코드를 고치거나 실물로 다시 확인하지는 않았다.

근거: [SDK 브리지의 main 반복문](../../vision/dg5f/dg5f_sdk_bridge.py),
[Unity의 SetMode·EnterSimToReal](../../unity/Assets/MLAgents/picknplace/Runtime/Dg5fTwinModeSwitcher.cs).

### `dg5f_readback_bridge.py` — 읽기 전용 실험

실물 손이 **누가 움직이든 상관없이**(제조사 프로그램 DGManager 로 움직이든, 손으로 한 관절씩
돌리든) 지금 각도를 읽어서 화면에 비추려던 코드다. 장비 라이브러리의 값 읽기 기능을 이 저장소에서
처음 연결해 본 코드이기도 하다.

### `dg5f_modbus_readback.py` — 실패로 결론난 조사

DGSDK를 쓰지 않고 표준 Modbus TCP로 직접 관절값을 읽으려 한 두 번째 시도.

> ⚠️ **두 실험의 결론(2026-08-31 실물 실측): 동시 접속 불가.**
> DGManager를 켜둔 채로는 개발자모드 SDK 경로도, 사용자모드 Modbus 경로도 붙지 않는다.
> 이 손은 **어떤 방식으로 접속하든 통틀어 한 번에 한 프로그램만** 붙을 수 있다.
> 따라서 실물을 쓰려면 둘 중 하나를 택해야 한다:
>
> - **SDK 브리지 하나만** 붙인다. 명령을 처리한 뒤 실제 각도를 되돌려 보낼 수는 있지만,
>   교시 중에는 위에 적은 제한이 있다.
> - DGManager로 자세를 잡았다면 **DGManager 연결을 종료한 뒤**, readback 브리지의 `--ip`와 `--capture-pose`로 자세를 캡처한다.
>
> readback 파일은 자세 캡처에도 쓰인다. Modbus 파일은 평상시 구동 대상으로 안내하지 않는다.
> 배경 조사는 [`docs/docs2/TESOLLO_SDK_기술부채_조사.md`](../docs2/TESOLLO_SDK_기술부채_조사.md) 참고.

## 3. Unity 쪽 짝 컴포넌트

| Unity 컴포넌트 | 짝이 되는 브리지 |
|---|---|
| `UrArmSender.cs` / `UrArmReceiver.cs` + `UrArmTwinDriver.cs` | `arm/ur_rtde_bridge.py` |
| `Dg5fSender.cs` / `Dg5fReceiver.cs` + `Dg5fHandDriver.cs` | `vision/dg5f/dg5f_sdk_bridge.py` |
| `Dg5fTwinModeSwitcher.cs` | 방향 전환 버튼. 브리지에 제어 패킷(`DG5FMODE` + 모드 바이트)을 보내 실물 교시 모드까지 함께 바꾼다. 관절 패킷과는 **길이로 구분**되어 섞이지 않는다 |
| `PicknPlaceArmJointPanel.cs` | 팔 조작 + URSim 연동 방향 선택을 한 패널에 통합 |

## 4. 정지·연결 해제의 의미와 문제 확인

- `Dg5fSender.cs` / `UrArmSender.cs`는 **기본값이 꺼짐**이다. 실수로 씬을 Play했다고 실물이 움직이면 안 된다.
- 설정은 `.env`를 Python 설정 모듈과 C# 설정 어댑터가 각각 읽는다. C#이 Python을 거쳐 읽는 구조는 아니다.
- Unity 팔 런처는 자신이 실행한 팔 브리지를 Play 정지·종료 때 정리한다. 별도 터미널에서 띄운
  손 브리지나 웹캠까지 자동 종료하는 것은 아니다.
- 손 트윈의 **연결 끊기(Off)**는 Unity의 실물 명령 송신을 끄고 교시 해제를 요청한다.
  웹캠 미러링은 계속될 수 있고 SDK 프로세스·TCP 연결은 남아 있다. 별도 비전 프로그램이
  `--bridge`로 명령을 보내고 있다면 그 송신도 따로 멈춰야 한다.
- UDP가 끊기면 브리지는 새 목표를 보내지 않고 마지막 자세 유지 안내를 출력한다.
  이 처리를 비상정지나 전원 차단으로 해석하지 않는다. 정상 종료 시 손은 `SystemStop`·연결 해제,
  팔은 `servoStop`·제어 스크립트 정리를 시도한다.

| 증상 | 먼저 확인할 곳 |
|---|---|
| 수신값은 보이는데 실물이 안 움직임 | 브리지 로그의 드라이런 여부, 장비 IP, SDK/RTDE 연결·명령 실패 로그 |
| 브리지가 시작되지 않음 | UDP 포트 점유, 손 DLL 경로, DGManager 등 다른 장비 클라이언트의 접속 여부 |
| URSim→Unity만 되고 반대가 안 됨 | 펜던트 Remote 상태와 브리지의 제어 재접속 로그 |
| 손 교시 중 Unity가 안 따라옴 | 위 알려진 피드백 제한. 웹캠 패킷을 실물 피드백으로 오인하지 않을 것 |

URSim과 실물 UR16e는 검증 대상을 구분한다. 저장소의 과거 실측 결과·실물 미검증 항목은
[SIM2REAL_ROADMAP.md](../SIM2REAL_ROADMAP.md)에 기록되어 있으며, 이 문서의 코드 대조는 실물 재시험을 뜻하지 않는다.

## 5. 코드 레벨 핵심 — 인자·패킷·SDK 호출

### 5-1. 팔 브리지 `arm/ur_rtde_bridge.py`

```text
python arm/ur_rtde_bridge.py [--ip [주소]] [--listen 5009] [--hz 10]
                             [--max-deg-per-sec 30] [--max-step N]
                             [--lookahead-time 0.1] [--gain 300]
                             [--echo-to-unity [--echo-ip ... --echo-port 5010]]
```

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `--ip` | **없음 = 드라이런** | 값 없이 `--ip`만 주면 `.env`의 `RTAUTO_UR_IP` 사용 |
| `--listen` | `PORT_UR_ARM_BRIDGE`(5009) | Unity `UrArmSender`가 쏘는 포트 |
| `--hz` | 10 | `servoJ` 송신 상한 |
| `--max-deg-per-sec` | `RTAUTO_UR_MAX_DEG_PER_SEC`(30) | 속도 제한 → `--max-step`으로 환산 |
| `--lookahead-time` / `--gain` | 0.1 / 300 | `servoJ` 파라미터 (ur_rtde 권장 0.03~0.2 / 100~2000) |
| `--echo-to-unity` | off | `getActualQ()`를 읽어 `PORT_UR_ARM_SIM`(5010)으로 송신 |

- 상수: `N_JOINTS = 6`, `MIN_PACKET_BYTES = 24`(=4×6),
  `JOINT_NAMES = [shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]`.
- 단위 변환은 `deg_to_rad()`/`rad_to_deg()` 두 함수에만 있다 — **UDP는 deg, RTDE는 rad.**
- **재접속 로직의 핵심**: `servoJ()`는 성공/실패를 bool로 돌려준다. 반환값을 버리면 로봇이
  명령을 안 받는데도 조용히 도는 것처럼 보인다. `control_alive()`가 이를 감지해
  `connect_control()`을 `CONTROL_RETRY_SEC`(2.0초) 간격으로 재시도한다.
  펜던트 Local↔Remote 전환 시 "URSim→Unity만 되고 반대가 안 되는" 증상의 원인이 여기다.
- 읽기(`RTDEReceiveInterface`)와 쓰기(`RTDEControlInterface`)는 **별도 연결**이라
  제어가 끊겨도 echo는 계속 살아 있다.
- 종료 시 `servoStop()` + 제어 스크립트 정리를 시도한다.

### 5-2. 손 SDK 브리지 `vision/dg5f/dg5f_sdk_bridge.py`

```text
python vision/dg5f/dg5f_sdk_bridge.py [--ip [주소]] [--port 502] [--model 5f_right]
                                      [--listen 5008] [--dll ...] [--hz 50]
                                      [--max-deg-per-sec 100] [--lpf 0.3]
                                      [--echo-to-unity] [--jog IDX:DEG] [--pose ...]
```

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `--ip` | **없음 = 드라이런(DLL 미사용)** | 값 없이 주면 `.env`의 `RTAUTO_DG5F_IP` |
| `--port` / `--model` | 502 / `5f_right` | 모델 코드는 `MODELS` 딕셔너리(`DGDataTypes.h DG_MODEL`) |
| `--dll` | `.env`의 `RTAUTO_DG5F_DLL` 또는 상대경로 기본값 | `DGSDK.dll` |
| `--hz` / `--max-deg-per-sec` / `--lpf` | 50 / 100 / 0.3 | 송신 주기·속도 제한·저역통과 |
| `--gain-p/-d/-i/-ilimit` | 2.0 / 5.0 / 0.05 / 0.1 | 접속 시 설정하는 서보 게인 (`--no-set-gains`로 생략) |
| `--jog IDX:DEG` / `--jog-hold 1.5` | — | 관절 하나만 흔들어 실물 가동범위·부호를 실측 |
| `--echo-to-unity` | off | 실제각을 `PORT_DG5F_SIM`(5006)으로 |

**관절 대응 상수 3종**(2026-08-31 실물 실측으로 확정): `JOINT_ORDER = list(range(20))`(항등),
`JOINT_SIGN = [1.0]*20`, `JOINT_OFFSET_DEG = [0.0]*20`. 즉 순서·부호·오프셋 변환이 없다.
실물로 나가는 값을 실제로 자르는 것은 **`JOINT_CLAMP_RIGHT`** — 채널마다 실제로 움직일 수 있는
범위다.

> ✅ **2026-09-16 정리.** 예전에는 이 표가 `dg5f_angles.URDF_LIMITS_DEG`(화면 쪽 한계)와 한 채널
> (`middle_abd`)에서 달랐다. 제조사가 준 **설명서(±30°)와 URDF(±25°)가 서로 달랐기** 때문이다.
> 실측할 방법이 없는 동안에는 **좁은 쪽(±25°)** 을 쓰기로 하고 맞췄다 — 지금은 **관절 20개가
> 오른손 URDF 와 전부 일치한다.** 좌우 뒤집히는 6개 채널의 부호 차이는 규약대로다.
> 근거와 되돌리는 조건은 [`DG5F_JOINT_RANGES.md`](DG5F_JOINT_RANGES.md) §5.

**SDK 호출 순서**(`Dg5fSdk.connect()`):
`SetGripperSystem` → `ConnectToGripper` → `SetGripperOption` → `SystemStart`,
실시간 구동은 `MoveServoJoint(float[20])`. `CONTROL_MODE_DEVELOPER = 1`,
`COMMUNICATION_MODE_ETHERNET = 0`, 성공 코드는 `DG_RESULT_NONE = 0`.
수신 데이터 종류는 `receivedDataType[]`에 JOINT(0x01)·CURRENT(0x02)·MODULE_ERROR_CODE(0x07)를 등록한다.
ctypes 구조체(`GripperSystemSetting`·`GripperSetting`·`ReceivedGripperData` 등)는 **`DGDataTypes.h`
레이아웃 그대로**라 헤더가 바뀌면 여기도 같이 바꿔야 한다.

### 5-3. 모드 제어 패킷 — 관절 패킷과 길이로 구분한다

| 항목 | 값 |
|---|---|
| 매직 | `CONTROL_MAGIC = b"DG5FMODE"` (C#은 `Dg5fTwinModeSwitcher.ControlMagic`) |
| 페이로드 | 매직 + 1바이트: `0` = sim→real(교시 해제), `1` = real→sim(교시 ON) |
| 관절 패킷 | `MIN_PACKET_BYTES = 80`(=4×20) 이상 |
| 구분 방법 | `data.startswith(CONTROL_MAGIC)` — 9바이트 제어 패킷과 80바이트 이상 관절 패킷은 섞이지 않는다 |

실물 전환은 `sdk.dll.ManualTeachMode(1|0)`이다. 교시에서 빠져나올 때 `sdk.read()`로
현재 자세를 명령 기준으로 다시 잡는다 — 안 그러면 교시 전 마지막 명령으로 홱 되돌아간다.

⚠️ **§2의 제한이 나오는 지점이 정확히 여기다.** main 반복문이 교시 중에는 `continue`로
관절 패킷 처리를 건너뛰는데, 실제각 읽기·echo가 그 아래에 있어 **교시 중에는 실행되지 않는다.**
Unity 쪽 `syncTimeout`(2초)·`syncSettle`(0.8초)은 피드백이 없어도 시간이 지나면 진행한다.

### 5-4. readback 브리지 `dg5f_readback_bridge.py`

`bind_readback(dll)`이 `GetReceivedGripperData()`를 바인딩한다(이 저장소에서 처음 만든 바인딩).

| 인자 | 뜻 |
|---|---|
| `--capture-pose [파일]` | **자세 캡처 모드.** 파일 생략 시 `.env`의 `RTAUTO_DG5F_GRASP_POSE` |
| `--pose-name grasp` | 저장할 자세 이름(JSON `name` 필드) |
| `--teach` / `--rest` / `--rest-sec 2.0` | 교시 모드 진입 / 휴식 자세 / 대기 |
| `--control-mode developer\|operator` | 접속 모드 |
| `--probe` / `--probe-top 3` | 어느 데이터 슬롯이 실제 관절값인지 탐색 |
| `--fake` | 장비 없이 동작 확인 |
| `--send-ip` / `--send-port` / `--hz 30` | Unity 송신 대상(기본 `UNITY_IP` / 5006) |

캡처된 JSON은 `Dg5fFistButton.LoadGraspPose()`가 읽는다. 필드는 `name`·`hand`·`captured_utc`·
`source`·`convention`·`channels[20]`·`deg[20]`이고, **Unity가 실제로 검사하는 것은 `deg`의 길이가
20인지 하나뿐**이다(`channels`는 읽지 않는다). 파일이 없거나 길이가 다르면 예외를 던지지 않고
Console에 안내만 남긴 뒤 '파지하기' 버튼을 비활성화한다 — 자세 파일이 없다고 데모 씬이 죽으면 안 된다.

### 5-5. Unity 런처가 실제로 실행하는 명령 (`UrArmBridgeLauncher.cs`)

| 인스펙터 필드 | 기본값 |
|---|---|
| `scriptRelativePath` | `arm/ur_rtde_bridge.py` |
| `arguments` | `--ip --echo-to-unity` (값 없는 `--ip` = `.env`의 로봇 IP 사용) |
| `showWindow` | true |

파이썬 실행파일은 `.env`의 `RTAUTO_PYTHON`(`cfg.PYTHON_EXE`). `Launch()` 성공 여부는 `IsRunning`·
`Status`로 노출되고, Play 정지·`OnDestroy`에서 `Stop()`이 프로세스를 죽인다 —
살아남으면 포트를 쥐고 있고, 더 나쁘게는 계속 명령을 보낸다.
