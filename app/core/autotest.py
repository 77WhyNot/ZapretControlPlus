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

from app.core import engine as engine_module
from app.core import logs, paths
from app.core.constants import USER_AGENT
from app.core.strategies import Strategy
from app.core.lazy import requests  # сеть подгружается при первом обращении

TEST_TIMEOUT = 6
# Автоподбор: секунды здесь умножаются на два десятка стратегий, поэтому
# ждём ровно столько, сколько нужно обходу, чтобы начать резать пакеты.
FAST_TIMEOUT = 3.0
SETTLE_SECONDS = 0.8
MAX_TARGETS = 10
MAX_WORKERS = 10

# Сначала гоняем все стратегии по нескольким «канарейкам» — этого хватает,
# чтобы отсеять нерабочие, — и только лучших проверяем по всему списку.
CANARY_TARGETS = 3
VERIFY_LIMIT = 3

STAGE_QUICK = "quick"
STAGE_FULL = "full"


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
    stage: str = STAGE_FULL      # quick — проверена бегло, full — по всем адресам

    @property
    def ratio(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def is_perfect(self) -> bool:
        return self.total > 0 and self.passed == self.total


DEFAULT_TARGETS: tuple[Target, ...] = (
    Target("ChatGPT", "https://chatgpt.com"),
    Target("Claude", "https://claude.ai"),
    Target("Gemini", "https://gemini.google.com"),
    Target("Discord", "https://discord.com"),
    Target("Discord Gateway", "https://gateway.discord.gg"),
    Target("Discord CDN", "https://cdn.discordapp.com"),
    Target("YouTube", "https://www.youtube.com"),
    Target("YouTube CDN", "https://i.ytimg.com"),
    Target("Google Video", "https://redirector.googlevideo.com"),
    Target("Google", "https://www.google.com"),
)


# Нейросети режут доступ по стране, поэтому проверять их особенно полезно.
AI_TARGETS: tuple[Target, ...] = (
    Target("ChatGPT", "https://chatgpt.com"),
    Target("Claude", "https://claude.ai"),
    Target("Gemini", "https://gemini.google.com"),
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
    # Нейросетей в списке апстрима нет — добавляем их всегда.
    known = {item.url for item in targets}
    for extra in AI_TARGETS:
        if extra.url not in known:
            targets.insert(0, extra)
    return targets or list(DEFAULT_TARGETS)


def _humanize(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z0-9])", " ", key).replace("_", " ").strip()


# --- одиночные проверки --------------------------------------------------


def _probe(target: Target, timeout: float = TEST_TIMEOUT,
           proxy_url: str | None = None) -> ProbeResult:
    """Новая сессия на каждую проверку: keep-alive скрыл бы смену стратегии."""
    session = requests.Session()
    session.trust_env = False
    # Когда VPN работает режимом «Прокси», проверяем именно через него —
    # иначе тест пойдёт мимо VPN по прямому каналу и покажет «недоступно».
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}
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


def probe_all(targets: Iterable[Target], timeout: float = TEST_TIMEOUT,
              proxy_url: str | None = None) -> list[ProbeResult]:
    targets = list(targets)
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets))) as pool:
        return list(pool.map(lambda t: _probe(t, timeout, proxy_url), targets))


def quick_check(proxy_url: str | None = None) -> list[ProbeResult]:
    """Быстрая проверка для главной страницы.

    proxy_url задаётся, когда VPN работает режимом «Прокси»: тогда проверка
    идёт через VPN, а не мимо него.
    """
    return probe_all(load_targets()[:MAX_TARGETS], proxy_url=proxy_url)


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
        time.sleep(0.6)
        results = probe_all(load_targets()[:MAX_TARGETS])
        blocked = [item.target for item in results if not item.ok]
        return blocked, results

    def evaluate(
        self,
        candidates: list[Strategy],
        targets: list[Target],
        mode: str = engine_module.MODE_PROCESS,
        on_progress: Callable[[int, int, Strategy, str], None] | None = None,
        on_result: Callable[[StrategyScore], None] | None = None,
    ) -> list[StrategyScore]:
        """Перебор в два прохода: быстрый отсев, затем полная проверка лучших.

        Гонять каждую стратегию по всему списку адресов долго и незачем:
        нерабочая стратегия не открывает и первый адрес. Поэтому сначала
        проверяем все стратегии по нескольким показательным адресам, а по
        всему списку — только тех, кто прошёл.
        """
        engine = engine_module.engine
        canary = _canary(targets)
        quick_only = len(canary) >= len(targets)
        scores: list[StrategyScore] = []
        total = len(candidates)

        try:
            for index, strategy in enumerate(candidates, start=1):
                if self.cancelled:
                    break
                if on_progress:
                    on_progress(index, total, strategy, STAGE_QUICK)

                score = self._measure(
                    strategy, canary, mode,
                    STAGE_FULL if quick_only else STAGE_QUICK,
                )
                scores.append(score)
                if on_result:
                    on_result(score)
                # Проверять было нечего кроме канареек — и они все открылись.
                if quick_only and score.is_perfect:
                    break

            # Второй проход: лучшие кандидаты — по всему списку адресов.
            if not quick_only and not self.cancelled:
                winners = sorted(
                    (item for item in scores if item.is_perfect),
                    key=lambda item: item.latency_ms or 10_000,
                )[:VERIFY_LIMIT]
                for position, quick in enumerate(winners, start=1):
                    if self.cancelled:
                        break
                    if on_progress:
                        on_progress(total, total, quick.strategy, STAGE_FULL)
                    logs.info(
                        f"Полная проверка ({position}/{len(winners)}): "
                        f"«{quick.strategy.title}»"
                    )
                    full = self._measure(quick.strategy, targets, mode, STAGE_FULL)
                    scores[scores.index(quick)] = full
                    if on_result:
                        on_result(full)
                    if full.is_perfect:
                        break
        finally:
            # Драйвер мы держали загруженным ради скорости — теперь уберём.
            engine.stop(quiet=True)

        return sorted(
            scores,
            key=lambda item: (
                0 if item.stage == STAGE_FULL else 1,
                -item.ratio,
                item.latency_ms or 10_000,
            ),
        )

    def _measure(self, strategy: Strategy, targets: list[Target], mode: str,
                 stage: str) -> StrategyScore:
        """Один замер: поднять стратегию, проверить адреса, снять."""
        engine = engine_module.engine
        score = StrategyScore(strategy=strategy, total=len(targets), stage=stage)
        try:
            engine.start(strategy, mode, quick=True)
        except engine_module.EngineError as exc:
            score.error = str(exc)
            logs.warn(f"Стратегия «{strategy.title}» не запустилась: {exc}")
            return score

        time.sleep(SETTLE_SECONDS)
        if self.cancelled:
            engine.stop(quiet=True, keep_driver=True)
            return score

        timeout = FAST_TIMEOUT if stage == STAGE_QUICK else TEST_TIMEOUT
        results = probe_all(targets, timeout=timeout)
        if stage == STAGE_FULL:
            # Один раз перепроверяем неответившие: сеть иногда моргает, а
            # из-за случайной осечки хорошая стратегия уходит вниз списка.
            retry = [item.target for item in results if not item.ok]
            if retry and not self.cancelled:
                fixed = {item.target.url: item for item in probe_all(retry, timeout)}
                results = [fixed.get(item.target.url, item) for item in results]

        score.results = results
        score.passed = sum(1 for item in results if item.ok)
        latencies = [item.ms for item in results if item.ok]
        score.latency_ms = statistics.median(latencies) if latencies else 0.0

        engine.stop(quiet=True, keep_driver=True)
        logs.info(
            f"Стратегия «{strategy.title}»: {score.passed}/{score.total} "
            f"({score.latency_ms:.0f} мс, "
            f"{'бегло' if stage == STAGE_QUICK else 'полностью'})"
        )
        return score


def _canary(targets: list[Target]) -> list[Target]:
    """Несколько показательных адресов из начала, середины и конца списка.

    Берём разные: нейросети, видео и Discord блокируются по-разному, и
    стратегия, открывшая только один из них, нам не подходит.
    """
    if len(targets) <= CANARY_TARGETS:
        return list(targets)
    positions = sorted({0, len(targets) // 2, len(targets) - 1})
    return [targets[index] for index in positions]


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
