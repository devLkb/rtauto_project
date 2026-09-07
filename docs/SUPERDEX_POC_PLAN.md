# SuperDex PoC 계획 — DG5F 다지 파지 RL 이관 평가

작성 2026-09-07 (v1). 브랜치 `SuperDexTest`에서만 진행한다.
상위 정본은 [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md) — 이 문서와 상충하면 로드맵이 우선한다.
관찰·액션·보상 스펙의 정본은 [`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)다.

---

## 1. 결정 요약

**DG5F 다지 파지 강화학습을 [Project SuperDex](https://github.com/facebookresearch/project_superdex)로
이관하는 것을 평가한다. Unity는 디지털 트윈·시각화·ROS2 통합 계층으로 유지한다.**

이관이 아니라 **평가**다 — 아래 §5 게이트를 순서대로 통과해야 채택이고, §6 기준에
걸리면 Unity로 회귀한다. 이 판단을 브랜치에서 하는 이유가 그것이다.

### 왜 SuperDex인가 — 두 가지 근거

**(1) Unity PhysX는 다지 파지를 표현 자체를 못 한다 (성능이 아니라 표현력 문제).**
PhysX는 non-kinematic Rigidbody에 concave mesh collider를 허용하지 않는다
([Unity Manual](https://docs.unity3d.com/6000.1/Documentation/Manual/rigidbody-configure-colliders.html)).
`ArticulationBody` 링크는 전부 dynamic이므로 **DG5F 지골·손가락 말단과 파지 대상 물체가
모두 convex hull로 근사**된다. 파지 성공은 접촉점 위치·법선 방향·마찰원이 결정하는데,
손가락 끝이 둥글려지면 접촉 법선이 실제와 다른 곳에 생기고 FOUP 손잡이·플랜지·홈 같은
concave 피처는 시뮬레이션에 존재하지 않는 형상이 된다. 정책은 없는 형상을 exploit하도록
학습하고, 이 실패는 sim에서 성공으로 보이다가 실물에서 터진다 — 보상 튜닝으로 메울 수
있는 갭이 아니다.

여기에 **질량비 문제**가 겹친다. 웨이퍼 적재 FOUP는 8~9 kg급, DG5F 손가락 링크는 수십 g
이다. 질량비 1:100 이상의 다접촉은 iterative solver가 가장 취약한 조건이다. SuperDex는
통합 implicit solver + **SDF collider**(convex decomposition 없이 non-convex dynamic body
처리)를 내세우며, 이는 정확히 이 조건을 겨냥한 설계다.

**(2) AI agent가 구현을 담당한다는 조건이 SuperDex에 결정적으로 유리하다.**
Unity ML-Agents 환경의 상태는 코드에만 있지 않다 — `BehaviorParameters`,
`DecisionRequester`, 센서 컴포넌트, 인스펙터 드래그 참조, 직렬화 필드가 `.unity`/`.prefab`
파일에 들어 있고 **AI agent는 이걸 신뢰성 있게 편집하지 못한다.** `CLAUDE.md` 원칙 3이
"창 이름 + 클릭 경로 + 정확한 필드명"까지 요구하는 이유가 그것이다 — Unity RL 작업의
상당 부분이 코드가 아니라 에디터 조작이라서 사람이 루프에 갇힌다.

SuperDex Lab은 `reset()`/`step()`/관찰/보상/종료가 전부 Python이고 태스크 설정은
`<env_module>.train.json` 레시피다. **에디터 상태가 0이다.** Studio는 asset을 한 번 굽는
용도로만 쓴다. 1인 체제 + AI agent 구현에서 이 차이가 개발 속도를 배로 가른다.

### 왜 Unity를 버리지 않는가

- **ROS2/Nav2/AMR 통합이 SuperDex에 전무하다.** 이 절반은 Unity가 계속 소유해야 한다.
- URSim ↔ Unity 양방향 팔 트윈(로드맵 v9·v12)은 RL과 무관하게 성립하는 독립 자산이다.
- 시연 UI·모니터링은 Unity가 실제로 최적 도구다.

### 기존 RL 자산의 처분

Unity ML-Agents RL 부분은 어차피 전면 재설계 대상이므로 **"기존 코드를 살리려고 Unity를
유지한다"는 근거는 성립하지 않는다.** 반대로, SuperDex에도 매니퓰레이션 태스크 스위트가
없어서 환경을 직접 만들어야 하지만 이는 **양쪽 비용이 대칭**이므로 SuperDex의 단점이
아니다. 지적 자산은 코드가 아니라 관찰·액션·보상 설계이며 그건
[`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)에 엔진 독립으로 남긴다.

---

## 2. 역할 분리 아키텍처

```text
[학습]  SuperDex (고정 버전 핀)
          DG5F 공식 asset (Tesollo 라이선스) + SDF collider
          DG5FGraspEnv (Gymnasium)
          RLlib PPO — critic=특권상태 / actor=실물에서 얻을 수 있는 관찰
          env runner = CPU 스레드에 팬아웃, learner = GPU (§8)
                  |
                  v
        RLlib checkpoint (RLModule + connectors)
                  |
        래퍼 nn.Module = normalize -> RLModule -> dist.mean -> rescale
                  |
                  v
          dg5f_policy_v{N}.onnx   <- raw_obs -> raw_action 자기완결
             (관찰·액션 스펙 버전을 ONNX 메타데이터에 기록)
                  |
        +---------+----------+
        v                    v
  Unity Inference Engine   ROS2 / Python onnxruntime
  (ML-Agents 미사용)         -> inference adapter
        |                    -> Tesollo dgsdk / UR16e RTDE
        v                    -> 실물 DG5F + UR16e + AMR
  디지털 트윈 / 시연 / 모니터링
  URSim <-> Unity 양방향 유지
  ROS2 / Nav2 통합 계층 (SuperDex에 없음 -> Unity가 계속 담당)
```

> ⚠️ **Unity 트윈의 용도를 여기서 못 박는다.**
> - ✅ 관찰·액션 계약 검증, AMR↔팔 순차 동작 시퀀싱, ROS2 통합 테스트, 시연·시각화·모니터링
> - ❌ **파지 안정성의 물리적 검증** — 정책은 SuperDex 접촉 물리로 학습됐고 Unity PhysX에서
>   실행하면 접촉 지배 구간에서 반드시 발산한다. 이걸 정하지 않으면 Unity에서 물체가
>   미끄러지는 걸 보고 정책 버그로 오진하며 시간을 버린다.

---

## 3. 확인된 SuperDex 사실 (2026-09-07 기준)

| 항목 | 내용 |
|---|---|
| 릴리스 | v1.0.0 **2026-08-24**. 저장소 생성 2026-08-20. `stable` 브랜치 존재, `main` 급변 |
| 라이선스 | 1st-party 코드 **Apache-2.0**, asset/문서 CC-BY-4.0, `superdex_mesh_cli`만 GPLv3 |
| 플랫폼 | Linux x86_64 / **Windows x86_64** / macOS ARM |
| Python | **3.12 전용** (`requires_python >=3.12,<3.13`) |
| 설치 | PyPI pre-built wheel. `superdex` / `superdex-lab` / `superdex-physics` 모두 **1.0.0**. `superdex`는 엄브렐라(py3-none-any), 플랫폼 바이너리는 `superdex-physics`의 `cp312-cp312-win_amd64` 등. **소스 빌드 불필요** — README의 CMake/Ninja/Clang 17+ 경로는 엔진을 직접 고칠 때만 |
| 실행 진입점 | Studio = `superdex-studio`. 예제는 클론에서 스크립트 직접 실행. 환경변수 `SUPERDEX_ASSETS_PATH`(asset 트리), `SUPERDEX_PRECISION=double`(fp64 빌드) |
| 구성 | Physics(C++) / Robotics(C++, pybind) / Studio(GUI) / Lab(RL, **pyproject에 Alpha**) |
| RL | Gymnasium + **Ray/RLlib 새 API 스택(RLModule)**. PPO 권장, SAC 실험적 |
| 기본 벤치마크 | CartPole / Ant / HalfCheetah **뿐** — 매니퓰레이션 태스크 없음 |
| 병렬화 | **native vectorization 없음.** Ray EnvRunner / Async·Sync·HybridVectorEnv (CPU 프로세스) |
| 학습 기본값 | `num_env_runners=32`(가용 CPU 초과 시 자동 캡), `num_gpus_per_learner=0` |
| 향후 | Teleop(Quest 3 / UE5) **Q4 2026** 예정 |

### DG5F asset (이 프로젝트에 직접 해당)

`assets/bots/hands/` 아래에 **Tesollo에서 라이선스받은 DG-5F-M** asset이 있다.

- `dg5f_long`, `dg5f_short` × `left/`, `right/`
- `dg5f_long_seed`, `dg5f_short_seed` — **Seed Robotics SINGLEX-3 촉각 센서**를 DG-5F-M
  지문 형상에 장착한 변형 (`assets/bots/sensors/dg5f_seed`)
- 조합: `assets/bots/arm_hand_combos/fr3_dg5f_short`, `fr3_dg5f_short_seed`
- 포함 요소: collision geometry 수정, joint axis/limit, mass, inertia,
  Coulomb/viscous friction, damping, actuator·sensor 정의
- **단서: 공식 README가 "simplified robot description"이라 명시.** 완전한 디지털 트윈으로
  간주하면 안 된다. 다만 비교 대상은 완벽한 트윈이 아니라 **자체 URDF→Unity 임포트본**이다.

팔 asset은 **FR3(Franka), OpenArm v20뿐 — UR16e 없음.** Studio에서 URDF import 필요(§5 게이트 3).

### 확인된 API 표면 (`superdex_robotics/examples/control/example_osc_jsc_control.py`)

FR3는 OSC, DG5F는 **JSC**(joint space PD, target joint position → torque)로 제어한다.
즉 **RL 액션을 raw torque가 아니라 DG5F target joint position으로 둘 수 있고**, 이는 실물
`dgsdk`의 명령 인터페이스와 같은 형태다 — sim2real에 유리한 구조다.

- 모듈: `superdex.physics`, `superdex.robotics`, `superdex.physics.paths`(`resolve_asset`)
- 컨트롤러: `ControllerBasicJscPdParams` / `ControllerBasicJscPdTarget`
  (OSC 쪽은 `ControllerBasicOscPdParams` / `...Target`)
- 수명주기: `initialize` → `create_scene` / `set_gravity` → `load_bot_prefab_from_file` →
  `create_context` → `create_bot` → `get_articulated_actor` → `create_controller` →
  루프(`get_current_observations_from_mochi` → `compute_output` →
  `set_external_forces_on_dofs` → `step`) → `destroy_bot` → `shutdown`
- 디버깅: `get_debug_server` (`superdex_physics_debugger`)
- 관절 이름 규약: `dg5f_joint_<finger>_<joint>` (예: `dg5f_joint_2_2` … `dg5f_joint_5_3`)
- asset 경로 형식(실측):
  `bots/arm_hand_combos/fr3_dg5f_short/right/fr3_dg5f_short_right.superdex_bot`
- **타임스텝 1/200 s (200 Hz)** — 접촉 시뮬레이션에 필요한 크기다. Unity 기본 fixed
  timestep 0.02 s의 4배 세밀도이며, Unity를 같은 수준으로 조이면 Unity의 throughput
  우위가 사라진다는 뜻이기도 하다.

---

## 4. 미확정 항목 — 게이트 진행 중 반드시 확정할 것

| # | 항목 | 왜 문제인가 | 확정 시점 |
|---|---|---|---|
| U1 | **DG-5F-M이 long wrist인가 short wrist인가** | SuperDex는 둘 다 제공한다. `config/rtauto_config.py`의 `DG5F_SHORT` 주석도 `"M"이 short면 1`로 미확정 상태다. 잘못 고르면 손목 길이만큼 전 학습이 틀어진다 | 게이트 0. Tesollo 도면/실물 실측 대조 |
| U2 | **손 단독 asset의 실제 경로** | 조합 asset 경로만 실측했다. 손 단독은 `bots/hands/dg5f_long/right/dg5f_long_right.superdex_bot` 형태로 **추정**한 것이다 | 게이트 0. 클론한 `assets/` 트리에서 직접 확인 |
| U3 | ~~PyPI 배포 버전 문자열~~ | **해소 (2026-09-07)** — PyPI 확인: `superdex` `superdex-lab` `superdex-physics` 모두 **1.0.0**, `requires_python >=3.12,<3.13`. `superdex-physics`에 `cp312-cp312-win_amd64.whl`이 있어 **Windows 소스 빌드 불필요**. `requirements-superdex.txt`에 `==1.0.0` 핀 반영 | 완료. `ray`/`onnx` 핀만 게이트 0-4에 남음 |
| U4 | **Tesollo asset 라이선스 범위** | 시뮬레이션·시각화·학술/비상업 연구·오픈소스 통합은 허용, 물리적 제조·3D 프린팅·하드웨어 복제는 금지. 제한 대상은 **하드웨어 형상 재현**이므로 학습된 가중치가 파생물로 걸릴 가능성은 낮지만, **asset 자체를 상용 제품에 재배포하는 것은 불가**. 공개 문서·영상에는 Tesollo attribution 필요 | **게이트 2 착수 전.** 벤더에 서면 질의 |
| U5 | **mediapipe의 Python 3.12 지원** | ML-Agents가 빠지면 3.10.11 핀의 근거가 사라지지만 비전 파이프라인이 같은 venv를 쓴다 | 게이트 1. venv를 분리하면 회피 가능(§7) |
| U6 | **단일 env steps/sec** | 전체 계획의 실현 가능성을 결정하는 숫자인데 공개 벤치마크가 없다 | 게이트 0에서 측정 |

> ⚠️ **SuperDex의 fidelity 주장은 3자 검증이 없다.** 인용 논문이 미출간이고 저장소의
> Lab 벤치마크는 CartPole/Ant/HalfCheetah뿐이다. 마케팅을 신뢰하지 말고 게이트 0·2에서
> 직접 확인한다.

---

## 5. 게이트 — 순서대로, 앞이 깨지면 뒤를 하지 않는다

### 게이트 0 — 물리 전제 확인 (반일). **RL 없이 먼저 한다.**

목적: SuperDex의 존재 이유(다지 접촉 안정성)가 DG5F에 대해 성립하는지, 그리고 감당 가능한
속도가 나오는지를 **가장 싸게** 확인한다.

1. Python 3.12 venv 생성 + 고정 버전 wheel 설치 (§7 절차)
2. `project_superdex` 클론 → `SUPERDEX_ASSETS_PATH` 설정
3. **동봉된 예제를 그대로 실행** — `examples/basic/example_bot_loading.py`,
   `examples/control/example_osc_jsc_control.py`
4. U1·U2·U3 확정: `assets/bots/hands/` 트리 확인, DG-5F-M 손목 길이 판정, wheel 버전 기록
5. `superdex_physics_debugger`(`get_debug_server`)로 접촉 시각화
6. **스크립트 파지 테스트**(학습 아님): 손 단독 asset 로드 → 중력 ON → 큐브 배치 →
   JSC로 닫는 자세 지령 → 유지

**판정**
- 물체가 흔들림(jitter)·관통(penetration) 없이 유지되는가
- **단일 env steps/sec 및 realtime factor 측정** (200 Hz 기준 실시간 배율)

> 게이트 0이 깨지면 SuperDex를 채택할 이유 자체가 사라진다. 반일 만에 알 수 있으므로
> 다른 어떤 작업보다 먼저 한다.

### 게이트 1 — 배포 계약 확인 (반일). DG5F와 독립이라 병행 가능.

`dg5f_policy.onnx` 화살표는 **다이어그램에서 유일하게 "될지 모르는" 구간**이고, 가장 싸게
확인할 수 있다. 근거:

- **RLlib 새 API 스택은 ONNX export를 지원하지 않는다**
  ([ray#45526](https://github.com/ray-project/ray/issues/45526) —
  `ONNX export not supported for RLModule API`). `export_policy_model(onnx=...)`는 구
  API 스택 전용이다.
- SuperDex의 `superdex_lab/apps/rllib/checkpoint_policy.py`도 ONNX를 만들지 않는다.
  RLModule + 관찰 전처리 + 액션 후처리를 **in-process Python 추론용으로** 복원할 뿐이며,
  커넥터를 못 쓸 때 학습과 발산할 수 있다고 코드가 직접 경고한다.
- 관찰 정규화와 액션 리스케일은 신경망 **바깥**, RLlib 커넥터
  (`EnvToModulePipeline`/`ModuleToEnvPipeline`)에 산다.

**절차**
1. CartPole PPO 5분 학습 (DG5F 불필요)
2. **래퍼 `nn.Module`을 export**:
   `forward(raw_obs)` → `normalize`(커넥터 통계를 **그래프 안 상수로 고정**) →
   `RLModule.forward_inference` → action distribution의 deterministic mean → `rescale` →
   `raw_action`
3. **3자 파리티 테스트**: 동일 obs 벡터를 (a) SuperDex Python (b) ROS2측
   `onnxruntime` (c) Unity Inference Engine C#에 넣어 액션이 허용오차 내 일치하는지

> ⚠️ **정규화 통계를 JSON으로 빼서 Unity C#과 ROS2 Python에 각각 구현하지 마라.**
> 구현이 셋으로 갈라지는 순간 계약이 조용히 깨지고, 이 프로젝트에서 가장 추적하기 어려운
> 버그가 된다. 그래프 안에 상수로 박아 ONNX 하나가 `raw_obs → raw_action` 전체를
> 자기완결적으로 담게 한다.
>
> Unity 추론은 **ML-Agents를 거치지 말고 Inference Engine(구 Sentis)을 직접** 쓴다 —
> [ML-Agents 공식 문서](https://github.com/Unity-Technologies/ml-agents/blob/main/docs/Unity-Inference-Engine.md)가
> 외부 학습 모델은 그렇게 하라고 명시한다. Sentis는 Unity 6에서 Inference Engine으로 개명됐다.

### 게이트 2 — DG5FGraspEnv (2~3일). **착수 전 U4(라이선스) 회신 확보.**

- wrist **고정**, 큐브 1종, 액션 = DG5F target joint position
- 관찰: 관절 위치/속도, 물체 위치/자세/선·각속도, 지문 접촉 (필요 시 촉각)
- 보상: 지문-물체 접촉, 다지 안정 접촉, 파지 안정성, 들어올림, 유지 시간
- 페널티: 낙하, 과도한 힘, 과도한 관절 운동, 미끄러짐
- **critic에 특권 상태(접촉력·물체 자세·마찰계수), actor에는 실물에서 얻을 수 있는 관찰만**
  (asymmetric actor-critic). ML-Agents로는 표현할 수 없는 구조이고, 접촉·촉각 정책
  sim2real의 표준 레시피다.
- 스펙은 [`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)에 **버전 번호를 붙여** 기록하고
  ONNX 메타데이터에 그 버전을 박는다.

**판정**: 100 eval 에피소드에서 **들어올린 뒤 2초 유지 성공률 ≥ 80 %**, 그리고 **집계
throughput 기록**.

### 게이트 3 — UR16e asset (1~2일)

`urdf/ur16e_dg5f_right_build/`의 URDF를 **Studio에서** import → remesh → watertight →
SDF bake → `.superdex_bot`.

> ⚠️ runtime URDF loader에는 제약이 있다 — mesh collision은 지원하나 **primitive
> collision(box/cylinder/sphere)은 일부 무시될 수 있고**, raw mesh가 watertight하지 않으면
> SDF collider 품질이 떨어진다. 그래서 production asset은 Studio 경유가 공식 권장 경로다.

**판정**: 관절 한계가 UR16e 스펙과 일치, 충돌 형상이 primitive 무시로 깨지지 않았는가,
자기충돌 정상. 관절 순서·부호·영점은 로드맵 v11의 URSim 검증 결과와 대조한다.

### 게이트 4 — 일반화와 domain randomization

실린더 + 산업 물체 1종 추가, mass/friction/scale randomization.

> ML-Agents는 DR과 curriculum이 YAML(`environment_parameters` +
> uniform/gaussian/multirangeuniform sampler)에 내장돼 있고 SuperDex에는 없다 — env 코드에
> 직접 쓴다. AI agent 구현 조건에서 비용은 작지만, **DR은 샘플 요구를 3~10배로 올려
> throughput 병목을 여기서 처음 만나게 된다**(§8).

**판정**: 정책이 유지되는가, 샘플 비용이 몇 배로 뛰는가.

### 이후 확장 순서 (게이트 통과 후)

1. wrist pose 액션 추가 → 2. approach + grasp + lift 결합 → 3. UR16e 통합 →
4. domain randomization 확대 → 5. sim-to-real

---

## 6. Unity 회귀 기준 — 사전에 못 박아 둔다

하나라도 걸리면 SuperDex를 중단하고 Unity ML-Agents로 돌아간다.

1. **게이트 0 실패** — 합리적 타임스텝에서 스크립트 파지가 불안정/관통.
   SuperDex의 핵심 주장이 DG5F에 대해 성립하지 않는다는 뜻
2. **게이트 1이 2일 내 미해결** — 아키텍처가 닫히지 않음
3. **게이트 2에서 집계 throughput < 2,000 steps/s** 또는 **5e7 step 내 파지 미발현**
4. **SuperDex 버그/API 파손으로 2주 연속 진척 없음** + upstream 이슈 2주 이상 무응답
5. **저장소 90일 무커밋 또는 archive**
6. **U4(라이선스)가 의도한 용도를 차단**하고 자체 asset 대체로도 해결되지 않음

회귀 비용이 낮게 유지되는 이유: 관찰·액션·보상 설계가
[`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)에 엔진 독립으로 남고, UR16e·DG5F URDF는
`urdf/`에 그대로 있다. 폴백은 Unity다 — `CLAUDE.md`에 따라 **MuJoCo 재도입은 배제**하며,
Isaac은 GPU 워크스테이션이 실제로 들어올 때만 검토한다.

> **과설계 금지.** SuperDex 호출은 env 코드의 `sim` 모듈 한 곳에 격리하되, 그 이상의
> 추상화 계층은 만들지 않는다. 근거는 `CLAUDE.md`가 금지하는 "나중 이식 대비" 과설계와
> 같은 함정이기 때문이다. 격리의 목적은 이식성이 아니라 **alpha 소프트웨어의 API 파손
> 반경을 한 파일로 묶는 것**이다.

---

## 7. 환경 구성 — venv를 분리한다

SuperDex는 **Python 3.12**, 기존 파이프라인은 **3.10.11**(ML-Agents 핀)이다.
ML-Agents가 빠지면 3.10.11의 근거가 사라지지만 mediapipe가 같은 venv를 쓰므로(U5),
**섞지 않고 분리한다.**

| venv | Python | 용도 | 위치 |
|---|---|---|---|
| 기존 | 3.10.11 | mediapipe 비전, ML-Agents, UR RTDE 브리지 | `vision/.vision/` |
| 신규 | 3.12 | SuperDex Physics/Robotics/Lab, RLlib | `superdex/.venv/` |

`.gitignore`의 `.venv/` 패턴이 모든 깊이에서 매칭되므로 `superdex/.venv/`는 이미 추적
제외다. 요구사항은 `requirements-superdex.txt`에 핀으로 고정한다.

절차를 바꿨으면 [`PYTHON_ENV_SETUP.md`](PYTHON_ENV_SETUP.md)를 **그 자리에서** 함께
갱신한다(원칙 2). 그 문서는 Windows와 Linux를 모두 다룬다 — 한쪽만 고치지 않는다.

### 설정 키 (원칙 1 — 값을 코드에 박지 않는다)

모두 `config/rtauto_config.py`가 정본이며 `.env`로 덮어쓴다.

| 키 (.env) | 기본값 | 의미 |
|---|---|---|
| `RTAUTO_SUPERDEX_REPO` | *(없음)* | `project_superdex` 클론 루트. 머신마다 다름 |
| `RTAUTO_SUPERDEX_ASSETS` | `<repo>/assets` | asset 트리. SuperDex 자신은 `SUPERDEX_ASSETS_PATH` 환경변수를 읽으므로 런처가 이 값을 그 이름으로 내보낸다 |
| `RTAUTO_SUPERDEX_PYTHON` | OS별 `superdex/.venv/...` | 3.12 venv의 python 실행파일 |
| `RTAUTO_SUPERDEX_SIM_HZ` | `200` | 물리 스텝 주기. 예제 실측값 1/200 s |
| `RTAUTO_SUPERDEX_ENV_RUNNERS` | `os.cpu_count() - 4` | Ray env runner 수. 회사 12T → 8, 집 16T → 12 (§8) |
| `RTAUTO_SUPERDEX_GPUS_PER_LEARNER` | `1` | learner GPU 수. SuperDex 기본값 0이지만 두 머신 모두 CUDA GPU가 있다 (§8) |
| `RTAUTO_SUPERDEX_RESULTS_DIR` | `superdex/results` | 학습 산출물 |
| `RTAUTO_SUPERDEX_POLICY_DIR` | `superdex/policies` | ONNX 정책 산출물 |

**wheel 버전 핀은 [`../requirements-superdex.txt`](../requirements-superdex.txt)가 정본이다**
(`requirements-mlagents.txt`와 같은 관례 — 버전 문자열을 `config/rtauto_config.py`에 중복
타이핑하지 않는다). `superdex`·`superdex-lab`은 PyPI 확인 결과 **`==1.0.0`으로 이미
고정**했고(U3 해소), `ray[rllib]`·`onnx`·`onnxruntime`만 게이트 0-4에서 `pip freeze`로
확인해 채운다.

손 asset 변형은 **새 키를 만들지 않고** 기존 `RTAUTO_DG5F_HAND`(`right`)와
`RTAUTO_DG5F_SHORT`에서 파생시킨다 — 같은 사실을 두 곳에 타이핑하지 않는다(원칙 1).
`config/rtauto_config.py`의 `superdex_hand_asset()`이 그 조합을 asset 상대경로로 만든다.

---

## 8. throughput 현실 점검

### 작업 머신이 둘이다

| | CPU | GPU | RAM | env runner 기본값 |
|---|---|---|---|---|
| **회사** (주 작업) | Ryzen 5 7600 — **6C/12T** | **RTX 2080 8 GB** (Turing, sm_75) | 32 GB | **8** |
| 집 | Ryzen 7 7800X3D — 8C/16T | RTX 4070 Ti 12 GB (Ada) | 32 GB | 12 |

> 로드맵 v5·v14가 "학습 머신 RTX 4070 Ti / 7800X3D"로 적은 것은 **집 머신**이다.
> 회사 머신이 주 작업 환경이고 코어·VRAM이 더 작다 — **성능 판정의 기준은 회사 머신이다.**

`RTAUTO_SUPERDEX_ENV_RUNNERS`의 기본값은 **`os.cpu_count()`에서 파생**시킨다(스레드−4).
머신 사양을 코드나 `.env`에 박지 않기 위한 것이며, 새 PC에서 아무 설정 없이도 그 머신에
맞는 값이 나와야 한다는 원칙 2를 만족시킨다. 실측으로 더 좋은 값을 찾으면 그때 `.env`로
덮어쓴다.

> ⚠️ **RTX 2080은 Turing이라 bf16을 지원하지 않는다.** 혼합정밀도를 켤 때 bf16 대신
> fp16을 쓰거나 fp32로 둔다 — 4070 Ti(Ada)에서 통하는 설정을 그대로 회사 머신에
> 가져오면 런타임 에러가 난다. VRAM도 8 GB로 4 GB 작으므로, 나중에 vision 관찰을 넣으면
> 여기서 먼저 막힌다.

### 계산

- SuperDex 기본값 `num_env_runners=32`는 **두 머신 어느 쪽의 스레드 수도 넘는다.**
  스크립트가 가용 CPU에 맞춰 자동 캡하지만, learner 1개와 OS·Unity 여유를 남긴 값을
  설정에서 준다.
- 물리는 CPU이지만 **learner는 GPU를 쓸 수 있다.** SuperDex 기본값
  `num_gpus_per_learner=0`을 그대로 두지 않고 `1`로 올려 시험한다.
- 집계 throughput ≈ (단일 env steps/sec) × **8**(회사 기준). 단일 env가 500 steps/s면
  4 k/s → 1e8 step에 약 7 시간. 100 steps/s면 800/s → 1e8에 약 35 시간.
  **U6 측정 없이는 계획을 확정할 수 없다.**
- PoC 목표 규모인 1e7~5e7 step은 위 두 경우 모두 **수 시간~반나절**로 들어온다.
  1e8 이상이 필요해지는 순간(게이트 4의 DR 확대) 회사 머신에서는 하룻밤 이상이 되므로,
  그때 집 머신 활용이나 태스크 설계 축소를 함께 검토한다.
- **PoC 범위는 이 예산 안에 들어온다.** wrist 고정 + 특권 상태 관찰 + 조밀 보상 +
  ~16~20차원 액션이면 통상 1e7~5e7 step 규모다.
- **넘어가는 지점**: in-hand reorientation, vision 기반 관찰, 광범위 ADR, 다물체 대규모
  일반화. 이는 게이트 4 이후의 문제다.
- **Isaac Lab(단일 GPU 4k~16k env, 5e4~5e5 steps/s) 대비로는 10~100배 열세다.** 다만
  **Unity와 비교하면 이 항목은 차별점이 아니다** — Unity가 throughput을 얻는 방식은 한
  씬에 agent 수백 개 복제인데, 다지 접촉을 안정화하려고 fixed timestep을 0.02 s에서
  1~5 ms로 내리고 solver iteration을 올리면 그 우위가 사라진다. **두 후보의 공유된
  약점**이므로 A/B 선택의 결정 변수로 쓰지 않는다.
- SuperDex Physics 안에 CUDA 코드가 있어 GPU 벡터화 여지는 있으나 **계획에 넣지 않는다.**

---

## 9. 리스크

| # | 리스크 | 크기 | 완화 |
|---|---|---|---|
| R1 | fidelity 주장 미검증 (3자 벤치마크·논문 없음) | 중 | 게이트 0·2에서 직접 측정 |
| R2 | RLlib 새 API 스택 ONNX 미지원 + 커넥터 밖 정규화 | 중 | 게이트 1의 래퍼 export + 3자 파리티 테스트. 프로젝트 전체에서 가장 추적하기 어려운 버그 후보 |
| R3 | API breaking change (6개월간 확실히 발생) | 중 | **고정 wheel 버전 핀, `main` 추적 금지.** SuperDex 호출을 `sim` 모듈 한 곳에 격리 |
| R4 | throughput 상한 → 실험 회전 속도 병목 | 중 | 태스크 설계로 샘플 요구 억제(특권 관찰·조밀 보상·curriculum·단계적 액션 확장) |
| R5 | UR16e URDF 임포트 품질 (primitive 무시, SDF 품질) | 중 | Studio 경유 bake 필수 경로화(게이트 3) |
| R6 | Tesollo asset 라이선스 (상용 재배포 제약) | 중 | U4 서면 확인. 막히면 `urdf/`의 자체 기술서로 asset 자체 제작 |
| R7 | Unity PhysX 발산을 정책 버그로 오진 | 중 | §2의 트윈 역할 정의를 준수 |
| R8 | 문서 부족 (2주 된 프로젝트, 오픈 이슈 3개 = 커뮤니티 부재) | 중 | 예제 코드 3종(`train_samples.py`, `run_inference.py`, `checkpoint_policy.py`) + OSC/JSC 예제가 정본 |
| R9 | Meta의 프로젝트 방기 | 중~고 (테일) | Apache-2.0 + C++ 소스 존재하나 1인 팀이 물리 엔진을 유지할 수는 없다. 반대 신호: Teleop Q4 2026 로드맵, 2026-09-06까지 커밋, Reality Labs의 전략적 이해관계 |

**핵심은 이 리스크가 파이프라인에 침투하지 않는다는 점이다.** MuJoCo 때는 엔진이
파이프라인 *안에* 박히는 구조여서 통합·유지보수 비용이 폐기 사유가 됐다. 지금 구조에서
SuperDex는 **ONNX 뒤에 있는 교체 가능한 학습기**이고, 진짜 지적 자산은 관찰·액션·보상
설계(엔진 독립)다. 되돌릴 수 있게 설계된 도입이다.

---

## 10. 진행 기록

| 날짜 | 게이트 | 결과 |
|---|---|---|
| 2026-09-07 | — | 브랜치 `SuperDexTest` 개설, 본 문서·설정 키·`requirements-superdex.txt` 신설 |

<!-- 게이트를 진행할 때마다 위 표에 한 줄씩 추가한다. 판정 근거(측정한 steps/sec,
     성공률, 실패 로그)를 함께 적는다 — 회귀 기준(§6) 판단의 근거가 된다. -->

---

## 11. 게이트 0 실행 절차

> 모든 명령은 **저장소 루트**(`D:\workspace\KDT_1_AX_rtauto` — 각자 clone 위치)에서
> 실행한다. 저장소 상대경로는 `/`로 적었고 PowerShell도 그대로 받는다.
> **새 터미널은 venv가 꺼져 있다** — 각 단계의 활성화 명령을 매번 포함했다.

### 0-1. Python 3.12 준비

기존 3.10.11은 그대로 둔다. 3.12를 **추가로** 설치한다 (python.org Windows installer,
설치 시 "py launcher" 체크). 확인:

**터미널 1 (PowerShell, 리포 루트, 환경 준비)**

```powershell
py -0p
```

목록에 `-V:3.12` 줄이 보여야 한다. 안 보이면 3.12가 설치되지 않은 것이다.

### 0-2. venv 생성과 활성화

**터미널 1 (PowerShell, 리포 루트, 환경 준비)**

```powershell
py -3.12 -m venv superdex/.venv
```

```bash
python3.12 -m venv superdex/.venv
```

활성화 (이후 모든 단계에서 이 터미널을 계속 쓴다):

```powershell
superdex/.venv/Scripts/Activate.ps1
```

```bash
source superdex/.venv/bin/activate
```

프롬프트 앞에 `(.venv)`가 붙어야 한다. 붙지 않으면 PowerShell 실행 정책 문제이므로
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행한 뒤 다시 활성화한다.

```powershell
python -m pip install --upgrade pip
python -c "import sys; print(sys.version)"
```

`3.12.x`가 찍혀야 한다.

### 0-3. torch (CUDA) 먼저 설치

**터미널 1 (PowerShell, 리포 루트, `(.venv)` 활성 상태)**

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu124
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

`True`가 찍혀야 learner를 4070 Ti로 돌릴 수 있다. `False`면 CPU learner로도 게이트는
진행 가능하니 멈추지 말고 기록만 남긴다. CUDA 태그(`cu124`)가 안 맞으면
<https://pytorch.org/get-started/locally/>에서 현재 태그를 확인해
`requirements-superdex.txt`의 주석을 정정한다.

### 0-4. SuperDex 설치

> **소스 빌드는 하지 않는다.** README의 "Building from Source"(CMake 3.25+ / Ninja /
> Clang 17+ / Windows는 MSVC Build Tools)는 **엔진을 직접 고칠 때만** 필요한 경로다.
> PyPI에 pre-built wheel이 있고 Windows용 `superdex_physics-1.0.0-cp312-cp312-win_amd64.whl`이
> 실제로 올라와 있다(2026-09-07 확인). 그냥 설치한다.

**터미널 1 (PowerShell, 리포 루트, `(.venv)` 활성 상태)**

```powershell
pip install -r requirements-superdex.txt
python -c "import superdex.physics, superdex.robotics; print('import OK')"
```

`import OK`가 찍히면 설치 성공이다.

남은 핀을 고정한다 — `superdex` 계열은 `==1.0.0`으로 이미 박혀 있고 `ray`/`onnx`/
`onnxruntime`만 남았다:

```powershell
pip freeze | Select-String -Pattern "^ray|^onnx|^gymnasium|^torch"
```

```bash
pip freeze | grep -E "^ray|^onnx|^gymnasium|^torch"
```

> 나온 버전으로 `requirements-superdex.txt`의 해당 줄을 `패키지==버전`으로 고치고 파일
> 맨 아래 ⚠️ 블록을 지운다. 핀을 걸지 않으면 며칠 뒤 `pip install`이 다른 버전을 물어와
> 재현이 깨진다(§9 R3).

Studio가 실행되는지 확인한다 (진입점 이름은 `superdex-studio`):

```powershell
superdex-studio
```

창이 뜨면 성공이다. 닫아서 종료한다. 창이 안 뜨고 명령을 못 찾으면 venv가 활성 상태인지
확인한다(`superdex/.venv/Scripts/` 안에 실행파일이 들어간다).

> **`uv`를 쓰고 싶다면** README가 권하는 경로는 `uv venv` + `uv pip install superdex`이고
> 실행은 `uv run superdex-studio` / `uv run --no-project <스크립트>`다. 위 절차와 결과는
> 같다 — `uv run --no-project X`는 "이 venv를 활성화하고 `python X`"와 동등하며,
> `--no-project`는 클론 안에서 실행할 때 그 저장소의 `pyproject.toml`을 무시하게 하는
> 옵션이다. 이 리포의 기존 venv들이 `python -m venv` + pip 관례를 쓰므로(원칙 2,
> `PYTHON_ENV_SETUP.md`) 여기서도 그쪽으로 통일했다.

### 0-5. 저장소 클론과 asset 경로 설정

asset 트리는 wheel에 없고 저장소 안에만 있다. 클론 위치는 자유이며 이 리포 밖에 둔다.

**터미널 1 (PowerShell, 리포 루트, `(.venv)` 활성 상태)**

```powershell
git clone --branch stable https://github.com/facebookresearch/project_superdex D:/src/project_superdex
```

> `main`이 아니라 **`stable`**을 받는다. `stable`이 없거나 비어 있으면 `main`에서
> 릴리스 태그 `v1.0.0`을 체크아웃한다: `git -C D:/src/project_superdex checkout v1.0.0`.

클론 경로를 `.env`에 적는다 (**코드나 명령에 박지 않는다** — 원칙 1). `.env`가 없으면
`.env.example`을 복사해 만든다.

```powershell
Copy-Item .env.example .env -WhatIf
```

`-WhatIf`로 먼저 확인하고, `.env`가 아직 없을 때만 `-WhatIf`를 떼고 실행한다.
그 다음 `.env`를 열어 아래 한 줄을 **주석 해제하고 실제 경로로** 고친다:

```text
RTAUTO_SUPERDEX_REPO=D:/src/project_superdex
```

확인:

```powershell
python -c "import sys; sys.path.insert(0,'config'); import rtauto_config as c; print(c.superdex_assets_path())"
```

`None`이 아니라 실제 `...\project_superdex\assets` 경로가 찍혀야 한다.

### 0-6. U1·U2 확정 — DG5F asset 경로와 손목 길이

**터미널 1 (PowerShell, 리포 루트, `(.venv)` 활성 상태)**

```powershell
Get-ChildItem -Recurse -Filter *.superdex_bot (& python -c "import sys; sys.path.insert(0,'config'); import rtauto_config as c; print(c.superdex_assets_path())") | Select-Object FullName
```

출력에서 확인할 것:

1. **U2** — 손 단독 asset의 실제 파일명이
   `config/rtauto_config.py`의 `superdex_hand_asset()`이 만드는 경로
   (`bots/hands/dg5f_long/right/dg5f_long_right.superdex_bot`)와 일치하는가.
   다르면 그 함수를 실제 경로 형식으로 고치고 docstring의 ⚠️ 주석을 지운다.
2. **U1** — `assets/bots/hands/dg5f_long/README.md`와 `dg5f_short/README.md`를 읽고
   손목 길이 치수를 Tesollo DG-5F-M 도면/실물과 대조한다. **이 판정을 미루면 손목
   길이만큼 틀린 기하로 전 학습이 진행된다.**

   > ⚠️ **판정 결과를 바로 `.env`에 반영하지 않는다.** `RTAUTO_DG5F_SHORT`는
   > `dg5f_variant()`를 통해 **기존 파이프라인의 URDF·메시 선택까지 바꾼다.** 결과는
   > 먼저 §10 진행 기록에 적고, `.env` 변경은 §12의 절차대로 기존 파이프라인 회귀
   > 확인과 함께 별도로 처리한다.

### 0-7. 동봉 예제 실행

> 여기서는 **직접 스크립트를 쓰지 않고 SuperDex가 동봉한 예제를 그대로 돌린다.**
> API 시그니처를 추측해 만든 코드로 물리를 판정하면 실패 원인이 SuperDex인지 우리
> 코드인지 구분되지 않는다. 측정 스크립트는 이 단계에서 실제 시그니처를 확인한 뒤 쓴다.

**터미널 1 (PowerShell, **클론 루트**, `(.venv)` 활성 상태)**

SuperDex Lab이 asset을 찾는 환경변수를 이 세션에 내보낸다 (리포 루트에서 값을 읽어온다):

```powershell
$env:SUPERDEX_ASSETS_PATH = & python -c "import sys; sys.path.insert(0,'D:/workspace/KDT_1_AX_rtauto/config'); import rtauto_config as c; print(c.superdex_assets_path())"
echo $env:SUPERDEX_ASSETS_PATH
```

```bash
export SUPERDEX_ASSETS_PATH=$(python -c "import sys; sys.path.insert(0,'$HOME/workspace/KDT_1_AX_rtauto/config'); import rtauto_config as c; print(c.superdex_assets_path())")
echo $SUPERDEX_ASSETS_PATH
```

클론 루트로 이동해 예제를 순서대로 실행한다:

```powershell
cd D:/src/project_superdex
python superdex_robotics/examples/basic/example_bot_loading.py
python superdex_robotics/examples/control/example_osc_jsc_control.py
```

> README는 같은 것을 `uv run --no-project superdex_robotics/examples/control/example_osc_jsc_control.py`
> 로 적는다. venv를 활성화한 상태에서는 위처럼 `python <스크립트>`가 동등하다.
> 접촉이 많은 씬을 물리 검증용으로 돌릴 때 fp64가 필요하면 이 터미널에
> `$env:SUPERDEX_PRECISION = "double"`을 내보낸 뒤 실행한다(기본은 fp32).

`example_osc_jsc_control.py`는 FR3를 OSC로, DG5F를 JSC(target joint position → torque)로
제어하며 200 Hz로 스텝한다. `argparse`가 없어 인자를 받지 않는다. 종료는 `Ctrl+C`.

**정상 판정** — 예외 없이 시뮬레이션이 진행되고 콘솔에 스텝/시간 로그가 흐른다.
`asset not found` 계열 에러면 0-5의 `SUPERDEX_ASSETS_PATH`가 이 터미널에 실제로
내보내졌는지(`echo`) 다시 확인한다.

접촉을 눈으로 보려면 예제가 쓰는 `get_debug_server`에 `superdex_physics_debugger`를
붙인다 — 실행 방법은 0-4에서 확인한 콘솔 스크립트 이름으로 결정된다.

### 0-8. 스크립트 파지 테스트와 측정 (U6 해소)

0-7에서 확인한 실제 시그니처를 근거로 측정 스크립트를 `superdex/scripts/` 아래에 쓴다.
필요한 것:

- 손 단독 asset 로드(0-6에서 확정한 경로), 중력 ON, 큐브 rigid actor 배치
- JSC로 닫는 관절 자세 지령 → 일정 시간 유지 (**학습 아님**)
- 측정: **단일 env steps/sec**, **realtime factor**(200 Hz 기준), 접촉 jitter,
  물체 관통 여부

**판정 기록** — 측정값을 §10 진행 기록 표에 남긴다. 이 숫자가 §8의 throughput 계산과
§6 회귀 기준 3을 판정하는 근거다.

> `superdex/scripts/`와 `superdex/envs/`는 **아직 존재하지 않는다** — 0-8에서 처음
> 만들어진다. 문서에 적힌 경로가 실제로 없으면 새 PC 사용자가 막히므로(원칙 2), 이
> 문서는 그 사실을 여기서 명시한다.

---

## 12. 급한 시연이 생겼을 때 — 기존 환경 보전

**SuperDex PoC는 기존 텔레옵·학습 환경을 건드리지 않도록 설계했다.** 시연 요청이 갑자기
들어와도 되돌릴 것이 없다.

### mediapipe는 영향받지 않는다

이 저장소는 `mediapipe==0.10.11`에 고정돼 있고 그 버전은 **Python 3.12를 지원하지
않는다.** 상위 버전으로 올리면 protobuf 4.x가 `mlagents`와 충돌한다
(`vision/requirements-vision-mlagents.constraints.txt`가 이걸 막고 있다).

그래서 **venv를 올리지 않고 따로 만든다.** 기존 환경은 손대지 않는다.

| venv | Python | 용도 | PoC의 영향 |
|---|---|---|---|
| `vision/.vision/` | 3.10.11 | mediapipe 텔레옵, ML-Agents, UR RTDE 브리지 | **없음 — 재설치·업그레이드 안 함** |
| `superdex/.venv/` | 3.12 | SuperDex, RLlib, ONNX | 신규 추가만 |

`requirements-vision.txt`, `requirements-mlagents.txt`,
`vision/requirements-vision-mlagents.constraints.txt`는 **이 브랜치에서 한 줄도 바뀌지
않았다.** 3.10.11 인터프리터도 그대로 설치돼 있다 — 3.12를 **추가** 설치하는 것이다.

### 브랜치 전환

브랜치 `SuperDexTest`가 `main`에 대해 바꾼 것은 **문서 4개 + `config/rtauto_config.py`
추가분 + 신규 파일 2개**뿐이다. `vision/`, `unity/`, `arm/`, `training/scripts/`의
`.py`/`.cs`/`.unity`/`.prefab`은 **하나도 바뀌지 않았고**,
`config/rtauto_config.py`도 **삭제·변경 라인이 0인 순수 추가**다(기존 키 그대로).

즉 **`SuperDexTest`에서 그대로 시연해도 동작이 달라지지 않는다.** 그래도 최소 리스크로
가려면 시연 전에 `main`으로 옮긴다:

**터미널 1 (PowerShell, 리포 루트, 시연 준비)**

```powershell
git status --short
```

출력이 비어 있어야 한다(미커밋 변경 없음). 그 다음:

```powershell
git checkout main
```

시연이 끝나면 돌아온다:

```powershell
git checkout SuperDexTest
```

> Unity 에디터가 열려 있는 상태로 브랜치를 바꾸지 않는다 — 에디터를 먼저 닫고 전환한
> 뒤 다시 연다. 이 브랜치는 `unity/` 아래를 바꾸지 않으므로 실제로는 재임포트가 없지만,
> 습관을 여기서 만들어 두면 나중 게이트에서 Unity 파일을 건드릴 때 사고가 없다.

### ⚠️ 진짜 위험한 것은 브랜치가 아니라 `.env`다

`.env`는 **git 비추적**이라 브랜치를 바꿔도 따라 바뀌지 않는다. 게이트 0에서 여기에
값을 넣으므로, 기존 파이프라인에 영향을 주는 키를 구분해야 한다.

| `.env` 키 | 기존 파이프라인 영향 | 비고 |
|---|---|---|
| `RTAUTO_SUPERDEX_*` | **없음** | 기존 코드가 읽지 않는다. 넣어도 안전 |
| `RTAUTO_DG5F_SHORT` | **있음 — 위험** | 아래 참고 |
| `RTAUTO_PYTHON` | **있음 — 위험** | Unity "브리지 실행" 버튼이 이걸로 `arm/ur_rtde_bridge.py`를 띄운다. **절대 `superdex/.venv`로 바꾸지 않는다** — 3.12에는 `ur_rtde`가 없어 브리지가 죽는다 |

**`RTAUTO_DG5F_SHORT`** — 게이트 0-6(U1)에서 DG-5F-M의 손목 길이를 판정하는데, `short`로
드러나면 `dg5f_variant()`의 반환값이 `dg5f_right` → `dg5f_right_short`로 바뀌어
**기존 URDF·메시 선택 경로가 함께 달라진다.** 이건 오염이 아니라 "기존 설정이 틀렸다"는
발견이지만, **시연이 걸려 있는 동안 이 값을 뒤집지 않는다.**

- U1 판정 결과는 먼저 **이 문서 §10 진행 기록에만 적는다.**
- `.env`의 `RTAUTO_DG5F_SHORT` 변경은 시연이 끝난 뒤, 기존 파이프라인 회귀 확인
  (텔레옵 실행 + URDF 빌드)과 함께 별도로 처리한다.
- SuperDex 쪽에서 다른 변형을 먼저 써 봐야 하면 `.env`를 고치지 말고 그 세션에서만
  `superdex_hand_asset()`의 결과를 인자로 덮어쓴다.
