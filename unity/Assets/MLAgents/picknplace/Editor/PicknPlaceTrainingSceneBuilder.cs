using System;
using System.Collections.Generic;
using System.Linq;
using KDT.PicknPlaceTraining;
using Unity.InferenceEngine;
using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Policies;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Regenerates the DG5F grasp + lift training scene from the robot prefab.
    /// The scene is a build artefact: never hand-edit it, re-run this menu item.
    ///
    /// Each training area contains: the robot, the floor panel, and a cube spawned
    /// at a random floor position (the grasp object) — a near-verbatim port of
    /// GraspLift's scene layout onto the confirmed UR16e + right-hand hardware.
    /// See docs/DG5F_PICKNPLACE.md for the full design rationale.
    /// </summary>
    public static class PicknPlaceTrainingSceneBuilder
    {
        const string SourceRobotPath = "Assets/Robots/Prefabs/ur16e_dg5f_right.prefab";
        const string TrainingRoot = "Assets/MLAgents/picknplace";
        const string TrainingPrefabPath = TrainingRoot + "/PicknPlaceTrainingArea.prefab";
        const string TrainingScenePath = TrainingRoot + "/DG5F_PicknPlaceTraining.unity";
        const string DeployedModelPath = TrainingRoot + "/Models/DG5FPicknPlace.onnx";
        const string CubeMaterialPath = TrainingRoot + "/PicknPlaceCube.mat";
        const string PanelPhysicsMaterialPath = TrainingRoot + "/PicknPlacePanel.physicMaterial";
        const string CubePhysicsMaterialPath = TrainingRoot + "/PicknPlaceCube.physicMaterial";
        // Raised from 20 (2026-08-27): the RTX 2080 was sitting at ~17% GPU
        // utilization with 20 areas — environment throughput (CPU-bound Unity
        // physics), not the PPO update, was the bottleneck. More parallel areas
        // feed more experience per second into the same GPU update, without
        // changing the learning algorithm itself. 12 WSL2 CPU cores had ample
        // headroom at 20 areas.
        const int TrainingAreaCount = 40;
        const int TrainingAreaColumns = 8;
        const float TrainingAreaSpacing = 3f;

        static readonly HashSet<string> CompetingDriverTypes = new HashSet<string>
        {
            "Dg5fReceiver",
            "Dg5fHandDriver",
            "Dg5fFingerIK",
            "Dg5fThumbIK",
            "Dg5fJointLogger",
            "HandSliderUI",
            "ArmTargetIK",
            "RobotInitialPoseSync",
            "Dg5fGraspAgent",
            "GraspTeleoperationHandoff",
            // Unity.Robotics.UrdfImporter.Control.Controller: the URDF-Importer
            // package's own demo keyboard controller. It ships on the imported
            // robot and calls the legacy UnityEngine.Input API every Update(),
            // which throws (the project uses the new Input System) and spams the
            // log at simulation rate across all 20 training areas — found while
            // smoke-testing the headless Linux player (2026-08-27). Harmless to
            // training itself (it never got a chance to drive joints — Dg5fPicknPlaceAgent
            // is the sole xDrive writer regardless), but wasteful over a
            // multi-hour headless run.
            "Controller"
        };

        [MenuItem("Tools/ML-Agents/Build DG5F PicknPlace Training Scene")]
        public static void Build()
        {
            EnsureFolder(TrainingRoot);
            var sourceRobot = AssetDatabase.LoadAssetAtPath<GameObject>(SourceRobotPath);
            if (sourceRobot == null)
                throw new InvalidOperationException(
                    $"Missing robot prefab: {SourceRobotPath}. Run "
                    + "\"Tools/Robots/Create UR16e DG5F Right Prefab\" first.");

            Scene scene = EditorSceneManager.NewScene(
                NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            scene.name = "DG5F_PicknPlaceTraining";

            var area = new GameObject("DG5F_PicknPlaceTrainingArea");
            var robot = (GameObject)PrefabUtility.InstantiatePrefab(sourceRobot, area.transform);
            robot.name = "UR16e_DG5F_PicknPlaceAgent";
            robot.transform.SetLocalPositionAndRotation(
                Vector3.up * Dg5fPicknPlaceSpec.PanelThickness,
                Quaternion.identity);
            DisableCompetingDrivers(robot);
            ConfigureJointDrives(robot);

            GameObject pedestal = CreatePanel(area.transform, GetOrCreatePanelPhysicsMaterial());
            Rigidbody cube = CreateCube(area.transform, GetOrCreateCubePhysicsMaterial());

            Transform palm = FindTransform(robot, "rl_dg_palm");
            var tips = new Transform[Dg5fPicknPlaceSpec.FingerCount];
            for (int finger = 0; finger < tips.Length; finger++)
                tips[finger] = FindTransform(robot, $"rl_dg_{finger + 1}_tip");
            Transform graspPoint = CreateGraspPoint(palm);

            var agent = robot.GetComponent<Dg5fPicknPlaceAgent>();
            if (agent == null) agent = robot.AddComponent<Dg5fPicknPlaceAgent>();
            agent.cubeTarget = cube;
            agent.cubeCollider = cube.GetComponent<Collider>();
            agent.pedestal = pedestal.transform;
            agent.pedestalCollider = pedestal.GetComponent<Collider>();
            agent.robotBase = robot.transform;
            agent.palm = palm;
            agent.graspPoint = graspPoint;
            agent.fingerTips = tips;
            agent.contactSensors = ConfigureObjectContactSensors(palm, tips, agent.cubeCollider);
            Collider panelCollider = pedestal.GetComponent<Collider>();
            var unsafeSurfaces = new[] { panelCollider };
            agent.safetySensors = ConfigureSafetySensors(robot, unsafeSurfaces, agent);
            agent.handSurfaceSensors = ConfigureHandSurfaceSensors(robot, panelCollider);
            agent.selfCollisionSensors = ConfigureSelfCollisionSensors(robot);
            agent.MaxStep = 0;

            var behavior = robot.GetComponent<BehaviorParameters>();
            if (behavior == null) behavior = robot.AddComponent<BehaviorParameters>();
            behavior.BehaviorName = Dg5fPicknPlaceSpec.BehaviorName;
            behavior.BehaviorType = BehaviorType.Default;
            var deployedModel = AssetDatabase.LoadAssetAtPath<ModelAsset>(DeployedModelPath);
            behavior.Model = deployedModel;
            if (deployedModel == null)
            {
                Debug.LogWarning(
                    $"[PicknPlaceTrainingSceneBuilder] Missing deployed model: {DeployedModelPath} "
                    + "(expected until the first training run finishes).");
            }
            behavior.DeterministicInference = true;
            behavior.BrainParameters.VectorObservationSize = Dg5fPicknPlaceSpec.ObservationSize;
            behavior.BrainParameters.NumStackedVectorObservations = 1;
            behavior.BrainParameters.ActionSpec =
                ActionSpec.MakeContinuous(Dg5fPicknPlaceSpec.ActionSize);
            behavior.BrainParameters.VectorActionDescriptions = new[]
            {
                "shoulder_pan_delta", "shoulder_lift_delta", "elbow_delta",
                "wrist_1_delta", "wrist_2_delta", "wrist_3_delta",
                "hand_closure_delta"
            };

            var requester = robot.GetComponent<DecisionRequester>();
            if (requester == null) requester = robot.AddComponent<DecisionRequester>();
            requester.DecisionPeriod = 5;
            requester.TakeActionsBetweenDecisions = false;

            PrefabUtility.SaveAsPrefabAssetAndConnect(
                area, TrainingPrefabPath, InteractionMode.AutomatedAction);
            PopulateTrainingAreas(area);
            ConfigureCamera(LayoutCenter());
            Selection.activeGameObject = area;

            EditorSceneManager.SaveScene(scene, TrainingScenePath);
            AddSceneToBuildSettings(TrainingScenePath);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Debug.Log(
                $"[PicknPlaceTrainingSceneBuilder] Built {TrainingPrefabPath} and {TrainingScenePath}");
        }

        static void PopulateTrainingAreas(GameObject firstArea)
        {
            GameObject trainingPrefab =
                AssetDatabase.LoadAssetAtPath<GameObject>(TrainingPrefabPath);
            if (trainingPrefab == null)
                throw new InvalidOperationException(
                    $"Missing generated training prefab: {TrainingPrefabPath}");

            ConfigureTrainingAreaInstance(firstArea, 0);
            for (int index = 1; index < TrainingAreaCount; index++)
            {
                var instance = (GameObject)PrefabUtility.InstantiatePrefab(trainingPrefab);
                ConfigureTrainingAreaInstance(instance, index);
            }
        }

        static void ConfigureTrainingAreaInstance(GameObject area, int index)
        {
            int row = index / TrainingAreaColumns;
            int column = index % TrainingAreaColumns;
            area.name = $"DG5F_PicknPlaceTrainingArea_{index:00}";
            area.transform.SetPositionAndRotation(
                new Vector3(column * TrainingAreaSpacing, row * TrainingAreaSpacing, 0f),
                Quaternion.identity);

            var agent = area.GetComponentInChildren<Dg5fPicknPlaceAgent>(true);
            if (agent == null)
                throw new InvalidOperationException(
                    $"Training area {index} has no {nameof(Dg5fPicknPlaceAgent)}.");
            agent.spawnSeed = 12345 + index;
        }

        static Vector3 LayoutCenter()
        {
            int rows = Mathf.CeilToInt((float)TrainingAreaCount / TrainingAreaColumns);
            return new Vector3(
                (TrainingAreaColumns - 1) * TrainingAreaSpacing * 0.5f,
                (rows - 1) * TrainingAreaSpacing * 0.5f,
                0f);
        }

        static void DisableCompetingDrivers(GameObject robot)
        {
            foreach (var behaviour in robot.GetComponents<MonoBehaviour>())
                if (behaviour != null && CompetingDriverTypes.Contains(behaviour.GetType().Name))
                    behaviour.enabled = false;
        }

        static void ConfigureJointDrives(GameObject robot)
        {
            foreach (var body in robot.GetComponentsInChildren<ArticulationBody>(true))
            {
                if (body.jointType != ArticulationJointType.RevoluteJoint) continue;
                var drive = body.xDrive;
                bool hand = body.name.Contains("_dg_");
                if (hand)
                {
                    drive.stiffness = 1500f;
                    drive.damping = 120f;
                    drive.forceLimit = 20f;
                }
                else
                {
                    drive.stiffness = Dg5fPicknPlaceSpec.ArmDriveStiffness;
                    drive.damping = Dg5fPicknPlaceSpec.ArmDriveDamping;
                    drive.forceLimit =
                        body.name.StartsWith("wrist_", StringComparison.Ordinal) ? 28f : 150f;
                }
                body.xDrive = drive;
                body.useGravity = false;
            }
        }

        static PicknPlaceObjectContactSensor[] ConfigureObjectContactSensors(
            Transform palm, Transform[] tips, Collider cubeCollider)
        {
            var sensors = new List<PicknPlaceObjectContactSensor>();
            for (int finger = 0; finger < tips.Length; finger++)
                AddContactSensors(tips[finger], finger, cubeCollider, sensors);
            AddContactSensors(palm, Dg5fPicknPlaceSpec.PalmContactIndex, cubeCollider, sensors);

            for (int index = 0; index < Dg5fPicknPlaceSpec.ContactPointCount; index++)
            {
                if (!sensors.Any(sensor => sensor.contactIndex == index))
                    throw new InvalidOperationException(
                        $"Contact point {index} has no collider to instrument.");
            }
            return sensors.ToArray();
        }

        static void AddContactSensors(
            Transform link, int contactIndex, Collider cubeCollider,
            List<PicknPlaceObjectContactSensor> sensors)
        {
            if (link == null)
                throw new InvalidOperationException(
                    $"Contact point {contactIndex} has no link transform.");

            var targets = new List<GameObject> { link.gameObject };
            Transform collisions = link.Find("Collisions");
            if (collisions != null)
            {
                foreach (Collider collider in collisions.GetComponentsInChildren<Collider>(true))
                {
                    if (collider == null || collider.isTrigger) continue;
                    targets.Add(collider.gameObject);
                }
            }
            if (targets.Count < 2)
                throw new InvalidOperationException(
                    $"Contact point {contactIndex} ({link.name}) has no collision geometry.");

            foreach (GameObject target in targets)
            {
                var sensor = target.GetComponent<PicknPlaceObjectContactSensor>();
                if (sensor == null)
                    sensor = target.AddComponent<PicknPlaceObjectContactSensor>();
                sensor.contactIndex = contactIndex;
                sensor.targetCollider = cubeCollider;
                sensors.Add(sensor);
            }
        }

        static PicknPlaceSurfaceContactSensor[] ConfigureSafetySensors(
            GameObject robot, Collider[] unsafeSurfaces, Dg5fPicknPlaceAgent agent)
        {
            var sensors = new List<PicknPlaceSurfaceContactSensor>();
            foreach (Collider collider in robot.GetComponentsInChildren<Collider>(true))
            {
                if (collider == null || !collider.enabled || collider.isTrigger) continue;
                ArticulationBody body = collider.GetComponentInParent<ArticulationBody>();
                if (body == null || body.isRoot) continue;
                if (IsHandCollider(collider.transform)) continue;

                var sensor = collider.GetComponent<PicknPlaceSurfaceContactSensor>();
                if (sensor == null)
                    sensor = collider.gameObject.AddComponent<PicknPlaceSurfaceContactSensor>();
                sensor.agent = agent;
                sensor.unsafeSurfaces = unsafeSurfaces;
                sensors.Add(sensor);
            }
            if (sensors.Count == 0)
                throw new InvalidOperationException(
                    "No moving arm colliders were available for surface safety.");
            return sensors.ToArray();
        }

        static bool IsHandCollider(Transform colliderTransform)
        {
            for (Transform current = colliderTransform; current != null; current = current.parent)
            {
                if (current.name.Contains("_dg_") || current.name == "rl_dg_mount")
                    return true;
            }
            return false;
        }

        static PicknPlaceHandSurfaceSensor[] ConfigureHandSurfaceSensors(
            GameObject robot, Collider panel)
        {
            var targets = new HashSet<GameObject>();
            foreach (Collider collider in robot.GetComponentsInChildren<Collider>(true))
            {
                if (collider == null || !collider.enabled || collider.isTrigger) continue;
                ArticulationBody body = collider.GetComponentInParent<ArticulationBody>();
                if (body == null || body.isRoot || !IsHandCollider(collider.transform)) continue;

                targets.Add(body.gameObject);
                targets.Add(collider.gameObject);
            }

            if (targets.Count == 0)
                throw new InvalidOperationException(
                    "No hand colliders were available for panel contact reporting.");

            var sensors = new List<PicknPlaceHandSurfaceSensor>(targets.Count);
            foreach (GameObject target in targets)
            {
                var sensor = target.GetComponent<PicknPlaceHandSurfaceSensor>();
                if (sensor == null)
                    sensor = target.AddComponent<PicknPlaceHandSurfaceSensor>();
                sensor.surface = panel;
                sensors.Add(sensor);
            }
            return sensors.ToArray();
        }

        /// Instruments every physical robot collider with a same-shaped trigger
        /// "shadow" so PicknPlaceSelfCollisionSensor can detect real geometric
        /// overlap between non-adjacent links without touching physics response —
        /// see that component's doc comment for why this can't reuse
        /// RobotSelfCollisionIgnore's ignore-pair table.
        static PicknPlaceSelfCollisionSensor[] ConfigureSelfCollisionSensors(GameObject robot)
        {
            var sensors = new List<PicknPlaceSelfCollisionSensor>();
            foreach (Collider collider in robot.GetComponentsInChildren<Collider>(true))
            {
                if (collider == null || collider.isTrigger) continue;
                ArticulationBody body = collider.GetComponentInParent<ArticulationBody>();
                if (body == null || body.isRoot) continue;

                AddTriggerShadow(collider.gameObject, collider);
                var sensor = collider.gameObject.GetComponent<PicknPlaceSelfCollisionSensor>();
                if (sensor == null)
                    sensor = collider.gameObject.AddComponent<PicknPlaceSelfCollisionSensor>();
                sensor.owningBody = body;
                sensors.Add(sensor);
            }
            if (sensors.Count == 0)
                throw new InvalidOperationException(
                    "No robot colliders were available for self-collision detection.");
            return sensors.ToArray();
        }

        /// Adds a same-shaped trigger-only collider alongside an existing physical
        /// one on the same GameObject. Handles the collider primitive types the
        /// URDF importer produces; throws on anything unexpected so a new/unusual
        /// collision-geometry type fails loudly at build time rather than silently
        /// leaving a gap in self-collision coverage.
        static void AddTriggerShadow(GameObject target, Collider source)
        {
            switch (source)
            {
                case BoxCollider box:
                {
                    var shadow = target.AddComponent<BoxCollider>();
                    shadow.center = box.center;
                    shadow.size = box.size;
                    shadow.isTrigger = true;
                    break;
                }
                case SphereCollider sphere:
                {
                    var shadow = target.AddComponent<SphereCollider>();
                    shadow.center = sphere.center;
                    shadow.radius = sphere.radius;
                    shadow.isTrigger = true;
                    break;
                }
                case CapsuleCollider capsule:
                {
                    var shadow = target.AddComponent<CapsuleCollider>();
                    shadow.center = capsule.center;
                    shadow.radius = capsule.radius;
                    shadow.height = capsule.height;
                    shadow.direction = capsule.direction;
                    shadow.isTrigger = true;
                    break;
                }
                case MeshCollider mesh:
                {
                    var shadow = target.AddComponent<MeshCollider>();
                    shadow.sharedMesh = mesh.sharedMesh;
                    // Trigger mesh colliders must be convex in PhysX.
                    shadow.convex = true;
                    shadow.isTrigger = true;
                    break;
                }
                default:
                    throw new InvalidOperationException(
                        $"Unsupported collider type for self-collision shadow: {source.GetType().Name} "
                        + $"on {target.name}.");
            }
        }

        static GameObject CreatePanel(Transform parent, PhysicsMaterial material)
        {
            var panel = GameObject.CreatePrimitive(PrimitiveType.Cube);
            panel.name = "PicknPlacePanel";
            panel.transform.SetParent(parent, false);
            panel.transform.SetLocalPositionAndRotation(
                Vector3.up * Dg5fPicknPlaceSpec.PanelThickness * 0.5f,
                Quaternion.identity);
            panel.transform.localScale = new Vector3(
                Dg5fPicknPlaceSpec.PanelWidth,
                Dg5fPicknPlaceSpec.PanelThickness,
                Dg5fPicknPlaceSpec.PanelDepth);
            panel.GetComponent<BoxCollider>().material = material;
            return panel;
        }

        /// The pick object: a plain cube, geometrically identical to GraspLift's
        /// block so its proven grasp contract transfers unchanged.
        static Rigidbody CreateCube(Transform parent, PhysicsMaterial material)
        {
            var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.name = "PicknPlaceCube";
            cube.transform.SetParent(parent, false);
            // Placeholder initial pose; Dg5fPicknPlaceAgent samples a fresh random
            // spawn at every episode reset.
            cube.transform.localPosition = new Vector3(
                -0.40f,
                Dg5fPicknPlaceSpec.PanelThickness + Dg5fPicknPlaceSpec.CurrentCubeHalfHeight,
                0.25f);
            cube.transform.localScale = new Vector3(
                Dg5fPicknPlaceSpec.CurrentCubeWidth,
                Dg5fPicknPlaceSpec.CurrentCubeHeight,
                Dg5fPicknPlaceSpec.CurrentCubeWidth);
            cube.GetComponent<Collider>().material = material;
            cube.GetComponent<Renderer>().sharedMaterial = GetOrCreateCubeMaterial();

            var body = cube.AddComponent<Rigidbody>();
            body.mass = Dg5fPicknPlaceSpec.CurrentCubeMass;
            body.centerOfMass = Dg5fPicknPlaceSpec.CurrentCubeCenterOfMassLocal;
            body.useGravity = true;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            body.interpolation = RigidbodyInterpolation.None;
            return body;
        }

        static Transform CreateGraspPoint(Transform palm)
        {
            Transform existing = palm.Find("GraspPoint");
            if (existing != null) UnityEngine.Object.DestroyImmediate(existing.gameObject);

            var grasp = new GameObject("GraspPoint").transform;
            grasp.SetParent(palm, false);
            grasp.localPosition = Dg5fPicknPlaceSpec.FullHandGraspPointLocalPosition;
            grasp.localRotation = Quaternion.identity;
            return grasp;
        }

        static Transform FindTransform(GameObject root, string name)
        {
            Transform found = root.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(item => item.name == name);
            if (found == null) throw new InvalidOperationException($"Missing transform: {name}");
            return found;
        }

        static PhysicsMaterial GetOrCreatePanelPhysicsMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>(PanelPhysicsMaterialPath);
            if (material != null) return material;
            material = new PhysicsMaterial("PicknPlacePanel")
            {
                dynamicFriction = 0.8f,
                staticFriction = 0.8f,
                bounciness = 0f,
                frictionCombine = PhysicsMaterialCombine.Average,
                bounceCombine = PhysicsMaterialCombine.Minimum
            };
            AssetDatabase.CreateAsset(material, PanelPhysicsMaterialPath);
            return material;
        }

        static PhysicsMaterial GetOrCreateCubePhysicsMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>(CubePhysicsMaterialPath);
            if (material != null) return material;
            // High friction (Maximum combine), mirroring GraspLift's block
            // material, so a good grasp holds through friction.
            material = new PhysicsMaterial("PicknPlaceCube")
            {
                dynamicFriction = 1.2f,
                staticFriction = 1.5f,
                bounciness = 0f,
                frictionCombine = PhysicsMaterialCombine.Maximum,
                bounceCombine = PhysicsMaterialCombine.Minimum
            };
            AssetDatabase.CreateAsset(material, CubePhysicsMaterialPath);
            return material;
        }

        static Material GetOrCreateCubeMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(CubeMaterialPath);
            if (material != null) return material;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            material = new Material(shader) { name = "PicknPlaceCube", color = Color.red };
            AssetDatabase.CreateAsset(material, CubeMaterialPath);
            return material;
        }

        static void ConfigureCamera(Vector3 focus)
        {
            Camera camera = UnityEngine.Object.FindAnyObjectByType<Camera>();
            if (camera == null) return;
            camera.transform.position = focus + Vector3.back * 18f;
            camera.transform.LookAt(focus);
        }

        static void AddSceneToBuildSettings(string scenePath)
        {
            var scenes = EditorBuildSettings.scenes.ToList();
            if (scenes.All(item => item.path != scenePath))
                scenes.Add(new EditorBuildSettingsScene(scenePath, true));
            EditorBuildSettings.scenes = scenes.ToArray();
        }

        static void EnsureFolder(string path)
        {
            string[] parts = path.Split('/');
            string current = parts[0];
            for (int i = 1; i < parts.Length; i++)
            {
                string next = current + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next)) AssetDatabase.CreateFolder(current, parts[i]);
                current = next;
            }
        }
    }
}
