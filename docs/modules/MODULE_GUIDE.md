# 모듈 지도 (MODULE_GUIDE)

이 프로젝트를 처음 맡는 사람을 위한 입구다. 코드를 읽지 않고도 **각 덩어리가 무엇을 받아
무엇을 만들고, 로봇을 실제로 움직이는 게 누구이며, 어디까지 만들어졌는지** 알 수 있게 하는 것이
목표다. 각 문서는 앞부분이 "무슨 일을 하고 무엇과 이어지는가", 뒷부분이 "어느 파일이 그걸 하는가"다.

> 🔶 **2026-09-16 정정 — `modules/` 전체에 해당한다.** 이 폴더의 문서들은 **2026-09-07** 에
> 코드를 하나씩 대조해 쓰였다. 그 이틀 뒤인 **2026-09-09 에 물체를 잡는 학습이 Unity 에서
> SuperDex 로 옮겨갔다.** 그래서 아래에서 학습을 Unity 일로 설명하는 부분은 **그때의 사실**이다.
> 지금 새로 학습하려면 [`SUPERDEX_POC_PLAN.md`](../SUPERDEX_POC_PLAN.md)를 본다.
> 나머지(Unity 화면·손동작 조작·장비 연결·설정)는 그대로 유효하다.

- 2026-09-07 에 저장소의 **코드와 씬 설정을 읽어서** 맞춘 내용이다. 실물 로봇으로 다시 시험했다는
  뜻도, 새 학습 결과의 성능을 확인했다는 뜻도 아니다.
- 지금 무엇이 이어져 있고 무엇이 안 되는지는 이 문서와 `modules/` 를 먼저 본다. 설계가 왜 바뀌어
  왔는지와 앞으로의 계획은 [`SIM2REAL_ROADMAP.md`](../SIM2REAL_ROADMAP.md), 실행 명령은 각 README 다.
  **옛 기록에 적힌 "현재"를 오늘의 상태로 읽지 않는다.** 계획된 기능을 다 만들어진 것으로 읽지도 않는다.
- 코드를 고치면 역할뿐 아니라 **무엇이 들어가고 나오는지, 누가 로봇을 움직일 권한을 갖는지,
  설정이 언제 반영되는지, 아직 안 되는 게 무엇인지**도 같이 고친다.

## 처음 읽는 순서

1. 이 페이지에서 전체 흐름과 지금 할 수 있는 범위를 읽는다.
2. [Unity](UNITY.md) 에서 화면의 자동/수동 전환, 실물과 주고받는 방향, 주먹 버튼이 각각 무엇을
   바꾸는지 확인한다.
3. 웹캠으로 손을 따라 하게 하는 것은 [비전](VISION_TELEOP.md), 실제 장비에 붙이는 것은
   [브리지](REAL_BRIDGES.md) 로 이어 읽는다.
4. 로봇이 스스로 잡는 쪽을 이해하려면 [Unity 안의 학습](RL_TRAINING.md) 에서 **그 프로그램이 매 순간
   무엇을 받아 보는지**와 **무엇을 성공으로 치는지**를 읽는다.
5. 새 컴퓨터에 옮기거나 설정·모델을 바꿀 때는 [설정·빌드](BUILD_TOOLING.md) 에서 설정이 어디 있고
   무엇을 다시 만들어야 하는지 확인한다.

## 영역별 문서

| 문서 | 다루는 범위 | 코드 위치 |
|---|---|---|
| [UNITY.md](UNITY.md) | Unity 안에서 도는 C# 전부 — 로봇 움직이기, 손동작 받기, 화면 단추, 에디터 도구 | `unity/Assets/**` |
| [RL_TRAINING.md](RL_TRAINING.md) | Unity 안에서 하던 학습 — 무엇을 보고, 무엇을 움직이고, 무엇에 점수를 주는가 + 학습 실행·감시 스크립트 | `unity/Assets/MLAgents/**`, `training/**` |
| [VISION_TELEOP.md](VISION_TELEOP.md) | 웹캠 → 사람 손 인식 → 로봇 손 20관절 각도 → 전송, 그리고 카메라 맞추기 | `vision/**` |
| [REAL_BRIDGES.md](REAL_BRIDGES.md) | 실제 장비에 붙는 연결 프로그램 — UR16e 팔, DG-5F 손 | `arm/**`, `vision/dg5f/*bridge*.py` |
| [BUILD_TOOLING.md](BUILD_TOOLING.md) | 설정이 어디 있나, 로봇 모델 만들기·불러오기, 실행파일 묶기·방화벽 | `config/`, `urdf/`, `tools/`, `build-support/` |
| [DG5F_JOINT_RANGES.md](DG5F_JOINT_RANGES.md) | 실물 손 관절 20개가 어디까지 움직이는가 (제조사 설명서 정리) | `vision/dg5f/`, `urdf/dg5f/` |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 위 내용을 **그림 9장**으로 — 연결·권한·경계를 한눈에 | 전체 |

## 전체 흐름 (한 장 요약)

아래에서 `UDP`는 **프로그램끼리 값을 주고받는 통신 방식**이고, 숫자(5006 등)는 **받는 쪽을 구분하는
번호**다. 전화 내선번호라고 생각하면 된다.

```text
사람이 손으로 조작할 때
  웹캠 → 사람 손 인식 → 로봇 손 20관절의 목표 각도로 변환
                    ├─ 5006번 → Unity 가 받음 → 화면 속 손이 움직임
                    └─ 5008번 → 손 연결 프로그램 → 실물 손 (직접 구동을 켰을 때만)

학습과 자동 시연  ※ 아래는 Unity 안에서 학습하던 때의 배선이다
  Unity 안의 상태 ←→ 파이썬 학습 프로그램 → 학습 결과 파일(.onnx)
  그 파일을 지정한 Unity → 팔 6축 + 손 쥐기/펴기 1축 → 화면 속 관절 목표 각도

Unity 에서 실물 손 움직이기
  Unity 의 저장된 자세 → Dg5fSender → 5008번 → 손 연결 프로그램 → 실물 손
  Unity ← 5006번 ← 실물이 지금 실제로 있는 각도를 되돌려 보냄
                  (명령을 처리한 뒤에만 보낸다. 손으로 직접 끌어 움직이는 중에는 제한이 있다)

팔을 실물 또는 URSim(팔 시뮬레이터)에 연결
  Unity UrArmSender → 5009번 → 팔 연결 프로그램 → URSim / 실물 UR16e
  Unity UrArmTwinDriver ← 5010번 ← 팔이 실제로 있는 각도를 되돌려 보냄
```

화살표는 **연결할 수 있는 길**을 보여 줄 뿐, 전부 동시에 켜라는 뜻이 아니다.

- **웹캠 송신과 실물 손의 되돌려 보내기는 같은 5006번을 쓴다.** 둘을 동시에 켜면 값이 섞인다.
- 스스로 잡는 프로그램, 저장된 자세 버튼, 웹캠이 **모두 같은 관절에 명령**한다. 누가 우선인지는
  [Unity 문서의 권한 표](UNITY.md) 를 본다.
- 위 번호는 기본값이다. 설정은 [`.env.example`](../../.env.example) 과 `.env` 에 있고 파이썬과 C#
  이 각각 읽는다. **실행파일로 묶었을 때 두 쪽이 설정을 찾는 위치가 서로 다른 문제**가 아직
  남아 있다 → [설정 문서](BUILD_TOOLING.md).

## 지금 할 수 있는 일과 아직 안 되는 것

| 경로 | 지금 상태 |
|---|---|
| 웹캠 한 대 → Unity 손 | **된다.** 학습과는 상관없는 별도 길이다 |
| Unity 안의 학습·데모 | UR16e + 오른손으로 **잡고 들어 올리기**까지. 옮겨서 내려놓기는 없다. 저장된 데모 씬에서 자동 조작이 꺼져 있는 제한은 Unity 문서 참고 |
| Unity ↔ URSim 팔 | 양방향 코드가 있고 과거에 확인한 기록도 있다. **실물 UR16e 로 다시 확인한 것과는 구분**해서 읽는다 |
| 손을 명령대로 움직이고, 실제 각도를 되돌려 받기 | 된다. 단 **손으로 직접 끌어 움직이는 중에 실물→화면 반영은 코드 결함으로 아직 안 된다** |
| 카메라 여러 대로 손의 3차원 위치 잡기 | 별도로 실행하고 따로 맞춰야 한다. 지금 손동작 조작이나 학습에 자동으로 연결되지 않는다 |
| 카메라로 물체를 찾아 실물에서 스스로 잡기 | **안 된다.** 실물에서 값을 얻는 방법, 카메라와 로봇의 좌표 맞추기, 검증이 모두 남아 있다 |

지금 학습 프로그램은 **Unity 안에 있는 물체의 위치·속도·닿음 정보를 그대로 읽는다.** 웹캠으로
사람 손을 따라가는 기능이 이 값을 대신 만들어 주지 않는다. 실물 자세를 녹화해 둔 JSON 파일도
**사람이 누르는 버튼에만** 쓰이고 학습 결과를 바꾸지 않는다.
이 두 경계는 [학습 문서](RL_TRAINING.md) 와 [Unity 문서](UNITY.md) 에 더 자세히 있다.

## 지금 쓰는 것과 예전 것

한눈에 구분이 안 되는 게 이 저장소에서 가장 헷갈리는 지점이라 여기에 못박는다.

**지금 쓰는 것 (확정 하드웨어 = UR16e + DG-5F-M-R 오른손)**

- 물체 잡는 학습: **`superdex/`** — 2026-09-09 에 여기로 옮겼다. 파이썬 3.12 전용이라 가상환경이
  따로다(`superdex/.venv/`). 정본은 [`SUPERDEX_POC_PLAN.md`](../SUPERDEX_POC_PLAN.md)
- Unity 안의 학습(`unity/Assets/MLAgents/picknplace/**`, 이름표 `DG5FPicknPlace`) — **Unity
  계열에서는 가장 최신이지만 새 학습은 여기서 하지 않는다.** 데모 씬과 기존 결과 때문에 남아 있다
- 데모 씬: `unity/Assets/Scenes/Pipeline_Demo_GraspLift.unity`
- 손동작 조작: `vision/dg5f/vision_node_dg5f.py`(미리보기 창) / `dg5f_teleop_gui.py`(조절 패널)
- 팔 연결: `arm/ur_rtde_bridge.py` + URSim

**예전 것 — 참고로만 남아 있음**

- `unity/Assets/MLAgents/GraspLift/**` — UR5e + **왼손** 기준. picknplace 가 이걸 거의 그대로
  옮겨 온 것이라 코드가 쌍둥이다.
- `unity/Assets/Script/`(끝에 s 가 없는 쪽) — Rainbow Robotics 팔과 통신하던 코드. 지금 어디에도
  연결돼 있지 않은 과거 팀 시절 잔재.
- `vision/zed_object_detection/**` — **폐기.** ZED 카메라로 물체를 찾던 길. 어디에도 연결돼 있지
  않고 **Unity 에서 받던 쪽 파일도 이미 삭제됐다.** 되살리는 것을 전제하지 않는다
  ([비전 문서 §4](VISION_TELEOP.md)).
- `training/archives/**`, `docs/archives/**` — 폐기된 세대의 설정·문서.
- 주석과 문서에 남은 SVH(SCHUNK 손) 언급 — DG5F 이전에 쓰던 손. 코드는 대부분 지웠고 "이 방식은
  SVH 때 확인했다"는 유래 설명으로만 남아 있다.

## "그 값은 어느 파일에 있나"

각 문서 끝에 **"코드 레벨 핵심"** 절을 뒀다(클래스·함수 이름, 실행 옵션, 상수 실제값, 데이터 배치).
여기서는 자주 찾는 것만 한 줄로 건다. **문서에 적힌 숫자와 코드가 다르면 코드가 맞다.**

| 찾는 것 | 정본 파일 | 문서 |
|---|---|---|
| 번호·주소·경로 (모든 설정) | `config/rtauto_config.py` + 저장소 맨 위 `.env` | [BUILD_TOOLING §5-1, §5-3](BUILD_TOOLING.md) |
| 같은 설정을 읽는 C# 쪽 | `unity/Assets/Scripts/RtautoConfig.cs` | [BUILD_TOOLING §5-1](BUILD_TOOLING.md) |
| 손 20채널의 순서와 이름 | `vision/dg5f/dg5f_angles.py` 의 `CHANNEL_NAMES` / `DG5F_CHANNELS` | [VISION_TELEOP §6-1](VISION_TELEOP.md) |
| 사람 손 → 로봇 각도 변환 | `dg5f_angles.compute_raw()` → `map_to_dg5f()` | [VISION_TELEOP §6-1](VISION_TELEOP.md) |
| 주고받는 값의 순서(숫자 72개) | `dg5f_angles.PACKET_FMT` ↔ `unity/Assets/Scripts/Dg5fReceiver.cs` | [VISION_TELEOP 패킷 계약](VISION_TELEOP.md), [UNITY §9-1](UNITY.md) |
| 실물 손이 넘지 못하게 막아 둔 각도 | `vision/dg5f/dg5f_sdk_bridge.py` 의 `JOINT_CLAMP_RIGHT` | [REAL_BRIDGES §5-2](REAL_BRIDGES.md) |
| 팔의 속도·힘 한계 | `unity/Assets/Scripts/UrArmLimits.cs` | [UNITY §9-3](UNITY.md) |
| "무엇을 성공으로 치는가" | `unity/Assets/MLAgents/picknplace/Runtime/Dg5fPicknPlaceSpec.cs` | [RL_TRAINING §7-3](RL_TRAINING.md) |
| 학습 프로그램이 받아 보는 숫자 57개의 내용 | `Dg5fPicknPlaceAgent.CollectObservations()` | [RL_TRAINING §7-1](RL_TRAINING.md) |
| 내놓은 숫자 7개가 관절에 적용되는 방식 | `Dg5fPicknPlaceAgent.OnActionReceived()` | [RL_TRAINING §7-2](RL_TRAINING.md) |
| 학습을 어떻게 돌릴지 정한 값들 | `training/config/dg5f_picknplace.yaml` | [RL_TRAINING §7-6](RL_TRAINING.md) |
| 학습이 잘 됐는지 가르는 기준 | `training/scripts/picknplace_monitor.py` 의 `GATES` | [RL_TRAINING §7-5](RL_TRAINING.md) |
| 로봇을 움직일 권한을 바꾸는 코드 | `PicknPlaceControlModeSwitcher` · `Dg5fTwinModeSwitcher` · `Dg5fFistButton` | [UNITY §9-4](UNITY.md) |
| 씬·프리팹 생성기가 박아 둔 경로 | `PicknPlaceTrainingSceneBuilder` 의 `const` | [BUILD_TOOLING §5-6](BUILD_TOOLING.md) |

**반드시 두 곳을 같이 고쳐야 하는 짝** — 한쪽만 바꾸면 **에러도 안 나면서 조용히 어긋난다**:

- `dg5f_angles.CHANNEL_NAMES` ↔ `Dg5fHandDriver.JointLabels` — 손 20채널의 순서
- `config/rtauto_config.py` ↔ `RtautoConfig.cs` ↔ `BuildEnvironment.cs` — 설정을 읽는 세 군데
- `Dg5fPicknPlaceSpec.ArmLinks` ↔ `UrArmJointNames.Names` — 팔 관절 이름
  (Unity 쪽 코드 묶음끼리 서로를 참조하면 컴파일이 안 되므로 **일부러 중복시켜 둔 것**이다,
  [UNITY §7](UNITY.md))
- `dg5f_sdk_bridge.JOINT_CLAMP_RIGHT` ↔ `dg5f_angles.URDF_LIMITS_DEG` — 실물과 화면 각각의 한계값
