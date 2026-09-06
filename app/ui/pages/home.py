"""Обзор: выключатель обхода, Smart DNS, фильтры и проверка доступности."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
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
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.rails import RailsBoard
from app.ui.widgets import (
    clear_layout,
    Button,
    Card,
    Divider,
    Spinner,
    StatItem,
    Switch,
    Worker,
    faint_label,
    section_label,
)


class HomePage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Обзор",
            "Два способа вернуть доступ: zapret ломает распознавание домена "
            "у провайдера, Smart DNS обходит блокировку по стране.",
            parent,
        )
        self._busy_zapret = False
        self._check_worker = None

        self._build_banners()
        self._build_rails()
        self._build_controls()
        self._build_filters()
        self._build_stats()

        context.status_changed.connect(lambda _: self._refresh())
        context.tunnels_changed.connect(lambda _: self._refresh())
        context.strategies_changed.connect(self._refresh)
        context.update_available.connect(self._update_available)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_uptime)
        self._tick.start(1000)

        self.apply_theme()

    # --- построение ------------------------------------------------------

    def _build_banners(self) -> None:
        self.banner_admin = Banner(
            self.context, "warning",
            "Программа запущена без прав администратора — обход не сможет "
            "работать. Перезапустите её от имени администратора.",
            kind="error",
        )
        self.body.addWidget(self.banner_admin)
        self.banner_admin.setVisible(not winapi.is_admin())

        # Чужой туннель — не ошибка. Программа просто объясняет, что при
        # включённом VPN обход не нужен, и предлагает снять его одной кнопкой.
        self.banner_tunnel = Banner(
            self.context, "globe", "", kind="warn", action_text="Выключить обход",
        )
        self.banner_tunnel.action.clicked.connect(lambda: self.stop_bypass())
        self.body.addWidget(self.banner_tunnel)
        self.banner_tunnel.setVisible(False)

        # Найденное обновление не должно лежать незамеченным на вкладке
        # из меню «Ещё» — показываем прямо здесь, с кнопкой.
        self._pending_updates: dict[str, object] = {}
        self.banner_update = Banner(
            self.context, "download", "", kind="info", action_text="Установить",
        )
        self.banner_update.action.clicked.connect(self._install_pending)
        self.body.addWidget(self.banner_update)
        self.banner_update.setVisible(False)

    def _build_rails(self) -> None:
        card = Card(padding=22, spacing=16)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.state_title = QLabel("Всё идёт напрямую")
        font = QFont("Bahnschrift", 16)
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

    def _build_controls(self) -> None:
        """Два инструмента рядом: обход и DNS. Оба включаются здесь."""
        from app.core import dnsctl

        row = QHBoxLayout()
        row.setSpacing(16)

        # --- zapret ---
        zapret_card = Card(padding=20, spacing=12)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(section_label("Обход DPI (zapret)"))
        head.addStretch(1)
        self.switch_zapret = Switch(False)
        self.switch_zapret.toggled.connect(self._toggle_zapret)
        head.addWidget(self.switch_zapret)
        zapret_card.add_layout(head)

        zapret_card.add(faint_label(
            "Ломает распознавание домена у провайдера. Работает сразу для "
            "всей системы, выбирать программы не нужно, скорость не падает."
        ))

        self.btn_strategy = Button("Основная")
        self.btn_strategy.clicked.connect(
            lambda: self.context.navigate.emit("strategies")
        )
        zapret_card.add(self.btn_strategy)
        row.addWidget(zapret_card, 1)

        # --- smart dns ---
        dns_card = Card(padding=20, spacing=12)
        head_dns = QHBoxLayout()
        head_dns.setSpacing(10)
        head_dns.addWidget(section_label("Smart DNS"))
        head_dns.addStretch(1)
        self.dns_state = faint_label("", wrap=False)
        head_dns.addWidget(self.dns_state)
        dns_card.add_layout(head_dns)

        dns_card.add(faint_label(
            "Возвращает доступ к Xbox Live, Game Pass и сервисам, которые "
            "режут по стране. Работает вместе с обходом и не мешает VPN."
        ))

        self.dns_box = QComboBox()
        for preset in dnsctl.PRESETS:
            self.dns_box.addItem(preset.title, preset.key)
        self.dns_box.currentIndexChanged.connect(self._change_dns)
        dns_card.add(self.dns_box)
        row.addWidget(dns_card, 1)

        self.body.addLayout(row)
        self._sync_dns()

    def _sync_dns(self) -> None:
        from app.core import dnsctl

        current = dnsctl.current_preset()
        self.dns_box.blockSignals(True)
        index = self.dns_box.findData(current)
        if index >= 0:
            self.dns_box.setCurrentIndex(index)
        self.dns_box.blockSignals(False)
        self.dns_state.setText(
            "выключен" if current == "auto" else "включён"
        )

    def _change_dns(self) -> None:
        from app.core import dnsctl

        key = str(self.dns_box.currentData())
        worker = Worker(self)
        worker.finished.connect(self._dns_done)
        worker.failed.connect(lambda message: self.context.error(str(message)))
        worker.run(dnsctl.apply_preset, key)
        self._dns_worker = worker

    def _dns_done(self, message) -> None:
        self.context.ok(str(message))
        self._sync_dns()
        self._refresh()

    def _build_filters(self) -> None:
        """Игровой фильтр и IPSet — те же два пункта, что в консольном меню."""
        from app.core import lists as lists_module
        from app.ui.widgets import SettingRow

        card = Card(padding=18, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Фильтры zapret"))
        header.addStretch(1)
        self.filters_hint = faint_label("применяются после перезапуска обхода",
                                        wrap=False)
        header.addWidget(self.filters_hint)
        card.add_layout(header)

        self.game_box = QComboBox()
        for key, label in GAME_FILTER_LABELS.items():
            self.game_box.addItem(label.capitalize(), key)
        self.game_box.currentIndexChanged.connect(self._change_game_filter)
        card.add(SettingRow(
            "Игровой фильтр",
            "Расширяет обход на порты 1024–65535, чтобы заработали игры и "
            "голосовые сервисы. Нагрузка растёт, а часть программ может начать "
            "сбоить — включайте, если без него игры не работают.",
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
            "определить нельзя, например для голосовых серверов Discord. "
            "«Без ограничений» отключает проверку по списку.",
            self.ipset_box,
        ))

        self.body.addWidget(card)
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
            f"{size} подсетей в списке · применяются после перезапуска обхода"
            if size else "применяются после перезапуска обхода"
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

    def _build_stats(self) -> None:
        card = Card(padding=18, spacing=14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(10)
        self.stat_zapret = StatItem("Обход", "выключен")
        self.stat_dns = StatItem("Smart DNS", "выключен")
        self.stat_filter = StatItem("Игровой фильтр", "—")
        self.stat_uptime = StatItem("Время работы", "—")
        for column, item in enumerate((
            self.stat_zapret, self.stat_dns, self.stat_filter, self.stat_uptime
        )):
            grid.addWidget(item, 0, column)
        grid.setColumnStretch(4, 1)
        card.add_layout(grid)

        card.add(Divider())

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        actions.addWidget(self.check_spinner)
        self.btn_check = Button("Проверить доступность", variant="primary")
        self.btn_check.clicked.connect(self._run_check)
        actions.addWidget(self.btn_check)
        self.btn_diag = Button("Диагностика")
        self.btn_diag.clicked.connect(
            lambda: self.context.navigate.emit("diagnostics")
        )
        actions.addWidget(self.btn_diag)
        self.btn_restart = Button("Перезапустить обход", variant="ghost")
        self.btn_restart.clicked.connect(self._restart_bypass)
        actions.addWidget(self.btn_restart)
        actions.addStretch(1)
        card.add_layout(actions)

        self.check_results = QVBoxLayout()
        self.check_results.setSpacing(6)
        card.add_layout(self.check_results)

        self.body.addWidget(card)

    def _restart_bypass(self) -> None:
        if not self.context.status.running:
            self.context.warn("Обход не запущен — нечего перезапускать.")
            return
        self.stop_bypass()
        QTimer.singleShot(1400, self.start_bypass)

    # --- состояние -------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_dns()
        self._sync_filters()
        self.context.refresh_status(force=True)
        self.context.refresh_tunnels(force=True)

    def _lane_clicked(self, key: str) -> None:
        if key == "zapret":
            self.context.navigate.emit("strategies")
        elif key == "dns":
            self.context.navigate.emit("dns")
        elif key == "vpn":
            self.context.navigate.emit("diagnostics")

    def _refresh(self) -> None:
        from app.core import dnsctl

        status = self.context.status
        tunnels = self.context.tunnels
        dns_preset = dnsctl.current_preset()
        dns_on = dns_preset != "auto"
        dns_title = next(
            (item.title for item in dnsctl.PRESETS if item.key == dns_preset), ""
        )

        self.switch_zapret.blockSignals(True)
        self.switch_zapret.setChecked(status.running, animate=False)
        self.switch_zapret.blockSignals(False)

        self.rails.update_state(
            zapret_on=status.running,
            zapret_targets=["YouTube", "Discord"] if status.running else [],
            dns_on=dns_on,
            dns_note=dns_title,
            tunnels=tunnels,
            direct_note="остальное",
        )

        if tunnels and status.running:
            self.state_title.setText("Обход работает вместе с VPN")
            self.state_detail.setText(
                f"Поднят чужой туннель ({', '.join(tunnels)}). Через него "
                "трафик и так идёт в обход, а обход DPI может ему мешать — "
                "лучше выключить что-то одно."
            )
        elif tunnels:
            self.state_title.setText(f"Работает VPN — {', '.join(tunnels)}")
            self.state_detail.setText(
                "Трафик уходит в чужой туннель. Программа в это не вмешивается "
                "и ничего не выключает."
            )
        elif status.running and dns_on:
            self.state_title.setText("Работают обход и Smart DNS")
            self.state_detail.setText(
                "Сайты из списка открываются в обход блокировки, а DNS "
                "возвращает сервисы, закрытые по стране."
            )
        elif status.running:
            self.state_title.setText("Работает обход")
            self.state_detail.setText(
                "Discord, YouTube и сайты из списка открываются в обход блокировки."
            )
        elif dns_on:
            self.state_title.setText("Работает только Smart DNS")
            self.state_detail.setText(
                "Блокировку по стране обходим, но DPI провайдера — нет. "
                "Включите обход, если сайты всё ещё не открываются."
            )
        else:
            self.state_title.setText("Всё идёт напрямую")
            self.state_detail.setText(
                "Ничего не включено. Начните с обхода — он быстрее VPN и "
                "не требует подписки."
            )

        self._sync_tunnel_banner(tunnels, status.running)

        self.stat_zapret.set_value(status.mode_label if status.running else "выключен")
        self.stat_dns.set_value(dns_title if dns_on else "выключен")

        from app.core import strategies as strategies_module

        self.stat_filter.set_value(
            GAME_FILTER_LABELS.get(strategies_module.read_game_filter(), "—")
        )

        strategy = self.context.current_strategy()
        self.btn_strategy.setText(
            f"✦  {strategy.title}" if strategy else "✦  стратегия не выбрана"
        )
        self.dns_state.setText("включён" if dns_on else "выключен")
        self._refresh_uptime()

    def _sync_tunnel_banner(self, tunnels: list[str], zapret_on: bool) -> None:
        if not tunnels:
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
        self._sync_update_banner()

    def _sync_update_banner(self) -> None:
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

    # --- переключатель ---------------------------------------------------

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
        self.switch_zapret.setEnabled(False)

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
        self.switch_zapret.setEnabled(True)
        self.context.refresh_status(force=True)
        (self.context.error if error else self.context.ok)(message)

    # --- проверка --------------------------------------------------------

    def _run_check(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        clear_layout(self.check_results)

        self.btn_check.setEnabled(False)
        self.check_spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._check_ready)
        worker.failed.connect(self._check_failed)
        worker.run(autotest.quick_check)
        self._check_worker = worker

    def _check_failed(self, message: str) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(message)

    def _check_ready(self, results) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        # Чистим здесь тоже: иначе повторный показ результатов наложился бы
        # на предыдущий, если отрисовку вызвали в обход кнопки.
        clear_layout(self.check_results)
        from app.ui.widgets import IconLabel

        for item in results:
            # Каждая строка — отдельный виджет, а не вложенная компоновка:
            # компоновки при очистке не удалялись и наезжали друг на друга.
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

        failed = [item for item in results if not item.ok]
        if not failed:
            self.context.ok("Все адреса открываются")
        else:
            self.context.warn(f"Не открылось адресов: {len(failed)}")

    # --- тема ------------------------------------------------------------

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.spinner.set_color(accent)
        self.check_spinner.set_color(accent)
        self.switch_zapret.set_colors(
            self.context.color("lane_zapret"),
            self.context.color("border_strong"),
            self.context.color("surface"),
        )
        self.rails.apply_theme()
        self._refresh()
