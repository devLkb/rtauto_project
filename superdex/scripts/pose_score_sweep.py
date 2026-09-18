# -*- coding: utf-8 -*-
"""채점표 만들기 — **어느 자세에서 잡히는가**를 훑어서 파일로 남긴다 (D-2).

무엇을 만드는가
---------------
`(물체 모양, 파지 직전 자세) -> 잡혔다 / 못 잡았다` 표다. 이 표가 있어야
"보이는 모양 -> 좋은 자세" 를 예측하는 프로그램(D-4)을 가르칠 수 있다.

설계: [`docs/FESTA_PREGRASP_PLAN.md`](../../docs/FESTA_PREGRASP_PLAN.md) §3·§7.

왜 이렇게 만드는가 — 두 가지를 알아야 한다
-------------------------------------------
**1. "이 자세가 좋은 자세인가" 는 거기서 실제로 잡아 봐야만 안다.**
실물에서는 잡지 않기로 했으므로(전시 범위), 가상 세계에서 잡아 보고 그 결과를 표로 남긴다.

**2. "물체를 손 기준 이 자리에 놓는 것" 과 "손을 물체 기준 저 자리에 두는 것" 은 같은 말이다.**
이 환경은 손목이 고정돼 있어 손을 못 움직이는 대신 **물체를 옮겨서** 같은 관계를 만든다.
그래서 `place`(물체 위치) + `place_rot`(물체 방향) 을 훑는 것이 곧 **파지 직전 자세를
훑는 것**이다. 표에는 사람이 읽기 쉽게 둘 다 적는다.

이미 있던 것과 무엇이 다른가
----------------------------
`object_oracle_sweep.py` 는 **궤적 값**(얼마나 빨리 쥐는가)을 훑어 "이 물체가 애초에
잡히는가" 를 봤다. 이 스크립트는 **자세**를 훑는다 — 궤적은 몇 개만 써서 자세 탓과
궤적 탓을 섞지 않는다(자세 하나당 궤적 몇 개 중 하나라도 성공하면 그 자세는 성공).

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/pose_score_sweep.py

터미널 1 (bash, 리포 루트):

    source superdex/.venv/bin/activate
    python -u superdex/scripts/pose_score_sweep.py

기본값은 **몇 분** 짜리 맛보기다. 넓게 훑으려면 `--xs`·`--yaws`·`--seeds` 를 늘린다.
결과는 `superdex/results/pose_score_<시각>.json` 에 남는다(git 비추적).
중간에 멈춰도 그때까지 한 것은 파일에 남는다. 멈추려면 `Ctrl+C`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "envs"))
sys.path.insert(0, str(REPO_ROOT / "superdex" / "scripts"))

import rtauto_config as cfg  # noqa: E402,F401  (환경이 asset 경로를 여기서 읽는다)

RESULTS_DIR = REPO_ROOT / "superdex" / "results"

#: 훑을 물체. (표시이름, 프리팹, 조각, 기준점)
#: 조각이 있는 프리팹(shape_box)은 조각 하나만 써야 한다 — 안 그러면 나머지 13개가
#: 같은 자리에 겹쳐 놓인다(object_oracle_sweep.py 머리말 참고).
SHAPE_BOX = "prefabs/shape_box/shape_box.mochi_prefab"
#: `shape_box` 도형 12종. 2026-09-14 에 **전부 잡히는 것이 확인**됐다
#: (docs/SUPERDEX_POC_PLAN.md "shape_box 오라클 스윕").
SHAPE_BOX_PIECES = ("cross", "triangle", "square", "trapezoid", "rectangle", "pentagon",
                    "parallelogram", "octagon", "hexagon", "ellipse", "diamond", "star")

#: ⚠️ **모양이 다양해야 한다 — 2026-09-18 에 확인된 병목.**
#: `shape_box` 도형 12종은 **전부 같은 두께의 납작한 판**이고 테두리만 다르다. 이것만으로
#: 배우면 "처음 보는 **모양**" 으로 넘어가지 못한다 — 실제로 물체 하나만 놓고 시키면
#: 13종 전부 100% 인데(외우는 것은 된다), 하나를 빼고 나머지로 배우면 0~15% 였다.
#: 그래서 **생김새가 근본적으로 다른 것**을 함께 넣는다. 아래 세 줄이 그것이다.
#: 크기·적합 판정의 근거: `superdex/scripts/survey_object_assets.py` 와
#: [`docs/SUPERDEX_POC_PLAN.md`](../../docs/SUPERDEX_POC_PLAN.md) "물체 asset 전수 조사".
OBJECTS = {
    # --- 생김새가 근본적으로 다른 것들 (3차원 형상) ---
    "duck_lamp": ("prefabs/duck_lamp/duck_lamp_recumbent.mochi_prefab", None, "root"),
    "paper_cup": ("prefabs/paper_cups/paper_cup.mochi_prefab", None, "com"),
    "shapebox_body": (SHAPE_BOX, "shapebox_body", "com"),
    # peg_board 는 뺐다 — 조사표에는 "적합" 으로 나오지만 프리팹에서 움직일 수 있는
    # actor 목록에 판이 없다(못 9개만 있다). 2026-09-18 확인.
    "sphere": ("prefabs/sphere/sphere.mochi_prefab", None, "com"),
    "fdt_peg": ("prefabs/functional_dexterity_test/fdt_peg.mochi_prefab", None, "com"),
    # --- 작은 정육면체 ---
    "block_red": ("prefabs/box_and_blocks/block_red.mochi_prefab", None, "com"),
}
#: 납작한 판 12종. 테두리만 다르므로 **이것만으로는 모양 다양성이 안 된다**(위 주석).
OBJECTS.update({name: (SHAPE_BOX, name, "com") for name in SHAPE_BOX_PIECES})

#: ⚠️ **벽이 얇은 물체를 넣을 때 확인할 기준.**
#:
#: 물리 계산에서 손가락이 물체 표면을 **0.5~0.7 mm 파고드는 것은 정상**이다(2026-09-17
#: 실측: 쥐는 힘·미는 힘·계산 간격을 바꿔도 이 값이 거의 안 변한다 — 엔진이 접촉에
#: 허용하는 고정 여유다). 그러므로 **벽이 그보다 얇은 물체는 판정을 믿을 수 없다.**
#:
#: 판단 기준은 물체 이름이 아니라 **벽 두께**다:
#:   벽 두께 < 1 mm  -> 판정을 믿지 마라. 넣기 전에 확인할 것
#:   벽 두께 >= 2 mm -> 문제 없다
#:
#: paper_cup 은 한때 여기 들어 있었으나 **잘못된 판단이었다** — 실측해 보니 시뮬레이터
#: 안의 벽 두께가 **2.2 mm** 로, 현실 종이컵(0.3~0.5 mm)과 달라 아무 문제가 없다.
#: 실물 값으로 시뮬레이터를 판단하지 마라. 재고 나서 판단한다.
WALL_THICKNESS_WARN_M = 0.001
TOO_THIN = ()

#: 자세 하나당 써 볼 쥐는 방식. (끝까지 쥐는 정도, 쥐는 데 걸리는 스텝, 더 조이는 정도)
#: 여러 개를 쓰는 이유는 **자세 탓과 쥐는 방식 탓을 섞지 않기 위해서**다 — 하나라도
#: 성공하면 그 자세는 "잡히는 자세" 로 친다.
TRAJECTORIES = ((1.0, 30, 1.0), (0.8, 60, 0.9))


def _quat_z(angle_rad):
    """Z축(위아래 축) 둘레로 도는 회전. 물체를 제자리에서 빙 돌린다."""
    return (0.0, 0.0, math.sin(angle_rad / 2.0), math.cos(angle_rad / 2.0))


def _quat_x(angle_rad):
    """X축 둘레로 도는 회전. 물체를 눕힌다."""
    return (math.sin(angle_rad / 2.0), 0.0, 0.0, math.cos(angle_rad / 2.0))


def build_poses(xs, ys, zs, yaws_deg, tilts_deg):
    """훑을 자세 목록. 위치 격자 × 방향 격자."""
    rots = [("yaw{:+.0f}".format(a), _quat_z(math.radians(a))) for a in yaws_deg]
    rots += [("tilt{:+.0f}".format(a), _quat_x(math.radians(a)))
             for a in tilts_deg if abs(a) > 1e-9]
    poses = []
    for x in xs:
        for y in ys:
            for z in zs:
                for rot_name, quat in rots:
                    poses.append({
                        "place": [float(x), float(y), float(z)],
                        "place_rot": [float(v) for v in quat],
                        "rot_name": rot_name,
                    })
    return poses


def score_pose(env, pose, seeds, seed0, run_trajectory):
    """자세 하나를 채점한다. 시드마다 쥐는 방식 몇 개를 써 보고 하나라도 되면 성공."""
    env.place = np.asarray(pose["place"], dtype=float)
    env.place_rot = np.asarray(pose["place_rot"], dtype=float)
    ok, tips, drops, trials = 0, [], 0, 0
    tilts = []          # 성공한 시도에서만 모은다 — 못 잡은 것의 각도는 뜻이 없다
    for i in range(seeds):
        seed = seed0 + i
        hit, best = False, 0
        for traj in TRAJECTORIES:
            r = run_trajectory(env, seed, *traj)
            trials += 1
            hit |= r["success"]
            best = max(best, r["tips_best"])
            drops += int(r["dropped"])
            if r["success"]:
                t_end = float(r.get("tilt_end", float("nan")))
                if t_end == t_end:              # NaN 이 아니면
                    tilts.append(t_end)
        ok += int(hit)
        tips.append(best)
    return {
        "success": ok,
        "seeds": seeds,
        "rate": ok / max(1, seeds),
        "tips_best_median": float(np.median(tips)),
        "drop_rate": drops / max(1, trials),
        # 잡은 뒤 물체가 손 안에서 돌아간 각도(도). 성공한 시도만 모은 중앙값·최대값.
        # 작을수록 물체가 반듯하게 따라 올라온다. 성공이 하나도 없으면 없음(None).
        "tilt_median_deg": float(np.median(tilts)) if tilts else None,
        "tilt_max_deg": float(np.max(tilts)) if tilts else None,
    }


def report(path):
    """이미 만든 채점표를 다시 읽어 사람이 읽을 요약을 낸다.

    표가 채점표로 쓸 만한지 보는 질문은 두 가지다:
      1. 자세에 따라 결과가 갈리는가 (다 성공/다 실패면 가르칠 게 없다)
      2. **물체마다 좋은 자세가 다른가** — 다 같으면 자세 하나로 고정하면 되고
         학습이 필요 없다. 다르면 "물체마다 자세가 다르다" 는 걸림돌이 실재한다는 뜻이다
    """
    from collections import defaultdict

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    if not rows:
        print("빈 표다: {}".format(path))
        return 1

    def key(r):
        return (tuple(r["place"]), r["rot_name"])

    objects, ok = [], defaultdict(set)
    poses = set()
    for r in rows:
        if r["object"] not in objects:
            objects.append(r["object"])
        poses.add(key(r))
        if r["rate"] >= 0.99:
            ok[r["object"]].add(key(r))

    print("채점표: {}".format(path))
    print("만든 때: {}".format(data.get("made_at", "?")))
    print("자세 {}개 × 물체 {}종 = {}칸".format(len(poses), len(objects), len(rows)))
    print()

    print("물체별 되는 자세 수 ({}개 중)".format(len(poses)))
    print("-" * 58)
    by_obj = defaultdict(list)
    for r in rows:
        by_obj[r["object"]].append(r)
    for name in objects:
        rs = by_obj[name]
        full = sum(1 for r in rs if r["rate"] >= 0.99)
        part = sum(1 for r in rs if 0.01 < r["rate"] < 0.99)
        print("  {:<12s} 다 성공 {:2d} / 가끔 {:2d} / 다 실패 {:2d}".format(
            name, full, part, len(rs) - full - part))
    print()

    print("물체별 잘 되는 자세 상위 3개")
    print("-" * 58)
    for name in objects:
        print("  [{}]".format(name))
        def _tilt(r):
            v = r.get("tilt_median_deg")
            return 999.0 if v is None else float(v)

        # 잡히는 것 먼저, 그다음 **덜 돌아간 것** 먼저 (config 의 GRASP_GOOD_TILT_DEG 참고)
        top = sorted(by_obj[name],
                     key=lambda r: (-r["rate"], _tilt(r), -r["tips_best_median"]))[:3]
        for r in top:
            x, _, z = r["place"]
            tilt = r.get("tilt_median_deg")
            print("     앞 {:.2f} m  높이 {:.2f} m  {:<8s} -> {:.0f}%  지문 {:.0f}개  기울기 {}".format(
                x, z, r["rot_name"], r["rate"] * 100, r["tips_best_median"],
                "{:.0f}도".format(tilt) if tilt is not None else "-"))
    print()

    # --- 기울기: 잡은 뒤 물체가 손 안에서 얼마나 돌아가는가 ------------------
    # 들어올렸을 때 물체가 반듯하게 따라 올라오길 원하면 이 값이 작아야 한다.
    # 아직 성공/실패 판정에는 안 넣는다 — 얼마를 넘으면 실패로 볼지는 이 분포를
    # 보고 정한다(짐작한 숫자를 먼저 박지 않는다).
    print("잡은 뒤 물체가 돌아간 각도 (성공한 자세만)")
    print("-" * 58)
    tilted = [r for r in rows if r["rate"] >= 0.99 and r.get("tilt_median_deg") is not None]
    if not tilted:
        print("  성공한 자세가 없어 잴 것이 없다")
    else:
        vals = np.asarray([r["tilt_median_deg"] for r in tilted], dtype=float)
        for lo, hi, label in ((0, 5, "5도 미만 (거의 안 돌아감)"),
                              (5, 15, "5~15도"),
                              (15, 45, "15~45도"),
                              (45, 1e9, "45도 이상 (크게 돌아감)")):
            n = int(((vals >= lo) & (vals < hi)).sum())
            print("  {:<26s} {:4d}칸 ({:3.0f}%)".format(
                label, n, 100.0 * n / len(vals)))
        print("  중앙값 {:.0f}도 / 가장 큰 것 {:.0f}도".format(
            float(np.median(vals)), float(vals.max())))
        for name in objects:
            v = [r["tilt_median_deg"] for r in by_obj[name]
                 if r["rate"] >= 0.99 and r.get("tilt_median_deg") is not None]
            if v:
                print("    {:<12s} 중앙값 {:4.0f}도 / 가장 작은 것 {:4.0f}도".format(
                    name, float(np.median(v)), float(np.min(v))))
    print()

    sets = [ok[name] for name in objects]
    shared = set.intersection(*sets) if sets else set()
    any_ok = set.union(*sets) if sets else set()
    # 기울기까지 본 "고를 만한 자세" 가 물체마다 몇 개나 남는지 — 학습 표본이 되는 수다
    thr = cfg.GRASP_GOOD_TILT_DEG
    print("기울기 {:.0f}도 이하까지 따지면 (config GRASP_GOOD_TILT_DEG)".format(thr))
    print("-" * 58)
    thin = []
    for name in objects:
        n = sum(1 for r in by_obj[name]
                if r["rate"] >= 0.99 and r.get("tilt_median_deg") is not None
                and r["tilt_median_deg"] <= thr)
        allgood = sum(1 for r in by_obj[name] if r["rate"] >= 0.99)
        print("  {:<12s} {:2d}개 (잡히는 자세 {:2d}개 중)".format(name, n, allgood))
        if n < 2:
            thin.append(name)
    if thin:
        print("  ⚠️ {}개 물체는 고를 만한 자세가 2개 미만이다: {}".format(len(thin), ", ".join(thin)))
        print("     학습이 안 되면 .env 의 RTAUTO_GRASP_GOOD_TILT_DEG 를 8~10 으로 올려 본다.")
    print()

    print("모든 물체에 다 통하는 자세 : {}개 / {}개".format(len(shared), len(poses)))
    for k in sorted(shared):
        print("    앞 {:.2f} m  옆 {:.2f} m  높이 {:.2f} m  {}".format(
            k[0][0], k[0][1], k[0][2], k[1]))
    print("어느 한 물체라도 되는 자세 : {}개".format(len(any_ok)))
    print()

    print("물체끼리 되는 자세가 얼마나 겹치나")
    print("-" * 58)
    overlaps = []
    for i, a in enumerate(objects):
        for b in objects[i + 1:]:
            inter, uni = len(ok[a] & ok[b]), len(ok[a] | ok[b])
            pct = 100.0 * inter / max(1, uni)
            overlaps.append(pct)
            print("  {:<11s} vs {:<11s} 겹침 {:2d} / 합 {:2d} = {:3.0f}%".format(
                a, b, inter, uni, pct))
    print()
    if overlaps:
        avg = sum(overlaps) / len(overlaps)
        print("평균 겹침 {:.0f}%".format(avg))
        if avg < 60:
            print("-> 물체마다 좋은 자세가 크게 다르다. 자세 하나로 고정할 수 없다는 뜻이고,")
            print("   그래서 '보이는 모양 -> 좋은 자세' 를 배우는 것(D-4)이 값어치가 있다.")
        else:
            print("-> 겹침이 크다. 자세를 고정해도 되는지 먼저 따져 봐야 한다.")
    return 0


def _floats(text):
    return [float(v) for v in str(text).split(",") if str(v).strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="채점표 — 어느 자세에서 잡히는가 (D-2)")
    ap.add_argument("--objects", default="block_red,square,ellipse",
                    help="훑을 물체. 쉼표로. 가능한 값: " + ", ".join(OBJECTS))
    ap.add_argument("--xs", default="0.03,0.04,0.05", help="손바닥 앞 거리(m)")
    ap.add_argument("--ys", default="0.0", help="좌우 치우침(m)")
    ap.add_argument("--zs", default="0.04", help="손바닥 위 높이(m)")
    ap.add_argument("--yaws", default="0,45,90", help="제자리 회전(도)")
    ap.add_argument("--tilts", default="0", help="눕히기(도). 0 은 건너뛴다")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--episode-seconds", type=float, default=1.0)
    ap.add_argument("--out", default=None, help="결과 파일 경로(기본: results 폴더에 시각으로)")
    ap.add_argument("--resume", action="store_true",
                    help="--out 파일에 이미 끝난 물체가 있으면 건너뛰고 이어서 한다")
    ap.add_argument("--report", default=None,
                    help="훑지 않고, 이미 만든 채점표 파일을 읽어 요약만 낸다")
    args = ap.parse_args()

    if args.report:
        return report(args.report)

    wanted = [o.strip() for o in args.objects.split(",") if o.strip()]
    unknown = [o for o in wanted if o not in OBJECTS]
    if unknown:
        print("모르는 물체: {}\n가능한 값: {}".format(unknown, list(OBJECTS)))
        return 2

    poses = build_poses(_floats(args.xs), _floats(args.ys), _floats(args.zs),
                        _floats(args.yaws), _floats(args.tilts))
    total = len(wanted) * len(poses)
    per_pose = args.seeds * len(TRAJECTORIES)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / "pose_score_{}.json".format(time.strftime("%Y%m%d_%H%M%S")))

    print("=== 채점표 만들기 (D-2) ===")
    print("물체 {}종 × 자세 {}개 = {}칸".format(len(wanted), len(poses), total))
    print("칸마다 {}번 잡아 본다 (시드 {} × 쥐는 방식 {})".format(
        per_pose, args.seeds, len(TRAJECTORIES)))
    print("전체 {}회. 결과 파일: {}".format(total * per_pose, out_path))
    print()

    from dg5f_grasp_env import Dg5fGraspEnv
    from gate2_oracle_search import run_trajectory

    # --resume: 이미 끝난 물체는 건너뛰고 이어서 한다
    already = {}
    if args.resume and out_path.exists():
        prev = json.loads(out_path.read_text(encoding="utf-8"))
        for r in prev.get("rows", []):
            already.setdefault(r["object"], []).append(r)
        finished = [n for n in wanted if len(already.get(n, [])) >= len(poses)]
        if finished:
            print("이어서 한다 — 이미 끝난 물체 {}종은 건너뛴다: {}".format(
                len(finished), ", ".join(finished)))
            print()

    rows = []
    t0 = time.perf_counter()
    done = 0

    def save():
        """지금까지 채운 것을 파일에 쓴다.

        ⚠️ **물체 하나가 끝날 때마다 부른다.** 전에는 끝에서 한 번만 썼는데, 세션이
        비정상 종료되면(Ctrl+C 가 아니라 프로세스가 통째로 죽는 경우) 파일이 아예
        안 생겨 몇십 분짜리 작업이 날아갔다 — 2026-09-17 에 두 번 겪었다.
        """
        out_path.write_text(json.dumps({
            "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "자세(물체를 손 기준 어디에 어떤 방향으로 두는가) 별 파지 성공 여부",
            "seeds": args.seeds, "trajectories": [list(t) for t in TRAJECTORIES],
            "episode_seconds": args.episode_seconds,
            "done": done, "total": total, "complete": done >= total,
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for obj_name in wanted:
            if len(already.get(obj_name, [])) >= len(poses):
                rows.extend(already[obj_name])
                done += len(already[obj_name])
                continue
            prefab, actor, ref = OBJECTS[obj_name]
            config = {"object_prefab": prefab, "object_ref": ref,
                      "place_jitter": 0.0, "episode_seconds": args.episode_seconds}
            if actor:
                config["object_actor"] = actor
            env = Dg5fGraspEnv(config)
            try:
                print("[{}]".format(obj_name), flush=True)
                for pose in poses:
                    got = score_pose(env, pose, args.seeds, args.seed0, run_trajectory)
                    rows.append(dict(object=obj_name, **pose, **got))
                    done += 1
                    px, py, pz = pose["place"]
                    print("   자리({:.3f},{:.3f},{:.3f}) {:>8s} -> {}/{} 성공"
                          "   지문 {:.0f}개   [{}/{}]".format(
                              px, py, pz, pose["rot_name"], got["success"], got["seeds"],
                              got["tips_best_median"], done, total), flush=True)
            finally:
                env.close()
                try:
                    import superdex.physics as physics
                    physics.destroy_scene(env.scene)  # 물체마다 씬이 쌓이지 않게
                except Exception:
                    pass
                save()          # 물체 하나 끝날 때마다 남긴다
    except KeyboardInterrupt:
        print("\n중간에 멈췄다 — 그때까지 한 것만 저장한다.")
    finally:
        save()

    seconds = time.perf_counter() - t0
    print()
    print("=" * 62)
    print("칸 {}개 채움, {:.0f}초 ({:.1f}초/칸)".format(
        len(rows), seconds, seconds / max(1, len(rows))))
    if rows:
        rates = [r["rate"] for r in rows]
        good = [r for r in rows if r["rate"] >= 0.99]
        bad = [r for r in rows if r["rate"] <= 0.01]
        print("성공률 범위: {:.0%} ~ {:.0%}   (다 성공 {}칸 / 다 실패 {}칸)".format(
            min(rates), max(rates), len(good), len(bad)))
        if max(rates) - min(rates) < 1e-9:
            print("⚠️ 모든 칸이 같은 결과다 — 자세를 바꿔도 결과가 안 변하면 채점표로 못 쓴다.")
            print("   훑는 범위(--xs/--yaws)를 넓히거나 물체를 바꿔 본다.")
        else:
            print("자세에 따라 결과가 갈린다 — 채점표로 쓸 수 있다.")
    print("결과: {}".format(out_path))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
