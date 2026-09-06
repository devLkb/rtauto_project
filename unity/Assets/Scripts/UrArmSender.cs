// UrArmSender.cs
// Unity의 UR16e 팔 6관절을 UDP로 내보내 URSim(또는 실물)을 Unity가 구동하게 한다.
// (Dg5fSender.cs와 같은 패턴, 대상만 손 20채널 -> 팔 6채널.)
//
//   Unity(이 컴포넌트) -> UDP:RTAUTO_PORT_UR_ARM_BRIDGE(기본 5009)
//     -> arm/ur_rtde_bridge.py -> ur_rtde RTDEControlInterface.servoJ() -> URSim/실물 UR16e
//
// 패킷: float32 little-endian x 6, 관절각[deg], 순서 = UrArmJointNames.Names와 동일
// (shoulder_pan/lift, elbow, wrist_1/2/3 — KDT.PicknPlaceTraining.Dg5fPicknPlaceSpec.ArmLinks
// 값과 같지만 어셈블리 순환 참조를 피하려고 별도 상수로 둔다. UrArmJointNames.cs 참고).
//
// ⚠️ 안전: URSim 전용이라면 위험이 없지만, IP를 실물 컨트롤박스로 바꾸면 이 컴포넌트가
//    실물 팔을 움직인다. 그래서 기본값이 꺼짐(sendEnabled=false)이다 — Dg5fSender.cs와
//    동일한 안전 관례.
//
// 포트의 유일한 출처는 config/rtauto_config.py(PORT_UR_ARM_BRIDGE) = 레포 루트 .env의
// RTAUTO_PORT_UR_ARM_BRIDGE이고, 이 스크립트도 RtautoConfig로 같은 파일을 읽는다 (원칙 1).

using System;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using UnityEngine;

public class UrArmSender : MonoBehaviour
{
    public const int ChannelCount = 6;

    [Header("송신 대상 (기본값 출처: 레포 .env / config/rtauto_config.py)")]
    [Tooltip("ur_rtde_bridge.py가 도는 PC의 IP. 같은 PC면 127.0.0.1.")]
    public string bridgeIp = "127.0.0.1";
    [Tooltip(".env에 RTAUTO_PORT_UR_ARM_BRIDGE가 없을 때만 쓰는 최후 기본값. "
             + "실제 사용 포트는 ActivePort.")]
    public int bridgePort = 5009;

    [Header("동작")]
    [Tooltip("켜면 URSim/실물이 Unity를 따라 움직인다. IP가 실물 컨트롤박스면 실제 팔이 " +
             "움직이므로 기본 꺼짐 — Dg5fSender.cs와 동일한 안전 관례.")]
    public bool sendEnabled = false;
    [Tooltip("초당 송신 횟수 상한. arm/ur_rtde_bridge.py 기본 수신 Hz(10)에 맞춘다.")]
    [Range(1f, 60f)] public float sendHz = 10f;
    [Tooltip("켜면 xDrive.target(명령각)을, 끄면 jointPosition(물리 실제각)을 보낸다.")]
    public bool sendCommandedAngle = true;
    [Tooltip("자체 On/Off 토글 박스를 그릴지. 기본 꺼짐 — Pipeline_Demo_GraspLift에서는 " +
             "PicknPlaceArmJointPanel의 'URSim 연동 방향'이 이 토글을 대신 소유한다(박스가 " +
             "둘로 갈라지지 않게). 그 패널이 없는 씬에서 단독으로 쓸 때만 켠다.")]
    public bool showUI = false;

    /// 실제 송신 포트. Inspector의 bridgePort는 .env가 없을 때의 기본값이다.
    public int ActivePort { get; private set; }

    ArticulationBody[] _joints;         // UrArmJointNames.Names 순서
    readonly float[] _deg = new float[ChannelCount];
    readonly byte[] _packet = new byte[ChannelCount * 4];
    UdpClient _client;
    IPEndPoint _endPoint;
    float _lastSend;
    int _foundJoints;
    string _status = "";

    void Start()
    {
        ActivePort = RtautoConfig.GetInt("RTAUTO_PORT_UR_ARM_BRIDGE", bridgePort);
        string ip = RtautoConfig.GetString("RTAUTO_UR_IP", bridgeIp);

        var bodies = GetComponentsInChildren<ArticulationBody>(true);
        _joints = new ArticulationBody[ChannelCount];
        for (int i = 0; i < ChannelCount; i++)
        {
            string name = UrArmJointNames.Names[i];
            _joints[i] = bodies.FirstOrDefault(b => b.name == name);
            if (_joints[i] != null) _foundJoints++;
            else Debug.LogError($"[UrArmSender] 관절 못 찾음: {name}");
        }

        try
        {
            _client = new UdpClient();
            _endPoint = new IPEndPoint(IPAddress.Parse(ip), ActivePort);
        }
        catch (Exception e)
        {
            Debug.LogError($"[UrArmSender] UDP 준비 실패 ({ip}:{ActivePort}) — {e.Message}", this);
            enabled = false;
            return;
        }

        Debug.Log($"[UrArmSender] 관절 매핑 {_foundJoints}/{ChannelCount}, 송신 대상 {ip}:{ActivePort} "
                  + $"(설정 출처: {RtautoConfig.SourceLabel}). 송신은 기본 꺼짐 — "
                  + "URSim/실물을 움직이려면 sendEnabled를 켜고 arm/ur_rtde_bridge.py를 실행하세요.");
    }

    void FixedUpdate()
    {
        if (!sendEnabled || _client == null || _joints == null) return;
        if (Time.time - _lastSend < 1f / Mathf.Max(1f, sendHz)) return;
        _lastSend = Time.time;

        for (int i = 0; i < ChannelCount; i++)
        {
            var ab = _joints[i];
            if (ab == null) { _deg[i] = 0f; continue; }
            _deg[i] = sendCommandedAngle
                ? ab.xDrive.target
                : (ab.dofCount > 0 ? ab.jointPosition[0] * Mathf.Rad2Deg : 0f);
        }

        Buffer.BlockCopy(_deg, 0, _packet, 0, _packet.Length);   // float32 LE
        try
        {
            _client.Send(_packet, _packet.Length, _endPoint);
            _status = $"송신 중 -> {_endPoint}";
        }
        catch (Exception e)
        {
            _status = "송신 실패: " + e.Message;
            Debug.LogWarning("[UrArmSender] " + _status);
        }
    }

    void OnGUI()
    {
        if (!showUI) return;
        GUILayout.BeginArea(DemoUiLayout.Right(78f), GUI.skin.box);
        bool next = GUILayout.Toggle(sendEnabled, sendEnabled ? " UR 송신 ON" : " UR 송신 OFF");
        if (next != sendEnabled)
        {
            sendEnabled = next;
            Debug.Log($"[UrArmSender] 송신 {(sendEnabled ? "ON" : "OFF")}");
        }
        GUILayout.Label(sendEnabled ? _status : $"대기 — {bridgeIp}:{ActivePort}");
        GUILayout.EndArea();
    }

    void OnDisable()
    {
        _status = "";
    }

    void OnDestroy()
    {
        _client?.Close();
        _client = null;
    }
}
