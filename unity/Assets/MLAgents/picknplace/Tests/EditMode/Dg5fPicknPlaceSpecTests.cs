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
            Dg5fPicknPlaceSpec.SetGraspStage(Dg5fPicknPlaceSpec.FinalGraspStage);
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

        [Test]
        public void DefaultCubeHeightIsTheRequestedTwelveCentimetrePillar()
        {
            Dg5fPicknPlaceSpec.SetCubeHeight(Dg5fPicknPlaceSpec.CubeHeight);
            Assert.AreEqual(0.12f, Dg5fPicknPlaceSpec.CurrentCubeHeight, 1e-6f,
                "the grasp target is the GraspLift-proven 12 cm square pillar");
        }

        [Test]
        public void CubeMassFollowsCubeVolume()
        {
            Dg5fPicknPlaceSpec.SetCubeWidth(0.03f);
            Dg5fPicknPlaceSpec.SetCubeHeight(0.09f);
            float smallWidthAndHeight = Dg5fPicknPlaceSpec.CurrentCubeMass;
            Dg5fPicknPlaceSpec.SetCubeWidth(0.05f);
            float largeWidth = Dg5fPicknPlaceSpec.CurrentCubeMass;
            Assert.Greater(largeWidth, smallWidthAndHeight);
            Dg5fPicknPlaceSpec.SetCubeHeight(0.12f);
            float largeWidthAndHeight = Dg5fPicknPlaceSpec.CurrentCubeMass;
            Assert.Greater(largeWidthAndHeight, largeWidth);
            Assert.AreEqual(
                0.05f * 0.05f * 0.12f * Dg5fPicknPlaceSpec.CubeDensity,
                largeWidthAndHeight,
                1e-6f);
        }

        [Test]
        public void CubeCenterOfMassHeightFractionIsClampedAndMappedToLocalSpace()
        {
            Dg5fPicknPlaceSpec.SetCubeComHeightFraction(0f);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.MinimumCubeComHeightFraction,
                Dg5fPicknPlaceSpec.CurrentCubeComHeightFraction,
                1e-6f);
            Dg5fPicknPlaceSpec.SetCubeComHeightFraction(1f);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.MaximumCubeComHeightFraction,
                Dg5fPicknPlaceSpec.CurrentCubeComHeightFraction,
                1e-6f);
            Dg5fPicknPlaceSpec.SetCubeComHeightFraction(float.NaN);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.CubeComHeightFraction,
                Dg5fPicknPlaceSpec.CurrentCubeComHeightFraction,
                1e-6f);

            float fraction = 0.25f;
            Dg5fPicknPlaceSpec.SetCubeComHeightFraction(fraction);
            Assert.AreEqual(
                fraction - 0.5f,
                Dg5fPicknPlaceSpec.CurrentCubeCenterOfMassLocal.y,
                1e-6f);
        }

        // --- contract -------------------------------------------------------

        [Test]
        public void PolicyShapeMatchesTheGraspLiftContract()
        {
            Assert.AreEqual(57, Dg5fPicknPlaceSpec.ObservationSize);
            Assert.AreEqual(7, Dg5fPicknPlaceSpec.ActionSize);
            Assert.AreEqual(6, Dg5fPicknPlaceSpec.ContactPointCount);
            Assert.AreEqual(5, Dg5fPicknPlaceSpec.PalmContactIndex);
            Assert.AreEqual(20, Dg5fPicknPlaceSpec.RightFistDeg.Length);
            Assert.AreEqual(6, Dg5fPicknPlaceSpec.ArmLinks.Length);
        }

        // --- curriculum -----------------------------------------------------

        [Test]
        public void GraspStageIsClampedAndRounded()
        {
            Dg5fPicknPlaceSpec.SetGraspStage(-4f);
            Assert.AreEqual(Dg5fPicknPlaceSpec.FirstGraspStage, Dg5fPicknPlaceSpec.CurrentGraspStage);
            Dg5fPicknPlaceSpec.SetGraspStage(99f);
            Assert.AreEqual(Dg5fPicknPlaceSpec.FinalGraspStage, Dg5fPicknPlaceSpec.CurrentGraspStage);
            Dg5fPicknPlaceSpec.SetGraspStage(1.6f);
            Assert.AreEqual(2, Dg5fPicknPlaceSpec.CurrentGraspStage);
            Dg5fPicknPlaceSpec.SetGraspStage(float.NaN);
            Assert.AreEqual(Dg5fPicknPlaceSpec.FirstGraspStage, Dg5fPicknPlaceSpec.CurrentGraspStage);
        }

        [Test]
        public void GraspStageWidensTheSpawnAnnulusOutward()
        {
            Dg5fPicknPlaceSpec.SetGraspStage(1);
            float stage1Min = Dg5fPicknPlaceSpec.CurrentMinimumSpawnRadius;
            float stage1Max = Dg5fPicknPlaceSpec.CurrentMaximumSpawnRadius;

            Dg5fPicknPlaceSpec.SetGraspStage(Dg5fPicknPlaceSpec.FinalGraspStage);
            Assert.Less(Dg5fPicknPlaceSpec.CurrentMinimumSpawnRadius, stage1Min);
            Assert.Greater(Dg5fPicknPlaceSpec.CurrentMaximumSpawnRadius, stage1Max);
        }

        [Test]
        public void CurriculumMonotonicallyTightensTheLiftContract()
        {
            Dg5fPicknPlaceSpec.SetGraspStage(1);
            float easyHeight = Dg5fPicknPlaceSpec.CurrentLiftTargetHeight;
            float easyHold = Dg5fPicknPlaceSpec.CurrentLiftHoldSeconds;
            Dg5fPicknPlaceSpec.SetGraspStage(3);
            Assert.Greater(Dg5fPicknPlaceSpec.CurrentLiftTargetHeight, easyHeight);
            Assert.Greater(Dg5fPicknPlaceSpec.CurrentLiftHoldSeconds, easyHold);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.LiftTargetHeight,
                Dg5fPicknPlaceSpec.CurrentLiftTargetHeight,
                1e-6f);
        }

        // --- cube spawn ---------------------------------------------------------

        [Test]
        public void EverySampledSpawnIsValidAtEveryStage()
        {
            for (int stage = Dg5fPicknPlaceSpec.FirstGraspStage;
                 stage <= Dg5fPicknPlaceSpec.FinalGraspStage;
                 stage++)
            {
                Dg5fPicknPlaceSpec.SetGraspStage(stage);
                for (int i = 0; i <= 40; i++)
                {
                    float u = i / 40f;
                    Vector3 spawn = Dg5fPicknPlaceSpec.SpawnCubeLocalPosition(
                        u, 1f - u, Dg5fPicknPlaceSpec.CubeHeight);
                    Assert.IsTrue(
                        Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                            spawn,
                            Dg5fPicknPlaceSpec.CubeWidth,
                            Dg5fPicknPlaceSpec.CubeHeight),
                        $"stage {stage} sample {u} produced an invalid spawn {spawn}");
                }
            }
        }

        [Test]
        public void IsValidCubeSpawnRejectsNonFinitePositions()
        {
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                new Vector3(float.NaN, 0f, 0f), Dg5fPicknPlaceSpec.CubeWidth,
                Dg5fPicknPlaceSpec.CubeHeight));
        }

        [Test]
        public void SpawnsRestOnThePanelTop()
        {
            Vector3 spawn = Dg5fPicknPlaceSpec.SpawnCubeLocalPosition(
                0.5f, 0.3f, Dg5fPicknPlaceSpec.CubeHeight);
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.SupportTopHeight + Dg5fPicknPlaceSpec.CubeHeight * 0.5f,
                spawn.y,
                1e-5f);
        }

        [Test]
        public void SpawnRadiusStaysInsideTheCurrentStageAnnulus()
        {
            Dg5fPicknPlaceSpec.SetGraspStage(1);
            for (int i = 0; i <= 20; i++)
            {
                float radius = Dg5fPicknPlaceSpec.AreaUniformRadius(i / 20f);
                Assert.GreaterOrEqual(radius, Dg5fPicknPlaceSpec.CurrentMinimumSpawnRadius - 1e-5f);
                Assert.LessOrEqual(radius, Dg5fPicknPlaceSpec.CurrentMaximumSpawnRadius + 1e-5f);
            }
        }

        // --- lift -----------------------------------------------------------

        [Test]
        public void LiftPotentialTracksHeightAndSaturatesAtTheTarget()
        {
            Dg5fPicknPlaceSpec.SetGraspStage(Dg5fPicknPlaceSpec.FinalGraspStage);
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.LiftPotential(-0.05f), 1e-6f);
            Assert.Greater(
                Dg5fPicknPlaceSpec.LiftPotential(0.08f),
                Dg5fPicknPlaceSpec.LiftPotential(0.04f));
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.LiftPotentialMaximum,
                Dg5fPicknPlaceSpec.LiftPotential(1f),
                1e-6f);
        }

        [Test]
        public void AFlyingObjectIsNotAStableLift()
        {
            float height = Dg5fPicknPlaceSpec.LiftTargetHeight + 0.01f;
            Assert.IsTrue(Dg5fPicknPlaceSpec.IsStableLift(height, 0.1f));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsStableLift(height, 5f));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsStableLift(0.01f, 0.1f));
        }

        [Test]
        public void LiftHeightIsMeasuredAgainstTheSpawnHeight()
        {
            Assert.AreEqual(0.07f, Dg5fPicknPlaceSpec.LiftHeight(0.37f, 0.30f), 1e-5f);
            Assert.AreEqual(-0.02f, Dg5fPicknPlaceSpec.LiftHeight(0.28f, 0.30f), 1e-5f);
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.LiftHeight(float.NaN, 0.3f));
        }

        // --- toppling / termination -----------------------------------------

        [Test]
        public void ToppleLimitMatchesGraspLiftsCubeScaleDefault()
        {
            // This task grasps a generic cube (not fragile wafer cargo), so it
            // should use the same tolerance GraspLift validated.
            Assert.AreEqual(45f, Dg5fPicknPlaceSpec.ToppleLimitDegrees, 1e-6f);
        }

        [Test]
        public void EpisodeTimesOutAtTheContractedLimit()
        {
            Assert.IsFalse(Dg5fPicknPlaceSpec.ReachedEpisodeTimeout(
                Dg5fPicknPlaceSpec.EpisodeTimeoutSeconds - 1f));
            Assert.IsTrue(Dg5fPicknPlaceSpec.ReachedEpisodeTimeout(
                Dg5fPicknPlaceSpec.EpisodeTimeoutSeconds));
        }

        [Test]
        public void FailurePenaltiesAreOrderedBySeverity()
        {
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.UnsafeSurfacePenalty,
                Dg5fPicknPlaceSpec.FailurePenalty("UnsafeSurfaceContact"));
            Assert.AreEqual(
                Dg5fPicknPlaceSpec.DropPenalty, Dg5fPicknPlaceSpec.FailurePenalty("Dropped"));
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.FailurePenalty("Timeout"));
            Assert.Less(
                Dg5fPicknPlaceSpec.FailurePenalty("UnsafeSurfaceContact"),
                Dg5fPicknPlaceSpec.FailurePenalty("Dropped"));
        }

        // --- numeric hygiene --------------------------------------------------

        [Test]
        public void NonFiniteInputsNeverProduceNonFiniteRewards()
        {
            float nan = float.NaN;
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.PotentialDelta(nan, 1f));
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.NewBestPotentialDelta(1f, nan));
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.NearObjectActionPenalty(nan));
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.LiftProgress(nan));
            Assert.AreEqual(0f, Dg5fPicknPlaceSpec.GraspProgress(nan));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsGraspConfirmed(nan));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsLiftComplete(nan));
            Assert.IsFalse(Dg5fPicknPlaceSpec.IsTopDownAligned(nan));
        }
    }
}
