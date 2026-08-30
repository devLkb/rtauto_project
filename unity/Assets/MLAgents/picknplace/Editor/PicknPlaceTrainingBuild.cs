using System;
using System.IO;
using KDT.MLAgents.Editor;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace KDT.PicknPlaceTraining.Editor
{
    /// <summary>
    /// Standalone player builds for the DG5FPicknPlace behavior.
    ///
    /// Two targets, same scene. The Linux player is the legacy headless-server
    /// artefact; the Windows player exists because mlagents-learn's --num-envs
    /// (several player processes feeding one PPO update) only works against a
    /// built player, and the current training machine is a Windows desktop. The
    /// Unity Editor path stays available but is limited to a single environment.
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
                "DG5F_PICKNPLACE_PLAYER_NAME");
        }

        [MenuItem("Tools/ML-Agents/Build DG5F PicknPlace Windows Player")]
        public static void BuildWindowsPlayer()
        {
            BuildPlayer(
                BuildTarget.StandaloneWindows64,
                "DG5F_PICKNPLACE_WINDOWS_BUILD_OUTPUT",
                "DG5F_PICKNPLACE_WINDOWS_PLAYER_NAME");
        }

        static void BuildPlayer(BuildTarget target, string outputKey, string playerNameKey)
        {
            PicknPlaceTrainingSceneBuilder.Build();

            BuildEnvironment environment = BuildEnvironment.Load();
            string outputDirectory = environment.GetPath(outputKey);
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
                    $"PicknPlace build failed: {report.summary.result}, "
                    + $"errors={report.summary.totalErrors}");

            if (target == BuildTarget.StandaloneLinux64)
            {
                LinuxPlayerPostProcess.Apply(environment, outputDirectory, dataDirectoryName);
            }
            else
            {
                // ML-Agents writes --timer-path output here and does not create the
                // folder itself; same reason LinuxPlayerPostProcess creates it.
                Directory.CreateDirectory(Path.Combine(
                    outputDirectory, dataDirectoryName, "ML-Agents", "Timers"));
            }

            Debug.Log($"[PicknPlaceTrainingBuild] Built {options.locationPathName}");
        }
    }
}
