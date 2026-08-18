"""Проверка доступности сервисов и автоподбор рабочей стратегии.

Логика подбора: сначала со снятым обходом смотрим, что именно не открывается,
затем перебираем стратегии и считаем, сколько из «сломанных» адресов ожили.
Проверять то, что и так работает, смысла нет — это только тратит время.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable

import requests

from app.core import engine as engine_module
from app.core import logs, paths
from app.core.constants import USER_AGENT
from app.core.strategies import Strategy

TEST_TIMEOUT = 6
SETTLE_SECONDS = 2.0
MAX_TARGETS = 7
MAX_WORKERS = 7


@dataclass(frozen=True)
class Target:
    key: str
    url: str

    @property
    def label(self) -> str:
        return re.sub(r"^https?://", "", self.url).rstrip("/")


@dataclass(frozen=True)
class ProbeResult:
    target: Target
    ok: bool
    ms: float


@dataclass
class StrategyScore:
    strategy: Strategy
    passed: int = 0
    total: int = 0
    latency_ms: float = 0.0
    results: list[ProbeResult] = field(default_factory=list)
    error: str = ""

    @property
    def ratio(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def is_perfect(self) -> bool:
        return self.total > 0 and self.passed == self.total


DEFAULT_TARGETS: tuple[Target, ...] = (
    Target("Discord", "https://discord.com"),
    Target("Discord Gateway", "https://gateway.discord.gg"),
    Target("Discord CDN", "https://cdn.discordapp.com"),
    Target("YouTube", "https://www.youtube.com"),
    Target("YouTube CDN", "https://i.ytimg.com"),
    Target("Google Video", "https://redirector.googlevideo.com"),
    Target("Google", "https://www.google.com"),
)


def load_targets() -> list[Target]:
    """Читаем utils/targets.txt, чтобы список рос вместе с апстримом."""
    path = paths.utils_dir() / "targets.txt"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(DEFAULT_TARGETS)

    targets: list[Target] = []
    pattern = re.compile(r'^\s*(\w+)\s*=\s*"([^"]+)"')
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if value.upper().startswith("PING:"):
            continue  # ICMP ничего не говорит о работе DPI
        targets.append(Target(_humanize(key), value))
    return targets or list(DEFAULT_TARGETS)


def _humanize(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z0-9])", " ", key).replace("_", " ").strip()


# --- одиночные проверки --------------------------------------------------


def _probe(target: Target, timeout: int = TEST_TIMEOUT) -> ProbeResult:
    """Новая сессия на каждую проверку: keep-alive скрыл бы смену стратегии."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    started = time.perf_counter()
    ok = False
    try:
        response = session.get(
            target.url, timeout=(timeout, timeout), stream=True, allow_redirects=True
        )
        ok = response.status_code < 500
        response.close()
    except requests.RequestException:
        ok = False
    finally:
        session.close()
    return ProbeResult(target, ok, (time.perf_counter() - started) * 1000)


def probe_all(targets: Iterable[Target], timeout: int = TEST_TIMEOUT) -> list[ProbeResult]:
    targets = list(targets)
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets))) as pool:
        return list(pool.map(lambda t: _probe(t, timeout), targets))


def quick_check() -> list[ProbeResult]:
    """Быстрая проверка для главной страницы."""
    return probe_all(load_targets()[:MAX_TARGETS])


# --- автоподбор ----------------------------------------------------------


class AutoTester:
    """Перебор стратегий с возможностью отмены."""

    def __init__(self) -> None:
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def find_blocked(self) -> tuple[list[Target], list[ProbeResult]]:
        """Что не открывается при выключенном обходе."""
        engine_module.engine.stop(quiet=True)
        time.sleep(1.0)
        results = probe_all(load_targets()[:MAX_TARGETS])
        blocked = [item.target for item in results if not item.ok]
        return blocked, results

    def evaluate(
        self,
        candidates: list[Strategy],
        targets: list[Target],
        mode: str = engine_module.MODE_PROCESS,
        on_progress: Callable[[int, int, Strategy], None] | None = None,
        on_result: Callable[[StrategyScore], None] | None = None,
    ) -> list[StrategyScore]:
        engine = engine_module.engine
        scores: list[StrategyScore] = []
        total = len(candidates)

        for index, strategy in enumerate(candidates, start=1):
            if self.cancelled:
                break
            if on_progress:
                on_progress(index, total, strategy)

            score = StrategyScore(strategy=strategy, total=len(targets))
            try:
                engine.start(strategy, mode)
            except engine_module.EngineError as exc:
                score.error = str(exc)
                logs.warn(f"Стратегия «{strategy.title}» не запустилась: {exc}")
                scores.append(score)
                if on_result:
                    on_result(score)
                continue

            time.sleep(SETTLE_SECONDS)
            if self.cancelled:
                engine.stop(quiet=True)
                break

            results = probe_all(targets)
            score.results = results
            score.passed = sum(1 for item in results if item.ok)
            latencies = [item.ms for item in results if item.ok]
            score.latency_ms = statistics.median(latencies) if latencies else 0.0

            engine.stop(quiet=True)
            scores.append(score)
            logs.info(
                f"Стратегия «{strategy.title}»: {score.passed}/{score.total} "
                f"({score.latency_ms:.0f} мс)"
            )
            if on_result:
                on_result(score)

            # Идеальный результат — дальше искать нечего.
            if score.is_perfect:
                break

        return sorted(
            scores,
            key=lambda item: (-item.passed, item.latency_ms or 10_000),
        )


def shortlist(all_strategies: list[Strategy]) -> list[Strategy]:
    """Самые ходовые стратегии для быстрого подбора."""
    preferred = [
        "general",
        "general (ALT)",
        "general (ALT2)",
        "general (FAKE TLS AUTO)",
        "general (FAKE TLS AUTO ALT)",
        "general (SIMPLE FAKE)",
        "general (ALT4)",
        "general (EXP)",
    ]
    by_id = {item.id: item for item in all_strategies}
    chosen = [by_id[key] for key in preferred if key in by_id]
    return chosen or all_strategies[:8]
