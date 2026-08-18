"""Журнал приложения: файл + кольцевой буфер для интерфейса."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Callable, Iterable

from app.core import paths

MAX_LINES = 2000
MAX_FILE_BYTES = 1_500_000

_lock = threading.RLock()
_buffer: deque[str] = deque(maxlen=MAX_LINES)
_listeners: list[Callable[[str], None]] = []


def _rotate_if_needed() -> None:
    path = paths.log_path()
    try:
        if path.exists() and path.stat().st_size > MAX_FILE_BYTES:
            backup = path.with_suffix(".old.log")
            backup.unlink(missing_ok=True)
            path.rename(backup)
    except OSError:
        pass


def write(message: str, level: str = "INFO") -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {level:<5} {message}"
    with _lock:
        _buffer.append(line)
        listeners = list(_listeners)
    try:
        _rotate_if_needed()
        full = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with paths.log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"{full} {level:<5} {message}\n")
    except OSError:
        pass
    for listener in listeners:
        try:
            listener(line)
        except Exception:  # noqa: BLE001 — журнал не должен ронять приложение
            pass


def info(message: str) -> None:
    write(message, "INFO")


def warn(message: str) -> None:
    write(message, "WARN")


def error(message: str) -> None:
    write(message, "ERROR")


def lines() -> list[str]:
    with _lock:
        return list(_buffer)


def clear() -> None:
    with _lock:
        _buffer.clear()


def subscribe(listener: Callable[[str], None]) -> None:
    with _lock:
        _listeners.append(listener)


def unsubscribe(listener: Callable[[str], None]) -> None:
    with _lock:
        if listener in _listeners:
            _listeners.remove(listener)


def extend(new_lines: Iterable[str]) -> None:
    for line in new_lines:
        write(line, "WINWS")
