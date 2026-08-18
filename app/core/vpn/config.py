"""Сборка конфигурации sing-box.

Весь трафик заходит в TUN, а правила решают, кому наружу напрямую (там его
подхватит zapret), а кому — в туннель. Поэтому VPN и zapret спокойно живут
одновременно и даже дополняют друг друга.
"""

from __future__ import annotations

from typing import Any

from app.core.vpn.links import Server

# Режимы раздельного туннелирования.
MODE_SELECTED = "selected"     # через VPN только выбранные программы
MODE_EXCEPT = "except"         # через VPN всё, кроме выбранных
MODE_ALL = "all"               # через VPN всё

MODE_LABELS = {
    MODE_SELECTED: "Только выбранные программы",
    MODE_EXCEPT: "Все, кроме выбранных",
    MODE_ALL: "Весь трафик",
}

PROXY_TAG = "proxy"
DIRECT_TAG = "direct"
AUTO_TAG = "auto"

# Стек TUN. Для сопоставления процессов на Windows важен системный стек:
# у gvisor поиск имени процесса по TCP работает не всегда.
STACK_DEFAULT = "mixed"


def build_config(
    servers: list[Server],
    selected: str = "",
    mode: str = MODE_SELECTED,
    vpn_apps: list[str] | None = None,
    direct_apps: list[str] | None = None,
    clash_port: int = 9797,
    clash_secret: str = "",
    stack: str = STACK_DEFAULT,
    log_level: str = "warn",
    dns_over_proxy: str = "1.1.1.1",
) -> dict[str, Any]:
    vpn_apps = [name for name in (vpn_apps or []) if name]
    direct_apps = [name for name in (direct_apps or []) if name]

    outbounds: list[dict[str, Any]] = []
    tags = [server.name for server in servers]

    for server in servers:
        outbounds.append(dict(server.outbound))

    # Автовыбор по задержке — им же пользуется кнопка «выбрать лучший».
    if tags:
        outbounds.append({
            "type": "urltest",
            "tag": AUTO_TAG,
            "outbounds": list(tags),
            "url": "https://www.gstatic.com/generate_204",
            "interval": "5m",
            "tolerance": 60,
        })

    selector_options = ([AUTO_TAG] if tags else []) + tags
    if not selector_options:
        selector_options = [DIRECT_TAG]
    default_choice = selected if selected in selector_options else selector_options[0]

    outbounds.append({
        "type": "selector",
        "tag": PROXY_TAG,
        "outbounds": selector_options,
        "default": default_choice,
        "interrupt_exist_connections": True,
    })
    outbounds.append({"type": "direct", "tag": DIRECT_TAG})

    rules: list[dict[str, Any]] = [
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
        {"ip_is_private": True, "outbound": DIRECT_TAG},
    ]

    if mode == MODE_ALL:
        final = PROXY_TAG
    elif mode == MODE_EXCEPT:
        if direct_apps:
            rules.append({"process_name": direct_apps, "outbound": DIRECT_TAG})
        final = PROXY_TAG
    else:
        if vpn_apps:
            rules.append({"process_name": vpn_apps, "outbound": PROXY_TAG})
        final = DIRECT_TAG

    config: dict[str, Any] = {
        "log": {"level": log_level, "timestamp": True},
        "dns": {
            "servers": [
                {"type": "local", "tag": "dns-local"},
                {
                    "type": "https",
                    "tag": "dns-remote",
                    "server": dns_over_proxy,
                    "detour": PROXY_TAG,
                },
            ],
            "rules": [
                {"query_type": ["A", "AAAA"], "server": "dns-local"},
            ],
            "final": "dns-local",
            "strategy": "prefer_ipv4",
            "independent_cache": True,
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "mtu": 9000,
                "auto_route": True,
                "strict_route": False,
                "stack": stack,
            }
        ],
        "outbounds": outbounds,
        "route": {
            "rules": rules,
            "final": final,
            "auto_detect_interface": True,
            "find_process": True,
            "default_domain_resolver": "dns-local",
        },
        "experimental": {
            "clash_api": {
                "external_controller": f"127.0.0.1:{clash_port}",
                "secret": clash_secret,
                "default_mode": "rule",
            },
            "cache_file": {"enabled": True, "store_fakeip": False},
        },
    }
    return config


def server_endpoints(servers: list[Server]) -> list[str]:
    """Адреса серверов — их нужно исключить из обработки zapret."""
    return sorted({server.host for server in servers if server.host})
