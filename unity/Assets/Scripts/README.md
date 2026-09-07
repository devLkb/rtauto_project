# `Assets/Scripts/` — 통신·구동·IK·로깅 공용 C#

어셈블리 **`KDT.RobotScripts`**. 이 프로젝트의 **가장 아래층**이며, 강화학습 어셈블리
(`KDT.PicknPlaceTraining` 등)가 이걸 참조한다. 반대 방향 참조는 순환 참조로 컴파일이 깨지므로
**여기서 RL 코드를 참조하면 안 된다.**

이름 규칙 하나만 기억하면 절반은 읽힌다: **`Receiver` = 밖에서 Unity로, `Sender` = Unity에서 밖으로.**

## 목차

1. [통신 6종 — 송수신 4개 + 구동 2개](#1-통신-6종--송수신-4개--구동-2개)
2. [설정·상수 3종](#2-설정상수-3종)
3. [물리 셋업 3종 — "안 붙이면 로봇이 떨린다"](#3-물리-셋업-3종--안-붙이면-로봇이-떨린다)
4. [수동 조작·IK 5종](#4-수동-조작ik-5종)
5. [로깅 2종](#5-로깅-2종)
6. [씬 소품 생성기 3종](#6-씬-소품-생성기-3종)
7. [브리지 런처](#7-브리지-런처)
8. [UI 배치기](#8-ui-배치기)
9. [자주 겪는 증상](#9-자주-겪는-증상)

## 1. 통신 6종 — 송수신 4개 + 구동 2개

| 파일 | 방향 | 하는 일 |
|---|---|---|
| `Dg5fReceiver.cs` | 밖 → Unity | 손 20관절각 UDP 수신. **들고만 있고 관절에 쓰지 않는다** |
| `Dg5fHandDriver.cs` | (소비) | 수신 각도를 손가락 `xDrive.target`에 적용 |
| `Dg5fSender.cs` | Unity → 밖 | Unity 손 관절값을 손 브리지로 송신 |
| `UrArmReceiver.cs` | 밖 → Unity | 팔 6관절 실제각 수신 |
| `UrArmTwinDriver.cs` | (소비) | 그 값을 팔 `ArticulationBody`에 적용 (URSim→Unity 트윈) |
| `UrArmSender.cs` | Unity → 밖 | Unity 팔 목표각을 팔 브리지로 송신 |

**수신과 구동을 분리한 이유**: 값을 받는 것과 관절에 쓰는 것은 다른 결정이다. 자동/수동,
IK 활성, 프리셋 버튼 등 여러 주체가 "지금 이 값을 쓸지"를 각자 판단해야 하는데, 수신기가
직접 쓰면 그 판단을 끼워 넣을 자리가 없다.

### 1-1. `Dg5fReceiver.cs` (238줄) — 손 각도 수신

| 상수·필드 | 기본값 | 설명 |
|---|---|---|
| `ChannelCount` | 20 | `GetAngles(float[20])`가 **유일한 각도 접근 통로** |
| `port` / `ActivePort` | 5006 / `.env` | 인스펙터 `port`는 `.env`가 없을 때의 **최후 기본값**. 실제 사용 포트는 `ActivePort` |
| `secondsSinceLastPacket` | ∞ | 0.5 이상이면 송신 끊김으로 본다 |
| `FingerTipCount` / `WristTipCount` / `RawRadCount` | 4 / 5 / 20 | 확장 필드 개수 |
| `HasData` | — | 한 번이라도 받았는지 |

**패킷 길이 = 버전.** 앞 20개만 있으면 동작하고, 나머지는 길이를 보고 선택적으로 읽는다.

| 길이 | 버전 | 추가된 것 |
|---|---|---|
| 20f | v1 | 관절 20각 |
| 24f | v2 | 엄지끝 + 핀치 |
| 25f | v3 | 끝거리 비율 |
| 37f | v4 | 검지~새끼 리치벡터 |
| 52f | v5 | 손목→끝 벡터 5개 |
| **72f** | **v6 (현재)** | `compute_raw` 20채널 라디안 |

접근 메서드는 해당 필드가 안 온 패킷이면 `false`를 반환한다:
`GetThumbTip(out Vector3, out bool pinch)` · `GetFingerTip(int, out Vector3)` ·
`GetWristTipVector(int, out Vector3)` · `GetPinchDistance(out float)` · `GetRawRadians(float[20])`.

⚠️ **웹캠과 실물 손 피드백(echo)이 같은 5006으로 들어오며, 수신기는 출처를 구별하지 않는다.**

### 1-2. `Dg5fHandDriver.cs` (199줄) — 손 관절 구동

| 필드 | 기본값 | 설명 |
|---|---|---|
| `enableTracking` | true | 수신값 적용 여부 |
| `lerpSpeed` | 12 | 목표각 보간 속도 |
| `staleTimeout` | 1.0초 | 초과 시 **마지막 포즈 유지**(0으로 떨어지지 않는다) |
| `isolateJoint` | `None_전체동작` | 한 관절만 수신값으로 움직이고 19개를 0으로 얼리는 격리 디버그 |
| `debugThumbLog` / `logRadiansToFile` | **true** | 디버그용 임시 ON — **시연·측정 전에 끈다** |
| `JointLabels[20]` | — | 채널 이름. `dg5f_angles.CHANNEL_NAMES`와 **같은 순서여야 한다** |

**관절 매핑은 이름 매칭이지 순서 매칭이 아니다.** `Start()`가 자식 `ArticulationBody` 중
이름에 `_dg_`가 들어간 것만 골라 접미사 `_dg_<손가락1~5>_<마디1~4>`로 사전을 만든 뒤
패킷 인덱스 `(f-1)*4+(j-1)`에 꽂는다. 그래서 오른손(`rl_dg_*`)/왼손(`ll_dg_*`)이 같은 코드로 동작한다.

Console 로그가 1차 판정 기준이다.

```text
성공: 관절 매핑 20/20, 포트 5006 수신 대기
실패: [Dg5fHandDriver] 관절 못 찾음: _dg_f_j
```

활성 IK(`Dg5fFingerIK`)가 맡은 손가락은 건너뛴다 — 두 구동자가 같은 관절을 쓰면 결과가
실행 순서에 좌우된다.

### 1-3. `Dg5fSender.cs` (163줄) / `UrArmSender.cs` (145줄) — 실물로 내보내기

| 필드 | `Dg5fSender` | `UrArmSender` |
|---|---|---|
| `sendEnabled` | **false** | **false** |
| `bridgeIp` / `bridgePort` | 127.0.0.1 / 5008 | 127.0.0.1 / 5009 |
| `sendHz` | 50 | 10 (브리지 `--hz` 기본값과 짝) |
| `sendCommandedAngle` | true | true |
| `showUI` | true | false |

> **`sendEnabled`가 기본 false인 것은 안전 설계다.** 씬을 Play했다고 실물이 움직이면 안 된다.
> `sendCommandedAngle`이 true면 `xDrive.target`(목표각)을, false면 실측각을 보낸다.

### 1-4. `UrArmReceiver.cs` (117줄) / `UrArmTwinDriver.cs` (102줄) — 팔 트윈

| 클래스 | 필드 | 기본값 |
|---|---|---|
| `UrArmReceiver` | `ChannelCount` / `port` | 6 / 5010. `GetAngles(float[6])` |
| `UrArmTwinDriver` | `receiver` / `driveEnabled` / `lerpSpeed` | 참조 / **false** / 15 |

`driveEnabled`가 "URSim을 움직이면 Unity가 따라온다" 방향을 켜는 스위치다.

> ⚠️ **되먹임 루프 주의.** 송신과 수신을 동시에 켜면 서로를 덮어쓴다. 그래서 모드 전환
> 컴포넌트들(`Dg5fTwinModeSwitcher`, `PicknPlaceArmJointPanel`)이 방향을 상호배타로 강제한다.

## 2. 설정·상수 3종

### `RtautoConfig.cs` (150줄) — `.env`를 C#에서 읽는 어댑터

C#은 파이썬을 import할 수 없어 **같은 우선순위를 의도해 `.env`를 직접 파싱한다.**

| 멤버 | 설명 |
|---|---|
| `GetInt(key, fallback)` / `GetString(key, fallback)` | 환경변수 → `.env` → `.env.example` → `fallback` |
| `RepoRoot` / `GetRepoPath(relativeOrAbsolute)` | 저장소 루트 기준 경로. 루트를 못 찾으면 `null` |
| `SourceLabel` | 이번 세션이 어느 파일에서 읽었는지 문자열로 노출(진단용) |
| `EnsureLoaded()` / `Merge(path)` | 지연 로드 + 파일 병합 |
| `ResolveRepositoryRoot()` | `Application.dataPath`의 **두 단계 위** |

**절대 예외를 던지지 않는다.** 파싱 실패 시 조용히 `fallback`으로 떨어진다 —
설정 파일 하나 때문에 시연 씬이 죽으면 안 되기 때문이다.

### `UrArmJointNames.cs` (18줄) / `UrArmLimits.cs` (43줄)

| 상수 | 값 | 근거 |
|---|---|---|
| `UrArmJointNames.Names` | UR16e 6관절 링크 이름 | URDF |
| `UrArmLimits.MaxDegPerSec` | `{120, 120, 180, 180, 180, 180}` | 실물 사양 |
| `UrArmLimits.MaxEffortNm` | `{330, 330, 150, 54, 54, 54}` | 〃 |
| `UrArmLimits.IndexOf(linkName)` | 링크 이름 → 인덱스 | — |

⚠️ `Names`는 `Dg5fPicknPlaceSpec.ArmLinks`와 **함께 갱신**해야 한다(순환 참조 회피용 의도적 중복).
속도·토크 한계는 학습 에이전트와 씬 빌더도 공용으로 참조한다.

## 3. 물리 셋업 3종 — "안 붙이면 로봇이 떨린다"

URDF를 Unity에 넣었을 때 생기는 고질적 문제를 막는 스크립트다. **증상이 곧 존재 이유**다.

| 파일 | 하는 일 | 안 붙이면 |
|---|---|---|
| `RobotSelfCollisionIgnore.cs` (78줄) | 로봇 자기 콜라이더끼리의 충돌 무시. `ignoreSelfCollision`(true), `toggleKey`, `SetIgnoreSelfCollision(bool)`, `ToggleSelfCollision()` | 인접 손가락 마디가 설계상 겹쳐 있어 PhysX가 밀어내고 드라이브가 되끌어오는 **접촉 진동**(명령 0인데 ±20~100° 발진) |
| `RobotInitialPoseSync.cs` (30줄) | Play 시작 시 관절 실제 위치를 목표값으로 텔레포트 | 영점 자세에서 목표 자세로 팔이 홱 들려 손가락이 채찍처럼 휘둘리고 수십 초 출렁임 |
| `RobotConfig.cs` (168줄) | 관절 게인·리밋 단일 출처. 값마다 출처를 `[REAL-UR]/[REAL-URDF]/[PLACEHOLDER]`로 표시 | 값이 여러 파일로 흩어짐 |

`RobotConfig`의 주요 기본값: `armStiffness 10000` / `armDamping 200` /
`handStiffness 10000` / `handDamping 200` / `handForceLimit 1000` /
`useGravity false` / `baseImmovable true` / `kinematicMirrorMode true`.
`JointSpec` 구조체는 `label`·`link`·`minDeg`·`maxDeg`·`maxVelDeg`·`maxEffortNm`을 담고,
`LoadDefaults()` / `Apply()` / `TryGetSpec(link, out spec)`으로 쓴다.

> ⚠️ **`RobotConfig.cs`는 UR5e + SVH 시절 파일이다.** 현재 학습 물리값이 아니다.
> 학습 씬의 드라이브 정본은 `Dg5fPicknPlaceSpec.ArmDriveStiffness/Damping`(10000/200)과
> `HandDriveStiffness/Damping/ForceLimit`(1500/120/20)이다.

## 4. 수동 조작·IK 5종

| 파일 | 줄 수 | 하는 일 |
|---|---|---|
| `HandSliderUI.cs` | 185 | 화면 슬라이더로 관절을 직접 돌린다. `armJoints`/`handJoints`(`JointSlider[]`), `showArm`, `driveHandJoints`, `LoadDefaults()`, `ResyncArmValuesFromCurrentPose()`. 현재는 Preview 씬 검수용 |
| `ArmTargetIK.cs` | 250 | 목표 오브젝트 위치로 손끝을 보내는 **CCD IK**(위치만, 자세 미제어) |
| `Dg5fFingerIK.cs` | 751 | **손끝 위치 리타게팅.** 사람 손끝 위치를 로봇 손 치수로 복원해 그 손가락 4관절을 IK로 보낸다 |
| `Dg5fFingerIKMode.cs` | 66 | 5개 손가락 IK의 구동 방식을 드롭다운 하나로 일괄 전환(Play 중 A/B 비교용). `applyToAll`(true) |
| `Dg5fIKVectorDebug.cs` | 86 | IK가 이번 프레임에 계산한 목표 벡터를 선으로 그린다. **산식을 복제하지 않고 값을 읽어 그린다** |

### `ArmTargetIK.cs`의 안정화 장치

CCD IK를 그냥 돌리면 급발진·헌팅·특이점 고착이 난다. 그래서 필드 대부분이 **제동 장치**다.

| 필드 | 기본값 | 역할 |
|---|---|---|
| `threshold` | 0.02 m | 도달 판정 거리 |
| `maxStepDeg` | 1.8° | FixedUpdate당 관절 최대 변화 (50Hz 기준 90°/s 상한) |
| `maxAccelDeg` | 0.12° | 스텝 **증가**의 프레임당 상한 — 급발진 채찍질 방지 |
| `distalStepScale` | 0.6 | 손목 3관절의 스텝 상한 비율(레버가 짧아 같은 각도가 더 크게 흔들린다) |
| `deadbandDeg` | 0.25° | 이 이하 오차는 무시 — 미세 헌팅 방지 |
| `rearmFactor` | 1.5 | 도달 후 `threshold×이 배수`를 넘어야 재가동(히스테리시스) |
| `windupDeg` | 15° | 명령이 실제 관절각보다 앞설 수 있는 최대치 |
| `reachMargin` | 0.88 | 링크 길이 합 대비 사용 반경 비율 |
| `stallFreezeSec` / `stallResumeMove` | 1.5초 / 0.03 m | 개선이 없으면 동결, 타겟이 이만큼 움직이면 해제(관절 한계·특이점 대비) |
| `signs[6]` | 전부 1 | 회전 부호가 반대인 관절만 −1 |

### `Dg5fFingerIK.cs`가 존재하는 이유

채널별 각도 매핑만으로는 **엄지의 결합운동(OK 사인 등)** 을 재현할 수 없다. 그래서 손끝
"위치"를 목표로 삼아 4관절을 푼다. 손가락 5개가 같은 컴포넌트를 `fingerIndex`만 바꿔 공유한다.

| 필드 | 기본값 | 역할 |
|---|---|---|
| `fingerIndex` | 1 | 1=엄지 … 5=새끼 |
| `ikMode` | `AnatomicalReach` | 구동 방식(`FingerIKMode` enum) |
| `maxStepDeg` / `iterations` | 1.0° / 1 | 스텝 상한·반복 횟수 |
| `enablePinchBlend` / `pinchOffset` | true / 0.012 m | 핀치 구간 블렌딩 |
| `robotThumbMaxReach` | 0.124 m | 로봇 엄지 최대 리치(치수 복원 기준) |
| `reachOffset` | `(0.174, -0.038, -0.092)` | 사람↔로봇 좌표 오프셋 |
| `targetLerp` / `softZone` / `windupDeg` | 6 / 0.015 m / 15° | 목표 보간·완충대·와인드업 |
| `priorGain` / `priorWeights[4]` / `priorStepRatio` / `priorAngleLerp` | 3 / 전부 1 / 0.3 / 4 | 자연스러운 자세로 끌어당기는 사전(prior) |
| `pinchNear` / `pinchFar` | 0.32 / 0.55 | 핀치 판정 구간 |
| `debugShowTip` / `debugLogCsv` / `debugLogFlushEvery` | true / true / 100 | 디버그 시각화·CSV |

노출 프로퍼티 `Active`(지금 이 손가락을 IK가 구동 중인가)와 `CurrentTarget`을
`Dg5fHandDriver`와 `Dg5fIKVectorDebug`가 읽는다.

## 5. 로깅 2종

| 파일 | 하는 일 |
|---|---|
| `Dg5fLogFile.cs` (46줄) | `Logs/` 아래 CSV를 여는 **유일한 통로**. `Create(prefix, out path)` |
| `Dg5fJointLogger.cs` (73줄) | 50Hz로 [수신값 / 목표각 / 실측각] 20관절 CSV 기록. `flushEverySamples`(100) |

**절대 덮어쓰지 않는다.** `Logs/<prefix>_<초단위 타임스탬프>.csv`, 같은 이름이 있으면 접미사를
붙인다 — 같은 분에 두 번 Play해 앞 로그가 사라지던 사고 때문이다.

현재 이 통로를 쓰는 것: `Dg5fJointLogger`(`unity_dg5f_*`), `Dg5fHandDriver`(`rad_dg5f_*`),
`Dg5fFingerIK`(IK 디버그).

타임스탬프가 **unix 초**라 파이썬 비전 로그와 그대로 시간 정렬된다 →
`vision/dg5f/analyze_teleop.py`로 분석한다. 다른 PC 로그를 비교하려면 두 PC의 시계도 맞아야 한다.

- Editor 로그: `unity/Logs/`
- Windows 플레이어 로그: 실행파일 옆 `Logs/`
- ⚠️ 여기서 **실측각은 Unity 물리 관절의 현재각**이며 실물 장비 센서값이 아니다.

## 6. 씬 소품 생성기 3종

| 파일 | 하는 일 |
|---|---|
| `RandomPillarGenerator.cs` (39줄) | 정적 팩토리 `Create(...)`. `PillarShape { Box, Cylinder }` |
| `RandomPillarSpawner.cs` (37줄) | 기둥 하나를 무작위 크기로 생성/제거. `minHeight 0.5` ~ `maxHeight 2.0`, `minWidth 0.1` ~ `maxWidth 0.4`. `Spawn()` / `Clear()` / `Pillar` |
| `RandomShelfStack.cs` (64줄) | 선반 더미 생성. `plateCount 5`, 폭 0.3~1.0, 깊이 0.3~1.0, 두께 0.02, 간격 0.15~0.4. `Build()` / `Clear()` |

학습 씬 장애물·배경 실험용이며 **현재 파이프라인의 필수 요소는 아니다.**

## 7. 브리지 런처

`UrArmBridgeLauncher.cs` (177줄) — Unity에서 **버튼 하나로** 팔 브리지를 띄우고 내린다.
터미널을 따로 열어 venv를 켤 필요를 없앤다.

| 인스펙터 필드 | 기본값 |
|---|---|
| `scriptRelativePath` | `arm/ur_rtde_bridge.py` |
| `arguments` | `--ip --echo-to-unity` (값 없는 `--ip` = `.env`의 로봇 IP 사용) |
| `showWindow` | true |

파이썬 실행파일은 `.env`의 `RTAUTO_PYTHON`. 상태는 `IsRunning` / `Status`로 노출된다.

> **Play를 멈추거나 `OnDestroy`에서 반드시 프로세스를 죽인다.** 살아남으면 포트를 쥐고 있고,
> 더 나쁘게는 계속 명령을 보낸다.

## 8. UI 배치기

`DemoUiLayout.cs` (80줄) — 화면 HUD 박스들이 서로 겹치지 않게 좌표를 계산해 쌓는 **공용 배치기**.
각 패널이 y좌표를 직접 박아 두던 시절 실제로 여러 번 겹쳤다.

| 멤버 | 값·역할 |
|---|---|
| `LeftWidth` / `RightWidth` | 280 / 264 |
| `Margin` / `Gap` | 10 / 6 |
| `Left(height)` / `Right(height)` | 다음 박스의 `Rect`를 돌려주고 커서를 내린다 |
| `LeftRemaining()` / `RightRemaining()` | 남은 세로 공간 |

프레임과 `EventType`을 추적해 `BeginPassIfNeeded()`로 매 패스 커서를 초기화한다 —
`OnGUI`가 한 프레임에 여러 번 호출되기 때문이다.

## 9. 자주 겪는 증상

| 증상 | 확인 순서 |
|---|---|
| 손이 전혀 안 움직임 | ① 비전 미리보기에서 손이 잡히는가 → ② Console의 `관절 매핑 20/20` 로그와 포트 → ③ 자동/수동·프리셋 제어권·트윈 방향 |
| 주먹 버튼 뒤 웹캠이 안 먹음 | `Dg5fFistButton.ReleaseHandToTracking()`(웹캠 복귀 버튼)을 눌렀는가 |
| 명령 0인데 손가락이 발진 | `RobotSelfCollisionIgnore`가 붙어 있는가 |
| Play 시작에 로봇이 채찍질 | `RobotInitialPoseSync`가 붙어 있는가 |
| Unity는 움직이는데 실물이 멈춤 | `Sender`의 `sendEnabled`, 브리지의 드라이런 여부 |
| 포트를 바꿨는데 반영 안 됨 | `ActivePort`(실사용)와 인스펙터 `port`(최후 기본값)를 혼동하지 않았는가. `RtautoConfig.SourceLabel`로 어느 파일을 읽었는지 확인 |

## 관련 문서

- [`docs/modules/UNITY.md`](../../../docs/modules/UNITY.md) — Unity 모듈 전체 설명(정본)
- [`unity/README.md`](../../README.md) — 프로젝트 개요·씬·메뉴
- [`unity/Assets/MLAgents/README.md`](../MLAgents/README.md) — RL 런타임(이 어셈블리를 참조한다)
- [`arm/README.md`](../../../arm/README.md) · [`vision/README.md`](../../../vision/README.md) — 짝이 되는 Python 브리지

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/Assets/Scripts/README.md`
- **갱신 대상**: `unity/Assets/Scripts/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/UNITY.md` §9
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

