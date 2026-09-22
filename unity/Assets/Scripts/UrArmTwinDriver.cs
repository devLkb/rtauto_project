// UrArmTwinDriver.cs
// UrArmReceiver가 받은 URSim/실물의 실제 관절각을 이 오브젝트의 ArticulationBody에
// 적용한다 — "URSim(또는 실물)을 조작하면 Unity가 따라온다"는 반대 방향(밖 -> Unity).
// UrArmSender(Unity -> 밖)의 정반대이며, Dg5fReceiver의 값을 실제로 소비하는 컴포넌트가
// 필요했던 것과 같은 이유로 만들었다 — 리시버는 데이터만 들고 있고 아무것도 움직이지
// 않으므로, 이 드라이버가 있어야 화면에서 실제로 눈에 보인다.
//
//   arm/ur_rtde_bridge.py --echo-to-unity (RTDE getActualQ, Unity 명령 여부와 무관하게
//   독립 타이머로 계속 송신) -> UDP:RTAUTO_PORT_UR_ARM_SIM -> UrArmReceiver -> 이 컴포넌트
//   -> ArticulationBody.xDrive.target
//
// ⚠️ 되먹임 루프 주의 (Dg5fSender/Dg5fHandDriver 동시 사용 경고와 동일한 이유):
//    같은 오브젝트에서 UrArmSender(sendEnabled=true, 명령각 송신)와 이 드라이버를
//    동시에 켜면 "Unity 목표 -> URSim -> 실제각 echo -> 이 드라이버가 다시 Unity 목표를
//    덮어씀" 루프가 된다. 값 자체는 수렴하므로 위험하진 않지만 두 힘이 같은 xDrive.target을
//    다투는 것이므로, 각 방향을 언제 쓸지 명확히 하자:
//      - "Unity(정책/사람 조작)가 URSim을 움직인다"      -> UrArmSender만 켠다
//      - "URSim(펜던트 조그·URScript)을 Unity가 따라간다" -> 이 드라이버만 켠다
//    기본값은 꺼짐 — 의도적으로 켤 것.

using UnityEngine;

public class UrArmTwinDriver : MonoBehaviour
{
    [Tooltip("UrArmReceiver — 비워두면 같은 오브젝트에서 자동으로 찾는다.")]
    public UrArmReceiver receiver;
    [Tooltip("켜면 이 오브젝트의 팔 ArticulationBody를 UrArmReceiver 수신값으로 구동한다. " +
             "UrArmSender와 동시에 켜면 되먹임 루프가 된다 — 위 클래스 주석 참고.")]
    public bool driveEnabled = false;
    [Range(1f, 30f)] public float lerpSpeed = 15f;
    [Tooltip("자체 On/Off 토글 박스를 그릴지. 기본 꺼짐 — Pipeline_Demo_GraspLift에서는 " +
             "PicknPlaceArmJointPanel의 'URSim 연동 방향'이 이 토글을 대신 소유한다.")]
    public bool showUI = false;

    ArticulationBody[] _joints;         // UrArmJointNames.Names 순서
    readonly float[] _target = new float[UrArmJointNames.Names.Length];
    readonly float[] _origStiffness = new float[UrArmJointNames.Names.Length];
    readonly float[] _origDamping = new float[UrArmJointNames.Names.Length];
    int _foundJoints;
    bool _wasDriving;   // 직전 틱에 이 드라이버가 실제로 관절을 쥐고 있었는지

    void Awake()
    {
        if (receiver == null) receiver = GetComponent<UrArmReceiver>();
    }

    void Start()
    {
        var bodies = GetComponentsInChildren<ArticulationBody>(true);
        _joints = new ArticulationBody[UrArmJointNames.Names.Length];
        for (int i = 0; i < _joints.Length; i++)
        {
            string name = UrArmJointNames.Names[i];
            foreach (var b in bodies)
            {
                if (b.name != name) continue;
                _joints[i] = b;
                _foundJoints++;
                break;
            }
            if (_joints[i] == null) Debug.LogError($"[UrArmTwinDriver] 관절 못 찾음: {name}");
            else
            {
                // bypassPhysicsSpring을 끄면 원래 스프링 세기로 되돌려야 하므로 시작값을 남겨둔다.
                _origStiffness[i] = _joints[i].xDrive.stiffness;
                _origDamping[i] = _joints[i].xDrive.damping;
            }
        }
        if (receiver == null)
            Debug.LogError("[UrArmTwinDriver] UrArmReceiver가 없습니다 — 같은 오브젝트에 붙이세요.", this);
        Debug.Log($"[UrArmTwinDriver] 관절 매핑 {_foundJoints}/{_joints.Length}. "
                  + "구동은 기본 꺼짐 — driveEnabled를 켜면 URSim/실물 실제각을 따라갑니다.");
    }

    [Tooltip("켜면 관절을 xDrive 스프링(stiffness/damping)에 맡기지 않고 매 물리 틱마다 " +
             "각도를 직접 박아 넣는다 — 빠른 추종 시 스프링이 목표를 지나쳤다 되돌아오며 " +
             "떠는(오버슈트) 현상 자체가 없어진다. lerpSpeed·각속도 상한(maxStep)은 그대로 " +
             "적용되므로 부드러움은 유지된다. 기본 켜짐(2026-09-22, 빠른 조그 시 흔들림 보고).")]
    public bool bypassPhysicsSpring = true;

    void FixedUpdate()
    {
        if (receiver == null || _joints == null) return;

        // 이 드라이버가 손을 놓는 순간(다른 방향으로 전환) 스프링을 원래 세기로 딱 한 번
        // 되돌린다 — 안 하면 PicknPlaceArmJointPanel(Unity→URSim 쪽) 등 다른 조작 경로가
        // 스프링 힘이 0인 채로 넘겨받아 팔이 힘없이 늘어진다(2026-09-22 실측 버그).
        // 매 틱 계속 되돌리면 그 반대(다른 경로가 의도적으로 0을 유지하려는 경우)와 다투므로
        // 전환 "순간"에만 1회 실행한다.
        if (!driveEnabled)
        {
            if (_wasDriving) RestoreSprings();
            _wasDriving = false;
            return;
        }
        _wasDriving = true;
        if (!receiver.GetAngles(_target)) return;

        float t = Mathf.Clamp01(Time.fixedDeltaTime * lerpSpeed);
        for (int i = 0; i < _joints.Length; i++)
        {
            var body = _joints[i];
            if (body == null) continue;
            var drive = body.xDrive;
            // Lerp은 "느낌"만 부드럽게 할 뿐 **속도 상한이 없다** — 오차가 크면 첫 틱에
            // 그만큼 크게 튄다(오차 비례). 그래서 실물이 낼 수 없는 순간이동처럼 보였다.
            // 실물 UR16e의 관절 최대 각속도(URDF → UrArmLimits.MaxDegPerSec, 어깨 120,
            // 팔꿈치·손목 180 deg/s)를 틱당 이동량으로 환산해 위에 한 번 더 clamp한다.
            // Lerp는 부드러움, 이 clamp는 물리적 상한 — 둘의 역할이 다르므로 둘 다 둔다.
            float smoothed = Mathf.Lerp(drive.target, _target[i], t);
            float maxStep = UrArmLimits.MaxDegPerSec[i] * Time.fixedDeltaTime;
            smoothed = Mathf.Clamp(smoothed, drive.target - maxStep, drive.target + maxStep);
            drive.target = smoothed;

            // 미러링은 "명령 포즈를 눈에 보이게 재현"하는 게 목적이라 스프링이 있을 이유가
            // 없다 — stiffness/damping을 0으로 꺼서 힘 자체가 안 나가게 하고, 각도는
            // jointPosition으로 직접 적용한다(2026-09-22: target만 갱신하고 힘은 살려두는
            // 이전 방식이 xDrive 힘과 직접 대입이 같은 틱에서 서로 다퉈 미세하게 떨림 — 스프링을
            // 완전히 꺼야 그 다툼 자체가 사라진다).
            if (bypassPhysicsSpring)
            {
                drive.stiffness = 0f;
                drive.damping = 0f;
                body.xDrive = drive;
                body.jointPosition = new ArticulationReducedSpace(smoothed * Mathf.Deg2Rad);
                body.jointVelocity = new ArticulationReducedSpace(0f);
            }
            else
            {
                // 토글을 끄면 시작 시점의 스프링 세기로 복원 — 0으로 꺼진 채 남지 않게.
                drive.stiffness = _origStiffness[i];
                drive.damping = _origDamping[i];
                body.xDrive = drive;
            }
        }
    }

    void RestoreSprings()
    {
        for (int i = 0; i < _joints.Length; i++)
        {
            var body = _joints[i];
            if (body == null) continue;
            var drive = body.xDrive;
            drive.stiffness = _origStiffness[i];
            drive.damping = _origDamping[i];
            body.xDrive = drive;
        }
    }

    void OnGUI()
    {
        if (!showUI) return;
        GUILayout.BeginArea(DemoUiLayout.Right(60f), GUI.skin.box);
        bool next = GUILayout.Toggle(driveEnabled, driveEnabled ? " UR 트윈 구동 ON" : " UR 트윈 구동 OFF");
        if (next != driveEnabled)
        {
            driveEnabled = next;
            Debug.Log($"[UrArmTwinDriver] 구동 {(driveEnabled ? "ON" : "OFF")}");
        }
        // IsFresh(HasData && 끊긴 지 오래 안 됨)를 본다 — HasData만 보면 브리지가 죽은
        // 뒤에도 "수신중"으로 계속 표시된다(2026-09-21 수정).
        GUILayout.Label(receiver != null && receiver.IsFresh ? "수신중" : "대기중");
        GUILayout.EndArea();
    }
}
