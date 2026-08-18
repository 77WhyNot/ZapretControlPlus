"""Заставка на время запуска.

Раньше окно показывалось недостроенным: десять страниц собирались уже после
того, как Windows нарисовала рамку, и это выглядело как рывки и мелькание.
Теперь пользователь видит спокойную заставку, а окно появляется готовым.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from app.core import paths
from app.core.constants import APP_NAME, APP_VERSION
from app.ui import icons

WIDTH = 380
HEIGHT = 200


class Splash(QWidget):
    """Небольшое окно с логотипом и строкой состояния."""

    def __init__(self, tokens: dict[str, str]) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.SplashScreen
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.tokens = tokens
        self._message = "Запуск…"
        self._progress = 0.0
        self._target = 0.0

        self.setFixedSize(WIDTH, HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        icon_path = paths.resource_path("icon.png")
        if icon_path.exists():
            self._logo = QPixmap(str(icon_path)).scaled(
                56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            self._logo = icons.pixmap("shield_check", tokens.get("accent", "#22C6D8"), 56)

        self._center()

        # Плавно подтягиваем полосу к цели, чтобы не было скачков.
        self._animation = QTimer(self)
        self._animation.timeout.connect(self._advance)
        self._animation.start(16)

    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - WIDTH // 2,
            area.center().y() - HEIGHT // 2,
        )

    def _advance(self) -> None:
        if abs(self._progress - self._target) < 0.005:
            self._progress = self._target
            return
        self._progress += (self._target - self._progress) * 0.18
        self.update()

    def step(self, message: str, value: float) -> None:
        """Обновить подпись и цель полосы (0…1)."""
        self._message = message
        self._target = max(0.0, min(1.0, value))
        self.update()
        QApplication.processEvents()

    def finish(self) -> None:
        self._animation.stop()
        self.close()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        surface = QColor(self.tokens.get("surface", "#121821"))
        border = QColor(self.tokens.get("border_strong", "#2A3441"))
        text_color = QColor(self.tokens.get("text", "#DCE3ED"))
        faint = QColor(self.tokens.get("text_faint", "#5E6B7D"))
        accent = QColor(self.tokens.get("accent", "#22C6D8"))

        painter.setPen(border)
        painter.setBrush(surface)
        painter.drawRoundedRect(QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1), 12, 12)

        painter.drawPixmap(30, 34, self._logo)

        title_font = QFont("Bahnschrift", 17)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(text_color)
        painter.drawText(QRectF(102, 38, WIDTH - 130, 28),
                         Qt.AlignmentFlag.AlignVCenter, APP_NAME)

        version_font = QFont("Segoe UI", 9)
        painter.setFont(version_font)
        painter.setPen(faint)
        painter.drawText(QRectF(102, 64, WIDTH - 130, 20),
                         Qt.AlignmentFlag.AlignVCenter, f"версия {APP_VERSION}")

        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(faint)
        painter.drawText(QRectF(30, HEIGHT - 60, WIDTH - 60, 20),
                         Qt.AlignmentFlag.AlignVCenter, self._message)

        track = QRectF(30, HEIGHT - 34, WIDTH - 60, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.tokens.get("border", "#1E2733")))
        painter.drawRoundedRect(track, 2, 2)

        if self._progress > 0:
            filled = QRectF(track.x(), track.y(),
                            track.width() * self._progress, track.height())
            painter.setBrush(accent)
            painter.drawRoundedRect(filled, 2, 2)
        painter.end()
