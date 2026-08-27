using System.Collections;
using System.Linq;
using KDT.PicknPlaceTraining;
using NUnit.Framework;
using Unity.MLAgents;
using Unity.MLAgents.Policies;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace KDT.PicknPlaceTraining.PlayModeTests
{
    /// <summary>
    /// Scene contract for the generated DG5F_PicknPlaceTraining scene: a cube
    /// (grasp object) spawned at a random floor position on the UR16e right-hand
    /// robot — a near-verbatim port of GraspLift's scene contract.
    /// </summary>
    public sealed class PicknPlaceSceneTests
    {
        const string SceneName = "DG5F_PicknPlaceTraining";

        static IEnumerator LoadScene(bool waitForSettling = true)
        {
            SceneManager.LoadScene(SceneName);
            yield return null;
            if (!waitForSettling) yield break;
            // Let the agents resolve, reset, and release their cubes (the release
            // happens two fixed steps after OnEpisodeBegin).
            for (int i = 0; i < 8; i++) yield return new WaitForFixedUpdate();
        }

        [UnityTest]
        public IEnumerator SceneHasTwentyIndependentTrainingAreas()
        {
            yield return LoadScene();

            var agents = Object.FindObjectsByType<Dg5fPicknPlaceAgent>(FindObjectsSortMode.None);
            Assert.That(agents, Has.Length.EqualTo(20));
            Assert.That(agents.Select(a => a.transform.root).Distinct().Count(), Is.EqualTo(20));
            Assert.That(agents.Select(a => a.cubeTarget).Distinct().Count(), Is.EqualTo(20));
            Assert.That(agents.Select(a => a.pedestal).Distinct().Count(), Is.EqualTo(20));
            Assert.That(agents.Select(a => a.spawnSeed).Distinct().Count(), Is.EqualTo(20));

            foreach (var agent in agents)
            {
                Transform area = agent.transform.root;
                Assert.That(agent.cubeTarget.transform.IsChildOf(area), Is.True,
                    "each area must own its own cube");
                Assert.That(agent.pedestal.IsChildOf(area), Is.True);
                var behavior = agent.GetComponent<BehaviorParameters>();
                Assert.That(behavior, Is.Not.Null, $"{area.name} must have behavior parameters");
                Assert.That(behavior.BehaviorName, Is.EqualTo(Dg5fPicknPlaceSpec.BehaviorName));
                Assert.That(behavior.DeterministicInference, Is.True,
                    $"{area.name} must use deterministic inference");
            }
        }

        [UnityTest]
        public IEnumerator BehaviorParametersMatchTheSpecShape()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            var behavior = agent.GetComponent<BehaviorParameters>();
            Assert.That(behavior.BrainParameters.VectorObservationSize,
                Is.EqualTo(Dg5fPicknPlaceSpec.ObservationSize));
            Assert.That(behavior.BrainParameters.NumStackedVectorObservations, Is.EqualTo(1));
            Assert.That(behavior.BrainParameters.ActionSpec.NumContinuousActions,
                Is.EqualTo(Dg5fPicknPlaceSpec.ActionSize));
            Assert.That(behavior.BrainParameters.ActionSpec.NumDiscreteActions, Is.EqualTo(0));
            Assert.That(agent.GetComponent<DecisionRequester>().DecisionPeriod, Is.EqualTo(5));
            Assert.That(agent.MaxStep, Is.EqualTo(0),
                "episode length is measured in simulation seconds, not agent steps");
        }

        [UnityTest]
        public IEnumerator CubeUsesTheDocumentedPhysicsSetup()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            Rigidbody cube = agent.cubeTarget;
            Assert.That(cube.mass, Is.EqualTo(Dg5fPicknPlaceSpec.CurrentCubeMass).Within(1e-6f));
            Assert.That(cube.useGravity, Is.True);
            Assert.That(cube.isKinematic, Is.False, "the cube must be released after reset");
            Assert.That(cube.collisionDetectionMode,
                Is.EqualTo(CollisionDetectionMode.ContinuousDynamic),
                "fast-closing fingers tunnel through a discrete-detection cube");

            Collider collider = cube.GetComponent<Collider>();
            Assert.That(collider, Is.TypeOf<BoxCollider>());
            // Measure the box itself, not its world AABB: the cube spawns with a
            // random yaw, so the axis-aligned bounds are wider than the box.
            var box = (BoxCollider)collider;
            Vector3 size = Vector3.Scale(box.size, cube.transform.lossyScale);
            Assert.That(size.x, Is.EqualTo(Dg5fPicknPlaceSpec.CurrentCubeWidth).Within(2e-3f));
            Assert.That(size.y, Is.EqualTo(Dg5fPicknPlaceSpec.CurrentCubeHeight).Within(2e-3f));
            Assert.That(size.z, Is.EqualTo(Dg5fPicknPlaceSpec.CurrentCubeWidth).Within(2e-3f));
            Assert.That(collider.material.staticFriction, Is.GreaterThan(1f),
                "the cube needs high friction for a friction grasp to hold");
        }

        [UnityTest]
        public IEnumerator CubeSpawnsUprightAndRestingOnThePanel()
        {
            // This is a spawn-geometry contract. Inspect the reset pose before the
            // two-step release, physics settling, or a policy decision can alter it.
            yield return LoadScene(waitForSettling: false);

            foreach (var agent in Object.FindObjectsByType<Dg5fPicknPlaceAgent>(
                         FindObjectsSortMode.None))
            {
                Vector3 local = agent.CurrentObjectLocalPosition;
                Assert.That(
                    Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                        local, Dg5fPicknPlaceSpec.CurrentCubeWidth, Dg5fPicknPlaceSpec.CurrentCubeHeight),
                    Is.True,
                    $"invalid spawn {local}");
                float tilt = Vector3.Angle(agent.cubeTarget.transform.up, Vector3.up);
                Assert.That(tilt, Is.LessThan(2f), "the cube must start upright");
            }
        }

        [UnityTest]
        public IEnumerator ContactSensorsCoverEveryFingertipAndThePalmAgainstTheCube()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            Assert.That(agent.contactSensors, Is.Not.Empty);
            for (int index = 0; index < Dg5fPicknPlaceSpec.ContactPointCount; index++)
            {
                var forIndex = agent.contactSensors
                    .Where(sensor => sensor != null && sensor.contactIndex == index)
                    .ToArray();
                Assert.That(forIndex, Is.Not.Empty, $"contact point {index} is uninstrumented");
                Assert.That(forIndex.All(sensor => sensor.targetCollider == agent.cubeCollider), Is.True);
            }
        }

        [UnityTest]
        public IEnumerator PanelSafetySensorsSkipTheHand()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            Assert.That(agent.safetySensors, Is.Not.Empty);
            foreach (var sensor in agent.safetySensors)
            {
                Assert.That(sensor.unsafeSurfaces, Does.Contain(agent.pedestalCollider));
                for (Transform t = sensor.transform; t != null; t = t.parent)
                {
                    Assert.That(t.name.Contains("_dg_"), Is.False,
                        "fingers must be free to work at the floor surface");
                }
            }
        }
    }
}
