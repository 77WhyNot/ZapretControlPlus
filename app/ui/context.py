"""Общий контекст: тема, состояние движка и уведомления для всех страниц."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core import strategies
from app.core.config import config
from app.core.engine import Status, engine
from app.ui import theme


class AppContext(QObject):
    """Единая шина между главным окном и страницами."""

    theme_changed = Signal()
    status_changed = Signal(object)
    strategies_changed = Signal()
    tunnels_changed = Signal(object)   # список чужих VPN-туннелей
    update_available = Signal(str, object)  # 'core' | 'app', UpdateInfo или None
    install_update = Signal(str)       # просьба поставить: 'core' | 'app'
    notify = Signal(str, str)          # текст, вид (ok/warn/error)
    navigate = Signal(str)             # ключ страницы

    def __init__(self) -> None:
        super().__init__()
        self._tokens = theme.build_tokens(
            str(config.get("theme")), str(config.get("accent"))
        )
        self._status = engine.status()
        self._tunnels: list[str] = []

    # --- тема ------------------------------------------------------------

    @property
    def tokens(self) -> dict[str, str]:
        return self._tokens

    def color(self, key: str, fallback: str = "#000000") -> str:
        return self._tokens.get(key, fallback)

    def rebuild_theme(self) -> str:
        """Пересобрать палитру и вернуть готовый QSS."""
        self._tokens = theme.build_tokens(
            str(config.get("theme")), str(config.get("accent"))
        )
        qss = theme.build_qss(self._tokens)
        self.theme_changed.emit()
        return qss

    @property
    def is_dark(self) -> bool:
        return self._tokens.get("is_dark") == "1"

    # --- состояние обхода ------------------------------------------------

    @property
    def status(self) -> Status:
        return self._status

    def refresh_status(self, force: bool = False) -> Status:
        status = engine.status()
        if force or status != self._status:
            self._status = status
            self.status_changed.emit(status)
        return status

    # --- чужие туннели ---------------------------------------------------

    @property
    def tunnels(self) -> list[str]:
        """Названия живых VPN-туннелей: Happ, WireGuard и прочие."""
        return list(self._tunnels)

    def refresh_tunnels(self, force: bool = False) -> list[str]:
        from app.core import netadapters

        found = netadapters.tunnel_names()
        if force or found != self._tunnels:
            self._tunnels = found
            self.tunnels_changed.emit(list(found))
        return list(found)

    # --- стратегии -------------------------------------------------------

    def current_game_filter(self) -> str:
        return strategies.read_game_filter()

    def load_strategies(self) -> list[strategies.Strategy]:
        return strategies.load_strategies(self.current_game_filter())

    def current_strategy(self) -> strategies.Strategy | None:
        wanted = self._status.strategy_id or str(config.get("last_strategy"))
        return strategies.find_strategy(wanted, self.current_game_filter())

    # --- уведомления -----------------------------------------------------

    def ok(self, text: str) -> None:
        self.notify.emit(text, "ok")

    def warn(self, text: str) -> None:
        self.notify.emit(text, "warn")

    def error(self, text: str) -> None:
        self.notify.emit(text, "error")
