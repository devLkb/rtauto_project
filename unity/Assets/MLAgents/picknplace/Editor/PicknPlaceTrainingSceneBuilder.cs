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
    /// Regenerates the DG5F pick-and-place training scene from the robot prefab.
    /// The scene is a build artefact: never hand-edit it, re-run this menu item.
    ///
    /// Each training area contains: the robot, the floor panel, a cube spawned at
    /// a random floor position (the pick object), and a fixed FOUP-shaped landing
    /// platform with a randomized marker on its top face (the place target). See
    /// docs/DG5F_PICKNPLACE.md for the full design rationale.
    /// </summary>
    public static class PicknPlaceTrainingSceneBuilder
    {
        const string SourceRobotPath = "Assets/Robots/Prefabs/ur16e_dg5f_right.prefab";
        const string TrainingRoot = "Assets/MLAgents/picknplace";
        const string TrainingPrefabPath = TrainingRoot + "/PicknPlaceTrainingArea.prefab";
        const string TrainingScenePath = TrainingRoot + "/DG5F_PicknPlaceTraining.unity";
        const string DeployedModelPath = TrainingRoot + "/Models/DG5FPicknPlace.onnx";
        const string CubeMaterialPath = TrainingRoot + "/PicknPlaceCube.mat";
        const string PlatformBodyMaterialPath = TrainingRoot + "/PicknPlacePlatformBody.mat";
        const string PlatformHandleMaterialPath = TrainingRoot + "/PicknPlacePlatformHandle.mat";
        const string MarkerMaterialPath = TrainingRoot + "/PicknPlaceMarker.mat";
        const string PanelPhysicsMaterialPath = TrainingRoot + "/PicknPlacePanel.physicMaterial";
        const string CubePhysicsMaterialPath = TrainingRoot + "/PicknPlaceCube.physicMaterial";
        const string PlatformPhysicsMaterialPath = TrainingRoot + "/PicknPlacePlatform.physicMaterial";
        const int TrainingAreaCount = 20;
        const int TrainingAreaColumns = 4;
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
            "GraspTeleoperationHandoff"
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
            GameObject platformRoot = CreatePlatform(area.transform, GetOrCreatePlatformPhysicsMaterial());
            Transform marker = CreatePlaceMarker(area.transform);

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
            agent.platform = platformRoot.transform;
            agent.platformCollider = platformRoot.GetComponentInChildren<BoxCollider>();
            agent.placeMarkerVisual = marker;
            agent.robotBase = robot.transform;
            agent.palm = palm;
            agent.graspPoint = graspPoint;
            agent.fingerTips = tips;
            agent.contactSensors = ConfigureObjectContactSensors(palm, tips, agent.cubeCollider);
            Collider panelCollider = pedestal.GetComponent<Collider>();
            var unsafeSurfaces = new[] { panelCollider, agent.platformCollider };
            agent.safetySensors = ConfigureSafetySensors(robot, unsafeSurfaces, agent);
            agent.handSurfaceSensors = ConfigureHandSurfaceSensors(robot, panelCollider);
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
                    // Same gains as GraspLift's UR5e setup — UR16e's heavier arm
                    // has not been retuned against these yet. See
                    // docs/SIM2REAL_ROADMAP.md Phase 2.
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
            // spawn (clear of the platform) at every episode reset.
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

        /// The place target: a fixed, static (no Rigidbody) FOUP-shaped landing
        /// platform — box body + a purely decorative handle bar. Never moves
        /// during an episode; only the marker on top of it is randomized.
        static GameObject CreatePlatform(Transform parent, PhysicsMaterial material)
        {
            var root = new GameObject("PicknPlacePlatform");
            root.transform.SetParent(parent, false);
            root.transform.localPosition = Dg5fPicknPlaceSpec.PlatformLocalPosition;

            var body = GameObject.CreatePrimitive(PrimitiveType.Cube);
            body.name = "PlatformBody";
            body.transform.SetParent(root.transform, false);
            body.transform.localPosition = Vector3.zero;
            body.transform.localScale = new Vector3(
                Dg5fPicknPlaceSpec.PlatformWidth,
                Dg5fPicknPlaceSpec.PlatformHeight,
                Dg5fPicknPlaceSpec.PlatformDepth);
            body.GetComponent<Collider>().material = material;
            body.GetComponent<Renderer>().sharedMaterial = GetOrCreatePlatformBodyMaterial();

            float handleCenterLocalY = Dg5fPicknPlaceSpec.PlatformHalfHeight
                + Dg5fPicknPlaceSpec.PlatformHandleClearanceAboveBody
                + Dg5fPicknPlaceSpec.PlatformHandleDiameter * 0.5f;

            var handleGO = new GameObject("PlatformHandle");
            handleGO.transform.SetParent(root.transform, false);
            handleGO.transform.localPosition = new Vector3(0f, handleCenterLocalY, 0f);
            var capsule = handleGO.AddComponent<CapsuleCollider>();
            capsule.direction = 0; // X axis: the bar spans across the body.
            capsule.radius = Dg5fPicknPlaceSpec.PlatformHandleDiameter * 0.5f;
            capsule.height = Dg5fPicknPlaceSpec.PlatformHandleLength;
            capsule.material = material;

            var handleVisual = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            handleVisual.name = "Visual";
            UnityEngine.Object.DestroyImmediate(handleVisual.GetComponent<Collider>());
            handleVisual.transform.SetParent(handleGO.transform, false);
            handleVisual.transform.localRotation = Quaternion.Euler(0f, 0f, 90f);
            handleVisual.transform.localScale = new Vector3(
                Dg5fPicknPlaceSpec.PlatformHandleDiameter,
                Dg5fPicknPlaceSpec.PlatformHandleLength * 0.5f,
                Dg5fPicknPlaceSpec.PlatformHandleDiameter);
            handleVisual.GetComponent<Renderer>().sharedMaterial = GetOrCreatePlatformHandleMaterial();

            return root;
        }

        /// Purely visual: a thin flat disc with no collider. Dg5fPicknPlaceAgent
        /// repositions it every episode to the freshly randomized marker point.
        static Transform CreatePlaceMarker(Transform parent)
        {
            var marker = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            marker.name = "PlaceMarker";
            UnityEngine.Object.DestroyImmediate(marker.GetComponent<Collider>());
            marker.transform.SetParent(parent, false);
            marker.transform.localScale = new Vector3(
                Dg5fPicknPlaceSpec.CurrentPlacePositionToleranceMeters * 2f,
                0.002f,
                Dg5fPicknPlaceSpec.CurrentPlacePositionToleranceMeters * 2f);
            marker.GetComponent<Renderer>().sharedMaterial = GetOrCreateMarkerMaterial();
            return marker.transform;
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

        static PhysicsMaterial GetOrCreatePlatformPhysicsMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>(PlatformPhysicsMaterialPath);
            if (material != null) return material;
            material = new PhysicsMaterial("PicknPlacePlatform")
            {
                dynamicFriction = 0.8f,
                staticFriction = 0.8f,
                bounciness = 0f,
                frictionCombine = PhysicsMaterialCombine.Average,
                bounceCombine = PhysicsMaterialCombine.Minimum
            };
            AssetDatabase.CreateAsset(material, PlatformPhysicsMaterialPath);
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

        static Material GetOrCreatePlatformBodyMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(PlatformBodyMaterialPath);
            if (material != null) return material;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            material = new Material(shader)
            {
                name = "PicknPlacePlatformBody",
                color = new Color(0.85f, 0.85f, 0.9f)
            };
            AssetDatabase.CreateAsset(material, PlatformBodyMaterialPath);
            return material;
        }

        static Material GetOrCreatePlatformHandleMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(PlatformHandleMaterialPath);
            if (material != null) return material;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            material = new Material(shader)
            {
                name = "PicknPlacePlatformHandle",
                color = new Color(0.5f, 0.5f, 0.55f)
            };
            AssetDatabase.CreateAsset(material, PlatformHandleMaterialPath);
            return material;
        }

        static Material GetOrCreateMarkerMaterial()
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(MarkerMaterialPath);
            if (material != null) return material;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            material = new Material(shader) { name = "PicknPlaceMarker", color = Color.green };
            AssetDatabase.CreateAsset(material, MarkerMaterialPath);
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
