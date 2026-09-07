# `arm/` — UR16e 팔 연동 (RTDE 브리지 + URSim 실행)

Unity 안의 로봇 팔과 **실물 UR16e / URSim(가상 컨트롤박스)** 를 UDP ↔ RTDE로 잇는 폴더다.
이 폴더에는 로봇팔 제어에 필요한 것만 있고, 손(그리퍼)은 [`vision/dg5f/`](../vision/dg5f/README.md),
학습 정책은 [`training/`](../training/README.md)이 담당한다.

- **입력**: Unity `UrArmSender`가 UDP로 보내는 팔 6관절 **목표각[deg]**
- **출력**: RTDE `servoJ` 명령(rad) → URSim/실물 UR16e
- **역방향(선택)**: RTDE `getActualQ()`로 읽은 **실제 6관절각** → UDP → Unity `UrArmReceiver`

## 목차

1. [무엇을 위한 폴더인가](#1-무엇을-위한-폴더인가)
2. [데이터 흐름](#2-데이터-흐름)
3. [파일별 역할](#3-파일별-역할)
4. [코드 레벨 상세 — `ur_rtde_bridge.py`](#4-코드-레벨-상세--ur_rtde_bridgepy)
5. [따라 하기: URSim으로 왕복 트윈 띄우기](#5-따라-하기-ursim으로-왕복-트윈-띄우기)
6. [증상별 확인 순서](#6-증상별-확인-순서)
7. [관련 문서](#7-관련-문서)

## 1. 무엇을 위한 폴더인가

시뮬레이션(Unity)에서 만든 팔 동작을 **실제 로봇 컨트롤러가 이해하는 언어로 번역**하는 것이
브리지의 유일한 일이다. 브리지는 물체를 인식하지도, 경로를 계획하지도 않는다. 그래서
"Unity에서 팔이 움직이는데 실물이 안 움직인다"는 문제는 거의 항상 이 폴더 안에서 답이 난다.

**왜 URSim을 먼저 쓰는가.** 실물 UR16e를 매번 켜지 않고도 RTDE 계약(포트·명령·단위)을 그대로
검증할 수 있기 때문이다. URSim은 UR가 배포하는 도커 이미지이며, 실제 컨트롤박스와 같은
RTDE 인터페이스를 노출한다. 채택 배경은 [`docs/SIM2REAL_ROADMAP.md`](../docs/SIM2REAL_ROADMAP.md) §9.

## 2. 데이터 흐름

```text
[Unity]                          [arm/ur_rtde_bridge.py]                  [URSim / 실물 UR16e]
UrArmSender.cs  ──UDP 5009──▶  수신(deg) → 슬루 제한 → deg_to_rad ──servoJ()──▶  관절 구동
UrArmReceiver.cs ◀─UDP 5010──  송신(deg) ← rad_to_deg ←─────────── getActualQ() ←┘
                               (--echo-to-unity 옵션일 때만)
```

- **UDP는 deg, RTDE는 rad.** 변환은 `deg_to_rad()` / `rad_to_deg()` 두 함수에만 있다.
- 포트 기본값 5009/5010은 코드에 박힌 값이 아니라
  [`config/rtauto_config.py`](../config/README.md)의 `PORT_UR_ARM_BRIDGE` / `PORT_UR_ARM_SIM`이다(원칙 1).
- **읽기(RTDEReceiveInterface)와 쓰기(RTDEControlInterface)는 별도 연결**이다. 그래서 제어가
  끊겨도 echo는 계속 살아 있고, 그 결과 "URSim→Unity는 되는데 Unity→URSim만 안 된다"는
  증상이 나온다(§6).

## 3. 파일별 역할

| 파일 | 줄 수 | 역할 |
|---|---|---|
| `ur_rtde_bridge.py` | 351 | **본체.** UDP 수신 → 속도 제한 → `servoJ` 송신, 선택적 실제각 echo, 제어 링크 자동 재접속 |
| `run_ursim.sh` | 18 | URSim 도커 컨테이너 실행 (Linux/macOS, bash) |
| `run_ursim.ps1` | 19 | 같은 내용의 Windows PowerShell 판 |

### `run_ursim.sh` / `run_ursim.ps1` — 왜 스크립트로 두었나

UR 공식 예시는 `-p 5900:5900 -p 6080:6080`만 게시한다. 그러면 화면(VNC)은 보이는데
**RTDE 포트(30001-30004)가 막혀 브리지가 접속하지 못한다.** 이 스크립트는 그 포트를 함께
게시한 명령을 고정해 둔 것이다.

```bash
docker run --rm -it \
  -e ROBOT_MODEL=UR16 \
  -p 5900:5900 -p 6080:6080 -p 29999:29999 -p 30001-30004:30001-30004 \
  universalrobots/ursim_e-series
```

- 펜던트(로봇 조작 화면)는 브라우저에서 `http://localhost:6080/vnc.html`.
- ⚠️ 포트를 게시하면 시뮬 로봇이 LAN에 노출된다. 공용 네트워크에서는 방화벽을 확인한다.
- `.env`의 기본값 `RTAUTO_UR_IP=127.0.0.1`이 이 컨테이너를 가리킨다.

## 4. 코드 레벨 상세 — `ur_rtde_bridge.py`

### 4-1. 실행 인자

```text
python arm/ur_rtde_bridge.py [--ip [주소]] [--listen 5009] [--hz 10]
                             [--max-deg-per-sec 30] [--max-step N]
                             [--lookahead-time 0.1] [--gain 300]
                             [--echo-to-unity] [--echo-ip …] [--echo-port 5010]
```

| 인자 | 기본값 | 설명 |
|---|---|---|
| `--ip` | **생략 = 드라이런** | 값 없이 `--ip`만 주면 `.env`의 `RTAUTO_UR_IP` 사용. 드라이런은 RTDE에 붙지 않고 수신값만 출력한다(배선 검증용) |
| `--listen` | `PORT_UR_ARM_BRIDGE`(5009) | Unity `UrArmSender.bridgePort`와 **반드시 같아야 한다** |
| `--hz` | 10 | `servoJ` 송신 상한. Unity `UrArmSender.sendHz` 기본값 10과 짝 |
| `--max-deg-per-sec` | `.env` `RTAUTO_UR_MAX_DEG_PER_SEC`(30) | 관절 각속도 상한. `--max-step = 이 값 / --hz`로 환산된다 |
| `--max-step` | (자동 계산) | 틱당 관절 최대 변화량[deg]을 직접 지정. 주면 `--max-deg-per-sec`를 무시 |
| `--lookahead-time` | 0.1 | `servoJ` 파라미터. ur_rtde 권장 0.03~0.2 |
| `--gain` | 300 | `servoJ` 서보 게인. ur_rtde 권장 100~2000 |
| `--echo-to-unity` | off | `getActualQ()`를 읽어 Unity로 되돌려 보낸다 |
| `--echo-ip` / `--echo-port` | `.env` `RTAUTO_UNITY_IP` / 5010 | echo 대상 |

### 4-2. 상수와 패킷 계약

| 이름 | 값 | 의미 |
|---|---|---|
| `N_JOINTS` | 6 | 팔 관절 수 |
| `MIN_PACKET_BYTES` | 24 (= 4×6) | 이보다 짧은 UDP 패킷은 무시 |
| `JOINT_NAMES` | `["shoulder_pan","shoulder_lift","elbow","wrist_1","wrist_2","wrist_3"]` | 패킷 순서의 정본 |
| `CONTROL_RETRY_SEC` | 2.0 | 제어 링크 재접속 간격[초] |
| `STALE_AFTER_SEC` | 1.0 | 마지막 수신 후 이 시간이 지나면 "패킷 끊김"으로 판정 |

패킷은 **float32 little-endian × 6, 단위 deg**다. Unity `UrArmSender.cs` / `UrArmReceiver.cs`가
같은 형식을 쓴다.

### 4-3. 핵심 함수 — 왜 이렇게 되어 있나

| 함수 | 하는 일 | 없으면 생기는 문제 |
|---|---|---|
| `deg_to_rad(deg6)` / `rad_to_deg(rad6)` | 단위 변환의 **유일한 통로** | 변환이 여러 곳에 흩어지면 한 곳만 고쳐 조용히 어긋난다 |
| `connect_control(mod, ip, announce)` | `RTDEControlInterface` 접속 시도. 실패해도 예외로 죽지 않고 `None` 반환 | 브리지를 먼저 띄우고 펜던트를 Remote로 바꾸는 자연스러운 순서에서 매번 재시작해야 한다 |
| `control_alive(rtde_c)` | 제어 링크가 실제로 명령을 받는 상태인지 확인 | `isConnected()`가 True인데 명령만 안 먹는 상태에 갇힌다 |
| `control_ready(now)` | 죽은 제어 링크를 `CONTROL_RETRY_SEC` 간격으로 조용히 재접속. 성공 시 **슬루 기준점을 로봇의 현재 자세로 다시 잡는다** | 재접속 직후 옛 목표로 최고속 점프 |
| `echo_if_due(now)` | Unity 수신 여부와 **무관한 독립 타이머**로 실제각 송신 | 펜던트로 직접 조그할 때 Unity 트윈이 안 따라온다 |

**설계상 중요한 두 가지**

1. **UDP 소켓을 RTDE 연결보다 먼저 바인드한다.** 포트 점유 같은 실패는 로봇을 건드리기 전에
   나야 하기 때문이다(손 브리지 `dg5f_sdk_bridge.py`와 같은 규칙).
2. **슬루 기준점(`last_cmd`)은 반드시 로봇의 현재 자세로 시작한다.** 아니면 연결 즉시 첫 목표로
   서보 최고속 점프가 일어난다.
3. `servoJ()`의 **반환값(bool)을 버리지 않는다.** 버리면 로봇이 명령을 안 받는데도 정상처럼
   보인다. `force_control_reconnect` 플래그가 이때 세워진다.
4. "패킷 끊김"은 소켓 타임아웃 1회가 아니라 **마지막 수신 이후 경과 시간**으로 판정한다.
   타임아웃으로 판정하면 정상 송신 중에도 경고가 끝없이 찍힌다(2026-09-04 실제 증상).
   한 번도 받은 적이 없으면 아예 경고하지 않는다 — URSim→Unity 단방향 사용은 정상 상태다.

### 4-4. 종료 동작

정상 종료(`Ctrl+C`) 시 `servoStop()`을 부르고 로봇에 올라간 제어 스크립트를 정리한다.
UDP가 끊기면 **새 목표를 보내지 않고 마지막 자세를 유지**한다 — 비상정지가 아니다.

## 5. 따라 하기: URSim으로 왕복 트윈 띄우기

> Unity 조작 지침은 [`docs/modules/UNITY.md`](../docs/modules/UNITY.md)와
> [`unity/README.md`](../unity/README.md)를 함께 본다.

**터미널 1 (bash 또는 PowerShell, 리포 루트, URSim 컨테이너)**

```bash
bash arm/run_ursim.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File arm/run_ursim.ps1
```

- 정상이면 도커 로그가 흐르다 멈추고, 브라우저에서 `http://localhost:6080/vnc.html`에
  펜던트 화면이 뜬다. **이 터미널은 띄워 둔 채로** 다음 단계로 간다.
- 펜던트에서 전원 ON → 브레이크 해제 → 우상단 메뉴에서 **Remote Control**로 전환한다.
  Local이면 읽기만 되고 Unity→로봇 명령이 들어가지 않는다.

**터미널 2 (bash 또는 PowerShell, 리포 루트, 팔 브리지)** — venv 활성화를 반드시 포함한다.

```bash
source vision/.vision/bin/activate
python arm/ur_rtde_bridge.py --ip --echo-to-unity
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python arm/ur_rtde_bridge.py --ip --echo-to-unity
```

정상이면 아래와 같은 로그가 나온다.

```text
[슬루] 각속도 상한 30 deg/s @ 10 Hz → 틱당 3.00°
[연결] 127.0.0.1 RTDE 접속 시도 …
[연결] RTDE 읽기 접속 완료 / 제어 접속 완료
[수신] UDP :5009 대기 — Unity UrArmSender 송신 필요
[echo] 실제 관절각을 10 Hz로 Unity(127.0.0.1:5010)에 계속 보냅니다 …
```

- `제어 대기 — 2초마다 자동 재시도합니다`가 나오면 펜던트가 Local이거나 브레이크가 잠긴
  상태다. **브리지를 재시작할 필요 없이** 펜던트만 Remote로 바꾸면 붙는다.
- `[오류] UDP :5009 바인드 실패`는 같은 포트를 듣는 브리지가 이미 떠 있다는 뜻이다.
- 이 터미널도 **띄워 둔 채로** Unity를 실행한다. 종료는 `Ctrl+C`.

> Unity의 팔 패널에는 이 브리지를 버튼 하나로 띄우는 `UrArmBridgeLauncher`가 붙어 있다
> (기본 인자가 정확히 `--ip --echo-to-unity`다). 터미널 2를 대신할 수 있으며,
> Play를 멈추면 프로세스를 반드시 죽인다.

## 6. 증상별 확인 순서

| 증상 | 먼저 확인할 것 |
|---|---|
| Unity는 움직이는데 URSim이 안 움직임 | 브리지 로그가 드라이런인지(`--ip` 누락), 펜던트가 Remote인지, `[제어]` 재접속 로그 |
| URSim→Unity만 되고 반대가 안 됨 | 제어 링크만 죽은 상태. 읽기와 쓰기가 별도 연결이라 생기는 정상적인 증상(§2) |
| 브리지가 시작조차 안 됨 | UDP 5009 포트 점유, `pip install ur_rtde` 여부 |
| 팔이 홱 점프함 | 슬루 기준점 문제. `--max-deg-per-sec`를 낮추고 재접속 로그를 확인 |
| `[hold] 패킷 끊김`이 계속 뜸 | Unity 송신이 실제로 멈춰 있는지 확인. 단방향(echo 전용) 사용이라면 정상 |

## 7. 관련 문서

- [`docs/modules/REAL_BRIDGES.md`](../docs/modules/REAL_BRIDGES.md) — 팔·손 브리지 전체 설명(정본)
- [`docs/SIM2REAL_ROADMAP.md`](../docs/SIM2REAL_ROADMAP.md) §9 — URSim 선행 개발 경로 채택 근거
- [`config/README.md`](../config/README.md) — 포트·IP 설정의 정본
- [`unity/Assets/Scripts/README.md`](../unity/Assets/Scripts/README.md) — 짝이 되는 C# 컴포넌트

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- arm/README.md`
- **갱신 대상**: `arm/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/REAL_BRIDGES.md`, `unity/Assets/Scripts/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

