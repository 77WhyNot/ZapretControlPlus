"""Переиспользуемые виджеты интерфейса."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons


def apply_variant(widget: QWidget, variant: str = "", size: str = "") -> QWidget:
    if variant:
        widget.setProperty("variant", variant)
    if size:
        widget.setProperty("size", size)
    return widget


def restyle(widget: QWidget) -> None:
    """Перечитать QSS после смены динамического свойства."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class Card(QFrame):
    """Панель с рамкой и скруглением."""

    def __init__(self, parent: QWidget | None = None, alt: bool = False,
                 padding: int = 18, spacing: int = 12) -> None:
        super().__init__(parent)
        self.setObjectName("CardAlt" if alt else "Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(spacing)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setFrameShape(QFrame.Shape.NoFrame)


class Badge(QLabel):
    """Небольшая цветная метка состояния."""

    def __init__(self, text: str = "", kind: str = "neutral",
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("badge", kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_kind(self, kind: str) -> None:
        self.setProperty("badge", kind)
        restyle(self)

    def update_state(self, text: str, kind: str) -> None:
        self.setText(text)
        self.set_kind(kind)


class IconLabel(QLabel):
    """Иконка, которая перерисовывается при смене темы."""

    def __init__(self, name: str, color: str, size: int = 20,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setFixedSize(size, size)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self._color = color
        ratio = self.devicePixelRatioF() or 1.0
        self.setPixmap(icons.pixmap(self._name, color, self._size, ratio))

    def set_icon(self, name: str) -> None:
        self._name = name
        self.set_color(self._color)


class Button(QPushButton):
    def __init__(self, text: str = "", variant: str = "", size: str = "",
                 icon_name: str = "", icon_color: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_variant(self, variant, size)
        self._icon_name = icon_name
        if icon_name and icon_color:
            self.set_icon(icon_name, icon_color)

    def set_icon(self, name: str, color: str, size: int = 17) -> None:
        self._icon_name = name
        self.setIcon(icons.icon(name, color, size))
        self.setIconSize(QSize(size, size))


class Switch(QWidget):
    """Анимированный переключатель вместо стандартного QCheckBox."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self._track_on = QColor("#C41E4A")
        self._track_off = QColor("#CDD4DE")
        self._knob = QColor("#FFFFFF")
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def set_colors(self, on: str, off: str, knob: str) -> None:
        self._track_on = QColor(on)
        self._track_off = QColor(off)
        self._knob = QColor(knob)
        self.update()

    def isChecked(self) -> bool:  # noqa: N802 — совместимость с QCheckBox
        return self._checked

    def setChecked(self, value: bool, animate: bool = True) -> None:  # noqa: N802
        if value == self._checked:
            return
        self._checked = value
        if animate:
            self._animation.stop()
            self._animation.setStartValue(self._offset)
            self._animation.setEndValue(1.0 if value else 0.0)
            self._animation.start()
        else:
            self.set_offset(1.0 if value else 0.0)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2

        track = QColor(self._track_off)
        target = QColor(self._track_on)
        blended = QColor(
            int(track.red() + (target.red() - track.red()) * self._offset),
            int(track.green() + (target.green() - track.green()) * self._offset),
            int(track.blue() + (target.blue() - track.blue()) * self._offset),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blended)
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)

        knob_size = self.height() - 6
        travel = self.width() - knob_size - 6
        x = 3 + travel * self._offset
        painter.setBrush(self._knob)
        painter.drawEllipse(QRectF(x, 3, knob_size, knob_size))
        painter.end()


class SettingRow(QWidget):
    """Строка настройки: заголовок, пояснение и управляющий элемент справа."""

    def __init__(self, title: str, description: str = "",
                 control: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        label = QLabel(title)
        label.setStyleSheet("font-weight: 600;")
        text_box.addWidget(label)
        if description:
            hint = QLabel(description)
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            text_box.addWidget(hint)
        layout.addLayout(text_box, 1)

        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control


class StatItem(QWidget):
    """Компактный показатель: подпись сверху, значение снизу."""

    def __init__(self, caption: str, value: str = "—",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._caption = QLabel(caption)
        self._caption.setObjectName("Faint")
        self._value = QLabel(value)
        font = QFont()
        font.setPointSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        self._value.setFont(font)
        layout.addWidget(self._caption)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class Toast(QFrame):
    """Всплывающее уведомление в правом нижнем углу окна."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 11)
        layout.setSpacing(10)
        self._icon = IconLabel("check", "#0E8A5F", 18, self)
        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setMaximumWidth(360)
        layout.addWidget(self._icon)
        layout.addWidget(self._text, 1)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, kind: str = "ok", colors: dict | None = None,
                     timeout: int = 4200) -> None:
        palette = colors or {}
        icon_name = {"ok": "check", "warn": "warning", "error": "cross"}.get(kind, "info")
        color = palette.get(
            {"ok": "success", "warn": "warning", "error": "danger"}.get(kind, "text"),
            "#0E8A5F",
        )
        self._icon.set_icon(icon_name)
        self._icon.set_color(color)
        self._text.setText(text)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(timeout)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            parent.width() - self.width() - 24,
            parent.height() - self.height() - 24,
        )


class Spinner(QWidget):
    """Круговой индикатор занятости."""

    def __init__(self, size: int = 18, color: str = "#C41E4A",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def start(self) -> None:
        self.show()
        self._timer.start(28)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        pen = painter.pen()
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setColor(self._color)
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, 100 * 16)
        painter.end()


def header_row(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return container


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def muted_label(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(wrap)
    return label


def faint_label(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Faint")
    label.setWordWrap(wrap)
    return label


def row(*widgets: QWidget, spacing: int = 10, stretch_last: bool = False) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        stretch = 1 if (stretch_last and index == len(widgets) - 1) else 0
        layout.addWidget(widget, stretch)
    return container


class Worker(QObject):
    """Блокирующая операция в отдельном потоке.

    Сигналы Qt из чужого потока доставляются в поток UI очередью, поэтому
    обработчики можно писать как обычный код интерфейса.
    """

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = None

    def run(self, function: Callable, *args, **kwargs) -> None:
        import threading

        def target() -> None:
            try:
                result = function(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — ошибку показываем пользователю
                self.failed.emit(str(exc))
                return
            self.finished.emit(result)

        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
