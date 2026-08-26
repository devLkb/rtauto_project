using Unity.Robotics.UrdfImporter;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// One-time bootstrap for PicknPlaceTrainingSceneBuilder: it needs
/// Assets/Robots/Prefabs/ur16e_dg5f_right.prefab (mirroring the existing
/// ur5e_dg5f_left.prefab / ur5e_dg5f_right.prefab), but only the URDF-imported
/// scene instance in UR16eDG5FRight_Preview.unity exists so far — no prefab has
/// been extracted from it yet.
///
/// This duplicates that scene's robot (never touching the scene itself), strips
/// the preview-only HandSliderUI component (SetupPreviewSceneControls.cs added it
/// for manual joint-slider testing; it is not part of the DG5F 20-DOF hand and
/// PicknPlaceTrainingSceneBuilder.DisableCompetingDrivers would disable it anyway),
/// keeps RobotSelfCollisionIgnore (a real physics setup, not a preview-only
/// control), fixes the root ArticulationBody in place, and saves the result as a
/// new prefab asset.
/// </summary>
public static class CreateUr16eDg5fRightPrefab
{
    const string ScenePath = "Assets/Scenes/UR16eDG5FRight_Preview.unity";
    const string PrefabPath = "Assets/Robots/Prefabs/ur16e_dg5f_right.prefab";

    [MenuItem("Tools/Robots/Create UR16e DG5F Right Prefab")]
    public static void Run()
    {
        var scene = EditorSceneManager.GetActiveScene();
        if (scene.path != ScenePath)
            scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

        var urdfRobot = Object.FindObjectOfType<UrdfRobot>();
        if (urdfRobot == null)
        {
            Debug.LogError(
                "[CreateUr16eDg5fRightPrefab] No UrdfRobot found in "
                + $"{ScenePath}.");
            return;
        }

        // Work on a detached duplicate so the Preview scene is never modified by
        // this menu command.
        var duplicate = Object.Instantiate(urdfRobot.gameObject);
        duplicate.name = "ur16e_dg5f_right";

        var handSlider = duplicate.GetComponent<HandSliderUI>();
        if (handSlider != null) Object.DestroyImmediate(handSlider);

        foreach (var articulationBody in duplicate.GetComponentsInChildren<ArticulationBody>(true))
        {
            if (articulationBody.isRoot) articulationBody.immovable = true;
        }

        string folder = "Assets/Robots/Prefabs";
        if (!AssetDatabase.IsValidFolder(folder))
            AssetDatabase.CreateFolder("Assets/Robots", "Prefabs");

        PrefabUtility.SaveAsPrefabAsset(duplicate, PrefabPath);
        Object.DestroyImmediate(duplicate);

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"[CreateUr16eDg5fRightPrefab] Saved {PrefabPath}.");
    }
}
