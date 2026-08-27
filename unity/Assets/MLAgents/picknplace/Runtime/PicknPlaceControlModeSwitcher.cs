using UnityEngine;
using Unity.MLAgents;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Pipeline_Demo_GraspLift(확정 하드웨어: UR16e + DG-5F-M-R 오른손)의 자동/수동 전환 토글.
    /// 자동은 Dg5fPicknPlaceAgent 정책(ONNX)이 그대로 팔+손을 움직여 큐브를 잡고 들어올리고,
    /// 수동은 사람이 PicknPlaceTeleopNudge(팔)와 실제 손 트래킹(Dg5fReceiver/Dg5fHandDriver,
    /// vision/dg5f/vision_node_dg5f.py가 UDP로 쏨)으로 직접 조종한다. GraspLift의
    /// GraspLiftControlModeSwitcher와 동일한 OnGUI 버튼 컨벤션을 따른다.
    /// </summary>
    public sealed class PicknPlaceControlModeSwitcher : MonoBehaviour
    {
        public Dg5fPicknPlaceAgent agent;
        public PicknPlaceTeleopNudge armNudge;
        public Dg5fReceiver handReceiver;
        public Dg5fHandDriver handDriver;

        [Tooltip("Game 뷰에 자동/수동 전환 UI(OnGUI)를 그릴지 여부")]
        public bool showModeUI = true;
        [Tooltip("빠른 디지털 트윈 시연은 정책 모델 없이 손/팔 텔레옵부터 사용하므로 Play 시작 시 수동 모드로 진입")]
        public bool startInManualMode = true;
        [Tooltip("켜면 현재 씬 자세를 고정하고 MediaPipe 오른손 손가락만 구동. 끄면 마우스 팔 조작도 활성화")]
        public bool handOnlyManualMode = false;

        bool _isManual;

        public bool IsManual => _isManual;

        void Start()
        {
            if (handOnlyManualMode)
            {
                DisableAutomaticAndArmControl();
                SetManualMode(true);
            }
            else if (startInManualMode)
            {
                SetManualMode(true);
            }
        }

        void DisableAutomaticAndArmControl()
        {
            if (agent != null)
            {
                agent.PauseForManualControl();
                agent.enabled = false;
                DecisionRequester requester = agent.GetComponent<DecisionRequester>();
                if (requester != null) requester.enabled = false;
            }
            if (armNudge != null) armNudge.SetActive(false);
        }

        void FixedUpdate()
        {
            // Agent.OnEpisodeBegin can run after this component's Start and make
            // the policy active again. Keep the ownership contract true on every
            // physics tick so policy actions never overwrite manual IK/UDP drives.
            if (_isManual && agent != null && agent.IsEpisodeActive)
                agent.PauseForManualControl();
        }

        public void SetManualMode(bool manual)
        {
            if (handOnlyManualMode && !manual) return;
            if (manual == _isManual) return;
            _isManual = manual;

            if (manual)
            {
                if (agent != null) agent.PauseForManualControl();
                if (armNudge != null) armNudge.SetActive(!handOnlyManualMode);
                if (handReceiver != null) handReceiver.enabled = true;
                if (handDriver != null) handDriver.enabled = true;
            }
            else
            {
                if (armNudge != null) armNudge.SetActive(false);
                if (handReceiver != null) handReceiver.enabled = false;
                if (handDriver != null) handDriver.enabled = false;
                // 사람이 임의로 옮겨놓은 자세에서 정책을 재개시키는 건 학습 분포 밖이라 위험하다 —
                // 항상 새 시도(에피소드 리셋)로 자동 모드에 복귀한다.
                if (agent != null) agent.EndEpisode();
            }
        }

        void OnGUI()
        {
            if (!showModeUI) return;

            GUILayout.BeginArea(new Rect(10, 10, 240, 96), GUI.skin.box);
            GUILayout.Label("제어 모드");
            if (handOnlyManualMode)
            {
                GUILayout.Label("[MediaPipe 오른손 미러]");
                DrawHandTrackingStatus();
                GUILayout.EndArea();
                return;
            }
            GUILayout.BeginHorizontal();
            if (GUILayout.Button(!_isManual ? "[자동]" : "자동")) SetManualMode(false);
            if (GUILayout.Button(_isManual ? "[수동]" : "수동")) SetManualMode(true);
            GUILayout.EndHorizontal();
            DrawHandTrackingStatus();
            GUILayout.EndArea();
        }

        /// 웹캠만 꽂고 바로 시연하는 흐름에서, 손이 안 움직일 때 원인이 "파이썬 미실행"인지
        /// "포즈 인식 실패"인지 화면만 보고 구분할 수 있게 한다. 콘솔을 열지 않아도 되도록.
        void DrawHandTrackingStatus()
        {
            if (handReceiver == null) return;

            bool live = handReceiver.enabled && handReceiver.secondsSinceLastPacket < 0.5f;
            Color previous = GUI.color;
            GUI.color = live ? Color.green : new Color(1f, 0.65f, 0f);
            GUILayout.Label(live
                ? $"손 트래킹: 수신중 (UDP {handReceiver.ActivePort})"
                : $"손 트래킹: 대기중 (UDP {handReceiver.ActivePort})");
            GUI.color = previous;
            if (!live)
                GUILayout.Label("vision_node_dg5f.py 실행 필요", GUI.skin.label);
        }
    }
}
