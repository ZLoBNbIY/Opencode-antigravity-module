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


if __name__ == "__main__":
    unittest.main()
