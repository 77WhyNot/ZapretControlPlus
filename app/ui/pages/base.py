"""Базовая страница: заголовок и прокручиваемое содержимое."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.widgets import Button, IconLabel


class Page(QWidget):
    """Общий каркас страницы."""

    def __init__(self, context: AppContext, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 12)
        header_layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        header_layout.addWidget(self.subtitle_label)

        self.header_extra = QHBoxLayout()
        self.header_extra.setContentsMargins(0, 6, 0, 0)
        self.header_extra.setSpacing(8)
        header_layout.addLayout(self.header_extra)

        outer.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer.addWidget(self.scroll, 1)

        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(28, 4, 28, 28)
        self.body.setSpacing(16)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(inner)

        context.theme_changed.connect(self.apply_theme)

    # --- переопределяемое ------------------------------------------------

    def apply_theme(self) -> None:
        """Перекрасить иконки при смене темы."""

    def on_activate(self) -> None:
        """Вызывается при переходе на страницу."""

    # --- помощники -------------------------------------------------------

    def add_stretch(self) -> None:
        self.body.addStretch(1)


class Banner(QFrame):
    """Заметная плашка-предупреждение с необязательной кнопкой."""

    def __init__(self, context: AppContext, icon_name: str, text: str,
                 kind: str = "warn", action_text: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.kind = kind
        self.icon_name = icon_name
        self.setObjectName("CardAlt")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(12)

        self.icon = IconLabel(icon_name, self._color(), 20, self)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)

        self.action = Button(action_text, variant="soft")
        self.action.setVisible(bool(action_text))
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)

        context.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    def _color(self) -> str:
        mapping = {"warn": "warning", "error": "danger", "ok": "success"}
        return self.context.color(mapping.get(self.kind, "accent"))

    def apply_theme(self) -> None:
        color = self._color()
        self.icon.set_color(color)
        background = {
            "warn": "warning_bg", "error": "danger_bg", "ok": "success_bg",
        }.get(self.kind, "accent_soft")
        self.setStyleSheet(
            f"QFrame#CardAlt {{ background: {self.context.color(background)}; "
            f"border: 1px solid {color}; border-radius: 12px; }}"
        )

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.apply_theme()


class StatusIcon(IconLabel):
    """Иконка результата проверки: галочка / восклицательный знак / крест."""

    MAPPING = {
        "ok": ("check", "success"),
        "warn": ("warning", "warning"),
        "error": ("cross", "danger"),
    }

    def __init__(self, context: AppContext, status: str = "ok", size: int = 18,
                 parent: QWidget | None = None) -> None:
        name, token = self.MAPPING.get(status, self.MAPPING["ok"])
        super().__init__(name, context.color(token), size, parent)
        self.context = context
        self.status = status

    def set_status(self, status: str) -> None:
        self.status = status
        name, token = self.MAPPING.get(status, self.MAPPING["ok"])
        self.set_icon(name)
        self.set_color(self.context.color(token))
