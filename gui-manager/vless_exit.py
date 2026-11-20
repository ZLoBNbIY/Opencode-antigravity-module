"""Background dashboard check of the actual VLESS egress."""

import http.client
import ipaddress
import json
import re
import threading
import time
from contextlib import closing


def _fetch(port, host, path):
    # Explicit CONNECT: never bypass VLESS because of NO_PROXY or use the
    # Hub's general dispatcher, which may choose a different route.
    with closing(http.client.HTTPSConnection("127.0.0.1", port, timeout=4)) as conn:
        conn.set_tunnel(host, 443)
        conn.request("GET", path, headers={"Host": host, "User-Agent": "AntigravityHub/1.0"})
        with conn.getresponse() as response:
            if response.status != 200:
                return ""
            return response.read(16384).decode()


def _location(ip, country):
    parsed = ipaddress.ip_address(ip)
    if not parsed.is_global:
        raise ValueError("Not a public IP")
    country = str(country or "").strip().upper()
    return {"ip": str(parsed), "country": country if re.fullmatch(r"[A-Z]{2}", country) and country != "XX" else None}


def probe_vless_exit(port):
    first = None
    try:
        trace = _fetch(port, "cloudflare.com", "/cdn-cgi/trace")
        fields = dict(line.split("=", 1) for line in trace.splitlines() if "=" in line)
        first = _location(fields.get("ip"), fields.get("loc"))
        if first["country"]:
            return first
    except (OSError, http.client.HTTPException, ValueError):
        pass
    try:
        data = json.loads(_fetch(port, "ipwho.is", "/?fields=ip,country_code"))
        if isinstance(data, dict):
            second = _location(data.get("ip"), data.get("country_code"))
            return second if second["country"] else first or second
    except (OSError, http.client.HTTPException, ValueError):
        pass
    return first


class VlessExitStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._revision = 0
        self._job = None
        self._next_check = 0
        self._result = None

    def snapshot(self, identity, port=None):
        """Return only location fields; identity is process/config bookkeeping."""
        with self._lock:
            if identity != self._key:
                self._key = identity
                self._revision += 1
                self._next_check = 0
                self._result = None
            if identity is None:
                return {"status": "stopped"}
            if self._job is None and time.monotonic() >= self._next_check:
                job = object()
                self._job = job
                threading.Thread(target=self._refresh, args=(job, self._revision, port),
                                 name="vless-dashboard-exit", daemon=True).start()
            return dict(self._result or {"status": "checking"})

    def _refresh(self, job, revision, port):
        result = None
        try:
            result = probe_vless_exit(port)
        finally:
            with self._lock:
                if self._job is job:
                    self._job = None
                    if revision == self._revision:
                        self._result = {"status": "ok", **result} if result else {"status": "unavailable"}
                        self._next_check = time.monotonic() + (180 if result else 30)
