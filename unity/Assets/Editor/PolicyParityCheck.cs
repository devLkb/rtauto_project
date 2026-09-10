// 게이트 1 — ONNX 정책의 Unity 다리 검증.
//
// superdex/scripts/export_onnx.py 가 만든 ONNX와 파리티 fixture를 읽어, Unity
// Inference Engine(구 Sentis, com.unity.ai.inference)으로 추론한 결과가 Python 쪽
// (SuperDex/RLlib 경로 + onnxruntime)과 허용 오차 내에서 일치하는지 확인한다.
//
// ⚠️ ML-Agents를 거치지 않는다. ML-Agents 공식 문서가 "외부에서 학습한 모델은 Sentis를
//    직접 쓰라"고 명시한다. BehaviorParameters에 꽂는 경로는 ML-Agents가 굽는 ONNX의
//    I/O 규약을 전제하므로 여기서는 쓸 수 없다.
//
// 실행 (터미널 1, PowerShell, 리포 루트):
//   & "C:\Program Files\Unity\Hub\Editor\6000.4.0f1\Editor\Unity.exe" -batchmode -quit `
//       -projectPath unity -executeMethod RtAuto.EditorTools.PolicyParityCheck.RunFromCommandLine `
//       -logFile -
// 종료 코드 0 = 통과, 2 = 오차 초과, 3 = 자산/fixture 문제.
//
// 에디터에서 직접 돌릴 때: 상단 메뉴 `RtAuto > Policy Parity Check`.

using System;
using System.Globalization;
using System.IO;
using Newtonsoft.Json.Linq;
using Unity.InferenceEngine;
using UnityEditor;
using UnityEngine;

namespace RtAuto.EditorTools
{
    public static class PolicyParityCheck
    {
        // ONNX는 Unity가 임포트 시점에 ModelAsset으로 변환하므로 Assets 안에 있어야 한다
        // (런타임 ONNX 로드는 지원되지 않는다). fixture는 저장소 원본을 그대로 읽는다 —
        // 같은 파일을 두 곳에 두지 않기 위해서다.
        const string kPolicyAssetDir = "Assets/Policies";
        const string kFixtureRepoDir = "superdex/policies";
        const string kDefaultName = "cart_pole_ppo";

        [MenuItem("RtAuto/Policy Parity Check")]
        public static void RunFromMenu()
        {
            Run(kDefaultName, out string report);
            Debug.Log(report);
        }

        public static void RunFromCommandLine()
        {
            string name = kDefaultName;
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-policyName") name = args[i + 1];
            }

            int code = Run(name, out string report);
            Debug.Log(report);
            EditorApplication.Exit(code);
        }

        /// <summary>0 = 통과, 2 = 오차 초과, 3 = 자산/fixture 문제.</summary>
        public static int Run(string policyName, out string report)
        {
            var log = new System.Text.StringBuilder();
            log.AppendLine("=== Policy Parity Check (Unity Inference Engine) ===");

            // 경로는 RtautoConfig 를 거친다 (원칙 1 — 리포 루트를 직접 계산하지 않는다).
            string fixturePath = RtautoConfig.GetRepoPath(
                Path.Combine(kFixtureRepoDir, policyName + ".parity.json"));
            string assetPath = $"{kPolicyAssetDir}/{policyName}.onnx";

            log.AppendLine($"fixture : {fixturePath}");
            log.AppendLine($"model   : {assetPath}");

            if (!File.Exists(fixturePath))
            {
                report = log.AppendLine($"[FAIL] fixture 파일이 없다. 먼저 실행: " +
                                        $"python superdex/scripts/export_onnx.py --checkpoint ...").ToString();
                return 3;
            }

            var modelAsset = AssetDatabase.LoadAssetAtPath<ModelAsset>(assetPath);
            if (modelAsset == null)
            {
                report = log.AppendLine(
                    $"[FAIL] ModelAsset을 못 찾았다. superdex/policies/{policyName}.onnx 를 " +
                    $"{kPolicyAssetDir}/ 로 복사한 뒤 Unity가 임포트하도록 한다.").ToString();
                return 3;
            }

            JObject fx = JObject.Parse(File.ReadAllText(fixturePath));
            int obsDim = fx["obs_dim"].Value<int>();
            int actDim = fx["act_dim"].Value<int>();
            double tol = fx["tolerance"].Value<double>();
            string specVersion = fx["policy_spec_version"].Value<string>();
            var obsRows = (JArray)fx["obs"];
            var expRows = (JArray)fx["expected_action"];
            int n = obsRows.Count;

            log.AppendLine($"spec    : {specVersion}");
            log.AppendLine($"shape   : obs {n}x{obsDim} -> action {n}x{actDim}, tol {tol:E1}");

            var flatObs = new float[n * obsDim];
            var flatExp = new float[n * actDim];
            for (int i = 0; i < n; i++)
            {
                var o = (JArray)obsRows[i];
                for (int j = 0; j < obsDim; j++) flatObs[i * obsDim + j] = o[j].Value<float>();
                var e = (JArray)expRows[i];
                for (int j = 0; j < actDim; j++) flatExp[i * actDim + j] = e[j].Value<float>();
            }

            Model model = ModelLoader.Load(modelAsset);
            using var worker = new Worker(model, BackendType.CPU);
            using var input = new Tensor<float>(new TensorShape(n, obsDim), flatObs);

            worker.SetInput("obs", input);
            worker.Schedule();

            using var output = (worker.PeekOutput("action") as Tensor<float>).ReadbackAndClone();
            float[] got = output.DownloadToArray();

            if (got.Length != flatExp.Length)
            {
                report = log.AppendLine(
                    $"[FAIL] 출력 크기 불일치: got {got.Length}, expected {flatExp.Length}").ToString();
                return 3;
            }

            double maxErr = 0.0;
            int worstIdx = 0;
            for (int i = 0; i < got.Length; i++)
            {
                double d = Math.Abs(got[i] - flatExp[i]);
                if (d > maxErr) { maxErr = d; worstIdx = i; }
            }

            log.AppendLine($"최대 오차: {maxErr.ToString("E3", CultureInfo.InvariantCulture)} " +
                           $"(index {worstIdx}: unity {got[worstIdx]:F6} vs python {flatExp[worstIdx]:F6})");

            bool pass = maxErr <= tol;
            log.AppendLine(pass
                ? "=== 판정: 통과 — Unity 다리가 Python 경로와 일치한다 ==="
                : $"=== 판정: 실패 — 허용 오차 {tol:E1} 초과 ===");

            report = log.ToString();
            return pass ? 0 : 2;
        }
    }
}
