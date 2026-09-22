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
    [Tooltip("IsFresh 판정 기준(초) — secondsSinceLastPacket이 이보다 크면 '끊김'으로 본다. "
             + "arm/ur_rtde_bridge.py의 STALE_AFTER_SEC(1.0)과 값을 맞춰 둔다.")]
    public float staleAfterSeconds = 1.0f;

    //: 관절각 정신머리 검사 — arm/ur_rtde_bridge.py의 UR_JOINT_LIMIT_DEG와 같은 값
    //: (URDF 팔 관절 6개의 소프트웨어 한계 ±2π rad = ±360°). 이보다 벗어난 값은
    //: 손상된 패킷이지 정상 관절각이 아니다(2026-09-21 코드 리뷰).
    const float JointLimitDeg = 360f;

    readonly float[] _latest = new float[ChannelCount];
    volatile bool _hasData;
    long _lastPacketUtcTicks; // 수신 스레드에서 Unity Time API 사용 불가 -> DateTime 사용
    bool _invalidWarned; // 비정상 패킷 경고 래치 — ReceiveLoop 스레드 안에서만 건드린다

    UdpClient _client;
    Thread _thread;
    volatile bool _running;
    readonly object _lock = new object();

    public bool HasData => _hasData;

    /// 패킷을 받은 적이 있고(HasData) **최근에도** 받고 있는가(끊긴 지 staleAfterSeconds
    /// 미만). 2026-09-21 코드 리뷰로 추가 — HasData만 보면 브리지가 죽은 뒤에도 "수신중"
    /// 으로 계속 표시된다(한 번 true가 되면 다시 false로 안 돌아가는 구조였다). 화면
    /// 표시·트윈 구동은 모두 이걸 봐야 한다.
    public bool IsFresh => _hasData && secondsSinceLastPacket < staleAfterSeconds;

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
        var decoded = new float[ChannelCount];
        while (_running)
        {
            try
            {
                byte[] data = _client.Receive(ref remote);
                // 프로토콜은 float32 x 6 단일 버전이다(DG5F처럼 다중 버전으로 늘어나지
                // 않는다) — 길이가 정확해야 한다. 짧거나 길면 손상/오조준 패킷으로 버린다.
                if (data.Length != ChannelCount * 4)
                {
                    WarnInvalid($"패킷 길이 {data.Length}바이트 (정확히 {ChannelCount * 4}바이트여야 함)");
                    continue;
                }
                bool ok = true;
                for (int i = 0; i < ChannelCount; i++)
                {
                    float v = BitConverter.ToSingle(data, i * 4);
                    if (float.IsNaN(v) || float.IsInfinity(v) || Mathf.Abs(v) > JointLimitDeg)
                    {
                        ok = false;
                        break;
                    }
                    decoded[i] = v;
                }
                if (!ok)
                {
                    // ⚠️ 비정상 값이면 _latest/_hasData/타임스탬프를 **전부 건드리지 않는다** —
                    // arm/ur_rtde_bridge.py의 validate_packet()과 같은 원칙(2026-09-21).
                    // 여기서 갱신하면 UrArmTwinDriver의 ArticulationBody.xDrive.target이
                    // NaN으로 오염돼 이후 Lerp가 계속 NaN을 내는 문제로 번질 수 있다.
                    WarnInvalid("숫자가 아니거나(NaN/Inf) 범위를 벗어난 관절각 포함");
                    continue;
                }
                _invalidWarned = false;
                lock (_lock)
                {
                    for (int i = 0; i < ChannelCount; i++)
                        _latest[i] = decoded[i];
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

    /// 비정상 패킷 경고 — 래치로 한 번만 찍는다(연속 거부 시 콘솔 도배 방지).
    void WarnInvalid(string reason)
    {
        if (_invalidWarned) return;
        _invalidWarned = true;
        Debug.LogWarning($"[UrArmReceiver] 비정상 패킷 거부 — {reason}. 계속되면 반복하지 않습니다.");
    }

    /// 메인 스레드에서 최신 6채널 각도[deg]를 buffer에 복사. **끊긴 상태(!IsFresh)면 false** —
    /// 값 자체는 여전히 최신 수신값이지만, 브리지가 죽었는데도 마지막 값을 계속 구동에
    /// 쓰지 않도록 호출자가 막아야 한다(2026-09-21, UrArmTwinDriver가 이 반환값을 본다).
    public bool GetAngles(float[] buffer)
    {
        if (!IsFresh) return false;
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
