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
import urllib.request
import urllib.error

DOMAIN_TO_TEST = "cloudcode-pa.googleapis.com"


def _build_dns_query(domain_name, txid=None):
    if txid is None:
        txid = secrets.randbits(16)
    query = bytearray(struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0))
    for part in domain_name.strip(".").split("."):
        if not part:
            continue
        encoded = part.encode("ascii")
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
        if (length & 0xC0) == 0xC0:
            if idx + 1 >= len(data):
                return len(data)
            return idx + 2
        idx += 1 + length
        jumps += 1
        if jumps > 128:
            return len(data)
    return idx


def _parse_a_record_ip(data, expected_txid=None):
    # Minimal DNS wire response parser to extract IPv4 address from Answer section
    try:
        if len(data) < 12:
            return None
        txid, flags, qdcount, ancount, _nscount, _arcount = struct.unpack("!HHHHHH", data[:12])
        if expected_txid is not None and txid != expected_txid:
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
            rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", data[idx:idx + 10])
            idx += 10
            if rtype == 1 and rdlen == 4 and idx + 4 <= len(data):
                ip_bytes = data[idx:idx + 4]
                return ".".join(str(b) for b in ip_bytes)
            idx += rdlen
    except Exception:
        pass
    return None


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def test_standard_dns(ip_address, timeout=4, domain=None) -> dict:
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
        sock.sendto(query, (ip, 53))
        data, _ = sock.recvfrom(4096)
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
    url = url.strip()
    if not url:
        return {"ok": False, "message": "URL не указан"}
    if url.startswith("http://"):
        return {"ok": False, "message": "DoH требует HTTPS URL"}
    if not url.startswith("https://"):
        url = "https://" + url
    txid = secrets.randbits(16)
    query = _build_dns_query(domain or DOMAIN_TO_TEST, txid=txid)
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
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
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
        with opener.open(req, timeout=timeout) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000)
            data = resp.read()
            resolved_ip = _parse_a_record_ip(data)
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
    host = host.strip()
    if not host:
        return {"ok": False, "message": "Хост не указан"}
    if host.startswith("[") and "]" in host:
        end = host.index("]")
        rest = host[end + 1:]
        host = host[1:end]
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    elif host.count(":") == 1:
        parts = host.split(":", 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except Exception:
            pass
    txid = secrets.randbits(16)
    query = _build_dns_query(domain or DOMAIN_TO_TEST, txid=txid)
    dot_msg = struct.pack("!H", len(query)) + query
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    s = None
    ss = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.settimeout(timeout)
        ss.sendall(dot_msg)
        len_prefix = _recv_exact(ss, 2)
        if len(len_prefix) < 2:
            return {"ok": False, "message": "Некорректный ответ DoT"}
        msg_len = struct.unpack("!H", len_prefix)[0]
        data = _recv_exact(ss, msg_len)
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
