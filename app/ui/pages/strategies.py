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
        self._tester = None
        self._auto_worker: Worker | None = None
        self._busy = False
        self._testing = False

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
        free = not self._busy and not self._testing
        self.btn_current_stop.setEnabled(running and free)
        self.btn_current_run.setEnabled(free)
        self._sync_launchers(free)
        active = next((item for item in self.context.load_strategies()
                       if item.id == status.strategy_id), None)
        self.current_hint.setText(
            "Идёт проверка стратегий — обход вернётся сам через несколько секунд."
            if self._testing else
            f"Сейчас работает «{active.title}»." if running and active else
            "Выберите стратегию и нажмите «Запустить». Не знаете какую — "
            "нажмите «Проверить все» ниже: программа проверит их разом."
        )

    def _sync_launchers(self, free: bool) -> None:
        """Всё, что запускает или снимает обход, — только когда движок свободен.

        Иначе двойной щелчок по «Применить» запускал два перезапуска разом,
        и они удаляли службу друг у друга, а «Проверить все» посреди
        перезапуска заставала обход «выключенным» и не возвращала его.
        """
        for row in self._rows:
            row.btn_run.setEnabled(free)
        if hasattr(self, "board"):
            self.board.set_enabled(free)
            self.btn_apply_best.setEnabled(free)
            if not self._testing:           # во время проверки это «Отменить»
                self.btn_auto.setEnabled(not self._busy)
        if hasattr(self, "btn_restart"):
            self.btn_restart.setEnabled(free)
            # Фильтры, поменянные посреди проверки, не попали бы в обход,
            # который она вернёт, — пусть подождут пару секунд.
            for widget in (self.game_box, self.ipset_box, self.game_ports_row, self.mode_box):
                widget.setEnabled(not self._testing)

    def _apply_current(self) -> None:
        strategy = self._selected_strategy()
        if strategy is None:
            self.context.error("Стратегия не найдена.")
            return
        self.run_strategy(strategy)

    def _stop_current(self) -> None:
        if self._busy or self._testing:
            return
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

    # --- подбор: все стратегии разом ---------------------------------------

    def _build_autopick(self) -> None:
        from app.ui.leaderboard import Leaderboard, ShimmerBar

        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.auto_icon = IconLabel("bolt", self.context.color("accent"), 20)
        header.addWidget(self.auto_icon)
        header.addWidget(section_label("Подбор стратегии"))
        header.addStretch(1)
        self.auto_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.auto_spinner)
        self.btn_auto = Button("Проверить все", variant="primary")
        self.btn_auto.clicked.connect(self._toggle_autopick)
        header.addWidget(self.btn_auto)
        card.add_layout(header)

        card.add(faint_label(
            "Программа на несколько секунд снимет обход, разом проверит все "
            "стратегии на заблокированных сайтах и вернёт всё как было. "
            "Останется выбрать лучшую — одним щелчком."
        ))

        self.auto_bar = ShimmerBar(self.context)
        card.add(self.auto_bar)
        self.auto_bar.setVisible(False)

        self.auto_status = faint_label("")
        card.add(self.auto_status)
        self.auto_status.setVisible(False)

        # Итог: коротко о лучшей и кнопка, чтобы поставить её сразу.
        self.auto_summary = QWidget()
        summary = QHBoxLayout(self.auto_summary)
        summary.setContentsMargins(0, 2, 0, 2)
        summary.setSpacing(10)
        self.auto_summary_text = QLabel("")
        self.auto_summary_text.setWordWrap(True)
        summary.addWidget(self.auto_summary_text, 1)
        self.btn_apply_best = Button("Применить лучшую", variant="primary")
        self.btn_apply_best.clicked.connect(self._apply_best)
        summary.addWidget(self.btn_apply_best, 0, Qt.AlignmentFlag.AlignVCenter)
        card.add(self.auto_summary)
        self.auto_summary.setVisible(False)

        self.board = Leaderboard(self.context)
        self.board.apply_requested.connect(self.run_strategy)
        card.add(self.board)
        self.board.setVisible(False)

        self._best_strategy: Strategy | None = None
        self.body.addWidget(card)

    def _toggle_autopick(self) -> None:
        if self._tester is not None:
            # Одна отмена на всё: перебор по одной делит флаг с проверкой разом.
            self._tester.cancel()
            self.auto_status.setText("Отменяем… обход вернётся через пару секунд.")
            self.btn_auto.setEnabled(False)
            return
        self._start_autopick()

    def _start_autopick(self) -> None:
        import time

        from PySide6.QtCore import QObject, Signal

        from app.core import parallel

        if self._busy or self._testing:
            # Посреди запуска или остановки проверка застала бы обход
            # «выключенным» и не вернула бы его.
            return
        all_strategies = self.context.load_strategies()
        if not all_strategies:
            # Раньше проверяющий создавался до этой проверки, и кнопка
            # «Подобрать» после неё оставалась выключенной навсегда.
            self.context.error("Стратегии не найдены — проверьте вкладку «Обновления».")
            return
        targets = autotest.load_targets()[:autotest.MAX_TARGETS]
        tester = parallel.ParallelTester()
        self._tester = tester

        class Events(QObject):
            event = Signal(str, object)

        events = Events(self)
        events.event.connect(self._on_test_event)
        self._events = events

        self._set_testing(True)
        self.btn_auto.setText("Отменить")
        self.btn_auto.setEnabled(True)
        self.auto_spinner.start()
        self.auto_bar.setVisible(True)
        self.auto_bar.start()
        self.auto_status.setVisible(True)
        self.auto_status.setText("Готовимся…")
        self.auto_summary.setVisible(False)
        self._done_ids: set[str] = set()
        self._total_count = 0

        def fallback(token) -> parallel.ParallelReport:
            """Разом нельзя — перебираем по одной, как раньше, но под ключом
            проверки и только ходовые стратегии: полный перебор — минуты."""
            started = time.perf_counter()
            sequential = autotest.AutoTester(token=token, cancel_event=tester.cancel_event)
            blocked, baseline = sequential.find_blocked()
            if sequential.cancelled:
                raise parallel.Cancelled("Проверка отменена.")
            report = parallel.ParallelReport(baseline=baseline, blocked=blocked)
            if not blocked:
                report.note = "Всё открывается и без обхода — сравнивать стратегии не на чем."
                report.seconds = time.perf_counter() - started
                return report
            candidates = autotest.shortlist(all_strategies)
            events.event.emit(parallel.EVENT_STARTED, (candidates, blocked))
            events.event.emit(parallel.EVENT_PHASE, "Проверяем по одной — так дольше…")
            report.scores = sequential.evaluate(
                candidates, blocked, mode=MODE_PROCESS,
                on_result=lambda score: events.event.emit(parallel.EVENT_RESULT, score),
            )
            # Прерванный перебор — не итог: лучшая из половины списка
            # выдавалась бы за лучшую вообще.
            if sequential.cancelled:
                raise parallel.Cancelled("Проверка отменена.")
            report.seconds = time.perf_counter() - started
            return report

        worker = Worker(self)
        worker.finished.connect(self._auto_finished)
        worker.failed.connect(self._auto_failed)
        worker.run(
            parallel.check_all, all_strategies, targets, tester,
            lambda kind, payload: events.event.emit(kind, payload), fallback,
        )
        self._auto_worker = worker

    def _on_test_event(self, kind: str, payload) -> None:
        from app.core import parallel

        if kind == parallel.EVENT_PHASE:
            self.auto_status.setText(str(payload))
        elif kind == parallel.EVENT_BASELINE:
            blocked = sum(1 for item in payload if not item.ok)
            self.auto_status.setText(
                f"Без обхода не открывается сайтов: {blocked} из {len(payload)}."
                if blocked else "Без обхода открывается всё."
            )
            self.auto_bar.set_fraction(0.15)
        elif kind == parallel.EVENT_STARTED:
            # Таблица начинается заново (в том числе при переходе на перебор
            # по одной) — и счёт вместе с ней.
            strategies_list, targets = payload
            self._done_ids = set()
            self._total_count = len(strategies_list)
            self.board.setVisible(True)
            self.board.start(strategies_list, targets)
            self.auto_bar.set_fraction(0.25)
        elif kind == parallel.EVENT_RESULT:
            self.board.update_score(payload)
            # По стратегиям, а не по событиям: у одной их бывает два
            # (после первой волны и после перепроверки осечек).
            self._done_ids.add(payload.strategy.id)
            if self._total_count:
                self.auto_bar.set_fraction(
                    0.25 + 0.6 * min(1.0, len(self._done_ids) / self._total_count))
        elif kind == parallel.EVENT_RETRY:
            self.auto_status.setText(f"Перепроверяем осечки: {payload}…")
            self.auto_bar.set_fraction(0.9)

    def _set_testing(self, testing: bool) -> None:
        """Пока идёт проверка, запускать и снимать обход со страницы нельзя."""
        self._testing = testing
        self._sync_current()

    def _finish_autopick(self) -> None:
        self.auto_spinner.stop()
        self.auto_bar.stop()
        self.btn_auto.setText("Проверить заново")
        self._tester = None
        self._set_testing(False)
        self.context.refresh_status(force=True)

    def _auto_failed(self, message: str) -> None:
        self._finish_autopick()
        self.board.stop_waiting()
        self.auto_status.setText(f"Проверка прервалась: {message}")
        self.context.error(f"Проверка прервалась: {message}")

    def _auto_finished(self, outcome) -> None:
        self._finish_autopick()
        report = outcome.report
        previous = outcome.previous
        back = (" Обход возвращён." if outcome.restored else "")
        if previous.external:
            # Чужой winws проверка снимает (иначе он перехватил бы весь трафик
            # и испортил сравнение), а вернуть его может только тот, кто запускал.
            back = " Сторонний winws снят — включите обход здесь или в той программе."
        if outcome.restore_error:
            self.context.error(f"Не удалось вернуть обход: {outcome.restore_error}")

        if outcome.cancelled:
            self.board.stop_waiting()
            self.auto_status.setText("Проверка отменена." + back)
            return
        if report.problem:
            self.board.setVisible(False)
            self.auto_status.setText(report.problem + back)
            self.context.warn(report.problem)
            return
        if report.note:
            self.board.setVisible(False)
            self.auto_status.setText(
                report.note + " Возможно, провайдер вас не блокирует." + back)
            self.context.ok("Блокировок не обнаружено")
            return

        scores = report.scores
        # «Сейчас» и «ваша» — только про обход, который работает и после
        # проверки: если вернуть не вышло, ничего не работает.
        current_id = previous.strategy.id \
            if outcome.restored and previous.strategy is not None else ""
        self.board.finish(scores, current_id)
        best = report.best
        how = "по одной" if outcome.sequential else "разом"
        self.auto_status.setText(
            f"Проверено стратегий: {len(scores)} {how} за {report.seconds:.0f} с." + back
        )
        if best is None:
            self._best_strategy = None
            self.auto_summary_text.setText(
                "Ни одна стратегия не открыла заблокированные сайты. Загляните "
                "в «Диагностику» — возможно, мешает другая программа."
            )
            self.btn_apply_best.setVisible(False)
            self.auto_summary.setVisible(True)
            self.context.warn("Рабочих стратегий не нашлось")
            return

        self._best_strategy = best.strategy
        mine = next((item for item in scores if item.strategy.id == current_id), None)
        text = (f"Лучшая — «{best.strategy.title}»: открыла {best.passed} из "
                f"{best.total} сайтов.")
        if mine is not None and mine.strategy.id != best.strategy.id:
            if mine.passed == best.passed:
                text += f" Ваша «{mine.strategy.title}» открывает столько же — менять не обязательно."
            else:
                text += (f" Ваша «{mine.strategy.title}» открыла {mine.passed} из "
                         f"{mine.total} — лучше сменить.")
        # «Стоит» — только если обход правда вернулся: при неудаче возврата
        # кнопка нужна, чтобы поставить стратегию снова.
        already = mine is not None and mine.strategy.id == best.strategy.id \
            and outcome.restored
        if already:
            text += " Она у вас и стоит."
        self.auto_summary_text.setText(text)
        self.btn_apply_best.setText(f"Применить «{best.strategy.title}»")
        self.btn_apply_best.setVisible(not already)
        self.auto_summary.setVisible(True)
        self.context.ok(f"Лучшая стратегия — «{best.strategy.title}»")

    def _apply_best(self) -> None:
        if self._best_strategy is not None:
            self.run_strategy(self._best_strategy)

    # --- фильтры ---------------------------------------------------------

    def _build_filters(self) -> None:
        from app.core import lists as lists_module
        from app.ui.widgets import SettingRow

        card = Card(padding=20, spacing=12)
        card.add(section_label("Фильтры"))

        self.game_box = QComboBox()
        for key, label in GAME_FILTER_LABELS.items():
            # Не capitalize(): он превратил бы «TCP и UDP» в «Tcp и udp».
            self.game_box.addItem(label[:1].upper() + label[1:], key)
        index = self.game_box.findData(self.context.current_game_filter())
        if index >= 0:
            self.game_box.setCurrentIndex(index)
        self.game_box.currentIndexChanged.connect(self._change_game_filter)
        card.add(SettingRow(
            "Игровой фильтр",
            "Расширяет обход на порты игр и голосовых сервисов (обычно 1024–65535). "
            "Нагрузка растёт, часть программ может сбоить — включайте, только "
            "если без него игры не работают.",
            self.game_box,
        ))

        # Свои порты — с ядра 1.10.3. Строка видна, только пока фильтр включён.
        ports = QWidget()
        ports_layout = QHBoxLayout(ports)
        ports_layout.setContentsMargins(0, 0, 0, 0)
        ports_layout.setSpacing(8)
        self.game_ports: dict[str, QLineEdit] = {}
        self.game_port_labels: dict[str, QLabel] = {}
        for kind in ("tcp", "udp"):
            caption = faint_label(kind.upper())
            field = QLineEdit()
            field.setPlaceholderText(strategies_module.DEFAULT_GAME_RANGE)
            field.setFixedWidth(180)
            field.setToolTip("Порты через запятую: одиночные или диапазоны, "
                             "например 1024-1934,1936-65535")
            field.editingFinished.connect(lambda kind=kind: self._change_game_ports(kind))
            ports_layout.addWidget(caption)
            ports_layout.addWidget(field)
            self.game_ports[kind] = field
            self.game_port_labels[kind] = caption
        self.game_ports_row = SettingRow(
            "Порты игрового фильтра",
            "Менять обычно не нужно. Если какая-то программа сбоит, её порт можно "
            "исключить: «1024-1934,1936-65535». Пустое поле — все порты от 1024.",
            ports,
        )
        card.add(self.game_ports_row)
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
        self._sync_game_ports()

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
        self._sync_game_ports()
        self._game_filter_saved(f"Игровой фильтр: {GAME_FILTER_LABELS[mode]}")

    def _sync_game_ports(self) -> None:
        settings = strategies_module.read_game_filter_settings()
        self.game_ports_row.setVisible(settings.mode != "off")
        for kind, field in self.game_ports.items():
            value = getattr(settings, f"{kind}_range")
            field.setText("" if value == strategies_module.DEFAULT_GAME_RANGE else value)
            field.setCursorPosition(0)
            self._mark_port_field(field, False)
            used = settings.mode in ("all", kind)
            field.setEnabled(used)
            self.game_port_labels[kind].setEnabled(used)

    @staticmethod
    def _mark_port_field(field: QLineEdit, invalid: bool) -> None:
        if field.property("invalid") == invalid:
            return
        field.setProperty("invalid", invalid)
        field.style().unpolish(field)
        field.style().polish(field)

    def _change_game_ports(self, kind: str) -> None:
        field = self.game_ports[kind]
        text = field.text().strip()
        value = strategies_module.validate_port_range(text) if text \
            else strategies_module.DEFAULT_GAME_RANGE
        if not value:
            self._mark_port_field(field, True)
            self.context.warn(f"Порты {kind.upper()}: нужны числа 1–65535 через "
                              "запятую или диапазоны вроде 1024-65535.")
            return
        self._mark_port_field(field, False)
        settings = strategies_module.read_game_filter_settings()
        if getattr(settings, f"{kind}_range") == value:
            return
        strategies_module.write_game_filter(settings.mode, **{f"{kind}_range": value})
        self._sync_game_ports()
        shown = "все от 1024" if value == strategies_module.DEFAULT_GAME_RANGE else value
        self._game_filter_saved(f"Порты {kind.upper()} игрового фильтра: {shown}")

    def _game_filter_saved(self, message: str) -> None:
        self._reload_rows(force=True)
        self.context.strategies_changed.emit()
        if self.context.status.running:
            self.context.warn(f"{message}. Перезапустите обход, чтобы изменения вступили в силу.")
        else:
            self.context.ok(message)

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
        if self._busy or self._testing:
            return  # второй щелчок, пока идёт первый запуск, или идёт проверка
        # Строка таблицы и итог проверки помнят стратегию с аргументами на
        # момент проверки; фильтры с тех пор могли поменять — берём заново.
        strategy = strategies_module.find_strategy(
            strategy.id, self.context.current_game_filter()) or strategy
        config.set("last_strategy", strategy.id)
        mode = str(config.get("run_mode", MODE_SERVICE))

        self._busy = True
        self.current_spinner.start()
        index = self.current_box.findData(strategy.id)
        if index >= 0:
            self.current_box.setCurrentIndex(index)
        self._sync_current()

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_run(strategy))
        worker.failed.connect(self._after_run_error)
        worker.run(engine.restart, strategy, mode)
        self._run_worker = worker

    def _after_run(self, strategy: Strategy) -> None:
        self._busy = False
        self.current_spinner.stop()
        self.context.refresh_status(force=True)
        self._sync_current()
        self.context.ok(f"Запущена стратегия «{strategy.title}»")

    def _after_run_error(self, message: str) -> None:
        self._busy = False
        self.current_spinner.stop()
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
        self.board.apply_theme()
        for row in self._rows:
            row.apply_theme()
        self._mark_running()
