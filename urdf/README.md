# `urdf/` — 로봇 모델(URDF)과 결합 빌더

시뮬레이션과 실물이 **같은 로봇 치수**를 쓰게 만드는 폴더다.
UR 팔의 공식 description과 Tesollo DG5F 손 URDF를 **하나의 결합 URDF로 합쳐**
Unity 임포트 소스를 만든다.

- **입력**: 외부 UR description 레포(xacro) + `urdf/dg5f/`의 손 URDF·메시
- **출력**: `urdf/ur16e_dg5f_right_build/` — 결합 URDF + 실제 메시 파일
- **다음 단계**: Unity 에디터 메뉴로 임포트 → 로봇 프리팹 → 학습 씬

## 목차

1. [폴더 구조](#1-폴더-구조)
2. [URDF가 무엇이고 왜 결합하는가](#2-urdf가-무엇이고-왜-결합하는가)
3. [`build_arm_hand.py` — 5단계 파이프라인](#3-build_arm_handpy--5단계-파이프라인)
4. [실행 인자](#4-실행-인자)
5. [산출물 상세](#5-산출물-상세)
6. [손 URDF 4변형과 링크 이름 규칙](#6-손-urdf-4변형과-링크-이름-규칙)
7. [따라 하기: 결합 URDF 다시 만들기](#7-따라-하기-결합-urdf-다시-만들기)
8. [알려진 함정](#8-알려진-함정)
9. [관련 문서](#9-관련-문서)

## 1. 폴더 구조

```text
urdf/
├── build_arm_hand.py              결합 빌더 (240줄) — 이 폴더의 유일한 실행 코드
├── dg5f/                          손 단독 URDF 4변형 + 메시 (입력)
│   ├── dg5f_right.urdf            링크 28 / 조인트 27
│   ├── dg5f_left.urdf
│   ├── dg5f_right_short.urdf
│   ├── dg5f_left_short.urdf
│   └── meshes/{dg5f_right,dg5f_left,dg5f_right_short,dg5f_left_short}/
│                                  시각용 .dae + 충돌용 _c.STL
└── ur16e_dg5f_right_build/        ★ 현재 쓰는 산출물 (Unity 임포트 소스)
    ├── ur16e_dg5f_right.urdf      링크 41 / 조인트 40  ← 결합 결과
    ├── ur16e_raw.urdf             링크 13 / 조인트 12  ← xacro를 편 중간 산출물
    └── meshes/
        ├── ur/ur10e/{visual,collision}/   ⚠️ ur16e가 공유하는 링크(§8)
        ├── ur/ur16e/{visual,collision}/   ur16e 고유 링크(upperarm, forearm)
        └── dg5f_right/                    손 메시
```

`urdf/dg5f/`는 **손만** 들어 있는 원본이고, `ur16e_dg5f_right_build/`는 팔+손을 합친
**생성물**이다. 생성물을 손으로 고치지 말고 빌더를 다시 돌린다.

## 2. URDF가 무엇이고 왜 결합하는가

URDF는 로봇의 **링크(강체)·조인트(관절)·질량·관성·가동범위·메시 경로**를 적은 XML 모델
파일이다. Unity는 URDF-Importer 패키지로 이 파일을 읽어 `ArticulationBody` 계층을 만든다.

팔과 손이 따로 있으면 Unity에서 두 로봇을 수동으로 붙여야 하고, 그 접합부 좌표가 사람 손에
달린 값이 된다. **결합 URDF는 그 접합을 파일 하나에 못 박아** 어느 PC에서 임포트해도 같은
로봇이 나오게 한다(원칙 2 — 새 머신 부트스트랩 보장).

접합 규칙은 하나다.

```text
UR의 tool0  ──(fixed joint "tool0_to_dg_mount", origin 0, rpy 0)──▶  <접두사>dg_mount
```

DG5F가 플랜지 마운트를 자체 보유하고 있어 오프셋이 0이다.

## 3. `build_arm_hand.py` — 5단계 파이프라인

함수 이름이 곧 단계 이름이다.

| 단계 | 함수 | 하는 일 |
|---|---|---|
| ① | `flatten_ur(ur_share, ur_type, out)` | UR description의 `ur.urdf.xacro`를 **단일 URDF로 편다**(`ur16e_raw.urdf`) |
| ② | `rewrite_mesh(root, from, to)` | `package://` URI를 **상대경로**로 치환 |
| ③ | `copy_meshes(pairs, build_dir)` | URDF가 **실제로 참조하는 하위폴더만** 복사 |
| ④ | `merge(...)` | 두 URDF의 자식 노드를 합치고 `tool0_to_dg_mount` fixed 조인트로 연결 |
| ⑤ | `verify(new_root, ...)` | 링크·조인트 개수, 중복, 도달성, 손끝 5개, inertial 누락 검사 |

### ① `flatten_ur` — ROS 없이 xacro 펴기

xacro는 보통 ROS의 `ament_index_python`으로 패키지 경로를 찾는다. 이 스크립트는 **가짜
모듈을 `sys.modules`에 주입**해 ROS 설치 없이 xacro를 돌린다. `get_package_share_directory`가
`ur_description`에 대해서만 사용자가 준 경로를 돌려주고 나머지는 `PackageNotFoundError`를 낸다.

> 주입 뒤에 `import xacro`를 해야 한다 — 순서가 바뀌면 진짜 ament를 찾다 실패한다.

### ② `rewrite_mesh` — 경로 규약

| 원본 | 치환 후 |
|---|---|
| `package://ur_description/meshes/…` | `meshes/ur/…` |
| `package://meshes/<변형>/…` | `meshes/<변형>/…` |

Unity `import_hand.py`가 **URDF 파일 기준 상대경로**로 메시를 해석하기 때문에 이 형태여야 한다.
치환 개수를 로그로 찍는다(`[mesh] 경로 패치: UR N개, DG5F M개`).

### ③ `copy_meshes` — 파일 크기 비교 후 복사

`src.stat().st_size != dst.stat().st_size`일 때만 복사한다. 재실행이 싸고 **멱등**이다.
빌드 폴더 자체가 임포트 소스이므로 메시 실파일이 반드시 함께 있어야 한다.

### ④ `merge` — 중복 material 제거와 접합

- UR 루트(`world ~ tool0`)와 DG5F 루트(`<prefix>dg_mount ~ <prefix>dg_5_tip`)의 자식을 순서대로 붙인다.
- `<material name=…>`은 두 URDF에 같은 이름이 있을 수 있어 **처음 것만 남긴다**(`seen_materials`).
- 결과 로봇 이름은 `<ur_type>_<variant>` (예: `ur16e_dg5f_right`).
- 마지막에 `tool0_to_dg_mount` fixed 조인트를 추가한다.

### ⑤ `verify` — 무엇을 검사하나

| 검사 | 통과 기준 | 왜 |
|---|---|---|
| 중복 링크명 | 0건 | 이름 매칭 구동 코드가 엉뚱한 관절을 잡는다 |
| `world`에서 도달 | 전 링크 도달 | 끊긴 링크는 Unity에서 떠다니는 조각이 된다 |
| 손끝 5개(`<prefix>dg_1_tip`~`dg_5_tip`) | 전부 도달 | 파지 판정·IK가 손끝 Transform을 참조한다 |
| `inertial` 없는 링크 | **목록만 출력**(실패 아님) | Unity 임포터가 기본 1kg/(1,1,1)을 넣는 함정. 후처리로 메워야 한다 |
| revolute 조인트 개수 | 로그 출력 | DG5F는 mimic이 없어 20관절 전부 독립 |

## 4. 실행 인자

```text
python urdf/build_arm_hand.py [--ur-type ur16e] [--hand right|left] [--short]
                              [--ur-description <경로>] [--out-dir <경로>]
```

| 인자 | 기본값(출처) | 설명 |
|---|---|---|
| `--ur-type` | `cfg.UR_TYPE` = `.env` `RTAUTO_UR_TYPE`(ur16e) | UR 기종 |
| `--hand` | `cfg.DG5F_HAND` = `RTAUTO_DG5F_HAND`(right) | 손 좌우 |
| `--short` | `cfg.DG5F_SHORT` = `RTAUTO_DG5F_SHORT`(0) | short 변형 사용 |
| `--ur-description` | `cfg.UR_DESCRIPTION` = `RTAUTO_UR_DESCRIPTION` | **외부 UR description 레포 경로**(저장소에 포함하지 않음) |
| `--out-dir` | `urdf/<ur_type>_<variant>_build/` | 출력 폴더 |

**기본값이 전부 `.env`에서 온다**는 점이 핵심이다 — 명령줄에 경로를 손으로 적기 시작하면
새 PC에서 반드시 어긋난다(원칙 1).

## 5. 산출물 상세

| 파일 | 링크 | 조인트 | 설명 |
|---|---|---|---|
| `ur16e_raw.urdf` | 13 | 12 | xacro를 편 UR16e 단독. 중간 산출물이며 임포트 대상이 아니다 |
| `ur16e_dg5f_right.urdf` | 41 | 40 | **임포트 대상.** UR16e 6축 + DG5F 20축 + fixed 접합 |
| `meshes/ur/…` | — | — | UR 시각(.dae)·충돌(.stl) 메시 |
| `meshes/dg5f_right/…` | — | — | 손 시각(.dae)·충돌(`*_c.STL`) 메시 |

## 6. 손 URDF 4변형과 링크 이름 규칙

| URDF | 변형 이름 | 링크 접두사 |
|---|---|---|
| `dg5f_right.urdf` | `dg5f_right` | `rl_` |
| `dg5f_left.urdf` | `dg5f_left` | `ll_` |
| `dg5f_right_short.urdf` | `dg5f_right_short` | `rl_` |
| `dg5f_left_short.urdf` | `dg5f_left_short` | `ll_` |

링크 이름은 `<접두사>dg_<손가락 1~5>_<마디 1~4>` 형태이고, 손끝은 `<접두사>dg_<손가락>_tip`이다.
**Unity의 `Dg5fHandDriver`는 이 접미사 `_dg_<f>_<j>`로 관절을 찾는다** — 위치 순서가 아니라
이름 매칭이라, 오른손/왼손 프리팹이 같은 C# 코드로 동작한다.

접두사 판정의 정본은 `cfg.dg5f_link_prefix()`이며 URDF 실측으로 확인한 값이다.

## 7. 따라 하기: 결합 URDF 다시 만들기

**사전 준비 (한 번만)** — UR description은 외부 공개 레포라 저장소에 없다. 클론한 뒤
경로를 `.env`에 적는다.

```text
RTAUTO_UR_DESCRIPTION=/home/<사용자>/src/Universal_Robots_ROS2_Description
```

**터미널 1 (bash 또는 PowerShell, 리포 루트, URDF 빌드)**

```bash
source vision/.vision/bin/activate
python urdf/build_arm_hand.py
```

```powershell
.\vision\.vision\Scripts\Activate.ps1
python urdf/build_arm_hand.py
```

정상이면 아래와 같은 로그가 나온다. **`verify`의 항목이 하나라도 `NOT reached`나 중복 링크로
찍히면 임포트하지 말고 먼저 고친다.**

```text
[mesh] 경로 패치: UR 14개, DG5F 56개
[mesh] UR 메시 하위폴더(실참조): ['ur10e', 'ur16e']
[mesh] 복사: 신규 0개
robot name: ur16e_dg5f_right
links: 41 | joints: 40 (revolute 26)
중복 링크명: NONE
world에서 도달: 41 / 41 | 미도달: NONE
  rl_dg_1_tip: OK
  …
inertial 없는 링크(임포트/MJCF 변환 후 관성 보정 필요): ['world', 'base_link', 'ft_frame', 'base', 'flange', 'tool0']
```

**다음 단계 (Unity)** — 산출 폴더가 곧 임포트 소스다.

1. Unity 상단 메뉴 `KDT > Import UR16e+DG5F-Right Preview Scene` 실행
2. `KDT > Preview Scene에 조작 컴포넌트 추가`
3. `Tools > Robots > Create UR16e DG5F Right Prefab`
4. `Tools > ML-Agents > Build DG5F PicknPlace Training Scene`

각 메뉴의 상세는 [`unity/README.md`](../unity/README.md)를 본다.

> ⚠️ **URDF를 고쳤다고 기존 씬·프리팹·플레이어가 자동 갱신되지 않는다.** 위 4단계를 순서대로
> 다시 밟은 뒤 물리 검증(`tools/urdf_hand_import/phys_compare.py`)과 플레이어 재빌드가 필요하다.

## 8. 알려진 함정

1. **UR 메시는 기종 폴더 하나만 복사하면 안 된다.** UR16e는 자기 몸체보다 짧은 링크
   (base/shoulder/wrist 등)를 리치가 비슷한 **ur10e 메시로 공유**한다. 그래서 빌더는
   `--ur-type` 폴더를 통째로 복사하지 않고 **URDF에서 실제 참조를 긁어서** 그 폴더만 복사한다
   (`ur_subfolders`). 실제 산출물에도 `meshes/ur/ur10e/`와 `meshes/ur/ur16e/`가 함께 있다.
2. **`inertial` 없는 링크**는 Unity 임포터가 1kg / (1,1,1) 관성으로 채운다.
   현재 산출물에서는 6개(`world`·`base_link`·`ft_frame`·`base`·`flange`·`tool0`)가 여기 해당하며,
   전부 **좌표 프레임용 가상 링크**라 물리적으로 문제가 되지 않는다. 손·팔의 실제 구동 링크에
   이 목록이 나타나면 그때는 반드시 고쳐야 한다. 이 기본값은
   물리 진동의 원인이 된다. `verify`가 목록을 출력하므로 임포트 후
   `tools/urdf_hand_import/phys_compare.py`로 반드시 대조한다.
3. **DG5F에는 mimic 조인트가 없다.** 20관절이 전부 독립이므로, 다른 그리퍼용 코드를
   가져올 때 mimic 처리를 기대하면 안 된다.
4. **MJCF 관련 언급은 폐기됐다.** MuJoCo 경로는 2026-08-26 결정으로 폐기되고 2026-08-27에
   잔재를 전부 삭제했다. 코드 주석에 남은 MJCF 언급은 **유래 설명일 뿐 의존성이 아니다.**

## 9. 관련 문서

- [`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) §2·§5-4 — 빌더 전체 설명(정본)
- [`tools/urdf_hand_import/README.md`](../tools/urdf_hand_import/README.md) — URDF → Unity 임포트 4단계 도구
- [`unity/README.md`](../unity/README.md) — 임포트 이후 Unity 쪽 절차
- [`config/README.md`](../config/README.md) — `RTAUTO_UR_DESCRIPTION` 등 경로 설정

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- urdf/README.md`
- **갱신 대상**: `urdf/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/BUILD_TOOLING.md`, `tools/urdf_hand_import/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

