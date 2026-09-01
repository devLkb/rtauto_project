// Dg5fSender.cs
// Unity의 DG5F 손 관절 20채널을 UDP로 내보내 **실물 그리퍼를 Unity가 구동**하게 한다.
// (Dg5fReceiver의 정확한 반대 방향: 저쪽은 밖→Unity, 이쪽은 Unity→밖.)
//
//   Unity(이 컴포넌트) → UDP:RTAUTO_PORT_DG5F_BRIDGE(기본 5008)
//     → vision/dg5f/dg5f_sdk_bridge.py → DGSDK.dll → 실물 DG-5F
//
// 패킷은 Dg5fReceiver/vision_node와 같은 계약의 앞부분만 쓴다: float32 little-endian × 20,
// 관절각[deg]. 채널 순서도 동일 — [0..3]엄지 1_1~1_4 / [4..7]검지 / [8..11]중지 /
// [12..15]약지 / [16..19]새끼. 브리지는 `<20f>` 이상이면 앞 20개만 읽으므로 이대로 맞는다.
//
// 관절 탐색 규칙은 Dg5fHandDriver와 동일하게 이름 접미사 "_dg_<손가락>_<마디>" 매칭이라
// 오른손(rl_dg_*)/왼손(ll_dg_*) 프리팹 모두 동작한다.
//
// ⚠️ 안전: 이 컴포넌트는 **실물 하드웨어를 움직인다.** 그래서 기본값이 꺼짐(sendEnabled=false)이고,
//    사람이 명시적으로 켜야만 송신한다. 실수로 씬을 Play했다고 실물이 움직이면 안 된다.
//    실물 쪽 안전장치(관절별 하드웨어 리밋 클램프·슬루 리밋)는 dg5f_sdk_bridge.py가 담당한다.
//
// 포트의 유일한 출처는 config/rtauto_config.py(PORT_DG5F_BRIDGE) = 레포 루트 .env의
// RTAUTO_PORT_DG5F_BRIDGE이고, 이 스크립트도 RtautoConfig로 같은 파일을 읽는다 (원칙 1).

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using UnityEngine;

public class Dg5fSender : MonoBehaviour
{
    public const int ChannelCount = 20;

    [Header("송신 대상 (기본값 출처: 레포 .env / config/rtauto_config.py)")]
    [Tooltip("dg5f_sdk_bridge.py가 도는 PC의 IP. 같은 PC면 127.0.0.1.")]
    public string bridgeIp = "127.0.0.1";
    [Tooltip(".env에 RTAUTO_PORT_DG5F_BRIDGE가 없을 때만 쓰는 최후 기본값. "
             + "실제 사용 포트는 ActivePort.")]
    public int bridgePort = 5008;

    [Header("동작")]
    [Tooltip("⚠️ 켜면 실물 그리퍼가 Unity를 따라 움직인다. 안전을 위해 기본 꺼짐 — "
             + "실물이 연결돼 있고 움직여도 되는 상황에서만 켤 것.")]
    public bool sendEnabled = false;
    [Tooltip("초당 송신 횟수 상한. 실물 브리지 기본 수신이 50Hz라 그에 맞춘다.")]
    [Range(1f, 120f)] public float sendHz = 50f;
    [Tooltip("켜면 xDrive.target(명령각)을, 끄면 jointPosition(물리 실제각)을 보낸다. "
             + "실물 구동에는 보통 '명령각'이 맞다 — 물리 지연·흔들림이 실물로 전파되지 않는다.")]
    public bool sendCommandedAngle = true;
    [Tooltip("화면에 송신 On/Off 토글 UI를 표시")]
    public bool showUI = true;

    /// 실제 송신 포트. Inspector의 bridgePort는 .env가 없을 때의 기본값이다.
    public int ActivePort { get; private set; }

    ArticulationBody[] _joints;         // 패킷 인덱스 순서
    readonly float[] _deg = new float[ChannelCount];
    readonly byte[] _packet = new byte[ChannelCount * 4];
    UdpClient _client;
    IPEndPoint _endPoint;
    float _lastSend;
    int _foundJoints;
    string _status = "";

    void Start()
    {
        ActivePort = RtautoConfig.GetInt("RTAUTO_PORT_DG5F_BRIDGE", bridgePort);
        string ip = RtautoConfig.GetString("RTAUTO_DG5F_BRIDGE_IP", bridgeIp);

        _joints = new ArticulationBody[ChannelCount];
        var bySuffix = new Dictionary<string, ArticulationBody>();
        foreach (var ab in GetComponentsInChildren<ArticulationBody>(true))
        {
            if (ab.jointType != ArticulationJointType.RevoluteJoint) continue;
            int k = ab.name.IndexOf("_dg_", StringComparison.Ordinal);
            if (k < 0) continue;   // 결합 로봇의 팔 관절 — 손 채널 대상 아님
            bySuffix[ab.name.Substring(k)] = ab;
        }
        for (int f = 1; f <= 5; f++)
            for (int j = 1; j <= 4; j++)
            {
                int idx = (f - 1) * 4 + (j - 1);
                if (bySuffix.TryGetValue($"_dg_{f}_{j}", out var ab))
                {
                    _joints[idx] = ab;
                    _foundJoints++;
                }
                else
                    Debug.LogError($"[Dg5fSender] 관절 못 찾음: _dg_{f}_{j}");
            }

        try
        {
            _client = new UdpClient();
            _endPoint = new IPEndPoint(IPAddress.Parse(ip), ActivePort);
        }
        catch (Exception e)
        {
            Debug.LogError($"[Dg5fSender] UDP 준비 실패 ({ip}:{ActivePort}) — {e.Message}", this);
            enabled = false;
            return;
        }

        Debug.Log($"[Dg5fSender] 관절 매핑 {_foundJoints}/20, 송신 대상 {ip}:{ActivePort} "
                  + $"(설정 출처: {RtautoConfig.SourceLabel}). 송신은 기본 꺼짐 — "
                  + "실물을 움직이려면 sendEnabled를 켜고 dg5f_sdk_bridge.py를 실행하세요.");
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

        Buffer.BlockCopy(_deg, 0, _packet, 0, _packet.Length);   // float32 LE — x86/ARM 모두 LE
        try
        {
            _client.Send(_packet, _packet.Length, _endPoint);
            _status = $"송신 중 → {_endPoint}";
        }
        catch (Exception e)
        {
            _status = "송신 실패: " + e.Message;
            Debug.LogWarning("[Dg5fSender] " + _status);
        }
    }

    void OnGUI()
    {
        if (!showUI) return;
        // 우상단은 Dg5fFistButton이 쓰므로 그 아래에 붙인다 — 그쪽 패널이 y=10..186이다
        // (주먹/펴기 · 파지하기 · 웹캠 복귀 · 소유권 표시 · 녹화). 그쪽 높이가 바뀌면 이 y도
        // 같이 내려야 한다. 2026-09-01에 실제로 겹쳐 있던 것을 바로잡았다.
        GUILayout.BeginArea(new Rect(Screen.width - 250, 194, 240, 78), GUI.skin.box);
        bool next = GUILayout.Toggle(sendEnabled, sendEnabled ? " 실물 송신 ON" : " 실물 송신 OFF");
        if (next != sendEnabled)
        {
            sendEnabled = next;
            Debug.Log($"[Dg5fSender] 실물 송신 {(sendEnabled ? "ON" : "OFF")}");
        }
        GUILayout.Label(sendEnabled ? _status : $"대기 — {bridgeIp}:{ActivePort}");
        GUILayout.EndArea();
    }

    void OnDisable()
    {
        // 씬 정지/컴포넌트 비활성 시 송신도 멈춘다 (실물이 마지막 명령을 유지하도록).
        _status = "";
    }

    void OnDestroy()
    {
        _client?.Close();
        _client = null;
    }
}
