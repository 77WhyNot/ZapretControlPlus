"""Главная: состояние, схема маршрутов и четыре главных тумблера.

Здесь только то, чем пользуются каждый день: включить или выключить обход,
VPN, прокси Telegram и Smart DNS — и сразу выбрать стратегию, сервер или
сервис, не уходя с экрана. Всё редкое живёт на своих вкладках.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.core import autotest, winapi
from app.core.config import config
from app.core.engine import engine
from app.core.vpn import config as vpn_config
from app.ui import tgws_actions, vpn_actions
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.rails import RailsBoard
from app.ui.widgets import (
    clear_layout,
    Button,
    Card,
    IconLabel,
    Spinner,
    Switch,
    Worker,
    faint_label,
)

# Сервис Smart DNS, который включается с главной, если человек ничего не выбирал.
DNS_DEFAULT_PRESET = "xbox"


def fade_in(widget: QWidget, duration: int = 220, delay: int = 0,
            keep: list | None = None) -> None:
    """Мягко проявить виджет. Эффект снимаем сразу после: он замедляет отрисовку."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    if keep is not None:
        keep.append(animation)
    QTimer.singleShot(delay, animation.start)


class QuickTile(QFrame):
    """Плитка главной функции: значок, название, состояние, выбор и тумблер."""

    toggled = Signal(bool)

    def __init__(self, context: AppContext, icon_name: str, title: str,
                 lane_token: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.lane_token = lane_token
        self._on = False
        self.setObjectName("Tile")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 14)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.badge = QLabel(self)
        self.badge.setFixedSize(40, 40)
        badge_layout = QHBoxLayout(self.badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        self.icon = IconLabel(icon_name, context.color("text_faint"), 20, self.badge)
        badge_layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.badge)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel(title, self)
        self.title.setStyleSheet("font-weight: 650; font-size: 14.5px; background: transparent;")
        texts.addWidget(self.title)
        self.state = QLabel("", self)
        self.state.setObjectName("Faint")
        texts.addWidget(self.state)
        top.addLayout(texts, 1)

        self.spinner = Spinner(16, context.color(lane_token))
        top.addWidget(self.spinner)
        self.switch = Switch(False)
        self.switch.toggled.connect(self.toggled.emit)
        top.addWidget(self.switch)
        layout.addLayout(top)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        layout.addLayout(self.controls)

        # Подсветка значка плавно перетекает между «выключено» и «включено».
        self._tint = QVariantAnimation(self)
        self._tint.setDuration(260)
        self._tint.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tint.valueChanged.connect(self._paint_badge)
        self._badge_color = QColor(context.color("hover", "#EEF1F5"))
        self.apply_theme()

    # --- состояние ---------------------------------------------------------

    def set_on(self, value: bool, animate: bool = True) -> None:
        changed = value != self._on
        self._on = value
        self.switch.blockSignals(True)
        self.switch.setChecked(value, animate=animate and changed)
        self.switch.blockSignals(False)
        if changed:
            self._retint(animate)
            self._restyle()

    def set_state(self, text: str) -> None:
        if self.state.text() == text:
            return
        self.state.setText(text)

    def set_busy(self, busy: bool) -> None:
        self.switch.setEnabled(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    # --- оформление --------------------------------------------------------

    def _target_color(self) -> QColor:
        token = f"{self.lane_token}_soft" if self._on else "hover"
        return QColor(self.context.color(token, "#EEF1F5"))

    def _retint(self, animate: bool) -> None:
        target = self._target_color()
        self.icon.set_color(self.context.color(
            self.lane_token if self._on else "text_faint"
        ))
        if not animate:
            self._tint.stop()
            self._paint_badge(target)
            return
        self._tint.stop()
        self._tint.setStartValue(self._badge_color)
        self._tint.setEndValue(target)
        self._tint.start()

    def _paint_badge(self, color) -> None:
        self._badge_color = QColor(color)
        self.badge.setStyleSheet(
            f"background: {self._badge_color.name()}; border-radius: 12px;"
        )

    def _restyle(self) -> None:
        lane = self.context.color(self.lane_token)
        border = lane if self._on else self.context.color("border")
        self.setStyleSheet(
            f"QFrame#Tile {{ background: {self.context.color('surface')}; "
            f"border: 1px solid {border}; border-radius: 14px; }}"
            f"QFrame#Tile:hover {{ border-color: {lane}; }}"
        )

    def apply_theme(self) -> None:
        color = self.context.color(self.lane_token)
        self.spinner.set_color(color)
        self.switch.set_colors(
            color, self.context.color("border_strong"), self.context.color("surface")
        )
        self._retint(animate=False)
        self._restyle()


class HomePage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Главная",
            "Включайте и выключайте одним щелчком. Стратегию, сервер и сервис "
            "можно выбрать прямо на плитке.",
            parent,
        )
        self._busy_zapret = False
        self._busy_dns = False
        self._busy_tg = False
        self._busy_vpn = False
        self._workers: dict[str, Worker | None] = {}
        self._check_worker: Worker | None = None
        self._pending_updates: dict[str, object] = {}
        self._animations: list = []
        self._shown_once = False

        self._build_banners()
        self._build_hero()
        self._build_tiles()
        self._build_check()

        context.status_changed.connect(lambda _: self._refresh())
        context.tunnels_changed.connect(lambda _: self._refresh())
        context.tgws_changed.connect(lambda _: self._refresh())
        context.vpn_status_changed.connect(lambda _: self._refresh())
        context.servers_changed.connect(self._reload_servers)
        context.strategies_changed.connect(self._reload_strategies)
        context.update_available.connect(self._update_available)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_uptime)
        self._tick.start(1000)

        self._reload_strategies()
        self._reload_servers()
        self._reload_dns()
        self.apply_theme()

    # --- плашки -----------------------------------------------------------

    def _build_banners(self) -> None:
        self.banner_admin = Banner(
            self.context, "warning",
            "Программа запущена без прав администратора — обход не сможет "
            "работать. Перезапустите её от имени администратора.",
            kind="error", compact=True,
        )
        self.body.addWidget(self.banner_admin)
        self.banner_admin.setVisible(not winapi.is_admin())

        # Чужой VPN: небольшая плашка, которая живёт, пока жив туннель.
        # Проверка идёт постоянно — окно опрашивает адаптеры каждые пару секунд.
        self.banner_tunnel = Banner(
            self.context, "globe", "", kind="warn",
            action_text="Выключить обход", compact=True,
        )
        self.banner_tunnel.action.clicked.connect(lambda: self.stop_bypass())
        self.body.addWidget(self.banner_tunnel)
        self.banner_tunnel.setVisible(False)

        self.banner_update = Banner(
            self.context, "cloud_download", "", kind="info",
            action_text="Установить", compact=True,
        )
        self.banner_update.action.clicked.connect(self._install_pending)
        self.body.addWidget(self.banner_update)
        self.banner_update.setVisible(False)

    # --- шапка ------------------------------------------------------------

    def _build_hero(self) -> None:
        card = Card(padding=22, spacing=12)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.state_dot = QLabel("●")
        self.state_dot.setStyleSheet("font-size: 15px; background: transparent;")
        top.addWidget(self.state_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        # Шрифт задаём стилем, а не setFont: общая тема перебивает setFont.
        self.state_title = QLabel("Всё идёт напрямую")
        self.state_title.setObjectName("HeroTitle")
        top.addWidget(self.state_title)
        top.addStretch(1)
        self.uptime = faint_label("", wrap=False)
        top.addWidget(self.uptime)
        self.spinner = Spinner(18, self.context.color("accent"))
        top.addWidget(self.spinner)
        card.add_layout(top)

        self.state_detail = faint_label("")
        card.add(self.state_detail)

        self.rails = RailsBoard(self.context)
        self.rails.lane_clicked.connect(self._lane_clicked)
        card.add(self.rails)

        self.body.addWidget(card)

    # --- плитки -------------------------------------------------------------

    def _build_tiles(self) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # Обход: стратегия выбирается тут же, из выпадающего списка.
        self.tile_zapret = QuickTile(self.context, "shield_check", "Обход DPI",
                                     "lane_zapret")
        self.tile_zapret.toggled.connect(self._toggle_zapret)
        self.strategy_box = QComboBox()
        self.strategy_box.setToolTip("Стратегия обхода")
        self.strategy_box.activated.connect(self._strategy_picked)
        self.tile_zapret.controls.addWidget(self.strategy_box, 1)
        more_zapret = Button("Подробнее", variant="ghost")
        more_zapret.clicked.connect(lambda: self.context.navigate.emit("strategies"))
        self.tile_zapret.controls.addWidget(more_zapret)
        grid.addWidget(self.tile_zapret, 0, 0)

        # VPN: сервер из подписки — тоже прямо здесь.
        self.tile_vpn = QuickTile(self.context, "layers", "VPN", "lane_vpn")
        self.tile_vpn.toggled.connect(self._toggle_vpn)
        self.server_box = QComboBox()
        self.server_box.setToolTip("Сервер VPN")
        self.server_box.activated.connect(self._server_picked)
        self.tile_vpn.controls.addWidget(self.server_box, 1)
        self.btn_vpn_more = Button("Подробнее", variant="ghost")
        self.btn_vpn_more.clicked.connect(lambda: self.context.navigate.emit("vpnconnect"))
        self.tile_vpn.controls.addWidget(self.btn_vpn_more)
        grid.addWidget(self.tile_vpn, 0, 1)

        # Telegram: включить и открыть.
        self.tile_tg = QuickTile(self.context, "telegram", "Telegram", "lane_tg")
        self.tile_tg.toggled.connect(self._toggle_tg)
        self.btn_tg_open = Button("Открыть в Telegram", variant="soft")
        self.btn_tg_open.clicked.connect(lambda: tgws_actions.open_in_telegram(self.context))
        self.tile_tg.controls.addWidget(self.btn_tg_open, 1)
        more_tg = Button("Подробнее", variant="ghost")
        more_tg.clicked.connect(lambda: self.context.navigate.emit("telegram"))
        self.tile_tg.controls.addWidget(more_tg)
        grid.addWidget(self.tile_tg, 1, 0)

        # Smart DNS: сервис выбирается из списка.
        self.tile_dns = QuickTile(self.context, "globe", "Smart DNS", "lane_dns")
        self.tile_dns.toggled.connect(self._toggle_dns)
        self.dns_box = QComboBox()
        self.dns_box.setToolTip("Сервис Smart DNS")
        self.dns_box.activated.connect(self._dns_picked)
        self.tile_dns.controls.addWidget(self.dns_box, 1)
        more_dns = Button("Подробнее", variant="ghost")
        more_dns.clicked.connect(lambda: self.context.navigate.emit("dns"))
        self.tile_dns.controls.addWidget(more_dns)
        grid.addWidget(self.tile_dns, 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        self._tiles = (self.tile_zapret, self.tile_vpn, self.tile_tg, self.tile_dns)

    # --- проверка ------------------------------------------------------------

    def _build_check(self) -> None:
        card = Card(padding=18, spacing=12)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_check = Button("Проверить доступность", variant="primary")
        self.btn_check.clicked.connect(self._run_check)
        actions.addWidget(self.btn_check)
        self.btn_speed = Button("Замерить скорость", variant="soft")
        self.btn_speed.clicked.connect(self._open_speed)
        actions.addWidget(self.btn_speed)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        actions.addWidget(self.check_spinner)
        actions.addStretch(1)
        self.btn_diag = Button("Диагностика", variant="ghost")
        self.btn_diag.clicked.connect(lambda: self.context.navigate.emit("diagnostics"))
        actions.addWidget(self.btn_diag)
        card.add_layout(actions)

        self.check_host = QWidget()
        self.check_grid = QGridLayout(self.check_host)
        self.check_grid.setContentsMargins(0, 0, 0, 0)
        self.check_grid.setHorizontalSpacing(22)
        self.check_grid.setVerticalSpacing(7)
        card.add(self.check_host)
        self.check_host.setVisible(False)

        self.body.addWidget(card)

    # --- списки на плитках ---------------------------------------------------

    def _reload_strategies(self) -> None:
        items = self.context.load_strategies()
        current = self.context.current_strategy()
        self.strategy_box.blockSignals(True)
        self.strategy_box.clear()
        for item in items:
            self.strategy_box.addItem(item.title, item.id)
        if current is not None:
            index = self.strategy_box.findData(current.id)
            if index >= 0:
                self.strategy_box.setCurrentIndex(index)
        self.strategy_box.setEnabled(bool(items))
        self.strategy_box.blockSignals(False)

    def _reload_servers(self) -> None:
        servers = self.context.servers()
        self.server_box.blockSignals(True)
        self.server_box.clear()
        for server in servers:
            self.server_box.addItem(server.name, server.name)
        if servers:
            index = self.server_box.findData(self.context.selected_server())
            if index >= 0:
                self.server_box.setCurrentIndex(index)
        else:
            self.server_box.addItem("Подписка не добавлена", "")
        self.server_box.setEnabled(bool(servers))
        self.server_box.blockSignals(False)
        self.btn_vpn_more.setText("Подробнее" if servers else "Добавить подписку")
        self._refresh()

    def _reload_dns(self) -> None:
        from app.core import dnsctl

        wanted = str(config.get("home_dns_preset", DNS_DEFAULT_PRESET))
        current = dnsctl.current_preset()
        chosen = current if current != "auto" else wanted
        self.dns_box.blockSignals(True)
        self.dns_box.clear()
        for preset in dnsctl.PRESETS:
            if preset.key != "auto":
                self.dns_box.addItem(preset.title, preset.key)
        index = self.dns_box.findData(chosen)
        if index >= 0:
            self.dns_box.setCurrentIndex(index)
        self.dns_box.blockSignals(False)

    # --- состояние -----------------------------------------------------------

    def on_activate(self) -> None:
        self.context.refresh_status(force=True)
        self.context.refresh_tunnels(force=True)
        self.context.refresh_tgws(force=True)
        self.context.refresh_vpn_status(force=True)
        self._reload_strategies()
        self._reload_dns()
        if not self._shown_once:
            # Первое появление: плитки проявляются по очереди.
            self._shown_once = True
            for index, tile in enumerate(self._tiles):
                fade_in(tile, 260, delay=60 + index * 70, keep=self._animations)

    def _lane_clicked(self, key: str) -> None:
        targets = {"zapret": "strategies", "dns": "dns", "tg": "telegram",
                   "vpn": "vpnconnect"}
        page = targets.get(key)
        if page:
            self.context.navigate.emit(page)

    def _dns_state(self) -> tuple[bool, str]:
        from app.core import dnsctl

        preset = dnsctl.current_preset()
        title = next((item.title for item in dnsctl.PRESETS if item.key == preset), "")
        return preset != "auto", title

    def _refresh(self) -> None:
        status = self.context.status
        tunnels = self.context.tunnels
        tg = self.context.tgws_status
        vpn = self.context.vpn_status
        dns_on, dns_title = self._dns_state()

        self.tile_zapret.set_on(status.running)
        self.tile_vpn.set_on(vpn.running)
        self.tile_tg.set_on(tg.running)
        self.tile_dns.set_on(dns_on)

        strategy = self.context.current_strategy()
        self.tile_zapret.set_state(
            f"работает · {status.mode_label}" if status.running
            else "выключен · сайты и Discord напрямую"
        )
        transport_label = ("туннель" if vpn_actions.transport() == vpn_config.TRANSPORT_TUN
                           else "прокси")
        if vpn.running:
            self.tile_vpn.set_state(
                f"работает · {transport_label} · "
                f"{vpn_config.MODE_LABELS.get(vpn.mode, '').lower()}"
                if vpn.transport == vpn_config.TRANSPORT_TUN
                else f"работает · {transport_label}"
            )
        elif self.context.servers():
            self.tile_vpn.set_state(f"выключен · {transport_label}")
        else:
            self.tile_vpn.set_state("выключен · нужна подписка")
        self.tile_tg.set_state(
            f"работает · порт {tg.port}" + (f" · соединений {tg.active}" if tg.active else "")
            if tg.running else "выключен · Telegram напрямую"
        )
        self.btn_tg_open.setEnabled(tg.running)
        self.tile_dns.set_state(
            f"работает · {dns_title}" if dns_on else "выключен · адреса от провайдера"
        )

        self.rails.update_state(
            zapret_on=status.running,
            zapret_targets=["YouTube", "Discord"] if status.running else [],
            dns_on=dns_on,
            dns_note=dns_title,
            tunnels=tunnels,
            direct_note="остальное",
            tg_on=tg.running,
            tg_note="WebSocket",
            vpn_on=vpn.running,
            vpn_chips=[vpn.server or "VPN"] if vpn.running else [],
        )

        active = [name for name, on in (
            ("обход", status.running), ("VPN", vpn.running),
            ("Telegram", tg.running), ("Smart DNS", dns_on),
        ) if on]
        if len(active) >= 2:
            title = "Работают " + ", ".join(active[:-1]) + " и " + active[-1]
            detail = "Всё включённое действует одновременно и друг другу не мешает."
        elif active:
            title = {"обход": "Работает обход", "VPN": "Работает VPN",
                     "Telegram": "Работает прокси Telegram",
                     "Smart DNS": "Работает Smart DNS"}[active[0]]
            detail = {
                "обход": "Discord, YouTube и сайты из списка открываются в обход "
                         f"блокировки. Стратегия — «{strategy.title if strategy else '—'}».",
                "VPN": ("Выбранные программы идут через туннель, остальные — напрямую."
                        if vpn.transport == vpn_config.TRANSPORT_TUN else
                        "Браузеры и всё, что уважает системный прокси, идут через VPN."),
                "Telegram": "Telegram идёт через WebSocket. Сайты и Discord — "
                            "напрямую: включите обход, если они не открываются.",
                "Smart DNS": "Блокировку по стране обходим, а DPI провайдера — нет. "
                             "Включите обход, если сайты не открываются.",
            }[active[0]]
        else:
            title = "Всё идёт напрямую"
            detail = "Ничего не включено. Начните с обхода — это один тумблер."
        self._set_state(title, detail, bool(active))
        self._sync_tunnel_banner(tunnels, status.running)
        self._refresh_uptime()

    def _set_state(self, title: str, detail: str, active: bool) -> None:
        """Смена заголовка с коротким проявлением, а не рывком."""
        self.state_dot.setStyleSheet(
            f"font-size: 15px; background: transparent; color: "
            f"{self.context.color('success' if active else 'text_faint')};"
        )
        self.state_detail.setText(detail)
        if self.state_title.text() == title:
            return
        self.state_title.setText(title)
        fade_in(self.state_title, 280, keep=self._animations)
        del self._animations[:-12]

    def _sync_tunnel_banner(self, tunnels: list[str], zapret_on: bool) -> None:
        if not tunnels or not config.get("warn_about_vpn", True):
            self.banner_tunnel.setVisible(False)
            return
        names = ", ".join(tunnels)
        self.banner_tunnel.set_text(
            f"Обнаружен другой VPN — {names}. Он может мешать обходу."
            if zapret_on else
            f"Обнаружен другой VPN — {names}. Программа его не трогает."
        )
        self.banner_tunnel.action.setVisible(zapret_on)
        if not self.banner_tunnel.isVisible():
            self.banner_tunnel.setVisible(True)
            fade_in(self.banner_tunnel, 220, keep=self._animations)

    def _update_available(self, kind: str, info) -> None:
        if info is None:
            self._pending_updates.pop(kind, None)
        else:
            self._pending_updates[kind] = info
        core = self._pending_updates.get("core")
        app_info = self._pending_updates.get("app")
        if app_info is not None:
            self.banner_update.set_text(
                f"Вышла новая версия программы {app_info.latest} — обновится сама."
            )
        elif core is not None:
            self.banner_update.set_text(
                f"Вышло обновление ядра zapret {core.latest} — свежие стратегии и списки."
            )
        self.banner_update.setVisible(bool(core or app_info))

    def _install_pending(self) -> None:
        kind = "app" if "app" in self._pending_updates else "core"
        self.context.navigate.emit("updates")
        self.context.install_update.emit(kind)

    def _refresh_uptime(self) -> None:
        seconds = engine.uptime_seconds()
        if not seconds:
            self.uptime.setText("")
            return
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        stamp = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        self.uptime.setText(f"обход работает {stamp}")

    # --- обход ---------------------------------------------------------------

    def toggle_bypass(self) -> None:
        """Тумблер из трея: включить, если выключено, и наоборот."""
        self._toggle_zapret(not self.context.status.running)

    def start_bypass(self) -> None:
        if not self.context.status.running:
            self._toggle_zapret(True)

    def stop_bypass(self) -> None:
        if self.context.status.running:
            self._toggle_zapret(False)

    def _toggle_zapret(self, value: bool) -> None:
        if self._busy_zapret:
            return
        if value:
            strategy = self.context.current_strategy()
            if strategy is None:
                self.context.error("Стратегия не найдена — проверьте вкладку «Запрет».")
                self._refresh()
                return
            self._run_zapret(engine.start, strategy,
                             f"Обход включён — «{strategy.title}»")
        else:
            self._run_zapret(engine.stop, None, "Обход выключен")

    def _strategy_picked(self, index: int) -> None:
        strategy_id = str(self.strategy_box.itemData(index) or "")
        if not strategy_id:
            return
        config.set("last_strategy", strategy_id)
        strategy = self.context.current_strategy()
        if strategy is None:
            return
        if self.context.status.running:
            self._run_zapret(engine.restart, strategy,
                             f"Стратегия сменена — «{strategy.title}»")
        else:
            self.context.ok(f"Стратегия «{strategy.title}» — включите обход тумблером.")
        self._refresh()

    def _run_zapret(self, action, strategy, message: str) -> None:
        if self._busy_zapret:
            return
        self._busy_zapret = True
        self.tile_zapret.set_busy(True)
        self.strategy_box.setEnabled(False)

        def done(error: str = "") -> None:
            self._busy_zapret = False
            self.tile_zapret.set_busy(False)
            self.strategy_box.setEnabled(True)
            self.context.refresh_status(force=True)
            self._refresh()
            if error:
                self.context.error(error)
            else:
                self.context.ok(message)

        worker = Worker(self)
        worker.finished.connect(lambda _: done())
        worker.failed.connect(done)
        if strategy is None:
            worker.run(action)
        else:
            worker.run(action, strategy, str(config.get("run_mode")))
        self._workers["zapret"] = worker

    # --- VPN -----------------------------------------------------------------

    def _toggle_vpn(self, value: bool) -> None:
        if self._busy_vpn:
            return
        self._busy_vpn = True
        self.tile_vpn.set_busy(True)

        def done(_ok: bool) -> None:
            self._busy_vpn = False
            self.tile_vpn.set_busy(False)
            self._refresh()

        if value:
            worker = vpn_actions.start(
                self, self.context, done,
                on_progress=lambda text: self.state_detail.setText(text),
            )
            if worker is None:
                done(False)
        else:
            worker = vpn_actions.stop(self, self.context, done)
        self._workers["vpn"] = worker

    def _server_picked(self, index: int) -> None:
        from app.core.vpn.engine import VpnError, vpn_engine

        name = str(self.server_box.itemData(index) or "")
        if not name:
            return
        config.set("vpn_selected_server", name)
        if not vpn_engine.status().running:
            self.context.ok(f"Сервер «{name}» — включите VPN тумблером.")
            return

        def switch() -> str:
            try:
                vpn_engine.switch_server(name)
            except VpnError as exc:
                raise RuntimeError(str(exc)) from exc
            return name

        worker = Worker(self)
        worker.finished.connect(lambda _: (
            self.context.ok(f"Активный сервер: «{name}»"),
            self.context.refresh_vpn_status(force=True),
        ))
        worker.failed.connect(self.context.error)
        worker.run(switch)
        self._workers["server"] = worker

    # --- Telegram --------------------------------------------------------------

    def _toggle_tg(self, value: bool) -> None:
        if self._busy_tg:
            return
        self._busy_tg = True
        self.tile_tg.set_busy(True)

        def done(ok: bool) -> None:
            self._busy_tg = False
            self.tile_tg.set_busy(False)
            self._refresh()
            if ok and value:
                # Человеку нужен следующий шаг, а не просто «включено».
                QTimer.singleShot(400, lambda: self.context.warn(
                    "Теперь нажмите «Открыть в Telegram», чтобы он подключился через прокси."
                ))

        self._workers["tg"] = tgws_actions.toggle(self, self.context, value, done)

    # --- Smart DNS ---------------------------------------------------------------

    def _toggle_dns(self, value: bool) -> None:
        key = str(self.dns_box.currentData() or DNS_DEFAULT_PRESET) if value else "auto"
        self._apply_dns(key)

    def _dns_picked(self, index: int) -> None:
        key = str(self.dns_box.itemData(index) or "")
        if not key:
            return
        config.set("home_dns_preset", key)
        on, _title = self._dns_state()
        if on:
            self._apply_dns(key)

    def _apply_dns(self, key: str) -> None:
        from app.core import dnsctl

        if self._busy_dns:
            return
        self._busy_dns = True
        self.tile_dns.set_busy(True)

        def done(message: str, error: bool = False) -> None:
            self._busy_dns = False
            self.tile_dns.set_busy(False)
            self._refresh()
            (self.context.error if error else self.context.ok)(message)

        worker = Worker(self)
        worker.finished.connect(lambda message: done(str(message)))
        worker.failed.connect(lambda message: done(str(message), error=True))
        worker.run(dnsctl.apply_preset, key)
        self._workers["dns"] = worker

    # --- проверка и скорость -----------------------------------------------------

    def _open_speed(self) -> None:
        """Кнопка ведёт на страницу замера и сразу его запускает."""
        self.context.navigate.emit("speed")
        window = self.window()
        ensure = getattr(window, "ensure_page", None)
        page = ensure("speed") if callable(ensure) else None
        starter = getattr(page, "start_measure", None)
        if callable(starter):
            QTimer.singleShot(260, starter)

    def _run_check(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        from app.core.vpn.engine import vpn_engine

        clear_layout(self.check_grid)
        self.btn_check.setEnabled(False)
        self.check_spinner.start()
        # В режиме «Прокси» VPN доступен только через локальный прокси —
        # проверяем через него, иначе тест пойдёт мимо VPN.
        worker = Worker(self)
        worker.finished.connect(self._check_ready)
        worker.failed.connect(self._check_failed)
        worker.run(autotest.quick_check, vpn_engine.proxy_url())
        self._check_worker = worker

    def _check_failed(self, message: str) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(message)

    def _check_ready(self, results) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        clear_layout(self.check_grid)
        self.check_host.setVisible(True)

        columns = 3
        for index, item in enumerate(results):
            row = QWidget(self.check_host)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            token = "success" if item.ok else "danger"
            line.addWidget(IconLabel(
                "check" if item.ok else "cross", self.context.color(token), 15, row
            ))
            line.addWidget(QLabel(item.target.key or item.target.label, row))
            line.addStretch(1)
            line.addWidget(faint_label(
                f"{item.ms:.0f} мс" if item.ok else "нет ответа", wrap=False
            ))
            self.check_grid.addWidget(row, index // columns, index % columns)
            fade_in(row, 220, delay=index * 40, keep=self._animations)

        failed = [item for item in results if not item.ok]
        if not failed:
            self.context.ok("Все адреса открываются")
        else:
            self.context.warn(f"Не открылось адресов: {len(failed)}")

    # --- тема ----------------------------------------------------------------------

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
        self.check_spinner.set_color(self.context.color("accent"))
        for tile in self._tiles:
            tile.apply_theme()
        self.rails.apply_theme()
        self._refresh()
