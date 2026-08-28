using System.Linq;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Pipeline_Demo_GraspLift 수동 모드의 대안 팔 조작 방식 — PicknPlaceTeleopNudge의 IK
    /// (조이스틱+높이 슬라이더, 작업공간 좌표계) 대신 UR16e 6축 관절 각도를 하나씩 슬라이더로
    /// 직접 지정한다. 슬라이더 범위는 각 ArticulationBody의 실제 xDrive 한계(URDF 임포트 시
    /// 설정된 물리 관절 한계, UR e-series 전 기종 ±360° — docs/SIM2REAL_ROADMAP.md 참고) 그대로다.
    /// Dg5fPicknPlaceSpec.ArmSafeMinDeg/MaxDeg는 RL 정책 학습용으로 손튜닝된 훨씬 좁은 "그럴듯한
    /// 자세" 봉투라 사람이 직접 조작할 때 굳이 그 안으로 제한할 이유가 없다 — 대신 그 봉투 밖으로
    /// 나가면 슬라이더 라벨을 주황색으로 바꿔 "이 구간은 RL 검증 밖(패널을 뚫고 내려가는 코너가
    /// 있다고 알려짐, 로드맵 참고)"이라는 경고만 준다.
    /// PicknPlaceControlModeSwitcher가 이 패널과 PicknPlaceTeleopNudge 중 하나만 활성화해
    /// 같은 xDrive.target을 두 곳에서 동시에 쓰지 않게 한다.
    /// </summary>
    public sealed class PicknPlaceArmJointPanel : MonoBehaviour
    {
        static readonly string[] JointLabels =
        {
            "Shoulder Pan", "Shoulder Lift", "Elbow", "Wrist 1", "Wrist 2", "Wrist 3"
        };

        static readonly Color WarningColor = new Color(1f, 0.65f, 0f);

        public Dg5fPicknPlaceAgent agent;
        [Tooltip("완전 초기화 시 함께 풀어줄 주먹쥐기 버튼(있으면). 비워두면 손 포즈는 " +
                 "그대로 두고 팔+물체만 리셋된다.")]
        public Dg5fFistButton fistButton;

        [Range(1f, 30f)] public float lerpSpeed = 8f;
        public bool showUI = true;

        ArticulationBody[] _joints;
        float[] _targetDeg;
        float[] _lowerLimitDeg;
        float[] _upperLimitDeg;
        float[] _initialTargetDeg;
        Vector3 _initialCubePosition;
        Quaternion _initialCubeRotation;
        bool _active;
        bool _resolved;
        Vector2 _scroll;

        public bool IsActive => _active;

        void Awake()
        {
            if (agent == null) agent = GetComponent<Dg5fPicknPlaceAgent>();
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
        /// 낡은 값으로 튀는 것을 막는다(PicknPlaceTeleopNudge.SetActive와 동일한 이유).
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

        /// PicknPlaceControlModeSwitcher가 조이스틱/관절직접 전환 시 호출한다.
        public void SetActive(bool active)
        {
            _active = active;
            if (active) SyncFromCurrentPose();
        }

        void FixedUpdate()
        {
            if (!_resolved || !_active) return;
            float t = Mathf.Clamp01(Time.fixedDeltaTime * lerpSpeed);
            for (int i = 0; i < _joints.Length; i++)
            {
                var body = _joints[i];
                if (body == null) continue;
                var drive = body.xDrive;
                drive.target = Mathf.Lerp(drive.target, _targetDeg[i], t);
                body.xDrive = drive;
            }
        }

        void OnGUI()
        {
            if (!showUI || !_active || !_resolved) return;

            // Dg5fFistButton의 우상단 패널(y 0~60) 바로 아래부터 화면 하단까지 확보하되,
            // "초기화" 버튼은 스크롤뷰 밖(항상 고정 위치)에 둔다 — Game 뷰가 작아서 6개 관절
            // 슬라이더가 다 안 들어가도 버튼 자체가 잘려 사라지는 일은 없고, 슬라이더 목록만
            // 스크롤된다. 고정 높이를 어림잡았다가 맨 아래 버튼이 영역 밖으로 잘려 안 보이던
            // 이전 버그(그리고 그 대안이었던 "넉넉한 고정 높이"도 Game 뷰가 그보다 작으면 여전히
            // 잘릴 수 있었던 문제)를 완전히 없앤다.
            Rect area = new Rect(Screen.width - 260, 70, 250, Mathf.Max(160f, Screen.height - 80));
            GUILayout.BeginArea(area, GUI.skin.box);
            GUILayout.Label("<b>팔 관절 직접 조작</b>");

            _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.ExpandHeight(true));
            for (int i = 0; i < _joints.Length; i++)
            {
                if (_joints[i] == null) continue;
                bool outsideTrainedEnvelope = _targetDeg[i] < Dg5fPicknPlaceSpec.ArmSafeMinDeg[i]
                    || _targetDeg[i] > Dg5fPicknPlaceSpec.ArmSafeMaxDeg[i];

                Color previous = GUI.color;
                if (outsideTrainedEnvelope) GUI.color = WarningColor;
                GUILayout.Label(outsideTrainedEnvelope
                    ? $"{JointLabels[i]}: {_targetDeg[i]:F0}° (검증 밖)"
                    : $"{JointLabels[i]}: {_targetDeg[i]:F0}°");
                GUI.color = previous;

                _targetDeg[i] = GUILayout.HorizontalSlider(_targetDeg[i], _lowerLimitDeg[i], _upperLimitDeg[i]);
            }
            GUILayout.EndScrollView();

            if (GUILayout.Button("초기화 (전체 리셋)")) FullReset();
            GUILayout.EndArea();
        }
    }
}
