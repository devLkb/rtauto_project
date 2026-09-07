# `docs/modules/` — 코드가 무슨 일을 하는지 설명하는 문서 묶음

"이 스크립트 왜 있지?"에 답하는 곳이다. 각 문서의 앞부분은 **역할·연결·사용 조건**,
뒷부분은 **파일별 역할과 코드 레벨 상세**(클래스·함수 이름, 실행 인자, 상수 실제값, 패킷 배치)다.

**입구는 [`MODULE_GUIDE.md`](MODULE_GUIDE.md)다.** 전체 데이터 흐름과 현재 범위를 거기서 먼저 읽는다.

## 문서 5개 + 입구 1개

| 문서 | 다루는 범위 | 코드 위치 | 짝이 되는 디렉터리 README |
|---|---|---|---|
| [`MODULE_GUIDE.md`](MODULE_GUIDE.md) | 전체 흐름, 현재 주력과 이전 세대 구분, 코드 레벨 입구 | 전체 | — |
| [`UNITY.md`](UNITY.md) | Unity 안의 로봇 구동·데모 UI·에디터 툴 | `unity/Assets/**` | [`unity/`](../../unity/README.md) · [`Assets/Scripts/`](../../unity/Assets/Scripts/README.md) |
| [`RL_TRAINING.md`](RL_TRAINING.md) | 강화학습 에이전트(보상·관찰·행동) + 학습 스크립트 | `unity/Assets/MLAgents/**`, `training/**` | [`Assets/MLAgents/`](../../unity/Assets/MLAgents/README.md) · [`training/`](../../training/README.md) |
| [`VISION_TELEOP.md`](VISION_TELEOP.md) | 웹캠 → 손 관절각 → UDP 송신, 카메라 캘리브레이션 | `vision/**` | [`vision/`](../../vision/README.md) |
| [`REAL_BRIDGES.md`](REAL_BRIDGES.md) | 실물·시뮬레이터 하드웨어와 붙는 브리지 | `arm/**`, `vision/dg5f/*bridge*.py` | [`arm/`](../../arm/README.md) |
| [`BUILD_TOOLING.md`](BUILD_TOOLING.md) | 설정 정본, URDF 빌드·임포트, 패키징·방화벽 | `config/`, `urdf/`, `tools/`, `build-support/` | [`config/`](../../config/README.md) · [`urdf/`](../../urdf/README.md) · [`tools/`](../../tools/README.md) |

## 모듈 문서와 디렉터리 README의 역할 분담

둘 다 있는 이유는 **묻는 방식이 다르기 때문**이다.

| | 모듈 문서 (`docs/modules/`) | 디렉터리 README |
|---|---|---|
| 답하는 질문 | "이 **기능**은 어디서 어떻게 이어지나" | "이 **폴더**를 열었는데 뭐가 뭔가" |
| 경계 | 기능 단위(폴더를 가로지른다) | 폴더 단위 |
| 예 | 손 텔레옵은 Python·Unity·브리지에 걸쳐 있다 | `vision/`에 있는 파일들의 목록과 상세 |

**값이 충돌하면 코드가 맞다.** 그다음이 모듈 문서, 그다음이 디렉터리 README다.
문서를 고쳤으면 다른 쪽도 함께 본다.

## 문서를 고칠 때의 규칙

`MODULE_GUIDE.md` 머리말에 적힌 규칙을 그대로 따른다.

1. 코드가 바뀌면 **역할뿐 아니라 입출력·제어권·설정 적용 시점·알려진 제한**도 함께 갱신한다.
2. 과거 기록의 "현재"나 **계획된 기능을 오늘의 구현 완료 상태로 해석하지 않는다.**
3. 문서에 적은 파일 경로·스크립트명이 **실제로 존재하는지 확인한다**(원칙 2).
4. 코드 대조는 **실물 재시험을 뜻하지 않는다.** 무엇을 근거로 확인했는지 함께 적는다.

## 관련 문서

- [`docs/README.md`](../README.md) — 문서 전체 인덱스
- [`docs/SIM2REAL_ROADMAP.md`](../SIM2REAL_ROADMAP.md) — 아키텍처 확정 사항·단계별 계획(최상위 정본)
- [`CLAUDE.md`](../../CLAUDE.md) — 프로젝트 최상위 지침

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- docs/modules/README.md`
- **갱신 대상**: `docs/modules/**`가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: 리포 루트 `README.md`의 디렉터리 README 지도
- **용어는 [`GLOSSARY`](../GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

