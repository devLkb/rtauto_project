# urdf_hand_import — URDF 로봇핸드 → Unity 임포트 파이프라인

SVH(2026-06)·Tesollo DG5F 4변형(2026-07-13)에서 검증한 임포트 절차를 범용 스크립트로 정리한 것.
새 핸드 URDF가 생기면 이 폴더의 스크립트 하나로 복사→패치→임포트→검증→프리팹까지 처리한다.

## 전제 조건

- Unity 에디터가 대상 프로젝트(`KDT_robot_AI`)를 열고 있고 unity-cli 커넥터가 살아있을 것
  (`unity-cli status` 로 확인)
- Unity 프로젝트에 `com.unity.robotics.urdf-importer` 패키지 설치돼 있을 것 (실제 임포트 엔진)
- `--verify` 사용 시 Python에 numpy 필요

## 사용법

```bash
# 기본: 복사+패치+임포트+감사 (씬에 인스턴스 남음)
python import_hand.py C:/path/to/hand.urdf

# 물리값 전수 대조까지 (권장)
python import_hand.py C:/path/to/hand.urdf --verify

# 프리팹 저장 + 씬 정리 (여러 변형 일괄 등록할 때)
python import_hand.py right.urdf left.urdf right_s.urdf left_s.urdf --prefab --remove-instance

# 임포트는 이미 했고 물리값 대조만 다시 (로봇 인스턴스가 씬에 있어야 함)
python phys_compare.py C:/path/to/hand.urdf

# 구동 준비: 프리팹에 Controller 제거/게인/중력off/자기충돌무시/초기포즈싱크 일괄 적용 (멱등)
python setup_drive.py dg5f_right dg5f_left dg5f_right_short dg5f_left_short

# 움직임 검증: 전 관절 사각파 프로브 → 정착오차/잔여진동/리밋침범 자동 판정
#   (로봇 인스턴스가 씬에 있어야 함. Play 진입/종료 자동)
python probe_test.py dg5f_right --urdf C:/path/to/dg5f_right.urdf
```

폴더·프리팹 이름은 URDF의 `<robot name="...">` 을 그대로 쓴다(`--name` 으로 강제 가능).
같은 이름으로 재실행하면 파일·프리팹을 덮어쓴다(재임포트 = 씬에 인스턴스 하나 더 생기니
기존 것은 지우고 실행 권장).

## 파이프라인이 하는 일

| 단계 | 내용 | 코드 |
|---|---|---|
| 1. 준비 | URDF+메시를 `Assets/Robots/<이름>/` 복사, `package://` → 상대경로 패치 | `import_hand.prepare` |
| 2. 임포트 | URDF-Importer 실행 (Y축, vHACD 콜리전 분해) | `IMPORT_SNIPPET` (unity-cli exec) |
| 3. 감사 | 바디/revolute 수 + **임포터 기본값 관성 링크(mass=1 또는 I=(1,1,1)) 검출** | 〃 |
| 4. 대조 | 질량/CoM/관성 고유값/리밋/effort ↔ URDF 원본 전수 비교 | `phys_compare.verify` |
| 5. 프리팹 | `Assets/Robots/Prefabs/<이름>.prefab` 저장 | 〃 |
| 6. 구동 준비 | Controller 제거 + 게인(10000/200/100000) + 중력off·루트고정 + 자기충돌무시·초기포즈싱크 부착 | `setup_drive.py` |
| 7. 구동 검증 | Play에서 전 관절 사각파 → 정착오차≤1°/잔여진동≤0.5°/리밋침범 0 판정 | `probe_test.py` |

## 구동 준비 각 항목의 이유 (setup_drive.py가 자동 적용)

1. **Controller 제거** — URDF-Importer가 붙이는 데모 컴포넌트. Play 시 모든 관절에
   JointControl을 추가해 우리가 넣은 xDrive.target을 매 프레임 덮어씀.
2. **드라이브 게인** — 임포트 직후 stiffness=0(모터 꺼짐). 기본 10000/200.
   ⚠️ forceLimit은 URDF effort 대신 100000으로 올림: stiffness 10000 기준 effort 7.5N·m는
   오차 0.04°에도 포화 → 뱅뱅 진동(WORKLOG §18 손목 사태 패턴). HW 토크상한 재현 포기.
3. **중력 off + 루트 immovable** — 디지털 트윈은 명령 포즈 유지가 목적. 안 하면 낙하+처짐.
4. **자기충돌 무시 + 초기 포즈 동기화** — vHACD 콜라이더 겹침 진동 방지 + Play 시작 채찍질 방지.
   `RobotSelfCollisionIgnore`/`RobotInitialPoseSync`(SVH 시절 검증된 범용 로직)를 루트에 부착.

DG5F 4변형 검증 결과(2026-07-13): probe 20관절 전부 정착오차 0.00°/잔여진동 0.00°/침범 0 PASS.

변형 교체 유틸: Unity 메뉴 **Tools/DG5F** (`Assets/Editor/DG5FVariantSwitcher.cs`) —
씬의 현재 핸드를 같은 위치·부모로 교체. 새 핸드 계열을 추가하면 그 스크립트의
`VariantNames` 에 이름을 추가하면 된다.

## 알려진 함정 (실측 기반)

- **badInertia > 0 이면 즉시 수정할 것** — 임포터 기본값 1kg/(1,1,1) 관성 링크는
  SVH 진동 사태의 근본 원인이었음 (WORKLOG §12). URDF에 `<inertial>` 이 전 링크에
  있으면 발생하지 않음 (DG5F가 이 경우).
- **PhysX 최소 관성 클램프**: URDF 관성이 1e-6 미만이면 Unity가 1e-6으로 올림.
  `phys_compare` 가 WARN으로 구분해줌 — 무해 (커지는 방향).
- **unity-cli exec 스니펫 제약**: `using` 지시문 불가(메서드 본문에 삽입됨 — 전부 풀네임으로),
  `$""` 보간 불가, 마지막 `return` 필수, `Object` 는 `UnityEngine.Object` 로 명시.
- `no Unity instances` 에러는 하트비트 순단일 수 있음 — 스크립트가 자동 재시도함.
- 에디터 스크립트 추가/변경 직후엔 도메인 리로드로 잠시 `not responding` 이 정상.
- 씬을 더럽히기 싫으면 임포트 전용 씬(예: `Assets/Scenes/DG5F_Import.unity`)에서 실행.

## 관련 (이 폴더 밖)

- `urdf/build_arm_hand.py` — UR 팔 xacro 변환 + DG5F 손 URDF **결합** (기종·좌우 파라미터화)
- `KDT/docs/WORKLOG.md` §15·§18 — SVH/DG5F 임포트·IK 작업 기록
