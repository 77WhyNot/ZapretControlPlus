"""Точка входа Zapret Control."""

from __future__ import annotations

import ctypes
import sys
import traceback

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core import lists, logs, paths, updater, winapi
from app.core.config import config
from app.core.constants import APP_ID, APP_NAME, APP_VERSION

IPC_KEY = f"{APP_ID}-single-instance"


def _install_excepthook() -> None:
    def handler(kind, value, tb) -> None:
        text = "".join(traceback.format_exception(kind, value, tb))
        logs.error(f"Необработанная ошибка:\n{text}")
        try:
            QMessageBox.critical(
                None,
                f"{APP_NAME} — ошибка",
                f"Произошла непредвиденная ошибка:\n\n{value}\n\n"
                f"Подробности записаны в журнал:\n{paths.log_path()}",
            )
        except Exception:  # noqa: BLE001 — окна может ещё не быть
            pass

    sys.excepthook = handler


def _already_running() -> bool:
    """Вторая копия просто показывает окно уже запущенной."""
    socket = QLocalSocket()
    socket.connectToServer(IPC_KEY)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


def _start_ipc_server(window) -> QLocalServer:
    QLocalServer.removeServer(IPC_KEY)
    server = QLocalServer()
    server.listen(IPC_KEY)

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        connection.readyRead.connect(lambda: window.show_normal())
        connection.disconnected.connect(connection.deleteLater)

    server.newConnection.connect(on_connection)
    return server


def _ensure_admin() -> bool:
    """В собранной версии запрашиваем повышение прав, если его почему-то нет."""
    if winapi.is_admin():
        return True
    if not getattr(sys, "frozen", False):
        return True  # в dev-режиме просто предупредим баннером в окне
    if winapi.relaunch_as_admin():
        return False
    return True


def _selftest() -> int:
    """Проверка собранного бандла: --selftest строит окно и выходит."""
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    application = QApplication(sys.argv)

    from app.core import autotest, diagnostics, strategies
    from app.ui.window import PAGES, MainWindow

    print(f"стратегий: {len(strategies.load_strategies('off'))}")
    print(f"версия ядра: {strategies.local_core_version()}")
    print(f"целей: {len(autotest.load_targets())}")
    print(f"проверок: {len(diagnostics.ALL_CHECKS)}")

    window = MainWindow()
    for key, title, _ in PAGES:
        window.show_page(key)
        print(f"страница {title}: ок")
    for theme_key in ("dark", "midnight", "sand", "light"):
        config.set("theme", theme_key, save=False)
        window.apply_theme()
    print("темы: ок")
    window.close()
    application.processEvents()
    print("SELFTEST OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    if not _ensure_admin():
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)

    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName(APP_ID)
    application.setQuitOnLastWindowClosed(False)

    # Отдельный AppUserModelID — иначе Windows группирует окно с python.exe.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass

    # Русские надписи в стандартных диалогах Qt («Да», «Отмена» и т.п.).
    translator = QTranslator()
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_ru", translations):
        application.installTranslator(translator)
        application.setProperty("translator", translator)

    _install_excepthook()

    if _already_running():
        return 0

    logs.info(f"Запуск {APP_NAME} {APP_VERSION} (admin={winapi.is_admin()})")
    if not paths.core_is_valid():
        logs.warn(f"Ядро zapret не найдено в {paths.core_dir()}")
    lists.ensure_user_lists()
    updater.uninstall_leftovers()

    from app.ui.window import MainWindow

    window = MainWindow()
    server = _start_ipc_server(window)
    application.setProperty("ipc_server", server)

    start_hidden = "--tray" in sys.argv and config.get("start_minimized", False)
    if start_hidden:
        window.hide()
    else:
        window.show()

    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
