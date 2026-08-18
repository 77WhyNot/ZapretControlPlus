"""Разбор ссылок на серверы в конфигурацию outbound для sing-box.

Поддержаны форматы, которые реально встречаются в подписках:
vless (в том числе Reality), vmess, trojan, shadowsocks и hysteria2.
Ссылку, которую разобрать не удалось, молча пропускаем — одна битая
строка не должна ломать всю подписку.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

SUPPORTED_SCHEMES = ("vless", "vmess", "trojan", "ss", "hysteria2", "hy2")


@dataclass
class Server:
    """Один сервер из подписки."""

    name: str
    protocol: str
    host: str
    port: int
    outbound: dict[str, Any] = field(repr=False, default_factory=dict)
    uri: str = field(repr=False, default="")

    @property
    def tag(self) -> str:
        return self.name

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def transport_label(self) -> str:
        """Короткая подпись для интерфейса: «VLESS Reality», «Hysteria2»."""
        if self.protocol == "vless":
            tls = self.outbound.get("tls") or {}
            if tls.get("reality", {}).get("enabled"):
                return "VLESS Reality"
            return "VLESS"
        return {
            "vmess": "VMess",
            "trojan": "Trojan",
            "shadowsocks": "Shadowsocks",
            "hysteria2": "Hysteria2",
        }.get(self.protocol, self.protocol.upper())


def _b64_decode(data: str) -> bytes:
    """base64 из подписок часто без выравнивания и в url-safe виде."""
    cleaned = re.sub(r"\s+", "", data)
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    padding = (-len(cleaned)) % 4
    try:
        return base64.b64decode(cleaned + "=" * padding)
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return b""


def _first(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[0] if values else default


def _name_from_fragment(parts, fallback: str) -> str:
    return unquote(parts.fragment).strip() or fallback


def _tls_block(params: dict[str, list[str]], host: str) -> dict[str, Any] | None:
    """Собрать секцию tls, включая Reality и подмену отпечатка."""
    security = _first(params, "security", "none").lower()
    sni = _first(params, "sni") or _first(params, "peer") or host
    fingerprint = _first(params, "fp")
    alpn = _first(params, "alpn")

    if security not in ("tls", "reality", "xtls"):
        return None

    tls: dict[str, Any] = {"enabled": True, "server_name": sni}
    if alpn:
        tls["alpn"] = [item for item in alpn.split(",") if item]
    if _first(params, "allowInsecure") in ("1", "true") or \
            _first(params, "insecure") in ("1", "true"):
        tls["insecure"] = True
    if fingerprint:
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

    if security == "reality":
        public_key = _first(params, "pbk")
        tls["reality"] = {
            "enabled": True,
            "public_key": public_key,
            "short_id": _first(params, "sid"),
        }
        # Reality без utls не работает — подставляем распространённый отпечаток.
        tls.setdefault("utls", {"enabled": True, "fingerprint": fingerprint or "chrome"})
    return tls


def _transport_block(params: dict[str, list[str]], host: str) -> dict[str, Any] | None:
    """Секция transport: ws, grpc, http, httpupgrade."""
    network = (_first(params, "type") or _first(params, "net") or "tcp").lower()
    path = _first(params, "path", "/")
    host_header = _first(params, "host") or host

    if network in ("tcp", "raw", ""):
        return None
    if network == "ws":
        block: dict[str, Any] = {"type": "ws", "path": path}
        if host_header:
            block["headers"] = {"Host": host_header}
        early = _first(params, "ed")
        if early.isdigit():
            block["max_early_data"] = int(early)
            block["early_data_header_name"] = "Sec-WebSocket-Protocol"
        return block
    if network == "grpc":
        return {
            "type": "grpc",
            "service_name": _first(params, "serviceName") or _first(params, "path", ""),
        }
    if network == "httpupgrade":
        return {"type": "httpupgrade", "path": path, "host": host_header}
    if network in ("http", "h2"):
        return {"type": "http", "path": path, "host": [host_header] if host_header else []}
    return None


# --- отдельные схемы -----------------------------------------------------


def _parse_vless(uri: str) -> Server | None:
    parts = urlsplit(uri)
    if not parts.hostname or not parts.port or not parts.username:
        return None
    params = parse_qs(parts.query)
    host, port = parts.hostname, int(parts.port)
    name = _name_from_fragment(parts, f"{host}:{port}")

    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": name,
        "server": host,
        "server_port": port,
        "uuid": parts.username,
    }
    flow = _first(params, "flow")
    if flow:
        outbound["flow"] = flow
    tls = _tls_block(params, host)
    if tls:
        outbound["tls"] = tls
    transport = _transport_block(params, host)
    if transport:
        outbound["transport"] = transport
    return Server(name, "vless", host, port, outbound, uri)


def _parse_vmess(uri: str) -> Server | None:
    payload = _b64_decode(uri[len("vmess://"):])
    if not payload:
        return None
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except ValueError:
        return None

    host = str(data.get("add") or "")
    try:
        port = int(data.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if not host or not port:
        return None

    name = str(data.get("ps") or f"{host}:{port}").strip()
    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": name,
        "server": host,
        "server_port": port,
        "uuid": str(data.get("id") or ""),
        "security": "auto",
    }
    try:
        outbound["alter_id"] = int(data.get("aid") or 0)
    except (TypeError, ValueError):
        outbound["alter_id"] = 0

    if str(data.get("tls") or "").lower() in ("tls", "reality"):
        outbound["tls"] = {
            "enabled": True,
            "server_name": str(data.get("sni") or data.get("host") or host),
        }

    network = str(data.get("net") or "tcp").lower()
    if network == "ws":
        transport: dict[str, Any] = {"type": "ws", "path": str(data.get("path") or "/")}
        if data.get("host"):
            transport["headers"] = {"Host": str(data["host"])}
        outbound["transport"] = transport
    elif network == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": str(data.get("path") or "")}

    return Server(name, "vmess", host, port, outbound, uri)


def _parse_trojan(uri: str) -> Server | None:
    parts = urlsplit(uri)
    if not parts.hostname or not parts.port or not parts.username:
        return None
    params = parse_qs(parts.query)
    host, port = parts.hostname, int(parts.port)
    name = _name_from_fragment(parts, f"{host}:{port}")

    outbound: dict[str, Any] = {
        "type": "trojan",
        "tag": name,
        "server": host,
        "server_port": port,
        "password": unquote(parts.username),
    }
    tls = _tls_block(params, host) or {"enabled": True, "server_name": host}
    outbound["tls"] = tls
    transport = _transport_block(params, host)
    if transport:
        outbound["transport"] = transport
    return Server(name, "trojan", host, port, outbound, uri)


def _parse_shadowsocks(uri: str) -> Server | None:
    body = uri[len("ss://"):]
    fragment = ""
    if "#" in body:
        body, fragment = body.split("#", 1)
    body = body.split("?", 1)[0]

    method = password = host = ""
    port = 0

    if "@" in body:
        # ss://base64(method:password)@host:port
        userinfo, _, hostpart = body.rpartition("@")
        decoded = _b64_decode(userinfo).decode("utf-8", errors="replace")
        if ":" not in decoded:
            decoded = unquote(userinfo)
        method, _, password = decoded.partition(":")
        host, _, port_text = hostpart.rpartition(":")
        host = host.strip("[]")
        port = int(port_text) if port_text.isdigit() else 0
    else:
        # ss://base64(method:password@host:port)
        decoded = _b64_decode(body).decode("utf-8", errors="replace")
        match = re.match(r"^(?P<m>[^:]+):(?P<p>.*)@(?P<h>.+):(?P<port>\d+)$", decoded)
        if not match:
            return None
        method, password = match.group("m"), match.group("p")
        host, port = match.group("h").strip("[]"), int(match.group("port"))

    if not host or not port or not method:
        return None
    name = unquote(fragment).strip() or f"{host}:{port}"
    outbound = {
        "type": "shadowsocks",
        "tag": name,
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }
    return Server(name, "shadowsocks", host, port, outbound, uri)


def _parse_hysteria2(uri: str) -> Server | None:
    parts = urlsplit(uri)
    if not parts.hostname:
        return None
    port = parts.port or 443
    params = parse_qs(parts.query)
    host = parts.hostname
    name = _name_from_fragment(parts, f"{host}:{port}")

    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "tag": name,
        "server": host,
        "server_port": port,
        "password": unquote(parts.username or "") or _first(params, "auth"),
        "tls": {
            "enabled": True,
            "server_name": _first(params, "sni") or host,
        },
    }
    if _first(params, "insecure") in ("1", "true"):
        outbound["tls"]["insecure"] = True
    obfs_password = _first(params, "obfs-password")
    if _first(params, "obfs") == "salamander" and obfs_password:
        outbound["obfs"] = {"type": "salamander", "password": obfs_password}
    return Server(name, "hysteria2", host, port, outbound, uri)


_PARSERS = {
    "vless": _parse_vless,
    "vmess": _parse_vmess,
    "trojan": _parse_trojan,
    "ss": _parse_shadowsocks,
    "hysteria2": _parse_hysteria2,
    "hy2": _parse_hysteria2,
}


def parse_link(uri: str) -> Server | None:
    uri = uri.strip()
    scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
    parser = _PARSERS.get(scheme)
    if parser is None:
        return None
    try:
        return parser(uri)
    except (ValueError, TypeError, AttributeError):
        return None


def parse_many(text: str) -> list[Server]:
    """Разобрать содержимое подписки: список ссылок, возможно в base64."""
    candidate = text.strip()
    if candidate and "://" not in candidate.split("\n", 1)[0]:
        decoded = _b64_decode(candidate).decode("utf-8", errors="replace")
        if "://" in decoded:
            candidate = decoded

    servers: list[Server] = []
    seen: set[str] = set()
    for line in candidate.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        server = parse_link(line)
        if server is None:
            continue
        key = f"{server.protocol}|{server.host}|{server.port}|{server.name}"
        if key in seen:
            continue
        seen.add(key)
        servers.append(server)

    _deduplicate_names(servers)
    return servers


def _deduplicate_names(servers: list[Server]) -> None:
    """Теги outbound в sing-box обязаны быть уникальными."""
    used: dict[str, int] = {}
    for server in servers:
        base = server.name or server.endpoint
        count = used.get(base, 0) + 1
        used[base] = count
        if count > 1:
            server.name = f"{base} ({count})"
        server.outbound["tag"] = server.name
