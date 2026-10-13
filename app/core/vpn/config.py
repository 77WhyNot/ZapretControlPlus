"""Сборка конфигурации sing-box.

Два способа доставить трафик в туннель:

* «Туннель» — TUN-адаптер перехватывает весь трафик, а правила решают, кому
  наружу напрямую (там его подхватит zapret), а кому — в VPN. Нужны права
  администратора, и в системе не должно быть другого живого туннеля.
* «Прокси» — sing-box слушает на 127.0.0.1, а Windows направляют туда
  системный прокси. Маршруты и адаптеры не трогаются вовсе, поэтому режим
  уживается с любым чужим VPN-клиентом. Выбор программ здесь не действует:
  VPN получают те, кто уважает системный прокси.
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

TRANSPORT_TUN = "tun"
TRANSPORT_PROXY = "proxy"
TRANSPORT_LABELS = {
    TRANSPORT_TUN: "Туннель — VPN для выбранных программ",
    TRANSPORT_PROXY: "Прокси — без конфликтов с другим VPN",
}

# Своё имя адаптера: с общим "tun0" мы дрались бы за него с любым другим
# клиентом на том же движке — например с Happ.
TUN_NAME = "ZapretControl"
PROBE_TAG = "probe-in"
PROXY_IN_TAG = "proxy-in"
PROXY_TAG = "proxy"
DIRECT_TAG = "direct"
AUTO_TAG = "auto"

# Куда программа ходит узнать адрес выхода VPN (engine.exit_address).
# Часть этих сервисов в списках «Российские сайты — напрямую» помечена как
# прямая — для самопроверки их всегда держим в туннеле.
PROBE_DOMAINS = ("ipinfo.io", "api.ip.sb", "ifconfig.co")

# Стек TUN. Для сопоставления процессов на Windows важен системный стек:
# у gvisor поиск имени процесса по TCP работает не всегда.
STACK_DEFAULT = "mixed"


def _outbounds(servers: list[Server], selected: str) -> list[dict[str, Any]]:
    outbounds: list[dict[str, Any]] = []
    tags = [server.name for server in servers]

    for server in servers:
        outbounds.append(dict(server.outbound))

    # Автовыбор по задержке. Интервал большой намеренно: при переключении
    # сервера рвутся живые соединения, а частая перепроверка делала это
    # каждые пять минут — со стороны выглядело как «интернет отваливается».
    if tags:
        outbounds.append({
            "type": "urltest",
            "tag": AUTO_TAG,
            "outbounds": list(tags),
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30m",
            "tolerance": 150,
            "interrupt_exist_connections": False,
        })

    selector_options = tags + ([AUTO_TAG] if tags else [])
    if not selector_options:
        selector_options = [DIRECT_TAG]
    # По умолчанию — выбранный сервер, а не автогруппа: она переключается
    # сама и обрывает соединения без ведома пользователя.
    default_choice = selected if selected in selector_options else selector_options[0]

    outbounds.append({
        "type": "selector",
        "tag": PROXY_TAG,
        "outbounds": selector_options,
        "default": default_choice,
        # Не рвём существующие соединения: иначе любое обращение к селектору
        # обрубает открытые вкладки и звонки.
        "interrupt_exist_connections": False,
    })
    outbounds.append({"type": "direct", "tag": DIRECT_TAG})
    return outbounds


def _experimental(clash_port: int, clash_secret: str) -> dict[str, Any]:
    return {
        "clash_api": {
            "external_controller": f"127.0.0.1:{clash_port}",
            "secret": clash_secret,
            "default_mode": "rule",
        },
        "cache_file": {"enabled": True, "store_fakeip": False},
    }


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
    strict_route: bool = False,
    ipv6: bool = False,
    mtu: int = 9000,
    dns_through_tunnel: bool = False,
    bypass_lan: bool = True,
    probe_port: int = 0,
    transport: str = TRANSPORT_TUN,
    proxy_port: int = 10808,
    ru_direct: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ru_direct — наборы «Российские сайты — напрямую» (тег → путь) или None."""
    if transport == TRANSPORT_PROXY:
        return build_proxy_config(servers, selected, clash_port, clash_secret,
                                  log_level, proxy_port, ru_direct)

    # Имя программы движок сравнивает посимвольно, поэтому кладём в правило
    # все написания — иначе «telegram.exe» из ручного ввода не совпадёт с
    # настоящим «Telegram.exe», и правило тихо не сработает.
    from app.core.vpn import apps as apps_module

    vpn_apps = apps_module.match_names([name for name in (vpn_apps or []) if name])
    direct_apps = apps_module.match_names(
        [name for name in (direct_apps or []) if name]
    )
    outbounds = _outbounds(servers, selected)

    # Порядок правил важен: сначала распознаём протокол, потом перехватываем
    # DNS, потом отсекаем локальную сеть — и только затем решаем по программе.
    rules: list[dict[str, Any]] = [
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
    ]
    # Служебный вход всегда идёт в туннель, что бы ни было в правилах:
    # только так можно узнать настоящий выходной адрес VPN. Само приложение
    # обычно ходит напрямую и увидело бы свой реальный IP.
    if probe_port:
        rules.append({"inbound": [PROBE_TAG], "outbound": PROXY_TAG})
    if bypass_lan:
        rules.append({"ip_is_private": True, "outbound": DIRECT_TAG})

    # «Российские сайты — напрямую»: из того, что ушло бы в туннель,
    # российское выпускаем мимо, а YouTube и Telegram держим в туннеле,
    # даже если их адрес российский. Порядок: сначала «в туннель», потом
    # «напрямую» — как «block-proxy-direct» в профиле Happ.
    if ru_direct is not None:
        from app.core.vpn import routing

        ru_rules = routing.direct_rules(ru_direct, DIRECT_TAG)
    else:
        ru_rules = []

    if mode == MODE_ALL:
        if ru_rules:
            keep = routing.vpn_rule(ru_direct, PROXY_TAG)
            rules.extend(([keep] if keep else []) + ru_rules)
        final = PROXY_TAG
    elif mode == MODE_EXCEPT:
        if direct_apps:
            rules.append({"process_name": direct_apps, "outbound": DIRECT_TAG})
        if ru_rules:
            keep = routing.vpn_rule(ru_direct, PROXY_TAG)
            rules.extend(([keep] if keep else []) + ru_rules)
        final = PROXY_TAG
    else:
        if vpn_apps:
            if ru_rules:
                # Остальные программы и так идут напрямую, поэтому «в туннель»
                # — только для своих: иначе YouTube потянуло бы в VPN всем.
                keep = routing.vpn_rule(ru_direct, PROXY_TAG, process_name=vpn_apps)
                rules.extend(([keep] if keep else []) + ru_rules)
            rules.append({"process_name": vpn_apps, "outbound": PROXY_TAG})
        final = DIRECT_TAG

    # DNS. Прямой путь — без detour вовсе: движок отказывается от
    # «detour на пустой direct» и не стартует. Через туннель — detour на
    # селектор.
    remote_dns: dict[str, Any] = {
        "type": "https",
        "tag": "dns-remote",
        "server": dns_over_proxy,
    }
    if dns_through_tunnel:
        remote_dns["detour"] = PROXY_TAG
    dns_final = "dns-remote" if dns_through_tunnel else "dns-local"
    dns_rules: list[dict[str, Any]] = []
    if ru_rules and dns_through_tunnel:
        # Российские имена — у обычного DNS: ответ через зарубежный сервер
        # нередко ведёт на зарубежный узел CDN, и сайт открывается медленно.
        dns_rules.append(routing.dns_rule(ru_direct, "dns-local"))
    dns_rules.append({"query_type": ["A", "AAAA"], "server": dns_final})

    config: dict[str, Any] = {
        "log": {"level": log_level, "timestamp": True},
        "dns": {
            "servers": [
                {"type": "local", "tag": "dns-local"},
                remote_dns,
            ],
            "rules": dns_rules,
            "final": dns_final,
            # Туннель без IPv6 не должен раздавать IPv6-адреса: иначе на
            # машине с IPv6 от провайдера программы, которые предпочитают
            # IPv6, уходят мимо туннеля со своим настоящим адресом.
            "strategy": "ipv4_only" if not ipv6 else "prefer_ipv6",
            "independent_cache": True,
        },
        "inbounds": ([
            {
                "type": "mixed",
                "tag": PROBE_TAG,
                "listen": "127.0.0.1",
                "listen_port": probe_port,
            }
        ] if probe_port else []) + [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": TUN_NAME,
                "address": (["172.19.0.1/30", "fdfe:dcba:9876::1/126"]
                            if ipv6 else ["172.19.0.1/30"]),
                "mtu": int(mtu),
                "auto_route": True,
                "strict_route": bool(strict_route),
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
        "experimental": _experimental(clash_port, clash_secret),
    }
    if ru_rules:
        config["route"]["rule_set"] = routing.rule_set_entries(ru_direct)
    return config


def build_proxy_config(
    servers: list[Server],
    selected: str = "",
    clash_port: int = 9797,
    clash_secret: str = "",
    log_level: str = "warn",
    proxy_port: int = 10808,
    ru_direct: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Только локальный прокси: ни адаптера, ни маршрутов, ни перехвата DNS."""
    rules: list[dict[str, Any]] = [{"action": "sniff"}]
    rule_sets: list[dict[str, Any]] = []
    if ru_direct is not None:
        from app.core.vpn import routing

        # В этом режиме вход один на всех, и самопроверка адреса идёт через
        # него же: без этого правила она увидела бы настоящий IP.
        rules.append({"inbound": [PROXY_IN_TAG], "domain": list(PROBE_DOMAINS),
                      "outbound": PROXY_TAG})
        keep = routing.vpn_rule(ru_direct, PROXY_TAG, inbound=[PROXY_IN_TAG])
        rules.extend(([keep] if keep else [])
                     + routing.direct_rules(ru_direct, DIRECT_TAG))
        rule_sets = routing.rule_set_entries(ru_direct)
    rules.append({"inbound": [PROXY_IN_TAG], "outbound": PROXY_TAG})
    route: dict[str, Any] = {
        "rules": rules,
        "final": DIRECT_TAG,
        "default_domain_resolver": "dns-local",
    }
    if rule_sets:
        route["rule_set"] = rule_sets
    return {
        "log": {"level": log_level, "timestamp": True},
        "dns": {
            "servers": [{"type": "local", "tag": "dns-local"}],
            "final": "dns-local",
            "strategy": "prefer_ipv4",
            "independent_cache": True,
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": PROXY_IN_TAG,
                "listen": "127.0.0.1",
                "listen_port": int(proxy_port),
            }
        ],
        "outbounds": _outbounds(servers, selected),
        "route": route,
        "experimental": _experimental(clash_port, clash_secret),
    }


def server_endpoints(servers: list[Server]) -> list[str]:
    """Адреса серверов — их нужно исключить из обработки zapret."""
    return sorted({server.host for server in servers if server.host})
