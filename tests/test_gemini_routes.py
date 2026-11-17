import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import gemini_routes


class GeminiRouteListTests(unittest.TestCase):
    def test_parser_preserves_exact_and_suffix_match_semantics(self):
        domains, exact = gemini_routes._parse("""
            # comment
            gemini.google
            full:geminiweb-pa.clients.google.com
            include:google-deepmind
        """)
        self.assertEqual(domains, {"gemini.google"})
        self.assertEqual(exact, {"geminiweb-pa.clients.google.com"})

    def test_parser_strips_v2fly_attributes_and_skips_regexp(self):
        domains, exact = gemini_routes._parse("""
            domain:gemini.google.com @cn
            full:ai.google.dev:@ads
            regexp:.*gemini.*
            keyword:google
        """)
        self.assertEqual(domains, {"gemini.google.com"})
        self.assertEqual(exact, {"ai.google.dev"})


if __name__ == "__main__":
    unittest.main()
