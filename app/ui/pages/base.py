"""Базовая страница: заголовок и прокручиваемое содержимое."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.widgets import Button, IconLabel


class Page(QWidget):
    """Общий каркас страницы."""

    def __init__(self, context: AppContext, title: str, subtitle: str = "",
                 parent: QWidget | None = None) -> None:
        # Родитель обязателен с самого начала: виджет без родителя Qt
        # считает окном и успевает мигнуть им на экране.
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        # Заголовок прячет TabbedPage: у вкладки раздела он общий, сверху.
        self.header = header
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 12)
        header_layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        # Сначала в компоновку, потом видимость: setVisible на виджете
        # без родителя заставляет Qt показать его отдельным окном.
        header_layout.addWidget(self.subtitle_label)
        self.subtitle_label.setVisible(bool(subtitle))

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


class TabbedPage(QWidget):
    """Раздел с вкладками: «VPN → Подключение | Программы» и подобные.

    Вкладки — обычные страницы, только без собственного заголовка: он у
    раздела один, а под ним — переключатель. Смена вкладки мягко проявляется.
    """

    def __init__(self, context: AppContext, title: str, subtitle: str,
                 tabs: list[tuple[str, str, type]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 6)
        header_layout.setSpacing(4)
        self.title_label = QLabel(title, header)
        self.title_label.setObjectName("PageTitle")
        header_layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle, header)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.subtitle_label)
        self.subtitle_label.setVisible(bool(subtitle))

        bar = QFrame(header)
        bar.setObjectName("SegmentBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 4, 4, 4)
        bar_layout.setSpacing(4)
        self._buttons: dict[str, QPushButton] = {}
        self.stack = QStackedWidget(self)
        self._pages: dict[str, QWidget] = {}
        self._order: list[str] = []
        for key, label, factory in tabs:
            button = QPushButton(label, bar)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.select_tab(k))
            bar_layout.addWidget(button)
            self._buttons[key] = button

            page = factory(context, self.stack)
            header_widget = getattr(page, "header", None)
            if header_widget is not None:
                header_widget.hide()
            self.stack.addWidget(page)
            self._pages[key] = page
            self._order.append(key)

        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.addWidget(bar)
        row.addStretch(1)
        header_layout.addLayout(row)

        outer.addWidget(header)
        outer.addWidget(self.stack, 1)
        self._current = ""
        if self._order:
            self.select_tab(self._order[0], activate=False)

    def tab_widget(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def warm_tabs(self) -> None:
        """Подготовить скрытые вкладки заранее, как и сами разделы."""
        size = self.stack.size()
        current = self.stack.currentWidget()
        for page in self._pages.values():
            if page is not current:
                page.resize(size)
                page.grab()

    def current_key(self) -> str:
        return self._current

    def select_tab(self, key: str, activate: bool = True) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        from PySide6.QtCore import QTimer

        from app.ui.widgets import transition

        changed = key != self._current
        self._current = key
        for name, button in self._buttons.items():
            button.setChecked(name == key)
        animated = False
        if changed and activate and self.stack.currentWidget() is not None:
            animated = transition(self.stack, lambda: self.stack.setCurrentWidget(page),
                                  self.context.color("bg"), duration=200, slide=8)
        else:
            self.stack.setCurrentWidget(page)
        if activate:
            handler = getattr(page, "on_activate", None)
            if callable(handler):
                if animated:
                    QTimer.singleShot(220, handler)
                else:
                    handler()

    def on_activate(self) -> None:
        page = self._pages.get(self._current)
        handler = getattr(page, "on_activate", None)
        if callable(handler):
            handler()


class Banner(QFrame):
    """Заметная плашка-предупреждение с необязательной кнопкой."""

    def __init__(self, context: AppContext, icon_name: str, text: str,
                 kind: str = "warn", action_text: str = "",
                 parent: QWidget | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self.context = context
        self.kind = kind
        self.icon_name = icon_name
        self.setObjectName("CardAlt")

        layout = QHBoxLayout(self)
        # Компактная — для постоянных подсказок вроде «обнаружен другой VPN»:
        # она должна быть видна, но не спорить за внимание с главным.
        if compact:
            layout.setContentsMargins(12, 7, 10, 7)
            layout.setSpacing(9)
        else:
            layout.setContentsMargins(16, 13, 16, 13)
            layout.setSpacing(12)

        self.icon = IconLabel(icon_name, self._color(), 16 if compact else 20, self)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter if compact
                         else Qt.AlignmentFlag.AlignTop)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        if compact:
            self.label.setStyleSheet("font-size: 12.5px; background: transparent;")
        layout.addWidget(self.label, 1)

        # Сначала родитель и компоновка, только потом видимость: setVisible
        # на виджете без родителя Qt понимает как «показать отдельным окном»,
        # и на экране мигает пустая кнопка.
        self.action = Button(action_text, variant="soft", parent=self)
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.action.setVisible(bool(action_text))

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
