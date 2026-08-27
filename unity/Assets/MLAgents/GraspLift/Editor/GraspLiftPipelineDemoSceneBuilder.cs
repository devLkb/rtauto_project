using System;
using System.Linq;
using Cinemachine;
using KDT.GraspLiftTraining;
using Unity.MLAgents.Policies;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace KDT.GraspLiftTraining.Editor
{
    /// <summary>
    /// Builds a single-robot live demo scene from the trained DG5FGraspLift behavior:
    /// duplicates DG5F_GraspLiftTrainingArea_00 out of the 20-parallel training scene
    /// and points a camera at it. agent.endEpisodeOnSuccess is set false so that on a
    /// successful grasp+lift the arm/hand simply stop being commanded and hold their
    /// last pose (Dg5fGraspLiftAgent.FixedUpdate no-ops once _episodeActive is false)
    /// instead of resetting into the next training episode. A GraspLiftControlModeSwitcher
    /// also lets the operator flip to manual mid-run: GraspLiftTeleopNudge takes over the
    /// arm (same joystick+height-slider feel as the reach demo's ArmTeleopNudge, just sized
    /// for the full workspace) and the shared robot prefab's existing Dg5fReceiver/
    /// Dg5fHandDriver (normally disabled for training) take over the fingers from real hand
    /// tracking (vision/dg5f/dg5f_teleop_gui.py). The Main Camera gets an overview/close-up
    /// Cinemachine camera pair (switchable via GraspLiftDemoCameraSwitcher, same pattern as
    /// the reach demo's DemoCameraSwitcher) so the grasp is visible up close with a zoom slider.
    /// </summary>
    public static class GraspLiftPipelineDemoSceneBuilder
    {
        public const string SourceScenePath =
            "Assets/MLAgents/GraspLift/DG5F_GraspLiftTraining.unity";
        public const string SourceAreaName = "DG5F_GraspLiftTrainingArea_00";
        // The production demo path belongs to the confirmed UR16e + DG-5F-M-R
        // right-hand PicknPlace builder. Keep this retired UR5e + left-hand demo
        // separate so running the legacy menu item cannot silently replace it.
        public const string DemoScenePath =
            "Assets/Scenes/Pipeline_Demo_GraspLift_LegacyLeft.unity";
        const string HandRootName = "ll_dg_palm";
        const string OverviewCameraName = "OverviewCamera";
        const string CloseUpCameraName = "GraspLiftCloseUpCamera";
        const float CloseUpCameraFieldOfView = 32f;
        const float MinZoomFieldOfView = 15f;
        const float MaxZoomFieldOfView = 120f;
        // Close-up camera starts live, matching the reach demo's convention.
        const int DefaultLiveCameraIndex = 1;

        // World-space offset (Transposer BindingMode.WorldSpace) so the close-up camera
        // doesn't spin with the wrist as the arm rotates into the grasp.
        static readonly Vector3 CloseUpCameraFollowOffset = new Vector3(0.4f, 0.3f, -0.4f);

        [MenuItem("Tools/ML-Agents/Build GraspLift Pipeline Demo Scene")]
        public static void Build()
        {
            if (EditorApplication.isPlaying)
                throw new InvalidOperationException(
                    "[GraspLiftPipelineDemoSceneBuilder] Stop Play mode before building the demo scene "
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
                    $"'{SourceAreaName}' not found in {SourceScenePath}.");
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

            Dg5fGraspLiftAgent agent = ConfigureAgent(areaCopy);
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
                $"[GraspLiftPipelineDemoSceneBuilder] Built {DemoScenePath} from "
                + $"{SourceAreaName} (endEpisodeOnSuccess=false — a successful "
                + "grasp+lift freezes the arm/hand in place instead of resetting; "
                + "automatic/manual control toggle wired via GraspLiftControlModeSwitcher).");
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

        static Dg5fGraspLiftAgent ConfigureAgent(GameObject area)
        {
            Dg5fGraspLiftAgent agent = area.GetComponentInChildren<Dg5fGraspLiftAgent>(true);
            if (agent == null)
                throw new InvalidOperationException(
                    $"Missing {nameof(Dg5fGraspLiftAgent)} on {area.name}.");
            agent.endEpisodeOnSuccess = false;
            return agent;
        }

        /// Dg5fReceiver/Dg5fHandDriver/HandSliderUI/ArmTargetIK already live on the shared
        /// robot prefab (ur5e_dg5f_left.prefab) — GraspLiftTrainingSceneBuilder just disables
        /// them for training. Wire up the new automatic/manual toggle on top of what's already
        /// there; both drivers start disabled (auto mode is the default).
        static void ConfigureManualTeleop(GameObject area, Dg5fGraspLiftAgent agent)
        {
            Dg5fReceiver receiver = area.GetComponentInChildren<Dg5fReceiver>(true);
            Dg5fHandDriver driver = area.GetComponentInChildren<Dg5fHandDriver>(true);
            if (receiver == null)
                throw new InvalidOperationException($"Missing {nameof(Dg5fReceiver)} on {area.name}.");
            if (driver == null)
                throw new InvalidOperationException($"Missing {nameof(Dg5fHandDriver)} on {area.name}.");
            receiver.enabled = false;
            driver.enabled = false;

            Transform handRoot = area.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(t => t.name == HandRootName);
            if (handRoot == null)
                throw new InvalidOperationException($"Missing transform: {HandRootName}");
            foreach (ArticulationBody body in handRoot.GetComponentsInChildren<ArticulationBody>(true))
                body.enabled = true;
            foreach (Collider collider in handRoot.GetComponentsInChildren<Collider>(true))
                collider.enabled = true;

            GraspLiftTeleopNudge nudge = agent.gameObject.GetComponent<GraspLiftTeleopNudge>();
            if (nudge == null) nudge = agent.gameObject.AddComponent<GraspLiftTeleopNudge>();

            GraspLiftControlModeSwitcher switcher =
                agent.gameObject.GetComponent<GraspLiftControlModeSwitcher>();
            if (switcher == null) switcher = agent.gameObject.AddComponent<GraspLiftControlModeSwitcher>();
            switcher.agent = agent;
            switcher.armNudge = nudge;
            switcher.handReceiver = receiver;
            switcher.handDriver = driver;
        }

        /// 기존 Main Camera에 CinemachineBrain을 붙이고, 그 자리를 물려받는 정적 OverviewCamera와
        /// palm을 따라다니며 graspPoint를 바라보는 GraspLiftCloseUpCamera 두 개의
        /// CinemachineVirtualCamera를 추가한 뒤 GraspLiftDemoCameraSwitcher(OnGUI 버튼+줌 슬라이더)로
        /// 전환할 수 있게 한다 — reach 데모의 ConfigureGraspCamera와 동일한 패턴.
        static void ConfigureCamera(Scene demoScene, Dg5fGraspLiftAgent agent)
        {
            Transform followTarget = agent.palm != null ? agent.palm : agent.robotBase;
            Transform lookTarget = agent.graspPoint != null ? agent.graspPoint : followTarget;

            GameObject mainCameraObject = demoScene.GetRootGameObjects()
                .FirstOrDefault(go => go.GetComponent<Camera>() != null);
            if (mainCameraObject == null)
                throw new InvalidOperationException(
                    "[GraspLiftPipelineDemoSceneBuilder] Missing Main Camera in demo scene.");

            if (mainCameraObject.GetComponent<CinemachineBrain>() == null)
                mainCameraObject.AddComponent<CinemachineBrain>();

            Transform originalCameraTransform = mainCameraObject.transform;
            CinemachineVirtualCamera overviewCamera = CreateStaticVirtualCamera(
                demoScene,
                OverviewCameraName,
                originalCameraTransform.position,
                originalCameraTransform.rotation);
            CinemachineVirtualCamera closeUpCamera = CreateCloseUpVirtualCamera(demoScene, followTarget, lookTarget);

            GraspLiftDemoCameraSwitcher switcher = agent.gameObject.GetComponent<GraspLiftDemoCameraSwitcher>();
            if (switcher == null) switcher = agent.gameObject.AddComponent<GraspLiftDemoCameraSwitcher>();
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
