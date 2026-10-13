"""Знакомство с программой и рассказ о новой версии.

Знакомство — прогулка по разделам: окно чуть темнеет, а нужное место
подсвечивается «окошком», к которому тянется нарисованная стрелка. Рядом —
карточка: что это и зачем. Можно листать назад и вперёд или пропустить.

«Что нового» после обновления: сначала на экране прежний облик программы,
и его широкими мазками кисти закрашивает новый. Потом приходит письмо со
штемпелем — что изменилось.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.core import paths
from app.core.config import config
from app.ui.ink import NoiseField, expo_out, inout, motion_level, quart_out
from app.ui.widgets import Button, MonoLabel, SerifTitle, fade_in, snapshot


# =========================================================================
# Шаги знакомства
# =========================================================================


@dataclass
class Step:
    title: str
    text: str
    target: Callable[[], object] | None = None   # виджет или QRect в координатах окна
    page: str = ""                               # куда перейти перед шагом
    pad: int = 10


def default_steps(window) -> list[Step]:
    """Прогулка по главному: от закладок до трея."""

    def page(key: str):
        return window.ensure_page(key)

    def home(attribute: str):
        return lambda: getattr(page("home"), attribute, None)

    def stamps():
        home_page = page("home")
        columns = getattr(home_page, "_columns", ())
        widgets = [column for column in columns if column.isVisible()]
        if not widgets:
            return None
        rect = QRect()
        for widget in widgets:
            top_left = widget.mapTo(window.root, widget.rect().topLeft())
            rect = rect.united(QRect(top_left, widget.size()))
        return rect

    def strategies_bed():
        return getattr(page("strategies"), "bed", None)

    def vpn_map():
        section = page("vpn")
        finder = getattr(section, "tab_widget", None)
        connect = finder("connect") if callable(finder) else None
        return getattr(connect, "map", None)

    return [
        Step("Здравствуйте, это *ZapretCtrl*",
             "Обход блокировок, VPN по программам, прокси Telegram и Smart DNS — в одном "
             "окне. Минута — и покажу, где что лежит. Пропустить можно в любой момент."),
        Step("Разделы — сверху, *как закладки*",
             "Главная, Запрет, VPN, Telegram, Smart DNS, Диагностика и Настройки. Редкие — "
             "справа, мельче. С клавиатуры: Ctrl+1…7 и Ctrl+Tab.",
             lambda: window.tab_bar, "home", pad=4),
        Step("Сад показывает, *что работает*",
             "Лоза на стене — обход, калитка к морю — VPN, птица с письмом — Telegram, "
             "указатель — Smart DNS. Выключенное нарисовано карандашом. Штемпель считает, "
             "сколько из четырёх включено. На рисунок можно нажать.",
             home("plate_host"), "home"),
        Step("Тумблеры — *под марками*",
             "Каждая марка — одна служба. Здесь же выбираются стратегия обхода, сервер VPN "
             "и сервис Smart DNS. Щелчок по марке открывает её раздел.",
             stamps, "home"),
        Step("Всё ли *открывается*",
             "Кнопка стучится на десяток заблокированных адресов и показывает, какие "
             "письма дошли, а какие вернулись. Рядом — замер скорости.",
             home("btn_check"), "home", pad=8),
        Step("Какая стратегия *приживётся*",
             "Не знаете, какую стратегию выбрать, — вырастите грядку: все проверятся разом "
             "секунд за пятнадцать. Лучшая расцветёт, щелчок по ростку ставит её.",
             strategies_bed, "strategies"),
        Step("VPN — *дальние берега*",
             "Подписка от любого сервиса. Туннель для выбранных программ или прокси, "
             "который уживается с другим VPN. Лодка плывёт к выбранному берегу.",
             vpn_map, "vpn"),
        Step("Луна и *солнце*",
             "Тёмная и светлая тема — одним щелчком. Остальное — тема «как в Windows», "
             "спокойные анимации и запуск вместе с системой — в Настройках.",
             lambda: window.title_bar.btn_theme, "home", pad=6),
        Step("И последнее: *трей*",
             "Крестик прячет окно к часам — обход и VPN продолжают работать. Совсем "
             "выйти — правой кнопкой по значку в трее. Всё, можно пользоваться!",
             lambda: window.title_bar.btn_close, "home", pad=6),
    ]


# =========================================================================
# Карточка
# =========================================================================


class _Card(QFrame):
    def __init__(self, context, parent: QWidget) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("TourCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.counter = MonoLabel("", context, "accent_ink", 10.5)
        top.addWidget(self.counter)
        top.addStretch(1)
        self.skip = Button("Пропустить", variant="link")
        top.addWidget(self.skip)
        layout.addLayout(top)

        self.title = SerifTitle("", context, 24, self)
        layout.addWidget(self.title)
        self.text = QLabel("", self)
        self.text.setWordWrap(True)
        self.text.setObjectName("Muted")
        layout.addWidget(self.text)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.dots = _Dots(context, self)
        bottom.addWidget(self.dots)
        bottom.addStretch(1)
        self.back = Button("Назад", variant="ghost")
        bottom.addWidget(self.back)
        self.next = Button("Далее  →", variant="primary")
        bottom.addWidget(self.next)
        layout.addLayout(bottom)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)
        self.setFixedWidth(372)
        self.restyle()

    def restyle(self) -> None:
        c = self.context
        self.setStyleSheet(
            f"QFrame#TourCard {{ background: {c.color('bg')}; border: 1px solid "
            f"{c.color('border_strong')}; border-radius: 18px; }}"
        )


class _Dots(QWidget):
    """Точки шагов: пройденные — тушью, текущая — глиной."""

    def __init__(self, context, parent: QWidget) -> None:
        super().__init__(parent)
        self.context = context
        self.count = 1
        self.index = 0
        self.setFixedHeight(12)

    def set_state(self, index: int, count: int) -> None:
        self.index, self.count = index, count
        self.setFixedWidth(count * 12)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for k in range(self.count):
            center = QPointF(5 + k * 12, 6)
            if k == self.index:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.context.color("clay")))
                painter.drawEllipse(center, 4, 4)
            else:
                pen = QPen(QColor(self.context.color("ink" if k < self.index else "decor")))
                pen.setWidthF(1.3)
                painter.setPen(pen)
                painter.setBrush(QColor(self.context.color("ink")) if k < self.index
                                 else Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, 3, 3)
        painter.end()


# =========================================================================
# Знакомство
# =========================================================================


class Tour(QWidget):
    """Подсветка и карточка поверх окна. Esc — пропустить, стрелки — листать."""

    def __init__(self, window, context, steps: list[Step] | None = None,
                 on_finish: Callable[[bool], None] | None = None) -> None:
        super().__init__(window.root)
        self.window_ = window
        self.context = context
        self.steps = steps or default_steps(window)
        self.on_finish = on_finish
        self.index = -1
        self._spot = QRectF()
        self._spot_from = QRectF()
        self._spot_to = QRectF()
        self._progress = 1.0
        self._arrow = 0.0
        self._veil = 0.0
        self._closing = False
        self._started = time.perf_counter()
        self._noise = NoiseField(seed=12, freq=0.7, amp=1.0)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(window.root.rect())

        self.card = _Card(context, self)
        self.card.skip.clicked.connect(lambda: self.finish(skipped=True))
        self.card.back.clicked.connect(lambda: self.go(self.index - 1))
        self.card.next.clicked.connect(self._next)

        self._spot_anim = QVariantAnimation(self)
        self._spot_anim.setDuration(620)
        self._spot_anim.setStartValue(0.0)
        self._spot_anim.setEndValue(1.0)
        self._spot_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._spot_anim.valueChanged.connect(self._advance_spot)
        self._arrow_anim = QVariantAnimation(self)
        self._arrow_anim.setDuration(700)
        self._arrow_anim.setStartValue(0.0)
        self._arrow_anim.setEndValue(1.0)
        self._arrow_anim.valueChanged.connect(self._advance_arrow)
        self._veil_anim = QVariantAnimation(self)
        self._veil_anim.setDuration(360)
        self._veil_anim.valueChanged.connect(self._advance_veil)
        self._veil_anim.finished.connect(self._veil_done)
        self._card_anim = QVariantAnimation(self)
        self._card_anim.setDuration(560)
        self._card_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._card_anim.valueChanged.connect(self.card.move)
        window.root.installEventFilter(self)

    # --- запуск и конец -------------------------------------------------

    def start(self) -> None:
        self.show()
        self.raise_()
        self.setFocus()
        self._veil_anim.setStartValue(0.0)
        self._veil_anim.setEndValue(1.0)
        self._veil_anim.start()
        self.go(0)

    def finish(self, skipped: bool = False) -> None:
        if self._closing:
            return
        self._closing = True
        config.set("tour_done", True)
        self._veil_anim.stop()
        self._veil_anim.setStartValue(self._veil)
        self._veil_anim.setEndValue(0.0)
        self._veil_anim.start()
        self.card.hide()
        if self.on_finish is not None:
            self.on_finish(skipped)

    def _veil_done(self) -> None:
        if self._closing:
            self.window_.root.removeEventFilter(self)
            self.hide()
            self.deleteLater()

    def _next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.window_.show_page("home")
            self.finish()
        else:
            self.go(self.index + 1)

    # --- шаги -----------------------------------------------------------

    def go(self, index: int) -> None:
        if not 0 <= index < len(self.steps) or self._closing:
            return
        self.index = index
        step = self.steps[index]
        if step.page and getattr(self.window_, "_current_key", "") != step.page:
            self.window_.show_page(step.page)
            # Раздел въезжает ~0,4 с — меряем цель, когда он встал на место.
            QTimer.singleShot(460, lambda i=index: self._place(i))
        else:
            self._place(index)
        card = self.card
        card.counter.setText(f"Шаг {index + 1} из {len(self.steps)}" if index else "Знакомство")
        card.title.set_title(step.title)
        card.text.setText(step.text)
        card.back.setVisible(index > 0)
        card.next.setText("Готово" if index == len(self.steps) - 1 else
                          ("Покажите  →" if index == 0 else "Далее  →"))
        card.skip.setVisible(index < len(self.steps) - 1)
        card.dots.set_state(index, len(self.steps))
        card.adjustSize()
        fade_in(card.title, 360)
        fade_in(card.text, 420, delay=60)

    def _target_rect(self, step: Step) -> QRectF:
        if step.target is None:
            return QRectF()
        target = step.target()
        if target is None:
            return QRectF()
        if isinstance(target, QRect):
            rect = QRectF(target)
        else:
            if not target.isVisible():
                return QRectF()
            # Цель в прокручиваемой странице — сперва показать её.
            parent = target.parentWidget()
            while parent is not None:
                ensure = getattr(parent, "ensureWidgetVisible", None)
                if callable(ensure):
                    ensure(target, 0, 40)
                    break
                parent = parent.parentWidget()
            top_left = target.mapTo(self.window_.root, target.rect().topLeft())
            rect = QRectF(top_left.x(), top_left.y(), target.width(), target.height())
        pad = step.pad
        rect = rect.adjusted(-pad, -pad, pad, pad)
        return rect.intersected(QRectF(self.rect()).adjusted(4, 4, -4, -4))

    def _place(self, index: int) -> None:
        if index != self.index or self._closing:
            return
        step = self.steps[index]
        target = self._target_rect(step)
        self._spot_from = QRectF(self._spot)
        self._spot_to = target
        if self._spot_from.isNull():
            # Первое окошко раскрывается из точки в его центре.
            center = target.center() if not target.isNull() else QPointF(self.rect().center())
            self._spot_from = QRectF(center, center)
        self._progress = 0.0
        self._spot_anim.stop()
        self._spot_anim.start()
        self._arrow = 0.0
        self._arrow_anim.stop()
        self._arrow_anim.start()
        self._move_card(target)

    def _move_card(self, target: QRectF) -> None:
        card = self.card
        card.adjustSize()
        w, h = card.width(), card.height()
        area = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        if target.isNull():
            pos = QPointF(area.center().x() - w / 2, area.center().y() - h / 2)
        else:
            gap = 46
            candidates = (
                QPointF(target.center().x() - w / 2, target.bottom() + gap),   # снизу
                QPointF(target.right() + gap, target.center().y() - h / 2),    # справа
                QPointF(target.left() - gap - w, target.center().y() - h / 2), # слева
                QPointF(target.center().x() - w / 2, target.top() - gap - h),  # сверху
            )
            pos = None
            for point in candidates:
                box = QRectF(point.x(), point.y(), w, h)
                clamped = QRectF(min(max(box.left(), area.left()), area.right() - w),
                                 min(max(box.top(), area.top()), area.bottom() - h), w, h)
                if not clamped.intersects(target):
                    pos = clamped.topLeft()
                    break
            if pos is None:
                pos = QPointF(area.right() - w, area.bottom() - h)
        if not card.isVisible():
            card.move(pos.toPoint())
            card.show()
            fade_in(card, 420)
            return
        self._card_anim.stop()
        self._card_anim.setStartValue(card.pos())
        self._card_anim.setEndValue(pos.toPoint())
        self._card_anim.start()

    # --- анимация -------------------------------------------------------

    def _advance_spot(self, value) -> None:
        self._progress = float(value)
        a, b = self._spot_from, self._spot_to
        if b.isNull():
            self._spot = QRectF()
        else:
            t = self._progress
            self._spot = QRectF(a.left() + (b.left() - a.left()) * t,
                                a.top() + (b.top() - a.top()) * t,
                                a.width() + (b.width() - a.width()) * t,
                                a.height() + (b.height() - a.height()) * t)
        self.update()

    def _advance_arrow(self, value) -> None:
        self._arrow = float(value)
        self.update()

    def _advance_veil(self, value) -> None:
        self._veil = float(value)
        self.update()

    # --- события --------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if watched is self.window_.root and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.window_.root.rect())
            if 0 <= self.index < len(self.steps):
                QTimer.singleShot(0, lambda: self._place(self.index))
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.finish(skipped=True)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._next()
        elif key == Qt.Key.Key_Left:
            self.go(self.index - 1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Окно под затемнением не трогаем: прогулку ведёт карточка.
        event.accept()

    # --- рисование ------------------------------------------------------

    def _ring(self, rect: QRectF, now: float) -> QPainterPath:
        """Обводка окошка от руки: слегка неровная и не совсем замкнутая."""
        path = QPainterPath()
        count = 72
        cx, cy = rect.center().x(), rect.center().y()
        rx, ry = rect.width() / 2 + 6, rect.height() / 2 + 6
        portion = quart_out(self._arrow * 1.3)
        steps = max(2, int(count * portion))
        for k in range(steps + 1):
            a = -math.pi * 0.62 + k / count * math.tau * 1.04
            wobble = 1.0 + 0.012 * self._noise.at(math.cos(a) * 3, math.sin(a) * 3 + now * 0.2)[0]
            # Скруглённый прямоугольник через «суперэллипс».
            ca, sa = math.cos(a), math.sin(a)
            x = cx + rx * wobble * math.copysign(abs(ca) ** 0.35, ca)
            y = cy + ry * wobble * math.copysign(abs(sa) ** 0.35, sa)
            if k == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        return path

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.context
        veil = QColor(c.color("ink" if not c.is_dark else "#000000"))
        veil.setAlphaF((0.34 if not c.is_dark else 0.55) * self._veil)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        spot = self._spot
        if not spot.isNull() and spot.width() > 1:
            hole = QPainterPath()
            hole.addRoundedRect(spot, 14, 14)
            shade = shade.subtracted(hole)
        painter.fillPath(shade, veil)

        if self._closing or spot.isNull() or spot.width() < 4 or self._progress < 0.2:
            painter.end()
            return
        now = time.perf_counter() - self._started
        pen = QPen(QColor(c.color("clay")))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._ring(spot, now))

        # Стрелка от карточки к окошку — прорисовывается.
        card = QRectF(self.card.geometry())
        if self.card.isVisible() and self._arrow > 0.05:
            start, end = self._arrow_ends(card, spot)
            mid = (start + end) / 2
            bend = QPointF(-(end.y() - start.y()), end.x() - start.x())
            length = math.hypot(bend.x(), bend.y()) or 1.0
            control = mid + QPointF(bend.x() / length * 34, bend.y() / length * 34)
            curve = QPainterPath(start)
            curve.quadTo(control, end)
            t = inout(self._arrow)
            points = [curve.pointAtPercent(k / 30 * t) for k in range(31)]
            # Стрелка светлая: она лежит на затемнении.
            arrow_pen = QPen(QColor(c.color("manilla") if c.is_dark else "#FAF9F5"))
            arrow_pen.setWidthF(2.0)
            arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arrow_pen)
            painter.drawPolyline(QPolygonF(points))
            if t > 0.92:
                tip = points[-1]
                before = curve.pointAtPercent(max(0.0, t - 0.06))
                angle = math.atan2(tip.y() - before.y(), tip.x() - before.x())
                for side in (-1, 1):
                    a = angle + math.pi + side * 0.45
                    painter.drawLine(tip, QPointF(tip.x() + 11 * math.cos(a),
                                                  tip.y() + 11 * math.sin(a)))
        painter.end()

    @staticmethod
    def _arrow_ends(card: QRectF, spot: QRectF) -> tuple[QPointF, QPointF]:
        """Откуда и куда тянуть стрелку: от ближнего края карточки к окошку."""
        cc, sc = card.center(), spot.center()
        dx, dy = sc.x() - cc.x(), sc.y() - cc.y()
        if abs(dx) * card.height() > abs(dy) * card.width():
            start = QPointF(card.right() + 4 if dx > 0 else card.left() - 4, cc.y())
        else:
            start = QPointF(cc.x(), card.bottom() + 4 if dy > 0 else card.top() - 4)
        # Остриё — на краю окошка, а не в его центре.
        ex = min(max(start.x(), spot.left() + 10), spot.right() - 10)
        ey = min(max(start.y(), spot.top() + 10), spot.bottom() - 10)
        end = QPointF(ex, ey)
        if spot.contains(end):
            if abs(dx) * card.height() > abs(dy) * card.width():
                end.setX(spot.left() - 8 if dx > 0 else spot.right() + 8)
            else:
                end.setY(spot.top() - 8 if dy > 0 else spot.bottom() + 8)
        return start, end


# =========================================================================
# Что нового: прежний облик закрашивается новым
# =========================================================================


class WhatsNew(QWidget):
    """Прежняя главная — и новая проступает поверх широкими мазками.

    Потом приходит письмо: что изменилось. «Показать, где что» запускает
    знакомство.
    """

    STROKES = 7
    STROKE_SECONDS = 1.05
    STAGGER = 0.16

    def __init__(self, window, context, changes, previous: str = "",
                 on_done: Callable[[str], None] | None = None) -> None:
        super().__init__(window.root)
        self.window_ = window
        self.context = context
        self.changes = list(changes)
        self.previous = previous
        self.on_done = on_done
        self._old: QPixmap | None = None
        self._new: QPixmap | None = None
        self._t0 = 0.0
        self._phase = "paint"
        self._veil = 0.0
        self._closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(window.root.rect())
        self._spines = self._make_spines()
        self._edge = NoiseField(seed=21, freq=0.012, amp=16.0, octaves=2)

        self.letter = self._build_letter()
        self.letter.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._veil_anim = QVariantAnimation(self)
        self._veil_anim.setDuration(420)
        self._veil_anim.valueChanged.connect(self._advance_veil)
        self._veil_anim.finished.connect(self._veil_done)
        self._rise = QVariantAnimation(self)
        self._rise.setDuration(760)
        self._rise.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._rise.valueChanged.connect(self.letter.move)

    # --- письмо ---------------------------------------------------------

    def _build_letter(self) -> QFrame:
        from app.core.constants import APP_NAME, APP_VERSION
        from app.ui.ink import render_mini_postmark
        from app.ui.naming import postmark_date
        from app.ui.shell import draw_tab_icon

        c = self.context
        letter = QFrame(self)
        letter.setObjectName("Letter")
        letter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        letter.setStyleSheet(
            f"QFrame#Letter {{ background: {c.color('bg')}; border: 1px solid "
            f"{c.color('border_strong')}; border-radius: 20px; }}"
        )
        shadow = QGraphicsDropShadowEffect(letter)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 110))
        letter.setGraphicsEffect(shadow)
        layout = QVBoxLayout(letter)
        layout.setContentsMargins(30, 24, 30, 22)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(6)
        version = f"{self.previous} → {APP_VERSION}" if self.previous else APP_VERSION
        column.addWidget(MonoLabel(f"Письмо · версия {version}", c, "accent_ink", 11))
        column.addWidget(SerifTitle(f"Что нового в *{APP_NAME} {APP_VERSION.rsplit('.', 1)[0]}*",
                                    c, 32, letter))
        top.addLayout(column, 1)
        mark = QLabel(letter)
        mark.setPixmap(render_mini_postmark(150, c.color("pm"), "ДОСТАВЛЕНО", postmark_date(),
                                            self.devicePixelRatioF()))
        mark.setStyleSheet("background: transparent;")
        top.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(14)
        for index, (icon, title, text, token) in enumerate(self.changes):
            cell = QHBoxLayout()
            cell.setSpacing(12)
            badge = _IconBadge(c, icon, token, draw_tab_icon, letter)
            cell.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            words = QVBoxLayout()
            words.setSpacing(3)
            name = QLabel(title, letter)
            name.setStyleSheet("font-weight: 500; font-size: 14px; background: transparent;")
            name.setWordWrap(True)
            words.addWidget(name)
            body = QLabel(text, letter)
            body.setObjectName("Faint")
            body.setWordWrap(True)
            words.addWidget(body)
            cell.addLayout(words, 1)
            grid.addLayout(cell, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        later = Button("Понятно", variant="soft")
        later.clicked.connect(lambda: self.close_animated("close"))
        buttons.addWidget(later)
        tour = Button("Показать, где что  →", variant="primary")
        tour.clicked.connect(lambda: self.close_animated("tour"))
        buttons.addWidget(tour)
        layout.addLayout(buttons)
        letter.setFixedWidth(min(760, max(520, self.width() - 80)))
        letter.adjustSize()
        return letter

    # --- мазки ----------------------------------------------------------

    def _make_spines(self) -> list[tuple[float, float, float]]:
        """Широкие мазки сверху вниз, чуть наискосок; соседние перекрываются."""
        result = []
        for k in range(self.STROKES):
            y = (k + 0.5) / self.STROKES
            tilt = 0.06 if k % 2 == 0 else -0.04
            result.append((y, tilt, k * self.STAGGER))
        return result

    def _mask(self, now: float) -> QPainterPath:
        w, h = self.width(), self.height()
        band = h / self.STROKES * 0.78 + 26
        mask = QPainterPath()
        mask.setFillRule(Qt.FillRule.WindingFill)
        for index, (y, tilt, delay) in enumerate(self._spines):
            p = inout((now - delay) / self.STROKE_SECONDS)
            if p <= 0:
                continue
            # Мазок идёт слева направо (через один — справа налево).
            reverse = index % 2 == 1
            length = (w + 160) * p
            x0 = -80 if not reverse else w + 80
            direction = 1 if not reverse else -1
            top, bottom = [], []
            steps = 40
            for k in range(steps + 1):
                s = k / steps
                x = x0 + direction * length * s
                cy = y * h + tilt * (x - w / 2)
                # Кончик мазка сужается, края — рваные.
                taper = min(1.0, (1 - s) * 6 + 0.25) if p < 1.0 else 1.0
                half = band / 2 * taper
                n1 = self._edge.at(x * 0.6, index * 37.0)[0]
                n2 = self._edge.at(x * 0.6, index * 37.0 + 90)[1]
                top.append(QPointF(x, cy - half + n1))
                bottom.append(QPointF(x, cy + half + n2))
            polygon = QPolygonF(top + list(reversed(bottom)))
            mask.addPolygon(polygon)
            mask.closeSubpath()
        return mask

    # --- ход ------------------------------------------------------------

    def start(self) -> None:
        from app.core.constants import APP_VERSION

        dark = self.context.is_dark
        legacy = paths.resource_path("legacy", "home-dark.png" if dark else "home-light.png")
        root = self.window_.root
        bg = QColor(self.context.color("bg"))
        self._new = snapshot(root, bg)
        if legacy.exists() and motion_level() != "off":
            image = QPixmap(str(legacy))
            # Старый снимок — по размеру окна (он был снят в 1240×860).
            self._old = image.scaled(root.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        self.show()
        self.raise_()
        self.setFocus()
        self._caption_from = f"было · Zapret Control+ {self.previous}".strip()
        self._caption_to = f"стало · ZapretCtrl {APP_VERSION}"
        if self._old is None:
            self._show_letter()
            return
        self._t0 = time.perf_counter()
        self._timer.start()

    def _total(self) -> float:
        return self._spines[-1][2] + self.STROKE_SECONDS + 0.35

    def _tick(self) -> None:
        now = time.perf_counter() - self._t0
        self.update()
        if now > self._total() + 0.5 and self._phase == "paint":
            self._phase = "letter"
            self._timer.stop()
            self._show_letter()

    def _show_letter(self) -> None:
        self._phase = "letter"
        self._old = None
        self._veil_anim.stop()
        self._veil_anim.setStartValue(0.0)
        self._veil_anim.setEndValue(1.0)
        self._veil_anim.start()
        letter = self.letter
        # Высота — по переносам строк: adjustSize их не учитывает.
        layout = letter.layout()
        letter.ensurePolished()
        layout.activate()
        height = layout.totalHeightForWidth(letter.width())
        letter.resize(letter.width(), max(height, letter.sizeHint().height()))
        x = (self.width() - letter.width()) // 2
        y = max(20, (self.height() - letter.height()) // 2)
        letter.move(x, y + 46)
        letter.show()
        fade_in(letter, 520)
        self._rise.stop()
        self._rise.setStartValue(letter.pos())
        self._rise.setEndValue(letter.pos() - QPointF(0, 46).toPoint())
        self._rise.start()

    def close_animated(self, action: str) -> None:
        if self._closing:
            return
        self._closing = True
        self.letter.hide()
        self._veil_anim.stop()
        self._veil_anim.setStartValue(self._veil)
        self._veil_anim.setEndValue(0.0)
        self._veil_anim.start()
        self._action = action

    def _advance_veil(self, value) -> None:
        self._veil = float(value)
        self.update()

    def _veil_done(self) -> None:
        if not self._closing:
            return
        self.hide()
        self.deleteLater()
        if self.on_done is not None:
            self.on_done(getattr(self, "_action", "close"))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._phase == "paint":
                self._timer.stop()
                self._show_letter()
            else:
                self.close_animated("close")
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Щелчок во время закрашивания — сразу к письму.
        if self._phase == "paint":
            self._timer.stop()
            self._show_letter()
        event.accept()

    # --- рисование ------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        from app.ui import fonts

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.context
        if self._phase == "paint" and self._old is not None and self._new is not None:
            now = time.perf_counter() - self._t0
            painter.drawPixmap(0, 0, self._old)
            mask = self._mask(now)
            painter.save()
            painter.setClipPath(mask)
            painter.drawPixmap(0, 0, self._new)
            painter.restore()
            # Подпись внизу: «было» тает, «стало» проступает.
            share = expo_out(max(0.0, (now - 0.6) / 1.2))
            painter.setFont(fonts.mono(11, 500, 0.12))
            metrics = painter.fontMetrics()
            for text, alpha in ((self._caption_from.upper(), 1 - share),
                                (self._caption_to.upper(), share)):
                if alpha <= 0.02:
                    continue
                width = metrics.horizontalAdvance(text) + 28
                box = QRectF((self.width() - width) / 2, self.height() - 54, width, 28)
                painter.setOpacity(alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c.color("ink")))
                painter.drawRoundedRect(box, 14, 14)
                painter.setPen(QColor(c.color("bg")))
                painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
            painter.setOpacity(1.0)
        if self._veil > 0.0:
            veil = QColor(c.color("ink") if not c.is_dark else "#000000")
            veil.setAlphaF((0.36 if not c.is_dark else 0.58) * self._veil)
            painter.fillRect(self.rect(), veil)
        painter.end()


class _IconBadge(QWidget):
    """Кружок с рисованным значком — для строк письма."""

    def __init__(self, context, icon: str, token: str, drawer, parent: QWidget) -> None:
        super().__init__(parent)
        self.context = context
        self.icon = icon
        self.token = token
        self.drawer = drawer
        self.setFixedSize(34, 34)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.context
        painter.setPen(Qt.PenStyle.NoPen)
        tint = QColor(c.color(f"{self.token}_soft", c.color("card")))
        painter.setBrush(tint)
        painter.drawEllipse(QRectF(1, 1, 32, 32))
        self.drawer(painter, self.icon, QRectF(8, 8, 18, 18),
                    QColor(c.color(self.token, c.color("ink"))), 1.6)
        painter.end()
