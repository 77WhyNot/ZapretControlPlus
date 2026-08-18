"""Замер задержки до серверов.

Когда туннель поднят, спрашиваем сам движок — он меряет полный путь через
прокси. Когда выключен, меряем время установки TCP-соединения: это не то же
самое, но позволяет сравнить серверы между собой, не поднимая туннель.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.vpn.links import Server

TIMEOUT = 3.0
WORKERS = 8


def tcp_latency(host: str, port: int, timeout: float = TIMEOUT) -> int:
    """Миллисекунды до установки соединения. -1 — не ответил."""
    try:
        info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return -1
    if not info:
        return -1

    family, socktype, proto, _, address = info[0]
    started = time.perf_counter()
    connection = socket.socket(family, socktype, proto)
    connection.settimeout(timeout)
    try:
        connection.connect(address)
    except (OSError, socket.timeout):
        return -1
    finally:
        try:
            connection.close()
        except OSError:
            pass
    return int((time.perf_counter() - started) * 1000)


def measure_all(servers: list[Server], timeout: float = TIMEOUT) -> dict[str, int]:
    """Задержка до каждого сервера: {имя сервера: мс}."""
    if not servers:
        return {}

    def measure(server: Server) -> tuple[str, int]:
        return server.name, tcp_latency(server.host, server.port, timeout)

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(servers))) as pool:
        return dict(pool.map(measure, servers))


def quality(latency: int) -> str:
    """Как показать задержку: хорошо / средне / плохо / нет ответа."""
    if latency < 0:
        return "dead"
    if latency <= 80:
        return "good"
    if latency <= 180:
        return "fair"
    return "poor"
