using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
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

        /// <summary>
        /// 관절 각속도 상한[deg/s]. 0 이하면 제한 없음(옛 동작).
        /// 실물 DG-5F는 dg5f_sdk_bridge.py의 슬루 리밋에 묶여 등속으로만 움직이는데, 이 버튼의
        /// 지수 감쇠 보간은 초기에 훨씬 빠르다(최대 이동 100° × closeSpeed 6 = 600 deg/s 대
        /// 실물 100 deg/s). 그래서 트윈이 실물보다 먼저 도착해 "유니티와 실물 움직임이 다르다"로
        /// 보인다(2026-08-31 실물 구동에서 확인). 여기서 같은 상한을 걸어 프로파일을 맞춘다.
        /// 기본값은 .env의 RTAUTO_DG5F_MAX_DEG_PER_SEC를 읽어 파이썬 브리지와 같은 값을 쓴다
        /// (숫자를 두 곳에 타이핑하지 않는다 — CLAUDE.md 원칙 1).
        /// </summary>
        [Tooltip("관절 각속도 상한[deg/s]. 실물 브리지와 같은 값을 .env에서 읽는다. 0=제한 없음")]
        public float maxJointDegPerSec = 0f;   // Start()에서 .env 값으로 채운다

        /// <summary>
        /// 관절 단계별 순차 폐합. 끄면 20관절이 동시에 닫힌다(옛 동작).
        ///
        /// 왜 (2026-08-31 실물): 컵을 잡을 때 전 관절이 동시에 닫히면 **끝마디가 먼저 컵 윗면에
        /// 부딪혀** 손가락이 컵을 감싸지 못한 채 막힌다. 사람은 뿌리(MCP)부터 감싸 넣고 끝마디
        /// (PIP/DIP)를 나중에 조인다 — 그 순서를 그대로 준다.
        ///
        /// 각 관절은 전체 폐합률이 자기 단계의 시작값을 넘긴 뒤에 움직이기 시작한다.
        /// 채널 안에서 손가락당 4관절은 뿌리→끝 순서다(j1 벌림·대향/CMC, j2 MCP, j3 PIP, j4 DIP).
        /// </summary>
        [Tooltip("관절을 뿌리→끝 순서로 순차 폐합. 끄면 전 관절 동시(옛 동작)")]
        public bool sequentialClosing = true;

        [Range(0.2f, 10f)]
        [Tooltip("한 그룹이 '도달했다'고 볼 오차[deg]. 이 안에 들어오면 다음 그룹이 출발한다. "
                 + "너무 작으면 다음 단계가 안 넘어가고, 너무 크면 단계가 겹친다")]
        public float stageTolerance = 1.5f;

        public bool showUI = true;

        /// <summary>
        /// 이 컴포넌트가 손 관절을 구동할지. false면 xDrive에 쓰지 않는다(UI는 그대로 보인다).
        ///
        /// 왜 `enabled`를 끄지 않는가: real→sim 모드에서는 Dg5fHandDriver가 손의 주인이라 이쪽이
        /// 비켜야 하는데(둘 다 xDrive.target에 쓰면 실행 순서에 좌우되는 경합), 컴포넌트를 통째로
        /// 끄면 OnGUI도 멈춰 **'현재 자세 녹화' 버튼이 사라진다.** 정작 그 모드가 손으로 자세를
        /// 잡아 녹화하는 모드다. 그래서 구동만 막고 UI는 살려둔다.
        /// Dg5fTwinModeSwitcher가 방향에 맞춰 켜고 끈다.
        /// </summary>
        [Tooltip("끄면 이 버튼이 손 관절을 구동하지 않는다(UI는 유지). 트윈 방향 전환이 제어한다")]
        public bool driveHand = true;

        /// <summary>
        /// 실물에서 캡처한 파지 자세 JSON. 비우면 .env의 RTAUTO_DG5F_GRASP_POSE를 쓴다.
        /// 만드는 법: 실물 손을 원하는 파지 자세로 잡아놓고
        ///   python vision/dg5f/dg5f_readback_bridge.py --ip &lt;IP&gt; --capture-pose
        /// 주먹(RightFistDeg)과 달리 파지 자세는 대상 물체마다 달라지므로 코드가 아니라 파일로 뺀다.
        /// </summary>
        [Tooltip("실물에서 캡처한 파지 자세 JSON 경로(저장소 루트 기준 상대경로 가능). "
                 + "비우면 .env의 RTAUTO_DG5F_GRASP_POSE 사용")]
        public string graspPoseFile = "";

        /// <summary>
        /// 파지 자세 JSON 스키마 (JsonUtility용 — 필드명이 JSON 키와 같아야 한다).
        /// 파이썬 쪽 dg5f_readback_bridge.py --capture-pose 가 쓰는 키와 같은 형식이어야
        /// 양쪽이 서로의 파일을 읽을 수 있다. 읽을 때 실제로 쓰는 건 name·deg 둘뿐이고,
        /// 나머지는 "이 자세가 언제 어디서 나왔는지" 기록용이다.
        /// </summary>
        [Serializable]
        class GraspPoseFile
        {
            public string name;
            public string hand;
            public string captured_utc;
            public string source;
            public string convention;
            public string[] channels;
            public float[] deg;
        }

        /// 채널 이름 — 파이썬 dg5f_angles.CHANNEL_NAMES와 같은 순서(기록용).
        static readonly string[] ChannelNames = {
            "thumb_cmc", "thumb_opp", "thumb_mcp", "thumb_ip",
            "index_abd", "index_mcp", "index_pip", "index_dip",
            "middle_abd", "middle_mcp", "middle_pip", "middle_dip",
            "ring_abd", "ring_mcp", "ring_pip", "ring_dip",
            "pinky_cmc", "pinky_lat", "pinky_mcp", "pinky_pip",
        };

        ArticulationBody[] _handJoints;
        float[] _openDeg;
        float[] _cmdDeg;          // 속도 제한을 적용한 실제 명령각 — 실물의 슬루와 같은 등속 접근
        float[] _graspDeg;        // 캡처한 파지 자세 (없으면 null → 버튼 비활성)
        string _graspName = "";
        string _recordNote = "";  // 녹화 결과 메시지 (몇 초만 표시)
        float _recordNoteUntil;
        float[] _activeTarget;    // 지금 향하는 목표 자세 = RightFistDeg 또는 _graspDeg
        float _closure;           // 비순차 모드에서만 쓰는 전체 폐합률
        float _targetClosure;     // 0 = 펴기, 1 = 쥐기 (순차 모드에서는 방향 지시로만 쓴다)
        int _releasedGroups;      // 순차 모드: 이 번호 미만 그룹이 목표를 향한다 (0 = 전부 열림)
        bool _holdPose;           // true면 버튼을 누를 때까지 현재 자세를 유지(ResyncToCurrentPose 참고)
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
            _cmdDeg = new float[_handJoints.Length];
            for (int i = 0; i < _handJoints.Length; i++)
                if (_handJoints[i] != null)
                    _openDeg[i] = _cmdDeg[i] = _handJoints[i].xDrive.target;

            // Inspector에서 손대지 않았으면(0) .env 값을 쓴다 — 실물 브리지와 같은 상한.
            // RtautoConfig의 원칙대로 파싱 실패에도 예외를 던지지 않고 기본값으로 떨어진다.
            if (maxJointDegPerSec <= 0f)
            {
                string raw = RtautoConfig.GetString("RTAUTO_DG5F_MAX_DEG_PER_SEC", "100");
                maxJointDegPerSec = float.TryParse(raw, NumberStyles.Float,
                                                   CultureInfo.InvariantCulture, out float parsed)
                                    && parsed > 0f
                    ? parsed
                    : 100f;
            }

            _activeTarget = Dg5fPicknPlaceSpec.RightFistDeg;
            LoadGraspPose();
            _resolved = true;
        }

        /// 캡처한 파지 자세를 읽어 _graspDeg에 담는다. 없거나 형식이 어긋나면 조용히 null로 두고
        /// 버튼만 비활성화한다 — 자세 파일이 없다고 데모 씬이 죽으면 안 된다(RtautoConfig와 같은 원칙).
        void LoadGraspPose()
        {
            string configured = string.IsNullOrEmpty(graspPoseFile)
                ? RtautoConfig.GetString("RTAUTO_DG5F_GRASP_POSE", "config/dg5f_grasp_pose.json")
                : graspPoseFile;
            string path = RtautoConfig.GetRepoPath(configured);
            if (path == null || !File.Exists(path))
            {
                Debug.Log($"[Dg5fFistButton] 파지 자세 파일 없음({configured}) — '파지하기' 버튼 비활성. "
                          + "실물 손을 파지 자세로 잡고 "
                          + "`python vision/dg5f/dg5f_readback_bridge.py --ip <IP> --capture-pose` 로 만드세요.");
                return;
            }
            try
            {
                var parsed = JsonUtility.FromJson<GraspPoseFile>(File.ReadAllText(path));
                if (parsed?.deg == null || parsed.deg.Length != Dg5fPicknPlaceSpec.HandJointCount)
                {
                    Debug.LogWarning($"[Dg5fFistButton] 파지 자세 파일의 deg 배열이 "
                                     + $"{Dg5fPicknPlaceSpec.HandJointCount}개가 아닙니다: {path}");
                    return;
                }
                _graspDeg = parsed.deg;
                _graspName = string.IsNullOrEmpty(parsed.name) ? "파지" : parsed.name;
                Debug.Log($"[Dg5fFistButton] 파지 자세 '{_graspName}' 로드: {path}");
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[Dg5fFistButton] 파지 자세 파일을 읽지 못했습니다 ({path}) — {e.Message}");
            }
        }

        static ArticulationBody FindBodyBySuffix(IEnumerable<ArticulationBody> bodies, string suffix)
        {
            foreach (var body in bodies)
                if (body.name.EndsWith(suffix, StringComparison.Ordinal)) return body;
            return null;
        }

        public void SetFist(bool closed)
        {
            if (closed) _activeTarget = Dg5fPicknPlaceSpec.RightFistDeg;
            SetClosed(closed);
        }

        /// <summary>
        /// 지금 손 자세를 파지 자세로 녹화해 JSON에 저장하고, 즉시 '파지하기' 버튼에 반영한다.
        ///
        /// 값의 출처는 **트윈의 현재 관절 자세**(xDrive.target)다. real→sim 모드에서 실물을 손으로
        /// 잡아 트윈이 그 자세를 따라간 상태라면, 그게 곧 실물 자세다. 파이썬
        /// `--capture-pose`와 같은 형식으로 쓰므로 어느 쪽으로 떠도 서로 읽을 수 있다.
        ///
        /// 명령줄 없이 마음에 드는 자세를 그 자리에서 다시 뜰 수 있게 하려고 만든 것이다 —
        /// 종이컵이 컵라면으로 바뀌면 자세도 바뀌니까.
        /// </summary>
        public bool RecordGraspPose(out string message)
        {
            message = "";
            if (!_resolved) { message = "아직 관절을 못 찾았습니다."; return false; }

            string configured = string.IsNullOrEmpty(graspPoseFile)
                ? RtautoConfig.GetString("RTAUTO_DG5F_GRASP_POSE", "config/dg5f_grasp_pose.json")
                : graspPoseFile;
            string path = RtautoConfig.GetRepoPath(configured);
            if (string.IsNullOrEmpty(path))
            {
                message = "저장 경로를 찾지 못했습니다(저장소 루트 확인).";
                return false;
            }

            var deg = new float[Dg5fPicknPlaceSpec.HandJointCount];
            for (int i = 0; i < deg.Length; i++)
                deg[i] = _handJoints[i] != null ? _handJoints[i].xDrive.target : 0f;

            var payload = new GraspPoseFile
            {
                name = string.IsNullOrEmpty(_graspName) || _graspName == "파지" ? "grasp" : _graspName,
                hand = "right",
                captured_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ",
                                                        CultureInfo.InvariantCulture),
                source = "Unity Dg5fFistButton 자세 녹화 (트윈 관절 xDrive.target)",
                convention = "our channel order/sign (URDF·Unity 기준, deg)",
                channels = ChannelNames,
                deg = deg,
            };

            try
            {
                string dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(path, JsonUtility.ToJson(payload, true));
            }
            catch (Exception e)
            {
                message = "저장 실패: " + e.Message;
                Debug.LogWarning("[Dg5fFistButton] 파지 자세 저장 실패 — " + e.Message, this);
                return false;
            }

            _graspDeg = deg;                 // 즉시 반영 — 다시 로드할 필요 없이 바로 재생 가능
            _graspName = payload.name;
            message = $"녹화 완료 → {configured}";
            Debug.Log($"[Dg5fFistButton] 파지 자세 '{payload.name}' 녹화: {path}");
            return true;
        }

        /// 지금 관절 자세를 '열린 손' 기준으로 다시 잡는다(폐합률도 0으로 되돌림).
        ///
        /// Start()에서 한 번 캡처한 _openDeg는 그 시점의 자세다. 트윈이 그 사이에 실물 자세를
        /// 따라가 다른 곳에 가 있으면(Dg5fTwinModeSwitcher의 sim→real 진입 동기화), 이 버튼이
        /// 다시 켜지는 순간 옛 자세로 되돌리려 들어 **실물이 크게 튄다.** 그래서 주인이 바뀔 때
        /// 기준을 새로 잡아준다.
        public void ResyncToCurrentPose()
        {
            if (!_resolved) return;
            // ⚠️ _openDeg(= '펴진 손'의 정의)는 건드리지 않는다. 예전엔 여기서 같이 덮어썼는데,
            //    sim→real 진입 시 실물이 파지 자세였다면 **그 자세가 '펴진 손'이 되어 버려**
            //    이후 '손 펴기'가 파지 자세로 갔다(2026-08-31). _openDeg는 씬 시작 시점의
            //    프리팹 기본(펴진) 자세로 계속 두고, 여기서는 명령 기준점만 현재 자세로 옮긴다.
            for (int i = 0; i < _handJoints.Length; i++)
                if (_handJoints[i] != null)
                    _cmdDeg[i] = _handJoints[i].xDrive.target;
            _closure = 0f;
            _targetClosure = 0f;
            _releasedGroups = 0;
            // 버튼을 누르기 전까지는 지금 자세를 그대로 유지한다. 이게 없으면 곧바로 _openDeg를
            // 향해 움직여, 실물 자세에 맞춰둔 의미가 사라진다(전환 직후 튐).
            _holdPose = true;
        }

        /// 캡처한 파지 자세로 간다. 자세 파일이 없으면 아무것도 하지 않는다.
        public void SetGrasp(bool closed)
        {
            if (closed)
            {
                if (_graspDeg == null) return;
                _activeTarget = _graspDeg;
            }
            SetClosed(closed);
        }

        void SetClosed(bool closed)
        {
            _holdPose = false;      // 사람이 자세를 지시했으니 '현재 자세 유지'를 푼다
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

        /// 채널 i가 지금 얼마나 닫혀 있어야 하는지(0~1). 단계 시작값을 넘기기 전에는 0이라
        /// 그 관절은 아직 움직이지 않는다.
        ///
        /// 펼 때는 이 식이 자동으로 **역순**을 만든다 — 전체 폐합률이 내려오면 시작값이 큰
        /// 관절(끝마디·엄지)의 폐합률이 먼저 0에 닿기 때문이다. 즉 조인 순서의 반대로 풀린다.
        /// 채널이 속한 순차 그룹. 낮은 번호부터 하나씩 **완료된 뒤에** 다음이 움직인다.
        ///
        /// ★그룹을 '시간'이 아니라 '완료'로 나누는 이유 (2026-08-31 실물):
        ///   처음에는 전체 폐합률(시간) 구간으로 단계를 나눴는데, 이동량이 큰 관절이 아직 가는
        ///   중인데도 시간이 지나 다음 단계가 출발했다. 특히 thumb_opp는 이동량이 ~88°로 가장
        ///   커서(다른 관절 40~60°) 등속으로 훨씬 오래 걸리는데, 그 사이 thumb_ip가 출발해
        ///   **엄지 끝이 먼저 접혀 컵 입구에 걸렸다.** 시간이 아니라 앞 그룹의 실제 도달을
        ///   기준으로 삼아야 한다.
        ///
        /// 그룹 순서는 사람이 물건을 감싸는 순서다: 손 모양 잡기 → 뿌리로 감싸기 → 끝마디 조이기
        /// → 엄지를 가로질러 오기 → 엄지 끝 조이기.
        static int GroupOf(int channel)
        {
            int fingerIdx = channel / 4;        // 0 = 엄지 … 4 = 새끼
            int jointIdx = channel % 4;         // 0 = j1(뿌리) … 3 = j4(끝)

            // 엄지는 네 손가락이 다 감싼 뒤에 온다(손바닥을 가로질러야 해서 먼저 오면 걸린다).
            if (fingerIdx == 0) return jointIdx <= 1 ? 3 : 4;   // (cmc, opp) → (mcp, ip)

            // ⚠️ 새끼만 채널 구성이 다르다: cmc / lat / mcp / pip.
            //    다른 손가락은 abd / mcp / pip / dip 이라 자리를 그대로 쓰면 새끼의
            //    mcp(뿌리 굽힘)가 남들 PIP와 같은 '끝마디' 그룹으로 밀린다.
            //    (채널 이름 출처: vision/dg5f/dg5f_angles.py DG5F_CHANNELS)
            if (fingerIdx == 4) return jointIdx <= 1 ? 0 : (jointIdx == 2 ? 1 : 2);

            return jointIdx == 0 ? 0 : (jointIdx == 1 ? 1 : 2);
        }

        const int MaxGroup = 4;

        void FixedUpdate()
        {
            if (!_resolved || !driveHand) return;

            // 실물 브리지의 슬루 리밋과 같은 '등속' 접근. 이게 없으면 지수 보간이라 초기 각속도가
            // (이동량 × closeSpeed)까지 치솟아 트윈이 실물보다 먼저 도착한다.
            float maxDelta = maxJointDegPerSec > 0f
                ? maxJointDegPerSec * Time.fixedDeltaTime
                : float.PositiveInfinity;

            if (_holdPose)
            {
                // 방금 다른 주인(Dg5fHandDriver)에게서 손을 넘겨받은 상태 — 버튼을 누르기 전까지는
                // 아무 데도 가지 않고 지금 자세를 지킨다.
                for (int i = 0; i < _handJoints.Length; i++)
                    if (_handJoints[i] != null) ApplyTarget(i);
                return;
            }

            if (!sequentialClosing)
            {
                // 옛 동작 — 20관절 동시. 물체를 감쌀 때는 끝마디가 먼저 닿아 막히므로 권장하지 않는다.
                float t = Mathf.Clamp01(Time.fixedDeltaTime * closeSpeed);
                _closure = Mathf.Lerp(_closure, _targetClosure, t);
                for (int i = 0; i < _handJoints.Length; i++)
                {
                    if (_handJoints[i] == null) continue;
                    float w = Mathf.Lerp(_openDeg[i], _activeTarget[i], _closure);
                    _cmdDeg[i] = Mathf.MoveTowards(_cmdDeg[i], w, maxDelta);
                    ApplyTarget(i);
                }
                return;
            }

            // 순차: _releasedGroups 미만 그룹만 목표를 향하고, 나머지는 열린 자세에 머문다.
            bool allArrived = true;
            for (int i = 0; i < _handJoints.Length; i++)
            {
                if (_handJoints[i] == null) continue;
                float want = GroupOf(i) < _releasedGroups ? _activeTarget[i] : _openDeg[i];
                _cmdDeg[i] = Mathf.MoveTowards(_cmdDeg[i], want, maxDelta);
                ApplyTarget(i);
                if (Mathf.Abs(_cmdDeg[i] - want) > stageTolerance) allArrived = false;
            }

            // 도달했을 때만 다음 그룹을 연다. 펼 때는 같은 식이 **역순**을 만든다 —
            // 목표가 0이라 높은 그룹(엄지 끝)부터 하나씩 되돌아간다.
            // ⚠️ 판정 기준은 '명령각'이지 실물 실제각이 아니다. sim→real에서는 수신이 꺼져 있어
            //    실물 피드백이 없기 때문이다. 실물은 이 명령 시퀀스를 약간의 지연을 두고 따라온다.
            if (allArrived)
            {
                int goal = _targetClosure > 0.5f ? MaxGroup + 1 : 0;
                if (_releasedGroups < goal) _releasedGroups++;
                else if (_releasedGroups > goal) _releasedGroups--;
            }
        }

        void ApplyTarget(int i)
        {
            var drive = _handJoints[i].xDrive;
            drive.target = Mathf.Clamp(_cmdDeg[i], drive.lowerLimit, drive.upperLimit);
            _handJoints[i].xDrive = drive;
        }

        void OnGUI()
        {
            if (!showUI) return;
            // 우상단 — 좌상단(PicknPlaceControlModeSwitcher), 우하단(PicknPlaceTeleopNudge)과
            // 겹치지 않는 모서리.
            GUILayout.BeginArea(new Rect(Screen.width - 250, 10, 240, 128), GUI.skin.box);
            // 구동권이 없을 때(real→sim: 손의 주인이 Dg5fHandDriver) 자세 버튼은 눌러도 소용없다.
            // 반면 '녹화'는 그 모드에서 쓰는 기능이라 계속 살려둔다.
            GUI.enabled = driveHand;
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("주먹 쥐기")) SetFist(true);
            if (GUILayout.Button("손 펴기")) SetFist(false);
            GUILayout.EndHorizontal();
            // 파지 자세는 녹화된 파일이 있을 때만 누를 수 있다.
            GUI.enabled = driveHand && _graspDeg != null;
            if (GUILayout.Button(_graspDeg != null ? $"파지하기 ({_graspName})" : "파지하기 (자세 없음)"))
                SetGrasp(true);
            GUI.enabled = true;
            // 지금 자세가 마음에 들면 그 자리에서 다시 뜬다 — real→sim으로 손에 자세를 잡아둔 뒤 누른다.
            if (GUILayout.Button("현재 자세 녹화"))
            {
                RecordGraspPose(out _recordNote);
                _recordNoteUntil = Time.realtimeSinceStartup + 4f;
            }
            if (!string.IsNullOrEmpty(_recordNote) && Time.realtimeSinceStartup < _recordNoteUntil)
                GUILayout.Label(_recordNote);
            GUILayout.EndArea();
        }
    }
}
