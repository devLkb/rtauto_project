using System;
using System.Linq;
using KDT.PicknPlaceTraining;
using Unity.MLAgents;
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
    /// pre-existing ones. A second arm-control mode, PicknPlaceArmJointPanel, lets the operator drag
    /// each of the 6 joints directly instead of nudging the end effector — the control mode switcher's
    /// "조이스틱/관절직접" toggle picks one at a time so they never fight over the same xDrive.target.
    /// That panel's "초기화" button teleports the arm and cube back to whatever PicknPlaceArmJointPanel
    /// captured in its own Start() — i.e. the pose actually on screen when Play began, not
    /// Dg5fPicknPlaceAgent.OnEpisodeBegin()'s HomeArmDeg/random cube spawn (which never runs
    /// automatically here since agent.enabled is permanently false) — and also releases the fist
    /// button so a held grasp cannot immediately fight the reset back closed.
    /// A Dg5fFistButton (top-right OnGUI) additionally lets the operator force the
    /// right-hand fist pose (Dg5fPicknPlaceSpec.RightFistDeg) without a webcam/MediaPipe running. The
    /// Main Camera is a single free-fly viewpoint (PicknPlaceFreeFlyCamera — WASD move + right-drag
    /// look, Scene-view-style), starting close to the grasp point instead of a fixed overview.
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
        const string WrongHandRootName = "ll_dg_palm";

        // Offset from the palm the free-fly camera starts at (same vantage the old close-up
        // camera used) so the operator begins near the grasp instead of a distant overview.
        static readonly Vector3 FreeFlyCameraStartOffset = new Vector3(0.4f, 0.3f, -0.4f);

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
            // The hierarchy contains collision/shadow objects with repeated names.
            // Never let ArmTargetIK's name-based fallback pick the wrong GraspPoint.
            armIK.endEffector = agent.graspPoint;
            foreach (ArticulationBody body in robot.GetComponentsInChildren<ArticulationBody>(true))
            {
                if (!Dg5fPicknPlaceSpec.ArmLinks.Contains(body.name)) continue;
                ArticulationDrive drive = body.xDrive;
                drive.stiffness = Dg5fPicknPlaceSpec.ArmDriveStiffness;
                drive.damping = Dg5fPicknPlaceSpec.ArmDriveDamping;
                body.xDrive = drive;
                body.useGravity = false;
            }
            receiver.enabled = false;
            driver.enabled = false;
            sliderUI.enabled = false;
            armIK.enabled = false;

            Transform handRoot = area.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(t => t.name == HandRootName);
            if (handRoot == null)
                throw new InvalidOperationException($"Missing transform: {HandRootName}");
            if (area.GetComponentsInChildren<Transform>(true)
                .Any(t => t.name == WrongHandRootName))
            {
                throw new InvalidOperationException(
                    $"Unexpected left-hand transform: {WrongHandRootName}. "
                    + "Pipeline_Demo_GraspLift must use DG-5F-M-R (right hand).");
            }
            foreach (ArticulationBody body in handRoot.GetComponentsInChildren<ArticulationBody>(true))
                body.enabled = true;
            foreach (Collider collider in handRoot.GetComponentsInChildren<Collider>(true))
                collider.enabled = true;

            PicknPlaceTeleopNudge nudge = robot.GetComponent<PicknPlaceTeleopNudge>();
            if (nudge == null) nudge = robot.AddComponent<PicknPlaceTeleopNudge>();
            nudge.agent = agent;
            nudge.armIK = armIK;
            nudge.armSliderUI = sliderUI;

            // Joint-space alternative to PicknPlaceTeleopNudge's Cartesian IK — lets the operator
            // drag each of the 6 UR16e joints directly instead of nudging the end effector.
            PicknPlaceArmJointPanel jointPanel = robot.GetComponent<PicknPlaceArmJointPanel>();
            if (jointPanel == null) jointPanel = robot.AddComponent<PicknPlaceArmJointPanel>();
            jointPanel.agent = agent;

            PicknPlaceControlModeSwitcher switcher =
                robot.GetComponent<PicknPlaceControlModeSwitcher>();
            if (switcher == null) switcher = robot.AddComponent<PicknPlaceControlModeSwitcher>();
            switcher.agent = agent;
            switcher.armNudge = nudge;
            switcher.armJointPanel = jointPanel;
            switcher.handReceiver = receiver;
            switcher.handDriver = driver;
            switcher.startInManualMode = true;
            // MediaPipe drives the right-hand fingers while the operator moves the
            // UR16e arm with PicknPlaceTeleopNudge's mouse joystick/height slider.
            switcher.handOnlyManualMode = false;
            nudge.maxHeightOffset = 0.2f;
            nudge.maxHorizontalOffset = 0.25f;
            nudge.horizontalMoveSpeed = 0.12f;

            // Webcam-free manual grasp: lets the operator force the validated right-hand
            // fist pose without MediaPipe running (unlike GraspLift's left-hand demo, which
            // has no equivalent — Dg5fGraspLiftSpec.LeftFistDeg is only ever driven by the
            // trained policy there).
            Dg5fFistButton fistButton = robot.GetComponent<Dg5fFistButton>();
            if (fistButton == null) fistButton = robot.AddComponent<Dg5fFistButton>();
            fistButton.agent = agent;
            fistButton.handDriver = driver;
            fistButton.handReceiver = receiver;

            // Full-reset button on the joint panel needs to release a held fist too,
            // otherwise Dg5fFistButton keeps driving the hand closed right through the reset.
            jointPanel.fistButton = fistButton;

            agent.enabled = false;
            DecisionRequester requester = robot.GetComponent<DecisionRequester>();
            if (requester != null) requester.enabled = false;
        }

        /// Main Camera 자체에 PicknPlaceFreeFlyCamera를 붙여 그 transform을 직접 조작하게 한다(우클릭
        /// 드래그 회전 + WASD 이동) — 더 이상 여러 카메라를 전환할 일이 없어 Cinemachine은 걷어내고,
        /// 시작 위치만 palm 근처(과거 클로즈업 카메라와 같은 오프셋)로 옮겨 가까운 곳에서 시작한다.
        static void ConfigureCamera(Scene demoScene, Dg5fPicknPlaceAgent agent)
        {
            Transform followTarget = agent.palm != null ? agent.palm : agent.robotBase;
            Transform lookTarget = agent.graspPoint != null ? agent.graspPoint : followTarget;

            GameObject mainCameraObject = demoScene.GetRootGameObjects()
                .FirstOrDefault(go => go.GetComponent<Camera>() != null);
            if (mainCameraObject == null)
                throw new InvalidOperationException(
                    "[PicknPlacePipelineDemoSceneBuilder] Missing Main Camera in demo scene.");

            Vector3 startPosition = followTarget.position + FreeFlyCameraStartOffset;
            Quaternion startRotation = Quaternion.LookRotation(
                (lookTarget.position - startPosition).normalized, Vector3.up);
            mainCameraObject.transform.SetPositionAndRotation(startPosition, startRotation);

            if (mainCameraObject.GetComponent<PicknPlaceFreeFlyCamera>() == null)
                mainCameraObject.AddComponent<PicknPlaceFreeFlyCamera>();
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
