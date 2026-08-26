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
    /// (pick object) spawned at a random floor position, and a fixed FOUP-shaped
    /// platform (place target) with a randomized marker on its top face.
    /// </summary>
    public sealed class PicknPlaceSceneTests
    {
        const string SceneName = "DG5F_PicknPlaceTraining";

        static IEnumerator LoadScene(bool waitForSettling = true)
        {
            SceneManager.LoadScene(SceneName);
            yield return null;
            if (!waitForSettling) yield break;
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
            Assert.That(agents.Select(a => a.platform).Distinct().Count(), Is.EqualTo(20));
            Assert.That(agents.Select(a => a.pedestal).Distinct().Count(), Is.EqualTo(20));
            Assert.That(agents.Select(a => a.spawnSeed).Distinct().Count(), Is.EqualTo(20));

            foreach (var agent in agents)
            {
                Transform area = agent.transform.root;
                Assert.That(agent.cubeTarget.transform.IsChildOf(area), Is.True,
                    "each area must own its own cube");
                Assert.That(agent.platform.IsChildOf(area), Is.True,
                    "each area must own its own platform");
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
                Is.EqualTo(CollisionDetectionMode.ContinuousDynamic));

            Collider collider = cube.GetComponent<Collider>();
            Assert.That(collider, Is.TypeOf<BoxCollider>());
            Assert.That(collider.material.staticFriction, Is.GreaterThan(1f),
                "the cube needs high friction for a friction grasp to hold");
        }

        [UnityTest]
        public IEnumerator PlatformIsStaticAndHasNoRigidbody()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            Assert.That(agent.platform.GetComponent<Rigidbody>(), Is.Null,
                "the landing platform must be a fixed, static object");
            Assert.That(agent.platformCollider, Is.Not.Null);
            Assert.That(agent.platformCollider, Is.TypeOf<BoxCollider>());

            var expectedWorldPos =
                agent.robotBase.TransformPoint(Dg5fPicknPlaceSpec.PlatformLocalPosition);
            Assert.That(
                Vector3.Distance(agent.platform.position, expectedWorldPos), Is.LessThan(1e-4f),
                "the platform must sit at the documented fixed position");
        }

        [UnityTest]
        public IEnumerator CubeSpawnsUprightAndClearOfThePlatform()
        {
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
        public IEnumerator SafetySensorsCoverBothPanelAndPlatformButSkipTheHand()
        {
            yield return LoadScene();

            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            Assert.That(agent.safetySensors, Is.Not.Empty);
            foreach (var sensor in agent.safetySensors)
            {
                Assert.That(sensor.unsafeSurfaces, Does.Contain(agent.pedestalCollider));
                Assert.That(sensor.unsafeSurfaces, Does.Contain(agent.platformCollider));
                for (Transform t = sensor.transform; t != null; t = t.parent)
                {
                    Assert.That(t.name.Contains("_dg_"), Is.False,
                        "fingers must be free to work at the floor/platform surface");
                }
            }
        }
    }
}
