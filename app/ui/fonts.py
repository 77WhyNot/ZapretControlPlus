"""Шрифты оформления: вшиты в программу, а не ждут их в системе.

Literata — заголовки (тонкий серифный, курсив для одного слова), Geist —
весь интерфейс, Geist Mono — моноширинные подписи заглавными. Все три под
лицензией SIL OFL, лицензии лежат рядом с файлами шрифтов.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from app.core import paths

SERIF = "Literata"
SANS = "Geist"
MONO = "Geist Mono"

FILES = (
    "Literata-Light.ttf", "Literata-LightItalic.ttf",
    "Literata-Regular.ttf", "Literata-Italic.ttf",
    "Geist-Regular.ttf", "Geist-Medium.ttf", "Geist-SemiBold.ttf",
    "GeistMono-Regular.ttf", "GeistMono-Medium.ttf",
)

_loaded: bool | None = None


def load() -> bool:
    """Зарегистрировать шрифты. Повторный вызов ничего не делает."""
    global _loaded
    if _loaded is not None:
        return _loaded
    ok = True
    for name in FILES:
        path = paths.resource_path("fonts", name)
        if not path.exists() or QFontDatabase.addApplicationFont(str(path)) < 0:
            ok = False
    _loaded = ok
    return ok


def serif(px: float, weight: int = 300, italic: bool = False) -> QFont:
    font = QFont(SERIF)
    font.setPixelSize(max(1, round(px)))
    font.setWeight(QFont.Weight.Light if weight <= 300 else QFont.Weight.Normal)
    font.setItalic(italic)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99 if px >= 24 else 100)
    return font


def sans(px: float, weight: int = 400) -> QFont:
    font = QFont(SANS)
    font.setPixelSize(max(1, round(px)))
    font.setWeight({500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold}.get(
        weight, QFont.Weight.Normal))
    return font


def mono(px: float, weight: int = 500, spacing: float = 0.1) -> QFont:
    """Моноширинная подпись; spacing — разрядка в долях кегля, как em в CSS."""
    font = QFont(MONO)
    font.setPixelSize(max(1, round(px)))
    font.setWeight(QFont.Weight.Medium if weight >= 500 else QFont.Weight.Normal)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * spacing)
    return font
