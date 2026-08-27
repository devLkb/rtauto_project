using System;
using System.Collections.Generic;
using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Sensors;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// PPO agent for the DG5F grasp + lift stage on a UR16e (right hand).
    ///
    /// Near-verbatim port of KDT.GraspLiftTraining.Dg5fGraspLiftAgent onto the
    /// confirmed hardware (UR16e + DG-5F-M-R right hand) instead of GraspLift's
    /// UR5e + left hand. The policy commands the 6 arm joints and a single
    /// hand-closure scalar that interpolates all 20 DG5F finger joints between the
    /// prefab's open pose and the validated <see cref="Dg5fPicknPlaceSpec.RightFistDeg"/>
    /// power-grasp pose. This component is the sole xDrive writer in the training
    /// scene.
    ///
    /// The episode is a single continuous task (no scripted lift phase): the policy
    /// must approach, close on the cube, satisfy a geometric grasp contract, and then
    /// raise the cube itself.
    /// </summary>
    public sealed class Dg5fPicknPlaceAgent : Agent
    {
        [Header("Scene references")]
        public Rigidbody cubeTarget;
        public Collider cubeCollider;
        public Transform pedestal;
        public Collider pedestalCollider;
        public Transform robotBase;
        public Transform palm;
        public Transform graspPoint;
        public Transform[] fingerTips = new Transform[Dg5fPicknPlaceSpec.FingerCount];
        public PicknPlaceObjectContactSensor[] contactSensors =
            Array.Empty<PicknPlaceObjectContactSensor>();
        public PicknPlaceSurfaceContactSensor[] safetySensors =
            Array.Empty<PicknPlaceSurfaceContactSensor>();
        public PicknPlaceHandSurfaceSensor[] handSurfaceSensors =
            Array.Empty<PicknPlaceHandSurfaceSensor>();

        [Header("Episode")]
        public bool useDeterministicSpawns;
        public int spawnSeed = 12345;
        [Tooltip("Training resets on a successful lift. A live demo instead freezes the arm/hand in place.")]
        public bool endEpisodeOnSuccess = true;

        [Header("Control")]
        public float armDeltaDegPerDecision = 2f;
        public float gripDeltaPerDecision = 0.08f;

        readonly Dictionary<ArticulationBody, float> _initialTargetDeg =
            new Dictionary<ArticulationBody, float>();

        ArticulationBody[] _allJoints;
        ArticulationBody[] _armJoints;
        ArticulationBody[] _handJoints;
        float[] _armTargetDeg;
        float[] _openHandDeg;
        readonly Vector3[] _contactDirections = new Vector3[Dg5fPicknPlaceSpec.ContactPointCount];

        float _closure;
        float _episodeSeconds;
        float _spawnObjectHeight;
        Vector3 _spawnObjectLocalPosition;

        float _previousApproachPotential;
        float _bestTopDownPotential;
        float _bestClosurePotential;
        float _bestContactPotential;
        float _bestGraspPotential;
        float _previousLiftPotential;

        float _graspSeconds;
        float _liftHoldSeconds;
        float _slipSeconds;
        float _bestLiftHeight;
        float _maxObjectTiltDeg;
        float _handSurfaceContactSeconds;
        float _handSurfaceContactSecondsSinceDecision;
        float _sumSquaredArmActionDeltas;
        float _sumGraspPostureAngleDegrees;
        int _armActionDecisionCount;
        int _graspPostureAngleSampleCount;
        int _contactCount;
        Vector3 _contactCentroid;
        readonly float[] _previousArmActions = new float[Dg5fPicknPlaceSpec.ArmJointCount];

        int _objectReleaseFixedSteps;
        bool _hasPreviousArmAction;
        bool _episodeActive;
        bool _graspConfirmed;
        bool _unsafeSurfaceContact;
        bool _resolved;

        System.Random _random;
        StatsRecorder _stats;

        public float CurrentClosure => _closure;
        public float CurrentEpisodeSeconds => _episodeSeconds;
        public bool IsGraspConfirmed => _graspConfirmed;
        public float CurrentGraspSeconds => _graspSeconds;
        public int CurrentContactCount => _contactCount;
        public float CurrentLiftHeight => LiftHeight();
        public float BestLiftHeight => _bestLiftHeight;
        public bool IsEpisodeActive => _episodeActive;
        public Vector3 CurrentObjectLocalPosition =>
            robotBase != null && cubeTarget != null
                ? robotBase.InverseTransformPoint(cubeTarget.position)
                : Vector3.zero;
        public string LastTerminationReason { get; private set; } = "None";

        /// Freezes the arm/hand exactly like a successful lift would (see FinishEpisode),
        /// but on demand — used when the operator flips the live demo to manual teleop.
        public void PauseForManualControl()
        {
            _episodeActive = false;
        }

        public float CurrentArmTargetDeg(int index)
        {
            if (_armTargetDeg == null)
                throw new InvalidOperationException("Agent has not initialized.");
            return _armTargetDeg[index];
        }

        public override void Initialize()
        {
            EnsureResolved();
        }

        void EnsureResolved()
        {
            if (_resolved) return;

            ResolveReferences();
            ResolveJoints();
            ResolveSafetySensors();
            ValidateConfiguration();

            _armTargetDeg = new float[Dg5fPicknPlaceSpec.ArmJointCount];
            _openHandDeg = new float[Dg5fPicknPlaceSpec.HandJointCount];
            foreach (var body in _allJoints)
            {
                try { _initialTargetDeg[body] = body.xDrive.target; }
                catch (Exception) { /* filled in lazily by InitialTargetDeg */ }
            }
            for (int i = 0; i < _handJoints.Length; i++)
                _openHandDeg[i] = InitialTargetDeg(_handJoints[i]);

            MaxStep = 0;
            _random = new System.Random(spawnSeed);
            _stats = Academy.Instance.StatsRecorder;

            _resolved = true;
        }

        void ResolveReferences()
        {
            if (robotBase == null) robotBase = transform;
            if (pedestal == null)
            {
                var found = GameObject.Find("PicknPlacePanel");
                if (found != null) pedestal = found.transform;
            }
            if (pedestalCollider == null && pedestal != null)
                pedestalCollider = pedestal.GetComponent<Collider>();

            var transforms = GetComponentsInChildren<Transform>(true);
            if (palm == null) palm = FindByName(transforms, "rl_dg_palm");
            if (graspPoint == null) graspPoint = FindByName(transforms, "GraspPoint");

            if (fingerTips == null || fingerTips.Length != Dg5fPicknPlaceSpec.FingerCount)
                fingerTips = new Transform[Dg5fPicknPlaceSpec.FingerCount];
            for (int finger = 0; finger < Dg5fPicknPlaceSpec.FingerCount; finger++)
            {
                if (fingerTips[finger] == null)
                    fingerTips[finger] = FindByName(transforms, $"rl_dg_{finger + 1}_tip");
            }

            if (contactSensors == null || contactSensors.Length == 0)
                contactSensors = GetComponentsInChildren<PicknPlaceObjectContactSensor>(true);
            foreach (var sensor in contactSensors)
                if (sensor != null) sensor.targetCollider = cubeCollider;
        }

        static Transform FindByName(IEnumerable<Transform> transforms, string name)
        {
            foreach (var item in transforms)
                if (item.name == name) return item;
            return null;
        }

        void ResolveJoints()
        {
            var bodies = GetComponentsInChildren<ArticulationBody>(true);

            _armJoints = new ArticulationBody[Dg5fPicknPlaceSpec.ArmJointCount];
            for (int i = 0; i < _armJoints.Length; i++)
                _armJoints[i] = FindBody(bodies, Dg5fPicknPlaceSpec.ArmLinks[i]);

            _handJoints = new ArticulationBody[Dg5fPicknPlaceSpec.HandJointCount];
            for (int finger = 1; finger <= Dg5fPicknPlaceSpec.FingerCount; finger++)
                for (int joint = 1; joint <= 4; joint++)
                {
                    int channel = (finger - 1) * 4 + joint - 1;
                    _handJoints[channel] = FindBodyBySuffix(bodies, $"_dg_{finger}_{joint}");
                }

            var all = new List<ArticulationBody>(_armJoints.Length + _handJoints.Length);
            foreach (var body in _armJoints)
                if (body != null) all.Add(body);
            foreach (var body in _handJoints)
                if (body != null) all.Add(body);
            _allJoints = all.ToArray();
        }

        void ResolveSafetySensors()
        {
            if (safetySensors == null || safetySensors.Length == 0)
                safetySensors = GetComponentsInChildren<PicknPlaceSurfaceContactSensor>(true);
            if (handSurfaceSensors == null || handSurfaceSensors.Length == 0)
                handSurfaceSensors = GetComponentsInChildren<PicknPlaceHandSurfaceSensor>(true);
        }

        static ArticulationBody FindBody(IEnumerable<ArticulationBody> bodies, string name)
        {
            foreach (var body in bodies)
                if (body.name == name) return body;
            return null;
        }

        static ArticulationBody FindBodyBySuffix(IEnumerable<ArticulationBody> bodies, string suffix)
        {
            foreach (var body in bodies)
                if (body.name.EndsWith(suffix, StringComparison.Ordinal)) return body;
            return null;
        }

        void ValidateConfiguration()
        {
            if (cubeTarget == null || cubeCollider == null || pedestal == null
                || pedestalCollider == null || robotBase == null || palm == null
                || graspPoint == null)
            {
                throw new InvalidOperationException(
                    "[Dg5fPicknPlaceAgent] Missing cubeTarget/cubeCollider/pedestal/robotBase/palm/graspPoint reference.");
            }
            for (int i = 0; i < _armJoints.Length; i++)
                if (_armJoints[i] == null)
                    throw new InvalidOperationException(
                        $"[Dg5fPicknPlaceAgent] Missing arm joint: {Dg5fPicknPlaceSpec.ArmLinks[i]}");
            for (int i = 0; i < _handJoints.Length; i++)
                if (_handJoints[i] == null)
                    throw new InvalidOperationException(
                        $"[Dg5fPicknPlaceAgent] Missing hand joint channel {i}.");
            for (int i = 0; i < Dg5fPicknPlaceSpec.FingerCount; i++)
                if (fingerTips[i] == null)
                    throw new InvalidOperationException(
                        $"[Dg5fPicknPlaceAgent] Missing fingertip {i}.");
            if (contactSensors == null || contactSensors.Length == 0)
                throw new InvalidOperationException(
                    "[Dg5fPicknPlaceAgent] No cube contact sensors were resolved.");
            for (int index = 0; index < Dg5fPicknPlaceSpec.ContactPointCount; index++)
            {
                bool covered = false;
                foreach (var sensor in contactSensors)
                    if (sensor != null && sensor.contactIndex == index) { covered = true; break; }
                if (!covered)
                    throw new InvalidOperationException(
                        $"[Dg5fPicknPlaceAgent] No cube contact sensor covers contact point {index}.");
            }
            if (safetySensors == null || safetySensors.Length == 0)
                throw new InvalidOperationException(
                    "[Dg5fPicknPlaceAgent] Moving arm-link surface safety sensors are required.");
            if (handSurfaceSensors == null || handSurfaceSensors.Length == 0)
                Debug.LogWarning(
                    "[Dg5fPicknPlaceAgent] No hand-panel contact sensors were resolved; "
                    + "the scrape penalty and contact-time stat will remain zero.",
                    this);
        }

        // ------------------------------------------------------------------ episode

        public override void OnEpisodeBegin()
        {
            EnsureResolved();
            _episodeActive = false;
            Dg5fPicknPlaceSpec.RefreshGraspStage();
            Dg5fPicknPlaceSpec.RefreshCubeWidth();
            Dg5fPicknPlaceSpec.RefreshCubeHeight();
            Dg5fPicknPlaceSpec.RefreshCubeComHeightFraction();
            Dg5fPicknPlaceSpec.RefreshToppleLimit();
            Dg5fPicknPlaceSpec.RefreshTopDownAlignmentPotentialMax();
            Dg5fPicknPlaceSpec.RefreshActionRatePenaltyScale();
            Dg5fPicknPlaceSpec.RefreshHandSurfacePenaltyPerSecond();
            Dg5fPicknPlaceSpec.RefreshGraspPosturePenaltyScale();

            _closure = 0f;
            _episodeSeconds = 0f;
            _graspSeconds = 0f;
            _liftHoldSeconds = 0f;
            _slipSeconds = 0f;
            _bestLiftHeight = 0f;
            _maxObjectTiltDeg = 0f;
            _handSurfaceContactSeconds = 0f;
            _handSurfaceContactSecondsSinceDecision = 0f;
            _sumSquaredArmActionDeltas = 0f;
            _sumGraspPostureAngleDegrees = 0f;
            _armActionDecisionCount = 0;
            _graspPostureAngleSampleCount = 0;
            Array.Clear(_previousArmActions, 0, _previousArmActions.Length);
            _hasPreviousArmAction = false;
            _graspConfirmed = false;
            _unsafeSurfaceContact = false;
            _contactCount = 0;
            _contactCentroid = Vector3.zero;
            _bestClosurePotential = 0f;
            _bestContactPotential = 0f;
            _bestGraspPotential = 0f;
            _previousLiftPotential = 0f;
            LastTerminationReason = "None";

            ResetRobot();
            ResetCubeTarget();
            foreach (var sensor in contactSensors)
                if (sensor != null) sensor.ResetContacts();
            foreach (var sensor in safetySensors)
                if (sensor != null) sensor.ResetContacts();
            foreach (var sensor in handSurfaceSensors)
                if (sensor != null) sensor.ResetContacts();

            _previousApproachPotential = Dg5fPicknPlaceSpec.DirectionalApproachPotential(
                GraspDistance(), PalmFacingAlignment());
            _bestTopDownPotential = TopDownAlignmentPotential();
            _episodeActive = true;
        }

        float InitialTargetDeg(ArticulationBody body)
        {
            if (_initialTargetDeg.TryGetValue(body, out float cached)) return cached;
            float value = body.xDrive.target;
            _initialTargetDeg[body] = value;
            return value;
        }

        void ResetRobot()
        {
            foreach (var body in _allJoints)
            {
                float targetDeg = InitialTargetDeg(body);
                var drive = body.xDrive;
                drive.target = targetDeg;
                body.xDrive = drive;
                body.jointPosition = new ArticulationReducedSpace(targetDeg * Mathf.Deg2Rad);
                body.jointVelocity = new ArticulationReducedSpace(0f);
            }

            for (int i = 0; i < _armJoints.Length; i++)
            {
                float initial = InitialTargetDeg(_armJoints[i]);
                _armTargetDeg[i] = Mathf.Clamp(
                    initial, Dg5fPicknPlaceSpec.ArmSafeMinDeg[i], Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]);
            }
            ApplyArmTargets();
            _closure = 0f;
            ApplyGripTargets();
        }

        void ResetCubeTarget()
        {
            Vector3 localPosition = Vector3.zero;
            bool sampled = false;
            for (int attempt = 0; attempt < 32 && !sampled; attempt++)
            {
                localPosition = Dg5fPicknPlaceSpec.SpawnCubeLocalPosition(
                    Next01(), Next01(), Dg5fPicknPlaceSpec.CurrentCubeHeight);
                sampled = Dg5fPicknPlaceSpec.IsValidCubeSpawn(
                    localPosition,
                    Dg5fPicknPlaceSpec.CurrentCubeWidth,
                    Dg5fPicknPlaceSpec.CurrentCubeHeight);
            }
            if (!sampled)
                throw new InvalidOperationException(
                    "[Dg5fPicknPlaceAgent] Could not sample a valid cube spawn pose.");

            if (!cubeTarget.isKinematic)
            {
                cubeTarget.linearVelocity = Vector3.zero;
                cubeTarget.angularVelocity = Vector3.zero;
            }
            cubeTarget.isKinematic = true;
            cubeTarget.useGravity = false;
            // Resize while kinematic and still parked away from the hand: rescaling a
            // live Rigidbody that is touching the fingers makes the solver explode.
            ApplyCubeSize();
            cubeTarget.position = robotBase.TransformPoint(localPosition);
            // Yaw only: the cube must always start upright so "lift" is measured
            // against a repeatable pose.
            cubeTarget.rotation = robotBase.rotation * Quaternion.AngleAxis(Next01() * 360f, Vector3.up);
            Physics.SyncTransforms();

            _spawnObjectLocalPosition = localPosition;
            _spawnObjectHeight = cubeTarget.position.y;
            // Articulation collider transforms lag direct jointPosition writes by one
            // physics step. Keep the cube kinematic for that step, then release it.
            _objectReleaseFixedSteps = 2;
        }

        /// Applies the current cube-size lesson to the cube's scale and mass.
        void ApplyCubeSize()
        {
            float width = Dg5fPicknPlaceSpec.CurrentCubeWidth;
            cubeTarget.transform.localScale =
                new Vector3(width, Dg5fPicknPlaceSpec.CurrentCubeHeight, width);
            cubeTarget.mass = Dg5fPicknPlaceSpec.CurrentCubeMass;
            // Rigidbody COM uses the unit cube's unscaled local space.
            cubeTarget.centerOfMass = Dg5fPicknPlaceSpec.CurrentCubeCenterOfMassLocal;
        }

        void ReleaseCubeTarget()
        {
            cubeTarget.isKinematic = false;
            cubeTarget.useGravity = true;
            cubeTarget.linearVelocity = Vector3.zero;
            cubeTarget.angularVelocity = Vector3.zero;
            // Re-latch every baseline after the settle step so the two throwaway
            // physics frames cannot leak shaping reward into the episode.
            _spawnObjectHeight = cubeTarget.position.y;
            _spawnObjectLocalPosition = robotBase.InverseTransformPoint(cubeTarget.position);
            _previousApproachPotential = Dg5fPicknPlaceSpec.DirectionalApproachPotential(
                GraspDistance(), PalmFacingAlignment());
            _bestTopDownPotential = TopDownAlignmentPotential();
            _previousLiftPotential = 0f;
        }

        float Next01()
        {
            if (!useDeterministicSpawns) return UnityEngine.Random.value;
            return (float)_random.NextDouble();
        }

        // ------------------------------------------------------------- observations

        public override void CollectObservations(VectorSensor sensor)
        {
            if (cubeTarget == null || robotBase == null || palm == null || graspPoint == null
                || _armJoints == null || fingerTips == null || contactSensors == null
                || !HasFinitePhysicsState())
            {
                for (int i = 0; i < Dg5fPicknPlaceSpec.ObservationSize; i++)
                    sensor.AddObservation(0f);
                return;
            }

            // 0..5: normalized arm joint positions.
            for (int i = 0; i < _armJoints.Length; i++)
            {
                float positionDeg = FirstOrZero(_armJoints[i].jointPosition) * Mathf.Rad2Deg;
                sensor.AddObservation(Dg5fPicknPlaceSpec.NormalizeJoint(
                    positionDeg, Dg5fPicknPlaceSpec.ArmSafeMinDeg[i], Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]));
            }

            // 6..11: normalized arm joint velocities.
            for (int i = 0; i < _armJoints.Length; i++)
                sensor.AddObservation(
                    Mathf.Clamp(FirstOrZero(_armJoints[i].jointVelocity) / Mathf.PI, -1f, 1f));

            // 12: hand closure, centred on zero.
            sensor.AddObservation(_closure * 2f - 1f);

            // 13..21: cube state in robot-base coordinates. The offset is measured to
            // the grasp target, i.e. the point the palm should actually reach.
            AddClampedVector(
                sensor,
                robotBase.InverseTransformDirection(GraspTargetPosition() - graspPoint.position),
                1f);
            AddClampedVector(
                sensor, robotBase.InverseTransformDirection(cubeTarget.linearVelocity), 2f);
            AddClampedVector(
                sensor, robotBase.InverseTransformDirection(cubeTarget.angularVelocity), 10f);

            // 22: vertical displacement from the spawn pose (the raw lift signal).
            sensor.AddObservation(
                Mathf.Clamp((cubeTarget.position.y - _spawnObjectHeight) / 0.2f, -1f, 1f));

            // 23..37: each fingertip relative to the cube, in palm coordinates.
            for (int i = 0; i < fingerTips.Length; i++)
                AddClampedVector(
                    sensor,
                    palm.InverseTransformDirection(fingerTips[i].position - cubeTarget.position),
                    0.2f);

            // 38..42: fingertip contact flags.
            for (int i = 0; i < Dg5fPicknPlaceSpec.FingerCount; i++)
                sensor.AddObservation(IsContactActive(i) ? 1f : 0f);

            // 43..48: commanded arm xDrive targets.
            for (int i = 0; i < _armTargetDeg.Length; i++)
                sensor.AddObservation(Dg5fPicknPlaceSpec.NormalizeJoint(
                    _armTargetDeg[i], Dg5fPicknPlaceSpec.ArmSafeMinDeg[i], Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]));

            // 49..56: grasp/lift task state.
            sensor.AddObservation(
                IsContactActive(Dg5fPicknPlaceSpec.PalmContactIndex) ? 1f : 0f);
            sensor.AddObservation(_contactCount / (float)Dg5fPicknPlaceSpec.ContactPointCount);
            sensor.AddObservation(Dg5fPicknPlaceSpec.GraspProgress(_graspSeconds));
            sensor.AddObservation(_graspConfirmed ? 1f : 0f);
            sensor.AddObservation(Dg5fPicknPlaceSpec.LiftProgress(LiftHeight()));
            sensor.AddObservation(Mathf.Clamp01(
                _liftHoldSeconds / Dg5fPicknPlaceSpec.CurrentLiftHoldSeconds));
            sensor.AddObservation(Mathf.Clamp01(
                GraspDistance() / Dg5fPicknPlaceSpec.MaximumObjectDistance));
            sensor.AddObservation(Mathf.Clamp01(
                _episodeSeconds / Dg5fPicknPlaceSpec.EpisodeTimeoutSeconds));
        }

        static void AddClampedVector(VectorSensor sensor, Vector3 value, float scale)
        {
            sensor.AddObservation(Mathf.Clamp(value.x / scale, -1f, 1f));
            sensor.AddObservation(Mathf.Clamp(value.y / scale, -1f, 1f));
            sensor.AddObservation(Mathf.Clamp(value.z / scale, -1f, 1f));
        }

        static float FirstOrZero(ArticulationReducedSpace values)
        {
            try { return values[0]; }
            catch (IndexOutOfRangeException) { return 0f; }
        }

        // ------------------------------------------------------------------ actions

        public override void OnActionReceived(ActionBuffers actions)
        {
            var continuous = actions.ContinuousActions;
            if (continuous.Length != Dg5fPicknPlaceSpec.ActionSize)
                throw new InvalidOperationException(
                    $"Expected {Dg5fPicknPlaceSpec.ActionSize} continuous actions, got {continuous.Length}.");
            if (!_episodeActive || _objectReleaseFixedSteps > 0) return;

            AddReward(Dg5fPicknPlaceSpec.DecisionTimePenalty);
            ScoreApproachProgress();
            float handSurfaceContactSeconds = _handSurfaceContactSecondsSinceDecision;
            _handSurfaceContactSecondsSinceDecision = 0f;
            AddReward(Dg5fPicknPlaceSpec.HandSurfaceContactPenalty(
                handSurfaceContactSeconds, _graspConfirmed));
            float graspDistance = GraspDistance();
            float graspPostureAngleDegrees = Dg5fPicknPlaceSpec.TopDownAngleDegrees(TopDownAlignment());
            AddReward(Dg5fPicknPlaceSpec.GraspPosturePenalty(
                graspPostureAngleDegrees, graspDistance, _graspConfirmed));
            if (!_graspConfirmed
                && Dg5fPicknPlaceSpec.IsFinite(graspDistance)
                && Dg5fPicknPlaceSpec.IsFinite(graspPostureAngleDegrees)
                && graspDistance <= Dg5fPicknPlaceSpec.GraspReadyDistance)
            {
                _sumGraspPostureAngleDegrees += graspPostureAngleDegrees;
                _graspPostureAngleSampleCount++;
            }

            bool nearObject = Dg5fPicknPlaceSpec.UsesNearObjectControl(graspDistance);
            float actionScale = nearObject ? Dg5fPicknPlaceSpec.NearObjectArmDeltaScale : 1f;
            float sumSquaredArmActions = 0f;
            float sumSquaredArmActionDeltas = 0f;
            for (int i = 0; i < _armTargetDeg.Length; i++)
            {
                float action = Mathf.Clamp(continuous[i], -1f, 1f);
                sumSquaredArmActions += action * action;
                if (_hasPreviousArmAction)
                {
                    float actionDelta = action - _previousArmActions[i];
                    sumSquaredArmActionDeltas += actionDelta * actionDelta;
                }
                _previousArmActions[i] = action;
                _armTargetDeg[i] = Mathf.Clamp(
                    _armTargetDeg[i] + action * armDeltaDegPerDecision * actionScale,
                    Dg5fPicknPlaceSpec.ArmSafeMinDeg[i], Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i]);
            }
            if (_hasPreviousArmAction)
            {
                AddReward(Dg5fPicknPlaceSpec.ArmActionRatePenalty(sumSquaredArmActionDeltas));
                _sumSquaredArmActionDeltas += sumSquaredArmActionDeltas;
            }
            _hasPreviousArmAction = true;
            _armActionDecisionCount++;
            if (nearObject)
                AddReward(Dg5fPicknPlaceSpec.NearObjectActionPenalty(sumSquaredArmActions));
            ApplyArmTargets();

            // Grip: closing pays only within GraspReadyDistance of the cube, and only
            // as a new-best potential so the fingers cannot be pumped for reward.
            float delta = Mathf.Clamp(continuous[6], -1f, 1f) * gripDeltaPerDecision;
            float newClosure = Mathf.Clamp01(_closure + delta);
            bool readyToGrasp = IsReadyToGrasp();
            AddReward(Dg5fPicknPlaceSpec.ClosureFarPenalty(newClosure - _closure, readyToGrasp));
            float closurePotential = Dg5fPicknPlaceSpec.ClosurePotential(newClosure, readyToGrasp);
            AddReward(Dg5fPicknPlaceSpec.NewBestPotentialDelta(_bestClosurePotential, closurePotential));
            _bestClosurePotential = Mathf.Max(_bestClosurePotential, closurePotential);
            _closure = newClosure;
            ApplyGripTargets();

            if (Dg5fPicknPlaceSpec.IsClosedHandAscent(
                    GraspPointHeightAbovePanel(), _closure, _graspConfirmed))
            {
                AddReward(Dg5fPicknPlaceSpec.ClosedHandAscentPenalty);
            }
        }

        bool IsReadyToGrasp()
        {
            return GraspDistance() <= Dg5fPicknPlaceSpec.GraspReadyDistance;
        }

        void ApplyArmTargets()
        {
            for (int i = 0; i < _armJoints.Length; i++)
            {
                var drive = _armJoints[i].xDrive;
                drive.target = Mathf.Clamp(_armTargetDeg[i], drive.lowerLimit, drive.upperLimit);
                _armJoints[i].xDrive = drive;
            }
        }

        void ApplyGripTargets()
        {
            for (int i = 0; i < _handJoints.Length; i++)
            {
                var drive = _handJoints[i].xDrive;
                float target = Mathf.Lerp(
                    _openHandDeg[i], Dg5fPicknPlaceSpec.RightFistDeg[i], Mathf.Clamp01(_closure));
                drive.target = Mathf.Clamp(target, drive.lowerLimit, drive.upperLimit);
                _handJoints[i].xDrive = drive;
            }
        }

        // ------------------------------------------------------------------ physics

        void FixedUpdate()
        {
            if (!_resolved)
            {
                // A ForcedFullReset can invoke OnEpisodeBegin before the robot
                // hierarchy is fully built. Retry every tick; once resolved, start the
                // episode OnEpisodeBegin could not complete earlier.
                EnsureResolved();
                if (!_resolved) return;
                OnEpisodeBegin();
                return;
            }
            if (!_episodeActive || cubeTarget == null || robotBase == null) return;

            if (_objectReleaseFixedSteps > 0)
            {
                _objectReleaseFixedSteps--;
                if (_objectReleaseFixedSteps == 0) ReleaseCubeTarget();
                return;
            }

            if (!HasFinitePhysicsState())
            {
                FinishEpisode(false, "NonFinitePhysics");
                return;
            }

            if (_unsafeSurfaceContact || HasUnsafeSurfaceContact())
            {
                FinishEpisode(false, "UnsafeSurfaceContact");
                return;
            }

            Vector3 objectLocalPosition = robotBase.InverseTransformPoint(cubeTarget.position);
            if (Dg5fPicknPlaceSpec.IsOutOfBounds(
                    objectLocalPosition, Dg5fPicknPlaceSpec.SupportTopHeight,
                    Dg5fPicknPlaceSpec.CurrentCubeHalfHeight))
            {
                FinishEpisode(false, "ObjectOutOfBounds");
                return;
            }

            if (Dg5fPicknPlaceSpec.IsPushedAway(
                    objectLocalPosition, _spawnObjectLocalPosition, _graspConfirmed))
            {
                FinishEpisode(false, "ObjectPushedAway");
                return;
            }

            float objectTiltDeg = ObjectTiltDegrees();
            _maxObjectTiltDeg = Mathf.Max(_maxObjectTiltDeg, objectTiltDeg);
            // A toppled cube is unliftable and used to be a profitable dead end.
            if (Dg5fPicknPlaceSpec.IsToppled(objectTiltDeg, _graspConfirmed))
            {
                FinishEpisode(false, "ObjectToppled");
                return;
            }

            _episodeSeconds += Time.fixedDeltaTime;
            if (HasHandSurfaceContact())
            {
                _handSurfaceContactSeconds += Time.fixedDeltaTime;
                _handSurfaceContactSecondsSinceDecision += Time.fixedDeltaTime;
            }
            UpdateContacts();

            if (!_graspConfirmed)
                UpdateGraspProgress();
            else if (UpdateLiftProgress())
                return;

            if (Dg5fPicknPlaceSpec.ReachedEpisodeTimeout(_episodeSeconds))
                FinishEpisode(false, "Timeout");
        }

        bool IsContactActive(int contactIndex)
        {
            if (contactSensors == null) return false;
            foreach (var sensor in contactSensors)
                if (sensor != null && sensor.contactIndex == contactIndex && sensor.IsTouching)
                    return true;
            return false;
        }

        void UpdateContacts()
        {
            _contactCount = 0;
            Vector3 centroidSum = Vector3.zero;
            Vector3 objectCenter = cubeTarget.position;

            for (int i = 0; i < Dg5fPicknPlaceSpec.ContactPointCount; i++)
            {
                if (!IsContactActive(i)) continue;
                Transform contactTransform =
                    i == Dg5fPicknPlaceSpec.PalmContactIndex ? palm : fingerTips[i];
                if (contactTransform == null) continue;

                Vector3 position = contactTransform.position;
                centroidSum += position;
                _contactDirections[_contactCount] = position - objectCenter;
                _contactCount++;
            }

            _contactCentroid = _contactCount > 0 ? centroidSum / _contactCount : objectCenter;
        }

        void UpdateGraspProgress()
        {
            bool candidate = Dg5fPicknPlaceSpec.IsGraspCandidate(
                _contactCount, _contactDirections, cubeTarget.position, _contactCentroid, _closure);

            if (!candidate)
            {
                // A grasp has to be continuous. Any frame that breaks the contract
                // restarts the dwell so contact flicker cannot accumulate into a
                // confirmed grasp.
                _graspSeconds = 0f;
                return;
            }

            // Dense credit for the number of fingers on the cube. New-best only, so
            // repeatedly tapping the cube cannot farm reward.
            float contactPotential = Dg5fPicknPlaceSpec.ContactPotential(_contactCount);
            AddReward(Dg5fPicknPlaceSpec.NewBestPotentialDelta(_bestContactPotential, contactPotential));
            _bestContactPotential = Mathf.Max(_bestContactPotential, contactPotential);

            _graspSeconds += Time.fixedDeltaTime;

            // Partial credit for holding a valid grasp, again new-best so the total
            // paid for reaching a confirmed grasp is exactly GraspConfirmReward.
            float graspPotential =
                Dg5fPicknPlaceSpec.GraspConfirmReward * Dg5fPicknPlaceSpec.GraspProgress(_graspSeconds);
            AddReward(Dg5fPicknPlaceSpec.NewBestPotentialDelta(_bestGraspPotential, graspPotential));
            _bestGraspPotential = Mathf.Max(_bestGraspPotential, graspPotential);

            if (Dg5fPicknPlaceSpec.IsGraspConfirmed(_graspSeconds))
            {
                _graspConfirmed = true;
                _slipSeconds = 0f;
                _liftHoldSeconds = 0f;
                _previousLiftPotential = Dg5fPicknPlaceSpec.LiftPotential(LiftHeight());
            }
        }

        /// Returns true when the episode ended inside this call.
        bool UpdateLiftProgress()
        {
            float liftHeight = LiftHeight();
            _bestLiftHeight = Mathf.Max(_bestLiftHeight, liftHeight);

            // Plain (not new-best) potential: the cube has to stay up. Letting it
            // sink hands the shaping back, which is the gradient a drop deserves.
            float liftPotential = Dg5fPicknPlaceSpec.LiftPotential(liftHeight);
            AddReward(Dg5fPicknPlaceSpec.PotentialDelta(_previousLiftPotential, liftPotential));
            _previousLiftPotential = liftPotential;

            bool stillGrasped = Dg5fPicknPlaceSpec.IsGraspCandidate(
                _contactCount, _contactDirections, cubeTarget.position, _contactCentroid, _closure);
            _slipSeconds = stillGrasped ? 0f : _slipSeconds + Time.fixedDeltaTime;

            // Dropped: contact lost past the grace window AND the cube has fallen
            // back toward the table. Losing contact while the cube is still up is a
            // re-grip, not a drop.
            if (_slipSeconds > Dg5fPicknPlaceSpec.SlipGraceSeconds
                && liftHeight < _bestLiftHeight * 0.3f)
            {
                FinishEpisode(false, "Dropped");
                return true;
            }

            float objectSpeed = cubeTarget.linearVelocity.magnitude;
            _liftHoldSeconds = Dg5fPicknPlaceSpec.IsStableLift(liftHeight, objectSpeed)
                ? _liftHoldSeconds + Time.fixedDeltaTime
                : 0f;

            if (Dg5fPicknPlaceSpec.IsLiftComplete(_liftHoldSeconds))
            {
                FinishEpisode(true, "Success", endEpisodeOnSuccess);
                return true;
            }
            return false;
        }

        void ScoreApproachProgress()
        {
            // Once the cube is grasped the hand is supposed to carry it away from
            // where it started, so the approach terms are frozen at that point.
            if (_graspConfirmed) return;

            float currentApproach = Dg5fPicknPlaceSpec.DirectionalApproachPotential(
                GraspDistance(), PalmFacingAlignment());
            AddReward(Dg5fPicknPlaceSpec.PotentialDelta(_previousApproachPotential, currentApproach));
            _previousApproachPotential = currentApproach;

            float currentTopDown = TopDownAlignmentPotential();
            AddReward(Dg5fPicknPlaceSpec.NewBestPotentialDelta(_bestTopDownPotential, currentTopDown));
            _bestTopDownPotential = Mathf.Max(_bestTopDownPotential, currentTopDown);
        }

        bool HasFinitePhysicsState()
        {
            if (!Dg5fPicknPlaceSpec.IsFinite(cubeTarget.position)
                || !Dg5fPicknPlaceSpec.IsFinite(cubeTarget.linearVelocity)
                || !Dg5fPicknPlaceSpec.IsFinite(cubeTarget.angularVelocity))
                return false;

            Quaternion rotation = cubeTarget.rotation;
            if (!Dg5fPicknPlaceSpec.IsFinite(rotation.x) || !Dg5fPicknPlaceSpec.IsFinite(rotation.y)
                || !Dg5fPicknPlaceSpec.IsFinite(rotation.z) || !Dg5fPicknPlaceSpec.IsFinite(rotation.w))
                return false;

            foreach (var joint in _allJoints)
            {
                if (!Dg5fPicknPlaceSpec.IsFinite(FirstOrZero(joint.jointPosition))
                    || !Dg5fPicknPlaceSpec.IsFinite(FirstOrZero(joint.jointVelocity))
                    || !Dg5fPicknPlaceSpec.IsFinite(joint.xDrive.target))
                    return false;
            }
            return true;
        }

        bool HasUnsafeSurfaceContact()
        {
            foreach (var sensor in safetySensors)
                if (sensor != null && sensor.HasUnsafeContact) return true;
            return false;
        }

        bool HasHandSurfaceContact()
        {
            if (handSurfaceSensors == null) return false;
            foreach (var sensor in handSurfaceSensors)
                if (sensor != null && sensor.IsTouching) return true;
            return false;
        }

        public void NotifyUnsafeSurfaceContact(Collider surface)
        {
            if (surface == pedestalCollider) _unsafeSurfaceContact = true;
        }

        void FinishEpisode(bool success, string reason, bool endEpisode = true)
        {
            if (!_episodeActive) return;
            _episodeActive = false;
            ScoreApproachProgress();

            if (success)
                AddReward(Dg5fPicknPlaceSpec.LiftSuccessReward);
            else
                AddReward(Dg5fPicknPlaceSpec.FailurePenalty(reason));

            RecordOutcome(success, reason);
            if (endEpisode) EndEpisode();
        }

        void RecordOutcome(bool success, string reason)
        {
            LastTerminationReason = reason;
            if (_stats == null) return;

            _stats.Add("PicknPlace/Success", success ? 1f : 0f, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/GraspConfirmed", _graspConfirmed ? 1f : 0f, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/GraspSeconds", _graspSeconds, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/ContactCount", _contactCount, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/FinalDistanceMeters", GraspDistance(), StatAggregationMethod.Average);
            _stats.Add("PicknPlace/BestLiftHeight", _bestLiftHeight, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/FinalLiftHeight", LiftHeight(), StatAggregationMethod.Average);
            _stats.Add("PicknPlace/ObjectTiltDegrees", ObjectTiltDegrees(), StatAggregationMethod.Average);
            _stats.Add("PicknPlace/MaxObjectTiltDegrees", _maxObjectTiltDeg, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/LiftHoldSeconds", _liftHoldSeconds, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/CompletionSeconds", _episodeSeconds, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/FinalClosure", _closure, StatAggregationMethod.Average);
            _stats.Add("PicknPlace/HandSurfaceContactSeconds", _handSurfaceContactSeconds,
                StatAggregationMethod.Average);
            _stats.Add(
                "PicknPlace/TopDownAngleDegrees",
                Dg5fPicknPlaceSpec.TopDownAngleDegrees(TopDownAlignment()),
                StatAggregationMethod.Average);
            _stats.Add(
                "PicknPlace/GraspPostureAngleDegrees",
                _graspPostureAngleSampleCount > 0
                    ? _sumGraspPostureAngleDegrees / _graspPostureAngleSampleCount
                    : 0f,
                StatAggregationMethod.Average);
            _stats.Add(
                "PicknPlace/MeanArmActionRate",
                _armActionDecisionCount > 0
                    ? _sumSquaredArmActionDeltas / _armActionDecisionCount
                    : 0f,
                StatAggregationMethod.Average);
            _stats.Add("Curriculum/GraspStage", Dg5fPicknPlaceSpec.CurrentGraspStage,
                StatAggregationMethod.Average);
            _stats.Add("Curriculum/CubeWidth", Dg5fPicknPlaceSpec.CurrentCubeWidth,
                StatAggregationMethod.Average);
            _stats.Add("Curriculum/CubeHeight", Dg5fPicknPlaceSpec.CurrentCubeHeight,
                StatAggregationMethod.Average);
            if (!success)
                _stats.Add($"Failure/{reason}", 1f, StatAggregationMethod.Sum);
        }

        // ------------------------------------------------------------------ geometry

        /// Where the palm grasp volume should end up: on the cube axis, 2.0 cm below
        /// its top face rather than at its geometric centre (see the spec constant).
        Vector3 GraspTargetPosition()
        {
            if (cubeTarget == null) return Vector3.zero;
            Vector3 up = robotBase != null ? robotBase.up : Vector3.up;
            return cubeTarget.position + up * Dg5fPicknPlaceSpec.CurrentGraspTargetHeightOffset;
        }

        float GraspDistance()
        {
            if (graspPoint == null || cubeTarget == null) return float.PositiveInfinity;
            return Vector3.Distance(graspPoint.position, GraspTargetPosition());
        }

        float LiftHeight()
        {
            if (cubeTarget == null) return 0f;
            return Dg5fPicknPlaceSpec.LiftHeight(cubeTarget.position.y, _spawnObjectHeight);
        }

        float ObjectTiltDegrees()
        {
            if (cubeTarget == null || robotBase == null) return 0f;
            return Dg5fPicknPlaceSpec.ObjectTiltDegrees(cubeTarget.transform.up, robotBase.up);
        }

        float GraspPointHeightAbovePanel()
        {
            if (graspPoint == null || pedestalCollider == null) return 0f;
            return graspPoint.position.y - pedestalCollider.bounds.max.y;
        }

        float PalmFacingAlignment()
        {
            if (graspPoint == null || palm == null || cubeTarget == null) return -1f;
            return Dg5fPicknPlaceSpec.PalmFacingAlignment(
                graspPoint.forward, GraspTargetPosition() - palm.position);
        }

        float TopDownAlignment()
        {
            if (graspPoint == null || robotBase == null) return -1f;
            return Dg5fPicknPlaceSpec.TopDownAlignment(graspPoint.forward, robotBase.up);
        }

        float TopDownAlignmentPotential()
        {
            if (graspPoint == null || cubeTarget == null || robotBase == null) return 0f;
            float heightAboveObject = Vector3.Dot(
                graspPoint.position - GraspTargetPosition(), robotBase.up);
            return Dg5fPicknPlaceSpec.TopDownAlignmentPotential(
                GraspDistance(), heightAboveObject, TopDownAlignment());
        }

        // ---------------------------------------------------------------- heuristic

        public override void Heuristic(in ActionBuffers actionsOut)
        {
            var actions = actionsOut.ContinuousActions;
            for (int i = 0; i < actions.Length; i++) actions[i] = 0f;

#if ENABLE_LEGACY_INPUT_MANAGER
            actions[0] = Axis(KeyCode.Q, KeyCode.A);
            actions[1] = Axis(KeyCode.W, KeyCode.S);
            actions[2] = Axis(KeyCode.E, KeyCode.D);
            actions[3] = Axis(KeyCode.R, KeyCode.F);
            actions[4] = Axis(KeyCode.T, KeyCode.G);
            actions[5] = Axis(KeyCode.Y, KeyCode.H);
            actions[6] = Axis(KeyCode.Space, KeyCode.LeftShift);
#endif
        }

#if ENABLE_LEGACY_INPUT_MANAGER
        static float Axis(KeyCode positive, KeyCode negative)
        {
            return (Input.GetKey(positive) ? 1f : 0f) - (Input.GetKey(negative) ? 1f : 0f);
        }
#endif
    }
}
