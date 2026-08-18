"""Запуск и остановка zapret: как обычный процесс либо как служба Windows.

Два режима отличаются временем жизни:
  * ``process`` — winws.exe живёт, пока открыто приложение;
  * ``service`` — служба ``zapret`` работает всегда, в том числе до входа
    в систему и после перезагрузки.
"""

from __future__ import annotations

import subprocess
import threading
import time
import winreg
from dataclasses import dataclass
from typing import Callable

from app.core import logs, paths, strategies, winapi
from app.core.constants import (
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY,
    SERVICE_NAME,
    SERVICE_REG_PATH,
    SERVICE_REG_VALUE,
    WINDIVERT_SERVICES,
    WINWS_EXE,
)
from app.core.strategies import Strategy

MODE_PROCESS = "process"
MODE_SERVICE = "service"


@dataclass(frozen=True)
class Status:
    running: bool
    mode: str                    # process | service | none
    strategy_id: str = ""
    pid: int | None = None
    external: bool = False       # запущено не нашим приложением
    detail: str = ""

    @property
    def mode_label(self) -> str:
        if not self.running:
            return "остановлено"
        if self.mode == MODE_SERVICE:
            return "служба Windows"
        return "процесс" + (" (внешний)" if self.external else "")


class EngineError(RuntimeError):
    pass


class Engine:
    """Единая точка управления обходом."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._process_strategy: str = ""
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._started_at: float = 0.0
        self.on_state_change: Callable[[], None] | None = None

    # --- состояние -------------------------------------------------------

    def status(self) -> Status:
        state = winapi.service_state(SERVICE_NAME)
        if state in ("running", "start_pending"):
            return Status(
                running=True,
                mode=MODE_SERVICE,
                strategy_id=self.service_strategy() or "",
                detail="служба запущена",
            )

        with self._lock:
            process = self._process
            strategy_id = self._process_strategy
        if process is not None and process.poll() is None:
            return Status(
                running=True,
                mode=MODE_PROCESS,
                strategy_id=strategy_id,
                pid=process.pid,
            )

        external = winapi.find_processes(WINWS_EXE)
        if external:
            return Status(
                running=True,
                mode=MODE_PROCESS,
                strategy_id="",
                pid=external[0],
                external=True,
                detail="winws.exe запущен вне приложения",
            )

        detail = ""
        if state is not None:
            detail = f"служба установлена, состояние: {state}"
        return Status(running=False, mode="none", detail=detail)

    def uptime_seconds(self) -> int:
        if not self._started_at:
            return 0
        return int(time.time() - self._started_at)

    def service_installed(self) -> bool:
        return winapi.service_exists(SERVICE_NAME)

    def service_strategy(self) -> str | None:
        return winapi.reg_read(
            winreg.HKEY_LOCAL_MACHINE, SERVICE_REG_PATH, SERVICE_REG_VALUE
        )

    # --- запуск ----------------------------------------------------------

    def start(self, strategy: Strategy, mode: str) -> None:
        if not paths.core_is_valid():
            raise EngineError(
                "Не найдено ядро zapret (bin\\winws.exe). "
                "Переустановите программу или восстановите ядро на вкладке «Обновления»."
            )
        if not winapi.is_admin():
            raise EngineError(
                "Нужны права администратора: WinDivert загружает драйвер режима ядра."
            )

        self.stop(quiet=True)
        winapi.enable_tcp_timestamps()

        if mode == MODE_SERVICE:
            self._start_service(strategy)
        else:
            self._start_process(strategy)

        self._started_at = time.time()
        self._notify()

    def _start_process(self, strategy: Strategy) -> None:
        command = strategies.build_command_line(strategy)
        logs.info(f"Запуск процесса: стратегия «{strategy.title}»")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            process = subprocess.Popen(
                command,
                cwd=str(paths.bin_dir()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=winapi.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise EngineError(f"Не удалось запустить winws.exe: {exc}") from exc

        with self._lock:
            self._process = process
            self._process_strategy = strategy.id

        self._reader = threading.Thread(
            target=self._pump_output, args=(process,), daemon=True
        )
        self._reader.start()

        # Даём процессу мгновение упасть, если аргументы неверные.
        time.sleep(1.2)
        if process.poll() is not None:
            with self._lock:
                self._process = None
            raise EngineError(
                f"winws.exe завершился сразу после запуска (код {process.returncode}). "
                "Подробности — в журнале."
            )

    def _pump_output(self, process: subprocess.Popen[bytes]) -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                line = winapi.decode_console(raw).rstrip()
                if line:
                    logs.write(line, "WINWS")
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass
            code = process.poll()
            if code not in (None, 0):
                logs.warn(f"winws.exe завершился с кодом {code}")
            self._notify()

    def _start_service(self, strategy: Strategy) -> None:
        command = strategies.build_command_line(strategy)
        logs.info(f"Установка службы: стратегия «{strategy.title}»")
        try:
            winapi.service_stop(SERVICE_NAME)
            winapi.service_delete(SERVICE_NAME)
        except winapi.ServiceError:
            pass

        # Windows может держать удалённую службу до закрытия последнего
        # дескриптора — коротко подождём, иначе CreateService вернёт 1072.
        for _ in range(12):
            if not winapi.service_exists(SERVICE_NAME):
                break
            time.sleep(0.25)

        try:
            winapi.service_create(
                SERVICE_NAME, SERVICE_DISPLAY, command,
                description=SERVICE_DESCRIPTION, autostart=True,
            )
            winapi.reg_write(
                winreg.HKEY_LOCAL_MACHINE, SERVICE_REG_PATH,
                SERVICE_REG_VALUE, strategy.id,
            )
            winapi.service_start(SERVICE_NAME)
        except winapi.ServiceError as exc:
            raise EngineError(str(exc)) from exc

        time.sleep(1.0)
        state = winapi.service_state(SERVICE_NAME)
        if state not in ("running", "start_pending"):
            raise EngineError(
                "Служба установлена, но не запустилась. "
                "Проверьте диагностику — обычно мешает другой обходчик DPI."
            )

    # --- остановка -------------------------------------------------------

    def stop(self, quiet: bool = False, remove_service: bool = True) -> None:
        stopped_something = False

        with self._lock:
            process = self._process
            self._process = None
            self._process_strategy = ""
        if process is not None and process.poll() is None:
            stopped_something = True
            try:
                process.terminate()
                process.wait(timeout=6)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

        if winapi.service_exists(SERVICE_NAME):
            stopped_something = True
            try:
                winapi.service_stop(SERVICE_NAME)
                if remove_service:
                    winapi.service_delete(SERVICE_NAME)
            except winapi.ServiceError as exc:
                if not quiet:
                    raise EngineError(str(exc)) from exc

        if winapi.process_running(WINWS_EXE):
            stopped_something = True
            winapi.kill_processes(WINWS_EXE)

        self._cleanup_windivert()
        self._started_at = 0.0

        if stopped_something and not quiet:
            logs.info("Обход остановлен")
        self._notify()

    def _cleanup_windivert(self) -> None:
        """Драйвер иногда остаётся висеть и мешает следующему запуску."""
        if winapi.process_running(WINWS_EXE):
            return
        for name in WINDIVERT_SERVICES:
            if not winapi.service_exists(name):
                continue
            try:
                winapi.service_stop(name, timeout=6)
                winapi.service_delete(name)
            except winapi.ServiceError:
                continue

    def restart(self, strategy: Strategy, mode: str) -> None:
        self.stop(quiet=True)
        self.start(strategy, mode)

    # --- служебное -------------------------------------------------------

    def _notify(self) -> None:
        callback = self.on_state_change
        if callback is not None:
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

    def shutdown(self, stop_running: bool) -> None:
        """Вызывается при выходе из приложения."""
        if stop_running:
            self.stop(quiet=True)
            return
        # Служба переживает выход, а дочерний процесс — нет.
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            logs.info("Приложение закрыто, останавливаю winws.exe")
            self.stop(quiet=True)


engine = Engine()
