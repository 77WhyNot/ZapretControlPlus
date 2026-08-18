"""Страница настроек: внешний вид, поведение, сеть."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox, QWidget

from app.core import net, paths, winapi
from app.core.config import config
from app.core.constants import AUTOSTART_TASK
from app.ui import theme
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Button,
    Card,
    Divider,
    SettingRow,
    Spinner,
    Switch,
    Worker,
    faint_label,
    section_label,
)


class ThemeCard(QWidget):
    """Карточка-превью темы."""

    picked = Signal(str)

    def __init__(self, key: str, title: str, colors: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.title = title
        self.colors = colors
        self.selected = False
        self.accent = "#C41E4A"
        self.setFixedSize(150, 104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, value: bool, accent: str) -> None:
        self.selected = value
        self.accent = accent
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        border = QColor(self.accent if self.selected else self.colors["border"])
        painter.setPen(border)
        painter.setBrush(QColor(self.colors["bg"]))
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 10, 10)

        # Имитация окна: боковое меню, шапка и пара карточек.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.colors["sidebar"]))
        painter.drawRoundedRect(9, 9, 34, self.height() - 18, 6, 6)

        painter.setBrush(QColor(self.colors["surface"]))
        painter.drawRoundedRect(49, 9, self.width() - 58, 20, 5, 5)
        painter.drawRoundedRect(49, 35, self.width() - 58, 26, 5, 5)

        painter.setBrush(QColor(self.accent))
        painter.drawRoundedRect(53, 41, 40, 13, 4, 4)
        painter.setBrush(QColor(self.colors["border"]))
        painter.drawRoundedRect(49, 67, self.width() - 58, 10, 4, 4)
        painter.drawRoundedRect(14, 16, 24, 5, 2, 2)
        painter.drawRoundedRect(14, 26, 24, 5, 2, 2)

        painter.setPen(QColor(self.colors["text"]))
        painter.drawText(
            12, self.height() - 12, self.title
        )
        painter.end()


class AccentDot(QWidget):
    """Кружок выбора акцентного цвета."""

    picked = Signal(str)

    def __init__(self, accent: theme.AccentDef, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.accent = accent
        self.selected = False
        self.ring = "#CDD4DE"
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(accent.title)

    def set_selected(self, value: bool, ring: str) -> None:
        self.selected = value
        self.ring = ring
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.accent.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.selected:
            pen = painter.pen()
            pen.setColor(QColor(self.accent.base))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.accent.base))
        inset = 7 if self.selected else 4
        painter.drawEllipse(
            inset, inset, self.width() - inset * 2, self.height() - inset * 2
        )
        painter.end()


class SettingsPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Настройки",
            "Внешний вид, поведение при запуске и параметры сети.",
        )
        self._switches: list[Switch] = []
        self._build_appearance()
        self._build_behaviour()
        self._build_network()
        self._build_danger()
        self.apply_theme()

    # --- внешний вид -----------------------------------------------------

    def _build_appearance(self) -> None:
        card = Card(padding=20, spacing=16)
        card.add(section_label("Оформление"))
        card.add(faint_label("Тема применяется сразу, перезапуск не нужен."))

        themes_row = QHBoxLayout()
        themes_row.setSpacing(12)
        self.theme_cards: list[ThemeCard] = []
        for item in theme.THEMES:
            widget = ThemeCard(item.key, item.title, item.colors)
            widget.picked.connect(self._pick_theme)
            themes_row.addWidget(widget)
            self.theme_cards.append(widget)
        themes_row.addStretch(1)
        card.add_layout(themes_row)

        system_row = QHBoxLayout()
        system_row.setSpacing(10)
        self.btn_system_theme = Button("Как в Windows", variant="ghost")
        self.btn_system_theme.clicked.connect(lambda: self._pick_theme("system"))
        system_row.addWidget(self.btn_system_theme)
        system_row.addStretch(1)
        card.add_layout(system_row)

        card.add(Divider())
        card.add(section_label("Акцентный цвет"))

        accents_row = QHBoxLayout()
        accents_row.setSpacing(10)
        self.accent_dots: list[AccentDot] = []
        for accent in theme.ACCENTS:
            dot = AccentDot(accent)
            dot.picked.connect(self._pick_accent)
            accents_row.addWidget(dot)
            self.accent_dots.append(dot)
        accents_row.addStretch(1)
        card.add_layout(accents_row)

        self.body.addWidget(card)

    def _pick_theme(self, key: str) -> None:
        config.set("theme", key)
        self._apply_theme_globally()
        self._sync_appearance()

    def _pick_accent(self, key: str) -> None:
        config.set("accent", key)
        self._apply_theme_globally()
        self._sync_appearance()

    def _apply_theme_globally(self) -> None:
        window = self.window()
        apply_theme = getattr(window, "apply_theme", None)
        if callable(apply_theme):
            apply_theme()

    def _sync_appearance(self) -> None:
        current_theme = str(config.get("theme"))
        current_accent = str(config.get("accent"))
        accent_color = self.context.color("accent")
        for widget in self.theme_cards:
            widget.set_selected(widget.key == current_theme, accent_color)
        for dot in self.accent_dots:
            dot.set_selected(dot.accent.key == current_accent, accent_color)
        self.btn_system_theme.setProperty(
            "variant", "soft" if current_theme == "system" else "ghost"
        )
        style = self.btn_system_theme.style()
        style.unpolish(self.btn_system_theme)
        style.polish(self.btn_system_theme)

    # --- поведение -------------------------------------------------------

    def _add_switch(self, card: Card, key: str, title: str, description: str,
                    on_change=None) -> Switch:
        switch = Switch(bool(config.get(key)))

        def handler(value: bool) -> None:
            config.set(key, value)
            if on_change is not None:
                on_change(value)

        switch.toggled.connect(handler)
        card.add(SettingRow(title, description, switch))
        self._switches.append(switch)
        return switch

    def _build_behaviour(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Поведение"))

        self._add_switch(
            card, "close_to_tray", "Сворачивать в трей при закрытии",
            "Крестик прячет окно, а программа продолжает работать рядом с часами.",
        )
        card.add(Divider())

        self._add_switch(
            card, "autostart_app", "Запускать вместе с Windows",
            "Создаётся задача планировщика с правами администратора, "
            "поэтому окно UAC при входе появляться не будет.",
            on_change=self._toggle_autostart,
        )
        card.add(Divider())

        self._add_switch(
            card, "start_minimized", "Запускаться свёрнутым в трей",
            "Окно не появится на экране — программа сразу уйдёт в трей.",
        )
        card.add(Divider())

        self._add_switch(
            card, "autorun_last_strategy", "Включать обход при запуске",
            "Последняя выбранная стратегия стартует автоматически. "
            "Для постоянной работы надёжнее режим службы.",
        )
        card.add(Divider())

        self._add_switch(
            card, "confirm_exit_while_running", "Спрашивать при выходе",
            "Предупреждать, если обход работает в режиме процесса и остановится.",
        )
        card.add(Divider())

        self._add_switch(
            card, "warn_about_vpn", "Предупреждать о включённом VPN",
            "Через VPN обход обычно не нужен и может мешать.",
        )
        card.add(Divider())

        self._add_switch(
            card, "diagnostics_autorun", "Запускать диагностику автоматически",
            "Проверки стартуют при первом открытии вкладки «Диагностика».",
        )

        self.body.addWidget(card)

    def _toggle_autostart(self, enabled: bool) -> None:
        import sys

        if not getattr(sys, "frozen", False):
            self.context.warn(
                "Автозапуск настраивается только в установленной версии программы."
            )
            return
        if enabled:
            ok, message = winapi.autostart_enable(
                AUTOSTART_TASK, sys.executable, "--tray"
            )
            if ok:
                self.context.ok("Автозапуск включён")
            else:
                config.set("autostart_app", False)
                self.context.error(f"Не удалось создать задачу автозапуска. {message}")
        else:
            winapi.autostart_disable(AUTOSTART_TASK)
            self.context.ok("Автозапуск выключен")

    # --- сеть ------------------------------------------------------------

    def _build_network(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Сеть и доступ к GitHub"))
        card.add(faint_label(
            "Обновления скачиваются с GitHub. Если он заблокирован, программа "
            "сама переберёт зеркала. Здесь можно задать прокси вручную."
        ))

        self.switch_proxy = Switch(bool(config.get("use_system_proxy", True)))
        self.switch_proxy.toggled.connect(
            lambda value: config.set("use_system_proxy", value)
        )
        self._switches.append(self.switch_proxy)
        card.add(SettingRow(
            "Использовать системный прокси",
            "Берём настройки прокси из Windows и переменных окружения.",
            self.switch_proxy,
        ))
        card.add(Divider())

        proxy_row = QHBoxLayout()
        proxy_row.setSpacing(10)
        self.proxy_input = QLineEdit(str(config.get("custom_proxy", "")))
        self.proxy_input.setPlaceholderText("http://127.0.0.1:8080 — оставьте пустым, если не нужен")
        self.proxy_input.editingFinished.connect(self._save_proxy)
        proxy_row.addWidget(self.proxy_input, 1)

        self.net_spinner = Spinner(16, self.context.color("accent"))
        proxy_row.addWidget(self.net_spinner)

        self.btn_test_net = Button("Проверить связь", variant="soft")
        self.btn_test_net.clicked.connect(self._test_connection)
        proxy_row.addWidget(self.btn_test_net)
        card.add_layout(proxy_row)

        self.net_status = faint_label(f"Текущий режим: {net.connectivity_hint()}.")
        card.add(self.net_status)

        self.body.addWidget(card)

    def _save_proxy(self) -> None:
        value = self.proxy_input.text().strip()
        if config.get("custom_proxy", "") == value:
            return
        config.set("custom_proxy", value)
        self.net_status.setText(f"Текущий режим: {net.connectivity_hint()}.")
        self.context.ok("Настройки прокси сохранены")

    def _test_connection(self) -> None:
        self.btn_test_net.setEnabled(False)
        self.net_spinner.start()
        self.net_status.setText("Проверяем доступ к GitHub…")

        from app.core.constants import UPSTREAM_REPO, UPSTREAM_VERSION_PATH

        url = (
            f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/main/"
            f"{UPSTREAM_VERSION_PATH}"
        )

        worker = Worker(self)
        worker.finished.connect(self._connection_ok)
        worker.failed.connect(self._connection_failed)
        worker.run(net.fetch_text, url)
        self._net_worker = worker

    def _connection_ok(self, payload) -> None:
        self.btn_test_net.setEnabled(True)
        self.net_spinner.stop()
        mirror = str(config.get("preferred_mirror", "")) or "direct"
        titles = {item.key: item.title for item in net.MIRRORS}
        titles["jsdelivr"] = "cdn.jsdelivr.net"
        self.net_status.setText(
            f"Связь есть. Сработал канал: {titles.get(mirror, mirror)}. "
            f"Версия ядра на сервере: {str(payload).strip()}."
        )
        self.context.ok("GitHub доступен")

    def _connection_failed(self, message: str) -> None:
        self.btn_test_net.setEnabled(True)
        self.net_spinner.stop()
        self.net_status.setText(message)
        self.context.error("GitHub недоступен ни напрямую, ни через зеркала")

    # --- сервис ----------------------------------------------------------

    def _build_danger(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Служебное"))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        btn_folder = Button("Папка с настройками", variant="ghost")
        btn_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))
        )
        buttons.addWidget(btn_folder)

        btn_core = Button("Папка ядра zapret", variant="ghost")
        btn_core.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.core_dir())))
        )
        buttons.addWidget(btn_core)

        btn_reset = Button("Сбросить настройки", variant="ghost")
        btn_reset.clicked.connect(self._reset)
        buttons.addWidget(btn_reset)
        buttons.addStretch(1)
        card.add_layout(buttons)

        self.body.addWidget(card)

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "Сброс настроек",
            "Вернуть все настройки программы к значениям по умолчанию?\n"
            "Списки доменов и ядро zapret не пострадают.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        config.reset()
        self._apply_theme_globally()
        self.on_activate()
        self.context.ok("Настройки сброшены")

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_appearance()
        self.proxy_input.setText(str(config.get("custom_proxy", "")))
        self.net_status.setText(f"Текущий режим: {net.connectivity_hint()}.")

    def apply_theme(self) -> None:
        self._sync_appearance()
        self.net_spinner.set_color(self.context.color("accent"))
        for switch in self._switches:
            switch.set_colors(
                self.context.color("accent"),
                self.context.color("border_strong"),
                self.context.color("surface"),
            )
