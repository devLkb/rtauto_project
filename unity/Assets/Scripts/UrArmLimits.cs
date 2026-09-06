// UrArmLimits.cs
// UR16e 팔 6관절의 **실물 동작 한계** — 관절 최대 각속도[deg/s]와 최대 토크[N·m].
// 순서는 UrArmJointNames.Names와 동일하다
// (shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3).
//
// 정본 출처: unity/Assets/Robots/ur16e_dg5f_right/ur16e_dg5f_right.urdf 의
// <limit effort="..." velocity="..."/>. URDF가 이 값들의 유일한 근거이며, 속도는
// URDF의 rad/s를 deg/s로 환산한 것이다:
//
//   관절            effort[N·m]   velocity[rad/s]   → [deg/s]
//   shoulder_pan       330.0        2.0943951         120
//   shoulder_lift      330.0        2.0943951         120
//   elbow              150.0        3.1415927         180
//   wrist_1/2/3         54.0        3.1415927         180
//
// ⚠️ 이 파일이 **KDT.RobotScripts**(unity/Assets/Scripts/)에 있는 것은 의도적이다.
// 어셈블리 의존이 KDT.PicknPlaceTraining → KDT.RobotScripts 한 방향이라, 위층인
// Dg5fPicknPlaceSpec은 이 파일을 참조할 수 있지만 반대는 순환 참조로 컴파일이 깨진다.
// 여기(아래층)에 두어야 UrArmTwinDriver(RobotScripts)와 Dg5fPicknPlaceSpec/
// Dg5fPicknPlaceAgent(PicknPlaceTraining) 양쪽이 **같은 정본 하나**를 쓸 수 있다.
// 같은 사정이 UrArmJointNames.cs 주석에도 적혀 있다.
//
// 로봇이 UR16e가 아닌 기종으로 바뀌면 URDF와 함께 이 값도 바꿔야 한다 — 과거
// PicknPlace 씬이 UR5e에서 UR16e로 바뀌었을 때 씬 빌더의 토크 한계가 UR5e 값
// (150/28)으로 남아 있어, 시뮬레이터 팔이 실물의 절반 토크로 학습되던 버그가 있었다.
public static class UrArmLimits
{
    /// 관절 최대 각속도[deg/s]. UrArmJointNames.Names 순서.
    public static readonly float[] MaxDegPerSec = { 120f, 120f, 180f, 180f, 180f, 180f };

    /// 관절 최대 토크[N·m]. UrArmJointNames.Names 순서.
    public static readonly float[] MaxEffortNm = { 330f, 330f, 150f, 54f, 54f, 54f };

    /// UrArmJointNames.Names에서 링크 이름의 인덱스. 없으면 -1.
    /// 이름으로 위 배열을 찾을 때 인덱스를 맹목적으로 쓰지 않기 위한 것 —
    /// 씬에 예상 밖의 ArticulationBody가 섞여 있어도 조용히 잘못된 한계를 먹이지 않는다.
    public static int IndexOf(string linkName)
    {
        for (int i = 0; i < UrArmJointNames.Names.Length; i++)
            if (UrArmJointNames.Names[i] == linkName) return i;
        return -1;
    }
}
