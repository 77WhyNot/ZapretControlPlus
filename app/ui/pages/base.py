"""Базовая страница: заголовок и прокручиваемое содержимое."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.widgets import Button, IconLabel, MonoLabel, SerifTitle


class LedeLabel(QLabel):
    """Пояснение под заголовком: строки не длиннее ~680 пикселей.

    Обычный setMaximumWidth компоновка не учитывает, когда считает высоту
    переносов, — и шапка обрезалась сверху. Здесь ширина ограничена в самом
    расчёте высоты.
    """

    LIMIT = 680

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        # QLabel вычитает поля сам — прибавляем их, чтобы текст считался
        # ровно в нужную ширину.
        return super().heightForWidth(min(width, self.LIMIT) + self.contentsMargins().right())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margin = max(0, self.width() - self.LIMIT)
        if self.contentsMargins().right() != margin:
            self.setContentsMargins(0, 0, margin, 0)


class PageHeader(QWidget):
    """Шапка раздела: моноподпись, заголовок Literata с курсивным словом,
    короткое пояснение и рисунок справа."""

    def __init__(self, context: AppContext, title: str, subtitle: str = "",
                 eyebrow: str = "", vignette=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        row = QHBoxLayout(self)
        row.setContentsMargins(40, 22, 40, 10)
        row.setSpacing(28)

        column = QVBoxLayout()
        column.setSpacing(7)
        self.eyebrow = MonoLabel(eyebrow, context, "accent_ink", 11, 0.1, self)
        column.addWidget(self.eyebrow)
        self.eyebrow.setVisible(bool(eyebrow))
        self.title_label = SerifTitle(title, context, 34, self)
        column.addWidget(self.title_label)
        self.subtitle_label = LedeLabel(subtitle, self)
        self.subtitle_label.setObjectName("Lede")
        self.subtitle_label.setWordWrap(True)
        column.addWidget(self.subtitle_label)
        self.subtitle_label.setVisible(bool(subtitle))
        # Пустая компоновка в колонке сжала бы её до минимума: Qt берёт
        # её нулевую предельную ширину. Поэтому — в виджете, который тянется.
        extra_host = QWidget(self)
        extra_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.extra = QHBoxLayout(extra_host)
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(8)
        column.addWidget(extra_host)
        row.addLayout(column, 1)

        self.side = QVBoxLayout()
        self.side.setSpacing(0)
        row.addLayout(self.side)
        self.vignette = None
        if vignette is not None:
            self.set_vignette(vignette)

    def set_vignette(self, widget: QWidget) -> None:
        self.vignette = widget
        widget.setParent(self)
        widget.setFixedWidth(240)
        self.side.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # В узком окне рисунок уступает место тексту.
        if self.vignette is not None:
            self.vignette.setVisible(self.width() >= 820)
        # Перенос строк меняет высоту шапки, а внешняя компоновка об этом не
        # узнаёт сама — без подсказки заголовок обрезался сверху.
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.totalHeightForWidth(self.width())
            if needed > 0 and needed != self.minimumHeight():
                self.setMinimumHeight(needed)


def vignette(context: AppContext, scene_factory) -> QWidget:
    """Маленький рисунок в шапке раздела — без подложки, прямо на бумаге."""
    from app.ui.ink import InkCanvas

    canvas = InkCanvas(scene_factory(), context, plate="", radius=0)
    canvas.setFixedHeight(104)
    return canvas


class Page(QWidget):
    """Общий каркас страницы."""

    def __init__(self, context: AppContext, title: str, subtitle: str = "",
                 parent: QWidget | None = None, eyebrow: str = "",
                 scene=None) -> None:
        # Родитель обязателен с самого начала: виджет без родителя Qt
        # считает окном и успевает мигнуть им на экране.
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        art = vignette(context, scene) if scene is not None else None
        header = PageHeader(context, title, subtitle, eyebrow, art, self)
        # Заголовок прячет TabbedPage: у вкладки раздела он общий, сверху.
        self.header = header
        self.title_label = header.title_label
        self.subtitle_label = header.subtitle_label
        self.eyebrow_label = header.eyebrow
        self.header_extra = header.extra
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
        self.body.setContentsMargins(40, 6, 40, 28)
        self.body.setSpacing(14)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(inner)

        context.theme_changed.connect(self.apply_theme)

    # --- переопределяемое ------------------------------------------------

    def apply_theme(self) -> None:
        """Перекрасить иконки при смене темы."""

    def on_activate(self) -> None:
        """Вызывается при переходе на страницу."""

    # --- помощники -------------------------------------------------------

    def set_eyebrow(self, text: str) -> None:
        self.eyebrow_label.setText(text)
        self.eyebrow_label.setVisible(bool(text))

    def section_texts(self) -> tuple[str, str, str]:
        """Слова для шапки раздела, когда страница — его вкладка."""
        return (self.eyebrow_label.text(), self.title_label.title(),
                self.subtitle_label.text())

    def add_stretch(self) -> None:
        self.body.addStretch(1)


class TabbedPage(QWidget):
    """Раздел с вкладками: «VPN → Подключение | Программы» и подобные.

    Вкладки — обычные страницы, только без собственного заголовка: он у
    раздела один, а справа от него — переключатель. Смена вкладки мягко
    проявляется.
    """

    def __init__(self, context: AppContext, title: str, subtitle: str,
                 tabs: list[tuple[str, str, type]],
                 parent: QWidget | None = None, eyebrow: str = "") -> None:
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = PageHeader(context, title, subtitle, eyebrow, None, self)
        self.header = header
        self.title_label = header.title_label
        self.subtitle_label = header.subtitle_label
        self.eyebrow_label = header.eyebrow

        bar = QFrame(header)
        bar.setObjectName("SegmentBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(3, 3, 3, 3)
        bar_layout.setSpacing(2)
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

        header.side.addStretch(1)
        header.side.addWidget(bar, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

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
        step = 0
        if self._current in self._order:
            step = 1 if self._order.index(key) > self._order.index(self._current) else -1
        self._current = key
        for name, button in self._buttons.items():
            button.setChecked(name == key)
        # Шапка подстраивается под вкладку, если у вкладки свои слова.
        texts = getattr(page, "section_texts", None)
        if callable(texts):
            eyebrow, title, subtitle = texts()
            self.eyebrow_label.setText(eyebrow)
            self.eyebrow_label.setVisible(bool(eyebrow))
            self.title_label.set_title(title)
            self.subtitle_label.setText(subtitle)
            self.subtitle_label.setVisible(bool(subtitle))
        animated = False
        if changed and activate and self.stack.currentWidget() is not None:
            animated = transition(self.stack, lambda: self.stack.setCurrentWidget(page),
                                  self.context.color("bg"), duration=340, slide=0,
                                  shift=14.0 * step)
        else:
            self.stack.setCurrentWidget(page)
        if activate:
            handler = getattr(page, "on_activate", None)
            if callable(handler):
                if animated:
                    QTimer.singleShot(360, handler)
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
