"""Страница «DNS»: Smart DNS для обхода гео-ограничений."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core import dnsctl
from app.ui.context import AppContext
from app.ui.pages.base import Page
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


class PresetCard(QFrame):
    """Карточка сервиса DNS."""

    chosen = Signal(str)

    def __init__(self, context: AppContext, preset: dnsctl.DnsPreset,
                 active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.preset = preset
        self.active = active
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(preset.title)
        self.title.setStyleSheet("font-weight: 600; font-size: 14px;")
        head.addWidget(self.title)
        self.badge = Badge("включён", "accent")
        self.badge.setVisible(active)
        head.addWidget(self.badge)
        head.addStretch(1)
        if preset.doh:
            head.addWidget(Badge("шифрование", "neutral"))
        layout.addLayout(head)

        layout.addWidget(faint_label(preset.description))

        self.addresses = QLabel(preset.label)
        self.addresses.setProperty("role", "mono")
        layout.addWidget(self.addresses)

        if preset.site:
            link = QLabel(f'<a href="{preset.site}">Сайт сервиса</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet(f"color: {context.color('accent_text')};")
            layout.addWidget(link)

        self.apply_theme()

    def set_active(self, value: bool) -> None:
        self.active = value
        self.badge.setVisible(value)
        self.apply_theme()

    def apply_theme(self) -> None:
        self.addresses.setStyleSheet(f"color: {self.context.color('text_faint')};")
        if self.active:
            accent = self.context.color("accent")
            self.setStyleSheet(
                f"QFrame#Card {{ background: {self.context.color('accent_soft')}; "
                f"border: 1px solid {accent}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#Card {{ background: {self.context.color('surface')}; "
                f"border: 1px solid {self.context.color('border')}; "
                f"border-radius: 12px; }}"
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.preset.key)
        super().mouseReleaseEvent(event)


class DnsPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "DNS",
            "Smart DNS отдаёт другой адрес сервисам, которые режут доступ по "
            "стране. Работает вместе с zapret и не мешает VPN.",
        )
        self._cards: list[PresetCard] = []
        self._busy = False

        self._build_status()
        self._build_presets()
        self.apply_theme()

    # --- состояние -------------------------------------------------------

    def _build_status(self) -> None:
        card = Card(padding=20, spacing=13)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(section_label("Сейчас"))
        head.addStretch(1)
        self.spinner = Spinner(16, self.context.color("accent"))
        head.addWidget(self.spinner)
        self.btn_restore = Button("Вернуть как было", variant="ghost")
        self.btn_restore.clicked.connect(self._restore)
        head.addWidget(self.btn_restore)
        card.add_layout(head)

        self.adapters_host = QWidget()
        self.adapters_layout = QVBoxLayout(self.adapters_host)
        self.adapters_layout.setContentsMargins(0, 0, 0, 0)
        self.adapters_layout.setSpacing(7)
        card.add(self.adapters_host)

        card.add(Divider())
        card.add(faint_label(
            "Если включён VPN, он использует собственный DNS внутри туннеля — "
            "системные настройки на туннельный трафик тогда не влияют."
        ))

        self.body.addWidget(card)

    def _refresh_adapters(self) -> None:
        clear_layout(self.adapters_layout)

        adapters = dnsctl.adapters()
        if not adapters:
            self.adapters_layout.addWidget(
                faint_label("Активных сетевых подключений не найдено.")
            )
            return

        for adapter in adapters:
            line = QWidget()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)

            dot = QLabel("●")
            token = "success" if adapter.up else "text_faint"
            dot.setStyleSheet(f"color: {self.context.color(token)}; font-size: 10px;")
            row.addWidget(dot)

            name = QLabel(adapter.name)
            name.setStyleSheet("font-weight: 600;")
            row.addWidget(name)
            row.addStretch(1)

            servers = QLabel(adapter.servers_label)
            servers.setProperty("role", "mono")
            servers.setStyleSheet(f"color: {self.context.color('text_dim')};")
            row.addWidget(servers)

            row.addWidget(Badge("авто" if adapter.automatic else "вручную",
                                "neutral" if adapter.automatic else "accent"))
            self.adapters_layout.addWidget(line)

        self.btn_restore.setVisible(dnsctl.has_backup())

    # --- пресеты ---------------------------------------------------------

    def _build_presets(self) -> None:
        card = Card(padding=20, spacing=13)
        card.add(section_label("Выберите сервис"))
        card.add(faint_label(
            "Настройки применяются ко всем активным подключениям. "
            "Исходные значения сохраняются — вернуть их можно одной кнопкой."
        ))

        current = dnsctl.current_preset()
        for preset in dnsctl.PRESETS:
            item = PresetCard(self.context, preset, preset.key == current)
            item.chosen.connect(self._apply)
            card.add(item)
            self._cards.append(item)

        self.body.addWidget(card)

    def _apply(self, key: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.spinner.start()

        worker = Worker(self)
        worker.finished.connect(self._applied)
        worker.failed.connect(self._failed)
        worker.run(dnsctl.apply_preset, key)
        self._worker = worker

    def _applied(self, message) -> None:
        self._busy = False
        self.spinner.stop()
        self.context.ok(str(message))
        self._sync()

    def _failed(self, message: str) -> None:
        self._busy = False
        self.spinner.stop()
        self.context.error(str(message))
        self._sync()

    def _restore(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._applied)
        worker.failed.connect(self._failed)
        worker.run(dnsctl.restore)
        self._worker = worker

    def _sync(self) -> None:
        current = dnsctl.current_preset()
        for card in self._cards:
            card.set_active(card.preset.key == current)
        self._refresh_adapters()

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._sync()

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
        for card in self._cards:
            card.apply_theme()
