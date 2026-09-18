# -*- coding: utf-8 -*-
"""예측기 학습 — 점 덩어리를 보고 "이 자세가 좋은가" 를 채점한다 (D-4).

무엇을 배우나
-------------
`(점 덩어리, 자세 후보) -> 이 자세로 잡으면 성공할까` 를 배운다.

**자세를 직접 내놓게 하지 않는 이유**: 물체 하나에 좋은 자세가 여러 개다(실측 12~23개).
하나만 내놓게 하면 여러 답의 **평균**이 나오는데, 평균은 대개 아무 데도 아니다.
채점 방식이면 여러 답이 다 높은 점수를 받을 수 있고, **실패한 자세도 학습에 쓴다**
(첫 채점표에서 성공 75칸 : 실패 213칸 — 실패 쪽이 훨씬 많다).

쓸 때는 자세 후보를 여러 개 넣어 보고 **가장 높은 점수**를 고르면 된다.

⚠️ 입력에 넣는 것 — §7-3
------------------------
[`docs/FESTA_PREGRASP_PLAN.md`](../../docs/FESTA_PREGRASP_PLAN.md) §7-3 에 따라
**점 좌표와 자세 후보뿐**이다. 물체 이름도, 시뮬레이터만 아는 값도 넣지 않는다.
코드에서 `_features()` 하나만 보면 무엇이 들어가는지 알 수 있게 모아 뒀다.

어떻게 채점하나 — 학습에 안 쓴 물체로
--------------------------------------
물체 하나를 빼고 나머지로 배운 뒤, **뺀 물체로 시험한다**(물체 수만큼 반복).
이게 이 프로젝트의 목적("처음 보는 물체")을 그대로 재는 방식이다.
학습에 쓴 물체로 재면 외운 것도 잘 나오므로 의미가 없다.

실행
----
터미널 1 (PowerShell, 리포 루트):

    superdex/.venv/Scripts/Activate.ps1
    python -u superdex/scripts/train_pose_predictor.py --data superdex/results/pose_dataset_<시각>.npz
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "config"))

import rtauto_config as cfg  # noqa: E402  (기준값의 유일한 출처 — 원칙 1)

RESULTS_DIR = REPO_ROOT / "superdex" / "results"

#: 한 점 덩어리에서 뽑아 쓸 점 개수. 장마다 점 수가 달라 맞춰 준다(실측 168~468개).
POINTS_PER_SAMPLE = 256

#: 성공/실패로 볼 경계. 그 사이(가끔 되는 것)는 **학습에서 뺀다** — 애매한 것을
#: 한쪽으로 몰면 잘못 가르치게 된다. 첫 채점표는 시드가 3개라 사이값이 아예 없었다.
GOOD_RATE = 0.99
BAD_RATE = 0.01

#: 잡은 뒤 물체가 이보다 많이 돌아가면, **잡히더라도 고르고 싶지 않은 자세**로 본다.
#: 정본은 config 하나뿐이다(숫자를 여기 베끼지 않는다).
#:
#: ⚠️ **그런 자세를 버리지 않고 "나쁜 예"로 넣는다.** 버리면 표본이 124개에서 42개로
#:    줄어 학습할 거리가 모자란다(2026-09-18 실측). 자리를 옮기면 표본 수는 그대로이고
#:    정답만 바뀐다 — 그리고 "잡히긴 하는데 돌아가는 자세" 와 "깔끔하게 잡히는 자세" 를
#:    가르는 것이야말로 모양을 제대로 봐야 풀리는 문제다.
MAX_TILT_DEG = cfg.GRASP_GOOD_TILT_DEG


#: 길이 값(미터)에 곱하는 수. 0.05 m 를 1.0 으로 만든다.
#:
#: ⚠️ **왜 필요한가 — 2026-09-18 실측으로 드러난 원인.** 미터로 그냥 넣으면 점 좌표가
#: 0.01~0.05, 손바닥 위치가 0.03~0.05 라 신경망 입장에서는 거의 0 을 넣는 것과 같다.
#: 안쪽 계산이 전부 0 근처로 눌려 학습이 굴러가지 않는다. 실제로 **배운 데이터에서조차
#: 맞힘 57%** (반반 찍기 수준)가 나왔다 — 못 외운 것이지 못 일반화한 것이 아니었다.
#:
#: 단위만 바꾸는 것이라 **정보는 하나도 안 버린다**(크기 정보도 그대로 남는다).
#: 물체 크기를 재서 나누는 방식은 크기 정보를 없애 버리므로 쓰지 않는다 — 큰 물체와
#: 작은 물체는 잡는 자세가 다르다.
LENGTH_SCALE = 20.0


def _quat_to_matrix(q):
    """쿼터니언 (x, y, z, w) → 3x3."""
    x, y, z, w = [float(v) for v in q]
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _features(points, pose_pos, pose_quat):
    """예측기에 들어가는 것 **전부**. 여기 없는 것은 안 들어간다(§7-3).

    점 덩어리를 **손바닥 기준으로 옮겨서** 넣는다. 자세는 이 옮기기에 이미 다 들어가
    있으므로 따로 넣지 않는다.

    ⚠️ **왜 이렇게 바꿨나 — 2026-09-18 에 찾은 구조적 결함.**
    전에는 물체 기준 점 덩어리와 자세 7개를 **따로** 넣고 각각 요약한 뒤 합쳤다.
    그런데 모양을 요약하는 단계에서 자세를 아직 못 봤기 때문에, **"내 손 앞에 물체가
    있나" 를 계산할 방법이 아예 없었다.** 아무리 오래 학습시켜도 못 만드는 정보다.

    실제로 그 구조로 낸 성적(1등 15% / 3등 안 62%)이 두 줄짜리 계산 규칙
    (`geometric_pose_score.py`)과 **소수점까지 같았다.** 신경망이 할 수 있는 최선이
    딱 그 수준이었다는 뜻이다. 그 계산 규칙이 맨 먼저 하는 일이 바로 이 옮기기다.

    이제 신경망은 "손 앞 3 cm 에 뭐가 있다" 를 처음부터 보고, 거기서 **더** 배울 수 있다.
    입력은 여전히 점 덩어리와 자세 후보뿐이라 §7-3 은 그대로 지킨다.
    """
    rot = _quat_to_matrix(pose_quat)
    # 물체 기준 점 -> 손바닥 기준 점
    local = (np.asarray(points, dtype=np.float64)
             - np.asarray(pose_pos, dtype=np.float64)) @ rot
    # 길이 값을 키운다(미터 그대로면 0 에 눌려 학습이 안 굴러간다 — 위 LENGTH_SCALE 설명)
    return local.astype(np.float32) * LENGTH_SCALE, np.asarray(pose_quat, dtype=np.float32)


def load_pairs(path):
    """저장된 데이터를 `(점 덩어리, 자세, 정답)` 짝으로 편다."""
    data = np.load(path, allow_pickle=True)
    pts = data["points"].astype(np.float32)
    start = data["cloud_start"]
    cloud_obj = data["cloud_object"]
    pose_pos = data["pose_pos"].astype(np.float32)
    pose_quat = data["pose_quat"].astype(np.float32)
    rate = data["pose_rate"].astype(np.float32)
    # 기울기가 없는 옛 파일도 읽히게 한다 — 없으면 "안 돌아간 것" 으로 둬서
    # 예전과 똑같이 동작한다(조용히 달라지지 않게).
    tilt = (data["pose_tilt"].astype(np.float32) if "pose_tilt" in data.files
            else np.zeros_like(rate))
    pose_obj = data["pose_object"]

    clouds_by_obj = {}
    for i, name in enumerate(cloud_obj):
        clouds_by_obj.setdefault(str(name), []).append(pts[start[i]:start[i + 1]])

    samples = []   # (점 덩어리, 자세7, 정답, 물체이름, 자세번호)
    for k in range(len(rate)):
        r = float(rate[k])
        if BAD_RATE < r < GOOD_RATE:
            continue                      # 애매한 것은 뺀다
        name = str(pose_obj[k])
        # 좋은 자세 = 잡히고 **그리고** 잡은 뒤 별로 안 돌아간다.
        # 잡히지만 많이 돌아가는 자세는 버리지 않고 **나쁜 예**로 넣는다.
        label = 1.0 if (r >= GOOD_RATE and float(tilt[k]) <= MAX_TILT_DEG) else 0.0
        for cloud in clouds_by_obj.get(name, []):
            cloud_f, pose_f = _features(cloud, pose_pos[k], pose_quat[k])
            samples.append((cloud_f, pose_f.astype(np.float32), label, name, k))
    return samples, sorted(clouds_by_obj)


def make_model(torch, nn):
    """점 덩어리를 요약하고 자세와 합쳐 점수를 내는 작은 신경망."""

    class PosePredictor(nn.Module):
        def __init__(self, width=128):
            super().__init__()
            # 점 하나하나를 같은 방식으로 훑은 뒤(점 순서에 흔들리지 않게),
            # **평균과 최대값을 둘 다** 남겨 덩어리 전체를 한 줄로 요약한다.
            #
            # ⚠️ **왜 평균이 꼭 있어야 하나 — 2026-09-18 에 찾은 두 번째 구조적 결함.**
            # 우리가 판단해야 하는 것은 "손 안에 물체가 **얼마나** 들었나" 다.
            # 그런데 최대값만 남기면 **세는 것이 불가능**하다 — 점 하나만 들어와도 값이
            # 꽉 차 버려서 100개 들어온 것과 구분이 안 된다.
            # 즉 최대값만 쓰는 구조로는 두 줄짜리 계산 규칙
            # (`geometric_pose_score.py`)조차 흉내 낼 수 없다.
            # 평균을 쓰면 그대로 "비율" 이 되므로 그 규칙을 포함할 수 있고,
            # 거기서 더 배울 수 있다.
            # 최대값도 함께 남긴다 — "가장 튀어나온 곳이 어디냐" 는 따로 쓸모가 있다.
            self.per_point = nn.Sequential(
                nn.Linear(3, 64), nn.ReLU(),
                nn.Linear(64, width), nn.ReLU(),
            )
            # 자세 위치는 점 덩어리를 옮길 때 이미 반영됐다. 남는 것은 방향뿐인데,
            # 이것도 "물체가 손 기준 어디 있나" 에 이미 들어가 있어 사실상 덤이다.
            # (중력 방향처럼 손 기준으로만은 알 수 없는 것을 나중에 넣을 자리로 남긴다)
            self.pose = nn.Sequential(nn.Linear(4, 64), nn.ReLU())
            self.head = nn.Sequential(
                nn.Linear(2 * width + 64, width), nn.ReLU(),
                nn.Linear(width, 1),
            )

        def forward(self, cloud, pose):        # cloud (B, N, 3) 손바닥 기준, pose (B, 4)
            per = self.per_point(cloud)
            shape = torch.cat([per.mean(dim=1), per.max(dim=1).values], dim=1)
            return self.head(torch.cat([shape, self.pose(pose)], dim=1)).squeeze(1)

    return PosePredictor


def batches(torch, samples, rng, size, device):
    """학습용 묶음. 장마다 점 수가 달라 정해진 개수만큼 뽑아 쓴다."""
    order = rng.permutation(len(samples))
    for i in range(0, len(order), size):
        idx = order[i:i + size]
        clouds, poses, labels = [], [], []
        for j in idx:
            cloud, pose, label = samples[j][:3]
            pick = rng.integers(0, len(cloud), POINTS_PER_SAMPLE)
            clouds.append(cloud[pick])
            poses.append(pose)
            labels.append(label)
        yield (torch.as_tensor(np.stack(clouds), device=device),
               torch.as_tensor(np.stack(poses), device=device),
               torch.as_tensor(np.asarray(labels, dtype=np.float32), device=device))


def evaluate(torch, model, samples, rng, device):
    """맞힌 비율과, 정답이 치우친 것을 감안한 지표."""
    if not samples:
        return float("nan"), float("nan"), 0
    model.eval()
    hits, n = 0, 0
    tp = fp = fn = tn = 0
    with torch.no_grad():
        for cloud, pose, label in batches(torch, samples, rng, 64, device):
            prob = torch.sigmoid(model(cloud, pose))
            pred = (prob >= 0.5).float()
            hits += int((pred == label).sum())
            n += len(label)
            tp += int(((pred == 1) & (label == 1)).sum())
            fp += int(((pred == 1) & (label == 0)).sum())
            fn += int(((pred == 0) & (label == 1)).sum())
            tn += int(((pred == 0) & (label == 0)).sum())
    acc = hits / max(1, n)
    # 좋은 자세를 좋다고 맞히는 비율(재현율)과, 좋다고 한 것 중 실제로 좋은 비율(정밀도)
    recall = tp / max(1, tp + fn)
    prec = tp / max(1, tp + fp)
    f1 = 2 * prec * recall / max(1e-9, prec + recall)
    return acc, f1, n


#: ⚠️ **좋은 자세가 0개인 물체는 채점에서 뺀다.** 어떤 방법을 써도 무조건 실패라서
#: 평균만 깎고 방법끼리의 차이를 가리지 못한다. 대신 **몇 종이 그랬는지 따로 적는다** —
#: 숨기는 것이 아니라 "이 물체는 지금 기준으로는 아예 못 잡는다" 는 별개의 사실이다.
#: (2026-09-18: sphere 는 둥글어 손 안에서 구르고, duck_lamp 는 물렁해 전부 5도를 넘었다)


def rank_poses(torch, model, samples, rng, device, topk=(1, 3)):
    """**실제로 쓸 방식 그대로 채점한다** — 후보를 전부 매기고 위에서 몇 개를 고른다.

    왜 "맞힌 비율" 로는 부족한가
    ----------------------------
    좋은 자세가 14% 뿐이라, **"다 나쁘다" 라고 찍기만 해도 맞힌 비율이 86%** 다.
    그런데 그건 자세를 **하나도 안 내놓는다** — 쓸모가 0인데 점수는 가장 높다.

    우리가 실제로 하는 일은 "이 자세가 좋은가/나쁜가" 를 맞히는 게 아니라
    **후보 여러 개 중 하나를 고르는 것**이다. 그래서 물어야 할 것은
    **"고른 자세가 진짜 좋은 자세였나"** 다. 아무거나 찍으면 14% 다.

    같은 자세가 점 덩어리 여러 장과 짝지어 있으므로 **자세별로 점수를 평균**낸다
    (한 장에서 우연히 높게 나온 것을 고르지 않게).
    """
    if not samples:
        return {k: float("nan") for k in topk}, 0, float("nan")
    model.eval()
    scores, labels = {}, {}
    with torch.no_grad():
        for i in range(0, len(samples), 64):
            chunk = samples[i:i + 64]
            clouds, poses = [], []
            for cloud, pose, _, _, _ in chunk:
                pick = rng.integers(0, len(cloud), POINTS_PER_SAMPLE)
                clouds.append(cloud[pick])
                poses.append(pose)
            prob = torch.sigmoid(model(
                torch.as_tensor(np.stack(clouds), device=device),
                torch.as_tensor(np.stack(poses), device=device))).cpu().numpy()
            for (_, _, label, _, key), pr in zip(chunk, prob):
                scores.setdefault(key, []).append(float(pr))
                labels[key] = float(label)

    order = sorted(scores, key=lambda k: -float(np.mean(scores[k])))
    good_rate = float(np.mean([labels[k] for k in order]))     # 아무거나 찍었을 때
    out = {}
    for k in topk:
        top = order[:k]
        out[k] = float(any(labels[t] >= 0.5 for t in top)) if top else float("nan")
    return out, len(order), good_rate


def main() -> int:
    ap = argparse.ArgumentParser(description="자세 채점 예측기 학습 (D-4)")
    ap.add_argument("--data", required=True, help="build_pose_dataset.py 가 만든 npz")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu", help="cpu 또는 cuda")
    ap.add_argument("--fit-check", action="store_true",
                    help="**진단용.** 물체 하나로 배우고 **그 물체로** 시험한다(빼지 않는다). "
                         "외우는 것조차 못 하면 데이터가 아니라 입력·구조 문제다")
    args = ap.parse_args()

    import torch
    from torch import nn

    device = torch.device(args.device)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    samples, objects = load_pairs(args.data)
    labels = np.asarray([s[2] for s in samples])

    print("=== 자세 채점 예측기 (D-4) ===")
    print("데이터   : {}".format(args.data))
    print("짝       : {}개 (좋은 자세 {:.0f}% / 나쁜 자세 {:.0f}%)".format(
        len(samples), 100 * labels.mean(), 100 * (1 - labels.mean())))
    print("물체     : {}".format(", ".join(objects)))
    print("입력     : **손바닥 기준으로 옮긴** 점 좌표 {}개 + 손바닥 방향 4개".format(
        POINTS_PER_SAMPLE))
    print("           — 그 밖에는 없다 (§7-3)")
    print("좋은 자세: 잡히고(성공률 {:.0%} 이상) **그리고** 잡은 뒤 {:.0f}도 이하로 돌아간 것".format(
        GOOD_RATE, MAX_TILT_DEG))
    print("채점 방식: 물체 하나를 빼고 배운 뒤 **뺀 물체로** 시험한다")
    print()

    PosePredictor = make_model(torch, nn)
    rows = []
    impossible = []
    t0 = time.perf_counter()

    if args.fit_check:
        print("⚠️ **진단 모드** — 물체 하나로 배우고 **그 물체로** 시험한다(안 빼고).")
        print("   여기서도 못 맞히면 모양 수를 늘려도 소용없다 — 입력·구조 문제다.")
        print()

    for held_out in objects:
        if args.fit_check:
            train = [s for s in samples if s[3] == held_out]
            test = train
        else:
            train = [s for s in samples if s[3] != held_out]
            test = [s for s in samples if s[3] == held_out]
        if not train or not test:
            continue
        model = PosePredictor().to(device)
        opt = torch.optim.Adam(model.parameters(), lr=args.lr)
        # 좋은 자세가 적으므로(약 26%) 그쪽에 가중치를 준다
        train_labels = np.asarray([s[2] for s in train])
        pos_weight = torch.as_tensor(
            float((1 - train_labels).sum() / max(1.0, train_labels.sum())), device=device)
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        for _ in range(args.epochs):
            model.train()
            for cloud, pose, label in batches(torch, train, rng, args.batch, device):
                opt.zero_grad()
                loss_fn(model(cloud, pose), label).backward()
                opt.step()

        tr_acc, tr_f1, _ = evaluate(torch, model, train, rng, device)
        te_acc, te_f1, n = evaluate(torch, model, test, rng, device)
        top, n_poses, chance = rank_poses(torch, model, test, rng, device)
        if chance <= 0.0:
            # 좋은 자세가 0개인 물체 — 어떤 방법도 무조건 실패라 평균만 깎는다(위 주석)
            impossible.append(held_out)
            print("  [{:<10s}] — 좋은 자세가 0개라 채점에서 뺀다".format(held_out), flush=True)
            continue
        rows.append((held_out, tr_acc, tr_f1, te_acc, te_f1, n, top[1], top[3], chance))
        print("  [{:<10s}] 배운 것 {:.0%}(F1 {:.2f}) | 안 배운 물체 {:.0%}(F1 {:.2f}) | "
              "**고른 자세가 좋았나** 1등 {} / 3등 안 {}  (후보 {}개, 아무거나 찍으면 {:.0%})".format(
                  held_out, tr_acc, tr_f1, te_acc, te_f1,
                  "O" if top[1] >= 0.5 else "X", "O" if top[3] >= 0.5 else "X",
                  n_poses, chance), flush=True)

    print()
    print("=" * 66)
    if rows:
        tr = float(np.mean([r[1] for r in rows]))
        te = float(np.mean([r[3] for r in rows]))
        te_f1 = float(np.mean([r[4] for r in rows]))
        print("평균: 배운 것 {:.0%}  /  **안 배운 물체 {:.0%}** (F1 {:.2f})".format(
            tr, te, te_f1))
        top1 = float(np.mean([r[6] for r in rows]))
        top3 = float(np.mean([r[7] for r in rows]))
        chance = float(np.mean([r[8] for r in rows]))
        print()
        print("**실제 쓰임 그대로 — 후보를 다 매기고 위에서 고르기**")
        print("  1등으로 고른 자세가 좋은 자세였던 물체: {:.0%} ({}종 중 {}종)".format(
            top1, len(rows), int(round(top1 * len(rows)))))
        print("  3등 안에 좋은 자세가 있던 물체      : {:.0%} ({}종 중 {}종)".format(
            top3, len(rows), int(round(top3 * len(rows)))))
        print("  아무거나 찍었을 때                 : {:.0%}".format(chance))
        if impossible:
            print("  ⚠️ 좋은 자세가 0개라 뺀 물체 {}종: {}".format(
                len(impossible), ", ".join(impossible)))
        print()
        base = float(labels.mean())
        # ⚠️ 어느 쪽으로 찍는 게 유리한지 **정답 비율을 보고 정한다.** 전에는 비율과
        #    무관하게 늘 "다 좋다" 라고 적어서, 좋은 자세가 14% 인 이 데이터에서
        #    사실과 반대로 보고됐다(2026-09-18 발견).
        lazy = "다 좋다" if base >= 0.5 else "다 나쁘다"
        print("그냥 '{}' 라고 찍으면 {:.0%} — 이보다 나아야 배운 것이다".format(
            lazy, max(base, 1 - base)))
        print()
        # 판정은 **고르기 성적**으로 한다. 맞힌 비율은 참고만 한다 — 좋은 자세가 14%
        # 뿐이라 "다 나쁘다" 라고 찍기만 해도 86% 가 나오는데, 그건 자세를 하나도
        # 안 내놓는 쓸모없는 답이기 때문이다(2026-09-18 판단).
        print("=" * 66)
        if top1 >= 0.7:
            print("판정: **쓸 만하다.** 안 배운 물체에서도 1등으로 고른 자세가 대체로 맞다.")
        elif top3 >= 0.7:
            print("판정: **반쯤 된다.** 1등은 자주 틀리지만 3등 안에는 들어온다 —")
            print("      후보 3개를 다 시도하는 방식이면 쓸 수 있다.")
        elif top1 > chance + 0.15:
            print("판정: **배우고는 있다.** 아무거나 찍는 것보다 확실히 낫지만 아직 모자라다.")
        else:
            print("판정: **아직 못 넘었다.** 아무거나 찍는 것과 크게 다르지 않다.")
        print()
        if te < max(base, 1 - base) + 0.05:
            print("(참고) 맞힌 비율만 보면 기준선을 못 넘는다.")
            # 원인을 데이터 탓으로 넘기기 전에 **배운 것부터 맞히는지** 본다.
            # 배운 것도 못 맞히면 데이터가 아니라 학습 쪽 문제다(2026-09-18 실측에서
            # 물체를 4종->13종으로 늘려도 안 변한 이유가 이것이었다).
            if tr < max(base, 1 - base) - 0.05:
                print("      ⚠️ **배운 데이터조차 못 맞힌다({:.0%}).** 데이터가 모자란 게".format(tr))
                print("         아니라 학습 쪽 문제다 — 입력 크기·모델 크기·학습 횟수를 본다.")
            else:
                print("      배운 것은 맞히는데 안 배운 물체에서 떨어진다 — 물체를 늘린다.")
        elif tr - te > 0.25:
            print("판정: **외우고 있다.** 배운 것은 잘 맞히는데 안 배운 물체에서 크게 떨어진다.")
            print("      물체 수를 늘리는 것이 먼저다.")
        else:
            print("판정: 안 배운 물체로도 넘어간다. 데이터를 늘려 더 확인할 값어치가 있다.")
    print("걸린 시간 {:.0f}초".format(time.perf_counter() - t0))
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
