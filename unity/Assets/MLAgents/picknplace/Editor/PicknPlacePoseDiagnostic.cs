using System.Linq;
using KDT.PicknPlaceTraining;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Temporary diagnostic: sweeps candidate arm home poses against the
    /// generated scene's live geometry and reports the resulting palm/graspPoint
    /// height and orientation, so a "look-down ready pose" can be chosen from
    /// measured data instead of guessed blind. Delete once the home pose is
    /// settled — this is not part of the training scene/build pipeline.
    /// </summary>
    public static class PicknPlacePoseDiagnostic
    {
        [MenuItem("Tools/ML-Agents/Diagnose PicknPlace Arm Poses")]
        public static void Run()
        {
            EditorSceneManager.OpenScene(
                "Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity", OpenSceneMode.Single);

            // Physics.SyncTransforms() does NOT recompute forward kinematics for an
            // ArticulationBody chain outside of an actual physics step — only
            // FixedUpdate-driven simulation (Play mode) propagates a jointPosition
            // write to descendant link Transforms. Manually stepping the engine via
            // Physics.Simulate is the documented way to force that recomputation in
            // Edit mode. Without this every candidate below silently reported the
            // scene's on-disk zero pose regardless of what was written.
            //
            // SimulationMode is a project-wide setting (ProjectSettings/
            // DynamicsManager.asset, m_SimulationMode) — leaving it on Script
            // after this tool exits would silently stop Play mode from ever
            // auto-stepping physics again for the whole project. This bit the
            // repo once already (2026-08-27): the setting got left on Script and
            // persisted to the committed ProjectSettings before being caught.
            // Always restore it, even if the sweep below throws.
            SimulationMode originalSimulationMode = Physics.simulationMode;
            Physics.simulationMode = SimulationMode.Script;
            try
            {
                RunSweep();
            }
            finally
            {
                Physics.simulationMode = originalSimulationMode;
            }
        }

        static void RunSweep()
        {
            var agent = Object.FindAnyObjectByType<Dg5fPicknPlaceAgent>();
            if (agent == null) throw new System.Exception("No Dg5fPicknPlaceAgent found in scene.");

            var armLinks = Dg5fPicknPlaceSpec.ArmLinks;
            var bodies = agent.GetComponentsInChildren<ArticulationBody>(true);
            var armBodies = new ArticulationBody[armLinks.Length];
            for (int i = 0; i < armLinks.Length; i++)
                armBodies[i] = bodies.FirstOrDefault(b => b.name == armLinks[i]);
            for (int i = 0; i < armBodies.Length; i++)
                if (armBodies[i] == null)
                    throw new System.Exception($"Missing arm body: {armLinks[i]}");

            Transform robotBase = agent.robotBase != null ? agent.robotBase : agent.transform;
            Transform palm = bodies.Select(b => b.transform)
                .FirstOrDefault(t => t.name == "rl_dg_palm");
            Transform graspPoint = palm != null ? palm.Find("GraspPoint") : null;
            Collider pedestal = agent.pedestalCollider;

            Debug.Log($"[PoseDiagnostic] robotBase={robotBase.position}, panelTopY={pedestal.bounds.max.y:F4}, "
                + $"palm found={palm != null}, graspPoint found={graspPoint != null}");

            // Log the CURRENT resting/live pose first (whatever the training scene
            // currently has applied, no changes yet), then sweep candidates.
            LogPose("CURRENT (pre-sweep)", armBodies, palm, graspPoint, robotBase, pedestal);

            var candidates = new (string name, float[] deg)[]
            {
                // wrist_2 sweep: downAngle tracked -wrist_2 almost exactly in the
                // first pass (w2=-90 -> 90deg, w2=-120 -> 120deg). ArmSafeMinDeg/
                // MaxDeg caps wrist_2 at -30 (the closest-to-zero the safe range
                // allows), so sweep toward that boundary to see if the linear
                // relationship holds and how much height it costs.
                ("w2-30_lift60_elbow90", new float[] { 0f, -60f, 90f, -90f, -30f, 0f }),
                ("w2-45_lift60_elbow90", new float[] { 0f, -60f, 90f, -90f, -45f, 0f }),
                ("w2-30_lift40_elbow60", new float[] { 0f, -40f, 60f, -90f, -30f, 0f }),
                ("w2-30_lift80_elbow100", new float[] { 0f, -80f, 100f, -90f, -30f, 0f }),
                ("w2-30_w1-60_lift60_elbow90", new float[] { 0f, -60f, 90f, -60f, -30f, 0f }),
                ("w2-30_w1-120_lift60_elbow90", new float[] { 0f, -60f, 90f, -120f, -30f, 0f }),
            };

            foreach (var candidate in candidates)
            {
                for (int i = 0; i < armBodies.Length; i++)
                {
                    float clamped = Mathf.Clamp(
                        candidate.deg[i],
                        Dg5fPicknPlaceSpec.ArmSafeMinDeg[i],
                        Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]);
                    armBodies[i].jointPosition = new ArticulationReducedSpace(clamped * Mathf.Deg2Rad);
                    armBodies[i].jointVelocity = new ArticulationReducedSpace(0f);
                    var drive = armBodies[i].xDrive;
                    drive.target = clamped;
                    armBodies[i].xDrive = drive;
                }
                Physics.Simulate(Time.fixedDeltaTime);
                LogPose(candidate.name, armBodies, palm, graspPoint, robotBase, pedestal);
            }

            Debug.Log("[PoseDiagnostic] Done. Scene left mutated in-memory; not saved.");
        }

        static void LogPose(
            string label, ArticulationBody[] armBodies, Transform palm, Transform graspPoint,
            Transform robotBase, Collider pedestal)
        {
            string actualDeg = string.Join(", ", armBodies.Select(
                b => (FirstOrZero(b.jointPosition) * Mathf.Rad2Deg).ToString("F1")));

            if (palm == null)
            {
                Debug.Log($"[PoseDiagnostic] {label}: arm(actual deg)=[{actualDeg}] palm=NULL");
                return;
            }

            float palmHeightAbovePanel = palm.position.y - pedestal.bounds.max.y;
            Vector3 palmForward = palm.forward;
            float palmDownAlignment = Vector3.Dot(palmForward.normalized, -robotBase.up.normalized);
            float palmDownAngle = Mathf.Acos(Mathf.Clamp(palmDownAlignment, -1f, 1f)) * Mathf.Rad2Deg;

            string graspInfo = "graspPoint=NULL";
            if (graspPoint != null)
            {
                float gpHeight = graspPoint.position.y - pedestal.bounds.max.y;
                float gpAlignment = Vector3.Dot(
                    graspPoint.forward.normalized, -robotBase.up.normalized);
                float gpAngle = Mathf.Acos(Mathf.Clamp(gpAlignment, -1f, 1f)) * Mathf.Rad2Deg;
                graspInfo = $"graspPoint.heightAbovePanel={gpHeight:F4} graspPoint.downAngle={gpAngle:F1}";
            }

            Debug.Log($"[PoseDiagnostic] {label}: arm(actual deg)=[{actualDeg}] "
                + $"palm.heightAbovePanel={palmHeightAbovePanel:F4} palm.downAngle={palmDownAngle:F1} "
                + graspInfo);
        }

        static float FirstOrZero(ArticulationReducedSpace values)
        {
            try { return values[0]; }
            catch (System.IndexOutOfRangeException) { return 0f; }
        }
    }
}
