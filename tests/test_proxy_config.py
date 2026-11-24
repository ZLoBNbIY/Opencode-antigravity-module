import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from proxy_config import (DNS_PROXY, ROUTE_PROXY, native_route_plugin, opencode_launch_environment,
                          select_effective_proxy, sync_process_proxy_environment,
                          sync_provider_proxies, sync_provider_routes, sync_provider_routes_text)


class ProxyConfigTests(unittest.TestCase):
    def test_process_proxy_environment_sets_route_and_keeps_loopback_bypass(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"NO_PROXY": "example.com,localhost", "no_proxy": "example.com,localhost"}, clear=True):
            sync_process_proxy_environment("http://127.0.0.1:20809")
            self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:20809")
            self.assertEqual(os.environ["https_proxy"], "http://127.0.0.1:20809")
            self.assertIn("127.0.0.1", os.environ["NO_PROXY"])
            self.assertIn("localhost", os.environ["no_proxy"])
            self.assertIn("example.com", os.environ["NO_PROXY"])

    def test_vless_has_priority_over_custom_and_dns(self):
        config = {
            "vless_enabled": True,
            "vless_url": "vless://example",
            "proxy": "http://proxy.example:8080",
            "dns_mode": "doh",
        }
        self.assertEqual(select_effective_proxy(config, 20809), "http://127.0.0.1:20809")

    def test_dns_proxy_is_used_when_vless_is_disabled(self):
        config = {"vless_enabled": False, "proxy": DNS_PROXY, "dns_mode": "standard"}
        self.assertEqual(select_effective_proxy(config, 20809), DNS_PROXY)

    def test_dns_proxy_replaces_stale_vless_proxy_when_disabled(self):
        config = {
            "vless_enabled": False,
            "vless_url": "vless://example",
            "proxy": "http://127.0.0.1:20809",
            "dns_mode": "doh",
        }
        self.assertEqual(select_effective_proxy(config, 20809), DNS_PROXY)

        config = {
            "provider": {
                "google": {"options": {"apiKey": "antigravity"}},
                "openrouter": {"options": {"baseURL": "https://openrouter.ai/api/v1"}},
                "hub": {"options": {"baseURL": "http://127.0.0.1:51186/v1", "proxy": "http://127.0.0.1:51180"}},
            },
            "providers": {
                "custom": {"settings": {"baseURL": "https://api.custom.example/v1"}},
                "hub-local": {"settings": {"baseURL": "http://127.0.0.1:1/v1"}},
            },
        }
        sync_provider_proxies(config, "http://127.0.0.1:20809")
        self.assertEqual(config["provider"]["google"]["options"]["proxy"], "http://127.0.0.1:20809")
        self.assertEqual(config["provider"]["openrouter"]["options"]["proxy"], "http://127.0.0.1:20809")
        self.assertNotIn("proxy", config["provider"]["hub"]["options"])
        self.assertEqual(config["providers"]["custom"]["settings"]["proxy"], "http://127.0.0.1:20809")
        self.assertNotIn("proxy", config["providers"]["hub-local"]["settings"])

    def test_proxy_is_removed_from_external_providers_when_disabled(self):
        config = {"provider": {"google": {"options": {"proxy": DNS_PROXY}}}}
        sync_provider_proxies(config, None)
        self.assertNotIn("proxy", config["provider"]["google"]["options"])

    def test_only_managed_providers_use_local_route_dispatcher(self):
        config = {"provider": {
            "google": {"options": {}},
            "openrouter": {"options": {}},
            "xpiki": {"options": {"proxy": ROUTE_PROXY}},
            "custom": {"options": {"baseURL": "https://api.example/v1", "proxy": "old"}},
            "hub": {"options": {"baseURL": "http://localhost:9000/v1", "proxy": ROUTE_PROXY}},
        }}
        hub = {
            "vless_enabled": True, "vless_url": "vless://example",
            "dns_mode": "doh",
            "proxy": "http://proxy.example:8080",
        }
        sync_provider_routes(config, hub, 10879, {
            "google": "vless", "openrouter": "direct",
            "xpiki": "proxy", "custom": "dns", "hub": "vless",
        })
        opts = config["provider"]
        self.assertEqual(opts["google"]["options"]["proxy"], ROUTE_PROXY)
        # A direct provider must be free of the loopback dispatcher.
        self.assertNotIn("proxy", opts["openrouter"]["options"])
        self.assertNotIn("proxy", opts["xpiki"]["options"])
        self.assertEqual(opts["custom"]["options"]["proxy"], "old")
        self.assertNotIn("proxy", opts["hub"]["options"])

    def test_legacy_hub_proxy_is_removed_from_unmanaged_providers(self):
        config = {"provider": {
            "openai": {"options": {"proxy": ROUTE_PROXY}}, "google": {"options": {}},
            "openrouter": {"options": {"proxy": ROUTE_PROXY}},
        }, "providers": {"opencode": {"settings": {"proxy": ROUTE_PROXY, "headerTimeout": 5000}},
                         "custom": {"name": "Unmanaged"}}}
        hub = {"vless_enabled": True, "vless_url": "vless://example",
               "dns_mode": "system"}
        sync_provider_routes(config, hub, 10879, {"google": "direct"})
        providers = config["provider"]
        self.assertNotIn("proxy", providers["openai"]["options"])
        self.assertNotIn("proxy", providers["google"]["options"])
        self.assertNotIn("proxy", providers["openrouter"]["options"])
        self.assertEqual(config["providers"]["opencode"]["settings"], {"headerTimeout": 5000})
        self.assertEqual(config["providers"]["custom"], {"name": "Unmanaged"})

    def test_jsonc_migration_preserves_comments_and_other_settings(self):
        text = ('{"providers":{"opencode":{"settings":{/* leave me */'
                f'"proxy":"{ROUTE_PROXY}","headerTimeout":5000,'
                '"other":"keep"}},"openai":{"settings":{"transport":"http"}}}}')
        updated = sync_provider_routes_text(text, {"provider_routes": {"openai": "direct"}}, 10879)
        self.assertIn("/* leave me */", updated)
        self.assertNotIn(ROUTE_PROXY, updated)
        self.assertIn('"other":"keep"', updated)
        self.assertIn('"transport":"http"', updated)
        self.assertEqual(sync_provider_routes_text(updated, {"provider_routes": {"openai": "direct"}}, 10879),
                         updated)

    def test_launch_env_removes_only_legacy_hub_proxy(self):
        base = {"Https_Proxy": ROUTE_PROXY, "all_proxy": DNS_PROXY,
                "HTTP_PROXY": "http://company.example:8080", "NO_PROXY": "example.com",
                "OTHER": ROUTE_PROXY}
        self.assertEqual(opencode_launch_environment(base), {
            "HTTP_PROXY": "http://company.example:8080", "NO_PROXY": "example.com", "OTHER": ROUTE_PROXY,
        })
        self.assertIn("Https_Proxy", base)

    def test_launch_env_normalizes_legacy_google_sentinel_for_v2_plugin(self):
        from unittest.mock import patch
        with patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.1.13"):
            env = opencode_launch_environment({"GOOGLE_GENERATIVE_AI_API_KEY": "antigravity"})
        self.assertEqual(env["GOOGLE_GENERATIVE_AI_API_KEY"], "common-auth-placeholder.google")
        # Real keys are never replaced.
        with patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.1.13"):
            env = opencode_launch_environment({"GOOGLE_GENERATIVE_AI_API_KEY": "AIza-real-key"})
        self.assertEqual(env["GOOGLE_GENERATIVE_AI_API_KEY"], "AIza-real-key")

    @unittest.skipUnless(shutil.which("node"), "Node required for OpenCode plugin smoke test")
    def test_native_plugin_routes_only_eligible_requests(self):
        with TemporaryDirectory() as path:
            root = Path(path)
            hub = root / "hub.json"
            hub.write_text('{"provider_routes":{"openai":"proxy"}}', encoding="utf-8")
            (root / "routes.mjs").write_bytes(native_route_plugin(hub))
            (root / "probe.mjs").write_text(r'''
import assert from "node:assert/strict";
import {writeFile} from "node:fs/promises";
import plugin from "./routes.mjs";
const handlers = new Map();
let settings;
const cleanup = await plugin.setup({
  provider: {transform: async apply => {
    apply({get: id => id === "openai", update: (_, update) => {
      const provider = {settings: {other: true}};
      update(provider);
      settings = provider.settings;
    }});
    return {dispose() {}};
  }},
  session: {hook: async (name, hook, scope) => {
    assert.equal(name, "http.request");
    handlers.set(scope.providerID, hook);
    return {dispose: () => handlers.delete(scope.providerID)};
  }},
});
assert.deepEqual(settings, {other: true, transport: "http"});
assert.equal(handlers.has("opencode"), false);
const run = async url => {
  const request = new Request(url, {
    method: "POST", headers: {authorization: "Bearer fixture"}, body: "payload",
  });
  const event = {request};
  await handlers.get("openai")(event);
  return event.request;
};
const codex = "https://chatgpt.com/backend-api/codex/responses?fixture=1";
const managed = await run(codex);
assert.match(managed.url, /^http:\/\/127\.0\.0\.1:10880\/r\/openai-chatgpt\/[a-f0-9]+\/backend-api\/codex\/responses\?fixture=1$/);
assert.equal(managed.headers.get("authorization"), "Bearer fixture");
assert.equal(await managed.text(), "payload");
for (const url of ["https://auth.openai.com/oauth/token", "https://opencode.ai/zen/v1/chat",
                    "https://chatgpt.com/backend-api/codex-other"]) {
  assert.equal((await run(url)).url, url);
}
await writeFile(new URL("./hub.json", import.meta.url), '{"provider_routes":{"openai":"direct"}}');
assert.equal((await run(codex)).url, codex);
await cleanup();
assert.equal(handlers.size, 0);
''', encoding="utf-8")
            subprocess.run(["node", str(root / "probe.mjs")], check=True, timeout=15)

    def test_auto_and_legacy_default_both_use_the_dispatcher(self):
        for mode in ("auto", "default"):
            config = {"provider": {"google": {"options": {}}}}
            sync_provider_routes(config, {}, 10879, {"google": mode})
            self.assertEqual(config["provider"]["google"]["options"]["proxy"], ROUTE_PROXY)

    def test_tokenlavka_uses_plain_http_reverse_endpoint(self):
        from proxy_config import REVERSE_BASE_URLS
        config = {"provider": {"tokenlavka": {"options": {
            "baseURL": "https://tokenlavka.com/v1"}}}}
        hub = {"provider_routes": {"tokenlavka": "default"}}
        sync_provider_routes(config, hub, 10879, hub["provider_routes"])
        opts = config["provider"]["tokenlavka"]["options"]
        self.assertEqual(opts["baseURL"], REVERSE_BASE_URLS["tokenlavka"])
        self.assertEqual(opts["hubBaseURL"], "https://tokenlavka.com/v1")
        self.assertNotIn("proxy", opts)

    def test_tokenlavka_keeps_reverse_endpoint_for_every_route(self):
        from proxy_config import REVERSE_BASE_URLS
        for mode in ("direct", "vless", "dns", "proxy", "auto", "default"):
            config = {"provider": {"tokenlavka": {"options": {
                "baseURL": "https://tokenlavka.com/v1"}}}}
            hub = {"provider_routes": {"tokenlavka": mode}}
            sync_provider_routes(config, hub, 10879, hub["provider_routes"])
            opts = config["provider"]["tokenlavka"]["options"]
            self.assertEqual(opts["baseURL"], REVERSE_BASE_URLS["tokenlavka"], mode)
            self.assertNotIn("proxy", opts)


if __name__ == "__main__":
    unittest.main()
