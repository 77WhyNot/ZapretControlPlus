"""Замер скорости интернета прямо в программе.

Меряем тем же путём, которым сейчас ходит трафик: если поднят VPN режимом
«Прокси», запросы идут через него — иначе цифры были бы не про то соединение,
которым человек пользуется.

Источник — открытые адреса Cloudflare (``speed.cloudflare.com``): они есть
в каждой стране, отдают сколько попросишь и не требуют ключей. Если
Cloudflare недоступен, загрузку меряем по запасным зеркалам, а отдачу
честно помечаем как неизмеренную.
"""

from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from app.core import logs
from app.core.constants import USER_AGENT
from app.core.lazy import requests  # сеть подгружается при первом обращении

CLOUDFLARE_DOWN = "https://speed.cloudflare.com/__down?bytes={bytes}"
CLOUDFLARE_UP = "https://speed.cloudflare.com/__up"
# Больше 100 МБ за раз Cloudflare не отдаёт (отвечает 403), поэтому берём
# порциями и повторяем запрос, пока не кончится отведённое время.
DOWNLOAD_PORTION = 25 * 1024 * 1024

# Запасные адреса на случай, если Cloudflare не открывается: только загрузка.
FALLBACK_DOWN = (
    "https://cachefly.cachefly.net/50mb.test",
    "https://proof.ovh.net/files/100Mb.dat",
)

PING_TRIES = 6
DOWNLOAD_SECONDS = 8.0
UPLOAD_SECONDS = 6.0
WARMUP_SECONDS = 1.2      # разгон TCP в счёт не идёт, иначе цифра занижена
DOWNLOAD_STREAMS = 4
UPLOAD_STREAMS = 3
CHUNK = 64 * 1024
UPLOAD_BLOCK = 4 * 1024 * 1024

Progress = Callable[[str, float], None]

STAGE_PING = "ping"
STAGE_DOWNLOAD = "download"
STAGE_UPLOAD = "upload"


@dataclass
class SpeedResult:
    """Итог замера. Нули означают «померить не удалось»."""

    download_mbps: float = 0.0
    upload_mbps: float = 0.0
    ping_ms: float = 0.0
    jitter_ms: float = 0.0
    source: str = ""
    route: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.download_mbps > 0


class Cancelled(RuntimeError):
    """Замер прерван пользователем."""


class SpeedTest:
    """Один замер. Создаём на каждый запуск — так проще отменять."""

    def __init__(self, proxy_url: str | None = None,
                 on_progress: Progress | None = None) -> None:
        self.proxy_url = proxy_url
        self.on_progress = on_progress
        self.cancel_event = threading.Event()
        self._bytes = 0
        self._lock = threading.Lock()

    # --- служебное -------------------------------------------------------

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _guard(self) -> None:
        if self.cancelled:
            raise Cancelled("Замер отменён.")

    def _session(self) -> requests.Session:
        session = requests.Session()
        # Системный прокси нас не касается: путь выбираем сами.
        session.trust_env = False
        if self.proxy_url:
            session.proxies = {"http": self.proxy_url, "https": self.proxy_url}
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        return session

    def _report(self, stage: str, mbps: float) -> None:
        if self.on_progress is not None:
            try:
                self.on_progress(stage, mbps)
            except Exception:  # noqa: BLE001 — интерфейс не должен ронять замер
                pass

    def _add(self, count: int) -> None:
        with self._lock:
            self._bytes += count

    def _read(self) -> int:
        with self._lock:
            return self._bytes

    # --- задержка --------------------------------------------------------

    def ping(self) -> tuple[float, float]:
        """Задержка и разброс: маленький запрос без тела."""
        session = self._session()
        samples: list[float] = []
        try:
            for index in range(PING_TRIES):
                self._guard()
                started = time.perf_counter()
                try:
                    response = session.get(
                        CLOUDFLARE_DOWN.format(bytes=0), timeout=(4, 4)
                    )
                    response.close()
                except requests.RequestException:
                    continue
                elapsed = (time.perf_counter() - started) * 1000
                # Первый запрос оплачивает установку соединения и TLS.
                if index:
                    samples.append(elapsed)
                    self._report(STAGE_PING, min(samples))
        finally:
            session.close()

        if not samples:
            return 0.0, 0.0
        jitter = 0.0
        if len(samples) > 1:
            # Медиана, а не среднее: один случайно подвисший запрос иначе
            # раздувает разброс до величин, которых на связи нет.
            jitter = statistics.median(
                abs(b - a) for a, b in zip(samples, samples[1:])
            )
        return min(samples), jitter

    # --- загрузка --------------------------------------------------------

    def download(self) -> tuple[float, str]:
        """Несколько потоков сразу: одним каналом широкий интернет не насытить."""
        for url in (CLOUDFLARE_DOWN.format(bytes=DOWNLOAD_PORTION),) + FALLBACK_DOWN:
            speed = self._download_from(url)
            if speed > 0:
                return speed, url.split("/")[2]
            self._guard()
            logs.warn(f"Замер скорости: {url.split('/')[2]} не ответил, пробую дальше")
        return 0.0, ""

    def _download_from(self, url: str) -> float:
        with self._lock:
            self._bytes = 0
        deadline = time.time() + DOWNLOAD_SECONDS
        marks: dict[str, tuple[float, int]] = {}
        alive = threading.Event()

        def stream() -> None:
            session = self._session()
            try:
                # Порция кончилась, а время ещё есть — просим следующую.
                while not self.cancelled and time.time() < deadline:
                    response = session.get(url, stream=True, timeout=(5, 8))
                    if response.status_code >= 400:
                        return
                    alive.set()
                    for block in response.iter_content(CHUNK):
                        if not block:
                            break
                        self._add(len(block))
                        if self.cancelled or time.time() >= deadline:
                            break
                    response.close()
            except requests.RequestException:
                return
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=DOWNLOAD_STREAMS) as pool:
            futures = [pool.submit(stream) for _ in range(DOWNLOAD_STREAMS)]
            started = time.time()
            while time.time() < deadline:
                time.sleep(0.2)
                now = time.time()
                if "warm" not in marks and now - started >= WARMUP_SECONDS:
                    marks["warm"] = (now, self._read())
                if "warm" in marks:
                    base_time, base_bytes = marks["warm"]
                    seconds = now - base_time
                    if seconds > 0.3:
                        self._report(
                            STAGE_DOWNLOAD,
                            (self._read() - base_bytes) * 8 / seconds / 1_000_000,
                        )
                if self.cancelled or all(future.done() for future in futures):
                    break
            finished = time.time()
            for future in futures:
                future.result()

        if not alive.is_set():
            return 0.0
        self._guard()
        base_time, base_bytes = marks.get("warm", (started, 0))
        seconds = max(finished - base_time, 0.001)
        total = self._read() - base_bytes
        if total < 256 * 1024:
            return 0.0
        return total * 8 / seconds / 1_000_000

    # --- отдача ----------------------------------------------------------

    def upload(self) -> float:
        with self._lock:
            self._bytes = 0
        deadline = time.time() + UPLOAD_SECONDS
        block = b"\0" * CHUNK
        alive = threading.Event()

        def feed():
            """Данные отдаём кусками и считаем по ходу, а не одним куском."""
            sent = 0
            while sent < UPLOAD_BLOCK:
                if self.cancelled or time.time() >= deadline:
                    return
                yield block
                sent += len(block)
                self._add(len(block))

        def stream() -> None:
            session = self._session()
            try:
                while not self.cancelled and time.time() < deadline:
                    response = session.post(
                        CLOUDFLARE_UP, data=feed(), timeout=(5, 12),
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    alive.set()
                    response.close()
            except requests.RequestException:
                return
            finally:
                session.close()

        marks: dict[str, tuple[float, int]] = {}
        with ThreadPoolExecutor(max_workers=UPLOAD_STREAMS) as pool:
            futures = [pool.submit(stream) for _ in range(UPLOAD_STREAMS)]
            started = time.time()
            while time.time() < deadline:
                time.sleep(0.2)
                now = time.time()
                if "warm" not in marks and now - started >= WARMUP_SECONDS:
                    marks["warm"] = (now, self._read())
                if "warm" in marks:
                    base_time, base_bytes = marks["warm"]
                    seconds = now - base_time
                    if seconds > 0.3:
                        self._report(
                            STAGE_UPLOAD,
                            (self._read() - base_bytes) * 8 / seconds / 1_000_000,
                        )
                if self.cancelled or all(future.done() for future in futures):
                    break
            finished = time.time()
            for future in futures:
                future.result()

        if not alive.is_set():
            return 0.0
        self._guard()
        base_time, base_bytes = marks.get("warm", (started, 0))
        seconds = max(finished - base_time, 0.001)
        total = self._read() - base_bytes
        if total < 128 * 1024:
            return 0.0
        return total * 8 / seconds / 1_000_000

    # --- всё вместе ------------------------------------------------------

    def run(self) -> SpeedResult:
        result = SpeedResult(route=describe_route())
        logs.info(f"Замер скорости ({result.route or 'напрямую'})")

        result.ping_ms, result.jitter_ms = self.ping()
        if not result.ping_ms:
            result.notes.append(
                "Сервер замера не отвечает. Проверьте интернет или включите обход."
            )

        result.download_mbps, result.source = self.download()
        if not result.download_mbps:
            result.notes.append("Загрузку измерить не удалось — сервер не ответил.")
            return result

        result.upload_mbps = self.upload()
        if not result.upload_mbps:
            result.notes.append("Отдачу измерить не удалось — сервер не принял данные.")

        logs.info(
            f"Скорость: загрузка {result.download_mbps:.1f} Мбит/с, "
            f"отдача {result.upload_mbps:.1f} Мбит/с, "
            f"задержка {result.ping_ms:.0f} мс ({result.source or '—'})"
        )
        return result


def describe_route(vpn=None, zapret_running: bool | None = None) -> str:
    """Каким путём пойдёт замер — это половина смысла результата.

    Окно передаёт состояние из своего последнего опроса: спрашивать службу
    Windows прямо из окна — это заметная пауза.
    """
    from app.core.engine import engine
    from app.core.vpn import config as vpn_config
    from app.core.vpn.engine import vpn_engine

    parts: list[str] = []
    if vpn is None:
        vpn = vpn_engine.status()
    if zapret_running is None:
        zapret_running = engine.status().running
    if vpn.running:
        parts.append(
            "через VPN (туннель)"
            if vpn.transport == vpn_config.TRANSPORT_TUN else "через VPN (прокси)"
        )
    if zapret_running:
        parts.append("с обходом DPI")
    return " ".join(parts) if parts else "напрямую"


def format_speed(mbps: float) -> str:
    if mbps <= 0:
        return "—"
    if mbps >= 100:
        return f"{mbps:.0f}"
    if mbps >= 10:
        return f"{mbps:.1f}"
    return f"{mbps:.2f}"


def verdict(result: SpeedResult) -> str:
    """Короткий человеческий вывод: цифры сами по себе мало что говорят."""
    if not result.ok:
        return "Замер не удался."
    speed = result.download_mbps
    if speed >= 90:
        quality = "Хватит на 4K, игры и несколько устройств сразу."
    elif speed >= 45:
        quality = "Хватит на 4K-видео и онлайн-игры."
    elif speed >= 20:
        quality = "Хватит на Full HD-видео и звонки."
    elif speed >= 8:
        quality = "Хватит на HD-видео, но большие файлы будут идти медленно."
    else:
        quality = "Низкая скорость: видео будет подтормаживать."
    if result.ping_ms and result.ping_ms > 180:
        quality += " Задержка большая — в играх будет заметно."
    return quality
