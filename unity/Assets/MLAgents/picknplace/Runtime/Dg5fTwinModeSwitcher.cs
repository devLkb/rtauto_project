// Dg5fTwinModeSwitcher.cs
// 디지털 트윈 방향 전환 UI — 명령줄을 다시 치지 않고 버튼으로 sim↔real 방향을 바꾼다.
//
//   [ sim → real ]  Unity가 실물을 구동 (송신 ON / 수신 OFF)
//   [ real → sim ]  실물이 Unity를 구동 (수신 ON / 송신 OFF, 실물은 교시 모드로 힘이 풀림)
//   [ 연결 끊기  ]  양쪽 정지 (실물은 마지막 자세 유지)
//
// 왜 '전환'이 필요한가:
//  ① 두 방향을 동시에 켜면 Unity → 실물 → (echo) → Unity → 실물 … 되먹임 루프가 된다.
//  ② Dg5fFistButton과 Dg5fHandDriver는 **둘 다 xDrive.target에 쓴다.** 같이 켜두면 실행 순서에
//     따라 결과가 달라지는 경합이 된다. 그래서 방향마다 쓰는 쪽 하나만 남긴다.
// 사람이 컴포넌트 체크박스를 손으로 여닫으면 위 둘을 매번 틀리기 쉬워서, 버튼 하나로 묶었다.
//
// 파이썬은 **한 번만** 띄우면 두 방향을 다 처리한다:
//   python vision/dg5f/dg5f_sdk_bridge.py --ip <그리퍼IP> --echo-to-unity
// 방향을 바꿀 때 이 컴포넌트가 그 프로세스로 제어 패킷(b"DG5FMODE" + 모드바이트)을 보내
// 실물 교시 모드까지 함께 전환한다. 관절 패킷(80바이트 이상)과 길이로 구분되어 섞이지 않는다.
//
// ★ sim→real로 들어갈 때는 **먼저 실물 자세를 트윈에 받아온 뒤** 구동을 시작한다.
//   안 그러면 Unity의 기본(손 편) 자세가 목표가 되어 실물이 그만큼 크게 움직인다.
//   먼저 맞춰두면 이동량이 0이라 튀지 않는다. (브리지 쪽 슬루 리밋도 별도로 걸려 있지만,
//   그건 '천천히 움직이게' 할 뿐 '움직일 필요 자체'를 없애주지는 못한다.)
//
// ⚠️ real→sim은 실물의 힘을 푼다(교시 모드). 물건을 쥔 상태에서 누르면 놓친다.
//
// 이 파일이 Assets/Scripts가 아니라 picknplace/Runtime에 있는 이유: Dg5fFistButton을 참조해야
// 하는데 asmdef가 KDT.PicknPlaceTraining → KDT.RobotScripts 한 방향만 열려 있어서, 반대로
// 두면 순환 참조가 된다.

using System;
using System.Collections;
using System.Net;
using System.Net.Sockets;
using System.Text;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    public class Dg5fTwinModeSwitcher : MonoBehaviour
    {
        public enum TwinMode { Off, SimToReal, RealToSim }

        [Header("연결 대상 (비우면 같은 GameObject에서 자동으로 찾는다)")]
        public Dg5fSender sender;
        public Dg5fReceiver receiver;
        public Dg5fHandDriver handDriver;
        public Dg5fFistButton fistButton;

        [Header("상태")]
        [Tooltip("현재 방향. 버튼으로 바꾼다 — 직접 고치면 전환 절차가 안 돌아 반영되지 않는다.")]
        public TwinMode mode = TwinMode.Off;
        public bool showUI = true;

        [Header("sim→real 진입 시 실물 자세 동기화")]
        [Tooltip("실물 상태 패킷을 이 시간(초) 안에 못 받으면 동기화를 건너뛴다. "
                 + "브리지를 --echo-to-unity 없이 띄웠거나 아직 안 띄웠을 때 무한정 기다리지 않게 한다.")]
        public float syncTimeout = 2f;
        [Tooltip("패킷을 받은 뒤 트윈이 실물 자세에 수렴할 때까지 기다리는 시간(초). "
                 + "Dg5fHandDriver의 lerp가 끝날 만큼은 줘야 한다.")]
        public float syncSettle = 0.8f;

        static readonly byte[] ControlMagic = Encoding.ASCII.GetBytes("DG5FMODE");

        UdpClient _control;
        IPEndPoint _bridgeEndPoint;
        Coroutine _pending;
        string _note = "";

        void Start()
        {
            if (sender == null) sender = GetComponent<Dg5fSender>();
            if (receiver == null) receiver = GetComponent<Dg5fReceiver>();
            if (handDriver == null) handDriver = GetComponent<Dg5fHandDriver>();
            if (fistButton == null) fistButton = GetComponent<Dg5fFistButton>();

            // 제어 패킷 대상 = 구동 브리지(dg5f_sdk_bridge.py)가 듣는 곳. Dg5fSender와 같은 곳이다.
            string ip = RtautoConfig.GetString("RTAUTO_DG5F_BRIDGE_IP", "127.0.0.1");
            int port = RtautoConfig.GetInt("RTAUTO_PORT_DG5F_BRIDGE", 5008);
            try
            {
                _control = new UdpClient();
                _bridgeEndPoint = new IPEndPoint(IPAddress.Parse(ip), port);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[Dg5fTwinModeSwitcher] 제어 소켓 준비 실패 ({ip}:{port}) — {e.Message}. "
                                 + "방향 전환은 Unity 쪽만 적용되고 실물 교시 모드는 안 바뀝니다.", this);
            }

            SetMode(TwinMode.Off);   // 안전: 씬을 켰다고 실물이 움직이거나 힘이 풀리면 안 된다
        }

        public void SetMode(TwinMode next)
        {
            if (_pending != null) { StopCoroutine(_pending); _pending = null; }
            mode = next;

            if (next == TwinMode.SimToReal && isActiveAndEnabled)
            {
                _pending = StartCoroutine(EnterSimToReal());
                return;
            }
            ApplyImmediate(next);
        }

        /// 되먹임 루프와 xDrive 경합을 막는 지점 — 방향마다 '쓰는 쪽'을 하나만 남긴다.
        void ApplyImmediate(TwinMode m)
        {
            bool simToReal = m == TwinMode.SimToReal;
            bool realToSim = m == TwinMode.RealToSim;

            if (sender != null) sender.sendEnabled = simToReal;
            if (receiver != null) receiver.enabled = realToSim;
            if (handDriver != null) handDriver.enabled = realToSim;
            // real→sim에서는 손 자세의 주인이 Dg5fHandDriver다. 주먹/파지 버튼이 같이 구동하면
            // 같은 xDrive.target을 두 컴포넌트가 매 틱 덮어써서 결과가 실행 순서에 좌우된다.
            // 컴포넌트를 끄지 않고 구동만 막는 이유: 끄면 OnGUI도 멈춰 '현재 자세 녹화' 버튼이
            // 사라지는데, 손으로 자세를 잡아 녹화하는 게 바로 이 모드이기 때문이다.
            if (fistButton != null) fistButton.driveHand = !realToSim;

            SendControl(realToSim);   // 실물 교시 모드: real→sim일 때만 힘을 푼다

            _note = m switch
            {
                TwinMode.SimToReal => "Unity가 실물을 구동합니다. 주먹/파지 버튼을 누르세요.",
                TwinMode.RealToSim => "실물 힘이 풀렸습니다. 손으로 자세를 잡으면 트윈이 따라옵니다.",
                _ => "양쪽 모두 정지. 실물은 마지막 자세를 유지합니다.",
            };
            Debug.Log($"[Dg5fTwinModeSwitcher] 모드 = {m} — {_note}");
        }

        /// sim→real 진입: ①실물 자세를 트윈에 받아 맞추고 ②그 자세를 기준으로 구동을 시작한다.
        IEnumerator EnterSimToReal()
        {
            SendControl(false);                                    // 교시 해제 — 실물이 현재 자세를 유지
            if (sender != null) sender.sendEnabled = false;        // 아직 구동하지 않는다
            if (fistButton != null) fistButton.driveHand = false;  // 트윈이 실물을 따라가는 동안 비켜준다
            if (receiver != null) receiver.enabled = true;
            if (handDriver != null) handDriver.enabled = true;
            _note = "실물 자세를 트윈에 맞추는 중…";

            float t0 = Time.time;
            while (Time.time - t0 < syncTimeout && (receiver == null || !receiver.HasData))
                yield return null;

            bool synced = receiver != null && receiver.HasData;
            if (synced) yield return new WaitForSeconds(syncSettle);

            if (receiver != null) receiver.enabled = false;
            if (handDriver != null) handDriver.enabled = false;
            if (fistButton != null)
            {
                // 지금 트윈 자세(=실물 자세)를 '열린 손' 기준으로 다시 잡는다. 안 하면 버튼이
                // Start() 때 캡처한 옛 자세로 되돌리려 들어 결국 실물이 튄다.
                fistButton.ResyncToCurrentPose();
                fistButton.driveHand = true;
            }
            if (sender != null) sender.sendEnabled = true;

            _note = synced
                ? "실물 자세에 맞춘 뒤 구동을 시작했습니다."
                : "⚠️ 실물 상태를 못 받아 동기화를 건너뛰었습니다 — 브리지를 --echo-to-unity로 띄웠는지 확인하세요.";
            Debug.Log($"[Dg5fTwinModeSwitcher] 모드 = SimToReal — {_note}");
            _pending = null;
        }

        void SendControl(bool teachOn)
        {
            if (_control == null) return;
            var packet = new byte[ControlMagic.Length + 1];
            Buffer.BlockCopy(ControlMagic, 0, packet, 0, ControlMagic.Length);
            packet[ControlMagic.Length] = (byte)(teachOn ? 1 : 0);
            try
            {
                _control.Send(packet, packet.Length, _bridgeEndPoint);
            }
            catch (Exception e)
            {
                // 브리지가 안 떠 있어도 Unity 쪽 전환은 진행한다 — 데모가 멈추면 안 된다.
                Debug.LogWarning("[Dg5fTwinModeSwitcher] 제어 패킷 송신 실패 — " + e.Message);
            }
        }

        void OnGUI()
        {
            if (!showUI) return;
            // 좌하단 — 우상단(주먹/파지·송신), 좌상단(제어모드 전환), 우하단(팔 조작)을 피한다.
            GUILayout.BeginArea(new Rect(10, Screen.height - 132, 280, 122), GUI.skin.box);
            GUILayout.Label("디지털 트윈 방향");

            GUI.enabled = mode != TwinMode.SimToReal;
            if (GUILayout.Button("sim → real  (Unity가 실물 구동)")) SetMode(TwinMode.SimToReal);
            GUI.enabled = mode != TwinMode.RealToSim;
            if (GUILayout.Button("real → sim  (실물이 Unity 구동)")) SetMode(TwinMode.RealToSim);
            GUI.enabled = mode != TwinMode.Off;
            if (GUILayout.Button("연결 끊기")) SetMode(TwinMode.Off);
            GUI.enabled = true;

            GUILayout.Label(_note);
            GUILayout.EndArea();
        }

        void OnDisable()
        {
            // 씬을 멈출 때 실물이 힘 풀린 채 남지 않도록 교시 모드를 되돌린다.
            if (mode == TwinMode.RealToSim) SendControl(false);
        }

        void OnDestroy()
        {
            _control?.Close();
            _control = null;
        }
    }
}
