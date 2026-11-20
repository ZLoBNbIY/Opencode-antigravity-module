import importlib.util
from pathlib import Path
import unittest


SUPPORT = Path(__file__).resolve().parents[1] / "packaging" / "windows"
spec = importlib.util.spec_from_file_location("release_version", SUPPORT / "release_version.py")
release_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_version)


class WindowsReleaseVersionTests(unittest.TestCase):
    def test_first_build_increments_baseline(self):
        self.assertEqual(release_version.release_tag([], []), ("v2.0.1", False))

    def test_increments_patch_numerically_and_ignores_prereleases(self):
        tags = ["v2.3.10", "v2.3.9", "v9.9.9-beta", "v2.3.010", "windows-build"]
        self.assertEqual(release_version.release_tag(tags, []), ("v2.3.11", False))

    def test_retry_reuses_tag_at_same_commit(self):
        self.assertEqual(release_version.release_tag(["v2.0.1", "v2.0.2"], ["v2.0.1"]),
                         ("v2.0.1", True))

    def test_windows_version_limit_is_reported(self):
        with self.assertRaises(ValueError):
            release_version.release_tag(["v2.0.65535"], [])
