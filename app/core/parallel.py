"""Проверка всех стратегий разом.

Как это устроено. Для каждой стратегии запускается свой winws, но перехватывает
он не весь трафик, а только соединения со своего диапазона локальных портов
(полный фильтр WinDivert через --wf-raw). Проверочные соединения программа
открывает сама — каждое со своего порта, — поэтому каждая копия winws
обрабатывает только «свои» и не мешает соседним. Два десятка стратегий
проверяются за несколько секунд вместо пары минут перебора по одной.

Соединения идут через настоящий адаптер (IP_UNICAST_IF), мимо туннеля VPN:
иначе туннель подхватил бы их и отправил дальше уже со своих портов.

Проверено на практике: копии не видят чужих соединений, результат совпадает с
поочерёдной проверкой. Работающий обход на время проверки нужно снять — он
перехватывает те же пакеты.
"""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import statistics
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

from app.core import logs, paths, winapi
from app.core.autotest import STAGE_FULL, ProbeResult, StrategyScore, Target
from app.core.constants import USER_AGENT
from app.core.strategies import Strategy

# Диапазоны портов для проверки: ниже динамических портов Windows
# (49152–65535), откуда берут порты все остальные программы, — поэтому копии
# winws не заденут чужие соединения.
PORT_FIRST = 31000
PORT_LAST = 47999
PORT_SPAN = 40                 # портов на стратегию: хватает и на повторы
MAX_INSTANCES = 32             # больше за раз не запускаем — по ~8 МБ на копию
# Порты для проверки «без обхода» — отдельно, тоже ниже динамических.
BASELINE_FIRST = PORT_LAST + 1
BASELINE_LAST = 49151
BASELINE_SPAN = 128

PROBE_TIMEOUT = 4.0
RETRY_TIMEOUT = 4.0
# Без обхода заблокированный сайт просто молчит — ждать его дольше незачем.
BASELINE_TIMEOUT = 3.0
READY_TIMEOUT = 6.0            # сколько ждём «capture is started» от копий
START_GAP = 0.05               # пауза между запусками копий
# Все проверки — одной волной: иначе при двух десятках стратегий они шли бы
# несколькими заходами по четыре секунды.
PROBE_WORKERS = 128
# Заблокированных адресов для сравнения хватает восьми: в списке апстрима это
# Discord и YouTube — ради них обход в основном и ставят.
MAX_TESTED = 8
IP_UNICAST_IF = 31
WSAEADDRINUSE = 10048
WINWS_READY = "capture is started"
TEST_DIR = "strategy-test"
PIDS_FILE = "pids.json"
# Что вернуть, если программу закроют или она упадёт посреди проверки.
# Лежит не в TEST_DIR: ту папку уборка копий стирает целиком.
RESTORE_FILE = "restore-after-check.json"
CREATE_NO_WINDOW = 0x08000000

# Ключи, которые задают фильтр перехвата: их заменяет наш --wf-raw.
WINDIVERT_KEYS = ("--wf-tcp=", "--wf-udp=", "--wf-raw-part=", "--wf-raw=", "--wf-l3=",
                  "--wf-iface=", "--wf-save=")

EVENT_PHASE = "phase"          # (text)
EVENT_BASELINE = "baseline"    # (list[ProbeResult]) — что открывается без обхода
EVENT_STARTED = "started"      # ((list[Strategy], list[Target])) — что и на чём проверяем
EVENT_RESULT = "result"        # (StrategyScore) — итог одной стратегии
EVENT_RETRY = "retry"          # (int) — сколько проверок повторяем

Event = Callable[[str, object], None]


class ParallelUnavailable(RuntimeError):
    """Разом проверить нельзя — нужен обычный перебор по одной."""


# Живые проверочные копии: при выходе из программы посреди проверки их снимает
# engine.shutdown через kill_running().
_live: set[subprocess.Popen] = set()
_live_lock = threading.Lock()


def kill_running() -> int:
    with _live_lock:
        processes = list(_live)
        _live.clear()
    killed = 0
    for process in processes:
        if process.poll() is None:
            try:
                process.kill()
                killed += 1
            except OSError:
                pass
    return killed


class Cancelled(RuntimeError):
    pass


@dataclass
class Host:
    target: Target
    host: str
    address: tuple[str, int] | None = None


@dataclass
class ParallelReport:
    scores: list[StrategyScore] = field(default_factory=list)
    baseline: list[ProbeResult] = field(default_factory=list)
    blocked: list[Target] = field(default_factory=list)
    seconds: float = 0.0
    note: str = ""                   # сравнивать не на чем: всё открывается и так
    problem: str = ""                # сравнивать не на чем из-за сбоя (например, DNS)

    @property
    def best(self) -> StrategyScore | None:
        good = [score for score in self.scores if score.passed and not score.error]
        return good[0] if good else None


def _host_of(target: Target) -> str:
    return urlsplit(target.url).hostname or ""


# --- проверочное соединение ----------------------------------------------


class _Ports:
    """Выдаёт порты по порядку внутри своего диапазона, каждый по разу.

    Порт, закрытый недавно, Windows ещё держит в TIME_WAIT, поэтому повторно
    его не берём — у каждой проверки свой.
    """

    def __init__(self, low: int, high: int) -> None:
        self.low, self.high = low, high
        self._next = low
        self._lock = threading.Lock()

    def take(self) -> int | None:
        with self._lock:
            if self._next > self.high:
                return None
            port = self._next
            self._next += 1
            return port


# С каких портов начнёт следующая проверка — чтобы «Проверить заново» через
# минуту не попадала на порты, которые ещё в TIME_WAIT после прошлой.
_cursor_lock = threading.Lock()
_next_range = PORT_FIRST
_next_baseline = BASELINE_FIRST


def _baseline_ports() -> _Ports:
    global _next_baseline
    with _cursor_lock:
        low = _next_baseline
        if low + BASELINE_SPAN - 1 > BASELINE_LAST:
            low = BASELINE_FIRST
        _next_baseline = low + BASELINE_SPAN
    return _Ports(low, low + BASELINE_SPAN - 1)


def probe(host: Host, ports: _Ports, iface: winapi.PhysicalInterface,
          timeout: float) -> ProbeResult:
    """TLS-рукопожатие и первая строка ответа HTTP — как в браузере, но с
    нашего порта и через настоящий адаптер."""
    started = time.perf_counter()
    deadline = started + timeout
    ok = False
    for _attempt in range(6):
        port = ports.take()
        if port is None or host.address is None:
            break
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if iface.index:
                # Номер адаптера — в сетевом порядке байт. Байтами, а не числом:
                # при номере от 128 htonl() не влезает в int, и setsockopt падал.
                sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF,
                                struct.pack("!I", iface.index))
            try:
                sock.bind((iface.address, port))
            except OSError:
                continue  # порт занят или зарезервирован системой — берём следующий
            sock.settimeout(max(0.2, deadline - time.perf_counter()))
            try:
                sock.connect(host.address)
            except OSError as exc:
                if getattr(exc, "winerror", None) == WSAEADDRINUSE:
                    # К этому адресу с этого порта недавно ходили, и связь
                    # ещё в TIME_WAIT (повторная проверка) — берём следующий.
                    continue
                raise
            context = ssl.create_default_context()
            with context.wrap_socket(sock, server_hostname=host.host) as tls:
                tls.settimeout(max(0.2, deadline - time.perf_counter()))
                tls.sendall(
                    f"GET / HTTP/1.1\r\nHost: {host.host}\r\nUser-Agent: {USER_AGENT}\r\n"
                    "Accept: */*\r\nConnection: close\r\n\r\n".encode("ascii")
                )
                ok = tls.recv(16).startswith(b"HTTP/")
            break
        except (OSError, ssl.SSLError, ValueError):
            break
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return ProbeResult(host.target, ok, (time.perf_counter() - started) * 1000)


# --- копии winws ---------------------------------------------------------


@dataclass
class _Instance:
    strategy: Strategy
    ports: _Ports
    process: subprocess.Popen | None = None
    ready: threading.Event = field(default_factory=threading.Event)
    output: list[str] = field(default_factory=list)
    error: str = ""


def _test_dir():
    return paths.data_dir() / TEST_DIR


def _filter_rule(low: int, high: int) -> str:
    return (
        "!impostor and !loopback and ("
        f"(outbound and tcp.SrcPort >= {low} and tcp.SrcPort <= {high}) or "
        f"(inbound and tcp.DstPort >= {low} and tcp.DstPort <= {high}))"
    )


def _arguments(instance: _Instance) -> list[str]:
    """Аргументы копии: стратегия как есть, но свой фильтр перехвата.

    Фильтр передаём прямо в командной строке, а не файлом: из папки
    программы winws файл фильтра прочитать не смог («could not read»).
    """
    tokens = [token for token in instance.strategy.tokens
              if not token.startswith(WINDIVERT_KEYS)]
    rule = _filter_rule(instance.ports.low, instance.ports.high)
    return [str(paths.winws_path()), *tokens, f"--wf-raw={rule}"]


def _watch(instance: _Instance) -> None:
    """Ждём от копии «capture is started» и копим её вывод на случай ошибки."""
    process = instance.process
    if process is None or process.stdout is None:
        return
    try:
        for raw in iter(process.stdout.readline, b""):
            line = winapi.decode_console(raw).rstrip()
            if not line:
                continue
            if len(instance.output) < 40:
                instance.output.append(line)
            if WINWS_READY in line:
                instance.ready.set()
    except (OSError, ValueError):
        pass
    finally:
        instance.ready.set()


def _remember(instances: list[_Instance]) -> None:
    """Номера своих копий — на случай, если программа упадёт посреди проверки."""
    records = []
    for item in instances:
        if item.process is not None:
            records.append({"pid": item.process.pid,
                            "started": winapi.process_started(item.process.pid)})
    try:
        (_test_dir() / PIDS_FILE).write_text(json.dumps(records), encoding="utf-8")
    except OSError:
        pass


def cleanup_leftovers() -> int:
    """Снять копии, оставшиеся от прерванной проверки. Только свои: по номеру
    процесса и времени его запуска."""
    path = _test_dir() / PIDS_FILE
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        records = []
    killed = 0
    winws = str(paths.winws_path())
    for record in records if isinstance(records, list) else []:
        try:
            pid, started = int(record["pid"]), int(record["started"])
        except (KeyError, TypeError, ValueError):
            continue
        if started and winapi.process_started(pid) == started \
                and pid in winapi.find_processes_by_path("winws.exe", winws):
            killed += winapi.kill_pid(pid)
    shutil.rmtree(_test_dir(), ignore_errors=True)
    if killed:
        logs.info(f"Сняты копии winws от прерванной проверки: {killed}")
    return killed


# --- сама проверка -------------------------------------------------------


class ParallelTester:
    """Все стратегии разом. Вызывается из фонового потока; отменяется cancel()."""

    def __init__(self) -> None:
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _guard(self) -> None:
        if self.cancelled:
            raise Cancelled("Проверка отменена.")

    def run(self, candidates: list[Strategy], targets: list[Target],
            on_event: Event | None = None) -> ParallelReport:
        try:
            return self._run(candidates, targets, on_event or (lambda _kind, _payload: None))
        except (ParallelUnavailable, Cancelled):
            raise
        except Exception as exc:  # noqa: BLE001
            # Неожиданный сбой сокетов или драйвера — не повод оставить без
            # проверки: пусть идёт обычный перебор по одной. Копии к этому
            # моменту уже сняты (finally в _run_batch).
            logs.warn(f"Проверка разом сорвалась: {exc!r}")
            raise ParallelUnavailable(f"сбой проверки разом: {exc}") from exc

    def _run(self, candidates: list[Strategy], targets: list[Target],
             emit: Event) -> ParallelReport:
        started = time.perf_counter()
        report = ParallelReport()

        iface = winapi.physical_interface()
        if iface is None:
            raise ParallelUnavailable("Не найден сетевой адаптер с выходом в интернет.")
        if not paths.winws_path().exists():
            raise ParallelUnavailable("Не найден winws.exe.")

        cleanup_leftovers()
        folder = _test_dir()
        folder.mkdir(parents=True, exist_ok=True)
        # Стратегии с fooling=ts без меток времени TCP не работают — движок
        # включает их при каждом запуске, проверка тоже.
        winapi.enable_tcp_timestamps()

        emit(EVENT_PHASE, "Узнаём адреса сайтов…")
        hosts = self._resolve(targets)
        self._guard()

        # Что открывается и без обхода — там стратегиям нечего доказывать.
        emit(EVENT_PHASE, "Смотрим, что заблокировано…")
        baseline_ports = _baseline_ports()
        report.baseline = self._probe_many(
            [(host, baseline_ports) for host in hosts], iface, BASELINE_TIMEOUT)
        emit(EVENT_BASELINE, list(report.baseline))
        blocked_urls = {item.target.url for item in report.baseline if not item.ok}
        tested = [host for host in hosts
                  if host.target.url in blocked_urls and host.address][:MAX_TESTED]
        report.blocked = [host.target for host in tested]
        if not tested:
            # Всё, что не открылось, не удалось и найти по имени: тут дело в
            # DNS, и стратегии не помогут — «всё открывается» было бы ложью.
            unresolved = [host.target.key or host.host for host in hosts
                          if host.target.url in blocked_urls and not host.address]
            if unresolved and not any(host.address for host in hosts):
                report.problem = ("Не удалось узнать адреса сайтов — похоже, не работает "
                                  "DNS или нет интернета. Стратегии тут не помогут.")
            elif unresolved:
                report.problem = (
                    f"Не удалось узнать адреса: {', '.join(unresolved[:4])} — похоже, их "
                    "прячет DNS, а стратегии тут не помогут: попробуйте другой DNS. "
                    "Остальное открывается и без обхода.")
            else:
                report.note = "Всё открывается и без обхода — сравнивать стратегии не на чем."
            report.seconds = time.perf_counter() - started
            return report
        self._guard()

        # Таблице — сразу весь список: партий может быть несколько.
        emit(EVENT_STARTED, (list(candidates), [host.target for host in tested]))
        scores: list[StrategyScore] = []
        batches = [candidates[index:index + MAX_INSTANCES]
                   for index in range(0, len(candidates), MAX_INSTANCES)]
        for batch in batches:
            scores.extend(self._run_batch(batch, tested, iface, folder, emit))
            self._guard()

        report.scores = sorted(
            scores,
            key=lambda item: (bool(item.error), -item.passed, item.latency_ms or 10_000),
        )
        report.seconds = time.perf_counter() - started
        best = report.best
        logs.info(
            f"Проверка всех стратегий: {len(scores)} за {report.seconds:.1f} с, "
            f"лучшая — «{best.strategy.title}» {best.passed}/{best.total}" if best else
            f"Проверка всех стратегий: {len(scores)} за {report.seconds:.1f} с, рабочих нет"
        )
        return report

    # --- этапы ------------------------------------------------------------

    def _resolve(self, targets: list[Target]) -> list[Host]:
        """Адреса узнаём один раз для всех копий: DNS не должен влиять на сравнение."""
        hosts = [Host(target, _host_of(target)) for target in targets if _host_of(target)]

        def lookup(host: Host) -> Host:
            try:
                info = socket.getaddrinfo(host.host, 443, socket.AF_INET, socket.SOCK_STREAM)
                host.address = info[0][4] if info else None
            except (OSError, UnicodeError):
                host.address = None
            return host

        with ThreadPoolExecutor(max_workers=min(16, max(1, len(hosts)))) as pool:
            return list(pool.map(lookup, hosts))

    def _probe_many(self, jobs, iface, timeout: float,
                    on_done: Callable[[int, ProbeResult], None] | None = None
                    ) -> list[ProbeResult]:
        results: list[ProbeResult | None] = [None] * len(jobs)
        if not jobs:
            return []
        with ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(jobs))) as pool:
            futures = {pool.submit(probe, host, ports, iface, timeout): index
                       for index, (host, ports) in enumerate(jobs)}
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
                if on_done is not None:
                    on_done(index, results[index])
        return [item for item in results if item is not None]

    def _allocate(self, count: int) -> list[_Ports]:
        """Свободные диапазоны портов. Порты, которые система зарезервировала
        (Hyper-V, WSL), пропускаем — проверяем по первому и последнему порту.

        Каждая партия и каждая следующая проверка берут диапазоны дальше
        по кругу: только что закрытые порты Windows ещё держит в TIME_WAIT.
        """
        global _next_range
        ranges: list[_Ports] = []
        with _cursor_lock:
            low = _next_range
            for _step in range((PORT_LAST - PORT_FIRST + 1) // PORT_SPAN):
                if len(ranges) >= count:
                    break
                if low + PORT_SPAN - 1 > PORT_LAST:
                    low = PORT_FIRST
                high = low + PORT_SPAN - 1
                if all(_bindable(port) for port in (low, high)):
                    ranges.append(_Ports(low, high))
                low += PORT_SPAN
            _next_range = low
        return ranges

    def _run_batch(self, batch: list[Strategy], hosts: list[Host],
                   iface, folder, emit: Event) -> list[StrategyScore]:
        ranges = self._allocate(len(batch))
        if len(ranges) < len(batch):
            raise ParallelUnavailable("Не хватило свободных портов для проверки.")
        instances = [_Instance(strategy, ports) for strategy, ports in zip(batch, ranges)]

        emit(EVENT_PHASE, f"Запускаем стратегии: {len(instances)}…")
        try:
            for instance in instances:
                try:
                    instance.process = subprocess.Popen(
                        _arguments(instance),
                        cwd=str(paths.bin_dir()),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                    )
                except OSError as exc:
                    instance.error = f"не запустилась: {exc}"
                    instance.ready.set()
                    continue
                with _live_lock:
                    _live.add(instance.process)
                threading.Thread(target=_watch, args=(instance,), daemon=True).start()
                # Небольшой разнос по времени: два десятка копий, разом
                # открывающих драйвер WinDivert, мешают друг другу.
                time.sleep(START_GAP)
            _remember(instances)

            deadline = time.monotonic() + READY_TIMEOUT
            for instance in instances:
                instance.ready.wait(max(0.0, deadline - time.monotonic()))
                self._guard()
            alive: list[_Instance] = []
            for instance in instances:
                process = instance.process
                if instance.error:
                    continue
                if process is None or process.poll() is not None:
                    # Первая строка вывода — версия winws, причина — в последних.
                    tail = " | ".join(line for line in instance.output[-4:]
                                      if not line.startswith("github version"))
                    instance.error = f"winws завершился: {tail or 'без сообщения'}"[:400]
                    logs.warn(f"Проверка разом: «{instance.strategy.title}» — {instance.error}")
                    # Только если не понят сам --wf-raw: неизвестный ключ в одной
                    # стратегии (самодельный .bat) — её ошибка, а не всей проверки.
                    if "wf-raw" in tail.lower():
                        raise ParallelUnavailable(
                            "Эта версия winws не умеет проверять стратегии разом.")
                    continue
                alive.append(instance)
            if not alive:
                reason = next((item.error for item in instances if item.error), "")
                raise ParallelUnavailable(f"Ни одна копия winws не запустилась. {reason}")
            self._guard()

            emit(EVENT_PHASE, "Проверяем…")
            scores = self._measure(alive, hosts, iface, emit)
            for instance in instances:
                if instance.error:
                    score = StrategyScore(strategy=instance.strategy, total=len(hosts),
                                          stage=STAGE_FULL, error=instance.error)
                    scores.append(score)
                    emit(EVENT_RESULT, score)
            return scores
        finally:
            for instance in instances:
                process = instance.process
                if process is not None and process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
            for instance in instances:
                process = instance.process
                if process is not None:
                    try:
                        process.wait(timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    with _live_lock:
                        _live.discard(process)
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, exist_ok=True)

    def _measure(self, alive: list[_Instance], hosts: list[Host], iface,
                 emit: Event) -> list[StrategyScore]:
        cells: dict[int, dict[str, ProbeResult]] = {id(item): {} for item in alive}
        jobs = [(item, host) for item in alive for host in hosts]
        lock = threading.Lock()

        def done(index: int, result: ProbeResult) -> None:
            instance, _host = jobs[index]
            with lock:
                row = cells[id(instance)]
                row[result.target.url] = result
                finished = len(row) == len(hosts)
            if finished:
                emit(EVENT_RESULT, _score(instance, hosts, row, final=False))

        self._probe_many([(host, item.ports) for item, host in jobs], iface,
                         PROBE_TIMEOUT, done)
        self._guard()

        # Один повтор для неудач у тех, кто открыл хоть что-то: при двух
        # десятках одновременных рукопожатий случайная осечка — не редкость,
        # и из-за неё хорошая стратегия уходила бы вниз таблицы.
        retry = [(item, host) for item in alive for host in hosts
                 if item.ports._next <= item.ports.high
                 and any(cell.ok for cell in cells[id(item)].values())
                 and not cells[id(item)][host.target.url].ok]
        if retry:
            emit(EVENT_RETRY, len(retry))
            results = self._probe_many([(host, item.ports) for item, host in retry],
                                       iface, RETRY_TIMEOUT)
            for (item, host), result in zip(retry, results):
                if result.ok:
                    cells[id(item)][host.target.url] = result
        scores = []
        for item in alive:
            score = _score(item, hosts, cells[id(item)], final=True)
            scores.append(score)
            emit(EVENT_RESULT, score)
        return scores


def _score(instance: _Instance, hosts: list[Host], row: dict[str, ProbeResult],
           final: bool) -> StrategyScore:
    results = [row[host.target.url] for host in hosts if host.target.url in row]
    latencies = [item.ms for item in results if item.ok]
    score = StrategyScore(
        strategy=instance.strategy, total=len(hosts), stage=STAGE_FULL,
        results=results, passed=sum(1 for item in results if item.ok),
        latency_ms=statistics.median(latencies) if latencies else 0.0,
    )
    if final:
        logs.info(f"Разом: «{instance.strategy.title}» {score.passed}/{score.total}"
                  + (f", {score.latency_ms:.0f} мс" if latencies else ""))
    return score


# --- проверка целиком: захват обхода, проверка, возврат ---------------------


@dataclass
class PreviousState:
    """Каким был обход до проверки — чтобы вернуть его как было."""

    running: bool
    mode: str
    strategy: Strategy | None
    external: bool


@dataclass
class CheckOutcome:
    report: ParallelReport
    previous: PreviousState
    sequential: bool = False         # разом не вышло — перебирали по одной
    restored: bool = False
    restore_error: str = ""
    cancelled: bool = False


class _ActiveCheck:
    """Идущая проверка: при выходе из программы её отменяют и дожидаются."""

    def __init__(self, tester: ParallelTester) -> None:
        self.tester = tester
        self.done = threading.Event()
        self.quitting = False


_active: list[_ActiveCheck] = []
_active_lock = threading.Lock()


def cancel_active(timeout: float, quitting: bool = False) -> bool:
    """Отменить идущую проверку и дождаться, пока она вернёт обход как был.

    quitting — программа закрывается: обход-процесс умер бы вместе с ней,
    возвращать стоит только службу. True — проверок больше не идёт.
    """
    with _active_lock:
        checks = list(_active)
    deadline = time.monotonic() + timeout
    for check in checks:
        check.quitting = check.quitting or quitting
        check.tester.cancel()
    return all(check.done.wait(max(0.0, deadline - time.monotonic())) for check in checks)


def capture_previous() -> PreviousState:
    """Вызывать под engine.exclusive(): между взглядом на обход и захватом
    его проверкой ничего не должно запуститься или остановиться."""
    from app.core import strategies as strategies_module
    from app.core.config import config
    from app.core.engine import engine

    status = engine.status()
    running = status.running and not status.external
    game_filter = strategies_module.read_game_filter()
    wanted = [status.strategy_id, str(config.get("last_strategy", ""))]
    if running:
        # Работающий обход вернём в любом случае: если его стратегии у нас
        # нет (службу ставил service.bat из другой папки), — так же, как это
        # делает обновление ядра.
        wanted.append("general")
    strategy = None
    for strategy_id in filter(None, wanted):
        strategy = strategies_module.find_strategy(strategy_id, game_filter)
        if strategy is not None:
            break
    if running and strategy is not None and status.strategy_id \
            and strategy.id != status.strategy_id:
        logs.warn(f"Стратегии «{status.strategy_id}» нет в ядре — после проверки "
                  f"верну «{strategy.title}»")
    return PreviousState(running=running, mode=status.mode, strategy=strategy,
                         external=status.external)


def _restore_path():
    return paths.data_dir() / RESTORE_FILE


def _remember_previous(previous: PreviousState) -> None:
    """Служба на время проверки удалена. Если программу закроют или она
    упадёт посреди проверки, следующий запуск вернёт службу по этой записи."""
    from app.core.engine import MODE_SERVICE

    if not (previous.running and previous.mode == MODE_SERVICE and previous.strategy):
        return
    try:
        _restore_path().write_text(json.dumps({"strategy": previous.strategy.id,
                                               "mode": previous.mode}), encoding="utf-8")
    except OSError:
        pass


def _forget_previous() -> None:
    try:
        _restore_path().unlink(missing_ok=True)
    except OSError:
        pass


def restore_interrupted() -> str:
    """При запуске программы: вернуть службу, снятую прерванной проверкой.

    Возвращает название стратегии, если служба возвращена, иначе "".
    """
    from app.core import strategies as strategies_module
    from app.core.engine import MODE_SERVICE, EngineError, engine

    try:
        record = json.loads(_restore_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    from app.core import netadapters
    from app.core.config import config

    _forget_previous()   # одна попытка: не долбить службой при каждом запуске
    if not isinstance(record, dict) or record.get("mode") != MODE_SERVICE:
        return ""
    if config.get("run_mode", MODE_SERVICE) != MODE_SERVICE:
        return ""        # с тех пор выбрали режим процесса — службу не навязываем
    if engine.status().running:
        return ""        # обход уже включили — не трогаем
    strategy = strategies_module.find_strategy(
        str(record.get("strategy", "")), strategies_module.read_game_filter())
    if strategy is None:
        return ""
    if config.get("pause_zapret_with_vpn", True) and netadapters.tunnel_names():
        # Поднят чужой VPN: при нём обход и так был бы снят. Запоминаем, что
        # его надо вернуть, — окно включит его само, когда VPN выключат.
        config.update({"last_strategy": strategy.id, "zapret_paused_by_vpn": True})
        logs.info(f"Обход после прерванной проверки вернётся, когда выключат VPN: "
                  f"«{strategy.title}»")
        return ""
    try:
        engine.start(strategy, MODE_SERVICE)
    except (EngineError, OSError) as exc:
        logs.warn(f"Не удалось вернуть обход после прерванной проверки: {exc}")
        return ""
    logs.info(f"Обход после прерванной проверки возвращён: «{strategy.title}»")
    return strategy.title


def _restore(previous: PreviousState, outcome: CheckOutcome, token: object,
             quitting: bool) -> None:
    """Поставить обход как был — ещё под ключом проверки, чтобы тумблер на
    главной не запустил его параллельно с нами."""
    from app.core import strategies as strategies_module
    from app.core.engine import MODE_SERVICE, EngineError, engine

    if not previous.running:
        return
    if quitting and previous.mode != MODE_SERVICE:
        return           # процесс всё равно закрылся бы вместе с программой
    if previous.strategy is None:
        outcome.restore_error = "не удалось понять, какая стратегия работала"
        logs.warn(f"Не удалось вернуть обход после проверки: {outcome.restore_error}")
        return
    # Фильтры могли поменять, пока шла проверка, — аргументы берём нынешние.
    strategy = strategies_module.find_strategy(
        previous.strategy.id, strategies_module.read_game_filter()) or previous.strategy
    try:
        engine.start(strategy, previous.mode, token=token)
        outcome.restored = True
    except EngineError as exc:
        outcome.restore_error = str(exc)
        logs.warn(f"Не удалось вернуть обход после проверки: {exc}")


def check_all(candidates: list[Strategy], targets: list[Target],
              tester: ParallelTester, on_event: Event | None = None,
              fallback: "Callable[[object], ParallelReport] | None" = None) -> CheckOutcome:
    """Снять обход, проверить стратегии и вернуть обход как было.

    Раньше автоподбор снимал обход и удалял службу — и так и оставлял: после
    подбора человек оставался без обхода, пока сам не нажмёт «Применить».
    fallback — перебор по одной, если разом нельзя: получает ключ проверки.
    """
    from app.core.engine import EngineError, engine

    active = _ActiveCheck(tester)
    with _active_lock:
        _active.append(active)
    try:
        # Запуск или остановка, что уже идут, доделываются, и только потом
        # смотрим, каким был обход, — иначе он «выключен» посреди перезапуска.
        with engine.exclusive():
            previous = capture_previous()
            token = engine.begin_test()
    except BaseException:
        with _active_lock:
            _active.remove(active)
        active.done.set()
        raise

    outcome = CheckOutcome(report=ParallelReport(), previous=previous)
    _remember_previous(previous)
    try:
        try:
            engine.stop(quiet=True, keep_driver=True, token=token)
            try:
                outcome.report = tester.run(candidates, targets, on_event)
            except ParallelUnavailable as exc:
                if tester.cancelled:
                    raise Cancelled("Проверка отменена.") from exc
                if fallback is None:
                    raise
                logs.warn(f"Разом проверить нельзя ({exc}) — перебираю по одной")
                outcome.sequential = True
                outcome.report = fallback(token)
                if tester.cancelled:
                    raise Cancelled("Проверка отменена.")
        except Cancelled:
            outcome.cancelled = True
        finally:
            # Снять всё, что осталось от проверки, и выгрузить драйвер.
            try:
                engine.stop(quiet=True, token=token)
            except EngineError:
                pass
    finally:
        try:
            _restore(previous, outcome, token, active.quitting)
        finally:
            engine.end_test(token)
            # Запись нужна, только если программа закрывается, а служба так и
            # не вернулась. Иначе человек уже видел ошибку и сам решит, что
            # ставить, — а через неделю служба воскресла бы без спроса.
            if not (active.quitting and outcome.restore_error):
                _forget_previous()
            with _active_lock:
                _active.remove(active)
            active.done.set()
    return outcome


def _bindable(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()
