from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))

import jsonc_config


class JsoncConfigTests(unittest.TestCase):
    def test_rejects_non_json_constants_in_input_and_edits(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                original = '{"nested": [' + constant + ']}'
                with self.assertRaises(ValueError):
                    jsonc_config.parse_config(original)
                with self.assertRaises(ValueError):
                    jsonc_config.set_property(original, ("new",), 1)
                with self.assertRaises(ValueError):
                    jsonc_config.set_property('{"nested": {}}', ("nested",), {"value": float(constant)})
        self.assertEqual(jsonc_config.parse_config('{"name": "NaN"}'), {"name": "NaN"})

    def test_trailing_comma_requires_preceding_value(self):
        for text in ("{,}", '{"a": [,]}', '{"a":[1,,]}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                jsonc_config.parse_config(text)
        self.assertEqual(jsonc_config.parse_config('{\r// Comment\r"a":[1,],\r}'), {"a": [1]})

    def test_path_selection_does_not_treat_inaccessible_as_missing(self):
        with TemporaryDirectory() as root, patch.object(Path, "lstat", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                jsonc_config.config_path(Path(root))
