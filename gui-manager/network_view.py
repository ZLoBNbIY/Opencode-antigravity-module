"""
Network, DNS & VLESS Tunnel View for Antigravity Hub.
Provides configuration and status for VLESS routing and custom DNS (DoH, DoT, Standard).
"""

import threading
import json
from pathlib import Path
from tkinter import messagebox, filedialog
import tkinter as tk
import customtkinter as ctk

from vless_manager import (
    vless_service,
    VlessParser,
    get_http_port,
    get_socks_port,
    DEFAULT_HTTP_PORT,
    DEFAULT_SOCKS_PORT,
    LOCAL_DNS_PROXY_PORT,
)
try:
    import dns_tester
except ImportError:
    from . import dns_tester

try:
    from proxy_config import PROVIDER_ROUTE_MODES, sync_provider_routes
except ImportError:
    from .proxy_config import PROVIDER_ROUTE_MODES, sync_provider_routes


PROVIDER_ROUTE_LABELS = {
    "default": "Общие настройки",
    "vless": "VLESS",
    "proxy": "Внешний прокси",
    "dns": "DNS-прокси Hub",
    "direct": "Напрямую",
    "google-smart": "Google SmartDNS (встроенный)",
}
PROVIDER_ROUTE_BY_LABEL = {label: mode for mode, label in PROVIDER_ROUTE_LABELS.items()}


def create_cyber_switch(master, text="", variable=None, command=None, font=None, **kwargs):
    return ctk.CTkSwitch(
        master,
        text=text,
        variable=variable,
        command=command,
        font=font,
        width=44,
        height=22,
        switch_width=36,
        switch_height=18,
        corner_radius=9,
        border_width=1,
        fg_color=("#d0d7de", "#21262d"),
        progress_color=("#1f883d", "#238636"),
        button_color=("#ffffff", "#ffffff"),
        button_hover_color=("#f6f8fa", "#f0f6fc"),
        border_color=("#afb8c1", "#30363d"),
        **kwargs
    )


class NetworkView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.grid_columnconfigure(0, weight=1)

        # Header Title
        ctk.CTkLabel(
            self,
            text="🌐 Сеть, DNS и VLESS-маршрутизация",
            font=app.font(20, "bold"),
            anchor="w",
            text_color=colors["text_primary"]
        ).pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            self,
            text="Управление сетевыми туннелями VLESS (обход геоблокировок) и защищёнными DNS-серверами (DoH / DoT / SmartDNS) для OpenCode.",
            font=app.font(12),
            anchor="w",
            text_color=colors["text_secondary"]
        ).pack(fill="x", pady=(0, 10))

        # Disclaimer Banner: VLESS vs DNS priority
        notice_banner = ctk.CTkFrame(self, fg_color=("#fffbeb", "#141d2e"), corner_radius=10, border_width=1, border_color="#f59e0b")
        notice_banner.pack(fill="x", pady=(0, 12))

        nb_header = ctk.CTkFrame(notice_banner, fg_color="transparent")
        nb_header.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            nb_header,
            text="⚠️ Важное примечание о приоритете VLESS и DNS",
            font=app.font(12, "bold"),
            text_color="#f59e0b"
        ).pack(side="left")

        ctk.CTkLabel(
            notice_banner,
            text="Маршрут задаётся отдельно для каждого провайдера ниже. Для провайдера на VLESS домен разрешает удалённый туннель; для DNS-прокси Hub используется выбранный DNS-сервер.",
            font=app.font(11),
            text_color=("#78350f", "#f1f5f9"),
            justify="left",
            wraplength=980,
            anchor="w"
        ).pack(fill="x", padx=14, pady=(0, 10))

        # =====================================================================
        # CARD 1: VLESS TUNNEL
        # =====================================================================
        vless_card = ctk.CTkFrame(self, fg_color=colors["card_bg"], corner_radius=12, border_width=1, border_color=colors["border"])
        vless_card.pack(fill="x", pady=6)

        vless_header_box = ctk.CTkFrame(vless_card, fg_color="transparent")
        vless_header_box.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            vless_header_box,
            text="⚡ Туннелирование VLESS (Reality / Vision / TLS)",
            font=app.font(14, "bold"),
            text_color=colors["text_primary"]
        ).pack(side="left")

        self.vless_badge = ctk.CTkLabel(
            vless_header_box,
            text="● Остановлен",
            font=app.font(11, "bold"),
            text_color="#ef4444",
            fg_color=colors["subbox_bg"],
            corner_radius=8,
            padx=10,
            pady=2
        )
        self.vless_badge.pack(side="right")

        ctk.CTkLabel(
            vless_card,
            text="Подключение через VLESS скрывает ваш реальный IP и обходит географические блокировки Google Gemini, OpenAI, Claude и OpenCode.",
            font=app.font(11),
            text_color=colors["text_secondary"],
            wraplength=980,
            justify="left",
            anchor="w"
        ).pack(fill="x", padx=16, pady=(0, 10))

        # VLESS URL Input
        ctk.CTkLabel(vless_card, text="Строка подключения (vless://):", font=app.font(11, "bold"), text_color=colors["text_primary"]).pack(anchor="w", padx=16, pady=(2, 2))
        self.vless_entry = ctk.CTkEntry(
            vless_card,
            placeholder_text="vless://uuid@host:port?security=reality&sni=...&pbk=...&type=tcp#ServerName",
            font=app.font(11),
            height=34,
            fg_color=colors["subbox_bg"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )
        self.vless_entry.pack(fill="x", padx=16, pady=(0, 8))
        self.vless_entry.insert(0, self.app.config_data.get("vless_url", "") or "")

        # Tunnel controls
        opts_box = ctk.CTkFrame(vless_card, fg_color="transparent")
        opts_box.pack(fill="x", padx=16, pady=(0, 6))

        row1 = ctk.CTkFrame(opts_box, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 6))

        self.vless_enabled_var = tk.BooleanVar(value=self.app.config_data.get("vless_enabled", False))
        create_cyber_switch(
            row1,
            text="Включить VLESS-туннель",
            variable=self.vless_enabled_var,
            command=self.on_vless_switch_toggled,
            font=app.font(12, "bold")
        ).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(
            vless_card,
            text=(
                f"🔌 Локальные порты туннеля: HTTP 127.0.0.1:{get_http_port()}, SOCKS 127.0.0.1:{get_socks_port()}. "
                "Они выбраны нестандартными, чтобы не пересекаться с другими VPN/Xray-клиентами "
                "(значения можно переопределить ключами vless_http_port / vless_socks_port в antigravity.json)."
            ),
            font=app.font(10),
            text_color=colors["text_secondary"],
            justify="left",
            wraplength=980,
            anchor="w"
        ).pack(fill="x", padx=16, pady=(0, 8))

        row2 = ctk.CTkFrame(opts_box, fg_color="transparent")
        row2.pack(fill="x")

        self.vless_kill_switch_var = tk.BooleanVar(value=self.app.config_data.get("vless_kill_switch", True))
        create_cyber_switch(
            row2,
            text="🛡️ Kill Switch (Защита от бана: блокировать OpenCode если VLESS оффлайн)",
            variable=self.vless_kill_switch_var,
            font=app.font(12)
        ).pack(side="left")

        # Core availability and status bar
        core_box = ctk.CTkFrame(vless_card, fg_color=colors["subbox_bg"], corner_radius=8, border_width=1, border_color=colors["border"])
        core_box.pack(fill="x", padx=16, pady=(4, 10))

        self.core_status_lbl = ctk.CTkLabel(
            core_box,
            text="Проверка ядра...",
            font=app.font(11),
            text_color=colors["text_secondary"],
            wraplength=520,
            justify="left",
            anchor="w"
        )
        self.core_status_lbl.pack(side="left", padx=12, pady=8)

        self.btn_download_core = ctk.CTkButton(
            core_box,
            text="⬇ Скачать sing-box (в 1 клик)",
            font=app.font(11, "bold"),
            fg_color=("#0969da", "#1f6feb"),
            hover_color=("#0550ae", "#388bfd"),
            text_color="#ffffff",
            height=28,
            corner_radius=6,
            command=self.download_core_action
        )
        self.btn_download_core.pack(side="right", padx=(4, 12), pady=6)

        self.btn_custom_core = ctk.CTkButton(
            core_box,
            text="📁 Указать exe",
            font=app.font(11),
            fg_color=colors["card_bg"],
            hover_color=("#eaeef2", "#21262d"),
            text_color=colors["text_primary"],
            border_width=1,
            border_color=colors["border"],
            height=28,
            corner_radius=6,
            command=self.select_custom_core_action
        )
        self.btn_custom_core.pack(side="right", padx=(0, 4), pady=6)

        # Action Buttons: Start, Stop, Test
        action_row = ctk.CTkFrame(vless_card, fg_color="transparent")
        action_row.pack(fill="x", padx=16, pady=(0, 12))

        self.btn_vless_start = ctk.CTkButton(
            action_row,
            text="▶ Запустить туннель",
            font=app.font(12, "bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            text_color="#ffffff",
            height=32,
            corner_radius=6,
            command=self.start_vless_action
        )
        self.btn_vless_start.pack(side="left", padx=(0, 8))

        self.btn_vless_stop = ctk.CTkButton(
            action_row,
            text="⏹ Остановить",
            font=app.font(12, "bold"),
            fg_color="#cf222e",
            hover_color="#a40e26",
            text_color="#ffffff",
            height=32,
            corner_radius=6,
            command=self.stop_vless_action
        )
        self.btn_vless_stop.pack(side="left", padx=(0, 8))

        self.btn_vless_test = ctk.CTkButton(
            action_row,
            text="🩺 Проверить подключение и IP",
            font=app.font(12, "bold"),
            fg_color=("#0969da", "#1f6feb"),
            hover_color=("#0550ae", "#388bfd"),
            text_color="#ffffff",
            height=32,
            corner_radius=6,
            command=self.test_vless_action
        )
        self.btn_vless_test.pack(side="left", padx=(0, 8))

        self.vless_test_lbl = ctk.CTkLabel(vless_card, text="", font=app.font(11), text_color="#3fb950", anchor="w")
        self.vless_test_lbl.pack(fill="x", padx=16, pady=(0, 8))

        # =====================================================================
        # CARD 2: CUSTOM DNS & SMARTDNS (FOR USERS WITHOUT VLESS)
        # =====================================================================
        dns_card = ctk.CTkFrame(self, fg_color=colors["card_bg"], corner_radius=12, border_width=1, border_color=colors["border"])
        dns_card.pack(fill="x", pady=6)

        ctk.CTkLabel(
            dns_card,
            text="🌐 Кастомные DNS-серверы (DoH / DoT / SmartDNS)",
            font=app.font(14, "bold"),
            text_color=colors["text_primary"]
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            dns_card,
            text="Альтернатива для тех, у кого нет VLESS-сервера. DNS применяется внутри компонентов Antigravity Hub и OpenCode без изменения системных настроек Windows.",
            font=app.font(11),
            text_color=colors["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # DNS Disclaimer Box
        dns_disclaimer = ctk.CTkFrame(dns_card, fg_color=("#fffbeb", "#141d2e"), corner_radius=8, border_width=1, border_color=("#fde68a", "#2a3749"))
        dns_disclaimer.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            dns_disclaimer,
            text="💡 DNS используется для провайдеров, которым назначен маршрут «DNS-прокси Hub». Для провайдеров на VLESS DNS-разрешение выполняет удалённый туннель.",
            font=app.font(11),
            text_color=("#92400e", "#fbbf24") if self.app.config_data.get("vless_enabled") else colors["text_secondary"],
            justify="left",
            anchor="w",
            wraplength=960
        ).pack(fill="x", padx=12, pady=8)

        # DNS Mode Selector
        mode_row = ctk.CTkFrame(dns_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(mode_row, text="Активный протокол DNS:", font=app.font(12, "bold"), text_color=colors["text_primary"]).pack(side="left", padx=(0, 10))

        dns_mode_labels = {"standard": "Обычный DNS", "dot": "DNS-over-TLS (DoT)", "doh": "DNS-over-HTTPS (DoH)", "system": "Системный DNS"}
        self.dns_mode_var = tk.StringVar(value=dns_mode_labels.get(self.app.config_data.get("dns_mode", "standard"), "Обычный DNS"))
        self.dns_mode_seg = ctk.CTkSegmentedButton(
            mode_row,
            values=["Обычный DNS", "DNS-over-TLS (DoT)", "DNS-over-HTTPS (DoH)", "Системный DNS"],
            variable=self.dns_mode_var,
            font=app.font(11, "bold"),
            selected_color=("#0969da", "#1f6feb"),
            selected_hover_color=("#0550ae", "#388bfd"),
            unselected_color=("#eaeef2", "#21262d"),
            unselected_hover_color=("#d0d7de", "#30363d"),
            corner_radius=6,
            text_color=colors["text_primary"],
        )
        self.dns_mode_seg.pack(side="left")

        # Three DNS Blocks
        dns_blocks_container = ctk.CTkFrame(dns_card, fg_color="transparent")
        dns_blocks_container.pack(fill="x", padx=16, pady=(0, 12))
        dns_blocks_container.grid_columnconfigure(0, weight=1, uniform="dns_col")
        dns_blocks_container.grid_columnconfigure(1, weight=1, uniform="dns_col")
        dns_blocks_container.grid_columnconfigure(2, weight=1, uniform="dns_col")

        # --- BLOCK 1: Standard DNS ---
        b1 = ctk.CTkFrame(dns_blocks_container, fg_color=colors["subbox_bg"], corner_radius=10, border_width=1, border_color=colors["border"])
        b1.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)

        b1_hdr = ctk.CTkFrame(b1, fg_color="transparent")
        b1_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b1_hdr, text="Обычный DNS", font=app.font(12, "bold"), text_color=colors["text_primary"]).pack(side="left")

        ctk.CTkLabel(b1, text="Основной DNS (Primary):", font=app.font(10), text_color=colors["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dns_primary_entry = ctk.CTkEntry(b1, font=app.font(11), height=28, fg_color=colors["card_bg"], border_color=colors["border"], text_color=colors["text_primary"])
        self.dns_primary_entry.pack(fill="x", padx=12, pady=(2, 6))
        current_dns_list = self.app.config_data.get("custom_dns", ["143.20.64.55", "31.58.216.201"])
        self.dns_primary_entry.insert(0, current_dns_list[0] if len(current_dns_list) > 0 else "143.20.64.55")

        ctk.CTkLabel(b1, text="Дополнительный DNS (Secondary):", font=app.font(10), text_color=colors["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dns_secondary_entry = ctk.CTkEntry(b1, font=app.font(11), height=28, fg_color=colors["card_bg"], border_color=colors["border"], text_color=colors["text_primary"])
        self.dns_secondary_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.dns_secondary_entry.insert(0, current_dns_list[1] if len(current_dns_list) > 1 else "31.58.216.201")

        b1_btn_row = ctk.CTkFrame(b1, fg_color="transparent")
        b1_btn_row.pack(fill="x", padx=12, pady=(4, 6))
        self.btn_test_std_dns = ctk.CTkButton(
            b1_btn_row,
            text="🩺 Проверить",
            font=app.font(11, "bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=colors["text_primary"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=6,
            height=28,
            command=self.test_standard_dns_action,
        )
        self.btn_test_std_dns.pack(fill="x")
        self.lbl_test_std_dns = ctk.CTkLabel(b1, text="", font=app.font(10), text_color="#3fb950", wraplength=200, justify="left")
        self.lbl_test_std_dns.pack(anchor="w", padx=12, pady=(0, 6))

        # --- BLOCK 2: DNS-over-TLS (DoT) ---
        b2 = ctk.CTkFrame(dns_blocks_container, fg_color=colors["subbox_bg"], corner_radius=10, border_width=1, border_color=colors["border"])
        b2.grid(row=0, column=1, sticky="nsew", padx=6, pady=4)

        b2_hdr = ctk.CTkFrame(b2, fg_color="transparent")
        b2_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b2_hdr, text="DNS-over-TLS (DoT)", font=app.font(12, "bold"), text_color=colors["text_primary"]).pack(side="left")

        ctk.CTkLabel(b2, text="Имя хоста DoT (порт 853):", font=app.font(10), text_color=colors["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dot_host_entry = ctk.CTkEntry(b2, font=app.font(11), height=28, fg_color=colors["card_bg"], border_color=colors["border"], text_color=colors["text_primary"])
        self.dot_host_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.dot_host_entry.insert(0, self.app.config_data.get("dot_host", "dns.bezmezhau.com"))

        ctk.CTkLabel(b2, text="Защищённый TLS-резолвинг\nбез перехвата провайдером.", font=app.font(10), text_color=colors["text_muted"], justify="left").pack(anchor="w", padx=12, pady=(2, 6))

        b2_btn_row = ctk.CTkFrame(b2, fg_color="transparent")
        b2_btn_row.pack(fill="x", padx=12, pady=(4, 6))
        self.btn_test_dot = ctk.CTkButton(
            b2_btn_row,
            text="🩺 Проверить",
            font=app.font(11, "bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=colors["text_primary"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=6,
            height=28,
            command=self.test_dot_action,
        )
        self.btn_test_dot.pack(fill="x")
        self.lbl_test_dot = ctk.CTkLabel(b2, text="", font=app.font(10), text_color="#3fb950", wraplength=200, justify="left")
        self.lbl_test_dot.pack(anchor="w", padx=12, pady=(0, 6))

        # --- BLOCK 3: DNS-over-HTTPS (DoH) ---
        b3 = ctk.CTkFrame(dns_blocks_container, fg_color=colors["subbox_bg"], corner_radius=10, border_width=1, border_color=colors["border"])
        b3.grid(row=0, column=2, sticky="nsew", padx=(6, 0), pady=4)

        b3_hdr = ctk.CTkFrame(b3, fg_color="transparent")
        b3_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b3_hdr, text="DNS-over-HTTPS (DoH)", font=app.font(12, "bold"), text_color=colors["text_primary"]).pack(side="left")

        ctk.CTkLabel(b3, text="URL эндпоинта DoH:", font=app.font(10), text_color=colors["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.doh_url_entry = ctk.CTkEntry(b3, font=app.font(11), height=28, fg_color=colors["card_bg"], border_color=colors["border"], text_color=colors["text_primary"])
        self.doh_url_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.doh_url_entry.insert(0, self.app.config_data.get("doh_url", "https://dns.bezmezhau.com/dns-query"))

        ctk.CTkLabel(b3, text="Стандарт RFC 8484 по HTTPS.\nМаксимальная скрытность.", font=app.font(10), text_color=colors["text_muted"], justify="left").pack(anchor="w", padx=12, pady=(2, 6))

        b3_btn_row = ctk.CTkFrame(b3, fg_color="transparent")
        b3_btn_row.pack(fill="x", padx=12, pady=(4, 6))
        self.btn_test_doh = ctk.CTkButton(
            b3_btn_row,
            text="🩺 Проверить",
            font=app.font(11, "bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=colors["text_primary"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=6,
            height=28,
            command=self.test_doh_action,
        )
        self.btn_test_doh.pack(fill="x")
        self.lbl_test_doh = ctk.CTkLabel(b3, text="", font=app.font(10), text_color="#3fb950", wraplength=200, justify="left")
        self.lbl_test_doh.pack(anchor="w", padx=12, pady=(0, 6))

        # Proxy Row
        proxy_row = ctk.CTkFrame(dns_card, fg_color="transparent")
        proxy_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(proxy_row, text="Внешний HTTP/SOCKS прокси (необязательно):", font=app.font(11, "bold"), text_color=colors["text_primary"], width=280, anchor="w").pack(side="left")
        self.proxy_entry = ctk.CTkEntry(
            proxy_row,
            placeholder_text="Оставьте пустым для встроенного туннеля OpenCode",
            font=app.font(11),
            height=30,
            fg_color=colors["subbox_bg"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )
        self.proxy_entry.pack(side="left", fill="x", expand=True)
        self.proxy_entry.insert(0, self.app.config_data.get("proxy", "") or "")

        # Per-provider routes. These are written to each provider's OpenCode
        # options, while leaving the Hub-wide defaults available as fallback.
        self.provider_route_vars = {}
        provider_routes_card = ctk.CTkFrame(self, fg_color=colors["card_bg"], corner_radius=12,
                                            border_width=1, border_color=colors["border"])
        provider_routes_card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            provider_routes_card,
            text="🧭 Маршрут для каждого провайдера",
            font=app.font(14, "bold"), text_color=colors["text_primary"]
        ).pack(anchor="w", padx=16, pady=(12, 3))
        ctk.CTkLabel(
            provider_routes_card,
            text="Google SmartDNS встроен в Hub: получает адрес выхода через DoH и переносит TLS без AG Unlocker. Используется для двух Cloud Code-доменов; вход Google следует общим настройкам. «Напрямую» использует системную сеть и DNS.",
            font=app.font(11), text_color=colors["text_secondary"], justify="left", wraplength=980
        ).pack(anchor="w", padx=16, pady=(0, 8))

        opencode_path = Path.home() / ".config" / "opencode" / "opencode.json"
        try:
            opencode_data = json.loads(opencode_path.read_text(encoding="utf-8")) if opencode_path.exists() else {}
        except Exception:
            opencode_data = {}
        provider_names = []
        for section_name in ("provider", "providers"):
            section = opencode_data.get(section_name, {})
            if isinstance(section, dict):
                provider_names.extend(name for name in section if name not in provider_names)
        saved_routes = self.app.config_data.get("provider_routes", {})
        if not isinstance(saved_routes, dict):
            saved_routes = {}
        self.provider_route_names = provider_names
        self.provider_route_vars = {}
        for provider_name in provider_names:
            route_row = ctk.CTkFrame(provider_routes_card, fg_color="transparent")
            route_row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(route_row, text=provider_name, font=app.font(11, "bold"),
                         text_color=colors["text_primary"], anchor="w", width=220).pack(side="left")
            mode = saved_routes.get(provider_name, "default")
            if mode not in PROVIDER_ROUTE_MODES:
                mode = "default"
            variable = tk.StringVar(value=PROVIDER_ROUTE_LABELS[mode])
            self.provider_route_vars[provider_name] = variable
            ctk.CTkOptionMenu(
                route_row, variable=variable,
                values=[label for label, value in PROVIDER_ROUTE_BY_LABEL.items()
                        if value != "google-smart" or provider_name == "google"],
                font=app.font(11), width=190, height=30,
                fg_color=colors["subbox_bg"], button_color=colors["border"],
                button_hover_color=colors["border"], text_color=colors["text_primary"]
            ).pack(side="left")
        if not provider_names:
            ctk.CTkLabel(provider_routes_card,
                         text="Провайдеры ещё не найдены в opencode.json. Сначала добавьте их в OpenCode и откройте эту вкладку снова.",
                         font=app.font(11), text_color=colors["text_secondary"], wraplength=950
                         ).pack(anchor="w", padx=16, pady=(0, 12))

        ctk.CTkLabel(provider_routes_card, text="DoH для Google SmartDNS (публичный сервис или свой):",
                     font=app.font(11), text_color=colors["text_secondary"]
                     ).pack(anchor="w", padx=16, pady=(12, 2))
        from google_smart_dns import DEFAULT_DOH
        self.google_smart_doh_entry = ctk.CTkEntry(provider_routes_card, font=app.font(11))
        self.google_smart_doh_entry.pack(fill="x", padx=16)
        self.google_smart_doh_entry.insert(0, app.config_data.get("google_smart_doh") or DEFAULT_DOH)

        google_tools = ctk.CTkFrame(provider_routes_card, fg_color="transparent")
        google_tools.pack(fill="x", padx=16, pady=12)
        self.btn_google_route_check = ctk.CTkButton(
            google_tools, text="Диагностика маршрута Google", command=self.diagnose_google_route,
            font=app.font(11), width=220)
        self.btn_google_route_check.pack(side="left", padx=(0, 8))
        ctk.CTkButton(google_tools, text="Тест Gemini 3.8", font=app.font(11),
                      command=self.app.test_google_generation_action).pack(side="left")
        ctk.CTkLabel(provider_routes_card,
                     text="Диагностика и тест используют сохранённые настройки. SmartDNS зависит от доступности внешнего сервиса, но не требует сторонней программы на ПК.",
                     font=app.font(11), text_color=colors["text_secondary"], wraplength=950
                     ).pack(anchor="w", padx=16, pady=(0, 12))

        # Save Button
        save_btn = ctk.CTkButton(
            self,
            text="💾 Сохранить настройки сети",
            font=app.font(13, "bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            text_color="#ffffff",
            height=36,
            corner_radius=6,
            command=self.save_network_settings
        )
        save_btn.pack(anchor="w", pady=(8, 16))

        self.update_core_status()
        self.update_vless_status()
        self.after(2500, self._poll_vless_status)

    # =========================================================================
    # VLESS ACTIONS
    # =========================================================================
    def update_core_status(self):
        cand = vless_service.find_core_executable(self.app.config_data.get("vless_core_path"))
        if cand:
            self.core_status_lbl.configure(text=f"✔ Найдено ядро: {cand.name} ({cand.parent})", text_color="#3fb950")
            self.btn_download_core.configure(text="🔄 Обновить sing-box")
        else:
            self.core_status_lbl.configure(text="⚠ Ядро Xray / sing-box не установлено", text_color="#d29922")
            self.btn_download_core.configure(text="⬇ Скачать sing-box (в 1 клик)")

    def update_vless_status(self):
        running = vless_service.is_running()
        if running:
            self.vless_badge.configure(text="● Туннель активен", text_color="#3fb950")
            self.btn_vless_start.configure(state="disabled")
            self.btn_vless_stop.configure(state="normal")
        else:
            self.vless_badge.configure(text="● Остановлен", text_color="#ef4444")
            self.btn_vless_start.configure(state="normal")
            self.btn_vless_stop.configure(state="disabled")

    def _poll_vless_status(self):
        """Keep the badge and controls synchronized with externally started tunnels."""
        try:
            if not self.winfo_exists():
                return
            self.update_vless_status()
            self.after(2500, self._poll_vless_status)
        except Exception:
            # The view may be closing while its scheduled refresh is pending.
            return

    def on_vless_switch_toggled(self):
        enabled = self.vless_enabled_var.get()
        if not enabled and any(
            PROVIDER_ROUTE_BY_LABEL.get(variable.get()) == "vless"
            for variable in self.provider_route_vars.values()
        ):
            self.vless_enabled_var.set(True)
            messagebox.showwarning(
                "VLESS используется",
                "Один или несколько провайдеров настроены на VLESS. Сначала измените их маршрут, затем отключайте туннель."
            )
            return
        url = self.vless_entry.get().strip()
        self.app.config_data["vless_enabled"] = enabled
        self.app.config_data["vless_url"] = url
        self.app.save_config()
        self.sync_opencode_proxy()
        if enabled:
            if url and not vless_service.is_running():
                self.start_vless_action()
        else:
            if vless_service.is_running():
                self.stop_vless_action()

    def sync_opencode_proxy(self):
        """Apply global and provider-specific routes to OpenCode configuration."""
        try:
            opencode_cfg_path = Path.home() / ".config" / "opencode" / "opencode.json"
            if not opencode_cfg_path.exists():
                return

            oc_data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
            hub_config = dict(self.app.config_data)
            hub_config["vless_url"] = self.vless_entry.get().strip()
            hub_config["vless_enabled"] = self.vless_enabled_var.get()
            entered_proxy = self.proxy_entry.get().strip()
            hub_config["proxy"] = entered_proxy if entered_proxy != f"http://127.0.0.1:{LOCAL_DNS_PROXY_PORT}" else ""
            routes = {
                name: PROVIDER_ROUTE_BY_LABEL.get(variable.get(), "default")
                for name, variable in self.provider_route_vars.items()
            }
            sync_provider_routes(oc_data, hub_config, get_http_port(), routes)

            opencode_cfg_path.write_text(
                json.dumps(oc_data, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                import opencode_config
                opencode_config.ensure_session_title_config(opencode_cfg_path)
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: Failed to sync proxy to opencode.json: {e}")

    def select_custom_core_action(self):
        f = filedialog.askopenfilename(
            title="Выберите исполняемый файл sing-box.exe или xray.exe",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if f:
            self.app.config_data["vless_core_path"] = f
            self.app.save_config()
            self.update_core_status()
            messagebox.showinfo("Ядро выбрано", f"Используется указанный файл:\n{f}")

    def download_core_action(self):
        self.btn_download_core.configure(state="disabled")

        def _worker():
            def _prog(msg):
                self.app.after(0, lambda m=msg: self.core_status_lbl.configure(text=m, text_color="#58a6ff"))

            ok, msg = vless_service.download_core("sing-box", progress_callback=_prog)

            def _done():
                self.btn_download_core.configure(state="normal")
                self.update_core_status()
                if ok:
                    messagebox.showinfo("Успешно", msg)
                else:
                    messagebox.showerror("Ошибка загрузки", msg)

            self.app.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def start_vless_action(self):
        url = self.vless_entry.get().strip()
        if not url:
            messagebox.showwarning("Внимание", "Введите строку подключения VLESS (vless://...)")
            return

        self.btn_vless_start.configure(state="disabled", text="⏳ Запуск...")

        def _worker():
            custom_path = self.app.config_data.get("vless_core_path")
            ok, msg = vless_service.start_tunnel(url, custom_core_path=custom_path)

            def _done():
                self.btn_vless_start.configure(state="normal", text="▶ Запустить туннель")
                if ok:
                    self.vless_enabled_var.set(True)
                    self.app.config_data["vless_enabled"] = True
                    self.app.config_data["vless_url"] = url
                    self.app.save_config()
                    self.sync_opencode_proxy()
                    self.update_vless_status()
                    self.vless_test_lbl.configure(text=f"✅ {msg}", text_color="#10b981")
                    # Auto-check connection
                    self.test_vless_action()
                else:
                    self.update_vless_status()
                    self.vless_test_lbl.configure(text=f"❌ {msg}", text_color="#ef4444")
                    messagebox.showerror("Ошибка запуска туннеля", msg)

            self.app.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def stop_vless_action(self):
        if any(PROVIDER_ROUTE_BY_LABEL.get(variable.get()) == "vless"
               for variable in self.provider_route_vars.values()):
            messagebox.showwarning(
                "VLESS используется",
                "Один или несколько провайдеров настроены на VLESS. Сначала измените их маршрут."
            )
            return
        ok, msg = vless_service.stop_tunnel()
        self.vless_enabled_var.set(False)
        self.app.config_data["vless_enabled"] = False
        self.app.save_config()
        self.sync_opencode_proxy()
        self.update_vless_status()
        self.vless_test_lbl.configure(text=f"ℹ {msg}", text_color="#94a3b8")

    def test_vless_action(self):
        self.btn_vless_test.configure(state="disabled", text="⏳ Проверка...")

        def _worker():
            res = vless_service.test_connection()

            def _done():
                self.btn_vless_test.configure(state="normal", text="🩺 Проверить подключение и IP")
                self.update_vless_status()
                if res.get("ok"):
                    loc_text = f" [{res.get('country')}]" if res.get('country') else ""
                    self.vless_test_lbl.configure(
                        text=f"✅ Подключено! Внешний IP: {res.get('ip')}{loc_text} • Пинг: {res.get('latency_ms')} мс",
                        text_color="#10b981"
                    )
                else:
                    self.vless_test_lbl.configure(
                        text=f"❌ {res.get('message')}",
                        text_color="#ef4444"
                    )

            self.app.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # DNS TESTS
    # =========================================================================
    def test_standard_dns_action(self):
        p_ip = self.dns_primary_entry.get().strip()
        self.btn_test_std_dns.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_standard_dns(p_ip or "143.20.64.55")
            def _update():
                self.btn_test_std_dns.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_std_dns.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_std_dns.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.app.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def test_dot_action(self):
        host = self.dot_host_entry.get().strip()
        self.btn_test_dot.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_dot_endpoint(host or "dns.bezmezhau.com")
            def _update():
                self.btn_test_dot.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_dot.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_dot.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.app.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def test_doh_action(self):
        url = self.doh_url_entry.get().strip()
        self.btn_test_doh.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_doh_endpoint(url or "https://dns.bezmezhau.com/dns-query")
            def _update():
                self.btn_test_doh.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_doh.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_doh.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.app.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    # =========================================================================
    # SAVE ALL SETTINGS
    # =========================================================================
    def save_network_settings(self):
        from google_smart_dns import resolver_url
        try:
            smart_doh = resolver_url({"google_smart_doh": self.google_smart_doh_entry.get().strip()})
        except ValueError as error:
            messagebox.showerror("Google SmartDNS", str(error))
            return
        provider_routes = {
            name: PROVIDER_ROUTE_BY_LABEL.get(variable.get(), "default")
            for name, variable in self.provider_route_vars.items()
        }
        if any(mode == "vless" for mode in provider_routes.values()) and not (
            self.vless_enabled_var.get() and self.vless_entry.get().strip()
        ):
            messagebox.showwarning(
                "Требуется VLESS",
                "Для выбранного маршрута VLESS укажите ссылку и включите туннель."
            )
            return
        if any(mode == "proxy" for mode in provider_routes.values()) and not self.proxy_entry.get().strip():
            messagebox.showwarning(
                "Не задан внешний прокси",
                "Для выбранного маршрута «Внешний прокси» сначала укажите адрес прокси."
            )
            return

        # 1. Save VLESS settings
        vless_url = self.vless_entry.get().strip()
        self.app.config_data["vless_url"] = vless_url
        self.app.config_data["vless_enabled"] = self.vless_enabled_var.get()

        # 2. Save DNS Mode
        selected_mode = self.dns_mode_var.get()
        if "DoT" in selected_mode:
            self.app.config_data["dns_mode"] = "dot"
        elif "DoH" in selected_mode:
            self.app.config_data["dns_mode"] = "doh"
        elif "Системный" in selected_mode:
            self.app.config_data["dns_mode"] = "system"
        else:
            self.app.config_data["dns_mode"] = "standard"

        # 3. Save Standard DNS
        p_ip = self.dns_primary_entry.get().strip()
        s_ip = self.dns_secondary_entry.get().strip()
        dns_list = []
        if p_ip: dns_list.append(p_ip)
        if s_ip: dns_list.append(s_ip)
        if dns_list:
            self.app.config_data["custom_dns"] = dns_list
        else:
            self.app.config_data.pop("custom_dns", None)

        # 4. Save DoT Host
        dot_val = self.dot_host_entry.get().strip()
        if dot_val:
            self.app.config_data["dot_host"] = dot_val
        else:
            self.app.config_data.pop("dot_host", None)

        # 5. Save DoH URL
        doh_val = self.doh_url_entry.get().strip()
        if doh_val:
            self.app.config_data["doh_url"] = doh_val
        else:
            self.app.config_data.pop("doh_url", None)

        # 6. Save User Proxy
        user_proxy = self.proxy_entry.get().strip()
        if user_proxy and user_proxy != f"http://127.0.0.1:{LOCAL_DNS_PROXY_PORT}":
            self.app.config_data["proxy"] = user_proxy
        else:
            self.app.config_data.pop("proxy", None)

        self.app.config_data["provider_routes"] = provider_routes
        self.app.config_data["google_smart_doh"] = smart_doh

        # Synchronize the selected proxy mode to OpenCode providers.
        self.sync_opencode_proxy()

        ok, msg = self.app.save_config()
        if ok:
            messagebox.showinfo(
                "Успешно",
                "Настройки сети успешно сохранены!\n\n"
                "• VLESS: " + ("Включен" if self.vless_enabled_var.get() else "Отключен") + "\n"
                f"• Режим DNS: {selected_mode}\n\n"
                "Для применения изменений перезапустите OpenCode."
            )
        else:
            messagebox.showerror("Ошибка", msg)
    def diagnose_google_route(self):
        self.btn_google_route_check.configure(state="disabled")

        def worker():
            import google_routes
            try:
                report = google_routes.diagnose_routes()
            except Exception:
                report = "Не удалось выполнить диагностику маршрута."

            def done():
                if not self.winfo_exists():
                    return
                self.btn_google_route_check.configure(state="normal")
                messagebox.showinfo("Маршрут Google", report, parent=self.app)

            self.app.after(0, done)

        threading.Thread(target=worker, daemon=True).start()
