# 모듈 지도 (MODULE_GUIDE)

이 프로젝트를 처음 인수받는 사용자를 위한 입구다. 코드를 읽지 않아도 **각 모듈이 무엇을 받아
무엇을 만들고, 누가 로봇을 제어하며, 어디까지 구현됐는지** 이해하는 것을 목표로 한다.
각 모듈 문서의 앞부분은 역할·연결·사용 조건, 뒷부분은 파일별 역할을 설명한다.

- 2026-09-07 저장소 코드·씬 설정 대조 기준이다. 이번 문서 갱신은 실물 재시험이나 새 모델의 성능 검증을 뜻하지 않는다.
- 현재 연결과 제한은 이 문서와 `modules/`를 먼저 본다. 설계 변경 이력·장기 계획은
  [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md), 실행 명령은 각 README를 참고한다.
  과거 기록의 “현재”나 계획된 기능을 오늘의 구현 완료 상태로 해석하지 않는다.
- 코드가 바뀌면 역할뿐 아니라 입출력·제어권·설정 적용 시점·알려진 제한도 함께 갱신한다.

## 처음 읽는 순서

1. 이 페이지에서 전체 흐름과 현재 범위를 읽는다.
2. [Unity](modules/UNITY.md)에서 화면의 자동/수동·트윈 방향·주먹 버튼이 각각 무엇을 바꾸는지 확인한다.
3. 웹캠 조작은 [비전](modules/VISION_TELEOP.md), 장비 접속은 [브리지](modules/REAL_BRIDGES.md)로 이어 읽는다.
4. 자동 파지를 이해하려면 [강화학습](modules/RL_TRAINING.md)의 관찰 출처·성공 조건을 읽는다.
5. 새 PC 인수나 모델·설정 변경 시 [설정·빌드](modules/BUILD_TOOLING.md)의 설정 위치와 재생성 순서를 확인한다.

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
사람의 손 조작
  웹캠 → MediaPipe → 동작 신호를 로봇 20관절 목표각으로 변환
                    ├─ UDP 5006 → Unity Receiver → HandDriver/활성 IK → 시뮬 손
                    └─ UDP 5008 → 손 SDK 브리지 → 실물 손 (직접 구동 선택 시)

학습과 자동 시연
  Unity 내부 상태 ←→ Python ML-Agents 학습 → ONNX 정책 파일
  대응 모델을 지정한 Unity Agent → 팔 6축 + 손 개폐 1축 → 시뮬 관절 목표각

Unity에서 실물 손 구동
  Unity 프리셋 → Dg5fSender → UDP 5008 → 손 SDK 브리지 → 실물 손
  Unity Receiver ← UDP 5006 ← 실제각 echo (명령 처리 후에만, 교시 중 제한 있음)

팔 실물/URSim 연결
  Unity UrArmSender → UDP 5009 → 팔 RTDE 브리지 → URSim/실물 UR16e
  Unity UrArmTwinDriver ← Receiver ← UDP 5010 ← 실제각 echo
```

화살표는 사용 가능한 연결을 보여주며, 모든 경로를 동시에 실행하라는 뜻은 아니다.
웹캠과 손 실제각 echo는 같은 수신 포트를 공유하므로 동시에 송신하지 않는다.
자동 정책·수동 프리셋·웹캠도 같은 관절에 명령하므로 [제어권 표](modules/UNITY.md)를 확인한다.

UDP는 프로그램 사이에서 값을 보내는 통신 방식이며 포트는 받는 프로그램을 구분하는 번호다.
위 숫자는 기본값이다. 설정은 [`.env.example`](../.env.example)·`.env`를 Python과 C#이 각각 읽으며,
**배포 실행파일에서 두 프로그램의 설정 탐색 위치가 다른 현재 제한**은 [설정 문서](modules/BUILD_TOOLING.md)에 있다.

## 현재 할 수 있는 일과 미완료 경계

| 경로 | 읽을 때 구분할 상태 |
|---|---|
| 단일 웹캠 → Unity 손 | 현재 텔레옵 경로. RL 학습과 독립 |
| PicknPlace 학습·데모 | UR16e + 오른손의 grasp+lift 과제. place는 미포함. 저장된 데모의 Agent 비활성 제한은 Unity 문서 참고 |
| Unity ↔ URSim 팔 | 양방향 코드와 과거 검증 기록이 있음. 실물 UR16e 재검증과 구분 |
| 손 SDK 구동·명령 후 echo | 현재 구현 경로. **교시 중 real→sim 피드백은 코드 결함으로 미완료** |
| 다중 카메라 3D 특징점 | 별도 실행·보정 경로. 현재 텔레옵·RL 관찰에 자동 연결되지 않음 |
| 카메라로 물체를 찾고 실물에서 자율 파지 | 실물 관찰 조달·좌표 변환·검증 등 후속 작업 필요 |

현재 RL은 Unity 내부의 물체 좌표·속도·접촉 정보를 직접 읽는다. 웹캠 손 추적이 이 정보를 대신 제공하지 않는다.
실물 자세를 녹화한 JSON도 수동 파지 버튼에 쓰이며 자동 정책을 갱신하지 않는다.
이 두 경계는 [강화학습 문서](modules/RL_TRAINING.md)와 [Unity 문서](modules/UNITY.md)에 설명되어 있다.

## 현재 주력과 이전 세대

한눈에 구분이 안 되는 게 이 저장소의 가장 큰 블랙박스라 여기에 못박는다.

**현재 주력 (확정 하드웨어 = UR16e + DG-5F-M-R 오른손)**

- RL: `unity/Assets/MLAgents/picknplace/**` (behavior 이름 `DG5FPicknPlace`)
- 데모 씬: `unity/Assets/Scenes/Pipeline_Demo_GraspLift.unity`
- 텔레옵: `vision/dg5f/vision_node_dg5f.py`(미리보기) / `dg5f_teleop_gui.py`(제어 패널)
- 팔 연동: `arm/ur_rtde_bridge.py` + URSim

**이전 세대 — 참고용으로만 남아 있음**

- `unity/Assets/MLAgents/GraspLift/**` — UR5e + **왼손** 기준. picknplace가 이걸 그대로 이식한
  것이라 코드가 거의 쌍둥이다. 새 작업은 picknplace 쪽에 한다.
- `unity/Assets/Script/`(단수 s) — Rainbow Robotics 팔 소켓 통신 코드. 현재 파이프라인
  어디에도 연결돼 있지 않은 과거 팀 시절 잔재.
- `vision/zed_object_detection/**` — **폐기.** ZED 스테레오 카메라 객체 검출 경로. 파이프라인
  어디에도 연결돼 있지 않고 Unity 수신 컴포넌트도 이미 삭제됐다. 되살리는 것을 전제하지 않는다
  ([비전 문서의 ZED 절](modules/VISION_TELEOP.md)).
- `training/archives/**`, `docs/archives/**` — 폐기된 behavior의 설정·문서.
- 주석·문서에 남아 있는 SVH(SCHUNK 손) 언급 — DG5F 이전에 쓰던 손. 코드는 대부분 제거됐고
  "이 로직은 SVH 때 검증됐다"는 유래 설명으로만 남아 있다.
