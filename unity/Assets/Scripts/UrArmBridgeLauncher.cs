// UrArmBridgeLauncher.cs
// Unity에서 버튼 하나로 arm/ur_rtde_bridge.py를 띄우고 내린다 — 터미널을 따로 열어
// venv를 활성화하고 명령을 치는 단계를 없애기 위한 것.
//
//   실행되는 명령 (작업 디렉터리 = 저장소 루트):
//     <RTAUTO_PYTHON> arm/ur_rtde_bridge.py --ip --echo-to-unity
//
// 파이썬 경로의 정본은 config/rtauto_config.py(PYTHON_EXE) = 레포 루트 .env의
// RTAUTO_PYTHON이고, 이 스크립트도 RtautoConfig로 같은 파일을 읽는다 (원칙 1).
// .env에 값이 없을 때만 OS별 공용 venv 기본 경로(docs/PYTHON_ENV_SETUP.md §2의
// vision/.vision)로 떨어진다 — 파이썬 쪽 rtauto_config.python_exe()와 같은 기본값이라
// 한쪽만 고치면 "터미널에서는 되는데 버튼으로는 안 된다"가 된다. 함께 고칠 것.
//
// ⚠️ Play를 멈출 때 반드시 프로세스를 죽인다. 살아남으면 UDP 포트를 계속 쥐고 있어
//    다음 실행이 "바인드 실패"로 죽고, 더 나쁘게는 URSim/실물에 계속 명령을 보낸다.
//    OnDisable(Play 정지)·OnApplicationQuit 양쪽에서 정리한다.
//
// 콘솔 창을 띄우는 이유(showWindow 기본 켜짐): 브리지 로그([연결] RTDE 접속 완료,
// 바인드 실패 원인 등)를 사람이 그대로 봐야 문제를 짚을 수 있다. 창을 숨기면 Unity
// 안에서는 "왜 안 되는지"가 전혀 안 보인다.

using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using Debug = UnityEngine.Debug;

public class UrArmBridgeLauncher : MonoBehaviour
{
    [Tooltip("저장소 루트 기준 브리지 스크립트 경로")]
    public string scriptRelativePath = "arm/ur_rtde_bridge.py";
    [Tooltip("브리지에 넘길 인자. --ip는 .env의 RTAUTO_UR_IP를 쓰라는 뜻이고(값 생략), "
             + "--echo-to-unity는 URSim 실제각을 Unity로 되돌려 보내게 한다.")]
    public string arguments = "--ip --echo-to-unity";
    [Tooltip("브리지 콘솔 창을 띄운다. 끄면 로그를 볼 수 없어 문제 원인 파악이 어렵다.")]
    public bool showWindow = true;

    Process _process;
    string _status = "대기 중";

    /// 지금 브리지가 돌고 있는가. 죽은 프로세스 핸들은 여기서 정리한다.
    public bool IsRunning
    {
        get
        {
            if (_process == null) return false;
            try
            {
                if (!_process.HasExited) return true;
                _status = $"종료됨 (코드 {_process.ExitCode})";
                _process.Dispose();
                _process = null;
                return false;
            }
            catch (InvalidOperationException)
            {
                _process = null;
                return false;
            }
        }
    }

    public string Status => _status;

    /// 브리지 실행. 이미 돌고 있으면 아무것도 하지 않는다.
    public bool Launch()
    {
        if (IsRunning) return true;

        string repoRoot = RtautoConfig.RepoRoot;
        if (string.IsNullOrEmpty(repoRoot))
        {
            _status = "저장소 루트를 못 찾음 (빌드된 플레이어에서는 지원 안 함)";
            Debug.LogError("[UrArmBridgeLauncher] " + _status, this);
            return false;
        }

        string python = ResolvePython(repoRoot);
        if (!File.Exists(python))
        {
            _status = "파이썬 없음 — venv 먼저 만들 것";
            Debug.LogError(
                $"[UrArmBridgeLauncher] 파이썬을 찾지 못했습니다: {python}\n"
                + "docs/PYTHON_ENV_SETUP.md §2대로 공용 venv(vision/.vision)를 만들거나, "
                + "레포 루트 .env에 RTAUTO_PYTHON=<파이썬 경로>를 넣으세요.", this);
            return false;
        }

        string script = Path.Combine(repoRoot, scriptRelativePath);
        if (!File.Exists(script))
        {
            _status = "브리지 스크립트 없음";
            Debug.LogError($"[UrArmBridgeLauncher] 스크립트가 없습니다: {script}", this);
            return false;
        }

        try
        {
            var info = new ProcessStartInfo
            {
                FileName = python,
                // 스크립트 경로는 저장소 상대로 넘긴다 — 작업 디렉터리가 루트라 그대로 열리고,
                // 콘솔에 찍히는 명령이 문서(README)의 명령과 같은 모양이 된다.
                Arguments = $"\"{scriptRelativePath}\" {arguments}",
                WorkingDirectory = repoRoot,
                UseShellExecute = showWindow,   // true여야 별도 콘솔 창이 열린다
                CreateNoWindow = !showWindow,
            };
            _process = Process.Start(info);
            _status = _process != null ? "실행 중" : "실행 실패";
            Debug.Log($"[UrArmBridgeLauncher] 실행: {python} {info.Arguments}  (cwd={repoRoot})");
            return _process != null;
        }
        catch (Exception e)
        {
            _process = null;
            _status = "실행 실패: " + e.Message;
            Debug.LogError("[UrArmBridgeLauncher] " + _status, this);
            return false;
        }
    }

    /// 브리지 종료. Play 정지 시에도 호출된다 — 안 죽이면 포트를 쥔 채 남는다.
    public void Stop()
    {
        if (_process == null) return;
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill();
                // 포트가 실제로 풀릴 때까지 잠깐 기다린다. 바로 다음 실행이 같은 포트를
                // 바인드하려다 실패하는 것을 막는다.
                _process.WaitForExit(2000);
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning("[UrArmBridgeLauncher] 종료 중 예외 — " + e.Message);
        }
        finally
        {
            try { _process.Dispose(); } catch (Exception) { }
            _process = null;
            _status = "중지됨";
        }
    }

    /// .env의 RTAUTO_PYTHON, 없으면 OS별 공용 venv 기본 경로.
    /// config/rtauto_config.py의 python_exe()와 같은 규칙을 유지할 것.
    static string ResolvePython(string repoRoot)
    {
        string configured = RtautoConfig.GetString("RTAUTO_PYTHON", "");
        if (!string.IsNullOrEmpty(configured))
        {
            return Path.IsPathRooted(configured)
                ? configured
                : Path.Combine(repoRoot, configured);
        }
#if UNITY_EDITOR_WIN || UNITY_STANDALONE_WIN
        return Path.Combine(repoRoot, "vision/.vision/Scripts/python.exe");
#else
        return Path.Combine(repoRoot, "vision/.vision/bin/python");
#endif
    }

    void OnDisable()
    {
        // Play 정지·컴포넌트 비활성 모두 여기로 온다.
        Stop();
    }

    void OnApplicationQuit()
    {
        Stop();
    }
}
