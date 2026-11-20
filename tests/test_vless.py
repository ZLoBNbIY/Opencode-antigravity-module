import concurrent.futures
import ctypes
import hashlib
import io
import socket
import ssl
import stat
import threading
import urllib.request
import zipfile
from pathlib import Path
import sys
import unittest
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import vless_manager
from vless_manager import VlessParser, vless_service


class ScopedMocksTestCase(unittest.TestCase):
    def enter_context(self, context):
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value


class CoreInstallationTests(ScopedMocksTestCase):
    def setUp(self):
        self.manager = vless_manager.VlessManager()
        self.folder = Path(self.enter_context(tempfile.TemporaryDirectory()))
        self.enter_context(mock.patch.object(vless_manager.VlessManager, "get_bin_dir", return_value=self.folder))
        self.enter_context(mock.patch.object(vless_manager, "platform", mock.Mock()))
        vless_manager.platform.machine.return_value = "AMD64"
        self.enter_context(mock.patch.object(vless_manager, "sys", mock.Mock(platform="win32")))
        self.build = self.enter_context(mock.patch("vless_manager.urllib.request.build_opener"))
        self.opener = self.build.return_value
        self.managed = self.folder / "managed-vless"

    def pin_zip(self, entries=None):
        if entries is None:
            entries = [("version/sing-box.exe", b"test core"), ("version/libcronet.dll", b"test dll")]
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
        contents = data.getvalue()
        self.url = vless_manager._CORE_RELEASES["sing-box"][0]
        self.digest = hashlib.sha256(contents).hexdigest()
        self.enter_context(mock.patch.dict(vless_manager._CORE_RELEASES, {"sing-box": (self.url, self.digest)}))
        self.destination = self.managed / f"sing-box-{self.digest}"
        self.opener.open.side_effect = lambda *args, **kwargs: self.response(contents)
        return contents

    @staticmethod
    def response(contents, url="https://release-assets.githubusercontent.com/test"):
        stream = io.BytesIO(contents)
        stream.geturl = lambda: url
        return stream

    def test_verified_install_and_engine_specific_discovery(self):
        self.pin_zip()
        (self.folder / "xray.exe").write_bytes(b"unverified legacy")
        ok, message = self.manager.download_core("sing-box")
        self.assertTrue(ok, message)
        self.assertEqual(list(self.managed.iterdir()), [self.destination])
        exe = self.destination / "sing-box.exe"
        self.assertEqual(exe.read_bytes(), b"test core")
        self.assertEqual((self.destination / "libcronet.dll").read_bytes(), b"test dll")
        self.assertEqual(self.manager.find_core_executable(core_type="sing-box"), exe)
        self.assertIsNone(self.manager.find_core_executable(core_type="xray"))
        self.assertIsNone(self.manager.find_core_executable(str(self.folder / "xray.exe")))
        self.assertEqual(self.manager.find_core_executable(str(exe)), exe)
        self.assertTrue(self.manager.download_core("sing-box")[0])
        self.opener.open.assert_called_once()
        self.assertEqual(self.opener.open.call_args.args[0].full_url, self.url)

    def test_checksum_mismatch_fails_before_opening_zip(self):
        data = self.pin_zip()
        self.opener.open.side_effect = lambda *args, **kwargs: self.response(data + b"changed")
        with mock.patch("vless_manager.zipfile.ZipFile") as unzip:
            self.assertFalse(self.manager.download_core("sing-box")[0])
            unzip.assert_not_called()
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_unsafe_and_ambiguous_zip_members_leave_no_install(self):
        symlink = zipfile.ZipInfo("version/link")
        symlink.create_system = 3
        symlink.external_attr = stat.S_IFLNK << 16
        for entries in (
            [("version/sing-box.exe", b"test"), ("../libcronet.dll", b"test")],
            [("version/sing-box.exe", b"test"), ("other/SING-BOX.exe", b"test")],
            [("version/sing-box.exe", b"test"), (symlink, b"test")],
            [("version/xray.exe", b"wrong engine")],
        ):
            with self.subTest(entries=entries):
                self.pin_zip(entries)
                self.assertFalse(self.manager.download_core("sing-box")[0])
                self.assertEqual(list(self.managed.iterdir()), [])

    def test_extraction_failure_never_publishes_partial_install(self):
        self.pin_zip()
        with mock.patch("vless_manager.shutil.copyfileobj", side_effect=OSError("disk full")):
            self.assertFalse(self.manager.download_core("sing-box")[0])
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_tampered_install_is_neither_launched_nor_reported_installed(self):
        self.pin_zip()
        self.assertTrue(self.manager.download_core("sing-box")[0])
        exe = self.destination / "sing-box.exe"
        for path, data in (
            (exe, b"same size"),
            (self.destination / "libcronet.dll", b"malicious"),
            (self.destination / "untrusted.dll", b"extra"),
            (self.destination / vless_manager._ARCHIVE_NAME, b"corrupt"),
        ):
            with self.subTest(path=path):
                previous = path.read_bytes() if path.exists() else None
                path.write_bytes(data)
                self.assertFalse(self.manager.download_core("sing-box")[0])
                with mock.patch("vless_manager.subprocess.Popen") as popen:
                    self.assertFalse(self.manager.start_tunnel("vless://id@example.org:443", custom_core_path=str(exe))[0])
                    popen.assert_not_called()
                if previous is None:
                    path.unlink()
                else:
                    path.write_bytes(previous)

    def test_concurrent_installers_publish_one_complete_release(self):
        data = self.pin_zip()
        barrier = threading.Barrier(2, timeout=5)

        def response(*args, **kwargs):
            barrier.wait()
            return self.response(data)

        self.opener.open.side_effect = response
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(vless_manager.VlessManager().download_core, "sing-box") for _ in range(2)]
            for job in jobs:
                ok, message = job.result(timeout=10)
                self.assertTrue(ok, message)
        self.assertEqual(list(self.managed.iterdir()), [self.destination])
        self.assertEqual(self.manager.find_core_executable(core_type="sing-box"), self.destination / "sing-box.exe")

    def test_certificate_failure_has_no_retry_and_no_unverified_context(self):
        self.opener.open.side_effect = ssl.SSLCertVerificationError("bad cert")
        with mock.patch("vless_manager.ssl._create_unverified_context") as insecure:
            self.assertFalse(self.manager.download_core("sing-box")[0])
            insecure.assert_not_called()
        self.opener.open.assert_called_once()
        handler = next(h for h in self.build.call_args.args if isinstance(h, urllib.request.HTTPSHandler))
        self.assertTrue(handler._context.check_hostname)
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_redirect_policy_and_final_origin(self):
        data = self.pin_zip()
        handler = vless_manager._ReleaseRedirectHandler()
        request = urllib.request.Request(self.url)
        for url in ("http://github.com/file", "https://github.com.evil.example/file",
                    "https://evil.example/file", "https://evil@github.com/file", "https://github.com:444/file"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    handler.redirect_request(request, None, 302, "redirect", {}, url)
                self.opener.open.side_effect = lambda *args, **kwargs: self.response(data, url)
                self.assertFalse(self.manager.download_core("sing-box")[0])
        approved = "https://release-assets.githubusercontent.com/file"
        self.assertEqual(handler.redirect_request(request, None, 302, "redirect", {}, approved).full_url, approved)
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_unsupported_platform_requires_manual_binary_without_network(self):
        vless_manager.platform.machine.return_value = "ARM64"
        self.assertFalse(self.manager.download_core("sing-box")[0])
        self.build.assert_not_called()


class VlessManagerTests(unittest.TestCase):

    def test_connection_returns_country_code_from_cloudflare_trace_first(self):
        manager = vless_manager.VlessManager()
        trace = ("fl=123abc\nip=203.0.113.7\nts=1794309000.000\n"
                 "loc=DE\nhttp=http\n")
        response = mock.MagicMock()
        response.read.return_value = trace.encode()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        manager._process = mock.Mock()
        manager._ports = (10879,)
        with mock.patch.object(manager, '_is_ready', return_value=True), \
             mock.patch("vless_manager.urllib.request.build_opener") as build:
            opener = build.return_value
            opener.open.return_value = response
            result = manager.test_connection(http_port=10879)
        self.assertTrue(result["ok"])
        self.assertEqual(result["ip"], "203.0.113.7")
        self.assertEqual(result["country"], "DE")
        requested_urls = [call.args[0].full_url for call in opener.open.call_args_list]
        self.assertIn("https://cloudflare.com/cdn-cgi/trace", requested_urls)

    def test_connection_does_not_report_success_without_a_valid_ip(self):
        manager = vless_manager.VlessManager()
        manager._process = mock.Mock()
        manager._ports = (10879,)
        with mock.patch.object(manager, "_is_ready", return_value=True), \
             mock.patch("vless_manager.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = lambda *args, **kwargs: io.BytesIO(b'{"ip":"not an ip"}')
            self.assertFalse(manager.test_connection()["ok"])

    def test_explicit_proxy_ignores_environment_bypass(self):
        proxy = "http://127.0.0.1:10879"
        req = urllib.request.Request("https://api.ipify.org")
        handler = vless_manager._TunnelProxyHandler({"https": proxy})
        with mock.patch("vless_manager.urllib.request.proxy_bypass", return_value=True) as bypass:
            handler.proxy_open(req, proxy, "https")
        bypass.assert_not_called()
        self.assertEqual(req.host, "127.0.0.1:10879")
        self.assertEqual(req._tunnel_host, "api.ipify.org")

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
        self.assertEqual(cfg["outbounds"][0]["flow"], "xtls-rprx-vision")

        # Do not infer Vision for share links that intentionally omit `flow`.
        params_without_flow = dict(params)
        params_without_flow.pop("flow")
        cfg_without_flow = vless_service.generate_sing_box_config(
            params_without_flow, 10879, 10878
        )
        self.assertNotIn("flow", cfg_without_flow["outbounds"][0])

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

class CoreProcessTests(ScopedMocksTestCase):
    URL = "vless://id@example.org:443"
    HTTP = 21879
    SOCKS = 21878

    def setUp(self):
        self.svc = vless_manager.VlessManager()
        self.root = Path(self.enter_context(tempfile.TemporaryDirectory()))
        self.enter_context(mock.patch.object(vless_manager, "VLESS_RUNTIME_DIR", self.root))
        self.exe = self.root / "xray.exe"
        self.exe.touch()
        self.child = mock.Mock(pid=4242)
        self.child.poll.return_value = None
        self.popen = self.enter_context(mock.patch("vless_manager.subprocess.Popen", return_value=self.child))
        self.run = self.enter_context(mock.patch("vless_manager.subprocess.run"))
        self.probe = self.enter_context(mock.patch.object(self.svc, "check_port_listening",
                                                        side_effect=lambda port: self.popen.called))
        self.ownership = self.enter_context(mock.patch.object(self.svc, "_owned_listener_ports",
                                                            side_effect=lambda pid, ports: set(ports)))
        self.enter_context(mock.patch.object(vless_manager, "_START_TIMEOUT", 0))

    def start(self):
        return self.svc.start_tunnel(self.URL, self.HTTP, self.SOCKS, str(self.exe))

    def test_explicit_operator_binary_starts_and_stops_only_owned_child(self):
        ok, message = self.start()
        self.assertTrue(ok, message)
        self.assertTrue(self.svc.is_running())
        self.assertEqual(self.popen.call_args.args[0][0], str(self.exe.resolve()))
        self.ownership.assert_called_with(4242, (self.HTTP, self.SOCKS))
        self.assertTrue(self.svc.stop_tunnel()[0])
        self.child.terminate.assert_called_once_with()
        self.child.kill.assert_not_called()
        self.run.assert_not_called()
        self.assertFalse(self.svc.is_running())
        self.assertEqual(list(self.root.iterdir()), [self.exe])

    def test_foreign_listener_does_not_count_as_ready_and_is_not_touched(self):
        self.probe.side_effect = None
        self.probe.return_value = True
        self.assertFalse(self.svc.is_running())
        self.assertFalse(self.svc.test_connection(self.HTTP)["ok"])
        ok, message = self.start()
        self.assertFalse(ok)
        self.assertIn(str(self.HTTP), message)
        self.assertTrue(self.svc.stop_tunnel()[0])
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_listening_port_race_does_not_report_success_or_kill_by_pid(self):
        self.ownership.side_effect = None
        self.ownership.return_value = set()
        self.assertFalse(self.start()[0])
        self.assertFalse(self.svc.is_running())
        self.child.terminate.assert_called_once_with()
        self.run.assert_not_called()

    def test_xray_requires_both_listeners_but_sing_box_requires_only_mixed_port(self):
        self.ownership.side_effect = None
        self.ownership.return_value = {self.HTTP}
        self.assertFalse(self.start()[0])
        self.child.terminate.assert_called_once_with()
        self.popen.reset_mock()
        self.exe = self.root / "sing-box.exe"
        self.exe.touch()
        self.assertTrue(self.start()[0])
        self.ownership.assert_called_with(self.child.pid, (self.HTTP,))

    def test_early_exit_not_reported_as_ready(self):
        self.child.poll.return_value = 9
        ok, message = self.start()
        self.assertFalse(ok)
        self.assertIn("9", message)
        self.assertFalse(self.svc.is_running())
        self.child.terminate.assert_not_called()

    def test_running_child_no_longer_owns_listeners(self):
        self.assertTrue(self.start()[0])
        self.ownership.side_effect = None
        self.ownership.return_value = set()
        self.assertFalse(self.svc.is_running())
        self.assertFalse(self.start()[0])
        self.popen.assert_called_once()

    def test_concurrent_start_cannot_report_pending_child_as_ready_and_stop_cancels(self):
        self.ownership.side_effect = None
        self.ownership.return_value = set()
        sleeping, resume = threading.Event(), threading.Event()

        def wait_for_stop(_delay):
            sleeping.set()
            resume.wait(5)

        with mock.patch.object(vless_manager, "_START_TIMEOUT", 10), \
             mock.patch("vless_manager.time.sleep", side_effect=wait_for_stop), \
             concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            start = pool.submit(self.start)
            try:
                self.assertTrue(sleeping.wait(5))
                self.assertFalse(self.start()[0])
                self.assertTrue(self.svc.stop_tunnel()[0])
            finally:
                resume.set()
            self.assertFalse(start.result(timeout=5)[0])
        self.popen.assert_called_once()
        self.child.terminate.assert_called_once()

    def test_windows_listener_ownership_uses_loopback_state_and_pid(self):
        loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
        port, socks = socket.htons(self.HTTP), socket.htons(self.SOCKS)
        rows = [3, 2, loopback, port, 0, 0, 4242, 2, loopback, socks, 0, 0, 5555,
                5, loopback, socks, 0, 0, 4242]
        data = (ctypes.c_uint32 * len(rows))(*rows)

        def table(buffer, size, *_args):
            if buffer is None:
                ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = ctypes.sizeof(data)
                return 122
            ctypes.memmove(buffer, data, ctypes.sizeof(data))
            return 0

        get_table = mock.Mock(side_effect=table)
        with mock.patch.object(ctypes, "WinDLL", create=True) as dll:
            dll.return_value.GetExtendedTcpTable = get_table
            self.assertEqual(vless_manager._windows_listener_ports(4242, (self.HTTP, self.SOCKS)), {self.HTTP})
            data[9] = port
            self.assertEqual(vless_manager._windows_listener_ports(4242, (self.HTTP, self.SOCKS)), set())


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

    def test_unowned_listener_is_not_promoted_to_a_proxy(self):
        self.assertIsNone(vless_manager.get_active_proxy({}, port_probe=lambda p: True))

    def test_custom_port_respects_config_file(self):
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
