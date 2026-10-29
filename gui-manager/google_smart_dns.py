"""Hub-owned DNS resolution and opaque TLS transport for Cloud Code.

The resolver supplies public forwarding addresses. No system DNS lookup of a
Cloud Code host, local Unlocker, certificate installation or TLS interception.
"""

import ipaddress
import secrets
import socket
import struct
import threading
import time
from urllib.parse import urlparse

GATE_HOSTS = ("daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com")
DEFAULT_DOH = "https://dns.dns-ai.ru/dns-query"
_cache = {}
_lock = threading.Lock()


def _query(host):
    name = b"".join(bytes([len(part)]) + part.encode("ascii") for part in host.split(".")) + b"\0"
    return secrets.token_bytes(2) + struct.pack("!5H", 0x100, 1, 0, 0, 0) + name + struct.pack("!HH", 1, 1)


def _name(data, offset):
    labels, visited, end = [], set(), None
    while True:
        if offset in visited or offset >= len(data):
            raise ValueError("Invalid DNS name")
        visited.add(offset)
        size = data[offset]
        if size & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise ValueError("Truncated DNS pointer")
            if end is None:
                end = offset + 2
            offset = ((size & 0x3F) << 8) | data[offset + 1]
            continue
        if size > 63 or offset + 1 + size > len(data):
            raise ValueError("Invalid DNS label")
        offset += 1
        if not size:
            return ".".join(labels).lower(), end if end is not None else offset
        labels.append(data[offset:offset + size].decode("ascii"))
        offset += size


def _answers(data, query):
    if len(data) < 12 or data[:2] != query[:2]:
        raise ValueError("DNS transaction mismatch")
    _, flags, questions, count, _, _ = struct.unpack_from("!6H", data)
    if not flags & 0x8000 or flags & 0x7A0F or questions != 1:
        raise ValueError("DNS response failed or was truncated")
    host, offset = _name(data, 12)
    expected, _ = _name(query, 12)
    if host != expected or data[offset:offset + 4] != struct.pack("!HH", 1, 1):
        raise ValueError("DNS question mismatch")
    offset += 4
    records, aliases = [], {host}
    for _ in range(count):
        owner, offset = _name(data, offset)
        kind, klass, ttl, size = struct.unpack_from("!HHIH", data, offset)
        offset += 10
        if offset + size > len(data):
            raise ValueError("Truncated DNS answer")
        value = None
        if klass == 1 and kind == 1 and size == 4:
            value = socket.inet_ntoa(data[offset:offset + 4])
        elif klass == 1 and kind == 5:
            value, _ = _name(data, offset)
        records.append((owner, kind, value, ttl))
        offset += size
    for _ in records:
        for owner, kind, value, _ttl in records:
            if kind == 5 and value and owner in aliases:
                aliases.add(value)
    addresses = [value for owner, kind, value, ttl in records
                 if owner in aliases and kind == 1 and value and ipaddress.ip_address(value).is_global]
    ttls = [ttl for owner, kind, value, ttl in records if owner in aliases and value and kind in (1, 5)]
    if not addresses:
        raise ValueError("DNS returned no public IPv4 address")
    return list(dict.fromkeys(addresses)), min(min(ttls), 120)


def resolver_url(config):
    url = str(config.get("google_smart_doh") or DEFAULT_DOH).strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Google SmartDNS требует HTTPS DoH URL без пароля")
    return url


def _resolver_urls(config):
    primary = resolver_url(config)
    fallback = DEFAULT_DOH if primary != DEFAULT_DOH else "https://dns.google/dns-query"
    return [primary, fallback]


def resolve(host, config):
    host = host.lower().rstrip(".")
    if host not in GATE_HOSTS:
        raise ValueError("Google SmartDNS supports Cloud Code hosts only")
    url = resolver_url(config)
    key = (host, url)
    # Serialize cache misses to avoid a DNS burst when the client opens a pool.
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.monotonic():
            return list(entry[1])
        import httpx
        query = _query(host)
        errors = []
        for candidate in _resolver_urls(config):
            try:
                # Ignore the Hub's HTTP_PROXY: resolving through ourselves would recurse.
                with httpx.Client(http2=True, trust_env=False, timeout=8) as client:
                    response = client.post(candidate, content=query, headers={
                        "Content-Type": "application/dns-message", "Accept": "application/dns-message"})
                    response.raise_for_status()
                    if response.headers.get("content-type", "").split(";")[0].strip() != "application/dns-message":
                        raise ValueError("DoH returned unexpected content")
                    addresses, ttl = _answers(response.content, query)
                _cache[key] = (time.monotonic() + ttl, addresses)
                return list(addresses)
            except Exception as exc:
                errors.append(f"{urlparse(candidate).hostname}: {exc}")
        raise OSError("Google SmartDNS resolvers failed: " + "; ".join(errors))


def connect(host, port, config):
    if port != 443:
        raise ValueError("Google SmartDNS supports TLS port 443 only")
    addresses = resolve(host, config)
    deadline = time.monotonic() + 12
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            upstream = socket.create_connection((address, port), timeout=min(4, remaining))
            upstream.settimeout(None)
            return upstream
        except OSError:
            continue
    with _lock:
        _cache.pop((host.lower().rstrip("."), resolver_url(config)), None)
    raise OSError("Google SmartDNS forwarding addresses are unreachable")
