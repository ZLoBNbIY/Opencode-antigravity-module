import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ("server.js", "index.js")


class Gemini4RouteTests(unittest.TestCase):
    def read_bundle(self, name):
        return (ROOT / "plugin" / "dist" / name).read_text(encoding="utf-8")

    def test_hydrogen_routes_to_the_available_sonar_wire_model(self):
        for name in BUNDLES:
            text = self.read_bundle(name)
            self.assertIn(
                'getDynamicWireModel("antigravity-gemini-4-hydrogen") || "gemini-4-hydrogen-sonar"',
                text,
                name,
            )

    def test_argon_is_not_advertised_until_the_account_catalog_lists_it(self):
        for name in BUNDLES:
            text = self.read_bundle(name)
            block = re.search(r"var ANTIGRAVITY_OPENCODE_MODEL_IDS = \[(.*?)\];", text, re.S)
            self.assertIsNotNone(block, name)
            self.assertNotIn('"antigravity-gemini-4-argon"', block.group(1), name)
            self.assertIn('"antigravity-gemini-4-hydrogen"', block.group(1), name)

    def test_catalog_sync_merges_both_endpoints_and_detects_gemini4(self):
        text = self.read_bundle("server.js")
        self.assertIn("Object.assign(mergedModels, data.models)", text)
        self.assertIn("const hydrogenWireModel = modelEntries", text)
        self.assertIn("const argonWireModel = modelEntries", text)
        self.assertNotIn(
            'ensureDynamicModelDefinition("antigravity-gemini-4-argon");\n'
            '  ensureDynamicModelDefinition("antigravity-gemini-4-hydrogen");',
            text,
        )

    def test_hub_health_probe_uses_the_sonar_wire_model(self):
        sys.path.insert(0, str(ROOT / "gui-manager"))
        import health_checker
        mapping = health_checker.ANTIGRAVITY_MODEL_INTERNAL_MAP
        self.assertEqual(mapping["antigravity-gemini-4-hydrogen"][1], "gemini-4-hydrogen-sonar")
        self.assertEqual(mapping["gemini-4-hydrogen"][1], "gemini-4-hydrogen-sonar")


if __name__ == "__main__":
    unittest.main()
