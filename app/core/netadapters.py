"""Сетевые адаптеры: определяем чужие туннели и чиним следы старых версий.

Программа больше не поднимает свой VPN и ничего не выключает. Модуль
остался по двум причинам:

* версии 2.x умели временно отключать чужой сетевой адаптер и при падении
  оставляли его выключенным — здесь мы это чиним;
* zapret и сторонний VPN-клиент делят один канал, поэтому знать о живом
  туннеле нужно, чтобы не мешать ему.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import logs, winapi

# Ключ из версий 2.x. Читаем его, чтобы вернуть выключенное, и стираем.
LEGACY_PAUSED_KEY = "vpn_paused_adapters"

# Адаптеры, которые поднимали мы сами: их возвращать некому и незачем.
OWN_ADAPTERS = ("zapretcontrol", "zapret control")


@dataclass(frozen=True)
class Tunnel:
    """Живой туннель стороннего клиента."""

    name: str
    description: str

    @property
    def title(self) -> str:
        """Понятное имя для показа человеку."""
        haystack = f"{self.name} {self.description}".lower()
        for needle, label in (
            ("happ", "Happ"),
            ("hiddify", "Hiddify"),
            ("nekoray", "NekoRay"),
            ("outline", "Outline"),
            ("wireguard", "WireGuard"),
            ("amnezia", "Amnezia"),
            ("openvpn", "OpenVPN"),
            ("warp", "Cloudflare WARP"),
            ("nordlynx", "NordVPN"),
            ("proton", "Proton VPN"),
            ("tailscale", "Tailscale"),
            ("radmin", "Radmin VPN"),
            ("hamachi", "Hamachi"),
        ):
            if needle in haystack:
                return label
        return self.name


def set_adapter_enabled(name: str, enabled: bool) -> bool:
    """Включить или выключить адаптер через netsh."""
    code, _ = winapi.run_hidden(
        ["netsh", "interface", "set", "interface",
         f"name={name}", f"admin={'enabled' if enabled else 'disabled'}"],
        timeout=30,
    )
    if code == 0:
        logs.info(f"Адаптер «{name}» {'включён' if enabled else 'выключен'}")
    return code == 0


def restore_paused_adapters() -> list[str]:
    """Вернуть адаптеры, выключенные прошлыми версиями программы.

    Список читаем прямо из файла настроек: ``config.load`` оставляет только
    ключи, описанные в ``DEFAULTS``, а ключа версий 2.x там уже нет — через
    обычный ``config.get`` он бы не нашёлся.
    """
    from app.core.config import config

    stored = config.raw().get(LEGACY_PAUSED_KEY) or []
    if not isinstance(stored, list):
        stored = []
    names = [str(name) for name in stored]
    restored = [name for name in names if set_adapter_enabled(name, True)]
    if names:
        config.drop_raw_key(LEGACY_PAUSED_KEY)
    return restored


def disabled_tunnels() -> list[str]:
    """Выключённые туннельные адаптеры — кандидаты на возврат вручную.

    Через GetAdaptersAddresses выключенный адаптер не виден вовсе, а
    «не подключён» и «выключен» там неразличимы. Поэтому спрашиваем
    PowerShell: AdminStatus = 2 означает именно «выключен администратором».
    Числовое значение не зависит от языка системы.
    """
    code, output = winapi.run_hidden(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-NetAdapter -IncludeHidden | ForEach-Object { "
         "$_.Name + '|' + [int]$_.AdminStatus + '|' + $_.InterfaceDescription }"],
        timeout=25,
    )
    if code != 0:
        return []

    found: list[str] = []
    for line in output.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) != 3 or parts[1] != "2":
            continue
        name, _status, description = parts
        haystack = f"{name} {description}".lower()
        if any(word in haystack for word in OWN_ADAPTERS):
            continue
        if any(word in haystack for word in winapi.PSEUDO_TUNNELS):
            continue
        if any(word in haystack for word in winapi.VPN_KEYWORDS):
            found.append(name)
    return found


def enable_all_tunnels() -> str:
    """Включить обратно всё выключенное — одна кнопка «почини мой VPN»."""
    restored = restore_paused_adapters()
    for name in disabled_tunnels():
        if name not in restored and set_adapter_enabled(name, True):
            restored.append(name)
    if not restored:
        return "Выключенных сетевых адаптеров не найдено — возвращать нечего."
    return "Включены обратно: " + ", ".join(restored)


def active_tunnels() -> list[Tunnel]:
    """Живые туннели сторонних клиентов."""
    return [
        Tunnel(adapter.name, adapter.description)
        for adapter in winapi.active_vpn_adapters()
        if not any(word in f"{adapter.name} {adapter.description}".lower()
                   for word in OWN_ADAPTERS)
    ]


def tunnel_names() -> list[str]:
    """Понятные названия живых туннелей без повторов."""
    return list(dict.fromkeys(tunnel.title for tunnel in active_tunnels()))
