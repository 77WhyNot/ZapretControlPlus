"""Настройки приложения (JSON в %LOCALAPPDATA%\\ZapretControl)."""

from __future__ import annotations

import json
import threading
from typing import Any

from app.core import paths
from app.core.constants import CONFIG_VERSION

DEFAULTS: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    # Внешний вид
    "theme": "rails",             # см. ui/theme.py
    "accent": "ruby",
    # Поведение
    "run_mode": "service",        # service | process
    "last_strategy": "general",
    "autorun_last_strategy": False,
    "autostart_app": False,
    "start_minimized": False,
    "close_to_tray": True,
    "confirm_exit_while_running": True,
    # Обновления
    "check_core_updates": True,
    "check_app_updates": True,
    "auto_install_core_updates": False,
    "update_check_interval_hours": 12,
    "last_update_check": 0,
    "skipped_core_version": "",
    "skipped_app_version": "",
    # Сеть
    "use_system_proxy": True,
    "custom_proxy": "",
    "preferred_mirror": "",       # запоминаем зеркало, которое сработало
    "warn_about_vpn": True,
    # Telegram
    "telegram_bypass": False,
    "telegram_mode": "split",
    # VPN
    "vpn_subscription_url": "",
    "vpn_selected_server": "",
    "vpn_mode": "selected",       # selected | except | all
    "vpn_apps": [],               # программы, которым нужен туннель
    "vpn_direct_apps": [],        # программы в обход туннеля
    "vpn_stack": "mixed",         # стек TUN: mixed | system | gvisor
    "vpn_autostart": False,
    "vpn_auto_exclude": True,     # адреса серверов — в исключения zapret
    "vpn_managed_excludes": [],
    "vpn_last_update": 0,
    # Прочее
    "first_run": True,
    "window_geometry": "",
    "diagnostics_autorun": True,
}


class Config:
    """Потокобезопасный словарь настроек с ленивым сохранением."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # --- доступ ----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
            return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
        if save:
            self.save()

    def update(self, values: dict[str, Any], save: bool = True) -> None:
        with self._lock:
            self._data.update(values)
        if save:
            self.save()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    # --- хранилище -------------------------------------------------------

    def load(self) -> None:
        path = paths.config_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        with self._lock:
            for key, value in raw.items():
                if key in DEFAULTS:
                    self._data[key] = value

    def save(self) -> None:
        path = paths.config_path()
        try:
            with self._lock:
                payload = json.dumps(self._data, ensure_ascii=False, indent=2)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def reset(self) -> None:
        with self._lock:
            keep = {
                "last_strategy": self._data.get("last_strategy"),
                "first_run": False,
            }
            self._data = dict(DEFAULTS)
            self._data.update(keep)
        self.save()


config = Config()
