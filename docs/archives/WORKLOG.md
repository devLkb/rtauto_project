# UR5e + Tesollo DG5F 디지털 트윈 작업 기록

> 현재 목표: **3D 목표 좌표 → 강화학습 기반 UR5e 팔 이동 → DG5F 손 원격조작**.
> 초기 SCHUNK SVH 및 웹캠 텔레옵 기록은 아래에 실험 이력으로 보존한다.
> 작성일: 2026-06-30 · 최종 갱신: 2026-07-20

---

## 0. 환경 / 도구

| 항목 | 값 |
|------|-----|
| Unity | 6000.4.0f1, **Built-in Render Pipeline** |
| Unity 프로젝트 | `C:\Users\dltmd\UnityProjects\cli_test\KDT_robot_AI` |
| 제어 도구 | **unity-cli** (커넥터 v0.3.22, port 8090) — 터미널에서 Unity Editor 제어 |
| 입력 자료 | `dex-urdf-main`(SVH·UR5e, plain URDF+OBJ), `Universal_Robots_ROS2_Description-rolling`(UR 공식, xacro) |
| 빌드 작업 폴더 | `C:\Users\dltmd\Desktop\KDT\ur5e_svh_build\` |
| Python | 3.11.7 (xacro, lxml 설치) |

**통신 방식 결정:** ROS2 없이 진행. 웹캠→MediaPipe→Unity 단방향 텔레오퍼레이션에는
ROS2(+WSL2+ROS-TCP-Connector)가 과해서, **Python이 UDP/JSON으로 관절각을 Unity에 직접 전송**하는 구조 채택.

---

## 1. unity-cli 설치 & 연결

- CLI 바이너리는 이미 `%LOCALAPPDATA%\unity-cli`에 있었고 **v0.3.0 → v0.3.22**로 업데이트.
- Unity 커넥터 패키지는 `manifest.json`에 등록돼 있었음. CLI와 버전을 맞추려고 **`#v0.3.22` 태그로 고정**.
- `unity-cli status` → `Unity: ready` 확인.

> **문제 ①** — `status`가 `not responding (heartbeat 794h前)`.
> **원인**: Unity Editor가 꺼져 있었음 + CLI/커넥터 버전이 어긋날 우려.
> **해결**: CLI 업데이트 + 커넥터 git URL을 `#v0.3.22`로 고정 → 프로젝트 열면 버전 일치 상태로 자동 재해석.

---

## 2. Phase 0 — dex-urdf 모델 임포트 (1차 시도)

1. `com.unity.robotics.urdf-importer` 패키지 추가.
2. dex-urdf의 **이미 펼쳐진(flat) `ur5e.urdf` + `schunk_svh_hand_right.urdf`** 와 OBJ 메시를 `Assets/Robots/`로 복사(상대경로 구조 유지).
3. `unity-cli exec`로 `UrdfRobotExtensions.Create(...)` 호출 → ArticulationBody 로봇 생성.

결과: `ur5e_robot`(ArticulationBody 9), `svh`(28, 메시 23) 임포트·렌더링 성공.

> **문제 ②** — exec C# 코드에 `Object.DestroyImmediate` 사용 시 컴파일 에러
> (`'Object'가 UnityEngine.Object와 System.Object 사이에서 모호`).
> **해결**: `UnityEngine.Object.DestroyImmediate`로 정규화.

> **문제 ③** — PowerShell에서 exec에 C# 멀티라인 코드를 넘길 때 escaping이 깨짐.
> **해결**: C# 코드를 파일로 저장 후 **stdin 파이프**(`cat script.cs | unity-cli exec`)로 전달.

> **참고**: dex-urdf의 상대 mesh 경로(`meshes/visual/...`)가 URDF-Importer에서 그대로 해석돼 경로 변환 불필요.
> 콘솔의 "mesh has no normals, recalculating" 경고는 OBJ 임포트 시 정상(에러 아님).

---

## 3. 결합 URDF 빌드 — 공식 UR xacro 처리 + SVH 합치기

> 사용자 요청: dex-urdf의 ur5e 대신 **공식 UR ROS2 description**을 xacro로 처리해 SVH와 결합한
> **단일 URDF**를 생성. 산출물 = `ur5e_svh_right.urdf` + Unity용 mesh 폴더.

### 3-1. UR5e xacro → flat URDF (`convert_ur.py`)

ROS 없이 Windows에서 처리:
- `pip install xacro lxml`
- xacro가 `$(find ur_description)`를 `ament_index_python.get_package_share_directory`로 해석함 →
  **가짜 `ament_index_python` 모듈을 `sys.modules`에 주입**해 UR 레포 루트를 반환하게 함.
- `xacro.process_file(ur.urdf.xacro, mappings={ur_type:ur5e, name:ur5e, force_abs_paths:false})`
- 결과 `ur5e_raw.urdf` (UTF-8). mesh 14개 모두 `package://ur_description/meshes/ur5e/...` 형태 ✅

> **문제 ④** — `xacro`가 ROS 패키지 경로 해석기(ament)에 의존해 순수 Windows에서 `$(find)` 실패.
> **해결**: 실제 ROS 설치 대신 **가짜 ament 모듈 주입**으로 ur_description 경로만 실제 폴더로 리턴.
> (UR 레포 루트가 이미 `urdf/ meshes/ config/`를 직접 포함하므로 그 경로를 그대로 사용.)

### 3-2. UR5e + SVH 결합 (`merge.py`, lxml)

- **이름 충돌 해결**: UR·SVH 둘 다 `base_link` 존재 → SVH의 `base_link`를 **`svh_base_link`로 rename**
  (링크 정의 + 이를 참조하는 joint의 parent/child 모두).
- **연결**: UR `tool0` → `svh_base_link`를 **fixed joint**로 부착(origin 0 0 0).
- **mesh 경로 통일**: UR `package://ur_description/meshes/` → `meshes/ur/`,  SVH `meshes/` → `meshes/svh/`.
- **mimic joint 11개 보존**.
- robot name = `ur5e_svh`.

검증 결과:
- 링크 **42** / 관절 **41** (= UR 13링크/12관절 + SVH 29링크/28관절 + 연결 1관절) ✅
- `world` 단일 루트에서 모든 링크 도달 가능, 손가락 끝 5개(fftip/thtip/mftip/rftip/lftip) 전부 연결 ✅
- mimic 11개 보존, mesh 참조 52개(고유 42) ✅

### 3-3. Unity용 mesh 폴더 (`unity_pkg/`)

```
unity_pkg/
├── ur5e_svh_right.urdf
└── meshes/
    ├── ur/ur5e/visual(.dae ×7) + collision(.stl ×7)   ← UR 공식 레포
    └── svh/visual(.obj ×23,.mtl ×2) + collision(.obj ×14)  ← dex-urdf (.glb 제외)
```
- **참조 메시 42개 전부 존재, 누락 0** ✅

> **참고**: SVH는 `.glb`가 아니라 `.obj`를 사용(Unity 호환). UR visual은 `.dae`, collision은 `.stl`.
> ur5e는 외부 텍스처가 없어(텍스처는 ur15/ur20 등 다른 모델용) `.dae` 내장 색상으로 충분.

### 3-4. Unity 임포트

- `unity_pkg` → `Assets/unity_pkg/`로 복사.
- 기존 분리 임포트(`Assets/Robots`, `ur5e_robot`/`svh`) 삭제.
- 임포트 설정 **Axis = Y, Mesh Decomposer = vHACD**로 `UrdfRobotExtensions.Create` 실행.
- 결과: 단일 로봇 **`ur5e_svh`** (ArticulationBody 41, 렌더러 50), 손이 `tool0`에 부착 확인.
- 재질 정상(UR 파란/은색) — **마젠타 깨짐 없음**.

> **문제 ⑤** — URP/HDRP 프로젝트면 URDF 임포트 시 머티리얼이 마젠타로 깨짐.
> **해결(예방)**: 임포트 전 `ProjectSettings/GraphicsSettings.asset`에서 SRP 미할당(`m_CustomRenderPipeline: {fileID: 0}`) 확인 → **Built-in RP** 확정.

---

## 4. Phase 1 — mimic 처리 + 씬 정비 + 구동 테스트

### 4-1. MimicJointController (`Assets/Scripts/MimicJointController.cs`)

- Unity URDF-Importer는 URDF `<mimic>`을 **자동 처리하지 않음** → 직접 구현.
- 로봇 루트에 부착하는 MonoBehaviour. `FixedUpdate`마다
  `mimic.xDrive.target = multiplier * source.xDrive.target + offset`.
- ArticulationBody는 **child link 이름의 GameObject**에 붙으므로, link 이름으로 자동 해석.
- SVH 오른손 mimic 11개 매핑 내장(`DefaultSvhRight`). 부착 후 **11/11 해석 성공**.

| mimic(child) | source(child) | multiplier |
|---|---|---|
| e2 | z (ThumbOpp) | 1.0 |
| b | a (ThumbFlex) | 1.01511 |
| c | a (ThumbFlex) | 1.44889 |
| t | p (IdxDist) | 1.045 |
| s | o (MidDist) | 1.0454 |
| n | j (Ring) | 1.3588 |
| r | j (Ring) | 1.42093 |
| m | i (Pinky) | 1.3588 |
| q | i (Pinky) | 1.42307 |
| virtual_l | virtual_i (Spread) | 0.5 |
| virtual_j | virtual_i (Spread) | 0.5 |

### 4-2. 씬 정비

- 바닥 Plane(`Ground`) + 그림자, Main Camera 프레이밍, Directional Light 조정.
- 로봇을 바닥(y=0) 위에 정렬.

### 4-3. 구동 테스트 (Play 모드)

- 9개 구동 관절에 `xDrive.target`(도) 설정 → 손가락 쥐기/펴기 + mimic 말단 굽힘 확인.
- 수치 검증: index distal `p` 65° → mimic `t` 67.2°(≈1.045×), thumb `a` 47° → `b` 47.8°·`c` 66.8° ✅

> **문제 ⑥ (가장 중요)** — target을 줘도 **손가락이 안 움직임**.
> **원인 1**: URDF-Importer가 임포트한 xDrive의 **stiffness=damping=forceLimit=0** → 힘이 안 실림.
> **원인 2**: URDF-Importer가 **Play 시작 시 루트 `Controller`가 각 관절에 `JointControl`(키보드 조작용)을
> 런타임 추가**해서 매 프레임 target을 자기 값으로 덮어씀.
> **해결**:
> 1. edit 모드에서 루트 **`Controller` 컴포넌트 제거** (→ Play해도 JointControl이 추가되지 않음).
> 2. 모든 revolute ArticulationBody에 **stiffness=10000 / damping=200 / forceLimit=1000** 설정.
> (JointControl은 edit 모드엔 없고 Play 때 생성되는 것이라, edit 모드 제거 시도에선 0개로 보였던 것.)

> **문제 ⑦** — Play 중 팔이 **중력으로 처짐**. 디지털 트윈은 명령 포즈를 그대로 유지해야 함.
> **해결**: 모든 ArticulationBody `useGravity=false` + 루트 `immovable=true`(베이스 고정).
> → 명령한 포즈를 처짐 없이 유지.

> **참고**: 손가락 사이 틈은 버그가 아니라 SCHUNK SVH(텐던 구동·기계식 링키지) 모델의 시각 메시 특성.

---

## 5. 현재 상태 / 산출물

**씬** `Assets/Scenes/SampleScene.unity` — 루트: `Main Camera`, `Directional Light`, `ur5e_svh`, `Ground`.

**로봇 `ur5e_svh`** 구성:
- ArticulationBody 41, 구동 가능한 단일 로봇(UR5e 6축 + SVH 9 DOF + mimic 11).
- `MimicJointController` 부착, 전 바디 `useGravity=false`, 베이스 고정, 기본 팔 포즈.
- 구동 9 DOF child link: `a`(ThumbFlex) `z`(ThumbOpp) `l`(IdxProx) `p`(IdxDist) `k`(MidProx) `o`(MidDist) `j`(Ring) `i`(Pinky) `virtual_i`(Spread). target 단위 = **도(deg)**.

**파일**
| 위치 | 내용 |
|------|------|
| `KDT/ur5e_svh_build/convert_ur.py` | UR xacro → flat URDF |
| `KDT/ur5e_svh_build/merge.py` | UR5e + SVH 결합 |
| `KDT/ur5e_svh_build/extract_joints.py` | 관절 child-link 매핑 추출 |
| `KDT/ur5e_svh_build/unity_pkg/` | 결합 URDF + mesh (배포본) |
| `Assets/unity_pkg/` | Unity 임포트본 |
| `Assets/Scripts/MimicJointController.cs` | mimic 연동 |
| `Assets/Scripts/HandSliderUI.cs` / `RobotConfig.cs` | Play 중 수동 슬라이더 + 관절 사양 단일 출처 |
| `Assets/Scripts/SvhReceiver.cs` / `SvhHandDriver.cs` | UDP 9각도 수신 → 관절 주입 (Phase 3) |
| `Assets/Scripts/SvhJointLogger.cs` | 추종 품질 CSV 로거 (검증용) |
| `Assets/Scripts/SvhSelfCollisionIgnore.cs` | 로봇 자기충돌 차단 (진동 수정) |
| `Assets/Scripts/SvhInitialPoseSync.cs` | Play 시작 시 목표 포즈 텔레포트 (초기 킥 제거) |
| `KDT/svh/` | 비전 파이프라인 + 보정 + 분석 스크립트 (상세: PROJECT_HANDOFF.md) |
| `KDT/backups/SampleScene_*.unity` | 씬 수정 전 백업들 |

---

## 6. (2026-07-02) Phase 2·3 — 비전 파이프라인 & Unity 수신 배선

> Python 쪽 상세는 `PROJECT_HANDOFF.md` 참고. 여기는 요약 + Unity 배선.

- **Phase 2** (`svh/` 폴더): `svh_angles.py`가 MediaPipe 21 landmark → SVH 9각도(rad) 계산,
  `vision_node.py`가 웹캠 캡처 → One Euro 필터 → **UDP 127.0.0.1:5005, `<9f` (float32×9)** 송신.
  가동범위는 dex-urdf `<limit>` 값. `calibrate_raw.py`로 개인 손 보정(`calibration.json`).
- **Phase 3** (`Assets/Scripts/`): `SvhReceiver.cs`(UDP 수신 스레드, rad) + `SvhHandDriver.cs`
  (패킷 index→**링크 이름** 매핑, rad→deg, HandSliderUI 슬라이더에 주입해 기존 lerp/xDrive 재사용).
- **패킷 순서**(SVH 드라이버 JTC/SVHChannel enum과 동일):
  `[0]ThumbFlex [1]ThumbOpp [2]IdxDist [3]IdxProx [4]MidDist [5]MidProx [6]Ring [7]Pinky [8]Spread`

> **문제 ⑧** — 패킷은 검지·중지가 **Distal→Proximal** 순인데 Unity 쪽 관례는 Prox→Dist.
> **해결**: 위치 매핑 금지, `SvhHandDriver.PacketIndexToLink`에서 **링크 이름으로** 매핑.
> **문제 ⑨** — `udp_test_receiver.py`가 127.0.0.1:5005에 살아 있으면(더 구체적 바인딩 우선)
> Unity로 패킷이 안 감. **Unity Play 중엔 테스트 리시버 종료 필수.**

프로브 패킷(웹캠 없이) 검증: 주먹 패킷 → 9관절 xDrive.target 기대값 정확 일치 ✅

---

## 7. (2026-07-02) SVH 메시·콜리전 정렬 최종 수정

**증상**: SVH 손의 시각 메시가 흩어져 보임(1차), 수정 후엔 손가락 콜리전이 회전 어긋남 + 손바닥 메시 위치 밀림(2차, 사용자 스크린샷으로 발견).

**핵심 사실(.obj 실측)**: 같은 링크의 visual .obj와 collision .obj는 **같은 프레임으로 제작**돼 있음
(bounds 크기·중심 일치). → 보정 회전은 Visuals와 Collisions **둘 다에 동일하게** 필요.
1차 수정이 Visuals에만 회전을 걸어 콜리전이 어긋난 채 남았던 것.

**최종 상태**(SampleScene.unity 저장):
| 대상 | 수정 |
|------|------|
| 손가락 지골 15개 (a,b,c,l,p,t,k,o,s,j,n,r,i,m,q) | `Visuals`·`Collisions` 둘 다 localRot **(0,270,180)** (origin=0이라 최상위 회전으로 충분) |
| base_link | Visuals 최상위 identity 복원, **origin 아래 메시 노드**에 (270,0,270) |
| e1 / e2 | 같은 방식, 둘 다 (270,0,90) |
| z (엄지베이스) | 같은 방식, (270,0,270) — 1차에서 "정상"으로 오판됐던 링크 |
| 콜리전 primitive(박스/원통) | URDF가 링크 프레임에 직접 정의 → 원래 정상, 불변 |

> **문제 ⑩** — 회전을 Visuals **최상위**에 걸면 URDF origin 오프셋까지 회전해 **위치가 밀림**.
> **해결**: origin 노드 아래 메시 노드에 회전 적용.
> **판정지표(신뢰순)**: ① 메시 정점→콜라이더 `Physics.ClosestPoint` 평균거리(24개 축정렬 회전 전수탐색)
> ② 링크로컬 **합성** 콜라이더 bounds(vHACD 다중 hull이라 전체 Encapsulate 필수) ③ 스크린샷.
> 최종 19링크 전부 0.1~9.6mm(잔차는 visual이 구동하우징 포함해 더 큰 정상 차이).

---

## 8. (2026-07-02) 라이브 웹캠 테스트 & 진동 디버깅

### 8-1. 계측 인프라

| 파일 | 역할 |
|------|------|
| `Assets/Scripts/SvhJointLogger.cs` | 매 FixedUpdate에 수신값/목표값/실제 관절각 CSV 기록 (`svh/unity_joint_log.csv`) |
| `svh/vision_node.py` (로깅 추가) | raw/필터후 각도 + 검출여부 CSV (`svh/vision_log.csv`) |
| `svh/analyze_tracking.py` | 두 로그 unix time 정렬 → 채널별 노이즈σ/스파이크/추종RMSE/지연 + `tracking_report.png` |

### 8-2. 라이브 테스트 결과 (1차)

- 비전→Unity 매핑·추종은 동작하나 **로봇 손가락이 까딱까딱 진동 + 펴도 접혔다 펴짐**.
- 분석: **보낸 명령(filtered)은 홀드 구간에서 평평** → 비전/필터 문제 아님.
  **실제 관절각(act)만 명령 0인 구간에서도 ±20~100° 진동** → Unity 물리 문제.

### 8-3. 원인 사슬 (이분법 실험으로 하나씩 규명)

> **문제 ⑪** — 인접 지골 콜라이더가 설계상 겹침(최대 13.5mm) + 손베이스↔팔 플랜지 겹침.
> **해결**: `SvhSelfCollisionIgnore.cs` — 로봇 내 전 콜라이더 쌍(990쌍) `Physics.IgnoreCollision`.
> (디지털 트윈은 자기충돌 불필요, 외부 물체와는 충돌 유지)
> **문제 ⑫** — virtual 너클 링크 4개의 관성이 임포터 디폴트 **(1,1,1) kg·m²**(5자릿수 과대),
> inertial 없는 지골들 질량 1.0kg 디폴트. **해결**: 실물 기준 질량 재배분(총 ~1.3kg) + `ResetInertiaTensor()`.
> **문제 ⑬ (핵심)** — **forceLimit=1000 포화**. 오차·속도가 조금만 커지면 요구 토크가 상한에 잘려
> 드라이브가 ±1000 뱅뱅 제어기가 됨 → 스스로 진동 유지. damping을 15배 올려도 무효(어차피 포화).
> **해결**: 손 관절 20개 **forceLimit 1000 → 100000**, damping 200 유지.
> **문제 ⑭** — Play 시작 시 관절이 URDF 영점에서 목표 포즈로 **홱 이동하며 손가락을 채찍질**(초기 킥).
> **해결**: `SvhInitialPoseSync.cs` — Start에서 jointPosition=target 텔레포트 + 속도 0.

### 8-4. 검증 결과

- **무입력 정지**: 전 관절 σ=0.000 — 진동 완전 소멸 ✅
- **주먹 프로브**: 목표 도달 ±2° 이내 ✅
- **⚠️ 미해결**: 주먹↔펴기 반복 후 잔여 출렁임(관절이 limit 밖 음수까지, 속도 1.3 rad/s 유지).
  damping 정상 적용에도 속도가 안 죽음 → **긴 체인 말단 초경량 링크에서 솔버 수렴 부족** 의심.

---

## 9. 다음 단계

1. **진동 잔여 해결**: 루트 ArticulationBody solverIterations 증가(32→128) → 부족 시
   fixedTimestep 0.02→0.01 → 그래도면 손가락 질량 상향/관절 limit 강제.
   → **§10에서 원인 특정으로 종결** (solver/질량 카드가 아니라 mimic 지골 드라이브가 원인).
2. **라이브 웹캠 재검증**: vision_node.py + Unity Play, `analyze_tracking.py`로 추종 품질 정량 확인.
3. thmOpp 방향 최종 판단(반대면 `svh_angles.py` min/max 스왑), spread 가동 확인.
4. One Euro/rate limit 튜닝(Phase 4), 이후 손목 pose → UR5e IK.

---

## 10. 진동 원인 특정 (2026-07-07 야간) ✅

7/7 하루 종일의 소거 진단(기각 가설 20개) 끝에 **런타임 비영속 이분법**으로 원인 확정.
전 과정·데이터는 `DEBUG_OSCILLATION_20260707.md` §8, 산출물은 `svh/diag_20260707/night_copyprobe/`.

- **방법**: 플레이 중 Instantiate 복제(씬 무수정)로 재현 범위를 축소 —
  로봇 전체 복제(재현) → 콜라이더 제거(무변화) → 손만(재현) → 검지 5바디만(재현)
  → **t(mimic 원위지골)+fftip 제거 → p2p 0.00° 완전 안정**.
- **원인**: 7/2에 "모든 revolute에 stiffness 10000/damping 200"을 일괄 적용하면서 **mimic 지골
  관절(t·s 등, 관성 ~1e-6 kg·m²)**에도 걸림 → 해당 관절이 수치 불안정 스프링이 되어 부모
  구동체인(l·p, k·o)으로 에너지를 퍼올림. z·virtual_i가 늘 정상이던 것, 검지·중지가 최악이던 것,
  mimic-OFF가 부분 완화에 그친 것 모두 이 구조로 설명됨.
- **수정 후보(미적용, 사용자 결정 대기)**: ① mimic 관절만 게인 하향(stiffness 100~500+임계감쇠)
  ② mimic 링크 선별 관성 상향. 최소 재현계(검지 5바디 복제)에서 A/B 검증 후 씬 적용 권장.

---

## 11. 기하 검증 + Solver Type TGS 전환 (2026-07-08)

상세: [DEBUG_OSCILLATION_20260708.md](DEBUG_OSCILLATION_20260708.md), 산출물 `svh/diag_20260708/`.

- **실험 A — 기하 전수 비교(기각)**: 정상(z, virtual_i) vs 진동(p, l, o, k) 6관절의
  앵커(월드 불일치 ≤0.0002mm/0.000°, matchAnchors 전부 True)·조상 스케일(전부 1)·URDF axis 대조
  (z만 `0 0 -1` → anchorRotation z=90°로 정확 반영) 전부 결백. **부모-상대 각속도 vs twist축
  사잇각 0.2~1.9°** — 전 관절이 자기 축대로만 회전(reduced coordinate라 축 이탈은 구조적으로 불가).
  함정: 월드 ω로 재면 정상 관절이 되레 59~71° 어긋나 보임 = 손바닥 흔들림(e1 최대 3.2rad/s, 팔로
  에너지 역류) 상속분.
- **실험 B — Solver Type PGS→TGS(부분 개선, 유지 중)**: `m_SolverType` 0→1만 변경 후 동일 프로브
  A/B. 진폭 대략 절반(p p2p 405→192°, l 144→61°), 주먹 추종오차 절반, l·k 리밋 침범 깊이
  −27/−36→−6/−10°. 단 침범 빈도 불변(22~43%), p·o는 여전히 −72~−86° 관통 → **필요조건이지 근본
  수정 아님**. §10 원인(초경량 mimic 지골 드라이브)과 수정 후보는 그대로 유효하며, 이후 A/B는
  TGS 위에서 재평가할 것.

---

## 12. ✅ 진동 완전 해결 — 임포터 기본값 관성 수정 (2026-07-08)

상세: [DEBUG_OSCILLATION_20260708.md §3](DEBUG_OSCILLATION_20260708.md). 데이터 `svh/diag_20260708/after_fixdefaults.csv`.

- **측정(수정 없이 전수 조사)**: 팁 5개(thtip/fftip/mftip/rftip/lftip)가 임포터 기본값
  **1.0kg/(1,1,1)kg·m²** 그대로 0.02kg mimic 지골 끝에 매달려 있었음(관성 ×1.7e6 역전).
  virtual_l/j/i도 (1,1,1) 기본값(콜라이더 없어 autoTensor 산출 불가), virtual_k만 7/2 수동값 잔존.
  flange/tool0/svh_base_link 더미도 1kg/(1,1,1).
- **수정(11개 링크만, 드라이브·솔버 불변)**: 팁5 → 0.005kg/(1e-6)³, virtual_l/j/i → 0.01kg/(1e-5)³,
  더미3 → 0.1kg/(1e-4)³. 백업 `backups/SampleScene_before_defaultinertia_102827.unity`, 씬 저장됨.
- **결과 (TGS 기준 대비 동일 프로브)**: p·o p2p 192/196° → **76.4°(=명령폭, 초과분 0)**,
  리밋 침범 22~43% → **전 채널 0.0%**, 주먹 추종오차 45.7/51.2° → **1.4/1.1°**,
  정상상태 잔여진동 **전 채널 p2p 0.00°**. z·virtual_i 부작용 없음.
- **결론**: §10의 mimic 지골 드라이브는 트리거, 에너지원은 기본값 관성 링크들.
  §10 수정 후보(mimic 게인 하향 등)는 불필요해져 폐기. **물리 진동 사건 종결.**

---

## 13. 비전 트랙 — thmOpp 방향 스왑 + 재보정 (2026-07-08)

- **라이브 미러링 첫 검증(사용자)**: 전반적으로 잘 따라오나 "엄지·검지가 완전히 안 굽혀짐".
  로그(vision_log_20260708_1035.csv, 46s, 검출 100%) 분석:
  - 주먹 때 **검지 근위 25% / 중지 근위 29%**만 도달(원위는 95~98%) → calibration.json의
    근위 human_max 과대(1.669/1.727)가 원인.
  - **thmOpp 역방향 확정**: 편 손 평균 0.142 vs 주먹 0.022 — 7/2부터 보류된 방향 문제 데이터로 종결.
  - spread는 세션 중 최대의 18%만 사용(데이터 빈약).
- **thmOpp 스왑 적용**: `svh_angles.py` SVH_CHANNELS의 thumb_opposition svh쪽 (0.0,0.9879) →
  **(0.9879,0.0)**. map_to_svh가 t를 0~1로 clamp 후 선형매핑이라 스왑=안전한 반전.
  Unity `SvhHandDriver.invertThumbOpposition=False` 확인(이중 반전 방지).
- **재보정 소동**: 1차 시도는 vision_node.py를 켜고 루틴을 수행 → **보정 저장 안 됨**
  (vision_node 로그는 매핑+clamp된 값이라 human 극값 역산도 불가). ⚠️ 보정은 반드시
  `calibrate_raw.py`(창 제목 "raw angle calibration") + `q` 종료로.
- **재보정 완료(10:58, calibration.json 갱신)**: 루틴 = 주먹꽉↔쫙 3회(MCP 의식) + 엄지 대향 3~5회 +
  **개별 손가락 5개 각 3회** + 벌림 3~5회 (천천히, 극단 1s 유지, 손등 정면, 손목 고정).
  핵심 변화: **검지 근위 max 1.669→0.579, 중지 근위 1.727→0.737**, 엄지굽힘 max 1.278→2.021.
  ⚠️ spread가 0.502~0.648(폭 0.146rad)로 좁게 잡힘 → 과민 가능성, 검증에서 확인할 것.
- **남은 것**: vision_node 검증 런(주먹·펴기 유지 후 q) → 주먹 때 근위 도달률(**합격선 80%**,
  이전 25/29%) + thmOpp 주먹 때 최대(~0.99)쪽 확인 + spread 과민 여부.

---

## 14. 비전 트림 + ML-Agents 로드맵 문서화 (2026-07-08)

- **트림 적용**(§13 검증 런 준비): calibration.json human_max — 엄지굽힘 2.021→**1.30**,
  검지근위 0.579→**0.535**(-7.6%), 중지근위 0.737→**0.65**(-11.8%). ⚠️ calibrate_raw.py 재보정 시 덮어써짐.
- **spread 임시 상수 0 고정**: `svh_angles.py` map_to_svh에 if 블록(주석 표기) — 주먹 때 벌어짐 억제.
  게이팅 코드는 미구현(추후 결정). 원복 = if 블록 삭제.
- **ML-Agents 도입 로드맵 작성**: [ML_AGENTS_ROADMAP.md](ML_AGENTS_ROADMAP.md) —
  모방학습/강화학습 시작 전 Phase 5~10 단계, Go/No-Go 조건 11개, 사용자 결정사항 4개
  (태스크 선택 / 팔 IK 포함 여부 / 행동공간 방식 / sim-to-real 목표) 정리.

---

## 15. RobotArm 패키지 선별 도입 + 팔 CCD IK 이식 (2026-07-08)

- **RobotArm.unitypackage 1차 임포트 사고**: "취소"했다고 생각했으나 13:04에 전체 임포트 완료돼 있었음
  (49개 경로 잔존, 13:43 백업 zip에도 포함 → 오염 백업). 전량 삭제 후 클린 백업 재생성
  (`backups/KDT_robot_AI_clean_no_robotarm_140316.zip`).
- **2차 선별 설치**: unitypackage를 tar로 풀어 GUID 보존 방식으로 Prefab/Script/Meterial/RobotArm.unity만
  복사(30항목). URP Settings·TutorialInfo·Readme·InputSystem_Actions 등 템플릿 부산물 19항목 제외.
  머티리얼 2개는 URP/Lit → **Standard 셰이더로 패치**(마젠타 예방). 컴파일 에러 0.
- **핵심 기능 = `JointOperation.cs`(CCD IK)**: target Transform을 향해 관절을 말단→베이스 순 회전.
  단 Transform 직접 회전 방식이라 ArticulationBody와 비호환 → **`Assets/Scripts/ArmTargetIK.cs`로 이식**.
  - HandSliderUI 팔 슬라이더 값에 주입(SvhHandDriver와 동일 패턴, xDrive 이중기록 방지).
  - 회전축 = ArticulationBody 앵커 X축(`transform.rotation * anchorRotation * Vector3.right`), 부호 전부 +1로 정상.
  - **함정(1차 실패)**: 오차각은 실제 포즈로 계산하는데 팔 드라이브 추종이 느려 명령이 ±360° 한계까지
    폭주(적분 와인드업). → `windupDeg=15°`(명령이 실제 관절각보다 15° 이상 못 앞서게)로 해결.
- **검증(Play)**: 초기 수렴 0.21→0.023m, 타겟 0.9m 재배치 후 재수렴 **0.97cm**(threshold 2cm 도달 시 정지),
  콘솔 에러·경고 0. 씬에 `IK_Target`(빨간 구, 콜라이더 제거) + 루트에 ArmTargetIK 부착, 저장됨.
  씬 백업: `backups/SampleScene_before_armik_142251.unity`.
- 우상단 GUI로 IK on/off + 타겟 거리 표시. IK는 위치만 추종(자세 미제어), 손 텔레옵과 공존.
- **후속 수정(같은 날)**: ① endEffector를 tool0(팔 플랜지) → **GraspPoint**(손끝 5개 중심, tool0 자식,
  로컬 (−0.013, 0.176, −0.002))로 교체 — 파지 기준점(TCP). ② **범위 밖 타겟 처리**: 타겟을 도달 반경
  구면으로 투영(reachMargin 0.88 — 링크 합산 반경은 손목 오프셋 때문에 과대라 0.9↑면 투영점 미도달로
  배회 재발) + **정체 감지**(1.5s간 5mm 미개선 시 동결, 타겟 3cm 이동 시 재개). 검증: 범위 밖 타겟에서
  잔여 흔들림 ±1~2mm 동결, 타겟 이동 시 재추종 후 재동결. 에러 0.

---

## 16. ⚠️ 복구 씬 함정 — "진동 재발" 소동 (2026-07-08 오후)

- **증상**: §12로 종결한 손가락 그네 진동이 재발한 것처럼 보임.
- **원인**: 에디터 크래시(10:13 추정) 후 **활성 씬이 `Assets/_Recovery/0 (3).unity`(§12 수정 전 복구본)로
  바뀌어 있었음**. 물리 감사 결과 이 씬은 팁·더미가 1kg/(1,1,1)로 원복된 상태. 진짜 SampleScene.unity(11:26 저장)에는
  §12 값 전부 무사 — **수정이 날아간 게 아니라 다른 씬을 보고 있었던 것**.
- **여파**: 오후의 RobotArm IK 배선·검증(§15)이 전부 복구 씬에 저장돼 있었음.
- **조치**: SampleScene 재오픈 → 물리 감사 통과 확인(팁 0.005/1e-6, virtual 1e-5, 더미 0.1/1e-4, TGS) →
  IK 배선(IK_Target+ArmTargetIK+GraspPoint) 재적용 + 촬영 준비(IK off, 타겟 숨김) 상태로 저장.
- **교훈**: 물리 이상 재발 시 값 감사 전에 **활성 씬 경로부터 확인**(`GetActiveScene().path`).
  `_Recovery/` 폴더의 씬(0.unity ~ 0 (3).unity, 7/1~7/8 크래시 복구본들)은 혼동 원인 — 정리 권장.

---

## 17. 현재 상태 스냅샷 (2026-07-08 저녁 기준)

**씬 (`Assets/Scenes/SampleScene.unity` — 반드시 이 씬으로 작업, §16 참고)**
- 물리: §12 관성 수정 유지 확인(팁 0.005kg/1e-6, virtual 1e-5, 더미 0.1kg/1e-4), TGS, 드라이브 10000/200/100000. 진동 없음.
- 손 텔레옵: SvhReceiver+SvhHandDriver 활성(enableTracking=True, invertThumbOpp=False).
- 팔 IK: ArmTargetIK 부착(§15), 촬영을 위해 **enableIK=false + IK_Target 숨김** 상태로 저장.
  다시 쓰려면 IK_Target 활성화 + 게임뷰 우상단 "IK 활성" 토글.
- ⚠️ `Assets/_Recovery/`에 크래시 복구 씬 4개 잔존(7/1·7/2·7/6·7/8) — §16 혼동 원인, **정리 예정(미처리)**.

**비전 파이프라인 (`KDT/svh/`)**
- 트림 적용(§14): 엄지굽힘 max 1.30, 검지근위 0.535, 중지근위 0.65 / spread 상수 0 임시 고정.
- **전송 주기 실측**(vision_log_20260708_1100.csv, 106.5s): 평균 53.1ms(**18.8Hz**), 중앙값 47ms.
  구조상 전송주기 = 프레임 처리속도(캡처 30fps 블로킹 최대 33ms + MediaPipe CPU 추론 ~15ms).
  SEND_HZ_CAP=120은 미작동 상한. Windows Python mediapipe는 GPU 불가 — 가속 필요 시
  ①model_complexity=0 ②캡처 스레드 분리 ③캠 60fps 순. Unity 50Hz lerp 보간이라 현 19Hz로 충분.

**남은 일 (우선순위순)**
1. 비전 검증 런(§13 합격선: 주먹 때 근위 도달률 ≥80%, thmOpp ~0.99, spread 억제 확인) — 영상 촬영 세션으로 겸행 가능.
2. `_Recovery` 복구 씬 정리.
3. Phase 4 안전장치(rate limit, One Euro 튜닝, spread 게이팅 여부 결정).
4. ML-Agents 트랙 착수 — 선행 조건·순서는 [ML_AGENTS_ROADMAP.md](ML_AGENTS_ROADMAP.md). 사용자 결정 4건(태스크/팔 IK 포함/행동공간/sim-to-real) 대기.

---

## 18. 팔 IK 출렁임 해결 — 순차 CCD + 손목 forceLimit (2026-07-13)

**증상**: IK_Target을 옮기면 팔이 따라오긴 하나 도달 전후로 크게 출렁임(왕복 요동).

**진단 방법**: unity-cli exec로 EditorApplication.update에 로거를 주입해 13초 3-웨이포인트
자동 실험 — 매 프레임 (dist, 관절별 cmd/drv/act)를 CSV 기록 후 pandas 분석. 원인 2건 확정.

1. **동시 과보정 (제어)**: `ArmTargetIK`가 6관절 모두 "같은 시점의 말단 오차"를 각자 전부
   보정 → 합산 오버슈트 → 매 프레임 왕복. **순차 CCD로 수정**: 관절 하나 스텝(클램프 반영)마다
   말단 예상 위치를 회전 갱신, 다음 관절은 잔여 오차만 보정. (`ArmTargetIK.cs` FixedUpdate)
2. **손목 드라이브 토크 포화 (물리, 주범)**: wrist_1/2/3만 forceLimit=28N·m(URDF effort 값)
   + stiffness 10000 → 오차 0.16°만 넘어도 포화 = 사실상 뱅뱅 제어, damping 무력화.
   손 전체 관성을 진 wrist_1이 도달 후 **~2Hz ±13° 링잉** → 말단 7~10cm 배회 = 관측된 출렁임.
   `|drv-act|max` 30°(wrist_1) vs 1~3°(타 관절)로 특정. **forceLimit 28→150** (씬 저장).

**검증(수정 후 동일 실험)**: 전 관절 |drv-act| ≤1.7°, 3웨이포인트 모두 ≤2cm 수렴 후
요동 p2p ≤0.3cm (수정 전 7~10cm). 씬 저장 + GitHub(kdt-ai) 푸시 완료(9b3a73d).

**부수 수정**: `SvhJointLogger` logPath 하드코딩(개발 PC 절대경로) → 프로젝트 상대
`Logs/unity_joint_log.csv` 자동 생성으로 변경 (다른 PC에서 Play 시 DirectoryNotFoundException 나던 것).

**남은 관찰**: 큰 스윙(반대편 이동) 시 마지막 20cm 수렴이 완만(~2초). 정체는 아니고
CCD 특성 + 게인(rotationSpeed=5) 문제 — 필요 시 게인 상향 또는 감쇠 스케줄링으로 개선 여지.

### §18-2. 후속: 부드러운 뻗기(같은 날, 8페이즈 배터리로 검증)

사용자 피드백("여전히 출렁") 후 시나리오 확장 테스트(범위내 드래그/근접/고저/범위밖 점프·드래그,
22s 자동 배터리, 50Hz 재샘플 jerk·반전 지표)로 잔여 원인 3건 추가 수정:

1. **급발진 채찍질**: 명령이 0→90°/s 즉시 점프(초기 뻗기 jerkRMS 2343). → **비대칭 가속 램프**
   (maxAccelDeg=0.12°/프레임, 스텝 "증가"만 제한·브레이크는 즉시). jerk 380으로.
   ⚠️ 대칭 램프(감속도 제한)는 오버슈트 후 관성으로 밀어 저주파 리밋사이클 유발 — 실측으로 기각.
2. **도달 경계 미세 헌팅**: threshold 언저리 on/off 반복. → **도달 히스테리시스**(rearmFactor=1.5,
   threshold 진입 후 1.5배 벗어나야 재가동) + deadband 0.25°.
3. **범위 밖 갈이(grinding)**: 투영점이 방향에 따라 실제 도달 불가 → 경계에서 무한 헌팅
   (홀드 중 반전율 7.1%, cmd반전 60). → **투영 시 도달 판정 3배 완화**(6cm). 반전 4.8%/36으로.
   손목 3관절 스텝 0.6배 축소(distalStepScale — 지그재그 주범).

최종 채택 파라미터(코드 기본값=씬 저장값): maxStep 1.8 / accel 0.12 / distal 0.6 /
deadband 0.25 / rearm 1.5 / stall 1.5 / 투영 시 th×3. 푸시 6e8480c.
⚠️함정: 씬에 직렬화된 옛 필드값이 코드 기본값 변경을 덮음 — 파라미터 튜닝은 씬 저장까지 해야 유효.

### §18-3. GraspPoint를 손끝 평면 → 실측 파지 중심으로 이설 (2026-07-13)

파지 준비: IK 기준점이 "편 손끝 5개 중심"이라 타겟이 손끝에 닿는 위치로 감 → 물체가
손 안에 못 들어옴. **실측 방식**: Play에서 손을 50% 굴곡으로 포즈(⚠️SvhHandDriver
enableTracking을 꺼야 주입값이 안 덮임) 후 엄지끝↔4손가락끝 중심의 중점 = C자 중앙 측정.
- GraspPoint(tool0 로컬): (-0.0127, 0.1759, -0.0024) → **(-0.0122, 0.1455, 0.0489)**
  (손끝에서 손바닥 쪽 3cm + 손바닥 안쪽 5cm)
- **검증**: IK 도달 후 반그립 시 공 중심이 엄지끝 2.7cm / 각 손가락끝 2.2~3.6cm 등거리
  = 파지 공간 정중앙. 씬 저장 + 푸시(2d9d0b5).
- 남은 것: **자세(orientation) 미제어** — 손바닥 접근 방향이 임의라 실제 파지엔 자세 제어
  추가 필요(다음 단계). unity-cli 팁: SceneView 카메라 프레이밍 후 screenshot이 반영 안 되는
  경우 있음(수치 검증 우선).

---

## 19. 핸드 전환: Tesollo DG5F 4변형 임포트 + 범용 파이프라인 스크립트화 + 구동 검증 (2026-07-13)

**결정**: 실사용 핸드 = Tesollo DG5F (`KDT/tesollo_model-main/.../dg5f/`). SVH 대비 5손가락×4관절
= **revolute 20개 전부 독립 구동, mimic 없음** → MimicJointController 불필요, 리타게팅은 재설계 필요.
URDF에 전 링크 inertial 존재(SVH 진동 사태의 근본 원인이 구조적으로 없음).

**임포트+검증 (오른손 → 4변형 전체)**:
- `Assets/Robots/<변형>/`에 URDF+메시 복사, package://→상대경로 패치, URDF-Importer(Y축+vHACD).
- 4변형 모두 바디 28/revolute 20/기본값관성 0, 콘솔 0. 프리팹 `Assets/Robots/Prefabs/dg5f_*.prefab` 4종.
- **물리값 전수 대조 통과**: 질량 28/28, CoM 28/28(<0.1mm), 리밋 20/20(도 단위 정확, 예: 엄지1 [-22°,77°]),
  forceLimit=effort 7.5N·m, 축 20/20(부호반전 규칙 일관). 유일 편차 = 팁 5개 관성 **PhysX 최소값(1e-6) 클램프**
  (URDF 2.0~3.3e-7 → 1e-6, 커지는 방향이라 무해).
- 변형 교체: `Assets/Editor/DG5FVariantSwitcher.cs` — **Tools/DG5F 메뉴**로 씬의 핸드를 같은 위치/부모로
  교체(Undo 지원, Play 중 차단). 씬 `Assets/Scenes/DG5F_Import.unity` (SampleScene 무손상).

**⭐범용 파이프라인 스크립트화 (`KDT/tools/urdf_hand_import/`)** — 일회성 exec 스니펫 탈피:
- `import_hand.py`: 복사→패치→임포트→감사(기본값 관성 검출)→`--verify` 물리대조→`--prefab` 저장. 다중 URDF 일괄.
- `phys_compare.py`: URDF vs Unity 질량/CoM/관성고유값/리밋/effort 대조 (PhysX 클램프는 WARN 분류).
- `setup_drive.py`: 구동 준비 일괄(멱등) — Controller 제거 + 게인 + 중력off·루트고정 + 컴포넌트 부착.
- `probe_test.py`: Play 자동 진입→전 관절 사각파 4사이클→CSV→pandas 판정(정착≤1°/진동≤0.5°/침범 0).
- 전부 dg5f로 E2E 실증. README에 함정 목록(exec 제약: using 불가/보간 불가/chosenAxis 등).

**구동 준비 적용 (4변형 프리팹 전체)**: ①Controller 제거 ②게인 10000/200/**forceLimit 100000**
(⚠️effort 7.5 유지 시 stiffness 10000 기준 0.04° 오차에도 토크 포화→§18 뱅뱅 패턴 확실시 — HW 토크상한
재현 포기 트레이드오프, 명시적 결정) ③useGravity=false 전체+루트 immovable ④SvhSelfCollisionIgnore·
SvhInitialPoseSync 부착(이름만 Svh, 로직 범용).

**구동 검증 (probe_test.py, dg5f_right)**: 20관절 사각파(가동범위 15%↔80%, 4사이클 13s, 345Hz 샘플)
→ **전 관절 정착오차 0.00° / 잔여진동 p2p 0.00° / 리밋침범 0 — 완전 합격**. "전부 0.000" 의심(§16류 동결)은
전이 구간 오차 131.75°·act 범위 -133~0°로 실구동 교차 확인. 주먹 포즈 스크린샷 확인, 에러·경고 0.
SVH에서 한 달 걸린 진동 문제가 DG5F에선 관성 데이터가 온전해 첫 시도 무진동.

**남은 것**: ①MediaPipe→20관절 리타게팅 설계(비전 트랙, 4번째 마디 처리 방식 결정 필요)
②UR5e+DG5F 결합 URDF(merge.py 개조) ③DG5F용 GraspPoint 재실측+자세 제어 ④ML-Agents 결정 4건.

---

## 20. DG5F 핸드트래킹 리타게팅 — 20채널 파이프라인 구축 + 배선 검증 (2026-07-13)

**손가락/관절 의미 확정** (URDF 기하 + 0°포즈 팁 월드좌표 실측): 1=엄지(1_2가 대향회전 [-155,0]),
2/3/4=검지/중지/약지(n_1 벌림 + MCP/PIP/DIP), 5=새끼(5_1 손바닥접기 [0,60] 추가 보유).
**"4번째 마디 문제" 없음** — 사람 손 해부학과 1:1 (벌림+굽힘3), MediaPipe에서 전부 직접 계산 가능.

**설계 (SVH 교훈 반영)**:
- 프로토콜: UDP `<20f'` **포트 5006**(SVH 5005와 공존), 값=**관절공간 각도[deg]** — 사람→관절
  매핑·보정·방향반전은 Python 한곳에, Unity는 clamp+lerp만 (책임 분리).
- 채널 순서 고정(엄지→새끼, 마디순) + Unity는 `_dg_<손가락>_<마디>` **이름 접미사 매칭**
  (위치 매칭 금지 — SVH 근위/원위 함정. 접미사라 좌우 프리팹 겸용).
- 벌림(n_1)·새끼접기(5_1)는 **게이트: 중립 0° 고정**으로 시작 (SVH spread 과민 전례). 굽힘 검증 후 해제.
- One Euro 재사용, deg 스케일이라 beta 0.01→0.0005.

**구현**: `KDT/dg5f/` — dg5f_angles.py(landmark→20ch 매핑+보정로드) / vision_node_dg5f.py(웹캠 루프)
/ probe_sender.py(웹캠 없이 fist/open 패킷) / README. Unity `Assets/Scripts/Dg5fReceiver.cs`(스레드 수신,
⚠️수신 스레드에서 Unity Time API 불가→DateTime) + `Dg5fHandDriver.cs`(RequireComponent, 첫 패킷 시
현재 target에서 스무딩 시작 = 홱 방지). 4개 프리팹에 `setup_drive.py --components`로 부착
(⚠️새 스크립트 컴파일 직후 도메인 리로드 타이밍에 exec하면 TYPE_NOT_FOUND — 재시도로 해결).

**배선 결정적 검증(웹캠 없이)**: Play + probe_sender fist/open → 20관절 xDrive.target 기대값
(리밋 clamp 반영) **일치 20/20, 오차 0.00°, 실측각 수렴**, 주먹 스크린샷 확인, 콘솔 0.

**남은 것(라이브)**: ①웹캠 라이브 테스트(사용자) — 엄지 대향(1_2)·CMC(1_1) 방향 확인(반대면
dg5f_angles.py에서 dg_min/max 스왑) ②보정 루틴(calibrate_raw.py 개조) ③게이트 단계 해제.

---

### §20-2. 라이브 이슈 해결 — 새끼 측면눕기·엄지 방향 (2026-07-13 저녁)

**사용자 리포트**: ①새끼를 굽히면 로봇 새끼가 아래로 접히지 않고 옆으로 누움 ②엄지 접기/펴기 방향
안 맞음, OK 사인 안 됨.

**진단 방법 (추측 대신 실측 2종)**:
1. **관절 스윕**: Play에서 관절 하나씩만 lo/hi로 구동, 손끝 궤적을 손바닥 로컬 좌표로 CSV 기록,
   검지 MCP(2_2) 굽힘 방향을 기준벡터로 각 관절의 굽힘/측면 성분 분해.
   ⚠️1차 스윕은 이전 텔레옵 잔여 target이 기준점 오염 → 전관절 0 리셋 후 재측정(2차)으로 확정.
2. **핀치 탐색**: 엄지 (대향×굽힘부호) 8조합 그리드로 엄지-검지 끝거리 실측.

**발견**:
- **새끼 5_2 = 측면 기울임 관절**(굽힘 0.42/측면 0.81) — 사람 MCP 굽힘을 여기 보낸 게 "옆으로 눕기"의
  원인. 새끼 굽힘 관절은 5_3(0.98)·5_4(0.99) 둘뿐. → **채널 재배정**: MCP→5_3, (PIP+DIP)평균→5_4,
  5_1(접기)·5_2(측면) 게이트 0.
- **엄지 mcp/ip 부호는 미러(음수)가 정답**: 핀치 탐색에서 음수 조합만 4.9~9.2cm 도달(양수 16cm+).
  단 대향≈0일 때 굽힘 방향이 시각적으로 반전돼 보이는 결합 특성 有 → thumb_opp dg_min을 -15°로
  (휴지 상태를 약간 대향으로) 완화.
- 기타: 보정 극값이 MediaPipe 스파이크로 오염(pip max 2.6~2.9rad=물리불가) → 현 파일 트림 +
  calibrate_dg5f.py를 백분위(2/98%)+물리캡 방식으로 개선. 엄지 CMC(1_1)는 프록시 노이즈 과대로 게이트.

**검증(왼손 프로브)**: OK 사인 패킷 → 엄지-검지 끝 4.9cm C자 형성 스크린샷 확인, 주먹 → 새끼 포함
전 손가락 정상 말림. ⚠️소동: 검증 중 20.8cm 미스터리 = **Edit 모드에서 측정**(Play가 꺼져 있었음
+ 이전 Play에서 수신기 포트 바인딩 실패 의심) — hasData=False && netstat에 UDP 5006 없으면 이 상황.

---

### §20-3. 엄지 손끝 위치 리타게팅 v2 — OK 사인 접촉 문제 해결 (2026-07-13 밤)

**배경**: 텔레옵 로그 정량 분석(analyze_teleop)은 전 채널 PASS(상관 1.00, 추종 ≤0.61°)였으나
사용자 체감 문제 잔존 — "OK 사인 때 엄지-검지 끝이 안 닿음, 엄지가 손바닥 안으로 안 접힘,
손등 쪽 펴기 재현 안 됨". **원인 = 채널별 독립 선형 매핑의 구조적 한계**: 관절각은 따라가도
결합 운동의 결과(손끝 위치)는 어긋남. 파이프라인 문제가 아니라 매핑 의미론 문제.

**해결 = 엄지만 작업공간(손끝 위치) 리타게팅**:
- **v2 프로토콜 `<24f`**: 관절각 20 + 엄지끝 정규화좌표 3 + 핀치 플래그 1 (v1 하위호환).
- 좌표 계약: 손바닥 해부학 좌표계(원점=중지MCP, ez=손목→중지MCP, ey=새끼→검지MCP, ex=cross,
  손길이 정규화) — 해부학 랜드마크 기반이라 좌/우 모델·거울 모드 불변, 미러 표 불필요.
- Unity `Dg5fThumbIK.cs`: 엄지 4관절 순차 CCD(§18 ArmTargetIK 패턴 — 예상 손끝 회전 갱신,
  스텝 2.5°/틱, 리밋 클램프). 로봇 대응점(palm/3_2/2_2/5_3)을 Start에서 캐시.
  활성 시 Dg5fHandDriver가 엄지 채널 주입 스킵. 게이트했던 엄지 CMC(1_1)도 IK가 활용 —
  손바닥 접기 성분 복원.
- **핀치 스냅**: 사람 엄지-검지 끝거리 < 손크기×0.35 → 로봇 검지 끝(+1.2cm 접촉 오프셋)을
  직접 목표로 — 사람/로봇 비율 차이와 무관하게 접촉 보장.

**검증(oktip 프로브)**: 엄지-검지 끝 거리 **1.2cm(=설정 오프셋값) 정확 수렴**, OK 링 형성
스크린샷 확인, 콘솔 0. ⚠️발견: 검지 컬이 얕으면(45/35/25°) 검지 끝이 엄지 작업공간 밖이라
최선 5.3cm — OK 프로브 검지를 62/52/38°로 조정. 부수: `Dg5fJointLogger.cs`(50Hz rx/tgt/act
기록) + `analyze_teleop.py`(전송/클램프/추종/동작재현 4계층 분리 진단) 검증 파이프라인 구축.

**남은 것**: 라이브 웹캠에서 엄지 IK 체감 검증(사용자) — 특히 핀치 스냅 임계(0.35) 튜닝,
저대향 구간 자연스러움. 이후 로드맵 3번(UR5e 결합).

**⚠️미해결(2026-07-13 밤, 사용자 라이브 피드백)**: ①엄지 스스로 까딱임 → 데드밴드 0.8cm/재가동
1.8cm 히스테리시스 + 목표 스무딩(10/s) + 와인드업 가드 15° + 핀치 히스테리시스(0.30/0.42) 적용
②적용 후에도 **"엄지 움직임이 부드럽지 않음"** — 다음 세션에서 이어서. 의심 후보: 데드밴드
동결↔재가동 경계에서 뚝뚝 끊기는 느낌(동결 방식 자체), CCD 스텝 제한(1.5°×2iter)로 인한 추종
지연, 비전 tip z(깊이) 노이즈. 진단 시 Dg5fJointLogger + analyze_teleop --channels thumb 활용.

### §20-4. 엄지 IK 개선 3종 — 자세 prior·연속 감쇠·핀치 연속 블렌딩 (2026-07-14)

**배경**: §20-3 미해결 ②(엄지 부드럽지 않음 — 동결↔재가동 경계 끊김 의심) + 여유자유도
배회(4관절 vs 위치 3D → 손끝은 맞아도 관절 "모양"이 사람과 다름) + 핀치 임계 근처 목표 점프.

**변경** (Unity `Dg5fThumbIK/Dg5fReceiver` + Python `vision_node_dg5f.py`):
1. **자세 prior**: IK 활성 시 버려지던 패킷 0..3(엄지 관절각)을 2순위 목표로 — CCD 후
   `priorGain`(3/s)·`priorWeights`(기본 {0,1,1,1} — **1_1=0 고정**: Python이 thumb_cmc 게이트라
   자세 정보 아님)로 사람 각도 쪽 블렌딩. 위치(CCD)가 항상 우선, 리밋·와인드업 클램프 동일.
2. **동결 → 연속 감쇠**: deadband/rearmBand 제거, `softZone`(1.5cm) 도입 — 오차에 비례해
   CCD 스텝 상한 축소(`stepCap = maxStepDeg × clamp01(err/softZone)`). 경계 없는 정지,
   prior와의 평형점에서 매끄럽게 멈춤.
3. **핀치 연속 블렌딩**: **v3 패킷 `<25f`** = v2 + [24] 엄지-검지 끝거리비(연속, One Euro).
   `pinchNear`(0.32)~`pinchFar`(0.55) 사이 SmoothStep으로 해부학 목표↔검지끝 스냅 연속 전환
   — 임계 점프 제거. v2 수신 시 기존 이진 스냅 폴백(양방향 하위호환, 길이로 버전 판별).
   ⚠️ 핀치 가중 w만큼 prior 약화(`×(1-w)`) — 초기 구현에서 prior가 접촉 목표를 반대로 당겨
   수렴 3.8cm에서 정체 → 약화 후 정상.

**검증(v3 프로브, 왼손 모델)**: 25f 수신·`GetPinchDistance` OK, IK Active, far(d=0.8)에서
prior 평형 확인, pinch(d=0.25)+검지 62/52/38에서 엄지-검지 끝거리 **1.2cm(=pinchOffset) 정확
수렴** — §20-3 oktip 벤치마크 동등. 컴파일 0에러, 콘솔 클린. 라이브 Unity 프로젝트
(`UnityProjects/cli_test/KDT_robot_AI`)에도 스크립트 배포 완료.

**⭐엄지 떨림 근본원인 규명 = CCD 리밋사이클 (같은 날 후속, 정지 프로브 정량 진단)**:
고정 입력인데 1_1/1_3/1_4가 p2p 17~23° 지속 요동(1_2만 안정), 패킷 끊기면 완전 정지
→ 물리 결백, 명령 레벨. **prior 끄고도 15~22° 동일 → prior 무죄, CCD 자체가 범인**:
도달 불가(작업공간 밖) 목표 → 오차가 softZone 아래로 안 내려가 매 틱 풀스텝 → 순차
CCD의 관절 간 그리디 순환 + 와인드업 가드 포화(|tgt-act|=15.000 정확)의 위상지연.
§20-3② "부드럽지 않음"의 정체로 추정 — 비율 차이로 비전 목표가 작업공간 밖에
떨어질 때마다 발생했을 것. **⚠️구버전 데드밴드 동결도 도달 불가 목표에선 같은 사이클**
(0.8cm 데드밴드에 영원히 미도달).

**수정 = 정체 감지 감쇠(stall damper)**: 최선 오차가 `stallTime`(0.6s) 내 1mm도 안
줄면 스텝 권한 지수 감쇠(×0.95/틱, 하한 0.02), 개선 시 **점진 회복**(×1.15/틱 — 즉시
1.0 리셋은 사이클 재점화 15~19° 실측), 목표 3mm 이동 시 전체 재가동. 시행착오 2건 기록:
①prior 스텝캡만으로는 무효(원인 오진) ②틱당 개선 판정(0.2mm)은 물리 추종 지연까지
정체로 오판해 핀치 수렴이 2.4cm에서 정체 — **시간창 판정이어야 함**.
최종 검증: 정지 65°(초기 과도)→7→6→1.2→0.7→1.1° 단조 감쇠 재점화 없음, 핀치 전환
재가동 정상, 접촉 1.2cm 유지. 진단·검증 전 과정 Dg5fJointLogger 5초 구간별 p2p로 수행.

**남은 것**: 라이브 웹캠 체감 검증(부드러움 §20-3② 재평가, priorGain/softZone/stallTime 튜닝).
미착수 로드맵: 엄지 체인 길이 정규화(비율 문제), IP 위치 2점 IK(v4), 작업공간 사영,
벌림 게이트 해제.

### §20-5. 엄지 CMC(1_1) 게이트 해제 — 앞뒤 움직임 재현 (2026-07-14)

**배경**: 엄지 앞뒤(안테포지션)가 로봇 1_1에 전혀 안 나타남. 경로 삼중 차단이 원인:
①Python 채널0 게이트(옛 프록시 노이즈, §20-2) ②priorWeights[0]=0 ③IK 목표의 앞뒤
성분이 깊이(z) 노이즈 축+여유자유도에 흡수.

**변경**:
- **Python 신프록시** `_thumb_elevation`: 엄지 중수골(CMC→MCP)의 손바닥 평면 이탈각
  arcsin — 옛 3점각(준일직선, 조건수 불량)과 달리 전 구간 안정. 채널0 게이트 해제,
  기본 매핑 (0.15,0.85)rad→(0,65)°. **⚠️옛 보정값이 신프록시를 오염** → 양쪽
  dg5f_calibration.json에서 thumb_cmc 항목 제거(재보정 필요). 좌우 미러는 기존
  LEFT_MIRROR_CHANNELS에 thumb_cmc가 이미 있어 무변경.
- **Unity CMC 피드포워드**(`cmcFeedforward`=8/s): 채널0→1_1 직결 lerp. **평시 CCD는
  1_1을 안 건드림**(CCD의 1_1 스텝 ×_pinchW) — 같은 관절 이중 제어 금지 원칙(§20-4
  리밋사이클 교훈). 핀치 시 역할 교대(ff는 ×(1-w)로 소멸, CCD가 1_1 인수 — 접촉 우선).

**검증(왼손, ch0 삼각파 스윕 프로브)**: rx↔act 1_1 **상관 0.991, 평균 오차 1.68°**,
정지 hold 시 1_1 p2p 0.07°, 핀치 1.2cm 유지. 잔여: 모순 입력(1_1 강제+손끝 고정)
최악 조건에서 1_3/1_4가 1~2.5°/s 미세 숨쉬기(정체 감쇠 하한 0.02의 크롤링) — 실손
입력은 두 신호가 일관돼 덜함, 하한 튜닝 여지.

**라이브 확인 필요(사용자)**: ①방향 — vision_node [send] 첫 값(ch0)이 엄지를 손바닥
앞쪽으로 움직일 때 증가해야. 반대면 채널 테이블 thumb_cmc (dg_min,dg_max)=(65,0) 스왑
②calibrate_dg5f.py 재보정(thumb_cmc 신프록시 범위 학습).

### §20-6. 엄지 체인 길이 정규화 + 작업공간 투영 (2026-07-14)

**배경**: §20-4 리밋사이클의 근본 원인 = 손길이 정규화가 사람/로봇 엄지 비율 차이를
무시 → 비전 목표가 로봇 엄지 작업공간 밖에 떨어짐. stall damper는 증상 치료였고,
이 수정이 정공법("엄지 체인 길이 정규화" 로드맵 항목 실행).

**변경** (패킷 레이아웃 v3 25f 불변, [20..22]의 의미만 변경 — Python/Unity 동시 배포 필수):
- Python `compute_thumb_tip`: 리치벡터 = **(엄지끝−엄지CMC) / 사람 엄지 체인 길이**
  (구: (엄지끝−중지MCP)/손길이). 구버전은 손바닥 오프셋과 리치가 섞여 체인 스케일을
  걸 수 없었음 → CMC 기준 분해로 리치만 스케일. 체인 길이는 보정값
  (`thumb_chain_ratio`×현재 손길이) 우선, 없으면 느린 EMA(α=0.02) 폴백 —
  ⚠️매 프레임 원시 마디합으로 나누면 z 노이즈가 스케일 노이즈로 직결.
  축(해부학 좌표계)·pinch_d(손길이 정규화 유지 — 핀치 임계 튜닝 보존) 불변.
- `calibrate_dg5f.py`: thumb_chain_ratio(체인/손길이, 중앙값) 측정·저장 추가.
  ⚠️기존 dg5f_calibration.json에는 이 키가 없어 재보정 전까지 EMA 폴백으로 동작.
- Unity `Dg5fThumbIK`: 복원 = **로봇 엄지 베이스(1_1 피벗) + 리치 × 로봇 체인 길이**
  (1_1→…→tip 마디합, Start 실측 14.8cm — 강체 거리라 포즈 불변). `reachClamp=0.95`
  외곽 구면 투영 추가(해부학 목표만 — 핀치 스냅 목표는 로봇 자신의 검지 끝이라
  도달성이 자명해 제외). stall damper 등 기존 안전장치는 최후 안전망으로 유지.
- `probe_sender.py`: oktip tip값을 새 의미로 갱신 + **tipfar 모드**(v3, 핀치 해제
  상태의 해부학 목표 — 정규화 스케일 검증용) 추가.

**검증(왼손 결합 프리팹 ur5e_dg5f_left, DG5F_Import 씬 Play)**:
- 합성 landmark 단위테스트: 일직선 엄지 → 리치 크기 0.995 ✅
- oktip 회귀: 핀치 **1.20cm 정확 유지**(§20-3 벤치마크 동등), 반복 샘플 불변 ✅
- tipfar(리치 0.753): reach 10.74cm = 체인의 72.6% (기대 75%, 차이는 prior 평형
  오프셋 — §20-4 far 검증과 동일 거동), **8s간 3샘플 완전 동일 = 리밋사이클 0** ✅
- 콘솔 에러·경고 0. 라이브 사본(KDT/dg5f, Unity 프로젝트 Assets/Scripts) 배포 완료.

**남은 것**: ①`calibrate_dg5f.py` 재보정으로 thumb_chain_ratio 실측(그 전까지 EMA,
2.5s 수렴이라 실용상 문제 없음) ②라이브 웹캠 체감 재평가(§20-3②) — stall damper
발동 빈도가 급감했는지가 이 수정의 품질 지표.

### §20-7. 엄지 앞뒤 미재현 + 라이브 떨림 — 관절 오배정·감쇠 무력화 수정 (2026-07-14 저녁)

**배경(재보정 후 라이브 사용자 리포트)**: ①엄지 앞뒤(깊이) 잘 안 됨(좌우는 됨) ②여전히 덜덜.
§20-6 자체는 정상 작동 확인(chain_ratio 0.8282 로드, ch0 풀레인지 송신, 1_1 방향 정상).

**진단(18:11 라이브 로그 + Play 관절 스윕 실측)**:
- **떨림 = 명령 레벨**: 입력 정지 중 tgt 자체가 p2p 8~10° 요동, act는 tgt를 corr 0.96~1.0
  추종(물리 결백). **stall damper가 라이브에서 무력화** — 재가동 임계 3mm < 상시 비전
  노이즈라 감쇠가 계속 리셋(정적 프로브에선 완벽했던 이유).
- **⭐1_1은 앞뒤 관절이 아님(스윕 실측)**: 1_1 풀스윕 시 손끝 이동 = 법선(앞뒤) 1.5cm /
  전방 13.4cm / 측면 5.7cm → **손바닥 평면 안 스윕 관절**. 깊이는 **1_2(대향 롤)**가 만듦
  (1_3/1_4=40° 굽힌 채 1_2 10→80°: 법선 3.0→8.3cm, 80° 부근 최대). §20-5의
  elevation→1_1 직결은 관절 오배정. 1_2는 CCD 점유+prior 미약이라 사람 대향과 상관
  -0.055 = 깊이 신호 전달 경로가 아예 없었음.

**수정**:
1. **프록시 교차 재배선**(dg5f_angles.py compute_raw): ch0(→1_1)=가로 스윕 proxy(구 ch1),
   ch1(→1_2)=elevation proxy(구 ch0). 채널 테이블 human 기본범위 교차 +
   **dg5f_calibration.json 양쪽 thumb_cmc↔thumb_opp 값 스왑**(방금 보정 재활용, 재보정 불필요).
2. **ff 목적지 1_1→1_2**(Dg5fThumbIK): `feedforwardJoint=1` 신설(CCD 스킵·prior 제외 로직
   일반화), priorWeights {0,1,1,1}→**{1,0,1,1}** (ff 관절 prior 금지 + 1_1은 prior 복원).
3. **감쇠 라이브 대응**: `rearmDist` 파라미터화 3→**8mm**(노이즈보다 크게), targetLerp 10→**6**.
4. 직렬화 함정 대응: 프리팹 5종+씬 인스턴스 2곳 값 일괄 갱신 후 저장(§18-2 교훈).

**검증(왼손 결합 프리팹, 세션 로그 unity_dg5f_20260714_1844)**:
- 노이즈 프로브(정지 목표+σ3mm, 라이브 조건 재현): 1s창 tgt p2p **0.7~2.4°**(이전 라이브
  8.5~10.6° 대비 ~1/7), 1_2는 0.00° 완전 정지 ✅
- elevation 삼각파 → act_1_2 **corr 1.000**(지연 139ms), 15~120° 풀레인지 추종 ✅ (깊이 경로 개통)
- oktip 회귀: 핀치 **1.20cm** 유지 ✅, 콘솔 0.
- ⚠️관찰: 프로브 단계 전환+패킷 공백 직후 핀치가 5.46cm 국소최소에 갇힌 사례 1회
  (깨끗한 시작에선 정상) — CCD 국소최소 + 감쇠 잔여 상태 의심, 라이브 재현 시 조사.

**남은 것**: 라이브 웹캠 체감 재평가(앞뒤 방향 부호 포함 — 반대면 thumb_opp (dg_min,dg_max)
스왑), 벌림 게이트 해제.

---

## 21. SVH 완전 제거 + 메인 리포 이전 (2026-07-13 밤)

- **메인 리포**: https://github.com/devLkb/KDT_1_AX_rtauto (새 환경 재현용 — 셋업은 리포 README).
  Python 규격(정정 전): **3.10.11/3.10.12 + venv 2분리** (당시 mediapipe 0.10.14 기준 protobuf 4.x ↔ mlagents protobuf 3.x 충돌 판단).
- **SVH 제거(DG5F 전환 확정)**: vision/svh, docs 코드사본, Unity의 SvhReceiver/SvhHandDriver/
  SvhJointLogger/MimicJointController, SampleScene+unity_pkg 삭제.
- **공용 컴포넌트 개명(GUID 보존)**: SvhInitialPoseSync→RobotInitialPoseSync,
  SvhSelfCollisionIgnore→RobotSelfCollisionIgnore — 파일명+.meta 동시 rename이라 DG5F 프리팹
  4종 참조 무손상 (missing 0, 컴파일 0에러, fist 프로브 스모크 통과). setup_drive.py 기본값 갱신.
- **유지**: ArmTargetIK+HandSliderUI+RobotConfig(팔 IK 스택), ur5e_svh_build(팔 변환).
  ⚠️ UR5e 팔이 이제 씬에 없음 — 결합(로드맵 3번) 시 ur5e_raw.urdf + merge.py 개조로 재구성.

---

## 22. UR5e + DG5F 결합 (2026-07-14, 로드맵 3번)

**빌드**: `urdf/ur5e_dg5f_build/merge_dg5f.py` — ur5e_raw.urdf(§21 이전 xacro 변환본) +
dg5f_left.urdf 결합. UR tool0 --(fixed, identity)--> **ll_dg_mount**(DG5F가 플랜지
장착용 마운트 링크를 자체 보유). 메시는 빌드 폴더 meshes/{ur,dg5f_left}/로 복사(자족적),
mimic 없음. 결과 `ur5e_dg5f_left.urdf`: 링크 41/관절 40(revolute 26=팔6+손20),
world→5tip 연결 OK, 중복명 0.

**임포트**: import_hand.py --verify --prefab → 바디 40, 물리 대조 전 항목 통과.
badInertia 5 = **inertial 없는 UR 더미 링크**(base_link/base/flange/tool0/ft_frame,
§12 함정) → 프리팹 내 mass 0.1/관성 1e-4 수정(remainBad 0). setup_drive로 26관절
10000/200/100000 + Controller 제거 + 중력off/루트고정 + 컴포넌트 8종 부착:
RobotSelfCollisionIgnore/RobotInitialPoseSync/**Dg5f 4종**(Receiver·HandDriver·
ThumbIK·JointLogger)/**팔 IK 2종**(HandSliderUI·ArmTargetIK). 팔 준비 포즈
(0,-60,60,-90,-90,0) 프리팹에 내장.

**⚠️Dg5f 스크립트 3종의 손 전용 가정 수정**: HandDriver/JointLogger가 revolute 전수에
`IndexOf("_dg_")` 접미사 파싱 → 팔 관절(UR)에서 Substring(-1) 예외로 Start 사망,
**수신까지 연쇄 침묵**(pkt_age=Infinity — 같은 GO의 Start 예외 연쇄). `_dg_` 없는
관절 skip으로 수정(ThumbIK도 방어 적용). 손 단독 프리팹과 양립.

**씬(DG5F_Import.unity)**: 손 단독 dg5f_left 인스턴스 **비활성**(UDP 5006 충돌 방지,
폴백 보존), ur5e_dg5f_left 프리팹 인스턴스 + IK_Target(빨간 구) 배치, ArmTargetIK.target
연결(**enableIK=false로 시작** — 팔 IK 활성화는 별도 검증 후), 카메라 프레이밍, 저장.

**스모크 검증**: 주먹↔펴기 사이클 + 핀치 v3 프로브 — 팔 준비 포즈 유지(act=tgt 정확,
진동 0), 손 20채널 추종(검지 2_2 tgt=act=62.0), 엄지 IK Active, **핀치 1.2cm**(손 단독과
동등), 콘솔 0. 스크린샷 Screenshots/ur5e_dg5f_smoke.png.

**남은 것**: ①팔 IK 활성 검증(enableIK 켜고 IK_Target 추종 — §18 파라미터는 코드
기본값에 내장돼 있음) ②GraspPoint(파지 중심) DG5F 기준 재측정(§18-3은 SVH 기준)
③오른손 변형 빌드는 merge_dg5f.py의 DG/DG_MESHES/이름만 교체.

---

## 부록 — 자주 쓰는 unity-cli 패턴

```bash
CLI="C:/Users/dltmd/AppData/Local/unity-cli/unity-cli.exe"
"$CLI" status                                   # 연결/상태
cat script.cs | "$CLI" exec                     # C# 실행 (stdin 파이프 권장)
"$CLI" editor play --wait                        # Play 진입
"$CLI" editor stop --wait                        # Play 종료
"$CLI" screenshot --view game --output_path Screenshots/x.png
"$CLI" console --type error,warning --lines 15   # 콘솔 로그
```
- exec C#에서 `Object`는 `UnityEngine.Object`로 명시.
- Play 진입/종료, 패키지 추가, 스크립트 변경은 **도메인 리로드**를 유발 → 잠시 `not responding`이 정상.


## 23. 비전+ML-Agents 공용 venv 의존성 정정 (2026-07-14)
<!-- 원래 §22로 매겨져 §22(UR5e+DG5F 결합)와 중복 → 23으로 정정 (2026-07-15) -->

- **정정**: 기존 문서의 "비전과 ML-Agents는 반드시 별도 venv" 결론은 `mediapipe==0.10.14`
  기준이었다. `mediapipe==0.10.11`로 낮추면 `protobuf==3.20.3`을 유지할 수 있어 ML-Agents와
  같은 가상환경에서 사용 가능.
- **실제 확인 환경**: `vision/.vision`, Python 3.10.12.
- **핵심 설치 버전**: `mediapipe==0.10.11`, `protobuf==3.20.3`, `numpy==1.23.5`,
  `opencv-contrib-python==4.8.1.78`, `pandas==2.0.3`, `scipy==1.10.1`, `torch==2.1.1+cpu`,
  `mlagents/mlagents_envs==1.2.0.dev0`(로컬 release23 소스 설치본).
- **검증**: `pip check` 통과, `mp.solutions.hands` import 통과, `mlagents-learn --help` 통과.
- **문서/파일 갱신**: `requirements-vision.txt`, `requirements-mlagents.txt`, README Python 셋업,
  `docs/ML_AGENTS_ROADMAP.md`, `docs/PROJECT_HANDOFF.md`를 공용 venv 기준으로 수정.


## 24. 결합 프리팹 ThumbIK 튜닝 누락 수정 + 엄지 목표 디버그 마커 (2026-07-15)

**배경**: §20-7 수정 후에도 라이브에서 "엄지 이동 중 덜덜 떨리다 정지" 잔존 보고.
씬/설정 전수 점검으로 원인 후보 1건 발견 + 눈으로 목표 계층을 확인할 디버그 수단 추가.

### §24-1. 결합 프리팹 ThumbIK 튜닝 누락 (설정 드리프트)

- **발견**: `ur5e_dg5f_left.prefab`의 Dg5fThumbIK만 `maxStepDeg=2.5 / iterations=3`
  (코드 기본값). §20-7 튜닝 배치는 손 단독 프리팹 4종(1.5/2)만 커버했고,
  결합 프리팹은 §22에서 그 뒤에 생성돼 튜닝을 못 받음 — 틱당 스텝 권한이
  검증 세팅의 2.5배(7.5° vs 3°)라 이동 중 CCD 그리디 진동이 크게 나타나는 조건.
- **수정**: 프리팹 1.5/2로 통일. 씬 인스턴스는 오버라이드 없이 상속 확인.
- **⚠️교훈**: 새 결합/파생 프리팹을 만들면 기존 튜닝값 전수 이식을 확인할 것
  (§18-2 "씬 직렬화가 코드 기본값을 덮는" 함정의 프리팹 변형).

### §24-2. 엄지 목표 디버그 마커 (Dg5fThumbIK)

- **추가**: `debugShowTip`(기본 on) — Play 중 구체 3개로 목표 계층 분리 표시.
  런타임 전용(씬 저장 안 됨), 콜라이더 없음.
  - 노랑 `DBG_ThumbTip_UDP`: UDP 수신 비율을 로봇 치수로 복원한 해부학 목표(핀치 블렌딩 전)
  - 빨강 `DBG_ThumbTip_CCDTarget`: 핀치 블렌딩+targetLerp 스무딩 후 CCD가 실제 쫓는 목표
  - 초록 `DBG_ThumbTip_Robot`: 로봇 엄지끝 실측
- **판독법**: 손 정지에 노랑이 떨면 비전(Python) 노이즈 / 노랑 안정+빨강·초록 떨면
  Unity(IK·물리) / 노랑이 작업공간 밖을 돌면 정규화(체인 비율) 문제.
- **상태**: 라이브 재검증 대기(§20-7 떨림 잔존 건 미종결). → §25에서 종결.


## 25. 엄지 리타게팅 스케일·앵커·1_2 정책 전면 재정렬 — 도달 불가 목표 소멸 (2026-07-15)

§20-7 이후 잔존하던 "엄지 이동 중 덜덜 떨리다 정지" 증상을 §24 디버그 인프라(3색 마커
+thumbik CSV)로 계층 분해 → 근본원인 3개를 순차 규명·수정. 같은 날 4세션 A/B로 검증.

### §25-1. 근본원인 (측정으로 확정)

물리·축부호·비전 전부 무죄(관절 |tgt−act| ~1.2°, corr 양수). **목표가 상시 도달권 밖 3~6cm**:
1. **사람 기준 길이 과소**: v1 보정 thumb_chain_ratio(마디합/손길이)=0.828이 MediaPipe z 압축
   편향으로 ~17% 과소 — 같은 세션 직선 최대 0.996 > 마디합 0.828 = 기하학적 모순 실측.
2. **로봇 기준 길이 과대**: 마디합 14.81cm(41.95/31.00/38.80/36.30mm, URDF=Unity 일치)를
   썼으나 **도달거리는 1_2(대향 롤)에 강의존** — URDF FK 리밋 스윕: 1_2=0°→체인의 77%,
   15°→84%, 90°→100%. 1_2가 elevation ff 전담(§20-5/20-7 정책)이라 CCD가 리치 확장에
   못 씀 → 실효 상한 12.4cm(84%).
3. **앵커 어긋남**: DG5F 엄지 팁 작업공간은 손바닥 법선(x)으로 최소 ~3cm(0.24) 떠 있는데
   (기구부 돌출 장착) 사람 엄지끝은 펴면 손바닥 평면에 붙음 — 라이브 명령 82%가 x<0.2
   = **명령의 89%가 작업공간 밖**(URDF 작업공간 83k점 × 명령 7,564개 대조).
   ⚠️오프라인 검증 함정: URDF→Unity (x,y,z)→(−y,z,x)는 **det=−1 반사**라 외적으로 만드는
   축이 뒤집힘 — 변환 후 프레임에서 축을 재계산해야 Unity 런타임과 일치.

### §25-2. 수정 3종 (전부 적용·검증됨)

1. **기준 길이 재정의(마디합→최대 도달거리)**: Python calibrate v2 —
   |엄지끝−CMC|직선/손길이 **p95**를 `thumb_reach_ratio`로 저장(보정 파일 version 게이트,
   v1이면 기본값 1.0+재보정 경고), compute_thumb_tip은 '펴짐 비율' n=직선/(손길이×비율)
   계산 후 **크기 1.0 클램프**. Unity `robotThumbMaxReach=0.124f`(serialized, 1_2 정책
   종속 주석) 복원 스케일+구면 안전망. probe_sender에 tipmax/tipover 모드 추가.
   재보정 실측 thumb_reach_ratio=0.9205. CALIBRATION_GUIDE에 "엄지 쭉 펴기" 동작 추가.
2. **가상 앵커 오프셋**: 명령 구름→작업공간 ICP 번역 피팅 →
   `reachOffset=(+0.174,−0.038,−0.092)`(정규화 단위) — 적용 시 작업공간 밖 89%→10%,
   기하 잔차 0.27cm. 디버그 CSV의 ach도 가상 앵커 기준으로 갱신.
3. **1_2를 CCD로 반환(2단계)**: cmcFeedforward 8→**0** + priorWeights {1,0,1,1}→**{1,1,1,1}**
   — 순수 파라미터 전환(ff 블록·CCD 제외 규칙이 자기 비활성), 원복=값 2개.
   §20-5 ff 도입 전제("위치로 깊이 재현 불가")는 앵커 정합으로 소멸. elevation은 약한
   prior로만. **프리팹 5종+씬 인스턴스 값 갱신**(§18-2 직렬화 함정).

### §25-3. 검증 (4세션 라이브 A/B + 프로브)

| 세션 | 평균오차 | p95 | x corr | z bias |
|---|---|---|---|---|
| ①수정전(14:47) | 5.16cm | 6.86 | 0.63 | −0.30 |
| ②스케일 재정의(15:52) | 4.26cm | 5.19 | 0.39 | −0.21 |
| ③앵커 오프셋(16:23) | 1.95cm | 3.21 | 0.54 | −0.04 |
| ④1_2 반환(16:36) | **1.33cm** | **2.93** | **0.90** | **−0.00** |

- 프로브: tipmax 12.36cm 정확/tipover 12.40 클램프/tipfar 1.47→**0.10cm**/oktip 1.19cm
  (전환 잔여상태 3.5~3.7cm 국소최소는 §20-7 기지 프로브 아티팩트 — 깨끗한 시작 정상)
- elevation(앞뒤) 보존: corr(rx_1_2, act_1_2)=0.884, 깊이 주경로는 위치 x축(corr 0.902)
- 정지 구간 err 0.77cm(softZone 안), damper 건강(감쇠 중 err 0.76cm = 수렴 근처에서만)

### §25-4. 정지 미세떨림 해결 — 주범은 CCD 권한 과다 (같은 날 저녁, 리플레이 A/B로 확정)

1단계 진단에서 "입력 노이즈 추종"으로 봤으나(로봇이 목표의 ×1.5~5 고주파), 라이브에서
떨림 잔존 보고 → 3중 수정으로 종결:

1. **tip One Euro 무력 상태 수정(Python)**: min_cutoff 0.6Hz는 1초 스케일 저속 드리프트를
   전부 통과시키고(입력 2.6=필터후 2.6cm/s 실측) beta 0.001은 속도 보상 무력 →
   vision_node에 tip 전용 `TIP_MIN_CUTOFF=0.15 / TIP_BETA=0.5` 신설(각도 20ch·핀치 불변).
2. **prior 각도 스무딩(Unity)**: prior가 쓰는 사람 관절각(패킷 0..3)이 노이즈 원시값이라
   매 틱 CCD와 줄다리기 → `priorAngleLerp=4/s` 신설. (기여 ~30% — 부수 요인으로 판명)
3. **주범 = CCD 권한 과다**: maxStepDeg 1.5×iterations 2 = 150°/s가 노이즈의 매 편위를
   전력 추격·오버슈트 — 부호교대율 12~17%(진동 아닌 "스프린트" 패턴), 입력 ×21 증폭.
   → **maxStepDeg 0.8 × iterations 1 (40°/s)**: 떨림 1/10 + 오차 절반.

**검증 방법론(신규 인프라): 녹화 리플레이 A/B** — `unity_dg5f_*.csv`(rx 20ch) +
`thumbik_*.csv`(n/pinch_d)에서 v3 패킷을 재구성해 5006으로 루프 재생(스크래치패드
replay_sender.py). 웹캠 없이 라이브 노이즈를 결정적으로 재현 → Play 중 exec로 파라미터를
페이즈별 전환하며 같은 입력에 대한 반응만 비교:

| 페이즈(같은 입력, HF 1.5cm/s) | 로봇 HF | 증폭 | err 평균 |
|---|---|---|---|
| A 기준(1.5×2, prior3) | 31.9cm/s | ×21 | 1.50cm |
| B prior=0 | 22.5 | ×15 | 0.92cm |
| **C 0.8×1 (채택)** | **3.3** | **×2.2** | **0.70cm** |
| D C+softZone 3cm | 3.7 | ×2.5 | 0.71cm |

회귀: oktip 4s만에 1.20cm(수렴 속도 무손실), tipfar 0.01cm(역대 최고), 콘솔 0.
코드 기본값+프리팹 5종+씬 갱신. **라이브 체감 확인됨(2026-07-15 저녁, 사용자)**.

- ⚠️노트북캠은 기존 웹캠보다 정지 드리프트 ~1.5배 — 캠 변경 시 재보정 권장.
- 남은 여지: 엄지 빠른 동작이 굼뜨면 maxStepDeg만 1.0~1.2 상향(iterations 1 유지).
- 다음 과제: 벌림 게이트 해제, GraspPoint DG5F 재측정, 팔 IK 활성 검증.

## 26. 엄지 "쭉 폄 = 로봇 쭉 폄" 정렬 — 직진도 비율 + 방향별 최대도달 테이블 (2026-07-15 밤)

라이브 확인에서 사용자 보고: 엄지를 손바닥 축 방향으로 완전히 뻗어도 노란공(UDP 복원
목표)·빨간공(CCD 목표)이 로봇 완전 폄 위치보다 안쪽 — 로봇이 굽힌 채 도달해버림.
로그 실측으로 **양쪽 계산 모두** 원인 확정 (THUMB_RETARGET §7 로드맵 1·2번에 해당):

### §26-1. 원인 (thumbik_20260715_1744/1803.csv 실측)

1. **Python 쪽 — 펴짐 비율이 방향 의존**: §25의 크기 정의(|끝−CMC| 직선 ÷ 손길이×보정
   비율 0.9205)는 보정 세션의 최대치를 상수로 박는 방식이라 MediaPipe z 압축의
   **방향 의존 오차**를 못 넘김. 실측: 손가락 방향으로 뻗으면 |n|→0.95~1.0,
   손바닥 옆/앞으로 뻗으면 |n|→**0.69~0.74에서 포화**(1803 세션 max 0.743).
2. **Unity 쪽 — 복원 반경이 구정책 잔재 + 단일 스칼라**: robotThumbMaxReach=0.124는
   1_2가 ff 전담이던 §20-5 정책의 실효 상한 실측값인데, §25-2-3에서 1_2를 CCD로
   반환한 뒤 재측정 안 됨(툴팁의 "정책 바꾸면 재측정" 경고 그대로 적중 — 기하학적
   최대는 14.8cm). 게다가 방향별 최대도달이 체인의 77~100%로 변해 단일 반경으론
   "사람 100% = 로봇 100%"가 모든 방향에서 성립 불가. 실측: |n|=1.0 수신 구간(138
   샘플)에서 act_1_3 평균 −40° = 로봇이 굽힌 채 목표 도달.

### §26-2. 수정 (Python + Unity 계약 동시 개정)

1. **펴짐 비율 = 직진도 (dg5f_angles.compute_thumb_tip)**: 크기를
   |엄지끝−CMC| 직선 ÷ (**같은 프레임** CMC→MCP→IP→끝 마디합 × 직진도 상한 0.97)로
   재정의. 같은 프레임 같은 랜드마크끼리의 비 → 삼각부등식으로 항상 0~1, 일직선이면
   이방성 z 압축이 분자·분모에 동일하게 걸려 비가 보존 = **어느 방향으로 뻗어도 1.0**.
   합성 랜드마크 검증: z를 0.4배 압축해도 쭉 편 엄지 3방향 모두 |n|=1.000, 굽히면
   비례 감소. 보정 의존 소멸(카메라·세션 이전 문제 해소) — calibrate v3가
   thumb_straight_ratio(직선/마디합 p95)를 선택 저장(기본 0.97), v1/v2 파일은
   경고 없이 기본값 폴백. CALIBRATION_GUIDE 갱신(동작 10번 필수→선택).
2. **방향별 최대도달 테이블 (Dg5fThumbIK)**: Start에서 엄지 4관절 리밋 박스를
   FK 스윕(13⁴=28,561 포즈, 원위→근위 순 rest 프레임 회전 — §18 CCD와 동일 원리)해
   가상 앵커 기준 방향 bin(방위 36×고도 18, 10°)별 최대 |tip−앵커|를 적층, 빈 bin은
   이웃 max 확산으로 충전, 조회는 쌍선형 보간. 복원식 = 가상앵커 + 방향 × 펴짐비율 ×
   **그 방향** 테이블 도달거리 (구면 클램프 → 비율 1.0 클램프로 대체). 정의상
   사람 100% 폄 = 그 방향 작업공간 경계 = 로봇 완전 폄. robotThumbMaxReach는
   reachOffset 거리 단위+테이블 폴백으로 역할 축소(0.124 유지 — ICP 오프셋이 이
   단위로 저장돼 있어 변경 금지). 디버그 CSV의 ach도 방향별 정규화로 갱신
   (1.0 = 그 방향 최대도달, n과 비교 가능 유지).

### §26-3. 배포/검증 상태

- 코드 3종(dg5f_angles/calibrate/probe_sender 주석) 루트 dg5f/에도 동기화,
  Dg5fThumbIK.cs는 라이브 Unity 프로젝트(KDT_robot_AI)에도 복사.
- probe_sender tipmax/tipover 완료기준 갱신: 노란공이 그 방향 작업공간 경계에 찍히고
  로봇 엄지가 완전히 뻗어야 함.
- ⚠️ 라이브 검증 대기: ① Play 시작 로그에 "방향별 최대도달 테이블 x.x~xx.xcm" 범위가
  대략 7~15cm인지 ② 엄지 쭉 폄 시 vision [send] tip 크기 ~1.0 ③ 노란공이 완전 폄
  팁 위치와 일치하고 로봇이 실제로 쭉 뻗는지 ④ 핀치·떨림 회귀 없는지(§25-4 처방 불변).
- 구 로그 리플레이는 n이 구정규화 값이라 이 수정 검증에 못 씀 — 라이브 필요.

## 27. 강화학습 범위 재확정 — 단일 GraspPoint 팔 도달 (2026-07-20)

기존 move→grasp→lift 단계형 전이학습과 DG5F 손가락 20관절을 포함한 policy 계약을
폐기했다. 새 제품 파이프라인은 `3D 카메라 목표 좌표 -> 강화학습 기반 UR5e 팔 이동
-> DG5F 손 원격조작`이며, 강화학습 팀의 책임은 가운데 팔 이동 단계로 한정한다.

- 새 Behavior: `DG5FGraspPointReach` spec 1.0.0
- policy I/O: observation 26, UR5e continuous action 6
- 작업점: palm-local 단일 `GraspPoint`; 손가락 20관절은 학습에서 제외
- 목표 분포: 패널 반경 0.20~0.85 m와 360° 전 방향을 각각 균등 생성
- 성공: 1 cm 이내·0.05 m/s 이하를 0.25초 유지, episode 최대 20초
- 학습: 이전 checkpoint/curriculum 없이 fresh PPO 5M steps
- 승인: 미학습 500 seed에서 성공률 90% 이상과 안전/물리 오류 0건

3D 카메라 수신·좌표 보정은 후속 adapter 경계로 남겼다. 위의 과거 파지·상승 기록은
실험 이력 보존 목적이며 현재 실행 계약으로 사용하지 않는다.

구현 검증 상태:

- Reach EditMode 22개와 PlayMode 3개 테스트 통과
- Linux player 빌드 및 `DG5FGraspPointReach` communicator 연결 통과
- `max_steps: 512` smoke가 checkpoint와 ONNX를 정상 export
- 5M 본학습 및 실제 500-seed 승인 평가는 후속 실행 항목
