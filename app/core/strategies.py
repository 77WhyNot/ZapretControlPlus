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

# Значения GameFilter в точности как в service.bat: порт 12 — это заглушка,
# которая гарантированно ничего не ловит.
GAME_FILTER_MODES: dict[str, tuple[str, str, str]] = {
    "off": ("12", "12", "12"),
    "all": ("1024-65535", "1024-65535", "1024-65535"),
    "tcp": ("1024-65535", "1024-65535", "12"),
    "udp": ("1024-65535", "12", "1024-65535"),
}

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
    game, tcp, udp = GAME_FILTER_MODES.get(game_filter, GAME_FILTER_MODES["off"])
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


def load_strategies(game_filter: str = "off") -> list[Strategy]:
    """Все стратегии из папки ядра (service*.bat игнорируются)."""
    core = paths.core_dir()
    if not core.is_dir():
        return []
    found: list[Strategy] = []
    for path in sorted(core.glob("*.bat"), key=lambda p: _natural_key(p.name)):
        if path.name.lower().startswith("service"):
            continue
        try:
            found.append(parse_strategy(path, game_filter))
        except (StrategyError, OSError):
            continue
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


def read_game_filter() -> str:
    flag = paths.utils_dir() / "game_filter.enabled"
    if not flag.exists():
        return "off"
    try:
        value = flag.read_text(encoding="utf-8", errors="replace").strip().lower()
    except OSError:
        return "off"
    if value in ("all", "tcp", "udp"):
        return value
    # service.bat трактует любое иное содержимое как UDP-режим.
    return "udp" if value else "off"


def write_game_filter(mode: str) -> None:
    flag = paths.utils_dir() / "game_filter.enabled"
    flag.parent.mkdir(parents=True, exist_ok=True)
    if mode == "off":
        flag.unlink(missing_ok=True)
        return
    flag.write_text(mode, encoding="utf-8")


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
