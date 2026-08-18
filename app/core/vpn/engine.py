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
        self.on_state_change: Callable[[], None] | None = None

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

        self._port = _free_port(self._port)
        self._secret = secrets.token_hex(16)
        config = config_module.build_config(
            servers, selected=selected, mode=mode,
            vpn_apps=vpn_apps, direct_apps=direct_apps,
            clash_port=self._port, clash_secret=self._secret, stack=stack,
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

        threading.Thread(target=self._pump, args=(process,), daemon=True).start()

        # Ждём, пока поднимется управляющий интерфейс.
        deadline = time.time() + 12
        while time.time() < deadline:
            if process.poll() is not None:
                raise VpnError(
                    "sing-box завершился сразу после запуска. Проверьте журнал: "
                    "чаще всего дело в неверном ключе подписки."
                )
            if self._clash_alive():
                self._started_at = time.time()
                self._notify()
                return
            time.sleep(0.4)

        self.stop(quiet=True)
        raise VpnError("VPN не поднялся за 12 секунд. Подробности — в журнале.")

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

    def shutdown(self) -> None:
        self.stop(quiet=True)


vpn_engine = VpnEngine()
