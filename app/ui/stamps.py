"""Почтовые марки и штемпели главной.

Марка — бумажный прямоугольник с перфорацией, внутри рисунок службы,
номинал (стратегия, страна, порт, сервис) и подпись. Включили службу —
рисунок распускается красками, а сверху ложится штемпель «РАБОТАЕТ».
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui import fonts
from app.ui.ink import (
    STAMP_PALETTE,
    SceneRenderer,
    blurred_shadow,
    expo_out,
    motion_level,
    perforated,
    quart_out,
    render_mini_postmark,
    render_postmark,
)

# Поля вокруг бумаги марки: сверху и справа висит штемпель, снизу — тень.
PAD_LEFT, PAD_TOP, PAD_RIGHT, PAD_BOTTOM = 4, 20, 30, 14


class StampCard(QWidget):
    """Марка с живым рисунком. Нажатие ведёт в раздел службы."""

    clicked = Signal()

    def __init__(self, context, scene, tint: str, caption: str, den: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.renderer = SceneRenderer(scene, STAMP_PALETTE)
        self.tint_token = tint
        self.caption = caption
        self.den = den
        self.on = False
        self._tint = 0.0          # 0 — серая бумага, 1 — подкрашенная
        self._mark = 0.0          # штемпель «работает»
        self._lift = 0.0          # приподнята под мышкой
        self._shadow = None
        self._shadow_key = None
        self._mark_pixmap = None
        self._mark_key = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._tint_anim = QVariantAnimation(self)
        self._tint_anim.setDuration(700)
        self._tint_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._tint_anim.valueChanged.connect(self._set_tint)
        self._mark_anim = QVariantAnimation(self)
        self._mark_anim.setDuration(560)
        self._mark_anim.valueChanged.connect(self._set_mark)
        self._lift_anim = QVariantAnimation(self)
        self._lift_anim.setDuration(420)
        self._lift_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._lift_anim.valueChanged.connect(self._set_lift)
        context.theme_changed.connect(self._theme_changed)
        self._theme_changed()

    # --- размеры --------------------------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        paper = width - PAD_LEFT - PAD_RIGHT
        art_w = paper - 16 - 16
        return int(PAD_TOP + 8 + 8 + art_w * 140 / 200 + 6 + 24 + 10 + 8 + PAD_BOTTOM)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(250, self.heightForWidth(250))

    # --- состояние ------------------------------------------------------

    def _theme_changed(self) -> None:
        self.renderer.motion = motion_level()
        self.renderer._invalidate(rebuild_units=True)
        self._shadow_key = None
        self._mark_key = None
        self._sync_clock()
        self.update()

    def set_den(self, den: str) -> None:
        if den != self.den:
            self.den = den
            self.update()

    def set_text(self, key: str, value: str) -> None:
        if self.renderer.scene.texts.get(key) != value:
            self.renderer.set_text(key, value)
            self.update()

    def set_on(self, on: bool, animate: bool = True) -> None:
        if on == self.on:
            return
        self.on = on
        animate = animate and self.isVisible() and motion_level() != "off"
        self.renderer.set_state("on", on, animate)
        for animation, value, setter in ((self._tint_anim, self._tint, self._set_tint),
                                         (self._mark_anim, self._mark, self._set_mark)):
            animation.stop()
            if animate:
                animation.setStartValue(value)
                animation.setEndValue(1.0 if on else 0.0)
            else:
                setter(1.0 if on else 0.0)
        if animate:
            self._tint_anim.start()
            # Штемпель ложится, когда рисунок уже распустился.
            self._mark_anim.setStartValue(-0.9 if on else self._mark)
            self._mark_anim.setDuration(1300 if on else 250)
            self._mark_anim.start()
        self._sync_clock()
        self.update()

    def _set_tint(self, value) -> None:
        self._tint = float(value)
        self.update()

    def _set_mark(self, value) -> None:
        self._mark = float(value)
        self.update()

    def _set_lift(self, value) -> None:
        self._lift = float(value)
        self.update()

    # --- кадры ----------------------------------------------------------

    def frame_divider(self) -> int:
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

    # --- мышь -----------------------------------------------------------

    def event(self, event) -> bool:  # noqa: A003
        from PySide6.QtCore import QEvent

        if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self._lift_anim.stop()
            self._lift_anim.setStartValue(self._lift)
            self._lift_anim.setEndValue(1.0 if event.type() == QEvent.Type.HoverEnter else 0.0)
            self._lift_anim.start()
        return super().event(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # --- рисование ------------------------------------------------------

    def _paper_rect(self) -> QRectF:
        return QRectF(PAD_LEFT, PAD_TOP, self.width() - PAD_LEFT - PAD_RIGHT,
                      self.height() - PAD_TOP - PAD_BOTTOM)

    def _shadow_pixmap(self, shape: QPainterPath):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.context.is_dark)
        if self._shadow_key != key:
            color = QColor(0, 0, 0, 120) if self.context.is_dark else QColor(20, 20, 19, 46)
            self._shadow = blurred_shadow(shape, self.size(), color, 9.0, (0.0, 4.0), dpr)
            self._shadow_key = key
        return self._shadow

    def _mini_mark(self):
        from app.ui.naming import postmark_date

        dpr = self.devicePixelRatioF()
        date = postmark_date()
        key = (dpr, date, self.context.is_dark)
        if self._mark_key != key:
            self._mark_pixmap = render_mini_postmark(
                104, self.context.color("pm"), "РАБОТАЕТ", date, dpr)
            self._mark_key = key
        return self._mark_pixmap

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        lift = expo_out(self._lift) * 3.0
        paper = self._paper_rect()
        shape = perforated(paper)

        shadow = self._shadow_pixmap(shape)
        if shadow is not None:
            painter.setOpacity(0.85 + 0.15 * self._lift)
            painter.drawPixmap(QPointF(0, lift * 0.4), shadow)
            painter.setOpacity(1.0)

        painter.translate(0, -lift)
        painter.fillPath(shape, QColor(self.context.color("stamp_paper")))

        face = paper.adjusted(8, 8, -8, -8)
        off = QColor(self.context.color("tint_off"))
        on = QColor(self.context.color(self.tint_token))
        t = self._tint
        tint = QColor(int(off.red() + (on.red() - off.red()) * t),
                      int(off.green() + (on.green() - off.green()) * t),
                      int(off.blue() + (on.blue() - off.blue()) * t))
        painter.fillRect(face, tint)
        pen = QPen(QColor(20, 20, 19, 72))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRect(face.adjusted(0.5, 0.5, -0.5, -0.5))

        art = QRectF(face.left() + 8, face.top() + 8, face.width() - 16,
                     (face.width() - 16) * 140 / 200)
        painter.save()
        painter.setClipRect(art)
        self.renderer.paint(painter, art, self.devicePixelRatioF())
        painter.restore()

        # Номинал и подпись.
        meta_y = art.bottom() + 6
        painter.setPen(QColor("#141413"))
        painter.setFont(fonts.serif(21, 400, italic=True))
        metrics = painter.fontMetrics()
        den = metrics.elidedText(self.den, Qt.TextElideMode.ElideRight, int(art.width() * 0.55))
        painter.drawText(QPointF(art.left() + 2, meta_y + metrics.ascent()), den)
        painter.setFont(fonts.mono(9.5, 500, 0.1))
        painter.setPen(QColor("#3D3D3A"))
        small = painter.fontMetrics()
        cap = small.elidedText(self.caption, Qt.TextElideMode.ElideRight, int(art.width() * 0.45))
        painter.drawText(QPointF(art.right() - 2 - small.horizontalAdvance(cap),
                                 meta_y + metrics.ascent() - 1), cap)

        # Штемпель «РАБОТАЕТ»: падает сверху чуть повёрнутым и ложится.
        if self._mark > 0.0:
            p = quart_out(self._mark) if self.on else self._mark
            mark = self._mini_mark()
            dpr = mark.devicePixelRatio() or 1.0
            w, h = mark.width() / dpr, mark.height() / dpr
            cx = paper.right() - w * 0.36 + 10
            cy = paper.top() + 8
            scale = 1.35 - 0.35 * expo_out(self._mark) if self.on else 1.0
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(-14)
            painter.scale(scale, scale)
            painter.setOpacity(0.9 * p)
            painter.drawPixmap(QPointF(-w / 2, -h / 2), mark)
            painter.restore()
        painter.end()
        if self.renderer.motion == "off" and not self.renderer.busy():
            from app.ui.widgets import frame_clock

            frame_clock().unsubscribe(self)


class Postmark(QWidget):
    """Большой штемпель над садом: «2/4», надпись по кругу и время.

    Когда число работающих меняется, штемпель «пробивается» заново: падает
    крупнее и с поворотом и ложится на место.
    """

    def __init__(self, context, size: int = 168, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._ring = ""
        self._number = ""
        self._sub = ""
        self._pixmap = None
        self._key = None
        self._press = 1.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(700)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._advance)
        context.theme_changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._key = None
        self.update()

    def set_text(self, ring: str, number: str, sub: str, press: bool = True) -> None:
        changed_number = number != self._number
        if (ring, number, sub) == (self._ring, self._number, self._sub):
            return
        self._ring, self._number, self._sub = ring, number, sub
        self._key = None
        if press and changed_number and self.isVisible() and motion_level() != "off":
            self._animation.stop()
            self._press = 0.0
            self._animation.start()
        self.update()

    def _advance(self, value) -> None:
        self._press = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        dpr = self.devicePixelRatioF()
        key = (self._ring, self._number, self._sub, dpr, self.context.color("pm"), self.width())
        if key != self._key:
            self._pixmap = render_postmark(self.width(), self.context.color("pm"), self._ring,
                                           self._number, self._sub, dpr)
            self._key = key
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        t = expo_out(self._press)
        scale = 1.3 - 0.3 * t
        angle = 4.0 * (1.0 - t)
        painter.setOpacity(0.92 * min(1.0, self._press * 2.2))
        c = self.width() / 2
        painter.translate(c, c)
        painter.rotate(angle)
        painter.scale(scale, scale)
        painter.translate(-c, -c)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()
