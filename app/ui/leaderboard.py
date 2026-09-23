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
