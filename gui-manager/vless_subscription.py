"""
VLESS Subscription Manager with AI Geographic Filtering.
Fetches, parses, filters, and benchmarks VLESS nodes from subscriptions
(e.g. igareck/vpn-configs-for-russia) for use with AI services (OpenAI, Claude, Gemini, etc.).
"""

import os
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

try:
    import hub_paths
    CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
    VLESS_RUNTIME_DIR = hub_paths.VLESS_RUNTIME_DIR
except Exception:
    CONFIG_DIR = Path.home() / ".config" / "opencode"
    VLESS_RUNTIME_DIR = CONFIG_DIR / "vless"

VLESS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = VLESS_RUNTIME_DIR / "subscription_cache.txt"

# Default subscription URLs from igareck/vpn-configs-for-russia
DEFAULT_SUBSCRIPTION_URL = "https://raw.githack.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt"
SUBSCRIPTION_MIRRORS = [
    "https://raw.githack.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://gitlab.com/igareck/vpn-configs-for-russia/-/raw/main/BLACK_VLESS_RUS.txt",
    "https://raw.githack.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
]

# Countries strictly blocked or restricted by OpenAI, Claude, Google AI
AI_BLOCKED_COUNTRIES: Set[str] = {
    "RU",  # Russia
    "IR",  # Iran
    "CN",  # China
    "HK",  # Hong Kong (OpenAI / Claude not supported)
    "BY",  # Belarus
    "KP",  # North Korea
    "CU",  # Cuba
    "SY",  # Syria
}

# Standard known country meta: code -> (display name, flag, is_ai_allowed)
COUNTRY_META: Dict[str, Tuple[str, str, bool]] = {
    "US": ("США (United States)", "🇺🇸", True),
    "DE": ("Германия (Germany)", "🇩🇪", True),
    "NL": ("Нидерланды (Netherlands)", "🇳🇱", True),
    "FR": ("Франция (France)", "🇫🇷", True),
    "PL": ("Польша (Poland)", "🇵🇱", True),
    "LT": ("Литва (Lithuania)", "🇱🇹", True),
    "JP": ("Япония (Japan)", "🇯🇵", True),
    "SG": ("Сингапур (Singapore)", "🇸🇬", True),
    "GB": ("Великобритания (UK)", "🇬🇧", True),
    "CA": ("Канада (Canada)", "🇨🇦", True),
    "SE": ("Швеция (Sweden)", "🇸🇪", True),
    "CH": ("Швейцария (Switzerland)", "🇨🇭", True),
    "IT": ("Италия (Italy)", "🇮🇹", True),
    "ES": ("Испания (Spain)", "🇪🇸", True),
    "FI": ("Финляндия (Finland)", "🇫🇮", True),
    "AT": ("Австрия (Austria)", "🇦🇹", True),
    "BG": ("Болгария (Bulgaria)", "🇧🇬", True),
    "IL": ("Израиль (Israel)", "🇮🇱", True),
    "TR": ("Турция (Turkey)", "🇹🇷", True),
    "IN": ("Индия (India)", "🇮🇳", True),
    "KR": ("Южная Корея (South Korea)", "🇰🇷", True),
    "AU": ("Австралия (Australia)", "🇦🇺", True),
    "BR": ("Бразилия (Brazil)", "🇧🇷", True),
    "RU": ("Россия (заблокировано в ИИ)", "🇷🇺", False),
    "IR": ("Иран (заблокировано в ИИ)", "🇮🇷", False),
    "HK": ("Гонконг (заблокировано в ИИ)", "🇭🇰", False),
    "CN": ("Китай (заблокировано в ИИ)", "🇨🇳", False),
}

# Name matching for countries in tags
COUNTRY_KEYWORDS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(United States|USA|America)\b", re.IGNORECASE), "US"),
    (re.compile(r"\b(Germany|Deutschland)\b", re.IGNORECASE), "DE"),
    (re.compile(r"\b(Netherlands|Holland|Amsterdam)\b", re.IGNORECASE), "NL"),
    (re.compile(r"\b(France|Paris)\b", re.IGNORECASE), "FR"),
    (re.compile(r"\b(Poland|Warsaw)\b", re.IGNORECASE), "PL"),
    (re.compile(r"\b(Lithuania|Vilnius)\b", re.IGNORECASE), "LT"),
    (re.compile(r"\b(Japan|Tokyo|Osaka)\b", re.IGNORECASE), "JP"),
    (re.compile(r"\b(Singapore)\b", re.IGNORECASE), "SG"),
    (re.compile(r"\b(United Kingdom|Britain|London|UK)\b", re.IGNORECASE), "GB"),
    (re.compile(r"\b(Canada|Toronto|Montreal)\b", re.IGNORECASE), "CA"),
    (re.compile(r"\b(Sweden|Stockholm)\b", re.IGNORECASE), "SE"),
    (re.compile(r"\b(Switzerland|Zurich)\b", re.IGNORECASE), "CH"),
    (re.compile(r"\b(Italy|Rome|Milan)\b", re.IGNORECASE), "IT"),
    (re.compile(r"\b(Spain|Madrid)\b", re.IGNORECASE), "ES"),
    (re.compile(r"\b(Finland|Helsinki)\b", re.IGNORECASE), "FI"),
    (re.compile(r"\b(Austria|Vienna)\b", re.IGNORECASE), "AT"),
    (re.compile(r"\b(Bulgaria|Sofia)\b", re.IGNORECASE), "BG"),
    (re.compile(r"\b(Israel|Tel Aviv)\b", re.IGNORECASE), "IL"),
    (re.compile(r"\b(Turkey|Istanbul)\b", re.IGNORECASE), "TR"),
    (re.compile(r"\b(India|Mumbai|Delhi)\b", re.IGNORECASE), "IN"),
    (re.compile(r"\b(Korea|Seoul)\b", re.IGNORECASE), "KR"),
    (re.compile(r"\b(Australia|Sydney)\b", re.IGNORECASE), "AU"),
    (re.compile(r"\b(Brazil|Sao Paulo)\b", re.IGNORECASE), "BR"),
    (re.compile(r"\b(Russia|Moscow|Saint Petersburg)\b", re.IGNORECASE), "RU"),
    (re.compile(r"\b(Iran|Tehran)\b", re.IGNORECASE), "IR"),
    (re.compile(r"\b(Hong Kong)\b", re.IGNORECASE), "HK"),
    (re.compile(r"\b(China|Beijing|Shanghai|Shenzhen)\b", re.IGNORECASE), "CN"),
]


def _country_from_flag_emoji(text: str) -> Optional[str]:
    """Extracts 2-letter country code from Regional Indicator Symbols (e.g. 🇺🇸 -> US)."""
    for i in range(len(text) - 1):
        c1, c2 = ord(text[i]), ord(text[i + 1])
        if 0x1F1E6 <= c1 <= 0x1F1FF and 0x1F1E6 <= c2 <= 0x1F1FF:
            char1 = chr(c1 - 0x1F1E6 + ord("A"))
            char2 = chr(c2 - 0x1F1E6 + ord("A"))
            return f"{char1}{char2}"
    return None


def detect_country(tag: str, server: str = "") -> Tuple[str, str, str, bool]:
    """
    Returns (code, display_name, flag, is_ai_allowed).
    Falls back to 'OTHER' if no country could be detected.
    """
    decoded = urllib.parse.unquote(tag)

    # 1. Check flag emoji
    code = _country_from_flag_emoji(decoded)
    if code:
        meta = COUNTRY_META.get(code)
        if meta:
            return code, meta[0], meta[1], meta[2]
        is_allowed = code not in AI_BLOCKED_COUNTRIES
        return code, f"Страна {code}", "", is_allowed

    # 2. Check keywords in tag
    for pattern, matched_code in COUNTRY_KEYWORDS:
        if pattern.search(decoded):
            meta = COUNTRY_META.get(matched_code)
            if meta:
                return matched_code, meta[0], meta[1], meta[2]
            return matched_code, f"Страна {matched_code}", "", matched_code not in AI_BLOCKED_COUNTRIES

    # 3. Check TLD in server domain
    if "." in server:
        tld = server.rsplit(".", 1)[-1].upper()
        if len(tld) == 2 and tld in COUNTRY_META:
            meta = COUNTRY_META[tld]
            return tld, meta[0], meta[1], meta[2]

    return "OTHER", "Другое (Other)", "🌐", True


@dataclass
class VlessNode:
    url: str
    server: str
    port: int
    tag: str
    country_code: str
    country_name: str
    flag: str
    is_ai_allowed: bool
    ping_ms: Optional[int] = None

    @property
    def display_label(self) -> str:
        ping_str = f" [{self.ping_ms}ms]" if self.ping_ms is not None else ""
        flag_str = f"{self.flag} " if self.flag else ""
        return f"{flag_str}{self.country_name}{ping_str} — {self.tag[:45]}"


def parse_vless_subscription(text: str) -> List[VlessNode]:
    """Parses raw text containing vless:// links into structured VlessNode objects."""
    nodes: List[VlessNode] = []
    seen_urls: Set[str] = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("vless://"):
            continue
        if line in seen_urls:
            continue
        seen_urls.add(line)

        try:
            parsed = urllib.parse.urlparse(line)
            netloc = parsed.netloc
            if "@" not in netloc:
                continue
            host_port = netloc.split("@")[1].split(":")
            server = host_port[0]
            port = int(host_port[1])
            tag = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"{server}:{port}"

            country_code, country_name, flag, is_ai_allowed = detect_country(tag, server)

            nodes.append(
                VlessNode(
                    url=line,
                    server=server,
                    port=port,
                    tag=tag,
                    country_code=country_code,
                    country_name=country_name,
                    flag=flag,
                    is_ai_allowed=is_ai_allowed,
                )
            )
        except Exception:
            continue

    return nodes


def fetch_subscription(
    url: str = DEFAULT_SUBSCRIPTION_URL,
    mirrors: Optional[List[str]] = None,
    timeout: float = 12.0,
    force_refresh: bool = False,
) -> Tuple[List[VlessNode], str]:
    """
    Downloads and parses the subscription list.
    Tries primary URL, then mirrors, falls back to local cache if offline.
    """
    if mirrors is None:
        mirrors = SUBSCRIPTION_MIRRORS

    candidates = [url] + [m for m in mirrors if m != url]

    # Try downloading from candidates
    last_err = ""
    for target in candidates:
        try:
            req = urllib.request.Request(
                target,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityHub/1.0"},
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                resp = opener.open(req, timeout=timeout)
            except Exception as e:
                if "cert" in str(e).lower() or "ssl" in str(e).lower():
                    ctx = ssl._create_unverified_context()
                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({}),
                        urllib.request.HTTPSHandler(context=ctx),
                    )
                    resp = opener.open(req, timeout=timeout)
                else:
                    raise

            with resp:
                raw_text = resp.read().decode("utf-8", errors="ignore")

            nodes = parse_vless_subscription(raw_text)
            if nodes:
                try:
                    CACHE_FILE.write_text(raw_text, encoding="utf-8")
                except Exception:
                    pass
                return nodes, f"Успешно загружено {len(nodes)} серверов"
        except Exception as e:
            last_err = str(e)
            continue

    # Fallback to local cache if present
    if CACHE_FILE.exists():
        try:
            cached_text = CACHE_FILE.read_text(encoding="utf-8", errors="ignore")
            nodes = parse_vless_subscription(cached_text)
            if nodes:
                return nodes, f"Загружено из локального кэша ({len(nodes)} серверов). Сеть недоступна."
        except Exception:
            pass

    return [], f"Не удалось загрузить подписку: {last_err or 'все зеркала недоступны'}"


def filter_nodes_by_country(nodes: List[VlessNode], filter_mode: str) -> List[VlessNode]:
    """
    filter_mode can be:
      - 'ai_allowed' (default): only nodes strictly permitted for AI models (no RU, IR, CN, HK)
      - 'US', 'DE', 'NL', etc.: specific country code
      - 'all': everything
    """
    if filter_mode == "ai_allowed":
        return [n for n in nodes if n.is_ai_allowed]
    if filter_mode == "all":
        return list(nodes)
    return [n for n in nodes if n.country_code.upper() == filter_mode.upper()]


def tcp_ping_node(node: VlessNode, timeout: float = 2.0) -> Optional[int]:
    """Measures TCP handshake latency to server:port."""
    start = time.time()
    try:
        with socket.create_connection((node.server, node.port), timeout=timeout):
            elapsed = int((time.time() - start) * 1000)
            node.ping_ms = elapsed
            return elapsed
    except Exception:
        node.ping_ms = None
        return None


def benchmark_and_pick_best(
    nodes: List[VlessNode],
    country_filter: str = "ai_allowed",
    max_check: int = 15,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Optional[VlessNode]:
    """
    Filters nodes and checks TCP latency for the top candidates,
    returning the one with the lowest ping.
    """
    filtered = filter_nodes_by_country(nodes, country_filter)
    if not filtered:
        return None

    candidates = filtered[:max_check]
    best_node: Optional[VlessNode] = None
    best_ping = 999999

    for idx, node in enumerate(candidates, 1):
        if progress_callback:
            progress_callback(f"Проверка {idx}/{len(candidates)}: {node.flag} {node.country_code} ({node.server})...")

        ping = tcp_ping_node(node, timeout=1.8)
        if ping is not None and ping < best_ping:
            best_ping = ping
            best_node = node

    return best_node
