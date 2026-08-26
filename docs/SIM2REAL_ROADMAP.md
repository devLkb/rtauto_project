# Sim2Real 로드맵 — 자율주행 + 웨이퍼 케이스 Pick & Place

작성 2026-08-25 (v2 — 시뮬레이터/미들웨어 아키텍처 확정 반영).
개정 2026-08-26 (v3 — **MuJoCo 폐기**, 물리·학습을 Unity 자체 엔진(PhysX)으로 환원하고
Gazebo를 검증 단계로 추가).
개정 2026-08-26 (v4 — **Gazebo 검증 단계 폐기**, ROS2 통합을
[Unity-Robotics-Hub](https://github.com/Unity-Technologies/Unity-Robotics-Hub)
(ROS-TCP-Connector/Endpoint)로 일원화 — 아래 "Gazebo 폐기 경위" 참고).
1인 풀타임·로컬 단독 머신(RTX 2080, Windows) 체제.

정책 계약 상세는 [`DG5F_GRASP_LIFT.md`](DG5F_GRASP_LIFT.md), SDK 실측 근거는
[`TESOLLO_SDK_기술부채_조사.md`](TESOLLO_SDK_기술부채_조사.md)를 우선한다.

> ⚠️ **MuJoCo 폐기 경위 (2026-08-26).** v2(2026-08-25)에서 물리·학습 엔진으로 MuJoCo
> 도입을 확정·검증까지 마쳤으나, **파이프라인 통합 및 후속 유지보수 어려움을 이유로
> 하루 만에 폐기**됐다. 이 v3는 그 결정을 반영해 물리·학습을 다시 Unity 자체 엔진
> (PhysX)으로 되돌리고, 대신 Unity 학습 다음 단계에 **Gazebo 범용 검증**을 추가한
> 구성으로 로드맵을 정리한 것이다. 아래 각 절의 MuJoCo 관련 서술은 이 개정으로
> 무효화됐고, 이번 개정에서 PhysX/Gazebo 기준으로 다시 썼다. 이미 만들어진 MuJoCo
> 산출물(`urdf/ur16e_dg5f_right_build/*.mjcf.xml`, `patch_mjcf.py`, Unity
> `org.mujoco` 패키지 의존성, `Assets/Plugins/x86_64/mujoco.dll`,
> `Assets/Tests/MjThroughput/` 등)은 삭제하지 않고 과거 이력으로 남겨두되, 새 작업의
> 기준으로 삼지 않는다.

> ⚠️ **Gazebo 검증 단계 폐기 경위 (2026-08-26, v3 발행 당일).** v3에서 Unity 학습
> 다음 단계로 추가했던 "Gazebo 범용 검증"(§7, 당시 설계 미착수)을 **폐기**한다.
> 대신 Unity가 [ROS-TCP-Connector/Endpoint](https://github.com/Unity-Technologies/Unity-Robotics-Hub)로
> **ROS2와 직접 통신**하며, 매니퓰레이션 정책·주행(Nav2) 모두 이 경로로 ROS2 생태계
> 정합성을 확인한다 — 별도 물리 시뮬레이터(Gazebo)를 거치지 않는다. §7이 미정으로
> 남겨뒀던 "Gazebo를 별도 실행해 결과만 비교 vs ROS-TCP-Connector로 Unity와 실시간
> 연동" 질문에 대한 답이 후자로 정해진 것이자, §9(Nav2)와의 중복 우려도 동일 도구로
> 해소됨을 뜻한다. §7은 이 개정에서 삭제하고 내용을 §9로 흡수했다(아래 "9. Phase 5"
> 참고). Unity-Robotics-Hub의 공식 지원 배지는 ROS/ROS2 **Melodic·Noetic·Foxy**까지만
> 명시하므로, Nav2에 필요한 최신 ROS2 배포판(Humble 이상) 호환은 착수 시 별도 확인이
> 필요하다 — §11 리스크 참고.

## 1. 확정된 시스템 아키텍처

| 레이어 | 담당 | 비고 |
|---|---|---|
| 물리·학습 | **Unity 자체 엔진(PhysX)** | ML-Agents. ~~MuJoCo~~ — 2026-08-26 폐기(파이프라인 통합·유지보수 부담) |
| ROS2 통합/검증 | **Unity-Robotics-Hub**(ROS-TCP-Connector/Endpoint) | Unity가 직접 ROS2와 통신. ~~Gazebo~~ — 2026-08-26 폐기(별도 물리 시뮬레이터 불필요, ROS2 생태계 정합성은 이 경로로 확인). 매니퓰레이션·주행 공용 |
| 자율주행 | **ROS2 + Nav2 + slam_toolbox** | [Robotics-Nav2-SLAM-Example](https://github.com/Unity-Technologies/Robotics-Nav2-SLAM-Example) 기반, 통신은 위 ROS-TCP-Connector/Endpoint 공유 |
| 실물 하드웨어 | **UR16e** (RTDE) + **Tesollo DG-5F-M-R (오른손)** (dgsdk) + **엔스퀘어(Nsquare) AMR**(모델·상세 스펙 미확보) | |
| 3D 비전 | **손·팔 장착 예정** (eye-in-hand / arm-mounted) | 시기 미정 |

⚠️ 스펙은 변동 가능하다고 통보받았다(2026-08-25). 따라서 로봇 치수·워크스페이스
상수를 **컴파일 상수로 굳히지 말고** 런타임 파라미터/설정으로 빼두는 편이 안전하다
(스펙에 이미 `Academy.Instance.EnvironmentParameters` 패턴이 있다).

**동작은 순차**: 이동 → 정지 → 로봇팔 → 그리퍼.

### 순차 동작이 아키텍처를 단순하게 만든다

두 가지 중요한 결과가 따라온다:

1. **주행과 매니퓰레이션이 물리적으로 얽힐 필요가 없다.** 베이스가 정지한 뒤에만
   팔/손이 움직이므로, 두 하위 시스템을 같은 프레임에서 동시에 시뮬레이션할 이유가
   없다. Unity(PhysX) 학습과 Gazebo 검증도 각 단계에 맞춰 필요할 때만 돌리면 된다.
2. **정책 관찰 설계가 그대로 유효하다.** 매니퓰레이션 중 베이스는 정지 상태이므로
   기존 obs57이 가정하는 "고정된 로봇 베이스 프레임"이 실물에서도 성립한다.
   모바일 매니퓰레이션(주행 중 파지)은 범위 밖.

## 2. 관찰·액션의 실물 조달 (SDK 조사 반영)

기존 정책은 obs 57 / act 7, 결정주기 0.1 s (10 Hz). 배포 ONNX 시그니처는
`obs_0 [batch,57]` → `deterministic_continuous_actions [batch,7]` 로 확인돼 있어
`onnxruntime`으로 Unity 없이 Python 추론이 가능하다.

### 액션 7 — 경로가 이미 열려 있다

- `[0..5]` 팔: 관절 각도 델타 누적 → `ArmSafeMinDeg/MaxDeg`로 clamp된 절대 목표각.
  **관절공간 위치 제어라 IK 불필요**, UR16e RTDE로 직접 명령.
- `[6]` 그립: 스칼라 closure → `Lerp(openHand, LeftFistDeg, closure)`로 20관절.
  결정적 고정 매핑이고, **기존 브리지가 텔레옵으로 이미 보내는 형식과 동일**하다.
  손가락 20개를 개별 출력하지 않고 스칼라 1개로 묶은 설계가 실물 이식에서 유리하다
  (정책이 물리적으로 불가능한 손 모양을 만들 여지가 구조적으로 없다).

### 관찰 57 — 병목은 **비전 하나**로 좁혀졌다

| 관찰 | 개수 | 실물 조달처 | 가능? |
|---|---:|---|:--:|
| 팔 관절 각도·속도 | 12 | UR16e RTDE | ✅ |
| 팔 명령각 | 6 | 우리가 보낸 값 | ✅ |
| 손 닫힘 | 1 | 우리가 보낸 값 | ✅ |
| 손끝·팜 접촉 플래그 | 6 | **SDK `get_fingertip_sensor_data()`** | ✅ |
| 손끝 위치(물체 기준) | 15 | URDF 순기구학 × 물체 자세 | ⚠️ 물체 자세 필요 |
| **물체 상대위치·속도·각속도·상승높이** | **10** | **비전(3D 자세 추정)** | ❌ **없음** |
| 과제 진행 상태 | 7 | 위 값에서 파생 | ⚠️ 파생 |

**핑거팁 FT·촉각 센서가 실재하므로 접촉 관찰은 실물에서 확보된다.** 어제 최대 리스크로
잡았던 "접촉 센싱 불가 → obs48 재학습" 분기는 소멸했다. 남은 단일 블로커는
**물체 6D 자세(직접 10칸, 파생 22칸)** 이고, 저장소에 카메라 수신 경로가 없다.

### 3D 비전이 손·팔에 장착되면 (eye-in-hand)

카메라가 로봇에 실린다는 건 물체 자세 조달 경로가 생긴다는 뜻이라 반가운 소식이지만,
고정 카메라와는 성질이 다르다:

- **캘리브레이션이 eye-in-hand 문제로 바뀐다** — 카메라↔플랜지(또는 장착 링크) 변환을
  구하고, 물체 자세를 **팔 순기구학을 통해 베이스 프레임으로 합성**해야 한다.
  FK 오차와 장착 변환 오차가 함께 전파된다.
- **노이즈가 팔 속도에 상관된다** — 움직이는 카메라는 모션 블러와 지연이 생긴다.
  따라서 도메인 랜덤화에서 관측 노이즈를 **상수가 아니라 속도 의존**으로 모델링해야 한다.
- **파지 순간 손 장착 카메라는 물체·손가락에 가려진다.** 접근 구간은 팔/손목 장착
  시야로 보고, 접촉 순간부터는 **핑거팁 FT 센서로 감각이 넘어가는** 구성이 자연스럽다.
  기존 관찰 설계(접촉 플래그 6칸)가 이 인계를 이미 담고 있다.
- **관찰 설계 결정을 명시적으로 해야 한다**: 지금처럼 **상태 기반 관찰**(비전은 자세
  추정기로만 사용)을 유지할지, 이미지를 관찰로 넣는 **비주얼 RL**로 갈지.
  → **상태 기반 유지를 권장한다.** 비주얼 RL은 단일 2080·1인 체제에서 훨씬 큰 문제다.
  카메라가 로봇에 실리면 나중에 비주얼 서보잉 단계를 얹을 여지는 열린다.
- 플랜지 적재는 가반하중을 잡아먹지만 UR16e 16 kg이면 여유가 있다.

## 3. 재학습은 피할 수 없다 (물리 엔진과 무관하게)

**전제를 분명히 한다: 현재 GraspLift 정책 가중치는 배포 산출물이 될 수 없다.**
물리 엔진을 PhysX로 유지하기로 하면서 이유 하나는 사라졌지만(§ "MuJoCo 폐기 경위"
참고 — 접촉 모델 차이로 인한 재학습 압박은 더 이상 없다), **하드웨어 변경**만으로도
재학습은 여전히 강제된다: UR5e→UR16e로 팔 기구학이 달라졌고 왼손→오른손으로 파지
기하가 뒤집혔다. 기존 정책(obs57/act7, 학습조건 99.75% / 균일밀도 99.24%, UR5e+왼손
Unity/PhysX 기준)은 **Phase 2 비교 기준선(baseline)** 으로 동결·보존하고, 배포
산출물로는 쓰지 않는다.

MuJoCo를 폐기하면서 오히려 단순해진 부분도 있다: 물리 엔진이 그대로 PhysX이므로
**접촉 센서(`GraspLiftObjectContactSensor`/`GraspLiftSurfaceContactSensor`/
`GraspLiftHandSurfaceSensor`)를 다른 API로 재작성할 필요가 없다** — v2에서 MuJoCo
플러그인의 트리거 콜라이더 미지원 때문에 예정했던 `MjSensor` 터치 재작성 작업은
통째로 사라졌다. 보상 코드(`Dg5fGraspLiftSpec.cs`)도 C#/Unity API 그대로이며 포팅이
필요 없다.

**재학습해도 살아남는 자산** — 이게 프로젝트의 진짜 가치다:
- `Dg5fGraspLiftSpec`에 축적된 **보상 설계 지식**(왜 closure가 0.75에서 포화하는지,
  왜 COM을 낮춰야 하는지, 왜 potential-based new-best 델타여야 하는지, 왜 topple을
  종료 조건으로 넣어야 하는지 — 전부 실측 근거가 주석에 남아 있음)
- URDF·메시, 안전 봉투(`ArmSafeMinDeg/MaxDeg`)
- Phase 1의 실물 배선(관절 대응표, RTDE, SDK 센서) 전부
- 비전 파이프라인 골격

## 4. Phase 0 — 스펙 확정 & 모델 정본화 (선행 차단 요소)

### 하드웨어 확정에 따른 모델 전면 교체 (2026-08-25)

기존 자산은 **UR5e + 왼손**이고 실물은 **UR16e + 오른손**이다. 팔 기종과 손 좌우가
모두 달라 결합 모델을 다시 빌드해야 한다. 이 절의 URDF 결합 작업은 물리 엔진
선택(PhysX든 MuJoCo였든)과 무관한 하드웨어 정본화 작업이라 MuJoCo 폐기와 무관하게
유효하다.

| | 기존 (저장소) | 실물 (확정) |
|---|---|---|
| 팔 | UR5e — 가반 5 kg, 리치 850 mm | **UR16e — 가반 16 kg, 리치 900 mm** |
| 손 | `dg5f_left` (왼손) | **DG-5F-M-R (오른손)** |
| 결합 산출물 | `ur5e_dg5f_left.urdf` | `ur16e_dg5f_right.urdf` (신규 빌드) |

**가반하중 16 kg은 웨이퍼 케이스에 결정적으로 유리하다.** FOUP는 웨이퍼를 채우면
수 kg이고 여기에 DG5F 손 자체 무게 + (예정된) 손 장착 카메라까지 플랜지에 얹히는데,
UR5e의 5 kg으로는 여유가 거의 없었다. UR16e는 실질적 헤드룸을 준다.

**리치는 850→900 mm로 소폭 증가**했고, 아래 상수를 **재도출 완료(2026-08-25)**:
(현재 값은 UR5e 기하에 맞춰 손으로 튜닝된 것이었다)

- `MaximumObjectDistance` 0.85→**0.90**: UR5e 리치와 정확히 일치했던 값이라
  UR16e 리치(0.90)로 그대로 대체.
- `MinimumSpawnRadius`/`MaximumSpawnRadius` 0.35/0.55→**0.37/0.58**: 리치 비율
  (0.90/0.85=1.0588)로 스케일 — 절대 거리를 유지하는 게 아니라 팔 리치 대비
  같은 상대 난이도를 유지하는 쪽을 택함.
- `PanelWidth`/`PanelDepth`(1.80) — **변경 없음**. 코드 주석에 "reach와 무관하게
  씬 스케일 유지를 위해 고정"이라 명시돼 있어, 리치 의존 상수가 아니었다
  (로드맵이 이전에 이 둘도 재도출 대상으로 잘못 나열했던 것 — 정정).
- `ArmSafeMinDeg`/`ArmSafeMaxDeg` — **변경 없음, 단 리스크 하나 발견**. URDF
  관절 하드웨어 리밋은 UR e-series 전체가 ±360°로 동일해서(실제 확인함) 이
  값들은 리치가 아니라 UR5e 기하에서 손으로 튜닝된 "그럴듯한 자세" 봉투다. MuJoCo
  sim 기준 FK 스윕으로 한 코너(shoulder_lift=-20°, elbow=140°)에서 손이 패널
  상판(z=0)보다 약 0.20 m 아래로 내려가는 것을 확인했으나, 이 FK 스윕 자체는
  MuJoCo sim 모델 기준이라 지금은 참고 데이터일 뿐이다 — **PhysX 재학습(Phase 2)
  전에 같은 스윕을 Unity/PhysX 모델로 다시 해서 재확인해야 한다.**
- 액추에이터 게인(더 무거운 팔) — Unity xDrive 게인을 UR16e 기준으로 재튜닝 필요
  (기존 UR5e 게인 10000/200/100000 그대로 못 씀). **미착수.**

#### 오른손 파지 포즈는 되돌리면 나온다

`LeftFistDeg` 주석에 **"Validated DG5F closed-hand pose, mirrored for the left-hand
URDF"** 라고 적혀 있다 — 원본이 오른손 포즈였고 왼손용으로 미러한 값이다. 따라서
오른손 전환은 **미러를 되돌리는 것**이고, 미러 채널 집합이 이미 코드에 있다
(브리지 `MIRROR_IDX = [0,1,2,3,4,8,12,16,17]`, `dg5f_angles.LEFT_MIRROR_CHANNELS`).
부수적으로 브리지의 `--unmirror` 플래그가 불필요해지고, 텔레옵 기본값이 원래
오른손이라 그쪽도 정합된다.

#### "M"의 정체 — 확정됨 (2026-08-25)

**M = 표준(비-short)** → `dg5f_right.urdf` + SDK 모델 코드 `5f_right`(0x5F22).
사용자가 보낸 참조 URDF(Tesollo 공식 `tesollo_model` 레포의 `dg5f_right.urdf`)를
저장소 기존 `urdf/dg5f/dg5f_right.urdf`와 diff한 결과 **완전히 동일** —
기존 자산이 이미 공식본이었다. `dg5f_sdk_bridge.py --model` 기본값을
`5f_right`로 갱신했다.

여전히 확인 필요한 것 — **UR16e**: Polyscope 버전, 네트워크(IP), RTDE 활성화 여부.

#### 재빌드 완료 — `ur16e_dg5f_right.urdf`

두 빌드 스크립트(`convert_ur.py`/`merge_dg5f.py`, 각각 죽은 개발자 PC 경로가
하드코딩돼 있었고 2026-08-26 삭제됨)를 기종·좌우 파라미터화한
`urdf/build_arm_hand.py` 하나로 통합했고, 공식
`UniversalRobots/Universal_Robots_ROS2_Description`(rolling 브랜치)로 실제 빌드까지
완료했다. 결과: `urdf/ur16e_dg5f_right_build/ur16e_dg5f_right.urdf` — 링크 41 /
조인트 40(revolute 26=팔6+손20), 손끝 5개 전부 도달, 중복 0. UR5e+왼손 빌드와
동일한 건전성 지표를 통과했다.

메시 검증: `ur16e` 전용 메시는 forearm/upperarm뿐이고 나머지는 `ur10e` 메시를
공유하는 정상 구조(관절 origin이 UR16e 고유 DH 파라미터 d1=0.1807/a2=-0.4784/
a3=-0.36와 일치함을 확인). 초기 `build_arm_hand.py`는 `--ur-type` 메시 폴더만
복사해 `ur10e` 공유 메시(base/shoulder/wrist1-3)를 빠뜨리는 버그가 있었다 —
생성된 URDF에서 실제 참조된 메시 폴더를 스캔해 복사하도록 수정.

inertial 없는 UR 더미 링크(`base_link`/`base`/`flange`/`tool0`/`ft_frame`)에 대한
관성 보정은 **Unity 임포터 기준으로 다시 필요 여부를 확인해야 한다** — v2에서
"MuJoCo는 fixed-joint 질량 0 바디를 자동 병합해 패치가 불필요하다"고 실측했지만,
이는 MuJoCo 컴파일러의 동작이라 Unity/PhysX(URDF-Importer)에는 그대로 적용되지
않는다. WORKLOG §12·§22가 남긴 "Unity 임포터 기본값(1kg/(1,1,1)) 함정" 패치 절차가
UR16e+오른손 조합에도 필요한지 Phase 2 착수 시 재확인.

#### 모델 정본화 — 재작업 필요

새로 빌드한 `ur16e_dg5f_right.urdf`를 이제 **MJCF가 아니라 Unity URDF-Importer로**
가져와 프리팹화한다(v2에서 계획했던 MJCF 변환·MuJoCo 액추에이터/터치센서/자기충돌
패치 작업은 전부 폐기 — 아래 참고 상자). Unity 임포트 후 손으로 맞춰야 하는 것:

- **xDrive 액추에이터 게인** — 기존 UR5e 게인(10000/200/100000)은 UR16e의 더
  무거운 링크 관성에 안 맞을 가능성이 높다. 재튜닝 필요. **미착수.**
- **접촉 센서** — 기존 Unity 콜라이더 트리거 기반 3종
  (`GraspLiftObjectContactSensor`/`GraspLiftSurfaceContactSensor`/
  `GraspLiftHandSurfaceSensor`)를 **그대로 재사용**한다. MuJoCo였다면 필요했던
  `MjSensor` 재작성이 통째로 불필요해졌다.
- **자기충돌 처리** — 기존 `unity/Assets/Scripts/RobotSelfCollisionIgnore.cs`를
  **그대로 재사용**한다(로봇 전체 콜라이더 쌍을 `Physics.IgnoreCollision`로
  블랑켓 비활성화하는 방식 — 이미 코드로 존재, UR16e+오른손 리그에 다시 붙이기만
  하면 됨).
- **대상 물체** — 블록(0.035×0.035×0.12 m, density 1800, COM 0.20 위치,
  `Dg5fGraspLiftSpec` 기본값과 일치 — Unity PhysX 콜라이더/리지드바디로 그대로 구현)
  / 웨이퍼 케이스(나중, 스펙 대기)

> ⚠️ **폐기된 MuJoCo 작업 (과거 이력, 참고용).** v2에서 `ur16e_dg5f_right.urdf`를
> MuJoCo Python에 로드하고 `patch_mjcf.py`로 26개 position 액추에이터·손끝/팜
> 터치센서·자기충돌 그룹·파지 대상 블록을 추가해 `ur16e_dg5f_right.sim.mjcf.xml`을
> 만들었으며, 5000스텝(10 s) 구동으로 추종오차 0.1° 이내·NaN 없음·자기충돌 오검출
> 없음을 확인했다(적분기는 `implicitfast`, 액추에이터 게인 팔 kp=2000/kv=200·손
> kp=20/kv=2). Unity 쪽도 `org.mujoco` 플러그인(태그 3.12.0)을 설치해 Unity
> 6000.4.0f1과의 호환을 확인하고, 학습영역 1/2/5/10/20개 병렬 처리량을 측정해
> 10개까지는 실시간(1x) 이상, 20개에서는 실시간의 0.38~0.46x로 떨어지는 것까지
> 실측했다. 이 모든 작업은 **2026-08-26 MuJoCo 폐기로 무효화**됐고, 위 수치들은
> 어떤 향후 결정의 근거로도 쓰지 않는다. 산출물 파일은 삭제하지 않고 남겨뒀다.

### 스펙 요구 목록 (미정 항목)

**이동 베이스 — 제조사 확정(2026-08-25): 엔스퀘어(Nsquare) AMR.** 모델·상세 스펙은
아직 미확보. Nav2가 요구하는 세부 항목은 여전히 확인 필요: 구동 방식(차동/전방향),
오도메트리 출력(엔코더), LiDAR 모델, **ROS2 드라이버 제공 여부**, 적재 하중(UR16e
33 kg급 + DG5F + 카메라 지지), 풋프린트, 배터리, 비상정지 경로. (참고: 웹 검색으로
공개 스펙 시트를 찾지 못했다 — 제조사 자료나 정확한 모델명이 확보되면 갱신)

**웨이퍼 케이스** — 치수, 질량, **파지 지점(손잡이/엣지/플랜지)**, 재질·마찰,
**허용 기울기·가속 한계**, 청정도 요구.

## 5. Phase 1 — 실물 구동·센싱 경로 (지금 착수 가능, sim 엔진 선택과 무관)

**이 단계를 sim 쪽 재학습보다 먼저 하는 이유가 두 가지다.** ①재학습에는 시간이
걸리는데 그 전에 실물 배선을 다 검증해두면 새 정책이 나왔을 때 갈아끼우기만 하면 된다.
②여기서 얻는 실측(마찰, 추종 오차, 센서 노이즈, 지연)이 **Unity PhysX 모델 캘리브레이션과
도메인 랜덤화 범위의 입력**이 된다. 순서를 뒤집으면 랜덤화를 추측으로 하게 된다.

1. **공식 `dgsdk` 패키지로 브리지 이관** — 현재 ctypes DLL 직접 호출을 교체.
   센서·상태 API가 한꺼번에 열리고 리눅스 실행도 가능해진다(ROS2/WSL2 통합에 필요).
2. **관절 대응표 확정 (안전 필수)** — `JOINT_ORDER`/`JOINT_SIGN`/`JOINT_OFFSET_DEG`가
   여전히 "미검증"이다. `--pose`로 한 관절씩 소각도 주입해 확정하고 표로 남긴다.
   틀린 채로 `MoveServoJoint`를 보내면 손가락이 리밋 방향으로 꺾인다.
3. **핑거팁 센서 실측** — `get_fingertip_sensor_data()` 신호 특성 파악, 접촉 플래그
   6개로 바꿀 **임계값 결정**. sim의 불리언 접촉과 실물 연속 FT값 사이의 변환 정의.
4. **`get_gripper_data()` 로깅** — 관절 실제값·전류·에러코드. 명령 대비 추종 오차를
   측정해 PhysX 액추에이터(xDrive) 모델에 반영.
5. **UR16e RTDE 연결** — `getActualQ`/`getActualQd`, 10 Hz `servoJ`. `ArmLinks` 순서가
   UR `q` 순서와 1:1인지, **부호·영점**이 URDF와 맞는지 대조. 여기가 틀리면 관찰
   정규화가 조용히 어긋난다.
6. **ArUco 마커로 물체 자세 공급** — 비전 파이프라인 없이 obs의 비전 의존 10칸을 채우는
   우회로. 마커/지그로 물체 자세를 주면 **비전 개발 전에 파지 루프 전체를 실물에서
   닫을 수 있다.**

**완료 기준**: 기존 Unity 학습 ONNX를 그대로 써서, ArUco로 자세를 공급한 상태에서
실물 UR16e+DG5F가 12 cm 블록을 파지·들어올린다. (성공률은 기대하지 않는다 —
랜덤화 없이 학습된 정책이라 실패해도 정상이다. **검증 대상은 배선과 관찰 조립이
맞는지**이며, 실패 모드 자체가 Phase 2 랜덤화 설계의 데이터다.)

## 6. Phase 2 — Unity PhysX 재학습 (새 하드웨어: UR16e + 오른손)

과제를 바꾸지 않고 **같은 12 cm 블록으로** 재학습한다. 기존 Unity 베이스라인
(학습조건 99.75% / 균일밀도 99.24%, UR5e+왼손)이 있으므로 **비교 가능한 성공률
도달을 포트 검증 게이트로 쓴다.** 과제를 동시에 바꾸지 않는 이유는 무엇이 깨졌는지
알 수 없게 되기 때문이다.

물리 엔진이 그대로 PhysX이므로(§ "MuJoCo 폐기 경위") v2에서 이 단계에 있던
"MJCF 물리 파라미터 캘리브레이션"·"보상/접촉 센싱을 `Mj*` API로 재작성" 항목은
사라졌다. 남는 작업:

1. §4에서 새로 빌드한 `ur16e_dg5f_right.urdf`를 Unity URDF-Importer로 임포트하고
   xDrive 게인을 UR16e 관성에 맞게 재튜닝(§4 "모델 정본화" 참고)
2. `Dg5fGraspLiftSpec.cs` 보상 코드는 **그대로 유지** — 포팅 불필요
3. 도메인 랜덤화를 **처음부터 설계에 포함** — 기존 Unity 베이스라인의 최대 약점이
   랜덤화 부재였다. Phase 1에서 **측정한 실제 노이즈 크기**를 범위로 쓴다:
   물체 자세 관측 노이즈·지연(최우선), 마찰, 질량, 액추에이터 지연·추종오차, 백래시
4. 짧은 주기 체크포인트 평가 후 조기 중단. 긴 blind run 금지(단일 GPU)
5. 학습 씬이 곧 최종 시각화 씬이다 — MuJoCo 안이 필요로 했던 "학습(MuJoCo)과
   시각화(Unity)가 같은 MJCF를 공유"하는 별도 동기화 문제 자체가 없다.

기존 Unity PhysX 학습 경로(`training/scripts/*` 중 GraspLift 계열,
`unity/Assets/MLAgents/GraspLift`)는 **레거시로 동결하고 삭제하지 않는다** —
위 포트 검증 게이트의 비교 기준(99.75%)이기 때문이다.

## 7. Phase 3 — ~~Gazebo 검증~~ 폐기, ROS2 통합은 §9로 흡수

**2026-08-26 폐기.** 별도 Gazebo 검증 단계를 두지 않는다. Unity가
[Unity-Robotics-Hub](https://github.com/Unity-Technologies/Unity-Robotics-Hub)의
ROS-TCP-Connector/Endpoint로 ROS2와 직접 통신하며, 매니퓰레이션 정책·Nav2 주행 검증
모두 이 경로를 공유한다. 상세 구성(설치·토폴로지·버전 호환)은 §9(Phase 5 — 자율주행)
참고 — 이 단계는 §9에 흡수됐으므로 별도 절로 남겨두지 않는다.

## 8. Phase 4 — 웨이퍼 케이스 재타겟 + Pick & Place

스펙 도착 후 착수. 기존 과제는 "파지+들어올려 유지"까지이고 **place가 없다** —
새 기능이다.

**분업을 권장한다: 파지는 RL, 이송·배치는 스크립트/플래너.**
- 파지는 접촉 리치라 스크립트로 짜기 어렵다 → RL의 몫
- 배치는 기하 문제이고 **정밀도·기울기·가속 제약 준수를 검증해야** 한다 →
  결정적 플래너가 훨씬 신뢰할 수 있고, 웨이퍼 취급 제약을 명시적으로 걸 수 있다

스펙에 따라 연쇄 변경되는 것: 물체 치수·질량·COM, `GraspTargetHeightOffset`,
**`LeftFistDeg` 파지 포즈 전면 재설계**(FOUP류는 5지 감싸쥐기가 아니라 손잡이/엣지
그립이 표준 → 접촉 대향각 90° 조건과 케이지 판정도 함께), `ToppleLimitDegrees`
(현재 45°, 웨이퍼는 훨씬 엄격할 것), YOLOv8 재학습.

> **선행 placeholder 착수 (2026-08-26, 같은 날 두 번 방향 조정).** 스펙 도착
> 전이지만 `Assets/MLAgents/picknplace`(`DG5FPicknPlace` behavior)로 구조를
> 먼저 세워뒀다. 1차 시도는 FOUP 손잡이를 직접 잡는 방식이었으나, 실제
> 착수해보니 place 보상 셰이핑 자체를 연습해두는 편이 이 시점에 더 유용하다고
> 판단해 **같은 날 방향을 바꿨다**: 지금 구현은 큐브(GraspLift 블록과 동일
> 지오메트리, 검증된 파지 아퍼처 재사용)를 바닥 랜덤 위치에서 집어, FOUP 형태
> 고정 플랫폼(박스 몸체 + 장식용 손잡이) 윗면의 랜덤 지점에 내려놓는 진짜
> pick-and-place다. 이 behavior 안에서는 place가 RL로 구현돼 있다 — 위
> "파지는 RL, 이송·배치는 결정적 플래너" 분업은 **모바일 매니퓰레이터가 실제
> FOUP 자체를 옮기는 것**에 대한 결정이라 여전히 유효하며, 이 큐브
> pick-and-place는 그 결정과 별개로 place 보상 구조를 미리 검증해두는
> 기반 작업이다. 큐브/플랫폼 치수는 여전히 잠정값. 설계 근거·상수 전체 목록은
> [`docs/DG5F_PICKNPLACE.md`](DG5F_PICKNPLACE.md) 참고.

## 9. Phase 5 — 자율주행 (Nav2) + ROS2 통합 (구 §7 Gazebo 검증 흡수)

이 Phase가 **Unity ↔ ROS2 통합의 유일한 경로**다(§7 참고, 2026-08-26 Gazebo 검증
단계 폐기 후 흡수). Nav2 주행뿐 아니라 매니퓰레이션 정책의 ROS2 생태계 정합성
확인도 여기서 같은 브릿지로 수행한다 — 별도 Gazebo 인스턴스 없음.

- **구성 요소** (Unity-Robotics-Hub 하위 저장소):
  - `ROS TCP Endpoint` — ROS2 쪽(Python), 메시지 송수신 서버.
  - `ROS TCP Connector` — Unity 패키지(UPM git URL), 메시지 송수신·시각화.
  - `URDF Importer` — Unity 패키지, URDF 로드(§4 모델 정본화와 연결).
- **토폴로지**: ROS2 + Nav2 + slam_toolbox를 **WSL2(Ubuntu) 또는 Docker**에서,
  Unity는 Windows에서, 둘을 **ROS-TCP-Connector/Endpoint**로 연결. ROS2를 Windows
  네이티브로 돌리는 건 피한다.
- **버전 호환 확인 필요**: Unity-Robotics-Hub 공식 지원 배지는 ROS Melodic/Noetic,
  **ROS2는 Foxy까지**만 명시한다. Nav2에 보통 쓰는 Humble 이상 호환은 착수 시
  별도 검증 필요(공식 미지원일 수 있음 — fork/커뮤니티 브랜치 확인).
  Robotics-Nav2-SLAM-Example 자체도 Unity 2020.3 LTS / ROS2 Foxy~Galactic 시절
  기준이라, 이 프로젝트의 **Unity 6000.4.0f1** + 렌더 파이프라인(Built-in) +
  예제 로봇·센서 프리팹 쪽에 포팅 작업이 필요하다.
- **원칙 1 (하드코딩 금지) 적용**: ROS_IP·TCP 포트는 [`config/rtauto_config.py`](../config/rtauto_config.py)에
  추가하고 Unity(C#)·Python 양쪽에서 그걸 참조한다. 리터럴로 박지 않는다.
- **베이스 스펙 대기 중에도 착수 가능** — 예제의 스톡 로봇으로 Nav2/SLAM 파이프라인을
  먼저 세우고, 실 베이스 스펙이 오면 교체한다. 스펙 대기로 막혔을 때 돌릴 작업.

## 10. Phase 6 — 통합 오케스트레이션

순차 상태기계: `NAVIGATE → STOP → LOCALIZE → PICK → (NAVIGATE) → PLACE`

**미들웨어 경계 권장안**: ROS2는 **주행과 상위 오케스트레이션**에만 쓰고,
매니퓰레이션 **10 Hz 내부 루프는 RTDE+dgsdk 직결**로 유지한다. `pick`/`place`를
ROS2 액션으로 노출해 상태기계가 호출하는 구조. 이유는 결정론적 제어 루프를 DDS에
태우면 지연·지터 관리가 추가 부담이 되고, 순차 동작이라 주행과 파지가 실시간으로
결합될 필요가 없기 때문이다. (Tesollo도 ROS2 패키지를 제공하므로 전면 ROS2 통합도
가능하지만, 1인 체제에서는 위 절충이 낫다고 본다.)

## 11. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| `ArmSafeMinDeg/MaxDeg` 봉투가 손을 패널 아래로 내리는 코너 존재 (MuJoCo 기준 FK로만 확인, PhysX 재확인 안 됨) | 학습 중 비현실적/위험 자세 방문 가능 | Phase 2 착수 시 Unity/PhysX 모델로 FK 스윕 재실행 |
| eye-in-hand FK·장착변환 오차 전파 | 물체 자세 오차 누적 | 캘리브레이션 후 정지자세 실측 검증 |
| 스펙 추가 변동 | 상수 재작업 반복 | 로봇·워크스페이스 상수를 런타임 파라미터로 유지 |
| 관절 대응 미검증 | **하드웨어 손상** | Phase 1-2, 실물 구동 전 필수 |
| xDrive 게인 UR16e 미재튜닝(더 무거운 팔) | Phase 2 학습 불안정 가능 | Phase 2 착수 시 재튜닝·검증 |
| 비전 자세 오차·지연 | 관찰 32칸 오염 | Phase 1 실측 → 랜덤화 범위로 사용 |
| Nav2 예제 ↔ Unity 6 비호환 | 주행 착수 지연 | 스톡 로봇으로 선행, 스펙 대기 중 수행 |
| Unity-Robotics-Hub 공식 지원이 ROS2 Foxy까지만 명시(Nav2는 보통 Humble+) | §9 착수 시 통신 브릿지 호환 문제 가능 | 착수 시 fork/커뮤니티 브랜치 여부 확인, 필요하면 직접 패치 |
| 웨이퍼 그립 방식이 5지 파지와 다름 | 파지 포즈·보상 재설계 | Phase 4에 재학습 일정 반영 |
| 단일 GPU 시분할 | 학습·하드웨어 동시 진행 불가 | 학습 야간 / 하드웨어·비전 주간 |
| 아키텍처 결정이 하루 만에 뒤집힌 전례(MuJoCo 확정→폐기) | 로드맵 신선도에 대한 신뢰 저하 | "확정" 표시된 결정도 며칠간 재확인 없이는 다음 대형 작업의 전제로 쓰지 않는다 |
