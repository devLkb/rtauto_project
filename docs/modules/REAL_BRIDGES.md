# 실물 하드웨어 브리지 모듈 설명

시뮬레이션(Unity)과 실제 장비 사이를 잇는 코드. **디지털 트윈의 양방향 경로**가 여기서 만들어진다.

공통 구조가 하나 있다. 브리지는 전부 이 모양이다:

```text
Unity ──UDP(관절각[deg])──> 브리지(파이썬) ──장비 SDK/프로토콜──> 실물
Unity <──UDP(실제 관절각)── 브리지 --echo-to-unity  <──상태 읽기──┘
```

- 저장소 전체가 **각도는 deg**로 통일돼 있다. 라디안 변환은 브리지가 경계에서 전담한다.
- 송신·수신을 동시에 켜면 되먹임 루프가 되므로, Unity 쪽 모드 전환 UI가 방향을 상호배타로 강제한다.

## 1. 팔 — `arm/ur_rtde_bridge.py`

UR16e(또는 URSim 가상 컨트롤박스)와 붙는 브리지.

```text
Unity UrArmSender.cs ──UDP 5009──> 이 브리지 ──ur_rtde servoJ()──> URSim / 실물 UR16e
Unity UrArmReceiver.cs <──UDP 5010── 이 브리지(--echo-to-unity) <──RTDE getActualQ()──┘
```

- 패킷: float32 × 6, 관절각[deg]. 순서는 `[shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3]`.
- 인자 없이 실행하면 **드라이런** — 로봇에 붙지 않고 수신값만 출력한다(배선 검증용).
- 실행 순서는 상관없다. 펜던트에서 Local↔Remote를 전환하면 로봇에 올려둔 제어 스크립트가 죽는데,
  그때 **Unity→로봇 방향만 조용히 멈추고 읽기는 계속 살아 있어서** "URSim→Unity는 되는데 반대만 안 된다"로
  보인다. 브리지가 이 상태를 감지해 주기적으로 스스로 다시 붙으므로 재시작할 필요가 없다.

**관련 파일**
| 파일 | 하는 일 |
|---|---|
| `arm/run_ursim.sh` / `run_ursim.ps1` | URSim 도커 컨테이너 실행. RTDE 포트(30001-30004)를 반드시 게시해야 한다 — 공식 예시는 5900/6080만 열어 RTDE가 막힌다. 펜던트 화면은 `http://localhost:6080/vnc.html` |
| `unity/Assets/Scripts/UrArmBridgeLauncher.cs` | Unity에서 **버튼 하나로** 이 브리지를 띄우고 내린다. 터미널을 따로 열어 venv를 켤 필요를 없앤다. Play를 멈추면 반드시 프로세스를 죽인다(살아남으면 포트를 쥐고 있고, 더 나쁘게는 계속 명령을 보낸다) |

## 2. 손 — Tesollo DG-5F 브리지 3종

그리퍼 쪽은 사연이 있어서 파일이 셋이다. **결론부터: `dg5f_sdk_bridge.py`만 쓰면 된다.**

### `vision/dg5f/dg5f_sdk_bridge.py` — 현역 (약 52KB)

```text
vision_node_dg5f.py --bridge ──UDP 5008──> 이 브리지 ──DGSDK.dll(ctypes)──> 실물 DG-5F
                                이 브리지 --echo-to-unity ──UDP 5006──> Unity 트윈
```

- 패킷 `[0..19]` 관절각[deg]을 그대로 실물 20모터에 중계한다(SDK도 20채널·deg라 1:1).
- SDK 호출 순서: `SetGripperSystem → ConnectToGripper → SetGripperOption → SystemStart`,
  실시간 구동은 `MoveServoJoint(float[20])` (DEVELOPER 모드 전용).
- 인자 없이 실행하면 **드라이런**(DLL 미사용, 수신값만 출력).
- 관절 대응(순서·부호·오프셋·클램프)은 2026-08-31 실물 실측으로 확정됐다 — 항등 대응, 부호 전부 +1,
  오프셋 0, 채널별 실제 가동범위로 클램프.
- 실물 쪽 안전장치(하드웨어 리밋 클램프·속도 제한)는 Unity가 아니라 **이 브리지**가 담당한다.

### `dg5f_readback_bridge.py` — 읽기 전용 실험

실물이 **누구에 의해 움직이든**(테솔로 공식 DGManager, 수기 조그 등) 실제 관절각을 읽어 Unity에 반사하려던 것.
`GetReceivedGripperData()`를 이 저장소에서 처음 바인딩한 코드.

### `dg5f_modbus_readback.py` — 실패로 결론난 조사

DGSDK를 쓰지 않고 표준 Modbus TCP로 직접 관절값을 읽으려 한 두 번째 시도.

> ⚠️ **두 실험의 결론(2026-08-31 실물 실측): 동시 접속 불가.**
> DGManager를 켜둔 채로는 개발자모드 SDK 경로도, 사용자모드 Modbus 경로도 붙지 않는다.
> 이 그리퍼는 **프로토콜·제어모드와 무관하게 TCP 세션을 전체에서 1개만 받는다.**
> 따라서 실물을 쓰려면 둘 중 하나를 택해야 한다:
> - `dg5f_sdk_bridge.py --echo-to-unity` — 우리 쪽이 **유일한** 실물 클라이언트가 되어 조종·읽기·Unity 반사를 모두 겸한다 (권장)
> - DGManager로 자세를 잡은 뒤 `dg5f_readback_bridge.py --capture-pose`로 스냅샷만 캡처
>
> 두 파일은 이 결론의 **근거 기록**으로 남아 있는 것이지, 평상시 실행 대상이 아니다.
> 배경 조사는 [`docs/docs2/TESOLLO_SDK_기술부채_조사.md`](../docs2/TESOLLO_SDK_기술부채_조사.md) 참고.

## 3. Unity 쪽 짝 컴포넌트

| Unity 컴포넌트 | 짝이 되는 브리지 |
|---|---|
| `UrArmSender.cs` / `UrArmReceiver.cs` + `UrArmTwinDriver.cs` | `arm/ur_rtde_bridge.py` |
| `Dg5fSender.cs` / `Dg5fReceiver.cs` + `Dg5fHandDriver.cs` | `vision/dg5f/dg5f_sdk_bridge.py` |
| `Dg5fTwinModeSwitcher.cs` | 방향 전환 버튼. 브리지에 제어 패킷(`DG5FMODE` + 모드 바이트)을 보내 실물 교시 모드까지 함께 바꾼다. 관절 패킷과는 **길이로 구분**되어 섞이지 않는다 |
| `PicknPlaceArmJointPanel.cs` | 팔 조작 + URSim 연동 방향 선택을 한 패널에 통합 |

## 4. 안전 관례

- `Dg5fSender.cs` / `UrArmSender.cs`는 **기본값이 꺼짐**이다. 실수로 씬을 Play했다고 실물이 움직이면 안 된다.
- IP·포트를 코드에 적지 않는다. 전부 `.env` → `config/rtauto_config.py` → (C#은) `RtautoConfig.cs`.
- 브리지 프로세스가 살아남으면 UDP 포트를 계속 쥐어 다음 실행이 바인드 실패로 죽는다. Unity 런처는
  Play 정지·종료 양쪽에서 정리한다.
