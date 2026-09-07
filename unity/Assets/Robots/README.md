# `Assets/Robots/` — 임포트된 로봇 자산 (생성물)

URDF에서 임포트한 **로봇 메시·프리팹**이 들어 있다. 대부분 도구가 만든 산출물이므로
**손으로 편집하지 않는다.** 바꾸고 싶으면 URDF를 고치고 임포트 메뉴를 다시 실행한다.

## 구조

```text
Assets/Robots/
├── Editor/CreateUr16eDg5fRightPrefab.cs   Preview 씬의 로봇 → 프리팹 추출
├── Prefabs/                               ★ 다른 코드가 참조하는 로봇 원본
│   ├── ur16e_dg5f_right.prefab               현역 (학습 씬 빌더의 입력)
│   ├── ur5e_dg5f_right.prefab                구세대
│   ├── ur5e_dg5f_left.prefab                 구세대 (GraspLift 기준)
│   └── dg5f_{right,left,right_short,left_short}.prefab   손 단독 4변형
├── ur16e_dg5f_right/meshes/…              현역 로봇의 메시 프리팹
├── ur5e_dg5f_{right,left}/meshes/…        구세대
└── dg5f_{right,left,right_short,left_short}/meshes/…     손 단독
```

`meshes/` 아래의 `*_c.prefab`은 **충돌(collision) 메시**를 담은 프리팹이다
(`_c` = collision). vHACD로 볼록 분해된 결과물이라 파일 수가 많다.

## 프리팹 하나만 기억하면 된다

```text
Assets/Robots/Prefabs/ur16e_dg5f_right.prefab
```

`PicknPlaceTrainingSceneBuilder.SourceRobotPath`가 이 경로를 **상수로** 참조한다.
**파일을 옮기거나 이름을 바꾸면 학습 씬 빌더가 깨진다.**

## 생성 경로

```text
urdf/build_arm_hand.py                     결합 URDF 생성
  → KDT > Import UR16e+DG5F-Right Preview Scene    URDF → 씬 (메시가 여기 복사된다)
  → KDT > Preview Scene에 조작 컴포넌트 추가
  → Tools > Robots > Create UR16e DG5F Right Prefab   씬의 로봇 → Prefabs/ 저장
  → Tools > ML-Agents > Build DG5F PicknPlace Training Scene
```

`CreateUr16eDg5fRightPrefab.cs` (67줄)의 고정 경로:

| 상수 | 값 |
|---|---|
| `ScenePath` | `Assets/Scenes/UR16eDG5FRight_Preview.unity` |
| `PrefabPath` | `Assets/Robots/Prefabs/ur16e_dg5f_right.prefab` |

**씬 자체는 건드리지 않고** 로봇만 프리팹으로 뽑는다.

## 링크 이름 규칙 (구동 코드가 의존한다)

| 손 | 접두사 | 예 |
|---|---|---|
| 오른손 | `rl_` | `rl_dg_palm`, `rl_dg_2_3`, `rl_dg_1_tip` |
| 왼손 | `ll_` | `ll_dg_palm`, `ll_dg_2_3` |

- `Dg5fHandDriver`는 접미사 `_dg_<손가락1~5>_<마디1~4>`로 관절을 찾는다 — **위치가 아니라 이름 매칭**.
- `PicknPlacePipelineDemoSceneBuilder`는 손 루트가 `rl_dg_palm`인지 확인하고
  `ll_dg_palm`(왼손)이면 **거부한다** — 구세대 프리팹으로 데모를 만드는 사고 방지.

## 손대기 전에 확인할 것

1. **프리팹을 직접 수정하면 다음 임포트 때 사라진다.** 물리값·드라이브 게인은
   `tools/urdf_hand_import/setup_drive.py`나 씬 빌더가 코드로 설정한다.
2. **임포터 기본 관성 함정** — URDF에 `<inertial>`이 없는 링크는 임포터가 1kg/(1,1,1)로
   채운다. 이 값은 진동의 원인이다. 임포트 후
   `tools/urdf_hand_import/phys_compare.py`로 URDF 원본과 전수 대조한다.
3. **구세대 프리팹(`ur5e_*`)은 참고용**이다. 새 작업은 `ur16e_dg5f_right`로 한다.

## 관련 문서

- [`unity/README.md`](../../README.md) §6 — 자산 생성 전체 절차
- [`urdf/README.md`](../../../urdf/README.md) — 결합 URDF와 링크 이름 규칙
- [`tools/urdf_hand_import/README.md`](../../../tools/urdf_hand_import/README.md) — 임포트·물리 검증
- [`unity/Assets/MLAgents/README.md`](../MLAgents/README.md) §8 — 씬 빌더가 참조하는 고정 경로

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/Assets/Robots/README.md`
- **갱신 대상**: `unity/Assets/Robots/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `urdf/README.md`, `unity/Assets/MLAgents/README.md` §8
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

