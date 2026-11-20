import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui-manager"))

from vless_exit import VlessExitStatus, _fetch, probe_vless_exit


class VlessExitTests(unittest.TestCase):
    def test_fetch_uses_explicit_tunnel_on_active_port(self):
        with patch("vless_exit.http.client.HTTPSConnection") as connection:
            response = connection.return_value.getresponse.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b"ip=8.8.8.8"
            self.assertEqual(_fetch(20809, "cloudflare.com", "/cdn-cgi/trace"), "ip=8.8.8.8")
            connection.assert_called_once_with("127.0.0.1", 20809, timeout=4)
            connection.return_value.set_tunnel.assert_called_once_with("cloudflare.com", 443)
            connection.return_value.request.assert_called_once_with(
                "GET", "/cdn-cgi/trace", headers={"Host": "cloudflare.com", "User-Agent": "AntigravityHub/1.0"})

    def test_probe_reads_country_and_public_ip(self):
        with patch("vless_exit._fetch", return_value="ip=2606:4700::1111\nloc=DE") as fetch:
            self.assertEqual(probe_vless_exit(20809), {"ip": "2606:4700::1111", "country": "DE"})
            fetch.assert_called_once()

    def test_fallback_rejects_private_ip_and_uses_new_pair(self):
        fallback = json.dumps({"ip": "8.8.4.4", "country_code": "fr"})
        with patch("vless_exit._fetch", side_effect=["ip=127.0.0.1\nloc=DE", fallback]):
            self.assertEqual(probe_vless_exit(20809), {"ip": "8.8.4.4", "country": "FR"})
        with patch("vless_exit._fetch", side_effect=OSError):
            self.assertIsNone(probe_vless_exit(20809))

    def test_cache_never_shows_result_from_previous_connection(self):
        status = VlessExitStatus()
        with patch("vless_exit.threading.Thread") as thread, \
                patch("vless_exit.probe_vless_exit", side_effect=[
                    {"ip": "8.8.8.8", "country": "DE"},
                    {"ip": "8.8.4.4", "country": "FR"},
                ]):
            self.assertEqual(status.snapshot(None), {"status": "stopped"})
            self.assertEqual(status.snapshot("A", 20809), {"status": "checking"})
            old = thread.call_args.kwargs
            self.assertEqual(status.snapshot("B", 20809), {"status": "checking"})
            old["target"](*old["args"])
            self.assertEqual(status.snapshot("B", 20809), {"status": "checking"})
            new = thread.call_args.kwargs
            new["target"](*new["args"])
            self.assertEqual(status.snapshot("B", 20809), {"status": "ok", "ip": "8.8.4.4", "country": "FR"})
            self.assertEqual(thread.call_count, 2)
            self.assertEqual(status.snapshot(None), {"status": "stopped"})


if __name__ == "__main__":
    unittest.main()
