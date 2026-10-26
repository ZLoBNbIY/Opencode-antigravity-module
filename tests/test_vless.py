import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import vless_manager
from vless_manager import VlessParser, vless_service


class VlessManagerTests(unittest.TestCase):
    def test_parse_vless_reality(self):
        url = (
            "vless://12345678-1234-1234-1234-123456789abc@198.51.100.1:443"
            "?security=reality&sni=example.com&fp=chrome&pbk=my-public-key"
            "&sid=abcdef12&type=tcp&flow=xtls-rprx-vision#MyServer"
        )
        params = VlessParser.parse_url(url)
        self.assertEqual(params["uuid"], "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(params["server"], "198.51.100.1")
        self.assertEqual(params["port"], 443)
        self.assertEqual(params["security"], "reality")
        self.assertEqual(params["sni"], "example.com")
        self.assertEqual(params["pbk"], "my-public-key")
        self.assertEqual(params["sid"], "abcdef12")
        self.assertEqual(params["flow"], "xtls-rprx-vision")
        self.assertEqual(params["type"], "tcp")
        self.assertEqual(params["tag"], "MyServer")

    def test_parse_vless_ws(self):
        url = (
            "vless://12345678-1234-1234-1234-123456789abc@domain.com:8443"
            "?security=tls&sni=domain.com&type=ws&path=/vless-ws#WebSocketTLS"
        )
        params = VlessParser.parse_url(url)
        self.assertEqual(params["server"], "domain.com")
        self.assertEqual(params["port"], 8443)
        self.assertEqual(params["security"], "tls")
        self.assertEqual(params["type"], "ws")
        self.assertEqual(params["path"], "/vless-ws")
        self.assertEqual(params["tag"], "WebSocketTLS")

    def test_generate_xray_config(self):
        params = {
            "uuid": "test-uuid",
            "server": "1.2.3.4",
            "port": 443,
            "security": "reality",
            "sni": "google.com",
            "alpn": ["h2", "http/1.1"],
            "fingerprint": "chrome",
            "pbk": "test-pbk",
            "sid": "test-sid",
            "flow": "xtls-rprx-vision",
            "type": "tcp",
            "path": "/",
            "serviceName": "",
            "tag": "test-node",
        }
        cfg = vless_service.generate_xray_config(params, 10809, 10808)
        self.assertEqual(len(cfg["inbounds"]), 2)
        self.assertEqual(cfg["inbounds"][0]["protocol"], "socks")
        self.assertEqual(cfg["inbounds"][0]["port"], 10808)
        self.assertEqual(cfg["inbounds"][1]["protocol"], "http")
        self.assertEqual(cfg["inbounds"][1]["port"], 10809)
        self.assertEqual(cfg["outbounds"][0]["protocol"], "vless")
        self.assertEqual(
            cfg["outbounds"][0]["streamSettings"]["realitySettings"]["publicKey"],
            "test-pbk"
        )

    def test_generate_sing_box_config(self):
        params = {
            "uuid": "test-uuid",
            "server": "1.2.3.4",
            "port": 443,
            "security": "reality",
            "sni": "google.com",
            "alpn": ["h2", "http/1.1"],
            "fingerprint": "chrome",
            "pbk": "test-pbk",
            "sid": "test-sid",
            "flow": "xtls-rprx-vision",
            "type": "tcp",
            "path": "/",
            "serviceName": "",
            "tag": "test-node",
        }
        cfg = vless_service.generate_sing_box_config(params, 10809, 10808)
        self.assertEqual(len(cfg["inbounds"]), 1)
        self.assertEqual(cfg["inbounds"][0]["type"], "mixed")
        self.assertEqual(cfg["inbounds"][0]["listen_port"], 10809)
        self.assertEqual(cfg["outbounds"][0]["type"], "vless")
        self.assertEqual(cfg["outbounds"][0]["tls"]["reality"]["public_key"], "test-pbk")

    def test_default_ports_are_isolated(self):
        self.assertEqual(vless_manager.DEFAULT_HTTP_PORT, 20809)
        self.assertEqual(vless_manager.DEFAULT_SOCKS_PORT, 20808)

    def test_kill_saved_pid_targets_only_hub_pid(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "core.pid"
            pid_file.write_text("99999", encoding="utf-8")
            with patch.object(vless_manager, "PID_FILE", pid_file), \
                 patch("subprocess.run") as mock_run:
                vless_service._kill_saved_pid()
                self.assertFalse(pid_file.exists())
                self.assertTrue(mock_run.called)
                args = mock_run.call_args[0][0]
                self.assertIn("/pid", args)
                self.assertIn("99999", args)
                self.assertNotIn("/im", args)


if __name__ == "__main__":
    unittest.main()
