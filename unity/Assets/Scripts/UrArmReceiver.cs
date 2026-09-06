// UrArmReceiver.cs
// arm/ur_rtde_bridge.py --echo-to-unity가 보내는 UR16e 실제 관절각(RTDE getActualQ) 수신.
// (Dg5fReceiver.cs와 같은 패턴, 대상만 손 20채널 -> 팔 6채널.)
//
// 패킷: float32 little-endian x 6, 관절각[deg], 순서 = UrArmJointNames.Names와 동일
// (shoulder_pan/lift, elbow, wrist_1/2/3).
//
// 포트 기본값 5010. 유일한 출처는 config/rtauto_config.py(PORT_UR_ARM_SIM) = 레포 루트
// .env의 RTAUTO_PORT_UR_ARM_SIM이고, 이 스크립트도 RtautoConfig로 같은 파일을 읽는다.
// "URSim의 실제 관절각이 Unity 트윈으로 돌아온다"는 왕복 확인용 — 명령(UrArmSender)과
// 실제(이 리시버)를 비교하면 명령 대비 추종 오차를 볼 수 있다.

using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

public class UrArmReceiver : MonoBehaviour
{
    public const int ChannelCount = 6;

    [Tooltip("레포 루트 .env에 RTAUTO_PORT_UR_ARM_SIM이 없을 때만 쓰는 최후 기본값. "
             + "실제 사용 포트는 ActivePort — .env를 고치면 파이썬과 함께 따라온다.")]
    public int port = 5010;
    [Tooltip("마지막 패킷 수신 후 경과(초). 0.5 이상이면 송신 끊김.")]
    public float secondsSinceLastPacket = float.PositiveInfinity;

    readonly float[] _latest = new float[ChannelCount];
    volatile bool _hasData;
    long _lastPacketUtcTicks; // 수신 스레드에서 Unity Time API 사용 불가 -> DateTime 사용

    UdpClient _client;
    Thread _thread;
    volatile bool _running;
    readonly object _lock = new object();

    public bool HasData => _hasData;

    /// Start()에서 확정된 실제 수신 포트. Inspector의 port는 .env가 없을 때의 기본값이다.
    public int ActivePort { get; private set; }

    void Start()
    {
        ActivePort = RtautoConfig.GetInt("RTAUTO_PORT_UR_ARM_SIM", port);

        try
        {
            _client = new UdpClient(ActivePort);
        }
        catch (SocketException e)
        {
            Debug.LogError(
                $"[UrArmReceiver] UDP {ActivePort} 포트를 열지 못했습니다 ({e.SocketErrorCode}). "
                + "이미 다른 프로세스가 이 포트를 쓰고 있을 가능성이 큽니다. "
                + $"포트를 바꾸려면 레포 루트 .env의 RTAUTO_PORT_UR_ARM_SIM을 수정합니다 (현재 출처: {RtautoConfig.SourceLabel}).",
                this);
            enabled = false;
            return;
        }

        Debug.Log($"[UrArmReceiver] UDP {ActivePort} 수신 대기 (설정 출처: {RtautoConfig.SourceLabel}). "
                  + "값이 안 들어오면 `python arm/ur_rtde_bridge.py --ip --echo-to-unity`가 "
                  + "실행 중인지 확인하세요.");

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
    }

    void ReceiveLoop()
    {
        var remote = new IPEndPoint(IPAddress.Any, ActivePort);
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
                if (_running) Debug.LogWarning("[UrArmReceiver] " + e.Message);
            }
        }
    }

    /// 메인 스레드에서 최신 6채널 각도[deg]를 buffer에 복사. 데이터 없으면 false.
    public bool GetAngles(float[] buffer)
    {
        if (!_hasData) return false;
        lock (_lock) { Array.Copy(_latest, buffer, ChannelCount); }
        return true;
    }

    void OnDestroy()
    {
        _running = false;
        _client?.Close();
        _thread?.Join(200);
    }
}
