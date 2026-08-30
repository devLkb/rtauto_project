using System.Linq;
using KDT.PicknPlaceTraining;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Measures thumb posture across the arm and grip poses the policy actually
    /// passes through, so the thumb constraint can be set from data instead of
    /// guessed. This is the tool that produced the numbers quoted on
    /// Dg5fPicknPlaceSpec.ThumbLowestSaturationMeters.
    ///
    /// Why it exists: the task brief forbids the thumb pointing at the floor, but
    /// the same brief wants a top-down grasp (palm normal within
    /// MaximumTopDownAngleDegrees of straight down). Those turned out to conflict
    /// under the original angle-based reading, which moved with grip closure
    /// rather than with thumb direction. Both readings are still logged side by
    /// side here (thumbDownAngle, the old one; thumbBelowOtherTips, the one the
    /// reward now uses) so the conflict stays visible if the hand model changes.
    ///
    /// Same Physics.Simulate caveat as PicknPlacePoseDiagnostic - see that file.
    /// </summary>
    public static class PicknPlaceThumbDiagnostic
    {
        [MenuItem("Tools/ML-Agents/Diagnose PicknPlace Thumb Orientation")]
        public static void Run()
        {
            EditorSceneManager.OpenScene(
                "Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity", OpenSceneMode.Single);

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

            var bodies = agent.GetComponentsInChildren<ArticulationBody>(true);
            var armLinks = Dg5fPicknPlaceSpec.ArmLinks;
            var armBodies = new ArticulationBody[armLinks.Length];
            for (int i = 0; i < armLinks.Length; i++)
            {
                armBodies[i] = bodies.FirstOrDefault(b => b.name == armLinks[i]);
                if (armBodies[i] == null) throw new System.Exception($"Missing arm body: {armLinks[i]}");
            }

            var handBodies = new ArticulationBody[Dg5fPicknPlaceSpec.HandJointCount];
            for (int finger = 1; finger <= Dg5fPicknPlaceSpec.FingerCount; finger++)
                for (int joint = 1; joint <= 4; joint++)
                {
                    int channel = (finger - 1) * 4 + joint - 1;
                    handBodies[channel] = bodies.FirstOrDefault(
                        b => b.name.EndsWith($"_dg_{finger}_{joint}"));
                    if (handBodies[channel] == null)
                        throw new System.Exception($"Missing hand body: _dg_{finger}_{joint}");
                }

            var openDeg = handBodies.Select(CurrentTargetDeg).ToArray();

            Transform robotBase = agent.robotBase != null ? agent.robotBase : agent.transform;
            Transform palm = bodies.Select(b => b.transform).FirstOrDefault(t => t.name == "rl_dg_palm");
            Transform thumbTip = agent.fingerTips != null && agent.fingerTips.Length > 0
                ? agent.fingerTips[0]
                : null;
            if (thumbTip == null)
                throw new System.Exception(
                    "agent.fingerTips[0] (the thumb tip) is null. That is exactly what the "
                    + "reward reads, and when it is null ThumbDownAngleDegrees() returns the "
                    + "safe 180 deg fallback, so the penalty would silently never fire.");

            Debug.Log("[ThumbDiagnostic] saturationDepth="
                + $"{Dg5fPicknPlaceSpec.ThumbLowestSaturationMeters:F3}m scale="
                + $"{Dg5fPicknPlaceSpec.ThumbDownPenaltyScale:F3}/decision "
                + $"maxTopDownAngle={Dg5fPicknPlaceSpec.MaximumTopDownAngleDegrees:F0}deg");

            // Home pose, hand open then closed: the two extremes every episode
            // passes through before the cube is even reached.
            ApplyArm(armBodies, Dg5fPicknPlaceSpec.HomeArmDeg);
            ApplyHand(handBodies, openDeg);
            Step();
            LogPose("home + open hand", armBodies, palm, thumbTip, handBodies, robotBase,
                agent.fingerTips);

            // Closure sweep. ApplyGripTargets lerps every hand joint from the open
            // pose to RightFistDeg by _closure, so the thumb's base-to-tip vector
            // swings with CURL, not just with wrist orientation. If the angle
            // tracks closure this strongly, the current measure is really a
            // penalty on closing the hand -- which is the task itself.
            foreach (float closure in new[] { 0f, 0.25f, 0.5f, 0.75f, 1f })
            {
                var pose = new float[handBodies.Length];
                for (int i = 0; i < pose.Length; i++)
                    pose[i] = Mathf.Lerp(openDeg[i], Dg5fPicknPlaceSpec.RightFistDeg[i], closure);
                ApplyHand(handBodies, pose);
                Step();
                LogPose($"home + closure={closure:F2}", armBodies, palm, thumbTip, handBodies,
                    robotBase, agent.fingerTips);
            }

            ApplyHand(handBodies, Dg5fPicknPlaceSpec.RightFistDeg);
            Step();
            LogPose("home + closed fist", armBodies, palm, thumbTip, handBodies, robotBase,
                agent.fingerTips);

            // wrist_3 is the tool roll: it spins the hand about the palm normal
            // without changing the top-down palm angle, so it is the one joint
            // that trades thumb orientation for nothing. If no roll gets the thumb
            // past the safe angle, the constraint and the top-down grasp are
            // geometrically in conflict and the penalty needs rethinking.
            var home = Dg5fPicknPlaceSpec.HomeArmDeg;
            for (float roll = -180f; roll <= 180f; roll += 30f)
            {
                var pose = new[] { home[0], home[1], home[2], home[3], home[4], roll };
                ApplyArm(armBodies, pose);
                ApplyHand(handBodies, Dg5fPicknPlaceSpec.RightFistDeg);
                Step();
                LogPose($"fist wrist_3={roll:F0}", armBodies, palm, thumbTip, handBodies,
                    robotBase, agent.fingerTips);
            }

            Debug.Log("[ThumbDiagnostic] Done. Scene left mutated in-memory; not saved.");
        }

        static void Step() => Physics.Simulate(Time.fixedDeltaTime);

        static float CurrentTargetDeg(ArticulationBody body) => body.xDrive.target;

        static void ApplyArm(ArticulationBody[] armBodies, float[] deg)
        {
            for (int i = 0; i < armBodies.Length; i++)
            {
                float clamped = Mathf.Clamp(
                    deg[i], Dg5fPicknPlaceSpec.ArmSafeMinDeg[i], Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]);
                SetJoint(armBodies[i], clamped);
            }
        }

        static void ApplyHand(ArticulationBody[] handBodies, float[] deg)
        {
            for (int i = 0; i < handBodies.Length; i++) SetJoint(handBodies[i], deg[i]);
        }

        static void SetJoint(ArticulationBody body, float deg)
        {
            body.jointPosition = new ArticulationReducedSpace(deg * Mathf.Deg2Rad);
            body.jointVelocity = new ArticulationReducedSpace(0f);
            var drive = body.xDrive;
            drive.target = deg;
            body.xDrive = drive;
        }

        static void LogPose(
            string label, ArticulationBody[] armBodies, Transform palm, Transform thumbTip,
            ArticulationBody[] handBodies, Transform robotBase, Transform[] fingerTips = null)
        {
            Vector3 down = -robotBase.up.normalized;
            Vector3 thumbDirection = thumbTip.position - handBodies[0].transform.position;
            float thumbAngle = Vector3.Angle(thumbDirection.normalized, down);
            float thumbBelowOthers = float.NaN;
            if (fingerTips != null && fingerTips.Length == Dg5fPicknPlaceSpec.FingerCount
                && fingerTips.All(t => t != null))
            {
                thumbBelowOthers = Vector3.Dot(fingerTips[0].position, down)
                    - fingerTips.Skip(1).Max(t => Vector3.Dot(t.position, down));
            }
            float penalty = Dg5fPicknPlaceSpec.ThumbDownPenalty(thumbBelowOthers);
            float palmAngle = palm == null ? float.NaN : Vector3.Angle(palm.forward.normalized, down);
            string arm = string.Join(", ", armBodies.Select(
                b => (FirstOrZero(b.jointPosition) * Mathf.Rad2Deg).ToString("F0")));

            // Curl-independent alternative: the thumb's PROXIMAL segment
            // (_dg_1_1 -> _dg_1_2) turns with the wrist and the thumb's spread
            // joint but barely with the curl, so it separates "the hand is
            // oriented thumb-down" from "the hand is closed".
            Vector3 proximal = handBodies[1].transform.position - handBodies[0].transform.position;
            float proximalAngle = Vector3.Angle(proximal.normalized, down);

            // Physical hazard the brief is really about: is the thumb the part of
            // the hand nearest the surface? Positive = below the palm.
            string tipInfo = "";
            if (fingerTips != null && fingerTips.Length == Dg5fPicknPlaceSpec.FingerCount
                && fingerTips.All(t => t != null) && palm != null)
            {
                float thumbBelow = Vector3.Dot(fingerTips[0].position - palm.position, down);
                float lowestOther = fingerTips.Skip(1)
                    .Max(t => Vector3.Dot(t.position - palm.position, down));
                tipInfo = $" thumbBelowPalm={thumbBelow:F3}m lowestOtherTipBelowPalm={lowestOther:F3}m"
                    + $" thumbBelowOtherTips={thumbBelow - lowestOther:F4}m"
                    + $" thumbIsLowest={(thumbBelow > lowestOther ? "YES" : "no")}";
            }

            Debug.Log($"[ThumbDiagnostic] {label}: arm=[{arm}] "
                + $"thumbDownAngle={thumbAngle:F1}deg proximalDownAngle={proximalAngle:F1}deg "
                + $"palmDownAngle={palmAngle:F1}deg "
                + $"penaltyPerDecision={penalty:F4} penaltyPerEpisode(200dec)={penalty * 200f:F2}"
                + tipInfo);
        }

        static float FirstOrZero(ArticulationReducedSpace values)
        {
            try { return values[0]; }
            catch (System.IndexOutOfRangeException) { return 0f; }
        }
    }
}
