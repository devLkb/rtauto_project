using System.IO;
using Unity.Robotics.UrdfImporter;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class ImportUr16eDg5fRightPreview
{
    [MenuItem("KDT/Import UR16e+DG5F-Right Preview Scene")]
    public static void Run()
    {
        string urdfPath = "Assets/Robots/ur16e_dg5f_right/ur16e_dg5f_right.urdf";
        string absPath = Path.GetFullPath(urdfPath);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        var settings = new ImportSettings();
        var enumerator = UrdfRobotExtensions.Create(absPath, settings, false);
        enumerator.MoveNext();
        GameObject robot = enumerator.Current;

        if (robot == null)
        {
            Debug.LogError("[ImportUr16eDg5fRightPreview] Import returned null robot GameObject.");
            return;
        }

        robot.transform.position = Vector3.zero;

        var camGo = GameObject.Find("Main Camera");
        if (camGo != null)
        {
            camGo.transform.position = new Vector3(1.5f, 1.2f, 1.5f);
            camGo.transform.LookAt(new Vector3(0, 0.5f, 0));
        }

        Directory.CreateDirectory("Assets/Scenes");
        string scenePath = "Assets/Scenes/UR16eDG5FRight_Preview.unity";
        EditorSceneManager.SaveScene(scene, scenePath);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"[ImportUr16eDg5fRightPreview] Imported '{robot.name}' and saved scene to {scenePath}");
    }
}
