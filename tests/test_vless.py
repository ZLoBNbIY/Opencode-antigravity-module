import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import vless_manager
from vless_manager import VlessParser, vless_service


class VlessManagerTests(unittest.TestCase):
    def test_core_status_and_download_check_the_requested_engine(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=root) as directory:
            folder = Path(directory)
            self.assertEqual(folder.resolve().parent, root)
            (folder / 'sing-box.exe').touch()
            manager = vless_manager.VlessManager()
            with mock.patch.object(manager, 'get_bin_dir', return_value=folder), \
                 mock.patch.object(vless_manager, 'CONFIG_DIR', folder), \
                 mock.patch('vless_manager.shutil.which', return_value=None), \
                 mock.patch('vless_manager.urllib.request.build_opener', side_effect=OSError('offline')) as opener:
                self.assertEqual(manager.find_core_executable(core_type='sing-box'), folder / 'sing-box.exe')
                self.assertIsNone(manager.find_core_executable(core_type='xray'))
                ok, _ = manager.download_core('sing-box')
                self.assertTrue(ok)
                opener.assert_not_called()
                ok, _ = manager.download_core('xray')
                self.assertFalse(ok)
                self.assertGreater(opener.call_count, 0)

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
        cfg = vless_service.generate_xray_config(params, 10879, 10878)
        self.assertEqual(len(cfg["inbounds"]), 2)
        self.assertEqual(cfg["inbounds"][0]["protocol"], "socks")
        self.assertEqual(cfg["inbounds"][0]["port"], 10878)
        self.assertEqual(cfg["inbounds"][1]["protocol"], "http")
        self.assertEqual(cfg["inbounds"][1]["port"], 10879)
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
        cfg = vless_service.generate_sing_box_config(params, 10879, 10878)
        self.assertEqual(len(cfg["inbounds"]), 1)
        self.assertEqual(cfg["inbounds"][0]["type"], "mixed")
        self.assertEqual(cfg["inbounds"][0]["listen_port"], 10879)
        self.assertEqual(cfg["outbounds"][0]["type"], "vless")
        self.assertEqual(cfg["outbounds"][0]["tls"]["reality"]["public_key"], "test-pbk")

    def test_default_ports_are_isolated(self):
        # Non-standard isolated ports: must differ from the common 10808/10809
        # used by other local VPN/Xray tools (e.g. browser VLESS extensions).
        self.assertEqual(vless_manager.DEFAULT_HTTP_PORT, 10879)
        self.assertEqual(vless_manager.DEFAULT_SOCKS_PORT, 10878)
        self.assertNotIn(vless_manager.DEFAULT_HTTP_PORT, (10808, 10809))
        self.assertNotIn(vless_manager.DEFAULT_SOCKS_PORT, (10808, 10809))
        self.assertNotEqual(
            vless_manager.DEFAULT_HTTP_PORT, vless_manager.DEFAULT_SOCKS_PORT
        )

    def test_reclaim_core_ports_targets_only_hub_core(self):
        from unittest.mock import patch, MagicMock

        svc = vless_manager.VlessManager()
        with patch.object(
            svc, "_get_listener_pids",
            side_effect=lambda port: [4242] if port == 10879 else []
        ) as listener_mock, \
             patch.object(
            svc, "_get_process_image", return_value="sing-box.exe"
        ), \
             patch.object(svc, "_kill_pid") as kill_mock:
            ok, err = svc._reclaim_core_ports(10879, 10878)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertTrue(listener_mock.called)
        kill_mock.assert_called_once_with(4242)

        # A foreign program on a port must not be killed; an error returned
        with patch.object(
            svc, "_get_listener_pids", side_effect=lambda port: [5555]
        ), \
             patch.object(
            svc, "_get_process_image", return_value="clash-verge.exe"
        ), \
             patch.object(svc, "_kill_pid") as kill_mock:
            ok, err = svc._reclaim_core_ports(10879, 10878)
        self.assertFalse(ok)
        self.assertIn("clash-verge.exe", err)
        self.assertIn("10879", err)
        kill_mock.assert_not_called()


class ActiveProxyPriorityTests(unittest.TestCase):
    """Priority must be: VLESS -> custom proxy -> local DNS proxy -> direct."""

    def test_vless_takes_priority_over_proxy_and_dns(self):
        cfg = {
            "vless_enabled": True,
            "vless_url": "vless://test",
            "proxy": "http://127.0.0.1:9999",
            "dns_mode": "doh",
        }
        self.assertEqual(
            vless_manager.get_active_proxy(cfg, port_probe=lambda p: False),
            "http://127.0.0.1:10879",
        )

    def test_custom_proxy_when_vless_off(self):
        cfg = {"proxy": "http://127.0.0.1:9999", "dns_mode": "doh"}
        self.assertEqual(
            vless_manager.get_active_proxy(cfg, port_probe=lambda p: False),
            "http://127.0.0.1:9999",
        )

    def test_local_dns_proxy_when_no_vless_no_custom(self):
        cfg = {"dns_mode": "doh"}
        probe = lambda p: p == vless_manager.LOCAL_DNS_PROXY_PORT
        self.assertEqual(
            vless_manager.get_active_proxy(cfg, port_probe=probe),
            "http://127.0.0.1:51180",
        )

    def test_direct_when_nothing_active(self):
        cfg = {"dns_mode": "system"}
        self.assertIsNone(vless_manager.get_active_proxy(cfg, port_probe=lambda p: False))

    def test_detached_core_port_respects_config_file(self):
        # All code paths must derive the port from the same config keys
        with mock.patch.object(vless_manager, "load_hub_config",
                               return_value={"vless_http_port": 20801}):
            http_p, socks_p = vless_manager.get_configured_ports()
        self.assertEqual((http_p, socks_p), (20801, 10878))
        with mock.patch.object(vless_manager, "load_hub_config",
                               return_value={"vless_http_port": 20801}):
            self.assertEqual(vless_manager.get_http_port(), 20801)


if __name__ == "__main__":
    unittest.main()
