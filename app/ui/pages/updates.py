"""Страница обновлений: ядро zapret и само приложение."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QProgressBar, QTextBrowser

from app.core import net, updater
from app.core.config import config
from app.core.constants import APP_REPO, APP_VERSION, UPSTREAM_HOME, UPSTREAM_REPO
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Divider,
    IconLabel,
    Spinner,
    StatItem,
    Switch,
    Worker,
    faint_label,
    section_label,
)


class UpdatesPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Обновления",
            "Стратегии обхода живут недолго: провайдеры подстраиваются, и "
            "авторы zapret выпускают новые версии. Держите ядро свежим.",
        )
        self._core_info: updater.UpdateInfo | None = None
        self._app_info: updater.UpdateInfo | None = None

        self._build_core_card()
        self._build_app_card()
        self._build_settings_card()
        self.apply_theme()

    # --- ядро ------------------------------------------------------------

    def _build_core_card(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.core_icon = IconLabel("shield_check", self.context.color("accent"), 20)
        header.addWidget(self.core_icon)
        header.addWidget(section_label("Ядро zapret"))
        header.addStretch(1)
        self.core_badge = Badge("не проверялось", "neutral")
        header.addWidget(self.core_badge)
        card.add_layout(header)

        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.core_current = StatItem("Установлено", updater.core_version())
        self.core_latest = StatItem("Доступно", "—")
        stats.addWidget(self.core_current)
        stats.addWidget(self.core_latest)
        stats.addStretch(1)
        card.add_layout(stats)

        self.core_progress = QProgressBar()
        self.core_progress.setVisible(False)
        card.add(self.core_progress)

        self.core_status = faint_label(
            "Обновление скачивается с GitHub. Ваши списки, исключения и "
            "настройки при этом сохраняются."
        )
        card.add(self.core_status)

        self.core_notes = QTextBrowser()
        self.core_notes.setOpenExternalLinks(True)
        self.core_notes.setMaximumHeight(190)
        self.core_notes.setVisible(False)
        card.add(self.core_notes)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.core_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.core_spinner)

        self.btn_core_check = Button("Проверить обновления", variant="primary")
        self.btn_core_check.clicked.connect(lambda: self.check_core(manual=True))
        controls.addWidget(self.btn_core_check)

        self.btn_core_install = Button("Установить обновление", variant="soft")
        self.btn_core_install.clicked.connect(self.install_core)
        self.btn_core_install.setVisible(False)
        controls.addWidget(self.btn_core_install)

        self.btn_core_page = Button("Страница релизов", variant="ghost")
        self.btn_core_page.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"{UPSTREAM_HOME}/releases"))
        )
        controls.addWidget(self.btn_core_page)
        controls.addStretch(1)
        card.add_layout(controls)

        self.body.addWidget(card)

    def check_core(self, manual: bool = False) -> None:
        self.btn_core_check.setEnabled(False)
        self.core_spinner.start()
        if manual:
            self.core_status.setText("Проверяем версию на GitHub…")

        worker = Worker(self)
        worker.finished.connect(lambda info: self._core_checked(info, manual))
        worker.failed.connect(lambda message: self._core_check_failed(message, manual))
        worker.run(updater.check_core_update)
        self._core_worker = worker

    def _core_check_failed(self, message: str, manual: bool) -> None:
        self.btn_core_check.setEnabled(True)
        self.core_spinner.stop()
        self.core_badge.update_state("нет связи", "warn")
        self.core_status.setText(message)
        if manual:
            self.context.error(message)

    def _core_checked(self, info: updater.UpdateInfo, manual: bool) -> None:
        self.btn_core_check.setEnabled(True)
        self.core_spinner.stop()
        self._core_info = info
        updater.mark_checked()

        self.core_current.set_value(info.current)
        self.core_latest.set_value(info.latest)

        if info.error:
            self.core_badge.update_state("нет связи", "warn")
            self.core_status.setText(
                f"{info.error} Проверьте подключение или укажите прокси в настройках."
            )
            if manual:
                self.context.error(info.error)
            return

        if info.notes:
            self.core_notes.setMarkdown(info.notes)
            self.core_notes.setVisible(True)

        if info.available:
            self.core_badge.update_state("есть обновление", "warn")
            self.core_status.setText(
                f"Доступна версия {info.latest}. Обход на время установки "
                "остановится и запустится снова автоматически."
            )
            self.btn_core_install.setVisible(True)
            if manual:
                self.context.warn(f"Доступна версия ядра {info.latest}")
            elif config.get("auto_install_core_updates", False):
                self.install_core(silent=True)
        else:
            self.core_badge.update_state("актуальная версия", "ok")
            self.core_status.setText(f"Установлена свежая версия ядра ({info.current}).")
            self.btn_core_install.setVisible(False)
            if manual:
                self.context.ok("У вас последняя версия ядра")

    def install_core(self, silent: bool = False) -> None:
        info = self._core_info
        if info is None or not info.available:
            return
        self.btn_core_install.setEnabled(False)
        self.btn_core_check.setEnabled(False)
        self.core_progress.setVisible(True)
        self.core_progress.setRange(0, 100)
        self.core_progress.setValue(0)
        self.core_spinner.start()

        worker = Worker(self)
        worker.progress.connect(self._core_progress)
        worker.finished.connect(self._core_installed)
        worker.failed.connect(self._core_install_failed)

        def job():
            return updater.install_core_update(
                info,
                progress=lambda text, percent: worker.progress.emit(text, percent),
            )

        worker.run(job)
        self._core_install_worker = worker

    def _core_progress(self, text: str, percent: int) -> None:
        self.core_status.setText(text)
        self.core_progress.setValue(percent)

    def _core_installed(self, version) -> None:
        self.core_spinner.stop()
        self.core_progress.setVisible(False)
        self.btn_core_install.setEnabled(True)
        self.btn_core_check.setEnabled(True)
        self.btn_core_install.setVisible(False)
        self.core_current.set_value(str(version))
        self.core_badge.update_state("актуальная версия", "ok")
        self.core_status.setText(f"Ядро обновлено до версии {version}.")
        self.context.strategies_changed.emit()
        self.context.refresh_status(force=True)
        self.context.ok(f"Ядро zapret обновлено до {version}")

    def _core_install_failed(self, message: str) -> None:
        self.core_spinner.stop()
        self.core_progress.setVisible(False)
        self.btn_core_install.setEnabled(True)
        self.btn_core_check.setEnabled(True)
        self.core_status.setText(message)
        self.context.error(f"Обновление не установилось: {message}")

    # --- приложение ------------------------------------------------------

    def _build_app_card(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.app_icon = IconLabel("download", self.context.color("accent"), 20)
        header.addWidget(self.app_icon)
        header.addWidget(section_label("Приложение Zapret Control"))
        header.addStretch(1)
        self.app_badge = Badge("не проверялось", "neutral")
        header.addWidget(self.app_badge)
        card.add_layout(header)

        stats = QHBoxLayout()
        stats.setSpacing(28)
        stats.addWidget(StatItem("Установлено", APP_VERSION))
        self.app_latest = StatItem("Доступно", "—")
        stats.addWidget(self.app_latest)
        stats.addStretch(1)
        card.add_layout(stats)

        self.app_progress = QProgressBar()
        self.app_progress.setVisible(False)
        card.add(self.app_progress)

        self.app_status = faint_label(
            "Новая версия скачивается и устанавливается сама — вручную ничего "
            "делать не нужно."
        )
        card.add(self.app_status)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.app_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.app_spinner)

        self.btn_app_check = Button("Проверить обновления")
        self.btn_app_check.clicked.connect(lambda: self.check_app(manual=True))
        controls.addWidget(self.btn_app_check)

        self.btn_app_install = Button("Обновить программу", variant="soft")
        self.btn_app_install.clicked.connect(self.install_app)
        self.btn_app_install.setVisible(False)
        controls.addWidget(self.btn_app_install)
        controls.addStretch(1)
        card.add_layout(controls)

        self.body.addWidget(card)

    def check_app(self, manual: bool = False) -> None:
        if not updater.running_from_installed_copy() and manual:
            self.context.warn(
                "Обновление приложения работает только в установленной версии."
            )
        self.btn_app_check.setEnabled(False)
        self.app_spinner.start()

        worker = Worker(self)
        worker.finished.connect(lambda info: self._app_checked(info, manual))
        worker.failed.connect(lambda message: self._app_check_failed(message, manual))
        worker.run(updater.check_app_update)
        self._app_worker = worker

    def _app_check_failed(self, message: str, manual: bool) -> None:
        self.btn_app_check.setEnabled(True)
        self.app_spinner.stop()
        self.app_badge.update_state("нет связи", "warn")
        if manual:
            self.context.error(message)

    def _app_checked(self, info: updater.UpdateInfo, manual: bool) -> None:
        self.btn_app_check.setEnabled(True)
        self.app_spinner.stop()
        self._app_info = info
        self.app_latest.set_value(info.latest)

        if info.error:
            self.app_badge.update_state("нет связи", "warn")
            self.app_status.setText(info.error)
            if manual:
                self.context.error(info.error)
            return

        if info.available:
            self.app_badge.update_state("есть обновление", "warn")
            self.app_status.setText(f"Доступна версия {info.latest}.")
            self.btn_app_install.setVisible(True)
            if manual:
                self.context.warn(f"Доступна версия приложения {info.latest}")
        else:
            self.app_badge.update_state("актуальная версия", "ok")
            self.app_status.setText("У вас последняя версия приложения.")
            self.btn_app_install.setVisible(False)
            if manual:
                self.context.ok("У вас последняя версия приложения")

    def install_app(self) -> None:
        info = self._app_info
        if info is None or not info.available:
            return
        answer = QMessageBox.question(
            self,
            "Обновление программы",
            f"Скачать и установить версию {info.latest}?\n\n"
            "Программа закроется, установщик отработает сам и запустит "
            "новую версию.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.btn_app_install.setEnabled(False)
        self.app_progress.setVisible(True)
        self.app_progress.setRange(0, 100)
        self.app_spinner.start()

        worker = Worker(self)
        worker.progress.connect(
            lambda text, percent: (
                self.app_status.setText(text), self.app_progress.setValue(percent)
            )
        )
        worker.finished.connect(self._app_downloaded)
        worker.failed.connect(self._app_install_failed)

        def job():
            return updater.install_app_update(
                info,
                progress=lambda text, percent: worker.progress.emit(text, percent),
            )

        worker.run(job)
        self._app_install_worker = worker

    def _app_downloaded(self, installer) -> None:
        self.app_spinner.stop()
        self.app_progress.setVisible(False)
        self.app_status.setText("Запускаем установщик…")
        updater.launch_installer(installer)
        window = self.window()
        quit_app = getattr(window, "quit_app", None)
        if callable(quit_app):
            quit_app()

    def _app_install_failed(self, message: str) -> None:
        self.app_spinner.stop()
        self.app_progress.setVisible(False)
        self.btn_app_install.setEnabled(True)
        self.app_status.setText(message)
        self.context.error(message)

    # --- настройки обновлений --------------------------------------------

    def _build_settings_card(self) -> None:
        from app.ui.widgets import SettingRow

        card = Card(padding=20, spacing=14)
        card.add(section_label("Как проверять обновления"))

        self.switch_core = Switch(bool(config.get("check_core_updates", True)))
        self.switch_core.toggled.connect(
            lambda value: config.set("check_core_updates", value)
        )
        card.add(SettingRow(
            "Проверять ядро при запуске",
            "Раз в несколько часов программа тихо спрашивает GitHub о новой версии.",
            self.switch_core,
        ))
        card.add(Divider())

        self.switch_auto = Switch(bool(config.get("auto_install_core_updates", False)))
        self.switch_auto.toggled.connect(
            lambda value: config.set("auto_install_core_updates", value)
        )
        card.add(SettingRow(
            "Устанавливать обновления ядра сами",
            "Найденное обновление скачается и применится без вопросов. "
            "Обход при этом коротко перезапустится.",
            self.switch_auto,
        ))
        card.add(Divider())

        self.switch_app = Switch(bool(config.get("check_app_updates", True)))
        self.switch_app.toggled.connect(
            lambda value: config.set("check_app_updates", value)
        )
        card.add(SettingRow(
            "Проверять обновления приложения",
            f"Репозиторий: {APP_REPO}" if APP_REPO
            else "Репозиторий не указан — обновление программы выключено.",
            self.switch_app,
        ))

        card.add(Divider())
        card.add(faint_label(
            f"Источник ядра: github.com/{UPSTREAM_REPO}. "
            f"Соединение: {net.connectivity_hint()}. Если GitHub недоступен, "
            "программа сама пробует зеркала."
        ))

        self.body.addWidget(card)

    # --- страница --------------------------------------------------------

    def check_silently(self) -> None:
        """Тихая проверка при запуске приложения."""
        self.check_core(manual=False)
        if config.get("check_app_updates", True) and updater.running_from_installed_copy():
            self.check_app(manual=False)

    def on_activate(self) -> None:
        self.core_current.set_value(updater.core_version())

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.core_icon.set_color(accent)
        self.app_icon.set_color(accent)
        self.core_spinner.set_color(accent)
        self.app_spinner.set_color(accent)
        on_accent = self.context.color("accent")
        for switch in (self.switch_core, self.switch_auto, self.switch_app):
            switch.set_colors(on_accent, self.context.color("border_strong"),
                              self.context.color("surface"))
