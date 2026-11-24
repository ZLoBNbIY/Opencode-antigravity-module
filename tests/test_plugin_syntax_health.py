"""Offline regressions for Node-backed plugin health and self-heal."""
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from test_plugin_v2_layout import V2_SOURCE, patcher, write_bundle


class PluginSyntaxHealthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.node = self.root / "node.exe"
        self.node.write_bytes(b"placeholder executable; subprocess is mocked")
        self.enterContext(patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}))
        self.which = self.enterContext(patch.object(patcher.shutil, "which", return_value=str(self.node)))
        self.run = self.enterContext(patch.object(patcher.subprocess, "run", side_effect=self.success))
        source = patcher._plan_gemini4_v2(V2_SOURCE)
        source = patcher._apply_exact_edits(source, patcher._route_edits_v2(source))
        source = patcher._plan_quota_breaker(source)
        self.healthy = patcher._plan_cloaking(source).encode("utf-8")

    def success(self, args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "", "")

    def bundle(self, name="server.js", content=None):
        target = write_bundle(self.root, name, "")
        target.write_bytes(self.healthy if content is None else content)
        package_json = target.parent.parent / "package.json"
        package_json.write_text(json.dumps({"version": "3.1.13", "type": "module"}), encoding="utf-8")
        return target

    def test_packaged_hub_prefers_its_bundled_node(self):
        bundled = self.root / "playwright" / "driver" / "node.exe"
        bundled.parent.mkdir(parents=True)
        bundled.touch()
        with patch.object(patcher.sys, "frozen", True, create=True), \
                patch.object(patcher.sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(patcher._find_syntax_node(), str(bundled))
        self.which.assert_not_called()

    def test_windows_hidden_snapshot_shared_with_cloaking_and_reused_across_polls(self):
        source = self.healthy.replace(b"\n", b"\r\n")
        self.bundle(content=source)
        self.bundle("index.js", source)

        def inspect_snapshot(args, **kwargs):
            node, check, filename = args
            self.assertEqual(node, str(self.node))
            self.assertEqual(check, "--check")
            self.assertEqual(kwargs["creationflags"], 0x08000000)
            snapshot = Path(filename)
            self.assertEqual(snapshot.suffix, ".mjs")
            self.assertEqual(snapshot.read_bytes(), source)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return self.success(args)

        self.run.side_effect = inspect_snapshot
        with patch.object(patcher.sys, "platform", "win32"), \
                patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            self.assertTrue(patcher._cloaking_syntax_ok(source.decode("utf-8")))
            for _ in range(3):
                health = patcher.verify_plugin_health(self.root)
                self.assertTrue(health["ok"], health)
                self.assertTrue(health["syntax_checked"])
                self.assertFalse(health["syntax_unavailable"])
                self.assertEqual(health["cloaking"]["active"], 2)
        self.run.assert_called_once()
        self.assertFalse(Path(self.run.call_args.args[0][-1]).exists())

    def test_new_bytes_node_and_nearest_package_mode_invalidate_cache(self):
        target = self.bundle()
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        target.write_bytes(self.healthy + b"\n// changed bytes\n")
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        replacement = self.node.with_suffix(".new")
        replacement.write_bytes(b"new executable")
        replacement.replace(self.node)
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        (target.parent / "package.json").write_text('{"type": "commonjs"}', encoding="utf-8")
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        self.assertEqual([Path(call.args[0][-1]).suffix for call in self.run.call_args_list],
                         [".mjs", ".mjs", ".mjs", ".cjs"])

    def test_transient_failures_do_not_become_reasons_and_are_retried(self):
        self.bundle()
        failures = [subprocess.CompletedProcess([], 1, "", ""),
                    subprocess.CompletedProcess([], 1, "", "Error: cannot open snapshot"),
                    OSError("process failed to spawn"), subprocess.TimeoutExpired("node", 30)]
        self.run.side_effect = [*failures, self.success([])]
        for failure in failures:
            with self.subTest(failure=failure):
                health = patcher.verify_plugin_health(self.root)
                self.assertFalse(health["ok"])
                self.assertEqual(health["state"], "syntax_unavailable")
                self.assertTrue(health["syntax_unavailable"])
                self.assertFalse(health["syntax_checked"])
                self.assertEqual(health["reasons"], [])
                self.assertEqual(health["quota_breaker"]["state"], "active")
                self.assertEqual(health["cloaking"]["state"], "active")
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        self.assertEqual(self.run.call_count, 5)

    def test_parser_error_is_real_drift_and_is_not_cached(self):
        self.bundle(content=self.healthy + b"\nconst broken = ;\n")
        self.run.side_effect = None
        self.run.return_value = subprocess.CompletedProcess(
            [], 1, "", "\nSyntaxError: Unexpected token ';'\n    at checkSyntax\n")
        for _ in range(2):
            health = patcher.verify_plugin_health(self.root)
            self.assertEqual(health["state"], "unsupported")
            self.assertTrue(health["syntax_checked"])
            self.assertFalse(health["syntax_unavailable"])
            self.assertEqual(health["reasons"], ["server.js: JS syntax error: SyntaxError: Unexpected token ';'"])
        self.assertEqual(self.run.call_count, 2)

    def test_concurrent_checks_share_in_flight_transient_result_but_retry_later(self):
        self.bundle()
        entered, joined, release = Event(), Event(), Event()

        class ObservedFuture(Future):
            def result(self):
                joined.set()
                return super().result(timeout=10)

        def temporary_failure(args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("did not release Node check")
            return subprocess.CompletedProcess(args, 1, "", "")

        self.run.side_effect = temporary_failure
        with patch.object(patcher, "Future", ObservedFuture), ThreadPoolExecutor(2) as workers:
            first = workers.submit(patcher.verify_plugin_health, self.root)
            try:
                self.assertTrue(entered.wait(10))
                second = workers.submit(patcher.verify_plugin_health, self.root)
                self.assertTrue(joined.wait(10))
            finally:
                release.set()
            self.assertTrue(first.result(timeout=10)["syntax_unavailable"])
            self.assertTrue(second.result(timeout=10)["syntax_unavailable"])
        self.run.assert_called_once()
        self.run.side_effect = self.success
        self.assertTrue(patcher.verify_plugin_health(self.root)["ok"])
        self.assertEqual(self.run.call_count, 2)

    def test_self_heal_does_not_patch_or_persist_when_only_node_is_missing(self):
        self.bundle()
        path = self.root / "patch-state.json"
        verified = b'{"verified_version":"3.1.13","verified_sha256":{"3.1.13:server.js":"prior"}}'
        self.which.return_value = None
        with patch.object(patcher, "patch_prompt_sanitizer") as apply:
            for prior in (None, verified):
                if prior is not None:
                    path.write_bytes(prior)
                result = patcher.self_heal_plugin(self.root, path)
                self.assertEqual(result["state"], "syntax_unavailable")
                self.assertFalse(result["ok"])
                self.assertTrue(result["syntax_unavailable"])
                self.assertEqual(result["reasons"], [])
                self.assertEqual(path.read_bytes() if path.exists() else None, prior)
        apply.assert_not_called()
        self.run.assert_not_called()

    def test_self_heal_repairs_real_drift_but_does_not_record_unchecked_result(self):
        target = self.bundle(content=V2_SOURCE.encode("utf-8"))
        path = self.root / "patch-state.json"
        path.write_bytes(b'{"verified_version":"3.1.13","degraded":false}')
        before = path.read_bytes()

        def later_failure(args, **kwargs):
            if Path(args[-1]).read_bytes() != V2_SOURCE.encode("utf-8"):
                return subprocess.CompletedProcess(args, 1, "", "")
            return self.success(args)

        self.run.side_effect = later_failure
        result = patcher.self_heal_plugin(self.root, path)
        self.assertEqual(result["state"], "syntax_unavailable")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["quota_breaker"]["state"], "active")
        self.assertEqual(result["cloaking"]["state"], "pending")
        self.assertNotEqual(target.read_bytes(), V2_SOURCE.encode("utf-8"))
        self.assertEqual(path.read_bytes(), before)

        self.run.side_effect = self.success
        result = patcher.self_heal_plugin(self.root, path)
        self.assertEqual(result["state"], "healed")
        self.assertTrue(result["syntax_checked"])
        self.assertEqual(patcher.load_patch_state(self.root, path)["verified_sha256"],
                         {"3.1.13:server.js": sha256(target.read_bytes()).hexdigest()})

    def test_self_heal_saves_only_the_checked_snapshot_if_the_live_bundle_changes(self):
        target = self.bundle()
        replacement = self.healthy + b"\n// replaced while Node checks\n"

        def update_while_checking(args, **kwargs):
            self.assertEqual(Path(args[-1]).read_bytes(), self.healthy)
            target.write_bytes(replacement)
            return self.success(args)

        self.run.side_effect = update_while_checking
        path = self.root / "patch-state.json"
        self.assertTrue(patcher.self_heal_plugin(self.root, path)["ok"])
        self.assertEqual(patcher.load_patch_state(self.root, path)["verified_sha256"],
                         {"3.1.13:server.js": sha256(self.healthy).hexdigest()})
        self.assertEqual(patcher.check_patch_state(self.root, path)["state"], "structure_changed")


class RealNodeSyntaxHealthTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed for this parser check")
    def test_same_bytes_pass_as_esm_but_fail_as_commonjs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = write_bundle(root, "server.js", "export const sample = 1;\n")
            package_json = target.parent.parent / "package.json"
            package_json.write_text('{"version":"3.1.13","type":"module"}', encoding="utf-8")
            health = patcher.verify_plugin_health(root)
            self.assertTrue(health["syntax_checked"], health)
            self.assertFalse(any("JS syntax error" in reason for reason in health["reasons"]))
            package_json.write_text('{"version":"3.1.13","type":"commonjs"}', encoding="utf-8")
            health = patcher.verify_plugin_health(root)
            self.assertTrue(health["syntax_checked"], health)
            self.assertFalse(health["syntax_unavailable"])
            self.assertTrue(any("JS syntax error" in reason for reason in health["reasons"]), health)


if __name__ == "__main__":
    unittest.main()
