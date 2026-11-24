"""
DNS Diagnostic & Testing Tool for Antigravity Hub
Tests:
1. Standard DNS (UDP/IPv4 port 53)
2. DNS-over-TLS (DoT port 853)
3. DNS-over-HTTPS (DoH RFC 8484)
"""

import time
import ssl
import socket
import struct
import secrets
import ipaddress
import urllib.parse
import urllib.request
import urllib.error

DOMAIN_TO_TEST = "cloudcode-pa.googleapis.com"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("DoH redirects are not allowed")


def _build_dns_query(domain_name, txid=None):
    if not isinstance(domain_name, str):
        raise ValueError("Invalid domain name")
    if txid is None:
        txid = secrets.randbits(16)
    query = bytearray(struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0))
    stripped = domain_name.strip().strip(".")
    if not stripped:
        raise ValueError("Empty domain name")
    total_len = 1
    for part in stripped.split("."):
        encoded = part.encode("ascii")
        if not (1 <= len(encoded) <= 63):
            raise ValueError("Invalid DNS label length")
        total_len += 1 + len(encoded)
        if total_len > 255:
            raise ValueError("DNS name too long")
        query.append(len(encoded))
        query.extend(encoded)
    query.append(0x00)
    query.extend([0x00, 0x01])  # Type A
    query.extend([0x00, 0x01])  # Class IN
    return bytes(query)


def _skip_dns_name(data, idx):
    jumps = 0
    while idx < len(data):
        length = data[idx]
        if length == 0:
            return idx + 1
        tag = length & 0xC0
        if tag == 0xC0:
            if idx + 1 >= len(data):
                raise ValueError("Truncated DNS compression pointer")
            return idx + 2
        if tag != 0:
            raise ValueError("Reserved DNS label tag")
        if length > 63 or idx + 1 + length > len(data):
            raise ValueError("Invalid DNS label length")
        idx += 1 + length
        jumps += 1
        if jumps > 128:
            raise ValueError("Too many DNS labels")
    raise ValueError("Truncated DNS name")


def _parse_a_record_ip(data, expected_txid=None):
    # Minimal DNS wire response parser to extract IPv4 address from Answer section
    try:
        if len(data) < 12:
            return None
        txid, flags, qdcount, ancount, _nscount, _arcount = struct.unpack("!HHHHHH", data[:12])
        if expected_txid is not None and txid != expected_txid:
            return None
        if not (flags & 0x8000):  # Must be QR=1 (response)
            return None
        rcode = flags & 0x0F
        if rcode != 0 or ancount == 0:
            return None
        idx = 12
        for _ in range(qdcount):
            idx = _skip_dns_name(data, idx)
            idx += 4  # skip type and class
            if idx > len(data):
                return None
        for _ in range(ancount):
            if idx >= len(data):
                break
            idx = _skip_dns_name(data, idx)
            if idx + 10 > len(data):
                break
            rtype, rclass, _ttl, rdlen = struct.unpack("!HHIH", data[idx:idx + 10])
            idx += 10
            if idx + rdlen > len(data):
                return None
            if rtype == 1 and rclass == 1 and rdlen == 4:
                ip_bytes = data[idx:idx + 4]
                return ".".join(str(b) for b in ip_bytes)
            idx += rdlen
    except Exception:
        pass
    return None


def _recv_exact(sock, n, deadline=None):
    buf = bytearray()
    while len(buf) < n:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("DoT read timed out")
            sock.settimeout(remaining)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def test_standard_dns(ip_address, timeout=4, domain=None) -> dict:
    if not isinstance(ip_address, str):
        return {"ok": False, "message": "IP не указан"}
    ip = ip_address.strip()
    if not ip:
        return {"ok": False, "message": "IP не указан"}
    txid = secrets.randbits(16)
    query = _build_dns_query(domain or DOMAIN_TO_TEST, txid=txid)
    t0 = time.perf_counter()
    sock = None
    try:
        addr_info = ipaddress.ip_address(ip)
        family = socket.AF_INET6 if addr_info.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        # A connected UDP socket only receives datagrams from this resolver's
        # address and port; the transaction ID still has to match below.
        sock.connect((ip, 53))
        sock.send(query)
        data = sock.recv(4096)
        elapsed = round((time.perf_counter() - t0) * 1000)
        resolved_ip = _parse_a_record_ip(data, expected_txid=txid)
        if not resolved_ip:
            return {"ok": False, "latency_ms": elapsed, "message": "DNS не вернул A-запись"}
        return {
            "ok": True,
            "latency_ms": elapsed,
            "resolved_ip": resolved_ip,
            "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
        }
    except socket.timeout:
        return {"ok": False, "message": "Таймаут (нет ответа за 4 сек)"}
    except Exception as e:
        return {"ok": False, "message": f"Ошибка: {str(e)[:60]}"}
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def test_doh_endpoint(url, timeout=5, domain=None) -> dict:
    if not isinstance(url, str):
        return {"ok": False, "message": "URL не указан"}
    url = url.strip()
    if not url:
        return {"ok": False, "message": "URL не указан"}
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return {"ok": False, "message": "Некорректный URL DoH"}
    if parsed.scheme.lower() != "https":
        return {"ok": False, "message": "DoH требует HTTPS URL"}
    if not parsed.hostname:
        return {"ok": False, "message": "Некорректный URL DoH"}
    url = parsed._replace(scheme="https").geturl()
    txid = secrets.randbits(16)
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        query = _build_dns_query(domain or DOMAIN_TO_TEST, txid=txid)
        req = urllib.request.Request(
            url,
            data=query,
            headers={
                "Content-Type": "application/dns-message",
                "Accept": "application/dns-message"
            },
            method="POST"
        )
        # Resolver availability must not depend on the selected AI provider proxy.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ctx),
            _NoRedirectHandler(),
        )
        with opener.open(req, timeout=timeout) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000)
            data = resp.read(65536)
            resolved_ip = _parse_a_record_ip(data, expected_txid=txid) if len(data) < 65536 else None
            if not resolved_ip:
                return {"ok": False, "latency_ms": elapsed, "message": "DoH не вернул A-запись"}
            return {
                "ok": True,
                "latency_ms": elapsed,
                "resolved_ip": resolved_ip,
                "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
            }
    except Exception as e:
        return {"ok": False, "message": f"Ошибка DoH: {str(e)[:60]}"}


def test_dot_endpoint(host, port=853, timeout=5, domain=None) -> dict:
    if not isinstance(host, str):
        return {"ok": False, "message": "Хост не указан"}
    host = host.strip()
    if not host:
        return {"ok": False, "message": "Хост не указан"}
    if host.startswith("["):
        if "]" not in host:
            return {"ok": False, "message": "Некорректный адрес DoT"}
        end = host.index("]")
        rest = host[end + 1:]
        host = host[1:end]
        if rest:
            if not (rest.startswith(":") and rest[1:].isdigit()):
                return {"ok": False, "message": "Некорректный порт DoT"}
            port = int(rest[1:])
    elif host.count(":") == 1:
        parts = host.split(":", 1)
        host = parts[0].strip()
        try:
            port = int(parts[1])
        except Exception:
            return {"ok": False, "message": "Некорректный порт DoT"}
    elif ":" in host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return {"ok": False, "message": "Некорректный адрес DoT"}
    if not host:
        return {"ok": False, "message": "Хост не указан"}
    if isinstance(port, bool):
        return {"ok": False, "message": "Некорректный порт DoT"}
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"ok": False, "message": "Некорректный порт DoT"}
    if not (1 <= port <= 65535):
        return {"ok": False, "message": "Некорректный порт DoT"}
    txid = secrets.randbits(16)
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    deadline = time.monotonic() + float(timeout)
    s = None
    ss = None
    try:
        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("DoT timed out")
            return budget

        query = _build_dns_query(domain or DOMAIN_TO_TEST, txid=txid)
        dot_msg = struct.pack("!H", len(query)) + query
        s = socket.create_connection((host, port), timeout=remaining())
        s.settimeout(remaining())
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.settimeout(remaining())
        ss.sendall(dot_msg)
        len_prefix = _recv_exact(ss, 2, deadline=deadline)
        if len(len_prefix) < 2:
            return {"ok": False, "message": "Некорректный ответ DoT"}
        msg_len = struct.unpack("!H", len_prefix)[0]
        data = _recv_exact(ss, msg_len, deadline=deadline)
        if len(data) < msg_len:
            return {"ok": False, "message": "Неполный ответ DoT"}
        elapsed = round((time.perf_counter() - t0) * 1000)
        resolved_ip = _parse_a_record_ip(data, expected_txid=txid)
        if not resolved_ip:
            return {"ok": False, "latency_ms": elapsed, "message": "DoT не вернул A-запись"}
        return {
            "ok": True,
            "latency_ms": elapsed,
            "resolved_ip": resolved_ip,
            "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
        }
    except Exception as e:
        return {"ok": False, "message": f"Ошибка DoT: {str(e)[:60]}"}
    finally:
        for sock in (ss, s):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
