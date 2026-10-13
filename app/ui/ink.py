"""Рисованные сцены: тушь, гуашь и дыхание линии — на чистом QPainter.

Сцена описывается как в SVG: пути, группы, покачивание и парение. Отрисовка
устроена так, чтобы живая картинка почти не грузила процессор:

* каждый элемент один раз рисуется в маленькую картинку (спрайт) под
  текущий масштаб и тему; линии туши — в нескольких «вдохах», у каждого
  своё лёгкое смещение, и вдохи плавно перетекают друг в друга;
* неподвижные соседние элементы склеиваются в один спрайт;
* на каждом кадре остаются только перемещения готовых картинок.

Вживую, без кэша, рисуется только то, что прямо сейчас прорисовывается
(включили службу — росток вырастает) и пара копеечных вещей: бегущий
пунктир, огоньки, подписи.
"""

from __future__ import annotations

import math
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui import fonts

# =========================================================================
# Кривые движения
# =========================================================================


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def expo_out(t: float) -> float:
    """Быстрый старт и долгое мягкое торможение — главная кривая."""
    t = clamp(t)
    return 1.0 if t >= 1.0 else 1.0 - math.pow(2.0, -10.0 * t)


def quart_out(t: float) -> float:
    t = clamp(t)
    return 1.0 - (1.0 - t) ** 4


def inout(t: float) -> float:
    """power2.inOut — для прорисовки линии."""
    t = clamp(t)
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def sine_inout(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * clamp(t))


def yoyo(now: float, period: float, phase: float = 0.0) -> float:
    """-1…1 по синусоиде «туда и обратно» за 2·period секунд."""
    return -math.cos(math.pi * (now + phase) / max(period, 0.01))


# =========================================================================
# Пути SVG
# =========================================================================

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def parse_path(d: str) -> QPainterPath:
    """Строка ``d`` из SVG → QPainterPath (все команды, включая дуги)."""
    path = QPainterPath()
    tokens = _TOKEN.findall(d)
    i = 0
    cmd = ""
    x = y = 0.0
    start_x = start_y = 0.0
    last_ctrl: tuple[float, float] | None = None
    last_cmd = ""
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            cmd = token
            i += 1
            if cmd in "Zz":
                path.closeSubpath()
                x, y = start_x, start_y
                last_ctrl = None
                last_cmd = "Z"
                continue
        if not cmd:
            break
        upper = cmd.upper()
        need = _ARGS[upper]
        if i + need > len(tokens):
            break
        args = [float(t) for t in tokens[i:i + need]]
        i += need
        rel = cmd.islower()
        if upper == "M":
            nx, ny = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            path.moveTo(nx, ny)
            x, y = start_x, start_y = nx, ny
            # Пары после первой — это уже lineTo.
            cmd = "l" if rel else "L"
            last_ctrl = None
        elif upper == "L":
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            path.lineTo(x, y)
            last_ctrl = None
        elif upper == "H":
            x = x + args[0] if rel else args[0]
            path.lineTo(x, y)
            last_ctrl = None
        elif upper == "V":
            y = y + args[0] if rel else args[0]
            path.lineTo(x, y)
            last_ctrl = None
        elif upper == "C":
            pts = [(args[k] + (x if rel else 0), args[k + 1] + (y if rel else 0))
                   for k in (0, 2, 4)]
            path.cubicTo(*pts[0], *pts[1], *pts[2])
            last_ctrl = pts[1]
            x, y = pts[2]
        elif upper == "S":
            if last_ctrl is not None and last_cmd in "CS":
                c1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1])
            else:
                c1 = (x, y)
            c2 = (args[0] + (x if rel else 0), args[1] + (y if rel else 0))
            end = (args[2] + (x if rel else 0), args[3] + (y if rel else 0))
            path.cubicTo(*c1, *c2, *end)
            last_ctrl = c2
            x, y = end
        elif upper == "Q":
            c = (args[0] + (x if rel else 0), args[1] + (y if rel else 0))
            end = (args[2] + (x if rel else 0), args[3] + (y if rel else 0))
            path.quadTo(*c, *end)
            last_ctrl = c
            x, y = end
        elif upper == "T":
            if last_ctrl is not None and last_cmd in "QT":
                c = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1])
            else:
                c = (x, y)
            end = (args[0] + (x if rel else 0), args[1] + (y if rel else 0))
            path.quadTo(*c, *end)
            last_ctrl = c
            x, y = end
        elif upper == "A":
            end = (args[5] + (x if rel else 0), args[6] + (y if rel else 0))
            _arc_to(path, x, y, args[0], args[1], args[2], bool(args[3]), bool(args[4]), *end)
            x, y = end
            last_ctrl = None
        last_cmd = upper
    return path


def _arc_to(path: QPainterPath, x1: float, y1: float, rx: float, ry: float, phi: float,
            large: bool, sweep: bool, x2: float, y2: float) -> None:
    """Дуга SVG через кубические кривые (стандартное преобразование)."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        path.lineTo(x2, y2)
        return
    rx, ry = abs(rx), abs(ry)
    cos_p, sin_p = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    segments = max(1, int(math.ceil(abs(delta) / (math.pi / 2))))
    step = delta / segments
    t = 4 / 3 * math.tan(step / 4)
    for k in range(segments):
        a1 = theta1 + k * step
        a2 = a1 + step
        e1 = (math.cos(a1), math.sin(a1))
        e2 = (math.cos(a2), math.sin(a2))
        p1 = (e1[0] - t * e1[1], e1[1] + t * e1[0])
        p2 = (e2[0] + t * e2[1], e2[1] - t * e2[0])

        def to_xy(px: float, py: float) -> tuple[float, float]:
            px, py = px * rx, py * ry
            return cos_p * px - sin_p * py + cx, sin_p * px + cos_p * py + cy

        path.cubicTo(*to_xy(*p1), *to_xy(*p2), *to_xy(*e2))


def circle(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def ellipse(cx: float, cy: float, rx: float, ry: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


def rect(x: float, y: float, w: float, h: float, r: float = 0.0) -> QPainterPath:
    path = QPainterPath()
    if r:
        path.addRoundedRect(QRectF(x, y, w, h), r, r)
    else:
        path.addRect(QRectF(x, y, w, h))
    return path


def as_path(shape) -> QPainterPath:
    if isinstance(shape, QPainterPath):
        return shape
    return parse_path(str(shape))


LEAF = "M0 0 C5 -7 14 -9 19 -1 C13 4 5 5 0 0Z"


def placed(shape, dx: float = 0.0, dy: float = 0.0, rotate: float = 0.0,
           scale: float = 1.0) -> QPainterPath:
    """Путь, сдвинутый и повёрнутый, как transform="translate rotate scale"."""
    transform = QTransform()
    transform.translate(dx, dy)
    transform.rotate(rotate)
    transform.scale(scale, scale)
    return transform.map(as_path(shape))


# =========================================================================
# Модель сцены
# =========================================================================


@dataclass
class Item:
    kind: str                      # ink | paint | text | flow | glow
    path: QPainterPath | None = None
    role: str = "ink"
    width: float = 2.2
    opacity: float = 1.0
    gouache: bool = False
    draw: bool = False             # прорисовывается при включении
    bloom: bool = False            # гуашь проявляется при включении
    fade: bool = False             # просто проявляется при включении
    delay: float = 0.0
    # подписи
    text: str | Callable[[], str] = ""
    font: tuple = ("mono", 9.0, 0.08)
    pos: tuple[float, float] = (0.0, 0.0)
    anchor: str = "start"          # start | middle | end
    # бегущий пунктир
    dash: tuple[float, float] = (3.0, 5.0)
    speed: float = 0.0             # единиц сцены в секунду
    breathe: bool = True

    def bounds(self) -> QRectF:
        if self.kind == "text":
            x, y = self.pos
            return QRectF(x - 40, y - 14, 80, 18)
        if self.path is None:
            return QRectF()
        margin = self.width + (4.0 if self.gouache else 1.5)
        return self.path.boundingRect().adjusted(-margin, -margin, margin, margin)


@dataclass
class Group:
    children: list = field(default_factory=list)
    anim: tuple | None = None      # ("sway", amp°, период, ox, oy) и т.п.
    phase: float = 0.0
    state: str = ""                # ключ состояния: dpi, vpn, tg, dns
    role: str = ""                 # live | sketch
    only: str = ""                 # light | dark
    lift: float = 0.0              # насколько опущена, пока выключено
    base: QTransform | None = None
    dynamic: str = ""              # имя динамической позиции (лодка и т.п.)

    def bounds(self) -> QRectF:
        box = QRectF()
        for child in self.children:
            box = box.united(child.bounds())
        return box


class Scene:
    """Сцена в координатах viewBox."""

    def __init__(self, width: float, height: float) -> None:
        self.width = float(width)
        self.height = float(height)
        self.root = Group()
        self._stack = [self.root]
        self.texts: dict[str, str] = {}
        self.motions: dict[str, QPainterPath] = {}
        self.motion_progress: dict[str, float] = {}
        self.motion_period: dict[str, float] = {}   # сек на один проход пути
        self._flags: list[dict] = [{}]

    # --- построение -----------------------------------------------------

    def _add(self, item: Item) -> Item:
        flags = self._flags[-1]
        if flags.get("fade"):
            item.fade = True
        if flags.get("bloom") and item.kind == "paint":
            item.bloom = True
        if flags.get("draw") and item.kind == "ink":
            item.draw = True
        if flags.get("delay") and not item.delay:
            item.delay = flags["delay"]
        self._stack[-1].children.append(item)
        return item

    def ink(self, d, thin: bool = False, width: float | None = None, role: str = "ink",
            opacity: float = 1.0, draw: bool = False, delay: float = 0.0,
            fade: bool = False, breathe: bool = True) -> Item:
        return self._add(Item("ink", as_path(d), role,
                              width if width is not None else (1.5 if thin else 2.2),
                              opacity, draw=draw, delay=delay, fade=fade, breathe=breathe))

    def pen(self, d, width: float = 1.6) -> Item:
        """Набросок карандашом — так выглядит выключенное."""
        return self._add(Item("ink", as_path(d), "pencil", width))

    def paint(self, d, role: str, gouache: bool = True, opacity: float = 1.0,
              bloom: bool = False, delay: float = 0.0, fade: bool = False) -> Item:
        return self._add(Item("paint", as_path(d), role, 0.0, opacity, gouache,
                              bloom=bloom, delay=delay, fade=fade))

    def text(self, value, x: float, y: float, size: float = 9.0, kind: str = "mono",
             role: str = "ink", anchor: str = "start", spacing: float = 0.08,
             italic: bool = False, fade: bool = False, opacity: float = 1.0) -> Item:
        font = (kind, size, spacing if kind == "mono" else italic)
        return self._add(Item("text", None, role, 0.0, opacity, text=value, font=font,
                              pos=(x, y), anchor=anchor, fade=fade))

    def flow(self, d, role: str = "ink", width: float = 1.4, dash=(3.0, 5.0),
             speed: float = 11.0, opacity: float = 1.0) -> Item:
        return self._add(Item("flow", as_path(d), role, width, opacity, dash=dash, speed=speed))

    def glow(self, x: float, y: float, r: float, role: str = "manilla") -> Item:
        return self._add(Item("glow", circle(x, y, r), role, 0.0))

    @contextmanager
    def group(self, anim: tuple | None = None, phase: float = 0.0, state: str = "",
              role: str = "", only: str = "", lift: float = 0.0,
              base: QTransform | None = None, dynamic: str = "",
              fade: bool = False, bloom: bool = False, draw: bool = False,
              delay: float = 0.0) -> Iterator[Group]:
        node = Group(anim=anim, phase=phase, state=state, role=role, only=only,
                     lift=lift, base=base, dynamic=dynamic)
        self._stack[-1].children.append(node)
        self._stack.append(node)
        flags = dict(self._flags[-1])
        if fade:
            flags["fade"] = True
        if bloom:
            flags["bloom"] = True
        if draw:
            flags["draw"] = True
        if delay:
            flags["delay"] = delay
        self._flags.append(flags)
        try:
            yield node
        finally:
            self._stack.pop()
            self._flags.pop()

    def motion(self, name: str, d, period: float = 0.0) -> None:
        """Путь, по которому едет группа с dynamic=name (лодка по морю).

        period — за сколько секунд она проходит его целиком и начинает снова;
        0 — положение задаётся вручную через motion_progress.
        """
        self.motions[name] = as_path(d)
        if period:
            self.motion_period[name] = period


# Анимации групп. Начало координат — доли рамки группы, как transform-origin.
def sway(amp: float = 3.0, period: float = 4.0, ox: float = 0.5, oy: float = 1.0) -> tuple:
    return ("sway", amp, period, ox, oy)


def sway_at(amp: float, period: float, x: float, y: float) -> tuple:
    """Покачивание вокруг точки сцены (а не доли рамки)."""
    return ("sway_abs", amp, period, x, y)


def floating(amp: float = 5.0, period: float = 5.0) -> tuple:
    return ("float", amp, period)


def drift(amp: float = 14.0, period: float = 18.0) -> tuple:
    return ("drift", amp, period)


def flap(period: float = 0.7, low: float = 0.45) -> tuple:
    return ("flap", period, low)


def twinkle(period: float = 3.2, low: float = 0.25) -> tuple:
    return ("twinkle", period, low)


def spin(period: float = 12.0) -> tuple:
    return ("spin", period)


# =========================================================================
# Палитра сцены
# =========================================================================

# Марки всегда на светлой бумаге — и в тёмной теме тоже.
STAMP_PALETTE = {
    "ink": "#141413", "pencil": "#A9A59A", "clay": "#D97757", "olive": "#788C5D",
    "matcha": "#CED6BF", "kraft": "#D4A27F", "manilla": "#EBDBBC", "sky": "#6A9BCC",
    "wall": "#EFE5D2", "glow": "#F7ECD6", "paper": "#FBF8F1", "soil": "#D6C1A3",
    "hill": "#CED6BF", "hill2": "#B9C4A6", "ground": "#C3CCB0", "sea": "#D3DAD6",
    "plate": "#E3DACC", "cut": "#F1EEE6", "muted": "#73726C", "ink3": "#5E5D59",
    "decor": "#87867F",
}


def scene_palette(tokens: dict[str, str]) -> dict[str, str]:
    palette = dict(tokens)
    palette.setdefault("paper", "#FBF8F1")
    return palette


# =========================================================================
# Бумажная фактура
# =========================================================================

_GRAIN: QImage | None = None


def grain_texture() -> QImage:
    """Сухая кисть: маска с мелкими просветами для гуаши."""
    global _GRAIN
    if _GRAIN is not None:
        return _GRAIN
    size = 128
    rnd = random.Random(9)
    raw = [rnd.random() for _ in range(size * size)]
    data = bytearray(size * size * 4)
    for yy in range(size):
        row = yy * size
        up = ((yy - 1) % size) * size
        for xx in range(size):
            # Чуть сглаженный шум: зерно не точечное, а с «волокном».
            r = (raw[row + xx] * 2 + raw[row + (xx + 1) % size] + raw[up + xx]) / 4
            alpha = 1.32 - 0.8 * (0.5 + (r - 0.5) * 1.25)
            a = int(255 * clamp(alpha, 0.45, 1.0))
            o = (row + xx) * 4
            data[o] = data[o + 1] = data[o + 2] = data[o + 3] = a
    image = QImage(bytes(data), size, size, QImage.Format.Format_ARGB32_Premultiplied)
    _GRAIN = image.copy()
    return _GRAIN


def blurred_shadow(path: QPainterPath, size: QSize, color: QColor, blur: float,
                   offset: tuple[float, float] = (0.0, 0.0), dpr: float = 1.0) -> QPixmap:
    """Мягкая тень формы: рисуем мелко и растягиваем — получается размытие."""
    factor = max(2.0, blur / 1.5)
    w = max(1, int(size.width() * dpr / factor))
    h = max(1, int(size.height() * dpr / factor))
    small = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    small.fill(Qt.GlobalColor.transparent)
    painter = QPainter(small)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(dpr / factor, dpr / factor)
    painter.translate(*offset)
    painter.fillPath(path, color)
    painter.end()
    big = small.scaled(int(size.width() * dpr), int(size.height() * dpr),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    # Второй проход сглаживает «ступеньки» билинейного растяжения.
    big = big.scaled(max(1, int(size.width() * dpr / 2)), max(1, int(size.height() * dpr / 2)),
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation).scaled(
        int(size.width() * dpr), int(size.height() * dpr),
        Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pixmap = QPixmap.fromImage(big)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


# =========================================================================
# Дыхание линии и рваный край гуаши
# =========================================================================


class NoiseField:
    """Плавное поле смещений: сумма нескольких синусоид под разными углами."""

    def __init__(self, seed: int, freq: float, amp: float, octaves: int = 1,
                 shift: float = 0.0) -> None:
        rnd = random.Random(seed)
        self.amp = amp
        self.waves_x = []
        self.waves_y = []
        for octave in range(octaves):
            f = freq * (2 ** octave)
            weight = 0.5 ** octave
            for waves in (self.waves_x, self.waves_y):
                for _ in range(3):
                    angle = rnd.uniform(0, math.tau)
                    k = f * rnd.uniform(0.75, 1.3) * math.tau
                    # shift сдвигает фазы: соседние кадры дыхания отличаются
                    # чуть-чуть, а за круг поле возвращается к началу.
                    turn = rnd.choice((-1.0, 1.0))
                    waves.append((k * math.cos(angle), k * math.sin(angle),
                                  rnd.uniform(0, math.tau) + turn * shift, weight))
        norm = sum(w for *_r, w in self.waves_x) / 1.6
        self.norm = norm or 1.0

    def at(self, x: float, y: float) -> tuple[float, float]:
        dx = sum(w * math.sin(kx * x + ky * y + p) for kx, ky, p, w in self.waves_x)
        dy = sum(w * math.sin(kx * x + ky * y + p) for kx, ky, p, w in self.waves_y)
        return self.amp * dx / self.norm, self.amp * dy / self.norm


def _densify(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    out = [points[0]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        n = int(length / step)
        for k in range(1, n + 1):
            t = k / (n + 1)
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


def _polylines(path: QPainterPath, scale: float, step: float) -> list[list[tuple[float, float]]]:
    """Путь → ломаные в координатах сцены, с точками не реже step пикселей."""
    transform = QTransform.fromScale(scale, scale)
    result = []
    for polygon in path.toSubpathPolygons(transform):
        pts = [(p.x() / scale, p.y() / scale) for p in polygon]
        if len(pts) >= 2:
            result.append(_densify(pts, step / scale))
    return result


def _displaced(lines, field_: NoiseField | None):
    if field_ is None:
        return lines
    out = []
    for line in lines:
        moved = []
        for x, y in line:
            dx, dy = field_.at(x, y)
            moved.append((x + dx, y + dy))
        out.append(moved)
    return out


def _to_polygon(line, scale: float, ox: float = 0.0, oy: float = 0.0) -> QPolygonF:
    return QPolygonF([QPointF((x - ox) * scale, (y - oy) * scale) for x, y in line])


def _lengths(line) -> list[float]:
    acc = [0.0]
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        acc.append(acc[-1] + math.hypot(x1 - x0, y1 - y0))
    return acc


def _prefix(line, acc: list[float], portion: float):
    """Начало ломаной длиной portion от всей (для прорисовки)."""
    total = acc[-1]
    if portion >= 1.0 or total <= 0:
        return line
    target = total * portion
    out = [line[0]]
    for k in range(1, len(line)):
        if acc[k] >= target:
            seg = acc[k] - acc[k - 1]
            t = (target - acc[k - 1]) / seg if seg else 0.0
            x0, y0 = line[k - 1]
            x1, y1 = line[k]
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            break
        out.append(line[k])
    return out


# =========================================================================
# Отрисовка
# =========================================================================

BREATHS = 8          # сколько кадров у одного «вдоха» линии
BREATH_STEP = 0.55   # секунд на перетекание кадра в следующий
BREATH_AMP = 1.0     # размах дыхания, в единицах сцены
GOUACHE_AMP = 2.0    # размах рваного края гуаши
TRANSITION = 2.4     # сколько длится прорисовка включения


@dataclass
class _Sprite:
    frames: list            # QImage: один кадр или BREATHS кадров дыхания
    x: float                # левый верх в координатах сцены
    y: float
    scale: float = 1.0      # под какой масштаб нарисован


@dataclass
class _Unit:
    """Подряд идущие элементы одной группы — рисуются одним спрайтом."""
    items: list
    chain: list             # группы от корня
    runs: list = field(default_factory=list)   # [(kind, [items])]


class SceneRenderer:
    """Рисует сцену в любой QPainter. Держит кэш под масштаб и палитру.

    Спрайты — QImage: их можно рисовать и в фоновом потоке. Кадры дыхания
    линии дорисовываются там же, пока сцена уже живёт на экране.
    """

    def __init__(self, scene: Scene, palette: dict[str, str] | None = None) -> None:
        self.scene = scene
        self.palette = dict(palette or STAMP_PALETTE)
        self.dark = False
        self.motion = "full"          # full | calm | off
        self.states: dict[str, bool] = {}
        self._changed: dict[str, float] = {}
        self._scale = 0.0
        self._dpr = 1.0
        self._key: tuple = ()
        self._pending_key: tuple = ()
        self._pending_since = 0.0
        self._generation = 0
        self._worker = None
        self._units: list[_Unit] = []
        self._item_cache: dict = {}
        self._run_cache: dict[tuple, _Sprite] = {}
        self._group_boxes: dict[int, QRectF] = {}
        self._started = time.perf_counter()
        self._build_units()

    # --- состояние ------------------------------------------------------

    def set_palette(self, palette: dict[str, str], dark: bool) -> None:
        self.palette = dict(palette)
        self.dark = dark
        self._invalidate(rebuild_units=True)

    def set_state(self, key: str, on: bool, animate: bool = True) -> bool:
        """Включить или выключить часть сцены. True — если что-то поменялось."""
        if self.states.get(key) == on:
            return False
        self.states[key] = on
        self._changed[key] = time.perf_counter() if animate and self.motion != "off" else -1e9
        return True

    def set_text(self, key: str, value: str) -> None:
        self.scene.texts[key] = value

    def busy(self, now: float | None = None) -> bool:
        """Идёт ли сейчас прорисовка включения/выключения."""
        now = time.perf_counter() if now is None else now
        return any(now - started < TRANSITION for started in self._changed.values())

    def restart(self) -> None:
        """Начать прорисовку заново: все включённые части рисуются с нуля."""
        now = time.perf_counter()
        for key, on in self.states.items():
            if on:
                self._changed[key] = now

    def _invalidate(self, rebuild_units: bool = False) -> None:
        self._generation += 1
        self._item_cache = {}
        self._run_cache = {}
        self._key = ()
        if rebuild_units:
            self._build_units()

    # --- разбиение на спрайты -------------------------------------------

    def _visible_group(self, group: Group) -> bool:
        if group.only == "light" and self.dark:
            return False
        if group.only == "dark" and not self.dark:
            return False
        return True

    def _build_units(self) -> None:
        units: list[_Unit] = []
        boxes: dict[int, QRectF] = {}

        def walk(group: Group, chain: list) -> None:
            if not self._visible_group(group):
                return
            boxes[id(group)] = group.bounds()
            current: list = []
            for child in group.children:
                if isinstance(child, Group):
                    if current:
                        units.append(_Unit(current, chain))
                        current = []
                    walk(child, chain + [child])
                else:
                    current.append(child)
            if current:
                units.append(_Unit(current, chain))

        walk(self.scene.root, [self.scene.root])
        for unit in units:
            runs: list = []
            for item in unit.items:
                kind = item.kind
                if kind == "paint":
                    kind = "gouache" if item.gouache else "flat"
                if kind in ("text", "flow", "glow"):
                    kind = "live"
                if runs and runs[-1][0] == kind:
                    runs[-1][1].append(item)
                else:
                    runs.append((kind, [item]))
            unit.runs = runs
        self._units = units
        self._group_boxes = boxes

    # --- геометрия ------------------------------------------------------

    def _field(self, k: int) -> NoiseField:
        return NoiseField(seed=31, freq=0.024, amp=BREATH_AMP,
                          shift=math.tau * k / BREATHS)

    def _ink_lines(self, item: Item, k: int, s: float, cache: dict):
        """Ломаные линии для кадра дыхания k (в координатах сцены)."""
        key = (id(item), "lines", k)
        cached = cache.get(key)
        if cached is None:
            base = cache.get((id(item), "base"))
            if base is None:
                base = _polylines(item.path, s, 5.0)
                cache[(id(item), "base")] = base
            breathe = item.breathe and self.motion == "full" and k > 0
            cached = _displaced(base, self._field(k) if breathe else None)
            cache[key] = cached
        return cached

    def _paint_shape(self, item: Item, s: float, cache: dict) -> QPainterPath:
        key = (id(item), "shape")
        cached = cache.get(key)
        if cached is None:
            if not item.gouache:
                cached = item.path
            else:
                center = item.path.boundingRect().center()
                seed = int(abs(center.x() * 13 + center.y() * 7)) % 997
                noise = NoiseField(seed=seed, freq=0.035, amp=GOUACHE_AMP, octaves=2)
                lines = _displaced(_polylines(item.path, s, 3.0), noise)
                cached = QPainterPath()
                cached.setFillRule(Qt.FillRule.WindingFill)
                for line in lines:
                    cached.addPolygon(QPolygonF([QPointF(x, y) for x, y in line]))
                    cached.closeSubpath()
            cache[key] = cached
        return cached

    def color(self, role: str) -> QColor:
        return QColor(self.palette.get(role, self.palette.get("ink", "#141413")))

    # --- спрайты --------------------------------------------------------

    @staticmethod
    def _run_box(items) -> QRectF:
        box = QRectF()
        for item in items:
            box = box.united(item.bounds())
        return box

    def _render_run(self, kind: str, items, frame: int, scale: float, dpr: float,
                    cache: dict) -> _Sprite:
        box = self._run_box(items)
        s = scale * dpr
        # Начало спрайта — ровно на пикселе, иначе картинка размоется.
        ox, oy = math.floor(box.left() * s) / s, math.floor(box.top() * s) / s
        w = max(1, int(math.ceil((box.right() - ox) * s)) + 2)
        h = max(1, int(math.ceil((box.bottom() - oy) * s)) + 2)
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if kind == "ink":
            for item in items:
                self._stroke(painter, item, self._ink_lines(item, frame, s, cache), s, ox, oy)
        else:
            painter.save()
            painter.scale(s, s)
            painter.translate(-ox, -oy)
            for item in items:
                painter.setOpacity(item.opacity)
                painter.fillPath(self._paint_shape(item, s, cache), self.color(item.role))
            painter.restore()
            if kind == "gouache":
                painter.setOpacity(1.0)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                painter.fillRect(QRectF(0, 0, w, h), QBrush(grain_texture()))
        painter.end()
        image.setDevicePixelRatio(dpr)
        return _Sprite([image], ox, oy, scale)

    def _stroke(self, painter: QPainter, item: Item, lines, s: float, ox: float, oy: float,
                portion: float = 1.0, opacity: float = 1.0) -> None:
        pen = QPen(self.color(item.role))
        pen.setWidthF(item.width * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setOpacity(item.opacity * opacity)
        if portion >= 1.0:
            for line in lines:
                painter.drawPolyline(_to_polygon(line, s, ox, oy))
            return
        # Прорисовка: все части пути тянутся одновременно.
        for line in lines:
            part = _prefix(line, _lengths(line), portion)
            if len(part) >= 2:
                painter.drawPolyline(_to_polygon(part, s, ox, oy))

    def _breathes(self, unit: _Unit, items) -> bool:
        """Дышат линии, которые стоят на месте: движущимся хватает движения."""
        if self.motion != "full" or not any(i.breathe for i in items):
            return False
        return not any(group.anim is not None or group.dynamic for group in unit.chain)

    def _sprite(self, unit_index: int, run_index: int) -> _Sprite:
        key = (unit_index, run_index)
        sprite = self._run_cache.get(key)
        if sprite is None:
            unit = self._units[unit_index]
            kind, items = unit.runs[run_index]
            sprite = self._render_run(kind, items, 0, self._scale, self._dpr, self._item_cache)
            if kind == "ink" and self._breathes(unit, items):
                sprite.frames = [sprite.frames[0]] + [None] * (BREATHS - 1)
                self._want_breaths = True
            self._run_cache[key] = sprite
        return sprite

    def _start_breaths(self) -> None:
        """Дорисовать кадры дыхания в фоне — окно в это время не ждёт."""
        if not getattr(self, "_want_breaths", False):
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self._want_breaths = False
        generation = self._generation
        scale, dpr = self._scale, self._dpr
        cache = self._item_cache
        jobs = []
        for (unit_index, run_index), sprite in list(self._run_cache.items()):
            if len(sprite.frames) > 1:
                jobs.append((sprite, self._units[unit_index].runs[run_index]))

        def work() -> None:
            for frame in range(1, BREATHS):
                for sprite, (kind, items) in jobs:
                    if generation != self._generation:
                        return
                    if sprite.frames[frame] is not None:
                        continue
                    try:
                        done = self._render_run(kind, items, frame, scale, dpr, cache)
                    except Exception:  # noqa: BLE001 — дыхание необязательно
                        return
                    if generation != self._generation:
                        return
                    sprite.frames[frame] = done.frames[0]

        import threading

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    # --- кадр -----------------------------------------------------------

    def _state_progress(self, group_chain: list, now: float) -> tuple[float, float, float]:
        """(видимость, время с переключения, сдвиг подъёма) для цепочки групп."""
        visible = 1.0
        since = 1e9
        lift = 0.0
        for group in group_chain:
            if not group.state:
                continue
            on = self.states.get(group.state, False)
            t = now - self._changed.get(group.state, -1e9)
            if group.role == "live":
                if on:
                    since = min(since, t)
                else:
                    visible *= 1.0 - expo_out(t / 0.5)
            elif group.role == "sketch":
                visible *= (1.0 - expo_out(t / 0.5)) if on else expo_out(t / 0.5)
            if group.lift:
                lift += group.lift * (1.0 - expo_out(t / 1.3)) if on else group.lift
        return visible, since, lift

    def _group_transform(self, group: Group, now: float) -> QTransform | None:
        anim = group.anim
        transform = QTransform(group.base) if group.base is not None else None
        if group.dynamic:
            path = self.scene.motions.get(group.dynamic)
            progress = self.scene.motion_progress.get(group.dynamic)
            period = self.scene.motion_period.get(group.dynamic)
            if progress is None and period:
                progress = 0.5 if self.motion == "off" else (now % period) / period
            if path is not None and progress is not None:
                point = path.pointAtPercent(clamp(progress))
                moved = QTransform.fromTranslate(point.x(), point.y())
                transform = moved if transform is None else transform * moved
        if anim is None or self.motion == "off":
            return transform
        kind = anim[0]
        calm = 0.5 if self.motion == "calm" else 1.0
        box = self._group_boxes.get(id(group), QRectF())
        result = QTransform()
        if kind in ("sway", "sway_abs"):
            _, amp, period, ox, oy = anim
            if kind == "sway":
                px, py = box.left() + box.width() * ox, box.top() + box.height() * oy
            else:
                px, py = ox, oy
            angle = amp * calm * sine_wave(now, period, group.phase)
            result.translate(px, py)
            result.rotate(angle)
            result.translate(-px, -py)
        elif kind == "float":
            _, amp, period = anim
            result.translate(0, amp * calm * sine_wave(now, period, group.phase))
        elif kind == "drift":
            _, amp, period = anim
            result.translate(amp * calm * sine_wave(now, period, group.phase), 0)
        elif kind == "flap":
            _, period, low = anim
            px, py = box.center().x(), box.bottom()
            k = 1.0 - (1.0 - low) * (0.5 + 0.5 * sine_wave(now, period, group.phase))
            result.translate(px, py)
            result.scale(1.0, k)
            result.translate(-px, -py)
        elif kind == "spin":
            _, period = anim
            c = box.center()
            result.translate(c.x(), c.y())
            result.rotate((now + group.phase) / period * 360.0)
            result.translate(-c.x(), -c.y())
        else:
            return transform
        return result if transform is None else result * transform

    def _group_opacity(self, group: Group, now: float) -> float:
        anim = group.anim
        if anim is None or anim[0] != "twinkle" or self.motion == "off":
            return 1.0
        _, period, low = anim
        return low + (1.0 - low) * (0.5 + 0.5 * sine_wave(now, period, group.phase))

    def _ensure_cache(self, scale: float, dpr: float, now: float) -> None:
        """Пересобрать кэш под новый размер — но не на каждом шаге растягивания.

        Пока окно тянут мышкой, рисуем старыми спрайтами (они растягиваются),
        а пересобираем, когда размер успокоится.
        """
        key = (round(scale, 4), round(dpr, 3), self.motion, self.dark)
        if key == self._key:
            self._pending_key = ()
            return
        same_kind = bool(self._key) and self._key[1:] == key[1:]
        if same_kind:
            if key != self._pending_key:
                self._pending_key = key
                self._pending_since = now
            if now - self._pending_since < 0.25:
                return
        self._generation += 1
        self._item_cache = {}
        self._run_cache = {}
        self._scale = scale
        self._dpr = dpr
        self._key = key
        self._pending_key = ()

    def settling(self) -> bool:
        """Ждём, пока успокоится размер, чтобы пересобрать кэш."""
        return bool(self._pending_key)

    def paint(self, painter: QPainter, target: QRectF, dpr: float = 1.0,
              now: float | None = None) -> None:
        """Нарисовать сцену, вписанную в target по ширине."""
        now = time.perf_counter() if now is None else now
        scale = target.width() / self.scene.width
        self._ensure_cache(scale, dpr, now)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(target.left(), target.top())
        painter.scale(scale, scale)
        base = painter.transform()

        breath_t = (now - self._started) / BREATH_STEP
        breath_k = int(breath_t)
        breath_e = sine_inout(breath_t - breath_k)
        animate = self.motion == "full"

        for unit_index, unit in enumerate(self._units):
            visible, since, lift = self._state_progress(unit.chain, now)
            if visible <= 0.003:
                continue
            transform = QTransform()
            opacity = visible
            for group in unit.chain:
                local = self._group_transform(group, now)
                if local is not None:
                    transform = local * transform
                opacity *= self._group_opacity(group, now)
            if lift:
                transform = transform * QTransform.fromTranslate(0, lift)
            painter.setTransform(transform * base)
            transitioning = since < TRANSITION
            for run_index, (kind, items) in enumerate(unit.runs):
                if kind == "live":
                    self._paint_live(painter, items, now, opacity, since)
                    continue
                if transitioning and any(i.draw or i.bloom or i.fade for i in items):
                    self._paint_transition(painter, kind, items, since, opacity)
                    continue
                sprite = self._sprite(unit_index, run_index)
                painter.setOpacity(opacity)
                frames = sprite.frames
                count = len(frames)
                if count > 1 and animate:
                    # Кадр перетекает в следующий без «вспышек»: пока первая
                    # половина — старый кадр целиком, новый проступает поверх;
                    # во второй — наоборот. Соседние кадры почти совпадают.
                    a = frames[breath_k % count] or frames[0]
                    b = frames[(breath_k + 1) % count] or frames[0]
                    if breath_e < 0.5:
                        bottom, top, top_alpha = a, b, breath_e * 2
                    else:
                        bottom, top, top_alpha = b, a, (1.0 - breath_e) * 2
                    self._blit(painter, sprite, bottom)
                    if top_alpha > 0.02 and top is not bottom:
                        painter.setOpacity(opacity * top_alpha)
                        self._blit(painter, sprite, top)
                else:
                    self._blit(painter, sprite, frames[0])
        painter.restore()
        self._start_breaths()

    @staticmethod
    def _blit(painter: QPainter, sprite: "_Sprite", image: QImage) -> None:
        dpr = image.devicePixelRatio() or 1.0
        s = sprite.scale
        painter.drawImage(QRectF(sprite.x, sprite.y, image.width() / dpr / s,
                                 image.height() / dpr / s), image)

    def _paint_transition(self, painter: QPainter, kind: str, items, since: float,
                          opacity: float) -> None:
        """Прорисовка включения: линии растут, гуашь распускается, подписи проявляются."""
        s = self._scale * self._dpr
        for item in items:
            if kind == "ink":
                if item.draw:
                    portion = inout((since - item.delay) / 1.1)
                    item_opacity = 1.0 if portion > 0 else 0.0
                elif item.fade:
                    portion = 1.0
                    item_opacity = expo_out((since - 0.25 - item.delay) / 0.8)
                else:
                    portion, item_opacity = 1.0, 1.0
                if item_opacity <= 0.0 or portion <= 0.0:
                    continue
                lines = self._ink_lines(item, 0, s, self._item_cache)
                painter.save()
                painter.scale(1.0 / s, 1.0 / s)
                self._stroke(painter, item, lines, s, 0.0, 0.0, portion, opacity * item_opacity)
                painter.restore()
            else:
                sprite = self._item_sprite(item, kind)
                if item.bloom:
                    t = since - 0.35 - item.delay
                    item_opacity = quart_out(t / 0.6)
                    grow = 0.82 + 0.18 * quart_out(t / 0.9)
                elif item.fade:
                    item_opacity = expo_out((since - 0.25 - item.delay) / 0.8)
                    grow = 1.0
                else:
                    item_opacity, grow = 1.0, 1.0
                if item_opacity <= 0.0:
                    continue
                painter.save()
                if grow != 1.0:
                    c = item.path.boundingRect().center()
                    painter.translate(c.x(), c.y())
                    painter.scale(grow, grow)
                    painter.translate(-c.x(), -c.y())
                painter.setOpacity(opacity * item_opacity)
                self._blit(painter, sprite, sprite.frames[0])
                painter.restore()

    def _item_sprite(self, item: Item, kind: str) -> "_Sprite":
        key = (id(item), "sprite")
        sprite = self._item_cache.get(key)
        if sprite is None:
            sprite = self._render_run(kind, [item], 0, self._scale, self._dpr, self._item_cache)
            self._item_cache[key] = sprite
        return sprite

    def _paint_live(self, painter: QPainter, items, now: float, opacity: float,
                    since: float) -> None:
        for item in items:
            item_opacity = opacity * item.opacity
            if item.fade and since < TRANSITION:
                item_opacity *= expo_out((since - 0.25 - item.delay) / 0.8)
            if item_opacity <= 0.003:
                continue
            painter.setOpacity(item_opacity)
            if item.kind == "text":
                value = item.text() if callable(item.text) else str(item.text)
                if value.startswith("$"):
                    value = self.scene.texts.get(value[1:], "")
                if not value:
                    continue
                font = self._font(item.font)
                # Шрифт задан в пикселях сцены — масштаб уже в painter.
                painter.setFont(font)
                painter.setPen(self.color(item.role))
                width = painter.fontMetrics().horizontalAdvance(value)
                x, y = item.pos
                if item.anchor == "middle":
                    x -= width / 2
                elif item.anchor == "end":
                    x -= width
                painter.drawText(QPointF(x, y), value)
            elif item.kind == "flow":
                pen = QPen(self.color(item.role))
                pen.setWidthF(item.width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                # Длина штриха задаётся в толщинах линии.
                pen.setDashPattern([item.dash[0] / item.width, item.dash[1] / item.width])
                if self.motion != "off":
                    pen.setDashOffset(-(now * item.speed) / item.width)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(item.path)
            elif item.kind == "glow":
                box = item.path.boundingRect()
                c = box.center()
                r = box.width() / 2
                gradient = QRadialGradient(c, r * 4.0)
                color = self.color(item.role)
                gradient.setColorAt(0.0, color)
                halo = QColor(color)
                halo.setAlphaF(0.45)
                gradient.setColorAt(0.22, halo)
                halo.setAlphaF(0.0)
                gradient.setColorAt(1.0, halo)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawEllipse(c, r * 4.0, r * 4.0)

    _fonts: dict = {}

    def _font(self, spec: tuple):
        font = self._fonts.get(spec)
        if font is None:
            kind, size, extra = spec
            if kind == "mono":
                font = fonts.mono(size, 500 if size < 12 else 400, extra)
            elif kind == "serif":
                font = fonts.serif(size, 400, italic=bool(extra))
            else:
                font = fonts.sans(size, 500)
            self._fonts[spec] = font
        return font


def sine_wave(now: float, period: float, phase: float = 0.0) -> float:
    """-1…1: «туда» за period секунд и «обратно» за столько же."""
    return -math.cos(math.pi * (now + phase) / max(period, 0.01))


# =========================================================================
# Виджет
# =========================================================================


def system_motion_enabled() -> bool:
    """Включены ли анимации в Windows (Параметры → Специальные возможности)."""
    try:
        import ctypes

        value = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):
            return bool(value.value)
    except (AttributeError, OSError):
        pass
    return True


def motion_level() -> str:
    """full — всё живёт; calm — без дыхания линии; off — неподвижно."""
    from app.core.config import config

    level = str(config.get("motion", "full"))
    if level not in ("full", "calm", "off"):
        level = "full"
    if level != "off" and not system_motion_enabled():
        return "off"
    return level


class InkCanvas(QWidget):
    """Сцена на «тарелке»: подложка со скруглением и живой рисунок поверх."""

    clicked_region = Signal(str)

    def __init__(self, scene: Scene, context=None, plate: str = "plate", radius: float = 24.0,
                 parent: QWidget | None = None, palette: dict | None = None,
                 max_height: int = 0, fit: str = "meet") -> None:
        super().__init__(parent)
        self.scene = scene
        # meet — сцена целиком внутри; slice — по ширине, лишнее небо срезается
        # сверху (для широких пейзажей на всю ширину окна).
        self.fit = fit
        self.context = context
        self.plate_role = plate
        self.radius = radius
        self.renderer = SceneRenderer(scene, palette or (context.tokens if context else None))
        self._fixed_palette = palette is not None
        self._regions: list[tuple[QRectF, str, str]] = []
        self._hover = ""
        self._max_height = max_height
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(60)
        if context is not None:
            context.theme_changed.connect(self.apply_theme)
        self.apply_theme()

    # --- размеры --------------------------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        height = int(round(width * self.scene.height / self.scene.width))
        if self._max_height:
            height = min(height, self._max_height)
        return height

    def sizeHint(self) -> QSize:  # noqa: N802
        width = int(self.scene.width)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 60)

    # --- состояние ------------------------------------------------------

    def apply_theme(self) -> None:
        self.renderer.motion = motion_level()
        if self.context is not None and not self._fixed_palette:
            self.renderer.set_palette(scene_palette(self.context.tokens), self.context.is_dark)
        else:
            self.renderer._invalidate(rebuild_units=True)
        self._sync_clock()
        self.update()

    def set_state(self, key: str, on: bool, animate: bool = True) -> None:
        if self.renderer.set_state(key, on, animate and self.isVisible()):
            self._sync_clock()
            self.update()

    def set_text(self, key: str, value: str) -> None:
        if self.scene.texts.get(key) != value:
            self.renderer.set_text(key, value)
            self.update()

    def restart(self) -> None:
        self.renderer.restart()
        self._sync_clock()
        self.update()

    def add_region(self, box: QRectF, key: str, tooltip: str = "") -> None:
        """Кликабельная область сцены (в координатах viewBox)."""
        self._regions.append((box, key, tooltip))
        self.setMouseTracking(True)

    # --- кадры ----------------------------------------------------------

    def frame_divider(self) -> int:
        """Прорисовка — 30 кадров в секунду, тихая жизнь сцены — 15."""
        return 1 if self.renderer.busy() else 2

    def _sync_clock(self) -> None:
        from app.ui.widgets import frame_clock

        if self.renderer.motion != "off" or self.renderer.busy():
            frame_clock().subscribe(self)
        else:
            frame_clock().unsubscribe(self)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_clock()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        from app.ui.widgets import frame_clock

        frame_clock().unsubscribe(self)

    def scene_rect(self) -> QRectF:
        if self.fit == "slice":
            # По ширине, но небо срезаем не больше чем на пятую часть: в очень
            # широком окне сцена встаёт посередине, а не теряет подписи.
            scale = min(self.width() / self.scene.width,
                        self.height() / (self.scene.height * 0.8))
            scale = max(scale, self.height() / self.scene.height)
            w, h = self.scene.width * scale, self.scene.height * scale
            return QRectF(round((self.width() - w) / 2), round(self.height() - h), w, h)
        scale = min(self.width() / self.scene.width, self.height() / self.scene.height)
        w, h = self.scene.width * scale, self.scene.height * scale
        return QRectF(round((self.width() - w) / 2), round((self.height() - h) / 2), w, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        if self.plate_role:
            painter.fillPath(clip, self.renderer.color(self.plate_role))
        painter.setClipPath(clip)
        self.renderer.paint(painter, self.scene_rect(), self.devicePixelRatioF())
        painter.end()
        if self.renderer.settling():
            # Размер успокоится — перерисуем начисто под новый масштаб.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(300, self.update)
        if self.renderer.motion == "off" and not self.renderer.busy():
            from app.ui.widgets import frame_clock

            frame_clock().unsubscribe(self)

    # --- мышь -----------------------------------------------------------

    def _region_at(self, pos) -> tuple[str, str]:
        r = self.scene_rect()
        scale = r.width() / self.scene.width
        x = (pos.x() - r.left()) / scale
        y = (pos.y() - r.top()) / scale
        for box, key, tip in self._regions:
            if box.contains(QPointF(x, y)):
                return key, tip
        return "", ""

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        key, tip = self._region_at(event.position())
        if key != self._hover:
            self._hover = key
            self.setCursor(Qt.CursorShape.PointingHandCursor if key else
                           Qt.CursorShape.ArrowCursor)
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            key, _tip = self._region_at(event.position())
            if key:
                self.clicked_region.emit(key)
        super().mouseReleaseEvent(event)


# =========================================================================
# Штемпель
# =========================================================================


def postmark_path_text(painter: QPainter, center: QPointF, radius: float, text: str,
                       font, start_angle: float = -90.0) -> None:
    """Текст по кругу, буква за буквой, равномерно на всю окружность."""
    painter.setFont(font)
    metrics = painter.fontMetrics()
    widths = [metrics.horizontalAdvance(ch) for ch in text]
    total = sum(widths) or 1.0
    circumference = 2 * math.pi * radius
    # Растягиваем разрядку так, чтобы текст обошёл круг ровно один раз.
    extra = (circumference - total) / max(len(text), 1)
    angle = math.radians(start_angle)
    for ch, w in zip(text, widths):
        step = (w + extra) / radius
        mid = angle + (w / 2) / radius
        x = center.x() + radius * math.cos(mid)
        y = center.y() + radius * math.sin(mid)
        painter.save()
        painter.translate(x, y)
        painter.rotate(math.degrees(mid) + 90)
        painter.drawText(QPointF(-w / 2, metrics.ascent() * 0.35), ch)
        painter.restore()
        angle += step


def render_postmark(size: int, color: str, ring: str, number: str, sub: str,
                    dpr: float = 1.0, rotation: float = -12.0, seed: int = 5) -> QPixmap:
    """Большой круглый штемпель: два кольца, надпись по кругу, число в центре."""
    s = size * dpr
    image = QImage(int(s), int(s), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.scale(s / 200.0, s / 200.0)
    painter.translate(100, 100)
    painter.rotate(rotation)
    painter.translate(-100, -100)
    ink = QColor(color)
    pen = QPen(ink)
    pen.setWidthF(2.6)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(100, 100), 76, 76)
    pen.setWidthF(2.0)
    painter.setPen(pen)
    painter.drawEllipse(QPointF(100, 100), 50, 50)
    painter.setPen(ink)
    postmark_path_text(painter, QPointF(100, 100), 62, ring, fonts.mono(10.5, 500, 0.14), -90)
    painter.setFont(fonts.serif(40, 300))
    metrics = painter.fontMetrics()
    painter.drawText(QPointF(100 - metrics.horizontalAdvance(number) / 2, 110), number)
    if sub:
        painter.setFont(fonts.mono(10, 500, 0.14))
        metrics = painter.fontMetrics()
        painter.drawText(QPointF(100 - metrics.horizontalAdvance(sub) / 2, 127), sub)
    painter.end()
    _stamp_wear(image, seed)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def render_mini_postmark(width: int, color: str, top: str, bottom: str,
                         dpr: float = 1.0, waves: bool = True) -> QPixmap:
    """Маленький штемпель гашения: круг с надписью и волнистые линии."""
    height = width * 70 / 120
    image = QImage(int(width * dpr), int(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(width * dpr / 120.0, width * dpr / 120.0)
    ink = QColor(color)
    pen = QPen(ink)
    pen.setWidthF(2.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(35, 35), 27, 27)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    painter.drawEllipse(QPointF(35, 35), 21, 21)
    if waves:
        painter.drawPath(parse_path(
            "M66 22 q 9 -6 18 0 t 18 0 t 18 0 M66 32 q 9 -6 18 0 t 18 0 t 18 0 "
            "M66 42 q 9 -6 18 0 t 18 0 t 18 0 M66 52 q 9 -6 18 0 t 18 0 t 18 0"))
    painter.setPen(ink)
    # Длинное слово ужимаем, чтобы оно встало внутрь кольца.
    size = 8.0
    painter.setFont(fonts.mono(size, 600, 0.06))
    while painter.fontMetrics().horizontalAdvance(top) > 38 and size > 5.5:
        size -= 0.5
        painter.setFont(fonts.mono(size, 600, 0.04))
    metrics = painter.fontMetrics()
    painter.drawText(QPointF(35 - metrics.horizontalAdvance(top) / 2, 33.5), top)
    painter.setFont(fonts.mono(7, 600, 0.06))
    metrics = painter.fontMetrics()
    painter.drawText(QPointF(35 - metrics.horizontalAdvance(bottom) / 2, 44), bottom)
    painter.end()
    _stamp_wear(image, 11)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def _stamp_wear(image: QImage, seed: int) -> None:
    """Штемпельная краска ложится неровно: выбиваем мелкие просветы."""
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    brush = QBrush(grain_texture())
    transform = QTransform()
    transform.translate(seed * 17 % 128, seed * 29 % 128)
    brush.setTransform(transform)
    painter.fillRect(QRectF(0, 0, image.width(), image.height()), brush)
    painter.end()


# =========================================================================
# Марка с перфорацией
# =========================================================================


def perforated(rect_: QRectF, radius: float = 4.0, gap: float = 12.0) -> QPainterPath:
    """Контур почтовой марки: прямоугольник с выбитыми полукругами по краю."""
    path = QPainterPath()
    path.addRect(rect_)
    holes = QPainterPath()
    nx = max(2, int(round(rect_.width() / gap)))
    ny = max(2, int(round(rect_.height() / gap)))
    step_x = rect_.width() / nx
    step_y = rect_.height() / ny
    for k in range(nx + 1):
        x = rect_.left() + k * step_x
        holes.addEllipse(QPointF(x, rect_.top()), radius, radius)
        holes.addEllipse(QPointF(x, rect_.bottom()), radius, radius)
    for k in range(1, ny):
        y = rect_.top() + k * step_y
        holes.addEllipse(QPointF(rect_.left(), y), radius, radius)
        holes.addEllipse(QPointF(rect_.right(), y), radius, radius)
    return path.subtracted(holes)
