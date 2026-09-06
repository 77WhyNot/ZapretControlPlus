"""Другие VPN-клиенты на компьютере — только чтобы знать, что они есть.

Программа их никогда не закрывает: под чужим клиентом может работать
VPN, которым человек пользуется прямо сейчас.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import winapi


@dataclass(frozen=True)
class VpnClient:
    key: str
    title: str
    processes: tuple[str, ...]
    hint: str = ""


# Процессы перечислены целиком: у многих клиентов есть отдельная служба,
# которая поднимет туннель заново, если закрыть только окно.
KNOWN_CLIENTS: tuple[VpnClient, ...] = (
    VpnClient("happ", "Happ", ("Happ.exe", "happd.exe"),
              "Оконный клиент и служба happd, которая держит туннель."),
    VpnClient("hiddify", "Hiddify", ("Hiddify.exe", "HiddifyCli.exe")),
    VpnClient("nekoray", "NekoRay / NekoBox", ("nekoray.exe", "nekobox.exe",
                                               "nekobox_core.exe")),
    # xray.exe и sing-box.exe намеренно не перечисляем: это общие ядра,
    # их запускают разные клиенты, и по ним нельзя понять чей туннель.
    VpnClient("v2rayn", "v2rayN", ("v2rayN.exe", "v2rayN-Core.exe")),
    VpnClient("clash", "Clash / Mihomo", ("clash.exe", "clash-win64.exe",
                                          "mihomo.exe", "Clash for Windows.exe")),
    VpnClient("outline", "Outline", ("Outline.exe", "OutlineService.exe",
                                     "tun2socks.exe")),
    VpnClient("amnezia", "AmneziaVPN", ("AmneziaVPN.exe", "AmneziaVPN-service.exe")),
    VpnClient("wireguard", "WireGuard", ("wireguard.exe", "wg.exe")),
    VpnClient("openvpn", "OpenVPN", ("openvpn.exe", "openvpn-gui.exe")),
    VpnClient("warp", "Cloudflare WARP", ("Cloudflare WARP.exe", "warp-svc.exe")),
    VpnClient("proton", "Proton VPN", ("ProtonVPN.exe", "ProtonVPNService.exe")),
    VpnClient("nord", "NordVPN", ("NordVPN.exe", "nordvpn-service.exe")),
)


@dataclass
class RunningClient:
    client: VpnClient
    pids: list[int]

    @property
    def title(self) -> str:
        return self.client.title


def running_clients(exclude_own: str = "") -> list[RunningClient]:
    """Найти запущенные сторонние VPN-клиенты."""
    own = exclude_own.lower()
    found: list[RunningClient] = []
    snapshot = list(winapi.iter_processes())

    for client in KNOWN_CLIENTS:
        pids: list[int] = []
        for pid, name in snapshot:
            low = name.lower()
            if low == own:
                continue
            if any(low == candidate.lower() for candidate in client.processes):
                pids.append(pid)
        if pids:
            found.append(RunningClient(client=client, pids=pids))
    return found


def describe() -> str:
    found = running_clients()
    if not found:
        return "чужих туннелей не найдено"
    return ", ".join(item.title for item in found)
