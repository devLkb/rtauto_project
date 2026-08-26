using System;
using System.IO;
using KDT.MLAgents.Editor;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Editor
{
    public static class PicknPlaceTrainingBuild
    {
        const string TrainingScene = "Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity";

        [MenuItem("Tools/ML-Agents/Build DG5F PicknPlace Linux Player")]
        public static void BuildLinuxPlayer()
        {
            PicknPlaceTrainingSceneBuilder.Build();

            BuildEnvironment environment = BuildEnvironment.Load();
            string outputDirectory = environment.GetPath("DG5F_PICKNPLACE_BUILD_OUTPUT");
            string playerName = environment.GetFileName("DG5F_PICKNPLACE_PLAYER_NAME");
            string dataDirectoryName =
                Path.GetFileNameWithoutExtension(playerName) + "_Data";
            Directory.CreateDirectory(outputDirectory);

            var options = new BuildPlayerOptions
            {
                scenes = new[] { TrainingScene },
                locationPathName = Path.Combine(outputDirectory, playerName),
                target = BuildTarget.StandaloneLinux64,
                subtarget = (int)StandaloneBuildSubtarget.Player,
                options = BuildOptions.None
            };

            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException(
                    $"PicknPlace build failed: {report.summary.result}, "
                    + $"errors={report.summary.totalErrors}");

            LinuxPlayerPostProcess.Apply(environment, outputDirectory, dataDirectoryName);

            Debug.Log($"[PicknPlaceTrainingBuild] Built {options.locationPathName}");
        }
    }
}
