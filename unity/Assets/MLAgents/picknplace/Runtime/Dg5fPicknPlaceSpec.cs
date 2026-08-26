using System;
using Unity.MLAgents;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Policy shape and task contract for DG5F pick-AND-place on a UR16e: grasp a
    /// cube spawned at a random floor position, carry it over to a fixed
    /// FOUP-shaped landing platform, and set it down on a randomly chosen point on
    /// the platform's top face.
    ///
    /// Design notes (see docs/DG5F_PICKNPLACE.md):
    /// * The approach/grasp half of this task (slots 0-48 of the observation,
    ///   the approach/top-down/grip/contact math below) is a near-verbatim port of
    ///   KDT.GraspLiftTraining.Dg5fGraspLiftSpec, now grasping a cube identical in
    ///   geometry to GraspLift's block (see Cube* constants) instead of a FOUP
    ///   handle. That half is proven through real training runs; only the
    ///   transport+place half below is new.
    /// * The FOUP-shaped object from this behavior's first iteration is now the
    ///   PLACE target: a fixed, static (no Rigidbody) landing platform. It is
    ///   never grasped, so it needs no mass/COM/curriculum — just a footprint the
    ///   spawn logic must avoid and a top face the marker randomizes over.
    /// * Placement uses the same continuous grip-closure action as before — there
    ///   is no separate "release" action. Success requires the policy to actually
    ///   open its hand while the cube rests at the target, not just hold it there.
    /// </summary>
    public static class Dg5fPicknPlaceSpec
    {
        public const string SpecVersion = "2.0.0";
        public const string BehaviorName = "DG5FPicknPlace";
        // See the CollectObservations slot map in Dg5fPicknPlaceAgent.cs — this
        // must match the number of AddObservation calls exactly or ML-Agents
        // throws a shape-mismatch error at runtime.
        public const int ObservationSize = 63;
        public const int ActionSize = 7;
        public const int ArmJointCount = 6;
        public const int HandJointCount = 20;
        public const int FingerCount = 5;
        public const int ContactPointCount = FingerCount + 1;
        public const int PalmContactIndex = FingerCount;

        // --- episode ------------------------------------------------------------
        // Longer than GraspLift's 20 s / pick-only PicknPlace's 25 s: this task
        // adds a transport-then-place phase after the grasp.
        public const float EpisodeTimeoutSeconds = 35f;
        public const float DecisionTimePenalty = -0.001f;

        // --- workspace ------------------------------------------------------------
        public const float PanelWidth = 1.80f;
        public const float PanelDepth = 1.80f;
        public const float PanelThickness = 0.25f;
        public const float SupportTopHeight = 0f;
        public const float MaximumObjectDistance = 0.90f;

        // --- cube geometry (the picked object) -------------------------------------
        // Identical to Dg5fGraspLiftSpec's Block* defaults — this is the exact
        // geometry GraspLiftHandGeometryProbe validated the closed-fist aperture
        // against (3.1-3.6 cm opposition), so the proven grasp contract transfers
        // unchanged.
        public const float CubeWidth = 0.035f;
        public const float CubeHeight = 0.12f;
        public const float MinimumCubeWidth = 0.025f;
        public const float MaximumCubeWidth = 0.060f;
        public const float MinimumCubeHeight = 0.06f;
        public const float MaximumCubeHeight = 0.15f;
        public const float CubeDensity = 1800f;
        public const float CubeComHeightFraction = 0.20f;
        public const float MinimumCubeComHeightFraction = 0.05f;
        public const float MaximumCubeComHeightFraction = 0.50f;
        public const string CubeWidthParameterName = "cube_width";
        public const string CubeHeightParameterName = "cube_height";
        public const string CubeComHeightFractionParameterName = "cube_com_height_fraction";

        static float _cubeWidth = CubeWidth;
        static float _cubeHeight = CubeHeight;
        static float _cubeComHeightFraction = CubeComHeightFraction;

        public static float CurrentCubeWidth => _cubeWidth;
        public static float CurrentCubeHeight => _cubeHeight;
        public static float CurrentCubeHalfHeight => _cubeHeight * 0.5f;
        public static float CurrentCubeMass => _cubeWidth * _cubeWidth * _cubeHeight * CubeDensity;
        public static float CurrentCubeComHeightFraction => _cubeComHeightFraction;

        /// Rigidbody.centerOfMass for the cube. It is a unit primitive cube scaled
        /// by (width, height, width), so its local space spans -0.5..0.5.
        public static Vector3 CurrentCubeCenterOfMassLocal =>
            new Vector3(0f, _cubeComHeightFraction - 0.5f, 0f);

        public static void RefreshCubeWidth()
        {
            SetCubeWidth(Academy.Instance.EnvironmentParameters.GetWithDefault(
                CubeWidthParameterName, CubeWidth));
        }

        public static void SetCubeWidth(float width)
        {
            _cubeWidth = IsFinite(width)
                ? Mathf.Clamp(width, MinimumCubeWidth, MaximumCubeWidth)
                : CubeWidth;
        }

        public static void RefreshCubeHeight()
        {
            SetCubeHeight(Academy.Instance.EnvironmentParameters.GetWithDefault(
                CubeHeightParameterName, CubeHeight));
        }

        public static void SetCubeHeight(float height)
        {
            _cubeHeight = IsFinite(height)
                ? Mathf.Clamp(height, MinimumCubeHeight, MaximumCubeHeight)
                : CubeHeight;
        }

        public static void RefreshCubeComHeightFraction()
        {
            SetCubeComHeightFraction(Academy.Instance.EnvironmentParameters.GetWithDefault(
                CubeComHeightFractionParameterName, CubeComHeightFraction));
        }

        public static void SetCubeComHeightFraction(float fraction)
        {
            _cubeComHeightFraction = IsFinite(fraction)
                ? Mathf.Clamp(fraction, MinimumCubeComHeightFraction, MaximumCubeComHeightFraction)
                : CubeComHeightFraction;
        }

        // The approach target is not the cube centre: for a top-down power grasp
        // the palm sits above the top face. Identical rationale to GraspLift's
        // GraspTargetHeightOffset.
        public const float GraspTargetHeightOffset = 0.040f;
        public static float CurrentGraspTargetHeightOffset =>
            GraspTargetHeightOffset + (CurrentCubeHeight - CubeHeight) * 0.5f;

        // --- platform geometry (the fixed, static place target) --------------------
        // Still FOUP-shaped (box body + carry handle) so the visual target reads
        // as "a FOUP", per the original brief — it is just no longer the grasped
        // object. Placeholder dimensions pending the real spec (see
        // docs/DG5F_PICKNPLACE.md).
        public const float PlatformWidth = 0.30f;
        public const float PlatformDepth = 0.30f;
        public const float PlatformHeight = 0.25f;
        public const float PlatformHalfHeight = PlatformHeight * 0.5f;
        // Purely decorative now (no grasp contract depends on it): a horizontal
        // bar on top so the platform still reads as a FOUP silhouette.
        public const float PlatformHandleDiameter = 0.035f;
        public const float PlatformHandleLength = 0.13f;
        public const float PlatformHandleClearanceAboveBody = 0.045f;

        // Fixed position within each training area, robot-base local. Radius 0.60 m
        // sits well inside the 0.90 m reach with margin for the platform's own
        // footprint. The cube spawn annulus (below) and this position are chosen so
        // neither footprint needs the other's exclusion check to be very tight.
        public static readonly Vector3 PlatformLocalPosition =
            new Vector3(0.60f, SupportTopHeight + PlatformHalfHeight, 0f);

        /// Height (robot-base local Y, i.e. above the panel top) of the platform's
        /// top face — where a placed cube's base should rest.
        public const float PlatformTopHeight = SupportTopHeight + PlatformHeight;

        /// Cube spawns must clear this horizontal radius from the platform centre
        /// (footprint half-diagonal ~0.21 m + cube half-width + margin).
        public const float PlatformExclusionRadius = 0.30f;

        // --- place marker (randomized per episode) ----------------------------------
        // Inset from the platform edges by enough that a cube centred on the
        // marker never hangs off the platform.
        public const float MarkerEdgeMargin = 0.05f;
        public const float MarkerRangeMeters = PlatformWidth * 0.5f - MarkerEdgeMargin;
        // Curriculum-narrowed placement precision (see place_stage below).
        public const float MinimumMarkerRangeMeters = 0.02f;

        public const string PlaceStageParameterName = "place_stage";
        public const int FirstPlaceStage = 1;
        public const int FinalPlaceStage = 3;

        static int _placeStage = FirstPlaceStage;

        public static int CurrentPlaceStage => _placeStage;

        public static void RefreshPlaceStage()
        {
            SetPlaceStage(Academy.Instance.EnvironmentParameters.GetWithDefault(
                PlaceStageParameterName, FinalPlaceStage));
        }

        public static void SetPlaceStage(float stage)
        {
            _placeStage = IsFinite(stage)
                ? Mathf.Clamp(Mathf.RoundToInt(stage), FirstPlaceStage, FinalPlaceStage)
                : FirstPlaceStage;
        }

        /// How far from the platform centre the marker may land this episode.
        /// Stage 1 keeps it near the centre (easy, generous placement tolerance
        /// effectively); later stages widen toward the full inset range.
        public static float CurrentMarkerRangeMeters
        {
            get
            {
                switch (_placeStage)
                {
                    case 1: return Mathf.Min(0.03f, MarkerRangeMeters);
                    case 2: return Mathf.Min(0.07f, MarkerRangeMeters);
                    default: return MarkerRangeMeters;
                }
            }
        }

        /// Position tolerance for a successful placement. Widened in early stages
        /// so the precision requirement ramps up alongside the marker range.
        public static float CurrentPlacePositionToleranceMeters
        {
            get
            {
                switch (_placeStage)
                {
                    case 1: return 0.06f;
                    case 2: return 0.045f;
                    default: return PlacePositionToleranceMeters;
                }
            }
        }

        public static Vector3 MarkerLocalOffset(float unitX, float unitZ)
        {
            float range = CurrentMarkerRangeMeters;
            return new Vector3(
                Mathf.Lerp(-range, range, Mathf.Clamp01(unitX)),
                0f,
                Mathf.Lerp(-range, range, Mathf.Clamp01(unitZ)));
        }

        // --- cube spawn (pick side) -------------------------------------------------
        // Identical annulus to Dg5fGraspLiftSpec's proven 0.35..0.55 m-class
        // range, expressed for the confirmed UR16e 0.90 m reach the same way
        // GraspLift derived it (see that file's MinimumSpawnRadius comment).
        public const float MinimumSpawnRadius = 0.37f;
        public const float MaximumSpawnRadius = 0.58f;

        public const string PickStageParameterName = "pick_stage";
        public const int FirstPickStage = 1;
        public const int FinalPickStage = 3;

        static int _pickStage = FirstPickStage;

        public static int CurrentPickStage => _pickStage;

        public static void RefreshPickStage()
        {
            SetPickStage(Academy.Instance.EnvironmentParameters.GetWithDefault(
                PickStageParameterName, FinalPickStage));
        }

        public static void SetPickStage(float stage)
        {
            _pickStage = IsFinite(stage)
                ? Mathf.Clamp(Mathf.RoundToInt(stage), FirstPickStage, FinalPickStage)
                : FirstPickStage;
        }

        public static float CurrentMinimumSpawnRadius
        {
            get
            {
                switch (_pickStage)
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
                switch (_pickStage)
                {
                    case 1: return 0.50f;
                    case 2: return 0.52f;
                    default: return MaximumSpawnRadius;
                }
            }
        }

        // --- approach shaping (unchanged from GraspLift) ---------------------------
        public const float ApproachPotentialMaximum = 1.0f;
        public const float FineApproachPotentialMaximum = 1.5f;
        public const float FineApproachDistance = 0.12f;
        public const float TopDownAlignmentPotentialMax = 0.3f;
        public const float MinimumTopDownAlignmentPotentialMax = 0f;
        public const float MaximumTopDownAlignmentPotentialMax = 5f;
        public const string TopDownAlignmentPotentialMaxParameterName = "topdown_potential_max";
        public const float TopDownAlignmentRewardDistance = 0.20f;
        public const float MaximumTopDownAngleDegrees = 35f;
        public const float TopDownRewardEntryAngleDegrees = 70f;

        // --- grip shaping (unchanged from GraspLift) --------------------------------
        public const float GraspReadyDistance = 0.045f;
        public const float CloseNearObjectReward = 1.0f;
        public const float EffectiveGripClosure = 0.75f;
        public const float CloseFarObjectPenalty = -0.25f;
        public const float MinimumGraspClosure = 0.30f;

        // --- contact / grasp confirmation (unchanged from GraspLift) ---------------
        public const float ContactPotentialMaximum = 0.4f;
        public const int GraspContactMinimum = 3;
        public const float GraspOppositionAngleDeg = 90f;
        public const float GraspCenterMaxDistance = 0.05f;
        public const float GraspConfirmSeconds = 0.30f;
        public const float GraspConfirmReward = 1.0f;

        // --- lift-clearance milestone (new, small — the real goal is placement) ----
        // One-shot bonus for having genuinely lifted the cube clear of the floor,
        // separate from (and much smaller than) the final placement reward.
        public const float LiftClearanceHeightMeters = 0.15f;
        public const float LiftClearanceReward = 1.0f;

        // --- transport shaping (new) -------------------------------------------------
        // The cube's flight target while carrying: fly at (marker.xz, hover
        // height) until horizontally aligned with the marker, then the target
        // height drops to the platform's top face for the final descent. This
        // keeps a loaded cube from being dragged sideways into the platform's
        // side wall instead of lifted over it.
        public const float TransportClearanceHeight = 0.08f;
        public const float TransportPotentialMaximum = 2.0f;
        public const float ArrivalXZToleranceMeters = 0.05f;
        public const float ArrivalHeightSlackMeters = 0.05f;
        // Physics contacts flicker during a re-grip; allow a short loss of
        // contact before declaring the cube dropped (identical rationale/value to
        // GraspLift's SlipGraceSeconds).
        public const float SlipGraceSeconds = 0.20f;

        public static float HoverHeight => PlatformTopHeight + TransportClearanceHeight;

        // --- placement success --------------------------------------------------------
        public const float PlacePositionToleranceMeters = 0.03f;
        public const float PlaceHeightToleranceMeters = 0.02f;
        public const float PlaceMaximumSpeed = 0.15f;
        // Generic cube, not fragile cargo, so this is more forgiving than a real
        // wafer-carrier tolerance would be.
        public const float PlaceUprightToleranceDegrees = 20f;
        public const float PlaceSettleSeconds = 0.5f;
        public const float PlaceSuccessReward = 6.0f;

        // --- penalties (values match GraspLift's proven cube-scale defaults) -------
        public const float DropPenalty = -1.0f;
        public const float PushAwayPenalty = -0.5f;
        public const float PushAwayDistance = 0.30f;
        public const float OutOfBoundsPenalty = -1.0f;
        public const float TopplePenalty = -0.3f;
        public const float ToppleLimitDegrees = 45f;
        public const string ToppleLimitParameterName = "topple_limit_deg";
        public const float UnsafeSurfacePenalty = -2.0f;
        public const float ClosedHandAscentPenalty = -0.004f;
        public const float ClosedHandAscentHeight = 0.15f;
        public const float NearObjectControlClearance = 0.08f;
        public const float NearObjectActionPenaltyScale = -0.002f;
        public const float NearObjectArmDeltaScale = 0.35f;
        public const float ActionRatePenaltyScale = -0.001f;
        public const float MinimumActionRatePenaltyScale = -1f;
        public const float MaximumActionRatePenaltyScale = 0f;
        public const string ActionRatePenaltyScaleParameterName = "action_rate_penalty_scale";
        public const float HandSurfacePenaltyPerSecond = -0.05f;
        public const float MinimumHandSurfacePenaltyPerSecond = -5f;
        public const float MaximumHandSurfacePenaltyPerSecond = 0f;
        public const string HandSurfacePenaltyPerSecondParameterName =
            "hand_surface_penalty_per_second";
        public const float GraspPosturePenaltyScale = 0f;
        public const float MinimumGraspPosturePenaltyScale = -1f;
        public const float MaximumGraspPosturePenaltyScale = 0f;
        public const string GraspPosturePenaltyScaleParameterName = "grasp_posture_penalty_scale";

        static float _topDownAlignmentPotentialMax = TopDownAlignmentPotentialMax;
        static float _actionRatePenaltyScale = ActionRatePenaltyScale;
        static float _handSurfacePenaltyPerSecond = HandSurfacePenaltyPerSecond;
        static float _graspPosturePenaltyScale = GraspPosturePenaltyScale;
        static float _toppleLimitDeg = ToppleLimitDegrees;

        public static float CurrentTopDownAlignmentPotentialMax => _topDownAlignmentPotentialMax;

        public static void RefreshTopDownAlignmentPotentialMax()
        {
            SetTopDownAlignmentPotentialMax(Academy.Instance.EnvironmentParameters.GetWithDefault(
                TopDownAlignmentPotentialMaxParameterName, TopDownAlignmentPotentialMax));
        }

        public static void SetTopDownAlignmentPotentialMax(float maximum)
        {
            _topDownAlignmentPotentialMax = IsFinite(maximum)
                ? Mathf.Clamp(maximum, MinimumTopDownAlignmentPotentialMax,
                    MaximumTopDownAlignmentPotentialMax)
                : TopDownAlignmentPotentialMax;
        }

        public static float CurrentActionRatePenaltyScale => _actionRatePenaltyScale;

        public static void RefreshActionRatePenaltyScale()
        {
            SetActionRatePenaltyScale(Academy.Instance.EnvironmentParameters.GetWithDefault(
                ActionRatePenaltyScaleParameterName, ActionRatePenaltyScale));
        }

        public static void SetActionRatePenaltyScale(float scale)
        {
            _actionRatePenaltyScale = IsFinite(scale)
                ? Mathf.Clamp(scale, MinimumActionRatePenaltyScale, MaximumActionRatePenaltyScale)
                : ActionRatePenaltyScale;
        }

        public static float CurrentHandSurfacePenaltyPerSecond => _handSurfacePenaltyPerSecond;

        public static void RefreshHandSurfacePenaltyPerSecond()
        {
            SetHandSurfacePenaltyPerSecond(Academy.Instance.EnvironmentParameters.GetWithDefault(
                HandSurfacePenaltyPerSecondParameterName, HandSurfacePenaltyPerSecond));
        }

        public static void SetHandSurfacePenaltyPerSecond(float scale)
        {
            _handSurfacePenaltyPerSecond = IsFinite(scale)
                ? Mathf.Clamp(scale, MinimumHandSurfacePenaltyPerSecond,
                    MaximumHandSurfacePenaltyPerSecond)
                : HandSurfacePenaltyPerSecond;
        }

        public static float CurrentGraspPosturePenaltyScale => _graspPosturePenaltyScale;

        public static void RefreshGraspPosturePenaltyScale()
        {
            SetGraspPosturePenaltyScale(Academy.Instance.EnvironmentParameters.GetWithDefault(
                GraspPosturePenaltyScaleParameterName, GraspPosturePenaltyScale));
        }

        public static void SetGraspPosturePenaltyScale(float scale)
        {
            _graspPosturePenaltyScale = IsFinite(scale)
                ? Mathf.Clamp(scale, MinimumGraspPosturePenaltyScale, MaximumGraspPosturePenaltyScale)
                : GraspPosturePenaltyScale;
        }

        public static float CurrentToppleLimitDegrees => _toppleLimitDeg;

        public static void RefreshToppleLimit()
        {
            SetToppleLimit(Academy.Instance.EnvironmentParameters.GetWithDefault(
                ToppleLimitParameterName, ToppleLimitDegrees));
        }

        public static void SetToppleLimit(float degrees)
        {
            _toppleLimitDeg = IsFinite(degrees) ? Mathf.Clamp(degrees, 5f, 180f) : ToppleLimitDegrees;
        }

        // Palm-local centre of the full-hand grasp volume — unchanged, defined
        // relative to the palm.
        public static readonly Vector3 FullHandGraspPointLocalPosition =
            new Vector3(0f, 0.05f, 0.04f);

        public static readonly string[] ArmLinks =
        {
            "shoulder_link", "upper_arm_link", "forearm_link",
            "wrist_1_link", "wrist_2_link", "wrist_3_link"
        };

        public static readonly float[] ArmSafeMinDeg = { -180f, -120f, 20f, -180f, -150f, -180f };
        public static readonly float[] ArmSafeMaxDeg = { 180f, -20f, 140f, 0f, -30f, 180f };

        // See Dg5fPicknPlaceAgent's earlier revision history / docs/DG5F_PICKNPLACE.md
        // for the mirror-reconstruction rationale.
        public static readonly float[] RightFistDeg =
        {
             40f, -80f,  60f,  60f,
              0f, 100f,  80f,  70f,
              0f, 100f,  80f,  70f,
              0f,  95f,  80f,  70f,
              0f,   0f,  80f,  70f
        };

        // --- shared math (ported unchanged from Dg5fGraspLiftSpec) ------------------

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

        public static float NewBestPotentialDelta(float previousBestPotential, float currentPotential)
        {
            if (!IsFinite(previousBestPotential) || !IsFinite(currentPotential)) return 0f;
            return Mathf.Max(0f, currentPotential - previousBestPotential);
        }

        public static float ApproachPotential(float distance)
        {
            if (!IsFinite(distance)) return 0f;
            return ApproachPotentialMaximum
                * (1f - Mathf.Clamp01(Mathf.Max(0f, distance) / MaximumObjectDistance));
        }

        public static float PalmFacingAlignment(Vector3 palmForward, Vector3 palmToObject)
        {
            if (!IsFinite(palmForward) || !IsFinite(palmToObject)
                || palmForward.sqrMagnitude <= 1e-12f || palmToObject.sqrMagnitude <= 1e-12f)
                return -1f;
            return Mathf.Clamp(Vector3.Dot(palmForward.normalized, palmToObject.normalized), -1f, 1f);
        }

        public static bool IsPalmFacingObject(float palmFacingAlignment)
        {
            return IsFinite(palmFacingAlignment) && palmFacingAlignment > 0f;
        }

        public static float FineApproachPotential(float distance)
        {
            if (!IsFinite(distance)) return 0f;
            return FineApproachPotentialMaximum
                * (1f - Mathf.Clamp01(Mathf.Max(0f, distance) / FineApproachDistance));
        }

        public static float DirectionalApproachPotential(float distance, float palmFacingAlignment)
        {
            return IsPalmFacingObject(palmFacingAlignment)
                ? ApproachPotential(distance) + FineApproachPotential(distance)
                : 0f;
        }

        public static float TopDownAlignment(Vector3 graspForward, Vector3 robotUp)
        {
            if (!IsFinite(graspForward) || !IsFinite(robotUp)
                || graspForward.sqrMagnitude <= 1e-12f || robotUp.sqrMagnitude <= 1e-12f)
                return -1f;
            return Mathf.Clamp(Vector3.Dot(graspForward.normalized, -robotUp.normalized), -1f, 1f);
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

        public static float TopDownAlignmentPotential(
            float distance, float heightAboveObject, float topDownAlignment)
        {
            if (!IsFinite(distance) || !IsFinite(heightAboveObject) || !IsFinite(topDownAlignment)
                || distance > TopDownAlignmentRewardDistance + 1e-6f || heightAboveObject < -1e-6f)
                return 0f;

            float progress = Mathf.Clamp01(
                (TopDownRewardEntryAngleDegrees - TopDownAngleDegrees(topDownAlignment))
                / (TopDownRewardEntryAngleDegrees - MaximumTopDownAngleDegrees));
            return _topDownAlignmentPotentialMax * progress * progress;
        }

        public static float GraspPosturePenalty(float angleDegrees, float graspDistance, bool graspConfirmed)
        {
            if (graspConfirmed || !IsFinite(angleDegrees) || !IsFinite(graspDistance)
                || graspDistance > GraspReadyDistance + 1e-6f)
                return 0f;

            float progress = Mathf.Clamp01(
                (angleDegrees - MaximumTopDownAngleDegrees) / (90f - MaximumTopDownAngleDegrees));
            return _graspPosturePenaltyScale * progress;
        }

        public static float ClosurePotential(float closure, bool readyToGrasp)
        {
            if (!readyToGrasp || !IsFinite(closure)) return 0f;
            return CloseNearObjectReward * Mathf.Clamp01(Mathf.Max(0f, closure) / EffectiveGripClosure);
        }

        public static float ClosureFarPenalty(float closureDelta, bool readyToGrasp)
        {
            if (readyToGrasp || !IsFinite(closureDelta)) return 0f;
            return Mathf.Max(0f, closureDelta) * CloseFarObjectPenalty;
        }

        public static float ContactPotential(int contactCount)
        {
            if (contactCount <= 0) return 0f;
            return ContactPotentialMaximum * Mathf.Clamp01(contactCount / (float)GraspContactMinimum);
        }

        public static float MaximumOppositionAngleDegrees(Vector3[] contactDirections, int contactCount)
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
                    float cosine = Mathf.Clamp(Vector3.Dot(firstNormalized, second.normalized), -1f, 1f);
                    float angle = Mathf.Acos(cosine) * Mathf.Rad2Deg;
                    if (angle > maximumAngle) maximumAngle = angle;
                }
            }
            return maximumAngle;
        }

        public static bool IsForceClosureLike(Vector3[] contactDirections, int contactCount)
        {
            return contactCount >= GraspContactMinimum
                && MaximumOppositionAngleDegrees(contactDirections, contactCount)
                    >= GraspOppositionAngleDeg - 1e-4f;
        }

        public static bool IsGraspGeometryValid(Vector3 objectCenter, Vector3 contactCentroid)
        {
            if (!IsFinite(objectCenter) || !IsFinite(contactCentroid)) return false;
            return Vector3.Distance(objectCenter, contactCentroid) <= GraspCenterMaxDistance + 1e-6f;
        }

        public static bool IsGraspCandidate(
            int contactCount, Vector3[] contactDirections, Vector3 objectCenter,
            Vector3 contactCentroid, float closure)
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

        public static bool IsClosedHandAscent(
            float graspPointHeightAbovePanel, float closure, bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            if (!IsFinite(graspPointHeightAbovePanel) || !IsFinite(closure)) return false;
            return closure >= MinimumGraspClosure && graspPointHeightAbovePanel > ClosedHandAscentHeight;
        }

        public static float PlanarDistance(Vector3 first, Vector3 second)
        {
            if (!IsFinite(first) || !IsFinite(second)) return float.PositiveInfinity;
            return new Vector2(first.x - second.x, first.z - second.z).magnitude;
        }

        public static bool IsPushedAway(
            Vector3 objectLocalPosition, Vector3 spawnLocalPosition, bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            return PlanarDistance(objectLocalPosition, spawnLocalPosition) > PushAwayDistance;
        }

        public static float ObjectTiltDegrees(Vector3 objectUp, Vector3 robotUp)
        {
            if (!IsFinite(objectUp) || !IsFinite(robotUp)
                || objectUp.sqrMagnitude <= 1e-12f || robotUp.sqrMagnitude <= 1e-12f)
                return 0f;
            float cosine = Mathf.Clamp(Vector3.Dot(objectUp.normalized, robotUp.normalized), -1f, 1f);
            return Mathf.Acos(cosine) * Mathf.Rad2Deg;
        }

        public static bool IsToppled(float tiltDegrees, bool graspConfirmed)
        {
            if (graspConfirmed) return false;
            return IsFinite(tiltDegrees) && tiltDegrees >= _toppleLimitDeg - 1e-4f;
        }

        public static bool IsOutOfBounds(Vector3 objectLocalPosition, float panelTopHeight, float halfHeight)
        {
            if (!IsFinite(objectLocalPosition)) return true;
            if (objectLocalPosition.magnitude > MaximumObjectDistance) return true;
            return objectLocalPosition.y < panelTopHeight - Mathf.Max(0f, halfHeight);
        }

        // --- cube spawn ------------------------------------------------------------

        public static float AreaUniformRadius(float unitSample)
        {
            float minimum = CurrentMinimumSpawnRadius;
            float maximum = CurrentMaximumSpawnRadius;
            return Mathf.Sqrt(Mathf.Lerp(minimum * minimum, maximum * maximum, Mathf.Clamp01(unitSample)));
        }

        public static float SpawnAzimuthRadians(float azimuthUnitSample)
        {
            return Mathf.Clamp01(azimuthUnitSample) * 2f * Mathf.PI;
        }

        public static Vector3 SpawnCubeLocalPosition(
            float radiusUnitSample, float azimuthUnitSample, float cubeHeight)
        {
            float horizontalRadius = AreaUniformRadius(radiusUnitSample);
            float azimuth = SpawnAzimuthRadians(azimuthUnitSample);
            return new Vector3(
                Mathf.Cos(azimuth) * horizontalRadius,
                SupportTopHeight + Mathf.Max(0f, cubeHeight) * 0.5f,
                Mathf.Sin(azimuth) * horizontalRadius);
        }

        /// True when a candidate cube spawn is inside the pick annulus, inside the
        /// panel, resting flush on the floor, and clear of the platform footprint.
        public static bool IsValidCubeSpawn(Vector3 localPosition, float cubeWidth, float cubeHeight)
        {
            if (!IsFinite(localPosition)) return false;
            float horizontalRadius = new Vector2(localPosition.x, localPosition.z).magnitude;
            float halfWidth = Mathf.Max(0f, cubeWidth) * 0.5f;
            float restingHeight = localPosition.y - Mathf.Max(0f, cubeHeight) * 0.5f;
            float distanceFromPlatform = Vector2.Distance(
                new Vector2(localPosition.x, localPosition.z),
                new Vector2(PlatformLocalPosition.x, PlatformLocalPosition.z));

            return horizontalRadius >= CurrentMinimumSpawnRadius - 1e-6f
                && horizontalRadius <= CurrentMaximumSpawnRadius + 1e-6f
                && Mathf.Abs(localPosition.x) + halfWidth <= PanelWidth * 0.5f
                && Mathf.Abs(localPosition.z) + halfWidth <= PanelDepth * 0.5f
                && Mathf.Abs(restingHeight - SupportTopHeight) <= 1e-5f
                && localPosition.magnitude <= MaximumObjectDistance
                && distanceFromPlatform >= PlatformExclusionRadius;
        }

        // --- transport / place -------------------------------------------------------

        /// The point the carried cube should currently be flying toward: above the
        /// marker at hover height until horizontally aligned, then the marker's
        /// own resting height for the final descent. markerWorldPosition.y is
        /// assumed to already be the resting (platform-top) height.
        public static Vector3 TransportTargetPosition(
            Vector3 markerWorldPosition, Vector3 robotUp, bool hasArrivedAboveMarker)
        {
            float targetHeightOffset = hasArrivedAboveMarker ? 0f : TransportClearanceHeight;
            return markerWorldPosition + robotUp.normalized * targetHeightOffset;
        }

        public static float TransportPotential(float distanceToTransportTarget)
        {
            if (!IsFinite(distanceToTransportTarget)) return 0f;
            return TransportPotentialMaximum
                * (1f - Mathf.Clamp01(Mathf.Max(0f, distanceToTransportTarget) / MaximumObjectDistance));
        }

        public static bool HasArrivedAboveMarker(float xzDistanceToMarker, float heightAbovePanel)
        {
            if (!IsFinite(xzDistanceToMarker) || !IsFinite(heightAbovePanel)) return false;
            return xzDistanceToMarker <= ArrivalXZToleranceMeters
                && heightAbovePanel >= HoverHeight - ArrivalHeightSlackMeters;
        }

        public static bool IsAtRestOnTarget(
            float xzDistanceToMarker, float heightAbovePanel, float speed, float tiltDegrees)
        {
            if (!IsFinite(xzDistanceToMarker) || !IsFinite(heightAbovePanel)
                || !IsFinite(speed) || !IsFinite(tiltDegrees))
                return false;
            return xzDistanceToMarker <= CurrentPlacePositionToleranceMeters
                && Mathf.Abs(heightAbovePanel - PlatformTopHeight) <= PlaceHeightToleranceMeters
                && speed <= PlaceMaximumSpeed
                && tiltDegrees <= PlaceUprightToleranceDegrees;
        }

        public static bool IsPlaceComplete(float settleSeconds)
        {
            return IsFinite(settleSeconds) && settleSeconds >= PlaceSettleSeconds - 1e-5f;
        }

        // --- termination --------------------------------------------------------

        public static bool ReachedEpisodeTimeout(float elapsedSeconds)
        {
            return IsFinite(elapsedSeconds) && elapsedSeconds >= EpisodeTimeoutSeconds - 1e-5f;
        }

        public static bool UsesNearObjectControl(float distance)
        {
            return IsFinite(distance) && distance <= NearObjectControlClearance + 1e-6f;
        }

        public static float NearObjectActionPenalty(float sumSquaredArmActions)
        {
            if (!IsFinite(sumSquaredArmActions)) return 0f;
            return NearObjectActionPenaltyScale * Mathf.Max(0f, sumSquaredArmActions) / ArmJointCount;
        }

        public static float ArmActionRatePenalty(float sumSquaredArmActionDeltas)
        {
            if (!IsFinite(sumSquaredArmActionDeltas)) return 0f;
            return _actionRatePenaltyScale * Mathf.Max(0f, sumSquaredArmActionDeltas) / ArmJointCount;
        }

        public static float HandSurfaceContactPenalty(float contactSeconds, bool graspConfirmed)
        {
            if (graspConfirmed || !IsFinite(contactSeconds) || contactSeconds <= 0f) return 0f;
            return _handSurfacePenaltyPerSecond * contactSeconds;
        }

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
