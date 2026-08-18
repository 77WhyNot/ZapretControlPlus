"""Запуск sing-box и управление им через Clash API.

sing-box поднимает TUN-адаптер, поэтому нужны права администратора —
те же, что и для zapret.
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from app.core import logs, paths, winapi
from app.core.vpn import config as config_module
from app.core.vpn.links import Server

SINGBOX_EXE = "sing-box.exe"
# Wintun на Windows создаётся долго, особенно если адаптер уже был занят.
START_TIMEOUT = 75
CLASH_TIMEOUT = 4
DELAY_URL = "https://www.gstatic.com/generate_204"


@dataclass(frozen=True)
class VpnStatus:
    running: bool
    server: str = ""
    mode: str = config_module.MODE_SELECTED
    pid: int | None = None
    detail: str = ""


class VpnError(RuntimeError):
    pass


class _AdapterBusy(RuntimeError):
    """Адаптер занят зависшим устройством — стоит убрать и повторить."""


def singbox_path() -> Path:
    """Рядом с exe в собранном виде, в payload — при запуске из исходников."""
    if paths.is_frozen():
        return paths.app_dir() / "singbox" / SINGBOX_EXE
    return paths.app_dir() / "payload" / "singbox" / SINGBOX_EXE


def _free_port(preferred: int = 9797) -> int:
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
            except OSError:
                continue
    return preferred



def orphan_tunnels() -> list[str]:
    """Включённые туннельные адаптеры, чей владелец уже не работает.

    Клиент, снятый принудительно, оставляет адаптер включённым, и тот
    продолжает держать маршрут по умолчанию с нулевой метрикой. Такой
    маршрут выигрывает у настоящего шлюза, и весь трафик уходит в никуда.
    """
    from app.core.vpn import clients as vpn_clients

    if vpn_clients.running_clients():
        return []  # чужой клиент работает — его адаптер трогать нельзя

    ours = config_module.TUN_NAME.lower()
    found: list[str] = []
    for adapter in winapi.list_adapters():
        if not adapter.up:
            continue
        haystack = f"{adapter.name} {adapter.description}".lower()
        if "sing-tun" not in haystack and "wintun" not in haystack:
            continue
        if adapter.name.lower() == ours:
            continue
        found.append(adapter.name)
    return found


def set_adapter_enabled(name: str, enabled: bool) -> bool:
    """Включить или выключить адаптер.

    Устройство не удаляем: чужой клиент должен остаться работоспособным.
    Пока наш туннель поднят, его брошенный адаптер просто отключён, а на
    выходе мы возвращаем всё как было — и Happ снова заработает.
    """
    code, _ = winapi.run_hidden(
        ["netsh", "interface", "set", "interface",
         f"name={name}", f"admin={'enabled' if enabled else 'disabled'}"],
        timeout=30,
    )
    if code == 0:
        logs.info(
            f"Адаптер «{name}» {'включён обратно' if enabled else 'временно выключен'}"
        )
    return code == 0


PAUSED_KEY = "vpn_paused_adapters"


def paused_adapters() -> list[str]:
    from app.core.config import config

    return list(config.get(PAUSED_KEY, []) or [])


def remember_paused(name: str) -> None:
    from app.core.config import config

    names = paused_adapters()
    if name not in names:
        names.append(name)
        config.set(PAUSED_KEY, names)


def restore_paused_adapters() -> list[str]:
    """Вернуть все адаптеры, которые мы когда-либо выключали.

    Вызывается и при остановке, и при запуске приложения: если программу
    закрыли или она упала, адаптер иначе остался бы выключенным навсегда.
    """
    from app.core.config import config

    restored: list[str] = []
    for name in paused_adapters():
        if set_adapter_enabled(name, True):
            restored.append(name)
    if restored:
        config.set(PAUSED_KEY, [])
    return restored


def pause_adapter(name: str) -> bool:
    """Выключить чужой адаптер по явной команде — с записью на диск."""
    if set_adapter_enabled(name, False):
        remember_paused(name)
        return True
    return False


def free_busy_adapters() -> str:
    """Освободить адаптер по явной команде пользователя.

    Автоматически это не делается никогда: под чужим адаптером может
    работать VPN, которым человек пользуется прямо сейчас.
    """
    names = orphan_tunnels()
    if not names:
        return "Занятых чужих туннелей не найдено."
    done = [name for name in names if pause_adapter(name)]
    if not done:
        return "Не удалось отключить: " + ", ".join(names)
    return ("Временно отключено: " + ", ".join(done)
            + ". Вернём обратно, как только выключите VPN здесь.")


class VpnEngine:
    """Единая точка управления туннелем."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._secret = secrets.token_hex(16)
        self._port = 9797
        self._servers: list[Server] = []
        self._selected = ""
        self._mode = config_module.MODE_SELECTED
        self._started_at = 0.0
        self._probe_port = 0
        self._last_output: list[str] = []
        # Список храним в настройках: если приложение закроют или оно
        # упадёт, выключенный адаптер иначе останется выключенным навсегда.
        # Именно так у пользователя перестал работать чужой клиент.
        self.on_state_change: Callable[[], None] | None = None
        self.on_progress: Callable[[str], None] | None = None

    # --- состояние -------------------------------------------------------

    @property
    def config_path(self) -> Path:
        return paths.data_dir() / "singbox-config.json"

    def status(self) -> VpnStatus:
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            return VpnStatus(
                running=True,
                server=self._selected,
                mode=self._mode,
                pid=process.pid,
            )
        # Наш процесс мог пережить падение приложения — узнаём его по пути.
        ours = winapi.find_processes_by_path(SINGBOX_EXE, str(singbox_path()))
        if ours:
            return VpnStatus(
                running=True, server=self._selected, mode=self._mode, pid=ours[0],
                detail="туннель поднят прошлым запуском приложения",
            )
        return VpnStatus(running=False)

    def foreign_tunnel_pids(self) -> list[int]:
        """sing-box, запущенный другой программой (например, клиентом Happ).

        Такой процесс мы не трогаем: это чужой туннель, и убивать его нельзя.
        """
        return winapi.foreign_processes(SINGBOX_EXE, str(singbox_path()))

    def uptime_seconds(self) -> int:
        if not self._started_at:
            return 0
        return int(time.time() - self._started_at)

    def is_available(self) -> bool:
        return singbox_path().exists()

    # --- запуск ----------------------------------------------------------

    def start(
        self,
        servers: list[Server],
        selected: str,
        mode: str,
        vpn_apps: list[str] | None = None,
        direct_apps: list[str] | None = None,
        stack: str = config_module.STACK_DEFAULT,
    ) -> None:
        try:
            self._start_once(servers, selected, mode, vpn_apps, direct_apps,
                             stack, retried=False)
        except _AdapterBusy:
            # Чужой адаптер молча не выключаем: под ним может работать VPN,
            # которым человек пользуется прямо сейчас. Называем виновника и
            # предлагаем решить это осознанно.
            busy = ", ".join(orphan_tunnels()) or "другой туннель"
            raise VpnError(
                f"Сетевой адаптер занят: {busy}. Это чужой VPN-клиент — "
                "программа его не трогает, чтобы не оборвать вам связь. "
                "Отключите его сами либо нажмите «Освободить адаптер» "
                "на вкладке «Диагностика»."
            ) from None

    def _start_once(
        self,
        servers: list[Server],
        selected: str,
        mode: str,
        vpn_apps: list[str] | None,
        direct_apps: list[str] | None,
        stack: str,
        retried: bool,
    ) -> None:
        exe = singbox_path()
        if not exe.exists():
            raise VpnError(
                "Не найден движок VPN (sing-box.exe). Переустановите программу."
            )
        if not servers:
            raise VpnError(
                "Список серверов пуст. Добавьте ссылку-подписку на вкладке «Серверы»."
            )
        if not winapi.is_admin():
            raise VpnError("Нужны права администратора: VPN создаёт сетевой адаптер.")

        self.stop(quiet=True)

        # Убитый клиент оставляет свой адаптер включённым, и тот продолжает
        # держать маршруты — наш трафик уходит в него как в чёрную дыру.
        # Поэтому, если ни один чужой клиент не запущен, чистим все зависшие,
        # а не только свои.
        # Чужие адаптеры автоматически НЕ трогаем: под ними может работать
        # тот VPN, которым человек пользуется прямо сейчас. Конфликт
        # разруливается по явной команде на вкладке «Диагностика».

        self._port = _free_port(self._port)
        self._probe_port = _free_port(0)
        self._secret = secrets.token_hex(16)
        self._last_output = []
        from app.core.config import config as settings

        config = config_module.build_config(
            servers, selected=selected, mode=mode,
            vpn_apps=vpn_apps, direct_apps=direct_apps,
            clash_port=self._port, clash_secret=self._secret, stack=stack,
            strict_route=bool(settings.get("vpn_strict_route", False)),
            ipv6=bool(settings.get("vpn_ipv6", False)),
            mtu=int(settings.get("vpn_mtu", 9000)),
            dns_through_tunnel=bool(settings.get("vpn_dns_through_tunnel", True)),
            bypass_lan=bool(settings.get("vpn_bypass_lan", True)),
            dns_over_proxy=str(settings.get("vpn_dns_server", "1.1.1.1")),
            probe_port=self._probe_port,
        )
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Проверяем конфиг заранее: так пользователь увидит внятную причину
        # («неверный ключ Reality»), а не молчаливое падение процесса.
        problem = self.validate_config()
        if problem:
            raise VpnError(problem)

        mode_label = config_module.MODE_LABELS.get(mode, mode)
        logs.info(f"Запуск VPN: сервер «{selected}», режим «{mode_label}»")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            process = subprocess.Popen(
                [str(exe), "run", "-c", str(self.config_path), "--disable-color"],
                cwd=str(exe.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=winapi.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise VpnError(f"Не удалось запустить sing-box: {exc}") from exc

        with self._lock:
            self._process = process
            self._servers = list(servers)
            self._selected = selected
            self._mode = mode

        started = time.time()
        threading.Thread(target=self._pump, args=(process,), daemon=True).start()

        # Создание адаптера Wintun на Windows нередко занимает 20-40 секунд:
        # сам движок пишет об этом «open interface take too much time».
        # Пока процесс жив, обрывать его нельзя — он ещё поднимается.
        deadline = time.time() + START_TIMEOUT
        notified_slow = False
        while time.time() < deadline:
            if process.poll() is not None:
                reason = self._failure_reason()
                if self._adapter_conflict() and not retried:
                    logs.warn("Адаптер занят, убираю зависшие и пробую снова")
                    raise _AdapterBusy()
                raise VpnError(reason)
            if self._clash_alive():
                self._started_at = time.time()
                logs.info(f"VPN поднялся за {time.time() - started:.0f} с")
                self._notify()
                return
            if not notified_slow and time.time() - started > 10:
                notified_slow = True
                if self._is_slow_interface():
                    logs.info(
                        "Windows долго создаёт сетевой адаптер — это нормально, ждём"
                    )
                    if self.on_progress is not None:
                        self.on_progress(
                            "Windows создаёт сетевой адаптер. При первом запуске "
                            "это занимает до минуты…"
                        )
            time.sleep(0.5)

        self.stop(quiet=True)
        raise VpnError(
            f"VPN не поднялся за {START_TIMEOUT} секунд. " + self._failure_reason()
        )

    def _adapter_conflict(self) -> bool:
        """Движок не смог создать адаптер, потому что такой уже есть."""
        text = " ".join(self._last_output[-12:]).lower()
        return ("already exists" in text or "element not found" in text
                or "configure tun interface" in text)

    def _is_slow_interface(self) -> bool:
        """Движок сообщил, что адаптер создаётся долго."""
        text = " ".join(self._last_output[-12:]).lower()
        return "take too much time" in text or "open interface" in text

    def _failure_reason(self) -> str:
        """Настоящая причина из вывода движка, а не общая фраза."""
        text = " ".join(self._last_output[-12:]).lower()
        hints = (
            ("permission denied", "Нет прав на создание сетевого адаптера. "
                                  "Запустите программу от имени администратора."),
            ("take too much time", "Windows слишком долго создаёт сетевой адаптер. "
                                   "Обычно помогает перезагрузка: в системе остался "
                                   "висеть адаптер от другого VPN-клиента."),
            ("wintun", "Не удалось загрузить драйвер Wintun. Обычно мешает "
                       "антивирус или другой VPN-клиент, который держит адаптер."),
            ("configure tun", "Windows не дала создать адаптер туннеля. Чаще всего "
                              "его занял другой VPN-клиент — закройте его."),
            ("address already in use", "Порт занят другой программой."),
            ("bind: ", "Не удалось занять порт — мешает другая программа."),
            ("timeout", "Сервер подписки не отвечает. Смените сервер или проверьте интернет."),
            ("authentication failed", "Сервер отверг ключ. Обновите подписку."),
            ("reality", "Сервер отверг ключ Reality. Обновите подписку."),
            ("no such host", "Адрес сервера не разрешается. Проверьте DNS или интернет."),
            ("connection refused", "Сервер отказал в соединении. Попробуйте другой."),
        )
        for needle, message in hints:
            if needle in text:
                return message
        tail = self._last_output[-1] if self._last_output else ""
        if tail:
            return f"Движок сообщил: {tail}"
        return ("Движок завершился молча. Откройте «Диагностика» → журнал, "
                "там будет причина.")

    def exit_address(self, timeout: int = 12) -> dict[str, str]:
        """Куда мир видит наш выход: адрес и страна — через сам туннель."""
        if not self._probe_port:
            raise VpnError("VPN не запущен.")
        # Вход mixed принимает и HTTP, и SOCKS. Берём HTTP: схему socks5h
        # библиотека requests без отдельного пакета PySocks не понимает
        # и падает с InvalidSchema.
        proxies = {
            "http": f"http://127.0.0.1:{self._probe_port}",
            "https": f"http://127.0.0.1:{self._probe_port}",
        }
        errors = []
        for url in ("https://ipinfo.io/json", "https://api.ip.sb/geoip",
                    "https://ifconfig.co/json"):
            try:
                response = requests.get(url, proxies=proxies, timeout=timeout)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                errors.append(type(exc).__name__)
                continue
            return {
                "ip": str(data.get("ip") or data.get("query") or "?"),
                "country": str(data.get("country") or data.get("country_code") or "?"),
                "city": str(data.get("city") or ""),
                "org": str(data.get("org") or data.get("asn_org") or ""),
                "source": url.split("/")[2],
            }
        raise VpnError(
            "Туннель поднят, но наружу через него ничего не проходит "
            f"({', '.join(errors)}). Смените сервер."
        )

    def direct_address(self, timeout: int = 10) -> dict[str, str]:
        """Тот же запрос мимо туннеля — для сравнения."""
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get("https://ipinfo.io/json", timeout=timeout)
            data = response.json()
            return {"ip": str(data.get("ip") or "?"),
                    "country": str(data.get("country") or "?")}
        except (requests.RequestException, ValueError):
            return {"ip": "?", "country": "?"}
        finally:
            session.close()

    def validate_config(self) -> str:
        """Проверить конфиг движком. Пустая строка — всё в порядке."""
        exe = singbox_path()
        if not exe.exists() or not self.config_path.exists():
            return ""
        code, output = winapi.run_hidden(
            [str(exe), "check", "-c", str(self.config_path)], timeout=20
        )
        if code == 0:
            return ""
        text = re.sub(r"\x1b\[[0-9;]*m", "", output).strip()
        message = text.splitlines()[-1] if text else "конфигурация отклонена движком"
        message = message.replace("FATAL", "").strip()

        if "public_key" in message:
            return (
                "Движок не принял ключ Reality у одного из серверов. "
                "Обновите подписку — скорее всего, ссылка устарела."
            )
        if "uuid" in message.lower():
            return "Движок не принял идентификатор сервера. Обновите подписку."
        return f"Конфигурация VPN отклонена движком: {message}"

    def _pump(self, process: subprocess.Popen[bytes]) -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                line = winapi.decode_console(raw).rstrip()
                if line:
                    logs.write(line, "VPN")
                    self._last_output.append(line)
                    del self._last_output[:-40]
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass
            self._notify()

    def stop(self, quiet: bool = False) -> None:
        with self._lock:
            process = self._process
            self._process = None
        stopped = False
        if process is not None and process.poll() is None:
            stopped = True
            try:
                process.terminate()
                process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        # Только свои процессы: чужой туннель другого клиента не наше дело.
        if winapi.kill_processes_by_path(SINGBOX_EXE, str(singbox_path())):
            stopped = True
        self._started_at = 0.0

        restore_paused_adapters()

        if stopped and not quiet:
            logs.info("VPN отключён")
        self._notify()

    def _notify(self) -> None:
        callback = self.on_state_change
        if callback is not None:
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

    # --- Clash API -------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._port}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}"}

    def _clash_alive(self) -> bool:
        try:
            response = requests.get(
                self._url("/version"), headers=self._headers(), timeout=2
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def switch_server(self, tag: str) -> None:
        """Переключить активный сервер без перезапуска туннеля."""
        try:
            response = requests.put(
                self._url(f"/proxies/{config_module.PROXY_TAG}"),
                headers=self._headers(),
                json={"name": tag},
                timeout=CLASH_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise VpnError(f"Не удалось переключить сервер: {exc}") from exc
        if response.status_code >= 300:
            raise VpnError(
                f"Сервер «{tag}» не принят движком (код {response.status_code})."
            )
        self._selected = tag
        logs.info(f"VPN: активный сервер «{tag}»")
        self._notify()

    def current_server(self) -> str:
        try:
            response = requests.get(
                self._url(f"/proxies/{config_module.PROXY_TAG}"),
                headers=self._headers(), timeout=CLASH_TIMEOUT,
            )
            if response.status_code == 200:
                return str(response.json().get("now") or "")
        except (requests.RequestException, ValueError):
            pass
        return self._selected

    def measure_delay(self, tag: str, timeout_ms: int = 4000) -> int:
        """Задержка через сам туннель. -1 — сервер не ответил."""
        try:
            response = requests.get(
                self._url(f"/proxies/{tag}/delay"),
                headers=self._headers(),
                params={"timeout": timeout_ms, "url": DELAY_URL},
                timeout=(timeout_ms / 1000) + 3,
            )
            if response.status_code != 200:
                return -1
            return int(response.json().get("delay", -1))
        except (requests.RequestException, ValueError, TypeError):
            return -1

    def traffic_snapshot(self) -> tuple[int, int]:
        """Суммарно принято/отправлено байт за сессию."""
        try:
            response = requests.get(
                self._url("/connections"), headers=self._headers(),
                timeout=CLASH_TIMEOUT,
            )
            if response.status_code != 200:
                return 0, 0
            data = response.json()
            return int(data.get("downloadTotal", 0)), int(data.get("uploadTotal", 0))
        except (requests.RequestException, ValueError, TypeError):
            return 0, 0

    def active_connections(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(
                self._url("/connections"), headers=self._headers(),
                timeout=CLASH_TIMEOUT,
            )
            if response.status_code != 200:
                return []
            return list(response.json().get("connections") or [])
        except (requests.RequestException, ValueError, TypeError):
            return []

    def routed_connections(self) -> list[dict[str, Any]]:
        """Кто куда пошёл: программа, адрес и через какой выход.

        Это единственный способ увидеть, работает ли раздельный туннель:
        движок сам сообщает, какой цепочкой ушло каждое соединение.
        """
        result: list[dict[str, Any]] = []
        for item in self.active_connections():
            meta = item.get("metadata") or {}
            chains = item.get("chains") or []
            process = str(meta.get("processPath") or meta.get("process") or "")
            if process:
                process = process.replace("\\", "/").rsplit("/", 1)[-1]
            host = str(meta.get("host") or meta.get("destinationIP") or "")
            port = str(meta.get("destinationPort") or "")
            result.append({
                "process": process or "неизвестно",
                "target": f"{host}:{port}" if port else host,
                "outbound": chains[0] if chains else "?",
                "chain": " ← ".join(chains) if chains else "",
                "network": str(meta.get("network") or ""),
            })
        return result

    def shutdown(self) -> None:
        self.stop(quiet=True)


vpn_engine = VpnEngine()
