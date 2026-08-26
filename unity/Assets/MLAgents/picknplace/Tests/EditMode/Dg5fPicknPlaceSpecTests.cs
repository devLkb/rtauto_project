using KDT.PicknPlaceTraining;
using NUnit.Framework;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Tests
{
    public sealed class Dg5fPicknPlaceSpecTests
    {
        [TearDown]
        public void ResetStage()
        {
            Dg5fPicknPlaceSpec.SetPickStage(Dg5fPicknPlaceSpec.FinalPickStage);
            Dg5fPicknPlaceSpec.SetPlaceStage(Dg5fPicknPlaceSpec.FinalPlaceStage);
            Dg5fPicknPlaceSpec.SetCubeWidth(Dg5fPicknPlaceSpec.CubeWidth);
            Dg5fPicknPlaceSpec.SetCubeHeight(Dg5fPicknPlaceSpec.CubeHeight);
            Dg5fPicknPlaceSpec.SetCubeComHeightFraction(Dg5fPicknPlaceSpec.CubeComHeightFraction);
            Dg5fPicknPlaceSpec.SetToppleLimit(Dg5fPicknPlaceSpec.ToppleLimitDegrees);
            Dg5fPicknPlaceSpec.SetTopDownAlignmentPotentialMax(
                Dg5fPicknPlaceSpec.TopDownAlignmentPotentialMax);
            Dg5fPicknPlaceSpec.SetActionRatePenaltyScale(Dg5fPicknPlaceSpec.ActionRatePenaltyScale);
            Dg5fPicknPlaceSpec.SetHandSurfacePenaltyPerSecond(
                Dg5fPicknPlaceSpec.HandSurfacePenaltyPerSecond);
            Dg5fPicknPlaceSpec.SetGraspPosturePenaltyScale(Dg5fPicknPlaceSpec.GraspPosturePenaltyScale);
        }

        // --- cube geometry parameters ------------------------------------------

        [Test]
        public void CubeWidthIsClampedToASensibleRange()
        {
            Dg5fPicknPlaceSpec.SetCubeWidth(0.001f);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.MinimumCubeWidth, Dg5fPicknPlaceSpec.CurrentCubeWidth, 1e-6f);
            Dg5fPicknPlaceSpec.SetCubeWidth(10f);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.MaximumCubeWidth, Dg5fPicknPlaceSpec.CurrentCubeWidth, 1e-6f);
            Dg5fPicknPlaceSpec.SetCubeWidth(float.NaN);
            Assert.AreEqual(Dg5fPicknPlaceSpec.CubeWidth, Dg5fPicknPlaceSpec.CurrentCubeWidth, 1e-6f);
        }

        [Test]
        public void CubeHalfHeightAndGraspTargetOffsetTrackCubeHeight()
        {
            Dg5fPicknPlaceSpec.SetCubeHeight(0.12f);
            Assert.AreEqual(0.06f, Dg5fPicknPlaceSpec.CurrentCubeHalfHeight, 1e-6f);
            Assert.AreEqual(
                0.04f, Dg5fPicknPlaceSpec.CurrentGraspTargetHeightOffset, 1e-6f,
                "the grasp target must retain its 2 cm inset below the top face");
        }

        // --- pick-stage curriculum (spawn annulus) ------------------------------

        [Test]
        public void PickSpawnAnnulusWidensOutwardAcrossStages()
        {
            Dg5fPicknPlaceSpec.SetPickStage(1);
            float stage1Min = Dg5fPicknPlaceSpec.CurrentMinimumSpawnRadius;
            float stage1Max = Dg5fPicknPlaceSpec.CurrentMaximumSpawnRadius;

            Dg5fPicknPlaceSpec.SetPickStage(Dg5fPicknPlaceSpec.FinalPickStage);
            Assert.Less(Dg5fPicknPlaceSpec.CurrentMinimumSpawnRadius, stage1Min);
            Assert.Greater(Dg5fPicknPlaceSpec.CurrentMaximumSpawnRadius, stage1Max);
        }

        // --- cube spawn validity — must avoid the platform footprint -----------

        [Test]
        public void IsValidCubeSpawnRejectsPositionsNearThePlatform()
        {
            Dg5fPicknPlaceSpec.SetPickStage(Dg5fPicknPlaceSpec.FinalPickStage);
            float restY = Dg5fPicknPlaceSpec.SupportTopHeight + Dg5fPicknPlaceSpec.CubeHeight * 0.5f;

            // Chosen to sit inside the pick annulus (radius ~0.49, within
            // 0.37..0.58) by radius alone, but only 0.25 m from the platform
            // centre (0.60, 0) — inside PlatformExclusionRadius (0.30). Isolates
            // the platform-exclusion check from the annulus check.
            var nearPlatform = new Vector3(0.45f, restY, 0.20f);
            Assert.Less(
                Vector2.Distance(new Vector2(0.45f, 0.20f), new Vector2(0.60f, 0f)),
                Dg5fPicknPlaceSpec.PlatformExclusionRadius,
                "test setup check: the candidate must actually be inside the exclusion disk");
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                nearPlatform, Dg5fPicknPlaceSpec.CubeWidth, Dg5fPicknPlaceSpec.CubeHeight),
                "a spawn inside the platform's exclusion radius must never be valid");

            float midRadius =
                (Dg5fPicknPlaceSpec.MinimumSpawnRadius + Dg5fPicknPlaceSpec.MaximumSpawnRadius) * 0.5f;
            // Opposite side of the panel from the platform (platform is at +X).
            var valid = new Vector3(-midRadius, restY, 0f);
            Assert.IsTrue(Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                valid, Dg5fPicknPlaceSpec.CubeWidth, Dg5fPicknPlaceSpec.CubeHeight));
        }

        [Test]
        public void IsValidCubeSpawnRejectsNonFinitePositions()
        {
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                new Vector3(float.NaN, 0f, 0f), Dg5fPicknPlaceSpec.CubeWidth,
                Dg5fPicknPlaceSpec.CubeHeight));
        }

        // --- place-stage curriculum ----------------------------------------------

        [Test]
        public void PlaceStagePrecisionTightensAcrossStages()
        {
            Dg5fPicknPlaceSpec.SetPlaceStage(1);
            float stage1Range = Dg5fPicknPlaceSpec.CurrentMarkerRangeMeters;
            float stage1Tolerance = Dg5fPicknPlaceSpec.CurrentPlacePositionToleranceMeters;

            Dg5fPicknPlaceSpec.SetPlaceStage(Dg5fPicknPlaceSpec.FinalPlaceStage);
            Assert.Greater(Dg5fPicknPlaceSpec.CurrentMarkerRangeMeters, stage1Range,
                "later stages randomize the marker over a wider area");
            Assert.Less(Dg5fPicknPlaceSpec.CurrentPlacePositionToleranceMeters, stage1Tolerance,
                "later stages demand tighter placement precision");
        }

        [Test]
        public void MarkerLocalOffsetStaysWithinTheCurrentRange()
        {
            Dg5fPicknPlaceSpec.SetPlaceStage(Dg5fPicknPlaceSpec.FinalPlaceStage);
            float range = Dg5fPicknPlaceSpec.CurrentMarkerRangeMeters;
            Vector3 corner = Dg5fPicknPlaceSpec.MarkerLocalOffset(1f, 1f);
            Assert.AreEqual(range, corner.x, 1e-4f);
            Assert.AreEqual(range, corner.z, 1e-4f);
            Vector3 center = Dg5fPicknPlaceSpec.MarkerLocalOffset(0.5f, 0.5f);
            Assert.AreEqual(0f, center.x, 1e-4f);
            Assert.AreEqual(0f, center.z, 1e-4f);
        }

        // --- transport / placement geometry --------------------------------------

        [Test]
        public void TransportTargetHoversUntilArrivedThenDropsToPlatformHeight()
        {
            var marker = new Vector3(1f, Dg5fPicknPlaceSpec.PlatformTopHeight, 0.5f);
            Vector3 hovering = Dg5fPicknPlaceSpec.TransportTargetPosition(marker, Vector3.up, false);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.PlatformTopHeight + Dg5fPicknPlaceSpec.TransportClearanceHeight,
                hovering.y, 1e-4f);

            Vector3 arrived = Dg5fPicknPlaceSpec.TransportTargetPosition(marker, Vector3.up, true);
            Assert.AreEqual(Dg5fPicknPlaceSpec.PlatformTopHeight, arrived.y, 1e-4f);
        }

        [Test]
        public void HasArrivedAboveMarkerRequiresBothXZAndHeight()
        {
            Assert.IsFalse(Dg5fPicknPlaceSpec.HasArrivedAboveMarker(0f, 0f),
                "xz-aligned but not yet at hover height");
            Assert.IsFalse(Dg5fPicknPlaceSpec.HasArrivedAboveMarker(1f, Dg5fPicknPlaceSpec.HoverHeight),
                "at hover height but not xz-aligned");
            Assert.IsTrue(Dg5fPicknPlaceSpec.HasArrivedAboveMarker(0f, Dg5fPicknPlaceSpec.HoverHeight));
        }

        [Test]
        public void IsAtRestOnTargetRequiresPositionSpeedAndUpright()
        {
            Assert.IsTrue(Dg5fPicknPlaceSpec.IsAtRestOnTarget(
                0f, Dg5fPicknPlaceSpec.PlatformTopHeight, 0f, 0f));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsAtRestOnTarget(
                1f, Dg5fPicknPlaceSpec.PlatformTopHeight, 0f, 0f), "too far from the marker");
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsAtRestOnTarget(
                0f, Dg5fPicknPlaceSpec.PlatformTopHeight, 5f, 0f), "moving too fast");
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsAtRestOnTarget(
                0f, Dg5fPicknPlaceSpec.PlatformTopHeight, 0f, 90f), "tipped over");
        }

        [Test]
        public void ToppleLimitMatchesGraspLiftsCubeScaleDefault()
        {
            // This task grasps a generic cube (not fragile wafer cargo), so it
            // should use the same tolerance GraspLift validated, not the FOUP
            // handle-grasp iteration's stricter placeholder.
            Assert.AreEqual(45f, Dg5fPicknPlaceSpec.ToppleLimitDegrees, 1e-6f);
        }
    }
}
