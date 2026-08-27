using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// PicknPlace 라이브 데모(Pipeline_Demo_GraspLift)의 수동(텔레옵) 모드에서 사람이 팔을
    /// 조종하게 해준다 — GraspLift의 GraspLiftTeleopNudge와 완전히 동일한 조작감(높이 슬라이더 +
    /// 화면 조이스틱, ArmTargetIK로 위치 유지)을 확정 하드웨어(UR16e + 오른손, Dg5fPicknPlaceAgent)로
    /// 그대로 옮긴 것. 세부 설계 근거(스폰 반경 전체를 덮는 범위, 손목을 수평 고정하지 않는 이유)는
    /// GraspLiftTeleopNudge의 문서 주석 참고 — 태스크 구조가 동일해 그대로 적용된다.
    /// </summary>
    public sealed class PicknPlaceTeleopNudge : MonoBehaviour
    {
        public Dg5fPicknPlaceAgent agent;
        public ArmTargetIK armIK;
        public HandSliderUI armSliderUI;

        [Tooltip("Game 뷰에 조절 UI(OnGUI)를 그릴지 여부")]
        public bool showControlUI = true;
        [Tooltip("기준점 위/아래로 조절 가능한 범위[m] — 스폰 반경 전체를 덮도록 nudge보다 크다")]
        public float maxHeightOffset = 0.5f;
        [Tooltip("기준점 기준 수평(로봇 기준 좌우/전후)으로 조절 가능한 최대 반경[m]")]
        public float maxHorizontalOffset = 0.6f;
        [Tooltip("조이스틱을 끝까지 밀었을 때 수평 이동 속도[m/s]")]
        public float horizontalMoveSpeed = 0.05f;

        const float JoystickSize = 110f;
        const float JoystickKnobSize = 26f;

        Transform _ikTarget;
        Vector3 _basePosition;
        float _heightOffset;
        Vector2 _horizontalOffset; // (right, forward)
        Vector2 _joystickInput;    // -1..1 per axis, read in FixedUpdate
        bool _dragging;
        bool _active;

        public bool IsActive => _active;

        void Awake()
        {
            if (agent == null) agent = GetComponent<Dg5fPicknPlaceAgent>();
            if (armIK == null) armIK = GetComponent<ArmTargetIK>();
            if (armSliderUI == null) armSliderUI = GetComponent<HandSliderUI>();

            // ArmTargetIK/HandSliderUI는 원래 사람이 직접 조작하려고 만든 컴포넌트라 자체 OnGUI
            // 패널이 있다 — 이 스크립트가 대신 조작하므로 그 패널들은 항상 숨긴다.
            if (armIK != null) armIK.showUI = false;
            if (armSliderUI != null) armSliderUI.showUI = false;

            _ikTarget = new GameObject("PicknPlaceTeleopNudgeTarget").transform;
        }

        void FixedUpdate()
        {
            if (!_active) return;

            Vector3 up = agent.robotBase != null ? agent.robotBase.up : Vector3.up;
            Vector3 right = agent.robotBase != null ? agent.robotBase.right : Vector3.right;
            Vector3 forward = agent.robotBase != null ? agent.robotBase.forward : Vector3.forward;

            if (_joystickInput.sqrMagnitude > 1e-6f)
            {
                Vector2 delta = _joystickInput * horizontalMoveSpeed * Time.fixedDeltaTime;
                _horizontalOffset += delta;
                if (_horizontalOffset.magnitude > maxHorizontalOffset)
                    _horizontalOffset = _horizontalOffset.normalized * maxHorizontalOffset;
            }

            _ikTarget.position = _basePosition
                + up * _heightOffset
                + right * _horizontalOffset.x
                + forward * _horizontalOffset.y;
        }

        /// PicknPlaceControlModeSwitcher가 자동/수동 전환 시 직접 호출한다.
        public void SetActive(bool active)
        {
            _active = active;
            if (active)
            {
                Transform endEffector = armIK != null ? armIK.endEffector : null;
                if (endEffector == null && agent != null) endEffector = agent.graspPoint;
                _basePosition = endEffector != null ? endEffector.position : transform.position;
                _heightOffset = 0f;
                _horizontalOffset = Vector2.zero;
                _joystickInput = Vector2.zero;
                _dragging = false;
                _ikTarget.position = _basePosition;

                if (armSliderUI != null)
                {
                    armSliderUI.driveHandJoints = false;
                    // 켜기 직전 실제 자세로 재동기화해야 팔이 튀지 않는다.
                    armSliderUI.ResyncArmValuesFromCurrentPose();
                    armSliderUI.enabled = true;
                }
                if (armIK != null)
                {
                    armIK.target = _ikTarget;
                    armIK.enableIK = true;
                    // 조이스틱이 타겟을 느리게 계속 옮기는 상황에서는 도달/정체 안전장치가
                    // "다 왔다"로 오판해 멈췄다 확 움직이는 끊김을 만든다 — 텔레옵 중엔 끈다.
                    armIK.ignoreArrivalAndStallGating = true;
                    // 손목을 특정 각도로 강제하지 않는다 — 6관절 전부 위치 CCD에 참여시켜
                    // 손이 자연스러운(필요하면 기운) 각도로 다가가게 둔다.
                    armIK.positionJointCount = -1;
                    armIK.enabled = true;
                }
            }
            else
            {
                if (armIK != null)
                {
                    armIK.enabled = false;
                    armIK.ignoreArrivalAndStallGating = false;
                    armIK.positionJointCount = -1;
                }
                if (armSliderUI != null) armSliderUI.enabled = false;
            }
        }

        void OnGUI()
        {
            if (!showControlUI || !_active) return;

            GUILayout.BeginArea(new Rect(Screen.width - 260, Screen.height - 210, 250, 120), GUI.skin.box);
            GUILayout.Label($"손 높이: {_heightOffset * 100f:+0.0;-0.0}cm");
            float nextHeight = GUILayout.HorizontalSlider(_heightOffset, -maxHeightOffset, maxHeightOffset);
            if (!Mathf.Approximately(nextHeight, _heightOffset)) _heightOffset = nextHeight;
            GUILayout.Label($"수평 이동: ({_horizontalOffset.x * 100f:F1}, {_horizontalOffset.y * 100f:F1})cm");
            GUILayout.EndArea();

            DrawJoystick();
        }

        void DrawJoystick()
        {
            var joyRect = new Rect(Screen.width - 260 + 62f, Screen.height - 210 - JoystickSize - 10f,
                JoystickSize, JoystickSize);
            GUI.Box(joyRect, "이동 (드래그)");
            Vector2 center = new Vector2(joyRect.x + joyRect.width / 2f, joyRect.y + joyRect.height / 2f);
            float maxRadius = joyRect.width / 2f - JoystickKnobSize / 2f;

            Event e = Event.current;
            if (e.type == EventType.MouseDown && joyRect.Contains(e.mousePosition))
                _dragging = true;
            else if (e.type == EventType.MouseUp)
                _dragging = false;

            Vector2 knobOffset = Vector2.zero;
            if (_dragging)
            {
                knobOffset = (Vector2)e.mousePosition - center;
                if (knobOffset.magnitude > maxRadius) knobOffset = knobOffset.normalized * maxRadius;
            }
            // 화면 아래쪽(+y)으로 드래그하면 로봇 기준 앞쪽(+z)으로 가도록 y축 부호를 뒤집는다.
            _joystickInput = _dragging
                ? new Vector2(knobOffset.x / maxRadius, -knobOffset.y / maxRadius)
                : Vector2.zero;

            Vector2 knobPos = center + knobOffset;
            GUI.Box(new Rect(knobPos.x - JoystickKnobSize / 2f, knobPos.y - JoystickKnobSize / 2f,
                JoystickKnobSize, JoystickKnobSize), "");
        }

        void OnDestroy()
        {
            if (_ikTarget != null) Destroy(_ikTarget.gameObject);
        }
    }
}
