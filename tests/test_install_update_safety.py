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


if __name__ == "__main__":
    unittest.main()
