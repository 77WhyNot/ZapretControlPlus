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

from app.core import autotest, strategies as strategies_module, telegram
from app.core.config import config
from app.core.engine import MODE_PROCESS, MODE_SERVICE, engine
from app.core.strategies import GAME_FILTER_LABELS, Strategy
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Divider,
    IconLabel,
    SettingRow,
    Spinner,
    Switch,
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
                 page: "StrategiesPage") -> None:
        super().__init__()
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
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Стратегии",
            "Стратегия — это набор приёмов обмана DPI. У разных провайдеров "
            "работают разные варианты, поэтому их и много.",
        )
        self._rows: list[StrategyRow] = []
        self._tester: autotest.AutoTester | None = None
        self._auto_worker: Worker | None = None

        self._build_autopick()
        self._build_telegram()
        self._build_game_filter()
        self._build_list()

        context.status_changed.connect(lambda _: self._mark_running())
        self.apply_theme()

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
            "а затем по очереди проверит стратегии и оставит лучшую. "
            "Во время подбора связь будет прерываться — это нормально."
        ))

        self.auto_progress = QProgressBar()
        self.auto_progress.setVisible(False)
        card.add(self.auto_progress)

        self.auto_status = faint_label("")
        self.auto_status.setVisible(False)
        card.add(self.auto_status)

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
                on_progress=lambda index, total, strategy: worker.progress.emit(
                    f"[{index}/{total}] {strategy.title}", index
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
        while self.auto_results_layout.count():
            item = self.auto_results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

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

    # --- Telegram --------------------------------------------------------

    def _build_telegram(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.tg_icon = IconLabel("bolt", self.context.color("accent"), 20)
        header.addWidget(self.tg_icon)
        header.addWidget(section_label("Обход Telegram"))
        header.addStretch(1)
        self.tg_badge = Badge("выключен", "neutral")
        header.addWidget(self.tg_badge)
        self.switch_tg = Switch(telegram.is_enabled())
        self.switch_tg.toggled.connect(self._toggle_telegram)
        header.addWidget(self.switch_tg)
        card.add_layout(header)

        card.add(faint_label(
            "Telegram общается по протоколу MTProto, где имени домена в пакете "
            "нет вообще — опознать его по списку сайтов невозможно. Поэтому "
            "обход работает по официальному списку подсетей Telegram. "
            "Секции добавляются к выбранной стратегии: отдельным процессом "
            "запустить нельзя, два winws не уживаются из-за общего драйвера."
        ))

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.tg_mode = QComboBox()
        for key, label in telegram.MODES.items():
            self.tg_mode.addItem(label, key)
        index = self.tg_mode.findData(telegram.mode())
        if index >= 0:
            self.tg_mode.setCurrentIndex(index)
        self.tg_mode.currentIndexChanged.connect(self._change_telegram_mode)
        controls.addWidget(self.tg_mode)

        self.tg_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.tg_spinner)

        self.btn_tg_update = Button("Обновить подсети", variant="ghost")
        self.btn_tg_update.clicked.connect(self._update_telegram_ipset)
        controls.addWidget(self.btn_tg_update)
        controls.addStretch(1)
        card.add_layout(controls)

        self.tg_hint = faint_label("")
        card.add(self.tg_hint)

        self.body.addWidget(card)
        self._sync_telegram()

    def _sync_telegram(self) -> None:
        enabled = telegram.is_enabled()
        self.tg_badge.update_state(
            "включён" if enabled else "выключен", "ok" if enabled else "neutral"
        )
        self.tg_hint.setText(telegram.summary())
        self.switch_tg.set_colors(
            self.context.color("accent"),
            self.context.color("border_strong"),
            self.context.color("surface"),
        )

    def _toggle_telegram(self, value: bool) -> None:
        telegram.set_enabled(value)
        self._sync_telegram()
        if self.context.status.running:
            self.context.warn(
                "Перезапустите обход, чтобы настройка Telegram вступила в силу."
            )
        else:
            self.context.ok("Обход Telegram " + ("включён" if value else "выключен"))

    def _change_telegram_mode(self) -> None:
        telegram.set_mode(str(self.tg_mode.currentData()))
        self._sync_telegram()
        if self.context.status.running and telegram.is_enabled():
            self.context.warn("Перезапустите обход, чтобы применить новый режим.")

    def _update_telegram_ipset(self) -> None:
        self.btn_tg_update.setEnabled(False)
        self.tg_spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._telegram_updated)
        worker.failed.connect(self._telegram_failed)
        worker.run(telegram.update_ipset)
        self._tg_worker = worker

    def _telegram_updated(self, count) -> None:
        self.btn_tg_update.setEnabled(True)
        self.tg_spinner.stop()
        self._sync_telegram()
        self.context.ok(f"Подсети Telegram обновлены: {count}")

    def _telegram_failed(self, message: str) -> None:
        self.btn_tg_update.setEnabled(True)
        self.tg_spinner.stop()
        self.context.error(str(message))

    # --- игровой фильтр --------------------------------------------------

    def _build_game_filter(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Игровой фильтр"))
        header.addStretch(1)
        self.game_box = QComboBox()
        for key, label in GAME_FILTER_LABELS.items():
            self.game_box.addItem(label.capitalize(), key)
        index = self.game_box.findData(self.context.current_game_filter())
        if index >= 0:
            self.game_box.setCurrentIndex(index)
        self.game_box.currentIndexChanged.connect(self._change_game_filter)
        header.addWidget(self.game_box)
        card.add_layout(header)

        card.add(faint_label(
            "Расширяет обход на порты 1024–65535, чтобы работали игры и голосовые "
            "сервисы. Обратная сторона: нагрузка растёт, а часть программ может "
            "начать сбоить. Включайте, только если без него игры не работают."
        ))
        self.body.addWidget(card)

    def _change_game_filter(self) -> None:
        mode = str(self.game_box.currentData())
        strategies_module.write_game_filter(mode)
        self._reload_rows()
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
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Все стратегии"))
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

        self.body.addWidget(card)
        self._reload_rows()

    def _reload_rows(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []

        items = self.context.load_strategies()
        for index, strategy in enumerate(items):
            if index:
                self.list_layout.addWidget(Divider())
            row = StrategyRow(self.context, strategy, self)
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

    # --- запуск ----------------------------------------------------------

    def run_strategy(self, strategy: Strategy) -> None:
        config.set("last_strategy", strategy.id)
        mode = str(config.get("run_mode", MODE_SERVICE))

        for row in self._rows:
            row.btn_run.setEnabled(False)

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_run(strategy))
        worker.failed.connect(self._after_run_error)
        worker.run(engine.restart, strategy, mode)
        self._run_worker = worker

    def _after_run(self, strategy: Strategy) -> None:
        for row in self._rows:
            row.btn_run.setEnabled(True)
        self.context.refresh_status(force=True)
        self.context.ok(f"Запущена стратегия «{strategy.title}»")

    def _after_run_error(self, message: str) -> None:
        for row in self._rows:
            row.btn_run.setEnabled(True)
        self.context.refresh_status(force=True)
        self.context.error(message)

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._reload_rows()

    def apply_theme(self) -> None:
        self.auto_icon.set_color(self.context.color("accent"))
        self.tg_icon.set_color(self.context.color("accent"))
        self.tg_spinner.set_color(self.context.color("accent"))
        self._sync_telegram()
        self.auto_spinner.set_color(self.context.color("accent"))
        for row in self._rows:
            row.apply_theme()
        self._mark_running()
