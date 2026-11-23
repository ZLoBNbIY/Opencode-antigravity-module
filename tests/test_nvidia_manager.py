import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import nvidia_manager


class NvidiaManagerTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(tmp)
        self.config = root / "opencode" / "opencode.jsonc"
        self.config.parent.mkdir()
        self.secret = root / "hub" / "opencode-secrets" / "nvidia-nim.key"
        self.enterContext(patch.multiple(nvidia_manager, CONFIG_DIR=self.config.parent, KEY_FILE=self.secret))
        if os.name == "nt":
            # Exercise file/JSONC behavior without setting any real ACLs.
            def open_fake_private_file(path):
                return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)

            self.enterContext(patch.object(nvidia_manager.secure_storage, "_open_windows_private_file",
                                           side_effect=open_fake_private_file))
        self.model_id = "nvidia/nemotron-3-ultra-550b-a55b"

    @patch("nvidia_manager._opener")
    def test_catalog_and_manual_probe_use_different_endpoints(self, make_opener):
        opener = make_opener.return_value
        opener.open.side_effect = [
            io.BytesIO(json.dumps({"data": [{"id": self.model_id}, {"id": self.model_id},
                                             {"id": "nvidia/embed-qa-4"}, {"id": 10}]}).encode()),
            io.BytesIO(b'{"choices":[{}]}'),
        ]
        self.assertEqual(nvidia_manager.fetch_models("nvapi-test"), [self.model_id])
        nvidia_manager.probe_model("nvapi-test", self.model_id)
        first, second = (call.args[0] for call in opener.open.call_args_list)
        self.assertEqual(first.full_url, nvidia_manager.BASE_URL + "/models")
        self.assertEqual(first.get_header("Authorization"), "Bearer nvapi-test")
        self.assertEqual(second.full_url, nvidia_manager.BASE_URL + "/chat/completions")
        self.assertEqual(json.loads(second.data)["model"], self.model_id)
        self.assertFalse(self.secret.exists())

    @patch("nvidia_manager.urllib.request.build_opener")
    @patch("provider_proxy.proxy_url_for_hub_requests", return_value="http://127.0.0.1:10880")
    def test_catalog_uses_hub_route_dispatcher(self, proxy_url, build_opener):
        opener = build_opener.return_value
        opener.open.return_value = io.BytesIO(b'{"data":[]}')
        self.assertEqual(nvidia_manager.fetch_models("nvapi-test"), [])
        proxy_url.assert_called_once_with()
        proxies = [handler.proxies for handler in build_opener.call_args.args
                   if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual(proxies, [{"http": "http://127.0.0.1:10880",
                                    "https": "http://127.0.0.1:10880"}])

    @patch("nvidia_manager._opener")
    def test_does_not_leak_response_body_on_auth_failure(self, make_opener):
        make_opener.return_value.open.side_effect = urllib.error.HTTPError(
            nvidia_manager.BASE_URL, 401, "nvapi-test", {}, None)
        with self.assertRaisesRegex(ValueError, r"^Ключ отклонён \(401\)"):
            nvidia_manager.probe_model("nvapi-test", self.model_id)

    def test_configure_and_disconnect_preserve_unrelated_jsonc(self):
        original = ('{\n  // Keep me\n  "model": "keep/default",\n'
                    '  "provider": {"legacy": {}},\n  "providers": {"keep": {}},\n}\n')
        self.config.write_text(original, encoding="utf-8")
        nvidia_manager.configure("nvapi-test", [self.model_id])
        text = self.config.read_text(encoding="utf-8")
        data = nvidia_manager.jsonc_config.parse_config(text)
        provider = data["providers"]["nvidia-nim"]
        self.assertEqual(provider["settings"]["apiKey"], "{file:" + self.secret.resolve().as_posix() + "}")
        self.assertEqual(provider["settings"]["baseURL"], nvidia_manager.BASE_URL)
        self.assertNotIn("nvapi-test", text)
        self.assertEqual(nvidia_manager.load_key(), "nvapi-test")
        self.assertEqual(nvidia_manager.state(), {"hasKey": True, "connected": True,
                                                  "selectedModels": [self.model_id]})
        nvidia_manager.disconnect()
        saved = self.config.read_text(encoding="utf-8")
        self.assertIn("// Keep me", saved)
        data = nvidia_manager.jsonc_config.parse_config(saved)
        self.assertEqual(data["model"], "keep/default")
        self.assertEqual(data["provider"], {"legacy": {}})
        self.assertEqual(data["providers"], {"keep": {}})
        self.assertFalse(self.secret.exists())

    def test_foreign_provider_stays_untouched(self):
        original = '{"providers":{"nvidia-nim":{"settings":{"baseURL":"https://example.com"}}}}'
        self.config.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "другой провайдер"):
            nvidia_manager.configure("nvapi-test", [self.model_id])
        nvidia_manager.disconnect()
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertFalse(self.secret.exists())

    def test_config_failure_restores_previous_key(self):
        nvidia_manager.configure("nvapi-first", [self.model_id])
        atomic_write = nvidia_manager.secure_storage.atomic_write

        def fail_config(path, text, **kwargs):
            if path.parent == self.config.parent:
                raise OSError("simulated config write failure")
            atomic_write(path, text, **kwargs)

        with patch.object(nvidia_manager.secure_storage, "atomic_write", side_effect=fail_config):
            with self.assertRaises(OSError):
                nvidia_manager.configure("nvapi-second", [self.model_id])
        self.assertEqual(nvidia_manager.load_key(), "nvapi-first")

    def test_configure_requests_windows_acl_and_preserves_config_bom_and_line_endings(self):
        original = b'\xef\xbb\xbf{\r\n  // Keep this line\r\n  "model": "keep/default"\r\n}\r\n'
        self.config.write_bytes(original)
        with patch.object(nvidia_manager.secure_storage, "atomic_write_bytes",
                          wraps=nvidia_manager.secure_storage.atomic_write_bytes) as write:
            nvidia_manager.configure("nvapi-test", [self.model_id])
        self.assertEqual(write.call_args_list[0].kwargs, {"private_windows": True})
        self.assertEqual(write.call_args_list[1].kwargs["private_parent"], False)
        self.assertTrue(self.config.read_bytes().startswith(b'\xef\xbb\xbf{\r\n  // Keep this line\r\n'))

    def test_unreadable_config_does_not_write_or_remove_key(self):
        nvidia_manager.configure("nvapi-first", [self.model_id])
        self.config.write_bytes(b"\xff")
        with self.assertRaises(ValueError):
            nvidia_manager.configure("nvapi-second", [self.model_id])
        with self.assertRaises(ValueError):
            nvidia_manager.disconnect()
        self.assertEqual(self.secret.read_bytes(), b"nvapi-first")
        self.assertEqual(self.config.read_bytes(), b"\xff")

    def test_invalid_key_is_not_reported_as_connected(self):
        nvidia_manager.configure("nvapi-first", [self.model_id])
        self.secret.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "повреждён"):
            nvidia_manager.state()
        self.assertEqual(self.secret.read_bytes(), b"\xff")

    def test_disconnect_does_not_delete_key_for_foreign_config(self):
        self.config.write_text("{}", encoding="utf-8")
        nvidia_manager.configure("nvapi-first", [self.model_id])
        original = b'{"providers":{"nvidia-nim":{"settings":{"baseURL":"https://example.com"}}}}'
        self.config.write_bytes(original)
        nvidia_manager.disconnect()
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.secret.read_bytes(), b"nvapi-first")
