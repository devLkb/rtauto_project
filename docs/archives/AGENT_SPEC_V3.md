---
title: DG5FStableGrasp Packaged Environment Spec
version: 3.0.0
status: active
---

# DG5FStableGrasp packaged environment 3.0.0

The Linux player distributed as
`DG5FStableGrasp-v3.0.0-linux-x86_64-20260718.tar.xz` is an external,
versioned V3 environment. It must not overwrite the repository-built V2
`DG5FGraspJoint26HandFirst` player.

## Policy contract

- Behavior: `DG5FStableGrasp`
- vector observations: 116
- continuous actions: 26
- curriculum parameter: `stable_grasp_stage`
- training areas: 20

The policy tensor shapes are identical to the repository's joint26 policy.
Operational `dg5f v2` therefore creates a read-only behavior-name bridge from
the verified bootstrap's `DG5FGraspJoint/checkpoint.pt` to
`DG5FStableGrasp/checkpoint.pt`, then starts a new run at step zero.

## Stable whole-hand stages

The values below are embedded constants in the packaged
`KDT.GraspTraining.dll`.

1. Acquire stable contact: thumb plus at least two non-thumb contacts held for
   0.5 seconds. No lift or post-lift hold is required.
2. Lift by 2 cm and hold at or above 2 cm for 0.5 seconds.
3. Lift by 5 cm and hold at or above 4 cm for 1 second.

The ball's maximum stable linear speed during a valid hold is 0.05 m/s.
Successful completion adds `+3.0`; acquiring the stable grasp adds `+0.5`.
Approach, per-finger contact, lift, and stable-hold potential rewards are also
used.

## Local installation contract

The package payload is installed at `training/builds/DG5FGraspV3`.
`training/manifests/DG5FStableGrasp-v3.0.0.json` records the package hashes and
policy names (an adjacent `DG5F_ENVIRONMENT.json` may contain the same data).
The training launcher validates the manifest against both the binaries and
`training/config/dg5f_grasp_v3.yaml` before starting ML-Agents.
