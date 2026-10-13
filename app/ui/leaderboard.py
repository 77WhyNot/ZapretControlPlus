"""Таблица проверки стратегий: все строки заполняются одновременно.

Анимации — на общем кадровом таймере и по реальному времени, как у схемы
маршрутов: кружки пульсируют, пока ждут ответа, и «щёлкают» цветом, когда он
пришёл. Фон строк рисуется ими самими — стиль с фоном на контейнере Qt
раздал бы всем вложенным подписям.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.autotest import ProbeResult, StrategyScore, Target
from app.core.strategies import Strategy
from app.ui.context import AppContext
from app.ui.widgets import Badge, Button, ElidedLabel, fade_in, frame_clock

VISIBLE_ROWS = 8          # после проверки видны лучшие, остальные — по кнопке
POP_SECONDS = 0.35


def _mix(first: QColor, second: QColor, share: float) -> QColor:
    share = max(0.0, min(1.0, share))
    return QColor(
        round(first.red() + (second.red() - first.red()) * share),
        round(first.green() + (second.green() - first.green()) * share),
        round(first.blue() + (second.blue() - first.blue()) * share),
    )


class ResultDots(QWidget):
    """Кружок на каждый проверяемый сайт: ждём, открылся, не открылся."""

    DOT = 9
    GAP = 5

    def __init__(self, context: AppContext, targets: list[Target],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._targets = list(targets)
        self._states: list[bool | None] = [None] * len(targets)
        self._changed: list[float] = [0.0] * len(targets)
        self._ms: list[float] = [0.0] * len(targets)
        self._pending = True
        width = max(1, len(targets)) * (self.DOT + self.GAP) - self.GAP + 4
        self.setFixedSize(width, 16)
        self._animate()

    def set_results(self, results: list[ProbeResult]) -> None:
        by_url = {item.target.url: item for item in results}
        now = time.perf_counter()
        for index, target in enumerate(self._targets):
            item = by_url.get(target.url)
            if item is None:
                continue
            if self._states[index] != item.ok:
                self._states[index] = item.ok
                self._changed[index] = now
            self._ms[index] = item.ms
        self._pending = any(state is None for state in self._states)
        self._update_tooltip()
        self._animate()

    def stop_waiting(self) -> None:
        """Ответа не будет (проверку отменили или стратегия не запустилась)."""
        self._pending = False
        self.update()

    def _update_tooltip(self) -> None:
        lines = []
        for target, state, ms in zip(self._targets, self._states, self._ms):
            name = target.key or target.label
            if state is None:
                lines.append(f"{name} — ждём ответа")
            elif state:
                lines.append(f"{name} — открылся за {ms:.0f} мс")
            else:
                lines.append(f"{name} — не открылся")
        self.setToolTip("\n".join(lines))

    def _animate(self) -> None:
        frame_clock().subscribe(self)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        now = time.perf_counter()
        idle = QColor(self.context.color("border_strong"))
        good = QColor(self.context.color("success"))
        bad = QColor(self.context.color("danger"))
        middle = self.height() / 2
        moving = False
        for index, state in enumerate(self._states):
            x = 2 + index * (self.DOT + self.GAP) + self.DOT / 2
            radius = self.DOT / 2
            if state is None:
                color = QColor(idle)
                if self._pending:
                    # Волна по кружкам — видно, что проверка идёт.
                    wave = 0.5 + 0.5 * math.sin(now * 5.0 - index * 0.7)
                    color.setAlphaF(0.35 + 0.55 * wave)
                    moving = True
            else:
                target = good if state else bad
                age = now - self._changed[index]
                if age < POP_SECONDS:
                    share = age / POP_SECONDS
                    color = _mix(idle, target, share * 1.6)
                    radius *= 1.0 + 0.45 * math.sin(math.pi * share)
                    moving = True
                else:
                    color = target
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x - radius, middle - radius, radius * 2, radius * 2))
        painter.end()
        if not moving:
            frame_clock().unsubscribe(self)


class ShimmerBar(QWidget):
    """Тонкая полоса хода проверки: доля готового и бегущий блик поверх."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setFixedHeight(4)
        self._running = False
        self._fraction = 0.0
        self._shown = 0.0
        self._last = time.perf_counter()

    def start(self) -> None:
        self._running = True
        self._fraction = 0.0
        self._shown = 0.0
        self._last = time.perf_counter()
        frame_clock().subscribe(self)
        self.update()

    def set_fraction(self, value: float) -> None:
        self._fraction = max(self._fraction, max(0.0, min(1.0, value)))
        frame_clock().subscribe(self)

    def stop(self) -> None:
        self._running = False
        self._fraction = 1.0
        frame_clock().subscribe(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        now = time.perf_counter()
        step = now - self._last
        self._last = now
        # Заполнение догоняет долю плавно, а не рывками по приходу событий.
        self._shown += (self._fraction - self._shown) * min(1.0, step * 6.0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        painter.setBrush(QColor(self.context.color("border")))
        painter.drawRoundedRect(rect, radius, radius)
        accent = QColor(self.context.color("accent"))
        if self._shown > 0.001:
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(0, 0, rect.width() * self._shown, rect.height()),
                                    radius, radius)
        if self._running:
            glint = QColor(255, 255, 255, 120)
            span = rect.width() * 0.18
            position = (now * 0.9 % 1.4 - 0.2) * rect.width()
            painter.setBrush(glint)
            painter.drawRoundedRect(QRectF(position, 0, span, rect.height()), radius, radius)
        painter.end()
        settled = abs(self._fraction - self._shown) < 0.002
        if not self._running and settled:
            frame_clock().unsubscribe(self)


class LeaderRow(QWidget):
    """Строка стратегии: место, название, кружки по сайтам, итог и «Применить»."""

    apply_requested = Signal(object)

    def __init__(self, context: AppContext, strategy: Strategy, targets: list[Target],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.strategy = strategy
        self.score: StrategyScore | None = None
        self._best = False
        self._current = False
        self._hover = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 8, 7)
        layout.setSpacing(10)

        self.rank = QLabel("", self)
        self.rank.setFixedWidth(22)
        self.rank.setObjectName("Faint")
        layout.addWidget(self.rank)

        self.title = ElidedLabel(strategy.title, self)
        self.title.setStyleSheet("font-weight: 600; background: transparent;")
        layout.addWidget(self.title, 1)

        self.tag = Badge("", "accent", self)
        self.tag.setVisible(False)
        layout.addWidget(self.tag)

        self.dots = ResultDots(context, targets, self)
        layout.addWidget(self.dots)

        self.count = QLabel("…", self)
        self.count.setFixedWidth(40)
        self.count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count.setStyleSheet("font-weight: 650; background: transparent;")
        layout.addWidget(self.count)

        self.latency = QLabel("", self)
        self.latency.setObjectName("Faint")
        self.latency.setFixedWidth(62)
        self.latency.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.latency)

        # Кнопка появляется только по итогу и только у тех, кто что-то открыл:
        # пока идёт проверка, применять нечего — движок занят ею.
        self.apply = Button("Применить", variant="soft", size="small", parent=self)
        self.apply.clicked.connect(lambda: self.apply_requested.emit(self.strategy))
        self.apply.setFixedWidth(108)
        layout.addWidget(self.apply)
        self.apply.setVisible(False)
        self.slot = QWidget(self)          # держит место, пока кнопки нет
        self.slot.setFixedWidth(108)
        layout.addWidget(self.slot)

    # --- состояние --------------------------------------------------------

    def set_score(self, score: StrategyScore) -> None:
        self.score = score
        if score.error:
            self.dots.stop_waiting()
            self.count.setText("—")
            self.count.setToolTip(score.error)
            self.latency.setText("не запустилась")
            self.latency.setToolTip(score.error)
            return
        self.dots.set_results(score.results)
        self.count.setText(f"{score.passed}/{score.total}")
        self._paint_count()
        # В проверке разом задержки выше обычных: два десятка рукопожатий
        # идут одновременно. Поэтому «≈» — это ориентир, а не замер.
        self.latency.setText(f"≈{score.latency_ms:.0f} мс" if score.latency_ms else "")
        if not self.locked:
            self.unlock()

    def _paint_count(self) -> None:
        """Цвет счёта — в стиле виджета, поэтому при смене темы красим заново."""
        score = self.score
        if score is None or score.error:
            return
        token = ("success" if score.is_perfect else "warning" if score.passed else "danger")
        self.count.setStyleSheet(
            f"font-weight: 650; background: transparent; color: {self.context.color(token)};"
        )

    def apply_theme(self) -> None:
        self._paint_count()
        self.dots.update()
        self.update()

    locked = True   # пока идёт проверка, применять нечего: движок занят ею

    def unlock(self) -> None:
        self.locked = False
        score = self.score
        useful = bool(score and score.passed and not score.error)
        self.apply.setVisible(useful)
        self.slot.setVisible(not useful)

    def stop_waiting(self) -> None:
        if self.score is None:
            self.count.setText("—")
        self.dots.stop_waiting()

    def set_rank(self, rank: int | None) -> None:
        self.rank.setText(f"{rank}" if rank else "")

    def set_marks(self, best: bool, current: bool) -> None:
        self._best, self._current = best, current
        if best:
            self.tag.update_state("лучшая", "ok")
        elif current:
            self.tag.update_state("сейчас", "neutral")
        self.tag.setVisible(best or current)
        self.update()

    # --- оформление ---------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not (self._best or self._hover):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        token = "success_bg" if self._best else "hover"
        painter.setBrush(QColor(self.context.color(token, self.context.color("hover"))))
        painter.drawRoundedRect(rect, 9, 9)
        if self._best:
            painter.setBrush(QColor(self.context.color("success")))
            painter.drawRoundedRect(QRectF(rect.x() + 1, rect.y() + 7, 3, rect.height() - 14),
                                    1.5, 1.5)
        painter.end()


class Leaderboard(QWidget):
    """Все стратегии разом: сначала в порядке списка, после — по результату."""

    apply_requested = Signal(object)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._rows: dict[str, LeaderRow] = {}
        self._order: list[str] = []
        self._expanded = False
        self._enabled = True
        self._animations: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.caption = QLabel("", self)
        self.caption.setObjectName("Faint")
        self.caption.setVisible(False)
        outer.addWidget(self.caption)

        self.rows_host = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        outer.addWidget(self.rows_host)

        self.more = Button("", variant="ghost", parent=self)
        self.more.clicked.connect(self._toggle_more)
        self.more.setVisible(False)
        outer.addWidget(self.more, 0, Qt.AlignmentFlag.AlignLeft)

    # --- во время проверки --------------------------------------------------

    def start(self, strategies: list[Strategy], targets: list[Target]) -> None:
        """Строки в порядке списка, кружки пульсируют — ждём ответов."""
        self.clear()
        self.caption.setText(
            "Сайты по порядку: " + ", ".join(target.key or target.label for target in targets)
        )
        self.caption.setVisible(bool(targets))
        for index, strategy in enumerate(strategies):
            row = LeaderRow(self.context, strategy, targets, self.rows_host)
            row.apply.setEnabled(self._enabled)
            row.apply_requested.connect(self.apply_requested.emit)
            self.rows_layout.addWidget(row)
            self._rows[strategy.id] = row
            self._order.append(strategy.id)
            # Строки появляются волной сверху вниз.
            fade_in(row, 220, delay=min(index, 16) * 18, keep=self._animations)
        self.more.setVisible(False)
        del self._animations[:-40]

    def update_score(self, score: StrategyScore) -> None:
        row = self._rows.get(score.strategy.id)
        if row is not None:
            row.set_score(score)

    def stop_waiting(self) -> None:
        for row in self._rows.values():
            row.stop_waiting()
            row.unlock()

    # --- после проверки -----------------------------------------------------

    def finish(self, scores: list[StrategyScore], current_id: str) -> None:
        """Пересортировать по результату: места проявляются сверху вниз.

        Переход-снимком тут не годится — высота таблицы меняется, когда
        лишние строки сворачиваются, а снимок размера не меняет.
        """
        # Итог — источник правды: строка, чьё событие не дошло, иначе
        # осталась бы без места и кнопки. Повторный счёт кружки не дёргает.
        for score in scores:
            row = self._rows.get(score.strategy.id)
            if row is not None and row.score is not score:
                row.set_score(score)
        ranked = [score.strategy.id for score in scores if score.strategy.id in self._rows]
        ranked += [key for key in self._order if key not in ranked]
        best = scores[0].strategy.id if scores and scores[0].passed and not scores[0].error \
            else ""

        self.rows_host.setUpdatesEnabled(False)
        try:
            for key in self._order:
                self.rows_layout.removeWidget(self._rows[key])
            self._order = ranked
            for position, key in enumerate(ranked, start=1):
                row = self._rows[key]
                self.rows_layout.addWidget(row)
                row.set_rank(position if row.score is not None and not row.score.error else None)
                row.set_marks(key == best, key == current_id)
                row.stop_waiting()
                row.unlock()
            self._expanded = False
            self._apply_visibility()
            self.rows_layout.activate()
        finally:
            self.rows_host.setUpdatesEnabled(True)
        for position, key in enumerate(ranked[:VISIBLE_ROWS]):
            fade_in(self._rows[key], 240, delay=position * 45, keep=self._animations)
        del self._animations[:-40]

    def clear(self) -> None:
        for row in self._rows.values():
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows.clear()
        self._order = []
        self.more.setVisible(False)
        self.caption.setVisible(False)

    def _apply_visibility(self) -> None:
        for position, key in enumerate(self._order):
            self._rows[key].setVisible(self._expanded or position < VISIBLE_ROWS)
        extra = len(self._order) - VISIBLE_ROWS
        self.more.setVisible(extra > 0)
        self.more.setText("Свернуть" if self._expanded else f"Показать остальные ({extra})")

    def _toggle_more(self) -> None:
        self._expanded = not self._expanded
        self._apply_visibility()
        if self._expanded:
            for position, key in enumerate(self._order[VISIBLE_ROWS:]):
                fade_in(self._rows[key], 200, delay=position * 25, keep=self._animations)
            del self._animations[:-40]

    def apply_theme(self) -> None:
        for row in self._rows.values():
            row.apply_theme()

    def set_enabled(self, enabled: bool) -> None:
        """Кнопки «Применить» — только пока движок свободен (не идёт запуск)."""
        self._enabled = enabled
        for row in self._rows.values():
            row.apply.setEnabled(enabled)


# =========================================================================
# Грядка стратегий
# =========================================================================


class _Sprout:
    def __init__(self, strategy: Strategy, index: int) -> None:
        self.strategy = strategy
        self.index = index
        self.score: StrategyScore | None = None
        self.grown_at = 0.0
        self.x = 0.0            # текущее положение (доли ширины ряда)
        self.x_from = 0.0
        self.x_to = 0.0
        self.rank: int | None = None
        self.best = False
        self.current = False


class SproutBed(QWidget):
    """Все стратегии — ростки на одной грядке.

    Чем выше росток, тем больше заблокированных сайтов открыла стратегия.
    Лучшая расцветает глиняным цветком, полный счёт — светлым, половина —
    маленьким, остальные остаются бутонами, а ничего не открывшие — семенами.
    Пока идёт проверка, ростки ждут и чуть мерцают; щелчок по выросшему
    ростку применяет стратегию.
    """

    apply_requested = Signal(object)

    HEIGHT = 250
    GROUND = 196

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.ink import LEAF, parse_path

        self.context = context
        self._items: list[_Sprout] = []
        self._testing = False
        self._finished = False
        self._locked = False
        self._hover = -1
        self._reordered = 0.0
        self._leaf = parse_path(LEAF)
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        context.theme_changed.connect(self.update)

    # --- данные ---------------------------------------------------------

    def preview(self, strategies: list[Strategy], current_id: str = "") -> None:
        """До проверки — грядка с семенами: столько, сколько стратегий."""
        if self._testing or self._finished:
            return
        self._items = [_Sprout(item, index) for index, item in enumerate(strategies)]
        for sprout in self._items:
            sprout.current = sprout.strategy.id == current_id
        self._place(instant=True)
        self.update()

    def start(self, strategies: list[Strategy], targets: list[Target]) -> None:
        self._items = [_Sprout(item, index) for index, item in enumerate(strategies)]
        self._testing = True
        self._finished = False
        self._place(instant=True)
        frame_clock().subscribe(self)
        self.update()

    def update_score(self, score: StrategyScore) -> None:
        for sprout in self._items:
            if sprout.strategy.id == score.strategy.id:
                first = sprout.score is None
                sprout.score = score
                if first:
                    sprout.grown_at = time.perf_counter()
        frame_clock().subscribe(self)

    def stop_waiting(self) -> None:
        self._testing = False
        self.update()

    def finish(self, scores: list[StrategyScore], current_id: str) -> None:
        self._testing = False
        self._finished = True
        by_id = {score.strategy.id: score for score in scores}
        for sprout in self._items:
            score = by_id.get(sprout.strategy.id)
            if score is not None and sprout.score is not score:
                if sprout.score is None:
                    sprout.grown_at = time.perf_counter()
                sprout.score = score
        order = [score.strategy.id for score in scores]
        position = {key: index for index, key in enumerate(order)}
        self._items.sort(key=lambda s: position.get(s.strategy.id, len(order) + s.index))
        best = scores[0].strategy.id if scores and scores[0].passed and not scores[0].error else ""
        for rank, sprout in enumerate(self._items, start=1):
            ok = sprout.score is not None and not sprout.score.error
            sprout.rank = rank if ok else None
            sprout.best = sprout.strategy.id == best
            sprout.current = sprout.strategy.id == current_id
        self._place(instant=False)
        frame_clock().subscribe(self)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked

    def _place(self, instant: bool) -> None:
        count = max(1, len(self._items))
        now = time.perf_counter()
        for index, sprout in enumerate(self._items):
            target = (index + 0.5) / count
            if instant:
                sprout.x = sprout.x_from = sprout.x_to = target
            else:
                sprout.x_from = sprout.x
                sprout.x_to = target
        self._reordered = now

    # --- кадры ----------------------------------------------------------

    def _busy(self, now: float) -> bool:
        if self._testing:
            return True
        if now - self._reordered < 1.2:
            return True
        return any(sprout.score is not None and now - sprout.grown_at < 2.0
                   for sprout in self._items)

    def frame_divider(self) -> int:
        return 1 if self._busy(time.perf_counter()) else 2

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        frame_clock().unsubscribe(self)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        from app.ui.ink import motion_level

        if motion_level() != "off":
            frame_clock().subscribe(self)

    # --- мышь -----------------------------------------------------------

    def _column(self) -> tuple[float, float]:
        left, right = 30.0, self.width() - 30.0
        return left, max(1.0, right - left)

    def _index_at(self, x: float) -> int:
        if not self._items:
            return -1
        left, width = self._column()
        step = width / len(self._items)
        for index, sprout in enumerate(self._items):
            cx = left + sprout.x * width
            if abs(x - cx) <= step / 2:
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(event.position().x())
        if index != self._hover:
            self._hover = index
            sprout = self._items[index] if index >= 0 else None
            usable = bool(sprout and sprout.score and sprout.score.passed
                          and not sprout.score.error and not self._locked and not self._testing)
            self.setCursor(Qt.CursorShape.PointingHandCursor if usable
                           else Qt.CursorShape.ArrowCursor)
            self.setToolTip(self._tooltip(sprout) if sprout else "")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def _tooltip(self, sprout: _Sprout) -> str:
        score = sprout.score
        title = sprout.strategy.title
        if score is None:
            return f"{title} — ждём проверки" if self._testing else \
                f"{title} — ещё не проверялась"
        if score.error:
            return f"{title} — не запустилась: {score.error}"
        text = f"{title} — открыла {score.passed} из {score.total}"
        if score.latency_ms:
            text += f", ≈{score.latency_ms:.0f} мс"
        if score.passed and not self._testing and not self._locked:
            text += ". Щёлкните, чтобы применить."
        return text

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self._testing \
                and not self._locked:
            index = self._index_at(event.position().x())
            if index >= 0:
                score = self._items[index].score
                if score and score.passed and not score.error:
                    self.apply_requested.emit(self._items[index].strategy)
        super().mouseReleaseEvent(event)

    # --- рисование ------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath, QPen

        from app.ui import fonts
        from app.ui.ink import expo_out, inout

        c = self.context
        now = time.perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left, width = self._column()
        ground = float(self.GROUND)
        top_room = 50.0
        max_h = ground - top_room
        ink = QColor(c.color("ink"))

        # Направляющие «8 из 8» и «половина».
        total = next((s.score.total for s in self._items if s.score and s.score.total), 8)
        guide = QPen(QColor(c.color("decor")))
        guide.setWidthF(1.0)
        guide.setDashPattern([2, 5])
        painter.setFont(fonts.mono(9, 500, 0.08))
        for share, label in ((1.0, f"{total} ИЗ {total}"), (0.5, f"{total // 2} ИЗ {total}")):
            y = ground - (22 + share * (max_h - 22))
            painter.setPen(guide)
            painter.drawLine(QPointF(left - 6, y), QPointF(left + width + 6, y))
            painter.setPen(QColor(c.color("ink3")))
            metrics = painter.fontMetrics()
            painter.drawText(QPointF(left + width + 6 - metrics.horizontalAdvance(label), y - 5),
                             label)

        # Земля.
        soil = QPainterPath()
        soil.moveTo(left - 20, ground - 2)
        soil.cubicTo(left + width * 0.25, ground - 6, left + width * 0.55, ground + 4,
                     left + width + 20, ground - 3)
        soil.lineTo(left + width + 20, ground + 16)
        soil.lineTo(left - 20, ground + 16)
        soil.closeSubpath()
        painter.fillPath(soil, QColor(c.color("soil")))
        line = QPainterPath()
        line.moveTo(left - 20, ground)
        line.cubicTo(left + width * 0.25, ground - 4, left + width * 0.55, ground + 5,
                     left + width + 20, ground - 1)
        pen = QPen(ink)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(line)

        reorder = expo_out((now - self._reordered) / 0.9)
        step = width / max(1, len(self._items))
        for index, sprout in enumerate(self._items):
            sprout.x = sprout.x_from + (sprout.x_to - sprout.x_from) * reorder
            x = left + sprout.x * width
            if index == self._hover:
                painter.setPen(Qt.PenStyle.NoPen)
                hover = QColor(c.color("card2"))
                painter.setBrush(hover)
                painter.drawRoundedRect(QRectF(x - step / 2 + 2, 6, step - 4, ground + 32), 8, 8)
            self._paint_sprout(painter, sprout, x, ground, max_h, now, ink)
            # Номер места под землёй.
            painter.setFont(fonts.mono(9, 500, 0.08))
            painter.setPen(QColor(c.color("ink3")))
            label = str(sprout.rank if sprout.rank else index + 1) if (
                sprout.rank or not self._finished) else "·"
            metrics = painter.fontMetrics()
            painter.drawText(QPointF(x - metrics.horizontalAdvance(label) / 2, ground + 32), label)
            if sprout.current:
                self._tag(painter, x, ground + 40, "СЕЙЧАС", QColor(c.color("manilla")),
                          below=True)
            if sprout.best and sprout.score:
                h = self._height(sprout, max_h)
                grow = inout((now - sprout.grown_at) / 1.1)
                y = ground - h * grow - 26
                self._tag(painter, x, max(20.0, y),
                          f"{sprout.strategy.title.upper()} · ЛУЧШАЯ", QColor(c.color("clay")))
        painter.end()
        # Выросшие ростки покачиваются всегда; грядке с одними семенами
        # кадры не нужны.
        growing = any(sprout.score is not None and sprout.score.passed
                      for sprout in self._items)
        if not growing and not self._busy(now):
            frame_clock().unsubscribe(self)

    def _height(self, sprout: _Sprout, max_h: float) -> float:
        score = sprout.score
        if score is None or score.error or not score.passed or not score.total:
            return 0.0
        return 22 + (score.passed / score.total) * (max_h - 22)

    def _paint_sprout(self, painter, sprout: _Sprout, x: float, ground: float, max_h: float,
                      now: float, ink: QColor) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath, QPen, QTransform

        from app.ui.ink import inout, quart_out, sine_wave

        c = self.context
        score = sprout.score
        pen = QPen(ink)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        if score is None:
            # Ждём ответа: семечко с крошечным ростком, который мерцает.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("kraft")))
            painter.drawEllipse(QPointF(x, ground + 1), 4.5, 3.2)
            if self._testing:
                alpha = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(now * 4.0 - sprout.index * 0.6))
                pen.setColor(QColor(c.color("olive")))
                pen.setWidthF(1.6)
                painter.setOpacity(alpha)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, ground - 1), QPointF(x + 0.5, ground - 9))
                painter.setOpacity(1.0)
            return
        if score.error or not score.passed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("kraft" if not score.error else "pencil")))
            painter.drawEllipse(QPointF(x, ground + 1), 4.5, 3.2)
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc = QPainterPath()
            arc.moveTo(x - 4.5, ground + 1)
            arc.cubicTo(x - 3, ground - 3, x + 3, ground - 3, x + 4.5, ground + 1)
            painter.drawPath(arc)
            return

        h = self._height(sprout, max_h)
        t = now - sprout.grown_at
        grow = inout(t / 1.1)
        if grow <= 0.0:
            return
        top = ground - h
        stem = QPainterPath()
        stem.moveTo(x, ground)
        stem.cubicTo(x - 5, ground - h * 0.35, x + 6, ground - h * 0.7, x, top)

        painter.save()
        # Покачивание — от основания, у каждого ростка своё.
        angle = 2.6 * sine_wave(now, 3.6 + (sprout.index % 5) * 0.35, sprout.index * 0.37)
        transform = QTransform()
        transform.translate(x, ground)
        transform.rotate(angle * min(1.0, grow))
        transform.translate(-x, -ground)
        painter.setTransform(transform, True)

        # Стебель прорисовывается снизу вверх.
        points = [stem.pointAtPercent(k / 24 * grow) for k in range(25)]
        pen.setWidthF(2.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)

        # Листья распускаются по очереди.
        leaves = max(1, score.passed // 2)
        olive = QColor(c.color("olive"))
        for k in range(leaves):
            share = (k + 1) / (leaves + 1)
            appear = quart_out((t - 0.35 - 0.12 * k) / 0.7)
            if appear <= 0.0:
                continue
            fy = ground - h * share
            left_side = (k + sprout.index) % 2 == 0
            leaf = QTransform()
            leaf.translate(x + (-1 if left_side else 1), fy)
            leaf.rotate(205 if left_side else -28)
            leaf.scale(0.78 * (0.5 + 0.5 * appear), 0.78 * (0.5 + 0.5 * appear))
            painter.setOpacity(appear)
            painter.fillPath(leaf.map(self._leaf), olive)
        painter.setOpacity(1.0)

        # Цветок или бутон на верхушке.
        bloom = quart_out((t - 0.75) / 0.9)
        if bloom > 0.0:
            ratio = score.passed / max(1, score.total)
            painter.setOpacity(bloom)
            if ratio < 0.5:
                bud = QPainterPath()
                bud.moveTo(x, top - 9)
                bud.cubicTo(x + 5, top - 4, x + 4, top + 2, x, top + 1)
                bud.cubicTo(x - 4, top + 2, x - 5, top - 4, x, top - 9)
                painter.fillPath(bud, olive)
                pen.setWidthF(1.4)
                painter.setPen(pen)
                painter.drawPath(bud)
            else:
                if sprout.best:
                    r, petal, heart = 6.5, "clay", "manilla"
                elif score.passed == score.total:
                    r, petal, heart = 5.0, "manilla", "kraft"
                else:
                    r, petal, heart = 3.8, "kraft", "kraft"
                r *= 0.6 + 0.4 * bloom
                cy = top - r * 0.9
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c.color(petal)))
                for p in range(5):
                    a = -math.pi / 2 + p * 2 * math.pi / 5
                    painter.drawEllipse(QPointF(x + r * 1.1 * math.cos(a),
                                                cy + r * 1.1 * math.sin(a)), r, r)
                painter.setBrush(QColor(c.color(heart)))
                painter.drawEllipse(QPointF(x, cy), r * 0.55, r * 0.55)
                pen.setWidthF(1.3)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(x, cy), r * 0.55, r * 0.55)
            painter.setOpacity(1.0)
        painter.restore()

    def _tag(self, painter, x: float, y: float, text: str, fill: QColor,
             below: bool = False) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen

        from app.ui import fonts

        painter.setFont(fonts.mono(8.5, 600, 0.06))
        metrics = painter.fontMetrics()
        w = metrics.horizontalAdvance(text) + 14
        rect = QRectF(x - w / 2, y - (0 if below else 16), w, 16)
        rect.moveLeft(max(2.0, min(rect.left(), self.width() - w - 2)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRect(rect)
        if not below:
            pen = QPen(QColor(self.context.color("ink")))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() + 8))
        painter.setPen(QColor("#141413"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
