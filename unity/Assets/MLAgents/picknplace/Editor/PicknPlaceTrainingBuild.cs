using System;
using System.IO;
using KDT.MLAgents.Editor;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Builds the standalone player that <c>mlagents-learn --env=...</c> drives for
    /// headless DG5FPicknPlace training.
    ///
    /// Two targets exist because the training host changed. The Linux player was
    /// written for the (now retired) dedicated GPU Linux box; the only machine left
    /// is a local Windows workstation (RTX 2080) — see
    /// <c>training/archives/scripts/README.md</c>. Headless training on that machine
    /// needs a StandaloneWindows64 player, so the target-specific parts (build
    /// target, output/player-name keys, post-processing) are parameters of one
    /// shared routine rather than a second copy of it.
    ///
    /// Both entry points are callable from batchmode:
    ///   Unity -batchmode -quit -projectPath unity \
    ///     -executeMethod KDT.PicknPlaceTraining.Editor.PicknPlaceTrainingBuild.BuildWindowsPlayer
    /// </summary>
    public static class PicknPlaceTrainingBuild
    {
        const string TrainingScene = "Assets/MLAgents/picknplace/DG5F_PicknPlaceTraining.unity";

        [MenuItem("Tools/ML-Agents/Build DG5F PicknPlace Linux Player")]
        public static void BuildLinuxPlayer()
        {
            BuildPlayer(
                BuildTarget.StandaloneLinux64,
                "DG5F_PICKNPLACE_BUILD_OUTPUT",
                "DG5F_PICKNPLACE_PLAYER_NAME",
                applyLinuxPostProcess: true);
        }

        [MenuItem("Tools/ML-Agents/Build DG5F PicknPlace Windows Player")]
        public static void BuildWindowsPlayer()
        {
            BuildPlayer(
                BuildTarget.StandaloneWindows64,
                "DG5F_PICKNPLACE_WINDOWS_BUILD_OUTPUT",
                "DG5F_PICKNPLACE_WINDOWS_PLAYER_NAME",
                applyLinuxPostProcess: false);
        }

        static void BuildPlayer(
            BuildTarget target,
            string outputDirectoryKey,
            string playerNameKey,
            bool applyLinuxPostProcess)
        {
            PicknPlaceTrainingSceneBuilder.Build();

            BuildEnvironment environment = BuildEnvironment.Load();
            string outputDirectory = environment.GetPath(outputDirectoryKey);
            string playerName = environment.GetFileName(playerNameKey);
            string dataDirectoryName =
                Path.GetFileNameWithoutExtension(playerName) + "_Data";
            Directory.CreateDirectory(outputDirectory);

            var options = new BuildPlayerOptions
            {
                scenes = new[] { TrainingScene },
                locationPathName = Path.Combine(outputDirectory, playerName),
                target = target,
                subtarget = (int)StandaloneBuildSubtarget.Player,
                options = BuildOptions.None
            };

            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException(
                    $"PicknPlace {target} build failed: {report.summary.result}, "
                    + $"errors={report.summary.totalErrors}");

            if (applyLinuxPostProcess)
                LinuxPlayerPostProcess.Apply(environment, outputDirectory, dataDirectoryName);
            else
                // The Linux post-process also creates this folder; the ML-Agents
                // profiler writes its timer JSON here at shutdown and fails the run
                // if the directory is missing.
                Directory.CreateDirectory(Path.Combine(
                    outputDirectory, dataDirectoryName, "ML-Agents", "Timers"));

            Debug.Log($"[PicknPlaceTrainingBuild] Built {options.locationPathName}");
        }
    }
}
