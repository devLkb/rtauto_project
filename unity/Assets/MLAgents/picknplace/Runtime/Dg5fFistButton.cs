using System;
using System.Collections.Generic;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Pipeline_Demo_GraspLift 수동 모드에서, 웹캠 손 트래킹 없이도 DG-5F 오른손을 한 번에
    /// 주먹 쥐기/펴기 하는 데모용 버튼. 관절은 Dg5fPicknPlaceAgent와 동일한 규칙
    /// (ArticulationBody 이름이 "_dg_{finger}_{joint}"로 끝남)으로 찾고, 목표 포즈는
    /// Dg5fPicknPlaceSpec.RightFistDeg(오른손 URDF용으로 검증된 주먹 포즈)를 그대로 쓴다.
    /// 버튼을 누르는 동안은 이 컴포넌트가 손을 전담해야 하므로, 같은 관절을 건드리는
    /// Dg5fHandDriver/Dg5fReceiver(웹캠 텔레옵)와 자동 정책(Dg5fPicknPlaceAgent)을 잠시 멈춘다.
    /// </summary>
    public sealed class Dg5fFistButton : MonoBehaviour
    {
        public Dg5fPicknPlaceAgent agent;
        public Dg5fHandDriver handDriver;
        public Dg5fReceiver handReceiver;

        [Range(1f, 30f)] public float closeSpeed = 6f;
        public bool showUI = true;

        ArticulationBody[] _handJoints;
        float[] _openDeg;
        float _closure;
        float _targetClosure;
        bool _resolved;
        bool _handDriverWasEnabled;
        bool _handReceiverWasEnabled;

        void Awake()
        {
            if (agent == null) agent = GetComponent<Dg5fPicknPlaceAgent>();
            if (handDriver == null) handDriver = GetComponent<Dg5fHandDriver>();
            if (handReceiver == null) handReceiver = GetComponent<Dg5fReceiver>();
        }

        // 씬 시작 직후, 다른 컴포넌트가 손가락을 움직이기 전에 "펴진 손" 기준 각도를 캡처한다.
        void Start()
        {
            var bodies = GetComponentsInChildren<ArticulationBody>(true);
            _handJoints = new ArticulationBody[Dg5fPicknPlaceSpec.HandJointCount];
            for (int finger = 1; finger <= Dg5fPicknPlaceSpec.FingerCount; finger++)
                for (int joint = 1; joint <= 4; joint++)
                {
                    int channel = (finger - 1) * 4 + joint - 1;
                    _handJoints[channel] = FindBodyBySuffix(bodies, $"_dg_{finger}_{joint}");
                }

            _openDeg = new float[_handJoints.Length];
            for (int i = 0; i < _handJoints.Length; i++)
                if (_handJoints[i] != null)
                    _openDeg[i] = _handJoints[i].xDrive.target;

            _resolved = true;
        }

        static ArticulationBody FindBodyBySuffix(IEnumerable<ArticulationBody> bodies, string suffix)
        {
            foreach (var body in bodies)
                if (body.name.EndsWith(suffix, StringComparison.Ordinal)) return body;
            return null;
        }

        public void SetFist(bool closed)
        {
            _targetClosure = closed ? 1f : 0f;

            if (closed)
            {
                if (handDriver != null) { _handDriverWasEnabled = handDriver.enabled; handDriver.enabled = false; }
                if (handReceiver != null) { _handReceiverWasEnabled = handReceiver.enabled; handReceiver.enabled = false; }
                if (agent != null) agent.PauseForManualControl();
            }
            else
            {
                if (handDriver != null) handDriver.enabled = _handDriverWasEnabled;
                if (handReceiver != null) handReceiver.enabled = _handReceiverWasEnabled;
            }
        }

        void FixedUpdate()
        {
            if (!_resolved) return;
            float t = Mathf.Clamp01(Time.fixedDeltaTime * closeSpeed);
            _closure = Mathf.Lerp(_closure, _targetClosure, t);
            for (int i = 0; i < _handJoints.Length; i++)
            {
                var body = _handJoints[i];
                if (body == null) continue;
                var drive = body.xDrive;
                float target = Mathf.Lerp(_openDeg[i], Dg5fPicknPlaceSpec.RightFistDeg[i], _closure);
                drive.target = Mathf.Clamp(target, drive.lowerLimit, drive.upperLimit);
                body.xDrive = drive;
            }
        }

        void OnGUI()
        {
            if (!showUI) return;
            // 우상단 — 좌상단(PicknPlaceControlModeSwitcher), 좌하단(PicknPlaceDemoCameraSwitcher),
            // 우하단(PicknPlaceTeleopNudge)과 겹치지 않는 유일한 모서리.
            GUILayout.BeginArea(new Rect(Screen.width - 250, 10, 240, 50), GUI.skin.box);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("주먹 쥐기")) SetFist(true);
            if (GUILayout.Button("손 펴기")) SetFist(false);
            GUILayout.EndHorizontal();
            GUILayout.EndArea();
        }
    }
}
