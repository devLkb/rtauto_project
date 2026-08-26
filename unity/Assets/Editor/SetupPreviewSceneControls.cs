using Unity.Robotics.UrdfImporter;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Preview 씬(UR16eDG5FRight_Preview.unity)의 로봇 루트에 Play 모드 조작에 필요한
/// 컴포넌트를 자동으로 붙인다: HandSliderUI(관절 슬라이더 조작), RobotSelfCollisionIgnore
/// (DG5F 손가락 자기충돌로 인한 접촉 진동/튕김 방지 — Assets/Scripts/RobotSelfCollisionIgnore.cs 참고).
/// </summary>
public static class SetupPreviewSceneControls
{
    private const string ScenePath = "Assets/Scenes/UR16eDG5FRight_Preview.unity";

    [MenuItem("KDT/Preview Scene에 조작 컴포넌트 추가")]
    public static void Run()
    {
        var scene = EditorSceneManager.GetActiveScene();
        if (scene.path != ScenePath)
            scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

        var urdfRobot = Object.FindObjectOfType<UrdfRobot>();
        if (urdfRobot == null)
        {
            Debug.LogError("[SetupPreviewSceneControls] 씬에서 UrdfRobot 컴포넌트를 찾지 못했습니다.");
            return;
        }

        GameObject root = urdfRobot.gameObject;

        // URDF Importer는 base link ArticulationBody를 기본적으로 immovable로 고정하지 않는다
        // (패키지 코드 전체에서 RuntimeUrdfImporterExample.cs 외엔 설정하는 곳이 없음).
        // 고정 안 하면 Play 시작 시 중력+xDrive 힘이 섞여 로봇 전체가 허공에서 튕겨 날아간다.
        foreach (var ab in root.GetComponentsInChildren<ArticulationBody>())
        {
            if (ab.isRoot)
            {
                ab.immovable = true;
                Debug.Log($"[SetupPreviewSceneControls] '{ab.name}' (root ArticulationBody) immovable = true 설정.");
            }
        }

        if (root.GetComponent<HandSliderUI>() == null)
            root.AddComponent<HandSliderUI>();
        else
            Debug.Log("[SetupPreviewSceneControls] HandSliderUI 이미 있음, 건너뜀.");

        if (root.GetComponent<RobotSelfCollisionIgnore>() == null)
            root.AddComponent<RobotSelfCollisionIgnore>();
        else
            Debug.Log("[SetupPreviewSceneControls] RobotSelfCollisionIgnore 이미 있음, 건너뜀.");

        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        AssetDatabase.SaveAssets();

        Debug.Log($"[SetupPreviewSceneControls] '{root.name}'에 HandSliderUI + RobotSelfCollisionIgnore 추가 완료, 씬 저장함.");
    }
}
