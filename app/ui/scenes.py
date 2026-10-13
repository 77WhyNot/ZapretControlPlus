"""Сцены программы: сад за стеной, марки, грядка, море, голубятня и прочие.

Каждая функция возвращает Scene в координатах своего viewBox. Части,
которые зависят от состояния, лежат в группах с state=… и role=live
(включено — нарисовано красками) или role=sketch (выключено — набросок).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF

from app.ui.ink import (
    LEAF,
    Scene,
    circle,
    drift,
    flap,
    floating,
    placed,
    rect,
    sway,
    sway_at,
    twinkle,
)

# =========================================================================
# Общие кусочки
# =========================================================================


def _flower(s: Scene, cx: float, cy: float, r: float = 6.5, petal: str = "clay",
            heart: str = "manilla", gouache: bool = True) -> None:
    for k in range(5):
        a = -math.pi / 2 + k * 2 * math.pi / 5
        d = r * 1.1
        s.paint(circle(cx + d * math.cos(a), cy + d * math.sin(a), r), petal, gouache)
    s.paint(circle(cx, cy, r * 0.58), heart, False)
    s.ink(circle(cx, cy, r * 0.58), thin=True)


def _leaf(s: Scene, x: float, y: float, rot: float, scale: float = 1.0,
          role: str = "olive", delay: float = 0.0) -> None:
    s.paint(placed(LEAF, x, y, rot, scale), role, delay=delay)


def _grass(s: Scene, x: float, y: float, phase: float = 0.0, slow: bool = False) -> None:
    with s.group(anim=sway(3, 5.2 if slow else 4.0), phase=phase):
        s.ink(f"M{x} {y} L{x - 2} {y - 10} M{x + 4} {y} L{x + 6} {y - 12} "
              f"M{x + 8} {y} L{x + 12} {y - 8}", thin=True)


def _cloud(s: Scene, d: str, amp: float = 14, period: float = 18, phase: float = 0) -> None:
    with s.group(anim=drift(amp, period), phase=phase):
        s.ink(d, thin=True)


def _sun_or_moon(s: Scene, cx: float, cy: float, r: float = 34) -> None:
    with s.group(only="light"):
        with s.group(anim=floating(6, 6.4)):
            s.paint(circle(cx, cy, r), "clay")
    with s.group(only="dark"):
        with s.group(anim=floating(6, 6.4)):
            s.paint(circle(cx, cy, r * 0.82), "manilla")
            s.paint(circle(cx + r * 0.38, cy - r * 0.26, r * 0.7), "cut", gouache=False)


def _stars(s: Scene, points) -> None:
    with s.group(only="dark"):
        for k, (x, y, r) in enumerate(points):
            with s.group(anim=twinkle(3.2), phase=-k * 0.9):
                s.paint(circle(x, y, r), "ink", gouache=False)


# =========================================================================
# Главная: сад за стеной
# =========================================================================

GARDEN_REGIONS = {
    "dpi": (QRectF(96, 120, 150, 145), "Обход DPI — открыть «Запрет»"),
    "vpn": (QRectF(318, 120, 92, 150), "VPN — открыть подключение"),
    "tg": (QRectF(212, 52, 96, 120), "Telegram — открыть раздел"),
    "dns": (QRectF(418, 140, 104, 128), "Smart DNS — открыть раздел"),
}


def garden() -> Scene:
    """Сад за каменной стеной. Лоза — обход, калитка к морю — VPN, птица с
    письмом — Telegram, указатель — Smart DNS."""
    s = Scene(560, 300)

    _sun_or_moon(s, 446, 80)
    with s.group(only="light"):
        _cloud(s, "M88 74 C 84 64, 96 56, 106 62 C 110 50, 130 50, 134 62 "
                  "C 146 58, 156 68, 148 76 Z")
        _cloud(s, "M232 52 C 230 44, 240 40, 247 44 C 251 36, 265 37, 267 45 "
                  "C 275 44, 279 51, 273 54 Z", period=24, phase=-6)
    _stars(s, [(92, 58, 1.3), (168, 34, 1.1), (246, 76, 1.4), (316, 40, 1.1), (372, 98, 1.2)])

    # Холмы и стена.
    s.paint("M0 176 C 60 140, 130 136, 200 156 C 260 172, 320 150, 380 146 "
            "C 440 142, 500 132, 560 142 L560 262 L0 262 Z", "hill2")
    s.ink("M0 176 C 60 140, 130 136, 200 156 C 260 172, 320 150, 380 146 "
          "C 440 142, 500 132, 560 142", thin=True, opacity=0.55)
    s.paint("M46 262 L46 172 L514 170 L514 262 Z", "wall")
    s.ink("M42 262 L43 176 Q44 168 53 168 L506 167 Q515 167 516 176 L518 262")
    s.ink("M44 179 C 180 177, 340 180, 516 177", thin=True)
    s.ink("M44 205 Q 180 202 324 206 M386 205 Q 450 203 516 204", thin=True)
    s.ink("M44 234 Q 180 236 324 232 M386 233 Q 450 236 517 234", thin=True)
    s.ink("M92 180 L91 204 M160 179 L161 203 M226 179 L225 204 M290 180 L291 205 "
          "M420 179 L419 204 M478 178 L479 203", thin=True)
    s.ink("M68 206 L69 233 M128 205 L127 234 M196 204 L197 234 M258 205 L257 233 "
          "M304 206 L305 232 M406 205 L405 233 M454 204 L455 234 M500 204 L499 234", thin=True)
    s.ink("M100 236 L101 261 M168 235 L167 262 M236 234 L237 262 M296 233 L295 262 "
          "M432 235 L433 262 M488 235 L487 262", thin=True)
    s.ink("M324 262 L324 210 Q324 186 355 186 Q386 186 386 210 L386 262")

    # VPN: калитка в стене, за ней море; флажок на шесте.
    with s.group(state="vpn", role="sketch"):
        s.pen("M340 193 L340 261 M355 189 L355 261 M370 193 L370 261")
        s.pen(circle(378, 230, 3))
    with s.group(state="vpn", role="live"):
        s.paint("M327 262 L327 211 Q327 190 355 190 Q383 190 383 211 L383 262 Z", "glow",
                bloom=True)
        s.paint("M330 240 C 342 236, 356 238, 366 235 C 372 234, 378 236, 382 238 "
                "L382 262 L330 262 Z", "sky", gouache=False, fade=True)
        s.ink("M332 240 C 342 236, 356 238, 366 235 C 372 234, 378 236, 382 238",
              thin=True, draw=True)
        s.paint("M387 262 L405 269 L405 199 L387 190 Z", "kraft", bloom=True)
        s.ink("M386 190 L405 199 L405 269 L386 262", draw=True)
        s.ink("M355 167 L355 132", draw=True)
        with s.group(anim=sway(3, 4.0, 0.0, 0.5), fade=True):
            s.paint("M356 133 C 366 132, 374 136, 384 137 C 375 142, 366 146, 356 148 Z", "sky")
            s.ink("M356 133 C 366 132, 374 136, 384 137 C 375 142, 366 146, 356 148", thin=True)

    # Обход: лоза по стене с цветком.
    with s.group(state="dpi", role="sketch"):
        s.pen("M122 262 C 119 252, 126 246, 122 236")
        s.pen("M122 248 C 116 243, 112 245, 109 249")
    with s.group(state="dpi", role="live"):
        s.ink("M120 262 C 106 240, 136 226, 124 206 C 112 186, 126 164, 150 158 "
              "C 176 152, 194 166, 198 186 C 202 206, 216 214, 234 208", draw=True)
        with s.group(bloom=True):
            for k, (x, y, rot) in enumerate(((115, 245, 205), (127, 226, -25), (118, 201, 195),
                                             (122, 179, -50), (170, 156, -70), (191, 172, 15),
                                             (198, 196, 165), (216, 211, 5))):
                _leaf(s, x, y, rot, delay=0.05 + k * 0.08)
        with s.group(anim=sway(3, 4.0)):
            s.ink("M150 158 L148 147", thin=True, draw=True)
            with s.group(bloom=True, delay=0.7):
                _flower(s, 148, 141, 6.5)

    # Telegram: птица с письмом взлетает с земли.
    with s.group(state="tg", role="sketch"):
        s.pen("M246 166 C 244 156, 256 150, 268 152 C 272 145, 284 144, 287 151 L 295 154 "
              "L 287 157 C 286 163, 279 167, 268 167 Z")
        s.pen("M246 163 L234 159 L238 167 Z")
        s.pen("M254 159 C 262 155, 270 157, 276 161")
    with s.group(state="tg", role="live", lift=70):
        with s.group(anim=floating(5, 5.0)):
            _bird(s, draw=True)

    # Smart DNS: указатель.
    with s.group(state="dns", role="sketch"):
        s.pen("M470 266 L468 146")
        s.pen("M471 152 L506 152 L515 160 L506 168 L471 168 Z")
        s.pen("M466 178 L432 178 L423 186 L432 194 L466 194 Z")
    with s.group(state="dns", role="live"):
        s.paint("M466 266 L465 146 L472 146 L473 266 Z", "kraft", bloom=True)
        s.ink("M470 266 L468 144", draw=True)
        with s.group(anim=sway(2.2, 5.2, 0.0, 0.5)):
            s.paint("M471 152 L506 152 L515 160 L506 168 L471 168 Z", "olive", bloom=True,
                    delay=0.1)
            s.ink("M471 152 L506 152 L515 160 L506 168 L471 168 Z", draw=True)
            s.text("$dns_sign", 476, 163.5, 8.5, fade=True, spacing=0.06)
        s.paint("M466 178 L432 178 L423 186 L432 194 L466 194 Z", "kraft", bloom=True,
                delay=0.2)
        s.ink("M466 178 L432 178 L423 186 L432 194 L466 194 Z", draw=True)
        s.text("DNS", 436, 189.5, 8.5, fade=True, spacing=0.06)
    s.texts["dns_sign"] = "COMSS"

    # Земля и трава.
    s.paint("M0 258 C 140 252, 300 264, 560 254 L560 300 L0 300 Z", "ground")
    s.ink("M0 260 C 140 254, 300 266, 560 256")
    _grass(s, 60, 262)
    _grass(s, 262, 266, -1.3, slow=True)
    _grass(s, 520, 259, -2.1)

    # Ночью над садом светлячки — пока хоть что-то работает.
    with s.group(only="dark"):
        with s.group(state="any", role="live"):
            for k, (x, y, r) in enumerate(((92, 128, 2.2), (214, 112, 2.0),
                                           (300, 148, 2.2), (396, 118, 1.8))):
                with s.group(anim=floating(5, 5.0 + (k % 2) * 1.4), phase=-k):
                    with s.group(anim=twinkle(3.2), phase=-k * 0.7):
                        s.glow(x, y, r)
    return s


def _bird(s: Scene, draw: bool = False, dx: float = 0.0, dy: float = 0.0) -> None:
    """Птица с письмом в лапах (из макета главной)."""
    def p(d: str) -> str:
        if not dx and not dy:
            return d
        from app.ui.ink import as_path

        from PySide6.QtGui import QTransform

        return QTransform.fromTranslate(dx, dy).map(as_path(d))

    # Крылья машут вместе с краской, иначе контур уезжал бы с заливки.
    with s.group(anim=flap(0.7)):
        s.paint(p("M248 95 C 244 80, 236 70, 226 66 C 238 78, 246 88, 258 95 Z"), "kraft",
                bloom=True)
        s.ink(p("M248 95 C 244 80, 236 70, 226 66 C 238 78, 246 88, 258 95"), draw=draw)
    with s.group(anim=flap(0.7), phase=-0.12):
        s.paint(p("M258 95 C 262 80, 272 68, 284 62 C 276 74, 272 86, 268 95 Z"), "kraft",
                bloom=True)
        s.ink(p("M258 95 C 262 80, 272 68, 284 62 C 276 74, 272 86, 268 95"), draw=draw)
    s.paint(p("M232 98 C 238 90, 262 88, 272 94 C 278 89, 286 91, 288 96 L 295 98 "
              "L 288 100 C 282 104, 260 106, 240 102 Z"), "manilla", bloom=True)
    s.ink(p("M232 98 C 238 90, 262 88, 272 94 C 278 89, 286 91, 288 96 L 295 98 L 288 100 "
            "C 282 104, 260 106, 240 102 Z"), draw=draw)
    s.ink(p("M234 99 L220 92 L222 105 Z"), draw=draw)
    s.paint(circle(283 + dx, 94 + dy, 1.4), "ink", gouache=False)
    with s.group(bloom=True, delay=0.35):
        s.paint(rect(286 + dx, 101 + dy, 13, 9, 1), "glow", gouache=False)
        s.paint(circle(292.5 + dx, 107 + dy, 1.8), "clay", gouache=False)
    s.ink(p("M286 101 L299 101 L299 110 L286 110 Z M286 101 L292.5 106 L299 101"), thin=True)


# =========================================================================
# Марки главной (200×140, всегда на светлой бумаге)
# =========================================================================


def stamp_dpi() -> Scene:
    s = Scene(200, 140)
    with s.group(state="on", role="live", bloom=True):
        s.paint("M0 74 L200 72 L200 140 L0 140 Z", "wall")
    s.ink("M0 74 L200 72", role="ink")
    s.ink("M0 98 Q100 95 200 98 M0 122 Q100 124 200 121 M40 74 L41 98 M100 73 L99 98 "
          "M160 72 L161 98 M70 98 L71 122 M130 98 L129 122 M190 98 L189 122 M30 122 L31 140 "
          "M110 122 L109 140 M170 122 L171 140", thin=True, width=1.4)
    with s.group(state="on", role="sketch"):
        s.ink("M52 140 C 40 118, 68 104, 60 86 C 52 70, 66 52, 92 48 C 116 44, 128 58, 130 76 "
              "C 132 92, 144 100, 160 96", role="pencil", width=2.0)
        s.ink("M92 48 L91 42", role="pencil", width=1.4)
        s.ink(circle(91, 38, 3.2), role="pencil", width=1.4)
    with s.group(state="on", role="live"):
        s.ink("M52 140 C 40 118, 68 104, 60 86 C 52 70, 66 52, 92 48 C 116 44, 128 58, 130 76 "
              "C 132 92, 144 100, 160 96", width=2.0, draw=True)
        with s.group(bloom=True):
            for k, (x, y, rot) in enumerate(((46, 124, 205), (64, 104, -25), (54, 84, 195),
                                             (60, 64, -50), (110, 46, -70), (128, 64, 15),
                                             (132, 88, 165), (150, 100, 5))):
                _leaf(s, x, y, rot, delay=k * 0.06)
        with s.group(anim=sway(3, 4.0)):
            s.ink("M92 48 L91 42", width=1.4, draw=True)
            with s.group(bloom=True, delay=0.6):
                for k in range(5):
                    a = -math.pi / 2 + k * 2 * math.pi / 5
                    s.paint(circle(91 + 6 * math.cos(a), 38 + 6 * math.sin(a), 5.5), "clay")
                s.paint(circle(91, 38, 3.2), "manilla", gouache=False)
            s.ink(circle(91, 38, 3.2), width=1.4)
    return s


def stamp_vpn() -> Scene:
    s = Scene(200, 140)
    with s.group(state="on", role="live", bloom=True):
        s.paint("M0 64 L200 62 L200 140 L0 140 Z", "wall")
        s.paint("M78 140 L78 92 Q78 76 100 76 Q122 76 122 92 L122 140 Z", "glow")
        s.paint("M80 118 C 90 114, 110 116, 120 113 L120 140 L80 140 Z", "sky")
        s.paint("M104 112 L106 96 L111 96 L113 112 Z", "paper", gouache=False)
        s.paint("M105 104 L112 104 L112.4 107 L104.6 107 Z", "clay", gouache=False)
    with s.group(state="on", role="live", fade=True):
        s.ink("M104 112 L106 96 L111 96 L113 112 M105 96 L108.5 91 L112 96", width=1.4)
    s.ink("M0 64 L200 62")
    s.ink("M0 88 Q40 86 76 88 M124 88 Q160 86 200 88 M0 112 Q40 114 76 112 M124 112 "
          "Q160 114 200 112 M36 64 L37 88 M160 63 L159 88 M20 88 L21 112 M56 88 L55 112 "
          "M144 88 L145 112 M184 88 L183 112 M38 112 L39 140 M168 112 L167 140", width=1.4)
    s.ink("M76 140 L76 92 Q76 72 100 72 Q124 72 124 92 L124 140")
    with s.group(state="on", role="sketch"):
        s.ink("M90 80 L90 139 M100 77 L100 139 M110 80 L110 139", role="pencil", width=1.4)
        s.ink("M100 62 L100 32", role="pencil", width=1.6)
    with s.group(state="on", role="live"):
        s.paint("M125 140 L142 146 L142 84 L125 76 Z", "kraft", bloom=True)
        s.ink("M124 76 L142 84 L142 146", draw=True)
        s.ink("M100 62 L100 32", draw=True)
        with s.group(anim=sway(3, 4.0, 0.0, 0.5), fade=True):
            s.paint("M101 33 C 110 32, 116 36, 124 37 C 116 41, 110 44, 101 46 Z", "sky")
            s.ink("M101 33 C 110 32, 116 36, 124 37 C 116 41, 110 44, 101 46", width=1.4)
    return s


def stamp_tg() -> Scene:
    s = Scene(200, 140)
    with s.group(state="on", role="live", bloom=True):
        s.paint("M0 120 C 40 104, 90 108, 120 116 C 150 124, 180 110, 200 112 L200 140 "
                "L0 140 Z", "matcha")
    s.ink("M0 120 C 40 104, 90 108, 120 116 C 150 124, 180 110, 200 112")
    with s.group(state="on", role="sketch"):
        s.ink("M14 110 C 30 84, 52 74, 62 86 C 70 96, 52 102, 51 90 C 50 76, 70 70, 86 76",
              role="pencil", width=1.4)
    with s.group(state="on", role="live"):
        s.flow("M14 110 C 30 84, 52 74, 62 86 C 70 96, 52 102, 51 90 C 50 76, 70 70, 86 76",
               width=1.4, dash=(3, 5), speed=11)
    with s.group(state="on", role="sketch"):
        with s.group(anim=None):
            s.ink(placed("M232 98 C 238 90, 262 88, 272 94 C 278 89, 286 91, 288 96 L 295 98 "
                         "L 288 100 C 282 104, 260 106, 240 102 Z M234 99 L220 92 L222 105 Z "
                         "M248 95 C 244 80, 236 70, 226 66 C 238 78, 246 88, 258 95 "
                         "M258 95 C 262 80, 272 68, 284 62 C 276 74, 272 86, 268 95",
                         -132, -26), role="pencil", width=1.8)
    with s.group(state="on", role="live"):
        with s.group(anim=floating(5, 5.0)):
            _bird(s, draw=True, dx=-132, dy=-26)
    return s


def stamp_dns() -> Scene:
    s = Scene(200, 140)
    with s.group(state="on", role="live", bloom=True):
        s.paint("M0 124 C 60 118, 140 128, 200 120 L200 140 L0 140 Z", "matcha")
    s.ink("M0 124 C 60 118, 140 128, 200 120")
    with s.group(state="on", role="live", bloom=True):
        s.paint("M96 132 L95 22 L102 22 L103 132 Z", "kraft")
    s.ink("M99 132 L98 20")
    with s.group(anim=sway(2.2, 5.2, 0.0, 0.5)):
        with s.group(state="on", role="live", bloom=True):
            s.paint("M101 30 L150 30 L160 40 L150 50 L101 50 Z", "olive")
        s.ink("M101 30 L150 30 L160 40 L150 50 L101 50 Z")
        s.text("$sign", 108, 44, 10, spacing=0.06)
    with s.group(state="on", role="live", bloom=True, delay=0.1):
        s.paint("M96 60 L50 60 L40 70 L50 80 L96 80 Z", "kraft")
    s.ink("M96 60 L50 60 L40 70 L50 80 L96 80 Z")
    s.text("DoH", 56, 74, 10, spacing=0.06)
    with s.group(state="on", role="live", bloom=True, delay=0.2):
        s.paint("M101 90 L144 90 L152 98 L144 106 L101 106 Z", "manilla")
    s.ink("M101 90 L144 90 L152 98 L144 106 L101 106 Z")
    s.text("$addr", 106, 102, 8.5, spacing=0.06)
    s.ink("M30 126 L28 118 M34 126 L36 116 M164 122 L162 114 M168 122 L171 113", width=1.4)
    s.texts["sign"] = "COMSS"
    s.texts["addr"] = "1.1.1.1"
    return s


# =========================================================================
# Запрет: виньетка и грядка стратегий
# =========================================================================


def sprouts_vignette() -> Scene:
    s = Scene(240, 104)
    _cloud(s, "M168 26 C 166 18, 176 14, 183 18 C 187 10, 201 11, 203 19 C 211 18, 215 25, "
              "209 28 Z", amp=12)
    s.paint("M0 84 C 60 80, 160 88, 240 82 L240 104 L0 104 Z", "soil")
    s.ink("M0 85 C 60 81, 160 89, 240 83")
    with s.group(anim=sway(3, 4.4)):
        s.ink("M70 85 C 66 72, 74 60, 70 50")
        _leaf(s, 69, 72, 205, 0.7)
        bud = "M70 42 C 75 47, 74 53, 70 52 C 66 53, 65 47, 70 42 Z"
        s.paint(bud, "olive", gouache=False)
        s.ink(bud, thin=True)
    with s.group(anim=sway(3, 4.0), phase=-1.0):
        s.ink("M120 85 C 115 64, 126 42, 120 26")
        _leaf(s, 119, 68, 205, 0.75)
        _leaf(s, 121, 50, -28, 0.75)
        _flower(s, 120, 18, 5.5)
    with s.group(anim=sway(3, 3.7), phase=-2.0):
        s.ink("M170 85 C 168 78, 172 72, 170 66")
        _leaf(s, 171, 76, -28, 0.6)
    return s


# =========================================================================
# VPN: карта «из сада морем»
# =========================================================================


def sea_map() -> Scene:
    s = Scene(1000, 170)
    _cloud(s, "M300 40 q6 -6 12 0 q6 -6 12 0 M346 58 q4 -4 8 0 q4 -4 8 0")
    _cloud(s, "M600 34 C 598 26, 608 22, 615 26 C 619 18, 633 19, 635 27 C 643 26, 647 33, "
              "641 36 Z", period=22)
    s.paint("M0 120 C 60 104, 140 106, 240 116 L240 170 L0 170 Z", "hill2")
    s.paint("M0 150 L0 70 L170 68 L170 150 Z", "wall")
    s.ink("M0 72 L170 70 L170 150")
    s.ink("M0 96 Q40 94 88 96 M142 96 L170 95 M0 122 Q40 124 88 122 M142 122 L170 121 "
          "M30 72 L31 96 M60 96 L59 122 M156 70 L157 95 M24 122 L25 150", thin=True)
    s.paint("M92 150 L92 105 Q92 89 115 89 Q138 89 138 105 L138 150 Z", "glow")
    s.ink("M90 150 L90 104 Q90 86 115 86 Q140 86 140 104 L140 150")
    s.paint("M141 150 L156 155 L156 98 L141 90 Z", "kraft")
    s.ink("M140 90 L156 98 L156 155")
    s.ink("M115 70 L115 42")
    with s.group(anim=sway(3, 4.0, 0.0, 0.5)):
        s.paint("M116 43 C 124 42, 130 46, 138 47 C 130 51, 124 54, 116 56 Z", "sky")
        s.ink("M116 43 C 124 42, 130 46, 138 47 C 130 51, 124 54, 116 56", thin=True)
    s.paint("M0 150 C 100 148, 180 152, 260 146 L260 170 L0 170 Z", "ground")
    s.ink("M0 150 C 100 148, 180 152, 260 146")
    s.paint("M232 132 C 400 124, 600 132, 1000 126 L1000 170 L232 170 Z", "sea")
    s.ink("M232 132 C 400 124, 600 132, 1000 126", thin=True)
    s.ink("M240 134 L292 134 M250 134 L250 148 M266 134 L266 148 M282 134 L282 148")
    with s.group(anim=drift(14, 18)):
        s.ink("M380 152 q6 -5 12 0 q6 5 12 0 M540 160 q6 -5 12 0 q6 5 12 0 "
              "M720 150 q6 -5 12 0 q6 5 12 0 M960 158 q6 -5 12 0 q6 5 12 0",
              thin=True, opacity=0.5)
    # Соседние берега — карандашом: их можно выбрать.
    s.ink("M540 132 C 550 122, 580 120, 600 128", role="pencil", width=1.6)
    s.text("$alt1", 570, 116, 9.5, role="pencil", anchor="middle", spacing=0.1)
    s.ink("M690 130 C 700 120, 724 120, 738 128", role="pencil", width=1.6)
    s.text("$alt2", 714, 112, 9.5, role="pencil", anchor="middle", spacing=0.1)
    route = ("M115 142 C 160 144, 210 136, 262 132 C 420 120, 640 104, 860 124")
    with s.group(state="on", role="sketch"):
        s.ink(route, role="pencil", width=2.0)
    with s.group(state="on", role="live"):
        s.ink(route, role="sky", width=3.0, draw=True, breathe=False)
        s.flow(route, role="plate", width=1.4, dash=(3, 13), speed=14.5)
        with s.group(dynamic="boat"):
            s.paint("M-10 0 L10 0 L7 5 L-7 5 Z", "kraft", gouache=False)
            s.paint("M0 -1 L0 -14 L9 -3 Z", "manilla", gouache=False)
            s.ink("M-10 0 L10 0 L7 5 L-7 5 Z M0 -1 L0 -14 L9 -3 L0 -3", thin=True,
                  breathe=False)
    s.motion("boat", "M262 132 C 420 120, 640 104, 860 124", period=9.0)
    # Остров с маяком.
    s.paint("M840 136 C 852 118, 900 112, 940 122 C 962 128, 966 136, 950 140 Z", "kraft")
    s.ink("M840 136 C 852 118, 900 112, 940 122 C 962 128, 966 136, 950 140", thin=True)
    with s.group(state="on", role="live"):
        with s.group(anim=sway_at(6, 6.0, 902, 96), fade=True):
            s.paint("M902 96 L966 78 L966 106 Z", "glow", gouache=False, opacity=0.75)
    s.paint("M895 122 L898 98 L907 98 L910 122 Z", "manilla", gouache=False)
    s.paint("M896.5 112 L908.5 112 L909 116 L896 116 Z M897.6 104 L907.4 104 L907.8 107.5 "
            "L897.2 107.5 Z", "clay", gouache=False)
    s.ink("M895 122 L898 98 L907 98 L910 122 M896 92 L909 92 L909 98 L896 98 Z "
          "M894 93 L902.5 85 L911 93", thin=True)
    s.text("$name", 902, 64, 16, kind="serif", italic=True, anchor="middle")
    s.text("$sub", 902, 48, 9.5, role="ink3", anchor="middle", spacing=0.1)
    # Роза ветров.
    with s.group(anim=None):
        s.ink(circle(974, 30, 12), thin=True)
        s.paint("M974 20 L977 30 L974 32 L971 30 Z", "clay", gouache=False)
        s.paint("M974 40 L977 30 L974 28 L971 30 Z", "ink", gouache=False, opacity=0.7)
    s.text("САД", 18, 164, 9.5, role="ink3", spacing=0.1)
    s.texts.update({"name": "", "sub": "", "alt1": "", "alt2": ""})
    return s


# =========================================================================
# VPN → Программы: лодочная станция
# =========================================================================


def boathouse() -> Scene:
    s = Scene(240, 104)
    s.paint("M0 74 C 60 70, 160 78, 240 72 L240 104 L0 104 Z", "sea")
    s.ink("M0 75 C 60 71, 160 79, 240 73", thin=True)
    s.ink("M24 74 L24 48 L92 48 L92 74 M18 50 L58 30 L98 50", width=2.0)
    s.paint("M26 74 L26 50 L90 50 L90 74 Z", "wall")
    s.paint("M48 74 L48 58 L68 58 L68 74 Z", "glow", gouache=False)
    s.ink("M48 74 L48 58 L68 58 L68 74", thin=True)
    s.ink("M8 80 L110 80 M20 80 L20 92 M50 80 L50 92 M80 80 L80 92", thin=True)
    with s.group(anim=floating(2.5, 3.6)):
        s.paint("M126 82 L166 82 L160 90 L132 90 Z", "kraft", gouache=False)
        s.ink("M126 82 L166 82 L160 90 L132 90 Z", thin=True)
    with s.group(anim=floating(2.5, 4.2), phase=-1.4):
        s.paint("M178 86 L210 86 L205 93 L183 93 Z", "sky", gouache=False)
        s.ink("M178 86 L210 86 L205 93 L183 93 Z M194 86 L194 70 L204 84", thin=True)
    with s.group(anim=drift(10, 16)):
        s.ink("M150 34 q5 -5 10 0 q5 -5 10 0", thin=True)
    return s


# =========================================================================
# Telegram: голубятня
# =========================================================================


def dovecote() -> Scene:
    """Голубятня на этом компьютере, дом Telegram вдали; голубь носит письма."""
    s = Scene(1000, 170)
    _sun_or_moon(s, 900, 46, 22)
    _stars(s, [(260, 30, 1.2), (420, 52, 1.1), (610, 24, 1.3), (720, 60, 1.0)])
    with s.group(only="light"):
        _cloud(s, "M330 40 C 328 32, 338 28, 345 32 C 349 24, 363 25, 365 33 C 373 32, 377 39, "
                  "371 42 Z", amp=16, period=20)
        _cloud(s, "M600 58 C 598 50, 608 46, 615 50 C 619 42, 633 43, 635 51 C 643 50, 647 57, "
                  "641 60 Z", amp=12, period=24, phase=-7)
    # Холмы и поле.
    s.paint("M0 122 C 90 104, 200 106, 300 118 C 420 130, 560 112, 700 116 C 820 120, 900 104, "
            "1000 110 L1000 170 L0 170 Z", "hill2")
    s.ink("M0 122 C 90 104, 200 106, 300 118 C 420 130, 560 112, 700 116 C 820 120, 900 104, "
          "1000 110", thin=True, opacity=0.5)
    s.paint("M0 146 C 200 140, 520 152, 1000 142 L1000 170 L0 170 Z", "ground")
    s.ink("M0 147 C 200 141, 520 153, 1000 143")
    # Дорожка между голубятней и домом.
    s.ink("M200 150 C 360 156, 560 146, 780 150", role="decor", width=1.4, opacity=0.8)
    # Голубятня на столбе.
    s.paint("M136 148 L135 84 L143 84 L144 148 Z", "kraft")
    s.ink("M139.5 148 L139 82")
    s.paint("M112 86 L168 86 L168 56 L112 56 Z", "wall")
    s.ink("M110 86 L170 86 M112 86 L112 56 L168 56 L168 86 M104 58 L140 34 L176 58")
    s.paint("M124 82 Q124 70 131 70 Q138 70 138 82 Z", "ink", gouache=False, opacity=0.85)
    s.paint("M144 82 Q144 72 150 72 Q156 72 156 82 Z", "ink", gouache=False, opacity=0.85)
    s.ink("M118 82 L162 82", thin=True)
    # Изгородь.
    s.ink("M20 148 L20 128 M44 148 L44 126 M68 148 L68 128 M12 134 L76 132 M12 142 L76 141",
          thin=True)
    # Путь письма.
    route = "M176 62 C 330 0, 620 4, 790 84"
    with s.group(state="on", role="sketch"):
        s.ink(route, role="pencil", width=1.4)
    with s.group(state="on", role="live"):
        s.flow(route, width=1.4, dash=(3, 7), speed=13)
        with s.group(dynamic="bird"):
            with s.group(anim=floating(2.5, 2.2)):
                s.paint("M-9 0 C -5 -5, 7 -5, 10 0 L 14 1 L 10 2 C 6 6, -5 5, -9 0 Z",
                        "manilla", gouache=False)
                s.ink("M-9 0 C -5 -5, 7 -5, 10 0 L 14 1 L 10 2 C 6 6, -5 5, -9 0 Z",
                      thin=True, breathe=False)
                s.paint(rect(6, 3, 9, 6, 1), "glow", gouache=False)
                s.ink("M6 3 L15 3 L15 9 L6 9 Z M6 3 L10.5 6.5 L15 3", width=1.0, breathe=False)
                with s.group(anim=flap(0.45)):
                    s.ink("M-1 -1 C -4 -10, -11 -15, -17 -16 C -10 -10, -5 -5, 2 -1",
                          thin=True, breathe=False)
    s.motion("bird", route, period=6.0)
    # Дом Telegram.
    s.paint("M780 148 L780 96 L860 96 L860 148 Z", "wall")
    s.ink("M778 148 L778 96 L862 96 L862 148 M772 98 L820 64 L868 98")
    s.paint("M800 148 L800 118 L820 118 L820 148 Z", "kraft")
    s.ink("M800 148 L800 118 L820 118 L820 148", thin=True)
    with s.group(state="on", role="live", fade=True):
        s.paint("M832 108 L848 108 L848 124 L832 124 Z", "glow", gouache=False)
    s.ink("M832 108 L848 108 L848 124 L832 124 Z M840 108 L840 124", thin=True)
    # Почтовый ящик: флажок поднят, пока письма ходят.
    s.ink("M890 148 L890 122", thin=True)
    s.paint("M880 112 L900 112 L900 124 L880 124 Z", "sky", gouache=False)
    s.ink("M880 112 L900 112 L900 124 L880 124 Z", thin=True)
    with s.group(state="on", role="sketch"):
        s.ink("M900 120 L908 120", role="pencil", width=1.4)
    with s.group(state="on", role="live", fade=True):
        with s.group(anim=sway(4, 2.6, 0.0, 1.0)):
            s.ink("M902 122 L902 106", thin=True)
            s.paint("M902 106 L910 108 L902 111 Z", "clay", gouache=False)
    s.text("$port", 140, 164, 9.5, role="ink3", anchor="middle", spacing=0.1)
    s.text("TELEGRAM", 820, 164, 9.5, role="ink3", anchor="middle", spacing=0.1)
    _grass(s, 260, 150)
    _grass(s, 520, 151, -1.0, slow=True)
    _grass(s, 700, 149, -2.0)
    s.texts["port"] = "127.0.0.1"
    return s


def crossroads() -> Scene:
    """Перекрёсток: дорога к провайдеру и дорога к сервису, посередине — указатель."""
    s = Scene(1000, 170)
    _sun_or_moon(s, 110, 50, 22)
    _stars(s, [(300, 30, 1.2), (470, 50, 1.1), (690, 26, 1.3), (880, 48, 1.1)])
    with s.group(only="light"):
        _cloud(s, "M640 44 C 638 36, 648 32, 655 36 C 659 28, 673 29, 675 37 C 683 36, 687 43, "
                  "681 46 Z", amp=14, period=20)
    s.paint("M0 124 C 160 112, 340 118, 500 122 C 680 126, 840 110, 1000 116 L1000 170 L0 170 Z",
            "matcha")
    s.ink("M0 124 C 160 112, 340 118, 500 122 C 680 126, 840 110, 1000 116", thin=True,
          opacity=0.55)
    s.paint("M0 150 C 240 144, 640 156, 1000 146 L1000 170 L0 170 Z", "ground")
    s.ink("M0 151 C 240 145, 640 157, 1000 147")
    # Городок провайдера — слева, карандашом: туда ведёт обычный DNS.
    s.ink("M120 128 L120 108 L140 96 L160 108 L160 128 M170 128 L170 112 L186 102 L202 112 "
          "L202 128 M210 128 L210 104 L226 104 L226 128", role="pencil", width=1.6)
    s.text("ПРОВАЙДЕР", 170, 144, 9, role="ink3", anchor="middle", spacing=0.1)
    # Замок сервиса — справа, красками.
    s.paint("M790 128 L790 98 L804 98 L804 90 L814 90 L814 98 L846 98 L846 90 L856 90 L856 98 "
            "L870 98 L870 128 Z", "wall")
    s.ink("M790 128 L790 98 L804 98 L804 90 L814 90 L814 98 L846 98 L846 90 L856 90 L856 98 "
          "L870 98 L870 128")
    s.paint("M822 128 L822 112 Q830 104 838 112 L838 128 Z", "kraft", gouache=False)
    s.ink("M822 128 L822 112 Q830 104 838 112 L838 128", thin=True)
    s.ink("M830 90 L830 70", thin=True)
    with s.group(anim=sway(3, 3.6, 0.0, 0.5)):
        s.paint("M831 70 L846 74 L831 79 Z", "clay", gouache=False)
    s.text("$service", 830, 144, 9, role="ink3", anchor="middle", spacing=0.1)
    # Дороги расходятся от указателя.
    left_road = "M480 152 C 420 140, 300 136, 230 132"
    right_road = "M520 152 C 600 140, 720 136, 780 132"
    with s.group(state="on", role="sketch"):
        s.flow(left_road, role="ink", width=1.6, dash=(4, 6), speed=10)
        s.ink(right_road, role="pencil", width=1.6)
    with s.group(state="on", role="live"):
        s.ink(left_road, role="pencil", width=1.6, breathe=False)
        s.flow(right_road, role="ink", width=1.6, dash=(4, 6), speed=10)
    # Указатель.
    s.paint("M496 152 L495 40 L504 40 L505 152 Z", "kraft")
    s.ink("M500 154 L499 36")
    with s.group(anim=sway(2.0, 5.2, 0.0, 0.5)):
        with s.group(state="on", role="live", bloom=True):
            s.paint("M504 46 L572 46 L584 58 L572 70 L504 70 Z", "olive")
        s.ink("M504 46 L572 46 L584 58 L572 70 L504 70 Z")
        s.text("$sign", 513, 62, 10, spacing=0.08)
    with s.group(anim=sway(1.6, 4.6, 1.0, 0.5), phase=-1.5):
        with s.group(state="on", role="sketch", bloom=True):
            s.paint("M496 80 L434 80 L422 92 L434 104 L496 104 Z", "kraft")
        s.ink("M496 80 L434 80 L422 92 L434 104 L496 104 Z")
        s.text("ПРОВАЙДЕР", 435, 96, 8.5, spacing=0.06)
    with s.group(state="on", role="live", bloom=True, delay=0.2):
        s.paint("M504 112 L556 112 L566 122 L556 132 L504 132 Z", "manilla")
    s.ink("M504 112 L556 112 L566 122 L556 132 L504 132 Z")
    s.text("DoH", 512, 126, 9, spacing=0.06)
    _grass(s, 330, 150)
    _grass(s, 640, 152, -1.2, slow=True)
    _grass(s, 940, 148, -2.0)
    s.texts["sign"] = "COMSS"
    s.texts["service"] = "СЕРВИСЫ"
    return s


# =========================================================================
# Диагностика: садовник с лупой
# =========================================================================


def inspection() -> Scene:
    s = Scene(240, 104)
    s.paint("M0 86 C 60 82, 160 90, 240 84 L240 104 L0 104 Z", "ground")
    s.ink("M0 87 C 60 83, 160 91, 240 85")
    with s.group(anim=sway(2.5, 4.4)):
        s.ink("M58 87 C 54 70, 62 60, 58 48")
        _leaf(s, 57, 70, 205, 0.7)
        _flower(s, 58, 42, 5.0)
    with s.group(anim=sway(2.5, 3.8), phase=-1):
        s.ink("M96 87 C 94 76, 99 70, 96 62")
        _leaf(s, 97, 74, -28, 0.6)
    # Лупа.
    with s.group(anim=floating(3, 4.6)):
        s.paint(circle(160, 46, 20), "glow", gouache=False, opacity=0.7)
        s.ink(circle(160, 46, 20))
        s.ink("M174 60 L196 82", width=4.0)
        s.ink("M150 38 C 152 34, 156 32, 160 32", thin=True, opacity=0.6)
    return s


# =========================================================================
# Настройки: день и ночь
# =========================================================================


def day_card() -> Scene:
    s = Scene(160, 90)
    s.paint(rect(0, 0, 160, 90), "plate", gouache=False)
    with s.group(anim=floating(3, 5.0)):
        s.paint(circle(118, 32, 14), "clay")
    _cloud(s, "M26 36 C 24 28, 34 24, 41 28 C 45 20, 59 21, 61 29 C 69 28, 73 35, 67 38 Z",
           amp=8, period=12)
    s.paint("M0 70 C 40 60, 100 66, 160 60 L160 90 L0 90 Z", "matcha")
    s.ink("M0 70 C 40 60, 100 66, 160 60")
    return s


def night_card() -> Scene:
    s = Scene(160, 90)
    with s.group(anim=floating(3, 5.6)):
        s.paint(circle(116, 32, 12), "manilla")
        s.paint(circle(122, 27, 10), "cut", gouache=False)
    for k, (x, y) in enumerate(((30, 24), (58, 40), (80, 18), (146, 54))):
        with s.group(anim=twinkle(2.8), phase=-k * 0.8):
            s.paint(circle(x, y, 1.3), "ink", gouache=False)
    s.paint("M0 70 C 40 60, 100 66, 160 60 L160 90 L0 90 Z", "hill")
    s.ink("M0 70 C 40 60, 100 66, 160 60")
    return s


# =========================================================================
# О программе: конверт
# =========================================================================


def envelope() -> Scene:
    s = Scene(320, 200)
    with s.group(anim=floating(4, 6.0)):
        s.paint("M40 60 L280 60 L280 180 L40 180 Z", "paper", gouache=False)
        s.paint("M40 60 L160 130 L280 60 Z", "manilla")
        s.ink("M40 60 L280 60 L280 180 L40 180 Z")
        s.ink("M40 60 L160 130 L280 60")
        s.ink("M40 180 L132 112 M280 180 L188 112", thin=True)
        s.paint(circle(160, 128, 9), "clay")
        s.ink(circle(160, 128, 9), thin=True)
        # Росток вместо сургучной печати.
        s.ink("M160 128 L160 120 M160 122 C 156 122, 154 119, 154 116 C 158 116, 160 118, 160 122",
              thin=True)
    with s.group(anim=sway(3, 4.0)):
        s.ink("M300 190 C 298 176, 304 168, 300 158")
        _leaf(s, 299, 176, 205, 0.6)
        _flower(s, 300, 152, 4.5)
    return s


# =========================================================================
# Списки сайтов: адресная книга
# =========================================================================


def address_book() -> Scene:
    s = Scene(240, 104)
    s.paint("M40 20 L150 14 L156 92 L46 98 Z", "manilla")
    s.ink("M40 20 L150 14 L156 92 L46 98 Z")
    s.ink("M96 17 L101 95", thin=True)
    s.ink("M54 34 L88 32 M55 46 L86 44 M56 58 L84 57 M110 30 L140 28 M111 42 L138 40 "
          "M112 54 L142 52 M113 66 L136 65", thin=True, opacity=0.7)
    s.paint("M150 30 L166 29 L167 41 L151 42 Z", "clay", gouache=False)
    s.paint("M151 48 L166 47 L167 59 L152 60 Z", "olive", gouache=False)
    s.paint("M152 66 L167 65 L168 77 L153 78 Z", "sky", gouache=False)
    with s.group(anim=sway(4, 3.8, 0.5, 1.0)):
        s.ink("M190 92 L206 30", width=2.4)
        s.paint("M204 28 L210 30 L208 36 L202 34 Z", "kraft", gouache=False)
        s.ink("M190 92 L193 82 L196 84 Z", thin=True)
    return s


# =========================================================================
# Скорость: стрелка-флюгер
# =========================================================================


def weathervane() -> Scene:
    s = Scene(240, 104)
    s.paint("M0 92 C 60 88, 160 96, 240 90 L240 104 L0 104 Z", "ground")
    s.ink("M0 93 C 60 89, 160 97, 240 91")
    s.ink("M120 93 L120 30")
    with s.group(anim=sway_at(10, 3.2, 120, 30)):
        s.paint("M84 30 L150 30 L150 24 L162 30 L150 36 L150 30 Z", "clay", gouache=False)
        s.ink("M84 30 L156 30 M146 24 L160 30 L146 36 M84 30 L76 22 M84 30 L76 38 "
              "M92 30 L84 22 M92 30 L84 38")
    s.ink(circle(120, 30, 3), thin=True)
    with s.group(anim=drift(16, 9)):
        s.ink("M30 50 q8 -4 16 0 M40 62 q6 -3 12 0", thin=True, opacity=0.6)
    with s.group(anim=drift(14, 7), phase=-2):
        s.ink("M180 56 q8 -4 16 0 M194 68 q6 -3 12 0", thin=True, opacity=0.6)
    return s


# =========================================================================
# Знакомство и «что нового»: росток в горшке
# =========================================================================


def seedling() -> Scene:
    s = Scene(200, 160)
    s.paint("M66 150 L134 150 L142 110 L58 110 Z", "kraft")
    s.ink("M66 150 L134 150 L142 110 L58 110 Z M54 110 L146 110", width=2.2)
    with s.group(state="on", role="live"):
        with s.group(anim=sway(3, 4.2)):
            s.ink("M100 110 C 96 90, 106 74, 100 52", draw=True)
            with s.group(bloom=True):
                _leaf(s, 99, 92, 205, 0.9, delay=0.1)
                _leaf(s, 101, 74, -28, 0.9, delay=0.25)
            with s.group(bloom=True, delay=0.6):
                _flower(s, 100, 44, 6.5)
    return s


def logo_sprout() -> Scene:
    """Знак программы: росток с глиняной точкой (как в заголовке окна)."""
    s = Scene(20, 20)
    s.ink("M10 18 L10 9 M10 11 C 6 11, 4 8, 4 5 C 8 5, 10 7, 10 11 M10 9 C 10 6, 12 4, 16 4 "
          "C 16 7, 14 9, 10 9", width=1.6, breathe=False)
    s.paint(circle(16, 4, 2.2), "clay", gouache=False)
    return s


def bed_board() -> Scene:
    """Пустая подложка грядки: сама грядка рисуется виджетом SproutBed."""
    return Scene(900, 256)
