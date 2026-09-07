# `build-support/` — Unity 플레이어 빌드 후처리용 벤더링 파일

Unity 학습용 플레이어를 빌드할 때 **빌드 후처리 단계에서 필요한 외부 바이너리**를 담아 두는
폴더다. 실행 코드가 아니라 빌드 산출물에 끼워 넣는 자산이므로, 평소에는 열어 볼 일이 없다.

## 내용

| 경로 | 무엇 | 왜 저장소에 두는가 |
|---|---|---|
| `linux/libdl.so.2` | Linux용 동적 링커 셰임 라이브러리 | Windows·macOS에서 **Linux 플레이어를 크로스 빌드**할 수 있게 한다 |

## 어디서 쓰이나

Unity 에디터 스크립트 [`unity/Assets/MLAgents/Editor/LinuxPlayerPostProcess.cs`](../unity/Assets/MLAgents/Editor/LinuxPlayerPostProcess.cs)가
Linux 플레이어 빌드가 끝난 뒤 이 파일을 산출물 폴더에 주입한다.

```text
Tools > ML-Agents > Build DG5F PicknPlace Linux Player
    → BuildPlayer(Linux)
    → LinuxPlayerPostProcess  ← 여기서 build-support/linux/libdl.so.2를 복사
    → training/builds/…/DG5FPicknPlace.x86_64  (실행 가능)
```

이 후처리가 없으면 일부 Linux 배포판에서 플레이어가 `libdl.so.2`를 찾지 못해 기동에 실패한다.

## 손대기 전에 알아둘 것

- **이 파일을 지우면 Linux 플레이어 빌드가 조용히 깨진다.** 빌드 자체는 성공하고, 학습을
  시작할 때 플레이어가 뜨지 않는 형태로 나타난다.
- 파일을 교체할 일이 생기면 `LinuxPlayerPostProcess.cs`의 복사 경로도 함께 확인한다
  (경로가 두 곳에 있으면 한쪽만 고쳐 어긋난다 — 원칙 1).
- Windows 플레이어 빌드에는 이 폴더가 쓰이지 않는다.

## 관련 문서

- [`docs/modules/BUILD_TOOLING.md`](../docs/modules/BUILD_TOOLING.md) §4 — 기타 도구
- [`unity/README.md`](../unity/README.md) — 플레이어 빌드 메뉴와 출력 경로
- [`training/README.md`](../training/README.md) — 빌드된 플레이어로 학습 실행하기

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- build-support/README.md`
- **갱신 대상**: `build-support/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `unity/README.md`
- **용어는 [`GLOSSARY`](../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

