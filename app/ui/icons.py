"""Иконки рисуем из SVG-строк: никаких шрифтов и внешних файлов.

Стиль — двухтоновый: мягкая заливка того же цвета под контуром. Цвет
подставляется в момент отрисовки, поэтому иконки сами подхватывают тему.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = (
    'fill="none" stroke="{color}" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"'
)
_FILL = 'fill="{color}" fill-opacity="0.18" stroke="none"'

_SHIELD = "M12 3l7 3v5.5c0 4.3-2.9 7.9-7 9.5-4.1-1.6-7-5.2-7-9.5V6l7-3z"
_PLANE = "M21 4L3.5 11l6 2.3L12 20l3.2-4.8L21 4z"
_GEAR = (
    "M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 "
    "00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 "
    "0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 "
    "00-1.5-1H3a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 "
    "0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 "
    "1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 "
    "00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"
)

PATHS: dict[str, str] = {
    # --- навигация ---
    "home": (
        '<path d="M4 10.5L12 4l8 6.5V19a1 1 0 01-1 1H5a1 1 0 01-1-1v-8.5z" {f}/>'
        '<path d="M4 10.5L12 4l8 6.5V19a1 1 0 01-1 1H5a1 1 0 01-1-1v-8.5z" {s}/>'
        '<path d="M9.5 20v-5.5h5V20" {s}/>'
    ),
    "telegram": (
        f'<path d="{_PLANE}" {{f}}/>'
        f'<path d="{_PLANE}" {{s}}/>'
        '<path d="M9.5 13.3L21 4" {s}/>'
    ),
    "route": (
        '<circle cx="6" cy="18" r="2.6" {f}/><circle cx="18" cy="6" r="2.6" {f}/>'
        '<circle cx="6" cy="18" r="2.6" {s}/><circle cx="18" cy="6" r="2.6" {s}/>'
        '<path d="M8.6 18H14a3 3 0 000-6h-4a3 3 0 010-6h5.4" {s}/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="9" {f}/>'
        '<circle cx="12" cy="12" r="9" {s}/>'
        '<path d="M3 12h18" {s}/>'
        '<path d="M12 3a15 15 0 010 18 15 15 0 010-18z" {s}/>'
    ),
    "activity": (
        '<circle cx="12" cy="12" r="9.5" {f}/>'
        '<path d="M3.5 12h3.6l2.2-5 3.6 10 2.2-5h5.4" {s}/>'
    ),
    "settings": (
        f'<path d="{_GEAR}" {{f}}/>'
        f'<path d="{_GEAR}" {{s}}/>'
        '<circle cx="12" cy="12" r="3" {s}/>'
    ),
    "list": (
        '<rect x="3" y="4" width="18" height="16" rx="3" {f}/>'
        '<path d="M8 9h9M8 12.5h9M8 16h6" {s}/>'
        '<path d="M5.5 9h.01M5.5 12.5h.01M5.5 16h.01" {s}/>'
    ),
    "cloud_download": (
        '<path d="M7 18a4 4 0 01-.6-7.95A5.5 5.5 0 0117.2 8.5 3.8 3.8 0 0118 16h-1" {f}/>'
        '<path d="M7 18a4 4 0 01-.6-7.95A5.5 5.5 0 0117.2 8.5 3.8 3.8 0 0118 16" {s}/>'
        '<path d="M12 12v9" {s}/><path d="M9 18l3 3 3-3" {s}/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9" {f}/>'
        '<circle cx="12" cy="12" r="9" {s}/>'
        '<path d="M12 11v5" {s}/><path d="M12 8h.01" {s}/>'
    ),
    # --- состояние и действия ---
    "shield": f'<path d="{_SHIELD}" {{f}}/><path d="{_SHIELD}" {{s}}/>',
    "shield_check": (
        f'<path d="{_SHIELD}" {{f}}/><path d="{_SHIELD}" {{s}}/>'
        '<path d="M9 12l2 2 4-4" {s}/>'
    ),
    "bolt": (
        '<path d="M13 3L5 14h6l-1 7 8-11h-6l1-7z" {f}/>'
        '<path d="M13 3L5 14h6l-1 7 8-11h-6l1-7z" {s}/>'
    ),
    "sparkles": (
        '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9L11 3z" {f}/>'
        '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9L11 3z" {s}/>'
        '<path d="M18.5 15l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1z" {s}/>'
    ),
    "layers": (
        '<path d="M12 3l8 4.5-8 4.5-8-4.5L12 3z" {f}/>'
        '<path d="M12 3l8 4.5-8 4.5-8-4.5L12 3z" {s}/>'
        '<path d="M4 12.5l8 4.5 8-4.5" {s}/>'
        '<path d="M4 16.5l8 4.5 8-4.5" {s}/>'
    ),
    "stethoscope": (
        '<circle cx="20" cy="12" r="2" {f}/>'
        '<path d="M6 3v5a4 4 0 008 0V3" {s}/>'
        '<path d="M10 15v1a5 5 0 0010 0v-2" {s}/>'
        '<circle cx="20" cy="12" r="2" {s}/>'
        '<path d="M10 12v3" {s}/>'
    ),
    "download": (
        '<path d="M12 4v10" {s}/><path d="M8 11l4 4 4-4" {s}/>'
        '<path d="M4 18v1a1 1 0 001 1h14a1 1 0 001-1v-1" {s}/>'
    ),
    "play": '<path d="M8 5.5l10 6.5-10 6.5v-13z" {f}/><path d="M8 5.5l10 6.5-10 6.5v-13z" {s}/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="2" {f}/><rect x="7" y="7" width="10" height="10" rx="2" {s}/>',
    "refresh": (
        '<path d="M20 11a8 8 0 10-1.7 5.4" {s}/>'
        '<path d="M20 5v6h-6" {s}/>'
    ),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5" {s}/>',
    "cross": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" {s}/>',
    "warning": (
        '<path d="M12 4.5l8.5 15h-17l8.5-15z" {f}/>'
        '<path d="M12 4.5l8.5 15h-17l8.5-15z" {s}/>'
        '<path d="M12 10v4" {s}/><path d="M12 17h.01" {s}/>'
    ),
    "chevron_down": '<path d="M6 9.5l6 6 6-6" {s}/>',
    "chevron_right": '<path d="M9.5 6l6 6-6 6" {s}/>',
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2.5" {f}/>'
        '<rect x="9" y="9" width="11" height="11" rx="2.5" {s}/>'
        '<path d="M5 15V6.5A2.5 2.5 0 017.5 4H15" {s}/>'
    ),
    "link": (
        '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1" {s}/>'
        '<path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" {s}/>'
    ),
    "gamepad": (
        '<path d="M7 7h10a5 5 0 014.9 6l-.8 4a2.5 2.5 0 01-4.3 1.2L15 16H9l-1.8 2.2A2.5 2.5 0 012.9 17l-.8-4A5 5 0 017 7z" {f}/>'
        '<path d="M7 7h10a5 5 0 014.9 6l-.8 4a2.5 2.5 0 01-4.3 1.2L15 16H9l-1.8 2.2A2.5 2.5 0 012.9 17l-.8-4A5 5 0 017 7z" {s}/>'
        '<path d="M8 11v3M6.5 12.5h3M15.5 11.5h.01M17.5 13.5h.01" {s}/>'
    ),
    # --- окно ---
    "minimize": '<path d="M6 12h12" {s}/>',
    "maximize": '<rect x="6" y="6" width="12" height="12" rx="2" {s}/>',
    "restore": (
        '<rect x="8" y="8" width="10" height="10" rx="2" {s}/>'
        '<path d="M6 15V7a1 1 0 011-1h8" {s}/>'
    ),
    "close": '<path d="M7 7l10 10M17 7L7 17" {s}/>',
    "sun": (
        '<circle cx="12" cy="12" r="4" {f}/><circle cx="12" cy="12" r="4" {s}/>'
        '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
        'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" {s}/>'
    ),
    "moon": (
        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" {f}/>'
        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" {s}/>'
    ),
    # --- прочее ---
    "search": '<circle cx="11" cy="11" r="6" {f}/><circle cx="11" cy="11" r="6" {s}/><path d="M15.5 15.5L20 20" {s}/>',
    "folder": (
        '<path d="M4 7a2 2 0 012-2h3.5l2 2H18a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V7z" {f}/>'
        '<path d="M4 7a2 2 0 012-2h3.5l2 2H18a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V7z" {s}/>'
    ),
    "external": (
        '<path d="M14 5h5v5" {s}/><path d="M19 5l-8 8" {s}/>'
        '<path d="M18 14v4a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h4" {s}/>'
    ),
    "trash": (
        '<path d="M5 7h14" {s}/>'
        '<path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" {s}/>'
        '<path d="M7 7l1 12a2 2 0 002 2h4a2 2 0 002-2l1-12" {s}/>'
    ),
    "save": (
        '<path d="M5 5h11l3 3v11a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z" {f}/>'
        '<path d="M5 5h11l3 3v11a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z" {s}/>'
        '<path d="M8 5v5h7V5" {s}/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9" {f}/><circle cx="12" cy="12" r="9" {s}/><path d="M12 7v5l3.5 2" {s}/>',
    "heart": (
        '<path d="M12 20s-7-4.4-7-9a4 4 0 017-2.6A4 4 0 0119 11c0 4.6-7 9-7 9z" {f}/>'
        '<path d="M12 20s-7-4.4-7-9a4 4 0 017-2.6A4 4 0 0119 11c0 4.6-7 9-7 9z" {s}/>'
    ),
}


def svg_markup(name: str, color: str) -> str:
    body = PATHS.get(name, PATHS["info"])
    body = body.replace("{s}", _STROKE.format(color=color))
    body = body.replace("{f}", _FILL.format(color=color))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="24" height="24">{body}</svg>'
    )


_pixmap_cache: dict[tuple, QPixmap] = {}
_icon_cache: dict[tuple, QIcon] = {}


def pixmap(name: str, color: str, size: int = 20,
           ratio: float = 1.0) -> QPixmap:
    key = (name, color, size, round(ratio, 2))
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached

    physical = int(size * ratio)
    image = QPixmap(physical, physical)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode("utf-8")))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    _pixmap_cache[key] = image
    return image


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """Рисуем с запасом по разрешению — Qt сгладит при уменьшении.

    Результат кэшируется: без этого смена темы перерисовывала каждую иконку
    заново и занимала полторы секунды.
    """
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    oversized = pixmap(name, color, size * 3)
    oversized.setDevicePixelRatio(1.0)
    result = QIcon(oversized)
    _icon_cache[key] = result
    return result


def clear_cache() -> None:
    _pixmap_cache.clear()
    _icon_cache.clear()


def icon_size(size: int) -> QSize:
    return QSize(size, size)
