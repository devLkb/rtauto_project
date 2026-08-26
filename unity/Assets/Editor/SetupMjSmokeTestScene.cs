using System.IO;
using KDT.MjSmokeTest;
using Mujoco;
using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Policies;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SetupMjSmokeTestScene
{
    const string MjcfPath = "urdf/ur16e_dg5f_right_build/ur16e_dg5f_right.sim.forunity.mjcf.xml";

    [MenuItem("KDT/Setup MjSmokeTest Scene")]
    public static void Run()
    {
        string absMjcfPath = Path.GetFullPath(MjcfPath);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        var importer = new MjImporterWithAssets();
        GameObject robot = importer.ImportFile(absMjcfPath);
        if (robot == null)
        {
            Debug.LogError("[SetupMjSmokeTestScene] MJCF import failed.");
            return;
        }
        robot.name = "area_0";

        var behaviorParams = robot.AddComponent<BehaviorParameters>();
        behaviorParams.BehaviorName = "MjSmokeTest";
        behaviorParams.BrainParameters.VectorObservationSize = 12;
        behaviorParams.BrainParameters.NumStackedVectorObservations = 1;
        behaviorParams.BrainParameters.ActionSpec = ActionSpec.MakeContinuous(6);

        var decisionRequester = robot.AddComponent<DecisionRequester>();
        decisionRequester.DecisionPeriod = 5;

        robot.AddComponent<MjSmokeTestAgent>();

        Directory.CreateDirectory("Assets/Scenes");
        string scenePath = "Assets/Scenes/MjSmokeTest.unity";
        EditorSceneManager.SaveScene(scene, scenePath);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"[SetupMjSmokeTestScene] Scene saved to {scenePath}");
    }
}
