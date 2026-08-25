using System;
using Unity.MLAgents;
using UnityEngine;

namespace KDT.GraspLiftTraining
{
    /// <summary>
    /// Policy shape and task contract for the DG5F grasp + lift stage.
    ///
    /// Design notes (see docs/DG5F_GRASP_LIFT.md):
    /// * The Isaac Lab reference (VAlikV/IsaacLab_delto_envs) proves the shape of the
    ///   task — approach, close on the object, confirm several opposed contacts, then
    ///   lift and require the object to actually rise. Only that logic is reused; the
    ///   implementation below is written against Unity physics and ML-Agents.
    /// * Observation/action shapes intentionally match the 57/7 reach contract so the
    ///   already-trained pre-grasp reach policy can seed this run via
    ///   `mlagents-learn --initialize-from`. Slots 0..48 keep their reach meaning;
    ///   slots 49..56 carry the new grasp/lift state.
    /// </summary>
    public static class Dg5fGraspLiftSpec
    {
        public const string SpecVersion = "1.0.0";
        public const string BehaviorName = "DG5FGraspLift";
        public const int ObservationSize = 57;
        public const int ActionSize = 7;
        public const int ArmJointCount = 6;
        public const int HandJointCount = 20;
        public const int FingerCount = 5;
        // Fingertips (5) + palm. The palm is a legitimate grasp contact for a
        // power grasp, so it participates in the contact count and the opposition
        // test just like a fingertip.
        public const int ContactPointCount = FingerCount + 1;
        public const int PalmContactIndex = FingerCount;

        // --- episode ------------------------------------------------------------
        // 20 s at a 0.1 s decision period is ~200 decisions: enough for approach +
        // close + lift without letting a stalled policy burn a whole buffer.
        public const float EpisodeTimeoutSeconds = 20f;
        // Small per-decision cost so dithering in place is never free.
        public const float DecisionTimePenalty = -0.001f;

        // --- workspace ----------------------------------------------------------
        // Identical to the reach task so the scene layout (and the transferred
        // policy's sense of scale) stays unchanged.
        public const float PanelWidth = 1.80f;
        public const float PanelDepth = 1.80f;
        public const float PanelThickness = 0.25f;
        public const float SupportTopHeight = 0f;
        // Equal to the arm's reach: was 0.85 m for UR5e (850 mm), now 0.90 m for
        // the confirmed UR16e (900 mm reach). See docs/SIM2REAL_ROADMAP.md Phase 0
        // for the hardware confirmation; PanelWidth/PanelDepth above are NOT
        // reach-derived (kept fixed on purpose, see comment above) so they did not
        // need to change.
        public const float MaximumObjectDistance = 0.90f;

        // Grasping is much harder than reaching, so the object spawns in a
        // narrower annulus than the reach task's 0.35..0.70 m. Scaled from the
        // UR5e-tuned 0.35..0.55 m by the UR16e/UR5e reach ratio (0.90/0.85 =
        // 1.0588) so the annulus keeps the same fraction of arm reach — i.e. the
        // task keeps the same relative difficulty rather than the same absolute
        // distance on a longer arm. Verified reachable by forward kinematics
        // against the built ur16e_dg5f_right.sim.mjcf.xml (wrist_3 horizontal
        // radius spans ~0.07-0.91 m across the ArmSafeMinDeg/MaxDeg envelope, so
        // this annulus sits well inside it).
        public const float MinimumSpawnRadius = 0.37f;
        public const float MaximumSpawnRadius = 0.58f;

        // --- block geometry -----------------------------------------------------
        // 0.035 m square cross section: GraspLiftHandGeometryProbe measured the
        // closed-hand thumb-to-finger opposition aperture at 3.1-3.6 cm, so the
        // original 5.5 cm face could not be opposed at all.
        //
        // Height now defaults to 0.12 m. The earlier 98.7% training-condition and
        // 96.3% uniform-density results used the old 0.09 m height / 0.30 COM pair.
        // At that height the roughly 0.13 m fingers had to reach below the block
        // midpoint, making panel contact a precondition of success: a -0.5/s surface
        // penalty reduced contact by only 1.5%. At 0.12 m the graspable region clears
        // the panel, matching the original design rationale and moving toward the
        // Isaac Lab reference's 0.15 m cylinder. The retrained 0.12 m / 0.20 COM
        // policy measured 99.75% success versus 98.95% for the deployed 0.09 m
        // policy, and 99.24% versus 96.32% on uniform density despite a harsher
        // 16 deg topple limit versus 21 deg. It also improved GraspConfirmed
        // (99.79% vs 99.39%), FinalLiftHeight (0.1456 m vs 0.142 m; 0.1432 m on
        // uniform density), HandSurfaceContactSeconds (1.05 s vs 3.45 s),
        // GraspPostureAngleDegrees (67.1 deg vs 72.8 deg), ObjectToppled
        // (1.0 vs 1.11), and Dropped (1.0 vs 1.2).
        //
        // Height remains runtime configurable up to the 0.15 m reference scale so
        // geometry experiments do not require rebuilding the player.
        //
        // Width and height are defaults: the live values come from the `block_width`
        // and `block_height` environment parameters (see CurrentBlockWidth and
        // CurrentBlockHeight).
        public const float BlockWidth = 0.035f;
        public const float BlockHeight = 0.12f;
        public const float MinimumBlockWidth = 0.025f;
        public const float MaximumBlockWidth = 0.060f;
        public const float MinimumBlockHeight = 0.06f;
        public const float MaximumBlockHeight = 0.15f;
        // Mass follows volume, so a wider or taller block is also heavier and
        // difficulty scales the way a real object would.
        //
        // Density raised from 400 to 1800 kg/m^3 (the 0.035 x 0.12 m default is
        // ~0.265 kg, in line with the Isaac Lab reference's 0.3 kg object). At
        // 400 kg/m^3 the old 0.09 m block weighed about 44 g and any incidental
        // fingertip brush sent it skidding, so the policy learned that closing its
        // hand near the block ended the episode and settled on hovering with the
        // hand open (measured: ContactCount 1.25, FinalClosure 0.3, zero lift). A
        // heavier block resists being nudged while still being well within what 20 N
        // finger drives can hold through friction.
        public const float BlockDensity = 1800f;
        public const float BlockHalfHeight = BlockHeight * 0.5f;
        public const string BlockWidthParameterName = "block_width";
        public const string BlockHeightParameterName = "block_height";

        // A uniform-density 0.035 x 0.09 m block standing on the panel tips at
        // atan(0.0175/0.045) = ~21 deg, which any incidental fingertip brush during
        // the descent exceeds. Measured consequence across four runs:
        // FinalLiftHeight settled at -0.021 m, almost exactly the -0.0275 m a toppled
        // block's centre drops, i.e. the block was on its side by the end of nearly
        // every episode.
        //
        // Dropping the centre of mass toward the base is the same trick a weighted
        // desk object uses: the static tip angle becomes atan(halfWidth / comHeight),
        // so the old 0.30 fraction raised it from ~21 deg to ~33 deg without changing
        // the geometry the hand has to grasp. The earlier 98.7% training-condition
        // and 96.3% uniform-density results were measured with that old 0.09 m /
        // 0.30 pair. Expressed as a fraction of the block height measured from its
        // base; 0.5 is the neutral (uniform-density) value.
        //
        // Candidate-height trade-off for a 0.035 m wide block, using
        // tipAngle = atan(halfWidth / comHeight) and
        // comHeight = fraction * height:
        // * height 0.09 m, fraction 0.30 -> ~33 deg
        // * height 0.12 m, fraction 0.30 -> ~26 deg
        // * height 0.12 m, fraction 0.20 -> ~36 deg
        // The 0.12 m default therefore uses 0.20: its ~36 deg static tip angle
        // preserves rather than trades away the old pair's ~33 deg stability. With
        // centre-of-mass lowering plus the ObjectToppled terminal, the retrained
        // policy improved every measured comparison listed in the height rationale:
        // 99.75%/99.24% success, 99.79% GraspConfirmed, 0.1456 m lift (0.1432 m
        // uniform density), 1.05 s panel contact, 67.1 deg posture, and 1.0 for both
        // ObjectToppled and Dropped. This is what makes the taller geometry viable
        // without returning to the old toppling local optimum.
        public const float BlockComHeightFraction = 0.20f;
        public const string BlockComHeightFractionParameterName = "block_com_height_fraction";
        public const float MinimumBlockComHeightFraction = 0.05f;
        public const float MaximumBlockComHeightFraction = 0.50f;

        static float _blockWidth = BlockWidth;
        static float _blockHeight = BlockHeight;
        static float _blockComHeightFraction = BlockComHeightFraction;

        /// Edge length of the block's square cross section for the current episode.
        public static float CurrentBlockWidth => _blockWidth;

        /// Height of the block for the current episode.
        public static float CurrentBlockHeight => _blockHeight;

        public static float CurrentBlockHalfHeight => _blockHeight * 0.5f;

        public static float CurrentBlockMass =>
            _blockWidth * _blockWidth * _blockHeight * BlockDensity;

        public static void RefreshBlockWidth()
        {
            SetBlockWidth(Academy.Instance.EnvironmentParameters.GetWithDefault(
                BlockWidthParameterName,
                BlockWidth));
        }

        public static void SetBlockWidth(float width)
        {
            _blockWidth = IsFinite(width)
                ? Mathf.Clamp(width, MinimumBlockWidth, MaximumBlockWidth)
                : BlockWidth;
        }

        public static void RefreshBlockHeight()
        {
            SetBlockHeight(Academy.Instance.EnvironmentParameters.GetWithDefault(
                BlockHeightParameterName,
                BlockHeight));
        }

        public static void SetBlockHeight(float height)
        {
            _blockHeight = IsFinite(height)
                ? Mathf.Clamp(height, MinimumBlockHeight, MaximumBlockHeight)
                : BlockHeight;
        }

        /// Height of the block's centre of mass as a fraction of its height, measured
        /// from the base. See BlockComHeightFraction.
        public static float CurrentBlockComHeightFraction => _blockComHeightFraction;

        /// Rigidbody.centerOfMass for the block. The block is a unit primitive cube
        /// scaled by (width, height, width), so its local space spans -0.5..0.5 and the
        /// offset is expressed in those unscaled units. This needs no block-height
        /// adjustment because Rigidbody.centerOfMass is in the cube's unscaled local
        /// space.
        public static Vector3 CurrentBlockCenterOfMassLocal =>
            new Vector3(0f, _blockComHeightFraction - 0.5f, 0f);

        public static void RefreshBlockCenterOfMass()
        {
            SetBlockComHeightFraction(Academy.Instance.EnvironmentParameters.GetWithDefault(
                BlockComHeightFractionParameterName,
                BlockComHeightFraction));
        }

        public static void SetBlockComHeightFraction(float fraction)
        {
            _blockComHeightFraction = IsFinite(fraction)
                ? Mathf.Clamp(
                    fraction,
                    MinimumBlockComHeightFraction,
                    MaximumBlockComHeightFraction)
                : BlockComHeightFraction;
        }
        // The approach target is not the block centre: for a top-down power grasp the
        // palm sits above the top face and the fingers cage the upper half, so aiming
        // the palm grasp-volume centre at the geometric centre would drive the palm
        // into the block. At the 0.12 m default, +4.0 cm puts it 2.0 cm below the
        // top face.
        public const float GraspTargetHeightOffset = 0.040f;
        // Preserve the same top-face inset as block height changes. Written as a
        // delta from the default so the default path returns the promoted constant
        // exactly.
        public static float CurrentGraspTargetHeightOffset =>
            GraspTargetHeightOffset + (CurrentBlockHeight - BlockHeight) * 0.5f;

        // --- approach shaping ---------------------------------------------------
        // Coarse term, calibrated to the whole workspace: it gets the hand into the
        // neighbourhood of the block.
        public const float ApproachPotentialMaximum = 1.0f;
        // Fine term. The coarse potential is scaled by MaximumObjectDistance (0.85 m
        // at measurement time, on UR5e; now 0.90 m for UR16e — the scaling argument
        // below is unaffected by that change), so closing the last 9 cm -> 1 cm —
        // precisely the range that decides whether a
        // grasp is geometrically possible — was worth only +0.09 and the gradient there
        // was essentially flat. Measured consequence: the policy parked 8.0 cm from the
        // grasp target (never closer than 5.9 cm) while the hand's grasp volume is only
        // ~4 cm across, so the block was never actually inside the hand and contacts
        // stalled at ~1.4 of the 3 required. This term puts a real gradient on the last
        // 12 cm.
        public const float FineApproachPotentialMaximum = 1.5f;
        public const float FineApproachDistance = 0.12f;
        // Keeping the palm pointing down is what makes a grasp reachable at all.
        // The transferred pre-grasp policy reached 25.3 deg, but the solved lift
        // policy drifted to 83-87 deg because this new-best potential was only 0.3
        // against the 1.5 fine-approach potential and stopped constraining posture
        // after being banked. Runtime tuning lets a sweep restore enough weight
        // without rebuilding the inference player.
        public const float TopDownAlignmentPotentialMax = 0.3f;
        public const float MinimumTopDownAlignmentPotentialMax = 0f;
        public const float MaximumTopDownAlignmentPotentialMax = 5f;
        public const string TopDownAlignmentPotentialMaxParameterName =
            "topdown_potential_max";
        public const float TopDownAlignmentRewardDistance = 0.20f;
        public const float MaximumTopDownAngleDegrees = 35f;
        public const float TopDownRewardEntryAngleDegrees = 70f;

        // --- grip shaping -------------------------------------------------------
        // Closing only pays inside this radius of the block centre.
        // Tightened from 0.10 m. The closing reward was being paid at 9 cm, where the
        // fingers cannot reach the block at all, so the policy closed its hand in mid
        // air, banked the full closing potential, and stopped approaching
        // (FinalClosure 0.37 with ContactCount 1.4). The hand's grasp volume is only
        // ~4 cm across, so closing only counts as progress inside that.
        public const float GraspReadyDistance = 0.045f;
        // Raised from 0.5: closing the hand is the single behaviour this stage has to
        // acquire, and it has to outweigh the risk of disturbing the block.
        public const float CloseNearObjectReward = 1.0f;
        // Closure at which the hand is maximally closed *usefully*. Measured with
        // GraspLiftHandGeometryProbe: thumb-to-finger separation bottoms out at
        // ~0.031-0.036 m around closure 0.75 and then WIDENS again to ~0.063 m at
        // closure 1.0 because the fingers curl past one another. Rewarding closure
        // linearly to 1.0 would therefore pay the policy to open its grip back up, so
        // the closing reward saturates here instead.
        public const float EffectiveGripClosure = 0.75f;
        // Closing the fist away from the object is actively wrong: it blocks the
        // approach and is the classic degenerate "grasp" the task must not reward.
        public const float CloseFarObjectPenalty = -0.25f;
        public const float MinimumGraspClosure = 0.30f;

        // --- contact / grasp confirmation ---------------------------------------
        public const float ContactPotentialMaximum = 0.4f;
        // Three contacts is the minimum that can cage a block; the Isaac reference
        // uses the same threshold.
        public const int GraspContactMinimum = 3;
        // Two contact directions at >= 90 deg means the fingers press from
        // genuinely different sides: a cheap force-closure proxy.
        public const float GraspOppositionAngleDeg = 90f;
        // The block centre has to sit inside the contact cage, not just brush it.
        // Tightened from 0.07: at 0.07 a hand merely resting its fingers on a block
        // that was still standing on the table satisfied the contract, which is how a
        // 57% GraspConfirmed rate coexisted with a 0.005 m mean lift height.
        public const float GraspCenterMaxDistance = 0.05f;
        // A grasp has to survive 0.3 s of physics before it counts, which rejects
        // single-frame collision flickers.
        public const float GraspConfirmSeconds = 0.30f;
        public const float GraspConfirmReward = 1.0f;

        // --- lift ---------------------------------------------------------------
        public const float LiftTargetHeight = 0.10f;
        // The dominant terminal shaping term: lifting is the goal of this stage.
        public const float LiftPotentialMaximum = 2.0f;
        public const float LiftHoldSeconds = 0.50f;
        // A block that is still flying upward (or being flicked) is not "held".
        public const float LiftMaximumSpeed = 0.50f;
        public const float LiftSuccessReward = 5.0f;
        // Physics contacts flicker during a re-grip; allow a short loss of contact
        // before declaring the object dropped.
        public const float SlipGraceSeconds = 0.20f;

        // --- penalties ----------------------------------------------------------
        public const float DropPenalty = -1.0f;
        // Softened from -1.0, and the distance widened from 0.15 m. Grasping requires
        // driving the fingers into contact, which always nudges the block a little; a
        // -1.0 terminal cliff at 15 cm made the expected value of ever closing the
        // hand negative (closing can earn at most +1.0), so the policy learned to
        // hover with an open hand and never grasp. The rule now only fires when the
        // block has genuinely been bulldozed across the panel.
        public const float PushAwayPenalty = -0.5f;
        public const float PushAwayDistance = 0.30f;
        public const float OutOfBoundsPenalty = -1.0f;
        // Knocking the block over used to be the most profitable thing the policy could
        // do: a block lying on the panel still satisfies the contact/opposition/cage
        // contract, so it banked the closing (+1.0), contact (+0.4) and grasp (+1.0)
        // rewards while the lift term stayed at zero forever. That is exactly the
        // ~1.75 plateau every run converged to. Ending the episode removes the local
        // optimum; the penalty stays small (a toppled block already forfeits the +5.0
        // success and the lift shaping) because a hard cliff next to the object is what
        // previously taught the policy to hover with an open hand instead of grasping.
        public const float TopplePenalty = -0.3f;
        // Only checked before the grasp is confirmed: once the hand owns the block it
        // is free to reorient it.
        public const float ToppleLimitDegrees = 45f;
        public const string ToppleLimitParameterName = "topple_limit_deg";
        // Real collision between a moving arm link and the panel: the only
        // hard-safety failure kept from the reach task.
        public const float UnsafeSurfacePenalty = -2.0f;
        // "Grasp 없이 팔만 상승": a closed but empty hand climbing away from the
        // table earns a steady drip of negative reward instead of a cliff, so it is
        // discouraged without destabilising the value function.
        public const float ClosedHandAscentPenalty = -0.004f;
        public const float ClosedHandAscentHeight = 0.15f;
        // Close to the block the arm must move gently or it will punt it away.
        public const float NearObjectControlClearance = 0.08f;
        public const float NearObjectActionPenaltyScale = -0.002f;
        public const float NearObjectArmDeltaScale = 0.35f;
        // Measured MeanArmActionRate is 0.40 over ~110 decisions. Because the helper
        // divides by six arm joints, the default costs only
        // -0.001 * (0.40 / 6) * 110 ~= -0.007 per episode (0.06% of return ~11).
        // The old -0.02 clamp still reached only about -0.15, so the wider runtime
        // range is required for a smoothness sweep to produce a meaningful signal.
        public const float ActionRatePenaltyScale = -0.001f;
        public const float MinimumActionRatePenaltyScale = -1f;
        public const float MaximumActionRatePenaltyScale = 0f;
        // Runtime tuning is needed to sweep smoothness against grasp success without
        // rebuilding the inference player.
        public const string ActionRatePenaltyScaleParameterName =
            "action_rate_penalty_scale";
        // Measured HandSurfaceContactSeconds is ~3.5 s, so the default costs only
        // -0.05/s * 3.5 s = -0.175, or about -0.18 per episode (1.6% of return ~11).
        // A sustained scrape should be sweepable into a material cost, while the
        // unchanged default keeps a brief brush negligible and non-terminal.
        public const float HandSurfacePenaltyPerSecond = -0.05f;
        public const float MinimumHandSurfacePenaltyPerSecond = -5f;
        public const float MaximumHandSurfacePenaltyPerSecond = 0f;
        // Runtime tuning is needed to balance scrape avoidance against reaching low
        // enough to grasp without rebuilding the inference player.
        public const string HandSurfacePenaltyPerSecondParameterName =
            "hand_surface_penalty_per_second";
        // Unlike the new-best top-down potential, this direct per-decision term keeps
        // constraining the wrist at the moment of grasp commitment. It defaults off
        // so an unparameterised run remains identical to the solved policy.
        public const float GraspPosturePenaltyScale = 0f;
        public const float MinimumGraspPosturePenaltyScale = -1f;
        public const float MaximumGraspPosturePenaltyScale = 0f;
        public const string GraspPosturePenaltyScaleParameterName =
            "grasp_posture_penalty_scale";

        static float _topDownAlignmentPotentialMax = TopDownAlignmentPotentialMax;
        static float _actionRatePenaltyScale = ActionRatePenaltyScale;
        static float _handSurfacePenaltyPerSecond = HandSurfacePenaltyPerSecond;
        static float _graspPosturePenaltyScale = GraspPosturePenaltyScale;

        /// Top-down alignment potential maximum for the current episode.
        public static float CurrentTopDownAlignmentPotentialMax =>
            _topDownAlignmentPotentialMax;

        public static void RefreshTopDownAlignmentPotentialMax()
        {
            SetTopDownAlignmentPotentialMax(
                Academy.Instance.EnvironmentParameters.GetWithDefault(
                    TopDownAlignmentPotentialMaxParameterName,
                    TopDownAlignmentPotentialMax));
        }

        public static void SetTopDownAlignmentPotentialMax(float maximum)
        {
            _topDownAlignmentPotentialMax = IsFinite(maximum)
                ? Mathf.Clamp(
                    maximum,
                    MinimumTopDownAlignmentPotentialMax,
                    MaximumTopDownAlignmentPotentialMax)
                : TopDownAlignmentPotentialMax;
        }

        /// Action-rate weight for the current episode.
        public static float CurrentActionRatePenaltyScale => _actionRatePenaltyScale;

        public static void RefreshActionRatePenaltyScale()
        {
            SetActionRatePenaltyScale(Academy.Instance.EnvironmentParameters.GetWithDefault(
                ActionRatePenaltyScaleParameterName,
                ActionRatePenaltyScale));
        }

        public static void SetActionRatePenaltyScale(float scale)
        {
            _actionRatePenaltyScale = IsFinite(scale)
                ? Mathf.Clamp(
                    scale,
                    MinimumActionRatePenaltyScale,
                    MaximumActionRatePenaltyScale)
                : ActionRatePenaltyScale;
        }

        /// Hand-panel contact weight for the current episode, expressed per second.
        public static float CurrentHandSurfacePenaltyPerSecond =>
            _handSurfacePenaltyPerSecond;

        public static void RefreshHandSurfacePenaltyPerSecond()
        {
            SetHandSurfacePenaltyPerSecond(
                Academy.Instance.EnvironmentParameters.GetWithDefault(
                    HandSurfacePenaltyPerSecondParameterName,
                    HandSurfacePenaltyPerSecond));
        }

        public static void SetHandSurfacePenaltyPerSecond(float scale)
        {
            _handSurfacePenaltyPerSecond = IsFinite(scale)
                ? Mathf.Clamp(
                    scale,
                    MinimumHandSurfacePenaltyPerSecond,
                    MaximumHandSurfacePenaltyPerSecond)
                : HandSurfacePenaltyPerSecond;
        }

        /// Direct grasp-posture weight for the current episode.
        public static float CurrentGraspPosturePenaltyScale =>
            _graspPosturePenaltyScale;

        public static void RefreshGraspPosturePenaltyScale()
        {
            SetGraspPosturePenaltyScale(
                Academy.Instance.EnvironmentParameters.GetWithDefault(
                    GraspPosturePenaltyScaleParameterName,
                    GraspPosturePenaltyScale));
        }

        public static void SetGraspPosturePenaltyScale(float scale)
        {
            _graspPosturePenaltyScale = IsFinite(scale)
                ? Mathf.Clamp(
                    scale,
                    MinimumGraspPosturePenaltyScale,
                    MaximumGraspPosturePenaltyScale)
                : GraspPosturePenaltyScale;
        }

        // Palm-local centre of the full-hand grasp volume (same anchor the reach
        // policy was trained against).
        public static readonly Vector3 FullHandGraspPointLocalPosition =
            new Vector3(0f, 0.05f, 0.04f);

        public static readonly string[] ArmLinks =
        {
            "shoulder_link", "upper_arm_link", "forearm_link",
            "wrist_1_link", "wrist_2_link", "wrist_3_link"
        };

        // Kept as-is for UR16e (2026-08-25): unlike MaximumObjectDistance/
        // SpawnRadius above, these bounds are not a simple function of reach —
        // they were hand-tuned against UR5e's link geometry to keep the arm out
        // of implausible/self-colliding configurations, and the raw URDF joint
        // limits are +-360 deg on every UR e-series model regardless of variant
        // (checked ur16e_dg5f_right.urdf), so there is no hardware-limit change
        // to fold in here.
        //
        // Forward-kinematics sweep against the verified ur16e_dg5f_right.sim.mjcf.xml
        // (all 64 corners of this envelope) found one corner
        // (shoulder_lift=-20 deg, elbow=140 deg) where the hand dips to
        // z ~= -0.20 m, i.e. below the panel top (z=0) — the "arm raised near
        // horizontal + elbow sharply bent" configuration folds the wrist/hand
        // down past the base mount plane. No same-methodology UR5e baseline model
        // exists to check whether this is a UR16e regression or a pre-existing
        // gap the training run simply never explored, so the bounds were left
        // unchanged rather than guessed at. Revisit with an actual training run
        // or a same-check on a UR5e sim model before tightening shoulder_lift/
        // elbow further.
        public static readonly float[] ArmSafeMinDeg =
        {
            -180f, -120f, 20f, -180f, -150f, -180f
        };

        public static readonly float[] ArmSafeMaxDeg =
        {
            180f, -20f, 140f, 0f, -30f, 180f
        };

        // Validated DG5F closed-hand pose, mirrored for the left-hand URDF.
        // Channel order: finger 1..5, joint 1..4.
        public static readonly float[] LeftFistDeg =
        {
            -40f, 80f, -60f, -60f,
              0f, 100f, 80f, 70f,
              0f, 100f, 80f, 70f,
              0f, 95f, 80f, 70f,
              0f, 0f, 80f, 70f
        };

        // --- curriculum ---------------------------------------------------------
        public const string GraspStageParameterName = "grasp_stage";
        public const int FirstGraspStage = 1;
        public const int FinalGraspStage = 3;

        static int _graspStage = FirstGraspStage;

        public static int CurrentGraspStage => _graspStage;

        public static void RefreshGraspStage()
        {
            SetGraspStage(Academy.Instance.EnvironmentParameters.GetWithDefault(
                GraspStageParameterName,
                FinalGraspStage));
        }

        public static void SetGraspStage(float stage)
        {
            _graspStage = IsFinite(stage)
                ? Mathf.Clamp(Mathf.RoundToInt(stage), FirstGraspStage, FinalGraspStage)
                : FirstGraspStage;
        }

        // Stage 1 keeps the block inside the sweet spot the reach policy already
        // solves and only asks for a 5 cm lift; later stages widen the workspace
        // and raise the bar toward the real contract.
        public static float CurrentMinimumSpawnRadius
        {
            get
            {
                switch (_graspStage)
                {
                    case 1: return 0.40f;
                    case 2: return 0.38f;
                    default: return MinimumSpawnRadius;
                }
            }
        }

        public static float CurrentMaximumSpawnRadius
        {
            get
            {
                switch (_graspStage)
                {
                    case 1: return 0.50f;
                    case 2: return 0.52f;
                    default: return MaximumSpawnRadius;
                }
            }
        }

        public static float CurrentLiftTargetHeight
        {
            get
            {
                switch (_graspStage)
                {
                    case 1: return 0.05f;
                    case 2: return 0.08f;
                    default: return LiftTargetHeight;
                }
            }
        }

        public static float CurrentLiftHoldSeconds
        {
            get
            {
                switch (_graspStage)
                {
                    case 1: return 0.25f;
                    case 2: return 0.35f;
                    default: return LiftHoldSeconds;
                }
            }
        }

        public static float GraspStageNormalized()
        {
            return (_graspStage - FirstGraspStage)
                / (float)(FinalGraspStage - FirstGraspStage);
        }

        // --- shared math --------------------------------------------------------

        public static float NormalizeJoint(float valueDeg, float lowerDeg, float upperDeg)
        {
            if (upperDeg <= lowerDeg) return 0f;
            return Mathf.Clamp((valueDeg - lowerDeg) / (upperDeg - lowerDeg) * 2f - 1f, -1f, 1f);
        }

        public static float PotentialDelta(float previousPotential, float currentPotential)
        {
            if (!IsFinite(previousPotential) || !IsFinite(currentPotential)) return 0f;
            return currentPotential - previousPotential;
        }

        public static float NewBestPotentialDelta(
            float previousBestPotential,
            float currentPotential)
        {
            if (!IsFinite(previousBestPotential) || !IsFinite(currentPotential))
                return 0f;
            return Mathf.Max(0f, currentPotential - previousBestPotential);
        }

        /// Distance-to-object potential. Potential-based shaping keeps the optimal
        /// policy unchanged while making the approach learnable.
        public static float ApproachPotential(float distance)
        {
            if (!IsFinite(distance)) return 0f;
            return ApproachPotentialMaximum
                * (1f - Mathf.Clamp01(Mathf.Max(0f, distance) / MaximumObjectDistance));
        }

        public static float PalmFacingAlignment(Vector3 palmForward, Vector3 palmToObject)
        {
            if (!IsFinite(palmForward)
                || !IsFinite(palmToObject)
                || palmForward.sqrMagnitude <= 1e-12f
                || palmToObject.sqrMagnitude <= 1e-12f)
            {
                return -1f;
            }

            return Mathf.Clamp(
                Vector3.Dot(palmForward.normalized, palmToObject.normalized),
                -1f,
                1f);
        }

        public static bool IsPalmFacingObject(float palmFacingAlignment)
        {
            // Only a positive dot product puts the object in the palm half-space,
            // i.e. somewhere the fingers can actually close around it.
            return IsFinite(palmFacingAlignment) && palmFacingAlignment > 0f;
        }

        /// Fine-resolution approach potential over the last FineApproachDistance.
        /// See the constant for why the coarse term alone is not enough.
        public static float FineApproachPotential(float distance)
        {
            if (!IsFinite(distance)) return 0f;
            return FineApproachPotentialMaximum
                * (1f - Mathf.Clamp01(Mathf.Max(0f, distance) / FineApproachDistance));
        }

        public static float DirectionalApproachPotential(
            float distance,
            float palmFacingAlignment)
        {
            return IsPalmFacingObject(palmFacingAlignment)
                ? ApproachPotential(distance) + FineApproachPotential(distance)
                : 0f;
        }

        public static float TopDownAlignment(Vector3 graspForward, Vector3 robotUp)
        {
            if (!IsFinite(graspForward)
                || !IsFinite(robotUp)
                || graspForward.sqrMagnitude <= 1e-12f
                || robotUp.sqrMagnitude <= 1e-12f)
            {
                return -1f;
            }

            return Mathf.Clamp(
                Vector3.Dot(graspForward.normalized, -robotUp.normalized),
                -1f,
                1f);
        }

        public static float TopDownAngleDegrees(float topDownAlignment)
        {
            if (!IsFinite(topDownAlignment)) return 180f;
            return Mathf.Acos(Mathf.Clamp(topDownAlignment, -1f, 1f)) * Mathf.Rad2Deg;
        }

        public static bool IsTopDownAligned(float topDownAlignment)
        {
            if (!IsFinite(topDownAlignment)) return false;
            float minimumAlignment = Mathf.Cos(MaximumTopDownAngleDegrees * Mathf.Deg2Rad);
            return topDownAlignment >= minimumAlignment - 1e-6f;
        }

        /// Rewards a top-down wrist pose, but only once the hand is close to and
        /// above the block — orientation far away from the object is meaningless.
        public static float TopDownAlignmentPotential(
            float distance,
            float heightAboveObject,
            float topDownAlignment)
        {
            if (!IsFinite(distance)
                || !IsFinite(heightAboveObject)
                || !IsFinite(topDownAlignment)
                || distance > TopDownAlignmentRewardDistance + 1e-6f
                || heightAboveObject < -1e-6f)
            {
                return 0f;
            }

            float progress = Mathf.Clamp01(
                (TopDownRewardEntryAngleDegrees - TopDownAngleDegrees(topDownAlignment))
                / (TopDownRewardEntryAngleDegrees - MaximumTopDownAngleDegrees));
            return _topDownAlignmentPotentialMax * progress * progress;
        }

        /// Per-decision cost for committing to a grasp with a wrist angle beyond the
        /// acceptable top-down cone. Approach motion remains free outside the grasp
        /// volume, and wrist motion is free again after grasp confirmation.
        public static float GraspPosturePenalty(
            float angleDegrees,
            float graspDistance,
            bool graspConfirmed)
        {
            if (graspConfirmed
                || !IsFinite(angleDegrees)
                || !IsFinite(graspDistance)
                || graspDistance > GraspReadyDistance + 1e-6f)
            {
                return 0f;
            }

            float progress = Mathf.Clamp01(
                (angleDegrees - MaximumTopDownAngleDegrees)
                / (90f - MaximumTopDownAngleDegrees));
            return _graspPosturePenaltyScale * progress;
        }

        /// Potential paid for having the fingers closed while next to the object.
        /// Consumed as a NEW-BEST delta by the agent, which caps the total closing
        /// credit at CloseNearObjectReward per episode.
        ///
        /// This must not be a plain per-step delta: opening the hand has to stay free
        /// (the policy needs to retry a failed grasp without paying twice), and a
        /// free-to-undo, paid-to-redo action is an unbounded reward pump — pumping the
        /// fingers open/closed while hovering over the block would out-earn actually
        /// grasping it.
        public static float ClosurePotential(float closure, bool readyToGrasp)
        {
            if (!readyToGrasp || !IsFinite(closure)) return 0f;
            // Saturates at EffectiveGripClosure: squeezing past it re-opens the grip
            // (see that constant), so there is nothing to pay for beyond it.
            return CloseNearObjectReward
                * Mathf.Clamp01(Mathf.Max(0f, closure) / EffectiveGripClosure);
        }

        /// Immediate cost for closing the fingers away from the object: the classic
        /// degenerate "grasp" the task must not reward. A penalty cannot be farmed by
        /// cycling, so unlike the reward above this one is a plain per-step delta.
        /// Opening is always free.
        public static float ClosureFarPenalty(float closureDelta, bool readyToGrasp)
        {
            if (readyToGrasp || !IsFinite(closureDelta)) return 0f;
            return Mathf.Max(0f, closureDelta) * CloseFarObjectPenalty;
        }

        /// Dense credit for getting fingers onto the block before the full grasp
        /// contract is satisfied.
        public static float ContactPotential(int contactCount)
        {
            if (contactCount <= 0) return 0f;
            return ContactPotentialMaximum
                * Mathf.Clamp01(contactCount / (float)GraspContactMinimum);
        }

        /// Largest pairwise angle (deg) between contact directions measured from the
        /// object centre. Directions must be packed into [0, contactCount).
        public static float MaximumOppositionAngleDegrees(
            Vector3[] contactDirections,
            int contactCount)
        {
            if (contactDirections == null) return 0f;
            int count = Mathf.Min(contactCount, contactDirections.Length);
            if (count < 2) return 0f;

            float maximumAngle = 0f;
            for (int i = 0; i < count; i++)
            {
                Vector3 first = contactDirections[i];
                if (!IsFinite(first) || first.sqrMagnitude <= 1e-12f) continue;
                Vector3 firstNormalized = first.normalized;
                for (int j = i + 1; j < count; j++)
                {
                    Vector3 second = contactDirections[j];
                    if (!IsFinite(second) || second.sqrMagnitude <= 1e-12f) continue;
                    float cosine = Mathf.Clamp(
                        Vector3.Dot(firstNormalized, second.normalized), -1f, 1f);
                    float angle = Mathf.Acos(cosine) * Mathf.Rad2Deg;
                    if (angle > maximumAngle) maximumAngle = angle;
                }
            }
            return maximumAngle;
        }

        /// Force-closure proxy: enough contacts, spread to opposite sides of the
        /// block. Without this test a hand that merely pokes the block from one
        /// side with three fingertips would register as a grasp.
        public static bool IsForceClosureLike(Vector3[] contactDirections, int contactCount)
        {
            return contactCount >= GraspContactMinimum
                && MaximumOppositionAngleDegrees(contactDirections, contactCount)
                    >= GraspOppositionAngleDeg - 1e-4f;
        }

        /// The block centre must sit inside the cage formed by the contacts, not
        /// just near one edge of it.
        public static bool IsGraspGeometryValid(Vector3 objectCenter, Vector3 contactCentroid)
        {
            if (!IsFinite(objectCenter) || !IsFinite(contactCentroid)) return false;
            return Vector3.Distance(objectCenter, contactCentroid)
                <= GraspCenterMaxDistance + 1e-6f;
        }

        public static bool IsGraspCandidate(
            int contactCount,
            Vector3[] contactDirections,
            Vector3 objectCenter,
            Vector3 contactCentroid,
            float closure)
        {
            return contactCount >= GraspContactMinimum
                && IsForceClosureLike(contactDirections, contactCount)
                && IsGraspGeometryValid(objectCenter, contactCentroid)
                && IsFinite(closure)
                && closure >= MinimumGraspClosure - 1e-6f;
        }

        public static float GraspProgress(float graspSeconds)
        {
            if (!IsFinite(graspSeconds)) return 0f;
            return Mathf.Clamp01(Mathf.Max(0f, graspSeconds) / GraspConfirmSeconds);
        }

        public static bool IsGraspConfirmed(float graspSeconds)
        {
            return IsFinite(graspSeconds) && graspSeconds >= GraspConfirmSeconds - 1e-5f;
        }

        public static float LiftHeight(float objectY, float spawnY)
        {
            if (!IsFinite(objectY) || !IsFinite(spawnY)) return 0f;
            return objectY - spawnY;
        }

        public static float LiftProgress(float liftHeight)
        {
            if (!IsFinite(liftHeight)) return 0f;
            return Mathf.Clamp01(Mathf.Max(0f, liftHeight) / CurrentLiftTargetHeight);
        }

        /// Not a new-best potential: the agent has to keep the block up. Letting it
        /// sink refunds the shaping, which is exactly the gradient a drop deserves.
        public static float LiftPotential(float liftHeight)
        {
            return LiftPotentialMaximum * LiftProgress(liftHeight);
        }

        public static bool IsLiftHeightReached(float liftHeight)
        {
            return IsFinite(liftHeight) && liftHeight >= CurrentLiftTargetHeight - 1e-5f;
        }

        public static bool IsStableLift(float liftHeight, float objectSpeed)
        {
            return IsLiftHeightReached(liftHeight)
                && IsFinite(objectSpeed)
                && objectSpeed <= LiftMaximumSpeed;
        }

        public static bool IsLiftComplete(float liftHoldSeconds)
        {
            return IsFinite(liftHoldSeconds)
                && liftHoldSeconds >= CurrentLiftHoldSeconds - 1e-5f;
        }

        public static bool IsClosedHandAscent(
            float graspPointHeightAbovePanel,
            float closure,
            bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            if (!IsFinite(graspPointHeightAbovePanel) || !IsFinite(closure)) return false;
            return closure >= MinimumGraspClosure
                && graspPointHeightAbovePanel > ClosedHandAscentHeight;
        }

        public static float PlanarDistance(Vector3 first, Vector3 second)
        {
            if (!IsFinite(first) || !IsFinite(second))
                return float.PositiveInfinity;
            return new Vector2(first.x - second.x, first.z - second.z).magnitude;
        }

        public static bool IsPushedAway(
            Vector3 objectLocalPosition,
            Vector3 spawnLocalPosition,
            bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            return PlanarDistance(objectLocalPosition, spawnLocalPosition) > PushAwayDistance;
        }

        static float _toppleLimitDeg = ToppleLimitDegrees;

        /// Tilt limit for the current episode. Settable to 180 via the
        /// `topple_limit_deg` environment parameter to disable the rule, which is how
        /// the diagnostic run measured tilt without changing the task.
        public static float CurrentToppleLimitDegrees => _toppleLimitDeg;

        public static void RefreshToppleLimit()
        {
            SetToppleLimit(Academy.Instance.EnvironmentParameters.GetWithDefault(
                ToppleLimitParameterName,
                ToppleLimitDegrees));
        }

        public static void SetToppleLimit(float degrees)
        {
            _toppleLimitDeg = IsFinite(degrees)
                ? Mathf.Clamp(degrees, 5f, 180f)
                : ToppleLimitDegrees;
        }

        /// Angle between the block's own up axis and the robot vertical. 0 deg is
        /// upright, 90 deg is lying on its side.
        public static float ObjectTiltDegrees(Vector3 objectUp, Vector3 robotUp)
        {
            if (!IsFinite(objectUp)
                || !IsFinite(robotUp)
                || objectUp.sqrMagnitude <= 1e-12f
                || robotUp.sqrMagnitude <= 1e-12f)
            {
                return 0f;
            }

            float cosine = Mathf.Clamp(
                Vector3.Dot(objectUp.normalized, robotUp.normalized), -1f, 1f);
            return Mathf.Acos(cosine) * Mathf.Rad2Deg;
        }

        public static bool IsToppled(float tiltDegrees, bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            return IsFinite(tiltDegrees)
                && tiltDegrees >= _toppleLimitDeg - 1e-4f;
        }

        public static bool IsOutOfBounds(
            Vector3 objectLocalPosition,
            float panelTopHeight,
            float blockHalfHeight)
        {
            if (!IsFinite(objectLocalPosition)) return true;
            if (objectLocalPosition.magnitude > MaximumObjectDistance) return true;
            // The block centre can never drop below the panel top minus half its own
            // height unless it fell off the panel.
            return objectLocalPosition.y < panelTopHeight - Mathf.Max(0f, blockHalfHeight);
        }

        // --- spawn --------------------------------------------------------------

        public static float AreaUniformRadius(float unitSample)
        {
            float minimum = CurrentMinimumSpawnRadius;
            float maximum = CurrentMaximumSpawnRadius;
            return Mathf.Sqrt(Mathf.Lerp(
                minimum * minimum,
                maximum * maximum,
                Mathf.Clamp01(unitSample)));
        }

        public static float SpawnAzimuthRadians(
            float distributionUnitSample,
            float azimuthUnitSample)
        {
            float distribution = Mathf.Clamp01(distributionUnitSample);
            float azimuth = Mathf.Clamp01(azimuthUnitSample);
            if (distribution < 0.5f)
                return azimuth * 2f * Mathf.PI;

            // Robot-local +Z is forward and +X is right. Half the samples stay
            // globally uniform; the other half concentrates on the forward and
            // right sectors the arm reaches most comfortably.
            float sectorCenter = distribution < 0.75f ? 0.5f * Mathf.PI : 0f;
            return sectorCenter + (azimuth - 0.5f) * 0.5f * Mathf.PI;
        }

        public static Vector3 SpawnBlockLocalPosition(
            float radiusUnitSample,
            float distributionUnitSample,
            float azimuthUnitSample,
            float blockHeight)
        {
            float horizontalRadius = AreaUniformRadius(radiusUnitSample);
            float azimuth = SpawnAzimuthRadians(distributionUnitSample, azimuthUnitSample);
            return new Vector3(
                Mathf.Cos(azimuth) * horizontalRadius,
                SupportTopHeight + Mathf.Max(0f, blockHeight) * 0.5f,
                Mathf.Sin(azimuth) * horizontalRadius);
        }

        public static bool IsValidSpawn(
            Vector3 localPosition,
            float blockWidth,
            float blockHeight)
        {
            if (!IsFinite(localPosition)) return false;
            float horizontalRadius =
                new Vector2(localPosition.x, localPosition.z).magnitude;
            float halfWidth = Mathf.Max(0f, blockWidth) * 0.5f;
            float restingHeight = localPosition.y - Mathf.Max(0f, blockHeight) * 0.5f;
            return horizontalRadius >= CurrentMinimumSpawnRadius - 1e-6f
                && horizontalRadius <= CurrentMaximumSpawnRadius + 1e-6f
                && Mathf.Abs(localPosition.x) + halfWidth <= PanelWidth * 0.5f
                && Mathf.Abs(localPosition.z) + halfWidth <= PanelDepth * 0.5f
                && Mathf.Abs(restingHeight - SupportTopHeight) <= 1e-5f
                && localPosition.magnitude <= MaximumObjectDistance;
        }

        // --- termination --------------------------------------------------------

        public static bool ReachedEpisodeTimeout(float elapsedSeconds)
        {
            return IsFinite(elapsedSeconds)
                && elapsedSeconds >= EpisodeTimeoutSeconds - 1e-5f;
        }

        public static bool UsesNearObjectControl(float distance)
        {
            return IsFinite(distance) && distance <= NearObjectControlClearance + 1e-6f;
        }

        public static float NearObjectActionPenalty(float sumSquaredArmActions)
        {
            if (!IsFinite(sumSquaredArmActions)) return 0f;
            return NearObjectActionPenaltyScale
                * Mathf.Max(0f, sumSquaredArmActions)
                / ArmJointCount;
        }

        public static float ArmActionRatePenalty(float sumSquaredArmActionDeltas)
        {
            if (!IsFinite(sumSquaredArmActionDeltas)) return 0f;
            return _actionRatePenaltyScale
                * Mathf.Max(0f, sumSquaredArmActionDeltas)
                / ArmJointCount;
        }

        public static float HandSurfaceContactPenalty(
            float contactSeconds,
            bool graspConfirmed)
        {
            if (graspConfirmed || !IsFinite(contactSeconds) || contactSeconds <= 0f)
                return 0f;
            return _handSurfacePenaltyPerSecond * contactSeconds;
        }

        /// Terminal penalties. Timeout and NonFinitePhysics add nothing: the shaping
        /// already reflects how far the attempt got, and an extra cliff there makes
        /// the value function pessimistic about ever trying.
        public static float FailurePenalty(string reason)
        {
            if (string.Equals(reason, "UnsafeSurfaceContact", StringComparison.Ordinal))
                return UnsafeSurfacePenalty;
            if (string.Equals(reason, "Dropped", StringComparison.Ordinal))
                return DropPenalty;
            if (string.Equals(reason, "ObjectPushedAway", StringComparison.Ordinal))
                return PushAwayPenalty;
            if (string.Equals(reason, "ObjectOutOfBounds", StringComparison.Ordinal))
                return OutOfBoundsPenalty;
            if (string.Equals(reason, "ObjectToppled", StringComparison.Ordinal))
                return TopplePenalty;
            return 0f;
        }

        public static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        public static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }
    }
}
