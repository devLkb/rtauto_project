using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace KDT.MLAgents.Editor
{
    public sealed class BuildEnvironment
    {
        readonly IReadOnlyDictionary<string, string> defaultValues;
        readonly IReadOnlyDictionary<string, string> localValues;

        BuildEnvironment(
            string repositoryRoot,
            IReadOnlyDictionary<string, string> defaultValues,
            IReadOnlyDictionary<string, string> localValues)
        {
            RepositoryRoot = repositoryRoot;
            this.defaultValues = defaultValues;
            this.localValues = localValues;
        }

        public string RepositoryRoot { get; }

        public static BuildEnvironment Load()
        {
            string projectRoot =
                Directory.GetParent(Application.dataPath)?.FullName
                ?? throw new InvalidOperationException(
                    "Cannot resolve Unity project root.");
            string repositoryRoot =
                Directory.GetParent(projectRoot)?.FullName
                ?? throw new InvalidOperationException(
                    "Cannot resolve repository root.");

            return new BuildEnvironment(
                repositoryRoot,
                ReadDotEnv(Path.Combine(repositoryRoot, ".env.example")),
                ReadDotEnv(Path.Combine(repositoryRoot, ".env")));
        }

        public string GetPath(params string[] keys)
        {
            string configuredPath = GetValue(keys);
            return ResolvePath(configuredPath);
        }

        public bool TryGetPath(out string path, params string[] keys)
        {
            if (TryGetValue(out string configuredPath, keys))
            {
                path = ResolvePath(configuredPath);
                return true;
            }

            path = null;
            return false;
        }

        string ResolvePath(string configuredPath)
        {
            return Path.GetFullPath(
                Path.IsPathRooted(configuredPath)
                    ? configuredPath
                    : Path.Combine(RepositoryRoot, configuredPath));
        }

        public string GetFileName(params string[] keys)
        {
            string fileName = GetValue(keys);
            if (!string.Equals(
                    fileName,
                    Path.GetFileName(fileName),
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    $"{keys[0]} must be a file name, not a path: {fileName}");
            }

            return fileName;
        }

        /// Optional integer setting. Returns <paramref name="fallback"/> when the
        /// key is absent, and throws when it is present but not a positive
        /// integer — a typo in .env must not silently fall back to a different
        /// training scale than the one the operator wrote down.
        public int GetPositiveInt(int fallback, params string[] keys)
        {
            if (!TryGetValue(out string raw, keys))
                return fallback;
            if (!int.TryParse(raw, out int value) || value <= 0)
                throw new InvalidOperationException(
                    $"{keys[0]} must be a positive integer, got: {raw}");
            return value;
        }

        string GetValue(params string[] keys)
        {
            if (TryGetValue(out string value, keys))
                return value;

            throw new InvalidOperationException(
                $"Missing build setting: {string.Join(" or ", keys)}. "
                + "Restore .env.example or define the environment variable.");
        }

        bool TryGetValue(out string result, params string[] keys)
        {
            foreach (string key in keys)
            {
                string value = Environment.GetEnvironmentVariable(key);
                if (!string.IsNullOrWhiteSpace(value))
                {
                    result = value.Trim();
                    return true;
                }
            }

            foreach (string key in keys)
            {
                if (localValues.TryGetValue(key, out string value)
                    && !string.IsNullOrWhiteSpace(value))
                {
                    result = value;
                    return true;
                }
            }

            foreach (string key in keys)
            {
                if (defaultValues.TryGetValue(key, out string value)
                    && !string.IsNullOrWhiteSpace(value))
                {
                    result = value;
                    return true;
                }
            }

            result = null;
            return false;
        }

        static IReadOnlyDictionary<string, string> ReadDotEnv(string path)
        {
            var values = new Dictionary<string, string>(
                StringComparer.Ordinal);
            if (!File.Exists(path))
                return values;

            foreach (string sourceLine in File.ReadAllLines(path))
            {
                string line = sourceLine.Trim();
                if (line.Length == 0 || line.StartsWith("#"))
                    continue;
                if (line.StartsWith("export ", StringComparison.Ordinal))
                    line = line.Substring("export ".Length).TrimStart();

                int separator = line.IndexOf('=');
                if (separator <= 0)
                    continue;

                string key = line.Substring(0, separator).Trim();
                string value = line.Substring(separator + 1).Trim();
                if (value.Length >= 2
                    && ((value[0] == '"' && value[value.Length - 1] == '"')
                        || (value[0] == '\'' && value[value.Length - 1] == '\'')))
                {
                    value = value.Substring(1, value.Length - 2);
                }

                if (key.Length > 0)
                    values[key] = value;
            }

            return values;
        }
    }
}
