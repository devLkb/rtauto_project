using System.Collections;
using System.IO;
using Mujoco;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.TestTools;

namespace KDT.MjThroughput
{
    // Phase 0 A/B spike: measure MjScene step rate with N parallel training areas,
    // each a clone of ur16e_dg5f_right.sim.mjcf.xml, all compiled into one MjScene
    // (single physics world) like a real ML-Agents multi-area training setup.
    public class MjThroughputTests
    {
        // Uses a ".stl"-lowercased copy of the sim mjcf: the plugin's MjImporterWithAssets
        // does a case-sensitive extension check and rejects the DG5F hand's original
        // "*.STL" filenames (NotImplementedException) even though Windows resolves the
        // path fine and Python MuJoCo loads the original file without issue. Editor-import
        // quirk only - the canonical ur16e_dg5f_right.sim.mjcf.xml is untouched.
        static string MjcfPath => Path.GetFullPath(Path.Combine(
            Application.dataPath, "..", "..",
            "urdf", "ur16e_dg5f_right_build", "ur16e_dg5f_right.sim.forunity.mjcf.xml"));

        const string TemplateDir = "Assets/Local/MjImports";
        const string PrefabPath = "Assets/Local/MjImports/ur16e_dg5f_right_area_template.prefab";
        const string PrefabNoGlobalsPath = "Assets/Local/MjImports/ur16e_dg5f_right_area_template_noglobals.prefab";

        // ImportFile() generates a randomly-suffixed "Assets/Local/MjImports/<name+rand>/Resources"
        // folder of baked mesh/material assets on every call, which becomes orphaned once we
        // delete the prefabs below - track it so CleanupTemplate() can remove it too.
        private string _generatedMeshAssetsDir;

        [OneTimeSetUp]
        public void ImportTemplateOnce()
        {
            if (!Directory.Exists(TemplateDir))
            {
                Directory.CreateDirectory(TemplateDir);
            }
            var beforeDirs = new System.Collections.Generic.HashSet<string>(Directory.GetDirectories(TemplateDir));

            var importer = new MjImporterWithAssets();
            GameObject template = importer.ImportFile(MjcfPath);
            Assert.IsNotNull(template, "MJCF import failed - see previous log errors.");

            foreach (var dir in Directory.GetDirectories(TemplateDir))
            {
                if (!beforeDirs.Contains(dir))
                {
                    _generatedMeshAssetsDir = dir.Replace('\\', '/');
                }
            }
            PrefabUtility.SaveAsPrefabAsset(template, PrefabPath);

            // MjGlobalSettings.Awake() throws if a second instance appears anywhere in the
            // scene, and that check fires the instant Instantiate() runs (before we get a
            // chance to destroy the clone's copy) - so areas 1..N-1 must be instantiated from
            // a variant prefab that never had a Global Settings child in the first place.
            var globals = template.transform.Find("Global Settings");
            if (globals != null)
            {
                Object.DestroyImmediate(globals.gameObject);
            }
            PrefabUtility.SaveAsPrefabAsset(template, PrefabNoGlobalsPath);

            Object.DestroyImmediate(template);
            AssetDatabase.SaveAssets();

            // The source mjcf assumes a 0.002s / implicitfast physics step (needed for the
            // finger actuators to stay stable) - Unity's own fixedDeltaTime drives MjScene,
            // not the mjcf's own <option timestep>, so it must be set here explicitly.
            Time.fixedDeltaTime = 0.002f;
        }

        [OneTimeTearDown]
        public void CleanupTemplate()
        {
            if (AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath) != null)
            {
                AssetDatabase.DeleteAsset(PrefabPath);
            }
            if (AssetDatabase.LoadAssetAtPath<GameObject>(PrefabNoGlobalsPath) != null)
            {
                AssetDatabase.DeleteAsset(PrefabNoGlobalsPath);
            }
            if (!string.IsNullOrEmpty(_generatedMeshAssetsDir) && AssetDatabase.IsValidFolder(_generatedMeshAssetsDir))
            {
                AssetDatabase.DeleteAsset(_generatedMeshAssetsDir);
            }
        }

        [UnityTest] public IEnumerator ParallelAreaThroughput_1Area() => ParallelAreaThroughput(1);
        [UnityTest] public IEnumerator ParallelAreaThroughput_2Areas() => ParallelAreaThroughput(2);
        [UnityTest] public IEnumerator ParallelAreaThroughput_5Areas() => ParallelAreaThroughput(5);
        [UnityTest] public IEnumerator ParallelAreaThroughput_10Areas() => ParallelAreaThroughput(10);
        [UnityTest] public IEnumerator ParallelAreaThroughput_20Areas() => ParallelAreaThroughput(20);

        private IEnumerator ParallelAreaThroughput(int areaCount)
        {
            var prefabWithGlobals = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            var prefabNoGlobals = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabNoGlobalsPath);
            if (prefabWithGlobals == null || prefabNoGlobals == null)
            {
                Debug.LogError("[MjThroughput] template prefab missing - OneTimeSetUp must have failed.");
                yield break;
            }

            for (int i = 0; i < areaCount; i++)
            {
                // MjGlobalSettings is a scene-wide singleton - only area 0 may have one.
                GameObject instance = Object.Instantiate(i == 0 ? prefabWithGlobals : prefabNoGlobals);
                instance.name = $"area_{i}";
                instance.transform.position = new Vector3(i * 3f, 0f, 0f);
            }

            // Give MjScene's singleton Start() a frame to compile the combined model.
            yield return null;
            yield return null;

            if (!MjScene.InstanceExists)
            {
                Debug.LogError($"[MjThroughput] areas={areaCount}: no MjScene instance was created.");
                yield break;
            }

            const int targetSteps = 200;
            int steps = 0;
            float t0 = Time.realtimeSinceStartup;
            while (steps < targetSteps)
            {
                yield return new WaitForFixedUpdate();
                steps++;
            }
            float elapsed = Time.realtimeSinceStartup - t0;
            double stepsPerSec = steps / elapsed;
            double simTimeRatio = stepsPerSec * Time.fixedDeltaTime;

            Debug.Log($"[MjThroughput] RESULT areas={areaCount} steps={steps} " +
                      $"wallSec={elapsed:F3} stepsPerSec={stepsPerSec:F1} " +
                      $"realtimeRatio={simTimeRatio:F2}x");

            if (MjScene.InstanceExists)
            {
                Object.DestroyImmediate(MjScene.Instance.gameObject);
            }
            for (int i = 0; i < areaCount; i++)
            {
                var go = GameObject.Find($"area_{i}");
                if (go != null)
                {
                    Object.DestroyImmediate(go);
                }
            }
        }
    }
}
