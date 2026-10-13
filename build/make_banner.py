"""Баннер для шапки README и страницы GitHub: название и сад из главной.

Рисуется тем же движком, что и интерфейс программы.

Запуск: python build/make_banner.py
Результат: docs/banner.png
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath  # noqa: E402

SIZE = (1280, 420)
TARGET = ROOT / "docs" / "banner.png"


def build() -> QImage:
    from app.ui import fonts, scenes, theme
    from app.ui.ink import SceneRenderer, render_postmark, scene_palette

    fonts.load()
    tokens = theme.build_tokens("light")
    width, height = SIZE
    image = QImage(width * 2, height * 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(2.0)
    image.fill(QColor(tokens["bg"]))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Слова слева.
    painter.setFont(fonts.mono(14, 500, 0.12))
    painter.setPen(QColor(tokens["accent_ink"]))
    painter.drawText(QPointF(64, 128), "ОБХОД · VPN · TELEGRAM · SMART DNS")
    painter.setFont(fonts.serif(84, 300))
    painter.setPen(QColor(tokens["ink"]))
    metrics = painter.fontMetrics()
    painter.drawText(QPointF(60, 222), "Zapret")
    x = 60 + metrics.horizontalAdvance("Zapret")
    painter.setFont(fonts.serif(84, 300, italic=True))
    painter.setPen(QColor(tokens["accent"]))
    painter.drawText(QPointF(x, 222), "Ctrl")
    painter.setFont(fonts.sans(20, 400))
    painter.setPen(QColor(tokens["ink3"]))
    painter.drawText(QPointF(64, 272), "Обход блокировок, VPN по программам,")
    painter.drawText(QPointF(64, 302), "Telegram и Smart DNS — в одном окне.")

    # Сад справа, на тарелке, всё включено.
    plate = QRectF(640, 40, 580, 310)
    path = QPainterPath()
    path.addRoundedRect(plate, 26, 26)
    painter.fillPath(path, QColor(tokens["plate"]))
    renderer = SceneRenderer(scenes.garden(), scene_palette(tokens))
    for key in ("dpi", "vpn", "tg", "dns", "any"):
        renderer.set_state(key, True, animate=False)
    painter.save()
    painter.setClipPath(path)
    renderer.paint(painter, QRectF(plate.left(), plate.top() + 5, plate.width(),
                                   plate.width() * 300 / 560), 2.0, now=time.perf_counter() + 30)
    painter.restore()
    mark = render_postmark(150, tokens["pm"], "САД И ПОЧТА · ВСЁ ДОХОДИТ · ZAPRETCTRL ·",
                           "4/4", "4.0", 2.0)
    painter.setOpacity(0.92)
    painter.drawPixmap(QPointF(plate.right() - 112, plate.top() - 30), mark)
    painter.end()
    return image


def main() -> None:
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    build().save(str(TARGET))
    print(f"Готово: {TARGET}")
    del application


if __name__ == "__main__":
    main()
