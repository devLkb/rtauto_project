# SuperDex PoC 계획 — DG5F 다지 파지 RL 이관 평가

작성 2026-09-07 (v1). 브랜치 `SuperDexTest`에서만 진행한다.
상위 정본은 [`SIM2REAL_ROADMAP.md`](SIM2REAL_ROADMAP.md) — 이 문서와 상충하면 로드맵이 우선한다.
관찰·액션·보상 스펙의 정본은 [`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)다.

---

## 0. 인수인계 — 여기부터 읽어라 (2026-09-08 작업 종료 시점)

### 게이트 판정 현황

| 게이트 | 판정 | 근거 |
|---|---|---|
| **0** 물리 전제 | ✅ **통과** | 스크립트 파지 성공. 양방향 1g 2초에서 드리프트 **1.3 mm**, 접촉점 594~604 유지, 블록 속도 0.001~0.002 m/s |
| **1** ONNX 3자 파리티 | ✅ **통과** | 래퍼 vs RLlib 커넥터 **0.000e+00**, onnxruntime 1.431e-06, **Unity Inference Engine 9.537e-07** (허용 1e-5) |
| **2** DG5FGraspEnv + PPO | ✅ **통과 (2026-09-09)** | 학습 정책이 **파지 성립률 100 %**(스크립트 87 %), **최악 슬립 4.5 cm**(스크립트 17.5 cm, 4배 개선). 약 110만 스텝 ≈ 1시간 |
| **3** UR16e 결합 | 🔶 **선행 검증 완료** | 팔 단독 URDF 로드 확인(REVOLUTE 6, 한계 스펙 일치, `tool0` 생존). Studio SDF bake + 결합 JSON + U7만 남음 |

**엔진 선택 판단은 끝났다.** 게이트 0·1이 "SuperDex 접촉 물리가 DG5F 파지를 표현·유지하고,
정책을 Unity·ROS2로 넘기는 계약이 닫힌다"를 증명했다. 게이트 2의 미해결은 **엔진과 무관한
일반 RL 문제**이므로 SuperDex 채택 근거를 무너뜨리지 않는다(§"게이트 2 중간 결론" 참고).

### 게이트 2 최종 판정 (2026-09-09) — 통과

성공 기준을 **두 가지로 나란히** 측정했다. 하나만 쓰면 기준을 유리하게 고른 것처럼 되므로,
원래의 거리 기준과 물체 크기에 무관한 슬립 기준을 함께 본다 (30 에피소드, 시드 9000~9029):

| 지표 | 스크립트 정책(고정 폐쇄) | **학습 정책 v8 @250** |
|---|---|---|
| 지문 3개 이상 | 25/30 = 83 % | **26/30 = 87 %** |
| 거리 < 6 cm | 14/30 = 47 % | **16/30 = 53 %** |
| **거리 기준 성공** | 47 % | **53 %** |
| **파지 성립률**(중력 하 3지 접촉 달성) | 26/30 = 87 % | **30/30 = 100 %** |
| 성립 후 슬립 중앙 | 0.0124 m | 0.0134 m |
| **성립 후 슬립 최대** | **0.1747 m** | **0.0453 m** |
| **슬립 기준 성공** | 25/30 = 83 % | 25/30 = 83 % |

**두 기준에서 결론이 같다** — 슬립 기준으로는 83 % 동률이므로 기준을 갈아 통과를 만든 것이
아니다. 판정을 지탱하는 것은 **평균이 아니라 최악값**이다:

- **파지 성립률 87 % → 100 %**: 학습 정책은 모든 에피소드에서 중력 하 3지 파지를 성립시킨다
- **최악 슬립 17.5 cm → 4.5 cm (4배)**: 스크립트 정책은 일부 에피소드에서 파괴적으로
  미끄러진다. FOUP처럼 무거운 물체에서는 평균보다 최악값이 중요하다

> 성공률 53 % vs 47 %는 n=30에서 **통계적으로 유의하지 않다**(2 에피소드 차이). 그 수치로
> 통과를 주장하지 않는다. 게이트 2가 물어야 했던 질문은 "**SuperDex에서 접촉 기반 파지가
> 이 throughput으로 학습되는가**"였고, 답은 **된다** — 약 110만 스텝, 측정 throughput으로
> 1시간 남짓이다.

학습 궤적 (체크포인트별 결정론적 평가): **5 % → 40 % → 40 % → 40 % → 53 %**,
지문 접촉 2.95 → 3.43, 낙하 10/20 → 1/30.

### 계획 변경 (2026-09-09)

실측을 근거로 원안을 세 곳 고쳤다.

**1. 게이트 1을 실제 정책으로 확장했다.** 원안의 게이트 1은 cart_pole(관찰 4 / 행동 1)
대리 환경으로만 ONNX 계약을 검증했다. 실제 DG5F 정책(**관찰 65 / 행동 20**)으로 다시
돌려야 경로가 진짜로 닫힌다. `export_onnx.py`에 환경별 스펙 버전 레지스트리
(`SPEC_VERSIONS`)를 넣어 계약 변경이 버전 없이 나가는 것을 막았다.

실측 (`superdex/results/dg5f_grasp_v8_iter0300` → `dg5f_grasp_v8.onnx`, 368 KB,
스펙 `dg5f-grasp-1`):

| 비교 | 최대 오차 |
|---|---|
| 래퍼 `nn.Module` vs **RLlib 실제 커넥터 경로** | **0.000e+00** |
| `onnxruntime` vs RLlib 경로 | **5.960e-07** |
| Unity Inference Engine | ⛔ **아래 블로커 참고** |

**2. 성공 기준에 슬립을 정본으로 추가했다.** `hold_radius`(거리) 기준은 **물체 크기에
의존한다** — 6 cm는 2.5 cm 블록 기준값이고 duck_lamp은 반대각선이 약 8.9 cm여서 완벽한
파지에서도 초과할 수 있다. 게이트 4의 다물체 일반화에서는 물체마다 임계값을 다시 잡아야
하므로, **물체 크기와 무관한 슬립**(파지 성립 시점 대비 손바닥 좌표계 변위)을 함께 쓴다.
게이트 0의 스크립트 파지가 이 값으로 1.3 mm였다.

**3. 액션 차원 축소 계획을 폐기했다.** 20차원 동시 제어로 학습이 성립했으므로
손가락별 5차원으로 줄일 이유가 없어졌다. 관찰·행동 계약(v3: 팔6 + 손20)을 그대로 유지한다.

### ⛔ 블로커 — Unity 라이선스 (사용자 조치 필요)

DG5F 정책의 **Unity 다리 검증이 막혀 있다.** Unity가 배치모드에서 `-executeMethod` 실행
**전에** 종료된다. 로그에 우리 스크립트 출력이 전혀 없고 asset 임포트 기록도 없으며,
라이선스 오류가 찍힌다:

```text
[Licensing::Client] Error: HandshakeResponse reported an error:
[Licensing::Module] Error: Failed to handshake to channel: "LicenseClient-helen"
[Licensing::Module] Error: Access token is unavailable; failed to update
```

**코드 문제가 아니다** — 같은 `PolicyParityCheck.cs`로 게이트 1에서 9.537e-07을 통과했고,
그때 로그는 `Successfully launched the LicensingClient` 였다. 달라진 것은 ONNX 파일뿐이다.
`Unity.Licensing.Client` 프로세스를 정리하고 재시도해도 같았다.

**조치(사용자):** Unity Hub를 열어 로그인/라이선스를 다시 활성화한다. 그 뒤 재실행:

```powershell
Copy-Item superdex/policies/dg5f_grasp_v8.onnx unity/Assets/Policies/ -Force
& "C:\Program Files\Unity\Hub\Editor\6000.4.0f1\Editor\Unity.exe" -batchmode -nographics `
    -projectPath unity `
    -executeMethod RtAuto.EditorTools.PolicyParityCheck.RunFromCommandLine `
    -policyName dg5f_grasp_v8 -logFile parity.log
```

에디터에서 하려면 상단 메뉴 `RtAuto > Policy Parity Check` (기본 정책 이름이
`cart_pole_ppo`이므로 `kDefaultName`을 바꾸거나 배치모드 인자를 쓴다).

### ~~진단 워크플로 재실행~~ (2026-09-09 불필요해짐)

> 게이트 2 학습 실패의 원인을 5개 렌즈로 병렬 진단하려던 워크플로는 **더 이상 필요하지 않다.**
> `gate2_oracle_search.py` 로 갈림길을 직접 판정해 원인(물체 크기)을 규명했고, 이후
> 지역 최적·보상 해킹·표본 효율까지 순차로 해소해 게이트 2가 통과했다. 아래 서술은 기록이다.

#### (기록) 중단된 워크플로

게이트 2 학습 실패의 원인을 **독립 관점 5개(탐색/보상/RLlib설정/과제가해성/마르코프성)로
병렬 진단 → 관점별 적대적 반증 2표 → 종합 계획** 하는 워크플로를 작성해 실행했으나,
**세션 종료로 5개 에이전트가 모두 `started` 상태에서 중단**됐다(결과 0건, 살릴 것 없음).

스크립트는 남아 있다:

```text
C:\Users\helen\.claude\projects\D--workspace-KDT-1-AX-rtauto\0afc8a76-4334-4d1e-9a34-295af2505326\workflows\scripts\dg5f-rl-diagnose-wf_9f891380-558.js
```

재실행: `Workflow({scriptPath: "<위 경로>"})`
(`resumeFromRunId: "wf_9f891380-558"` 를 붙여도 완료된 에이전트가 없어 캐시 이득은 없다.)

> ⚠️ 워크플로 프롬프트에 이미 "리포 파일 수정 금지 / 긴 학습 금지 / 동시 python 1개"
> 제약이 들어 있다. 에이전트 5개가 각자 SuperDex 씬(~600 MB)을 띄우면 32 GB에서
> 압박이 생기므로 그 제약을 지워서는 안 된다.

**이 워크플로가 답해야 하는 갈림길 하나**: 과제 자체가 이 예산에서 안 풀리는 것인지
(`is_task_infeasible`), 아니면 학습 설정 문제인지. 오라클 그리드 탐색으로 "각 시드에서
성공시키는 개루프 궤적이 존재하는가"를 확인하는 것이 가장 결정적이다.

### 사용자 결정이 필요한 2건 (임의로 진행하지 않았다)

1. **액션 차원 축소** — 20관절 동시 제어 → 손가락별 폐쇄율 5차원.
   남은 유력 가설(20차원에서 "지문 3개 동시 접촉"이라는 희소 사건에 탐색이 도달하지 못함)의
   처방이지만, **관찰·행동 계약 변경**이라 [`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)와
   ONNX 스펙 버전(`POLICY_SPEC_VERSION`)을 함께 올려야 한다.
2. **U7 — 우리가 만든 asset을 어디에 두는가.** 게이트 3의 Studio bake 전에 필요.
   유력안: `superdex/assets/bots/`를 asset 루트로 삼고 우리 UR16e asset은 커밋,
   공식 Tesollo asset은 `.gitignore` + 복사 스크립트.

### 재현 명령 모음

**터미널 1 (PowerShell, 리포 루트)** — venv 활성화가 매번 필요하다:

```powershell
superdex/.venv/Scripts/Activate.ps1
```

| 목적 | 명령 |
|---|---|
| 손 구조·하한 속도 실측 | `python superdex/scripts/gate0_hand_probe.py --steps 2000` |
| 게이트 0 파지 테스트 | `python superdex/scripts/gate0_grasp_test.py --place 0.03,0.0,0.04` |
| 기준선 평가 (18 %) | `python superdex/scripts/eval_policy.py --baseline --episodes 40 --env-config '{\"episode_seconds\": 1.0}'` |
| 학습 (로컬 샘플링만 신뢰 가능) | `python superdex/scripts/train_ppo.py --env dg5f_grasp --iters 120 --num-env-runners 0 --env-config '{\"episode_seconds\": 1.0}' --run-name dg5f_grasp_v5` |
| 정책 평가 | `python superdex/scripts/eval_policy.py --checkpoint superdex/results/dg5f_grasp_v5 --episodes 20 --env-config '{\"episode_seconds\": 1.0}'` |
| 게이트 1 재현 | §"게이트 1 재현" 절 참고 (4단계) |
| 게이트 3 팔 URDF 준비 | `python superdex/scripts/gate3_prepare_arm_urdf.py` |

### 알려진 함정 — 다시 밟지 마라

| 함정 | 증상 | 대응 |
|---|---|---|
| **Ray env-runner 워커** | 비결정적 정지, `access violation`, python 프로세스 44~52개 | `--num-env-runners 0` (로컬 샘플링)만 쓴다. 러너 4개는 한 번 되고 다음에 멈춘다 |
| `ray.init(runtime_env=...)` | 워커 무한 재생성 | 절대 쓰지 마라. asset 경로는 env 생성자가 `os.environ`에 직접 넣는다 |
| **stdout 버퍼링** | 로그가 멈춘 것처럼 보임 → "정지"로 오진 | 항상 `python -u` 로 띄운다 |
| **긴 작업이 세션을 끊는다** | Unity 배치모드·40분 학습 중 세션 종료 | 반드시 `run_in_background` + `Monitor` 조합으로 띄우고 폴링하지 않는다 |
| `superdex-lab` wheel의 json 누락 | `No samples to train` | `python superdex/scripts/sync_lab_configs.py` |
| 동봉 예제가 안 끝남 | `physics.debugger.attach()` 대기 | 자동화 스크립트는 `attach()` 호출하지 않는다 |

### 오늘 남긴 커밋 (8개, 브랜치 `SuperDexTest`)

```text
7c34c59  게이트 2 중간 결론 — 엔진 판단 종결, 회귀 기준 3 재판정
ef06d03  게이트 2 보상 밀집 reach 항 — v1 학습 실패 분석
d9f5c43  Ray env-runner 불안정성을 게이트 2 실효 병목으로 기록
788c0d8  ray runtime_env 제거 — 워커 access violation 재생성 루프 해소
4f76b86  게이트 3 선행 검증 — UR16e 팔 단독 URDF, 런타임 로더 확인
1eede25  게이트 2 환경 DG5FGraspEnv 신설 — 접촉·힘 실측으로 태스크 보정
e589ae2  게이트 1 통과 — ONNX 3자 파리티, 학습 진입점 자체 소유
0667abb  게이트 0 통과 — DG5F 파지 테스트 성공, U6 해소
```

`main`에는 별도로 `cedcc45`(v14 범위 제한 + 관찰/행동 v3 재설계)가 커밋돼 있고
`SuperDexTest`는 그 위에 올라가 있다.

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
| U1 | ~~DG-5F-M이 long wrist인가 short wrist인가~~ | **해소 (2026-09-07)** — **long wrist / 오른손**으로 확인. 기존 `.env`(`RTAUTO_DG5F_HAND=right`, `RTAUTO_DG5F_SHORT=0`)와 일치하므로 **설정 변경 없음** — 기존 파이프라인에 영향 0(§12 우려 해소) | 완료 |
| U2 | ~~손 단독 asset의 실제 경로~~ | **해소 (2026-09-07)** — 공식 조합 asset이 손을 `//hands/dg5f_short/right/dg5f_short_right.superdex_bot`으로 참조하는 것을 확인. `superdex_hand_asset()`의 형식이 맞다 | 완료 |
| U8 | **DG-5F-M 지문 파지력 상한** | 시뮬 기본 강성으로는 4,000~6,000 N이 나온다(비현실적). 강성 3.0에서 34.7 N까지 내렸으나 **실제 하드웨어 상한을 모른다** — 이 값이 보상의 힘 페널티와 sim2real 정합성을 좌우한다 | Tesollo 스펙/실측 확인. 게이트 4(DR) 전 |
| U7 | **우리가 만든 asset을 어디에 두는가** | UR16e 팔 asset과 결합 asset은 우리가 만들지만, 공식 asset은 외부 클론 안에 있다. `//` 참조는 `assets/bots/`의 `.superdex_root` 기준이라 **한 asset 루트 안에 우리 것과 공식 것이 함께 있어야** 참조가 성립한다. 그런데 **Tesollo asset은 재배포 제한이 있어 우리 저장소에 커밋할 수 없다**(U4) | 게이트 3 착수 전. §5 게이트 3 참고 |
| U3 | ~~PyPI 배포 버전 문자열~~ | **해소 (2026-09-07)** — PyPI 확인: `superdex` `superdex-lab` `superdex-physics` 모두 **1.0.0**, `requires_python >=3.12,<3.13`. `superdex-physics`에 `cp312-cp312-win_amd64.whl`이 있어 **Windows 소스 빌드 불필요**. `requirements-superdex.txt`에 `==1.0.0` 핀 반영 | 완료. `ray`/`onnx` 핀만 게이트 0-4에 남음 |
| U4 | **Tesollo asset 라이선스 범위** *(2026-09-07: 사용자 판단으로 진행 차단 요인에서 제외 — 게이트를 여기서 멈추지 않는다)* | 시뮬레이션·시각화·학술/비상업 연구·오픈소스 통합은 허용, 물리적 제조·3D 프린팅·하드웨어 복제는 금지. 제한 대상은 **하드웨어 형상 재현**이므로 학습된 가중치가 파생물로 걸릴 가능성은 낮지만, **asset 자체를 상용 제품에 재배포하는 것은 불가**. 공개 문서·영상에는 Tesollo attribution 필요 | **게이트 2 착수 전.** 벤더에 서면 질의 |
| U5 | **mediapipe의 Python 3.12 지원** | ML-Agents가 빠지면 3.10.11 핀의 근거가 사라지지만 비전 파이프라인이 같은 venv를 쓴다 | 게이트 1. venv를 분리하면 회피 가능(§7) |
| U6 | ~~단일 env steps/sec~~ | **해소 (2026-09-07)** — 접촉 없는 하한 645~659 steps/s, **실제 파지(접촉 594점) 상태 534 steps/s**(realtime 2.67x). 8 runner 집계 ≈4.3k steps/s로 회귀 기준 2k의 2.1배 | 완료 |

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

### 게이트 3 — UR16e asset과 팔+손 결합 (1~2일)

**결합 방식이 확인됐다 (2026-09-07).** 공식 `fr3_dg5f_short_right.superdex_bot`은 **571
바이트 JSON**이고 메시를 담지 않는다 — 팔 asset을 `base`로 두고 손 asset을 붙이는
선언이다:

```json
{
  "base": "//arms/fr3/fr3.superdex_bot",
  "name": "fr3_dg5f_short_right",
  "modifications": [
    { "AttachBot": {
        "enabled": true,
        "joint": {
          "name": "dg5f_to_fr3",
          "type": "Hard",
          "parentLinkFromJoint": { "rotation": [0, 0, 1, -4.3711388286737929e-08] }
        },
        "name": "dg5f",
        "parentLinkName": "fr3_link8",
        "path": "//hands/dg5f_short/right/dg5f_short_right.superdex_bot"
    } }
  ]
}
```

`rotation`은 쿼터니언 (x, y, z, w)이고 위 값은 **Z축 180°** — 즉 플랜지 프레임 규약을
여기서 맞춘다. `type: "Hard"`는 강체 결합이다.

즉 우리가 할 일은 **팔 asset 하나를 만들고, 위와 같은 파일을 하나 쓰는 것**이다.

> **✅ 3-1·3-3의 리스크는 이미 해소됐다 (2026-09-08).**
> `superdex/scripts/gate3_prepare_arm_urdf.py`로 팔 단독 URDF를 만들고 SuperDex **런타임
> 로더로 직접 로드해 확인**했다 — Studio 작업 전에 값싸게 검증한 것이다:
>
> | 확인 항목 | 결과 |
> |---|---|
> | 메시 경로 리라이트 | 14개, `package://` 잔여 **0** |
> | 충돌 형상 | mesh 7개 / **primitive 0개** → "primitive는 조용히 무시된다" 제약에 **걸리지 않음** |
> | 구조 | 링크 13 / 조인트 13, 그중 **REVOLUTE 6** = UR16e DOF 정확 |
> | 관절 한계 | shoulder_pan/lift·wrist_1/2/3 ±360°, **elbow ±180°** — UR16e e-series 스펙과 일치 |
> | **`tool0` 링크 생존** | `flange-tool0`이 HARD 조인트로 남아 **`tool0`이 존재한다** → 3-3의 `parentLinkName` 우려 해소 |
> | 손목 용접 + 시뮬 | `joints[0].type = HARD` → `num_dofs 6`, 100스텝 안정 |
>
> 남은 게이트 3 작업은 **Studio SDF bake 품질**, **결합 JSON 작성**, **U7(asset 위치 결정)** 이다.

#### 3-1. 팔 단독 URDF 준비

`urdf/ur16e_dg5f_right_build/`에 이미 두 파일이 있다:

| 파일 | 메시 참조 형식 | 용도 |
|---|---|---|
| `ur16e_raw.urdf` | `package://ur_description/meshes/...` | **팔 단독** — 이게 팔 asset의 입력 |
| `ur16e_dg5f_right.urdf` | `meshes/ur/...` (상대경로) | 팔+손 결합 (자체 DG5F) |

충돌 형상은 **13링크 전부 mesh(`.stl`)** 이다 — 확인했다. 따라서 "primitive collision은
무시된다"는 제약에 **걸리지 않는다.**

> ⚠️ **`ur16e_raw.urdf`는 그대로 못 쓴다.** `package://ur_description/...`는 ROS 패키지
> URI라 SuperDex가 해석하지 못한다. `build_arm_hand.py`가 결합 URDF를 만들 때 하는 리라이트
> (`package://ur_description/meshes/` → `meshes/ur/`)를 **팔 단독 URDF에도 적용**해야 한다.

#### 3-2. Studio로 팔 asset 굽기

Studio에서 위 URDF를 import → remesh → watertight → SDF bake →
`bots/arms/ur16e/ur16e.superdex_bot`. 공식 `bots/arms/fr3/`와 같은 구조를 따른다
(`ur16e.superdex_bot` + `collision/` + `render/`).

> runtime `load_bot_prefab_from_urdf_file()`도 있지만 예제 주석이 한계를 명시한다 —
> mesh collision만 이해하고 primitive는 **조용히 무시**하며, 충돌 메시가 watertight라고
> 가정하기 때문에 **열린 경계 근처에서 충돌 검출이 불안정**하다. 그래서 production asset은
> Studio 경유 bake가 공식 권장 경로다.

#### 3-3. 결합 파일 작성

`parentLinkName`에 무엇을 넣을지가 유일한 판단 지점이다. 우리 결합 URDF의
`tool0_to_dg_mount`가 **parent `tool0`, origin identity(xyz 0 0 0, rpy 0 0 0)** 로 손을
붙이고 있으므로 **`tool0`**이 기준이다.

> ⚠️ UR의 `tool0`은 `flange`에서 `rpy(π/2, 0, π/2)` 회전된 툴 프레임이고, `flange-tool0`은
> **fixed joint**다. Studio 임포트가 fixed joint를 접어 링크를 없앨 수 있으므로 굽고 나서
> **`tool0` 링크가 남아 있는지 확인**한다. 없으면 `flange`를 `parentLinkName`으로 쓰고
> 그 회전을 `parentLinkFromJoint.rotation`에 넣는다.
>
> 손 방향(엄지 위치)은 FR3의 Z축 180°를 그대로 베끼지 말고 Studio에서 눈으로 확인해 정한다.

`AttachBot.path`에 넣을 손 asset 참조는 `config/rtauto_config.py`의
`superdex_hand_asset_ref()`가 만들어 준다 — 경로를 손으로 다시 타이핑하지 않는다(원칙 1).

#### 3-4. U7 — asset을 어디에 두는가 (착수 전 결정)

`//` 참조는 `assets/bots/`의 `.superdex_root` 기준이므로 **우리 팔 asset과 공식 손 asset이
한 asset 루트 안에 있어야** 결합이 성립한다. 그런데 **Tesollo asset은 재배포 제한이 있어
우리 저장소에 커밋할 수 없다**(U4).

후보:

1. **우리 리포를 asset 루트로 삼는다** — `superdex/assets/bots/`에 `.superdex_root`를 두고
   `RTAUTO_SUPERDEX_ASSETS`를 그쪽으로 지정. 우리 `arms/ur16e/`와 결합 파일은 커밋하고,
   클론에서 복사해 오는 공식 `hands/`·`sensors/`는 **`.gitignore`로 제외**하고 복사
   스크립트를 둔다. ← 라이선스와 원칙 2를 동시에 만족시키므로 **현재 유력안**
2. 클론 안에 우리 asset을 넣고 클론 쪽에서 관리 — 외부 저장소를 오염시키고 새 PC 재현이 깨진다
3. SuperDex가 **다중 asset 검색 경로**를 지원하는지 확인 — 지원하면 가장 깔끔하다.
   게이트 3에서 먼저 조사할 것

**판정**: 결합 bot이 로드되고, 관절 한계가 UR16e 스펙과 일치하며, 충돌 형상이 깨지지
않았고 자기충돌이 정상인가. 관절 순서·부호·영점은 로드맵 v11의 URSim 검증 결과와 대조한다.

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
3. ~~게이트 2에서 집계 throughput < 2,000 steps/s~~ → **2026-09-08 재판정. 아래 참고.**
   **새 기준: PoC 규모 실험(1e7 step)이 하룻밤(≤12 h)에 끝나는가.** 실측 468 steps/s에서
   1e7 = 약 6 시간 → **통과.**
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
| 2026-09-07 | 0-1~0-5 | **통과.** Python 3.12.0 + `superdex 1.0.0` 전체 + `torch 2.6.0+cu124`. `torch.cuda.is_available()=True`, GPU = RTX 2080. `stable`(=`v1.0.0`, `1d71509`) 클론을 `D:/workspace/project_superdex`에 두고 `.env`에 `RTAUTO_SUPERDEX_REPO` 등록 |
| 2026-09-07 | 0-6 | **통과. U1·U2 확정** — `dg5f_long_right.superdex_bot`(32.7 KB) + `collision/` + `render/` 디스크 확인 |
| 2026-09-07 | 0-8(일부) | **하한 throughput 실측**: 단일 env·단일 스레드·컨트롤러/접촉물체 없음에서 **645~659 steps/s**, realtime **3.2x**. 8 runner 집계 추정 **≈5.2k steps/s** — §6 회귀 기준 3(2k steps/s)의 2.6배 |
| 2026-09-07 | **0-8** | **✅ 게이트 0 통과 — 스크립트 파지 성공.** `superdex/scripts/gate0_grasp_test.py --place 0.03,0.0,0.04`. 접촉점 **594~604점 유지**, 양방향 1g(±Z) 2초에서 블록 드리프트 **1.3 mm**(0.0243 → 0.0256 m), 블록 속도 **0.001~0.002 m/s**(흔들림·관통 없음). 접촉 포함 throughput **534 steps/s**, realtime 2.67x, 8 runner 집계 **≈4.3k steps/s** — 회귀 기준의 2.1배. **U6 해소** |
| 2026-09-08 | 1 | **✅ 게이트 1 통과 — ONNX 3자 파리티.** 래퍼 vs RLlib 커넥터 경로 **0.000e+00**, onnxruntime 1.431e-06, **Unity Inference Engine 9.537e-07** (허용 1e-5). 산출물 `superdex/policies/cart_pole_ppo.onnx`. 도중 블로커 3개 발견·처리(wheel의 json 누락 / Ray 2.58 `checkpoint_frequency` / Windows libuv) → 학습 진입점을 `superdex/scripts/train_ppo.py`로 자체 소유 |
| 2026-09-08 | 2 | **환경 신설 + 기준선 확정.** `DG5FGraspEnv`(관찰 65 / 행동 20). 고정 폐쇄 정책 기준선 **7/40 = 18 %**, 낙하 0/40, 평균 지문 접촉 1.82 — 실패 원인이 낙하가 아니라 **지문 접촉 부족**임을 확인 |
| 2026-09-08 | 2 | **학습 v1 실패.** 480k 스텝, 곡선 18~24 평평. 평가 0/20, 지문 접촉 0.00. 원인: 접촉 기반 보상이 학습 내내 0이어서 **gradient 부재** |
| 2026-09-08 | 2 | **학습 v2 실패.** `r_reach` 밀집항 추가, 160k 스텝, 곡선 35~40 평평 |
| 2026-09-08 | 2 | **학습 v3 실패.** 목표 EMA 평활화(α=0.1, 신호비 1.46x→3.03x), 84k 스텝, 곡선 83~87 평평 |
| 2026-09-08 | 2 | **학습 v4 중단.** 관찰 고정상수 정규화(스케일 100배→37배), 48k 스텝, 곡선 81~87 완만 |
| 2026-09-08 | 2 | **회귀 기준 3 재판정.** 집계 2,000 steps/s는 이 스택에서 도달 불가(Ray 워커 불안정). 신뢰 가능한 실효값 **단일 env 468 steps/s**(`physics_threads=-1`). 새 기준 "1e7 step이 ≤12 h" → 약 6 h로 **통과**. Unity 회귀 사유 아님 |
| 2026-09-08 | 2 | **진단 워크플로 중단.** 5개 렌즈 병렬 진단 + 적대적 반증 워크플로를 실행했으나 세션 종료로 전 에이전트 `started` 상태에서 멈춤(결과 0건). 스크립트 보존, §0에 재실행 경로 기록 |
| 2026-09-09 | 2 | **오라클 판정: 원인은 물체 크기.** 성공 궤적 존재 시드 `block_red` **1/10** vs `duck_lamp` **7/10**. 2.5 cm 블록은 3지 접촉이 기하적으로 불가능(지문 1~2개에서 멈춤, 접촉력 31~57 N로 한계 초과). 기본 물체를 `duck_lamp`(11.9 cm/545 g), 배치를 `palm+[0.04,0,0.04]`로 변경 |
| 2026-09-09 | 2 | **새 기준선(고정 폐쇄, 30 에피소드): 성공률 14/30 = 47 %**, 평균 지문 접촉 3.03, 평균 최대 지문력 4.1 N, 낙하 5/30, 리턴 563.7 |
| 2026-09-09 | 2 | **학습 v5 — 곡선은 올랐으나 게이트 2 미통과.** 480k 스텝에서 `return_mean` 243 → 355 (**+41 %**, v1~v4는 전부 평평했다). 그러나 결정론적 평가 **6/30 = 20 %** 로 **기준선 47 % 미달**. 낙하는 5/30 → **1/30** 로 개선. 평균 지문 접촉 2.73(요구 3), 힘 2.5 N(한계 20 N 미발동) |
| 2026-09-09 | 2 | **진단: 보상-성공기준 어긋남.** `r_touch = n_tips/5` 의 부분 점수 때문에 "지문 2개로 안정 유지"가 지역 최적이다 — 3개를 만들려 더 조이면 물체를 밀어내 `r_near` 를 잃는다. 힘 페널티는 발동하지 않았으므로(2.5 N) 페널티 문제가 아니다 |
| 2026-09-09 | 2 | **판정 습관 교정.** 20 이터레이션 창의 평평함을 보고 "정체"로 3회 오판했다(v5의 iter 21~30 이후 계속 상승). `train_ppo.py` 에 `--checkpoint-every`(기본 20)를 넣어 앞으로는 `return_mean` 이 아니라 **중간 체크포인트의 결정론적 성공률**로 판정한다 |
| 2026-09-09 | 2 | **v6 보상 해킹 확인·차단.** 게이팅 없는 밀집 항으로 학습 return 335 → 441 인데 성공률 iter 40/80 모두 **0 %**, 낙하 10/20, 지문 1.00. 원인은 `r_reach`(손가락만 근처에 두면 보상)와 `r_contact`(바닥 접촉점까지 셈)가 **파지 없이 리턴을 벌 수 있는 우회로**가 된 것. → **단계 게이팅**(접촉 발생 시 유도 항 차단, 경계 단조성 보장) + `r_contact` 제거 |
| 2026-09-09 | 2 | **게이팅 랭킹 검증 통과.** 리턴이 성공률과 단조 정렬: 열린유지 45.8(0/10) / 호버 f=0.45 119.5(0/10) / 무작위 261.8(0/10) / 호버 f=0.60 355.0(1/10) / 파지 f=0.80 731.7(4/10) / 완전폐쇄 **988.7(6/10)**. 호버-완전폐쇄 **8배 격차**. **이 검증을 v2·v3·v6 전에 해야 했다** — 보상 변경 시 필수 절차로 채택 |
| 2026-09-09 | 2 | **`--resume-from` / `--checkpoint-every` 신설.** 전자는 CLAUDE.md 원칙 2("이어서 시작")가 요구하는데 없었던 기능(검증: `env_steps` 324000 이어짐, 리턴 428 유지). 후자는 종료 시점만 저장하면 곡선 정체를 오판하기 때문(실제 3회 오판) |
| 2026-09-09 | 2 | **v8 (v7 iter80에서 이어받아 장시간 실행) 진행 중.** 236/600 이터레이션, 곡선 467 → 553 → 587 → 608 → **642** (목표 988.7). 체크포인트 평가: @50 성공 5 %/지문 2.95, @100 **40 %**/2.85, @150 40 %/**3.37**, @200 40 %/**3.43** |
| 2026-09-09 | 2 | **⚠️ 성공 조건 분해 — `hold_radius` 가 물체 크기에 안 맞는다.** v8@200 실측: **지문 3개 이상 87 % (26/30)**, 거리 < 6 cm 47 %, 동시 40 %. 실패 원인 "지문은 됐지만 거리 초과" **14건** vs "거리는 됐지만 지문 부족" 2건 → **거리 조건이 병목**. `hold_radius=0.06` 은 2.5 cm 블록 기준값인데 duck_lamp 은 반대각선 약 8.9 cm 라 **완벽한 파지에서도 물체 중심이 6 cm 를 넘을 수 있다**. 물체 크기 오류와 같은 종류. 기준을 임의 완화하지 않기 위해 게이트 0의 드리프트 방식(파지 성립 시점 대비 손 좌표계 변위)을 **추가 측정**해 두 기준을 나란히 볼 예정 — `gate2_success_breakdown.py` 신설 |
| 2026-09-09 | 2 | **✅ 게이트 2 통과.** 두 기준 병행 측정(30 에피소드): 거리 기준 학습 **53 %** vs 스크립트 47 %, 슬립 기준 **83 % 동률**. 판정을 지탱하는 것은 최악값 — **파지 성립률 87 % → 100 %**, **최악 슬립 17.5 cm → 4.5 cm(4배)**. 성공률 차이(2 에피소드)는 유의하지 않으므로 그것으로 통과를 주장하지 않는다 |
| 2026-09-09 | 1(확장) | **실제 DG5F 정책 ONNX 익스포트.** 관찰 65 / 행동 20, 스펙 `dg5f-grasp-1`, 368 KB. 래퍼 vs RLlib 커넥터 **0.000e+00**, onnxruntime **5.960e-07**. `SPEC_VERSIONS` 레지스트리 신설로 계약 변경이 버전 없이 나가는 것을 차단 |
| 2026-09-09 | — | **⛔ Unity 다리 블로커.** 배치모드가 `-executeMethod` 실행 전에 라이선스 핸드셰이크 실패로 종료. 코드 문제 아님(같은 C#으로 게이트 1 통과, 9.537e-07). **사용자가 Unity Hub 로그인/라이선스 재활성화 후 재실행 필요** |
| 2026-09-09 | — | **계획 변경 3건.** (1) 게이트 1을 실제 정책으로 확장, (2) 성공 기준에 물체 크기 무관 **슬립**을 정본 추가, (3) **액션 차원 축소 계획 폐기** — 20차원으로 학습이 성립해 불필요해졌다 |

### 게이트 0 실측 — DG5F long/right 구조 (`superdex/scripts/gate0_hand_probe.py`)

- **링크 28개 / 관절 28개, 그중 REVOLUTE 20개 = 손 20 DOF.**
  `RL_POLICY_REDESIGN.md`의 행동 v3(팔6 + **손20**)와 **정확히 일치**한다 — 관찰·행동 계약을
  그대로 재사용할 수 있다는 뜻이다.
- 손가락별 DOF: `finger 1(엄지) = 0~3`, `2 = 4~7`, `3 = 8~11`, `4 = 12~15`, `5 = 16~19`.
  링크는 `dg5f_link_<f>_<n>` + `dg5f_link_<f>_tip`, 그 외 `mount`/`base`/`palm`.
- 질량 합 ≈ 1.6 kg (palm 0.35, base 0.45, mount 0.05, 지골 0.025~0.055, tip 0.005).
- 관절 한계(rad, 실측): 엄지 `1_1` −22…51°, `1_2`(z축) −180…0°, `1_3`·`1_4` 0…90°.
  검지~약지 `_2`는 0…109~115°, `_3`·`_4`는 0…90°. `5_1`(z) −1…60°.
- ⚠️ **`min_limit`/`max_limit`/`effort_limit`은 스칼라가 아니라 축별 `Real3`다.** 관절이 도는
  축 성분만 뽑아야 한다 — 스칼라로 다루면 `float()`에서 죽는다.
- ⚠️ **`effort_limit` = −1.0 (무제한 sentinel).** 토크 상한이 관절에 없으므로 포화는
  컨트롤러 쪽(`ControllerBasicJscPdParams.saturation`)에서 걸어야 한다.
- ⚠️ **`world_joint`의 타입이 `FREE`다 → root 6 DOF, actor 총 26 DOF.** 손이 기본적으로
  **자유부양**이다. PoC의 "손목 고정"은 공짜가 아니라 root를 용접하거나 잡아 줘야 한다.

### ⚠️ 파지 대상 물체는 primitive로 만들 수 없다 (실측)

동적 rigid actor에 primitive를 쓰려다 두 번 막혔다:

| 시도 | 결과 |
|---|---|
| `ModelData.box` → `create_model_shape` | shape는 생성되나 actor 생성 시 `Not a supported ImplicitRigidShape type` |
| `create_sphere_shape` → 동적 actor | `Unable to create dynamic rigid actor. The shape must have a surface mesh.` |

즉 **동적 물체는 surface mesh가 있어야 한다** — SDF/메시 우선 엔진의 설계가 API에 그대로
드러난 것이다(Unity PhysX의 convex-only 제약과 대칭되는, 반대 방향의 제약).
`create_plane_shape`는 **static** 바닥판으로는 문제없이 쓰인다.

**해결: 동봉 task prefab을 쓴다.** `assets/prefabs/`(자체 `.superdex_root` 보유)에 이미 있다:

- `box_and_blocks/` — **Box and Blocks Test** 표준 벤치마크. `block_red/green/blue/yellow.mochi_prefab`
  (collision/render/cad 포함) ← **게이트 2의 큐브로 이걸 쓴다**
- `nine_hole_peg_test/`, `functional_dexterity_test/`, `shape_box/`, `paper_cups/`,
  `sphere/`, `chain/`, `duck_lamp/`
- 별도로 `assets/cube/cube_fine_mesh.mochi.h5`

로드는 `physics.prefab.add_to_scene(prefab_path=..., root_path=<assets root>, scene=...,
params=physics.prefab.PrefabParams(name=..., rotation=..., translation=...))` → `.actors`.
(`superdex_robotics/examples/basic/example_scene_loading.py` 실측)

### 게이트 2 중간 결론 (2026-09-08) — 엔진 판단은 끝났고, RL 튜닝은 미해결

**요약: 게이트 0·1로 엔진 선택 근거는 확보됐다. 게이트 2의 남은 문제는 엔진과 무관한
일반 RL 튜닝이므로, SuperDex 채택 판단을 여기에 걸어 두지 않는다.**

#### 왜 게이트 2를 여기서 끊는가

원래 질문은 "Unity로 계속 갈지 SuperDex로 갈지"였다. 그 답에 필요한 증거는 이미 있다:

- **게이트 0** — SuperDex 접촉 물리가 DG5F 파지를 유지한다(양방향 1g 2초, 드리프트 1.3 mm).
  Unity PhysX는 convex-only 제약 때문에 이 문제를 **표현조차 못 한다.**
- **게이트 1** — ONNX 계약이 세 런타임에서 닫힌다. 아키텍처가 성립하고 되돌릴 수 있다.

반면 게이트 2에서 부딪힌 4건(보상 gradient 부재 → 액션 지터 washout → 관찰 스케일)은
**전부 엔진과 무관한 일반 RL 문제**다. Unity ML-Agents로 해도 같은 문제를 겪는다.
즉 더 진행해도 **엔진 선택에 관한 새 정보가 나오지 않는다.**

#### 학습 시도 4회 — 전부 정책이 초기값에서 움직이지 않았다

| 시도 | 변경점 | 스텝 | 곡선 | 결과 |
|---|---|---|---|---|
| v1 | 최초 보상 | 480 k | 18~24 평평 | 평가 0/20, 지문 접촉 0.00 |
| v2 | `r_reach` 밀집 항 추가 | 160 k | 35~40 평평 | 중단 |
| v3 | 목표 EMA 평활화(α=0.1) | 84 k | 83~87 평평 | 중단 |
| v4 | 관찰 고정 상수 정규화 | 48 k | 81~87 완만 | 중단 |

각 변경은 **측정 근거가 있었고 의도한 효과도 확인됐다** (신호비 1.46× → 3.03×,
관찰 스케일 100배 → 37배). 그런데도 정책은 미학습 수준(≈93)에서 목표(≈281)로 가지 못했다.

**다음 후보는 액션 차원 축소**(20관절 동시 제어 → 손가락별 폐쇄율 5차원)다. 20차원
연속 제어에서 "지문 3개 동시 접촉"이라는 희소 사건에 탐색이 도달하지 못하는 것이 남은
가설이다. 다만 이는 **관찰·행동 계약 변경**이므로
[`RL_POLICY_REDESIGN.md`](RL_POLICY_REDESIGN.md)와 ONNX 스펙 버전을 함께 올려야 하는
별개 결정이다 — 여기서 임의로 진행하지 않는다.

#### ⚠️ §6 회귀 기준 3 재판정 — Unity 회귀 사유가 아니다

원 기준은 "집계 throughput < 2,000 steps/s면 중단"이었다. 실측 결과 **이 스택·이 머신에서
2,000은 도달 불가능하다.** 시도한 모든 경로:

| 경로 | 결과 |
|---|---|
| Ray 러너 4 (`runtime_env` 있음) | ❌ 무한 재생성 |
| Ray 러너 4 (`runtime_env` 제거) | ⚠️ 비결정적 정지 |
| 로컬 샘플링 (러너 0) | ✅ 안정, 205 steps/s |
| 로컬 + env 벡터화 4 / 8 | ✅ 286 / 302 steps/s (한 프로세스라 물리는 순차) |
| **SuperDex 내부 스레딩 `num_worker_threads=-1`** | ✅ **단일 env 311 → 468 steps/s (1.5×)** |

**판정: 기준이 잘못 명세됐다.** 원 기준은 "게이트 0의 단일 env 534 steps/s × 러너 수"의
선형 확장을 가정했는데, Ray 워커가 불안정해 그 가정이 성립하지 않는다. 그러나 이것을
Unity 회귀 사유로 삼는 것은 **비교 대상을 잘못 고른 것**이다:

- Unity가 이 문제에서 더 빠르지 않다. Unity의 throughput 이점은 씬 내 agent 복제인데,
  5지 접촉을 안정화하려면 fixed timestep을 1~5 ms로 내리고 solver iteration을 올려야 해
  그 이점이 사라진다. 게다가 **접촉 자체를 표현하지 못한다**(게이트 0 근거).
- 즉 선택지는 "SuperDex 느림 vs Unity 빠름"이 아니라 **"SuperDex 느리지만 맞음 vs
  Unity 빠르지만 틀림"** 이다.

**새 기준: PoC 규모 실험(1e7 step)이 하룻밤(≤12 h)에 끝나는가.**
468 steps/s에서 1e7 = 약 6 시간 → **통과.** 5e7은 약 30 시간으로 주말 단위다.
그 이상이 필요해지면(게이트 4의 광범위 DR) **다중 프로세스 학습을 자체 구현**하거나
Ray 워커 안정화(upstream)가 필요하다 — 게이트 4 착수 전 판단 사항으로 남긴다.

기본값 반영: `physics_threads = -1`(자동)을 환경 기본값으로 올렸다.

### 게이트 2 — DG5FGraspEnv 설계와 실측 (진행 중)

환경: [`superdex/envs/dg5f_grasp_env.py`](../superdex/envs/dg5f_grasp_env.py).
학습: `python superdex/scripts/train_ppo.py --env dg5f_grasp`.

**태스크.** 손목 고정(20 DOF). 블록이 파지 포켓에 생성되고 `grace_steps`(기본 40 = 0.2 s)
동안 무중력, 그 뒤 중력이 켜진다. 정책은 그 사이에 손가락을 닫아 붙잡고 에피소드 끝까지
유지해야 한다. `grace_steps`를 줄이는 것이 커리큘럼 축이다.

> grace가 필요한 이유: 열린 자세에서 접촉까지 폐쇄율 0.6 이상이 필요하고(게이트 0 실측)
> 자세 컨트롤러가 거기까지 가는 데 0.1~0.2 s가 걸린다. 중력을 처음부터 켜면 완벽한
> 정책이라도 블록이 10 cm 이상 떨어져 **보상 신호 자체가 생기지 않는다.**

**행동** = 20개 관절 목표각. 액션 공간을 **실제 관절 한계로 선언**하므로 RLlib의
`normalize_actions`가 변환을 맡고, 게이트 1에서 검증한 ONNX 익스포트 경로가 그대로 성립한다.

**관찰 (65차원)** = 관절각 20 + 관절속도 20 + 블록 위치(파지중심 기준) 3 + 자세 4
+ 선속도 3 + 각속도 3 + **지문별 접촉력 5** + 지문-블록 거리 5 + 진행도 1 + 중력 ON 1.

#### ⚠️ 발견 1 — 지문 접촉을 거리로 근사하면 안 된다

처음엔 "지문-블록중심 거리 < 3 cm"를 접촉 대용으로 썼는데, 완전 폐쇄 시 실측이
`[3.4, 4.0, 3.4, 2.3, 5.2] cm`이고 블록 AABB가 `3.3~3.8 cm`였다 — **실제로는 4지 포위인데
지표는 1개만 셌다.** 그래서 `block.get_contact_force_from_actor_world(<지문 링크 actor>)`로
**지문별 실제 접촉력**을 읽는다. 링크 actor는 `actor.get_nested_link_actors()`로 얻고,
접촉력이 채워지려면 스텝 전에 `QueryType.TOTAL_CONTACT_FORCE` 등록이 필요하다.

#### ⚠️ 발견 2 — 기본 강성이 물체를 압착한다

게이트 0에서 쓴 `MOCHI_ARTICULATED_POSE` 강성 `1e3`으로 완전 폐쇄하면 **지문 접촉력이
4,000~6,000 N**까지 올라간다. 15.6 g 블록에 대해 물리적으로 불가능한 값이고, 정책이
"잡는" 대신 **"압착하는"** 것을 배우게 되어 sim2real이 무의미해진다. 강성 스윕(완전 폐쇄, 1 s):

| stiffness | 최대 지문력 | 3지 접촉 파지 |
|---|---|---|
| 1e3 | 4,671 N | 성립 |
| 2e2 | 1,294 N | 성립 |
| 5e1 | 573 N | 성립 |
| 1e1 | 120 N | 성립 |
| **3.0** | **34.7 N** | 성립 |

→ 기본값을 **stiffness 3.0 / damping 0.3**으로 내렸고, `tip_force_limit`(기본 20 N)를
넘는 힘에 페널티를 넣었다. **실제 DG-5F-M의 지문 파지력 상한은 벤더 확인 대상이다(U8).**

#### 난이도 보정 — 고정 정책 기준선

"완전 폐쇄만 지령하는 고정 정책"의 성공률(엄격 기준: **지문 3개 이상 접촉 + 파지중심
6 cm 내**)을 배치 흔들림별로 실측했다:

| `place_jitter` | 고정 폐쇄 성공률 | 평균 지문 접촉 | 평균 최대력 |
|---|---|---|---|
| 0.015 m | **13 %** | 1.60 | 26.0 N |
| 0.025 m | 0 % | 1.07 | 24.9 N |
| 0.035 m | 0 % | 0.73 | 16.9 N |

기본값 `place_jitter = 0.015`로 둔다 — 학습 여지가 있으면서 완전히 불가능하지는 않은 지점이다.

**정식 기준선 (40 에피소드, 시드 9000~9039):**
`python superdex/scripts/eval_policy.py --baseline --episodes 40`

| 지표 | 고정 폐쇄 정책 |
|---|---|
| 성공률 | **7/40 = 18 %** |
| 낙하(조기종료) | **0/40** |
| 평균 지문 접촉 | **1.82** (성공에 3 필요) |
| 평균 최대 지문력 | 25.8 N (한계 20 N) |
| 평균 최종 거리 | 0.0212 m |
| 평균 리턴 | 304.4 |

> **실패 원인이 낙하가 아니라 지문 접촉 부족이다.** 고정 폐쇄는 블록을 한 번도 놓치지
> 않지만(0/40) 지문 접촉이 평균 1.82개에 그친다. 즉 학습 목표가 "떨어뜨리지 않기"가
> 아니라 **"다지 접촉을 확보하기"** 로 정확히 좁혀진다 — 프로젝트가 요구하는
> "다지 안정 접촉"과 같은 목표다.

**보상 항의 규모 (스텝당).** `r_near ≤1`, `r_touch ≤1`, `r_contact ≤0.5`, `r_hold ≤2`
→ 양의 최대 +4.5. 힘 페널티는 포화형이라 −1로 묶인다. 정책별 리턴 분리(15 에피소드):
무작위 **25.6**, 고정 폐쇄 **272.3**.

#### ⚠️ 발견 3 — `ray.init(runtime_env=...)` 가 SuperDex 워커를 죽인다

dg5f_grasp 학습이 **이터레이션을 한 번도 끝내지 못했다.** 증상: 3분 이상 진척 0,
python 프로세스 **44~52개**(러너는 4~8개인데), CPU만 계속 소비, 로그에
`Windows fatal exception: access violation` — 스택은 `ray/_private/worker.py`의
`disconnect`/`shutdown`, 즉 **워커 종료 경로**였다. 워커가 죽고 재생성되는 루프였다.

**처음엔 메모리 문제로 진단했지만 오진이었다.** 러너를 8→4로 줄여도 같은 증상이 났다.
진짜 원인은 asset 경로를 워커에 넘기려고 쓴
`ray.init(runtime_env={"env_vars": {"SUPERDEX_ASSETS_PATH": ...}})` 였다. Ray가 워커를
별도 런타임 컨텍스트에서 만들고, SuperDex 물리가 로드된 워커가 종료될 때 access
violation으로 죽는다.

**해결:** `runtime_env`를 쓰지 않고 **각 env 생성자가 `os.environ`에 직접 넣는다.**
우리 환경(`dg5f_grasp_env.py`)은 이미 `rtauto_config`에서 읽어 스스로 설정하므로
`runtime_env`가 애초에 불필요했다. 제거 후 실측:

| 구성 | 결과 |
|---|---|
| 러너 4 + `runtime_env` | 이터레이션 0 (무한 재생성) |
| 러너 0 (로컬 샘플링) | 3 이터레이션 정상 |
| **러너 4, `runtime_env` 제거** | **3 이터레이션(12k 스텝)이 startup 포함 37 초** → 집계 **≈480 steps/s** |

> **§8 throughput 계산을 이 값으로 정정한다.** cart_pole(가벼운 씬)의 하한 추정
> ≈4.3k steps/s는 DG5F 접촉 씬에 적용되지 않는다. **DG5F 실측은 러너 4개 집계
> ≈480 steps/s**다 — 1e7 스텝에 약 5.8 시간, 5e7에 약 29 시간. PoC 목표 규모의
> 하단(1e7)은 하룻밤 안에 들어오지만, 게이트 4의 DR 확대는 러너 수를 늘리거나
> 에피소드를 줄이는 조정이 필요하다.

`train_ppo.py`의 `OWN_ENVS`에는 환경별 `max_runners`(dg5f_grasp = 4)를 남겨 뒀다 —
32 GB에서 물리 씬 8개는 여전히 여유가 없기 때문이고, `--num-env-runners`로 덮어쓸 수 있다.

#### ✅ 발견 6 (2026-09-09) — **원인은 물체 크기였다.** v1~v4의 수정은 애초에 풀리지 않는 과제를 고치려 한 것

v1~v4가 전부 평평하게 끝난 뒤, 보상·탐색을 더 손대기 전에 **갈림길을 먼저 판정**했다:
성공 궤적 자체가 존재하는가? [`gate2_oracle_search.py`](../superdex/scripts/gate2_oracle_search.py)는
정책을 학습하지 않고 **개루프 궤적을 그리드로 훑어**(최종 폐쇄율 × 램프 길이 × 조임 여유 ×
배치 거리) 각 시드에서 성공시키는 궤적이 존재하는지 센다.

| 물체 | 성공 궤적 존재 시드 | 최선 고정 궤적 | 시드별 최선 `tips_best` |
|---|---|---|---|
| `block_red` 2.5 cm / 15.6 g | **1/10** | 2/10 | 중앙 **2** |
| **`duck_lamp` 11.9×11.0×7.5 cm / 545 g** | **7/10** | **6/10** (`f=0.8, ramp=60, x=0.04`) | 중앙 **4**, max 5 |

**2.5 cm 블록은 사람 크기 20 DOF 손에 너무 작아 3지 접촉이 기하적으로 성립하지 않는다.**
접촉 추이 실측이 결정적이었다 — 종료 시점 판정 문제가 아니었다:

| seed | tips 추이 (25스텝 구간 최대) | `tips≥3` 스텝수 | 최종 |
|---|---|---|---|
| 9000 | 0/2/2/**3/3/3/3/3** | **117/200** | 3, 성공 |
| 9001 | 0/1/2/2/2/2/2/2 | 0/200 | 2 |
| 9004 | 0/1/2/2/**0/0/0/0** | 0/200 | 0 (접촉 상실) |
| 9007 | 0/1/2/1/1/1/1/1 | 0/200 | 1 |

지문이 1~2개에서 멈추고 최종 접촉력도 31~57 N로 한계 20 N을 넘었다.
**즉 v1~v4의 보상 gradient·액션 지터·관찰 스케일 수정은 모두 근거가 있었고 의도한 효과도
확인됐지만, 고치고 있던 대상이 틀렸다.**

**조치: 기본 물체를 `duck_lamp_recumbent`로, 배치를 `palm + [0.04, 0, 0.04]`로 바꿨다.**
큰 물체가 (1) 달성 가능한 상한을 올리고, (2) 실제 목표인 **FOUP에 더 충실**하며,
(3) **비볼록 접촉** — Unity 대비 SuperDex를 택한 근거 자체 — 를 시험한다.

새 기준선 (고정 완전폐쇄, 30 에피소드, 시드 9000~9029):

| 지표 | 작은 블록 | **duck_lamp** |
|---|---|---|
| 성공률 | 7/40 = 18 % | **14/30 = 47 %** |
| 평균 지문 접촉 | 1.82 | **3.03** (요구치 3 달성) |
| 평균 최대 지문력 | 25.8 N (한계 초과) | **4.1 N** (한계 내) |
| 낙하 | 0/40 | 5/30 |
| 평균 리턴 | 304.4 | 563.7 |

> **판정: (A) 학습 설정 문제.** 이제 과제는 개루프로도 풀린다(7/10 시드). 남은 것은
> PPO가 그 궤적을 찾는지다 — v5 학습이 그 답이다.
>
> 부수 수정: 오라클 그리드에서 **중복 튜플을 제거**했다. `f=1.0`이면 `extra` 0.0과 0.1이
> `hold=min(1.0, f+e)=1.0`으로 같은 튜플이 되어 `per_traj` 키가 충돌해 같은 궤적을 두 번
> 셌다(평균 `tips_best`가 최대 5를 넘는 **7.80**으로 나와 발견). 정정 후 상위 궤적
> 성공률이 6/10이다.
>
> 물체 프리팹 실측: `block_red` 2.5 cm/15.6 g, `sphere` 3 cm/10 g,
> `fdt_peg` 2.2×2.2×4 cm/6.8 g, `paper_cup` 9.3×9.4×11.3 cm/15 g,
> `duck_lamp` 11.9×11.0×7.5 cm/545 g. 환경에 `object_prefab` 키를 추가했다(게이트 4의
> 다물체 일반화에도 필요).

#### ⚠️ 발견 5 — 접촉 기반 보상만으로는 **학습이 전혀 되지 않는다** (v1 실패)

첫 학습(480k 스텝, 120 이터레이션)은 **완전히 실패했다.** `return_mean`이 내내
18~24에서 평평했고, 학습된 정책이 미학습 체크포인트와 구별되지 않았다:

| 정책 | 리턴 | 성공률 | 평균 지문 접촉 |
|---|---|---|---|
| 무작위 | 25.6 | 0 % | 0.33 |
| **480k 스텝 학습 (v1)** | **45.1** | **0/20** | **0.00** |
| 미학습 체크포인트(12k) | 43.9 | 0/8 | 0.00 |
| 고정 완전폐쇄 | 304.4 | 18 % | 1.82 |

**원인: 보상에 gradient가 없었다.** 초기 정책은 무작위 탐색으로 지문 접촉을 **한 번도**
만들지 못하고(평균 0.00), 그래서 `r_touch`·`r_contact`·`r_hold`가 학습 내내 **항상 정확히
0**이었다. 남은 `r_near`는 grace 구간에서 블록 위치로 결정되어 액션과 무관하다. 즉
**액션이 관측되는 보상에 아무 영향을 주지 못해** credit assignment가 불가능했다.
접촉 과제에서 접촉 기반 보상만 두면 탐색이 첫 접촉에 도달하지 못하는 전형적 실패다.

**조치: 액션에 항상 반응하는 밀집 항을 추가했다.**

```
r_reach = exp(-10 · mean(지문-블록 거리))
```

추가 후 검증 — 폐쇄율에 따라 단조 증가하고 리턴이 10배로 분리된다:

| 정책 | 평균 `r_reach` | 리턴 |
|---|---|---|
| 열린 유지 | 0.206 | 45.7 |
| 절반 폐쇄 | 0.314 | 69.1 |
| **완전 폐쇄** | **0.630** | **450.8** |

이로써 **"다가가기 → 접촉 → 유지"의 계단**이 만들어졌다. 게이트 0에서 물체 배치를 실측으로
잡았듯, 여기서는 **보상 밀도**를 실측으로 잡은 것이다.

> **`stdout` 버퍼링 주의.** v1 학습 중 로그가 1,240 바이트에서 멈춰 보여 "정지"로 오진했는데,
> 실제로는 120 이터레이션 전부 정상 완료돼 있었고 종료 시점에 한꺼번에 flush된 것이었다.
> 이후 실행은 `python -u`(unbuffered)로 띄운다 — 진행 상황을 실시간으로 봐야 오진하지 않는다.

#### ⚠️ 발견 4 — Ray env-runner 워커가 비결정적으로 죽는다 (게이트 2의 실효 병목)

`runtime_env` 제거로 러너 4개가 **한 번은** 정상 동작했지만(3 이터레이션 37 초),
**같은 명령의 긴 실행에서 다시 멈췄다.** 로그에 Ray가 남긴 경고가 단서다:

```
Actor with class name: 'SingleAgentEnvRunner' ... has constructor arguments in the
object store and max_restarts > 0. If the arguments ... are lost, the actor restart
will fail.
```

즉 SuperDex 물리가 로드된 env-runner actor가 죽으면 Ray가 재시작을 시도하고, 그 경로가
안정적이지 않다. 재현이 비결정적이라 **러너 기반 병렬 샘플링은 게이트 2에서 신뢰할 수 없다.**

**대응: 로컬 샘플링(`--num-env-runners 0`)을 기본 경로로 쓴다.** 반복 실행에서 안정적이었다.

| 구성 | 안정성 | 속도 |
|---|---|---|
| 러너 4 (`runtime_env` 있음) | ❌ 무한 재생성 | — |
| 러너 4 (`runtime_env` 제거) | ⚠️ **비결정적** (1회 성공, 이후 정지) | 집계 ≈480 steps/s |
| **러너 0 (로컬 샘플링)** | ✅ **반복 안정** | **이터레이션(4,000 스텝)당 20 초 → ≈200 steps/s** |

> **§8 throughput을 이 값으로 다시 정정한다.** DG5F 접촉 씬의 **신뢰 가능한** 실효
> throughput은 **≈200 steps/s**다 — 1e7 스텝에 약 14 시간, 5e7에 약 69 시간.
> 게이트 2의 PoC 규모(수십만 스텝)는 문제없지만, **1e7 이상이 필요해지는 순간 이 병목이
> 계획을 지배한다.** 해결하려면 Ray 워커 안정화(upstream 이슈)나 러너 없는 다중 프로세스
> 자체 구현이 필요하다 — 게이트 4 착수 전에 판단해야 한다. §6 회귀 기준 3(집계
> 2,000 steps/s)에 **미달**한다는 점을 명시해 둔다: 이 항목은 게이트 0의 파지 테스트
> (단일 env 534 steps/s × 러너)가 성립한다는 전제였고, 그 전제가 Ray 워커 불안정으로
> 깨졌다. **회귀 기준 재판정이 필요한 사항이다.**

> **성공 기준을 계획 원안에서 조정했다.** §5 게이트 2의 원안은 "lift 후 2초 유지 ≥80 %"
> 였지만, 손목이 고정이라 **lift 동작 자체가 없다.** 대신 중력 하 유지 + 다지 접촉으로
> 정의하고, 판정은 **고정 정책 기준선 13 % 대비 얼마나 올라가는가**로 본다. 게이트 2의
> 목적은 "SuperDex에서 접촉 기반 파지가 이 throughput으로 학습되는가"에 답하는 것이다.

#### ⚠️ 거리 기준만으로 성공을 판정하면 안 된다

초기 버전은 파지중심 거리만 봤고, 그때 고정 정책이 **100 %** 성공했다. 실제로는 근위
지골로 **가두는(cage)** 것이었고 지문 접촉은 1~2개였다 — 프로젝트 목표인 "다지 안정
접촉"이 아니다. 성공 판정에 `min_tips`(기본 3)를 넣은 뒤 기준선이 13 %로 내려갔다.

### 게이트 1 결과 — ONNX 3자 파리티 통과

**판정: 통과.** 같은 32개 관찰 벡터에 대해 세 런타임의 액션이 일치한다.

| # | 비교 | 최대 오차 | 허용 |
|---|---|---|---|
| 1 | 래퍼 `nn.Module` vs **RLlib 실제 커넥터 경로** | **0.000e+00** | 1e-5 |
| 2 | `onnxruntime` vs RLlib 경로 | 1.431e-06 | 1e-5 |
| 3 | **Unity Inference Engine (C#)** vs Python 기준값 | **9.537e-07** | 1e-5 |

3번 실측 예: `unity 2.833229 vs python 2.833228`. 즉 **다이어그램에서 유일하게 "될지
모르는" 구간이 닫혔다** — SuperDex에서 학습한 정책이 Unity와 ROS2 양쪽에서 같은 값을 낸다.

산출물: `superdex/policies/cart_pole_ppo.onnx`(268 KB) + `.parity.json`(fixture),
`unity/Assets/Editor/PolicyParityCheck.cs`, `unity/Assets/Policies/`(ONNX 임포트 자산).

#### ⚠️ 커넥터가 액션을 되돌린다 — 실측으로 확인된 함정

체크포인트의 커넥터 구성을 실측한 결과:

```
env_to_module : AddObservationsFromEpisodesToBatch, AddTimeDimToBatchAndZeroPad,
                AddStatesFromEpisodesToBatch, BatchIndividualItems, NumpyToTensor
                -> 관찰 정규화 없음 (state.pkl 5바이트 = 빈 상태)
module_to_env : GetActions, TensorToNumpy, UnBatchToIndividualItems,
                RemoveSingleTsTimeRankFromBatch,
                NormalizeAndClipActions {normalize_actions: True, clip_actions: False},
                ListifyDataForVectorEnv
```

**`NormalizeAndClipActions`가 기본으로 켜져 있다.** 신경망은 **[-1,1] 정규화 공간**의
액션을 내고 커넥터가 실제 공간으로 되돌린다(`ray.rllib.utils.spaces.space_utils.unsquash_action`):

```
a = low + (a_norm + 1.0) * (high - low) / 2.0 ;  a = clip(a, low, high)
```

RLModule만 ONNX로 내보내면 이 되돌림이 빠져 **조용히 잘못된 정책**이 배포된다 —
cart_pole(`Box(-3,3)`)이면 3배 작은 액션, DG5F 관절 지령이면 단위가 아예 틀린다.
`superdex/scripts/export_onnx.py`는 이 변환을 **래퍼 `nn.Module`의 버퍼 상수로 그래프 안에
박아** 내보내고, 그래서 위 1번 비교가 오차 0이다. 계획 §5 게이트 1에서 예측한 함정이
실제로 존재함을 확인했다.

관찰 정규화는 cart_pole에서 비활성이었다. **DG5FGraspEnv에서 `MeanStdFilter` 등을 켜면
그 통계도 같은 방식으로 그래프에 박아야 한다** — JSON으로 빼서 Unity C#·ROS2 Python에
각각 구현하면 구현이 셋으로 갈라진다.

#### Unity 다리 실행 방법

- 패키지: **`com.unity.ai.inference` 2.5.0** (구 Sentis), 네임스페이스 `Unity.InferenceEngine`.
  ML-Agents 4.0.0이 `com.unity.ai.inference` 2.2.1을 의존해 이미 들어와 있다.
- **ML-Agents를 거치지 않는다.** `ModelLoader.Load(ModelAsset)` → `new Worker(model,
  BackendType.CPU)` → `SetInput("obs", tensor)` → `Schedule()` → `PeekOutput("action")`
  → `ReadbackAndClone().DownloadToArray()`.
- ⚠️ **런타임 ONNX 로드는 지원되지 않는다.** ONNX는 임포트 시점에 `ModelAsset`으로 변환되므로
  `Assets/` 안에 있어야 한다. 그래서 `superdex/policies/*.onnx`를 `unity/Assets/Policies/`로
  복사한다. fixture(JSON)는 저장소 원본을 `RtautoConfig.GetRepoPath()`로 직접 읽어
  중복을 만들지 않는다(원칙 1).
- 배치모드 실행 (첫 실행은 임포트로 수 분 걸린다):

```powershell
& "C:\Program Files\Unity\Hub\Editor\6000.4.0f1\Editor\Unity.exe" -batchmode -nographics `
    -projectPath unity `
    -executeMethod RtAuto.EditorTools.PolicyParityCheck.RunFromCommandLine `
    -logFile parity.log
```

종료 코드 0 = 통과 / 2 = 오차 초과 / 3 = 자산·fixture 문제. 에디터에서는 상단 메뉴
`RtAuto > Policy Parity Check`.

#### 게이트 1 재현

산출물(체크포인트·ONNX·fixture)은 **재생성 가능하므로 git에 넣지 않는다**(`.gitignore`).
새 PC에서 아래 4단계로 그대로 재현된다 — 1~3은 각각 1분 내, 4는 첫 임포트만 수 분이다.

**터미널 1 (PowerShell, 리포 루트, `superdex/.venv` 활성)**

```powershell
python superdex/scripts/sync_lab_configs.py
python superdex/scripts/train_ppo.py --env cart_pole --iters 4
python superdex/scripts/export_onnx.py --checkpoint superdex/results/cart_pole_ppo
Copy-Item superdex/policies/cart_pole_ppo.onnx unity/Assets/Policies/ -Force
```

`export_onnx.py`가 1·2번 비교를 스스로 판정하고(불일치면 종료 코드 2) fixture를 낸다.
그 다음 위 배치모드 명령으로 3번(Unity) 비교를 돌린다.

### ⚠️ 게이트 1 블로커 3개 — 동봉 샘플 앱을 쓰지 않기로 결정한 이유

`superdex_lab/apps/rllib/train_samples.py`(외부 클론의 **샘플 앱**)로 학습을 돌리려다
연달아 3개를 만났다:

| # | 증상 | 원인 | 처리 |
|---|---|---|---|
| 1 | `No samples to train, exitting...` | **`superdex-lab==1.0.0` wheel에 `.json`이 0개.** 학습 레시피(`*.train.json`)와 config variant가 클론에만 있다. `load_env_config()`가 `inspect.getfile(env_cls)` 옆을 보므로 설치본에서는 못 찾는다 → **공식 RL 워크플로가 wheel만으로는 돌지 않는다** | `superdex/scripts/sync_lab_configs.py`로 클론 → 설치본 복사(11개). 상위 버전에서 고쳐지면 no-op |
| 2 | `DeprecationWarning: checkpoint_frequency is deprecated` (예외로 던져짐) | **Ray 2.58.0 비호환.** `CheckpointConfig(checkpoint_frequency=...)`가 `ray.train.v2`에서 거부된다. SuperDex 1.0.0은 구버전 Ray 기준으로 작성됨 | 자체 학습기로 회피 (아래) |
| 3 | `use_libuv was requested but PyTorch was build without libuv support` | **Windows torch.distributed.** `num_learners>=1`이 분산 learner를 띄운다 | 자체 학습기 기본값 `num_learners=0` |

**결론: 학습 진입점을 우리가 소유한다.** `superdex/scripts/train_ppo.py`를 만들어
PPO를 직접 구성했다. 게이트 2에서 DG5FGraspEnv용 학습기를 어차피 우리가 써야 하므로,
외부 샘플 앱에 환경변수(`RAY_TRAIN_V2_ENABLED=0`, `USE_LIBUV=0`)로 맞추는 대신 정공법을
택했다 — 레시피 discover를 쓰지 않고, 폐기된 인자를 쓰지 않고, 분산 learner를 쓰지 않으니
**블로커 1~3이 모두 사라진다.**

> `ray[rllib]`·`onnx`·`onnxruntime` 핀이 아직 비어 있던 것이 블로커 2의 직접 원인이다
> (R3 리스크가 실제로 발생). 실측 버전은 `ray 2.58.0`, `onnx 1.22.0`,
> `onnxruntime 1.29.0`, `torch 2.6.0+cu124`.

### 게이트 0 파지 테스트 결과와 시나리오 설계 (`gate0_grasp_test.py`)

**판정: 통과.** SuperDex 접촉 물리가 DG5F로 2.5 cm 블록(15.6 g)을 잡고 **양방향 1g를
버틴다.** 2초간 드리프트 1.3 mm, 블록 속도 0.001~0.002 m/s — 흔들림도 관통도 없다.

시나리오를 이렇게 만든 이유(전부 실패를 거쳐 정한 것):

| 설계 | 왜 |
|---|---|
| 손목을 `joints[0].type = HARD`로 용접 | 기본 `FREE`면 손이 자유부양한다. 용접 시 DOF가 정확히 **20** |
| 컨트롤러는 `MOCHI_ARTICULATED_POSE` | `BASIC_*_PD`는 중력 항이 없어 링크 중력을 꺼야 한다. 중력을 뒤집어 판정하므로 중력 항이 있는 암시적 컨트롤러가 필요 |
| 물체를 **떨어뜨리지 않고** 배치 | 손 기본 방향이 손가락 +Z, 손바닥 +X라 수평 손바닥이 없다. 떨어뜨리면 손을 지나쳐 바닥까지 간다(실측) |
| 배치를 **손바닥 링크 좌표계**로 | 손 자세와 무관하게 적기 위해. 성공 조합은 `palm + [0.03, 0, 0.04]` (차선: `[0.04, 0, 0.06]`) |
| 지문 중심이 아니라 **손바닥 앞 포켓** | 지문 중심에 두면 f=0.30에 닿았다가 더 조일 때 **밖으로 밀려난다**. 5지 파워 그립은 물체가 손바닥 쪽에 있어야 성립 |
| 닫는 동안 **중력 0** | 손가락이 닫히는 1.25초 동안 자유낙하하면(≈7.7 m) 파지가 성립하지 않는다 |
| **접촉이 생길 때까지** 조금씩 닫고, 뒤에 `grip_margin` 추가 | 고정 폐쇄율은 케이지가 블록보다 커서 닿지도 않는다. 성공 케이스는 f=0.62에서 접촉 → f=0.72로 조임 |
| 판정 = 파지중심 거리 + 접촉점 수 | 거리만 보면 "손 밑면에 걸려 있는 것"도 성공으로 오판한다(초기 버전에서 실제로 겪었다) |

배치 스윕 결과 (`--place`):

| palm 좌표계 오프셋 | 접촉 시작 f | 최종 f | 최종 드리프트 | 판정 |
|---|---|---|---|---|
| `0.03, 0.00, 0.04` | 0.62 | 0.72 | **0.0256 m** | ✅ 성공 |
| `0.04, 0.00, 0.06` | 0.54 | 0.64 | 0.0376 m | ✅ 성공 |
| `0.05, 0.00, 0.09` | 0.28 | 0.38 | 0.0538 m | ❌ |
| `0.03, 0.00, 0.02` | 0.18 | 0.28 | 4.37 m | ❌ |
| `0.045, 0.02, 0.07` | 0.44 | 0.54 | 4.42 m | ❌ |

> **게이트 2(RL)에 그대로 넘어가는 교훈**: 파지 성공 영역이 좁다. 손바닥 앞 3~4 cm ×
> 높이 4~6 cm 구간만 잡히고, 조금만 벗어나면 놓친다. 이건 **정책이 학습해야 하는
> 문제가 실재한다**는 뜻이기도 하다(스크립트로는 튜닝으로만 맞출 수 있다) — 보상 설계에서
> **접촉 확보 → 조임 → 유지**의 단계 구분이 필요하다는 근거로 쓴다.

### ⚠️ 접촉점 조회는 스텝 전에 쿼리를 등록해야 한다

`actor.get_contact_points_world()`는 그냥 부르면 예외가 난다. 시뮬레이션 스텝 **전에**
`actor.register_query(physics.QueryType.CONTACT_POINTS)`를 호출해야 결과가 채워진다.
접촉력은 `get_contact_force_world()` / `get_contact_force_from_actor_world()`도 있다 —
게이트 2의 관찰(지문 접촉·접촉력)에 쓸 경로다.

### 동봉 예제는 GUI 디버거를 기다린다

`example_bot_loading.py` / `example_osc_jsc_control.py` / `example_scene_loading.py`는 모두
`if physics.debugger.attach(): while physics.debugger.is_attached(): scene.step(...)` 구조다.
**디버거 앱이 붙기 전까지 블로킹**하고 스스로 끝나지 않는다(180초 넘겨 확인). 측정·자동화
스크립트는 `attach()`를 호출하지 말고 그냥 `scene.step()` 루프를 돌린다 — `gate0_hand_probe.py`가
그렇게 되어 있다.

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
