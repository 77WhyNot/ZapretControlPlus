"""Telegram через WebSocket: локальный MTProto-прокси внутри программы.

Ядро — tg-ws-proxy от Flowseal (MIT), лежит в ``app/vendor/tgwsproxy``.
Telegram Desktop подключается к 127.0.0.1:1443 как к обычному MTProto-прокси,
а прокси заворачивает трафик в WebSocket до серверов Telegram. Сторонних
серверов нет, данные остаются зашифрованными самим Telegram.

Прокси крутится в отдельном потоке со своим циклом asyncio, чтобы не
мешать интерфейсу; остановка — через событие внутри этого цикла.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass

from app.core import logs
from app.core.config import config

DEFAULT_PORT = 1443
HOST = "127.0.0.1"
START_TIMEOUT = 8.0
STOP_TIMEOUT = 8.0


class TgWsError(RuntimeError):
    pass


@dataclass(frozen=True)
class TgWsStatus:
    running: bool
    port: int
    active: int = 0
    total: int = 0
    websocket: int = 0
    fallback: int = 0
    bytes_up: int = 0
    bytes_down: int = 0
    uptime: int = 0
    error: str = ""


class _LogBridge(logging.Handler):
    """Пробрасывает журнал прокси в журнал программы."""

    SKIP = ("====", "Connect:", "tg://proxy", "Secret:", "Target DC", "DC1:",
            "DC2:", "DC3:", "DC4:", "DC5:", "CF proxy", "CF worker",
            "Listening on", "Telegram MTProto WS Bridge Proxy")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if any(marker in text for marker in self.SKIP):
            return
        if record.levelno >= logging.ERROR:
            logs.error(f"TG WS: {text}")
        elif record.levelno >= logging.WARNING:
            logs.warn(f"TG WS: {text}")
        elif record.levelno >= logging.INFO:
            logs.info(f"TG WS: {text}")


def _humanize(exc: BaseException, port: int) -> str:
    text = str(exc)
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (10048, 98, 48):
        return (f"Порт {port} уже занят другой программой — возможно, отдельно "
                "запущен TG WS Proxy. Закройте его или смените порт в настройках.")
    if isinstance(exc, PermissionError):
        return f"Windows не разрешает открыть порт {port}. Попробуйте другой порт."
    return text or type(exc).__name__


class TgWsEngine:
    """Запуск, остановка и состояние прокси."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._bound = False
        self._error = ""
        self._started_at = 0.0
        self._bridge: _LogBridge | None = None

    # --- настройки -------------------------------------------------------

    @staticmethod
    def port() -> int:
        try:
            value = int(config.get("tg_ws_port", DEFAULT_PORT))
        except (TypeError, ValueError):
            value = DEFAULT_PORT
        return value if 1 <= value <= 65535 else DEFAULT_PORT

    @staticmethod
    def secret() -> str:
        """Секрет прокси: создаётся один раз и хранится в настройках."""
        stored = str(config.get("tg_ws_secret", "") or "")
        if len(stored) == 32 and all(ch in "0123456789abcdef" for ch in stored.lower()):
            return stored.lower()
        fresh = os.urandom(16).hex()
        config.set("tg_ws_secret", fresh)
        return fresh

    def link(self) -> str:
        return f"tg://proxy?server={HOST}&port={self.port()}&secret=dd{self.secret()}"

    def web_link(self) -> str:
        """Та же ссылка через t.me — открывается и из браузера."""
        return f"https://t.me/proxy?server={HOST}&port={self.port()}&secret=dd{self.secret()}"

    # --- состояние -------------------------------------------------------

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and self._bound)

    def status(self) -> TgWsStatus:
        from app.vendor.tgwsproxy.stats import stats

        running = self.is_running()
        return TgWsStatus(
            running=running,
            port=self.port(),
            active=stats.connections_active if running else 0,
            total=stats.connections_total if running else 0,
            websocket=stats.connections_ws if running else 0,
            fallback=(stats.connections_tcp_fallback + stats.connections_cfproxy)
            if running else 0,
            bytes_up=stats.bytes_up if running else 0,
            bytes_down=stats.bytes_down if running else 0,
            uptime=int(time.time() - self._started_at) if running else 0,
            error=self._error,
        )

    # --- запуск и остановка ----------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            if self._thread and self._thread.is_alive():
                self.stop()

            from app.vendor.tgwsproxy import tg_ws_proxy as engine_module
            from app.vendor.tgwsproxy.config import proxy_config

            proxy_config.host = HOST
            proxy_config.port = self.port()
            proxy_config.secret = self.secret()
            proxy_config.fallback_cfproxy = True

            if self._bridge is None:
                self._bridge = _LogBridge()
                logger = logging.getLogger("tg-mtproto-proxy")
                logger.setLevel(logging.INFO)
                logger.addHandler(self._bridge)
                logger.propagate = False

            self._ready.clear()
            self._bound = False
            self._error = ""
            self._thread = threading.Thread(
                target=self._thread_main, args=(engine_module,),
                name="tg-ws-proxy", daemon=True,
            )
            self._thread.start()

        if not self._ready.wait(START_TIMEOUT):
            self.stop()
            raise TgWsError("Прокси не ответил за отведённое время.")
        if not self._bound:
            message = self._error or "Прокси не смог открыть порт."
            self._thread = None
            raise TgWsError(message)
        self._started_at = time.time()
        logs.info(f"Telegram WS-прокси запущен на {HOST}:{self.port()}")

    def _thread_main(self, engine_module) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def runner() -> None:
            self._stop_event = asyncio.Event()
            task = asyncio.ensure_future(engine_module._run(self._stop_event))
            for _ in range(int(START_TIMEOUT * 20)):
                if engine_module._server_instance is not None:
                    self._bound = True
                    self._ready.set()
                    break
                if task.done():
                    break
                await asyncio.sleep(0.05)
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            loop.run_until_complete(runner())
        except Exception as exc:  # noqa: BLE001
            self._error = _humanize(exc, self.port())
            logs.warn(f"Telegram WS-прокси остановился: {self._error}")
        finally:
            self._bound = False
            self._ready.set()
            # Пул заготовленных WebSocket-соединений продолжает подключаться
            # и после остановки сервера — без отмены Python ругается на каждую
            # брошенную задачу при закрытии цикла.
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                # Даём TLS-транспортам закрыться, пока цикл ещё жив.
                loop.run_until_complete(asyncio.sleep(0.3))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                pass
            loop.close()
            self._loop = None
            self._stop_event = None

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            loop = self._loop
            event = self._stop_event
            if thread is None or not thread.is_alive():
                self._thread = None
                self._bound = False
                return
            if loop is not None and event is not None:
                try:
                    loop.call_soon_threadsafe(event.set)
                except RuntimeError:
                    pass
        thread.join(STOP_TIMEOUT)
        with self._lock:
            self._thread = None
            self._bound = False
        logs.info("Telegram WS-прокси остановлен")


tgws_engine = TgWsEngine()


def desired_enabled() -> bool:
    return bool(config.get("tg_ws_enabled", False))


def set_desired_enabled(value: bool) -> None:
    config.set("tg_ws_enabled", bool(value))
