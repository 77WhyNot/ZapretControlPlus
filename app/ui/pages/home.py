"""Обзор: три переключателя, схема маршрутов и проверка доступности.

Всё редкое — фильтры, перезапуск — спрятано в раскрывающийся раздел
«Дополнительно», чтобы обычному человеку хватало одного экрана.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
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
from app.core.strategies import GAME_FILTER_LABELS
from app.core.vpn import config as vpn_config
from app.ui import tgws_actions, vpn_actions
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.rails import RailsBoard
from app.ui.widgets import (
    clear_layout,
    Button,
    Card,
    Collapsible,
    Divider,
    IconLabel,
    Spinner,
    StatItem,
    Switch,
    Worker,
    faint_label,
    section_label,
)

# Smart DNS на главной — это один переключатель: включить сервис для Xbox
# или вернуть как было. Остальные сервисы выбираются на своей вкладке.
DNS_DEFAULT_PRESET = "xbox"


class ToolCard(Card):
    """Карточка инструмента: заголовок, переключатель, пояснение, кнопка."""

    def __init__(self, context: AppContext, icon_name: str, title: str,
                 text: str, lane_token: str) -> None:
        super().__init__(padding=18, spacing=10)
        self.context = context
        self.lane_token = lane_token

        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon = IconLabel(icon_name, context.color(lane_token), 20)
        head.addWidget(self.icon)
        head.addWidget(section_label(title))
        head.addStretch(1)
        self.spinner = Spinner(15, context.color(lane_token))
        head.addWidget(self.spinner)
        self.switch = Switch(False)
        head.addWidget(self.switch)
        self.add_layout(head)

        self.text = faint_label(text)
        self.add(self.text)

        self.state = faint_label("", wrap=False)
        self.add(self.state)

        self.action = Button("", variant="soft")
        self.add(self.action)

    def set_checked(self, value: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(value, animate=False)
        self.switch.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        self.switch.setEnabled(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    def apply_theme(self) -> None:
        color = self.context.color(self.lane_token)
        self.icon.set_color(color)
        self.spinner.set_color(color)
        self.switch.set_colors(
            color, self.context.color("border_strong"), self.context.color("surface")
        )


class HomePage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Обзор",
            "Включите то, что не работает: сайты и Discord — обход, Telegram — "
            "прокси, Xbox и сервисы с блокировкой по стране — Smart DNS.",
            parent,
        )
        self._busy_zapret = False
        self._busy_dns = False
        self._busy_tg = False
        self._busy_vpn = False
        self._vpn_worker: Worker | None = None
        self._check_worker: Worker | None = None
        self._tg_worker: Worker | None = None
        self._dns_worker: Worker | None = None
        self._pending_updates: dict[str, object] = {}
        self._row_animations: list[QPropertyAnimation] = []

        self._build_banners()
        self._build_hero()
        self._build_tools()
        self._build_check()
        self._build_more()

        context.status_changed.connect(lambda _: self._refresh())
        context.tunnels_changed.connect(lambda _: self._refresh())
        context.tgws_changed.connect(lambda _: self._refresh())
        context.vpn_status_changed.connect(lambda _: self._refresh())
        context.servers_changed.connect(self._refresh)
        context.strategies_changed.connect(self._refresh)
        context.update_available.connect(self._update_available)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_uptime)
        self._tick.start(1000)

        self.apply_theme()

    # --- плашки -----------------------------------------------------------

    def _build_banners(self) -> None:
        self.banner_admin = Banner(
            self.context, "warning",
            "Программа запущена без прав администратора — обход не сможет "
            "работать. Перезапустите её от имени администратора.",
            kind="error",
        )
        self.body.addWidget(self.banner_admin)
        self.banner_admin.setVisible(not winapi.is_admin())

        # Чужой туннель — не ошибка: объясняем и даём кнопку.
        self.banner_tunnel = Banner(
            self.context, "globe", "", kind="warn", action_text="Выключить обход",
        )
        self.banner_tunnel.action.clicked.connect(lambda: self.stop_bypass())
        self.body.addWidget(self.banner_tunnel)
        self.banner_tunnel.setVisible(False)

        # Найденное обновление показываем здесь, а не на вкладке из «Ещё».
        self.banner_update = Banner(
            self.context, "cloud_download", "", kind="info", action_text="Установить",
        )
        self.banner_update.action.clicked.connect(self._install_pending)
        self.body.addWidget(self.banner_update)
        self.banner_update.setVisible(False)

    # --- главная карточка --------------------------------------------------

    def _build_hero(self) -> None:
        card = Card(padding=22, spacing=14)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.state_title = QLabel("Всё идёт напрямую")
        font = QFont("Bahnschrift", 17)
        font.setWeight(QFont.Weight.DemiBold)
        self.state_title.setFont(font)
        top.addWidget(self.state_title)
        top.addStretch(1)
        self.spinner = Spinner(20, self.context.color("accent"))
        top.addWidget(self.spinner)
        card.add_layout(top)

        self.state_detail = faint_label("")
        card.add(self.state_detail)

        self.rails = RailsBoard(self.context)
        self.rails.lane_clicked.connect(self._lane_clicked)
        card.add(self.rails)

        self.body.addWidget(card)

    # --- три инструмента ---------------------------------------------------

    def _build_tools(self) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self.card_zapret = ToolCard(
            self.context, "shield_check", "Обход DPI",
            "Сайты, YouTube и Discord. Работает сразу для всей системы, "
            "скорость не падает.", "lane_zapret",
        )
        self.card_zapret.switch.toggled.connect(self._toggle_zapret)
        self.card_zapret.action.setText("Стратегия")
        self.card_zapret.action.clicked.connect(
            lambda: self.context.navigate.emit("strategies")
        )
        grid.addWidget(self.card_zapret, 0, 0)

        self.card_vpn = ToolCard(
            self.context, "layers", "VPN",
            "Ваша подписка: туннель для выбранных программ или прокси без "
            "конфликтов с другим VPN.", "lane_vpn",
        )
        self.card_vpn.switch.toggled.connect(self._toggle_vpn)
        self.card_vpn.action.setText("Серверы")
        self.card_vpn.action.clicked.connect(lambda: self.context.navigate.emit("vpn"))
        grid.addWidget(self.card_vpn, 0, 1)

        self.card_tg = ToolCard(
            self.context, "telegram", "Telegram",
            "Прокси внутри программы: включите и нажмите «Открыть в Telegram».",
            "lane_tg",
        )
        self.card_tg.switch.toggled.connect(self._toggle_tg)
        self.card_tg.action.setText("Открыть в Telegram")
        self.card_tg.action.clicked.connect(self._open_telegram)
        grid.addWidget(self.card_tg, 1, 0)

        self.card_dns = ToolCard(
            self.context, "globe", "Smart DNS",
            "Xbox Live, Game Pass и сервисы, закрытые по стране. "
            "Не мешает обходу и VPN.", "lane_dns",
        )
        self.card_dns.switch.toggled.connect(self._toggle_dns)
        self.card_dns.action.setText("Другой сервис")
        self.card_dns.action.clicked.connect(lambda: self.context.navigate.emit("dns"))
        grid.addWidget(self.card_dns, 1, 1)

        self.body.addLayout(grid)

    # --- проверка ----------------------------------------------------------

    def _build_check(self) -> None:
        card = Card(padding=18, spacing=14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(10)
        self.stat_zapret = StatItem("Обход", "выключен")
        self.stat_vpn = StatItem("VPN", "выключен")
        self.stat_tg = StatItem("Telegram", "выключен")
        self.stat_dns = StatItem("Smart DNS", "выключен")
        self.stat_uptime = StatItem("Время работы", "—")
        for column, item in enumerate((
            self.stat_zapret, self.stat_vpn, self.stat_tg, self.stat_dns, self.stat_uptime
        )):
            grid.addWidget(item, 0, column)
        grid.setColumnStretch(5, 1)
        card.add_layout(grid)

        card.add(Divider())

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        actions.addWidget(self.check_spinner)
        self.btn_check = Button("Проверить доступность", variant="primary")
        self.btn_check.clicked.connect(self._run_check)
        actions.addWidget(self.btn_check)
        self.btn_speed = Button("Замерить скорость", variant="soft")
        self.btn_speed.clicked.connect(self._open_speed)
        actions.addWidget(self.btn_speed)
        self.btn_diag = Button("Диагностика", variant="ghost")
        self.btn_diag.clicked.connect(lambda: self.context.navigate.emit("diagnostics"))
        actions.addWidget(self.btn_diag)
        actions.addStretch(1)
        card.add_layout(actions)

        self.check_results = QVBoxLayout()
        self.check_results.setSpacing(6)
        card.add_layout(self.check_results)

        self.body.addWidget(card)

    # --- дополнительно -----------------------------------------------------

    def _build_more(self) -> None:
        """Игровой фильтр, IPSet и перезапуск — в одном клике, но не на виду."""
        from app.core import lists as lists_module
        from app.ui.widgets import SettingRow

        self.more = Collapsible("Дополнительно", self.context)
        self.more.set_hint("игровой фильтр · IPSet · перезапуск")

        card = Card(padding=18, spacing=12)

        self.game_box = QComboBox()
        for key, label in GAME_FILTER_LABELS.items():
            self.game_box.addItem(label.capitalize(), key)
        self.game_box.currentIndexChanged.connect(self._change_game_filter)
        card.add(SettingRow(
            "Игровой фильтр",
            "Расширяет обход на порты 1024–65535, чтобы заработали игры и "
            "голосовые сервисы. Нагрузка растёт, часть программ может сбоить — "
            "включайте, если без него игры не работают.",
            self.game_box,
        ))
        card.add(Divider())

        self.ipset_box = QComboBox()
        for key, label in lists_module.IPSET_MODES.items():
            self.ipset_box.addItem(label, key)
        self.ipset_box.currentIndexChanged.connect(self._change_ipset)
        card.add(SettingRow(
            "Фильтр по IP (IPSet)",
            "Список подсетей заблокированных сервисов — нужен там, где домен "
            "определить нельзя, например для голосовых серверов Discord.",
            self.ipset_box,
        ))
        card.add(Divider())

        restart_row = QHBoxLayout()
        restart_row.setSpacing(10)
        self.filters_hint = faint_label("", wrap=False)
        restart_row.addWidget(self.filters_hint)
        restart_row.addStretch(1)
        self.btn_restart = Button("Перезапустить обход", variant="ghost")
        self.btn_restart.clicked.connect(self._restart_bypass)
        restart_row.addWidget(self.btn_restart)
        card.add_layout(restart_row)

        self.more.body.addWidget(card)
        self.body.addWidget(self.more)
        self._sync_filters()

    def _sync_filters(self) -> None:
        from app.core import lists as lists_module
        from app.core import strategies as strategies_module

        self.game_box.blockSignals(True)
        index = self.game_box.findData(strategies_module.read_game_filter())
        if index >= 0:
            self.game_box.setCurrentIndex(index)
        self.game_box.blockSignals(False)

        self.ipset_box.blockSignals(True)
        index = self.ipset_box.findData(lists_module.ipset_mode())
        if index >= 0:
            self.ipset_box.setCurrentIndex(index)
        self.ipset_box.blockSignals(False)

        size = lists_module.ipset_size()
        self.filters_hint.setText(
            (f"{size} подсетей в списке · " if size else "")
            + "фильтры применяются после перезапуска обхода"
        )

    def _change_game_filter(self) -> None:
        from app.core import strategies as strategies_module

        mode = str(self.game_box.currentData())
        strategies_module.write_game_filter(mode)
        strategies_module.invalidate_cache()
        self.context.strategies_changed.emit()
        if self.context.status.running:
            self.context.warn(
                f"Игровой фильтр: {GAME_FILTER_LABELS[mode]}. "
                "Перезапустите обход, чтобы применить."
            )
        else:
            self.context.ok(f"Игровой фильтр: {GAME_FILTER_LABELS[mode]}")

    def _change_ipset(self) -> None:
        from app.core import lists as lists_module

        mode = str(self.ipset_box.currentData())
        try:
            lists_module.set_ipset_mode(mode)
        except (RuntimeError, OSError) as exc:
            self.context.error(str(exc))
            self._sync_filters()
            return
        self._sync_filters()
        if self.context.status.running:
            self.context.warn(
                f"Фильтр IP: {lists_module.IPSET_MODES[mode]}. "
                "Перезапустите обход, чтобы применить."
            )
        else:
            self.context.ok(f"Фильтр IP: {lists_module.IPSET_MODES[mode]}")

    def _restart_bypass(self) -> None:
        if not self.context.status.running:
            self.context.warn("Обход не запущен — нечего перезапускать.")
            return
        self.stop_bypass()
        QTimer.singleShot(1400, self.start_bypass)

    # --- состояние ---------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_filters()
        self.context.refresh_status(force=True)
        self.context.refresh_tunnels(force=True)
        self.context.refresh_tgws(force=True)
        self.context.refresh_vpn_status(force=True)

    def _lane_clicked(self, key: str) -> None:
        targets = {"zapret": "strategies", "dns": "dns", "tg": "telegram",
                   "vpn": "vpn", "foreign": "diagnostics"}
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

        self.card_zapret.set_checked(status.running)
        self.card_vpn.set_checked(vpn.running)
        self.card_tg.set_checked(tg.running)
        self.card_dns.set_checked(dns_on)

        servers = self.context.servers()
        transport_label = ("туннель" if vpn_actions.transport() == vpn_config.TRANSPORT_TUN
                           else "прокси")
        if vpn.running:
            self.card_vpn.state.setText(
                f"работает · {transport_label} · {vpn.server or 'сервер'}"
            )
        elif servers:
            self.card_vpn.state.setText(
                f"выключен · {transport_label} · {self.context.selected_server()}"
            )
        else:
            self.card_vpn.state.setText("выключен · подписка не добавлена")
        self.card_vpn.action.setText("Серверы" if servers else "Добавить подписку")

        strategy = self.context.current_strategy()
        self.card_zapret.state.setText(
            f"работает · {strategy.title if strategy else 'стратегия'}"
            if status.running else
            f"выключен · стратегия: {strategy.title if strategy else '—'}"
        )
        self.card_zapret.action.setText(
            "Сменить стратегию" if status.running else "Выбрать стратегию"
        )
        self.card_tg.state.setText(
            f"работает · порт {tg.port}" + (f" · соединений {tg.active}" if tg.active else "")
            if tg.running else "выключен · Telegram подключается напрямую"
        )
        self.card_tg.action.setEnabled(tg.running)
        self.card_dns.state.setText(
            f"работает · {dns_title}" if dns_on else "выключен · адреса от провайдера"
        )
        self.card_dns.action.setText(
            "Другой сервис" if dns_on else "Выбрать сервис"
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
            vpn_chips=[vpn_config.MODE_LABELS.get(vpn.mode, "")
                       if vpn.transport == vpn_config.TRANSPORT_TUN else "прокси"],
        )

        active = []
        if status.running:
            active.append("обход")
        if vpn.running:
            active.append("VPN")
        if tg.running:
            active.append("Telegram")
        if dns_on:
            active.append("Smart DNS")

        if tunnels and status.running:
            title = "Обход работает вместе с VPN"
            detail = (f"Поднят чужой туннель ({', '.join(tunnels)}). Через него трафик "
                      "и так идёт мимо блокировок, а обход может ему мешать — "
                      "лучше оставить что-то одно.")
        elif tunnels:
            title = f"Работает VPN — {', '.join(tunnels)}"
            detail = ("Трафик уходит в чужой туннель. Программа в это не "
                      "вмешивается и ничего не выключает.")
        elif len(active) >= 2:
            title = "Работают " + ", ".join(active)
            detail = "Всё, что включено, действует одновременно и друг другу не мешает."
        elif active:
            title = {"обход": "Работает обход", "Telegram": "Работает прокси Telegram",
                     "Smart DNS": "Работает только Smart DNS",
                     "VPN": "Работает VPN"}[active[0]]
            detail = {
                "обход": "Discord, YouTube и сайты из списка открываются в обход блокировки.",
                "VPN": ("Выбранные программы идут через туннель, остальные — напрямую."
                        if vpn.transport == vpn_config.TRANSPORT_TUN else
                        "Браузеры и всё, что уважает системный прокси, идут через VPN."),
                "Telegram": "Telegram идёт через WebSocket. Сайты и Discord — напрямую: "
                            "включите обход, если они не открываются.",
                "Smart DNS": "Блокировку по стране обходим, но DPI провайдера — нет. "
                             "Включите обход, если сайты не открываются.",
            }[active[0]]
        else:
            title = "Всё идёт напрямую"
            detail = "Ничего не включено. Начните с обхода — это один переключатель."

        self._set_state(title, detail)
        self._sync_tunnel_banner(tunnels, status.running)

        self.stat_zapret.set_value(status.mode_label if status.running else "выключен")
        self.stat_vpn.set_value(transport_label if vpn.running else "выключен")
        self.stat_tg.set_value("работает" if tg.running else "выключен")
        self.stat_dns.set_value(dns_title if dns_on else "выключен")
        self._refresh_uptime()

    def _set_state(self, title: str, detail: str) -> None:
        """Смена заголовка с коротким проявлением, а не рывком."""
        if self.state_title.text() == title:
            self.state_detail.setText(detail)
            return
        self.state_title.setText(title)
        self.state_detail.setText(detail)
        effect = QGraphicsOpacityEffect(self.state_title)
        self.state_title.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self.state_title)
        animation.setDuration(260)
        animation.setStartValue(0.15)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.state_title.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _sync_tunnel_banner(self, tunnels: list[str], zapret_on: bool) -> None:
        if not tunnels or not config.get("warn_about_vpn", True):
            self.banner_tunnel.setVisible(False)
            return
        names = ", ".join(tunnels)
        if zapret_on:
            self.banner_tunnel.set_kind("warn")
            self.banner_tunnel.set_text(
                f"Одновременно работают обход и VPN ({names}). Обход правит "
                "пакеты уже на входе в туннель, и VPN может из-за этого рваться. "
                "Оставьте что-то одно."
            )
            self.banner_tunnel.action.setVisible(True)
        else:
            self.banner_tunnel.set_kind("ok")
            self.banner_tunnel.set_text(
                f"Обнаружен VPN: {names}. Программа его не трогает — ни адаптер, "
                "ни процесс. Обход выключен, они друг другу не мешают."
            )
            self.banner_tunnel.action.setVisible(False)
        self.banner_tunnel.setVisible(True)

    def _update_available(self, kind: str, info) -> None:
        if info is None:
            self._pending_updates.pop(kind, None)
        else:
            self._pending_updates[kind] = info
        core = self._pending_updates.get("core")
        app_info = self._pending_updates.get("app")
        if app_info is not None:
            self.banner_update.set_text(
                f"Вышла новая версия программы {app_info.latest}. Установится "
                "сама: программа закроется и откроется уже обновлённой."
            )
        elif core is not None:
            self.banner_update.set_text(
                f"Вышло обновление ядра zapret {core.latest} — свежие стратегии "
                "и списки. Обход на пару секунд перезапустится."
            )
        self.banner_update.setVisible(bool(core or app_info))

    def _install_pending(self) -> None:
        kind = "app" if "app" in self._pending_updates else "core"
        self.context.navigate.emit("updates")
        self.context.install_update.emit(kind)

    def _refresh_uptime(self) -> None:
        seconds = engine.uptime_seconds()
        if not seconds:
            self.stat_uptime.set_value("—")
            return
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        self.stat_uptime.set_value(
            f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        )

    # --- переключатели -----------------------------------------------------

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
        self._busy_zapret = True
        self.spinner.start()
        self.card_zapret.set_busy(True)

        if value:
            strategy = self.context.current_strategy()
            if strategy is None:
                self._zapret_done("Стратегия не найдена.", error=True)
                return
            mode = str(config.get("run_mode"))
            worker = Worker(self)
            worker.finished.connect(
                lambda _: self._zapret_done(f"Обход включён — «{strategy.title}»")
            )
            worker.failed.connect(lambda msg: self._zapret_done(msg, error=True))
            worker.run(engine.start, strategy, mode)
        else:
            worker = Worker(self)
            worker.finished.connect(lambda _: self._zapret_done("Обход выключен"))
            worker.failed.connect(lambda msg: self._zapret_done(msg, error=True))
            worker.run(engine.stop)
        self._zapret_worker = worker

    def _zapret_done(self, message: str, error: bool = False) -> None:
        self._busy_zapret = False
        self.spinner.stop()
        self.card_zapret.set_busy(False)
        self.context.refresh_status(force=True)
        (self.context.error if error else self.context.ok)(message)

    def _toggle_tg(self, value: bool) -> None:
        if self._busy_tg:
            return
        self._busy_tg = True
        self.card_tg.set_busy(True)

        def done(ok: bool) -> None:
            self._busy_tg = False
            self.card_tg.set_busy(False)
            self._refresh()
            if ok and value:
                # Человеку нужен следующий шаг, а не просто «включено».
                QTimer.singleShot(400, lambda: self.context.warn(
                    "Теперь нажмите «Открыть в Telegram», чтобы он подключился через прокси."
                ))

        self._tg_worker = tgws_actions.toggle(self, self.context, value, done)

    def _open_telegram(self) -> None:
        tgws_actions.open_in_telegram(self.context)

    def _toggle_vpn(self, value: bool) -> None:
        if self._busy_vpn:
            return
        self._busy_vpn = True
        self.card_vpn.set_busy(True)
        self.spinner.start()

        def done(_ok: bool) -> None:
            self._busy_vpn = False
            self.card_vpn.set_busy(False)
            self.spinner.stop()
            self._refresh()

        if value:
            self._vpn_worker = vpn_actions.start(
                self, self.context, done,
                on_progress=lambda text: self.state_detail.setText(text),
            )
            if self._vpn_worker is None:
                done(False)
        else:
            self._vpn_worker = vpn_actions.stop(self, self.context, done)

    def _toggle_dns(self, value: bool) -> None:
        from app.core import dnsctl

        if self._busy_dns:
            return
        self._busy_dns = True
        self.card_dns.set_busy(True)
        key = DNS_DEFAULT_PRESET if value else "auto"

        worker = Worker(self)
        worker.finished.connect(lambda message: self._dns_done(str(message)))
        worker.failed.connect(lambda message: self._dns_done(str(message), error=True))
        worker.run(dnsctl.apply_preset, key)
        self._dns_worker = worker

    def _dns_done(self, message: str, error: bool = False) -> None:
        self._busy_dns = False
        self.card_dns.set_busy(False)
        self._refresh()
        (self.context.error if error else self.context.ok)(message)

    # --- проверка ----------------------------------------------------------

    def _run_check(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        clear_layout(self.check_results)

        self.btn_check.setEnabled(False)
        self.check_spinner.start()
        # В режиме «Прокси» VPN доступен только через локальный прокси —
        # проверяем через него, иначе тест пойдёт мимо VPN.
        from app.core.vpn.engine import vpn_engine

        proxy_url = vpn_engine.proxy_url()
        worker = Worker(self)
        worker.finished.connect(self._check_ready)
        worker.failed.connect(self._check_failed)
        worker.run(autotest.quick_check, proxy_url)
        self._check_worker = worker

    def _open_speed(self) -> None:
        """Кнопка ведёт на страницу замера и сразу его запускает."""
        self.context.navigate.emit("speed")
        window = self.window()
        ensure = getattr(window, "ensure_page", None)
        page = ensure("speed") if callable(ensure) else None
        starter = getattr(page, "start_measure", None)
        if callable(starter):
            QTimer.singleShot(260, starter)

    def _check_failed(self, message: str) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(message)

    def _check_ready(self, results) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        clear_layout(self.check_results)
        self._row_animations.clear()

        for index, item in enumerate(results):
            row = QWidget(self)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(9)

            token = "success" if item.ok else "danger"
            line.addWidget(IconLabel(
                "check" if item.ok else "cross", self.context.color(token), 15
            ))
            line.addWidget(QLabel(item.target.key or item.target.label))
            line.addStretch(1)
            line.addWidget(faint_label(
                f"{item.ms:.0f} мс" if item.ok else "нет ответа", wrap=False
            ))
            self.check_results.addWidget(row)
            self._fade_row(row, delay=index * 45)

        failed = [item for item in results if not item.ok]
        if not failed:
            self.context.ok("Все адреса открываются")
        else:
            self.context.warn(f"Не открылось адресов: {len(failed)}")

    def _fade_row(self, row: QWidget, delay: int) -> None:
        """Строки результата проявляются одна за другой."""
        effect = QGraphicsOpacityEffect(row)
        effect.setOpacity(0.0)
        row.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", row)
        animation.setDuration(220)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: row.setGraphicsEffect(None))
        self._row_animations.append(animation)
        QTimer.singleShot(delay, animation.start)

    # --- тема --------------------------------------------------------------

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.spinner.set_color(accent)
        self.check_spinner.set_color(accent)
        for card in (self.card_zapret, self.card_vpn, self.card_tg, self.card_dns):
            card.apply_theme()
        self.more.apply_theme()
        self.rails.apply_theme()
        self._refresh()
