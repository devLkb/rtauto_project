using System;
using System.Linq;
using Cinemachine;
using KDT.PicknPlaceTraining;
using Unity.MLAgents.Policies;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Builds a single-robot live demo scene from the trained DG5FPicknPlace behavior
    /// (confirmed hardware: UR16e + DG-5F-M-R right hand) onto Assets/Scenes/Pipeline_Demo_GraspLift.unity
    /// — same target scene GraspLiftPipelineDemoSceneBuilder used for the retired UR5e + left-hand
    /// demo, now re-pointed at the confirmed-hardware model from UR16eDG5FRight_Preview.unity
    /// (via ur16e_dg5f_right.prefab / DG5F_PicknPlaceTraining.unity — see docs/DG5F_PICKNPLACE.md).
    ///
    /// Duplicates DG5F_PicknPlaceTrainingArea_00 out of the 40-parallel training scene and points a
    /// camera at it. agent.endEpisodeOnSuccess is set false so that on a successful grasp+lift the
    /// arm/hand simply stop being commanded and hold their last pose (Dg5fPicknPlaceAgent.FixedUpdate
    /// no-ops once _episodeActive is false) instead of resetting into the next training episode.
    ///
    /// A PicknPlaceControlModeSwitcher lets the operator flip to manual mid-run: PicknPlaceTeleopNudge
    /// takes over the arm (joystick+height-slider, ArmTargetIK) and Dg5fReceiver/Dg5fHandDriver take
    /// over the fingers from real hand tracking (vision/dg5f/vision_node_dg5f.py, right-hand model —
    /// run with no arguments). Unlike GraspLift's shared ur5e_dg5f_left.prefab, ur16e_dg5f_right.prefab
    /// does not ship these teleop components (CreateUr16eDg5fRightPrefab strips even the preview-only
    /// HandSliderUI), so this builder adds them fresh on the robot root instead of just enabling
    /// pre-existing ones. The Main Camera gets an overview/close-up Cinemachine camera pair
    /// (switchable via PicknPlaceDemoCameraSwitcher) so the grasp is visible up close with a zoom slider.
    ///
    /// Auto mode runs whatever ONNX model is currently assigned on the training area's
    /// BehaviorParameters (Assets/MLAgents/picknplace/Models/DG5FPicknPlace.onnx, dropped in once
    /// training finishes) — SetInferenceOnly leaves BehaviorType at Default (Heuristic/idle) until a
    /// model is actually present, so this builder is safe to run before training completes.
    /// </summary>
    public static class PicknPlacePipelineDemoSceneBuilder
    {
        public const string SourceScenePath =
            "Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity";
        public const string SourceAreaName = "DG5F_PicknPlaceTrainingArea_00";
        public const string DemoScenePath = "Assets/Scenes/Pipeline_Demo_GraspLift.unity";
        const string HandRootName = "rl_dg_palm";
        const string OverviewCameraName = "OverviewCamera";
        const string CloseUpCameraName = "PicknPlaceCloseUpCamera";
        const float CloseUpCameraFieldOfView = 32f;
        const float MinZoomFieldOfView = 15f;
        const float MaxZoomFieldOfView = 120f;
        // Close-up camera starts live, matching the reach/GraspLift demo convention.
        const int DefaultLiveCameraIndex = 1;

        // World-space offset (Transposer BindingMode.WorldSpace) so the close-up camera
        // doesn't spin with the wrist as the arm rotates into the grasp.
        static readonly Vector3 CloseUpCameraFollowOffset = new Vector3(0.4f, 0.3f, -0.4f);

        [MenuItem("Tools/ML-Agents/Build PicknPlace Pipeline Demo Scene")]
        public static void Build()
        {
            if (EditorApplication.isPlaying)
                throw new InvalidOperationException(
                    "[PicknPlacePipelineDemoSceneBuilder] Stop Play mode before building the demo scene "
                    + "(EditorSceneManager.OpenScene cannot run while playing).");

            Scene sourceScene = EditorSceneManager.OpenScene(
                SourceScenePath,
                OpenSceneMode.Additive);

            GameObject sourceArea = sourceScene.GetRootGameObjects()
                .FirstOrDefault(go => go.name == SourceAreaName);
            if (sourceArea == null)
            {
                EditorSceneManager.CloseScene(sourceScene, true);
                throw new InvalidOperationException(
                    $"'{SourceAreaName}' not found in {SourceScenePath}. Run "
                    + "\"Tools/ML-Agents/Build DG5F PicknPlace Training Scene\" first.");
            }

            GameObject areaCopy = UnityEngine.Object.Instantiate(sourceArea);
            areaCopy.name = SourceAreaName;

            // Additive (not Single) so sourceScene stays loaded until the copy has
            // been moved out of it — closing it first destroys areaCopy along with it.
            Scene demoScene = EditorSceneManager.NewScene(
                NewSceneSetup.DefaultGameObjects,
                NewSceneMode.Additive);
            demoScene.name = "Pipeline_Demo_GraspLift";
            SceneManager.MoveGameObjectToScene(areaCopy, demoScene);

            EditorSceneManager.CloseScene(sourceScene, true);
            EditorSceneManager.SetActiveScene(demoScene);

            // Now that demoScene exists alongside whatever else is loaded, it's
            // always safe to close a stale scene at the same path (never the
            // last loaded scene at this point).
            CloseExistingDemoSceneIfLoaded(demoScene);

            Dg5fPicknPlaceAgent agent = ConfigureAgent(areaCopy);
            ConfigureManualTeleop(areaCopy, agent);
            ConfigureCamera(demoScene, agent);
            SetInferenceOnly(areaCopy);

            EnsureFolder("Assets/Scenes");
            if (!EditorSceneManager.SaveScene(demoScene, DemoScenePath))
                throw new InvalidOperationException($"Failed to save {DemoScenePath}.");
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Selection.activeGameObject = areaCopy;
            Debug.Log(
                $"[PicknPlacePipelineDemoSceneBuilder] Built {DemoScenePath} from "
                + $"{SourceAreaName} (endEpisodeOnSuccess=false — a successful "
                + "grasp+lift freezes the arm/hand in place instead of resetting; "
                + "automatic/manual control toggle wired via PicknPlaceControlModeSwitcher).");
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

        static Dg5fPicknPlaceAgent ConfigureAgent(GameObject area)
        {
            Dg5fPicknPlaceAgent agent = area.GetComponentInChildren<Dg5fPicknPlaceAgent>(true);
            if (agent == null)
                throw new InvalidOperationException(
                    $"Missing {nameof(Dg5fPicknPlaceAgent)} on {area.name}.");
            agent.endEpisodeOnSuccess = false;
            return agent;
        }

        /// Unlike GraspLift's shared ur5e_dg5f_left.prefab, ur16e_dg5f_right.prefab was never given
        /// Dg5fReceiver/Dg5fHandDriver/ArmTargetIK/HandSliderUI (CreateUr16eDg5fRightPrefab strips even
        /// the preview-only HandSliderUI before saving it) — so these are added fresh here, all on the
        /// robot root (agent.gameObject), matching where PicknPlaceTeleopNudge/PicknPlaceControlModeSwitcher
        /// resolve them via GetComponent. Both drivers start disabled (auto mode is the default).
        static void ConfigureManualTeleop(GameObject area, Dg5fPicknPlaceAgent agent)
        {
            GameObject robot = agent.gameObject;

            Dg5fReceiver receiver = robot.GetComponent<Dg5fReceiver>();
            if (receiver == null) receiver = robot.AddComponent<Dg5fReceiver>();
            Dg5fHandDriver driver = robot.GetComponent<Dg5fHandDriver>();
            if (driver == null) driver = robot.AddComponent<Dg5fHandDriver>();
            HandSliderUI sliderUI = robot.GetComponent<HandSliderUI>();
            if (sliderUI == null) sliderUI = robot.AddComponent<HandSliderUI>();
            ArmTargetIK armIK = robot.GetComponent<ArmTargetIK>();
            if (armIK == null) armIK = robot.AddComponent<ArmTargetIK>();
            receiver.enabled = false;
            driver.enabled = false;
            sliderUI.enabled = false;
            armIK.enabled = false;

            Transform handRoot = area.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(t => t.name == HandRootName);
            if (handRoot == null)
                throw new InvalidOperationException($"Missing transform: {HandRootName}");
            foreach (ArticulationBody body in handRoot.GetComponentsInChildren<ArticulationBody>(true))
                body.enabled = true;
            foreach (Collider collider in handRoot.GetComponentsInChildren<Collider>(true))
                collider.enabled = true;

            PicknPlaceTeleopNudge nudge = robot.GetComponent<PicknPlaceTeleopNudge>();
            if (nudge == null) nudge = robot.AddComponent<PicknPlaceTeleopNudge>();

            PicknPlaceControlModeSwitcher switcher =
                robot.GetComponent<PicknPlaceControlModeSwitcher>();
            if (switcher == null) switcher = robot.AddComponent<PicknPlaceControlModeSwitcher>();
            switcher.agent = agent;
            switcher.armNudge = nudge;
            switcher.handReceiver = receiver;
            switcher.handDriver = driver;
        }

        /// 기존 Main Camera에 CinemachineBrain을 붙이고, 그 자리를 물려받는 정적 OverviewCamera와
        /// palm을 따라다니며 graspPoint를 바라보는 PicknPlaceCloseUpCamera 두 개의
        /// CinemachineVirtualCamera를 추가한 뒤 PicknPlaceDemoCameraSwitcher(OnGUI 버튼+줌 슬라이더)로
        /// 전환할 수 있게 한다 — GraspLift 데모의 ConfigureCamera와 동일한 패턴.
        static void ConfigureCamera(Scene demoScene, Dg5fPicknPlaceAgent agent)
        {
            Transform followTarget = agent.palm != null ? agent.palm : agent.robotBase;
            Transform lookTarget = agent.graspPoint != null ? agent.graspPoint : followTarget;

            GameObject mainCameraObject = demoScene.GetRootGameObjects()
                .FirstOrDefault(go => go.GetComponent<Camera>() != null);
            if (mainCameraObject == null)
                throw new InvalidOperationException(
                    "[PicknPlacePipelineDemoSceneBuilder] Missing Main Camera in demo scene.");

            if (mainCameraObject.GetComponent<CinemachineBrain>() == null)
                mainCameraObject.AddComponent<CinemachineBrain>();

            Transform originalCameraTransform = mainCameraObject.transform;
            CinemachineVirtualCamera overviewCamera = CreateStaticVirtualCamera(
                demoScene,
                OverviewCameraName,
                originalCameraTransform.position,
                originalCameraTransform.rotation);
            CinemachineVirtualCamera closeUpCamera = CreateCloseUpVirtualCamera(demoScene, followTarget, lookTarget);

            PicknPlaceDemoCameraSwitcher switcher = agent.gameObject.GetComponent<PicknPlaceDemoCameraSwitcher>();
            if (switcher == null) switcher = agent.gameObject.AddComponent<PicknPlaceDemoCameraSwitcher>();
            switcher.cameras = new[] { overviewCamera, closeUpCamera };
            switcher.cameraLabels = new[] { "전체 보기", "클로즈업" };
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

        static CinemachineVirtualCamera CreateCloseUpVirtualCamera(
            Scene scene, Transform followTarget, Transform lookTarget)
        {
            var cameraObject = new GameObject(CloseUpCameraName);
            SceneManager.MoveGameObjectToScene(cameraObject, scene);

            var vcam = cameraObject.AddComponent<CinemachineVirtualCamera>();
            vcam.Follow = followTarget;
            vcam.LookAt = lookTarget;
            vcam.m_Lens.FieldOfView = CloseUpCameraFieldOfView;

            var body = vcam.AddCinemachineComponent<CinemachineTransposer>();
            body.m_BindingMode = CinemachineTransposer.BindingMode.WorldSpace;
            body.m_FollowOffset = CloseUpCameraFollowOffset;

            vcam.AddCinemachineComponent<CinemachineComposer>();
            return vcam;
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
