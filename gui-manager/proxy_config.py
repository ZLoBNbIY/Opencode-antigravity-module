"""Shared proxy routing rules for OpenCode configuration."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import jsonc_config

DNS_PROXY = "http://127.0.0.1:51180"
VLESS_PROXY = "http://127.0.0.1:20809"
ROUTE_PROXY = "http://127.0.0.1:10880"
# Plain-HTTP reverse endpoints. OpenCode 2.x (Bun) cannot reliably speak to a
# local CONNECT proxy, so providers with a reverse endpoint get a rewritten
# baseURL instead of options.proxy.
REVERSE_BASE_URLS = {"tokenlavka": "http://127.0.0.1:10880/r/tokenlavka/v1"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PROXY_ENV_KEYS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY"}
MANAGED_PROVIDER_IDS = frozenset({
    "google", "openai", "claude-pro", "xpiki", "deepseek-account",
    "openrouter-free", "tokenlavka", "nvidia-nim",
})
# Native OpenCode requests use a provider-scoped HTTP hook. Keep destinations
# fixed here; the dispatcher must never accept a destination from the client.
NATIVE_ROUTES = {
    "openai-chatgpt": ("openai", "https://chatgpt.com/backend-api/codex"),
    "openai-api": ("openai", "https://api.openai.com/v1"),
    "xpiki-api": ("xpiki", "https://api.xpiki.com/v1"),
    "openrouter-free-api": ("openrouter-free", "https://openrouter.ai/api/v1"),
    "deepseek-api": ("deepseek-account", "https://api.deepseek.com"),
    "nvidia-nim-api": ("nvidia-nim", "https://integrate.api.nvidia.com/v1"),
}
NATIVE_PROVIDER_IDS = frozenset(provider for provider, _ in NATIVE_ROUTES.values())
NATIVE_PLUGIN_NAME = "antigravity-hub-routes.js"
NATIVE_PLUGIN_MARKER = b"// Managed by AI HUB: provider-scoped routes\n"


def native_routes(config, deepseek_provider_id=None):
    """Resolve provider-level custom API URLs without transferring auth data."""
    routes = {}
    for key, (provider, default) in NATIVE_ROUTES.items():
        alias = (deepseek_provider_id if provider == "deepseek-account" and
                 deepseek_provider_id not in {"opencode", "opencode-go"} else None)
        endpoint = default
        if provider in {"deepseek-account", "xpiki", "openrouter-free", "nvidia-nim"}:
            for section in ("provider", "providers"):
                entries = config.get(section)
                entry = entries.get(alias or provider) if isinstance(entries, dict) else None
                if not isinstance(entry, dict):
                    continue
                for holder in ("options", "settings"):
                    settings = entry.get(holder)
                    if not isinstance(settings, dict):
                        continue
                    base = settings.get("baseURL") or settings.get("baseUrl")
                    if isinstance(base, str):
                        try:
                            parsed = urlparse(base)
                            if (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                                    and not parsed.query and not parsed.fragment):
                                endpoint = base.rstrip("/")
                        except ValueError:
                            pass
        routes[key] = (provider, endpoint, alias)
    return routes


def native_route_revision(endpoint):
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:24]


def native_route_plugin(config_path: Path, config=None, deepseek_provider_id=None, *, owner_path=None) -> bytes:
    routes = [[key, *route, native_route_revision(route[1])]
              for key, route in native_routes(config or {}, deepseek_provider_id).items()]
    return NATIVE_PLUGIN_MARKER + f"""import {{ access, readFile }} from "node:fs/promises";

const configPath = {json.dumps(str(config_path))};
const ownerPath = {json.dumps(str(owner_path) if owner_path is not None else None)};
const routes = {json.dumps(routes)};
async function hubConfig() {{
  try {{
    if (ownerPath) await access(ownerPath);
    return JSON.parse((await readFile(configPath, "utf8")).replace(/^\\uFEFF/, ""));
  }} catch (error) {{
    if (error.code === "ENOENT") return null;
    throw error;
  }}
}}

export default {{
  id: "antigravity-hub.provider-routes",
  async setup(ctx) {{
    const registrations = [];
    const config = await hubConfig();
    if (config && config.provider_routes?.openai !== "direct") {{
      registrations.push(await ctx.provider.transform((editor) => {{
        if (editor.get("openai")) editor.update("openai", (draft) => {{
          draft.settings = {{ ...draft.settings, transport: "http" }};
        }});
      }}));
    }}
    for (const provider of new Set(routes.flatMap(([, id, , alias]) => alias ? [id, alias] : [id]))) {{
      registrations.push(await ctx.session.hook("http.request", async (event) => {{
        const url = new URL(event.request.url);
        const match = routes.find(([, id, endpoint, alias]) => {{
          if (id !== provider && alias !== provider) return false;
          const base = new URL(endpoint);
          return url.origin === base.origin &&
            (base.pathname === "/" || url.pathname === base.pathname ||
             url.pathname.startsWith(base.pathname + "/"));
        }});
        if (!match) return;
        const config = await hubConfig();
        if (!config || config.provider_routes?.[match[1]] === "direct") return;
        event.request = new Request(
          "{ROUTE_PROXY}/r/" + match[0] + "/" + match[4] + url.pathname + url.search, event.request);
      }}, {{ providerID: provider }}));
    }}
    return async () => {{
      for (const registration of registrations) await registration.dispose();
    }};
  }},
}};
""".encode("utf-8")


def _legacy_hub_proxy(value):
    return isinstance(value, str) and value.strip().lower().rstrip("/") in {
        ROUTE_PROXY, DNS_PROXY,
    }


def opencode_launch_environment(base=None):
    """Do not pass a stale Hub dispatcher or legacy auth sentinel to OpenCode."""
    env = {
        key: value for key, value in (os.environ if base is None else base).items()
        if not (key.upper() in PROXY_ENV_KEYS and _legacy_hub_proxy(value))
    }
    # 3.1.x identifies its own requests with the OpenCode common-auth
    # placeholder.  Some systems still carry the 3.0.x "antigravity" value in
    # GOOGLE_GENERATIVE_AI_API_KEY; left unchanged, OpenCode sends it to Google
    # and gets "API key not valid" instead of letting the plugin attach OAuth.
    # Only that exact legacy sentinel is rewritten, for the 3.1.x profile.
    try:
        import opencode_config
        key = "GOOGLE_GENERATIVE_AI_API_KEY"
        current = env.get(key)
        expected = opencode_config.google_api_key_sentinel()
        if (isinstance(current, str)
                and current.strip() == opencode_config.GOOGLE_SENTINEL_API_KEY
                and expected == opencode_config.GOOGLE_SENTINEL_API_KEY_V2):
            env[key] = expected
    except Exception:
        pass
    return env


def select_effective_proxy(config: dict, http_port: int) -> str | None:
    """Return the proxy selected by the Hub's VLESS/DNS priority rules."""
    if config.get("vless_enabled") and config.get("vless_url"):
        return f"http://127.0.0.1:{http_port}"

    user_proxy = config.get("proxy")
    if user_proxy and user_proxy not in (DNS_PROXY, f"http://127.0.0.1:{http_port}"):
        return user_proxy

    if config.get("dns_mode") in ("standard", "dot", "doh"):
        return DNS_PROXY
    return None



def sync_process_proxy_environment(proxy: str | None) -> None:
    """Keep OpenCode's HTTPS proxy variables aligned with the Hub route."""
    import os

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        if proxy:
            os.environ[name] = proxy
        else:
            os.environ.pop(name, None)

    for name in ("NO_PROXY", "no_proxy"):
        current = [entry.strip() for entry in os.environ.get(name, "").split(",") if entry.strip()]
        current = [entry for entry in current if entry not in LOCAL_HOSTS]
        current.extend(("127.0.0.1", "localhost", "::1"))
        os.environ[name] = ",".join(dict.fromkeys(current))

def _is_local_endpoint(options: dict) -> bool:
    base_url = options.get("baseURL") or options.get("baseUrl")
    if not isinstance(base_url, str):
        return False
    try:
        return urlparse(base_url).hostname in LOCAL_HOSTS
    except ValueError:
        return False


def _sync_section(section: dict, proxy: str | None) -> None:
    for provider in section.values():
        if not isinstance(provider, dict):
            continue
        options = provider.get("options")
        settings = provider.get("settings")
        target = options if isinstance(options, dict) else None
        if target is None and isinstance(settings, dict):
            target = settings
        if target is None:
            target = provider.setdefault("options", {})

        if _is_local_endpoint(target):
            target.pop("proxy", None)
            continue
        if proxy:
            target["proxy"] = proxy
        else:
            target.pop("proxy", None)


def sync_provider_proxies(config: dict, proxy: str | None) -> dict:
    """Apply proxy to every external provider, leaving Hub-local endpoints alone."""
    for section_name in ("provider", "providers"):
        section = config.get(section_name)
        if isinstance(section, dict):
            _sync_section(section, proxy)
    return config


def sync_provider_routes(config: dict, hub_config: dict, http_port: int,
                         routes: dict | None = None, *, deepseek_provider_id=None) -> dict:
    """Configure Hub providers and remove stale Hub proxies from other entries."""
    routes = routes or {}

    for section_name in ("provider", "providers"):
        section = config.get(section_name)
        if not isinstance(section, dict):
            continue
        for provider_name, provider in section.items():
            if not isinstance(provider, dict):
                continue
            options = provider.get("options")
            settings = provider.get("settings")
            deepseek_alias = (provider_name == deepseek_provider_id and
                              provider_name not in {"opencode", "opencode-go"})
            managed = provider_name in MANAGED_PROVIDER_IDS or deepseek_alias
            route_key = "deepseek-account" if deepseek_alias else provider_name
            mode = routes.get(route_key, "default")
            if (not managed or route_key in NATIVE_PROVIDER_IDS
                    or (mode == "direct" and provider_name not in REVERSE_BASE_URLS)):
                for holder in (options, settings):
                    if isinstance(holder, dict) and _legacy_hub_proxy(holder.get("proxy")):
                        holder.pop("proxy", None)
                continue
            target = options if isinstance(options, dict) else settings if isinstance(settings, dict) else None
            if target is None:
                target = provider.setdefault("options", {})
            # A hub-managed reverse endpoint is local on purpose; it still
            # needs the route logic below (hubBaseURL holds the real target).
            if _is_local_endpoint(target) and not target.get("hubBaseURL"):
                if _legacy_hub_proxy(target.get("proxy")):
                    target.pop("proxy", None)
                continue

            if provider_name in REVERSE_BASE_URLS:
                original = target.get("hubBaseURL") or target.get("baseURL")
                if original and original != REVERSE_BASE_URLS[provider_name]:
                    target["hubBaseURL"] = original
                # Keep the local endpoint for every mode: "direct" only chooses
                # a direct upstream inside the dispatcher. Sending Bun straight
                # to the real https URL brings back ECONNRESET.
                target["baseURL"] = REVERSE_BASE_URLS[provider_name]
                target.pop("proxy", None)
            else:
                target["proxy"] = ROUTE_PROXY
    return config


def sync_provider_routes_text(text, hub_config, http_port, *, deepseek_provider_id=None):
    """Migrate/set only Hub routing fields; preserve unrelated JSONC comments."""
    before = jsonc_config.parse_config(text)
    after = sync_provider_routes(jsonc_config.parse_config(text), hub_config, http_port,
                                 hub_config.get("provider_routes"),
                                 deepseek_provider_id=deepseek_provider_id)
    for section_name in ("provider", "providers"):
        section = after.get(section_name)
        if not isinstance(section, dict):
            continue
        for provider_name, provider in section.items():
            if not isinstance(provider, dict):
                continue
            old_provider = before[section_name][provider_name]
            for holder in ("options", "settings"):
                current = provider.get(holder)
                if not isinstance(current, dict):
                    continue
                old = old_provider.get(holder)
                path = (section_name, provider_name, holder)
                if not isinstance(old, dict):
                    text = jsonc_config.set_property(text, path, current)
                    continue
                for key in ("proxy", "baseURL", "hubBaseURL"):
                    if key not in current and key in old:
                        text = jsonc_config.remove_property(text, (*path, key))
                    elif key in current and (key not in old or current[key] != old[key]):
                        text = jsonc_config.set_property(text, (*path, key), current[key])
    return text
