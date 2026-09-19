"""Схема маршрутов: три пути, по активным бежит пунктир.

Это главный элемент интерфейса. Он отвечает на единственный вопрос, ради
которого программу открывают: куда сейчас идёт мой трафик.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.context import AppContext
from app.ui.widgets import frame_clock

DASH_PERIOD = 26.0
TRACK_HEIGHT = 4
FLOW_SPEED = 38.0  # пикселей в секунду — прежний темп, но без привязки к кадрам


class LaneTrack(QWidget):
    """Полоса пути. Когда активна — по ней движется пунктир.

    Кадры приходят от общего таймера программы, а положение пунктира считается
    по реальному времени: запоздавший кадр рисует верное место, а не «шаг
    назад», поэтому движение ровное.
    """

    def __init__(self, color: str, idle_color: str, active: bool = False,
                 parent: QWidget | None = None, background: str = "#FFFFFF") -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.idle_color = QColor(idle_color)
        self.background = QColor(background)
        self.active = False
        self.setMinimumHeight(14)
        self.setMinimumWidth(80)
        # Полоса сама закрашивает свой фон: иначе на каждом кадре Qt заново
        # рисовал под ней фон карточки со стилем и скруглениями — это и
        # съедало процессор, пока пунктир бежит.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.set_active(active)

    def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        if active:
            frame_clock().subscribe(self)
        else:
            frame_clock().unsubscribe(self)
        self.update()

    def set_colors(self, color: str, idle_color: str, background: str = "") -> None:
        self.color = QColor(color)
        self.idle_color = QColor(idle_color)
        if background:
            self.background = QColor(background)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.active:
            frame_clock().subscribe(self)

    @property
    def _phase(self) -> float:
        return (time.perf_counter() * FLOW_SPEED) % DASH_PERIOD

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.background)
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
    """Ярлык программы или сервиса на пути.

    Скруглённую плашку рисуем сами. Если задать её стилем (background +
    border-radius), Qt считает ярлык непрозрачным целиком и не рисует фон под
    его скруглёнными углами — отсюда были тёмные уголки и полоса между
    соседними ярлыками.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fill = QColor("#FFFFFF")
        self._edge = QColor("#CDD4DE")

    def apply_colors(self, background: str, border: str, text: str) -> None:
        self._fill = QColor(background)
        self._edge = QColor(border)
        self.setStyleSheet(
            f"background: transparent; border: none; color: {text};"
            "padding: 3px 9px; font-size: 11.5px;"
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(self._edge, 1))
        painter.setBrush(self._fill)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        painter.end()
        super().paintEvent(event)


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
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(12)

        self.label = QLabel(title.upper())
        self.label.setFixedWidth(104)
        font = QFont("Bahnschrift", 10)
        font.setWeight(QFont.Weight.DemiBold)
        self.label.setFont(font)
        layout.addWidget(self.label)

        self.track = LaneTrack(
            context.color(color_token), context.color("border_strong"),
            background=context.color("surface"),
        )
        layout.addWidget(self.track, 1)

        self.chips_host = QWidget(self)
        self.chips_layout = QHBoxLayout(self.chips_host)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(5)
        self._chips: list[LaneChip] = []
        self._chip_texts: list[str] = []
        layout.addWidget(self.chips_host, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme()

    def set_active(self, active: bool) -> None:
        self.track.set_active(active)
        self.label.setStyleSheet(
            f"color: {self.context.color(self.color_token)};" if active
            else f"color: {self.context.color('text_faint')};"
        )

    def set_chips(self, items: list[str]) -> None:
        """Ярлыки переиспользуем: раньше их удаляли и создавали заново на
        каждое обновление экрана, раз в пару секунд, — и в этот миг проступал
        мусор под ними."""
        items = list(items[:4])
        if items == self._chip_texts:
            return
        self._chip_texts = items
        while len(self._chips) < len(items):
            chip = LaneChip("", self.chips_host)
            self._paint_chip(chip)
            self.chips_layout.addWidget(chip)
            self._chips.append(chip)
        for index, chip in enumerate(self._chips):
            if index < len(items):
                chip.setText(items[index])
                chip.show()
            else:
                chip.hide()

    def _paint_chip(self, chip: LaneChip) -> None:
        chip.apply_colors(
            self.context.color("surface_alt"),
            self.context.color("border_strong"),
            self.context.color("text_dim"),
        )

    def apply_theme(self) -> None:
        self.track.set_colors(
            self.context.color(self.color_token), self.context.color("border_strong"),
            self.context.color("surface"),
        )
        for chip in self._chips:
            self._paint_chip(chip)
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
            ("tg", "Telegram", "lane_tg"),
            ("dns", "Smart DNS", "lane_dns"),
            ("vpn", "VPN", "lane_vpn"),
        ):
            lane = LaneRow(context, key, title, token)
            lane.clicked.connect(self.lane_clicked.emit)
            layout.addWidget(lane)
            self.lanes[key] = lane

        self.apply_theme()

    def update_state(self, zapret_on: bool, zapret_targets: list[str],
                     dns_on: bool, dns_note: str,
                     tunnels: list[str], direct_note: str,
                     tg_on: bool = False, tg_note: str = "",
                     vpn_on: bool = False, vpn_chips: list[str] | None = None) -> None:
        self.lanes["direct"].set_active(True)
        self.lanes["direct"].set_chips([direct_note] if direct_note else [])
        self.lanes["zapret"].set_active(zapret_on)
        self.lanes["zapret"].set_chips(zapret_targets)
        self.lanes["tg"].set_active(tg_on)
        self.lanes["tg"].set_chips([tg_note] if tg_on and tg_note else [])
        self.lanes["dns"].set_active(dns_on)
        self.lanes["dns"].set_chips([dns_note] if dns_on and dns_note else [])
        self.lanes["vpn"].set_active(vpn_on)
        self.lanes["vpn"].set_chips(list(vpn_chips or []) if vpn_on else [])
        # Чужой VPN на схеме не рисуем: о нём говорит небольшая плашка над ней.

    def apply_theme(self) -> None:
        faint = self.context.color("text_faint")
        self.left_caption.setStyleSheet(f"color: {faint}; letter-spacing: 1.5px;")
        self.right_caption.setStyleSheet(f"color: {faint}; letter-spacing: 1.5px;")
        for lane in self.lanes.values():
            lane.apply_theme()
