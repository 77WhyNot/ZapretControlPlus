"""Заставка на время запуска: бумажная карточка, на которой прорастает росток.

Раньше окно показывалось недостроенным: десять страниц собирались уже после
того, как Windows нарисовала рамку, и это выглядело как рывки и мелькание.
Теперь пользователь видит спокойную заставку, а окно появляется готовым.
Пока программа собирается, росток знака тянется вверх — это и есть полоса
загрузки; на последнем шаге загорается глиняная точка.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app.core.constants import APP_AUTHOR, APP_EDITION, APP_NAME, APP_VERSION

WIDTH = 400
HEIGHT = 210


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
        # Без прозрачности за скруглёнными углами виден серый фон окна.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        from app.ui import fonts
        from app.ui.ink import parse_path

        fonts.load()
        self._stem = parse_path("M10 18 L10 9")
        self._leaf_left = parse_path("M10 11 C 6 11, 4 8, 4 5 C 8 5, 10 7, 10 11")
        self._leaf_right = parse_path("M10 9 C 10 6, 12 4, 16 4 C 16 7, 14 9, 10 9")

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

    @staticmethod
    def _prefix(path: QPainterPath, portion: float) -> list[QPointF]:
        portion = max(0.0, min(1.0, portion))
        return [path.pointAtPercent(k / 24 * portion) for k in range(25)]

    def paintEvent(self, event) -> None:  # noqa: N802
        from app.ui import fonts

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = self.tokens
        paper = QColor(t.get("bg", "#FAF9F5"))
        ring = QColor(t.get("border_strong", "#D9D6CC"))
        ink = QColor(t.get("ink", "#141413"))
        muted = QColor(t.get("muted", "#73726C"))
        clay = QColor(t.get("clay", "#D97757"))
        olive = QColor(t.get("olive", "#788C5D"))

        painter.setPen(ring)
        painter.setBrush(paper)
        painter.drawRoundedRect(QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1), 18, 18)

        # Росток растёт вместе с загрузкой: стебель, листья, точка.
        p = self._progress
        painter.save()
        painter.translate(30, 34)
        painter.scale(4.0, 4.0)
        pen = QPen(ink)
        pen.setWidthF(0.45)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stem = self._prefix(self._stem, p / 0.35)
        painter.setPen(pen)
        for a, b in zip(stem, stem[1:]):
            painter.drawLine(a, b)
        for leaf, start in ((self._leaf_left, 0.3), (self._leaf_right, 0.55)):
            share = (p - start) / 0.35
            if share <= 0:
                continue
            painter.setOpacity(min(1.0, share * 1.5))
            painter.fillPath(leaf, olive)
            painter.setOpacity(1.0)
            points = self._prefix(leaf, share)
            painter.setPen(pen)
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
        if p >= 0.98:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(clay)
            painter.drawEllipse(QPointF(16, 4), 2.2, 2.2)
        painter.restore()

        painter.setFont(fonts.serif(30, 300))
        painter.setPen(ink)
        painter.drawText(QRectF(132, 40, WIDTH - 150, 40),
                         Qt.AlignmentFlag.AlignVCenter, APP_NAME)
        painter.setFont(fonts.mono(10.5, 500, 0.1))
        painter.setPen(QColor(t.get("accent_ink", "#A84B2A")))
        painter.drawText(QRectF(134, 82, WIDTH - 150, 18), Qt.AlignmentFlag.AlignVCenter,
                         f"{APP_VERSION} {APP_EDITION}".strip().upper() + f" · {APP_AUTHOR.upper()}")

        painter.setFont(fonts.sans(12.5, 400))
        painter.setPen(muted)
        painter.drawText(QRectF(134, HEIGHT - 66, WIDTH - 160, 20),
                         Qt.AlignmentFlag.AlignVCenter, self._message)

        # Тонкая линия земли под ростком — и ход загрузки поверх неё.
        ground = QRectF(30, HEIGHT - 40, WIDTH - 60, 1.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.get("border", "#E3E2DE")))
        painter.drawRoundedRect(ground, 0.8, 0.8)
        if self._progress > 0:
            painter.setBrush(ink)
            painter.drawRoundedRect(QRectF(ground.x(), ground.y() - 0.4,
                                           ground.width() * self._progress, 2.4), 1.2, 1.2)
        painter.end()
