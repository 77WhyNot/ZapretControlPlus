"""Иконки программ.

Берём настоящую иконку из exe-файла. Если файла нет — рисуем кружок
с первой буквой названия: цвет выводим из самого названия, чтобы у каждой
программы он был свой и не менялся между запусками.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

_provider: QFileIconProvider | None = None
_cache: dict[str, QPixmap] = {}

# Приглушённые оттенки: буквенные значки не должны спорить с цветами маршрутов.
FALLBACK_COLORS = (
    "#5C7CA6", "#6A8C5E", "#A67C52", "#8A5FA6", "#B06A6A",
    "#4F8C8C", "#8C7A4F", "#7A6AA6", "#A65F8A", "#5F8CA6",
)


def _icon_provider() -> QFileIconProvider:
    global _provider
    if _provider is None:
        _provider = QFileIconProvider()
    return _provider


def _letter_pixmap(title: str, size: int, ratio: float) -> QPixmap:
    digest = hashlib.md5(title.lower().encode("utf-8")).digest()
    color = QColor(FALLBACK_COLORS[digest[0] % len(FALLBACK_COLORS)])

    physical = int(size * ratio)
    pixmap = QPixmap(physical, physical)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)

    letter = (title.strip()[:1] or "?").upper()
    font = QFont("Bahnschrift", int(size * 0.5))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return pixmap


def app_pixmap(path: str, title: str, size: int = 32, ratio: float = 1.0) -> QPixmap:
    key = f"{path.lower()}|{title.lower()}|{size}|{ratio:.2f}"
    cached = _cache.get(key)
    if cached is not None:
        return cached

    pixmap: QPixmap | None = None
    if path and Path(path).is_file():
        icon = _icon_provider().icon(QFileInfo(path))
        if not icon.isNull():
            candidate = icon.pixmap(int(size * ratio), int(size * ratio))
            if not candidate.isNull():
                candidate.setDevicePixelRatio(ratio)
                pixmap = candidate

    if pixmap is None or pixmap.isNull():
        pixmap = _letter_pixmap(title, size, ratio)

    _cache[key] = pixmap
    return pixmap


def clear_cache() -> None:
    _cache.clear()
