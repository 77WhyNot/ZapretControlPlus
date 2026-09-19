"""Ответ на «обновлюсь потом»: клоун во весь экран.

Шутка для своих. Закрывается щелчком, любой клавишей и сама через несколько
секунд — задержать человека она не может.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

CLOWN = "\U0001F921"
TEXT = "Мда...."
LIFETIME = 5.0      # секунд на экране
FADE = 0.25         # проявление и угасание
COUNT = 70          # сколько мелких надписей


class ClownScreen(QWidget):
    """Экран с клоуном и бегущими «Мда....»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWindowOpacity(0.0)

        screen = (parent.screen() if parent is not None else None) \
            or QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

        rng = random.Random(4242)
        # (доля ширины, доля высоты, размер, скорость, сдвиг фазы, наклон)
        self._motes = [
            (rng.random(), rng.random(), rng.uniform(11.0, 24.0),
             rng.uniform(0.02, 0.09), rng.uniform(0.0, 6.28), rng.uniform(-18.0, 18.0))
            for _ in range(COUNT)
        ]
        self._started = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def play(self) -> None:
        self._started = time.perf_counter()
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()

    # --- кадры --------------------------------------------------------------

    def _tick(self) -> None:
        elapsed = time.perf_counter() - self._started
        if elapsed >= LIFETIME:
            self._timer.stop()
            self.close()
            return
        # Проявление в начале и угасание в конце — чтобы не бил по глазам.
        if elapsed < FADE:
            self.setWindowOpacity(elapsed / FADE)
        elif elapsed > LIFETIME - FADE:
            self.setWindowOpacity(max(0.0, (LIFETIME - elapsed) / FADE))
        else:
            self.setWindowOpacity(1.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#0B0E14"))
        elapsed = time.perf_counter() - self._started

        font = QFont("Bahnschrift", 12)
        for left, top, size, speed, phase, angle in self._motes:
            # Надписи медленно всплывают и по кругу возвращаются вниз.
            y = ((top - elapsed * speed) % 1.15 - 0.08) * height
            painter.save()
            painter.translate(left * width, y)
            painter.rotate(angle)
            font.setPointSizeF(size)
            painter.setFont(font)
            alpha = 70 + 95 * (0.5 + 0.5 * math.sin(elapsed * 2.1 + phase))
            painter.setPen(QColor(226, 232, 244, int(alpha)))
            painter.drawText(0, 0, TEXT)
            painter.restore()

        painter.save()
        painter.translate(width / 2, height / 2)
        painter.rotate(7.0 * math.sin(elapsed * 2.3))
        scale = 1.0 + 0.06 * math.sin(elapsed * 3.1)
        painter.scale(scale, scale)
        emoji = QFont("Segoe UI Emoji")
        emoji.setPixelSize(max(64, int(min(width, height) * 0.38)))
        painter.setFont(emoji)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRect(-width // 2, -height // 2, width, height),
                         Qt.AlignmentFlag.AlignCenter, CLOWN)
        painter.restore()

        hint = QFont("Bahnschrift", 11)
        painter.setFont(hint)
        painter.setPen(QColor(226, 232, 244, 90))
        painter.drawText(QRect(0, height - 60, width, 40),
                         Qt.AlignmentFlag.AlignCenter, "щёлкните, чтобы закрыть")
        painter.end()

    # --- закрытие -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)


def show_clown(parent: QWidget | None = None) -> ClownScreen:
    """Показать клоуна поверх всего. Ссылку держит сам Qt: окно само удалится."""
    screen = ClownScreen(parent)
    screen.play()
    return screen
