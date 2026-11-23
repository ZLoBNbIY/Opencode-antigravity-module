import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui-manager"))
import auto_updater


class UpdateSafetyTests(unittest.TestCase):
    local = "a" * 40
    remote = "b" * 40

    def run_update(self, *, status="", operation=None, fetch_code=0, ancestry=(1, 0), merge_code=0,
                   resulting_head=None, branch=auto_updater.UPSTREAM_REF, rewrite=False):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            if operation:
                (repo / ".git").mkdir()
                (repo / ".git" / operation).touch()

            def fake_run(command, **kwargs):
                self.assertEqual(command[0], "git")
                self.assertIn("core.hooksPath=/dev/null", command)
                args = next(command[i:] for i, arg in enumerate(command)
                            if arg in {"rev-parse", "symbolic-ref", "status", "ls-remote", "fetch", "merge-base", "merge"})
                calls.append(args)
                rc, stdout = 0, ""
                if args == ["rev-parse", "--show-toplevel"]:
                    stdout = str(repo)
                elif args == ["rev-parse", "--verify", "HEAD"]:
                    stdout = (resulting_head or self.remote) if any(c[0] == "merge" for c in calls) else self.local
                elif args[:2] == ["rev-parse", "--git-path"]:
                    stdout = f".git/{args[2]}"
                elif args[0] == "symbolic-ref":
                    stdout = branch
                elif args[0] == "status":
                    stdout = status
                elif args[:2] == ["ls-remote", "--get-url"]:
                    stdout = "https://other.example/repo" if rewrite else auto_updater.UPSTREAM_URL
                elif args[0] == "ls-remote":
                    self.assertEqual(args[2:], [auto_updater.UPSTREAM_URL, auto_updater.UPSTREAM_REF])
                    stdout = f"{self.remote}\t{auto_updater.UPSTREAM_REF}"
                elif args[0] == "fetch":
                    self.assertEqual(args[-2:], [auto_updater.UPSTREAM_URL, self.remote])
                    self.assertIn("--no-write-fetch-head", args)
                    rc = fetch_code
                elif args[0] == "merge-base":
                    rc = ancestry[0 if args[2] == self.remote else 1]
                elif args[0] == "merge":
                    self.assertEqual(args, ["merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", self.remote])
                    rc = merge_code
                else:
                    self.fail(f"Unexpected Git command: {args}")
                return subprocess.CompletedProcess(command, rc, stdout, "mock failure" if rc else "")

            with patch.object(auto_updater.subprocess, "run", side_effect=fake_run):
                ok, message = auto_updater.apply_update_git(repo)
        return ok, message, [args[0] for args in calls]

    def test_refuses_dirty_branch_in_progress_or_wrong_branch_without_fetch(self):
        for params in [{"status": "?? unsaved"}, {"operation": "MERGE_HEAD"}, {"branch": "refs/heads/work"}]:
            with self.subTest(params=params):
                ok, _, calls = self.run_update(**params)
                self.assertFalse(ok)
                self.assertNotIn("ls-remote", calls)
                self.assertNotIn("merge", calls)

    def test_refuses_git_url_rewrite_without_fetching_or_merging(self):
        ok, message, calls = self.run_update(rewrite=True)
        self.assertFalse(ok)
        self.assertIn("перенаправляет", message)
        self.assertEqual(calls.count("ls-remote"), 1)
        self.assertNotIn("fetch", calls)
        self.assertNotIn("merge", calls)

    def test_fetch_failure_or_divergence_does_not_merge(self):
        for params in [{"fetch_code": 1}, {"ancestry": (1, 1)}]:
            with self.subTest(params=params):
                ok, _, calls = self.run_update(**params)
                self.assertFalse(ok)
                self.assertIn("fetch", calls)
                self.assertNotIn("merge", calls)

    def test_already_in_history_is_not_reapplied(self):
        ok, _, calls = self.run_update(ancestry=(0, 1))
        self.assertTrue(ok)
        self.assertNotIn("merge", calls)

    def test_fast_forward_reports_unsigned_and_does_not_execute_scripts(self):
        ok, message, calls = self.run_update()
        self.assertTrue(ok)
        self.assertIn("Подпись коммита не проверялась", message)
        self.assertIn("патчи не запускались", message)
        self.assertEqual(calls.count("status"), 2)
        self.assertEqual(calls[-2:], ["merge", "rev-parse"])

    def test_merge_failure_or_unconfirmed_head_is_not_reported_as_success(self):
        for params in [{"merge_code": 1}, {"resulting_head": self.local}]:
            with self.subTest(params=params):
                ok, message, calls = self.run_update(**params)
                self.assertFalse(ok)
                self.assertIn("Проверьте git status и HEAD", message)
                self.assertIn("откат не выполнялся", message)
                self.assertIn("merge", calls)


@unittest.skipUnless(shutil.which("git"), "requires Git")
class OfflineGitUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.git("init", "--initial-branch=V2")
        self.git("config", "user.name", "Updater Test")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        self.base = self.commit("original")
        self.git("switch", "-c", "advertised")
        self.target = self.commit("updated")
        self.git("switch", "V2")

    def git(self, *args):
        result = subprocess.run(
            ["git", *args], cwd=self.repo, env=auto_updater._direct_git_env(),
            text=True, capture_output=True, check=True, timeout=15,
        )
        return result.stdout.strip()

    def commit(self, content):
        (self.repo / "fixture.txt").write_text(content, encoding="utf-8")
        self.git("add", "fixture.txt")
        self.git("commit", "-m", content)
        return self.git("rev-parse", "HEAD")

    def apply_offline(self):
        # Stand in for HTTPS discovery and transport only. Real Git checks
        # the fixture's HEAD, operation state, ancestors, and ff-only merge.
        git_output = auto_updater._git_output

        def output(repo, *args, **kwargs):
            if args[0] == "fetch":
                self.assertEqual(args[-2:], (auto_updater.UPSTREAM_URL, self.target))
                return git_output(repo, "cat-file", "-e", self.target + "^{commit}")
            return git_output(repo, *args, **kwargs)

        with patch.object(auto_updater, "_upstream_sha", return_value=self.target), \
             patch.object(auto_updater, "_git_output", side_effect=output):
            return auto_updater.apply_update_git(self.repo, expected_commit=self.target)

    def test_real_fast_forward_does_not_write_tracking_refs_or_fetch_head(self):
        before = self.git("for-each-ref", "refs/remotes", "refs/tags")
        ok, message = self.apply_offline()
        self.assertTrue(ok, message)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.target)
        self.assertEqual((self.repo / "fixture.txt").read_text(encoding="utf-8"), "updated")
        self.assertEqual(self.git("for-each-ref", "refs/remotes", "refs/tags"), before)
        self.assertFalse((self.repo / ".git" / "FETCH_HEAD").exists())

    def test_real_divergence_keeps_local_commit_and_worktree(self):
        local = self.commit("local edit")
        ok, message = self.apply_offline()
        self.assertFalse(ok, message)
        self.assertIn("разошлась", message)
        self.assertEqual(self.git("rev-parse", "HEAD"), local)
        self.assertEqual((self.repo / "fixture.txt").read_text(encoding="utf-8"), "local edit")

    def test_real_untracked_file_and_in_progress_operation_stop_before_transport(self):
        untracked = self.repo / "do not remove.txt"
        operation = self.repo / ".git" / "MERGE_HEAD"
        for path in (untracked, operation):
            with self.subTest(path=path.name):
                path.write_text(self.target + "\n", encoding="ascii")
                with patch.object(auto_updater, "_upstream_sha") as upstream:
                    ok, message = auto_updater.apply_update_git(self.repo)
                    self.assertFalse(ok, message)
                    upstream.assert_not_called()
                self.assertEqual(path.read_text(encoding="ascii"), self.target + "\n")
                self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
                path.unlink()

    def test_real_file_transport_is_denied_and_rewrite_is_rejected(self):
        self.git("config", "url." + self.repo.as_uri() + ".insteadOf", auto_updater.UPSTREAM_URL)
        with self.assertRaisesRegex(RuntimeError, "перенаправляет"):
            auto_updater._upstream_sha(self.repo)
        with self.assertRaisesRegex(RuntimeError, "transport 'file' not allowed"):
            auto_updater._git_output(self.repo, "ls-remote", self.repo.as_uri())

    def test_update_advisory_ignores_replacement_refs(self):
        self.git("switch", "advertised")
        replacement = self.commit("replacement")
        self.git("switch", "V2")
        self.git("replace", self.base, replacement)
        self.git("merge-base", "--is-ancestor", self.target, "HEAD")
        self.assertTrue(auto_updater._has_newer_remote_commit(self.repo, self.base, self.target))


def find_bash():
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


@unittest.skipUnless(find_bash(), "requires Bash (Git Bash on Windows)")
class ShellInstallSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "config home" / "opencode"
        self.source = self.root / "module source"
        self.source.mkdir()
        shutil.copyfile(ROOT / "install.sh", self.source / "install.sh")
        (self.source / "config-templates").mkdir()
        (self.source / "scripts").mkdir()
        (self.source / "gui-manager").mkdir()
        (self.source / "scripts" / "patch_plugin.mjs").touch()
        (self.source / "gui-manager" / "requirements.txt").touch()
        for name in ("opencode.json", "antigravity.json"):
            (self.source / "config-templates" / name).write_text('{"fresh": true}\n', encoding="utf8")

    def run_install(self, *args, setup=""):
        env = dict(os.environ, XDG_CONFIG_HOME=str(self.config.parent), MOCK_SOURCE=str(self.source))
        env.pop("OPENCODE_CONFIG_DIR", None)
        script = (
            'if command -v cygpath >/dev/null 2>&1; then '
            'XDG_CONFIG_HOME="$(cygpath -u "$XDG_CONFIG_HOME")"; '
            'MOCK_SOURCE="$(cygpath -u "$MOCK_SOURCE")"; fi\n'
            + setup + '\nsource "$MOCK_SOURCE/install.sh" "$@"'
        )
        return subprocess.run([find_bash(), "-c", script, "mock-install", *args], env=env,
                              capture_output=True, text=True, errors="replace", timeout=20)

    def test_existing_unparseable_jsonc_and_antigravity_are_preserved_byte_for_byte(self):
        self.config.mkdir(parents=True)
        existing = {"opencode.jsonc": b"\xef\xbb\xbf{ // keep every byte\r\n",
                    "antigravity.json": b"broken config\r\n"}
        for name, data in existing.items():
            (self.config / name).write_bytes(data)
        result = self.run_install("--skip-patch", "--skip-python")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("were not updated or validated", result.stdout)
        self.assertEqual({p.name: p.read_bytes() for p in self.config.iterdir()}, existing)

    def test_new_config_is_published_and_temp_files_are_removed(self):
        result = self.run_install("--skip-patch", "--skip-python")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in self.config.iterdir()), ["antigravity.json", "opencode.json"])

    def test_failed_mock_patch_stops_without_success_message(self):
        result = self.run_install("--skip-python", setup='node() { if [[ "$1" == "-e" ]]; then return 0; fi; return 29; }')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("exit 29", result.stderr)
        self.assertNotIn("Installer steps completed", result.stdout)
        self.assertFalse(list(self.config.glob(".antigravity-install-*")))

    def test_failed_mock_pip_stops_without_success_message(self):
        result = self.run_install("--skip-patch", setup='python3() { if [[ "$*" == *"pip install"* ]]; then return 27; fi; }')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("exit 27", result.stderr)
        self.assertIn("unlocked GUI requirements", result.stderr)
        self.assertNotIn("Installer steps completed", result.stdout)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "requires Windows PowerShell")
class PowerShellInstallSafetyTests(unittest.TestCase):
    def test_config_publisher_preserves_jsonc_and_creates_missing_file(self):
        # Import only the config-publishing function, never the installer body.
        # All writes are confined to a disposable fixture directory.
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            config = fixture / "config folder"
            config.mkdir()
            jsonc = config / "opencode.jsonc"
            original = b"\xef\xbb\xbf{ // keep this unparseable JSONC\r\n"
            jsonc.write_bytes(original)
            template = fixture / "template.json"
            template.write_bytes(b'{"fresh": true}\r\n')
            harness = fixture / "mock.ps1"
            harness.write_text(
                r"""
param($Installer, $Config, $Template)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Installer, [ref]$tokens, [ref]$errors)
if ($errors) { throw ($errors | Out-String) }
$publisher = $ast.Find({
    param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Publish-NewConfig'
}, $false)
. ([scriptblock]::Create($publisher.Extent.Text))
Publish-NewConfig $Template (Join-Path $Config 'opencode.json') @('opencode.json', 'opencode.jsonc')
Publish-NewConfig $Template (Join-Path $Config 'antigravity.json') @('antigravity.json')
""",
                encoding="ascii",
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness),
                 str(ROOT / "install.ps1"), str(config), str(template)],
                capture_output=True, text=True, errors="replace", timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name: p.read_bytes() for p in config.iterdir()},
                             {"opencode.jsonc": original, "antigravity.json": template.read_bytes()})


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "requires Windows PowerShell")
class PowerShellUninstallSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fixture = Path(temp.name)

    def invoke_functions(self, names, commands, script="uninstall.ps1"):
        harness = self.fixture / "harness.ps1"
        harness.write_text(
            r"""
param($ScriptPath, $Fixture)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
if ($errors) { throw ($errors | Out-String) }
""" + "$names = @(" + ", ".join(f"'{name}'" for name in names) + ")\n" + r"""
foreach ($name in $names) {
    $function = $ast.Find({
        param($Node)
        $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $name
    }, $false)
    if (-not $function) { throw "Missing $name" }
    . ([scriptblock]::Create($function.Extent.Text))
}
""" + commands,
            encoding="ascii",
        )
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness),
             str(ROOT / script), str(self.fixture.resolve())],
            capture_output=True, text=True, errors="replace", timeout=15,
        )

    def run_removal(self, content, name="opencode.json"):
        config = self.fixture / name
        config.write_bytes(content)
        result = self.invoke_functions(
            ["Get-SafeFile", "Get-JsonValueEnd", "Get-JsonString", "Test-HubPluginEntry",
             "Get-HubPluginRemoval", "Remove-HubPlugin"],
            f"Remove-HubPlugin (Join-Path $Fixture '{name}')\n",
        )
        self.assertEqual(sorted(p.name for p in self.fixture.iterdir()), ["harness.ps1", name])
        return result, config.read_bytes()

    def test_removes_v1_and_v2_by_span_without_changing_user_settings(self):
        content = (
            b'\xef\xbb\xbf{\r\n  "n": 9007199254740993, "plugin": ['
            b'["@cortexkit/opencode-antigravity-auth@latest",{}], "keep-v1"],\r\n'
            b'  "nested": {"plugin": ["@cortexkit/opencode-antigravity-auth"]},\r\n'
            b'  "pl\\u0075gins": ["first", {"package":"@cortexkit/opencode-antigravity-auth@3.0.0",'
            b'"options":{"nested":[1,2]}}, {"package": "./local","options":{"x":1}},'
            b'"@cortexkit/opencode-antigravity-auth", "@cortexkit/opencode-antigravity-auth-extra"]\r\n}\r\n'
        )
        expected = (
            b'\xef\xbb\xbf{\r\n  "n": 9007199254740993, "plugin": [ "keep-v1"],\r\n'
            b'  "nested": {"plugin": ["@cortexkit/opencode-antigravity-auth"]},\r\n'
            b'  "pl\\u0075gins": ["first",  {"package": "./local","options":{"x":1}},'
            b' "@cortexkit/opencode-antigravity-auth-extra"]\r\n}\r\n'
        )
        result, actual = self.run_removal(content)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(actual, expected)
        result, actual = self.run_removal(actual)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(actual, expected)

    def test_removes_scalar_and_only_array_entry(self):
        content = (b'{"plugin":"@cortexkit/opencode-antigravity-auth",'
                   b'"plugins":[{"package":"@cortexkit/opencode-antigravity-auth"}]}')
        result, actual = self.run_removal(content)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(actual, b'{"plugin":[],"plugins":[]}')

    def test_retains_jsonc_and_ambiguous_json(self):
        for name, content in (
            ("opencode.jsonc", b'{"plugins": ["@cortexkit/opencode-antigravity-auth"], // comment\n}'),
            ("opencode.json", b'{"plugins":[{"package":"other","package":"@cortexkit/opencode-antigravity-auth"}]}'),
        ):
            with self.subTest(name=name):
                result, actual = self.run_removal(content, name)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(actual, content)
                (self.fixture / name).unlink()

    def test_source_cleanup_requires_exact_shortcut_and_autostart_targets(self):
        result = self.invoke_functions(["Test-SourceShortcut", "Test-SourceAutostart"], r"""
$checkout = Join-Path $Fixture 'checkout copy'
$script = Join-Path $checkout 'gui-manager\antigravity_manager.pyw'
$launcher = Join-Path $checkout 'gui-manager\start_manager.bat'
$real = '"C:\Example Python\pythonw.exe" "' + $script + '"'
if (-not (Test-SourceAutostart $real $checkout)) { throw 'Did not identify source command' }
foreach ($command in @("$real --extra", '"C:\Other\AntigravityHub.exe"',
                        '"C:\Other\pythonw.exe" "C:\Other\gui-manager\antigravity_manager.pyw"')) {
    if (Test-SourceAutostart $command $checkout) { throw "Foreign command matched: $command" }
}
$link = [pscustomobject]@{TargetPath=$launcher; Arguments=''}
if (-not (Test-SourceShortcut $link $checkout)) { throw 'Did not identify source shortcut' }
$link.Arguments = '--more'
if (Test-SourceShortcut $link $checkout) { throw 'Shortcut with extra arguments matched' }
$link.Arguments = ''
foreach ($target in @("C:\Other\gui-manager\start_manager.bat", "$launcher.extra", "C:\AI HUB\AntigravityHub.exe")) {
    $link.TargetPath = $target
    if (Test-SourceShortcut $link $checkout) { throw "Foreign shortcut matched: $target" }
}
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
