"""Общие действия для WebSocket-прокси Telegram: их вызывают и главная,
и вкладка «Telegram», поэтому логика живёт в одном месте."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from app.core import tgws
from app.ui.context import AppContext
from app.ui.widgets import Worker


def toggle(parent: QObject, context: AppContext, value: bool,
           on_done: Callable[[bool], None] | None = None) -> Worker:
    """Включить или выключить прокси в фоне. Возвращает рабочего — держите ссылку."""
    engine = tgws.tgws_engine
    tgws.set_desired_enabled(value)

    def job() -> bool:
        if value:
            engine.start()
        else:
            engine.stop()
        return value

    def finished(result) -> None:
        context.refresh_tgws(force=True)
        context.ok("Telegram через WebSocket " + ("включён" if result else "выключен"))
        if on_done:
            on_done(True)

    def failed(message: str) -> None:
        if value:
            tgws.set_desired_enabled(False)
        context.refresh_tgws(force=True)
        context.error(str(message))
        if on_done:
            on_done(False)

    worker = Worker(parent)
    worker.finished.connect(finished)
    worker.failed.connect(failed)
    worker.run(job)
    return worker


def open_in_telegram(context: AppContext) -> None:
    """Ссылка tg://proxy — Telegram Desktop сам предложит включить прокси."""
    if not tgws.tgws_engine.is_running():
        context.warn("Сначала включите прокси, иначе Telegram не сможет подключиться.")
        return
    QDesktopServices.openUrl(QUrl(tgws.tgws_engine.link()))
    context.ok("Telegram должен спросить, включить ли прокси. Если не открылся — "
               "скопируйте ссылку и отправьте себе в «Избранное».")


def copy_link(context: AppContext) -> None:
    QApplication.clipboard().setText(tgws.tgws_engine.link())
    context.ok("Ссылка скопирована. Отправьте её себе в «Избранное» в Telegram и нажмите на неё.")
