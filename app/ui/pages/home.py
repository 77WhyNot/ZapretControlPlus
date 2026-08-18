"""Главная страница: схема маршрутов и два выключателя."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QMessageBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.core import autotest, winapi
from app.core.config import config
from app.core.engine import MODE_PROCESS, MODE_SERVICE, engine
from app.core.strategies import GAME_FILTER_LABELS
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
        self._build_tunnel()
        self._build_dns()
        self._build_filters()
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
        """Два выключателя. Под каждым — что выбрано, и это же кнопка перехода."""
        row = QHBoxLayout()
        row.setSpacing(16)

        # --- zapret ---
        zapret_card = Card(padding=20, spacing=12)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(section_label("Zapret"))
        head.addStretch(1)
        self.switch_zapret = Switch(False)
        self.switch_zapret.toggled.connect(self._toggle_zapret)
        head.addWidget(self.switch_zapret)
        zapret_card.add_layout(head)

        zapret_card.add(faint_label(
            "Ломает распознавание домена у провайдера. Работает сразу для "
            "всей системы, выбирать программы не нужно."
        ))

        self.btn_strategy = Button("Основная")
        self.btn_strategy.clicked.connect(
            lambda: self.context.navigate.emit("strategies")
        )
        zapret_card.add(self.btn_strategy)
        row.addWidget(zapret_card, 1)

        # --- vpn ---
        vpn_card = Card(padding=20, spacing=12)
        head_vpn = QHBoxLayout()
        head_vpn.setSpacing(10)
        head_vpn.addWidget(section_label("VPN"))
        head_vpn.addStretch(1)
        self.switch_vpn = Switch(False)
        self.switch_vpn.toggled.connect(self._toggle_vpn)
        head_vpn.addWidget(self.switch_vpn)
        vpn_card.add_layout(head_vpn)

        vpn_card.add(faint_label(
            "Уводит в туннель только выбранные программы. Остальные остаются "
            "на zapret."
        ))

        self.btn_server = Button("Подписка не настроена")
        self.btn_server.clicked.connect(lambda: self.context.navigate.emit("servers"))
        vpn_card.add(self.btn_server)
        row.addWidget(vpn_card, 1)

        self.body.addLayout(row)

    def _build_tunnel(self) -> None:
        """Состав туннеля виден сразу, менять — не уходя со страницы."""
        card = Card(padding=16, spacing=10)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.tunnel_caption = faint_label("В туннеле", wrap=False)
        header.addWidget(self.tunnel_caption)
        header.addStretch(1)
        self.btn_edit_apps = Button("Изменить", variant="ghost")
        self.btn_edit_apps.clicked.connect(
            lambda: self.context.navigate.emit("vpnapps")
        )
        header.addWidget(self.btn_edit_apps)
        card.add_layout(header)

        self.tunnel_host = QWidget()
        self.tunnel_row = QHBoxLayout(self.tunnel_host)
        self.tunnel_row.setContentsMargins(0, 0, 0, 0)
        self.tunnel_row.setSpacing(7)
        card.add(self.tunnel_host)

        self.body.addWidget(card)

    def _refresh_tunnel(self) -> None:
        from app.ui.appicons import app_pixmap
        from app.ui.widgets import clear_layout

        clear_layout(self.tunnel_row)
        mode = str(config.get("vpn_mode", vpn_config.MODE_SELECTED))

        if mode == vpn_config.MODE_ALL:
            self.tunnel_caption.setText("В туннеле")
            self.tunnel_row.addWidget(faint_label("весь трафик", wrap=False))
            self.tunnel_row.addStretch(1)
            return

        key = "vpn_direct_apps" if mode == vpn_config.MODE_EXCEPT else "vpn_apps"
        self.tunnel_caption.setText(
            "Мимо туннеля" if mode == vpn_config.MODE_EXCEPT else "В туннеле"
        )
        names = list(config.get(key, []) or [])

        if not names:
            self.tunnel_row.addWidget(faint_label(
                "программы не выбраны — нажмите «Изменить»", wrap=False
            ))
            self.tunnel_row.addStretch(1)
            return

        ratio = self.devicePixelRatioF() or 1.0
        for name in names[:6]:
            chip = QWidget(self.tunnel_host)
            line = QHBoxLayout(chip)
            line.setContentsMargins(7, 4, 10, 4)
            line.setSpacing(7)

            icon = QLabel(chip)
            icon.setFixedSize(18, 18)
            icon.setPixmap(app_pixmap(
                apps_module.resolve_executable(name),
                apps_module._pretty_name(name), 18, ratio,
            ))
            line.addWidget(icon)
            title = QLabel(apps_module._pretty_name(name), chip)
            title.setStyleSheet("font-size: 12px;")
            line.addWidget(title)

            chip.setStyleSheet(
                f"background: {self.context.color('surface_alt')};"
                f"border: 1px solid {self.context.color('border')};"
                "border-radius: 8px;"
            )
            self.tunnel_row.addWidget(chip)

        if len(names) > 6:
            self.tunnel_row.addWidget(faint_label(f"и ещё {len(names) - 6}", wrap=False))
        self.tunnel_row.addStretch(1)

    def _resolve_foreign_clients(self) -> bool:
        """Спросить и закрыть чужие VPN-клиенты. False — пользователь отказался."""
        from app.core.vpn import clients as vpn_clients

        found = vpn_clients.running_clients()
        if not found:
            return True

        names = ", ".join(item.title for item in found)
        answer = QMessageBox.question(
            self, "Другой VPN уже работает",
            f"Запущены: {names}." + LINE_BREAK * 2
            + "Два туннеля одновременно не работают — они делят один сетевой "
              "адаптер, и наш просто не поднимется." + LINE_BREAK * 2
            + "Закрыть их и продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        message = vpn_clients.stop_all(found)
        self.context.ok(message)
        QTimer.singleShot(0, lambda: None)
        import time as _time

        _time.sleep(1.5)
        return True

    def _build_dns(self) -> None:
        """Третий инструмент рядом с двумя другими, а не в глубине меню."""
        from app.core import dnsctl
        from app.ui.widgets import SettingRow

        card = Card(padding=18, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Smart DNS"))
        header.addStretch(1)
        self.dns_details = Button("Подробнее", variant="ghost")
        self.dns_details.clicked.connect(lambda: self.context.navigate.emit("dns"))
        header.addWidget(self.dns_details)
        card.add_layout(header)

        self.dns_box = QComboBox()
        for preset in dnsctl.PRESETS:
            self.dns_box.addItem(preset.title, preset.key)
        self.dns_box.currentIndexChanged.connect(self._change_dns)
        card.add(SettingRow(
            "Сервис DNS",
            "Третий способ разблокировки: возвращает доступ к Xbox Live, "
            "Game Pass и сервисам, которые режут по стране. Работает вместе "
            "с zapret и не мешает VPN.",
            self.dns_box,
        ))

        self.body.addWidget(card)
        self._sync_dns()

    def _sync_dns(self) -> None:
        from app.core import dnsctl

        self.dns_box.blockSignals(True)
        index = self.dns_box.findData(dnsctl.current_preset())
        if index >= 0:
            self.dns_box.setCurrentIndex(index)
        self.dns_box.blockSignals(False)

    def _change_dns(self) -> None:
        from app.core import dnsctl
        from app.ui.widgets import Worker

        key = str(self.dns_box.currentData())
        worker = Worker(self)
        worker.finished.connect(lambda message: self.context.ok(str(message)))
        worker.failed.connect(lambda message: self.context.error(str(message)))
        worker.run(dnsctl.apply_preset, key)
        self._dns_worker = worker

    def _check_vpn_exit(self) -> None:
        """Показать, каким адресом нас видит мир через туннель."""
        from app.core.vpn.engine import vpn_engine
        from app.ui.widgets import Worker

        if not self.context.vpn_status.running:
            self.context.warn("VPN выключен — проверять нечего.")
            return

        self.btn_vpn_check.setEnabled(False)
        self.check_spinner.start()

        def job():
            return vpn_engine.exit_address(), vpn_engine.direct_address()

        worker = Worker(self)
        worker.finished.connect(self._show_exit)
        worker.failed.connect(self._exit_failed)
        worker.run(job)
        self._exit_worker = worker

    def _exit_failed(self, message: str) -> None:
        self.btn_vpn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(message)

    def _show_exit(self, payload) -> None:
        through, direct = payload
        self.btn_vpn_check.setEnabled(True)
        self.check_spinner.stop()

        same = through.get("ip") == direct.get("ip")
        where = through.get("country", "?")
        city = through.get("city") or ""
        place = f"{where}, {city}" if city else where

        if same:
            self.context.error(
                f"Туннель не работает: мир видит тот же адрес {through['ip']} "
                f"({place}), что и без VPN. Смените сервер."
            )
        else:
            self.context.ok(
                f"VPN работает: снаружи вас видят как {through['ip']} — {place}. "
                f"Без туннеля было бы {direct.get('ip', '?')} "
                f"({direct.get('country', '?')})."
            )

    def _build_filters(self) -> None:
        """Игровой фильтр и IPSet — те же два переключателя, что в меню zapret."""
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
        self.stat_zapret = StatItem("Zapret", "выключен")
        self.stat_vpn = StatItem("VPN", "выключен")
        self.stat_subscription = StatItem("Подписка", "—")
        self.stat_uptime = StatItem("Время работы", "—")
        for column, item in enumerate((
            self.stat_zapret, self.stat_vpn, self.stat_subscription, self.stat_uptime
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
        self.btn_vpn_check = Button("Проверить VPN")
        self.btn_vpn_check.clicked.connect(self._check_vpn_exit)
        actions.addWidget(self.btn_vpn_check)
        self.btn_diag = Button("Диагностика")
        self.btn_diag.clicked.connect(
            lambda: self.context.navigate.emit("diagnostics")
        )
        actions.addWidget(self.btn_diag)
        self.btn_restart = Button("Перезапустить", variant="ghost")
        self.btn_restart.clicked.connect(self._restart_all)
        actions.addWidget(self.btn_restart)
        actions.addStretch(1)
        card.add_layout(actions)

        self.check_results = QVBoxLayout()
        self.check_results.setSpacing(6)
        card.add_layout(self.check_results)

        self.body.addWidget(card)

    def _restart_all(self) -> None:
        """Перезапустить то, что сейчас включено."""
        status = self.context.status
        vpn = self.context.vpn_status
        if not status.running and not vpn.running:
            self.context.warn("Нечего перезапускать — ничего не включено.")
            return
        if status.running:
            self.switch_zapret.setChecked(False, animate=False)
            self._toggle_zapret(False)
            QTimer.singleShot(1200, lambda: self._toggle_zapret(True))
        if vpn.running:
            QTimer.singleShot(2400, lambda: self._toggle_vpn(False))
            QTimer.singleShot(3600, lambda: self._toggle_vpn(True))

    # --- состояние -------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_dns()
        self._sync_filters()
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
        # Списки выбора переехали на свои страницы — здесь только показ.
        self._refresh()

    def _reload_servers(self) -> None:
        self._refresh()

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

        strategy = self.context.current_strategy()
        self.btn_strategy.setText(
            f"✦  {strategy.title}" if strategy else "✦  стратегия не выбрана"
        )
        server = self.context.selected_server()
        servers = self.context.servers()
        if servers:
            self.btn_server.setText(f"⇄  {server or servers[0].name}   ·   {len(servers)} серверов")
        else:
            self.btn_server.setText("⇄  подписка не настроена")

        from app.core.vpn import subscription as sub
        _, info = sub.load_cached()
        days = info.days_left
        if not servers:
            self.stat_subscription.set_value("—")
        elif days is None:
            self.stat_subscription.set_value("бессрочная")
        else:
            self.stat_subscription.set_value(f"{days} дн.")

        self._refresh_tunnel()
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
            mode = str(config.get("run_mode"))
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
            # Чужой туннель займёт адаптер, и наш просто не поднимется.
            if not self._resolve_foreign_clients():
                self._vpn_done("Запуск отменён", error=False)
                return
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
