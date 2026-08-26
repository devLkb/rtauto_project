# Archived training configs

`training/config/` 안에서 어떤 스크립트·문서에서도 더 이상 참조되지 않는 것으로
확인된 설정 파일을 여기로 옮긴다. 재현이 필요할 때를 대비해 삭제하지 않고
보존만 한다.

- `mj_smoketest.yaml` — MuJoCo 물리 엔진 스모크 테스트 설정. MuJoCo 도입
  자체가 2026-08-26 폐기됐다(`CLAUDE.md` 참고, 파이프라인 통합·유지보수
  문제로 Unity PhysX로 환원). 이 config를 소비하는 스크립트는 없었다.
- `dg5f_grasp_lift_eval_h012.yaml` — 0.12 m 블록 지오메트리 승격 여부를
  결정하기 위한 1회성 inference-only probe. 결정은 이미 내려졌고(0.12 m
  채택), 그 뒤를 잇는 평가 config인 `dg5f_grasp_lift_eval_deployed.yaml`과
  `dg5f_grasp_lift_eval_h012_com050.yaml`이 `training/config/`에 현역으로
  남아 `docs/DG5F_GRASP_LIFT.md`의 config 표에 등재돼 있다. 이 probe
  자체는 표에도, 어떤 스크립트에도 없었다.

`training/config/` 안의 나머지 실험별 config(`*_s1_posture010`,
`*_t1_topdown150` 등)는 겉보기엔 1회성이어도 옮기지 않았다 — 전부
`docs/DG5F_GRASP_LIFT.md`의 config 표에 용도가 등재돼 있고, top-down 계열은
`training/scripts/evaluate_dg5f_grasp_lift_topdown.sh`가 지금도 실제로
실행 인자로 받는다. 그 표와 파일 목록이 어긋나면 재현성 문서로서의 가치를
잃으므로, 표에서 이름이 빠지고 어떤 스크립트도 참조하지 않는 것으로 확인된
config만 이 폴더로 옮긴다.
