import io
import json
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
        self.model_id = "nvidia/nemotron-3-ultra-550b-a55b"

    @patch("nvidia_manager.urllib.request.build_opener")
    def test_catalog_and_manual_probe_use_different_endpoints(self, build_opener):
        opener = build_opener.return_value
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

    @patch("nvidia_manager.urllib.request.build_opener")
    def test_does_not_leak_response_body_on_auth_failure(self, build_opener):
        build_opener.return_value.open.side_effect = urllib.error.HTTPError(
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

        def fail_config(path, text):
            if path.parent == self.config.parent:
                raise OSError("simulated config write failure")
            atomic_write(path, text)

        with patch.object(nvidia_manager.secure_storage, "atomic_write", side_effect=fail_config):
            with self.assertRaises(OSError):
                nvidia_manager.configure("nvapi-second", [self.model_id])
        self.assertEqual(nvidia_manager.load_key(), "nvapi-first")
