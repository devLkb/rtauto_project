# `training/test-results/` — Unity 테스트 실행 결과(NUnit XML)

Unity **Test Runner**를 배치모드로 돌렸을 때 나오는 NUnit XML 보고서를 보관한다.
사람이 직접 만드는 파일이 아니라 **실행 산출물**이며, "그때 무엇을 어떻게 확인했는가"의 증거로 남긴다.

## 파일 이름 규칙

```text
grasplift-<모드>[-<목적>][-<날짜-시각>].xml
```

| 조각 | 뜻 |
|---|---|
| `editmode` / `playmode` | Unity 테스트 모드. EditMode는 로봇 없이 순수 계산, PlayMode는 씬을 실제로 돌린다 |
| `spawn-baseline` / `spawn-fixed` / `spawn-precision` / `spawn-restored` | 스폰 관련 수정 전후 비교 세트 |
| `topple` / `promote` / `verify` / `sweep` | 각각 전도 판정, 승급, 검증, 스윕 실험 |
| `v2` / `v3` / `h` | 계약 버전·변형 |
| `20260729-0310` 등 | 실행 시각 |

이름이 곧 **무엇을 확인하려던 실행인지**를 말한다. 예를 들어
`grasplift-playmode-spawn-baseline-20260729.xml`과 `…-spawn-fixed-20260729.xml`은
같은 날 스폰 수정 전후를 비교한 한 쌍이다.

## 읽는 법

NUnit XML의 루트 `<test-run>` 요소에 요약이 들어 있다.

```bash
grep -o 'result="[^"]*"' training/test-results/grasplift-playmode.xml | head -1
grep -oE 'total="[0-9]+" passed="[0-9]+" failed="[0-9]+"' training/test-results/grasplift-playmode.xml | head -1
```

실패한 케이스만 보려면:

```bash
grep -B2 'result="Failed"' training/test-results/<파일>.xml | head -40
```

## 결과를 새로 만들려면

Unity 에디터에서는 `Window > General > Test Runner`를 열고 EditMode / PlayMode 탭에서
**Run All**을 누른다. 배치모드로 XML을 뽑으려면:

```bash
"$UNITY_EDITOR" -batchmode -projectPath unity \
    -runTests -testPlatform PlayMode \
    -testResults training/test-results/<이름>.xml \
    -logFile unity_batch_logs/test_playmode.log
```

```powershell
& "C:/Program Files/Unity/Hub/Editor/6000.4.0f1/Editor/Unity.exe" -batchmode -projectPath unity `
    -runTests -testPlatform EditMode `
    -testResults training/test-results/<이름>.xml `
    -logFile unity_batch_logs/test_editmode.log
```

- Unity Editor를 **닫고** 실행한다 — 한 프로젝트를 두 번 열지 못한다.
- `-testPlatform`은 `EditMode` 또는 `PlayMode`.
- 파일 이름에 **목적과 날짜**를 넣는다. 그래야 나중에 비교 쌍을 알아볼 수 있다.

## 주의

- 여기 XML은 **`GraspLift`(구세대) 시절 실행 결과**가 대부분이다. 현역 PicknPlace의 최신
  상태를 보여주지 않는다.
- **파일이 있다는 것이 지금도 통과한다는 뜻은 아니다.** 날짜를 확인하고, 필요하면 다시 돌린다.

## 관련 문서

- [`unity/Assets/MLAgents/README.md`](../../unity/Assets/MLAgents/README.md) §9 — 어떤 테스트가 무엇을 검증하나
- [`training/tests/README.md`](../tests/README.md) — 파이썬 쪽 회귀 테스트
- [`unity/README.md`](../../unity/README.md) §8 — 배치모드 실행 형식

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- training/test-results/README.md`
- **갱신 대상**: `training/test-results/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `unity/Assets/MLAgents/README.md` §9
- **용어는 [`GLOSSARY`](../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

