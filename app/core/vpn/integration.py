"""Стыковка zapret и VPN.

Трафик sing-box до VPN-сервера уходит через обычный сетевой адаптер на
порт 443 — и zapret, ничего не подозревая, начинает его резать и подделывать.
Туннель после этого не поднимается. Поэтому адреса серверов подписки нужно
занести в исключения zapret.

Строки, добавленные программой, запоминаются в настройках, а не помечаются
комментарием в самом файле: так ничего не сломается, даже если конкретная
сборка zapret комментарии в ipset не понимает.
"""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor

from app.core import logs, paths
from app.core.config import config
from app.core.vpn.links import Server

EXCLUDE_FILE = "ipset-exclude-user.txt"
MANAGED_KEY = "vpn_managed_excludes"
RESOLVE_WORKERS = 8


def resolve_host(host: str) -> list[str]:
    """IP-адреса сервера. Если это уже адрес — возвращаем как есть."""
    host = host.strip()
    if not host:
        return []
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        records = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return []
    found: list[str] = []
    for record in records:
        address = record[4][0]
        if address not in found:
            found.append(address)
    return found


def _to_cidr(address: str) -> str | None:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    if parsed.is_private or parsed.is_loopback or parsed.is_unspecified:
        return None
    return f"{parsed}/32" if parsed.version == 4 else f"{parsed}/128"


def collect_server_cidrs(servers: list[Server]) -> list[str]:
    hosts = sorted({server.host for server in servers if server.host})
    if not hosts:
        return []
    result: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(RESOLVE_WORKERS, len(hosts))) as pool:
        for addresses in pool.map(resolve_host, hosts):
            for address in addresses:
                cidr = _to_cidr(address)
                if cidr:
                    result.add(cidr)
    return sorted(result)


def _exclude_path():
    return paths.lists_dir() / EXCLUDE_FILE


def _read_lines() -> list[str]:
    path = _exclude_path()
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def sync_excludes(servers: list[Server]) -> tuple[int, bool]:
    """Обновить исключения zapret. Возвращает (сколько адресов, было ли изменение)."""
    managed_before = set(config.get(MANAGED_KEY, []) or [])
    wanted = set(collect_server_cidrs(servers))

    if wanted == managed_before and _exclude_path().exists():
        existing = set(_read_lines())
        if wanted.issubset(existing):
            return len(wanted), False

    # Пользовательские строки — всё, что не добавляли мы.
    user_lines = [
        line for line in _read_lines()
        if line.strip() and line.strip() not in managed_before
    ]
    merged = user_lines + [cidr for cidr in sorted(wanted) if cidr not in user_lines]

    path = _exclude_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пустой файл zapret считает ошибкой конфигурации.
        body = "\n".join(merged) if merged else "203.0.113.113/32"
        path.write_text(body + "\n", encoding="utf-8")
    except OSError as exc:
        logs.warn(f"Не удалось обновить исключения zapret: {exc}")
        return len(wanted), False

    config.set(MANAGED_KEY, sorted(wanted))
    logs.info(f"В исключения zapret занесено адресов VPN: {len(wanted)}")
    return len(wanted), True


def clear_excludes() -> bool:
    """Убрать из исключений всё, что добавляла программа."""
    managed = set(config.get(MANAGED_KEY, []) or [])
    if not managed:
        return False
    remaining = [
        line for line in _read_lines()
        if line.strip() and line.strip() not in managed
    ]
    try:
        body = "\n".join(remaining) if remaining else "203.0.113.113/32"
        _exclude_path().write_text(body + "\n", encoding="utf-8")
    except OSError:
        return False
    config.set(MANAGED_KEY, [])
    logs.info("Адреса VPN убраны из исключений zapret")
    return True


def managed_count() -> int:
    return len(config.get(MANAGED_KEY, []) or [])
