"""Главная: сад за стеной и четыре почтовые марки.

Сад показывает, что работает: лоза на стене — обход, калитка к морю — VPN,
птица с письмом — Telegram, указатель — Smart DNS. Выключенное нарисовано
карандашом, включённое распускается красками. Под садом — марки с
тумблерами: включить, выключить и выбрать стратегию, сервер или сервис,
не уходя с экрана. Штемпель над садом считает, сколько из четырёх работает.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core import autotest, winapi
from app.core.config import config
from app.core.engine import engine
from app.core.vpn import config as vpn_config
from app.ui import scenes, tgws_actions, vpn_actions
from app.ui.context import AppContext
from app.ui.ink import InkCanvas
from app.ui.naming import capital, join_ru, long_date, server_code, strategy_den
from app.ui.pages.base import Banner, Page
from app.ui.stamps import Postmark, StampCard
from app.ui.widgets import (
    Button,
    Card,
    MonoLabel,
    SerifTitle,
    Spinner,
    StatusChip,
    Switch,
    Worker,
    clear_layout,
    fade_in,
    faint_label,
)

# Сервис Smart DNS, который включается с главной, если человек ничего не выбирал.
DNS_DEFAULT_PRESET = "comss"

NAMES = {"dpi": "обход", "vpn": "VPN", "tg": "Telegram", "dns": "Smart DNS"}
ORDER = ("dpi", "vpn", "tg", "dns")


class StampColumn(QWidget):
    """Марка, под ней — состояние с тумблером и выбор (стратегии, сервера…)."""

    toggled = Signal(bool)
    opened = Signal()

    def __init__(self, context: AppContext, key: str, scene, tint: str, caption: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.key = key
        self._on = False
        # Марка — вещь небольшая: в широком окне она не растёт, а стоит
        # посередине своего места.
        self.setMaximumWidth(244)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.stamp = StampCard(context, scene, tint, caption, parent=self)
        self.stamp.clicked.connect(self.opened.emit)
        layout.addWidget(self.stamp)

        slip = QHBoxLayout()
        slip.setContentsMargins(PAD_SIDE, 0, PAD_SIDE + 26, 0)
        slip.setSpacing(8)
        self.chip = StatusChip("Ждёт", context, False, self)
        self.chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        slip.addWidget(self.chip, 1)
        self.spinner = Spinner(14, context.color("accent"))
        slip.addWidget(self.spinner)
        self.switch = Switch(False)
        self.switch.toggled.connect(self.toggled.emit)
        slip.addWidget(self.switch)
        layout.addLayout(slip)

        self.controls = QHBoxLayout()
        self.controls.setContentsMargins(PAD_SIDE, 0, PAD_SIDE + 26, 0)
        self.controls.setSpacing(6)
        layout.addLayout(self.controls)

    def set_on(self, value: bool, animate: bool = True) -> None:
        changed = value != self._on
        self._on = value
        self.switch.blockSignals(True)
        self.switch.setChecked(value, animate=animate and changed)
        self.switch.blockSignals(False)
        self.stamp.set_on(value, animate)

    def set_state(self, chip: str, detail: str, kind: str = "") -> None:
        self.chip.set_state(chip, self._on, kind)
        self.chip.setToolTip(detail)
        self.stamp.setToolTip(detail)

    def set_busy(self, busy: bool) -> None:
        self.switch.setEnabled(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()


PAD_SIDE = 4


class HomePage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(context, "Главная", "", parent)
        self._busy_zapret = False
        self._busy_dns = False
        self._busy_tg = False
        self._busy_vpn = False
        self._workers: dict[str, Worker | None] = {}
        self._check_worker: Worker | None = None
        self._pending_updates: dict[str, object] = {}
        self._animations: list = []
        self._shown_once = False
        self._first_state = True

        # Шапки раздела у главной нет: её заголовок — живая строка о саде.
        self.header.hide()
        self.body.setContentsMargins(40, 18, 40, 22)
        self.body.setSpacing(20)

        self._build_banners()
        self._build_hero()
        self._build_stamps()
        self._build_check()

        context.status_changed.connect(lambda _: self._refresh())
        context.tunnels_changed.connect(lambda _: self._refresh())
        context.foreign_vpn_changed.connect(lambda _: self._refresh())
        context.dns_changed.connect(lambda _: self._refresh())
        context.tgws_changed.connect(lambda _: self._refresh())
        context.vpn_status_changed.connect(lambda _: self._refresh())
        context.servers_changed.connect(self._reload_servers)
        context.strategies_changed.connect(self._reload_strategies)
        context.update_available.connect(self._update_available)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
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

    # --- шапка: слова слева, сад справа -----------------------------------

    def _build_hero(self) -> None:
        hero = QHBoxLayout()
        hero.setSpacing(40)

        words = QVBoxLayout()
        words.setSpacing(14)
        words.addStretch(1)
        self.eyebrow = MonoLabel("Сейчас", self.context, "accent_ink", 11, 0.1)
        words.addWidget(self.eyebrow)
        self.state_title = SerifTitle("Сад *спит*, почта закрыта", self.context, 40)
        self.state_title.setMinimumWidth(240)
        words.addWidget(self.state_title)
        self.state_detail = QLabel("")
        self.state_detail.setObjectName("Lede")
        self.state_detail.setWordWrap(True)
        words.addWidget(self.state_detail)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_check = Button("Проверить доступность  →", variant="primary")
        self.btn_check.setToolTip("Открыть десяток заблокированных адресов и посмотреть, "
                                  "какие отвечают прямо сейчас")
        self.btn_check.clicked.connect(self._run_check)
        actions.addWidget(self.btn_check)
        self.btn_speed = Button("Замерить скорость", variant="soft")
        self.btn_speed.clicked.connect(self._open_speed)
        actions.addWidget(self.btn_speed)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        actions.addWidget(self.check_spinner)
        actions.addStretch(1)
        words.addLayout(actions)
        words.addStretch(1)
        hero.addLayout(words, 5)

        # Тарелка с садом, на краю — большой штемпель.
        self.plate_host = QWidget()
        self.plate_host.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Maximum)
        plate_layout = QVBoxLayout(self.plate_host)
        plate_layout.setContentsMargins(0, 22, 20, 0)
        self.plate_host.setMaximumWidth(620)
        self.garden = InkCanvas(scenes.garden(), self.context, plate="plate", radius=24)
        for key, (box, tip) in scenes.GARDEN_REGIONS.items():
            self.garden.add_region(box, key, tip)
        self.garden.clicked_region.connect(self._open_section)
        plate_layout.addWidget(self.garden)
        self.postmark = Postmark(self.context, 160, self.plate_host)
        # По центру по высоте: в узком окне колонка слов выше сада, и без
        # выравнивания тарелка растягивалась пустой бумагой.
        hero.addWidget(self.plate_host, 7, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(hero)

    def _place_postmark(self) -> None:
        geometry = self.garden.geometry()
        # Штемпель — по размеру сада: в узком окне он не должен его закрывать.
        size = int(min(164, max(96, geometry.width() * 0.27)))
        if size != self.postmark.width():
            self.postmark.setFixedSize(size, size)
            self.postmark.update()
        self.postmark.move(geometry.right() - size + int(size * 0.24),
                           geometry.top() - int(size * 0.18))
        self.postmark.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_stamps()
        QTimer.singleShot(0, self._place_postmark)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._place_postmark)

    # --- марки ------------------------------------------------------------

    def _build_stamps(self) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(18)
        grid.setContentsMargins(4, 0, 4, 0)

        self.col_dpi = StampColumn(self.context, "dpi", scenes.stamp_dpi(), "tint_dpi",
                                   "ОБХОД DPI")
        self.col_dpi.toggled.connect(self._toggle_zapret)
        self.col_dpi.opened.connect(lambda: self._open_section("dpi"))
        self.strategy_box = QComboBox()
        self.strategy_box.setToolTip("Стратегия обхода")
        self.strategy_box.activated.connect(self._strategy_picked)
        self.col_dpi.controls.addWidget(self.strategy_box, 1)

        self.col_vpn = StampColumn(self.context, "vpn", scenes.stamp_vpn(), "tint_vpn",
                                   "VPN")
        self.col_vpn.toggled.connect(self._toggle_vpn)
        self.col_vpn.opened.connect(lambda: self._open_section("vpn"))
        self.server_box = QComboBox()
        self.server_box.setToolTip("Сервер VPN")
        self.server_box.activated.connect(self._server_picked)
        self.col_vpn.controls.addWidget(self.server_box, 1)
        self.btn_vpn_more = Button("Добавить подписку", variant="soft")
        self.btn_vpn_more.clicked.connect(lambda: self.context.navigate.emit("vpnconnect"))
        self.col_vpn.controls.addWidget(self.btn_vpn_more, 1)

        self.col_tg = StampColumn(self.context, "tg", scenes.stamp_tg(), "tint_tg", "TELEGRAM")
        self.col_tg.toggled.connect(self._toggle_tg)
        self.col_tg.opened.connect(lambda: self._open_section("tg"))
        self.btn_tg_open = Button("Открыть в Telegram", variant="soft")
        self.btn_tg_open.clicked.connect(lambda: tgws_actions.open_in_telegram(self.context))
        self.col_tg.controls.addWidget(self.btn_tg_open, 1)

        self.col_dns = StampColumn(self.context, "dns", scenes.stamp_dns(), "tint_dns",
                                   "SMART DNS")
        self.col_dns.toggled.connect(self._toggle_dns)
        self.col_dns.opened.connect(lambda: self._open_section("dns"))
        self.dns_box = QComboBox()
        self.dns_box.setToolTip("Сервис Smart DNS")
        self.dns_box.activated.connect(self._dns_picked)
        self.col_dns.controls.addWidget(self.dns_box, 1)

        # Списки сжимаются вместе с окном, а не распирают марку длиной
        # самого длинного названия.
        for box in (self.strategy_box, self.server_box, self.dns_box):
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            box.setMinimumContentsLength(4)

        self._columns = (self.col_dpi, self.col_vpn, self.col_tg, self.col_dns)
        self._stamps_grid = grid
        self._stamp_columns = 0
        self.body.addLayout(grid)
        self._fit_stamps()

    def _fit_stamps(self) -> None:
        """Четыре марки в ряд, а в узком окне — две на две."""
        columns = 4 if self.width() >= 900 else 2
        if columns == self._stamp_columns:
            return
        self._stamp_columns = columns
        for index, column in enumerate(self._columns):
            self._stamps_grid.removeWidget(column)
            self._stamps_grid.addWidget(column, index // columns, index % columns,
                                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        for index in range(4):
            self._stamps_grid.setColumnStretch(index, 1 if index < columns else 0)

    # --- проверка доступности: письма, которые дошли или вернулись --------

    def _build_check(self) -> None:
        self.check_card = Card(padding=18, spacing=10)
        top = QHBoxLayout()
        top.setSpacing(12)
        title = QLabel("Письма на заблокированные адреса")
        title.setObjectName("CardTitle")
        top.addWidget(title)
        top.addStretch(1)
        self.check_summary = StatusChip("", self.context, True)
        top.addWidget(self.check_summary)
        self.check_card.add_layout(top)

        self.check_host = QWidget()
        self.check_grid = QGridLayout(self.check_host)
        self.check_grid.setContentsMargins(0, 0, 0, 0)
        self.check_grid.setHorizontalSpacing(26)
        self.check_grid.setVerticalSpacing(6)
        self.check_card.add(self.check_host)
        self.body.addWidget(self.check_card)
        self.check_card.setVisible(False)

    # --- списки под марками ----------------------------------------------

    def _reload_strategies(self) -> None:
        items = self.context.load_strategies()
        current = self.context.current_strategy()
        # Список тот же и выбрана та же — пересобирать нечего: это лишняя
        # работа сразу после перехода на главную.
        signature = ([(item.title, item.id) for item in items],
                     current.id if current is not None else "")
        if signature == getattr(self, "_strategies_signature", None):
            return
        self._strategies_signature = signature
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
        self.col_dpi.stamp.set_den(strategy_den(current.title) if current else "—")

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
        self.server_box.setEnabled(bool(servers))
        self.server_box.blockSignals(False)
        # Без подписки выбирать нечего — вместо списка кнопка, где её взять.
        self.server_box.setVisible(bool(servers))
        self.btn_vpn_more.setVisible(not servers)
        self._sync_vpn_den()
        self._refresh()

    def _sync_vpn_den(self) -> None:
        name = self.context.selected_server() or (self.server_box.currentData() or "")
        self.col_vpn.stamp.set_den(server_code(str(name)) if self.context.servers() else "—")

    def _reload_dns(self) -> None:
        from app.core import dnsctl

        wanted = str(config.get("home_dns_preset", DNS_DEFAULT_PRESET))
        if wanted not in dnsctl.PRESET_BY_KEY or wanted == "auto":
            wanted = DNS_DEFAULT_PRESET
        current = self.context.dns_preset
        chosen = current if current in dnsctl.PRESET_BY_KEY and current != "auto" else wanted
        self.dns_box.blockSignals(True)
        self.dns_box.clear()
        for preset in dnsctl.PRESETS:
            if preset.key != "auto":
                self.dns_box.addItem(preset.title, preset.key)
        index = self.dns_box.findData(chosen)
        if index >= 0:
            self.dns_box.setCurrentIndex(index)
        self.dns_box.blockSignals(False)
        self._sync_dns_den()

    def _sync_dns_den(self) -> None:
        from app.core import dnsctl

        key = str(self.dns_box.currentData() or DNS_DEFAULT_PRESET)
        preset = dnsctl.PRESET_BY_KEY.get(key)
        title = preset.title.replace(" DNS", "") if preset else "DNS"
        self.col_dns.stamp.set_den(title)
        self.col_dns.stamp.set_text("sign", title.upper()[:7])
        address = preset.ipv4[0] if preset and preset.ipv4 else ""
        if len(address) > 8:
            address = ".".join(address.split(".")[:2]) + "…"
        self.col_dns.stamp.set_text("addr", address)
        self.garden.set_text("dns_sign", title.upper()[:6])

    # --- состояние ----------------------------------------------------------

    def on_activate(self) -> None:
        # Свежие данные — фоновым опросом: синхронный опрос здесь тормозил
        # анимацию перехода на главную.
        poll = getattr(self.window(), "_poll_state", None)
        if callable(poll):
            poll(force=True)
        self._reload_strategies()
        self._reload_dns()
        if not self._shown_once:
            # Первое появление: марки ложатся на стол по очереди.
            self._shown_once = True
            for index, column in enumerate(self._columns):
                fade_in(column, 420, delay=120 + index * 80, keep=self._animations)

    def _open_section(self, key: str) -> None:
        targets = {"dpi": "strategies", "dns": "dns", "tg": "telegram", "vpn": "vpnconnect"}
        page = targets.get(key)
        if page:
            self.context.navigate.emit(page)

    def _dns_state(self) -> tuple[bool, str]:
        from app.core import dnsctl

        # Из последнего фонового опроса: реестр читать на каждое обновление
        # экрана — лишние миллисекунды в потоке окна.
        preset = self.context.dns_preset or "auto"
        if preset.startswith("retired:"):
            return True, dnsctl.retired_title(preset) + " (закрыт)"
        title = next((item.title for item in dnsctl.PRESETS if item.key == preset), "")
        if preset == "custom":
            title = "свои адреса"
        return preset != "auto", title

    def _refresh(self) -> None:
        status = self.context.status
        tg = self.context.tgws_status
        vpn = self.context.vpn_status
        dns_on, dns_title = self._dns_state()
        animate = not self._first_state
        self._first_state = False

        states = {"dpi": status.running, "vpn": vpn.running, "tg": tg.running, "dns": dns_on}
        for key, column in zip(ORDER, self._columns):
            column.set_on(states[key], animate)
            self.garden.set_state(key, states[key], animate)
        self.garden.set_state("any", any(states.values()), animate)

        strategy = self.context.current_strategy()
        testing = engine.testing
        if testing:
            self.col_dpi.set_state("Идёт проверка…", "Идёт проверка стратегий — обход вернётся сам.",
                                   "warn")
        elif status.running:
            self.col_dpi.set_state(
                f"Работает · {status.mode_label}{self._uptime_suffix()}",
                f"Обход работает · {status.mode_label}. Стратегия «"
                f"{strategy.title if strategy else '—'}».")
        else:
            self.col_dpi.set_state("Ждёт", "Обход выключен — сайты и Discord идут напрямую.")

        from app.core.vpn.engine import vpn_engine

        transport_label = ("туннель" if vpn_actions.transport() == vpn_config.TRANSPORT_TUN
                           else "прокси")
        if vpn_engine.is_starting():
            self.col_vpn.set_state("Подключается…", "VPN поднимается.", "warn")
        elif vpn.running:
            mode = (vpn_config.MODE_LABELS.get(vpn.mode, "").lower()
                    if vpn.transport == vpn_config.TRANSPORT_TUN else "")
            self.col_vpn.set_state(f"Работает · {transport_label}",
                                   f"VPN работает · {transport_label}"
                                   + (f" · {mode}" if mode else "")
                                   + (f" · {vpn.server}" if vpn.server else ""))
        elif self.context.servers():
            self.col_vpn.set_state("Ждёт", f"VPN выключен · {transport_label}.")
        else:
            self.col_vpn.set_state("Нужна подписка", "Добавьте подписку на вкладке VPN.")
        self._sync_vpn_den()

        if tg.running:
            self.col_tg.set_state(
                f"Работает · {tg.active} соед." if tg.active else "Работает",
                f"Прокси Telegram работает · порт {tg.port}"
                + (f" · соединений {tg.active}" if tg.active else ""))
        else:
            self.col_tg.set_state("Ждёт", "Прокси выключен — Telegram идёт напрямую.")
        self.col_tg.stamp.set_den(str(tg.port or config.get("tg_ws_port", 1443)))
        self.btn_tg_open.setEnabled(tg.running)

        if dns_on:
            self.col_dns.set_state(f"Работает · {dns_title}", f"Smart DNS работает · {dns_title}.",
                                   "warn" if "закрыт" in dns_title else "")
        else:
            self.col_dns.set_state("Ждёт", "DNS — как выдаёт провайдер или роутер.")

        self._set_headline(states, status, vpn, strategy)
        self._sync_tunnel_banner(self.context.foreign_vpn, status.running)

    def _uptime_suffix(self) -> str:
        seconds = engine.uptime_seconds()
        if not seconds:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes, _secs = divmod(remainder, 60)
        return f" · {hours}:{minutes:02d}" if hours else f" · {minutes} мин"

    def _set_headline(self, states: dict, status, vpn, strategy) -> None:
        on = [key for key in ORDER if states[key]]
        off = [key for key in ORDER if not states[key]]
        if len(on) == 4:
            title = "Письма доходят, сад *цветёт*"
            detail = "Обход, VPN, Telegram и Smart DNS работают одновременно и друг другу не мешают."
            ring = "ВСЁ ДОХОДИТ"
        elif not on:
            title = "Сад *спит*, почта закрыта"
            detail = ("Включите обход — и письма на заблокированные адреса снова начнут "
                      "доходить. Тумблер под первой маркой.")
            ring = "ПОЧТА ЗАКРЫТА"
        else:
            names = join_ru([NAMES[key] for key in on])
            verb = "работает" if len(on) == 1 else "работают"
            title = f"{capital(names)} *{verb}*, остальное ждёт"
            ring = "ДОХОДИТ ЧАСТЬ"
            if len(on) == 1:
                detail = {
                    "dpi": "Discord, YouTube и сайты из списка открываются в обход "
                           f"блокировки. Стратегия «{strategy.title if strategy else '—'}».",
                    "vpn": ("Выбранные программы идут через туннель, остальные — напрямую."
                            if vpn.transport == vpn_config.TRANSPORT_TUN else
                            "Браузеры и всё, что уважает системный прокси, идут через VPN."),
                    "tg": "Telegram идёт через WebSocket. Сайты и Discord — напрямую: "
                          "включите обход, если они не открываются.",
                    "dns": "Блокировку по стране обходим, а DPI провайдера — нет. "
                           "Включите обход, если сайты не открываются.",
                }[on[0]]
            else:
                rest = join_ru([NAMES[key] for key in off])
                detail = (f"{capital(rest)} {'выключен' if len(off) == 1 else 'выключены'}. "
                          "Включить можно тумблером под маркой.")
        clock = time.strftime("%H:%M")
        self.eyebrow.setText(f"Сейчас · {len(on)} из 4 · {clock}")
        self.state_detail.setText(detail)
        self.postmark.set_text(f"САД И ПОЧТА · {ring} · {long_date()} ·", f"{len(on)}/4", clock,
                               press=self.isVisible())
        if self.state_title.title() != title:
            self.state_title.set_title(title)
            fade_in(self.state_title, 420, keep=self._animations)
            del self._animations[:-16]

    def _sync_tunnel_banner(self, foreign: list[str], zapret_on: bool) -> None:
        """Небольшая плашка, пока работает сторонний VPN — туннелем или прокси."""
        if not foreign or not config.get("warn_about_vpn", True):
            self.banner_tunnel.setVisible(False)
            return
        names = ", ".join(foreign)
        self.banner_tunnel.set_text(
            f"Обнаружен другой VPN — {names}. Он может мешать работе программы."
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

    def _sync_vpn_starting(self) -> None:
        """Пока туннель поднимается, марка занята — второй щелчок не нужен."""
        from app.core.vpn.engine import vpn_engine

        starting = vpn_engine.is_starting()
        if starting:
            self.col_vpn.set_busy(True)
            self.col_vpn.set_state("Подключается…", "VPN поднимается.", "warn")
        elif not self._busy_vpn and not self.col_vpn.switch.isEnabled():
            self.col_vpn.set_busy(False)
            self._refresh()

    def _on_tick(self) -> None:
        # Часы и «подключается…» нужны, только пока главная на экране.
        if not self.isVisible() or self.window().isMinimized():
            return
        self._sync_vpn_starting()
        if int(time.time()) % 20 == 0:
            self._refresh()

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
        if engine.testing:
            # Обход сейчас у проверки стратегий; она сама вернёт его как было.
            self.context.warn("Идёт проверка стратегий — обход вернётся сам через пару секунд.")
            self._refresh()
            return
        if value:
            strategy = self.context.current_strategy()
            if strategy is None:
                self.context.error("Стратегия не найдена — проверьте раздел «Запрет».")
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
        if engine.testing:
            # Обход сейчас у проверки, и вернёт она прежнюю стратегию — выбор
            # потерялся бы молча. Возвращаем список к прежней.
            self.context.warn("Идёт проверка стратегий — выберите стратегию через пару секунд.")
            current = self.context.current_strategy()
            position = self.strategy_box.findData(current.id) if current else -1
            if position >= 0:
                self.strategy_box.blockSignals(True)
                self.strategy_box.setCurrentIndex(position)
                self.strategy_box.blockSignals(False)
            return
        config.set("last_strategy", strategy_id)
        strategy = self.context.current_strategy()
        if strategy is None:
            return
        self.col_dpi.stamp.set_den(strategy_den(strategy.title))
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
        self.col_dpi.set_busy(True)
        self.strategy_box.setEnabled(False)

        def done(error: str = "") -> None:
            self._busy_zapret = False
            self.col_dpi.set_busy(False)
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
        if value and not self.context.servers():
            # Без подписки включать нечего — показываем, куда её вставить.
            self.col_vpn.set_on(False)
            self.context.warn("Сначала добавьте подписку — вставьте ссылку и нажмите «Обновить».")
            self.context.navigate.emit("vpnconnect")
            return
        self._busy_vpn = True
        self.col_vpn.set_busy(True)

        def done(_ok: bool) -> None:
            self._busy_vpn = False
            self.col_vpn.set_busy(False)
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
        self._sync_vpn_den()
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
        self.col_tg.set_busy(True)

        def done(ok: bool) -> None:
            self._busy_tg = False
            self.col_tg.set_busy(False)
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
        self._sync_dns_den()
        on, _title = self._dns_state()
        if on:
            self._apply_dns(key)

    def _apply_dns(self, key: str) -> None:
        from app.core import dnsctl

        if self._busy_dns:
            return
        self._busy_dns = True
        self.col_dns.set_busy(True)

        def done(message: str, error: bool = False) -> None:
            self._busy_dns = False
            self.col_dns.set_busy(False)
            self.context.refresh_dns()
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
            QTimer.singleShot(420, starter)

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
        was_hidden = not self.check_card.isVisible()
        self.check_card.setVisible(True)

        # Чем шире окно, тем больше столбцов и тем меньше строк по высоте.
        width = self.scroll.viewport().width()
        columns = 4 if width >= 980 else 3 if width >= 700 else 2
        for index, item in enumerate(results):
            row = QWidget(self.check_host)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 3, 0, 3)
            line.setSpacing(8)
            chip = StatusChip("", self.context, item.ok, row)
            chip.set_state("дошло" if item.ok else "возврат", item.ok,
                           "" if item.ok else "error")
            chip.setFixedWidth(84)
            line.addWidget(chip)
            name = QLabel(item.target.key or item.target.label, row)
            line.addWidget(name, 1)
            line.addWidget(faint_label(f"{item.ms:.0f} мс" if item.ok else "—", wrap=False))
            self.check_grid.addWidget(row, index // columns, index % columns)
            fade_in(row, 320, delay=index * 45, keep=self._animations)

        failed = [item for item in results if not item.ok]
        passed = len(results) - len(failed)
        self.check_summary.set_state(f"дошло {passed} из {len(results)}", not failed,
                                     "" if not failed else "warn")
        if was_hidden:
            fade_in(self.check_card, 380, keep=self._animations)
        QTimer.singleShot(80, lambda: self.scroll.ensureWidgetVisible(self.check_card, 0, 20))
        if not failed:
            self.context.ok("Все письма дошли — адреса открываются")
        else:
            self.context.warn(f"Вернулось писем: {len(failed)} — эти адреса не открылись")

    # --- тема ----------------------------------------------------------------------

    def apply_theme(self) -> None:
        self.check_spinner.set_color(self.context.color("accent"))
        for column in self._columns:
            column.spinner.set_color(self.context.color("accent"))
        self._refresh()
