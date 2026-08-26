# SVH 손가락 진동 디버깅 캠페인 — 2026-07-07

> 증상: 로봇 손가락이 (A) 주먹 명령인데 펴지거나 제멋대로 움직이고 (B) 홀드 중에도 그네처럼 출렁임.
> 이 문서는 7/7 하루 동안의 전 실험·측정·기각 가설을 기록한다.
> **[7/7 야간 업데이트] 원인 특정 완료 — §8 참고.** 트리거 = 구동관절 아래 매달린 mimic 원위지골(t 등)
> 서브트리. 최소 재현계 5바디, t 제거 시 p2p 0.00°로 완전 안정. §2~§7은 야간 세션 이전 기록임.

관련 문서: `WORKLOG.md`(§6~9, 7/2 1차 진동 디버깅), 메모리 `unity-digital-twin-project`.
**속편: [DEBUG_OSCILLATION_20260708.md](DEBUG_OSCILLATION_20260708.md)** — 기하 전수 검증(기각·결백 확정) + Solver Type PGS→TGS(진폭 절반, 잔존).
산출물: `svh/diag_20260707/` (프로브·분석 스크립트 + 실험 로그 CSV 전부).

---

## 1. 결론 요약 (현재까지)

- **A와 B는 같은 원인.** 매핑·비전 입력은 결백(입력 p2p ≤1°일 때 관절 실측 p2p 106°).
- 손가락 관절들은 사실상 **드라이브 힘이 거의 전달되지 않는 준자유 관절**처럼 거동한다.
  걸린 힘(stiffness 10000 기준 수천 N·m급) 대비 관측 운동이 5~6자릿수 약함.
- 그동안 "수렴"으로 보였던 것(7/2 주먹 프로브 ±2°)은 목표각이 마침 **하드리밋 값**이라
  리밋에 눌린 것으로 재해석됨 (리밋 안쪽 80% 목표를 주면 추종이 가장 나빴음).
- **고립 재현체는 어떤 조건에서도 완벽 작동** (동일 게인·동일 미세 관성·직렬 평행축 2관절·킥 주입까지).
  → 문제는 프로젝트 물리설정/게인이 아니라 **임포트된 로봇 인스턴스 내부**에만 있다.
- 정상 관절 z(엄지대향)·virtual_i(spread)와 병든 관절(굴곡 계열 전부)의 정적 구성은 동일.
  차이는 축 방향(자기 축에 대한 서브트리 유효관성)뿐인데, 이것도 재현 실험으로는 재현 안 됨.

## 2. 기각된 가설 전체 (실험 근거 포함)

| # | 가설 | 실험 | 결과 |
|---|------|------|------|
| 1 | 비전 입력 지터 | 정지 구간 rx std/p2p 측정 | rx p2p ≤0.9° vs act p2p 106° → 기각 |
| 2 | 채널 매핑/부호 반전 | corr(rx,tgt) 전 채널 1.00, map_to_svh 검사 | 기각 |
| 3 | stiffness 과다 (10000→1000+임계감쇠) | 프로브 전/후 비교 | 무반응/일부 악화 → 기각 |
| 4 | 솔버 반복 부족 (6/1→128/8) | 〃 | 무반응 (idxDist 65→112) → 기각 |
| 5 | mimic 매 스텝 주입 | 런타임 비활성 프로브 | **부분 효과**: 구동1관절 손가락만 절반~1/4 완화, 검지·중지(구동 2관절 직렬)는 여전 → 증폭기일 뿐 근원 아님 |
| 6 | 하드 리밋 부재 | twistLock 조회 | 20관절 전부 LimitedMotion **활성인데 60°+ 관통됨** → 부재 아님(무력화가 문제) |
| 7 | 목표가 리밋 위(리밋 싸움) | 80%/15% 목표 프로브 | 오히려 악화(idxDist 130° p2p) → 기각 |
| 8 | 스텝 충격 | 0.8s 램프 프로브 | 무반응 → 기각 |
| 9 | Ground 접촉 | ComputePenetration | 0건 (손 y=0.35~0.55m) → 기각 |
| 10 | 자기충돌 무시 실패 | 플레이 중 겹침쌍 검사 | 겹침 47쌍 전부 ignore 정상 → 기각 |
| 11 | 중력/루트 | useGravity 0/41, root immovable | 정상 → 기각 |
| 12 | maxJointVelocity 캡 | 조회 | 100 rad/s (관측 1.3) → 기각 |
| 13 | driveType 오설정 | 조회 | 전부 Force, targetVelocity 0 → 기각 |
| 14 | 관성 과소 악조건 (하한 1e-3) | 씬 적용 프로브 | **악화** (idxDist 65→149, thmFlex 27→79) → 기각·원복. 단 "반응은 크게 함" |
| 15 | 스크립트의 매 스텝 xDrive 재기록 | 전 스크립트 끄고 target 1회 기록 | 여전히 0.1~0.6 rad/s로 기어가 오버슈트·스윙 → 기각 |
| 16 | SvhInitialPoseSync 텔레포트 오염 | 에디트 모드에서 끄고 플레이 | 여전(초기킥 부활로 더 험함) → 기각 |
| 17 | 앵커/축 뒤틀림 | §4 앵커 정밀 비교 | 전부 결백 → 기각 |
| 18 | 직렬 평행축 강성 체인 | 3바디 재현(손가락 관성) | 완벽 작동 → 기각 |
| 19 | 교란 후 링잉 잔존 (일반 현상) | 재현체에 3 rad/s 킥 | 1스텝 만에 소멸 → 기각 |
| 20 | 숨은 자유 DOF | dofCount 조회 | 전부 dof=1 → 기각 |

## 3. 핵심 측정 데이터

### 3-1. 프로브 실험 3지표 (주먹 홀드 정상상태, 홀드 앞 1초 제외)

기준(before) = stiffness 10000 / damping 200 / solver 6/1 / 자동 관성. 프로브 = 주먹↔펴기 4사이클(2.5s씩, 60Hz UDP).

| 실험 | idxDist p2p | midDist p2p | ring/pinky p2p | 한계밖 음수 | 비고 |
|------|------------|------------|----------------|------------|------|
| before (기준) | 65.4° | 97.8° | 52.8 / 38.3° | 22~37% | `before.csv` |
| stiffness 1000+임계감쇠 | 74.6° | 73.6° | 61.8 / 105.7° | 23~46% | `after.csv` |
| solver 128/8 | 112.0° | 103.4° | 42.6 / 50.4° | 21~35% | `after_solver.csv` |
| mimic OFF | 81.1° | 67.2° | **21.0 / 11.3°** | 26~35% | `after_nomimic.csv` |
| 리밋 안쪽 80%/15% 목표 | 130.3° | 122.1° | 33.1 / 57.6° | 25~50% | `after_midlimit.csv` |
| 0.8s 램프 | 110.4° | 56.3° | 25.0 / 59.1° | 24~44% | `after_ramp.csv` |
| 관성 하한 1e-3 | 149.0° | 86.1° | 55.1 / 27.9° | 22~35% | `after_inertia.csv` |

- thmOpp(z)·spread(virtual_i)는 **모든 실험에서 p2p ~0, 오차 0** — 유일한 정상 관절.

### 3-2. 파형·주파수 (결정적)

- 진동 주파수 0.3~0.7Hz(주기 2~3초), 스텝간 부호교대율 1~4% → 솔버 채터링(25Hz) 아님.
- 주먹 스텝 순간 idxDist: 명령 반대방향 **−71°** 킥 → **+137°**까지 관통(상한 76.4, LimitedMotion 활성인데) → 수 초 그네. `waveform.py` 참고.
- 속도는 항상 ~0.1–5 rad/s 범위(7/2 기록 "vel 1.3 rad/s 유지"와 일치).
- 진동 중에도 xDrive 파라미터는 온전(라이브 샘플링: 10000/200/100000 유지, driveType=Force).
- 팔은 과도기 후 완전 정지(vel 0.00)인데 손가락만 홀로 진동 → 팔 유발 아님.
- 부모 l이 자식 p의 **정확히 0.195배 비율로 동조** 진동 — 고정 모드 형상(자유 진자 모드처럼).

### 3-3. 앵커 정밀 비교 (z, virtual_i vs p, l, o, k) — 전부 결백

- matchAnchors 전부 True, 월드 앵커 불일치 0.00mm / 0.00°.
- 스케일 체인에 비단위/비균일 스케일 없음.
- URDF 원본 axis 전부 `0 0 1`(z 관절만 `0 0 -1`) — 임포트 앵커 회전과 정합.
- **플레이 중 실축 검증**: 드라이브 twist축(월드) vs 실제 상대 각속도 방향 사잇각 = 병든 관절 포함 **전부 0~1°**. jointVelocity와 각속도 크기·부호 일치. 축은 완벽.

### 3-4. 리플렉션 전 속성 diff (재현체 vs 로봇 p) — `prop_diff.txt`

트리비얼 제외 실차이: anchorRotation 부호(+90° vs −90° about Z), linearLockX=Limited(로봇),
linear/angularDamping·jointFriction 0(로봇, 재현체는 0.05), automaticCenterOfMass=False(로봇, URDF CoM 수동값 (0,0,0.01) — URDF와 정합).

## 4. 현재 상태 (2026-07-07 저녁 기준)

- **씬(SampleScene.unity)**: 기준 상태로 저장됨 — 드라이브 10000/200(손·팔), solver 6/1, 자동 관성, SvhInitialPoseSync enabled. 즉 실험 전 상태와 동일.
- **씬 백업**: `KDT/backups/SampleScene_before_stiffness1000_165717.unity`, `SampleScene_before_inertiafloor_*.unity`.
- **코드 변경(유지됨)**: `svh/vision_node.py` 로그 파일명 타임스탬프화(`vision_log_%Y%m%d_%H%M.csv`) — 덮어쓰기 방지.
- **로그 보존**: 7/6 라이브 세션 Unity 로그 = `svh/unity_joint_log_20260706_live.csv` (7/6 파이썬 로그는 vision_node 재실행으로 소실됨 — rx가 원본 대체).
- Unity 에디터는 unity-cli(포트 8090)로 제어. 프로브는 Unity SvhReceiver(UDP 5005)로 쏨 — **udp_test_receiver.py 켜두면 안 됨**.

## 5. 재현/재개 방법

```powershell
# 표준 프로브 (주먹<->펴기 4사이클) — Unity play 중 실행
unity-cli editor play --wait
python svh/diag_20260707/probe_cycle.py     # 변형: probe_variant.py mid|ramp
unity-cli editor stop
# 로그는 svh/unity_joint_log.csv 에 쌓임 (SvhJointLogger가 플레이 중 자동 기록)

# 3지표 비교 (before.csv 기준 대비)
python svh/diag_20260707/compare_ba.py <상대로그.csv>   # 경로 상수 SP 수정 필요(스크래치패드 기준으로 작성됨)
```

주의: `diag_20260707/*.py`의 경로 상수(SP)는 세션 스크래치패드를 가리키고 있으므로 재사용 시 `svh/diag_20260707/`로 수정할 것.

## 6. 남은 가설 (우선순위순)

1. **로봇 인스턴스 고유의 숨은 상태** — 재현체는 모두 정상이므로, 로봇 쪽 ArticulationBody 속성/트리의
   무언가가 다름. §3-4 diff의 후보(anchorRotation 부호, linearLockX=Limited, CoM 수동)를 재현체에
   이식하는 실험이 **중단 지점**(§7).
2. 트리 수준 원인 — 42바디 전체 체인(무거운 팔 위 초경량 손) 조합에서만 발현될 가능성.
   판별: SVH 손만 새 씬에 fresh import 후 단일 관절 스텝 테스트 (임포터/URDF 문제 vs 이 인스턴스 오염 양분).
3. 씬 인스턴스 오염 — 7/2 메시·콜리전 회전 수정, 관성 재배분 등 수차례 수동 조작 이력.
   fresh import가 정상이면 재임포트로 해결(수동 수정사항 이관 필요: 메시 회전, MimicJointController 등).

## 7. 재개 지점 (중단된 실험)

**"clone-props 재현체"**: 완벽 작동하던 고립 재현체에 §3-4 diff의 로봇 속성을 전부 이식
(anchorRotation/parentAnchorRotation = (0,0,-0.70711,0.70711), linearLockX=Limited/linY·Z=Locked,
linear·angularDamping=0, jointFriction=0, automaticCenterOfMass=false + CoM(0,0,0.01), 나머지는 기존 재현체와 동일)
→ target 40° 스텝 응답 관찰.
- **여전히 완벽하면**: 바디 속성 결백 확정 → 남은 가설 2(트리) → 손만 fresh import 테스트로 진행.
- **출렁이면**: 이식한 속성 절반씩 이분법으로 범인 특정 (linearLockX=Limited가 1순위 용의자 —
  revolute에서 linear 잠금은 무시된다고 알려져 있으나 검증된 적 없음).

수정 방침(사용자 지시): 원인 확정 전까지 **씬·코드 수정 금지**, 진단(런타임 비영속 실험)만.
원인 나오면 임포트 재실행 vs 수동 교정 중 사용자가 결정.

---

## 8. 야간 세션 (7/7 밤) — 원인 특정 완료

전 실험 런타임 비영속(플레이 중 생성, 씬·코드 무수정). 산출물: `svh/diag_20260707/night_copyprobe/`
(각 실험의 .cs 프로브 + 로그 CSV + summary). 프로토콜: 손 목표 0으로 1.5s 정착 → 주먹 스텝 → 8~9s 홀드,
정상상태(스텝 +2s 이후) p2p / mean|err| 판정. 에디터 상태: 드라이브 10000/200, solver 6/1 (기준 상태 그대로).

### 8-1. 실험 시퀀스와 결과

| # | 실험 | 구성 | 결과 (정상상태 p2p) | 판정 |
|---|------|------|--------------------|------|
| 1 | §7 clone-props 재현체 | 수제 3바디(virtual_l→l→p 속성 전체 이식: anchorRot 부호, lockX=Limited, CoM수동, damping/friction 0, 관성 1e-6, 10000/200, solver 6/1) | l·p 모두 **0.00°**, 오차 ≤0.05°, 과도응답도 단조·무킥 | **바디 속성 결백 확정** |
| 2 | 로봇 전체 Instantiate 복제 | 플레이 중 원본 복제(+2.5m), UDP·슬라이더·로거 스크립트 제거(mimic·selfcollision·initialpose 유지), 9관절 직접 스텝 | a86/i86/j59/k55/l52/**o164/p189**, z·virtual_i 0 — 원본과 동일 시그니처 | **병은 직렬화 상태에 실림** (스크립트 입력 아님) |
| 3 | 복제본 콜라이더 전부 제거 | #2 + 관성·CoM 동결 후 Collider 45개 DestroyImmediate | #2와 사실상 동일(p 190, o 164 …) — 결정론적 재현 | **콜라이더/접촉 결백** |
| 4 | 손 서브트리만 복제 | svh_base_link 이하만 Instantiate(팔 없음) → 루트 immovable, 콜라이더 제거, 스크립트·mimic 없음 | l16/k19/a22/j23/i17/**o58/p67**, z·virtual_i 0 (원본 mimic-OFF 시그니처와 일치) | **팔·전체 트리 결백** |
| 5 | 검지 하나만 복제 | virtual_l 이하 5바디(virtual_l·l·p·t·fftip)만, 동일 처리 | l 15.66 / **p 66.51** — #4와 수치까지 동일 | **최소 재현계 = 5바디** |
| 6 | #5에서 t 서브트리 제거 | t(+fftip) GameObject 파괴 → 3바디 | l·p 모두 **p2p 0.00°** — 완전 안정 | **범인 = t 서브트리** |

### 8-2. 결론

- **진동의 트리거는 구동관절(p) 아래 매달린 mimic 원위지골 관절 t (+fftip)다.**
  t의 revolute 드라이브도 7/2 일괄 설정으로 stiffness 10000/damping 200을 갖고 있고(target 0),
  t 링크 관성은 ~1e-6 kg·m² 수준 → 이 관절 자체가 수치적으로 불안정한 초고강성 스프링이 되어
  부모 체인(l, p)으로 에너지를 퍼올린다. MimicJointController의 target 주입 여부와 무관
  (스크립트를 다 죽여도 재현) — 그래서 7/7 낮의 "mimic OFF 부분 완화" 실험이 근원을 못 잡았던 것.
- 기존 관찰 전부 설명됨:
  - **z(엄지대향)·virtual_i(spread)만 항상 정상** = 이 둘은 자기 아래에 "드라이브 달린 초경량 mimic
    지골"이 직결로 매달려 있지 않은 구동관절.
  - 검지·중지(o/p)가 최악 = 구동 2관절 직렬 + 각각 아래 mimic 지골(s, t)이 달린 구조.
  - mimic-OFF에서 ring/pinky만 크게 완화 = mimic 주입은 증폭기, t류 관절의 존재가 본질.
  - 고립 재현체(§2 #18, §8 #1)가 전부 완벽했던 이유 = 재현체엔 t에 해당하는 자식 관절이 없었다.
- 부차 확인: RequireComponent 때문에 SvhReceiver는 SvhHandDriver/SvhJointLogger보다 먼저
  DestroyImmediate 불가(콘솔 에러 → **Error Pause로 물리 동결**되어 첫 복제 프로브가 무효였음.
  샘플수 ~10kHz + 전 관절 정확히 0.000이면 pause 의심할 것).

### 8-3. 수정 후보 (미실행 — 사용자 결정 대기)

원인이 "mimic 지골 관절의 드라이브 강성 vs 관성 부조화"이므로, 후보 우선순위:
1. **mimic 관절만 드라이브 게인 하향** (예: stiffness 100~500, damping 임계감쇠) — 구동 9관절은 10000 유지.
   mimic은 어차피 MimicJointController가 target을 따라 붙이므로 낮은 강성으로 충분할 가능성.
2. mimic 지골 링크의 관성 하한 상향 (단 §2 #14에서 전 링크 일괄 1e-3은 악화였음 — mimic만 선별 적용은 미검증).
3. 위 둘 조합 + 표준 프로브/라이브 웹캠 재검증.
검증 순서 제안: 최소 재현계(검지 5바디 복제)에서 후보를 먼저 A/B → 통과하면 씬에 적용.

### 8-4. 재현 방법 (야간 실험)

```powershell
# Unity play 중, 각 프로브는 자기완결(생성→스텝→로그→자기파괴)
cat svh/diag_20260707/night_copyprobe/finger_only_probe.cs | unity-cli exec --allow-async
# 결과: 스크립트 상단 outDir 상수 경로에 *_summary.txt / *_log.csv 생성 (경로 상수 수정해서 쓸 것)
```

주의: 프로브 .cs의 `outDir` 상수는 당시 세션 스크래치패드 경로임 — 재사용 시 수정.
