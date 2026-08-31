// RtautoConfig.cs
// 런타임에서 저장소 루트의 .env / .env.example을 읽어 설정값을 얻는다.
//
// 왜 필요한가 (CLAUDE.md 원칙 1): 포트·IP의 유일한 정본은 config/rtauto_config.py이고
// 그 값은 레포 루트 .env(.env.example 복사본)로 관리한다. Unity C#은 파이썬 모듈을
// import할 수 없으므로, 지금까지는 같은 숫자를 C#에 다시 타이핑할 수밖에 없었다.
// 그러면 .env에서 포트를 바꿨을 때 파이썬은 새 포트로 쏘고 Unity는 옛 포트에서 계속
// 기다린다 — 에러 하나 없이 손만 안 움직이는 조용한 실패가 된다.
// 이 클래스가 그 간극을 메워, 양쪽이 항상 같은 파일 하나를 보게 만든다.
//
// 우선순위는 파이썬 쪽 config/rtauto_config.py와 동일하게 맞춘다:
//   프로세스 환경변수 > 레포 .env > 레포 .env.example > 코드 기본값
//
// 설계 원칙: 절대 예외를 던지지 않는다. 파일이 없거나(standalone 빌드) 읽기에 실패하면
// 조용히 기본값으로 떨어진다. 시연 도중 설정 파일 때문에 씬이 죽는 일은 없어야 한다.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

public static class RtautoConfig
{
    static Dictionary<string, string> _values;
    static string _sourceLabel = "코드 기본값";

    /// 이번 세션에서 설정값을 어디서 읽었는지 (로그용).
    public static string SourceLabel
    {
        get { EnsureLoaded(); return _sourceLabel; }
    }

    /// 정수 설정값. 없거나 파싱 실패면 fallback.
    public static int GetInt(string key, int fallback)
    {
        string raw = GetString(key, null);
        if (string.IsNullOrEmpty(raw)) return fallback;
        return int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed)
            ? parsed
            : fallback;
    }

    /// 문자열 설정값. 없으면 fallback.
    public static string GetString(string key, string fallback)
    {
        EnsureLoaded();

        // 1) 프로세스 환경변수가 최우선 (파이썬 쪽과 동일한 규칙)
        try
        {
            string fromEnv = Environment.GetEnvironmentVariable(key);
            if (!string.IsNullOrEmpty(fromEnv)) return fromEnv;
        }
        catch (Exception)
        {
            // 일부 플랫폼(WebGL 등)은 환경변수 접근을 막는다 — 파일 값으로 진행
        }

        return _values != null && _values.TryGetValue(key, out string value) ? value : fallback;
    }

    /// 저장소 루트 기준 상대경로를 절대경로로 바꾼다. 이미 절대경로면 그대로 돌려준다.
    /// 루트를 못 찾으면(standalone 빌드 등) null — 호출부가 조용히 건너뛸 수 있게 예외는 안 던진다.
    /// config/rtauto_config.py가 "상대경로는 저장소 루트 기준"으로 다루는 규칙과 같게 맞춘 것이다.
    public static string GetRepoPath(string relativeOrAbsolute)
    {
        if (string.IsNullOrEmpty(relativeOrAbsolute)) return null;
        try
        {
            if (Path.IsPathRooted(relativeOrAbsolute)) return relativeOrAbsolute;
            string root = ResolveRepositoryRoot();
            return root == null ? null : Path.Combine(root, relativeOrAbsolute);
        }
        catch (Exception)
        {
            return null;
        }
    }

    static void EnsureLoaded()
    {
        if (_values != null) return;
        _values = new Dictionary<string, string>(StringComparer.Ordinal);

        string repoRoot = ResolveRepositoryRoot();
        if (repoRoot == null) return;

        // .env.example을 먼저 깔고 .env로 덮어쓴다 — .env가 더 높은 우선순위.
        var sources = new List<string>();
        if (Merge(Path.Combine(repoRoot, ".env.example"))) sources.Add(".env.example");
        if (Merge(Path.Combine(repoRoot, ".env"))) sources.Add(".env");
        if (sources.Count > 0) _sourceLabel = string.Join(" + ", sources.ToArray());
    }

    /// 레포 루트 = Unity 프로젝트 폴더(unity/)의 부모. Application.dataPath는 unity/Assets.
    /// standalone 빌드에서는 이 경로에 .env가 없고, 그때는 그냥 기본값을 쓴다.
    static string ResolveRepositoryRoot()
    {
        try
        {
            DirectoryInfo projectRoot = Directory.GetParent(Application.dataPath);
            return projectRoot?.Parent?.FullName;
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// KEY=value 파일을 읽어 _values에 병합. 읽었으면 true.
    /// 파이썬 _load_dotenv와 같은 관용 처리: BOM, 값의 따옴표, `export ` 접두사.
    static bool Merge(string path)
    {
        try
        {
            if (!File.Exists(path)) return false;
            foreach (string rawLine in File.ReadAllLines(path))
            {
                string line = rawLine.Trim();
                if (line.Length == 0 || line[0] == '#') continue;
                if (line.StartsWith("export ", StringComparison.Ordinal))
                    line = line.Substring("export ".Length).TrimStart();

                int eq = line.IndexOf('=');
                if (eq <= 0) continue;

                // File.ReadAllLines는 UTF-8 BOM을 알아서 벗기지만, 다른 인코딩으로 저장된
                // 파일에서 U+FEFF가 남아 첫 키가 조용히 무시되는 걸 막는다.
                string key = line.Substring(0, eq).Trim().TrimStart('\uFEFF');
                string value = line.Substring(eq + 1).Trim();
                if (value.Length >= 2 && value[0] == value[value.Length - 1]
                    && (value[0] == '"' || value[0] == '\''))
                    value = value.Substring(1, value.Length - 2);

                if (key.Length > 0) _values[key] = value;
            }
            return true;
        }
        catch (Exception)
        {
            // 파일이 잠겨있거나 권한이 없어도 시연을 막지 않는다
            return false;
        }
    }
}
