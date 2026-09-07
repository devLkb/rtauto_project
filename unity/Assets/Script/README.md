# ⛔ `Assets/Script/` (단수) — 과거 팀 시절 잔재, 현재 파이프라인과 무관

**이 폴더의 코드는 현재 UR16e 파이프라인 어디에서도 참조되지 않는다.**
새 작업의 출발점으로 삼지 말 것.

> ⚠️ **`Assets/Scripts/`(복수)와 헷갈리지 말 것.** 현역 코드는 복수형 폴더에 있다
> ([`Assets/Scripts/README.md`](../Scripts/README.md)).

## 무엇인가

Rainbow Robotics 협동로봇을 **소켓 통신으로 제어**하던 코드다. 네임스페이스가
`com.rainbow.external`인 것이 표식이다. 현재 하드웨어는 UR16e이고 통신은 RTDE
([`arm/README.md`](../../../arm/README.md))이므로 이 경로는 쓰이지 않는다.

| 파일 | 줄 수 | 내용 |
|---|---|---|
| `ActionAPI.cs` | 464 | `com.rainbow.external` — 로봇 동작 명령 API |
| `RBSocket.cs` | 214 | 〃 — 소켓 통신 |
| `Globals.cs` | 155 | 〃 — 전역 상태 |
| `Const.cs` | 363 | 명령 코드·상수 테이블 |
| `BufferUtil.cs` | 154 | 바이트 버퍼 유틸 |
| `JointOperation.cs` | 126 | `MonoBehaviour` — 관절 조작 + CCD IK |

## 살아남은 것 하나

`JointOperation.cs`의 **CCD IK 로직만** `Assets/Scripts/ArmTargetIK.cs`로 이식돼 살아 있다.
현재 쓰는 것은 이식본이며, 원본은 여기 남아 있을 뿐이다.

## 지우지 않은 이유

과거 실험의 통신 규약(명령 코드, 패킷 배치)을 다시 확인해야 할 가능성이 남아 있어 기록으로
보존한다. 실제로 다시 쓰게 된다면 **하드웨어·프로토콜 선택부터 새로 정하는 것**이 전제다.

## 관련 문서

- [`Assets/Scripts/README.md`](../Scripts/README.md) — 현역 통신·구동 코드
- [`docs/modules/UNITY.md`](../../../docs/modules/UNITY.md) §8 — 잔재 설명
- [`arm/README.md`](../../../arm/README.md) — 현재 팔 통신 경로(RTDE)

---

## 문서 이력

| 버전 | 변경 일자 | 변경자 | 변경 내용 | 변경 사유 |
|---|---|---|---|---|
| v1.0 | 2026-09-07 | devlkb | 최초 작성 | 디렉터리별 문서 신설 — 인수인계 시 코드를 읽지 않고도 이 폴더를 이해할 수 있게 |

- **근거 기준**: 2026-09-07 저장소 **코드·설정 대조**. 실물 재시험이나 성능 재검증을 뜻하지 않는다.
- **변경자·상세 diff의 정본은 git 이력**이다: `git log --follow -- unity/Assets/Script/README.md`
- **갱신 대상**: `unity/Assets/Script/**` (잔재)가 바뀌면 이 문서의 역할·입출력·상수·알려진 제한을 함께 고친다.
- **함께 갱신할 문서**: `docs/modules/UNITY.md` §8
- **용어는 [`GLOSSARY`](../../../docs/GLOSSARY.md)를 따른다.** 새 용어를 쓰려면 거기에 먼저 추가한다.

