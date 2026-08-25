// CameraTargetReceiver.cs
// 외부 3D 카메라 프로세스가 UDP로 보내는 타겟 좌표를 받아, 로봇팔(robotBase) 기준
// 로컬 좌표계 위치에 빨간 타겟 공(target)을 배치한다.
// README의 "3D 카메라 목표 좌표(후속 입력 경계)"를 구현하는 부분 — 학습 중에는
// Dg5fGraspPointReachAgent.ResetTarget()이 같은 target을 랜덤으로 옮기므로, 이 리시버는
// 학습이 아닌 라이브 운용(카메라로 실제 목표를 인식하는 모드)에서만 사용한다.
// 패킷: float32 little-endian '<3f'.
//   inputIsCameraSpace=true(기본)  → 카메라 자체 좌표계 기준 (x, y, z)[m].
//     cameraTransform(캘리브레이션된 카메라 위치/방향)로 월드 좌표를 구한 뒤 robotBase
//     기준으로 다시 변환한다. cameraAxisSign으로 카메라 SDK 축 관례(OpenCV 등은 보통
//     Y-down/Z-forward)를 Unity(Y-up) 관례로 보정한다.
//   inputIsCameraSpace=false        → 이미 robotBase 로컬 좌표로 계산되어 오는 값(기존 동작).
// vision/dg5f의 UDP 수신 패턴(Dg5fReceiver.cs)과 동일한 구조.
// 포트 5007 — SVH(5005)·DG5F 손(5006)·DG5F 실물 SDK 브리지(5008)와 공존.
// 포트 번호의 유일한 출처는 config/rtauto_config.py(PORT_ZED_TARGET) — 바꾸려면 거기부터.

using System;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

public class CameraTargetReceiver : MonoBehaviour
{
    public int port = 5007;

    [Tooltip("좌표계 원점 — 로봇팔 베이스 Transform")]
    public Transform robotBase;
    [Tooltip("이동시킬 타겟 오브젝트(빨간 공) — Reach 학습 씬의 Target/RedBall과 동일 오브젝트. " +
             "continuousApply=false면 비워둘 수 있다(TryGetRobotLocalPosition을 다른 스크립트가 직접 호출).")]
    public Transform target;

    [Tooltip("true(기본): 매 프레임 target.position을 카메라 좌표로 덮어씀(Reach의 실시간 추종). " +
             "false: 자동 적용을 끄고, TryGetRobotLocalPosition()을 호출한 쪽(예: Grasp 에이전트의 " +
             "에피소드 리셋)에서 필요할 때만 1회성으로 좌표를 가져다 쓴다 — 물리 시뮬레이션되는 공을 " +
             "매 프레임 텔레포트해서 물리와 충돌하지 않게 하기 위함.")]
    public bool continuousApply = true;

    [Tooltip("true: 수신 좌표를 cameraTransform 기준 카메라 로컬 좌표로 해석. " +
             "false: 수신 좌표가 이미 robotBase 로컬 좌표(기존 동작).")]
    public bool inputIsCameraSpace = true;
    [Tooltip("실제 카메라 위치/방향에 맞게 캘리브레이션된 Transform. inputIsCameraSpace=true일 때 필수.")]
    public Transform cameraTransform;
    [Tooltip("카메라 SDK 축 관례 보정 — 예: OpenCV/RealSense(X-right, Y-down, Z-forward) → " +
             "Unity(X-right, Y-up, Z-forward)는 Y만 뒤집으면 되므로 기본값 (1,-1,1).")]
    public Vector3 cameraAxisSign = new Vector3(1f, -1f, 1f);

    [Tooltip("target을 로봇팔 작업반경 안으로 강제 클램프할지 여부 (카메라 오검출 안전망)")]
    public bool clampToWorkspace = true;
    [Tooltip("Dg5fReachSpec.MinimumTargetRadius와 동일 기본값")]
    public float minRadius = 0.20f;
    [Tooltip("Dg5fReachSpec.MaximumTargetRadius와 동일 기본값")]
    public float maxRadius = 0.85f;

    [Tooltip("마지막 패킷 수신 후 경과(초). 0.5 이상이면 카메라 신호 끊김.")]
    public float secondsSinceLastPacket = float.PositiveInfinity;

    [Tooltip("true: 수신값을 Unity 콘솔에 로그로 찍음(raw 좌표 + robotBase 로컬 변환 결과). " +
             "디버그/카메라 확인용 — 기본은 꺼둠(20Hz 수신이라 매 프레임 찍으면 콘솔이 넘침).")]
    public bool logToConsole = false;
    [Tooltip("logToConsole=true일 때 로그 최소 간격(초)")]
    public float logIntervalSeconds = 0.5f;
    float _lastLogTime = float.NegativeInfinity;

    [Tooltip("true: 수신 패킷마다(스로틀 없이) Logs/camera_target_received_*.csv에 1행씩 기록. " +
             "t_unix가 zed_sender.py의 로그와 같은 단위(unix 초)라 값·시간으로 직접 대조 가능.")]
    public bool logToFile = false;
    StreamWriter _fileWriter;
    long _lastLoggedPacketTicks = -1;

    public enum TargetSourceMode { Camera, Random, Manual }

    [Header("타겟 소스 모드 (Play 중 우측 상단 UI 또는 여기서 전환 가능)")]
    public TargetSourceMode mode = TargetSourceMode.Camera;

    [Tooltip("Manual 모드에서 타겟을 놓을 robotBase 기준 로컬 좌표. Random 모드에서 뽑힌 값도 여기 반영된다.")]
    public Vector3 manualLocalPosition = new Vector3(0.4f, 0.10f, 0f);
    [Tooltip("Random 모드에서 뽑는 높이(로컬 Y) 최솟값")]
    public float randomLocalYMin = 0.05f;
    [Tooltip("Random 모드에서 뽑는 높이(로컬 Y) 최댓값")]
    public float randomLocalYMax = 0.40f;

    [Tooltip("Game 뷰에 모드 전환 UI(OnGUI)를 그릴지 여부")]
    public bool showModeUI = true;

    string _manualXText, _manualYText, _manualZText;
    bool _manualTextDirty = true;

    const int ChannelCount = 3;
    readonly float[] _latest = new float[ChannelCount];
    volatile bool _hasData;
    long _lastPacketUtcTicks;

    UdpClient _client;
    Thread _thread;
    volatile bool _running;
    readonly object _lock = new object();

    public bool HasData => _hasData;

    void Start()
    {
        if (robotBase == null || (continuousApply && target == null))
        {
            Debug.LogError("[CameraTargetReceiver] robotBase가 없거나, continuousApply=true인데 target이 없음.");
            enabled = false;
            return;
        }
        if (inputIsCameraSpace && cameraTransform == null)
        {
            Debug.LogError("[CameraTargetReceiver] inputIsCameraSpace=true인데 cameraTransform이 없음.");
            enabled = false;
            return;
        }
        if (logToFile)
        {
            _fileWriter = Dg5fLogFile.Create("camera_target_received", out string path);
            _fileWriter.WriteLine(
                "t_unix,raw_x,raw_y,raw_z,robotLocal_x,robotLocal_y,robotLocal_z,world_x,world_y,world_z");
            Debug.Log($"[CameraTargetReceiver] 파일 기록 시작: {path}");
        }

        _client = new UdpClient(port);
        _running = true;
        _thread = new Thread(ReceiveLoop) { IsBackground = true };
        _thread.Start();
    }

    void Update()
    {
        long ticks = Interlocked.Read(ref _lastPacketUtcTicks);
        secondsSinceLastPacket = _hasData
            ? (float)(DateTime.UtcNow - new DateTime(ticks, DateTimeKind.Utc)).TotalSeconds
            : float.PositiveInfinity;

        if (logToConsole) LogLatestIfDue();
        if (logToFile) LogToFileIfNewPacket();

        if (!continuousApply) return;
        ApplyModeTarget();
    }

    void ApplyModeTarget()
    {
        switch (mode)
        {
            case TargetSourceMode.Camera:
                if (!TryGetRobotLocalPosition(out Vector3 robotLocal)) return;
                target.position = robotBase.TransformPoint(robotLocal);
                break;
            case TargetSourceMode.Manual:
                Vector3 local = clampToWorkspace ? ClampToWorkspace(manualLocalPosition) : manualLocalPosition;
                target.position = robotBase.TransformPoint(local);
                break;
            case TargetSourceMode.Random:
                // 매 프레임 재적용하지 않음 — RandomizeTarget()이 모드 전환/버튼 클릭 시 1회 텔레포트.
                break;
        }
    }

    /// UI(OnGUI)의 모드 버튼에서 호출. 같은 모드로 재클릭해도 부작용 없음.
    public void SetMode(TargetSourceMode newMode)
    {
        if (mode == newMode)
        {
            if (newMode == TargetSourceMode.Random) RandomizeTarget();
            return;
        }
        mode = newMode;
        if (newMode == TargetSourceMode.Random) RandomizeTarget();
        _manualTextDirty = true;
    }

    /// [minRadius, maxRadius] 환형(annulus) 안, [randomLocalYMin, randomLocalYMax] 높이에서
    /// robotBase 로컬 좌표를 1개 뽑아 target을 즉시 그 위치로 옮긴다.
    public void RandomizeTarget()
    {
        if (target == null || robotBase == null) return;
        float angle = UnityEngine.Random.Range(0f, Mathf.PI * 2f);
        float radius = UnityEngine.Random.Range(minRadius, maxRadius);
        float y = UnityEngine.Random.Range(randomLocalYMin, randomLocalYMax);
        var local = new Vector3(Mathf.Cos(angle) * radius, y, Mathf.Sin(angle) * radius);
        manualLocalPosition = local;
        target.position = robotBase.TransformPoint(local);
        _manualTextDirty = true;
    }

    /// robotBase 기준 로컬 좌표로 변환된 최신 카메라 좌표를 1회성으로 가져온다(카메라-공간
    /// 변환 + 작업반경 클램프까지 적용됨). 데이터가 없으면 false.
    /// continuousApply=false로 두고 다른 스크립트(예: 에피소드 리셋 시점의 공 스폰)에서
    /// 필요할 때만 호출하는 용도.
    public bool TryGetRobotLocalPosition(out Vector3 robotLocal)
    {
        robotLocal = Vector3.zero;
        if (!TryGetLocalPosition(out Vector3 raw)) return false;

        robotLocal = inputIsCameraSpace
            ? robotBase.InverseTransformPoint(
                cameraTransform.TransformPoint(Vector3.Scale(raw, cameraAxisSign)))
            : raw;

        if (clampToWorkspace) robotLocal = ClampToWorkspace(robotLocal);
        return true;
    }

    void LogLatestIfDue()
    {
        if (Time.unscaledTime - _lastLogTime < logIntervalSeconds) return;
        if (!TryGetLocalPosition(out Vector3 raw)) return;
        _lastLogTime = Time.unscaledTime;

        if (TryGetRobotLocalPosition(out Vector3 robotLocal))
        {
            // raw.magnitude = 카메라 원점 기준 거리 — zed_sender.py의 nearest['distance']와
            // 동일한 값(카메라-공간 변환 이전의 원본 좌표 크기이므로 inputIsCameraSpace 값과 무관).
            Debug.Log(
                $"[CameraTargetReceiver] raw={raw} (dist={raw.magnitude:F3}) "
                + $"-> robotLocal={robotLocal} world={robotBase.TransformPoint(robotLocal)}");
        }
        else
        {
            Debug.Log($"[CameraTargetReceiver] raw={raw} (robotBase 미설정 등으로 변환 불가)");
        }
    }

    /// 실제로 새 패킷이 온 경우에만(중복 프레임 방지) 1행 기록 — zed_sender.py 로그의
    /// sent_x/y/z와 여기 raw_x/y/z가 값으로 정확히 일치해야 정상.
    void LogToFileIfNewPacket()
    {
        long ticks = Interlocked.Read(ref _lastPacketUtcTicks);
        if (ticks == _lastLoggedPacketTicks) return;
        if (!TryGetLocalPosition(out Vector3 raw)) return;
        _lastLoggedPacketTicks = ticks;

        bool hasLocal = TryGetRobotLocalPosition(out Vector3 robotLocal);
        double tUnix = new DateTimeOffset(new DateTime(ticks, DateTimeKind.Utc))
            .ToUnixTimeMilliseconds() / 1000.0;

        string F(float v) => v.ToString("F6", CultureInfo.InvariantCulture);
        string robotLocalX = hasLocal ? F(robotLocal.x) : "";
        string robotLocalY = hasLocal ? F(robotLocal.y) : "";
        string robotLocalZ = hasLocal ? F(robotLocal.z) : "";
        string worldX = "", worldY = "", worldZ = "";
        if (hasLocal && robotBase != null)
        {
            Vector3 world = robotBase.TransformPoint(robotLocal);
            worldX = F(world.x);
            worldY = F(world.y);
            worldZ = F(world.z);
        }

        _fileWriter.WriteLine(string.Join(",", new[]
        {
            tUnix.ToString("F3", CultureInfo.InvariantCulture),
            F(raw.x), F(raw.y), F(raw.z),
            robotLocalX, robotLocalY, robotLocalZ,
            worldX, worldY, worldZ,
        }));
        _fileWriter.Flush();
    }

    void ReceiveLoop()
    {
        var remote = new IPEndPoint(IPAddress.Any, port);
        while (_running)
        {
            try
            {
                byte[] data = _client.Receive(ref remote);
                if (data.Length < ChannelCount * 4) continue;
                lock (_lock)
                {
                    for (int i = 0; i < ChannelCount; i++)
                        _latest[i] = BitConverter.ToSingle(data, i * 4);
                }
                Interlocked.Exchange(ref _lastPacketUtcTicks, DateTime.UtcNow.Ticks);
                _hasData = true;
            }
            catch (Exception e)
            {
                if (_running) Debug.LogWarning("[CameraTargetReceiver] " + e.Message);
            }
        }
    }

    /// 메인 스레드에서 최신 수신 좌표(원본, 미변환)를 읽는다. 데이터 없으면 false.
    bool TryGetLocalPosition(out Vector3 raw)
    {
        raw = Vector3.zero;
        if (!_hasData) return false;
        lock (_lock) { raw = new Vector3(_latest[0], _latest[1], _latest[2]); }
        return true;
    }

    /// 평면(XZ) 반경만 [minRadius, maxRadius]로 클램프 — 방향은 유지, 높이(Y)는 그대로 둔다.
    Vector3 ClampToWorkspace(Vector3 local)
    {
        float planarRadius = new Vector2(local.x, local.z).magnitude;
        if (planarRadius < 1e-6f) return local;
        float clampedRadius = Mathf.Clamp(planarRadius, minRadius, maxRadius);
        float scale = clampedRadius / planarRadius;
        return new Vector3(local.x * scale, local.y, local.z * scale);
    }

    void OnGUI()
    {
        if (!showModeUI) return;
        if (_manualTextDirty)
        {
            _manualXText = manualLocalPosition.x.ToString("F3", CultureInfo.InvariantCulture);
            _manualYText = manualLocalPosition.y.ToString("F3", CultureInfo.InvariantCulture);
            _manualZText = manualLocalPosition.z.ToString("F3", CultureInfo.InvariantCulture);
            _manualTextDirty = false;
        }

        GUILayout.BeginArea(new Rect(10, 10, 260, 190), GUI.skin.box);
        GUILayout.Label("타겟 소스 모드");
        GUILayout.BeginHorizontal();
        if (GUILayout.Button(mode == TargetSourceMode.Camera ? "[Camera]" : "Camera")) SetMode(TargetSourceMode.Camera);
        if (GUILayout.Button(mode == TargetSourceMode.Random ? "[Random]" : "Random")) SetMode(TargetSourceMode.Random);
        if (GUILayout.Button(mode == TargetSourceMode.Manual ? "[Manual]" : "Manual")) SetMode(TargetSourceMode.Manual);
        GUILayout.EndHorizontal();

        if (mode == TargetSourceMode.Random)
        {
            if (GUILayout.Button("다시 뽑기")) RandomizeTarget();
        }
        else if (mode == TargetSourceMode.Manual)
        {
            GUILayout.Label("Local X"); _manualXText = GUILayout.TextField(_manualXText);
            GUILayout.Label("Local Y"); _manualYText = GUILayout.TextField(_manualYText);
            GUILayout.Label("Local Z"); _manualZText = GUILayout.TextField(_manualZText);
            if (GUILayout.Button("적용") && target != null && robotBase != null)
            {
                if (float.TryParse(_manualXText, NumberStyles.Float, CultureInfo.InvariantCulture, out float x)
                    && float.TryParse(_manualYText, NumberStyles.Float, CultureInfo.InvariantCulture, out float y)
                    && float.TryParse(_manualZText, NumberStyles.Float, CultureInfo.InvariantCulture, out float z))
                {
                    manualLocalPosition = new Vector3(x, y, z);
                }
            }
        }

        if (target != null && robotBase != null)
        {
            Vector3 shown = robotBase.InverseTransformPoint(target.position);
            GUILayout.Label($"target local = ({shown.x:F3}, {shown.y:F3}, {shown.z:F3})");
        }
        GUILayout.EndArea();
    }

    void OnDestroy()
    {
        _running = false;
        _client?.Close();
        _thread?.Join(200);
        if (_fileWriter != null) { _fileWriter.Flush(); _fileWriter.Dispose(); _fileWriter = null; }
    }
}
