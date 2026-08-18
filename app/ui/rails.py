"""Схема маршрутов: три пути, по активным бежит пунктир.

Это главный элемент интерфейса. Он отвечает на единственный вопрос, ради
которого программу открывают: куда сейчас идёт мой трафик.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.context import AppContext

DASH_PERIOD = 26.0
TRACK_HEIGHT = 4


class LaneTrack(QWidget):
    """Полоса пути. Когда активна — по ней движется пунктир."""

    def __init__(self, color: str, idle_color: str, active: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.idle_color = QColor(idle_color)
        self.active = active
        self._phase = 0.0
        self.setMinimumHeight(14)
        self.setMinimumWidth(80)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        if active:
            self._timer.start(40)

    def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        if active:
            self._timer.start(40)
        else:
            self._timer.stop()
        self.update()

    def set_colors(self, color: str, idle_color: str) -> None:
        self.color = QColor(color)
        self.idle_color = QColor(idle_color)
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 1.4) % DASH_PERIOD
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        middle = self.height() / 2

        base = QPen(self.color if self.active else self.idle_color)
        base.setWidth(TRACK_HEIGHT)
        base.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(base)
        painter.drawLine(0, int(middle), self.width(), int(middle))

        if not self.active:
            painter.end()
            return

        flow = QPen(QColor(255, 255, 255, 170))
        flow.setWidth(TRACK_HEIGHT)
        flow.setCapStyle(Qt.PenCapStyle.RoundCap)
        flow.setStyle(Qt.PenStyle.CustomDashLine)
        # Пунктир задаётся в единицах толщины пера.
        flow.setDashPattern([9 / TRACK_HEIGHT, 17 / TRACK_HEIGHT])
        flow.setDashOffset(-self._phase / TRACK_HEIGHT)
        painter.setPen(flow)
        painter.drawLine(0, int(middle), self.width(), int(middle))
        painter.end()


class LaneChip(QLabel):
    """Ярлык программы или сервиса на пути."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def apply_colors(self, background: str, border: str, text: str) -> None:
        self.setStyleSheet(
            f"background: {background}; border: 1px solid {border}; color: {text};"
            "border-radius: 6px; padding: 3px 9px; font-size: 11.5px;"
        )


class LaneRow(QWidget):
    """Один путь: подпись, полоса и ярлыки того, что по нему идёт."""

    clicked = Signal(str)

    def __init__(self, context: AppContext, key: str, title: str,
                 color_token: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.key = key
        self.color_token = color_token
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(12)

        self.label = QLabel(title.upper())
        self.label.setFixedWidth(104)
        font = QFont("Bahnschrift", 10)
        font.setWeight(QFont.Weight.DemiBold)
        self.label.setFont(font)
        layout.addWidget(self.label)

        self.track = LaneTrack(
            context.color(color_token), context.color("border_strong")
        )
        layout.addWidget(self.track, 1)

        self.chips_host = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_host)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(5)
        layout.addWidget(self.chips_host, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme()

    def set_active(self, active: bool) -> None:
        self.track.set_active(active)
        self.label.setStyleSheet(
            f"color: {self.context.color(self.color_token)};" if active
            else f"color: {self.context.color('text_faint')};"
        )

    def set_chips(self, items: list[str]) -> None:
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for text in items[:4]:
            chip = LaneChip(text)
            chip.apply_colors(
                self.context.color("surface_alt"),
                self.context.color("border_strong"),
                self.context.color("text_dim"),
            )
            self.chips_layout.addWidget(chip)

    def apply_theme(self) -> None:
        self.track.set_colors(
            self.context.color(self.color_token), self.context.color("border_strong")
        )
        self.set_active(self.track.active)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class RailsBoard(QWidget):
    """Три пути целиком, с подписями «Программы» и «Интернет»."""

    lane_clicked = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        caption = QHBoxLayout()
        caption.setContentsMargins(0, 0, 0, 6)
        self.left_caption = QLabel("ПРОГРАММЫ")
        self.right_caption = QLabel("ИНТЕРНЕТ")
        small = QFont("Bahnschrift", 9)
        small.setWeight(QFont.Weight.DemiBold)
        for label in (self.left_caption, self.right_caption):
            label.setFont(small)
        caption.addWidget(self.left_caption)
        caption.addStretch(1)
        caption.addWidget(self.right_caption)
        layout.addLayout(caption)

        self.lanes: dict[str, LaneRow] = {}
        for key, title, token in (
            ("direct", "Напрямую", "lane_direct"),
            ("zapret", "Zapret", "lane_zapret"),
            ("vpn", "VPN", "lane_vpn"),
        ):
            lane = LaneRow(context, key, title, token)
            lane.clicked.connect(self.lane_clicked.emit)
            layout.addWidget(lane)
            self.lanes[key] = lane

        self.apply_theme()

    def update_state(self, zapret_on: bool, vpn_on: bool,
                     vpn_apps: list[str], zapret_targets: list[str],
                     direct_note: str) -> None:
        self.lanes["direct"].set_active(True)
        self.lanes["direct"].set_chips([direct_note] if direct_note else [])
        self.lanes["zapret"].set_active(zapret_on)
        self.lanes["zapret"].set_chips(zapret_targets)
        self.lanes["vpn"].set_active(vpn_on)
        self.lanes["vpn"].set_chips(vpn_apps)

    def apply_theme(self) -> None:
        faint = self.context.color("text_faint")
        self.left_caption.setStyleSheet(f"color: {faint}; letter-spacing: 1.5px;")
        self.right_caption.setStyleSheet(f"color: {faint}; letter-spacing: 1.5px;")
        for lane in self.lanes.values():
            lane.apply_theme()
