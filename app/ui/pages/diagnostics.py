"""Страница диагностики: проверки системы и журнал работы."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import diagnostics as diag
from app.core import logs, paths
from app.ui.context import AppContext
from app.ui.pages.base import Page, StatusIcon
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Divider,
    Spinner,
    Worker,
    faint_label,
    section_label,
)


class CheckRow(QWidget):
    """Результат одной проверки с кнопкой исправления."""

    def __init__(self, context: AppContext, result: diag.CheckResult,
                 page: "DiagnosticsPage") -> None:
        super().__init__()
        self.context = context
        self.result = result
        self.page = page

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon = StatusIcon(context, result.status, 18)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(result.title)
        title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(title)
        kind = {"ok": "ok", "warn": "warn", "error": "error"}[result.status]
        label = {"ok": "в норме", "warn": "внимание", "error": "проблема"}[result.status]
        title_row.addWidget(Badge(label, kind))
        title_row.addStretch(1)
        text_box.addLayout(title_row)

        self.message = faint_label(result.message)
        text_box.addWidget(self.message)

        if result.link:
            link = QLabel(f'<a href="{result.link}">Подробнее об этой проблеме</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet(f"color: {context.color('accent_text')};")
            text_box.addWidget(link)

        layout.addLayout(text_box, 1)

        if result.fix is not None and result.fix_label:
            self.fix_button = Button(result.fix_label, variant="soft")
            self.fix_button.clicked.connect(self._run_fix)
            layout.addWidget(self.fix_button, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            self.fix_button = None

    def _run_fix(self) -> None:
        if self.result.fix is None or self.fix_button is None:
            return
        self.fix_button.setEnabled(False)
        self.fix_button.setText("Выполняем…")

        worker = Worker(self)
        worker.finished.connect(self._fix_done)
        worker.failed.connect(self._fix_failed)
        worker.run(self.result.fix)
        self._worker = worker

    def _fix_done(self, message) -> None:
        if self.fix_button is not None:
            self.fix_button.setEnabled(True)
            self.fix_button.setText(self.result.fix_label)
        self.context.ok(str(message) or "Готово")
        self.page.run_checks()

    def _fix_failed(self, message: str) -> None:
        if self.fix_button is not None:
            self.fix_button.setEnabled(True)
            self.fix_button.setText(self.result.fix_label)
        self.context.error(message)


class DiagnosticsPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Диагностика",
            "Проверяем всё, что обычно мешает обходу работать: службы, "
            "драйверы, конкурирующие программы и настройки сети.",
        )
        self._ran_once = False
        self._build_summary()
        self._build_results()
        self._build_log()
        self.apply_theme()

    def _build_summary(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Состояние системы"))
        header.addStretch(1)
        self.spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.spinner)
        self.btn_run = Button("Проверить заново", variant="primary")
        self.btn_run.clicked.connect(self.run_checks)
        header.addWidget(self.btn_run)
        card.add_layout(header)

        badges = QHBoxLayout()
        badges.setSpacing(8)
        self.badge_ok = Badge("0 в норме", "ok")
        self.badge_warn = Badge("0 предупреждений", "warn")
        self.badge_error = Badge("0 проблем", "error")
        for badge in (self.badge_ok, self.badge_warn, self.badge_error):
            badges.addWidget(badge)
        badges.addStretch(1)
        card.add_layout(badges)

        self.summary_text = faint_label(
            "Нажмите «Проверить заново», чтобы запустить диагностику."
        )
        card.add(self.summary_text)

        self.body.addWidget(card)

    def _build_results(self) -> None:
        self.results_card = Card(padding=6, spacing=0)
        self.results_layout = self.results_card.body()
        # Пустая карточка выглядит как артефакт вёрстки — показываем по результату.
        self.results_card.setVisible(False)
        self.body.addWidget(self.results_card)

    def _build_log(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Журнал"))
        header.addStretch(1)

        self.btn_open_log = Button("Открыть файл", variant="ghost")
        self.btn_open_log.clicked.connect(self._open_log_file)
        header.addWidget(self.btn_open_log)

        self.btn_clear_log = Button("Очистить", variant="ghost")
        self.btn_clear_log.clicked.connect(self._clear_log)
        header.addWidget(self.btn_clear_log)
        card.add_layout(header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(190)
        self.log_view.setPlaceholderText(
            "Здесь появятся события запуска, вывод winws.exe и ошибки."
        )
        card.add(self.log_view)

        self.body.addWidget(card)
        logs.subscribe(self._append_log_line)
        self._reload_log()

    # --- проверки --------------------------------------------------------

    def run_checks(self) -> None:
        self.btn_run.setEnabled(False)
        self.spinner.start()
        self.summary_text.setText("Идёт проверка…")

        worker = Worker(self)
        worker.finished.connect(self._checks_done)
        worker.failed.connect(self._checks_failed)
        worker.run(diag.run_all)
        self._worker = worker

    def _checks_failed(self, message: str) -> None:
        self.btn_run.setEnabled(True)
        self.spinner.stop()
        self.context.error(f"Диагностика не завершилась: {message}")

    def _checks_done(self, results) -> None:
        self.btn_run.setEnabled(True)
        self.spinner.stop()
        self._ran_once = True

        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        ordered = sorted(
            results,
            key=lambda item: {"error": 0, "warn": 1, "ok": 2}.get(item.status, 3),
        )
        for index, result in enumerate(ordered):
            if index:
                self.results_layout.addWidget(Divider())
            self.results_layout.addWidget(CheckRow(self.context, result, self))
        self.results_card.setVisible(bool(ordered))

        passed, warnings, errors = diag.summarize(results)
        self.badge_ok.setText(f"{passed} в норме")
        self.badge_warn.setText(f"{warnings} предупреждений")
        self.badge_error.setText(f"{errors} проблем")

        if errors:
            self.summary_text.setText(
                "Найдены проблемы, которые почти наверняка ломают обход. "
                "Исправьте их — рядом с каждой есть кнопка."
            )
        elif warnings:
            self.summary_text.setText(
                "Критичных проблем нет. Предупреждения стоит посмотреть, "
                "если обход работает нестабильно."
            )
        else:
            self.summary_text.setText("Всё в порядке — система готова к обходу.")

    # --- журнал ----------------------------------------------------------

    def _reload_log(self) -> None:
        self.log_view.setPlainText("\n".join(logs.lines()))
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _append_log_line(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _clear_log(self) -> None:
        logs.clear()
        self.log_view.clear()

    def _open_log_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.log_path())))

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        from app.core.config import config

        if not self._ran_once and config.get("diagnostics_autorun", True):
            self.run_checks()

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
