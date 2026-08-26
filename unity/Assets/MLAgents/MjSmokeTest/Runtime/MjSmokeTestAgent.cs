using Mujoco;
using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Sensors;
using UnityEngine;

namespace KDT.MjSmokeTest
{
    // Minimal from-scratch ML-Agents <-> MuJoCo-plugin wiring smoke test.
    // Deliberately ignores Dg5fGraspLiftAgent.cs (which drives ArticulationBody.xDrive,
    // the old PhysX robot) - this proves the new MjActuator/MjHingeJoint path connects
    // to mlagents-learn at all, nothing more. Arm-only (6 joints), no hand, no reward
    // shaping, no episode reset logic.
    public class MjSmokeTestAgent : Agent
    {
        static readonly string[] ArmJointNames =
        {
            "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
            "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"
        };

        MjHingeJoint[] _joints;
        MjActuator[] _actuators;

        public override void Initialize()
        {
            _joints = new MjHingeJoint[ArmJointNames.Length];
            _actuators = new MjActuator[ArmJointNames.Length];

            var allJoints = GetComponentsInChildren<MjHingeJoint>(true);
            var allActuators = GetComponentsInChildren<MjActuator>(true);

            for (int i = 0; i < ArmJointNames.Length; i++)
            {
                var jointName = ArmJointNames[i];
                foreach (var j in allJoints)
                {
                    if (j.name == jointName) { _joints[i] = j; break; }
                }
                var actuatorName = $"act_{jointName}";
                foreach (var a in allActuators)
                {
                    if (a.name == actuatorName) { _actuators[i] = a; break; }
                }
                if (_joints[i] == null || _actuators[i] == null)
                {
                    Debug.LogError($"[MjSmokeTest] could not find joint/actuator for {jointName}");
                }
            }
        }

        public override void CollectObservations(VectorSensor sensor)
        {
            for (int i = 0; i < _joints.Length; i++)
            {
                sensor.AddObservation(_joints[i] != null ? _joints[i].Configuration : 0f);
                sensor.AddObservation(_joints[i] != null ? _joints[i].Velocity : 0f);
            }
        }

        public override void OnActionReceived(ActionBuffers actions)
        {
            for (int i = 0; i < _actuators.Length; i++)
            {
                if (_actuators[i] == null) continue;
                // Smoke test only: map the action straight to an absolute radian target,
                // no clamping to the real joint safety envelope.
                _actuators[i].Control = Mathf.Clamp(actions.ContinuousActions[i], -1f, 1f);
            }
            AddReward(-0.001f);
        }

        public override void Heuristic(in ActionBuffers actionsOut)
        {
            var a = actionsOut.ContinuousActions;
            for (int i = 0; i < a.Length; i++) a[i] = 0f;
        }
    }
}
