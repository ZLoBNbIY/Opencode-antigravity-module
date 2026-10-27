"""Shared proxy routing rules for OpenCode configuration."""

from urllib.parse import urlparse

DNS_PROXY = "http://127.0.0.1:51180"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def select_effective_proxy(config: dict, http_port: int) -> str | None:
    """Return the proxy selected by the Hub's VLESS/DNS priority rules."""
    if config.get("vless_enabled") and config.get("vless_url"):
        return f"http://127.0.0.1:{http_port}"

    user_proxy = config.get("proxy")
    if user_proxy and user_proxy != DNS_PROXY:
        return user_proxy

    if config.get("dns_mode") in ("standard", "dot", "doh"):
        return DNS_PROXY
    return None


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
