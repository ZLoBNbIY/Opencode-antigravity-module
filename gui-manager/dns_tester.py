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
import urllib.request
import urllib.error

DOMAIN_TO_TEST = "cloudcode-pa.googleapis.com"

def _build_dns_query(domain_name):
    query = bytearray([0x12, 0x34, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    for part in domain_name.split('.'):
        query.append(len(part))
        query.extend(part.encode('ascii'))
    query.append(0x00)
    query.extend([0x00, 0x01]) # Type A
    query.extend([0x00, 0x01]) # Class IN
    return bytes(query)

def _parse_a_record_ip(data):
    # Minimal DNS wire response parser to extract IPv4 address
    try:
        if len(data) < 12:
            return None
        # skip header (12 bytes)
        idx = 12
        # skip question section
        while idx < len(data) and data[idx] != 0:
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
                break
            idx += 1 + data[idx]
        if idx < len(data) and data[idx] == 0:
            idx += 1
        idx += 4 # skip type and class
        # parse answer section
        while idx < len(data):
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                if idx < len(data): idx += 1
            if idx + 10 > len(data):
                break
            rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[idx:idx+10])
            idx += 10
            if rtype == 1 and rdlen == 4 and idx + 4 <= len(data):
                ip_bytes = data[idx:idx+4]
                return ".".join(str(b) for b in ip_bytes)
            idx += rdlen
    except Exception:
        pass
    return None

def test_standard_dns(ip_address, timeout=4, domain=None) -> dict:
    ip = ip_address.strip()
    if not ip:
        return {"ok": False, "message": "IP не указан"}
    query = _build_dns_query(domain or DOMAIN_TO_TEST)
    t0 = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(query, (ip, 53))
        data, _ = sock.recvfrom(512)
        elapsed = round((time.perf_counter() - t0) * 1000)
        sock.close()
        resolved_ip = _parse_a_record_ip(data)
        return {
            "ok": True,
            "latency_ms": elapsed,
            "resolved_ip": resolved_ip or "OK",
            "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
        }
    except socket.timeout:
        return {"ok": False, "message": "Таймаут (нет ответа за 4 сек)"}
    except Exception as e:
        return {"ok": False, "message": f"Ошибка: {str(e)[:60]}"}

def test_doh_endpoint(url, timeout=5, domain=None) -> dict:
    url = url.strip()
    if not url:
        return {"ok": False, "message": "URL не указан"}
    if not url.startswith("http"):
        url = "https://" + url
    query = _build_dns_query(domain or DOMAIN_TO_TEST)
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
            return {
                "ok": True,
                "latency_ms": elapsed,
                "resolved_ip": resolved_ip or "OK",
                "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
            }
    except Exception as e:
        return {"ok": False, "message": f"Ошибка DoH: {str(e)[:60]}"}

def test_dot_endpoint(host, port=853, timeout=5, domain=None) -> dict:
    host = host.strip()
    if not host:
        return {"ok": False, "message": "Хост не указан"}
    if ":" in host and not host.startswith("["):
        parts = host.split(":")
        host = parts[0]
        try: port = int(parts[1])
        except Exception: pass
    query = _build_dns_query(domain or DOMAIN_TO_TEST)
    dot_msg = struct.pack("!H", len(query)) + query
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.connect((host, port))
        ss.sendall(dot_msg)
        # read 2 bytes length
        len_prefix = ss.recv(2)
        if len(len_prefix) < 2:
            return {"ok": False, "message": "Некорректный ответ DoT"}
        msg_len = struct.unpack("!H", len_prefix)[0]
        data = ss.recv(msg_len)
        elapsed = round((time.perf_counter() - t0) * 1000)
        ss.close()
        resolved_ip = _parse_a_record_ip(data)
        return {
            "ok": True,
            "latency_ms": elapsed,
            "resolved_ip": resolved_ip or "OK",
            "message": f"Доступен ({elapsed} мс, IP: {resolved_ip})"
        }
    except Exception as e:
        return {"ok": False, "message": f"Ошибка DoT: {str(e)[:60]}"}
