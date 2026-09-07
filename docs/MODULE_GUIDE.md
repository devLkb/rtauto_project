# 모듈 지도 (MODULE_GUIDE)

이 저장소에 있는 코드가 **각각 무슨 일을 하는지**를 파일 단위로 정리한 문서의 입구다.
"이 스크립트 왜 있는 거지?"가 생기면 여기서 해당 영역 문서로 간다.

- 이 문서는 **역할 설명**이다. 아키텍처 결정의 근거·일정·리스크는
  [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md)가 정본이고, 실행 절차는 각 README가 정본이다.
- 코드가 바뀌면 이 문서들도 함께 고친다. 특히 파일이 삭제/개명될 때.

## 영역별 문서

| 문서 | 다루는 범위 | 코드 위치 |
|---|---|---|
| [modules/UNITY.md](modules/UNITY.md) | Unity 안에서 도는 모든 C# — 로봇 구동, 텔레옵 수신, 데모 HUD, 에디터 툴 | `unity/Assets/**` |
| [modules/RL_TRAINING.md](modules/RL_TRAINING.md) | 강화학습 에이전트(보상·관찰·행동) + 학습 실행/감시 스크립트 | `unity/Assets/MLAgents/**`, `training/**` |
| [modules/VISION_TELEOP.md](modules/VISION_TELEOP.md) | 웹캠 → 손 관절각 → UDP 송신(텔레옵), 카메라 캘리브레이션 | `vision/**` |
| [modules/REAL_BRIDGES.md](modules/REAL_BRIDGES.md) | 실물/시뮬레이터 하드웨어와 붙는 브리지 — UR16e RTDE, DG-5F SDK | `arm/**`, `vision/dg5f/*bridge*.py` |
| [modules/BUILD_TOOLING.md](modules/BUILD_TOOLING.md) | 설정 정본, URDF 빌드·임포트, 패키징·방화벽 등 주변 도구 | `config/`, `urdf/`, `tools/`, `build-support/` |

## 전체 데이터 흐름 (한 장 요약)

```text
                      ┌───────────────────────── 사람 조작 경로 ─────────────────────────┐
  웹캠 ──> MediaPipe ──> 손 20관절각[deg] ──UDP 5006──> Unity Dg5fReceiver ──> 손 xDrive
        (vision/dg5f/vision_node_dg5f.py                └─UDP 5008──> dg5f_sdk_bridge.py ──> 실물 DG-5F
         또는 dg5f_teleop_gui.py)

                      ┌───────────────────────── 자율(RL) 경로 ─────────────────────────┐
  Unity 학습 씬 ──> ML-Agents(PPO) ──> 정책 .onnx ──> Dg5fPicknPlaceAgent ──> 팔6축 + 손 개폐 1축
        (unity/Assets/MLAgents/picknplace)              (training/scripts/train_picknplace.py로 학습)

                      ┌───────────────────────── 팔 실물/URSim 경로 ────────────────────┐
  Unity UrArmSender ──UDP 5009──> arm/ur_rtde_bridge.py ──RTDE servoJ──> URSim/실물 UR16e
  Unity UrArmTwinDriver <──UDP 5010── 같은 브리지 --echo-to-unity <──RTDE getActualQ──┘
```

포트·IP·경로의 **유일한 정본**은 [`config/rtauto_config.py`](../config/rtauto_config.py) + 리포 루트 `.env`다
(CLAUDE.md 원칙 1). Unity C#도 `RtautoConfig.cs`로 같은 `.env`를 읽는다.

## 지금 살아있는 것 / 죽은 것

한눈에 구분이 안 되는 게 이 저장소의 가장 큰 블랙박스라 여기에 못박는다.

**현재 주력 (확정 하드웨어 = UR16e + DG-5F-M-R 오른손)**
- RL: `unity/Assets/MLAgents/picknplace/**` (behavior 이름 `DG5FPicknPlace`)
- 데모 씬: `unity/Assets/Scenes/Pipeline_Demo_GraspLift.unity`
- 텔레옵: `vision/dg5f/vision_node_dg5f.py`(headless) / `dg5f_teleop_gui.py`(GUI)
- 팔 연동: `arm/ur_rtde_bridge.py` + URSim

**이전 세대 — 참고용으로만 남아 있음**
- `unity/Assets/MLAgents/GraspLift/**` — UR5e + **왼손** 기준. picknplace가 이걸 그대로 이식한
  것이라 코드가 거의 쌍둥이다. 새 작업은 picknplace 쪽에 한다.
- `unity/Assets/Script/`(단수 s) — Rainbow Robotics 팔 소켓 통신 코드. 현재 파이프라인
  어디에도 연결돼 있지 않은 과거 팀 시절 잔재.
- `vision/zed_object_detection/**` — **폐기.** ZED 스테레오 카메라 객체 검출 경로. 파이프라인
  어디에도 연결돼 있지 않고 Unity 수신 컴포넌트도 이미 삭제됐다. 되살리는 것을 전제하지 않는다
  ([상세](modules/VISION_TELEOP.md#4-zed-객체-검출-visionzed_object_detection----폐기-사용하지-않는다)).
- `training/archives/**`, `docs/archives/**` — 폐기된 behavior의 설정·문서.
- 주석·문서에 남아 있는 SVH(SCHUNK 손) 언급 — DG5F 이전에 쓰던 손. 코드는 대부분 제거됐고
  "이 로직은 SVH 때 검증됐다"는 유래 설명으로만 남아 있다.
