"""Управление DNS-серверами системы.

Третий инструмент разблокировки рядом с zapret и VPN: DPI ломает распознавание
домена, туннель уводит трафик, а Smart DNS отдаёт другой адрес для сервисов,
которые режут доступ по стране.

Читаем настройки из реестра — вывод netsh переведён на русский и разбирать его
ненадёжно. А вот применяем через netsh: он корректно перезагружает стек.
"""

from __future__ import annotations

import re
import winreg
from dataclasses import dataclass, field

from app.core import logs, winapi
from app.core.config import config

TCPIP_INTERFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
TCPIP6_INTERFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces"
NETWORK_CLASS = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"

BACKUP_KEY = "dns_backup"


@dataclass(frozen=True)
class DnsPreset:
    key: str
    title: str
    description: str
    ipv4: tuple[str, ...]
    ipv6: tuple[str, ...] = ()
    doh: str = ""
    site: str = ""

    @property
    def label(self) -> str:
        return ", ".join(self.ipv4) if self.ipv4 else "автоматически"


PRESETS: tuple[DnsPreset, ...] = (
    DnsPreset(
        key="auto",
        title="Автоматически",
        description="Как выдаёт роутер или провайдер. Исходное состояние Windows.",
        ipv4=(),
    ),
    DnsPreset(
        key="xbox",
        title="Xbox DNS",
        description=(
            "Возвращает доступ к Xbox Live и Game Pass (ошибка 0x80a40401), "
            "а также к ChatGPT, Twitch и Spotify. Через себя гонит только "
            "заблокированные запросы, остальное идёт напрямую."
        ),
        ipv4=("111.88.96.50", "111.88.96.51"),
        ipv6=("2a00:ab00:1233:26::50", "2a00:ab00:1233:26::51"),
        doh="https://xbox-dns.ru/dns-query",
        site="https://xbox-dns.ru/",
    ),
    DnsPreset(
        key="comss",
        title="Comss DNS",
        description="Российский сервис разблокировки с фильтрацией рекламы.",
        ipv4=("83.220.169.155", "212.109.195.93"),
        doh="https://dns.comss.one/dns-query",
        site="https://www.comss.ru/page.php?id=7315",
    ),
    DnsPreset(
        key="cloudflare",
        title="Cloudflare",
        description="Быстрый и нейтральный. Ничего не разблокирует, но не подменяет ответы.",
        ipv4=("1.1.1.1", "1.0.0.1"),
        ipv6=("2606:4700:4700::1111", "2606:4700:4700::1001"),
        doh="https://cloudflare-dns.com/dns-query",
    ),
    DnsPreset(
        key="adguard",
        title="AdGuard DNS",
        description="Режет рекламу и трекеры на уровне запросов.",
        ipv4=("94.140.14.14", "94.140.15.15"),
        doh="https://dns.adguard-dns.com/dns-query",
    ),
    DnsPreset(
        key="google",
        title="Google",
        description="Проверенный запасной вариант, если остальные недоступны.",
        ipv4=("8.8.8.8", "8.8.4.4"),
        doh="https://dns.google/dns-query",
    ),
)

PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}


@dataclass
class Adapter:
    guid: str
    name: str
    up: bool
    servers: list[str] = field(default_factory=list)
    automatic: bool = True

    @property
    def servers_label(self) -> str:
        if not self.servers:
            return "автоматически"
        return ", ".join(self.servers)


def _friendly_name(guid: str) -> str:
    return winapi.reg_read(
        winreg.HKEY_LOCAL_MACHINE, rf"{NETWORK_CLASS}\{guid}\Connection", "Name"
    ) or ""


def _split_servers(value: str) -> list[str]:
    return [item for item in re.split(r"[,\s]+", value.strip()) if item]


def adapters() -> list[Adapter]:
    """Физические сетевые адаптеры с их текущими DNS. Первыми — активные.

    Туннели VPN пропускаем: их DNS задаёт сам клиент, и вмешательство туда
    только сломает туннель.
    """
    live = {item.name: item for item in winapi.list_adapters()}
    tunnels = {item.name for item in winapi.active_vpn_adapters()}
    result: list[Adapter] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TCPIP_INTERFACES)
    except OSError:
        return result

    with root:
        index = 0
        while True:
            try:
                guid = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1

            name = _friendly_name(guid)
            if not name:
                continue
            info = live.get(name)
            if info is None:
                continue
            if info.if_type in (winapi.IF_TYPE_PPP, winapi.IF_TYPE_TUNNEL):
                continue
            if name in tunnels:
                continue
            haystack = f"{name} {info.description}".lower()
            if any(word in haystack for word in winapi.VPN_KEYWORDS):
                continue

            static = winapi.reg_read(
                winreg.HKEY_LOCAL_MACHINE, rf"{TCPIP_INTERFACES}\{guid}", "NameServer"
            ) or ""
            dhcp = winapi.reg_read(
                winreg.HKEY_LOCAL_MACHINE, rf"{TCPIP_INTERFACES}\{guid}", "DhcpNameServer"
            ) or ""
            servers = _split_servers(static) or _split_servers(dhcp)
            result.append(Adapter(
                guid=guid, name=name, up=info.up,
                servers=servers, automatic=not _split_servers(static),
            ))

    result.sort(key=lambda item: (not item.up, item.name.lower()))
    return result


def active_adapters() -> list[Adapter]:
    return [item for item in adapters() if item.up]


def current_preset() -> str:
    """Какой пресет сейчас похож на настройки активных адаптеров."""
    live = active_adapters()
    if not live:
        return "auto"
    applied = {tuple(item.servers) for item in live if not item.automatic}
    if not applied:
        return "auto"
    for preset in PRESETS:
        if preset.key == "auto":
            continue
        if any(set(preset.ipv4).issubset(set(servers)) for servers in applied):
            return preset.key
    return "custom"


# --- применение ----------------------------------------------------------


def _netsh(args: list[str]) -> tuple[bool, str]:
    code, output = winapi.run_hidden(["netsh", *args], timeout=25)
    return code == 0, output.strip()


def _backup(adapter_list: list[Adapter]) -> None:
    """Запоминаем исходные настройки, чтобы было куда вернуться."""
    if config.get(BACKUP_KEY):
        return
    snapshot = {
        item.name: {"automatic": item.automatic, "servers": item.servers}
        for item in adapter_list
    }
    config.set(BACKUP_KEY, snapshot)


def apply_preset(preset_key: str, targets: list[Adapter] | None = None) -> str:
    """Назначить DNS выбранным адаптерам. Возвращает текст результата."""
    preset = PRESET_BY_KEY.get(preset_key)
    if preset is None:
        raise ValueError(preset_key)
    if not winapi.is_admin():
        raise RuntimeError("Смена DNS требует прав администратора.")

    chosen = targets if targets is not None else active_adapters()
    if not chosen:
        raise RuntimeError("Нет активных сетевых подключений.")

    _backup(chosen)
    done: list[str] = []
    failed: list[str] = []

    for adapter in chosen:
        if preset.key == "auto":
            ok, _ = _netsh(["interface", "ipv4", "set", "dnsservers",
                            f"name={adapter.name}", "source=dhcp"])
            _netsh(["interface", "ipv6", "set", "dnsservers",
                    f"name={adapter.name}", "source=dhcp"])
        else:
            ok, message = _netsh([
                "interface", "ipv4", "set", "dnsservers",
                f"name={adapter.name}", "static", preset.ipv4[0], "primary", "no",
            ])
            if ok and len(preset.ipv4) > 1:
                _netsh(["interface", "ipv4", "add", "dnsservers",
                        f"name={adapter.name}", preset.ipv4[1], "index=2", "no"])
            if preset.ipv6:
                _netsh(["interface", "ipv6", "set", "dnsservers",
                        f"name={adapter.name}", "static", preset.ipv6[0],
                        "primary", "no"])
                if len(preset.ipv6) > 1:
                    _netsh(["interface", "ipv6", "add", "dnsservers",
                            f"name={adapter.name}", preset.ipv6[1], "index=2", "no"])
        if ok:
            done.append(adapter.name)
        else:
            failed.append(adapter.name)

    if preset.doh and preset.key != "auto":
        enable_doh(preset)

    flush_cache()
    config.set("dns_preset", preset.key)
    logs.info(f"DNS переключён на «{preset.title}»: {', '.join(done) or 'ничего'}")

    if failed and not done:
        raise RuntimeError(
            "Не удалось изменить DNS ни на одном подключении: " + ", ".join(failed)
        )
    text = f"DNS «{preset.title}» применён: {', '.join(done)}."
    if failed:
        text += f" Не получилось: {', '.join(failed)}."
    return text


def enable_doh(preset: DnsPreset) -> bool:
    """Зашифрованный DNS. Доступно не во всех сборках Windows — не критично."""
    if not preset.doh:
        return False
    ok_any = False
    for address in preset.ipv4:
        ok, _ = _netsh([
            "dns", "add", "encryption", f"server={address}",
            f"dohtemplate={preset.doh}", "autoupgrade=yes", "udpfallback=no",
        ])
        ok_any = ok_any or ok
    if ok_any:
        logs.info("Включён шифрованный DNS (DoH)")
    return ok_any


def flush_cache() -> bool:
    code, _ = winapi.run_hidden(["ipconfig", "/flushdns"], timeout=20)
    return code == 0


def restore() -> str:
    """Вернуть DNS, какими они были до первого вмешательства."""
    snapshot = config.get(BACKUP_KEY) or {}
    if not snapshot:
        return apply_preset("auto")

    restored: list[str] = []
    for adapter in adapters():
        saved = snapshot.get(adapter.name)
        if saved is None:
            continue
        if saved.get("automatic", True) or not saved.get("servers"):
            _netsh(["interface", "ipv4", "set", "dnsservers",
                    f"name={adapter.name}", "source=dhcp"])
        else:
            servers = list(saved["servers"])
            _netsh(["interface", "ipv4", "set", "dnsservers",
                    f"name={adapter.name}", "static", servers[0], "primary", "no"])
            for position, address in enumerate(servers[1:], start=2):
                _netsh(["interface", "ipv4", "add", "dnsservers",
                        f"name={adapter.name}", address, f"index={position}", "no"])
        restored.append(adapter.name)

    flush_cache()
    config.set(BACKUP_KEY, {})
    config.set("dns_preset", "auto")
    logs.info("DNS возвращены к исходным настройкам")
    return f"Исходные настройки DNS возвращены: {', '.join(restored) or 'нечего менять'}."


def has_backup() -> bool:
    return bool(config.get(BACKUP_KEY))
