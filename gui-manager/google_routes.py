"""Credential-free descriptions and diagnostics of Hub Google routes."""

import socket
from urllib.parse import urlparse

GATE_HOSTS = ("daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com")


def describe_route(host, hub_config=None):
    import provider_proxy

    upstream = provider_proxy.select_upstream(host, hub_config=hub_config)
    if upstream is None:
        return "Системный маршрут / DNS (может использовать VPN или Unlocker)"
    if upstream == "dns://hub":
        return "DNS-прокси Hub"
    parsed = urlparse(upstream)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}"


def diagnose_routes():
    import provider_proxy

    config = provider_proxy._read_json(provider_proxy.CONFIG_DIR / "antigravity.json")
    rows = []
    for host in GATE_HOSTS:
        try:
            route = describe_route(host, config)
            addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
            dns_label = "Системный DNS; при внешнем прокси имя разрешает прокси"
            rows.append(f"{host}\nМаршрут: {route}\n{dns_label}: {', '.join(addresses)}")
        except Exception as error:
            rows.append(f"{host}: ошибка диагностики ({type(error).__name__})")
    rows.append("DNS и доступность TCP не подтверждают генерацию. Используйте тест модели.")
    return "\n\n".join(rows)
