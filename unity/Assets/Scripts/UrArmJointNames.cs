// UrArmJointNames.cs
// UR16e 팔 6관절의 ArticulationBody 이름(URDF 링크명). 순서 = shoulder_pan, shoulder_lift,
// elbow, wrist_1, wrist_2, wrist_3.
//
// ⚠️ KDT.PicknPlaceTraining.Dg5fPicknPlaceSpec.ArmLinks와 값이 같아야 하지만 그걸 직접
// 참조하지 않는다: 이 파일이 속한 어셈블리(KDT.RobotScripts)는 더 아래 계층이고
// KDT.PicknPlaceTraining이 이미 KDT.RobotScripts를 참조하고 있어(그 asmdef의 references),
// 반대 방향 참조를 걸면 순환 참조로 컴파일이 깨진다. 이 값(URDF 링크명)은 로봇 모델이
// 바뀌지 않는 한 안 바뀌는 하드웨어 상수라 두 곳에 값을 나란히 두는 쪽을 택했다 —
// Dg5fPicknPlaceSpec.ArmLinks를 바꾸면 이 배열도 함께 바꿀 것.
public static class UrArmJointNames
{
    public static readonly string[] Names =
    {
        "shoulder_link", "upper_arm_link", "forearm_link",
        "wrist_1_link", "wrist_2_link", "wrist_3_link"
    };
}
