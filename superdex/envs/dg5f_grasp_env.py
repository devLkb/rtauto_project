# -*- coding: utf-8 -*-
"""DG5FGraspEnv — 손목 고정 DG5F 다지 파지 강화학습 환경 (게이트 2).

docs/SUPERDEX_POC_PLAN.md §5 게이트 2. 게이트 0에서 **실측한 값들이 그대로 들어간다**:

  - `prefab.joints[0].type = HARD` 로 손목 용접 -> DOF 정확히 20 (기본 FREE면 자유부양)
  - 파지 성공 영역은 손바닥 링크 좌표계 `palm + [0.03, 0, 0.04]` 부근 (스윕 실측)
  - 접촉점 조회는 스텝 **전에** `register_query(QueryType.CONTACT_POINTS)` 등록 필요
  - 동적 물체는 surface mesh가 있어야 하므로 Box and Blocks Test 블록 프리팹을 쓴다
  - 컨트롤러는 `MOCHI_ARTICULATED_POSE` (BASIC_*_PD는 중력 항이 없다)

**태스크.** 손목은 고정이다. 블록이 파지 포켓에 생성되고, `grace_steps` 동안은 무중력이며
그 뒤 중력이 켜진다. 정책은 그 사이에 손가락을 닫아 블록을 붙잡고, 에피소드가 끝날 때까지
파지 중심 근처에 유지해야 한다. `grace_steps`를 줄이는 것이 커리큘럼 축이다.

> 왜 grace가 필요한가: 열린 자세에서 접촉까지 폐쇄율 0.6 이상이 필요하고(게이트 0 실측)
> 자세 컨트롤러가 거기까지 가는 데 0.1~0.2초가 걸린다. 중력을 처음부터 켜면 완벽한
> 정책이라도 블록이 10 cm 이상 떨어져 보상 신호가 생기지 않는다.

**행동.** 20개 관절의 목표 각도. 액션 공간을 실제 관절 한계로 선언하므로 RLlib의
`normalize_actions`가 [-1,1] <-> 관절범위 변환을 담당하고, 게이트 1에서 검증한 ONNX
익스포트 경로(래퍼가 unsquash를 그래프에 박음)가 그대로 성립한다.

**관찰 (65차원).** 관절각 20 + 관절속도 20 + 블록 위치(파지중심 기준) 3 + 블록 자세 4
+ 블록 선속도 3 + 블록 각속도 3 + **지문별 접촉력 크기 5** + 지문-블록 거리 5
+ 진행도 1 + 중력 ON 1. 스펙 정본은 docs/RL_POLICY_REDESIGN.md — 바꾸면 거기와 ONNX
스펙 버전을 함께 올린다.

> ⚠️ 지문 접촉을 **거리로 근사하지 않는다.** 처음엔 "지문-블록중심 거리 < 3 cm"를 썼는데
> 실측에서 완전 폐쇄 시 지문 거리가 `[3.4, 4.0, 3.4, 2.3, 5.2] cm`이고 블록 AABB가
> 3.3~3.8 cm였다 — 실제로는 4지 포위인데 지표는 1개만 셌다. 그래서
> `block.get_contact_force_from_actor_world(<지문 링크 actor>)`로 **지문별 실제 접촉력**을
> 읽는다. 링크 actor는 `actor.get_nested_link_actors()`로 얻고, 접촉력이 채워지려면
> 스텝 전에 `QueryType.TOTAL_CONTACT_FORCE` 등록이 필요하다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "config") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (경로·asset 위치의 유일한 출처 — 원칙 1)

_assets = cfg.superdex_assets_path()
if _assets is not None:
    os.environ.setdefault("SUPERDEX_ASSETS_PATH", str(_assets))

import superdex.physics as physics  # noqa: E402
import superdex.robotics as robotics  # noqa: E402
from superdex.physics.paths import get_assets_root, resolve_asset  # noqa: E402

BLOCK_PREFAB = "prefabs/box_and_blocks/block_red.mochi_prefab"       # 2.5cm / 15.6g
DUCK_LAMP_PREFAB = "prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab"  # 11.9x11.0x7.5cm / 545g
PALM_LINK = "dg5f_link_palm"
TIP_LINKS = tuple(f"dg5f_link_{f}_tip" for f in "12345")
FLEX_SUFFIXES = ("_2", "_3", "_4")

# physics.initialize()는 프로세스 전역이다. env runner가 프로세스마다 하나씩 만들어지므로
# 프로세스당 한 번만 부르고, 두 번째 env는 그대로 재사용한다.
_PHYSICS_READY = False


def _ensure_physics(threads: int = 0):
    global _PHYSICS_READY
    if not _PHYSICS_READY:
        physics.initialize(num_worker_threads=threads)
        _PHYSICS_READY = True


class Dg5fGraspEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, config=None):
        super().__init__()
        c = dict(config or {})
        self.hz = int(c.get("sim_hz", cfg.SUPERDEX_SIM_HZ))
        self.dt = 1.0 / self.hz
        self.episode_seconds = float(c.get("episode_seconds", 3.0))
        self.max_steps = int(self.episode_seconds * self.hz)
        self.grace_steps = int(c.get("grace_steps", 40))
        # 게이트 0 스윕에서 유일하게 안정적으로 잡힌 지점. 리셋마다 이 값 주변을 흔든다.
        self.place = np.asarray(c.get("place", (0.04, 0.0, 0.04)), dtype=float)
        # 배치 흔들림. 난이도를 결정하는 축이다 — 완전 폐쇄만 하는 고정 정책의 성공률
        # (엄격 기준: 지문 3개 + 파지중심 6 cm 내)이 실측으로 다음과 같다:
        #   0.015 -> 13%,  0.025 -> 0%,  0.035 -> 0%
        # 0.015를 기본값으로 둔다: 학습 여지가 있으면서 완전 불가능하지는 않은 지점.
        self.place_jitter = float(c.get("place_jitter", 0.015))
        self.start_frac = float(c.get("start_frac", 0.25))
        self.hold_radius = float(c.get("hold_radius", 0.06))
        # 지문 접촉 판정 임계 [N], 그리고 성공에 요구하는 지문 접촉 개수.
        # 프로젝트 목표가 "다지 안정 접촉"이므로 근위 지골로 가두는 것은 성공이 아니다.
        self.tip_force_threshold = float(c.get("tip_force_threshold", 0.05))
        self.min_tips = int(c.get("min_tips", 3))
        self.action_rate_penalty = float(c.get("action_rate_penalty", 0.01))
        # 목표 평활화 계수. 낮을수록 스텝별 지터가 억제되고 실효 목표가 정책 평균에 수렴한다.
        # step() 의 실측 근거 주석 참고.
        self.action_smooth = float(c.get("action_smooth", 0.1))

        # ⚠️ 강성 기본값을 1e3에서 3.0으로 내렸다. 1e3에서는 완전 폐쇄 시 지문 접촉력이
        # **4,000~6,000 N**까지 올라간다 — 15.6 g 블록에 대해 물리적으로 불가능한 값이고,
        # 정책이 "잡는" 대신 "압착하는" 것을 배우게 되며 sim2real이 무의미해진다.
        # 실측 스윕(완전 폐쇄, 1초): 1e3 -> 4671 N / 2e2 -> 1294 N / 5e1 -> 573 N /
        #                            1e1 -> 120 N / 3.0 -> 34.7 N (3지 접촉 파지는 모두 성립)
        self.stiffness = float(c.get("stiffness", 3.0))
        self.damping = float(c.get("damping", 0.3))
        # 이 값을 넘는 지문 접촉력에 페널티를 준다. 실제 DG-5F-M의 지문 파지력 상한은
        # 벤더 확인이 필요하다 (docs/SUPERDEX_POC_PLAN.md U8).
        self.tip_force_limit = float(c.get("tip_force_limit", 20.0))
        # 포화형 페널티의 가중치와 스케일. 스텝당 최대 -force_penalty 로 묶인다.
        self.force_penalty = float(c.get("force_penalty", 1.0))
        self.force_penalty_scale = float(c.get("force_penalty_scale", 50.0))
        # 파지 대상 프리팹. 게이트 4의 다물체 일반화와 오라클 탐색에서 바꿔 끼운다.
        # 실측 AABB: block_red 2.5cm/15.6g, sphere 3cm/10g, fdt_peg 2.2x2.2x4cm/6.8g,
        #            paper_cup 9.3x9.4x11.3cm/15g, duck_lamp_recumbent 11.9x11.0x7.5cm/545g
        # ⚠️ 기본 물체를 2.5cm 블록에서 duck_lamp(11.9x11.0x7.5cm, 545g)로 바꿨다.
        # 오라클 그리드 탐색(superdex/scripts/gate2_oracle_search.py) 실측 근거:
        #   block_red 2.5cm : 성공 궤적이 존재하는 시드 1/10, 시드별 최선 tips_best 중앙 2
        #   duck_lamp        : 성공 궤적이 존재하는 시드 7/10, 최선 고정 궤적 6/10,
        #                      시드별 최선 tips_best 중앙 4 / max 5
        # 2.5cm 블록은 사람 크기 손에 너무 작아 **3지 접촉이 기하적으로 성립하지 않는다**
        # (지문이 1~2개만 닿는다). 큰 물체가 (1) 달성 가능한 상한을 올리고, (2) 실제
        # 목표인 FOUP에 더 충실하며, (3) 비볼록 접촉 — Unity 대비 SuperDex를 택한 근거
        # 자체 — 를 시험한다.
        self.object_prefab = str(c.get("object_prefab", DUCK_LAMP_PREFAB))

        # SuperDex 내부 스레딩. 실측: 0(단일) 311 steps/s vs -1(자동) 468 steps/s = 1.5배.
        # 기본값을 -1로 둔다 — 공짜로 얻는 속도다.
        _ensure_physics(int(c.get("physics_threads", -1)))
        self._build_scene()

        n_obs = 20 + 20 + 3 + 4 + 3 + 3 + 5 + 5 + 1 + 1
        self.observation_space = spaces.Box(-np.inf, np.inf, (n_obs,), dtype=np.float32)
        # 실제 관절 한계를 그대로 선언한다 -> RLlib이 정규화/역정규화를 맡고,
        # 게이트 1에서 검증한 ONNX 익스포트 경로가 그대로 성립한다.
        self.action_space = spaces.Box(
            self.joint_low.astype(np.float32), self.joint_high.astype(np.float32),
            (20,), dtype=np.float32,
        )

        self._steps = 0
        self._prev_action = None

    # ------------------------------------------------------------------ scene
    def _build_scene(self):
        self.scene = physics.create_scene("Dg5fGraspEnv")
        self.scene.set_gravity([0, 0, 0])  # grace 구간에서 시작

        ground = physics.create_plane_shape(normal=[0, 0, 1], distance=0)
        self.scene.create_rigid_actor(name="ground", shape=ground, is_static=True)

        prefab = robotics.load_bot_prefab_from_file(
            str(resolve_asset(cfg.superdex_hand_asset()))
        )
        # 손목 용접 — 이걸 안 하면 world_joint가 FREE라 손이 자유부양한다(게이트 0 실측).
        prefab.joints[0].type = physics.ArticulatedJointType.HARD
        prefab.world_from_root = physics.TransformRT(
            rotation=[0.0, 0.0, 0.0, 1.0], translation=[0.0, 0.0, 0.4]
        )

        self.link_names = [prefab.links[i].name for i in range(len(prefab.links))]
        self.palm_idx = self.link_names.index(PALM_LINK)
        self.tip_idx = [self.link_names.index(n) for n in TIP_LINKS]

        ctx = robotics.create_context()
        self.bot = robotics.create_bot(self.scene, prefab, ctx)
        self.actor = self.bot.get_articulated_actor()
        assert self.actor.get_num_dofs() == 20, (
            f"손목 용접 후 DOF가 20이어야 한다 (실제 {self.actor.get_num_dofs()})"
        )

        # 관절 한계 (min_limit/max_limit은 축별 Real3다 — 게이트 0 실측)
        lows, highs, flex = [], [], []
        dof = 0
        for i in range(len(prefab.joints)):
            j = prefab.joints[i]
            if j.type != physics.ArticulatedJointType.REVOLUTE:
                continue
            ax = [round(float(v), 0) for v in j.axis]
            k = ax.index(1.0) if 1.0 in ax else (ax.index(-1.0) if -1.0 in ax else 0)
            lows.append(float(j.min_limit[k]))
            highs.append(float(j.max_limit[k]))
            if j.name.endswith(FLEX_SUFFIXES):
                flex.append(dof)
            dof += 1
        self.joint_low = np.asarray(lows, dtype=np.float64)
        self.joint_high = np.asarray(highs, dtype=np.float64)
        self.flex_dofs = np.asarray(flex, dtype=np.int64)

        self._pose_buf = physics.DynamicArrayReal(20)
        self._vel_buf = physics.DynamicArrayReal(20)
        self._tf_buf = physics.DynamicArrayTransformRT(len(self.link_names))

        self.actor.get_articulated_pose(self._pose_buf)
        self.open_pose = np.array([float(v) for v in self._pose_buf], dtype=np.float64)
        self.full_closed = self.open_pose.copy()
        # 굽힘은 max_limit 방향 (게이트 0 실측: _2/_3/_4의 min은 0)
        self.full_closed[self.flex_dofs] = self.joint_high[self.flex_dofs]

        tracking = physics.PoseTrackingParams(stiffness=self.stiffness, damping=self.damping)
        self.pose_ctrl = self.bot.create_controller("MOCHI_ARTICULATED_POSE")
        self.pose_ctrl.set_params(
            robotics.ControllerMochiArticulatedPoseParams(
                pose_controller_params=physics.PoseControllerParams(
                    joint_tracking=physics.DynamicArrayPoseTrackingParams([tracking])
                )
            )
        )
        self.pose_ctrl.initialize(True)

        physics.prefab.add_to_scene(
            prefab_path=str(resolve_asset(self.object_prefab)),
            root_path=str(get_assets_root()),
            scene=self.scene,
            params=physics.prefab.PrefabParams(name="block", translation=[0.0, 0.0, 0.4]),
        )
        found = []
        self.scene.for_each_actor(lambda a: found.append(a))
        self.block = next(a for a in found
                          if a.get_name().startswith("block") and not a.is_static())
        # 접촉점·접촉력은 스텝 전에 쿼리를 등록해야 채워진다 (게이트 0 실측).
        self.block.register_query(physics.QueryType.CONTACT_POINTS)
        self.block.register_query(physics.QueryType.TOTAL_CONTACT_FORCE)

        # 지문 링크의 개별 actor. 접촉을 거리로 근사하지 않고 여기서 직접 읽는다.
        bot_name = self.bot.get_name()
        by_name = {}
        for h in self.actor.get_nested_link_actors():
            a = self.scene.get_actor(h)
            by_name[a.get_name()] = a
        self.tip_actors = []
        for ln in TIP_LINKS:
            a = by_name.get(f"{bot_name}/{ln}") or by_name.get(ln)
            if a is None:
                raise RuntimeError(
                    f"지문 링크 actor '{ln}' 를 못 찾았다. 후보: {sorted(by_name)[:8]}"
                )
            self.tip_actors.append(a)

        # 리셋용 기준 상태. 블록 위치는 리셋 때 set_root_transform으로 다시 흔든다.
        self._base_state = self.scene.capture_state()

    # ------------------------------------------------------------------ helpers
    def _pose_at(self, frac):
        return self.open_pose + (self.full_closed - self.open_pose) * float(frac)

    def _link_positions(self):
        self.actor.get_articulated_link_transforms(self._tf_buf)
        return self._tf_buf

    def _grasp_center(self, tf):
        pts = [np.asarray(tf[i].translation, dtype=float) for i in self.tip_idx]
        pts.append(np.asarray(tf[self.palm_idx].translation, dtype=float))
        return np.mean(pts, axis=0)

    def _palm_to_world(self, tf, offset):
        local = physics.TransformRT()
        local.translation = [float(v) for v in offset]
        return np.asarray((tf[self.palm_idx] * local).translation, dtype=float)

    def _n_contacts(self):
        try:
            return len(self.block.get_contact_points_world())
        except Exception:
            return 0

    def _observe(self):
        self.actor.get_articulated_pose(self._pose_buf)
        self.actor.get_articulated_joint_velocities(self._vel_buf)
        q = np.array([float(v) for v in self._pose_buf], dtype=np.float64)
        qd = np.array([float(v) for v in self._vel_buf], dtype=np.float64)

        tf = self._link_positions()
        center = self._grasp_center(tf)
        bt = np.asarray(self.block.get_root_transform().translation, dtype=float)
        bq = np.asarray(self.block.get_root_transform().rotation, dtype=float)
        bv = np.asarray(self.block.get_linear_velocity(), dtype=float)
        bw = np.asarray(self.block.get_angular_velocity(), dtype=float)

        tips = np.stack([np.asarray(tf[i].translation, dtype=float) for i in self.tip_idx])
        tip_dist = np.linalg.norm(tips - bt[None, :], axis=1)

        # 지문별 실제 접촉력 [N]. 거리 근사를 쓰지 않는 이유는 모듈 docstring 참고.
        tip_force = np.zeros(5, dtype=np.float64)
        for k, ta in enumerate(self.tip_actors):
            try:
                f = np.asarray(
                    self.block.get_contact_force_from_actor_world(ta), dtype=float
                )
                tip_force[k] = float(np.linalg.norm(f))
            except Exception:
                tip_force[k] = 0.0

        # ⚠️ 관찰 정규화는 **환경 안에서 고정 상수로** 한다. 근거 두 가지:
        #
        # (1) 안 하면 학습이 되지 않는다. 실측 스케일(무작위 롤아웃 660 샘플):
        #       q          |mean| 0.60  max   1.4
        #       qd         |mean| 6.14  max  40.8   <- 100배
        #       blk상대위치 |mean| 0.04  max   0.10
        #       blk각속도   |mean| 5.47  max  34.9   <- 100배
        #       지문거리    |mean| 0.11  max   0.30
        #     RLlib 새 API 스택은 관찰 정규화를 기본으로 하지 않는다(게이트 1에서 커넥터
        #     구성을 실측해 확인: env_to_module에 필터가 없다). 정규화 없는 MLP는 속도
        #     채널에 지배되고 정작 과제에 중요한 위치·거리 채널에 눈이 먼다.
        # (2) running filter(MeanStdFilter)를 쓰면 통계가 커넥터에 살아 ONNX 밖으로 새어나간다.
        #     게이트 1에서 정한 원칙 — 변환은 전부 그래프 안에 상수로 박는다 — 을 지키려면
        #     스케일이 **고정 상수**여야 한다.
        obs = np.concatenate([
            q,                                  # 이미 O(1) (rad)
            qd / 20.0,                           # ±41 -> ±2
            (bt - center) * 10.0,                # ±0.1 -> ±1
            bq,                                  # 쿼터니언, 이미 O(1)
            bv / 2.0,                            # ±2 -> ±1
            bw / 20.0,                           # ±35 -> ±1.75
            tip_force / max(self.tip_force_limit, 1e-6),   # N -> 한계 대비 비율
            tip_dist * 10.0,                     # 0.04~0.30 -> 0.4~3.0
            [self._steps / max(1, self.max_steps)],
            [1.0 if self._steps >= self.grace_steps else 0.0],
        ])
        return obs.astype(np.float32), center, bt, tip_dist, tip_force

    # ------------------------------------------------------------------ gym API
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.scene.restore_state(self._base_state, False)
        self.scene.set_gravity([0, 0, 0])
        self._steps = 0
        self._prev_action = None
        self._target = None

        start = self._pose_at(self.start_frac)
        arr = physics.DynamicArrayReal(start.tolist())
        self.actor.set_articulated_target_pose(arr)
        self.actor.set_articulated_pose_from_joints(arr)

        tf = self._link_positions()
        jitter = self.np_random.uniform(-self.place_jitter, self.place_jitter, size=3)
        spawn = self._palm_to_world(tf, self.place + jitter)
        t = physics.TransformRT()
        t.translation = [float(v) for v in spawn]
        self.block.set_root_transform(t)
        self.block.set_velocity([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])

        obs = self._observe()[0]
        return obs, {}

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=np.float64), self.joint_low, self.joint_high)

        # ⚠️ 목표 평활화(EMA)가 없으면 학습이 되지 않는다 — 실측 근거:
        # 평균을 '완전 폐쇄'로 고정하고 정규화 공간에서 지터만 줬을 때 리턴이
        #   std 0.0 -> 432.1,  0.1 -> 369.8,  0.3 -> 260.3,  0.5 -> 136.7,  1.0 -> 111.2
        # 로 무너진다. RLlib PPO의 초기 log_std=0은 정규화 공간 std=1.0, 즉 최악 지점이다.
        # 완벽한 정책 평균조차 111밖에 못 받고 좋은/나쁜 평균의 차이가 9.6배에서 2.4배로
        # 압축돼 gradient가 소멸한다(v1·v2 모두 평평하게 끝난 원인).
        #
        # 부드러운 자세 컨트롤러(stiffness 3.0)는 **응답**을 저역통과하지만 지령 목표 자체의
        # 지터는 남는다. 목표를 EMA로 평활화하면 실효 목표가 정책 평균에 수렴해
        # 평균의 효과가 복원된다.
        self._target = a if self._target is None else (
            (1.0 - self.action_smooth) * self._target + self.action_smooth * a
        )
        self.actor.set_articulated_target_pose(
            physics.DynamicArrayReal(self._target.tolist())
        )

        if self._steps == self.grace_steps:
            self.scene.set_gravity([0, 0, -9.81])

        self.scene.step(self.dt)
        self._steps += 1

        obs, center, bt, tip_dist, tip_force = self._observe()
        dist = float(np.linalg.norm(bt - center))
        ncon = self._n_contacts()
        gravity_on = self._steps > self.grace_steps
        n_tips = int(np.sum(tip_force > self.tip_force_threshold))

        # --- 보상: 접촉 확보 -> 조임 -> 유지 의 3단 구조.
        # 게이트 0에서 파지 성공 영역이 좁다는 것을 확인했으므로(스윕 5종 중 2종만 성공)
        # 단계를 분리해 탐색이 접촉부터 배우게 한다.
        # ⚠️ r_reach 가 없으면 학습이 전혀 되지 않는다 (480k 스텝 실측).
        # 초기 정책은 지문 접촉을 **한 번도** 만들지 못해(평균 지문 접촉 0.00)
        # r_touch/r_contact/r_hold 가 학습 내내 항상 0이었고, 남은 항 r_near 는 grace 구간에서
        # 액션과 무관하게 결정된다 -> **액션이 보상에 영향을 주지 못해 gradient가 없다.**
        # r_reach 는 어떤 자세에서도 액션에 반응하는 밀집 신호를 주어
        # "다가가기 -> 접촉 -> 유지"의 계단을 만든다.
        r_reach = float(np.exp(-10.0 * float(np.mean(tip_dist))))
        r_near = float(np.exp(-8.0 * dist))                     # 파지중심 근접 유지
        r_touch = n_tips / 5.0                                  # 다지 접촉 비율 (0~1)
        r_contact = float(np.tanh(ncon / 200.0))                # 접촉 규모
        r_hold = 1.0 if (gravity_on and dist < self.hold_radius
                         and n_tips >= self.min_tips) else 0.0

        rate = 0.0
        if self._prev_action is not None:
            span = np.maximum(self.joint_high - self.joint_low, 1e-6)
            rate = float(np.mean(np.abs(a - self._prev_action) / span))
        self._prev_action = a

        # 과도한 파지력 페널티 — 압착으로 성공하는 것을 막는다(강성 실측 근거는 __init__ 주석).
        #
        # ⚠️ 선형 페널티(-0.02 * overforce)를 쓰면 안 된다. 무작위 정책의 누적 과도력이
        # 평균 4,150 N / 최대 35,439 N으로 극단적으로 치우쳐(15에피소드 실측) 페널티가
        # 리턴을 지배하고(리턴 -596~+37) 분산이 폭발해 PPO 학습 신호가 망가진다.
        # 그래서 **포화형**으로 스텝당 [-1, 0]에 묶는다 — 양의 항 최대 +4.5/스텝과 비교 가능한
        # 규모가 되고 분산이 유한해진다.
        overforce = float(np.sum(np.maximum(0.0, tip_force - self.tip_force_limit)))
        r_force = -float(np.tanh(overforce / self.force_penalty_scale))

        reward = (1.0 * r_reach + 1.0 * r_near + 1.0 * r_touch
                  + 0.5 * r_contact + 2.0 * r_hold
                  - self.action_rate_penalty * rate
                  + self.force_penalty * r_force)

        dropped = gravity_on and dist > 0.25
        terminated = bool(dropped)
        if dropped:
            reward -= 5.0
        truncated = self._steps >= self.max_steps

        info = {
            "dist": dist, "n_contacts": ncon, "gravity_on": gravity_on,
            "tips_touching": n_tips,
            "tip_force_max": float(np.max(tip_force)),
            # 성공 = 중력 하에서 파지중심 근처 유지 **그리고** 지문 min_tips개 이상 접촉.
            # 거리만 보면 근위 지골로 가둔 것도 성공으로 오판한다(게이트 0에서 겪었다).
            "is_success": bool(truncated and not dropped
                               and dist < self.hold_radius
                               and n_tips >= self.min_tips),
        }
        return obs, float(reward), terminated, truncated, info

    def close(self):
        try:
            self.scene.release_state(self._base_state)
        except Exception:
            pass
        try:
            robotics.destroy_bot(self.scene, self.bot)
        except Exception:
            pass
