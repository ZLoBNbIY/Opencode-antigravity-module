import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from deepseek_browser import WebError, parse_web_sse, supports_cdp
from deepseek_bridge import WebBridge
from deepseek_config import parse_config, set_property
from deepseek_format import completion_response, messages_to_prompt, parse_tool_calls, sse_frames
from deepseek_http import DeepSeekHttpClient
from deepseek_manager import DeepSeekManager, MODELS, PROVIDER_ID
from deepseek_pow import deepseek_hash_v1, solve_pow
from deepseek_storage import dpapi, protect_channel, protect_secret, unprotect_secret

TOOLS = [{"type": "function", "function": {"name": "hub_probe", "parameters": {"type": "object"}}}]


class BrowserAndPowTests(unittest.TestCase):
    def test_chromium_family_is_supported_but_firefox_is_not_cdp(self):
        self.assertTrue(supports_cdp(r"C:\Program Files\Yandex\YandexBrowser\Application\browser.exe"))
        self.assertTrue(supports_cdp(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"))
        self.assertFalse(supports_cdp(r"C:\Program Files\Mozilla Firefox\firefox.exe"))

    def test_pure_python_pow_hash_and_solver(self):
        challenge = {
            "algorithm": "DeepSeekHashV1", "salt": "salt", "expire_at": 123,
            "difficulty": 1, "challenge": deepseek_hash_v1(b"salt_123_0").hex(),
            "signature": "signature", "target_path": "/api/v0/chat/completion",
        }
        import base64
        answer = json.loads(base64.b64decode(solve_pow(challenge)))
        self.assertEqual(answer["answer"], 0)
        self.assertEqual(answer["target_path"], challenge["target_path"])


class DirectHttpTests(unittest.TestCase):
    class Response:
        status = 200
        def __init__(self, url, payload):
            self.url, self.payload = url, payload
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return self.url
        def read(self, limit=-1): return self.payload if limit < 0 else self.payload[:limit]

    class Opener:
        def __init__(self, challenge):
            self.challenge = challenge
            self.requests = []
        def open(self, request, timeout):
            self.requests.append(request)
            path = request.full_url.removeprefix("https://chat.deepseek.com")
            if path == "/api/v0/chat_session/create":
                payload = {"code": 0, "data": {"biz_data": {"chat_session": {"id": "session-1"}}}}
            elif path == "/api/v0/chat/create_pow_challenge":
                payload = {"code": 0, "data": {"biz_data": {"challenge": self.challenge}}}
            else:
                payload = b'data: {"v":{"response":{"fragments":[{"type":"RESPONSE","content":"DIRECT_OK"}]}}}\n\n'
                return DirectHttpTests.Response(request.full_url, payload)
            return DirectHttpTests.Response(request.full_url, json.dumps(payload).encode())

    def test_direct_web_chat_uses_session_pow_and_completion_without_browser(self):
        challenge = {
            "algorithm": "DeepSeekHashV1", "salt": "s", "expire_at": 42,
            "difficulty": 1, "challenge": deepseek_hash_v1(b"s_42_0").hex(),
            "signature": "sig", "target_path": "/api/v0/chat/completion",
        }
        opener = self.Opener(challenge)
        client = DeepSeekHttpClient({"token": "web-token", "cookies": {"session": "cookie"}, "userAgent": "browser UA"}, opener)
        self.assertEqual(client.generate("hello", "expert", threading.Event()), "DIRECT_OK")
        self.assertEqual(len(opener.requests), 3)
        completion = opener.requests[-1]
        self.assertEqual(completion.full_url, "https://chat.deepseek.com/api/v0/chat/completion")
        self.assertEqual(completion.get_header("Authorization"), "Bearer web-token")
        self.assertEqual(completion.get_header("Cookie"), "session=cookie")
        self.assertTrue(completion.get_header("X-ds-pow-response"))
        body = json.loads(completion.data)
        self.assertEqual(body["model_type"], "expert")
        self.assertEqual(body["chat_session_id"], "session-1")


class StorageTests(unittest.TestCase):
    def test_web_session_is_protected_and_roundtrips(self):
        session = {"token": "sensitive-token", "cookies": {"sid": "cookie"}, "userAgent": "ua"}
        record = protect_secret("deepseek-web-session", session)
        if os.name == "nt":
            self.assertNotIn("sensitive-token", json.dumps(record))
        self.assertEqual(unprotect_secret(record, "deepseek-web-session"), session)


class FormatTests(unittest.TestCase):
    def test_prompt_preserves_history_and_has_web_tool_instructions(self):
        prompt = messages_to_prompt({"messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}, {"role": "tool", "content": "result", "tool_call_id": "id"}], "tools": TOOLS})
        self.assertNotIn("System: rules", prompt)
        self.assertIn("Tool id: result", prompt)
        self.assertIn("no native function-calling channel", prompt)

    def test_hidden_system_and_developer_instructions_are_never_forwarded(self):
        prompt = messages_to_prompt({"messages": [
            {"role": "system", "content": "secret system prompt"},
            {"role": "developer", "content": "secret developer prompt"},
            {"role": "user", "content": "visible question"},
        ]})
        self.assertNotIn("secret", prompt)
        self.assertIn("User: visible question", prompt)

    def test_only_declared_valid_tools_are_parsed(self):
        text = '```tool_calls\n[{"name":"hub_probe","arguments":{"value":"test"}}]\n```'
        content, calls = parse_tool_calls(text, TOOLS)
        self.assertEqual(content, "")
        self.assertEqual(calls[0]["function"]["name"], "hub_probe")
        for invalid in (text.replace("hub_probe", "shell"), text.replace('{"value":"test"}', '"bad"'), 'Example: [{"name":"hub_probe","arguments":{}}]'):
            self.assertIsNone(parse_tool_calls(invalid, TOOLS)[1])

    def test_none_and_no_tools_never_execute_json(self):
        text = '[{"name":"hub_probe","arguments":{}}]'
        self.assertIsNone(parse_tool_calls(text, [], "auto")[1])
        self.assertIsNone(parse_tool_calls(text, TOOLS, "none")[1])

    def test_mixed_batch_is_not_partially_executed(self):
        text = '[{"name":"hub_probe","arguments":{}},{"name":"unknown","arguments":{}}]'
        self.assertIsNone(parse_tool_calls(text, TOOLS)[1])

    def test_images_and_empty_messages_rejected(self):
        for payload in ({"messages": []}, {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": "private"}]}]}):
            with self.assertRaises(ValueError):
                messages_to_prompt(payload)

    def test_completion_and_sse_finish_reasons(self):
        for text, tools, expected in (("answer", [], "stop"), ('[{"name":"hub_probe","arguments":{}}]', TOOLS, "tool_calls")):
            result = completion_response({"model": MODELS[0], "tools": tools}, "prompt", text)
            self.assertEqual(result["choices"][0]["finish_reason"], expected)
            stream = "".join(sse_frames(result))
            self.assertIn('"finish_reason": "' + expected + '"', stream)
            self.assertTrue(stream.endswith("data: [DONE]\n\n"))

    def test_web_sse_thinking_does_not_become_response(self):
        events = [
            {"v": {"response": {"fragments": [{"type": "THINK", "content": "private thought"}]}}},
            {"p": "response/fragments/-1/content", "o": "APPEND", "v": "more thought"},
            {"p": "response/fragments", "o": "APPEND", "v": [{"type": "RESPONSE", "content": "hello"}]},
            {"p": "response/fragments/-1/content", "o": "APPEND", "v": " world"},
            {"v": "!"}, {"p": "response/status", "v": "FINISHED"}, {"v": "not content"},
        ]
        self.assertEqual(parse_web_sse("\n".join("data: " + json.dumps(item) for item in events)), "hello world!")

    def test_error_and_empty_web_streams_fail(self):
        for body in ("data: [DONE]", 'data: {"error":{"message":"SECRET"}}'):
            with self.assertRaises(WebError) as raised:
                parse_web_sse(body)
            self.assertNotIn("SECRET", str(raised.exception))


class BridgeTests(unittest.TestCase):
    def start(self, generate=lambda *args: "OK"):
        bridge = WebBridge(generate, MODELS)
        self.addCleanup(bridge.close)
        return bridge

    def request(self, bridge, path, body=None, authenticated=True, origin=None):
        parsed = urllib.parse.urlsplit(bridge.origin)
        client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + bridge.key
        if origin:
            headers["Origin"] = origin
        try:
            client.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
            response = client.getresponse()
            return response.status, response.read().decode()
        finally:
            client.close()

    def test_models_require_channel_key_and_browser_origins_are_denied(self):
        bridge = self.start()
        self.assertEqual(self.request(bridge, "/v1/models", authenticated=False)[0], 401)
        self.assertEqual(self.request(bridge, "/v1/models", origin="https://evil.test")[0], 401)
        status, text = self.request(bridge, "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in json.loads(text)["data"]}, set(MODELS))

    def test_generation_and_buffered_sse(self):
        bridge = self.start(lambda prompt, model, cancel: "answer")
        payload = {"model": MODELS[0], "messages": [{"role": "user", "content": "test"}]}
        status, text = self.request(bridge, "/v1/chat/completions", payload)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["choices"][0]["message"]["content"], "answer")
        payload["stream"] = True
        status, text = self.request(bridge, "/v1/chat/completions", payload)
        self.assertEqual(status, 200)
        self.assertIn("data: [DONE]", text)

    def test_invalid_model_and_remote_paid_route_never_generate(self):
        generate = Mock(return_value="answer")
        bridge = self.start(generate)
        payload = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "test"}]}
        self.assertEqual(self.request(bridge, "/v1/chat/completions", payload)[0], 400)
        self.assertEqual(self.request(bridge, "/anthropic/v1/messages", payload)[0], 404)
        generate.assert_not_called()

    def test_busy_requests_are_not_parallelized(self):
        entered, release = threading.Event(), threading.Event()
        def generate(*args):
            entered.set()
            release.wait(timeout=3)
            return "answer"
        bridge = self.start(generate)
        payload = {"model": MODELS[0], "messages": [{"role": "user", "content": "test"}]}
        first = threading.Thread(target=lambda: self.request(bridge, "/v1/chat/completions", payload))
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.request(bridge, "/v1/chat/completions", payload)[0], 429)
        finally:
            release.set()
            first.join(timeout=4)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manager = DeepSeekManager(root / "data", root / "config")
        self.addCleanup(self.manager.shutdown)
        fake = Mock()
        fake.running = True
        fake.brand = "chrome"
        fake.session_ready.return_value = True
        fake.capture_session.return_value = {"token": "token", "cookies": {"sid": "cookie"}, "userAgent": "ua"}
        fake.generate.return_value = "answer"
        self.manager.browser = fake

    def test_login_starts_only_internal_channel_and_auto_configures_models(self):
        self.manager.login()
        self.assertTrue(self.manager.signed_in)
        self.assertTrue(self.manager.bridge.origin.startswith("http://127.0.0.1:"))
        cfg = parse_config((self.manager.config_dir / "opencode.json").read_text())
        self.assertEqual(set(cfg["providers"][PROVIDER_ID]["models"]), set(MODELS))
        self.assertNotIn(self.manager.bridge.key, json.dumps(cfg))
        self.manager.browser.show.assert_called_once()
        self.manager.browser.close.assert_called_once()
        self.assertTrue(self.manager.session_file.exists())

    def test_paid_provider_disabled_without_deleting_its_credentials(self):
        self.manager.config_dir.mkdir(parents=True)
        path = self.manager.config_dir / "opencode.jsonc"
        path.write_text('''{
 // keep comment
 "providers":{"google":{"name":"keep"},"deepseek-account":{"name":"DeepSeek Account (Antigravity Hub)","models":{"deepseek-flash":{}}}},
 "model":"deepseek-account/deepseek-flash",
 "plugins":["keep-plugin"],
}''', encoding="utf-8")
        old = self.manager.root / "account.json"
        old.parent.mkdir(parents=True)
        old.write_text("DO NOT DELETE")
        self.assertTrue(self.manager.needs_restore())
        self.manager.restore()
        data = parse_config(path.read_text())
        self.assertTrue(data["providers"]["deepseek-account"]["models"]["deepseek-flash"]["disabled"])
        self.assertEqual(data["providers"]["google"], {"name": "keep"})
        self.assertIn("keep-plugin", data["plugins"])
        self.assertIn("// keep comment", path.read_text())
        self.assertEqual(old.read_text(), "DO NOT DELETE")

    def test_cancel_before_login_is_not_lost(self):
        cancel = self.manager.prepare_login()
        self.manager.cancel_login()
        with self.assertRaises(WebError):
            self.manager.login(cancel=cancel)
        self.manager.browser.show.assert_not_called()
        self.assertFalse(self.manager.signed_in)

    def test_models_mapped_to_web_modes_not_paid_ids(self):
        self.manager.state["enabled"] = True
        self.manager.session_file.parent.mkdir(parents=True, exist_ok=True)
        from deepseek_storage import atomic_write
        atomic_write(self.manager.session_file, json.dumps(protect_secret("deepseek-web-session", {"token": "token", "cookies": {"sid": "cookie"}, "userAgent": "ua"})))
        self.manager.web_client = Mock()
        self.manager.web_client.generate.return_value = "answer"
        for model, mode in zip(MODELS, ("default", "expert")):
            self.manager.generate("prompt", model, threading.Event())
            self.assertEqual(self.manager.web_client.generate.call_args.args[1], mode)
        self.manager.browser.generate.assert_not_called()

    def test_restore_does_not_launch_browser(self):
        self.manager.state["enabled"] = True
        self.manager.restore()
        self.manager.browser.start.assert_not_called()
        self.manager.browser.show.assert_not_called()

    def test_logout_preserves_browser_profile(self):
        self.manager.login()
        profile = self.manager.root / "browser-profiles/chrome/test-data"
        profile.parent.mkdir(parents=True)
        profile.write_text("keep")
        self.manager.logout()
        self.assertFalse(self.manager.signed_in)
        self.assertEqual(profile.read_text(), "keep")
        self.assertFalse(self.manager.channel_file.exists())

    def test_user_provider_is_not_overwritten(self):
        self.manager.config_dir.mkdir(parents=True)
        path = self.manager.config_dir / "opencode.json"
        text = '{"providers":{"deepseek-web":{"name":"user"}}}'
        path.write_text(text)
        with self.assertRaises(ValueError):
            self.manager.configure_opencode()
        self.assertEqual(path.read_text(), text)

    def test_channel_dpapi_contains_no_site_token(self):
        value = {"purpose": "deepseek-web-channel", "origin": "http://127.0.0.1:12345", "key": "a" * 64}
        protected = protect_channel(value)
        self.assertEqual(protected["version"], 3)
        if os.name == "nt":
            import base64
            self.assertNotIn("a" * 64, json.dumps(protected))
            self.assertEqual(json.loads(dpapi(base64.b64decode(protected["payload"]), True)), value)


class JsoncTests(unittest.TestCase):
    def test_insert_and_noop_preserve_comments(self):
        for text in ('{}', '{"a":1, // keep\n}', '{"a":1 // keep\n}'):
            updated = set_property(text, ("providers", "web"), {})
            self.assertIn("web", parse_config(updated)["providers"])
            self.assertEqual(set_property(updated, ("providers", "web"), {}), updated)
            if "keep" in text:
                self.assertIn("// keep", updated)

    def test_duplicates_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_config('{"a":1,"a":2}')

if __name__ == "__main__":
    unittest.main()
