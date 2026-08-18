"""Разбор подписок в формате готовых конфигов Xray.

Часть панелей отдаёт не ссылки vless://, а массив полноценных конфигураций
Xray в JSON — по одной на сервер. Здесь мы вытаскиваем из каждой рабочий
outbound и переводим его в формат sing-box.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.vpn.links import Server

# Служебные outbound, которые есть в каждом конфиге и нам не нужны.
SERVICE_PROTOCOLS = {"freedom", "blackhole", "dns"}

# Отпечатки TLS, которые понимает sing-box.
KNOWN_FINGERPRINTS = {
    "chrome", "firefox", "edge", "safari", "360", "qq",
    "ios", "android", "random", "randomized",
}


def _proxy_outbound(config: dict[str, Any]) -> dict[str, Any] | None:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        return None
    for item in outbounds:
        if not isinstance(item, dict):
            continue
        if item.get("protocol") in SERVICE_PROTOCOLS:
            continue
        if item.get("protocol"):
            return item
    return None


def _tls_block(stream: dict[str, Any], fallback_host: str) -> dict[str, Any] | None:
    security = str(stream.get("security") or "none").lower()
    if security not in ("tls", "reality", "xtls"):
        return None

    if security == "reality":
        settings = stream.get("realitySettings") or {}
    else:
        settings = stream.get("tlsSettings") or {}

    server_name = str(settings.get("serverName") or "") or fallback_host
    tls: dict[str, Any] = {"enabled": True, "server_name": server_name}

    alpn = settings.get("alpn")
    if isinstance(alpn, list) and alpn:
        tls["alpn"] = [str(item) for item in alpn]
    if settings.get("allowInsecure"):
        tls["insecure"] = True

    fingerprint = str(settings.get("fingerprint") or "").lower()
    if fingerprint not in KNOWN_FINGERPRINTS:
        fingerprint = "chrome"
    tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

    if security == "reality":
        tls["reality"] = {
            "enabled": True,
            "public_key": str(settings.get("publicKey") or ""),
            "short_id": str(settings.get("shortId") or ""),
        }
    return tls


def _transport_block(stream: dict[str, Any]) -> dict[str, Any] | None:
    network = str(stream.get("network") or "tcp").lower()

    if network in ("tcp", "raw", ""):
        return None
    if network == "grpc":
        settings = stream.get("grpcSettings") or {}
        return {
            "type": "grpc",
            "service_name": str(settings.get("serviceName") or ""),
        }
    if network == "ws":
        settings = stream.get("wsSettings") or {}
        block: dict[str, Any] = {
            "type": "ws",
            "path": str(settings.get("path") or "/"),
        }
        headers = settings.get("headers")
        if isinstance(headers, dict) and headers.get("Host"):
            block["headers"] = {"Host": str(headers["Host"])}
        return block
    if network == "httpupgrade":
        settings = stream.get("httpupgradeSettings") or {}
        return {
            "type": "httpupgrade",
            "path": str(settings.get("path") or "/"),
            "host": str(settings.get("host") or ""),
        }
    if network in ("http", "h2"):
        settings = stream.get("httpSettings") or {}
        hosts = settings.get("host")
        return {
            "type": "http",
            "path": str(settings.get("path") or "/"),
            "host": [str(item) for item in hosts] if isinstance(hosts, list) else [],
        }
    return None


def _convert(outbound: dict[str, Any], name: str) -> Server | None:
    protocol = str(outbound.get("protocol") or "").lower()
    settings = outbound.get("settings") or {}
    stream = outbound.get("streamSettings") or {}

    if protocol in ("vless", "vmess"):
        vnext = settings.get("vnext") or []
        if not vnext:
            return None
        node = vnext[0]
        host = str(node.get("address") or "")
        port = int(node.get("port") or 0)
        users = node.get("users") or []
        if not host or not port or not users:
            return None
        user = users[0]

        result: dict[str, Any] = {
            "type": protocol,
            "tag": name,
            "server": host,
            "server_port": port,
            "uuid": str(user.get("id") or ""),
        }
        if protocol == "vless":
            flow = str(user.get("flow") or "").strip()
            if flow:
                result["flow"] = flow
        else:
            result["alter_id"] = int(user.get("alterId") or 0)
            result["security"] = str(user.get("security") or "auto")

    elif protocol in ("trojan", "shadowsocks"):
        servers = settings.get("servers") or []
        if not servers:
            return None
        node = servers[0]
        host = str(node.get("address") or "")
        port = int(node.get("port") or 0)
        if not host or not port:
            return None

        if protocol == "trojan":
            result = {
                "type": "trojan",
                "tag": name,
                "server": host,
                "server_port": port,
                "password": str(node.get("password") or ""),
            }
        else:
            result = {
                "type": "shadowsocks",
                "tag": name,
                "server": host,
                "server_port": port,
                "method": str(node.get("method") or ""),
                "password": str(node.get("password") or ""),
            }
    else:
        return None

    tls = _tls_block(stream, host)
    if tls:
        result["tls"] = tls
    elif protocol == "trojan":
        result["tls"] = {"enabled": True, "server_name": host}

    transport = _transport_block(stream)
    if transport:
        result["transport"] = transport

    return Server(
        name=name,
        protocol="vless" if protocol == "vless" else protocol,
        host=host,
        port=port,
        outbound=result,
        uri="",
    )


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[") or stripped.startswith("{")


def parse(text: str) -> list[Server]:
    """Разобрать подписку-JSON. Пустой список — формат не подошёл."""
    try:
        data = json.loads(text)
    except ValueError:
        return []

    if isinstance(data, dict):
        # Иногда конфиг приходит один, без массива.
        data = [data]
    if not isinstance(data, list):
        return []

    servers: list[Server] = []
    for index, config in enumerate(data, start=1):
        if not isinstance(config, dict):
            continue
        outbound = _proxy_outbound(config)
        if outbound is None:
            continue
        name = str(config.get("remarks") or outbound.get("tag") or "").strip()
        if not name or name.lower() == "proxy":
            name = f"Сервер {index}"
        server = _convert(outbound, name)
        if server is not None:
            servers.append(server)

    _deduplicate(servers)
    return servers


def _deduplicate(servers: list[Server]) -> None:
    """Теги outbound в sing-box должны быть уникальными."""
    used: dict[str, int] = {}
    for server in servers:
        base = server.name
        count = used.get(base, 0) + 1
        used[base] = count
        if count > 1:
            server.name = f"{base} ({count})"
        server.outbound["tag"] = server.name
