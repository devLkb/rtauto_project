# dg5f — DG5F 핸드트래킹 텔레옵 파이프라인

웹캠 MediaPipe → 20관절 각도 → UDP → Unity DG5F 구동. (SVH 파이프라인 `svh/`의 후속)

> 최종 갱신 2026-07-21. 이 문서는 **현재 코드 기준**. 과거 설계 변천은 `docs/WORKLOG.md` 참조.

## 구성

| 파일 | 역할 |
|---|---|
| `dg5f_angles.py` | MediaPipe 21 landmark → 20채널 사람 프록시(rad) → DG5F 관절각[deg] 매핑 (채널 테이블·보정 로드·엄지 리타게팅) |
| `vision_node_dg5f.py` | 웹캠 캡처 → 각도 → One Euro 필터 → UDP 송신 메인 루프 |
| `calibrate_dg5f.py` | 채널별 human_min/max + 엄지 직진도 보정 → `dg5f_calibration.json` 저장 |
| `probe_sender.py` | 웹캠 없이 fist/open/cycle 패킷 송신 (배선 결정적 검증용) |
| `probe_landmarks.py` / `analyze_lmprobe.py` | 랜드마크 21×3 원본 덤프 + 프록시 후보 SNR·부호 분석 (프록시 설계 검증용) |
| `analyze_teleop.py` | 텔레옵 추종 검증 — vision 로그 ↔ Unity 관절 로그 시간정렬 대조 |
| `joint_ranges.py` | 사람/로봇 관절 가동범위 대조표 (매핑 검증·참고용, `python joint_ranges.py`) |
| `one_euro_filter.py` | 저역통과 필터 |
| `dg5f_calibration.json` | (없으면 기본값) 채널별 human_min/max + thumb_straight_ratio — 재보정 시 생성 |
| `CALIBRATION_GUIDE.md` | 보정 시 해야 할 동작 체크리스트 |

Unity 쪽(`unity/Assets/Scripts/`): `Dg5fReceiver.cs`(UDP 수신) + `Dg5fHandDriver.cs`(관절 주입·관절 격리 디버그) + `Dg5fFingerIK.cs`/`Dg5fFingerIKMode.cs`(손가락 IK·구동모드 일괄스위치) + `Dg5fIKVectorDebug.cs`(IK 목표 시각화) + `Dg5fJointLogger.cs`(로깅). 4개 DG5F 프리팹 루트에 부착.

## 프로토콜 (Python ↔ Unity 계약)

- UDP `127.0.0.1:5006` (⚠️ SVH는 5005 — 공존 가능). 포트 `UNITY_PORT`, `--bridge` 시 실물 SDK로도 동시 송신(`BRIDGE_PORT` 5008 — 값은 `config/rtauto_config.py`가 유일한 출처, 구 5007은 ZED 좌표 송신과 충돌해 변경).
- **v6 패킷: `'<72f'` (72 float32, little-endian)**
  - `[0..19]` DG5F 관절각 20개 **[deg]** — 순서 = `CHANNEL_NAMES`(아래)
  - `[20..22]` 엄지끝 정규화 좌표 xyz / `[23]` 핀치 플래그 / `[24]` 엄지-검지 끝거리 비율
  - `[25..36]` 손가락 리치벡터 4×3 (검지/중지/약지/새끼) / `[37..51]` 손목→끝 벡터 5×3 (엄지 포함)
  - `[52..71]` **20채널 라디안 원값**(compute_raw, 매핑·필터 전) — 비전 프록시 vs 로봇 관절 라디안 비교/디버그용(`Dg5fReceiver.GetRawRadians`)
- 값 `[0..19]` = **DG5F 관절공간 각도[deg]**. 사람→관절 매핑·보정·방향반전은 전부 Python(`dg5f_angles`). Unity는 URDF 리밋 clamp + lerp 스무딩 + xDrive.target 기록만.
- 채널 순서(고정): `[0..3]` 엄지 1_1~1_4 / `[4..7]` 검지 2_1~2_4 / `[8..11]` 중지 / `[12..15]` 약지 / `[16..19]` 새끼. Unity는 `_dg_<손가락>_<마디>` **이름 접미사 매칭**(위치 매칭 금지, 좌 `ll_`/우 `rl_` 공용).

## 손가락/관절 의미와 매핑 (2026-07-21 현재)

FK 실측(왼손 URDF)으로 축·역할 확정. 전관절 격리 눈검증 완료.

### 엄지 (손가락 1) — 4채널 모두 확정
| 관절 | 프록시(`compute_raw`) | 로봇 동작 | 매핑 |
|---|---|---|---|
| **1_1** thumb_cmc | `_thumb_abduction` (cmc→mcp 벡터의 손바닥평면 방위각) | 손바닥평면 안 **벌림(검지와 수직)↔접힘(손가락과 평행)** | **`|abd|` → 로봇 [FOLD_DEG=−65, SPREAD_DEG=+22]° 양방향 선형** |
| **1_2** thumb_opp | `_thumb_opposition` (엄지 근위마디가 손바닥평면 밖으로 **들린 각** = `arcsin(dot(v,n)/‖v‖)`, 실측 rest 11~14°·완전대향 37°) | 평면 밖 **대향**(손바닥서 떠서 가로질러) | `REST`(0.20) 뺀 뒤 ratio는 `[0,RATIO_HI=0.62]`→[0,−95]°, direct는 1:1 × `THUMB_OPP_GAIN`(3.9), clamp[0,−155]° |
| **1_3** thumb_mcp | `_bend`(랜드마크 2 꼭짓점) | 엄지 밑동(MCP) 굽힘 | 굽힘 1:1, clamp[0,80]° |
| **1_4** thumb_ip | `_bend`(랜드마크 3 꼭짓점) | 엄지 끝(IP) 굽힘 | 굽힘 1:1, clamp[0,80]° |

- **1_1 매핑이 왜 `|abd|` 크기 기반인가**(2026-07-21): 실측상 벌림/접힘이 프록시 **부호가 아니라 크기**로 구분되고(벌림=큰각/접힘=작은각≈0), 이 부호는 손 방향·거울상에 **불변**. 그래서 부호 뒤집기가 아니라 크기 `|abd|`를 로봇 양방향각에 직접 선형매핑 → 손을 어떻게 들든 일관. 튜닝: `THUMB_CMC_FOLD_DEG/SPREAD_DEG`(로봇각), `THUMB_CMC_H_FOLD/SPREAD`(사람 |abd| 범위). thumb_cmc는 **LEFT_MIRROR 제외**(왼손각 직접 산출).
- **1_1↔1_2 혼합**: 안장관절이라 대향+벌림/접힘이 자연히 섞임 — 인위적 디커플링 안 함(`THUMB_ABD_OPP_GATE=False`가 기본, True면 실험적으로 fold 중 벌림 감쇠).
- **1_2 공식 교체**(2026-07-27): 옛 `arctan2(depth, |width|)`는 분모(=1_1 벌림량)가 엄지를 모을수록 0으로 가 **손만 펴도 60°씩 출렁였다**(손 편 프레임의 59~61%, 실제 들림각 3~6°를 60°로 뻥튀기). 분모를 마디 길이로 바꾼 `arcsin` 형태로 교체 → crosstalk corr −0.62→−0.13(좌), 중립 체류 39%→80%, 완전대향 −95° 유지. 이때 `THUMB_OPP_REST` 0.672→**0.20**, `RATIO_HI` 1.4→**0.62**, `GAIN` 1.5→**3.9**가 세트로 따라간다(값 스케일이 달라져 옛 상수를 남기면 대향이 아예 안 걸림). ⚠️ 상수는 **실측 분포에서 직접** 잡을 것 — 옛 프록시에서 역산하면 tan 발산 때문에 상단이 부풀어 2배 넘게 빗나간다(1차 시도에서 HI를 63°로 잡아 도달률 0%, "대향이 안 움직임" 발생).

### 검지·중지·약지 (손가락 2/3/4)
| 관절 | 프록시 | 매핑 |
|---|---|---|
| **n_1** abd | `_abduction`(중지 근위지골 9→10 기준 좌우 벌림, 부호각) | **1:1 signed** × `ABD_GAIN`(1.0), clamp. raw=0(중지 평행)→0°. **게이트 해제됨** |
| **n_2** mcp | `_bend`(손목·MCP·PIP) | 굽힘 1:1, clamp |
| **n_3** pip | `_bend`(MCP·PIP·DIP) | 굽힘 1:1, clamp |
| **n_4** dip | **`DIP_PIP_COUPLING(0.75) × n_3(PIP)`** — 측정 안 함 | PIP에서 유도 |
- **n_4(DIP)를 왜 유도하나**(2026-07-21): DIP·TIP의 z(깊이)가 MediaPipe에서 부실해 측정 굽힘이 노이즈투성이(격리 검증: 2_4·3_4·4_4 "z로 잘 추정 못함"). 해부학상 DIP는 신전건 메커니즘으로 PIP에 종속(사람도 DIP만 독립굴곡 불가)이라 `0.75×PIP`로 유도하는 게 강건. `DIP_PIP_COUPLING`으로 튜닝.
- 중지 3_1(middle_abd)은 벌림 **기준축**이라 항상 ≈0.

### 새끼 (손가락 5) — 구조 특이
| 관절 | 프록시 | 매핑 |
|---|---|---|
| **5_1** pinky_cmc | `_palm_fold`(요측/척측 손바닥평면 이면각) | 손바닥접기(cupping). **현재 게이트(중립 0° 고정)** — 굽힘 crosstalk 과증폭으로 막아둠 |
| **5_2** pinky_lat | `_abduction`(PINKY) | 측면 벌림. 1:1, clamp[−12,12]°. ⚠️MediaPipe 새끼 노이즈·crosstalk 커서 추정 약함 |
| **5_3** pinky_mcp | `_bend`(손목·MCP·PIP) | 굽힘 1:1 |
| **5_4** pinky_pip | **`(1+DIP_PIP_COUPLING)=1.75 × PIP`** | 로봇은 원위관절 1개뿐 → 사람 PIP+DIP 합을 PIP에서 유도(옛 `(PIP+측정DIP)/2`는 DIP 부실로 과소평가) |

## 왼손 모델 사용

씬을 왼손 결합 모델(`ur5e_dg5f_left`)로, 스크립트에 `left` 인자:
```bash
python vision_node_dg5f.py left      # 웹캠에도 왼손을 보여줄 것(미러 텔레옵)
python probe_sender.py fist left
```
`dg5f_angles.LEFT_MIRROR_CHANNELS`에 든 채널만 부호 반전: `thumb_opp, thumb_mcp, thumb_ip, index_abd, middle_abd, ring_abd, pinky_cmc, pinky_lat`.
**thumb_cmc(1_1)은 제외** — `|abd|` 매핑이 왼손각을 직접 산출하므로 또 반전하면 안 됨(우수 모델은 `THUMB_CMC_FOLD_DEG/SPREAD_DEG` 부호를 뒤집을 것).
보정은 좌우 공용(굽힘 크기만 잼) — 실제 쓸 손으로 하는 게 정확.

## Unity 구동 모드 (Dg5fFingerIKMode.HandDriveMode)

한 드롭다운으로 이 손의 5개 손가락 구동 방식을 일괄 전환(Play 중 실시간):
- **AnatomicalReach** — 해부학 방향 × 펴짐비율 × 방향별 FK 최대도달 테이블 (§26)
- **RobotRootTipVector** — 손목→끝 벡터(v5) × 로봇 손길이
- **ChainRatioReach** — 마디합 비율(3:3 마디 대응, 앵커 n_2 피벗)
- **JointAnglesOnly** — IK 끄고 패킷 관절각 채널로 20관절 직접 구동(실물 Tesollo SDK와 동일 인터페이스, 트윈/실물 비교용)

엄지는 별도 IK(손끝 위치 목표) 옵션 있음 — 채널별 매핑으로 재현 어려운 결합운동(대향×굽힘) 대응. IK 세부는 `Dg5fFingerIK.cs`/`Dg5fThumbIK` 참조.

**관절 격리 디버그**: `Dg5fHandDriver.isolateJoint` 드롭다운 — 한 관절만 수신값으로 움직이고 나머지 19개는 0(중립)으로 얼려 관절별 눈검증. `None_전체동작`이면 정상 구동.

## 검증 상태 (2026-07-21)

- ✅ 배선 결정적 검증(probe_sender): fist/open 패킷 → 20관절 xDrive.target 기대값 일치.
- ✅ 전관절 격리 눈검증 완료: 엄지 4채널 역할·방향 확정, 손가락 굽힘/벌림 역할 확정.
- ✅ 엄지 1_1 방향 근본수정(|abd| 양방향), 손가락 DIP-PIP 결합(rhand `c71a31a`).
- ⬜ 라이브 재확인 대기: ① 1_1 벌림/접힘 방향·범위 체감(반대면 `THUMB_CMC_*` 조정) ② 1_2 대향 **중립/도달**(새 공식 상수 `THUMB_OPP_REST=0.40`·`RATIO_HI=1.10` 라이브 1회 확인 — 중립에서 엄지 뻗으면 REST↑, 끝까지 못 가면 RATIO_HI↓. 방향이 **양손 다** 반대면 `THUMB_OPP_SIGN=-1.0`, 한쪽만이면 `THUMB_OPP_HAND_SIGN`) ③ DIP 결합계수(0.75)·새끼 5_4 게인 ④ 5_1 게이트 해제 여부 ⑤ 검지 PIP(2_3)·새끼 5_2 추정 약함(MediaPipe 한계).

## 주의

- Unity Play 중 같은 포트(5006)에 로컬 테스트 수신기 띄우지 말 것(패킷 뺏김 — SVH 함정).
- IK/파지 수동 실험 시 `Dg5fHandDriver.enableTracking` 끄기(매 프레임 덮어씀).
- ⚠️ **프리팹/씬 직렬화가 코드 기본값을 이길 수 있음** — 인스펙터 값 확인(maxStepDeg·lerpSpeed 사건 전례).
- vision 로그는 실행마다 새 파일(`logs/vision_dg5f_YYYYMMDD_HHMM.csv`) — truncate 함정 방지.
- 보정은 반드시 `calibrate_dg5f.py`로(vision_node 로그는 clamp된 값이라 역산 불가). 단 thumb_cmc(1_1)·DIP는 이제 보정값을 매핑에 쓰지 않음(1_1=상수 범위, DIP=PIP 유도).
