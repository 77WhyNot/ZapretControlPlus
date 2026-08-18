"""Диагностика системы — портированные проверки из service.bat плюс свои."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.core import logs, paths, winapi
from app.core.constants import WINDIVERT_SERVICES, WINWS_EXE

OK = "ok"
WARN = "warn"
ERROR = "error"


@dataclass
class CheckResult:
    key: str
    title: str
    status: str
    message: str
    fix_label: str = ""
    fix: Callable[[], str] | None = field(default=None, repr=False)
    link: str = ""


# --- вспомогательное -----------------------------------------------------


def _services_matching(*needles: str) -> list[str]:
    """Службы, в имени которых встречаются все указанные подстроки."""
    found = []
    for name in winapi.installed_service_names():
        low = name.lower()
        if all(needle.lower() in low for needle in needles):
            found.append(name)
    return found


def _remove_services(names: list[str]) -> str:
    removed, failed = [], []
    for name in names:
        try:
            winapi.service_stop(name, timeout=8)
            winapi.service_delete(name)
            removed.append(name)
        except winapi.ServiceError:
            failed.append(name)
    parts = []
    if removed:
        parts.append("удалено: " + ", ".join(removed))
    if failed:
        parts.append("не удалось удалить: " + ", ".join(failed))
    return "; ".join(parts) or "Нечего удалять."


# --- проверки ------------------------------------------------------------


def check_admin() -> CheckResult:
    if winapi.is_admin():
        return CheckResult("admin", "Права администратора", OK,
                           "Программа запущена с нужными правами.")
    return CheckResult(
        "admin", "Права администратора", ERROR,
        "Без прав администратора WinDivert не сможет загрузить драйвер. "
        "Перезапустите программу от имени администратора.",
    )


def check_core() -> CheckResult:
    missing = [
        name for name, path in (
            ("bin\\winws.exe", paths.winws_path()),
            ("bin\\WinDivert64.sys", paths.bin_dir() / "WinDivert64.sys"),
            ("bin\\WinDivert.dll", paths.bin_dir() / "WinDivert.dll"),
        ) if not path.exists()
    ]
    if not missing:
        return CheckResult("core", "Файлы ядра zapret", OK, "Все файлы на месте.")
    return CheckResult(
        "core", "Файлы ядра zapret", ERROR,
        "Не хватает файлов: " + ", ".join(missing) +
        ". Обычно их удаляет антивирус — добавьте папку программы в исключения.",
    )


def check_bfe() -> CheckResult:
    state = winapi.service_state("BFE")
    if state == "running":
        return CheckResult("bfe", "Служба Base Filtering Engine", OK, "Работает.")

    def fix() -> str:
        try:
            winapi.service_start("BFE")
            return "Служба BFE запущена."
        except winapi.ServiceError as exc:
            return f"Не удалось запустить BFE: {exc}"

    return CheckResult(
        "bfe", "Служба Base Filtering Engine", ERROR,
        "Служба BFE не работает, без неё zapret не сможет перехватывать трафик.",
        fix_label="Запустить", fix=fix,
    )


def check_tcp_timestamps() -> CheckResult:
    state = winapi.tcp_timestamps_state()
    if state is True:
        return CheckResult("timestamps", "TCP timestamps", OK, "Включены.")

    def fix() -> str:
        return ("TCP timestamps включены." if winapi.enable_tcp_timestamps()
                else "Не удалось изменить параметр netsh.")

    if state is False:
        return CheckResult(
            "timestamps", "TCP timestamps", WARN,
            "Отключены. Часть стратегий использует fooling=ts и без них не работает.",
            fix_label="Включить", fix=fix,
        )
    return CheckResult(
        "timestamps", "TCP timestamps", WARN,
        "Не удалось определить состояние. Можно включить принудительно.",
        fix_label="Включить", fix=fix,
    )


def check_proxy() -> CheckResult:
    proxy = winapi.system_proxy()
    if not proxy:
        return CheckResult("proxy", "Системный прокси", OK, "Отключён.")
    return CheckResult(
        "proxy", "Системный прокси", WARN,
        f"Включён прокси {proxy}. Если вы им не пользуетесь — отключите: "
        "он может ломать соединения вместе с zapret.",
    )


def check_vpn() -> CheckResult:
    adapters = winapi.active_vpn_adapters()
    if not adapters:
        return CheckResult("vpn", "VPN-подключения", OK, "Активных VPN-туннелей не найдено.")
    names = ", ".join(sorted({adapter.name for adapter in adapters}))
    return CheckResult(
        "vpn", "VPN-подключения", WARN,
        f"Активны: {names}. Через VPN трафик и так идёт в обход, а zapret может "
        "конфликтовать с туннелем. Для проверки стратегий VPN лучше отключить.",
    )


def check_conflicting_bypass() -> CheckResult:
    names: list[str] = []
    for candidate in ("GoodbyeDPI", "discordfix_zapret", "winws1", "winws2", "zapret2"):
        names.extend(_services_matching(candidate))
    names = sorted(set(names))
    if not names:
        return CheckResult("conflicts", "Другие обходчики DPI", OK, "Конфликтов не найдено.")
    return CheckResult(
        "conflicts", "Другие обходчики DPI", ERROR,
        "Найдены конкурирующие службы: " + ", ".join(names) +
        ". Они используют тот же драйвер WinDivert и мешают zapret.",
        fix_label="Удалить их", fix=lambda: _remove_services(names),
    )


def check_windivert() -> CheckResult:
    winws_running = winapi.process_running(WINWS_EXE)
    stuck = [
        name for name in WINDIVERT_SERVICES
        if winapi.service_state(name) in ("running", "stopping")
    ]
    if not stuck:
        return CheckResult("windivert", "Драйвер WinDivert", OK, "Состояние в норме.")
    if winws_running:
        return CheckResult("windivert", "Драйвер WinDivert", OK, "Загружен, обход работает.")

    def fix() -> str:
        return _remove_services(stuck)

    return CheckResult(
        "windivert", "Драйвер WinDivert", WARN,
        "Драйвер остался загружен, хотя winws.exe не запущен. "
        "Это мешает следующему запуску.",
        fix_label="Выгрузить", fix=fix,
    )


def check_adguard() -> CheckResult:
    if not winapi.process_running("AdguardSvc.exe"):
        return CheckResult("adguard", "AdGuard", OK, "Не запущен либо не мешает.")
    return CheckResult(
        "adguard", "AdGuard", WARN,
        "Запущен AdGuard. Его фильтрация часто ломает голосовые каналы Discord.",
        link="https://github.com/Flowseal/zapret-discord-youtube/issues/417",
    )


def check_killer() -> CheckResult:
    names = _services_matching("killer")
    if not names:
        return CheckResult("killer", "Killer Network Service", OK, "Не установлен.")
    return CheckResult(
        "killer", "Killer Network Service", ERROR,
        "Найдены службы Killer: " + ", ".join(names) +
        ". Они перехватывают трафик и конфликтуют с zapret.",
        link="https://github.com/Flowseal/zapret-discord-youtube/issues/2512",
    )


def check_intel() -> CheckResult:
    names = [
        name for name in winapi.installed_service_names()
        if "intel" in name.lower() and "connectivity" in name.lower()
    ]
    if not names:
        return CheckResult("intel", "Intel Connectivity Service", OK, "Не установлен.")
    return CheckResult(
        "intel", "Intel Connectivity Service", ERROR,
        "Найдено: " + ", ".join(names) + ". Служба конфликтует с обходом DPI.",
        link="https://github.com/ValdikSS/GoodbyeDPI/issues/541",
    )


def check_checkpoint() -> CheckResult:
    names = _services_matching("TracSrvWrapper") + _services_matching("EPWD")
    if not names:
        return CheckResult("checkpoint", "Check Point", OK, "Не установлен.")
    return CheckResult(
        "checkpoint", "Check Point", ERROR,
        "Найдено: " + ", ".join(names) + ". Клиент Check Point несовместим с zapret.",
    )


def check_smartbyte() -> CheckResult:
    names = _services_matching("smartbyte")
    if not names:
        return CheckResult("smartbyte", "SmartByte", OK, "Не установлен.")
    return CheckResult(
        "smartbyte", "SmartByte", ERROR,
        "Найдено: " + ", ".join(names) +
        ". Отключите SmartByte через services.msc или удалите.",
    )


def check_secure_dns() -> CheckResult:
    if winapi.doh_configured():
        return CheckResult("dns", "Шифрованный DNS", OK, "DNS-over-HTTPS настроен.")
    return CheckResult(
        "dns", "Шифрованный DNS", WARN,
        "DNS-over-HTTPS не настроен. Провайдер видит имена сайтов и может "
        "подменять ответы. Включите DoH в настройках Windows или в браузере.",
    )


def check_hosts() -> CheckResult:
    try:
        content = Path(winapi.hosts_file()).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return CheckResult("hosts", "Файл hosts", WARN, "Не удалось прочитать файл hosts.")
    suspicious = [
        line.strip() for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
        and ("youtube.com" in line or "youtu.be" in line)
    ]
    if not suspicious:
        return CheckResult("hosts", "Файл hosts", OK, "Посторонних записей нет.")
    return CheckResult(
        "hosts", "Файл hosts", WARN,
        f"Найдено записей для YouTube: {len(suspicious)}. "
        "Если вы их не добавляли, они могут мешать доступу.",
    )


DISCORD_FLAVOURS = (
    ("Discord.exe", "discord"),
    ("DiscordPTB.exe", "discordptb"),
    ("DiscordCanary.exe", "discordcanary"),
    ("DiscordDevelopment.exe", "discorddevelopment"),
)


def clear_discord_cache() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return "Не найдена папка AppData."
    cleared, closed = [], []
    for process_name, folder in DISCORD_FLAVOURS:
        base = Path(appdata) / folder
        if not base.is_dir():
            continue
        if winapi.process_running(process_name):
            winapi.kill_processes(process_name)
            closed.append(folder)
        for cache in ("Cache", "Code Cache", "GPUCache"):
            target = base / cache
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                if not target.exists():
                    cleared.append(f"{folder}/{cache}")
    if not cleared:
        return "Кэш Discord не найден — очищать нечего."
    logs.info(f"Очищен кэш Discord: {len(cleared)} папок")
    suffix = f" Закрыт: {', '.join(closed)}." if closed else ""
    return f"Очищено папок: {len(cleared)}.{suffix}"


def check_discord_cache() -> CheckResult:
    appdata = os.environ.get("APPDATA", "")
    installed = [
        folder for _, folder in DISCORD_FLAVOURS
        if appdata and (Path(appdata) / folder).is_dir()
    ]
    if not installed:
        return CheckResult("discord", "Кэш Discord", OK, "Discord не установлен.")
    return CheckResult(
        "discord", "Кэш Discord", WARN,
        "После смены стратегии Discord часто держит старые соединения в кэше. "
        "Если голос не работает — очистите кэш.",
        fix_label="Очистить кэш", fix=clear_discord_cache,
    )


ALL_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_admin,
    check_core,
    check_bfe,
    check_conflicting_bypass,
    check_windivert,
    check_tcp_timestamps,
    check_vpn,
    check_proxy,
    check_killer,
    check_intel,
    check_checkpoint,
    check_smartbyte,
    check_adguard,
    check_secure_dns,
    check_hosts,
    check_discord_cache,
)


def run_all(on_result: Callable[[CheckResult], None] | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in ALL_CHECKS:
        try:
            result = check()
        except Exception as exc:  # noqa: BLE001 — одна упавшая проверка не должна ломать все
            result = CheckResult(
                getattr(check, "__name__", "check"), "Проверка", WARN,
                f"Проверка не выполнилась: {exc}",
            )
        results.append(result)
        if on_result:
            on_result(result)
    return results


def summarize(results: list[CheckResult]) -> tuple[int, int, int]:
    errors = sum(1 for item in results if item.status == ERROR)
    warnings = sum(1 for item in results if item.status == WARN)
    passed = sum(1 for item in results if item.status == OK)
    return passed, warnings, errors
