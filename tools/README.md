# `tools/` — 파이프라인 밖의 보조 도구

학습·시연 경로에는 들어가지 않지만 **로봇 자산을 만들고, 결과를 그림으로 뽑고, 개발 PC 환경을
손보는** 데 쓰는 스크립트 모음이다. 매일 돌리는 것이 아니라 "필요할 때 한 번" 쓰는 도구들이라
각각 어떤 상황에서 꺼내 쓰는지부터 적는다.

## 목차

1. [한눈에 보기](#1-한눈에-보기)
2. [`urdf_hand_import/` — URDF를 Unity 로봇으로](#2-urdf_hand_import--urdf를-unity-로봇으로)
3. [`plot_grasp_lift_curves.py` — 학습 곡선 그래프](#3-plot_grasp_lift_curvespy--학습-곡선-그래프)
4. [`plot_grasp_lift_slides.py` — 발표용 그림 2장](#4-plot_grasp_lift_slidespy--발표용-그림-2장)
5. [`unity_firewall_toggle.*` — Unity 방화벽 토글](#5-unity_firewall_toggle--unity-방화벽-토글)
6. [관련 문서](#6-관련-문서)

## 1. 한눈에 보기

| 경로 | 언제 쓰나 | 실행 환경 |
|---|---|---|
| `urdf_hand_import/` | 새 URDF 로봇을 Unity에 넣을 때 (임포트 → 물리 검증 → 구동 준비 → 움직임 검증) | Python + Unity 에디터 + unity-cli |
| `plot_grasp_lift_curves.py` | 학습 런들의 곡선을 한 장에 비교할 때 | Python (matplotlib, tensorboard) |
| `plot_grasp_lift_slides.py` | 발표 자료용 그림 2장을 뽑을 때 | 〃 |
| `unity_firewall_toggle.ps1` / `.bat` | 다른 PC에서 UDP를 받아야 할 때 잠깐 방화벽을 열 때 | **Windows 전용**, 관리자 권한 |

## 2. `urdf_hand_import/` — URDF를 Unity 로봇으로

전용 README가 있다: [`tools/urdf_hand_import/README.md`](urdf_hand_import/README.md).
여기서는 **어떤 순서로 무엇이 나오는지**만 요약한다.

```text
① import_hand.py   URDF·메시 복사 + package:// 경로 패치 + URDF-Importer 실행 + 감사 + 프리팹 저장
② phys_compare.py  Unity에 들어간 물리값 ↔ URDF 원본 전수 대조 (질량·CoM·관성·리밋·토크)
③ setup_drive.py   드라이브 게인 + 중력 off + 루트 고정 + 자기충돌 무시·초기포즈 동기화 부착 (멱등)
④ probe_test.py    전 관절 사각파 → 정착오차·잔여진동·리밋 침범 자동 판정
```

| 단계 | 핵심 인자·판정 상수 |
|---|---|
| ① | `--project` / `--cli` (기본은 `.env`의 `RTAUTO_UNITY_PROJECT` / `RTAUTO_UNITY_CLI`), `--name`, `--prefab`, `--remove-instance`, `--verify`, `--no-vhacd` |
| ② | `MASS_TOL 1e-3 kg` · `COM_TOL 1e-4 m` · `INERTIA_RTOL 2%` · `LIM_TOL 0.1°`. PhysX 최소 관성 클램프(`1e-6`)는 **WARN으로 분리**. 리밋 부호 반전(flip)도 정상으로 인정 |
| ③ | `--stiffness 10000` · `--damping 200` · `--force-limit 100000` · `--components` |
| ④ | `SETTLE_TOL 1.0°` · `P2P_TOL 0.5°` · `LIMIT_MARGIN 0.5°`(침범 0건). 사각파 `--phases 8` × `--phase-dur 1.5s` |

> **`--force-limit 100000`은 의도된 타협이다.** URDF의 실제 토크값(예: 7.5 N·m)을 넣으면
> stiffness 10000 기준 오차 0.04°에도 토크가 포화돼 **뱅뱅 진동**이 난다. 그래서 사실상
> 무제한으로 올리고 **하드웨어 토크 상한 재현을 포기**했다. 실물 이관 때 다시 봐야 할 지점이다.
>
> ⚠️ 이 값들은 **범용 도구의 기본값**이다. 현재 PicknPlace 학습 씬은 별도로 드라이브를 설정하며
> 팔은 `UrArmLimits.MaxEffortNm`, 손은 `Dg5fPicknPlaceSpec.HandDriveForceLimit`(20)를 쓴다.
> 범용 도구의 값을 학습 물리값으로 착각하지 않는다.

## 3. `plot_grasp_lift_curves.py` — 학습 곡선 그래프

TensorBoard 이벤트 파일을 읽어 **누적 보상 / 성공률 / 에피소드 길이** 3단 패널 PNG를 만든다.

```text
python tools/plot_grasp_lift_curves.py [run_id ...] [-o out.png] [--smooth 0.6]
```

| 항목 | 값 |
|---|---|
| 입력 | `training/results/<run_id>/` 아래 이벤트 파일 |
| behavior | `DG5FGraspLift` (상수 `BEHAVIOR`) |
| 기본 출력 | `docs/images/dg5f_grasp_lift_curves.png` |
| 패널(`PANELS`) | `Environment/Cumulative Reward` · `GraspLift/Success` · `Environment/Episode Length` |
| 스무딩 | 지수 이동평균, 기본 가중치 0.6 (`--smooth`) |

`run_id`를 생략하면 `DEFAULT_RUNS`의 5개 런(배포 h012 + top-down 계수 스윕 t1~t4)을 그린다.

- 백엔드를 `Agg`로 고정해 **화면 없이(headless) 실행된다.**
- ⚠️ 이 스크립트는 **GraspLift(구세대, UR5e+왼손) 태그 전용**이다. 현역 PicknPlace의
  태그는 `PicknPlace/*`이므로 그대로는 그려지지 않는다.

## 4. `plot_grasp_lift_slides.py` — 발표용 그림 2장

```text
python tools/plot_grasp_lift_slides.py
```

인자 없이 실행하며 `docs/images/` 아래에 두 장을 만든다.

| 출력 | 내용 |
|---|---|
| `dg5f_grasp_lift_slide_training.png` | 배포 정책(`dg5f_grasp_lift_h012_topdown`)의 학습 곡선 |
| `dg5f_grasp_lift_slide_tradeoff.png` | top-down 계수 스윕의 **자세 vs 신뢰성 트레이드오프** |

트레이드오프 그림의 x축(`SWEEP`)은 `topdown_potential_max` 값이다 —
배포(0.30, spec 기본값) / T1(1.50) / T3(2.25) / T2(3.00) 순으로 배치해 "계수를 올릴수록
자세는 좋아지지만 성공률이 떨어지는" 지점을 보여준다. `tail_mean(run, tag, n=10)`으로
각 런의 마지막 10개 요약값 평균을 쓴다.

발표용이라 색상이 상수로 고정돼 있다: `INK #1b1b1f` / `ACCENT #2563eb` / `WARN #dc2626` / `GRID #d4d4d8`.

## 5. `unity_firewall_toggle.*` — Unity 방화벽 토글

**Windows 전용.** Unity Editor의 **공용(Public) 프로필 인바운드 규칙**을 허용 ↔ 차단으로
토글한다. 다른 PC에서 UDP(손 각도 등)를 받아야 할 때만 잠깐 열고, 끝나면 다시 닫는 용도다.

| 파일 | 역할 |
|---|---|
| `unity_firewall_toggle.bat` | 더블클릭 진입점. PowerShell 스크립트를 `-ExecutionPolicy Bypass`로 호출 |
| `unity_firewall_toggle.ps1` | 실제 로직. 관리자 권한이 아니면 **UAC 창을 띄워 자기 자신을 재실행** |

동작 상세:

- 대상 규칙 이름은 `$ruleName = "Unity 6000.4.0f1 Editor"`. **Unity 버전을 올리면 이 문자열도
  바꿔야 한다.**
- `Get-NetFirewallRule`로 Public 프로필 규칙을 찾고, 현재 `Action`이 `Allow`면 `Block`으로,
  아니면 `Allow`로 뒤집는다.
- 같은 이름 규칙이 Domain/Public 두 프로필에 중복 존재할 수 있어, `netsh`의 이름+프로필 텍스트
  매칭 대신 **이미 고유하게 식별된 객체에 `Set-NetFirewallRule`을 직접 건다.** CIM 경로가
  실패하면 `netsh`로 한 번 더 시도한다(fallback).
- 규칙을 찾지 못하면 빨간 글씨로 안내만 하고 아무것도 바꾸지 않는다.

**따라 하기 (Windows 탐색기)**: `tools/unity_firewall_toggle.bat`을 더블클릭 →
UAC 창에서 "예" → 콘솔에 바뀐 상태가 출력된다. 테스트가 끝나면 **다시 한 번 실행해 닫는다.**

## 6. 관련 문서

- [`tools/urdf_hand_import/README.md`](urdf_hand_import/README.md) — 임포트 도구 상세(정본)
- [`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) §3·§4 — 임포트·기타 도구
- [`docs/modules/RL_TRAINING.md`](../docs/modules/RL_TRAINING.md) — 그래프에 쓰이는 태그의 의미
- [`urdf/README.md`](../urdf/README.md) — 임포트 이전 단계(결합 URDF 생성)

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- tools/README.md`
- **갱신 대상**: `tools/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/BUILD_TOOLING.md`, `docs/images/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

