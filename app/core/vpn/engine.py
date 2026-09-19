"""Запуск sing-box и управление им через Clash API.

Правила безопасности, выстраданные на практике:

* чужие туннели, адаптеры и процессы программа **никогда не трогает** —
  под ними может работать VPN, которым человек пользуется прямо сейчас;
* в режиме «Туннель» при живом чужом туннеле мы просто не стартуем и
  объясняем почему; в режиме «Прокси» уживаемся с кем угодно;
* убираем только своё: свой процесс (по пути к файлу) и свой адаптер
  (по имени), и только если они остались от прошлого запуска.
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

from app.core import logs, netadapters, paths, sysproxy, winapi
from app.core.vpn import config as config_module
from app.core.vpn.links import Server

SINGBOX_EXE = "sing-box.exe"
# Wintun на Windows создаётся долго, особенно если адаптер уже был занят.
START_TIMEOUT = 75
PROXY_START_TIMEOUT = 20
CLASH_TIMEOUT = 4
DELAY_URL = "https://www.gstatic.com/generate_204"


@dataclass(frozen=True)
class VpnStatus:
    running: bool
    server: str = ""
    mode: str = config_module.MODE_SELECTED
    transport: str = config_module.TRANSPORT_TUN
    pid: int | None = None
    detail: str = ""


class VpnError(RuntimeError):
    pass


class VpnSuperseded(VpnError):
    """Запуск отменён более свежим запросом.

    Человеку об этом сообщать нечего: он сам только что нажал что-то ещё.
    """


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


def own_adapter_present() -> bool:
    """Наш адаптер остался в системе (движок упал или его сняли силой)."""
    wanted = config_module.TUN_NAME.lower()
    return any(adapter.name.lower() == wanted for adapter in winapi.list_adapters())


def remove_own_adapter() -> bool:
    """Убрать только свой адаптер — по имени, ничего чужого.

    Брошенный адаптер держит маршрут по умолчанию, и трафик уходит в него
    как в чёрную дыру. Wintun обычно удаляет его сам, но после падения
    процесса он остаётся.
    """
    if not own_adapter_present():
        return False
    name = config_module.TUN_NAME
    code, _ = winapi.run_hidden(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"Get-PnpDevice -Class Net -ErrorAction SilentlyContinue | "
         f"Where-Object {{ $_.FriendlyName -eq '{name}' }} | "
         "ForEach-Object { pnputil /remove-device $_.InstanceId | Out-Null }"],
        timeout=30,
    )
    if code != 0 or own_adapter_present():
        # Хотя бы обесточить: выключенный адаптер маршрутов не держит.
        winapi.run_hidden(
            ["netsh", "interface", "set", "interface", f"name={name}", "admin=disabled"],
            timeout=20,
        )
    gone = not own_adapter_present()
    logs.info("Свой брошенный адаптер убран" if gone
              else "Свой брошенный адаптер выключен")
    return True


class VpnEngine:
    """Единая точка управления туннелем."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        # Запуск и остановка — строго по одному за раз. Без этого два
        # одновременных запуска (например, «сменил режим» и «отметил
        # программу») убивали процессы друг друга и оставляли брошенный
        # адаптер: со стороны выглядело как «VPN вообще перестал работать».
        self._op_lock = threading.RLock()
        self._request = 0
        # Сколько запусков сейчас в пути. Нужно интерфейсу: пока туннель
        # поднимается (при старте это до 20 секунд), тумблер должен показывать
        # «подключается», а не «выключен» — иначе человек жмёт ещё раз.
        self._starting = 0
        self._secret = secrets.token_hex(16)
        self._port = 9797
        self._servers: list[Server] = []
        self._selected = ""
        self._mode = config_module.MODE_SELECTED
        self._transport = config_module.TRANSPORT_TUN
        self._started_at = 0.0
        self._probe_port = 0
        self._proxy_applied = False
        self._last_output: list[str] = []
        # Режим «Прокси» направляет системный прокси на нас. В проверках это
        # выключают: иначе на время теста прокси получает вся машина.
        self.apply_system_proxy = True
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
                running=True, server=self._selected, mode=self._mode,
                transport=self._transport, pid=process.pid,
            )
        return VpnStatus(running=False, transport=self._transport)

    def foreign_tunnel_pids(self) -> list[int]:
        """sing-box, запущенный другой программой (например, клиентом Happ).

        Такой процесс мы не трогаем: это чужой туннель, и убивать его нельзя.
        """
        return winapi.foreign_processes(SINGBOX_EXE, str(singbox_path()))

    @staticmethod
    def foreign_tunnels() -> list[str]:
        """Живые чужие туннели — с ними режим «Туннель» не уживётся."""
        return netadapters.tunnel_names()

    def uptime_seconds(self) -> int:
        if not self._started_at:
            return 0
        return int(time.time() - self._started_at)

    def is_available(self) -> bool:
        return singbox_path().exists()

    @property
    def transport(self) -> str:
        return self._transport

    def proxy_url(self) -> str | None:
        """HTTP-прокси нашего движка, когда VPN работает режимом «Прокси».

        В этом режиме трафик уходит в VPN только через системный прокси, а он
        локальный. Проверка доступности должна идти этим же путём, иначе она
        тестирует прямой (заблокированный) канал и показывает «недоступно».
        """
        if (self.status().running
                and self._transport == config_module.TRANSPORT_PROXY
                and self._probe_port):
            return f"http://127.0.0.1:{self._probe_port}"
        return None

    def local_proxy_url(self) -> str | None:
        """Локальный вход движка в любом режиме.

        В режиме «Прокси» это тот же прокси, что получает вся система, а в
        режиме «Туннель» — служебный вход, который правилами всегда заведён
        в VPN. Он нужен программам, которые ходят мимо системного прокси, —
        например языковому серверу Antigravity на Go.
        """
        if self.status().running and self._probe_port:
            return f"http://127.0.0.1:{self._probe_port}"
        return None

    # --- наследство прошлого запуска -------------------------------------

    def restore_leftovers(self) -> list[str]:
        """Прибрать за собой после падения: процесс, адаптер, системный прокси.

        Только своё. Возвращает список того, что пришлось чинить.
        """
        with self._op_lock:
            return self._restore_locked()

    def _restore_locked(self) -> list[str]:
        fixed: list[str] = []
        try:
            if winapi.kill_processes_by_path(SINGBOX_EXE, str(singbox_path())):
                fixed.append("движок")
                time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            logs.warn(f"Не удалось снять свой старый движок: {exc}")
        try:
            if winapi.is_admin() and remove_own_adapter():
                fixed.append("адаптер")
        except Exception as exc:  # noqa: BLE001
            logs.warn(f"Не удалось убрать свой адаптер: {exc}")
        try:
            if sysproxy.restore_if_left():
                fixed.append("системный прокси")
        except Exception as exc:  # noqa: BLE001
            logs.warn(f"Не удалось вернуть системный прокси: {exc}")
        return fixed

    # --- запуск и очередь запросов ---------------------------------------

    def _new_request(self) -> int:
        """Каждый запрос получает номер: побеждает самый свежий."""
        with self._lock:
            self._request += 1
            return self._request

    def _superseded(self, token: int) -> bool:
        with self._lock:
            return token != self._request

    def start(
        self,
        servers: list[Server],
        selected: str,
        mode: str,
        vpn_apps: list[str] | None = None,
        direct_apps: list[str] | None = None,
        stack: str = config_module.STACK_DEFAULT,
        transport: str | None = None,
    ) -> None:
        from app.core.config import config as settings

        token = self._new_request()
        exe = singbox_path()
        if not exe.exists():
            raise VpnError(
                "Не найден движок VPN (sing-box.exe). Переустановите программу."
            )
        if not servers:
            raise VpnError(
                "Список серверов пуст. Добавьте ссылку-подписку на вкладке «VPN»."
            )
        if transport is None:
            transport = str(settings.get("vpn_transport", config_module.TRANSPORT_TUN))
        if transport not in config_module.TRANSPORT_LABELS:
            transport = config_module.TRANSPORT_TUN

        # Режим «только выбранные», но никто не выбран — туннель поднимется и
        # не сделает ровным счётом ничего. Честнее сказать это сразу.
        if (transport == config_module.TRANSPORT_TUN
                and mode == config_module.MODE_SELECTED
                and not [name for name in (vpn_apps or []) if name]):
            raise VpnError(
                "Выбран режим «Только выбранные программы», но ни одна программа "
                "не отмечена — через VPN не пойдёт ничего. Откройте «Программы VPN» "
                "и отметьте нужные либо выберите «Весь трафик»."
            )

        if transport == config_module.TRANSPORT_TUN:
            # Сначала про чужой туннель: это самая частая и самая понятная
            # причина, и для неё права не нужны.
            foreign = self.foreign_tunnels()
            if foreign:
                names = ", ".join(foreign)
                raise VpnError(
                    f"Сейчас работает другой VPN — {names}. Два туннеля одновременно "
                    "не уживаются, а чужой программа не трогает. Выключите его сами "
                    "или переключите VPN в режим «Прокси» — он не трогает маршруты "
                    "и работает рядом с любым клиентом."
                )
            if not winapi.is_admin():
                raise VpnError("Нужны права администратора: VPN создаёт сетевой адаптер.")

        # Дальше — по очереди: пока идёт чужой запуск, свой не начинаем.
        # Иначе два запуска снимают процессы друг друга и дерутся за адаптер.
        with self._lock:
            self._starting += 1
        try:
            with self._op_lock:
                if self._superseded(token):
                    logs.info("Запуск VPN отменён: пришёл более свежий запрос")
                    return
                try:
                    self._start_queued(token, servers, selected, mode, vpn_apps,
                                       direct_apps, stack, transport, settings)
                except VpnSuperseded:
                    logs.info("Запуск VPN прерван: пришёл более свежий запрос")
        finally:
            with self._lock:
                self._starting -= 1

    def is_starting(self) -> bool:
        """Туннель прямо сейчас поднимается."""
        with self._lock:
            return self._starting > 0

    def _start_queued(
        self,
        token: int,
        servers: list[Server],
        selected: str,
        mode: str,
        vpn_apps: list[str] | None,
        direct_apps: list[str] | None,
        stack: str,
        transport: str,
        settings,
    ) -> None:
        self._stop_locked(quiet=True)

        # Туннель на холодную нередко не встаёт с первой попытки: Windows долго
        # создаёт адаптер Wintun, а от прерванной попытки остаётся «повисший»
        # адаптер, и sing-box жалуется «create adapter: file already exists».
        # Лечится одним — убрать свой адаптер и попробовать снова. Ровно это и
        # делал ручной путь «прокси → туннель». Прокси встаёт сразу, ему повтор
        # не нужен.
        attempts = 3 if transport == config_module.TRANSPORT_TUN else 1
        last_error = ""
        for attempt in range(attempts):
            if transport == config_module.TRANSPORT_TUN:
                # Свой брошенный адаптер держит маршруты и мешает создать новый.
                remove_own_adapter()
                if attempt:
                    time.sleep(1.5)
            try:
                self._start_once(token, servers, selected, mode, vpn_apps,
                                 direct_apps, stack, transport, settings)
                return
            except VpnSuperseded:
                raise
            except VpnError as exc:
                last_error = str(exc)
                if transport != config_module.TRANSPORT_TUN or not self._adapter_conflict():
                    raise
                logs.warn(
                    f"Туннель не поднялся ({last_error}); убираю свой адаптер "
                    "и пробую снова"
                )
        self._stop_locked(quiet=True)
        raise VpnError(
            (last_error + " Помогает перезагрузка компьютера.")
            if last_error else "VPN не поднялся."
        )

    def _adapter_conflict(self) -> bool:
        """Движок не смог создать или открыть адаптер — поможет повторная попытка."""
        text = " ".join(self._last_output[-14:]).lower()
        return any(marker in text for marker in (
            "already exists", "element not found", "configure tun",
            "create adapter", "take too much time", "open interface",
        ))

    def _start_once(
        self,
        token: int,
        servers: list[Server],
        selected: str,
        mode: str,
        vpn_apps: list[str] | None,
        direct_apps: list[str] | None,
        stack: str,
        transport: str,
        settings,
    ) -> None:
        exe = singbox_path()
        self._port = _free_port(self._port)
        self._secret = secrets.token_hex(16)
        self._last_output = []
        proxy_port = int(settings.get("vpn_proxy_port", 10808) or 10808)
        if transport == config_module.TRANSPORT_PROXY:
            proxy_port = _free_port(proxy_port)
            self._probe_port = proxy_port
        else:
            self._probe_port = _free_port(0)

        # Прокси Smart DNS для Gemini и Antigravity: адрес берём из кэша, а если
        # он устарел — спрашиваем сервис. Без сети просто пойдём через VPN.
        try:
            from app.core import google as google_module

            google_proxy_ip, google_proxy_hosts = google_module.smartdns_route()
        except Exception as exc:  # noqa: BLE001
            logs.warn(f"Прокси Smart DNS для Google не получен: {exc}")
            google_proxy_ip, google_proxy_hosts = "", []

        config = config_module.build_config(
            servers, selected=selected, mode=mode,
            vpn_apps=vpn_apps, direct_apps=direct_apps,
            clash_port=self._port, clash_secret=self._secret, stack=stack,
            strict_route=bool(settings.get("vpn_strict_route", False)),
            ipv6=bool(settings.get("vpn_ipv6", False)),
            mtu=int(settings.get("vpn_mtu", 9000)),
            dns_through_tunnel=bool(settings.get("vpn_dns_through_tunnel", False)),
            bypass_lan=bool(settings.get("vpn_bypass_lan", True)),
            dns_over_proxy=str(settings.get("vpn_dns_server", "1.1.1.1")),
            probe_port=self._probe_port if transport == config_module.TRANSPORT_TUN else 0,
            transport=transport,
            proxy_port=proxy_port,
            google_via_vpn=bool(settings.get("google_route_vpn", True)),
            google_proxy_ip=google_proxy_ip,
            google_proxy_hosts=google_proxy_hosts,
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
        transport_label = "туннель" if transport == config_module.TRANSPORT_TUN else "прокси"
        logs.info(f"Запуск VPN ({transport_label}): сервер «{selected}», режим «{mode_label}»")
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
            self._transport = transport

        started = time.time()
        threading.Thread(target=self._pump, args=(process,), daemon=True).start()

        # Создание адаптера Wintun на Windows нередко занимает 20-40 секунд:
        # сам движок пишет об этом «open interface take too much time».
        # Пока процесс жив, обрывать его нельзя — он ещё поднимается.
        timeout = START_TIMEOUT if transport == config_module.TRANSPORT_TUN else PROXY_START_TIMEOUT
        deadline = time.time() + timeout
        notified_slow = False
        while time.time() < deadline:
            if self._superseded(token):
                # Человек уже нажал что-то ещё: сворачиваемся и уступаем.
                self._abandon(process)
                raise VpnSuperseded("Запуск VPN отменён.")
            if process.poll() is not None:
                # Процесс умер — прибираем свой мусор, чтобы повтор начался с нуля.
                winapi.kill_processes_by_path(SINGBOX_EXE, str(singbox_path()))
                with self._lock:
                    self._process = None
                raise VpnError(self._failure_reason())
            if self._clash_alive():
                self._started_at = time.time()
                logs.info(f"VPN поднялся за {time.time() - started:.0f} с")
                if transport == config_module.TRANSPORT_PROXY and self.apply_system_proxy:
                    sysproxy.apply(proxy_port)
                    self._proxy_applied = True
                self._notify()
                return
            if not notified_slow and time.time() - started > 10:
                notified_slow = True
                if self._is_slow_interface() and self.on_progress is not None:
                    self.on_progress(
                        "Windows создаёт сетевой адаптер. При первом запуске "
                        "это занимает до минуты…"
                    )
            time.sleep(0.5)

        self._stop_locked(quiet=True)
        raise VpnError(f"VPN не поднялся за {timeout} секунд. " + self._failure_reason())

    def _abandon(self, process: subprocess.Popen[bytes]) -> None:
        """Снять только что запущенный свой процесс, ничего больше не трогая."""
        with self._lock:
            if self._process is process:
                self._process = None
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def _is_slow_interface(self) -> bool:
        text = " ".join(self._last_output[-12:]).lower()
        return "take too much time" in text or "open interface" in text

    def _failure_reason(self) -> str:
        """Настоящая причина из вывода движка, а не общая фраза."""
        text = " ".join(self._last_output[-12:]).lower()
        hints = (
            ("permission denied", "Нет прав на создание сетевого адаптера. "
                                  "Запустите программу от имени администратора."),
            ("take too much time", "Windows слишком долго создаёт сетевой адаптер. "
                                   "Обычно помогает перезагрузка."),
            ("wintun", "Не удалось загрузить драйвер Wintun. Обычно мешает "
                       "антивирус или другой VPN-клиент, который держит адаптер."),
            ("already exists", "Windows не дала создать адаптер: такой уже есть. "
                               "Помогает перезагрузка."),
            ("configure tun", "Windows не дала создать адаптер туннеля. Чаще всего "
                              "его занял другой VPN-клиент — выключите его или "
                              "переключитесь в режим «Прокси»."),
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
        if not self._probe_port or not self.status().running:
            raise VpnError("VPN не запущен.")
        # Вход mixed принимает и HTTP, и SOCKS. Берём HTTP: схему socks5h
        # библиотека requests без отдельного пакета PySocks не понимает.
        proxies = {
            "http": f"http://127.0.0.1:{self._probe_port}",
            "https": f"http://127.0.0.1:{self._probe_port}",
        }
        errors = []
        for url in ("https://ipinfo.io/json", "https://api.ip.sb/geoip",
                    "https://ifconfig.co/json"):
            try:
                session = requests.Session()
                session.trust_env = False
                response = session.get(url, proxies=proxies, timeout=timeout)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                errors.append(type(exc).__name__)
                continue
            finally:
                session.close()
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
        # Номер запроса прерывает чужой запуск: тот увидит, что его обогнали,
        # свернётся сам и освободит очередь.
        self._new_request()
        with self._op_lock:
            self._stop_locked(quiet=quiet)

    def _stop_locked(self, quiet: bool = False) -> None:
        with self._lock:
            process = self._process
            self._process = None
            transport = self._transport
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

        if self._proxy_applied or sysproxy.read().get("server", "").endswith(
                f"127.0.0.1:{self._probe_port}") and self._probe_port:
            sysproxy.restore()
        self._proxy_applied = False

        if stopped and transport == config_module.TRANSPORT_TUN:
            # Wintun убирает адаптер сам; если не успел — уберём свой.
            time.sleep(0.8)
            try:
                remove_own_adapter()
            except Exception as exc:  # noqa: BLE001
                logs.warn(f"Не удалось убрать свой адаптер: {exc}")

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
                self._url("/version"), headers=self._headers(), timeout=2,
                proxies={"http": None, "https": None},
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def switch_server(self, tag: str) -> None:
        """Переключить активный сервер без перезапуска туннеля."""
        try:
            response = requests.put(
                self._url(f"/proxies/{config_module.PROXY_TAG}"),
                headers=self._headers(), json={"name": tag},
                timeout=CLASH_TIMEOUT, proxies={"http": None, "https": None},
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
                proxies={"http": None, "https": None},
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
                proxies={"http": None, "https": None},
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
                timeout=CLASH_TIMEOUT, proxies={"http": None, "https": None},
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
                timeout=CLASH_TIMEOUT, proxies={"http": None, "https": None},
            )
            if response.status_code != 200:
                return []
            return list(response.json().get("connections") or [])
        except (requests.RequestException, ValueError, TypeError):
            return []

    def routed_connections(self) -> list[dict[str, Any]]:
        """Кто куда пошёл: программа, адрес и через какой выход."""
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
