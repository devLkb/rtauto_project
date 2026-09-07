# 실물 하드웨어 브리지 모듈 설명

브리지는 Unity·비전 프로그램의 관절 명령을 장비가 이해하는 통신으로 바꾸는 Python 프로그램이다.
반대로 장비에서 읽은 실제 관절각을 Unity로 보내면 화면의 로봇이 실물을 따라간다. 이때 화면 속 로봇을
**디지털 트윈**이라고 부른다. 브리지 자체는 물체를 인식하거나 파지 동작을 계획하지 않는다.

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

- 브리지의 UDP 관절 명령은 **deg(도)**다. 팔 RTDE는 rad(라디안)를 사용해 브리지에서 변환한다.
  비전 내부 계산과 Unity 물리 관절의 현재값에도 rad가 있으므로 저장소 전체가 deg인 것은 아니다.
- Unity UI는 자신이 관리하는 구동 방향을 전환한다. 외부 웹캠 송신까지 막지는 않으며,
  웹캠과 손 피드백을 동시에 UDP 5006으로 보내면 Unity에서 입력이 섞인다.
- 브리지를 실행하는 것과 장비에 연결하는 것은 다르다. 두 구동 브리지 모두 `--ip` 생략 시
  **드라이런**이다. 값 없이 `--ip`만 주면 `.env`의 장비 IP를 사용한다. 실물 접속 전에는
  [설정 문서](BUILD_TOOLING.md)의 장비 IP와 브리지 PC IP를 구분한다.

## 1. 팔 — `arm/ur_rtde_bridge.py`

UR16e(또는 URSim 가상 컨트롤박스)와 붙는 브리지.

```text
Unity UrArmSender.cs ──UDP 5009──> 이 브리지 ──ur_rtde servoJ()──> URSim / 실물 UR16e
Unity UrArmReceiver.cs <──UDP 5010── 이 브리지(--echo-to-unity) <──RTDE getActualQ()──┘
```

- 패킷: float32 × 6, 관절각[deg]. 순서는 `[shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]`.
- 인자 없이 실행하면 **드라이런** — 로봇에 붙지 않고 수신값만 출력한다(배선 검증용).
- 펜던트에서 Local↔Remote를 전환하면 로봇에 올려둔 제어 스크립트가 종료될 수 있는데,
  그때 **Unity→로봇 방향만 조용히 멈추고 읽기는 계속 살아 있어서** "URSim→Unity는 되는데 반대만 안 된다"로
  보인다. 브리지는 제어 명령 실패를 감지해 재접속을 시도한다. 로봇의 Remote 설정·접속 가능한
  네트워크가 전제이며, 모든 연결 장애가 자동 복구된다는 보장은 아니다.

**관련 파일**

| 파일 | 하는 일 |
|---|---|
| `arm/run_ursim.sh` / `run_ursim.ps1` | URSim 도커 컨테이너 실행. RTDE 포트(30001-30004)를 반드시 게시해야 한다 — 공식 예시는 5900/6080만 열어 RTDE가 막힌다. 펜던트 화면은 `http://localhost:6080/vnc.html` |
| `unity/Assets/Scripts/UrArmBridgeLauncher.cs` | Unity에서 **버튼 하나로** 이 브리지를 띄우고 내린다. 터미널을 따로 열어 venv를 켤 필요를 없앤다. Play를 멈추면 반드시 프로세스를 죽인다(살아남으면 포트를 쥐고 있고, 더 나쁘게는 계속 명령을 보낸다) |

## 2. 손 — Tesollo DG-5F 브리지 3종

실시간 구동은 `dg5f_sdk_bridge.py`, 자세 캡처·별도 읽기 실험은 `dg5f_readback_bridge.py`를 사용한다.
`dg5f_modbus_readback.py`는 과거 통신 조사 기록이다.

### `vision/dg5f/dg5f_sdk_bridge.py` — 현재 구동 경로

```text
vision_node_dg5f.py --bridge ──UDP 5008──> 이 브리지 ──DGSDK.dll(ctypes)──> 실물 DG-5F
                 관절 명령 처리 뒤에만 --echo-to-unity ──UDP 5006──> Unity 트윈
```

- 패킷 `[0..19]` 관절각[deg]을 그대로 실물 20모터에 중계한다(SDK도 20채널·deg라 1:1).
- SDK 호출 순서: `SetGripperSystem → ConnectToGripper → SetGripperOption → SystemStart`,
  실시간 구동은 `MoveServoJoint(float[20])` (DEVELOPER 모드 전용).
- 인자 없이 실행하면 **드라이런**(DLL 미사용, 수신값만 출력).
- 관절 대응(순서·부호·오프셋·클램프)은 2026-08-31 실물 실측으로 확정됐다 — 항등 대응, 부호 전부 +1,
  오프셋 0, 채널별 실제 가동범위로 클램프.
- 실물로 나가는 명령에는 브리지의 하드웨어 리밋 제한·속도 제한이 적용된다.
  Unity에도 별도의 제한이 있지만 실물 검증을 대신하지 않는다.

### 알려진 제한 — 손 real→sim은 현재 완료된 기능으로 취급하지 않는다

2026-09-07 코드 대조 기준, Unity에서 `real→sim`을 선택하면 브리지에 교시 모드를 요청한다.
교시 모드는 손에 힘을 풀어 사람이 자세를 잡게 하는 기능이다. **물건을 쥔 채 전환하면 놓칠 수 있다.**
그런데 현재 브리지 반복문은 교시 중 관절 패킷을 건너뛰고, 패킷이 없어도 즉시 대기로 돌아간다.
실제각 읽기·echo는 그 뒤에 있어 **교시 중에는 실행되지 않는다**.

따라서 `--echo-to-unity`만 붙이면 교시 중 실물 손을 계속 따라온다고 기대하면 안 된다.
sim→real 진입 전 자세 동기화도 피드백을 못 받으면 시간 초과 후 진행할 수 있다.
UI의 방향 표시만으로 동기화나 장비 모드 전환 성공을 판단하지 말고 브리지 로그를 함께 확인한다.
이 제한은 이번 문서 수정에서 발견 상태를 기록한 것이며, 코드 수정·실물 재검증은 완료되지 않았다.

근거: [SDK 브리지의 main 반복문](../../vision/dg5f/dg5f_sdk_bridge.py),
[Unity의 SetMode·EnterSimToReal](../../unity/Assets/MLAgents/picknplace/Runtime/Dg5fTwinModeSwitcher.cs).

### `dg5f_readback_bridge.py` — 읽기 전용 실험

실물이 **누구에 의해 움직이든**(테솔로 공식 DGManager, 수기 조그 등) 실제 관절각을 읽어 Unity에 반사하려던 것.
`GetReceivedGripperData()`를 이 저장소에서 처음 바인딩한 코드.

### `dg5f_modbus_readback.py` — 실패로 결론난 조사

DGSDK를 쓰지 않고 표준 Modbus TCP로 직접 관절값을 읽으려 한 두 번째 시도.

> ⚠️ **두 실험의 결론(2026-08-31 실물 실측): 동시 접속 불가.**
> DGManager를 켜둔 채로는 개발자모드 SDK 경로도, 사용자모드 Modbus 경로도 붙지 않는다.
> 이 그리퍼는 **프로토콜·제어모드와 무관하게 TCP 세션을 전체에서 1개만 받는다.**
> 따라서 실물을 쓰려면 둘 중 하나를 택해야 한다:
>
> - SDK 브리지를 유일한 클라이언트로 사용한다. 관절 명령 처리 후 echo는 가능하지만 교시 중 피드백에는 위 제한이 있다.
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
