"""Страница стратегий: список, ручной запуск и автоподбор."""

from __future__ import annotations

import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.core import autotest, strategies as strategies_module
from app.core.config import config
from app.core.engine import MODE_PROCESS, MODE_SERVICE, engine
from app.core.strategies import GAME_FILTER_LABELS, Strategy
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    clear_layout,
    Badge,
    Button,
    Card,
    Collapsible,
    Divider,
    IconLabel,
    Spinner,
    Worker,
    faint_label,
    section_label,
)


class ArgumentsDialog(QDialog):
    """Показывает итоговую командную строку winws.exe."""

    def __init__(self, context: AppContext, strategy: Strategy,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Аргументы — {strategy.title}")
        self.resize(880, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(faint_label(
            "Именно эта команда запускается при включении обхода. "
            "Её же приложение прописывает в службу Windows."
        ))

        view = QPlainTextEdit()
        view.setReadOnly(True)
        command = strategies_module.build_command_line(strategy)
        view.setPlainText("\n".join(textwrap.wrap(command, 130)))
        layout.addWidget(view, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        copy_button = Button("Скопировать", variant="soft")
        copy_button.clicked.connect(lambda: self._copy(command))
        buttons.addWidget(copy_button)
        close_button = Button("Закрыть")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.context = context

    def _copy(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self.context.ok("Команда скопирована в буфер обмена")


class StrategyRow(QWidget):
    """Одна строка в списке стратегий."""

    def __init__(self, context: AppContext, strategy: Strategy,
                 page: "StrategiesPage", parent: QWidget | None = None) -> None:
        # Родителя передаём сразу: виджет без родителя до вставки в
        # компоновку считается окном и может мигнуть на экране.
        super().__init__(parent)
        self.context = context
        self.strategy = strategy
        self.page = page

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.marker = IconLabel("layers", context.color("text_faint"), 18)
        layout.addWidget(self.marker, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel(strategy.title)
        self.title.setStyleSheet("font-weight: 600; font-size: 14px;")
        title_row.addWidget(self.title)

        if strategy.badge:
            kind = {
                "рекомендуется": "ok",
                "не рекомендуется": "warn",
                "эксперимент": "accent",
            }.get(strategy.badge, "neutral")
            title_row.addWidget(Badge(strategy.badge, kind))

        self.running_badge = Badge("сейчас работает", "accent")
        self.running_badge.setVisible(False)
        title_row.addWidget(self.running_badge)
        title_row.addStretch(1)
        text_box.addLayout(title_row)

        if strategy.hint:
            text_box.addWidget(faint_label(strategy.hint))
        text_box.addWidget(faint_label(strategy.subtitle))
        layout.addLayout(text_box, 1)

        self.btn_args = Button("Аргументы", variant="ghost")
        self.btn_args.clicked.connect(self._show_args)
        layout.addWidget(self.btn_args, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_run = Button("Запустить", variant="soft")
        self.btn_run.clicked.connect(lambda: self.page.run_strategy(self.strategy))
        layout.addWidget(self.btn_run, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme()

    def apply_theme(self) -> None:
        self.marker.set_color(self.context.color("text_faint"))

    def set_running(self, running: bool) -> None:
        self.running_badge.setVisible(running)
        self.marker.set_icon("shield_check" if running else "layers")
        self.marker.set_color(
            self.context.color("success") if running else self.context.color("text_faint")
        )
        self.btn_run.setText("Перезапустить" if running else "Запустить")

    def _show_args(self) -> None:
        dialog = ArgumentsDialog(self.context, self.strategy, self)
        dialog.exec()


class StrategiesPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Запрет",
            "Обход блокировок DPI. Стратегия — набор приёмов обмана провайдера: "
            "у разных провайдеров работают разные, поэтому их много.",
            parent,
        )
        self._rows: list[StrategyRow] = []
        self._rows_signature: tuple = ()
        self._tester: autotest.AutoTester | None = None
        self._auto_worker: Worker | None = None
        self._busy = False

        self._build_current()
        self._build_autopick()
        self._build_filters()
        self._build_discord()
        self._build_list()

        context.status_changed.connect(lambda _: self._mark_running())
        context.strategies_changed.connect(self._reload_current)
        self.apply_theme()

    # --- текущая стратегия ------------------------------------------------

    def _build_current(self) -> None:
        card = Card(padding=20, spacing=13)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.current_icon = IconLabel("shield_check", self.context.color("accent"), 20)
        header.addWidget(self.current_icon)
        header.addWidget(section_label("Стратегия"))
        header.addStretch(1)
        self.current_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.current_spinner)
        self.current_badge = Badge("выключен", "neutral")
        header.addWidget(self.current_badge)
        card.add_layout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.current_box = QComboBox()
        # Длинные названия стратегий не должны распирать окно: список сам
        # сжимается, а в раскрытом виде показывает названия целиком.
        self.current_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.current_box.setMinimumContentsLength(14)
        self.current_box.setMinimumWidth(170)
        row.addWidget(self.current_box, 1)
        self.btn_current_args = Button("Аргументы", variant="ghost")
        self.btn_current_args.clicked.connect(self._show_current_args)
        row.addWidget(self.btn_current_args)
        self.btn_current_run = Button("Запустить", variant="primary")
        self.btn_current_run.clicked.connect(self._apply_current)
        row.addWidget(self.btn_current_run)
        self.btn_current_stop = Button("Остановить", variant="soft")
        self.btn_current_stop.clicked.connect(self._stop_current)
        row.addWidget(self.btn_current_stop)
        card.add_layout(row)

        self.current_hint = faint_label("")
        card.add(self.current_hint)
        card.add(Divider())

        from app.ui.widgets import SettingRow

        self.mode_box = QComboBox()
        self.mode_box.addItem("Служба Windows — работает всегда", MODE_SERVICE)
        self.mode_box.addItem("Процесс — пока открыта программа", MODE_PROCESS)
        self.mode_box.currentIndexChanged.connect(self._mode_changed)
        card.add(SettingRow(
            "Режим работы",
            "Служба продолжает обход и после закрытия программы, и после "
            "перезагрузки. Процесс живёт, только пока открыта программа.",
            self.mode_box,
        ))

        self.body.addWidget(card)
        self._reload_current()

    def _reload_current(self) -> None:
        items = self.context.load_strategies()
        current = self.context.current_strategy()
        self.current_box.blockSignals(True)
        self.current_box.clear()
        for item in items:
            label = item.title + (f" — {item.badge}" if item.badge else "")
            self.current_box.addItem(label, item.id)
        if current is not None:
            index = self.current_box.findData(current.id)
            if index >= 0:
                self.current_box.setCurrentIndex(index)
        self.current_box.blockSignals(False)

        self.mode_box.blockSignals(True)
        index = self.mode_box.findData(str(config.get("run_mode", MODE_SERVICE)))
        if index >= 0:
            self.mode_box.setCurrentIndex(index)
        self.mode_box.blockSignals(False)
        self._sync_current()

    def _selected_strategy(self) -> Strategy | None:
        wanted = str(self.current_box.currentData() or "")
        return next((item for item in self.context.load_strategies()
                     if item.id == wanted), None)

    def _sync_current(self) -> None:
        status = self.context.status
        running = status.running
        self.current_badge.update_state(
            f"работает · {status.mode_label}" if running else "выключен",
            "ok" if running else "neutral",
        )
        self.btn_current_run.setText("Перезапустить" if running else "Запустить")
        self.btn_current_stop.setEnabled(running and not self._busy)
        self.btn_current_run.setEnabled(not self._busy)
        active = next((item for item in self.context.load_strategies()
                       if item.id == status.strategy_id), None)
        self.current_hint.setText(
            f"Сейчас работает «{active.title}»." if running and active else
            "Выберите стратегию и нажмите «Запустить». Не знаете какую — "
            "нажмите «Подобрать» ниже, программа проверит их сама."
        )

    def _apply_current(self) -> None:
        strategy = self._selected_strategy()
        if strategy is None:
            self.context.error("Стратегия не найдена.")
            return
        self.run_strategy(strategy)

    def _stop_current(self) -> None:
        self._busy = True
        self.current_spinner.start()
        self._sync_current()
        worker = Worker(self)
        worker.finished.connect(lambda _: self._current_done("Обход выключен"))
        worker.failed.connect(lambda message: self._current_done(message, error=True))
        worker.run(engine.stop)
        self._stop_worker = worker

    def _current_done(self, message: str, error: bool = False) -> None:
        self._busy = False
        self.current_spinner.stop()
        self.context.refresh_status(force=True)
        self._sync_current()
        (self.context.error if error else self.context.ok)(message)

    def _show_current_args(self) -> None:
        strategy = self._selected_strategy()
        if strategy is not None:
            ArgumentsDialog(self.context, strategy, self).exec()

    def _mode_changed(self) -> None:
        mode = str(self.mode_box.currentData())
        config.set("run_mode", mode)
        label = "служба Windows" if mode == MODE_SERVICE else "процесс"
        if self.context.status.running:
            self.context.warn(f"Режим: {label}. Нажмите «Перезапустить», чтобы применить.")
        else:
            self.context.ok(f"Режим работы: {label}")

    # --- автоподбор ------------------------------------------------------

    def _build_autopick(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.auto_icon = IconLabel("bolt", self.context.color("accent"), 20)
        header.addWidget(self.auto_icon)
        header.addWidget(section_label("Автоподбор стратегии"))
        header.addStretch(1)
        self.auto_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.auto_spinner)

        self.auto_scope = QComboBox()
        self.auto_scope.addItem("Быстрый — 8 популярных", "quick")
        self.auto_scope.addItem("Полный — все стратегии", "full")
        header.addWidget(self.auto_scope)

        self.btn_auto = Button("Подобрать", variant="primary")
        self.btn_auto.clicked.connect(self._toggle_autopick)
        header.addWidget(self.btn_auto)
        card.add_layout(header)

        card.add(faint_label(
            "Программа выключит обход, посмотрит, какие адреса не открываются, "
            "и прогонит стратегии в два захода: сначала быстро по нескольким "
            "показательным адресам, затем лучших — по всему списку. "
            "Во время подбора связь будет прерываться — это нормально."
        ))

        self.auto_progress = QProgressBar()
        card.add(self.auto_progress)
        self.auto_progress.setVisible(False)

        self.auto_status = faint_label("")
        card.add(self.auto_status)
        self.auto_status.setVisible(False)

        self.auto_results = QWidget()
        self.auto_results_layout = QVBoxLayout(self.auto_results)
        self.auto_results_layout.setContentsMargins(0, 0, 0, 0)
        self.auto_results_layout.setSpacing(6)
        card.add(self.auto_results)

        self.body.addWidget(card)

    def _toggle_autopick(self) -> None:
        if self._tester is not None and not self._tester.cancelled:
            self._tester.cancel()
            self.auto_status.setText("Отмена… дождитесь завершения текущей проверки.")
            self.btn_auto.setEnabled(False)
            return
        self._start_autopick()

    def _start_autopick(self) -> None:
        self._clear_auto_results()
        tester = autotest.AutoTester()
        self._tester = tester

        all_strategies = self.context.load_strategies()
        if not all_strategies:
            self.context.error("Стратегии не найдены — проверьте вкладку «Обновления».")
            return
        scope = self.auto_scope.currentData()
        candidates = (
            autotest.shortlist(all_strategies) if scope == "quick" else all_strategies
        )

        self.btn_auto.setText("Отменить")
        self.auto_spinner.start()
        self.auto_progress.setVisible(True)
        self.auto_progress.setRange(0, len(candidates))
        self.auto_progress.setValue(0)
        self.auto_status.setVisible(True)
        self.auto_status.setText("Проверяем, что заблокировано…")

        worker = Worker(self)
        worker.progress.connect(self._auto_progress)
        worker.finished.connect(self._auto_finished)
        worker.failed.connect(self._auto_failed)

        def job():
            blocked, baseline = tester.find_blocked()
            if not blocked:
                return {"blocked": [], "scores": [], "baseline": baseline}
            worker.progress.emit(
                f"Не открывается адресов: {len(blocked)}. Подбираем стратегию…", 0
            )
            scores = tester.evaluate(
                candidates,
                blocked,
                mode=MODE_PROCESS,
                on_progress=lambda index, total, strategy, stage: worker.progress.emit(
                    f"[{index}/{total}] {strategy.title}"
                    if stage == autotest.STAGE_QUICK
                    else f"Полная проверка: {strategy.title}",
                    index,
                ),
            )
            return {"blocked": blocked, "scores": scores, "baseline": baseline}

        worker.run(job)
        self._auto_worker = worker

    def _auto_progress(self, text: str, value: int) -> None:
        self.auto_status.setText(text)
        if value:
            self.auto_progress.setValue(value)

    def _auto_failed(self, message: str) -> None:
        self._finish_autopick()
        self.context.error(f"Автоподбор прервался: {message}")

    def _finish_autopick(self) -> None:
        self.auto_spinner.stop()
        self.auto_progress.setVisible(False)
        self.btn_auto.setText("Подобрать")
        self.btn_auto.setEnabled(True)
        self._tester = None
        self.context.refresh_status(force=True)

    def _clear_auto_results(self) -> None:
        clear_layout(self.auto_results_layout)

    def _auto_finished(self, payload) -> None:
        self._finish_autopick()
        blocked = payload.get("blocked", [])
        scores = payload.get("scores", [])

        if not blocked:
            self.auto_status.setText(
                "Все проверяемые адреса открываются и без обхода. "
                "Возможно, включён VPN или провайдер вас не блокирует."
            )
            self.context.ok("Блокировок не обнаружено")
            return

        if not scores:
            self.auto_status.setText("Подбор отменён.")
            return

        best = scores[0]
        self.auto_status.setText(
            f"Проверено стратегий: {len(scores)}. Лучший результат — "
            f"«{best.strategy.title}» ({best.passed} из {best.total})."
        )

        for score in scores[:8]:
            self.auto_results_layout.addWidget(self._score_row(score))

        if best.passed == 0:
            self.context.warn(
                "Ни одна стратегия не открыла заблокированные адреса. "
                "Загляните в «Диагностику» — возможно, мешает другая программа."
            )
        else:
            self.context.ok(f"Лучшая стратегия: «{best.strategy.title}»")

    def _score_row(self, score: autotest.StrategyScore) -> QWidget:
        line = QWidget()
        layout = QHBoxLayout(line)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if score.error:
            kind, token, icon_name = "error", "danger", "cross"
        elif score.is_perfect:
            kind, token, icon_name = "ok", "success", "check"
        elif score.passed:
            kind, token, icon_name = "warn", "warning", "warning"
        else:
            kind, token, icon_name = "error", "danger", "cross"

        layout.addWidget(IconLabel(icon_name, self.context.color(token), 16))

        name = QLabel(score.strategy.title)
        name.setStyleSheet("font-weight: 600;")
        layout.addWidget(name)

        if score.error:
            layout.addWidget(faint_label("не запустилась"))
        else:
            layout.addWidget(Badge(f"{score.passed} из {score.total}", kind))
            if score.stage == autotest.STAGE_QUICK:
                layout.addWidget(Badge("быстрая проверка", "neutral"))
            if score.latency_ms:
                layout.addWidget(faint_label(f"{score.latency_ms:.0f} мс"))
        layout.addStretch(1)

        if not score.error and score.passed:
            apply_button = Button("Применить", variant="soft")
            apply_button.clicked.connect(
                lambda _=False, s=score.strategy: self.run_strategy(s)
            )
            layout.addWidget(apply_button)
        return line

    # --- фильтры ---------------------------------------------------------

    def _build_filters(self) -> None:
        from app.core import lists as lists_module
        from app.ui.widgets import SettingRow

        card = Card(padding=20, spacing=12)
        card.add(section_label("Фильтры"))

        self.game_box = QComboBox()
        for key, label in GAME_FILTER_LABELS.items():
            self.game_box.addItem(label.capitalize(), key)
        index = self.game_box.findData(self.context.current_game_filter())
        if index >= 0:
            self.game_box.setCurrentIndex(index)
        self.game_box.currentIndexChanged.connect(self._change_game_filter)
        card.add(SettingRow(
            "Игровой фильтр",
            "Расширяет обход на порты 1024–65535, чтобы работали игры и голосовые "
            "сервисы. Нагрузка растёт, часть программ может сбоить — включайте, "
            "только если без него игры не работают.",
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
        self.filters_hint = faint_label("")
        restart_row.addWidget(self.filters_hint, 1)
        self.btn_restart = Button("Перезапустить обход", variant="ghost")
        self.btn_restart.clicked.connect(self._restart_bypass)
        restart_row.addWidget(self.btn_restart)
        card.add_layout(restart_row)

        self.body.addWidget(card)
        self._sync_filters()

    def _sync_filters(self) -> None:
        from app.core import lists as lists_module

        self.game_box.blockSignals(True)
        index = self.game_box.findData(self.context.current_game_filter())
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
        status = self.context.status
        if not status.running:
            self.context.warn("Обход не запущен — нечего перезапускать.")
            return
        strategy = self.context.current_strategy()
        if strategy is not None:
            self.run_strategy(strategy)

    # --- Discord ---------------------------------------------------------

    def _build_discord(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Discord"))
        header.addStretch(1)
        self.discord_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.discord_spinner)
        card.add_layout(header)

        card.add(faint_label(
            "Discord держит адреса голосовых серверов в кэше и после смены "
            "стратегии продолжает стучаться по старым. Перезапуск с очисткой кэша "
            "чаще всего и чинит неработающий голос."
        ))

        from app.core import diagnostics as diag

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_discord_restart = Button("Перезапустить Discord", variant="soft")
        self.btn_discord_restart.clicked.connect(
            lambda: self._run_discord(diag.restart_discord_clean, self.btn_discord_restart)
        )
        row.addWidget(self.btn_discord_restart)
        self.btn_discord_cache = Button("Очистить кэш Discord", variant="ghost")
        self.btn_discord_cache.clicked.connect(
            lambda: self._run_discord(diag.clear_discord_cache, self.btn_discord_cache)
        )
        row.addWidget(self.btn_discord_cache)
        self.btn_discord_start = Button("Запустить Discord", variant="ghost")
        self.btn_discord_start.clicked.connect(
            lambda: self._run_discord(diag.launch_discord, self.btn_discord_start)
        )
        row.addWidget(self.btn_discord_start)
        row.addStretch(1)
        card.add_layout(row)

        self.body.addWidget(card)

    def _run_discord(self, function, button) -> None:
        button.setEnabled(False)
        self.discord_spinner.start()

        def done(message: str, error: bool = False) -> None:
            button.setEnabled(True)
            self.discord_spinner.stop()
            (self.context.error if error else self.context.ok)(message)

        worker = Worker(self)
        worker.finished.connect(lambda result: done(str(result)))
        worker.failed.connect(lambda message: done(message, True))
        worker.run(function)
        self._discord_worker = worker

    def _change_game_filter(self) -> None:
        mode = str(self.game_box.currentData())
        strategies_module.write_game_filter(mode)
        self._reload_rows(force=True)
        self.context.strategies_changed.emit()
        status = self.context.status
        if status.running:
            self.context.warn(
                f"Игровой фильтр: {GAME_FILTER_LABELS[mode]}. "
                "Перезапустите обход, чтобы изменения вступили в силу."
            )
        else:
            self.context.ok(f"Игровой фильтр: {GAME_FILTER_LABELS[mode]}")

    # --- список ----------------------------------------------------------

    def _build_list(self) -> None:
        # Двадцать с лишним строк нужны редко — они свёрнуты, а обычная
        # смена стратегии идёт из списка вверху страницы.
        self.list_more = Collapsible("Все стратегии", self.context)
        self.list_more.set_hint("описания, аргументы, запуск любой")

        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию…")
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._filter_rows)
        header.addWidget(self.search)
        card.add_layout(header)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        card.add(self.list_container)

        self.list_more.body.addWidget(card)
        self.body.addWidget(self.list_more)
        self._reload_rows()

    def _reload_rows(self, force: bool = False) -> None:
        items = self.context.load_strategies()
        signature = tuple(item.id for item in items) + (
            self.context.current_game_filter(),
        )
        # 21 строка со значками строится заметно долго, а меняется редко —
        # пересобираем только когда список стратегий или фильтр изменились.
        if not force and signature == self._rows_signature and self._rows:
            self._mark_running()
            return
        self._rows_signature = signature

        clear_layout(self.list_layout)
        self._rows = []

        for index, strategy in enumerate(items):
            if index:
                self.list_layout.addWidget(Divider(self.list_container))
            row = StrategyRow(self.context, strategy, self, self.list_container)
            self.list_layout.addWidget(row)
            self._rows.append(row)
        self._mark_running()

    def _filter_rows(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(index).widget()
            if isinstance(widget, StrategyRow):
                visible = needle in widget.strategy.title.lower() or not needle
                widget.setVisible(visible)

    def _mark_running(self) -> None:
        status = self.context.status
        active = status.strategy_id if status.running else ""
        for row in self._rows:
            row.set_running(bool(active) and row.strategy.id == active)
        if hasattr(self, "current_badge"):
            self._sync_current()

    # --- запуск ----------------------------------------------------------

    def run_strategy(self, strategy: Strategy) -> None:
        config.set("last_strategy", strategy.id)
        mode = str(config.get("run_mode", MODE_SERVICE))

        self._busy = True
        self.current_spinner.start()
        index = self.current_box.findData(strategy.id)
        if index >= 0:
            self.current_box.setCurrentIndex(index)
        self._sync_current()
        for row in self._rows:
            row.btn_run.setEnabled(False)

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_run(strategy))
        worker.failed.connect(self._after_run_error)
        worker.run(engine.restart, strategy, mode)
        self._run_worker = worker

    def _after_run(self, strategy: Strategy) -> None:
        self._busy = False
        self.current_spinner.stop()
        for row in self._rows:
            row.btn_run.setEnabled(True)
        self.context.refresh_status(force=True)
        self._sync_current()
        self.context.ok(f"Запущена стратегия «{strategy.title}»")

    def _after_run_error(self, message: str) -> None:
        self._busy = False
        self.current_spinner.stop()
        for row in self._rows:
            row.btn_run.setEnabled(True)
        self.context.refresh_status(force=True)
        self._sync_current()
        self.context.error(message)

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._reload_rows()
        self._reload_current()
        self._sync_filters()

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.auto_icon.set_color(accent)
        self.auto_spinner.set_color(accent)
        self.current_icon.set_color(accent)
        self.current_spinner.set_color(accent)
        self.discord_spinner.set_color(accent)
        self.list_more.apply_theme()
        for row in self._rows:
            row.apply_theme()
        self._mark_running()
