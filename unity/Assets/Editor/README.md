# `Assets/Editor/` — 로봇 임포트·검수용 에디터 메뉴

**Play 하지 않고 Unity 상단 메뉴에서 실행하는 스크립트들**이다. 씬 파일을 손으로 편집하는
대신 이걸 다시 돌리는 것이 이 저장소의 규칙이다.

여기 있는 것은 **로봇 자산 준비 단계**의 도구다. 학습 씬·플레이어 빌드는
[`Assets/MLAgents/`](../MLAgents/README.md)의 에디터 도구가 담당한다.

## 파일 3개

| 파일 | 줄 수 | 메뉴 | 하는 일 |
|---|---|---|---|
| `ImportUr16eDg5fRightPreview.cs` | 46 | `KDT > Import UR16e+DG5F-Right Preview Scene` | 결합 URDF를 임포트해 Preview 씬을 만든다 |
| `SetupPreviewSceneControls.cs` | 59 | `KDT > Preview Scene에 조작 컴포넌트 추가` | 그 씬 로봇에 슬라이더 UI·자기충돌 무시를 붙인다 |
| `DG5FVariantSwitcher.cs` | 77 | `Tools > DG5F > Right / Right Short / Left / Left Short` | 씬의 손을 오른손/왼손/숏 변형으로 교체 |

세 파일 모두 `public static class` + `[MenuItem]` 형태이며, 진입점은 `Run()`이다.

## 각 스크립트 상세

### `ImportUr16eDg5fRightPreview.cs`

입력은 [`urdf/ur16e_dg5f_right_build/`](../../../urdf/README.md)의 결합 URDF다.
URDF-Importer 패키지(`com.unity.robotics.urdf-importer`)를 호출해 `ArticulationBody` 계층을
만들고 `Assets/Scenes/UR16eDG5FRight_Preview.unity`에 배치한다.

**실행 전 확인**: `urdf/ur16e_dg5f_right_build/ur16e_dg5f_right.urdf`가 존재해야 한다.
없으면 `python urdf/build_arm_hand.py`를 먼저 돌린다.

### `SetupPreviewSceneControls.cs`

임포트 직후 로봇은 **그냥은 못 쓴다.** 이 메뉴가 그 격차를 메운다.

- `HandSliderUI` — 화면 슬라이더로 관절을 직접 돌려 검수
- `RobotSelfCollisionIgnore` — 인접 마디 겹침으로 인한 **접촉 진동** 방지
- (필요 시) `RobotInitialPoseSync` — Play 시작 시 채찍질 방지

각 컴포넌트의 의미는 [`Assets/Scripts/README.md`](../Scripts/README.md) §3에 있다.

### `DG5FVariantSwitcher.cs`

씬의 현재 손을 **같은 위치·같은 부모로** 교체한다. 손 변형 4종을 눈으로 비교할 때 쓴다.

```csharp
static readonly string[] VariantNames = { …dg5f_right, dg5f_right_short, dg5f_left, dg5f_left_short… };
```

새 핸드 계열을 추가하면 **이 배열에 이름을 추가**하면 된다.
변형 이름의 정본은 `config/rtauto_config.py`의 `dg5f_variant()`다.

## 이웃 폴더의 에디터 스크립트

| 위치 | 메뉴 | 하는 일 |
|---|---|---|
| `Assets/Robots/Editor/CreateUr16eDg5fRightPrefab.cs` | `Tools > Robots > Create UR16e DG5F Right Prefab` | Preview 씬의 로봇을 프리팹으로 추출 |
| `Assets/MLAgents/picknplace/Editor/` | `Tools > ML-Agents > …` | 학습 씬·데모 씬 생성, 플레이어 빌드, 자세 진단 |
| `Assets/MLAgents/Editor/` | (메뉴 없음) | 빌드 경로 어댑터, Linux 후처리 |

## 따라 하기

새 PC에서 자산을 만드는 전체 순서는 [`unity/README.md`](../../README.md) §6에 있다.
이 폴더의 메뉴는 그중 1~3단계에 해당한다.

각 메뉴를 실행한 뒤 **Console 창**(`Window > General > Console`)에 빨간 에러가 없는지
확인하고 다음으로 넘어간다.

## 관련 문서

- [`unity/README.md`](../../README.md) — 메뉴 전체 경로와 실행 순서
- [`urdf/README.md`](../../../urdf/README.md) — 임포트 입력이 되는 결합 URDF
- [`tools/urdf_hand_import/README.md`](../../../tools/urdf_hand_import/README.md) — 명령줄 임포트 도구
- [`docs/modules/UNITY.md`](../../../docs/modules/UNITY.md) §6 — 에디터 툴 표

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/Assets/Editor/README.md`
- **갱신 대상**: `unity/Assets/Editor/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `unity/README.md` §5
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

