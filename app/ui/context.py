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
    tgws_changed = Signal(object)      # состояние WebSocket-прокси Telegram
    vpn_status_changed = Signal(object)
    servers_changed = Signal()
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
        self._tgws = None
        self._tgws_key: tuple = ()
        self._vpn = None
        self._servers: list = []

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

    # --- Telegram через WebSocket -----------------------------------------

    @property
    def tgws_status(self):
        if self._tgws is None:
            from app.core.tgws import tgws_engine

            self._tgws = tgws_engine.status()
        return self._tgws

    def refresh_tgws(self, force: bool = False):
        from app.core.tgws import tgws_engine

        status = tgws_engine.status()
        key = (status.running, status.port, status.active, status.websocket,
               status.fallback, status.error)
        self._tgws = status
        if force or key != self._tgws_key:
            self._tgws_key = key
            self.tgws_changed.emit(status)
        return status

    # --- VPN -------------------------------------------------------------

    @property
    def vpn_status(self):
        if self._vpn is None:
            from app.core.vpn.engine import vpn_engine

            self._vpn = vpn_engine.status()
        return self._vpn

    def refresh_vpn_status(self, force: bool = False):
        from app.core.vpn.engine import vpn_engine

        status = vpn_engine.status()
        if force or status != self._vpn:
            self._vpn = status
            self.vpn_status_changed.emit(status)
        return status

    def servers(self) -> list:
        """Серверы подписки: держим в контексте, чтобы не читать кэш на каждой странице."""
        if not self._servers:
            from app.core.vpn import subscription

            self._servers, _ = subscription.load_cached()
        return list(self._servers)

    def set_servers(self, servers: list) -> None:
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
