"""Разбор стратегий zapret из .bat-файлов.

Стратегии приходят из GitHub в виде .bat-скриптов, поэтому парсим их, а не
дублируем аргументы в коде: после обновления ядра новые стратегии
подхватываются автоматически.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core import paths

# Значения GameFilter, GameFilterTCP и GameFilterUDP считает game_filter_ports —
# в точности как service.bat, вместе со своими диапазонами портов.
GAME_FILTER_LABELS = {
    "off": "выключен",
    "all": "TCP и UDP",
    "tcp": "только TCP",
    "udp": "только UDP",
}

# Короткие пояснения по семействам стратегий — их нет в самих .bat.
FAMILY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^general$", re.I),
     "Базовая стратегия. Начинайте подбор с неё."),
    (re.compile(r"FAKE TLS AUTO", re.I),
     "Подменяет TLS ClientHello, собирая фейк на лету. Часто помогает, "
     "когда обычные фейки перестали работать."),
    (re.compile(r"SIMPLE FAKE", re.I),
     "Простые фейковые пакеты. Меньше всего нагружает соединение."),
    (re.compile(r"EXP", re.I),
     "Экспериментальная: самые свежие приёмы обхода, могут работать нестабильно."),
    (re.compile(r"ALT", re.I),
     "Альтернативный набор параметров десинхронизации."),
]


@dataclass
class Strategy:
    """Одна стратегия обхода."""

    id: str                      # имя файла без расширения
    title: str                   # короткое имя для интерфейса
    path: Path
    tokens: list[str] = field(default_factory=list)
    hint: str = ""
    recommended: bool = False
    not_recommended: bool = False
    experimental: bool = False

    @property
    def subtitle(self) -> str:
        return self.path.name

    @property
    def badge(self) -> str:
        if self.recommended:
            return "рекомендуется"
        if self.not_recommended:
            return "не рекомендуется"
        if self.experimental:
            return "эксперимент"
        return ""


class StrategyError(RuntimeError):
    pass


# --- Чтение и разбор -----------------------------------------------------


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for codec in ("utf-8-sig", "utf-8", "cp866", "cp1251"):
        try:
            return data.decode(codec)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_command(text: str) -> str:
    """Склеить строку запуска winws.exe из .bat (с учётом переносов через ^)."""
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("::"):
            continue
        if "winws.exe" in stripped:
            start = index
            break
    if start < 0:
        raise StrategyError("в файле не найден запуск winws.exe")

    parts: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index].rstrip()
        if line.endswith("^"):
            parts.append(line[:-1])
            index += 1
            continue
        parts.append(line)
        break
    command = " ".join(parts)

    marker = 'winws.exe"'
    position = command.find(marker)
    if position < 0:
        raise StrategyError("не удалось отделить аргументы от команды запуска")
    return command[position + len(marker):]


def _tokenize(raw: str) -> list[str]:
    """Разбить строку аргументов, уважая кавычки cmd."""
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in raw:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if char.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _substitute(tokens: list[str], game_filter: str) -> list[str]:
    game, tcp, udp = game_filter_ports(game_filter)
    bin_prefix = str(paths.bin_dir()) + os.sep
    lists_prefix = str(paths.lists_dir()) + os.sep
    core_prefix = str(paths.core_dir()) + os.sep

    result: list[str] = []
    for token in tokens:
        token = token.replace("%BIN%", bin_prefix)
        token = token.replace("%LISTS%", lists_prefix)
        token = token.replace("%~dp0", core_prefix)
        token = token.replace("%GameFilterTCP%", tcp)
        token = token.replace("%GameFilterUDP%", udp)
        token = token.replace("%GameFilter%", game)
        result.append(token)
    return result


def parse_strategy(path: Path, game_filter: str = "off") -> Strategy:
    text = _read_text(path)
    raw_args = _extract_command(text)
    # В cmd без delayed expansion "^!" означает обычный "!".
    raw_args = raw_args.replace("^!", "!")
    tokens = _substitute(_tokenize(raw_args), game_filter)

    stem = path.stem
    match = re.search(r"\((.+)\)", stem)
    title = match.group(1).strip() if match else "Основная"

    comments = " ".join(
        line.strip().lstrip(":").strip()
        for line in text.splitlines()
        if line.strip().startswith("::")
    ).upper()

    hint = ""
    for pattern, text_hint in FAMILY_HINTS:
        if pattern.search(stem):
            hint = text_hint
            break

    return Strategy(
        id=stem,
        title=title,
        path=path,
        tokens=tokens,
        hint=hint,
        recommended=stem.lower() == "general",
        not_recommended="NOT RECOMMENDED" in comments,
        experimental=bool(re.search(r"\bEXP\b", stem, re.I)),
    )


def _natural_key(name: str) -> list[object]:
    """Сортировка как в service.bat: ALT2 раньше ALT10."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
    ]


_cache: dict[tuple, list[Strategy]] = {}
# Сверка файлов на диске — обход папки и два десятка обращений к файлам.
# Список спрашивают по многу раз подряд (на запуске — два десятка раз),
# поэтому сверяемся не чаще раза в пару секунд.
RECHECK_SECONDS = 2.0
_checked: dict[str, float] = {}


def invalidate_cache() -> None:
    _cache.clear()
    _checked.clear()


def load_strategies(game_filter: str = "off") -> list[Strategy]:
    """Все стратегии из папки ядра (service*.bat игнорируются).

    Разбор 21 файла заметен на глаз, а вызывается он при каждом открытии
    страницы — поэтому результат кэшируется до изменения файлов.
    """
    import time

    now = time.monotonic()
    if _cache and now - _checked.get(game_filter, -RECHECK_SECONDS) < RECHECK_SECONDS:
        for key, cached in _cache.items():
            if key[0] == game_filter:
                return cached

    core = paths.core_dir()
    if not core.is_dir():
        return []

    try:
        signature = tuple(sorted(
            (path.name, path.stat().st_mtime_ns)
            for path in core.glob("*.bat")
        ))
    except OSError:
        signature = ()
    # Порты игрового фильтра подставляются в аргументы — они тоже часть ключа.
    key = (game_filter, game_filter_ports(game_filter), signature)
    _checked[game_filter] = now
    cached = _cache.get(key)
    if cached is not None:
        return cached

    found: list[Strategy] = []
    for path in sorted(core.glob("*.bat"), key=lambda p: _natural_key(p.name)):
        if path.name.lower().startswith("service"):
            continue
        try:
            found.append(parse_strategy(path, game_filter))
        except (StrategyError, OSError):
            continue
    _cache.clear()
    _checked.clear()
    _checked[game_filter] = now
    _cache[key] = found
    return found


def find_strategy(strategy_id: str, game_filter: str = "off") -> Strategy | None:
    for strategy in load_strategies(game_filter):
        if strategy.id == strategy_id:
            return strategy
    return None


# --- Сборка командной строки --------------------------------------------


def quote_token(token: str) -> str:
    """Кавычки ставим так же, как это делает service.bat."""
    if " " not in token:
        return token
    if token.startswith("--") and "=" in token:
        key, _, value = token.partition("=")
        return f'{key}="{value}"'
    return f'"{token}"'


def build_command_line(strategy: Strategy) -> str:
    from app.core import telegram

    exe = paths.winws_path()
    # Telegram не отдельная стратегия, а добавка к выбранной: два winws
    # одновременно не уживаются из-за общего драйвера WinDivert.
    tokens = telegram.augment(strategy.tokens)
    parts = [f'"{exe}"'] + [quote_token(token) for token in tokens]
    return " ".join(parts)


# --- Режим GameFilter (файл-флаг совместим с service.bat) ----------------


DEFAULT_GAME_RANGE = "1024-65535"
_RANGE_ITEM = re.compile(r"^[1-9]\d{0,4}(?:-[1-9]\d{0,4})?$")


@dataclass(frozen=True)
class GameFilterSettings:
    """Игровой фильтр: режим и диапазоны портов (с ядра 1.10.3 их можно менять)."""

    mode: str = "off"                 # off | all | tcp | udp
    tcp_range: str = DEFAULT_GAME_RANGE
    udp_range: str = DEFAULT_GAME_RANGE


def validate_port_range(value: str) -> str:
    """Диапазон вида «1024-1934,1936-65535» — или пустая строка, если он неверен.

    Правила те же, что в service.bat: числа 1–65535, начало не больше конца.
    """
    value = value.replace(" ", "")
    if not value:
        return ""
    for item in value.split(","):
        if not _RANGE_ITEM.match(item):
            return ""
        start, _, end = item.partition("-")
        low, high = int(start), int(end or start)
        if high > 65535 or low > high:
            return ""
    return value


def _game_flag() -> Path:
    return paths.utils_dir() / "game_filter.enabled"


def read_game_filter_settings() -> GameFilterSettings:
    """Файл-флаг так же, как его читает service.bat ядра 1.10.3.

    Строки «ключ=значение»: mode=all|tcp|udp, tcp=<порты>, udp=<порты>.
    Старый формат — одно слово all, tcp или udp — тоже понимается: строка
    «tcp» без значения включает режим, «tcp=…» задаёт порты.
    """
    flag = _game_flag()
    try:
        text = flag.read_text(encoding="utf-8", errors="replace") if flag.exists() else ""
    except OSError:
        text = ""
    mode = "disabled"
    tcp_candidate = udp_candidate = ""
    for line in text.splitlines():
        key, _, value = line.strip().partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key == "mode":
            mode = value.lower()
        elif key == "all":
            mode = "all"
        elif key == "udp":
            if value:
                udp_candidate = value
            else:
                mode = "udp"
        elif key == "tcp":
            if value:
                tcp_candidate = value
            else:
                mode = "tcp"
    if mode not in ("all", "tcp", "udp"):
        mode = "off"
    return GameFilterSettings(
        mode=mode,
        tcp_range=validate_port_range(tcp_candidate) or _saved_range("tcp"),
        udp_range=validate_port_range(udp_candidate) or _saved_range("udp"),
    )


def _saved_range(kind: str) -> str:
    """Свои порты, заданные в программе: файл при выключенном фильтре удаляется."""
    from app.core.config import config

    return validate_port_range(str(config.get(f"game_filter_{kind}_range", "") or "")) \
        or DEFAULT_GAME_RANGE


def read_game_filter() -> str:
    return read_game_filter_settings().mode


def game_filter_ports(mode: str | None = None) -> tuple[str, str, str]:
    """Значения GameFilter, GameFilterTCP и GameFilterUDP — как в service.bat.

    Порт 12 — заглушка, которая гарантированно ничего не ловит.
    """
    settings = read_game_filter_settings()
    mode = settings.mode if mode is None else mode
    tcp, udp = settings.tcp_range, settings.udp_range
    if mode == "all":
        return tcp, tcp, udp
    if mode == "tcp":
        return tcp, tcp, "12"
    if mode == "udp":
        return udp, "12", udp
    return "12", "12", "12"


def write_game_filter(mode: str, tcp_range: str | None = None,
                      udp_range: str | None = None) -> None:
    """Записать файл так, чтобы его поняли и старое ядро, и новое.

    Первая строка — режим одним словом: так его читает service.bat до 1.10.2
    (он смотрит только на первую строку). Порты — строками «tcp=…», «udp=…»,
    их читает 1.10.3. Порты не указаны — остаются прежние. Выключенный фильтр
    — нет файла: любую строку старое ядро приняло бы за «включить UDP».
    """
    from app.core.config import config

    flag = _game_flag()
    current = read_game_filter_settings()
    tcp = validate_port_range(tcp_range or "") or current.tcp_range
    udp = validate_port_range(udp_range or "") or current.udp_range
    config.update({
        "game_filter_tcp_range": "" if tcp == DEFAULT_GAME_RANGE else tcp,
        "game_filter_udp_range": "" if udp == DEFAULT_GAME_RANGE else udp,
    })
    if mode == "off":
        flag.unlink(missing_ok=True)
        invalidate_cache()
        return
    flag.parent.mkdir(parents=True, exist_ok=True)
    lines = [mode]
    if tcp != DEFAULT_GAME_RANGE:
        lines.append(f"tcp={tcp}")
    if udp != DEFAULT_GAME_RANGE:
        lines.append(f"udp={udp}")
    flag.write_text("\n".join(lines) + "\n", encoding="utf-8")
    invalidate_cache()


def local_core_version() -> str:
    """Версия ядра берётся из service.bat — это источник правды апстрима."""
    service = paths.core_dir() / "service.bat"
    if not service.exists():
        return "—"
    try:
        text = _read_text(service)
    except OSError:
        return "—"
    match = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text)
    return match.group(1).strip() if match else "—"
