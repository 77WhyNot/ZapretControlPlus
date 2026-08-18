"""Темы оформления: палитры, акцентные цвета и генерация QSS."""

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


THEMES: tuple[ThemeDef, ...] = (
    ThemeDef("rails", "Рельсы", True, {
        "bg": "#0E1219",
        "surface": "#121821",
        "surface_alt": "#161E29",
        "sidebar": "#0B0F15",
        "titlebar": "#0B0F15",
        "border": "#1E2733",
        "border_strong": "#2A3441",
        "text": "#DCE3ED",
        "text_dim": "#8593A6",
        "text_faint": "#5E6B7D",
        "hover": "#16202C",
        "input": "#0D131B",
        "code_bg": "#090D13",
        "success": "#3FD08A",
        "warning": "#E9A23B",
        "danger": "#E0284F",
        "success_bg": "#0F2A20",
        "warning_bg": "#2A2314",
        "danger_bg": "#2A121C",
        "scroll": "#2A3441",
    }),
    ThemeDef("light", "Светлая", False, {
        "bg": "#F3F5F8",
        "surface": "#FFFFFF",
        "surface_alt": "#F8FAFC",
        "sidebar": "#FFFFFF",
        "titlebar": "#FFFFFF",
        "border": "#E3E7ED",
        "border_strong": "#CDD4DE",
        "text": "#12161C",
        "text_dim": "#576070",
        "text_faint": "#8C95A4",
        "hover": "#EEF1F5",
        "input": "#FFFFFF",
        "code_bg": "#F6F8FA",
        "success": "#0E8A5F",
        "warning": "#B25E09",
        "danger": "#C6293B",
        "success_bg": "#E6F6EF",
        "warning_bg": "#FDF3E4",
        "danger_bg": "#FCEBEC",
        "scroll": "#C9D0DA",
    }),
    ThemeDef("dark", "Тёмная", True, {
        "bg": "#15181E",
        "surface": "#1D212A",
        "surface_alt": "#232833",
        "sidebar": "#1A1E26",
        "titlebar": "#1A1E26",
        "border": "#2C323E",
        "border_strong": "#3B4351",
        "text": "#E8ECF3",
        "text_dim": "#9CA7B8",
        "text_faint": "#6E7889",
        "hover": "#262C38",
        "input": "#1A1F28",
        "code_bg": "#12161D",
        "success": "#3ECF8E",
        "warning": "#E9A23B",
        "danger": "#F2606F",
        "success_bg": "#152A22",
        "warning_bg": "#2C2415",
        "danger_bg": "#2E1A1E",
        "scroll": "#39414F",
    }),
    ThemeDef("midnight", "Полночь", True, {
        "bg": "#080B12",
        "surface": "#101725",
        "surface_alt": "#151D2E",
        "sidebar": "#0C121D",
        "titlebar": "#0C121D",
        "border": "#1D2739",
        "border_strong": "#2B3852",
        "text": "#DEE5F2",
        "text_dim": "#8E9CB5",
        "text_faint": "#5F6C85",
        "hover": "#182134",
        "input": "#0D1420",
        "code_bg": "#070A11",
        "success": "#38D39F",
        "warning": "#EDAF4B",
        "danger": "#FF6B7E",
        "success_bg": "#0C2620",
        "warning_bg": "#2A2213",
        "danger_bg": "#2B1620",
        "scroll": "#2A3648",
    }),
    ThemeDef("sand", "Тёплая", False, {
        "bg": "#F6F2EC",
        "surface": "#FFFDFA",
        "surface_alt": "#FAF6F0",
        "sidebar": "#FFFDFA",
        "titlebar": "#FFFDFA",
        "border": "#E7DFD4",
        "border_strong": "#D2C7B8",
        "text": "#1E1A15",
        "text_dim": "#6A6055",
        "text_faint": "#968B7D",
        "hover": "#F1EBE2",
        "input": "#FFFDFA",
        "code_bg": "#F7F3ED",
        "success": "#0E8A5F",
        "warning": "#B25E09",
        "danger": "#C6293B",
        "success_bg": "#E8F5EE",
        "warning_bg": "#FBF1E1",
        "danger_bg": "#FBEAEA",
        "scroll": "#D6CCBE",
    }),
)

THEME_BY_KEY = {theme.key: theme for theme in THEMES}


@dataclass(frozen=True)
class AccentDef:
    key: str
    title: str
    base: str
    hover: str
    press: str
    on_accent: str = "#FFFFFF"


ACCENTS: tuple[AccentDef, ...] = (
    AccentDef("cyan", "Бирюзовый путь", "#22C6D8", "#3AD6E6", "#17A6B6", "#04131A"),
    AccentDef("ruby", "Рубин", "#C41E4A", "#D82B58", "#A4173C"),
    AccentDef("amber", "Янтарь", "#CF7211", "#E28320", "#AC5D0B"),
    AccentDef("emerald", "Изумруд", "#0E9F6E", "#16B27D", "#0A8159"),
    AccentDef("sapphire", "Сапфир", "#2563EB", "#3B76F0", "#1D4FC4"),
    AccentDef("violet", "Аметист", "#7C3AED", "#8C4FF2", "#672FC7"),
    AccentDef("teal", "Бирюза", "#0D8E93", "#12A2A8", "#0A7276"),
    AccentDef("graphite", "Графит", "#4A5567", "#5A6678", "#3A4353"),
)

ACCENT_BY_KEY = {accent.key: accent for accent in ACCENTS}


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


def resolve_theme_key(key: str) -> str:
    if key == "system":
        return "dark" if system_prefers_dark() else "light"
    return key if key in THEME_BY_KEY else "light"


def build_tokens(theme_key: str, accent_key: str) -> dict[str, str]:
    theme = THEME_BY_KEY[resolve_theme_key(theme_key)]
    accent = ACCENT_BY_KEY.get(accent_key, ACCENT_BY_KEY["ruby"])

    tokens = dict(theme.colors)
    tokens.update({
        "accent": accent.base,
        "accent_hover": accent.hover,
        "accent_press": accent.press,
        "on_accent": accent.on_accent,
        "is_dark": "1" if theme.dark else "0",
    })
    # Мягкие подложки акцента: на тёмной теме подмешиваем к фону, на светлой — к белому.
    base_for_tint = theme.colors["surface"]
    tokens["accent_soft"] = mix(base_for_tint, accent.base, 0.16 if theme.dark else 0.10)
    tokens["accent_soft_hover"] = mix(base_for_tint, accent.base, 0.24 if theme.dark else 0.16)
    tokens["accent_border"] = mix(theme.colors["border"], accent.base, 0.45)
    tokens["accent_text"] = accent.hover if theme.dark else accent.press
    tokens["overlay"] = rgba("#000000", 0.45 if theme.dark else 0.28)

    # Цвета маршрутов — это не украшение, а способ читать состояние:
    # один и тот же цвет означает один и тот же путь трафика во всей программе.
    tokens["lane_direct"] = "#7C8AA0" if theme.dark else "#68758A"
    tokens["lane_zapret"] = "#E0284F" if theme.dark else "#C41E4A"
    tokens["lane_vpn"] = "#22C6D8" if theme.dark else "#0E93A6"
    tokens["lane_direct_soft"] = mix(theme.colors["surface"], tokens["lane_direct"],
                                     0.18 if theme.dark else 0.12)
    tokens["lane_zapret_soft"] = mix(theme.colors["surface"], tokens["lane_zapret"],
                                     0.18 if theme.dark else 0.10)
    tokens["lane_vpn_soft"] = mix(theme.colors["surface"], tokens["lane_vpn"],
                                  0.18 if theme.dark else 0.10)
    return tokens


# Шрифты: Bahnschrift — это DIN, дорожный указатель. Для программы про
# маршруты трафика он к месту и есть в Windows 10 и 11 из коробки.
DISPLAY_FONT = '"Bahnschrift", "Franklin Gothic Medium", "Segoe UI", sans-serif'
MONO_FONT = '"Cascadia Mono", "Consolas", monospace'


# =========================================================================
# QSS
# =========================================================================

QSS_TEMPLATE = """
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: {text};
}}

/* Окно без системной рамки: скруглять углы нельзя — без прозрачности
   за ними остался бы мусор, поэтому рисуем аккуратную рамку в 1 пиксель. */
QWidget#Root {{
    background: {bg};
    border: 1px solid {border_strong};
}}

/* ---------- Заголовок окна ---------- */

QWidget#TitleBar {{
    background: {titlebar};
    border-bottom: 1px solid {border};
}}

QLabel#TitleText {{
    font-size: 13px;
    font-weight: 600;
    color: {text};
}}

QLabel#TitleVersion {{
    font-size: 11px;
    color: {text_faint};
}}

QPushButton#WinButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0px;
    min-width: 38px;
    max-width: 38px;
    min-height: 28px;
    max-height: 28px;
}}
QPushButton#WinButton:hover {{ background: {hover}; }}
QPushButton#WinButton:pressed {{ background: {border}; }}
QPushButton#WinClose:hover {{ background: {danger}; }}

/* ---------- Боковое меню ---------- */

QWidget#Sidebar {{
    background: {sidebar};
    border-right: 1px solid {border};
}}

QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: {text_dim};
}}
QPushButton#NavButton:hover {{
    background: {hover};
    color: {text};
}}
QPushButton#NavButton:checked {{
    background: {accent_soft};
    color: {accent_text};
    font-weight: 600;
}}

QLabel#NavSection {{
    color: {text_faint};
    font-size: 11px;
    font-weight: 600;
    padding: 6px 12px 2px 12px;
}}

/* ---------- Контент ---------- */

QWidget#Content {{ background: {bg}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QLabel#PageTitle {{
    font-family: "Bahnschrift", "Franklin Gothic Medium", "Segoe UI", sans-serif;
    font-size: 25px;
    font-weight: 600;
    letter-spacing: 0.2px;
    color: {text};
}}

QLabel[role="display"] {{
    font-family: "Bahnschrift", "Franklin Gothic Medium", "Segoe UI", sans-serif;
    font-weight: 600;
}}

QLabel[role="mono"], QPlainTextEdit[role="mono"] {{
    font-family: "Cascadia Mono", "Consolas", monospace;
}}

QLabel[lane="direct"] {{ color: {lane_direct}; }}
QLabel[lane="zapret"] {{ color: {lane_zapret}; }}
QLabel[lane="vpn"] {{ color: {lane_vpn}; }}
QLabel#PageSubtitle {{
    font-size: 13px;
    color: {text_dim};
}}
QLabel#SectionTitle {{
    font-size: 14px;
    font-weight: 620;
    color: {text};
}}
QLabel#Muted {{ color: {text_dim}; }}
QLabel#Faint {{ color: {text_faint}; font-size: 12px; }}

/* ---------- Карточки ---------- */

QFrame#Card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 14px;
}}
QFrame#CardAlt {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#Divider {{
    background: {border};
    max-height: 1px;
    border: none;
}}

/* ---------- Кнопки ---------- */

QPushButton {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: 9px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
    color: {text};
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {text_faint}; background: {surface_alt}; }}

QPushButton[variant="primary"] {{
    background: {accent};
    border: 1px solid {accent};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {accent_press}; border-color: {accent_press}; }}
QPushButton[variant="primary"]:disabled {{
    background: {border}; border-color: {border}; color: {text_faint};
}}

QPushButton[variant="soft"] {{
    background: {accent_soft};
    border: 1px solid {accent_border};
    color: {accent_text};
    font-weight: 600;
}}
QPushButton[variant="soft"]:hover {{ background: {accent_soft_hover}; }}

QPushButton[variant="danger"] {{
    background: {danger};
    border: 1px solid {danger};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{ background: {danger}; }}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {text_dim};
}}
QPushButton[variant="ghost"]:hover {{ background: {hover}; color: {text}; }}

QPushButton[size="large"] {{
    padding: 13px 26px;
    font-size: 14px;
    border-radius: 11px;
}}

/* ---------- Поля ввода ---------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{
    background: {input};
    border: 1px solid {border_strong};
    border-radius: 9px;
    padding: 8px 11px;
    selection-background-color: {accent};
    selection-color: {on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
    border-color: {accent};
}}
QPlainTextEdit, QTextEdit {{ font-family: "Cascadia Mono", "Consolas", monospace; }}

QComboBox {{
    background: {input};
    border: 1px solid {border_strong};
    border-radius: 9px;
    padding: 7px 11px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {accent_border}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {accent_soft};
    selection-color: {accent_text};
    outline: none;
}}

/* ---------- Прочие контролы ---------- */

QCheckBox, QRadioButton {{ spacing: 8px; color: {text}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {border_strong};
    background: {input};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}

QProgressBar {{
    background: {border};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {scroll}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {scroll}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 7px;
    padding: 6px 9px;
}}

QMenu {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: 9px;
    padding: 5px;
}}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {accent_text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QSplitter::handle {{ background: {border}; }}

/* ---------- Значки состояния ---------- */

QLabel[badge="ok"] {{
    background: {success_bg}; color: {success};
    border-radius: 7px; padding: 3px 9px; font-size: 12px; font-weight: 600;
}}
QLabel[badge="warn"] {{
    background: {warning_bg}; color: {warning};
    border-radius: 7px; padding: 3px 9px; font-size: 12px; font-weight: 600;
}}
QLabel[badge="error"] {{
    background: {danger_bg}; color: {danger};
    border-radius: 7px; padding: 3px 9px; font-size: 12px; font-weight: 600;
}}
QLabel[badge="accent"] {{
    background: {accent_soft}; color: {accent_text};
    border-radius: 7px; padding: 3px 9px; font-size: 12px; font-weight: 600;
}}
QLabel[badge="neutral"] {{
    background: {hover}; color: {text_dim};
    border-radius: 7px; padding: 3px 9px; font-size: 12px; font-weight: 600;
}}
"""


def build_qss(tokens: dict[str, str]) -> str:
    return QSS_TEMPLATE.format(**tokens)
