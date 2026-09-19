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
    "theme": "light",             # см. ui/theme.py
    "accent": "sapphire",
    "accent_migrated_blue": False,  # разовый перевод старого рубина на синий
    "last_dark_theme": "rails",   # куда возвращает кнопка «тёмная» в заголовке
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
    "auto_install_core_updates": True,   # ядро ставится само, обход коротко перезапускается
    "update_check_interval_hours": 12,
    "last_update_check": 0,
    "skipped_core_version": "",
    "skipped_app_version": "",
    # Напоминание о новой версии программы: показываем не чаще раза в сутки.
    "update_notice_interval_hours": 24,
    "last_update_notice": 0,
    "notified_app_version": "",
    # Сеть
    "use_system_proxy": True,
    "custom_proxy": "",
    "preferred_mirror": "",       # запоминаем зеркало, которое сработало
    "warn_about_vpn": True,
    # Telegram
    "telegram_bypass": False,
    "telegram_mode": "split",
    # Telegram через WebSocket-прокси (ядро tg-ws-proxy внутри программы)
    "tg_ws_enabled": False,       # желаемое состояние: поднимать при запуске
    "tg_ws_port": 1443,
    "tg_ws_secret": "",           # создаётся один раз, иначе ссылка в Telegram устареет
    # Сосуществование со сторонним VPN (Happ, Hiddify, WireGuard и др.)
    "pause_zapret_with_vpn": True,   # снимать обход, пока поднят чужой туннель
    "zapret_paused_by_vpn": False,   # обход снят нами — вернуть после VPN
    # VPN (sing-box внутри программы)
    "vpn_subscription_url": "",
    "vpn_selected_server": "",
    "vpn_transport": "tun",         # tun — туннель по программам | proxy — без конфликтов
    "vpn_mode": "selected",         # selected | except | all
    "vpn_apps": [],                 # программы, которым нужен туннель
    "vpn_direct_apps": [],          # программы в обход туннеля
    "vpn_stack": "mixed",           # стек TUN: mixed | system | gvisor
    "vpn_strict_route": False,
    "vpn_ipv6": False,
    "vpn_mtu": 9000,
    "vpn_dns_through_tunnel": False,
    "vpn_dns_server": "1.1.1.1",
    "vpn_bypass_lan": True,
    "vpn_autostart": False,         # поднимать VPN вместе с программой
    "vpn_auto_exclude": True,       # адреса серверов — в исключения zapret
    "vpn_managed_excludes": [],
    "vpn_last_update": 0,
    "vpn_proxy_port": 10808,
    "vpn_proxy_backup": {},         # системный прокси до нас (режим «Прокси»)
    # Прочее
    "home_dns_preset": "xbox",      # сервис Smart DNS для тумблера на главной
    "speedtest_last": {},           # последний замер скорости, чтобы не пустовало
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
        self._migrate()

    def _migrate(self) -> None:
        """Разовые правки уже сохранённых настроек."""
        changed = False
        # Основной цвет программы стал синим. Рубин был цветом по умолчанию,
        # который никто не выбирал осознанно, — переводим его один раз.
        if not self._data.get("accent_migrated_blue"):
            if self._data.get("accent") == "ruby":
                self._data["accent"] = "sapphire"
            self._data["accent_migrated_blue"] = True
            changed = True
        if changed:
            self.save()

    def raw(self) -> dict[str, Any]:
        """Файл настроек как есть, вместе с ключами прошлых версий.

        ``load`` оставляет только известные ключи, поэтому списки от старых
        версий (например, выключенные ими сетевые адаптеры) сюда не попадают.
        Чтобы их починить, файл приходится читать напрямую.
        """
        path = paths.config_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def drop_raw_key(self, key: str) -> None:
        """Убрать из файла ключ, оставшийся от прошлой версии."""
        raw = self.raw()
        if key not in raw:
            return
        path = paths.config_path()
        del raw[key]
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

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
