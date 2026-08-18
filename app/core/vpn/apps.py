"""Список программ для раздельного туннелирования.

sing-box сопоставляет правила по имени исполняемого файла, поэтому именно
имя (Telegram.exe) и есть идентификатор. Пользователю показываем понятное
название, а храним имя файла.
"""

from __future__ import annotations

import os
import winreg
from dataclasses import dataclass
from pathlib import Path

from app.core import winapi

# Системные процессы, которым в списке делать нечего.
SYSTEM_PROCESSES = {
    "system", "system idle process", "registry", "memory compression",
    "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "winlogon.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "taskhostw.exe",
    "sihost.exe", "ctfmon.exe", "conhost.exe", "dllhost.exe", "runtimebroker.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "explorer.exe", "spoolsv.exe", "audiodg.exe",
    "wudfhost.exe", "wmiprvse.exe", "securityhealthservice.exe", "msmpeng.exe",
    "nissrv.exe", "sppsvc.exe", "lsaiso.exe", "wlanext.exe", "smartscreen.exe",
    "applicationframehost.exe", "backgroundtaskhost.exe", "widgets.exe",
    "sing-box.exe", "winws.exe", "zapretcontrolplus.exe",
}

# Программы, которые чаще всего заворачивают в туннель. Показываем их даже
# если сейчас они не запущены.
POPULAR = (
    ("Telegram.exe", "Telegram"),
    ("Discord.exe", "Discord"),
    ("chrome.exe", "Google Chrome"),
    ("msedge.exe", "Microsoft Edge"),
    ("firefox.exe", "Mozilla Firefox"),
    ("browser.exe", "Яндекс Браузер"),
    ("opera.exe", "Opera"),
    ("brave.exe", "Brave"),
    ("Spotify.exe", "Spotify"),
    ("steam.exe", "Steam"),
    ("EpicGamesLauncher.exe", "Epic Games"),
    ("WhatsApp.exe", "WhatsApp"),
    ("Viber.exe", "Viber"),
    ("Slack.exe", "Slack"),
    ("Code.exe", "Visual Studio Code"),
    ("obs64.exe", "OBS Studio"),
    ("vlc.exe", "VLC"),
)

POPULAR_NAMES = {name.lower(): title for name, title in POPULAR}


@dataclass(frozen=True)
class AppEntry:
    """Программа, которой можно назначить маршрут."""

    process: str          # имя файла, как его видит sing-box
    title: str            # что показываем пользователю
    path: str = ""        # полный путь, если удалось узнать
    running: bool = False

    @property
    def key(self) -> str:
        return self.process.lower()


APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

# Где искать программы, которых нет в реестре App Paths.
COMMON_DIRS = (
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    os.environ.get("LOCALAPPDATA", ""),
    os.environ.get("APPDATA", ""),
)

_path_cache: dict[str, str] = {}


def resolve_executable(process: str) -> str:
    """Найти полный путь к программе — он нужен, чтобы показать её иконку."""
    key = process.lower()
    if key in _path_cache:
        return _path_cache[key]

    found = ""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for suffix in ("", r"\WOW6432Node"):
            path = rf"SOFTWARE{suffix}\Microsoft\Windows\CurrentVersion\App Paths\{process}"
            value = winapi.reg_read(root, path, "")
            if value:
                candidate = os.path.expandvars(value.strip('"'))
                if os.path.isfile(candidate):
                    found = candidate
                    break
        if found:
            break

    if not found:
        # Неглубокий обход популярных папок: полный поиск по диску слишком дорог.
        for base in COMMON_DIRS:
            if not base or not os.path.isdir(base):
                continue
            try:
                for entry in os.scandir(base):
                    if not entry.is_dir():
                        continue
                    candidate = os.path.join(entry.path, process)
                    if os.path.isfile(candidate):
                        found = candidate
                        break
            except OSError:
                continue
            if found:
                break

    _path_cache[key] = found
    return found


def _pretty_name(process: str, path: str = "") -> str:
    known = POPULAR_NAMES.get(process.lower())
    if known:
        return known
    stem = Path(process).stem
    if not stem:
        return process
    # CamelCase и подчёркивания превращаем в читаемое название.
    spaced = stem.replace("_", " ").replace("-", " ")
    return spaced[:1].upper() + spaced[1:]


def running_apps(only_windowed: bool = True) -> list[AppEntry]:
    """Запущенные программы.

    По умолчанию только те, у кого есть окно: иначе список тонет в фоновых
    службах вроде ArmouryCrate или обновлятора видеодрайвера.
    """
    windowed = winapi.windowed_pids() if only_windowed else set()
    seen: dict[str, AppEntry] = {}
    for pid, name in winapi.iter_processes():
        low = name.lower()
        if not low.endswith(".exe") or low in SYSTEM_PROCESSES:
            continue
        if only_windowed and pid not in windowed:
            continue
        if low in seen:
            continue
        path = winapi.process_path(pid)
        if path:
            normalized = os.path.normcase(path)
            # Служебные процессы Windows игнорируем целыми папками.
            if "\\windows\\system32\\" in normalized or "\\windows\\syswow64\\" in normalized:
                continue
        seen[low] = AppEntry(
            process=name, title=_pretty_name(name, path), path=path, running=True
        )
    return sorted(seen.values(), key=lambda item: item.title.lower())


def known_apps(installed_only: bool = True) -> list[AppEntry]:
    """Популярные программы, даже если они сейчас не запущены.

    По умолчанию показываем только реально установленные — предлагать
    маршрут для программы, которой на компьютере нет, бессмысленно.
    """
    result: list[AppEntry] = []
    for name, title in POPULAR:
        path = resolve_executable(name)
        if installed_only and not path:
            continue
        result.append(AppEntry(process=name, title=title, path=path, running=False))
    return result


def catalog(include_background: bool = False,
            extra: list[str] | None = None) -> list[AppEntry]:
    """Список для выбора: запущенные программы, популярные и уже выбранные."""
    entries: dict[str, AppEntry] = {}
    for entry in known_apps():
        entries[entry.key] = entry
    for entry in running_apps(only_windowed=not include_background):
        entries[entry.key] = entry

    # Программы, которым маршрут уже назначен, показываем всегда — даже
    # если они не запущены и не нашлись на диске.
    for name in extra or []:
        key = name.lower()
        if key in entries:
            continue
        entries[key] = AppEntry(
            process=name, title=_pretty_name(name),
            path=resolve_executable(name), running=False,
        )

    return sorted(
        entries.values(),
        key=lambda item: (not item.running, item.title.lower()),
    )


def normalize(names: list[str]) -> list[str]:
    """Убрать дубликаты и пустые строки, сохранив порядок."""
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        cleaned = name.strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        result.append(cleaned)
    return result


def describe(names: list[str]) -> str:
    """Короткая подпись для интерфейса: «Telegram, Discord и ещё 3»."""
    if not names:
        return "не выбрано"
    titles = [_pretty_name(name) for name in names[:2]]
    rest = len(names) - len(titles)
    text = ", ".join(titles)
    return f"{text} и ещё {rest}" if rest > 0 else text
