"""Тема «Пергамент»: бумага цвета слоновой кости днём и тёплая ночь.

Все нейтральные тона тёплые, без холодных серых. Один насыщенный акцент —
глина. Остальные краски (олива, крафт, небо, манила) — для рисунков и для
цвета маршрутов: обход — глина, VPN — небо, Telegram — крафт, DNS — олива.
"""

from __future__ import annotations

import winreg
from dataclasses import dataclass

from app.core import winapi

# =========================================================================
# Палитры
# =========================================================================


@dataclass(frozen=True)
class ThemeDef:
    key: str
    title: str
    dark: bool
    colors: dict[str, str]


PAPER = {
    # поверхности
    "bg": "#FAF9F5", "side": "#F3F1EA", "card": "#F0EEE6", "card2": "#EBE8DE",
    "plate": "#E3DACC", "field": "#FAF9F5",
    # тушь и текст
    "ink": "#141413", "ink2": "#3D3D3A", "ink3": "#5E5D59", "muted": "#73726C",
    "decor": "#87867F", "pencil": "#AEABA1",
    # акцент и состояние
    "accent": "#C6613F", "accent_ink": "#A84B2A", "ok": "#4F6A3A",
    "warn": "#9A6524", "bad": "#B23A2B", "btn": "#141413", "on_btn": "#FAF9F5",
    # краски рисунков
    "clay": "#D97757", "olive": "#788C5D", "matcha": "#CED6BF", "kraft": "#D4A27F",
    "manilla": "#EBDBBC", "sky": "#6A9BCC", "sky_ink": "#3F6FA0", "soil": "#D6C1A3",
    "sea": "#D3DAD6", "hill": "#CED6BF", "hill2": "#B9C4A6", "ground": "#C3CCB0",
    "wall": "#EFE5D2", "glow": "#F7ECD6", "cut": "#E3DACC", "pm": "#C6613F",
    "stamp_paper": "#FBF8F1", "stamp_desk": "#E9E4D8",
}

NIGHT = {
    "bg": "#1A1918", "side": "#161514", "card": "#232220", "card2": "#292826",
    "plate": "#2A2926", "field": "#1A1918",
    "ink": "#ECE9E0", "ink2": "#D6D3CA", "ink3": "#B0AEA5", "muted": "#9C9A92",
    "decor": "#6B6A64", "pencil": "#6A6862",
    "accent": "#D97757", "accent_ink": "#E08A6C", "ok": "#A8BB8A",
    "warn": "#D9A066", "bad": "#E5806E", "btn": "#ECE9E0", "on_btn": "#1A1918",
    "clay": "#D97757", "olive": "#7F9463", "matcha": "#4A5540", "kraft": "#C4936F",
    "manilla": "#EBDBBC", "sky": "#6A9BCC", "sky_ink": "#8FB4DC", "soil": "#3A332B",
    "sea": "#1F272B", "hill": "#323A2C", "hill2": "#3B4433", "ground": "#2A3025",
    "wall": "#3B3732", "glow": "#EBDBBC", "cut": "#2A2926", "pm": "#D97757",
    "stamp_paper": "#ECE6D8", "stamp_desk": "#24231F",
}

THEMES: tuple[ThemeDef, ...] = (
    ThemeDef("light", "Бумага", False, PAPER),
    ThemeDef("dark", "Ночь", True, NIGHT),
)

THEME_BY_KEY = {theme.key: theme for theme in THEMES}

# Ключи тем прошлых версий: у кого была тёмная — та остаётся тёмной.
LEGACY_THEMES = {"rails": "dark", "midnight": "dark", "sand": "light"}

THEME_CHOICES = (
    ("light", "Бумага", "Днём: слоновая кость и тушь"),
    ("dark", "Ночь", "Вечером: тёплая темнота и луна"),
    ("system", "Как в Windows", "Сама переходит вслед за системой"),
)


# =========================================================================
# Вспомогательное
# =========================================================================


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """Смешать два цвета: ratio=0 → color_a, ratio=1 → color_b."""
    a, b = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    return _rgb_to_hex(tuple(
        max(0, min(255, round(a[i] + (b[i] - a[i]) * ratio))) for i in range(3)
    ))


def rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def system_prefers_dark() -> bool:
    value = winapi.reg_read(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "AppsUseLightTheme",
    )
    if value is None:
        return False
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def normalize_theme_key(key: str) -> str:
    """Ключ из настроек → light / dark / system."""
    key = LEGACY_THEMES.get(key, key)
    return key if key in ("light", "dark", "system") else "light"


def resolve_theme_key(key: str) -> str:
    key = normalize_theme_key(key)
    if key == "system":
        return "dark" if system_prefers_dark() else "light"
    return key


def build_tokens(theme_key: str, accent_key: str = "") -> dict[str, str]:
    """Палитра в виде словаря. accent_key оставлен для совместимости."""
    theme = THEME_BY_KEY[resolve_theme_key(theme_key)]
    c = dict(theme.colors)
    dark = theme.dark
    bg, ink = c["bg"], c["ink"]

    tokens = dict(c)
    tokens.update({
        "is_dark": "1" if dark else "0",
        # Имена, на которые опираются страницы.
        "surface": c["card"],
        "surface_alt": c["card2"],
        "sidebar": c["side"],
        "titlebar": c["side"],
        "border": mix(bg, ink, 0.10 if not dark else 0.09),
        "border_strong": mix(bg, ink, 0.17 if not dark else 0.16),
        "text": ink,
        "text_dim": c["ink3"],
        "text_faint": c["muted"],
        "hover": c["card2"],
        "input": c["field"],
        "code_bg": c["side"],
        "success": c["ok"],
        "warning": c["warn"],
        "danger": c["bad"],
        "success_bg": mix(bg, c["olive"], 0.16 if not dark else 0.20),
        "warning_bg": mix(bg, c["kraft"], 0.24 if not dark else 0.18),
        "danger_bg": mix(bg, c["clay"], 0.16 if not dark else 0.18),
        "scroll": mix(bg, ink, 0.22),
        "accent_hover": mix(c["accent"], ink if not dark else "#FFFFFF", 0.12),
        "accent_press": mix(c["accent"], "#000000", 0.15),
        "on_accent": "#FAF9F5" if not dark else "#1A1918",
        "accent_text": c["accent_ink"],
        "accent_soft": mix(c["card"], c["clay"], 0.14 if not dark else 0.18),
        "accent_soft_hover": mix(c["card"], c["clay"], 0.22 if not dark else 0.26),
        "accent_border": mix(bg, c["clay"], 0.45),
        "overlay": rgba("#141413", 0.32 if not dark else 0.55),
        "btn_hover": mix(c["btn"], bg, 0.16),
    })

    # Цвета маршрутов — способ читать состояние: один цвет — один путь
    # трафика во всей программе. Совпадают с подкраской марок на главной.
    lanes = {
        "lane_direct": c["decor"],
        "lane_zapret": c["accent"],
        "lane_vpn": c["sky_ink"] if not dark else c["sky"],
        "lane_tg": "#A26C3E" if not dark else c["kraft"],
        "lane_dns": "#5F7346" if not dark else "#A8BB8A",
        "lane_foreign": "#8A7F9E" if not dark else "#A497B8",
    }
    tokens.update(lanes)
    for name, value in lanes.items():
        tokens[f"{name}_soft"] = mix(c["card"], value, 0.14 if not dark else 0.20)
    # Подкраска марок: включённая марка теплеет своим цветом.
    tokens.update({
        "tint_dpi": "#F4DCCD", "tint_vpn": "#DBE4EC",
        "tint_tg": "#EFE1CC", "tint_dns": "#E0E6D4", "tint_off": "#F1EEE6",
    } if not dark else {
        "tint_dpi": "#E9CDBA", "tint_vpn": "#CCD8E3",
        "tint_tg": "#E3D3BB", "tint_dns": "#D3DBC4", "tint_off": "#E4DFD3",
    })
    return tokens


# =========================================================================
# QSS
# =========================================================================

QSS_TEMPLATE = """
* {{
    font-family: "Geist", "Segoe UI", sans-serif;
    font-size: 13.5px;
    color: {text};
}}

QWidget#Root {{
    background: {bg};
    border: 1px solid {border_strong};
}}

/* ---------- Заголовок окна и закладки ---------- */

QWidget#TitleBar {{ background: {side}; }}
QWidget#TabBar {{ background: {side}; }}

QLabel#TitleText {{
    font-size: 13px;
    font-weight: 500;
    color: {text};
    background: transparent;
}}
QLabel#TitleVersion {{
    font-family: "Geist Mono", monospace;
    font-size: 10.5px;
    font-weight: 500;
    color: {muted};
    background: transparent;
}}
QLabel#TitleState {{
    font-size: 12px;
    color: {ink3};
    background: transparent;
}}

QPushButton#WinButton, QPushButton#WinClose {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0px;
    min-width: 38px; max-width: 38px;
    min-height: 30px; max-height: 30px;
}}
QPushButton#WinButton:hover {{ background: {card}; }}
QPushButton#WinButton:pressed {{ background: {card2}; }}
QPushButton#WinClose:hover {{ background: {bad}; }}

/* ---------- Контент ---------- */

QWidget#Content {{ background: {bg}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QLabel#PageTitle {{
    font-family: "Literata", Georgia, serif;
    font-size: 34px;
    font-weight: 300;
    color: {text};
    background: transparent;
}}
QLabel#HeroTitle {{
    font-family: "Literata", Georgia, serif;
    font-size: 40px;
    font-weight: 300;
    color: {text};
    background: transparent;
}}
QLabel#CardTitle, QLabel#SectionTitle {{
    font-family: "Literata", Georgia, serif;
    font-size: 20px;
    font-weight: 400;
    color: {text};
    background: transparent;
}}
QLabel#PageSubtitle, QLabel#Lede {{
    font-size: 14.5px;
    color: {ink3};
    background: transparent;
}}
QLabel#Muted {{ color: {ink3}; background: transparent; }}
QLabel#Faint {{ color: {muted}; font-size: 12.5px; background: transparent; }}

QLabel[role="display"] {{
    font-family: "Literata", Georgia, serif;
    font-weight: 400;
}}
QLabel[role="mono"], QPlainTextEdit[role="mono"] {{
    font-family: "Geist Mono", "Cascadia Mono", monospace;
}}

QLabel[lane="direct"] {{ color: {lane_direct}; }}
QLabel[lane="zapret"] {{ color: {lane_zapret}; }}
QLabel[lane="dns"] {{ color: {lane_dns}; }}
QLabel[lane="tg"] {{ color: {lane_tg}; }}
QLabel[lane="vpn"] {{ color: {lane_vpn}; }}
QLabel[lane="foreign"] {{ color: {lane_foreign}; }}

/* ---------- Раскрывающийся раздел ---------- */

QFrame#CollapsibleHeader {{
    background: {card};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#CollapsibleHeader:hover {{ border-color: {border_strong}; background: {card2}; }}

/* ---------- Карточки ---------- */

QFrame#Card {{
    background: {card};
    border: 1px solid {border};
    border-radius: 16px;
}}
QFrame#CardAlt {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#Tile {{
    background: {card};
    border: 1px solid {border};
    border-radius: 16px;
}}
QFrame#Divider {{
    background: {border};
    max-height: 1px;
    border: none;
}}

/* ---------- Кнопки ---------- */

QPushButton {{
    background: {card};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 8px 15px;
    font-size: 13.5px;
    font-weight: 500;
    color: {text};
}}
QPushButton:hover {{ background: {card2}; }}
QPushButton:pressed {{ background: {plate}; }}
QPushButton:disabled {{ color: {muted}; background: {card}; border-color: {border}; }}

QPushButton[variant="primary"] {{
    background: {btn};
    border: 1px solid {btn};
    color: {on_btn};
}}
QPushButton[variant="primary"]:hover {{ background: {btn_hover}; border-color: {btn_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {ink2}; border-color: {ink2}; }}
QPushButton[variant="primary"]:disabled {{
    background: {card2}; border-color: {border}; color: {muted};
}}

QPushButton[variant="soft"] {{
    background: {card};
    border: 1px solid {border_strong};
    color: {text};
}}
QPushButton[variant="soft"]:hover {{ background: {card2}; }}

QPushButton[variant="accent"] {{
    background: {accent};
    border: 1px solid {accent};
    color: {on_accent};
}}
QPushButton[variant="accent"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}

QPushButton[variant="danger"] {{
    background: transparent;
    border: 1px solid {bad};
    color: {bad};
}}
QPushButton[variant="danger"]:hover {{ background: {danger_bg}; }}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {ink3};
}}
QPushButton[variant="ghost"]:hover {{ background: {card}; color: {text}; }}
QPushButton[variant="ghost"]:disabled {{ background: transparent; border-color: transparent; }}

QPushButton[variant="link"] {{
    background: transparent;
    border: none;
    padding: 2px 0px;
    color: {accent_ink};
}}
QPushButton[variant="link"]:hover {{ color: {text}; }}

QPushButton[sizeVariant="large"] {{
    padding: 11px 20px;
    font-size: 14px;
    border-radius: 9px;
}}
QPushButton[sizeVariant="small"] {{
    padding: 4px 10px;
    font-size: 12.5px;
    border-radius: 7px;
}}

/* ---------- Поля ввода ---------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{
    background: {field};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {clay};
    selection-color: #141413;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
    border-color: {accent};
}}
QLineEdit[invalid="true"] {{ border-color: {bad}; }}
QPlainTextEdit, QTextEdit {{ font-family: "Geist Mono", "Cascadia Mono", monospace; font-size: 12.5px; }}
QLineEdit[secret="true"] {{ font-family: "Geist Mono", monospace; }}

QComboBox {{
    background: {field};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 7px 30px 7px 10px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {decor}; }}
QComboBox:disabled {{ color: {muted}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {bg};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {card2};
    selection-color: {text};
    outline: none;
}}

QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}

/* ---------- Прочие контролы ---------- */

QCheckBox, QRadioButton {{ spacing: 9px; color: {text}; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1.5px solid {ink3};
    background: {field};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked {{
    background: {ink};
    border-color: {ink};
    image: url("{check}");
}}
QRadioButton::indicator:checked {{
    background: {field};
    border: 5px solid {ink};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}

QProgressBar {{
    background: {card2};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {clay}; border-radius: 3px; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 3px 2px;
}}
QScrollBar::handle:vertical {{
    background: {scroll}; border-radius: 3px; min-height: 30px; margin: 0px 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {decor}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 3px; }}
QScrollBar::handle:horizontal {{ background: {scroll}; border-radius: 3px; min-width: 30px; margin: 2px 0px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {ink};
    color: {bg};
    border: none;
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12.5px;
}}

/* Вкладки внутри раздела. */
QFrame#SegmentBar {{
    background: {card};
    border: 1px solid {border};
    border-radius: 10px;
}}
QPushButton#SegmentButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 14px;
    color: {ink3};
    font-weight: 500;
}}
QPushButton#SegmentButton:hover {{ color: {text}; }}
QPushButton#SegmentButton:checked {{
    background: {bg};
    border: 1px solid {border_strong};
    color: {text};
}}

QDialog, QMessageBox {{
    background: {bg};
}}
QMessageBox QLabel {{
    color: {text};
    font-size: 13.5px;
    background: transparent;
}}
QMessageBox QPushButton {{
    min-width: 88px;
}}

QMenu {{
    background: {bg};
    border: 1px solid {border_strong};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background: {card}; color: {text}; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QSplitter::handle {{ background: {border}; }}

QTableWidget, QTreeWidget, QListWidget {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 10px;
    gridline-color: {border};
    selection-background-color: {card2};
    selection-color: {text};
    outline: none;
}}
QHeaderView::section {{
    background: {card};
    color: {ink3};
    border: none;
    border-bottom: 1px solid {border};
    padding: 6px 8px;
    font-family: "Geist Mono", monospace;
    font-size: 10.5px;
    font-weight: 500;
}}

/* ---------- Значки состояния: как штамп на бланке ---------- */

QLabel[badge] {{
    font-family: "Geist Mono", monospace;
    font-size: 10.5px;
    font-weight: 500;
    border-radius: 6px;
    padding: 3px 8px;
}}
QLabel[badge="ok"] {{ background: {success_bg}; color: {ok}; }}
QLabel[badge="warn"] {{ background: {warning_bg}; color: {warn}; }}
QLabel[badge="error"] {{ background: {danger_bg}; color: {bad}; }}
QLabel[badge="accent"] {{ background: {accent_soft}; color: {accent_ink}; }}
QLabel[badge="neutral"] {{ background: {card2}; color: {ink3}; }}
"""


def _asset(name: str, draw) -> str:
    """Маленькая картинка для стиля (стрелка списка, галочка) — PNG в кэше.

    PNG, а не SVG: SVG в стилях Qt читает отдельный плагин, и если его нет,
    стрелки просто пропадают.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    from app.core import paths

    folder = paths.cache_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.exists():
        image = QImage(48, 48, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(4, 4)
        draw(painter)
        painter.end()
        if not image.save(str(target)):
            return ""
    return target.as_posix()


def _stroke_asset(name: str, color: str, points, width: float) -> str:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPen, QPolygonF

    def draw(painter) -> None:
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

    return _asset(name, draw)


def build_qss(tokens: dict[str, str]) -> str:
    ink3 = tokens["ink3"].lstrip("#")
    bg = tokens["bg"].lstrip("#")
    chevron = _stroke_asset(f"chevron-{ink3}.png", tokens["ink3"],
                            ((3.0, 4.6), (6.0, 7.8), (9.0, 4.6)), 1.4)
    check = _stroke_asset(f"check-{bg}.png", tokens["bg"],
                          ((2.6, 6.4), (5.0, 8.8), (9.6, 3.4)), 1.6)
    return QSS_TEMPLATE.format(chevron=chevron, check=check, **tokens)
