"""Общие действия VPN: их зовут и главная, и вкладка «VPN», и «Программы»."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer

from app.core.config import config
from app.core.vpn import config as vpn_config
from app.core.vpn import integration
from app.core.vpn.engine import vpn_engine
from app.ui.context import AppContext
from app.ui.widgets import Worker


def transport() -> str:
    value = str(config.get("vpn_transport", vpn_config.TRANSPORT_TUN))
    return value if value in vpn_config.TRANSPORT_LABELS else vpn_config.TRANSPORT_TUN


def set_transport(value: str) -> None:
    if value in vpn_config.TRANSPORT_LABELS:
        config.set("vpn_transport", value)


def desired_enabled() -> bool:
    return bool(config.get("vpn_autostart", False))


def _settings(context: AppContext) -> dict:
    return {
        "servers": context.servers(),
        "selected": context.selected_server(),
        "mode": str(config.get("vpn_mode", vpn_config.MODE_SELECTED)),
        "vpn_apps": list(config.get("vpn_apps", []) or []),
        "direct_apps": list(config.get("vpn_direct_apps", []) or []),
        "stack": str(config.get("vpn_stack", vpn_config.STACK_DEFAULT)),
        "transport": transport(),
    }


def start(parent: QObject, context: AppContext,
          on_done: Callable[[bool], None] | None = None,
          on_progress: Callable[[str], None] | None = None) -> Worker | None:
    """Поднять VPN в фоне. Возвращает рабочего — держите ссылку."""
    if vpn_engine.is_starting():
        # Второй запуск поверх идущего только перезапустил бы туннель и
        # оборвал соединения. Тот, что уже идёт, сообщит о себе сам.
        context.warn("VPN уже подключается — подождите несколько секунд.")
        if on_done:
            on_done(False)
        return None
    settings = _settings(context)
    if not settings["servers"]:
        context.error("Сначала добавьте подписку на вкладке «VPN».")
        context.navigate.emit("vpnconnect")
        if on_done:
            on_done(False)
        return None

    auto_exclude = bool(config.get("vpn_auto_exclude", True))
    worker = Worker(parent)

    def job() -> bool:
        # Иначе zapret порежет трафик до самого VPN-сервера.
        if auto_exclude:
            integration.sync_excludes(settings["servers"])
        vpn_engine.on_progress = lambda text: worker.progress.emit(text, 0)
        try:
            vpn_engine.start(
                settings["servers"], settings["selected"], settings["mode"],
                settings["vpn_apps"], settings["direct_apps"], settings["stack"],
                transport=settings["transport"],
            )
        finally:
            vpn_engine.on_progress = None
        return True

    def finished(_result) -> None:
        config.set("vpn_autostart", True)
        context.refresh_vpn_status(force=True)
        if not vpn_engine.status().running:
            # Запуск уступил более свежему запросу — сообщит уже тот.
            if on_done:
                on_done(False)
            return
        label = "туннель" if settings["transport"] == vpn_config.TRANSPORT_TUN else "прокси"
        context.ok(f"VPN включён ({label}) — сервер «{settings['selected']}»")
        if on_done:
            on_done(True)

    def failed(message: str) -> None:
        context.refresh_vpn_status(force=True)
        context.error(str(message))
        if on_done:
            on_done(False)

    if on_progress:
        worker.progress.connect(lambda text, _v: on_progress(text))
    worker.finished.connect(finished)
    worker.failed.connect(failed)
    worker.run(job)
    return worker


def stop(parent: QObject, context: AppContext,
         on_done: Callable[[bool], None] | None = None) -> Worker:
    config.set("vpn_autostart", False)
    worker = Worker(parent)

    def finished(_result) -> None:
        context.refresh_vpn_status(force=True)
        context.ok("VPN выключен")
        if on_done:
            on_done(True)

    def failed(message: str) -> None:
        context.refresh_vpn_status(force=True)
        context.error(str(message))
        if on_done:
            on_done(False)

    worker.finished.connect(finished)
    worker.failed.connect(failed)
    worker.run(vpn_engine.stop)
    return worker


# Перезапуск один на всю программу: человек отмечает программы пачкой, и
# каждый щелчок не должен поднимать свой туннель наперегонки с соседним.
_restart_worker: Worker | None = None
_restart_pending: tuple | None = None


def restart_busy() -> bool:
    return _restart_worker is not None and _restart_worker.busy()


def restart_if_running(parent: QObject, context: AppContext, reason: str,
                       on_done: Callable[[bool], None] | None = None) -> Worker | None:
    """Правила читаются движком только при запуске — перезапускаем сами."""
    global _restart_worker, _restart_pending

    if not vpn_engine.status().running:
        return None
    if restart_busy():
        # Уже перезапускаем. Правки, сделанные после чтения настроек, не
        # потеряются: запомним просьбу и повторим сразу после.
        _restart_pending = (parent, context, reason)
        return _restart_worker
    context.warn(f"{reason} — перезапускаю VPN…")
    worker = Worker(parent)

    def job() -> bool:
        # Настройки читаем в момент запуска: пока ждали очереди, человек мог
        # отметить ещё пару программ — поедут сразу все.
        fresh = _settings(context)
        vpn_engine.start(
            fresh["servers"], fresh["selected"], fresh["mode"],
            fresh["vpn_apps"], fresh["direct_apps"], fresh["stack"],
            transport=fresh["transport"],
        )
        return True

    def run_pending() -> None:
        """Пока перезапускались, правила могли поменяться ещё раз."""
        global _restart_pending

        request, _restart_pending = _restart_pending, None
        if request is not None:
            QTimer.singleShot(300, lambda: restart_if_running(*request))

    def finished(_result) -> None:
        context.refresh_vpn_status(force=True)
        if vpn_engine.status().running:
            context.ok("VPN перезапущен с новыми правилами")
        if on_done:
            on_done(True)
        run_pending()

    def failed(message: str) -> None:
        context.refresh_vpn_status(force=True)
        context.error(f"Не удалось перезапустить: {message}")
        if on_done:
            on_done(False)
        run_pending()

    worker.finished.connect(finished)
    worker.failed.connect(failed)
    worker.run(job)
    _restart_worker = worker
    return worker


def check_exit(parent: QObject, context: AppContext,
               on_done: Callable[[bool, str], None] | None = None) -> Worker | None:
    """Каким адресом нас видит мир через VPN — и отличается ли он от прямого."""
    if not vpn_engine.status().running:
        context.warn("VPN выключен — проверять нечего.")
        return None

    worker = Worker(parent)

    def job():
        return vpn_engine.exit_address(), vpn_engine.direct_address()

    def finished(payload) -> None:
        through, direct = payload
        where = through.get("country", "?")
        city = through.get("city") or ""
        place = f"{where}, {city}" if city else where
        if through.get("ip") == direct.get("ip"):
            message = (f"VPN не работает: мир видит тот же адрес {through['ip']} "
                       f"({place}), что и без него. Смените сервер.")
            context.error(message)
            if on_done:
                on_done(False, message)
        else:
            message = (f"VPN работает: снаружи вас видят как {through['ip']} — {place}. "
                       f"Без VPN было бы {direct.get('ip', '?')} ({direct.get('country', '?')}).")
            context.ok(message)
            if on_done:
                on_done(True, message)

    def failed(message: str) -> None:
        context.error(str(message))
        if on_done:
            on_done(False, str(message))

    worker.finished.connect(finished)
    worker.failed.connect(failed)
    worker.run(job)
    return worker
