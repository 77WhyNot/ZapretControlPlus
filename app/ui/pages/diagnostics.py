"""Страница диагностики: проверки системы и журнал работы."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import diagnostics as diag
from app.core import logs, paths
from app.core.vpn import clients as vpn_clients
from app.ui.context import AppContext
from app.ui.pages.base import Page, StatusIcon
from app.ui.widgets import (
    clear_layout,
    Badge,
    Button,
    Card,
    Divider,
    Spinner,
    Worker,
    faint_label,
    section_label,
)


# Перенос строки для диалогов: держим константой, чтобы не зависеть
# от того, как разные инструменты обрабатывают экранирование.
LINE_BREAK = chr(10)


class CheckRow(QWidget):
    """Результат одной проверки с кнопкой исправления."""

    def __init__(self, context: AppContext, result: diag.CheckResult,
                 page: "DiagnosticsPage",
                 parent: QWidget | None = None) -> None:
        # Без родителя виджет до вставки в компоновку считается окном.
        super().__init__(parent)
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
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Диагностика",
            "Проверяем всё, что обычно мешает обходу работать: службы, "
            "драйверы, конкурирующие программы и настройки сети.",
            parent,
        )
        self._ran_once = False
        self._build_summary()
        self._build_results()
        self._build_tools()
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

        clear_layout(self.results_layout)

        ordered = sorted(
            results,
            key=lambda item: {"error": 0, "warn": 1, "ok": 2}.get(item.status, 3),
        )
        for index, result in enumerate(ordered):
            if index:
                self.results_layout.addWidget(Divider(self.results_card))
            self.results_layout.addWidget(
                CheckRow(self.context, result, self, self.results_card)
            )
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

    # --- инструменты -----------------------------------------------------

    def _build_tools(self) -> None:
        card = Card(padding=20, spacing=13)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Инструменты"))
        header.addStretch(1)
        self.tools_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.tools_spinner)
        card.add_layout(header)

        card.add(faint_label(
            "Discord держит адреса голосовых серверов в кэше и после смены "
            "стратегии продолжает стучаться по старым. Перезапуск с очисткой "
            "чаще всего и чинит неработающий голос."
        ))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_discord_restart = Button("Перезапустить Discord", variant="soft")
        self.btn_discord_restart.clicked.connect(
            lambda: self._run_tool(diag.restart_discord_clean,
                                   self.btn_discord_restart)
        )
        row.addWidget(self.btn_discord_restart)

        self.btn_discord_cache = Button("Только очистить кэш")
        self.btn_discord_cache.clicked.connect(
            lambda: self._run_tool(diag.clear_discord_cache, self.btn_discord_cache)
        )
        row.addWidget(self.btn_discord_cache)

        self.btn_discord_start = Button("Запустить Discord", variant="ghost")
        self.btn_discord_start.clicked.connect(
            lambda: self._run_tool(diag.launch_discord, self.btn_discord_start)
        )
        row.addWidget(self.btn_discord_start)
        row.addStretch(1)
        card.add_layout(row)

        card.add(Divider())

        self.clients_label = faint_label("")
        card.add(self.clients_label)

        clients_row = QHBoxLayout()
        clients_row.setSpacing(10)
        self.btn_stop_clients = Button("Закрыть чужие VPN-клиенты", variant="soft")
        self.btn_stop_clients.clicked.connect(self._stop_clients)
        clients_row.addWidget(self.btn_stop_clients)

        self.btn_flush_dns = Button("Сбросить кэш DNS", variant="ghost")
        self.btn_flush_dns.clicked.connect(
            lambda: self._run_tool(self._flush_dns, self.btn_flush_dns)
        )
        clients_row.addWidget(self.btn_flush_dns)
        clients_row.addStretch(1)
        card.add_layout(clients_row)

        self.body.addWidget(card)
        self._refresh_clients()

    def _flush_dns(self) -> str:
        from app.core import dnsctl

        return ("Кэш DNS очищен." if dnsctl.flush_cache()
                else "Не удалось очистить кэш DNS.")

    def _refresh_clients(self) -> None:
        found = vpn_clients.running_clients()
        if found:
            names = ", ".join(item.title for item in found)
            self.clients_label.setText(
                f"Сейчас запущены сторонние VPN-клиенты: {names}. "
                "Два туннеля одновременно конфликтуют — закройте их, "
                "прежде чем включать VPN здесь."
            )
            self.btn_stop_clients.setEnabled(True)
        else:
            self.clients_label.setText("Сторонних VPN-клиентов не запущено.")
            self.btn_stop_clients.setEnabled(False)

    def _stop_clients(self) -> None:
        found = vpn_clients.running_clients()
        if not found:
            self._refresh_clients()
            return
        names = ", ".join(item.title for item in found)
        answer = QMessageBox.question(
            self, "Закрыть чужие клиенты",
            f"Будут принудительно закрыты: {names}."
            + LINE_BREAK * 2 +
            
            "Их туннели отключатся, несохранённые данные в этих программах "
            "могут потеряться. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_tool(lambda: vpn_clients.stop_all(found), self.btn_stop_clients)

    def _run_tool(self, function, button) -> None:
        button.setEnabled(False)
        self.tools_spinner.start()

        worker = Worker(self)
        worker.finished.connect(lambda result: self._tool_done(str(result), button))
        worker.failed.connect(lambda message: self._tool_done(message, button, True))
        worker.run(function)
        self._tool_worker = worker

    def _tool_done(self, message: str, button, error: bool = False) -> None:
        button.setEnabled(True)
        self.tools_spinner.stop()
        (self.context.error if error else self.context.ok)(message)
        self._refresh_clients()


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
        self._refresh_clients()
        from app.core.config import config

        if not self._ran_once and config.get("diagnostics_autorun", True):
            self.run_checks()

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
        self.tools_spinner.set_color(self.context.color("accent"))
