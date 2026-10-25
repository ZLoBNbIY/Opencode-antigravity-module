"""
VLESS Tunnel Manager for Antigravity Hub.
Supports parsing vless:// URLs, configuring and running Xray-core or sing-box,
and routing traffic from OpenCode and Antigravity Hub.
"""

import os
import sys
import json
import time
import socket
import urllib.parse
import urllib.request
import subprocess
import threading
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

CONFIG_DIR = Path.home() / ".config" / "opencode"
VLESS_RUNTIME_DIR = CONFIG_DIR / "vless"
VLESS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_HTTP_PORT = 10809
DEFAULT_SOCKS_PORT = 10808

SING_BOX_DOWNLOAD_URL = "https://github.com/SagerNet/sing-box/releases/download/v1.10.7/sing-box-1.10.7-windows-amd64.zip"
XRAY_DOWNLOAD_URL = "https://github.com/XTLS/Xray-core/releases/download/v24.11.30/Xray-windows-64.zip"


class VlessParser:
    """Parses vless:// URI strings into structured configuration."""

    @staticmethod
    def parse_url(url_str: str) -> Dict[str, Any]:
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
        self._lock = threading.Lock()
        self._status = "stopped"
        self._last_test_result: Optional[Dict[str, Any]] = None

    def get_bin_dir(self) -> Path:
        local_bin = Path(__file__).resolve().parent / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        return local_bin

    def find_core_executable(self, custom_path: Optional[str] = None) -> Optional[Path]:
        if custom_path and os.path.exists(custom_path) and os.path.isfile(custom_path):
            return Path(custom_path)

        # Check local module bin
        bin_dir = self.get_bin_dir()
        for name in ("xray.exe", "sing-box.exe", "xray", "sing-box"):
            cand = bin_dir / name
            if cand.exists():
                return cand

        # Check user config bin
        user_bin = CONFIG_DIR / "bin"
        for name in ("xray.exe", "sing-box.exe", "xray", "sing-box"):
            cand = user_bin / name
            if cand.exists():
                return cand

        # Check system PATH
        for cmd in ("xray", "sing-box", "xray.exe", "sing-box.exe"):
            found = shutil.which(cmd)
            if found:
                return Path(found)

        return None

    def is_core_available(self, custom_path: Optional[str] = None) -> bool:
        return self.find_core_executable(custom_path) is not None

    def download_core(self, core_type: str = "sing-box", progress_callback=None) -> Tuple[bool, str]:
        """Downloads sing-box or xray-core into bin folder."""
        bin_dir = self.get_bin_dir()
        url = SING_BOX_DOWNLOAD_URL if core_type == "sing-box" else XRAY_DOWNLOAD_URL
        archive_path = bin_dir / "core_archive.zip"

        try:
            if progress_callback:
                progress_callback(f"Загрузка {core_type} из GitHub...")

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AntigravityHub-VlessManager/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp, open(archive_path, "wb") as f:
                total_size = resp.length or 0
                downloaded = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        pct = int((downloaded / total_size) * 100)
                        progress_callback(f"Загрузка {core_type}: {pct}%")

            if progress_callback:
                progress_callback("Распаковка архива...")

            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.namelist():
                    basename = os.path.basename(member)
                    if basename in ("sing-box.exe", "xray.exe"):
                        with zf.open(member) as source:
                            target_file = bin_dir / basename
                            with open(target_file, "wb") as out_f:
                                shutil.copyfileobj(source, out_f)

            # Cleanup zip archive safely on Windows
            import gc
            gc.collect()
            time.sleep(0.2)
            try:
                if archive_path.exists():
                    archive_path.unlink()
            except Exception:
                pass

            found = self.find_core_executable()
            if found:
                return True, f"Ядро успешно установлено: {found.name}"
            return False, "Не удалось обнаружить исполняемый файл в скачанном архиве."
        except Exception as e:
            if archive_path.exists():
                try:
                    archive_path.unlink()
                except Exception:
                    pass
            return False, f"Ошибка загрузки ядра: {e}"

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
                "spiderX": "",
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
        # For TCP Reality, xtls-rprx-vision is the universal standard
        if params["security"] == "reality" and not flow and params["type"] == "tcp":
            flow = "xtls-rprx-vision"
        if flow:
            outbound["flow"] = flow

        if transport_obj:
            outbound["transport"] = transport_obj

        config = {
            "log": {"level": "warn"},
            "dns": {
                "servers": [
                    {"tag": "remote-dns", "address": "https://1.1.1.1/dns-query", "detour": "vless-out"}
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
            # If port 10809 is actively listening, tunnel is definitely up!
            if self.check_port_listening(DEFAULT_HTTP_PORT):
                self._status = "running"
                return True
            if self._process is None:
                return False
            poll = self._process.poll()
            if poll is not None:
                self._process = None
                self._status = "stopped"
                return False
            return True

    def check_port_listening(self, port: int, timeout: float = 0.5) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def start_tunnel(
        self,
        vless_url: str,
        http_port: int = DEFAULT_HTTP_PORT,
        socks_port: int = DEFAULT_SOCKS_PORT,
        custom_core_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        with self._lock:
            if self._process and self._process.poll() is None:
                return True, "Туннель уже запущен."

            core_exe = self.find_core_executable(custom_core_path)
            if not core_exe:
                return False, "Исполняемый файл Xray/sing-box не найден. Скачайте его или укажите путь."

            try:
                params = VlessParser.parse_url(vless_url)
            except Exception as e:
                return False, f"Ошибка в URL VLESS: {e}"

            is_xray = "xray" in core_exe.name.lower()
            config_file = VLESS_RUNTIME_DIR / "config.json"

            if is_xray:
                config_data = self.generate_xray_config(params, http_port, socks_port)
                cmd = [str(core_exe), "run", "-c", str(config_file)]
            else:
                config_data = self.generate_sing_box_config(params, http_port, socks_port)
                cmd = [str(core_exe), "run", "-c", str(config_file)]

            try:
                config_file.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                return False, f"Не удалось записать конфигурацию: {e}"

            # Run process without visible window on Windows
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            # If port is already occupied by a previously detached core, stop it first
            if self.check_port_listening(http_port):
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/f", "/im", "sing-box.exe"], capture_output=True, creationflags=0x08000000)
                    subprocess.run(["taskkill", "/f", "/im", "xray.exe"], capture_output=True, creationflags=0x08000000)
                    time.sleep(0.3)

            # Log core output to file for diagnosis
            log_file = VLESS_RUNTIME_DIR / "core.log"
            try:
                log_fh = open(log_file, "w", encoding="utf-8")
            except Exception:
                log_fh = subprocess.DEVNULL

            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(VLESS_RUNTIME_DIR),
                    creationflags=creation_flags,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                )
            except Exception as e:
                return False, f"Не удалось запустить процесс ядра: {e}"

        # Wait for port to become active
        for _ in range(35):
            time.sleep(0.1)
            if self.check_port_listening(http_port):
                self._status = "running"
                return True, f"VLESS туннель успешно запущен на 127.0.0.1:{http_port}"

        # Check if process died
        if self._process and self._process.poll() is not None:
            err_details = ""
            log_file = VLESS_RUNTIME_DIR / "core.log"
            if log_file.exists():
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    if lines:
                        err_details = "\n" + "\n".join(lines[-4:])
                except Exception:
                    pass
            return False, f"Процесс ядра завершился с кодом ошибки {self._process.returncode}.{err_details}"

        self._status = "running"
        return True, f"VLESS процесс запущен (порт {http_port})."

    def stop_tunnel(self) -> Tuple[bool, str]:
        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait(timeout=1)
                except Exception:
                    pass
                finally:
                    self._process = None

            if sys.platform == "win32":
                subprocess.run(["taskkill", "/f", "/im", "sing-box.exe"], capture_output=True, creationflags=0x08000000)
                subprocess.run(["taskkill", "/f", "/im", "xray.exe"], capture_output=True, creationflags=0x08000000)

            self._status = "stopped"

        return True, "VLESS туннель остановлен."

    def test_connection(self, http_port: int = DEFAULT_HTTP_PORT, timeout: int = 8) -> Dict[str, Any]:
        """Tests the proxy connection by fetching IP and country through the tunnel."""
        if not self.check_port_listening(http_port):
            return {
                "ok": False,
                "message": f"Локальный порт {http_port} недоступен. Запустите туннель перед проверкой.",
                "latency_ms": None,
                "ip": None,
                "country": None,
            }

        proxy_url = f"http://127.0.0.1:{http_port}"
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)

        start = time.time()
        # Test trace or geo
        endpoints = [
            ("https://api.ipify.org?format=json", "ipify"),
            ("https://cloudflare.com/cdn-cgi/trace", "cf"),
        ]

        for url, service_type in endpoints:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "AntigravityHub/1.0"}
                )
                with opener.open(req, timeout=timeout) as resp:
                    data = resp.read().decode("utf-8", errors="ignore")
                    elapsed = int((time.time() - start) * 1000)

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

                    result = {
                        "ok": True,
                        "message": f"Туннель активен! IP: {ip or 'OK'}" + (f" ({country})" if country else ""),
                        "latency_ms": elapsed,
                        "ip": ip,
                        "country": country,
                    }
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
