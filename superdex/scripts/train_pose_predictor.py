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


def _features(points, pose_pos, pose_quat):
    """예측기에 들어가는 것 **전부**. 여기 없는 것은 안 들어간다(§7-3).

    - `points`   : 카메라가 본 점들 (물체 기준 좌표)
    - `pose_pos` : 채점할 손바닥 위치
    - `pose_quat`: 채점할 손바닥 방향
    """
    return points, np.concatenate([pose_pos, pose_quat])


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

    samples = []   # (점 덩어리, 자세7, 정답, 물체이름)
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
            samples.append((cloud_f, pose_f.astype(np.float32), label, name))
    return samples, sorted(clouds_by_obj)


def make_model(torch, nn):
    """점 덩어리를 요약하고 자세와 합쳐 점수를 내는 작은 신경망."""

    class PosePredictor(nn.Module):
        def __init__(self, width=128):
            super().__init__()
            # 점 하나하나를 같은 방식으로 훑고(점 순서에 흔들리지 않게),
            # 가장 큰 값만 남겨 덩어리 전체를 한 줄로 요약한다.
            self.per_point = nn.Sequential(
                nn.Linear(3, 64), nn.ReLU(),
                nn.Linear(64, width), nn.ReLU(),
            )
            self.pose = nn.Sequential(nn.Linear(7, 64), nn.ReLU())
            self.head = nn.Sequential(
                nn.Linear(width + 64, width), nn.ReLU(),
                nn.Linear(width, 1),
            )

        def forward(self, cloud, pose):        # cloud (B, N, 3), pose (B, 7)
            shape = self.per_point(cloud).max(dim=1).values
            return self.head(torch.cat([shape, self.pose(pose)], dim=1)).squeeze(1)

    return PosePredictor


def batches(torch, samples, rng, size, device):
    """학습용 묶음. 장마다 점 수가 달라 정해진 개수만큼 뽑아 쓴다."""
    order = rng.permutation(len(samples))
    for i in range(0, len(order), size):
        idx = order[i:i + size]
        clouds, poses, labels = [], [], []
        for j in idx:
            cloud, pose, label, _ = samples[j]
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


def main() -> int:
    ap = argparse.ArgumentParser(description="자세 채점 예측기 학습 (D-4)")
    ap.add_argument("--data", required=True, help="build_pose_dataset.py 가 만든 npz")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu", help="cpu 또는 cuda")
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
    print("입력     : 점 좌표 {}개 + 자세 7개 — **그 밖에는 없다** (§7-3)".format(
        POINTS_PER_SAMPLE))
    print("좋은 자세: 잡히고(성공률 {:.0%} 이상) **그리고** 잡은 뒤 {:.0f}도 이하로 돌아간 것".format(
        GOOD_RATE, MAX_TILT_DEG))
    print("채점 방식: 물체 하나를 빼고 배운 뒤 **뺀 물체로** 시험한다")
    print()

    PosePredictor = make_model(torch, nn)
    rows = []
    t0 = time.perf_counter()

    for held_out in objects:
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
        rows.append((held_out, tr_acc, tr_f1, te_acc, te_f1, n))
        print("  [{:<10s}] 배운 것 맞힘 {:.0%} (F1 {:.2f})  |  "
              "**안 배운 물체** 맞힘 {:.0%} (F1 {:.2f}, {}짝)".format(
                  held_out, tr_acc, tr_f1, te_acc, te_f1, n), flush=True)

    print()
    print("=" * 66)
    if rows:
        tr = float(np.mean([r[1] for r in rows]))
        te = float(np.mean([r[3] for r in rows]))
        te_f1 = float(np.mean([r[4] for r in rows]))
        print("평균: 배운 것 {:.0%}  /  **안 배운 물체 {:.0%}** (F1 {:.2f})".format(
            tr, te, te_f1))
        base = float(labels.mean())
        print("그냥 '다 좋다' 라고 찍으면 {:.0%} — 이보다 나아야 배운 것이다".format(
            max(base, 1 - base)))
        print()
        if te < max(base, 1 - base) + 0.05:
            print("판정: **아직 못 넘었다.** 배관은 돌아가지만 안 배운 물체로 넘어가지 못한다.")
            print("      물체 4종·점 덩어리 32장으로는 당연한 결과다 — 데이터를 늘려야 한다.")
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
