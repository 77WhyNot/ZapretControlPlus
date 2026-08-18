"""Общий контекст: тема, состояние движка и уведомления для всех страниц."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core import strategies
from app.core.config import config
from app.core.engine import Status, engine
from app.core.vpn import subscription
from app.core.vpn.engine import VpnStatus, vpn_engine
from app.core.vpn.links import Server
from app.ui import theme


class AppContext(QObject):
    """Единая шина между главным окном и страницами."""

    theme_changed = Signal()
    status_changed = Signal(object)
    vpn_status_changed = Signal(object)
    strategies_changed = Signal()
    servers_changed = Signal()
    notify = Signal(str, str)          # текст, вид (ok/warn/error)
    navigate = Signal(str)             # ключ страницы

    def __init__(self) -> None:
        super().__init__()
        self._tokens = theme.build_tokens(
            str(config.get("theme")), str(config.get("accent"))
        )
        self._status = engine.status()
        self._vpn_status = vpn_engine.status()
        self._servers: list[Server] = []

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

    # --- VPN -------------------------------------------------------------

    @property
    def vpn_status(self) -> VpnStatus:
        return self._vpn_status

    def refresh_vpn_status(self, force: bool = False) -> VpnStatus:
        status = vpn_engine.status()
        if force or status != self._vpn_status:
            self._vpn_status = status
            self.vpn_status_changed.emit(status)
        return status

    def servers(self) -> list[Server]:
        """Серверы подписки: держим в контексте, чтобы не читать кэш на каждой странице."""
        if not self._servers:
            self._servers, _ = subscription.load_cached()
        return list(self._servers)

    def set_servers(self, servers: list[Server]) -> None:
        self._servers = list(servers)
        self.servers_changed.emit()

    def selected_server(self) -> str:
        chosen = str(config.get("vpn_selected_server", ""))
        names = [server.name for server in self.servers()]
        if chosen in names:
            return chosen
        return names[0] if names else ""

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
