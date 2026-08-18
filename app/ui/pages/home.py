"""Главная страница: схема маршрутов и два выключателя."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
from app.core.engine import MODE_PROCESS, MODE_SERVICE, engine
from app.core.vpn import apps as apps_module
from app.core.vpn import config as vpn_config
from app.core.vpn import integration
from app.core.vpn.engine import vpn_engine
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
            "Маршруты",
            "Три пути наружу. Напрямую идёт всё, что не отправлено в туннель, "
            "и там его подхватывает zapret.",
            parent,
        )
        self._busy_zapret = False
        self._busy_vpn = False
        self._check_worker = None

        self._build_banners()
        self._build_rails()
        self._build_controls()
        self._build_stats()

        context.status_changed.connect(lambda _: self._refresh())
        context.vpn_status_changed.connect(lambda _: self._refresh())
        context.servers_changed.connect(self._reload_servers)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_uptime)
        self._tick.start(1000)

        self.apply_theme()

    # --- построение ------------------------------------------------------

    def _build_banners(self) -> None:
        self.banner_admin = Banner(
            self.context, "warning",
            "Программа запущена без прав администратора — ни zapret, ни VPN "
            "не смогут работать. Перезапустите её от имени администратора.",
            kind="error",
        )
        self.body.addWidget(self.banner_admin)
        self.banner_admin.setVisible(not winapi.is_admin())

        self.banner_foreign = Banner(
            self.context, "globe",
            "", kind="warn",
        )
        self.body.addWidget(self.banner_foreign)
        self.banner_foreign.setVisible(False)

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
        row = QHBoxLayout()
        row.setSpacing(16)

        # --- zapret ---
        zapret_card = Card(padding=20, spacing=13)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.zapret_title = section_label("Zapret")
        head.addWidget(self.zapret_title)
        head.addStretch(1)
        self.switch_zapret = Switch(False)
        self.switch_zapret.toggled.connect(self._toggle_zapret)
        head.addWidget(self.switch_zapret)
        zapret_card.add_layout(head)

        zapret_card.add(faint_label(
            "Ломает распознавание домена у провайдера. Работает для всей "
            "системы сразу, выбирать программы не нужно."
        ))

        self.strategy_box = QComboBox()
        self.strategy_box.currentIndexChanged.connect(self._strategy_picked)
        zapret_card.add(self.strategy_box)

        self.mode_box = QComboBox()
        self.mode_box.addItem("Служба Windows", MODE_SERVICE)
        self.mode_box.addItem("Процесс", MODE_PROCESS)
        self.mode_box.currentIndexChanged.connect(
            lambda: config.set("run_mode", self.mode_box.currentData())
        )
        zapret_card.add(self.mode_box)
        row.addWidget(zapret_card, 1)

        # --- vpn ---
        vpn_card = Card(padding=20, spacing=13)
        head_vpn = QHBoxLayout()
        head_vpn.setSpacing(10)
        self.vpn_title = section_label("VPN")
        head_vpn.addWidget(self.vpn_title)
        head_vpn.addStretch(1)
        self.switch_vpn = Switch(False)
        self.switch_vpn.toggled.connect(self._toggle_vpn)
        head_vpn.addWidget(self.switch_vpn)
        vpn_card.add_layout(head_vpn)

        vpn_card.add(faint_label(
            "Уводит трафик в туннель. Можно включить только для выбранных "
            "программ — остальные останутся на zapret."
        ))

        self.server_box = QComboBox()
        self.server_box.currentIndexChanged.connect(self._server_picked)
        vpn_card.add(self.server_box)

        self.vpn_mode_box = QComboBox()
        for key, label in vpn_config.MODE_LABELS.items():
            self.vpn_mode_box.addItem(label, key)
        self.vpn_mode_box.currentIndexChanged.connect(
            lambda: config.set("vpn_mode", self.vpn_mode_box.currentData())
        )
        vpn_card.add(self.vpn_mode_box)
        row.addWidget(vpn_card, 1)

        self.body.addLayout(row)

    def _build_stats(self) -> None:
        card = Card(padding=20, spacing=14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        self.stat_zapret = StatItem("Zapret", "выключен")
        self.stat_vpn = StatItem("VPN", "выключен")
        self.stat_server = StatItem("Сервер", "—")
        self.stat_uptime = StatItem("Время работы", "—")
        for column, item in enumerate(
            (self.stat_zapret, self.stat_vpn, self.stat_server, self.stat_uptime)
        ):
            grid.addWidget(item, 0, column)
        grid.setColumnStretch(4, 1)
        card.add_layout(grid)

        card.add(Divider())

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        actions.addWidget(self.check_spinner)
        self.btn_check = Button("Проверить доступность", variant="soft")
        self.btn_check.clicked.connect(self._run_check)
        actions.addWidget(self.btn_check)
        self.btn_apps = Button("Настроить приложения", variant="ghost")
        self.btn_apps.clicked.connect(lambda: self.context.navigate.emit("vpnapps"))
        actions.addWidget(self.btn_apps)
        actions.addStretch(1)
        card.add_layout(actions)

        self.check_results = QVBoxLayout()
        self.check_results.setSpacing(6)
        card.add_layout(self.check_results)

        self.body.addWidget(card)

    # --- состояние -------------------------------------------------------

    def on_activate(self) -> None:
        self._reload_strategies()
        self._reload_servers()
        self.context.refresh_status(force=True)
        self.context.refresh_vpn_status(force=True)
        self._check_foreign_tunnel()

    def _check_foreign_tunnel(self) -> None:
        foreign = vpn_engine.foreign_tunnel_pids()
        if not foreign:
            self.banner_foreign.setVisible(False)
            return
        self.banner_foreign.set_text(
            "Другая программа уже держит VPN-туннель (например, Happ). "
            "Два туннеля одновременно конфликтуют — отключите её, прежде чем "
            "включать VPN здесь. Чужой процесс программа не трогает."
        )
        self.banner_foreign.setVisible(True)

    def _reload_strategies(self) -> None:
        items = self.context.load_strategies()
        current = str(config.get("last_strategy"))
        self.strategy_box.blockSignals(True)
        self.strategy_box.clear()
        for strategy in items:
            label = strategy.title
            if strategy.badge:
                label = f"{strategy.title}  ·  {strategy.badge}"
            self.strategy_box.addItem(label, strategy.id)
        index = self.strategy_box.findData(current)
        if index >= 0:
            self.strategy_box.setCurrentIndex(index)
        self.strategy_box.blockSignals(False)

        mode_index = self.mode_box.findData(str(config.get("run_mode")))
        if mode_index >= 0:
            self.mode_box.blockSignals(True)
            self.mode_box.setCurrentIndex(mode_index)
            self.mode_box.blockSignals(False)

    def _reload_servers(self) -> None:
        servers = self.context.servers()
        chosen = self.context.selected_server()
        self.server_box.blockSignals(True)
        self.server_box.clear()
        if not servers:
            self.server_box.addItem("Подписка не настроена", "")
            self.server_box.setEnabled(False)
        else:
            self.server_box.setEnabled(True)
            for server in servers:
                self.server_box.addItem(server.name, server.name)
            index = self.server_box.findData(chosen)
            if index >= 0:
                self.server_box.setCurrentIndex(index)
        self.server_box.blockSignals(False)

        mode_index = self.vpn_mode_box.findData(str(config.get("vpn_mode")))
        if mode_index >= 0:
            self.vpn_mode_box.blockSignals(True)
            self.vpn_mode_box.setCurrentIndex(mode_index)
            self.vpn_mode_box.blockSignals(False)

    def _strategy_picked(self) -> None:
        value = self.strategy_box.currentData()
        if value:
            config.set("last_strategy", value)

    def _server_picked(self) -> None:
        value = self.server_box.currentData()
        if value:
            config.set("vpn_selected_server", value)

    def _lane_clicked(self, key: str) -> None:
        if key == "vpn":
            self.context.navigate.emit("servers")
        elif key == "zapret":
            self.context.navigate.emit("strategies")

    def _refresh(self) -> None:
        status = self.context.status
        vpn = self.context.vpn_status

        self.switch_zapret.blockSignals(True)
        self.switch_zapret.setChecked(status.running, animate=False)
        self.switch_zapret.blockSignals(False)
        self.switch_vpn.blockSignals(True)
        self.switch_vpn.setChecked(vpn.running, animate=False)
        self.switch_vpn.blockSignals(False)

        mode = str(config.get("vpn_mode", vpn_config.MODE_SELECTED))
        if mode == vpn_config.MODE_EXCEPT:
            vpn_apps = ["всё, кроме выбранных"]
        elif mode == vpn_config.MODE_ALL:
            vpn_apps = ["весь трафик"]
        else:
            names = list(config.get("vpn_apps", []) or [])
            vpn_apps = [apps_module._pretty_name(name) for name in names[:3]] or ["никто"]

        self.rails.update_state(
            zapret_on=status.running,
            vpn_on=vpn.running,
            vpn_apps=vpn_apps if vpn.running else [],
            zapret_targets=["YouTube", "Discord"] if status.running else [],
            direct_note="остальное",
        )

        if status.running and vpn.running:
            self.state_title.setText("Работают zapret и VPN")
            self.state_detail.setText(
                "Выбранные программы идут через туннель, остальные — напрямую "
                "с обходом DPI."
            )
        elif vpn.running:
            self.state_title.setText("Работает VPN")
            self.state_detail.setText("Трафик уходит в туннель по вашим правилам.")
        elif status.running:
            self.state_title.setText("Работает zapret")
            self.state_detail.setText(
                "Discord, YouTube и сайты из списка открываются в обход блокировки."
            )
        else:
            self.state_title.setText("Всё идёт напрямую")
            self.state_detail.setText(
                "Ничего не включено. Начните с zapret — он быстрее и не требует подписки."
            )

        self.stat_zapret.set_value(status.mode_label if status.running else "выключен")
        self.stat_vpn.set_value(
            vpn_config.MODE_LABELS.get(vpn.mode, "включён") if vpn.running else "выключен"
        )
        self.stat_server.set_value(
            (vpn.server or self.context.selected_server() or "—") if vpn.running else "—"
        )
        self._refresh_uptime()

    def _refresh_uptime(self) -> None:
        seconds = max(engine.uptime_seconds(), vpn_engine.uptime_seconds())
        if not seconds:
            self.stat_uptime.set_value("—")
            return
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        self.stat_uptime.set_value(
            f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        )

    # --- переключатели ---------------------------------------------------

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
            mode = str(self.mode_box.currentData() or config.get("run_mode"))
            worker = Worker(self)
            worker.finished.connect(
                lambda _: self._zapret_done(f"Zapret включён — «{strategy.title}»")
            )
            worker.failed.connect(lambda msg: self._zapret_done(msg, error=True))
            worker.run(engine.start, strategy, mode)
        else:
            worker = Worker(self)
            worker.finished.connect(lambda _: self._zapret_done("Zapret выключен"))
            worker.failed.connect(lambda msg: self._zapret_done(msg, error=True))
            worker.run(engine.stop)
        self._zapret_worker = worker

    def _zapret_done(self, message: str, error: bool = False) -> None:
        self._busy_zapret = False
        self.spinner.stop()
        self.switch_zapret.setEnabled(True)
        self.context.refresh_status(force=True)
        (self.context.error if error else self.context.ok)(message)

    def _toggle_vpn(self, value: bool) -> None:
        if self._busy_vpn:
            return
        self._busy_vpn = True
        self.spinner.start()
        self.switch_vpn.setEnabled(False)

        if value:
            servers = self.context.servers()
            if not servers:
                self._vpn_done(
                    "Сначала добавьте подписку на вкладке «Серверы».", error=True
                )
                self.context.navigate.emit("servers")
                return
            selected = self.context.selected_server()
            mode = str(config.get("vpn_mode", vpn_config.MODE_SELECTED))
            vpn_apps = list(config.get("vpn_apps", []) or [])
            direct_apps = list(config.get("vpn_direct_apps", []) or [])
            stack = str(config.get("vpn_stack", vpn_config.STACK_DEFAULT))
            auto_exclude = bool(config.get("vpn_auto_exclude", True))

            def job():
                # Иначе zapret порежет трафик до самого VPN-сервера.
                if auto_exclude:
                    integration.sync_excludes(servers)
                vpn_engine.start(servers, selected, mode, vpn_apps, direct_apps, stack)

            worker = Worker(self)
            worker.finished.connect(lambda _: self._vpn_done("VPN включён"))
            worker.failed.connect(lambda msg: self._vpn_done(msg, error=True))
            worker.run(job)
        else:
            worker = Worker(self)
            worker.finished.connect(lambda _: self._vpn_done("VPN выключен"))
            worker.failed.connect(lambda msg: self._vpn_done(msg, error=True))
            worker.run(vpn_engine.stop)
        self._vpn_worker = worker

    def _vpn_done(self, message: str, error: bool = False) -> None:
        self._busy_vpn = False
        self.spinner.stop()
        self.switch_vpn.setEnabled(True)
        self.context.refresh_vpn_status(force=True)
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
        self.switch_vpn.set_colors(
            self.context.color("lane_vpn"),
            self.context.color("border_strong"),
            self.context.color("surface"),
        )
        self.rails.apply_theme()
        self._refresh()
