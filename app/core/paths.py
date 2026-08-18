"""Пути приложения.

В собранном виде рядом с exe лежит папка ``core`` — это обычная установка
zapret (bin / lists / utils / *.bat). Она обновляется из GitHub, поэтому
намеренно вынесена наружу, а не внутрь бандла PyInstaller.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core.constants import APP_ID


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Папка, где лежит исполняемый файл (или корень проекта в dev-режиме)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def core_dir() -> Path:
    """Папка с ядром zapret."""
    if is_frozen():
        return app_dir() / "core"
    return app_dir() / "payload" / "zapret"


def bin_dir() -> Path:
    return core_dir() / "bin"


def lists_dir() -> Path:
    return core_dir() / "lists"


def utils_dir() -> Path:
    return core_dir() / "utils"


def winws_path() -> Path:
    return bin_dir() / "winws.exe"


def resource_path(*parts: str) -> Path:
    """Ресурс, вшитый в бандл (иконки и т.п.)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", app_dir()))
        return base.joinpath("resources", *parts)
    return app_dir().joinpath("app", "resources", *parts)


def data_dir() -> Path:
    """Пользовательские данные: конфиг, логи, кэш."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def log_path() -> Path:
    return data_dir() / "zapret-control.log"


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_dir() -> Path:
    path = data_dir() / "backup"
    path.mkdir(parents=True, exist_ok=True)
    return path


def core_is_valid() -> bool:
    """Ядро на месте и пригодно к запуску."""
    return winws_path().exists() and (bin_dir() / "WinDivert64.sys").exists()
