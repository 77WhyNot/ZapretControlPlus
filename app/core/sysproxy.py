"""Системный прокси Windows (WinINET) — для режима VPN «Прокси».

В этом режиме программа не создаёт сетевой адаптер и не трогает маршруты:
sing-box слушает на 127.0.0.1, а Windows говорят использовать этот адрес
как прокси. Так VPN получают браузеры, Discord и всё, что уважает
системный прокси, — и при этом чужой туннель (Happ и другие) продолжает
работать как ни в чём не бывало.

Исходные настройки прокси сохраняются в конфиг программы и возвращаются
при остановке; если программа упала, их вернёт следующий запуск.
"""

from __future__ import annotations

import ctypes
import winreg
from typing import Any

from app.core import logs
from app.core.config import config

KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BACKUP_KEY = "vpn_proxy_backup"
# Локальные адреса ходят мимо прокси, иначе ломаются панели роутеров и т.п.
OVERRIDE = "<local>;localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;192.168.*"

INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39


def read() -> dict[str, Any]:
    """Текущие настройки прокси текущего пользователя."""
    result: dict[str, Any] = {"enable": 0, "server": "", "override": ""}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            for name, field in (("ProxyEnable", "enable"), ("ProxyServer", "server"),
                                ("ProxyOverride", "override")):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    result[field] = value
                except OSError:
                    continue
    except OSError:
        pass
    result["enable"] = int(result.get("enable") or 0)
    return result


def _write(enable: int, server: str, override: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, str(server or ""))
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, str(override or ""))
    _refresh()


def _refresh() -> None:
    """Сказать Windows, что настройки изменились, — иначе браузеры не заметят."""
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
        wininet.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0)
    except (AttributeError, OSError):
        pass


def is_ours(port: int) -> bool:
    current = read()
    return bool(current["enable"]) and str(current["server"]).endswith(f"127.0.0.1:{port}")


def apply(port: int) -> None:
    """Направить системный прокси на наш sing-box, запомнив, что было."""
    current = read()
    if not is_ours(port) and not config.get(BACKUP_KEY):
        config.set(BACKUP_KEY, current)
    _write(1, f"127.0.0.1:{port}", OVERRIDE)
    logs.info(f"Системный прокси направлен на 127.0.0.1:{port}")


def restore() -> bool:
    """Вернуть настройки прокси, какими они были до нас."""
    backup = config.get(BACKUP_KEY)
    if not isinstance(backup, dict):
        return False
    try:
        _write(int(backup.get("enable") or 0), str(backup.get("server") or ""),
               str(backup.get("override") or ""))
    except OSError as exc:
        logs.warn(f"Не удалось вернуть системный прокси: {exc}")
        return False
    config.set(BACKUP_KEY, {})
    logs.info("Системный прокси возвращён как был")
    return True


def restore_if_left() -> bool:
    """После падения прокси мог остаться направленным в никуда — чиним."""
    backup = config.get(BACKUP_KEY)
    if not isinstance(backup, dict) or not backup:
        return False
    current = read()
    if bool(current["enable"]) and "127.0.0.1:" in str(current["server"]):
        return restore()
    config.set(BACKUP_KEY, {})
    return False
