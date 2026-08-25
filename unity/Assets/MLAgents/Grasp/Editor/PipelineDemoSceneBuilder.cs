using System;
using System.Linq;
using Cinemachine;
using Unity.MLAgents.Policies;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace KDT.GraspTraining.Editor
{
    /// <summary>
    /// Builds the single-robot live pipeline scene from the already-trained
    /// DG5FGrasp behavior (57 obs / 7 action, arm + grip closure): duplicates
    /// DG5F_GraspTrainingArea_00 out of the 20-parallel training scene, re-enables
    /// the hand teleop path (Dg5fReceiver/Dg5fHandDriver) that GraspTrainingSceneBuilder
    /// disables for training, and adds a CameraTargetReceiver that feeds the ball's
    /// one-shot spawn position (Dg5fGraspAgent.cameraReceiver) instead of continuously
    /// overwriting a Transform — GraspBall is a real simulated Rigidbody, not a
    /// kinematic marker, so it must stay physics-driven between episode resets.
    /// Dg5fGraspAgent.driveHandJoints is set to false so the trained policy only
    /// actuates the 6 arm joints; the 20 finger joints are left to Dg5fHandDriver.
    /// ArmTargetIK/HandSliderUI/Dg5fFingerIK/Dg5fFingerIKMode/Dg5fIKVectorDebug/
    /// Dg5fThumbIK/RobotInitialPoseSync are force-disabled — some finger-level
    /// instances were found already enabled on the checked-in training area, which
    /// would fight Dg5fHandDriver once hand physics is re-enabled. Also wires an
    /// overview/grasp-close-up Cinemachine camera pair onto the demo scene's Main
    /// Camera (switchable via DemoCameraSwitcher) so the grasp is visible up close
    /// during the live demo.
    /// </summary>
    public static class PipelineDemoSceneBuilder
    {
        public const string SourceScenePath =
            "Assets/MLAgents/Grasp/DG5F_GraspTraining.unity";
        public const string SourceAreaName = "DG5F_GraspTrainingArea_00";
        public const string DemoScenePath = "Assets/Scenes/Pipeline_Demo.unity";
        const string HandRootName = "ll_dg_palm";
        const int CameraReceiverPort = 5007;  // CameraTargetReceiver.cs 기본값과 동일하게 유지 — 유일한 출처는 config/rtauto_config.py(PORT_ZED_TARGET)
        const string CubeMaterialPath = "Assets/MLAgents/Grasp/GraspCube.mat";
        const string CylinderMaterialPath = "Assets/MLAgents/Grasp/GraspCylinder.mat";
        const string OverviewCameraName = "OverviewCamera";
        const string GraspCameraName = "GraspCloseUpCamera";
        const float GraspCameraFieldOfView = 32f;
        const float MinZoomFieldOfView = 15f;
        const float MaxZoomFieldOfView = 120f;
        // Grasp camera starts live (matches what the demo already showed working);
        // the switcher lets the operator cut back to the overview camera.
        const int DefaultLiveCameraIndex = 1;

        // World-space offset (Transposer BindingMode.WorldSpace) so the close-up
        // camera doesn't spin with the wrist as the arm rotates into the grasp.
        static readonly Vector3 GraspCameraFollowOffset = new Vector3(0.4f, 0.3f, -0.4f);

        static readonly string[] HandTeleopTypeNames =
        {
            "Dg5fReceiver",
            "Dg5fHandDriver",
            "Dg5fJointLogger"
        };

        // Must stay disabled: HandSliderUI/ArmTargetIK would fight the RL agent's
        // direct arm xDrive writes, and the finger-level IK scripts would fight
        // Dg5fHandDriver on the same finger joints once hand physics is re-enabled.
        static readonly string[] ForceDisabledTypeNames =
        {
            "ArmTargetIK",
            "HandSliderUI",
            "Dg5fFingerIK",
            "Dg5fFingerIKMode",
            "Dg5fIKVectorDebug",
            "Dg5fThumbIK",
            "RobotInitialPoseSync"
        };

        [MenuItem("Tools/ML-Agents/Build Pipeline Demo Scene")]
        public static void Build()
        {
            Scene sourceScene = EditorSceneManager.OpenScene(
                SourceScenePath,
                OpenSceneMode.Additive);

            GameObject sourceArea = sourceScene.GetRootGameObjects()
                .FirstOrDefault(go => go.name == SourceAreaName);
            if (sourceArea == null)
            {
                EditorSceneManager.CloseScene(sourceScene, true);
                throw new InvalidOperationException(
                    $"'{SourceAreaName}' not found in {SourceScenePath}.");
            }

            GameObject areaCopy = UnityEngine.Object.Instantiate(sourceArea);
            areaCopy.name = SourceAreaName;

            // Additive (not Single) so sourceScene stays loaded until the copy has
            // been moved out of it — closing it first destroys areaCopy along with it.
            Scene demoScene = EditorSceneManager.NewScene(
                NewSceneSetup.DefaultGameObjects,
                NewSceneMode.Additive);
            demoScene.name = "Pipeline_Demo";
            SceneManager.MoveGameObjectToScene(areaCopy, demoScene);

            EditorSceneManager.CloseScene(sourceScene, true);
            EditorSceneManager.SetActiveScene(demoScene);

            // Now that demoScene exists alongside whatever else is loaded, it's
            // always safe to close a stale scene at the same path (never the
            // last loaded scene at this point).
            CloseExistingDemoSceneIfLoaded(demoScene);

            ReEnableHandTeleop(areaCopy);
            CameraTargetReceiver cameraReceiver = ConfigureCameraReceiver(areaCopy);
            ConfigureAgent(areaCopy, cameraReceiver);
            ConfigureGraspCamera(areaCopy, demoScene);
            ConfigureArmTeleopNudge(areaCopy);
            ConfigureTargetVariety(areaCopy);
            SetInferenceOnly(areaCopy);

            EnsureFolder("Assets/Scenes");
            if (!EditorSceneManager.SaveScene(demoScene, DemoScenePath))
                throw new InvalidOperationException($"Failed to save {DemoScenePath}.");
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Selection.activeGameObject = areaCopy;
            Debug.Log(
                $"[PipelineDemoSceneBuilder] Built {DemoScenePath} from "
                + $"{SourceAreaName} (Grasp-based; hand teleop re-enabled, "
                + "arm+grip stays RL with driveHandJoints=false, ball spawn "
                + "wired to CameraTargetReceiver).");
        }

        static void CloseExistingDemoSceneIfLoaded(Scene except)
        {
            for (int i = SceneManager.sceneCount - 1; i >= 0; i--)
            {
                Scene s = SceneManager.GetSceneAt(i);
                if (s != except && s.path == DemoScenePath)
                    EditorSceneManager.CloseScene(s, true);
            }
        }

        static void ReEnableHandTeleop(GameObject area)
        {
            foreach (MonoBehaviour behaviour in
                     area.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (behaviour == null) continue;
                string typeName = behaviour.GetType().Name;
                if (Array.IndexOf(HandTeleopTypeNames, typeName) >= 0)
                    behaviour.enabled = true;
                else if (Array.IndexOf(ForceDisabledTypeNames, typeName) >= 0)
                    behaviour.enabled = false;
            }

            Transform handRoot = area.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(t => t.name == HandRootName);
            if (handRoot == null)
                throw new InvalidOperationException(
                    $"Missing transform: {HandRootName}");

            foreach (ArticulationBody body in
                     handRoot.GetComponentsInChildren<ArticulationBody>(true))
            {
                body.enabled = true;
            }
            foreach (Collider collider in
                     handRoot.GetComponentsInChildren<Collider>(true))
            {
                collider.enabled = true;
            }
        }

        static CameraTargetReceiver ConfigureCameraReceiver(GameObject area)
        {
            Dg5fGraspAgent agent = area.GetComponentInChildren<Dg5fGraspAgent>(true);
            if (agent == null)
                throw new InvalidOperationException(
                    $"Missing {nameof(Dg5fGraspAgent)} on {area.name}.");

            CameraTargetReceiver receiver =
                agent.gameObject.GetComponent<CameraTargetReceiver>();
            if (receiver == null)
                receiver = agent.gameObject.AddComponent<CameraTargetReceiver>();

            receiver.port = CameraReceiverPort;
            receiver.robotBase = agent.robotBase;
            receiver.target = null;
            receiver.continuousApply = false;
            receiver.inputIsCameraSpace = false;
            receiver.clampToWorkspace = true;
            receiver.minRadius = Dg5fGraspSpec.V1MinimumSpawnRadius;
            receiver.maxRadius = Dg5fGraspSpec.V1MaximumSpawnRadius;
            receiver.logToConsole = true;
            receiver.logToFile = true;
            return receiver;
        }

        static void ConfigureAgent(GameObject area, CameraTargetReceiver cameraReceiver)
        {
            Dg5fGraspAgent agent = area.GetComponentInChildren<Dg5fGraspAgent>(true);
            agent.cameraReceiver = cameraReceiver;
            agent.driveHandJoints = false;
            // Training leaves this true (episode-per-attempt throughput). The live demo
            // needs a completed reach+hold to call LockArmForTeleoperation(), which is what
            // flips GraspTeleoperationHandoff.IsExternalHandControl and actually enables
            // Dg5fReceiver/Dg5fHandDriver — otherwise the hand teleop UDP socket never opens.
            agent.endEpisodeOnReach = false;
        }

        /// 팔이 잠긴(텔레옵) 구간에서만 ArmTargetIK/HandSliderUI를 빌려 써서 높이(슬라이더)와
        /// 수평 위치(조이스틱)를 조절할 수 있게 하는 ArmTeleopNudge를 붙인다. ArmTargetIK/
        /// HandSliderUI 자체는 ReEnableHandTeleop 대상이 아니라 ForceDisabledTypeNames로 이미
        /// 꺼진 채 시작하고, ArmTeleopNudge가 런타임에 필요할 때만 켠다.
        static void ConfigureArmTeleopNudge(GameObject area)
        {
            Dg5fGraspAgent agent = area.GetComponentInChildren<Dg5fGraspAgent>(true);
            if (agent.GetComponent<ArmTeleopNudge>() == null)
                agent.gameObject.AddComponent<ArmTeleopNudge>();
        }

        /// 기존 Main Camera(기본 위치에서 벗어난 적 없는 미사용 스폰 카메라)에 CinemachineBrain을
        /// 붙이고, 그 자리를 그대로 물려받는 정적 OverviewCamera와, graspPoint를 바라보며 palm을
        /// 따라다니는 GraspCloseUpCamera 두 개의 CinemachineVirtualCamera를 추가한 뒤
        /// DemoCameraSwitcher(OnGUI 버튼)로 둘을 전환할 수 있게 한다. Follow offset은 WorldSpace
        /// 바인딩이라 손목이 회전해도 카메라가 같이 돌지 않고 안정적으로 유지된다.
        static void ConfigureGraspCamera(GameObject area, Scene demoScene)
        {
            Dg5fGraspAgent agent = area.GetComponentInChildren<Dg5fGraspAgent>(true);
            Transform followTarget = agent.palm != null ? agent.palm : agent.robotBase;
            Transform lookTarget = agent.graspPoint != null ? agent.graspPoint : followTarget;

            GameObject mainCameraObject = demoScene.GetRootGameObjects()
                .FirstOrDefault(go => go.GetComponent<Camera>() != null);
            if (mainCameraObject == null)
                throw new InvalidOperationException(
                    "[PipelineDemoSceneBuilder] Missing Main Camera in demo scene.");

            if (mainCameraObject.GetComponent<CinemachineBrain>() == null)
                mainCameraObject.AddComponent<CinemachineBrain>();

            Transform originalCameraTransform = mainCameraObject.transform;
            CinemachineVirtualCamera overviewCamera = CreateStaticVirtualCamera(
                demoScene,
                OverviewCameraName,
                originalCameraTransform.position,
                originalCameraTransform.rotation);
            CinemachineVirtualCamera graspCamera = CreateGraspVirtualCamera(demoScene, followTarget, lookTarget);

            DemoCameraSwitcher switcher = agent.gameObject.GetComponent<DemoCameraSwitcher>();
            if (switcher == null) switcher = agent.gameObject.AddComponent<DemoCameraSwitcher>();
            switcher.cameras = new[] { overviewCamera, graspCamera };
            switcher.cameraLabels = new[] { "전체 보기", "그랩 클로즈업" };
            switcher.defaultCameraIndex = DefaultLiveCameraIndex;
            switcher.minFieldOfView = MinZoomFieldOfView;
            switcher.maxFieldOfView = MaxZoomFieldOfView;
            switcher.SetActiveCamera(DefaultLiveCameraIndex);
        }

        static CinemachineVirtualCamera CreateStaticVirtualCamera(
            Scene scene, string name, Vector3 position, Quaternion rotation)
        {
            var cameraObject = new GameObject(name);
            SceneManager.MoveGameObjectToScene(cameraObject, scene);
            cameraObject.transform.SetPositionAndRotation(position, rotation);
            return cameraObject.AddComponent<CinemachineVirtualCamera>();
        }

        static CinemachineVirtualCamera CreateGraspVirtualCamera(
            Scene scene, Transform followTarget, Transform lookTarget)
        {
            var cameraObject = new GameObject(GraspCameraName);
            SceneManager.MoveGameObjectToScene(cameraObject, scene);

            var vcam = cameraObject.AddComponent<CinemachineVirtualCamera>();
            vcam.Follow = followTarget;
            vcam.LookAt = lookTarget;
            vcam.m_Lens.FieldOfView = GraspCameraFieldOfView;

            var body = vcam.AddCinemachineComponent<CinemachineTransposer>();
            body.m_BindingMode = CinemachineTransposer.BindingMode.WorldSpace;
            body.m_FollowOffset = GraspCameraFollowOffset;

            vcam.AddCinemachineComponent<CinemachineComposer>();
            return vcam;
        }

        /// GraspBall 외에 정육면체/원통 후보를 추가로 만들고 GraspTargetSwitcher로 묶어,
        /// 라이브 데모 중 어떤 물체를 향해 팔이 접근할지 전환할 수 있게 한다. 정책은 구 모양으로
        /// 학습됐으므로 다른 모양에서는 접근 정확도가 다소 떨어질 수 있다(데모 목적으로는 허용).
        static void ConfigureTargetVariety(GameObject area)
        {
            Dg5fGraspAgent agent = area.GetComponentInChildren<Dg5fGraspAgent>(true);
            Rigidbody ball = agent.ball;
            if (ball == null)
                throw new InvalidOperationException(
                    $"[PipelineDemoSceneBuilder] Missing ball reference on cloned agent in {area.name}.");

            Collider ballCollider = ball.GetComponent<Collider>();
            PhysicsMaterial surface = ballCollider != null ? ballCollider.material : null;
            Transform parent = ball.transform.parent;
            Vector3 spawnLocalPosition = ball.transform.localPosition;

            Rigidbody cube = CreateExtraTarget(
                parent,
                PrimitiveType.Cube,
                "GraspCube",
                Vector3.one * 0.036f,
                spawnLocalPosition,
                surface,
                CubeMaterialPath,
                Color.blue);
            Rigidbody cylinder = CreateExtraTarget(
                parent,
                PrimitiveType.Cylinder,
                "GraspCylinder",
                new Vector3(0.04f, 0.02f, 0.04f),
                spawnLocalPosition,
                surface,
                CylinderMaterialPath,
                Color.green);

            GraspTargetSwitcher switcher = agent.gameObject.GetComponent<GraspTargetSwitcher>();
            if (switcher == null) switcher = agent.gameObject.AddComponent<GraspTargetSwitcher>();
            switcher.agent = agent;
            switcher.targets = new[] { ball, cube, cylinder };
            switcher.targetLabels = new[] { "빨간 공", "파란 정육면체", "초록 원통" };
        }

        static Rigidbody CreateExtraTarget(
            Transform parent,
            PrimitiveType primitive,
            string name,
            Vector3 localScale,
            Vector3 localPosition,
            PhysicsMaterial physicsMaterial,
            string materialPath,
            Color color)
        {
            var target = GameObject.CreatePrimitive(primitive);
            target.name = name;
            target.transform.SetParent(parent, false);
            target.transform.localPosition = localPosition;
            target.transform.localScale = localScale;
            target.GetComponent<Collider>().material = physicsMaterial;
            target.GetComponent<Renderer>().sharedMaterial = GetOrCreateMaterial(materialPath, name, color);

            var body = target.AddComponent<Rigidbody>();
            body.mass = 0.05f;
            body.useGravity = true;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            body.interpolation = RigidbodyInterpolation.None;

            // 처음엔 비활성 — GraspTargetSwitcher가 전환할 때만 켜진다.
            target.SetActive(false);
            return body;
        }

        static Material GetOrCreateMaterial(string path, string name, Color color)
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material != null) return material;
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            material = new Material(shader) { name = name, color = color };
            AssetDatabase.CreateAsset(material, path);
            return material;
        }

        static void SetInferenceOnly(GameObject area)
        {
            BehaviorParameters behavior =
                area.GetComponentInChildren<BehaviorParameters>(true);
            if (behavior == null) return;

            // Only force InferenceOnly (which requires a Model) once a matching
            // trained model is actually assigned. With no Model, Default falls
            // back to Heuristic (idle) instead of throwing at Play time.
            behavior.BehaviorType = behavior.Model != null
                ? BehaviorType.InferenceOnly
                : BehaviorType.Default;
        }

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = System.IO.Path.GetDirectoryName(path)?.Replace('\\', '/');
            string leaf = System.IO.Path.GetFileName(path);
            if (!string.IsNullOrEmpty(parent) && !AssetDatabase.IsValidFolder(parent))
                EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, leaf);
        }
    }
}
