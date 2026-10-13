"""Оболочка окна: заголовок, закладки разделов и смена темы «волной».

Закладки сверху, как у блокнота: активная — цвета страницы и сливается
с ней, под названием глиняная точка. Точка переезжает к новой закладке.
Если окно узкое, у закладок остаются одни значки, а редкие разделы уходят
в «Ещё».
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from app.core.constants import APP_EDITION, APP_NAME, APP_VERSION
from app.ui import fonts, icons
from app.ui.ink import NoiseField, expo_out, parse_path

TITLE_HEIGHT = 40
TABS_HEIGHT = 46

# Значки закладок: рисованные, в сетке 20×20 (из макета).
TAB_ICONS = {
    "home": "M3 10 L10 4 L17 10 M5 9 L5 16 L15 16 L15 9",
    "strategies": "M10 17 L10 9 M10 11 C 6 11, 4 8, 4 5 C 8 5, 10 7, 10 11 "
                  "M10 9 C 10 6, 12 4, 16 4 C 16 7, 14 9, 10 9",
    "vpn": "M4 17 L4 9 C 4 4, 16 4, 16 9 L16 17 M2 17 L18 17",
    "telegram": "M3 12 C 6 7, 9 7, 10 11 C 11 7, 14 7, 17 12 M9 13 C 9 11, 11 11, 11 13",
    "dns": "M10 18 L10 3 M10 5 L15 5 L17 7 L15 9 L10 9 M10 11 L5 11 L3 13 L5 15 L10 15",
    "diagnostics": "M13.5 8.5 A5 5 0 1 1 3.5 8.5 A5 5 0 1 1 13.5 8.5 Z M12.2 12.2 L17 17",
    "settings": "M13 10 A3 3 0 1 1 7 10 A3 3 0 1 1 13 10 Z M10 2.5 L10 4.5 M10 15.5 L10 17.5 "
                "M2.5 10 L4.5 10 M15.5 10 L17.5 10 M4.7 4.7 L6.1 6.1 M13.9 13.9 L15.3 15.3 "
                "M4.7 15.3 L6.1 13.9 M13.9 6.1 L15.3 4.7",
    "speed": "M3 14 A7 7 0 1 1 17 14 M10 14 L13 8",
    "lists": "M5 3 L15 3 L15 17 L5 17 Z M8 7 L12 7 M8 10 L12 10 M8 13 L11 13",
    "about": "M3 6 L17 6 L17 15 L3 15 Z M3 6 L10 11 L17 6",
}

_PATHS: dict[str, QPainterPath] = {}


def tab_icon_path(key: str) -> QPainterPath:
    path = _PATHS.get(key)
    if path is None:
        path = parse_path(TAB_ICONS.get(key, TAB_ICONS["home"]))
        _PATHS[key] = path
    return path


def draw_tab_icon(painter: QPainter, key: str, rect: QRectF, color: QColor,
                  width: float = 1.6) -> None:
    painter.save()
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / 20.0, rect.height() / 20.0)
    pen = QPen(color)
    pen.setWidthF(width * 20.0 / rect.width())
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(tab_icon_path(key))
    painter.restore()


# =========================================================================
# Знак программы
# =========================================================================


class LogoMark(QWidget):
    """Росток с глиняной точкой — знак ZapretCtrl."""

    PATH = ("M10 18 L10 9 M10 11 C 6 11, 4 8, 4 5 C 8 5, 10 7, 10 11 "
            "M10 9 C 10 6, 12 4, 16 4 C 16 7, 14 9, 10 9")

    def __init__(self, context, size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setFixedSize(size, size)
        self._path = parse_path(self.PATH)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(self.width() / 20.0, self.height() / 20.0)
        pen = QPen(QColor(self.context.color("ink")))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(self._path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.context.color("clay")))
        painter.drawEllipse(QPointF(16, 4), 2.2, 2.2)
        painter.end()


class StateDot(QWidget):
    """Точка состояния в заголовке: олива — работает, серая — выключено."""

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.on = False
        self.setFixedSize(8, 8)

    def set_on(self, on: bool) -> None:
        if on != self.on:
            self.on = on
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.context.color("ok" if self.on else "decor")))
        painter.drawEllipse(QRectF(1, 1, 6, 6))
        painter.end()


# =========================================================================
# Заголовок окна
# =========================================================================


class TitleBar(QWidget):
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    theme_toggle_requested = Signal()

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_HEIGHT)
        self.context = context

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(10)

        self.logo = LogoMark(context, 18, self)
        layout.addWidget(self.logo)

        title = QLabel(APP_NAME, self)
        title.setObjectName("TitleText")
        layout.addWidget(title)

        version = QLabel(f"{APP_VERSION} {APP_EDITION}".strip(), self)
        version.setObjectName("TitleVersion")
        layout.addWidget(version)

        layout.addSpacing(10)
        self.state_dot = StateDot(context, self)
        layout.addWidget(self.state_dot)
        self.state_label = QLabel("", self)
        self.state_label.setObjectName("TitleState")
        layout.addWidget(self.state_label)

        layout.addStretch(1)

        self.btn_theme = self._window_button("moon", "WinButton")
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.clicked.connect(self.theme_toggle_requested.emit)
        layout.addWidget(self.btn_theme)
        layout.addSpacing(4)

        self.btn_min = self._window_button("minimize", "WinButton")
        self.btn_max = self._window_button("maximize", "WinButton")
        self.btn_close = self._window_button("close", "WinClose")
        self.btn_min.setToolTip("Свернуть")
        self.btn_max.setToolTip("Развернуть")
        self.btn_close.setToolTip("Закрыть")
        self.btn_min.clicked.connect(self.minimize_requested.emit)
        self.btn_max.clicked.connect(self.maximize_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)
        for button in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(button)

        context.theme_changed.connect(self.apply_theme)
        context.status_changed.connect(lambda _status: self.refresh_state())
        context.vpn_status_changed.connect(lambda _status: self.refresh_state())

    def _window_button(self, icon_name: str, object_name: str) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName(object_name)
        button.setProperty("iconName", icon_name)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setIcon(icons.icon(icon_name, self.context.color("ink3"), 15))
        button.setIconSize(icons.icon_size(15))
        return button

    def apply_theme(self) -> None:
        for button in (self.btn_min, self.btn_max, self.btn_close):
            name = str(button.property("iconName"))
            button.setIcon(icons.icon(name, self.context.color("ink3"), 15))
        dark = self.context.is_dark
        self.btn_theme.setProperty("iconName", "sun" if dark else "moon")
        self.btn_theme.setIcon(icons.icon("sun" if dark else "moon", self.context.color("ink3"), 15))
        self.btn_theme.setToolTip("Светлая тема — бумага" if dark else "Тёмная тема — ночь")
        self.logo.update()
        self.state_dot.update()

    def set_maximized(self, maximized: bool) -> None:
        name = "restore" if maximized else "maximize"
        self.btn_max.setProperty("iconName", name)
        self.btn_max.setToolTip("Восстановить" if maximized else "Развернуть")
        self.btn_max.setIcon(icons.icon(name, self.context.color("ink3"), 15))

    def refresh_state(self) -> None:
        status = self.context.status
        vpn = self.context.vpn_status
        parts = []
        if status.running:
            parts.append(f"обход работает · {status.mode_label}")
        if vpn is not None and getattr(vpn, "running", False):
            server = getattr(vpn, "server", "")
            parts.append(f"VPN плывёт через {server}" if server else "VPN включён")
        self.state_dot.set_on(bool(parts))
        self.state_label.setText(" · ".join(parts) if parts else "обход выключен")

    def is_drag_zone(self, position) -> bool:
        child = self.childAt(position)
        return not isinstance(child, QPushButton)


# =========================================================================
# Закладки
# =========================================================================


class _Tab:
    def __init__(self, key: str, title: str, mini: bool) -> None:
        self.key = key
        self.title = title
        self.mini = mini
        self.rect = QRectF()
        self.visible = True
        self.icon_only = False


class TabBar(QWidget):
    """Закладки разделов. Рисуются сами: так они ведут себя как бумага."""

    selected = Signal(str)

    def __init__(self, context, primary, extra, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TABS_HEIGHT)
        self.setMouseTracking(True)
        self.context = context
        self.tabs = [_Tab(k, t, False) for k, t, *_ in primary]
        self.tabs += [_Tab(k, t.split()[0] if k != "about" else "О программе", True)
                      for k, t, *_ in extra]
        self._titles_full = {k: t for k, t, *_ in list(primary) + list(extra)}
        self.current = ""
        self._hover = ""
        self._pressed = ""
        self._more_rect = QRectF()
        self._more_visible = False
        self._dot_from = QPointF()
        self._dot_to = QPointF()
        self._dot_progress = 1.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(520)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._advance)
        self._font_main = fonts.sans(13.5, 500)
        self._font_mini = fonts.sans(12.5, 500)
        context.theme_changed.connect(self.update)

    # --- раскладка ------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_tabs()

    def _text_width(self, tab: _Tab) -> float:
        from PySide6.QtGui import QFontMetricsF

        metrics = QFontMetricsF(self._font_mini if tab.mini else self._font_main)
        return metrics.horizontalAdvance(tab.title)

    def _layout_tabs(self) -> None:
        left, right = 18.0, self.width() - 18.0
        top, height = 8.0, TABS_HEIGHT - 8.0
        primary = [t for t in self.tabs if not t.mini]
        minis = [t for t in self.tabs if t.mini]

        def widths(icon_only: bool) -> list[float]:
            result = []
            for tab in primary:
                text = 0 if icon_only else self._text_width(tab) + 7
                result.append(13 + 15 + text + 13)
            return result

        mini_widths = [self._text_width(t) + 20 for t in minis]
        gap = 2.0
        for mode in ("full", "more", "icons"):
            icon_only = mode == "icons"
            main = widths(icon_only)
            need = sum(main) + gap * len(main)
            if mode == "full":
                need += 24 + sum(mini_widths) + gap * len(minis)
            else:
                need += 24 + 64
            if need <= right - left or mode == "icons":
                break
        x = left
        for tab, w in zip(primary, main):
            tab.rect = QRectF(x, top, w, height)
            tab.icon_only = icon_only
            tab.visible = True
            x += w + gap
        self._more_visible = mode != "full"
        if mode == "full":
            x = right - sum(mini_widths) - gap * (len(minis) - 1)
            for tab, w in zip(minis, mini_widths):
                tab.rect = QRectF(x, top, w, height)
                tab.visible = True
                x += w + gap
            self._more_rect = QRectF()
        else:
            for tab in minis:
                tab.visible = False
            self._more_rect = QRectF(right - 64, top, 64, height)
        self._snap_dot()
        self.update()

    def _tab(self, key: str) -> _Tab | None:
        return next((t for t in self.tabs if t.key == key), None)

    def _anchor(self, key: str) -> QPointF:
        tab = self._tab(key)
        if tab is None:
            return QPointF()
        rect = tab.rect if tab.visible else self._more_rect
        return QPointF(rect.center().x(), rect.bottom() - 5.5)

    def _snap_dot(self) -> None:
        if self.current:
            self._dot_from = self._dot_to = self._anchor(self.current)
            self._dot_progress = 1.0

    # --- выбор ----------------------------------------------------------

    def set_current(self, key: str, animate: bool = True) -> None:
        if key == self.current:
            return
        start = self._dot_position()
        self.current = key
        target = self._anchor(key)
        if not animate or start.isNull() or not self.isVisible():
            self._dot_from = self._dot_to = target
            self._dot_progress = 1.0
        else:
            self._dot_from = start
            self._dot_to = target
            self._dot_progress = 0.0
            self._animation.stop()
            self._animation.start()
        self.update()

    def index_of(self, key: str) -> int:
        for index, tab in enumerate(self.tabs):
            if tab.key == key:
                return index
        return -1

    def _advance(self, value) -> None:
        self._dot_progress = float(value)
        self.update()

    def _dot_position(self) -> QPointF:
        t = expo_out(self._dot_progress)
        return self._dot_from + (self._dot_to - self._dot_from) * t

    # --- мышь -----------------------------------------------------------

    def _hit(self, pos) -> str:
        for tab in self.tabs:
            if tab.visible and tab.rect.contains(pos):
                return tab.key
        if self._more_visible and self._more_rect.contains(pos):
            return "__more__"
        return ""

    def is_drag_zone(self, pos) -> bool:
        return not self._hit(QPointF(pos))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        key = self._hit(event.position())
        if key != self._hover:
            self._hover = key
            self.setCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor)
            tab = self._tab(key)
            self.setToolTip(self._titles_full.get(key, "") if tab and tab.icon_only else "")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._hit(event.position())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            key = self._hit(event.position())
            if key and key == self._pressed:
                if key == "__more__":
                    self._show_more()
                else:
                    self.selected.emit(key)
        self._pressed = ""
        super().mouseReleaseEvent(event)

    def _show_more(self) -> None:
        menu = QMenu(self)
        for tab in self.tabs:
            if tab.mini:
                action = menu.addAction(self._titles_full.get(tab.key, tab.title))
                action.triggered.connect(lambda _=False, k=tab.key: self.selected.emit(k))
        point = self.mapToGlobal(self._more_rect.bottomLeft().toPoint())
        menu.exec(point)

    # --- рисование ------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.context
        line = QColor(c.color("border"))
        # Нижняя граница полосы — под активной закладкой она прерывается.
        painter.fillRect(QRectF(0, self.height() - 1, self.width(), 1), line)

        for tab in self.tabs:
            if not tab.visible:
                continue
            active = tab.key == self.current
            hover = tab.key == self._hover and not active
            rect = tab.rect
            if active or hover:
                path = QPainterPath()
                r = 10.0
                bottom = rect.bottom() + (1 if active else 0)
                path.moveTo(rect.left(), bottom)
                path.lineTo(rect.left(), rect.top() + r)
                path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
                path.lineTo(rect.right() - r, rect.top())
                path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
                path.lineTo(rect.right(), bottom)
                fill = QColor(c.color("bg") if active else c.color("card"))
                painter.fillPath(path, fill)
                if active:
                    pen = QPen(line)
                    pen.setWidthF(1.0)
                    painter.setPen(pen)
                    painter.drawPath(path)
            color = QColor(c.color("ink") if (active or hover) else c.color("ink3"))
            font = self._font_mini if tab.mini else self._font_main
            painter.setFont(font)
            x = rect.left() + (10 if tab.mini else 13)
            if not tab.mini:
                icon_rect = QRectF(x, rect.center().y() - 8.5, 15, 15)
                if tab.icon_only:
                    icon_rect.moveLeft(rect.center().x() - 7.5)
                draw_tab_icon(painter, tab.key, icon_rect, color)
                x += 15 + 7
            if not tab.icon_only:
                painter.setPen(color)
                metrics = painter.fontMetrics()
                baseline = rect.center().y() - 1 + (metrics.ascent() - metrics.descent()) / 2
                painter.drawText(QPointF(x, baseline), tab.title)

        if self._more_visible:
            rect = self._more_rect
            more_active = any(t.mini and t.key == self.current for t in self.tabs)
            hover = self._hover == "__more__"
            if hover:
                path = QPainterPath()
                path.addRoundedRect(rect.adjusted(0, 0, 0, 10), 10, 10)
                painter.save()
                painter.setClipRect(rect)
                painter.fillPath(path, QColor(c.color("card")))
                painter.restore()
            painter.setFont(self._font_mini)
            painter.setPen(QColor(c.color("ink") if (hover or more_active) else c.color("ink3")))
            metrics = painter.fontMetrics()
            text = "Ещё ▾"
            painter.drawText(QPointF(rect.center().x() - metrics.horizontalAdvance(text) / 2,
                                     rect.center().y() - 1 + (metrics.ascent() - metrics.descent()) / 2),
                             text)

        # Глиняная точка под активной закладкой.
        if self.current:
            dot = self._dot_position()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("clay")))
            # В полёте точка чуть вытягивается — как капля.
            stretch = 1.0 + 1.6 * math.sin(math.pi * min(1.0, self._dot_progress * 1.6)) \
                if self._dot_progress < 1.0 else 1.0
            painter.drawEllipse(dot, 2.5 * stretch, 2.5)
        painter.end()


# =========================================================================
# Смена темы: новая тема разливается кругом от кнопки
# =========================================================================


class ThemeWash(QWidget):
    """Новый вид окна проступает кругом с неровным краем, как краска."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._before = None
        self._after = None
        self._origin = QPointF()
        self._progress = 0.0
        self._radius = 0.0
        self._edge = self._make_edge()
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(760)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self._finish)
        self.hide()

    @staticmethod
    def _make_edge() -> list[float]:
        noise = NoiseField(seed=7, freq=0.9, amp=1.0, octaves=2)
        return [1.0 + 0.05 * noise.at(math.cos(a), math.sin(a))[0]
                for a in (k * math.tau / 96 for k in range(96))]

    def play(self, before, after, origin: QPointF) -> None:
        self._before = before
        self._after = after
        self._origin = origin
        w, h = self.parentWidget().width(), self.parentWidget().height()
        corners = [QPointF(0, 0), QPointF(w, 0), QPointF(0, h), QPointF(w, h)]
        self._radius = max(math.hypot(p.x() - origin.x(), p.y() - origin.y())
                           for p in corners) * 1.12
        self.setGeometry(self.parentWidget().rect())
        self._progress = 0.0
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.start()

    def _advance(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _finish(self) -> None:
        self.hide()
        self._before = self._after = None

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._before is None or self._after is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self._before)
        radius = self._radius * expo_out(self._progress * 1.05)
        if radius > 0.5:
            spin = self._progress * 0.6
            points = []
            count = len(self._edge)
            for k, wobble in enumerate(self._edge):
                angle = k * math.tau / count + spin
                r = radius * wobble
                points.append(QPointF(self._origin.x() + r * math.cos(angle),
                                      self._origin.y() + r * math.sin(angle)))
            clip = QPainterPath()
            clip.addPolygon(QPolygonF(points))
            clip.closeSubpath()
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, self._after)
        painter.end()


def cursor_in(widget: QWidget) -> QPointF:
    return QPointF(widget.mapFromGlobal(QCursor.pos()))
