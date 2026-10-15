import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import openrouter_manager


class OpenRouterModelTests(unittest.TestCase):
    @patch("openrouter_manager._openrouter_opener")
    def test_catalog_keeps_all_free_text_chat_models(self, get_opener):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"data": [
            {"id": "qwen/qwen-coder:free", "name": "Qwen Coder", "context_length": 64000,
             "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"modality": "text->text"}},
            {"id": "meta-llama/llama-3:free", "name": "Llama", "context_length": 32000,
             "pricing": {"prompt": "0.0", "completion": "0.0"}, "architecture": {"modality": "text->text"}},
            {"id": "google/gemma:free", "name": "Gemma", "context_length": 16000,
             "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"modality": "text+image->text"}},
            {"id": "qwen/qwen-paid", "name": "Paid Qwen", "pricing": {"prompt": "0.1", "completion": "0.2"}},
            {"id": "google/audio-free", "name": "Free Audio", "pricing": {"prompt": "0", "completion": "0"},
             "architecture": {"modality": "text->audio"}},
            {"id": "google/text-audio-free", "name": "Free Audio Text", "pricing": {"prompt": "0", "completion": "0"},
             "architecture": {"modality": "text->text+audio"}},
        ]}).encode()
        opener = Mock()
        opener.open.return_value = response
        get_opener.return_value = opener

        models = openrouter_manager.fetch_free_models("test-key")
        self.assertEqual([model["id"] for model in models], ["google/gemma:free", "meta-llama/llama-3:free", "qwen/qwen-coder:free"])
        self.assertEqual(next(model for model in models if model["id"] == "qwen/qwen-coder:free")["context"], 64000)

    def test_config_adds_selected_models_in_separate_free_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(json.dumps({"disabled_providers": ["google"], "provider": {
                "openrouter": {"models": {"my-custom-model": {"name": "Keep this"}}}
            }}), encoding="utf-8")
            openrouter_manager.configure_models([{
                "id": "qwen/qwen-coder:free", "name": "Qwen Coder", "context": 64000, "output": 8192,
            }], temp_dir)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            models = saved["provider"]["openrouter-free"]["models"]
            self.assertEqual(models, {"qwen/qwen-coder:free": {
                "name": "Qwen Coder", "limit": {"context": 64000, "output": 8192},
            }})
            self.assertEqual(saved["provider"]["openrouter-free"]["name"], "OpenRouter Free")
            self.assertEqual(saved["provider"]["openrouter-free"]["options"]["baseURL"], "https://openrouter.ai/api/v1")
            self.assertEqual(saved["disabled_providers"], ["google", "openrouter"])

    def test_api_key_is_protected_in_hub_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openrouter.json"
            with patch.object(openrouter_manager, "SECRET_FILE", path):
                openrouter_manager.save_api_key("sk-or-test-secret")
                self.assertNotIn("sk-or-test-secret", path.read_text(encoding="utf-8"))
                self.assertEqual(openrouter_manager.load_api_key(), "sk-or-test-secret")

    @patch("openrouter_manager.subprocess.run")
    @patch("openrouter_manager.openai_manager.find_opencode_cli", return_value="opencode-cli")
    def test_opencode_credential_uses_current_key_variant(self, _find_cli, run):
        run.return_value.returncode = 0
        openrouter_manager.sync_opencode_credential("sk-or-test-secret")
        imported = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(imported[0]["value"], {"type": "key", "key": "sk-or-test-secret"})


if __name__ == "__main__":
    unittest.main()
