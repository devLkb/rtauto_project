using System.Linq;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Pipeline_Demo_GraspLift의 **팔 조작 창구** — UR16e 6축을 관절 각도로 직접 지정하고,
    /// 같은 패널에서 URSim(또는 실물) 연동 방향까지 고른다. 예전에는 이것 말고도
    /// PicknPlaceTeleopNudge(마우스 조이스틱 + 높이 슬라이더의 작업공간 IK)라는 두 번째
    /// 팔 조작 방식이 있었으나 **2026-09-04에 걷어냈다**: URSim 연동은 관절각(RTDE `servoJ`)이
    /// 기준이라 작업공간 IK를 함께 두면 같은 xDrive.target을 두 방식이 다투고, 화면에도
    /// 조이스틱 박스가 하나 더 붙어 HUD가 겹쳤다. 팔 조작 경로는 이 패널 하나로 통일한다.
    ///
    /// 슬라이더 범위는 각 ArticulationBody의 실제 xDrive 한계(URDF 임포트 시 설정된 물리 관절
    /// 한계, UR e-series 전 기종 ±360° — docs/SIM2REAL_ROADMAP.md 참고) 그대로다.
    /// Dg5fPicknPlaceSpec.ArmSafeMinDeg/MaxDeg는 RL 정책 학습용으로 손튜닝된 훨씬 좁은 "그럴듯한
    /// 자세" 봉투라 사람이 직접 조작할 때 굳이 그 안으로 제한할 이유가 없다.
    ///
    /// URSim 연동(arm/ur_rtde_bridge.py 경유)은 방향이 둘이고 **동시에 켜면 되먹임 루프**가 된다
    /// (Unity 목표 → URSim → 실제각 echo → 다시 Unity 목표). 그래서 사람이 컴포넌트 체크박스를
    /// 손으로 여닫는 대신 이 패널이 상호배타를 강제한다 — 손 쪽 Dg5fTwinModeSwitcher와 같은 방침:
    ///   · Unity → URSim : 이 슬라이더가 URSim을 움직인다 (UrArmSender)
    ///   · URSim → Unity : 펜던트 조그/URScript를 Unity가 따라간다 (UrArmTwinDriver)
    /// </summary>
    public sealed class PicknPlaceArmJointPanel : MonoBehaviour
    {
        static readonly string[] JointLabels =
        {
            "Shoulder Pan", "Shoulder Lift", "Elbow", "Wrist 1", "Wrist 2", "Wrist 3"
        };

        public Dg5fPicknPlaceAgent agent;
        [Tooltip("완전 초기화 시 함께 풀어줄 주먹쥐기 버튼(있으면). 비워두면 손 포즈는 " +
                 "그대로 두고 팔+물체만 리셋된다.")]
        public Dg5fFistButton fistButton;

        [Header("URSim / 실물 팔 연동 (arm/ur_rtde_bridge.py)")]
        [Tooltip("Unity → URSim 방향. 비워두면 같은 오브젝트에서 찾는다.")]
        public UrArmSender urSender;
        [Tooltip("URSim → Unity 방향. 비워두면 같은 오브젝트에서 찾는다.")]
        public UrArmTwinDriver urTwinDriver;
        [Tooltip("URSim 실제 관절각 수신. 비워두면 같은 오브젝트에서 찾는다.")]
        public UrArmReceiver urReceiver;
        [Tooltip("arm/ur_rtde_bridge.py를 버튼으로 띄우는 실행기. 비워두면 같은 오브젝트에서 찾는다.")]
        public UrArmBridgeLauncher urBridgeLauncher;

        [Range(1f, 30f)] public float lerpSpeed = 8f;
        public bool showUI = true;

        ArticulationBody[] _joints;
        float[] _targetDeg;
        float[] _lowerLimitDeg;
        float[] _upperLimitDeg;
        float[] _initialTargetDeg;
        readonly float[] _actualDeg = new float[6];
        Vector3 _initialCubePosition;
        Quaternion _initialCubeRotation;
        bool _active;
        bool _resolved;
        Vector2 _scroll;

        public bool IsActive => _active;

        void Awake()
        {
            if (agent == null) agent = GetComponent<Dg5fPicknPlaceAgent>();
            if (urSender == null) urSender = GetComponent<UrArmSender>();
            if (urTwinDriver == null) urTwinDriver = GetComponent<UrArmTwinDriver>();
            if (urReceiver == null) urReceiver = GetComponent<UrArmReceiver>();
            if (urBridgeLauncher == null) urBridgeLauncher = GetComponent<UrArmBridgeLauncher>();
        }

        // 씬 시작 직후, 다른 컴포넌트가 팔/큐브를 움직이기 전에 관절 ArticulationBody와
        // "Scene에 저장된 그대로의" 초기 자세·큐브 위치를 캡처해둔다. 이 데모 씬은
        // agent.enabled가 처음부터 false라 Dg5fPicknPlaceAgent.OnEpisodeBegin()(홈 자세로
        // 순간이동 + 큐브 랜덤 스폰)이 자동으로 실행되지 않는다 — 즉 Play를 눌렀을 때 실제로
        // 보이는 자세는 HomeArmDeg가 아니라 여기서 캡처하는 이 값이다.
        void Start()
        {
            var bodies = GetComponentsInChildren<ArticulationBody>(true);
            int n = Dg5fPicknPlaceSpec.ArmLinks.Length;
            _joints = new ArticulationBody[n];
            _targetDeg = new float[n];
            _lowerLimitDeg = new float[n];
            _upperLimitDeg = new float[n];
            _initialTargetDeg = new float[n];
            for (int i = 0; i < n; i++)
            {
                _joints[i] = bodies.FirstOrDefault(b => b.name == Dg5fPicknPlaceSpec.ArmLinks[i]);
                if (_joints[i] == null) continue;
                var drive = _joints[i].xDrive;
                _lowerLimitDeg[i] = drive.lowerLimit;
                _upperLimitDeg[i] = drive.upperLimit;
                _initialTargetDeg[i] = drive.target;
            }
            if (agent != null && agent.cubeTarget != null)
            {
                _initialCubePosition = agent.cubeTarget.position;
                _initialCubeRotation = agent.cubeTarget.rotation;
            }
            SyncFromCurrentPose();
            _resolved = true;
        }

        /// 활성화 직전 실제 자세로 슬라이더를 재동기화한다 — 켜는 순간 팔이 슬라이더의
        /// 낡은 값으로 튀는 것을 막는다.
        public void SyncFromCurrentPose()
        {
            if (_joints == null) return;
            for (int i = 0; i < _joints.Length; i++)
                if (_joints[i] != null)
                    _targetDeg[i] = _joints[i].xDrive.target;
        }

        /// "완전 초기화" — Play를 눌렀을 때 실제로 화면에 보였던 그 장면(Start()에서 캡처해둔
        /// 관절 각도·큐브 위치)으로 순간이동시킨다. Dg5fPicknPlaceAgent.OnEpisodeBegin()을 쓰지
        /// 않는 이유: 이 데모는 agent.enabled가 처음부터 false라 그게 자동 실행된 적이 없고,
        /// 호출하면 오히려 (a) 팔이 HomeArmDeg라는 낯선 자세로 튀고 (b) 큐브가 매번 새 랜덤
        /// 위치로 스폰돼 데모가 재현되지 않는다 — 데모 리셋은 매번 같은 그림이어야 한다.
        ///
        /// ⚠️ URSim으로 송신 중이면 이 순간이동이 그대로 URSim 목표가 된다. 브리지의 슬루
        /// 리밋(RTAUTO_UR_MAX_DEG_PER_SEC)이 속도는 막아주지만 "움직일 필요 자체"를 없애주진
        /// 않으므로, 초기화 전에 송신을 끄는 쪽이 안전하다.
        public void FullReset()
        {
            if (fistButton != null) fistButton.SetFist(false);
            for (int i = 0; i < _joints.Length; i++)
            {
                if (_joints[i] == null) continue;
                float deg = _initialTargetDeg[i];
                _targetDeg[i] = deg;
                var drive = _joints[i].xDrive;
                drive.target = deg;
                _joints[i].xDrive = drive;
                _joints[i].jointPosition = new ArticulationReducedSpace(deg * Mathf.Deg2Rad);
                _joints[i].jointVelocity = new ArticulationReducedSpace(0f);
            }
            if (agent != null && agent.cubeTarget != null)
            {
                Rigidbody cube = agent.cubeTarget;
                cube.linearVelocity = Vector3.zero;
                cube.angularVelocity = Vector3.zero;
                cube.position = _initialCubePosition;
                cube.rotation = _initialCubeRotation;
            }
            Physics.SyncTransforms();
        }

        /// URSim이 보고한 실제 관절각을 슬라이더·xDrive 목표로 가져온다. 트윈 구동(URSim→Unity)을
        /// 상시로 켜지 않고 "지금 이 순간만 맞추고 싶을 때" 쓴다 — 두 자세가 벌어진 채로
        /// Unity→URSim 송신을 켜면 URSim이 그 간극만큼 한 번에 움직이려 하기 때문이다.
        public void PullFromUrsim()
        {
            if (urReceiver == null || !urReceiver.GetAngles(_actualDeg)) return;
            for (int i = 0; i < _joints.Length && i < _actualDeg.Length; i++)
            {
                if (_joints[i] == null) continue;
                float deg = Mathf.Clamp(_actualDeg[i], _lowerLimitDeg[i], _upperLimitDeg[i]);
                _targetDeg[i] = deg;
                var drive = _joints[i].xDrive;
                drive.target = deg;
                _joints[i].xDrive = drive;
            }
        }

        /// PicknPlaceControlModeSwitcher가 자동/수동 전환 시 호출한다.
        public void SetActive(bool active)
        {
            _active = active;
            if (active) SyncFromCurrentPose();
        }

        void FixedUpdate()
        {
            if (!_resolved || !_active) return;
            // URSim→Unity 방향일 때는 UrArmTwinDriver가 xDrive의 주인이다. 여기서 같이 쓰면
            // 두 힘이 같은 target을 다투므로 슬라이더 반영을 멈추고, 대신 슬라이더 쪽을
            // 실제 자세로 계속 따라가게 해서 방향을 되돌렸을 때 튀지 않게 한다.
            if (urTwinDriver != null && urTwinDriver.driveEnabled)
            {
                SyncFromCurrentPose();
                return;
            }
            float t = Mathf.Clamp01(Time.fixedDeltaTime * lerpSpeed);
            for (int i = 0; i < _joints.Length; i++)
            {
                var body = _joints[i];
                if (body == null) continue;
                var drive = body.xDrive;
                // A Lerp smooths the *feel* but imposes no velocity ceiling: its first step
                // is proportional to the error, so dragging a slider a long way made the arm
                // appear to teleport, which the real UR16e cannot do. Clamp the per-tick step
                // to the real joint speed limit (URDF -> UrArmLimits.MaxDegPerSec: 120 deg/s
                // at the shoulder, 180 at elbow/wrists). Lerp for smoothness, this clamp for
                // the physical ceiling — they do different jobs, so both stay.
                float smoothed = Mathf.Lerp(drive.target, _targetDeg[i], t);
                float maxStep = UrArmLimits.MaxDegPerSec[i] * Time.fixedDeltaTime;
                drive.target = Mathf.Clamp(
                    smoothed, drive.target - maxStep, drive.target + maxStep);
                body.xDrive = drive;
            }
        }

        void OnGUI()
        {
            if (!showUI || !_resolved) return;

            // 좌표를 직접 박지 않고 DemoUiLayout에서 받아온다 — 오른쪽 열은 팔/URSim 전용이라
            // 이 패널이 사실상 독차지하지만, 다른 패널이 하나 붙어도 겹치지 않는다.
            GUILayout.BeginArea(DemoUiLayout.Right(DemoUiLayout.RightRemaining()), GUI.skin.box);
            GUILayout.Label("<b>UR16e 팔</b>");

            // URSim 연동은 자동(정책) 모드에서도 의미가 있다 — 정책이 움직인 Unity 팔을
            // URSim이 그대로 따라오는 게 이 프로젝트가 말하는 디지털 트윈이다. 그래서 이
            // 구역만은 수동/자동과 무관하게 항상 그린다. 슬라이더는 수동일 때만 나온다.
            DrawUrsimSection();
            GUILayout.Space(4f);

            if (!_active)
            {
                GUILayout.Label("관절 슬라이더는 '수동' 모드에서 나옵니다");
                GUILayout.EndArea();
                return;
            }

            bool ursimOwnsArm = urTwinDriver != null && urTwinDriver.driveEnabled;
            _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.ExpandHeight(true));
            bool hasActual = urReceiver != null && urReceiver.GetAngles(_actualDeg);
            for (int i = 0; i < _joints.Length; i++)
            {
                if (_joints[i] == null) continue;
                // 명령각과 URSim 실제각을 한 줄에 나란히 — 둘이 벌어져 있으면 추종이 안 되고
                // 있다는 뜻이고, 그게 곧 "시뮬과 실물이 다르다"의 1차 지표다.
                string actual = hasActual ? $"  /  URSim {_actualDeg[i]:F2}°" : "";
                GUILayout.Label($"{JointLabels[i]}: {_targetDeg[i]:F2}°{actual}");
                // URSim이 팔을 쥐고 있을 때는 슬라이더를 잠근다 — 만져도 무시되는 컨트롤을
                // 그대로 두면 "왜 안 움직이지"가 된다.
                GUI.enabled = !ursimOwnsArm;
                _targetDeg[i] = GUILayout.HorizontalSlider(
                    _targetDeg[i], _lowerLimitDeg[i], _upperLimitDeg[i]);
                GUI.enabled = true;
            }
            GUILayout.EndScrollView();

            GUI.enabled = urReceiver != null && urReceiver.HasData;
            if (GUILayout.Button("URSim 실제각으로 맞추기")) PullFromUrsim();
            GUI.enabled = true;
            if (GUILayout.Button("초기화 (전체 리셋)")) FullReset();
            GUILayout.EndArea();
        }

        /// URSim 연동 방향 선택 + 상태. 두 방향은 상호배타 — 하나를 켜면 다른 하나가 꺼진다.
        void DrawUrsimSection()
        {
            if (urSender == null && urTwinDriver == null) return;

            DrawBridgeLauncher();

            bool toUrsim = urSender != null && urSender.sendEnabled;
            bool fromUrsim = urTwinDriver != null && urTwinDriver.driveEnabled;

            GUILayout.Label("URSim 연동 방향");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button(toUrsim ? "[Unity→URSim]" : "Unity→URSim")) SetDirection(!toUrsim, false);
            if (GUILayout.Button(fromUrsim ? "[URSim→Unity]" : "URSim→Unity")) SetDirection(false, !fromUrsim);
            GUILayout.EndHorizontal();

            // "브리지가 도는지"를 화면에서 바로 알 수 있게 한다 — 콘솔을 열지 않아도
            // 원인이 파이썬 미실행인지 방향 설정인지 구분된다(손 트래킹 상태 표시와 같은 취지).
            bool live = urReceiver != null && urReceiver.HasData
                        && urReceiver.secondsSinceLastPacket < 0.5f;
            Color previous = GUI.color;
            GUI.color = live ? Color.green : new Color(1f, 0.65f, 0f);
            GUILayout.Label(live
                ? $"URSim: 수신중 (UDP {urReceiver.ActivePort})"
                : "URSim: 대기중");
            GUI.color = previous;
            if (!live)
                GUILayout.Label("ur_rtde_bridge.py --ip --echo-to-unity 필요");
        }

        /// 브리지(arm/ur_rtde_bridge.py) 실행/중지 버튼. 터미널을 따로 열고 venv를 켜는
        /// 단계를 없앤다. 실제 실행은 UrArmBridgeLauncher가 하고, 여기서는 버튼만 그린다.
        void DrawBridgeLauncher()
        {
            if (urBridgeLauncher == null) return;

            bool running = urBridgeLauncher.IsRunning;
            GUILayout.BeginHorizontal();
            GUI.enabled = !running;
            if (GUILayout.Button("브리지 실행")) urBridgeLauncher.Launch();
            GUI.enabled = running;
            if (GUILayout.Button("브리지 중지")) urBridgeLauncher.Stop();
            GUI.enabled = true;
            GUILayout.EndHorizontal();
            GUILayout.Label("브리지: " + urBridgeLauncher.Status);
        }

        void SetDirection(bool toUrsim, bool fromUrsim)
        {
            // 방향 전환 순간에 슬라이더가 낡은 값을 들고 있으면 URSim이 그 값으로 튄다 —
            // 켜기 직전에 현재 자세로 맞춰서 이동량을 0에서 시작하게 한다(README의
            // "실물 송신 켜기 전 중립 자세" 절차와 같은 이유).
            if (toUrsim) SyncFromCurrentPose();
            if (urSender != null) urSender.sendEnabled = toUrsim;
            if (urTwinDriver != null) urTwinDriver.driveEnabled = fromUrsim;
        }
    }
}
