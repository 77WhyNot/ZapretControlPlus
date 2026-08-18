"""Иконки рисуем из SVG-строк: никаких шрифтов и внешних файлов.

Цвет подставляется в момент отрисовки, поэтому иконки автоматически
подхватывают текущую тему.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = (
    'fill="none" stroke="{color}" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"'
)

PATHS: dict[str, str] = {
    "shield": '<path d="M12 3l7 3v5.5c0 4.3-2.9 7.9-7 9.5-4.1-1.6-7-5.2-7-9.5V6l7-3z" {s}/>',
    "shield_check": (
        '<path d="M12 3l7 3v5.5c0 4.3-2.9 7.9-7 9.5-4.1-1.6-7-5.2-7-9.5V6l7-3z" {s}/>'
        '<path d="M9 12l2 2 4-4" {s}/>'
    ),
    "layers": (
        '<path d="M12 3l8 4.5-8 4.5-8-4.5L12 3z" {s}/>'
        '<path d="M4 12.5l8 4.5 8-4.5" {s}/>'
        '<path d="M4 16.5l8 4.5 8-4.5" {s}/>'
    ),
    "list": (
        '<path d="M8 6h12M8 12h12M8 18h12" {s}/>'
        '<path d="M4 6h.01M4 12h.01M4 18h.01" {s}/>'
    ),
    "stethoscope": (
        '<path d="M6 3v5a4 4 0 008 0V3" {s}/>'
        '<path d="M10 15v1a5 5 0 0010 0v-2" {s}/>'
        '<circle cx="20" cy="12" r="2" {s}/>'
        '<path d="M10 12v3" {s}/>'
    ),
    "download": (
        '<path d="M12 4v10" {s}/><path d="M8 11l4 4 4-4" {s}/>'
        '<path d="M4 18v1a1 1 0 001 1h14a1 1 0 001-1v-1" {s}/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3" {s}/>'
        '<path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 '
        '00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 '
        '0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 '
        '00-1.5-1H3a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 '
        '0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 '
        '1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 '
        '00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z" {s}/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9" {s}/>'
        '<path d="M12 11v5" {s}/><path d="M12 8h.01" {s}/>'
    ),
    "play": '<path d="M8 5.5l10 6.5-10 6.5v-13z" {s}/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="2" {s}/>',
    "refresh": (
        '<path d="M20 11a8 8 0 10-1.7 5.4" {s}/>'
        '<path d="M20 5v6h-6" {s}/>'
    ),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5" {s}/>',
    "cross": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" {s}/>',
    "warning": (
        '<path d="M12 4.5l8.5 15h-17l8.5-15z" {s}/>'
        '<path d="M12 10v4" {s}/><path d="M12 17h.01" {s}/>'
    ),
    "minimize": '<path d="M6 12h12" {s}/>',
    "maximize": '<rect x="6" y="6" width="12" height="12" rx="2" {s}/>',
    "restore": (
        '<rect x="8" y="8" width="10" height="10" rx="2" {s}/>'
        '<path d="M6 15V7a1 1 0 011-1h8" {s}/>'
    ),
    "close": '<path d="M7 7l10 10M17 7L7 17" {s}/>',
    "search": '<circle cx="11" cy="11" r="6" {s}/><path d="M15.5 15.5L20 20" {s}/>',
    "folder": (
        '<path d="M4 7a2 2 0 012-2h3.5l2 2H18a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 '
        '01-2-2V7z" {s}/>'
    ),
    "external": (
        '<path d="M14 5h5v5" {s}/><path d="M19 5l-8 8" {s}/>'
        '<path d="M18 14v4a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h4" {s}/>'
    ),
    "bolt": '<path d="M13 3L5 14h6l-1 7 8-11h-6l1-7z" {s}/>',
    "trash": (
        '<path d="M5 7h14" {s}/>'
        '<path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" {s}/>'
        '<path d="M7 7l1 12a2 2 0 002 2h4a2 2 0 002-2l1-12" {s}/>'
    ),
    "save": (
        '<path d="M5 5h11l3 3v11a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z" {s}/>'
        '<path d="M8 5v5h7V5" {s}/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="9" {s}/>'
        '<path d="M3 12h18" {s}/>'
        '<path d="M12 3a15 15 0 010 18 15 15 0 010-18z" {s}/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9" {s}/><path d="M12 7v5l3.5 2" {s}/>',
    "heart": (
        '<path d="M12 20s-7-4.4-7-9a4 4 0 017-2.6A4 4 0 0119 11c0 4.6-7 9-7 9z" {s}/>'
    ),
}


def svg_markup(name: str, color: str) -> str:
    body = PATHS.get(name, PATHS["info"]).replace("{s}", _STROKE.format(color=color))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="24" height="24">{body}</svg>'
    )


def pixmap(name: str, color: str, size: int = 20,
           ratio: float = 1.0) -> QPixmap:
    physical = int(size * ratio)
    image = QPixmap(physical, physical)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode("utf-8")))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return image


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """Рисуем с запасом по разрешению — Qt сгладит при уменьшении."""
    oversized = pixmap(name, color, size * 3)
    oversized.setDevicePixelRatio(1.0)
    return QIcon(oversized)


def icon_size(size: int) -> QSize:
    return QSize(size, size)
