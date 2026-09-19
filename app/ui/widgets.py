"""Переиспользуемые виджеты интерфейса."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
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
    QLayout,
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


# --- плавность ------------------------------------------------------------


class FrameClock(QObject):
    """Один кадровый таймер на всю программу — вместо таймера у каждой анимации.

    Анимации подписываются на него и сами считают положение по реальному
    времени. Тогда кадр, пришедший с задержкой, просто рисует правильное
    положение, а не «отстаёт на шаг», — движение не спотыкается. Когда
    подписчиков нет или все они скрыты (окно в трее), таймер стоит.
    """

    def __init__(self) -> None:
        super().__init__()
        import weakref

        self._subscribers = weakref.WeakSet()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        # 30 кадров в секунду: пунктир ползёт медленно, и на глаз это так же
        # гладко, как 60, а процессор нагружается вдвое меньше.
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def subscribe(self, widget: QWidget) -> None:
        self._subscribers.add(widget)
        if not self._timer.isActive():
            self._timer.start()

    def unsubscribe(self, widget: QWidget) -> None:
        self._subscribers.discard(widget)
        if not self._subscribers:
            self._timer.stop()

    def wake(self) -> None:
        """Окно снова на экране — продолжить анимации, если они есть."""
        if self._subscribers and not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        drawn = 0
        for widget in list(self._subscribers):
            try:
                if widget.isVisible() and not widget.window().isMinimized():
                    widget.update()
                    drawn += 1
            except RuntimeError:  # виджет уже удалён
                self._subscribers.discard(widget)
        # Ничего не видно (окно в трее или свёрнуто) — таймер засыпает и не
        # будит процессор 60 раз в секунду. Проснётся по wake() или подписке.
        if not drawn:
            self._timer.stop()


_clock: FrameClock | None = None


def frame_clock() -> FrameClock:
    global _clock
    if _clock is None:
        _clock = FrameClock()
    return _clock


def fade_in(widget: QWidget, duration: int = 220, delay: int = 0,
            keep: list | None = None) -> None:
    """Мягко проявить виджет. Эффект снимаем сразу после: он замедляет отрисовку."""
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    if keep is not None:
        keep.append(animation)
    if delay <= 0:
        animation.start()
        return
    # Таймер живёт при виджете: если виджет успели закрыть, запускать анимацию
    # уже некому и нечему — иначе Qt падает на удалённом объекте.
    timer = QTimer(widget)
    timer.setSingleShot(True)
    timer.timeout.connect(animation.start)
    timer.start(delay)


def snapshot(widget: QWidget, background: QColor):
    """Картинка виджета на сплошном фоне — без прозрачных дыр."""
    from PySide6.QtGui import QPixmap

    grabbed = widget.grab()
    result = QPixmap(grabbed.size())
    result.setDevicePixelRatio(grabbed.devicePixelRatio())
    result.fill(background)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, grabbed)
    painter.end()
    return result


class _Transition(QWidget):
    """Кадр перехода: старый вид тает, новый чуть поднимается на место.

    Рисуются только две готовые картинки. Прежде старый кадр таял поверх
    живой страницы, и Qt на каждом кадре перерисовывал её целиком со всеми
    виджетами — отсюда и подлагивание на тяжёлых разделах.
    """

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("Transition")
        self._host = host
        self._before = None
        self._after = None
        self._background = QColor("#000000")
        self._slide = 0.0
        self._progress = 0.0
        # Непрозрачный: под ним Qt ничего не перерисовывает.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()
        # Окно тянут мышкой прямо во время перехода — снимки уже не того
        # размера, поэтому переход честнее оборвать.
        host.installEventFilter(self)

        from PySide6.QtCore import QVariantAnimation

        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.finish)

    def play(self, before, after, background: QColor, duration: int, slide: float) -> None:
        # Слой один на всю жизнь окна: новый виджет Qt каждый раз заново
        # сверял бы со всеми правилами темы, а это лишние миллисекунды щелчка.
        self._before = before
        self._after = after
        self._background = QColor(background)
        self._slide = slide
        self._progress = 0.0
        self.setGeometry(self._host.rect())
        self._animation.setDuration(duration)
        self.show()
        self.raise_()
        self._animation.start()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if (watched is self._host and event.type() == QEvent.Type.Resize
                and self.isVisible()):
            self.finish()
        return False

    def _advance(self, value) -> None:
        self._progress = float(value)
        self.update()

    def finish(self) -> None:
        self._animation.stop()
        self.hide()
        # Картинки размером с окно держать незачем.
        self._before = self._after = None

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._after is None or self._before is None:
            return
        painter = QPainter(self)
        progress = self._progress
        offset = (1.0 - progress) * self._slide
        if offset > 0.01:
            painter.fillRect(self.rect(), self._background)
        painter.drawPixmap(0, int(round(offset)), self._after)
        if progress < 1.0:
            painter.setOpacity(1.0 - progress)
            painter.drawPixmap(0, 0, self._before)
        painter.end()


def transition(host: QWidget, switch: Callable[[], None], background,
               duration: int = 220, slide: float = 10.0) -> bool:
    """Сменить содержимое host плавно: switch() меняет его, а переход рисуется
    поверх из двух снимков. Возвращает True, если переход был."""
    if not host.isVisible() or host.width() < 2 or host.height() < 2:
        switch()
        return False
    background = QColor(background)
    overlay = getattr(host, "_transition_layer", None)
    if overlay is None:
        overlay = _Transition(host)
        host._transition_layer = overlay
    # Снимок берём вместе с недоигранным переходом, если он есть: так новый
    # начнётся ровно с того, что сейчас на экране.
    before = snapshot(host, background)
    overlay.finish()
    switch()
    after = snapshot(host, background)
    overlay.play(before, after, background, duration, slide)
    return True


def confirm(parent: QWidget, title: str, text: str, yes: str = "Да",
            no: str = "Нет", default_yes: bool = True) -> bool:
    """Вопрос «да или нет» в цветах темы.

    Стандартный QMessageBox.question берёт системный белый фон, а цвет
    текста — из темы, и в тёмной теме текст пропадал. Здесь и фон, и кнопки
    свои, а подписи — по-русски.
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    yes_button = box.addButton(yes, QMessageBox.ButtonRole.YesRole)
    no_button = box.addButton(no, QMessageBox.ButtonRole.NoRole)
    apply_variant(yes_button, "primary")
    for button in (yes_button, no_button):
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Кнопки уже отполированы стилем при создании — перечитываем его.
        restyle(button)
    box.setDefaultButton(yes_button if default_yes else no_button)
    box.exec()
    return box.clickedButton() is yes_button


def clear_layout(layout) -> None:
    """Полностью опустошить компоновку.

    Наивная версия удаляет только виджеты, а вложенные компоновки остаются
    и накладываются на новые — интерфейс визуально «наезжает» сам на себя.
    """
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # setParent(None) здесь нельзя: Qt делает виджет отдельным окном,
            # и до отложенного удаления он успевает мигнуть на экране.
            widget.hide()
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            clear_layout(child)
            child.deleteLater()


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
        self._track_on = QColor("#2563EB")
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
        target = self._target()
        was_visible = self.isVisible()
        self.show()
        self.raise_()
        if target is not None:
            if was_visible:
                self.move(target)
            else:
                # Выезжает снизу. Двигаем только положение — это дёшево,
                # в отличие от прозрачности поверх тени.
                from PySide6.QtCore import QPoint

                slide = getattr(self, "_slide", None)
                if slide is None:
                    slide = QPropertyAnimation(self, b"pos", self)
                    slide.setDuration(220)
                    slide.setEasingCurve(QEasingCurve.Type.OutCubic)
                    self._slide = slide
                slide.stop()
                slide.setStartValue(target + QPoint(0, 18))
                slide.setEndValue(target)
                slide.start()
        self._timer.start(timeout)

    def _target(self):
        parent = self.parentWidget()
        if parent is None:
            return None
        from PySide6.QtCore import QPoint

        return QPoint(parent.width() - self.width() - 24,
                      parent.height() - self.height() - 24)

    def _reposition(self) -> None:
        target = self._target()
        if target is not None:
            self.move(target)


class Spinner(QWidget):
    """Круговой индикатор занятости."""

    # Оборотов в секунду: скорость задана временем, а не числом кадров.
    TURNS_PER_SECOND = 1.1

    def __init__(self, size: int = 18, color: str = "#2563EB",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._started = 0.0
        self.setFixedSize(size, size)
        self.hide()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def start(self) -> None:
        import time

        if not self.isVisible():
            self._started = time.perf_counter()
        self.show()
        frame_clock().subscribe(self)

    def stop(self) -> None:
        frame_clock().unsubscribe(self)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        import time

        angle = ((time.perf_counter() - self._started) * 360 * self.TURNS_PER_SECOND) % 360
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        pen = painter.pen()
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setColor(self._color)
        painter.setPen(pen)
        painter.drawArc(rect, int(-angle * 16), 100 * 16)
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


class ElidedLabel(QLabel):
    """Подпись в одну строку: не влезает — обрезается многоточием.

    Обычная подпись без переноса не даёт окну стать уже своей длины, и в
    узком окне страница вылезала за край. Полный текст — в подсказке.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = str(text)
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # Шрифт задаёт тема: после неё ширина текста другая.
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self._elide()

    def _elide(self) -> None:
        room = max(0, self.contentsRect().width())
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, room)
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class FlowLayout(QLayout):
    """Элементы в ряд, а если не влезают — с переносом на следующую строку."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 10) -> None:
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = height = 0
        for item in self._visible():
            hint = item.sizeHint()
            width += hint.width() + (self._gap if width else 0)
            height = max(height, hint.height())
        return QSize(width, height)

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize(0, 0)
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        return size

    def _visible(self) -> list:
        return [item for item in self._items if not item.isEmpty()]

    def _arrange(self, rect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._visible():
            hint = item.sizeHint()
            if line and x + hint.width() > rect.x() + rect.width():
                x = rect.x()
                y += line + self._gap
                line = 0
            if apply:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


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


class _CollapsibleHeader(QFrame):
    """Заголовок раскрывающегося раздела: вся полоса — кнопка."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Collapsible(QWidget):
    """Раскрывающийся раздел: заголовок-кнопка и содержимое, которое
    плавно выезжает. Сюда прячем то, что нужно редко, но должно быть рядом."""

    toggled = Signal(bool)
    MAX_HEIGHT = 16777215

    def __init__(self, title: str, context, expanded: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Не QPushButton: кнопка не учитывает высоту вложенной компоновки
        # и схлопывается в полоску. Обычная рамка с обработкой клика надёжнее.
        self.header = _CollapsibleHeader(self)
        self.header.setObjectName("CollapsibleHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        self.chevron = IconLabel("chevron_right", context.color("text_dim"), 16, self.header)
        row.addWidget(self.chevron)
        self.title_label = QLabel(title, self.header)
        self.title_label.setStyleSheet("font-weight: 600; background: transparent;")
        row.addWidget(self.title_label)
        row.addStretch(1)
        self.hint = QLabel("", self.header)
        self.hint.setObjectName("Faint")
        self.hint.setStyleSheet("background: transparent;")
        row.addWidget(self.hint)
        outer.addWidget(self.header)

        self.content = QWidget(self)
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 2, 0, 0)
        self.body.setSpacing(14)
        outer.addWidget(self.content)
        self.content.setMaximumHeight(self.MAX_HEIGHT if expanded else 0)
        self.content.setVisible(expanded)

        self._animation = QPropertyAnimation(self.content, b"maximumHeight", self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._animation_done)
        self._sync_chevron()

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    # Выше этой высоты содержимое раскрывается без анимации высоты: каждый
    # её кадр заново раскладывает всё содержимое, и длинные списки дёргались.
    HEAVY_HEIGHT = 320

    def set_expanded(self, value: bool, animate: bool = True) -> None:
        if value == self._expanded:
            return
        self._expanded = value
        self._animation.stop()
        heavy = self.content.sizeHint().height() > self.HEAVY_HEIGHT
        if not animate:
            self.content.setMaximumHeight(self.MAX_HEIGHT if value else 0)
            self.content.setVisible(value)
        elif heavy:
            # Раскладка — один раз, а плавность даёт «вуаль» цвета фона,
            # которая тает поверх содержимого: её отрисовка почти бесплатна.
            self.content.setMaximumHeight(self.MAX_HEIGHT if value else 0)
            self.content.setVisible(value)
            if value:
                self._veil()
        elif value:
            self.content.setMaximumHeight(0)
            self.content.setVisible(True)
            self._animation.setStartValue(0)
            self._animation.setEndValue(self.content.sizeHint().height())
            self._animation.start()
        else:
            self._animation.setStartValue(self.content.height())
            self._animation.setEndValue(0)
            self._animation.start()
        self._sync_chevron()
        self.toggled.emit(value)

    def _animation_done(self) -> None:
        if self._expanded:
            self.content.setMaximumHeight(self.MAX_HEIGHT)
        else:
            self.content.setVisible(False)

    def _veil(self, duration: int = 240) -> None:
        from PySide6.QtCore import QVariantAnimation

        veil = QWidget(self.content)
        veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        veil.setGeometry(0, 0, self.content.width() or self.width(),
                         self.content.sizeHint().height())
        base = QColor(self.context.color("bg", "#F4F6F9"))
        veil.show()
        veil.raise_()

        def paint(alpha) -> None:
            veil.setStyleSheet(
                f"background: rgba({base.red()}, {base.green()}, {base.blue()}, "
                f"{int(alpha)});"
            )

        fade = QVariantAnimation(veil)
        fade.setDuration(duration)
        fade.setStartValue(255.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.valueChanged.connect(paint)
        fade.finished.connect(veil.deleteLater)
        paint(255)
        fade.start()

    def _sync_chevron(self) -> None:
        self.chevron.set_icon("chevron_down" if self._expanded else "chevron_right")

    def apply_theme(self) -> None:
        self.chevron.set_color(self.context.color("text_dim"))
