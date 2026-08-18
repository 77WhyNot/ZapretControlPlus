"""Другие VPN-клиенты на компьютере.

Два туннеля одновременно не работают: оба перехватывают маршрут по умолчанию
и дерутся за него. Поэтому программа умеет найти чужой клиент и предложить
его закрыть — но только по явной команде пользователя.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import logs, winapi


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


def stop_client(client: VpnClient) -> tuple[int, list[str]]:
    """Закрыть клиент. Возвращает (сколько процессов снято, что не удалось)."""
    stopped = 0
    failed: list[str] = []
    for process_name in client.processes:
        pids = winapi.find_processes(process_name)
        if not pids:
            continue
        killed = winapi.kill_processes(process_name)
        stopped += killed
        if killed < len(pids):
            failed.append(process_name)

    # Часть клиентов ставит службу — без её остановки туннель поднимется снова.
    for service in _service_candidates(client):
        try:
            if winapi.service_running(service):
                winapi.service_stop(service, timeout=8)
                stopped += 1
        except winapi.ServiceError:
            failed.append(service)

    if stopped:
        logs.info(f"Закрыт сторонний VPN-клиент: {client.title}")
    return stopped, failed


def _service_candidates(client: VpnClient) -> tuple[str, ...]:
    table = {
        "happ": ("HappService", "happd"),
        "outline": ("OutlineService",),
        "amnezia": ("AmneziaVPN",),
        "warp": ("CloudflareWARP",),
        "proton": ("ProtonVPNService",),
        "nord": ("nordvpn-service", "NordVPN Service"),
        "wireguard": (),
        "openvpn": ("OpenVPNService", "OpenVPNServiceInteractive"),
    }
    names = table.get(client.key, ())
    installed = winapi.installed_service_names()
    return tuple(name for name in names if name in installed)


def stop_all(clients: list[RunningClient]) -> str:
    """Закрыть все найденные клиенты и вернуть текст для пользователя."""
    if not clients:
        return "Сторонние VPN-клиенты не запущены."
    done: list[str] = []
    problems: list[str] = []
    for item in clients:
        stopped, failed = stop_client(item.client)
        if stopped:
            done.append(item.title)
        if failed:
            problems.append(f"{item.title} ({', '.join(failed)})")

    parts = []
    if done:
        parts.append("Закрыто: " + ", ".join(done) + ".")
    if problems:
        parts.append("Не удалось полностью закрыть: " + ", ".join(problems)
                     + ". Возможно, нужны права администратора.")
    return " ".join(parts) or "Ничего закрывать не пришлось."


def describe() -> str:
    found = running_clients()
    if not found:
        return "чужих туннелей не найдено"
    return ", ".join(item.title for item in found)
