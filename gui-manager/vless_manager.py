"""
VLESS Tunnel Manager for Antigravity Hub.
Supports parsing vless:// URLs, configuring and running Xray-core or sing-box,
and routing traffic from OpenCode and Antigravity Hub.
"""

import ctypes
import hashlib
import ipaddress
import os
import platform
import sys
import json
import time
import socket
import ssl
import stat
import tempfile
import urllib.parse
import urllib.request
import subprocess
import threading
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

try:
    import hub_paths
    CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
    VLESS_RUNTIME_DIR = hub_paths.VLESS_RUNTIME_DIR
except Exception:
    CONFIG_DIR = Path.home() / ".config" / "opencode"
    VLESS_RUNTIME_DIR = CONFIG_DIR / "vless"
VLESS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# Non-standard ports to avoid collisions with other local VPN/proxy tools
# (for example browser extensions that run their own Xray on 10808/10809).
# Can be overridden in ~/.config/opencode/antigravity.json:
#   "vless_http_port": <int>, "vless_socks_port": <int>
DEFAULT_HTTP_PORT = 10879
DEFAULT_SOCKS_PORT = 10878
LOCAL_DNS_PROXY_PORT = 51180

# SHA-256 from the official GitHub Releases API asset `digest` fields:
# /repos/SagerNet/sing-box/releases/tags/v1.14.4
# /repos/XTLS/Xray-core/releases/tags/v26.11.9
# Update URLs and digests together; do not fetch replacement digests at runtime.
_CORE_RELEASES = {
    "sing-box": (
        "https://github.com/SagerNet/sing-box/releases/download/v1.14.4/sing-box-1.14.4-windows-amd64.zip",
        "99185d75d314a07dbba4a130c8ad986cbeb629a07927975636b341ca61f991df",
    ),
    "xray": (
        "https://github.com/XTLS/Xray-core/releases/download/v26.11.9/Xray-windows-64.zip",
        "1262522266337b824f07beb8e1375786b437683b3890105469088f8e17e0a69d",
    ),
}
_RELEASE_HOSTS = {"github.com", "release-assets.githubusercontent.com"}
_ARCHIVE_NAME = "release.zip"
_MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
_MAX_EXTRACTED_SIZE = 512 * 1024 * 1024
_START_TIMEOUT = 8.0


def _check_release_origin(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in _RELEASE_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError("Недоверенный источник загрузки ядра")


class _ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_release_origin(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TunnelProxyHandler(urllib.request.ProxyHandler):
    def proxy_open(self, req, proxy, proxy_type):
        # These probes must not bypass the explicitly selected proxy via NO_PROXY.
        if req.type != "https":
            raise ValueError("HTTPS required for tunnel health checks")
        req.set_proxy(urllib.parse.urlsplit(proxy).netloc, "http")
        return None


class _TunnelRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("HTTPS required for tunnel health checks")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _sha256(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _plain_path(path: Path, mode_check) -> bool:
    info = path.lstat()
    return (mode_check(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _verified_archive(archive, digest: str) -> None:
    if os.fstat(archive.fileno()).st_size > _MAX_ARCHIVE_SIZE or _sha256(archive) != digest:
        raise ValueError("Контрольная сумма SHA-256 архива ядра не совпадает")
    archive.seek(0)


def _core_members(zf: zipfile.ZipFile, core_type: str) -> Dict[str, zipfile.ZipInfo]:
    allowed = {f"{core_type}.exe"}
    if core_type == "sing-box":
        allowed.add("libcronet.dll")
    else:
        allowed.update(("geoip.dat", "geosite.dat"))
    members = {}
    for entry in zf.infolist():
        parts = entry.orig_filename.rstrip("/").split("/")
        unix_type = stat.S_IFMT(entry.external_attr >> 16)
        if (any(part in ("", ".", "..") or any(c in part for c in "\\:\0") for part in parts)
                or unix_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError("Недопустимый путь или тип файла в архиве ядра")
        name = parts[-1].lower()
        if name in allowed:
            if name in members or entry.is_dir() or unix_type == stat.S_IFDIR:
                raise ValueError("Неоднозначный файл в архиве ядра")
            members[name] = entry
    if f"{core_type}.exe" not in members or sum(e.file_size for e in members.values()) > _MAX_EXTRACTED_SIZE:
        raise ValueError("Неожиданное содержимое архива ядра")
    return members


def _windows_listener_ports(pid: int, ports: Tuple[int, ...]) -> set[int]:
    # GetExtendedTcpTable: DWORD count, then MIB_TCPROW_OWNER_PID rows (6 DWORDs).
    dword = ctypes.c_uint32
    row_type = dword * 6
    get_table = ctypes.WinDLL("iphlpapi.dll", winmode=0x800).GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(dword), ctypes.c_int,
                          dword, ctypes.c_int, dword]
    get_table.restype = dword
    size = dword()
    buffer = None
    for _ in range(4):
        result = get_table(buffer, ctypes.byref(size), 0, socket.AF_INET, 3, 0)
        if result == 0 and buffer is not None:
            count = dword.from_buffer(buffer).value
            if count > (len(buffer) - ctypes.sizeof(dword)) // ctypes.sizeof(row_type):
                break
            rows = (row_type * count).from_buffer(buffer, ctypes.sizeof(dword))
            loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
            owned, competing = set(), set()
            for state, address, network_port, _, _, owner in rows:
                port = socket.ntohs(network_port & 0xFFFF)
                if state == 2 and port in ports:
                    if address == loopback and owner == pid:
                        owned.add(port)
                    elif address in (0, loopback):
                        competing.add(port)
            return owned - competing
        if result != 122 or not 0 < size.value <= 16 * 1024 * 1024:
            break
        buffer = ctypes.create_string_buffer(size.value)
    return set()


def load_hub_config() -> Dict[str, Any]:
    """Reads the Hub configuration file (silently returns {} on errors)."""
    cfg_file = CONFIG_DIR / "antigravity.json"
    try:
        if cfg_file.exists():
            return json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _sanitize_port(value: Any, fallback: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return fallback
    if 1024 <= port <= 65535:
        return port
    return fallback


def get_configured_ports() -> Tuple[int, int]:
    """Returns (http_port, socks_port), taking user overrides into account."""
    cfg = load_hub_config()
    http_port = _sanitize_port(cfg.get("vless_http_port"), DEFAULT_HTTP_PORT)
    socks_port = _sanitize_port(cfg.get("vless_socks_port"), DEFAULT_SOCKS_PORT)
    if http_port == socks_port:
        socks_port = DEFAULT_SOCKS_PORT if http_port != DEFAULT_SOCKS_PORT else DEFAULT_HTTP_PORT
    return http_port, socks_port


def get_http_port() -> int:
    return get_configured_ports()[0]


def get_socks_port() -> int:
    return get_configured_ports()[1]


def is_port_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def get_active_proxy(
    cfg: Optional[Dict[str, Any]] = None,
    port_probe=None,
    is_local_proxy_running=None,
) -> Optional[str]:
    """
    Returns the effective local proxy URL for Hub-managed traffic.

    Priority per Hub network policy:
      1. VLESS tunnel (built-in Xray/sing-box).
      2. User-defined external proxy (from the "proxy" config key).
      3. Local DNS proxy (custom DNS mode) on 127.0.0.1:51180.
      4. None (direct connection).
    """
    if cfg is None:
        cfg = load_hub_config()
    if port_probe is None:
        port_probe = is_port_open

    http_port = _sanitize_port(cfg.get("vless_http_port"), DEFAULT_HTTP_PORT)

    # 1. VLESS is a routing preference, not a readiness check. Do not silently
    # switch a configured VLESS route to direct when the tunnel is unavailable.
    if cfg.get("vless_enabled") and cfg.get("vless_url"):
        return f"http://127.0.0.1:{http_port}"

    # 2. User-defined external proxy
    user_proxy = cfg.get("proxy")
    if user_proxy and str(user_proxy).strip() != f"http://127.0.0.1:{LOCAL_DNS_PROXY_PORT}":
        return str(user_proxy).strip()

    # 3. Local DNS proxy (custom DNS mode: standard / DoT / DoH)
    if cfg.get("dns_mode") in ("standard", "dot", "doh"):
        if is_local_proxy_running is None:
            is_local_proxy_running = lambda: port_probe(LOCAL_DNS_PROXY_PORT)
        if is_local_proxy_running():
            return f"http://127.0.0.1:{LOCAL_DNS_PROXY_PORT}"

    return None


class VlessParser:
    """Parses vless:// URI strings into structured configuration."""

    @staticmethod
    def parse_url(url_str: str) -> Dict[str, Any]:
        if not isinstance(url_str, str):
            raise ValueError("Укажите ссылку VLESS")
        url_str = url_str.strip()
        if not url_str.startswith("vless://"):
            raise ValueError("Ссылка должна начинаться с 'vless://'")

        parsed = urllib.parse.urlparse(url_str)
        user_info = parsed.netloc.split("@")
        if len(user_info) != 2:
            raise ValueError("Некорректный формат vless:// (ожидается uuid@host:port)")

        uuid = user_info[0]
        host_port = user_info[1].split(":")
        if len(host_port) != 2:
            raise ValueError("Некорректный адрес или порт сервера")

        server = host_port[0]
        try:
            port = int(host_port[1])
        except ValueError:
            raise ValueError(f"Некорректный номер порта: {host_port[1]}")

        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}

        tag = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"{server}:{port}"

        return {
            "uuid": uuid,
            "server": server,
            "port": port,
            "security": params.get("security", "none"),
            "sni": params.get("sni", params.get("peer", server)),
            "alpn": params.get("alpn", "").split(",") if params.get("alpn") else ["h2", "http/1.1"],
            "fingerprint": params.get("fp", "chrome"),
            "pbk": params.get("pbk", ""),
            "sid": params.get("sid", ""),
            "spx": params.get("spx", ""),
            "flow": params.get("flow", ""),
            "type": params.get("type", "tcp"),
            "path": params.get("path", "/"),
            "serviceName": params.get("serviceName", params.get("service_name", "")),
            "tag": tag,
        }


class VlessManager:
    """Manages the VLESS client core process, configuration, and health testing."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._runtime: Optional[Path] = None
        self._ports: Tuple[int, ...] = ()
        self._lock = threading.Lock()
        self._status = "stopped"
        self._last_test_result: Optional[Dict[str, Any]] = None
        self._exit_generation = 0

    def exit_generation(self) -> int:
        """Return the revision of the last transition to or from a ready tunnel."""
        with self._lock:
            return self._exit_generation

    def get_bin_dir(self) -> Path:
        try:
            import hub_paths
            p = hub_paths.BIN_DIR
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            local_bin = Path(__file__).resolve().parent / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            return local_bin

    def _managed_core(self, directory: Path, core_type: str, digest: str) -> Path:
        archive_path = directory / _ARCHIVE_NAME
        if (not _plain_path(directory.parent, stat.S_ISDIR)
                or not _plain_path(directory, stat.S_ISDIR)
                or not _plain_path(archive_path, stat.S_ISREG)):
            raise ValueError("Небезопасный каталог управляемого ядра")
        # The retained pinned archive authenticates the installed files. A local
        # sidecar of hashes could be altered together with the executable.
        with archive_path.open("rb") as archive:
            _verified_archive(archive, digest)
            with zipfile.ZipFile(archive) as zf:
                members = _core_members(zf, core_type)
                if {p.name for p in directory.iterdir()} != {*members, _ARCHIVE_NAME}:
                    raise ValueError("Неожиданные файлы в каталоге ядра")
                for name, member in members.items():
                    path = directory / name
                    if not _plain_path(path, stat.S_ISREG) or path.stat().st_size != member.file_size:
                        raise ValueError("Повреждён файл установленного ядра")
                    with path.open("rb") as installed, zf.open(member) as original:
                        if _sha256(installed) != _sha256(original):
                            raise ValueError("Контрольная сумма установленного файла не совпадает")
        return directory / f"{core_type}.exe"

    def find_core_executable(self, custom_path: Optional[str] = None, core_type: Optional[str] = None) -> Optional[Path]:
        try:
            bin_dir = self.get_bin_dir().absolute()
            managed = bin_dir / "managed-vless"
            candidate = Path(os.path.abspath(custom_path)) if custom_path else None
            if candidate is not None:
                resolved = candidate.resolve(strict=True)
                # Old flat installs were not verified. Do not implicitly trust
                # them, even if an old Hub configuration stored the path.
                managed_roots = (managed, bin_dir, CONFIG_DIR / "bin", Path(__file__).resolve().parent / "bin")
                managed_path = any(path.is_relative_to(root_path)
                                   for path in (candidate, resolved)
                                   for root in managed_roots
                                   for root_path in (root.absolute(), root.resolve()))
                if not managed_path:
                    # An explicit path outside Hub bin dirs is operator trust.
                    return resolved if resolved.is_file() else None
            for kind in ((core_type,) if core_type else ("xray", "sing-box")):
                if kind not in _CORE_RELEASES:
                    continue
                _, digest = _CORE_RELEASES[kind]
                directory = managed / f"{kind}-{digest}"
                if candidate is not None and candidate != directory / f"{kind}.exe":
                    continue
                try:
                    return self._managed_core(directory, kind, digest)
                except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
                    continue
        except (OSError, ValueError, RuntimeError):
            pass
        return None

    def is_core_available(self, custom_path: Optional[str] = None) -> bool:
        return self.find_core_executable(custom_path) is not None

    def download_core(self, core_type: str = "sing-box", progress_callback=None) -> Tuple[bool, str]:
        """Install a pinned archive via an atomic, same-filesystem directory rename."""
        if core_type not in _CORE_RELEASES:
            return False, "Неизвестное ядро"
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            return False, "Автоустановка поддерживает только Windows x64. Укажите путь к проверенному ядру."
        url, digest = _CORE_RELEASES[core_type]
        try:
            bin_dir = self.get_bin_dir().absolute()
            if not _plain_path(bin_dir, stat.S_ISDIR):
                raise ValueError("Небезопасный каталог для установки ядра")
            managed = bin_dir / "managed-vless"
            managed.mkdir(exist_ok=True)
            if not _plain_path(managed, stat.S_ISDIR):
                raise ValueError("Небезопасный каталог управляемого ядра")
            destination = managed / f"{core_type}-{digest}"
            if os.path.lexists(destination):
                core = self._managed_core(destination, core_type, digest)
                return True, f"Ядро уже установлено: {core.name}"
            _check_release_origin(url)
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=managed) as staging_path:
                staging = Path(staging_path)
                if progress_callback:
                    progress_callback(f"Загрузка {core_type}...")
                req = urllib.request.Request(url, headers={"User-Agent": "AntigravityHub/1.0"})
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                    _ReleaseRedirectHandler(),
                )
                with opener.open(req, timeout=30) as resp, (staging / _ARCHIVE_NAME).open("xb") as archive:
                    _check_release_origin(resp.geturl())
                    downloaded = 0
                    for chunk in iter(lambda: resp.read(65536), b""):
                        downloaded += len(chunk)
                        if downloaded > _MAX_ARCHIVE_SIZE:
                            raise ValueError("Архив ядра слишком велик")
                        archive.write(chunk)
                if progress_callback:
                    progress_callback("Проверка и распаковка архива...")
                with (staging / _ARCHIVE_NAME).open("rb") as archive:
                    _verified_archive(archive, digest)
                    with zipfile.ZipFile(archive) as zf:
                        for name, member in _core_members(zf, core_type).items():
                            with zf.open(member) as source, (staging / name).open("xb") as target:
                                shutil.copyfileobj(source, target)
                try:
                    # Concurrent installers cannot replace a populated release.
                    staging.rename(destination)
                except OSError:
                    if not os.path.lexists(destination):
                        raise
                    self._managed_core(destination, core_type, digest)
            return True, f"Ядро успешно установлено: {core_type}.exe"
        except Exception as e:
            return False, (f"Ошибка установки ядра: {e}. Если установка повреждена, удалите её каталог "
                           "вручную или укажите путь к проверенному ядру.")

    def generate_xray_config(self, params: Dict[str, Any], http_port: int, socks_port: int) -> Dict[str, Any]:
        """Creates an Xray JSON config."""
        stream_settings: Dict[str, Any] = {
            "network": params["type"],
            "security": params["security"],
        }

        if params["security"] == "reality":
            stream_settings["realitySettings"] = {
                "show": False,
                "fingerprint": params["fingerprint"] or "chrome",
                "serverName": params["sni"],
                "publicKey": params["pbk"],
                "shortId": params["sid"],
                "spiderX": params.get("spx", ""),
            }
        elif params["security"] == "tls":
            stream_settings["tlsSettings"] = {
                "serverName": params["sni"],
                "fingerprint": params["fingerprint"] or "chrome",
                "alpn": params["alpn"],
            }

        if params["type"] == "ws":
            stream_settings["wsSettings"] = {
                "path": params["path"],
                "headers": {"Host": params["sni"]},
            }
        elif params["type"] == "grpc":
            stream_settings["grpcSettings"] = {
                "serviceName": params["serviceName"],
                "multiMode": True,
            }

        user_obj: Dict[str, Any] = {
            "id": params["uuid"],
            "encryption": "none",
        }
        if params.get("flow"):
            user_obj["flow"] = params["flow"]

        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "port": socks_port,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": True},
                },
                {
                    "port": http_port,
                    "listen": "127.0.0.1",
                    "protocol": "http",
                    "settings": {"timeout": 300},
                },
            ],
            "outbounds": [
                {
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": params["server"],
                                "port": params["port"],
                                "users": [user_obj],
                            }
                        ]
                    },
                    "streamSettings": stream_settings,
                },
                {
                    "protocol": "freedom",
                    "tag": "direct",
                },
            ],
        }
        return config

    def generate_sing_box_config(self, params: Dict[str, Any], http_port: int, socks_port: int) -> Dict[str, Any]:
        """Creates a sing-box JSON config."""
        is_tls = params["security"] in ("reality", "tls")
        tls_obj: Dict[str, Any] = {
            "enabled": is_tls,
        }

        if is_tls:
            sni = params.get("sni", "").strip()
            # In TLS/Reality, server_name (SNI) must NOT be an IP address
            if sni and not (sni.replace(".", "").isdigit() or ":" in sni):
                tls_obj["server_name"] = sni

            tls_obj["utls"] = {
                "enabled": True,
                "fingerprint": params["fingerprint"] or "chrome",
            }

            if params["security"] == "reality":
                tls_obj["reality"] = {
                    "enabled": True,
                    "public_key": params["pbk"],
                    "short_id": params["sid"],
                }

        transport_obj: Optional[Dict[str, Any]] = None
        if params["type"] == "ws":
            ws_headers = {}
            if params.get("sni"):
                ws_headers["Host"] = params["sni"]
            transport_obj = {
                "type": "ws",
                "path": params["path"],
                "headers": ws_headers,
            }
        elif params["type"] == "grpc":
            transport_obj = {
                "type": "grpc",
                "service_name": params["serviceName"],
            }

        outbound: Dict[str, Any] = {
            "type": "vless",
            "tag": "vless-out",
            "server": params["server"],
            "server_port": params["port"],
            "uuid": params["uuid"],
        }
        if is_tls:
            outbound["tls"] = tls_obj

        flow = params.get("flow", "").strip()
        if flow:
            outbound["flow"] = flow

        if transport_obj:
            outbound["transport"] = transport_obj

        config = {
            "log": {"level": "warn"},
            "dns": {
                "servers": [
                    {"type": "https", "tag": "remote-dns", "server": "1.1.1.1", "detour": "vless-out"}
                ]
            },
            "inbounds": [
                {
                    "type": "mixed",
                    "tag": "mixed-in",
                    "listen": "127.0.0.1",
                    "listen_port": http_port,
                }
            ],
            "outbounds": [
                outbound,
                {"type": "direct", "tag": "direct"},
            ],
        }
        return config

    def is_running(self) -> bool:
        with self._lock:
            return self._is_ready()

    def _is_ready(self) -> bool:
        proc = self._process
        return (self._status == "running" and proc is not None
                and self._owns_listeners(proc, self._ports))

    def check_port_listening(self, port: int, timeout: float = 0.5) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def _owned_listener_ports(self, pid: int, ports: Tuple[int, ...]) -> set[int]:
        """Check OS socket ownership, not process names or an open port alone."""
        addresses = {f"127.0.0.1:{port}": port for port in ports}
        try:
            if sys.platform == "win32":
                return _windows_listener_ports(pid, ports)
            if sys.platform.startswith("linux"):
                proc_dir = Path("/proc") / str(pid)
                sockets = set()
                for fd in (proc_dir / "fd").iterdir():
                    try:
                        sockets.add(os.readlink(fd))
                    except FileNotFoundError:
                        continue
                address_hex = int.from_bytes(socket.inet_aton("127.0.0.1"), sys.byteorder)
                keys = {f"{address_hex:08X}:{port:04X}": port for port in ports}
                wildcard = {f"00000000:{port:04X}": port for port in ports}
                rows = (proc_dir / "net/tcp").read_text().splitlines()[1:]
                owned, competing = set(), set()
                for row in map(str.split, rows):
                    if len(row) < 10 or row[3] != "0A":
                        continue
                    if row[1] in keys:
                        if f"socket:[{row[9]}]" in sockets:
                            owned.add(keys[row[1]])
                        else:
                            competing.add(keys[row[1]])
                    elif row[1] in wildcard:
                        competing.add(wildcard[row[1]])
                return owned - competing
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-i4TCP", "-sTCP:LISTEN", "-Fn"],
                    capture_output=True, text=True, errors="replace", timeout=2, check=True,
                )
                return {addresses[line[1:]] for line in result.stdout.splitlines()
                        if line.startswith("n") and line[1:] in addresses}
        except (OSError, subprocess.SubprocessError):
            pass
        return set()

    def _owns_listeners(self, proc: subprocess.Popen, ports: Tuple[int, ...]) -> bool:
        return (bool(ports) and proc.poll() is None
                and self._owned_listener_ports(proc.pid, ports) == set(ports)
                and all(self.check_port_listening(port) for port in ports)
                and proc.poll() is None)

    def _clear_child(self) -> None:
        if self._status == "running":
            self._exit_generation += 1
        self._process = None
        self._ports = ()
        self._status = "stopped"
        if self._runtime is not None:
            shutil.rmtree(self._runtime, ignore_errors=True)
            self._runtime = None

    def _stop_child(self) -> bool:
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                if proc.poll() is None:
                    return False
        self._clear_child()
        return True

    def start_tunnel(
        self,
        vless_url: str,
        http_port: Optional[int] = None,
        socks_port: Optional[int] = None,
        custom_core_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        cfg_http, cfg_socks = get_configured_ports()
        http_port = http_port or cfg_http
        socks_port = socks_port or cfg_socks

        with self._lock:
            if self._process and self._process.poll() is None:
                if self._is_ready():
                    return True, "Туннель уже запущен."
                return False, "Ядро уже запускается или не готово. При необходимости остановите его."
            self._clear_child()
            try:
                params = VlessParser.parse_url(vless_url)
            except ValueError as e:
                return False, f"Ошибка в URL VLESS: {e}"

            core_exe = self.find_core_executable(custom_core_path)
            if not core_exe:
                return False, ("Не найдено проверенное ядро Xray/sing-box. Установите его и выберите заново "
                               "или укажите путь к ядру, которое вы проверили самостоятельно.")
            is_xray = "xray" in core_exe.name.lower()
            ports = (http_port, socks_port) if is_xray else (http_port,)
            if (any(type(port) is not int or not 1024 <= port <= 65535 for port in ports)
                    or len(set(ports)) != len(ports)):
                return False, "Недопустимые или совпадающие локальные порты VLESS."
            if any(self.check_port_listening(port) for port in ports):
                return False, (
                    f"Локальный порт VLESS занят ({'/'.join(map(str, ports))}). "
                    f"Остановите другую программу самостоятельно или измените "
                    f"vless_http_port/vless_socks_port в {CONFIG_DIR / 'antigravity.json'}."
                )
            generate = self.generate_xray_config if is_xray else self.generate_sing_box_config
            config_data = generate(params, http_port, socks_port)
            try:
                self._runtime = Path(tempfile.mkdtemp(prefix="run-", dir=VLESS_RUNTIME_DIR.absolute()))
                config_file = self._runtime / "config.json"
                config_file.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8")
                log_file = self._runtime / "core.log"
                with log_file.open("xb") as log:
                    proc = subprocess.Popen(
                        [str(core_exe), "run", "-c", str(config_file)],
                        cwd=str(self._runtime),
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                self._process = proc
                self._ports = ports
                self._status = "starting"
            except (OSError, ValueError) as e:
                self._clear_child()
                return False, f"Не удалось запустить процесс ядра: {e}"

        deadline = time.monotonic() + _START_TIMEOUT
        while True:
            with self._lock:
                if self._process is not proc:
                    return False, "Запуск туннеля отменён."
                rc = proc.poll()
                if rc is not None:
                    details = ""
                    try:
                        with log_file.open("rb") as log:
                            log.seek(max(0, log_file.stat().st_size - 4096))
                            lines = log.read(4096).decode("utf-8", errors="replace").strip().splitlines()
                        details = "\n".join(lines[-4:])
                    except OSError:
                        pass
                    self._clear_child()
                    return False, f"Процесс ядра завершился с кодом {rc}. {details}"
                if self._owns_listeners(proc, ports):
                    self._status = "running"
                    self._exit_generation += 1
                    return True, f"VLESS туннель запущен на 127.0.0.1:{http_port}"
                if time.monotonic() >= deadline:
                    stopped = self._stop_child()
                    message = f"Ядро не открыло ожидаемые порты VLESS за отведённое время ({ports})."
                    return False, message if stopped else message + " Не удалось остановить процесс ядра."
            time.sleep(0.1)

    def stop_tunnel(self) -> Tuple[bool, str]:
        with self._lock:
            if not self._stop_child():
                return False, "Не удалось остановить процесс ядра VLESS."

        return True, "VLESS туннель остановлен."

    def test_connection(self, http_port: Optional[int] = None, timeout: int = 8) -> Dict[str, Any]:
        """Tests the proxy connection by fetching IP and country through the tunnel."""
        with self._lock:
            proc = self._process
            if http_port is None:
                http_port = self._ports[0] if self._ports else get_http_port()
            ready = self._is_ready() and http_port == self._ports[0]
        if not ready:
            return {
                "ok": False,
                "message": f"Локальный порт {http_port} недоступен. Запустите туннель перед проверкой.",
                "latency_ms": None,
                "ip": None,
                "country": None,
            }

        proxy_url = f"http://127.0.0.1:{http_port}"
        proxy_handler = _TunnelProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler, _TunnelRedirectHandler())

        start = time.time()

        def lookup_country(ip_address):
            """Resolve a 2-letter country code when the IP service did not provide one."""
            if not ip_address:
                return ""
            for template in ("https://ipwho.is/{ip}?fields=country_code",
                             "https://ipapi.co/{ip}/country_code/"):
                try:
                    geo_req = urllib.request.Request(
                        template.format(ip=ip_address),
                        headers={"User-Agent": "AntigravityHub/1.0"},
                    )
                    with opener.open(geo_req, timeout=min(timeout, 6)) as geo_resp:
                        payload = geo_resp.read().decode("utf-8", errors="ignore").strip()
                    try:
                        parsed = json.loads(payload)
                        code = parsed.get("country_code") or parsed.get("country")
                    except Exception:
                        code = payload
                    code = str(code or "").strip().upper()
                    if len(code) == 2 and code.isalpha():
                        return code
                except Exception:
                    continue
            return ""

        # Cloudflare trace first: it returns BOTH the exit IP and its country
        # code (loc=...). ipify only returns the IP, so it is a fallback.
        endpoints = [
            ("https://cloudflare.com/cdn-cgi/trace", "cf"),
            ("https://api.ipify.org?format=json", "ipify"),
        ]

        for url, service_type in endpoints:
            attempt_start = time.time()
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "AntigravityHub/1.0"}
                )
                with opener.open(req, timeout=timeout) as resp:
                    data = resp.read().decode("utf-8", errors="ignore")
                    elapsed = int((time.time() - attempt_start) * 1000)

                    ip = ""
                    country = ""
                    if service_type == "ipify":
                        try:
                            j = json.loads(data)
                            ip = j.get("ip", "")
                        except Exception:
                            pass
                    elif service_type == "cf":
                        for line in data.splitlines():
                            if line.startswith("ip="):
                                ip = line.split("=", 1)[1]
                            elif line.startswith("loc="):
                                country = line.split("=", 1)[1]
                    ip = str(ipaddress.ip_address(ip))
                    if len(country) != 2 or not country.isascii() or not country.isalpha():
                        country = lookup_country(ip)
                    else:
                        country = country.upper()

                    result = {
                        "ok": True,
                        "message": f"Туннель активен! IP: {ip}" + (f" ({country})" if country else ""),
                        "latency_ms": elapsed,
                        "ip": ip,
                        "country": country,
                    }
                    with self._lock:
                        if self._process is not proc or not self._is_ready():
                            break
                        self._last_test_result = result
                    return result
            except Exception:
                continue

        elapsed = int((time.time() - start) * 1000)
        return {
            "ok": False,
            "message": f"Ошибка соединения через туннель (таймаут или сервер недоступен, {elapsed}ms)",
            "latency_ms": elapsed,
            "ip": None,
            "country": None,
        }


# Global singleton instance
vless_service = VlessManager()
