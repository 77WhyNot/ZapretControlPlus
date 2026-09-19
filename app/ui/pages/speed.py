"""Страница «Скорость»: замер интернета прямо в программе.

Меряем тем путём, которым трафик идёт прямо сейчас, — с обходом, через VPN
или напрямую. Так видно не «скорость тарифа», а скорость, которая реально
достаётся программам.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

from app.core import speedtest
from app.core.config import config
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Button,
    Card,
    Divider,
    StatItem,
    Worker,
    faint_label,
    section_label,
)

# Шкала логарифмическая: между 5 и 50 Мбит/с разница важнее, чем между
# 500 и 550, а линейная стрелка этого не показывает.
SCALE_MAX = 1000.0


class Gauge(QWidget):
    """Круговая шкала с цифрой посередине."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._value = 0.0
        self._caption = "Мбит/с"
        self._stage = "готов к замеру"
        self.setMinimumHeight(248)
        self.setMaximumHeight(300)
        self._animation = QPropertyAnimation(self, b"value", self)
        self._animation.setDuration(420)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    # --- свойство для анимации -------------------------------------------

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = max(value, 0.0)
        self.update()

    value = Property(float, get_value, set_value)

    def animate_to(self, value: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._value)
        self._animation.setEndValue(max(value, 0.0))
        self._animation.start()

    def set_stage(self, text: str, caption: str = "Мбит/с") -> None:
        self._stage = text
        self._caption = caption
        self.update()

    # --- рисование --------------------------------------------------------

    def _fraction(self) -> float:
        if self._value <= 0:
            return 0.0
        return min(math.log10(1 + self._value) / math.log10(1 + SCALE_MAX), 1.0)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Дуга должна целиком помещаться по высоте: снизу ещё подпись стадии.
        diameter = max(min(self.width() - 80, self.height() - 56), 90)
        rect = QRectF((self.width() - diameter) / 2, 12.0, diameter, diameter)
        start = 215 * 16
        span = 250 * 16

        pen = QPen(QColor(self.context.color("border")))
        pen.setWidthF(max(diameter / 16, 8))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, start, -span)

        pen.setColor(QColor(self.context.color("accent")))
        painter.setPen(pen)
        painter.drawArc(rect, start, -int(span * self._fraction()))

        painter.setPen(QColor(self.context.color("text")))
        font = QFont("Bahnschrift", max(int(diameter / 5.2), 16))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(rect.left(), rect.center().y() - diameter / 4,
                   rect.width(), diameter / 2.6),
            Qt.AlignmentFlag.AlignCenter, speedtest.format_speed(self._value),
        )

        painter.setPen(QColor(self.context.color("text_dim")))
        small = QFont()
        small.setPointSize(9)
        painter.setFont(small)
        painter.drawText(
            QRectF(rect.left(), rect.center().y() + diameter / 8, rect.width(), 22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._caption,
        )
        painter.drawText(
            QRectF(0, rect.bottom() - 4, self.width(), 26),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._stage,
        )
        painter.end()


class SpeedPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Скорость интернета",
            "Замер идёт тем же путём, которым сейчас ходит трафик: через обход, "
            "через VPN или напрямую. Ничего включать и выключать не нужно.",
            parent,
        )
        self._test: speedtest.SpeedTest | None = None
        self._worker: Worker | None = None
        self._peak = 0.0

        self._build_gauge()
        self._build_numbers()
        self._build_note()
        self._restore_last()
        self.apply_theme()

    # --- шкала ------------------------------------------------------------

    def _build_gauge(self) -> None:
        card = Card(padding=20, spacing=12)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(section_label("Замер"))
        head.addStretch(1)
        self.route_label = faint_label("", wrap=False)
        head.addWidget(self.route_label)
        card.add_layout(head)

        self.gauge = Gauge(self.context)
        card.add(self.gauge)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_run = Button("Замерить скорость", variant="primary")
        self.btn_run.clicked.connect(self.toggle)
        actions.addWidget(self.btn_run)
        actions.addStretch(1)
        card.add_layout(actions)

        self.body.addWidget(card)

    # --- цифры ------------------------------------------------------------

    def _build_numbers(self) -> None:
        card = Card(padding=18, spacing=12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(10)
        self.stat_down = StatItem("Загрузка", "—")
        self.stat_up = StatItem("Отдача", "—")
        self.stat_ping = StatItem("Задержка", "—")
        self.stat_jitter = StatItem("Разброс", "—")
        for column, item in enumerate(
            (self.stat_down, self.stat_up, self.stat_ping, self.stat_jitter)
        ):
            grid.addWidget(item, 0, column)
        grid.setColumnStretch(4, 1)
        card.add_layout(grid)

        card.add(Divider())
        self.verdict = QLabel("Нажмите «Замерить скорость» — это занимает около 20 секунд.")
        self.verdict.setWordWrap(True)
        card.add(self.verdict)

        self.source_label = faint_label("")
        card.add(self.source_label)

        self.body.addWidget(card)

    def _build_note(self) -> None:
        card = Card(padding=18, spacing=8)
        card.add(section_label("Что означают цифры"))
        card.add(faint_label(
            "Загрузка — с какой скоростью к вам приходят данные: видео, сайты, "
            "игры. Отдача — с какой скоростью уходят от вас: звонки, стримы, "
            "выгрузка файлов. Задержка — насколько быстро сервер отвечает, "
            "разброс — насколько ровно. Для игр важнее задержка, для видео — "
            "загрузка."
        ))
        card.add(faint_label(
            "Через VPN скорость всегда ниже прямого канала — трафик идёт через "
            "чужой сервер. Обход DPI на скорость почти не влияет: он правит "
            "только начало соединения."
        ))
        self.body.addWidget(card)

    # --- запуск -----------------------------------------------------------

    def toggle(self) -> None:
        if self._worker is not None and self._worker.busy():
            if self._test is not None:
                self._test.cancel()
            self.btn_run.setEnabled(False)
            self.gauge.set_stage("останавливаю…")
            return
        self.start_measure()

    def start_measure(self) -> None:
        if self._worker is not None and self._worker.busy():
            return
        self._peak = 0.0
        self.route_label.setText(speedtest.describe_route())
        self.gauge.animate_to(0.0)
        self.gauge.set_stage("измеряю задержку…", "мс")
        self.btn_run.setText("Остановить")
        self.stat_down.set_value("—")
        self.stat_up.set_value("—")
        self.stat_ping.set_value("—")
        self.stat_jitter.set_value("—")
        self.verdict.setText("Идёт замер. Не закрывайте программу и не качайте "
                             "ничего параллельно — иначе цифры будут ниже.")

        worker = Worker(self)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)

        from app.core.vpn.engine import vpn_engine

        test = speedtest.SpeedTest(
            proxy_url=vpn_engine.proxy_url(),
            on_progress=lambda stage, mbps: worker.progress.emit(
                stage, int(mbps * 100)
            ),
        )
        self._test = test
        self._worker = worker
        worker.run(test.run)

    def _on_progress(self, stage: str, packed: int) -> None:
        value = packed / 100
        if stage == speedtest.STAGE_PING:
            self.gauge.set_stage("измеряю задержку…", "мс")
            self.gauge.animate_to(value)
            self.stat_ping.set_value(f"{value:.0f} мс")
            return
        caption = "Мбит/с"
        if stage == speedtest.STAGE_DOWNLOAD:
            self.gauge.set_stage("загрузка…", caption)
            self.stat_down.set_value(f"{speedtest.format_speed(value)} Мбит/с")
        else:
            self.gauge.set_stage("отдача…", caption)
            self.stat_up.set_value(f"{speedtest.format_speed(value)} Мбит/с")
        self.gauge.animate_to(value)

    def _on_finished(self, result: speedtest.SpeedResult) -> None:
        self._finish_ui()
        self.gauge.animate_to(result.download_mbps)
        self.gauge.set_stage("замер готов", "Мбит/с")
        self.stat_down.set_value(
            f"{speedtest.format_speed(result.download_mbps)} Мбит/с"
        )
        self.stat_up.set_value(
            f"{speedtest.format_speed(result.upload_mbps)} Мбит/с"
            if result.upload_mbps else "—"
        )
        self.stat_ping.set_value(f"{result.ping_ms:.0f} мс" if result.ping_ms else "—")
        self.stat_jitter.set_value(
            f"{result.jitter_ms:.0f} мс" if result.ping_ms else "—"
        )

        text = speedtest.verdict(result)
        if result.notes:
            text += " " + " ".join(result.notes)
        self.verdict.setText(text)
        self.source_label.setText(
            f"Источник: {result.source or '—'} · путь: {result.route}"
        )

        config.set("speedtest_last", {
            "download": round(result.download_mbps, 2),
            "upload": round(result.upload_mbps, 2),
            "ping": round(result.ping_ms, 1),
            "jitter": round(result.jitter_ms, 1),
            "route": result.route,
            "time": int(time.time()),
        })
        if result.ok:
            self.context.ok(
                f"Скорость: {speedtest.format_speed(result.download_mbps)} Мбит/с"
            )
        else:
            self.context.warn("Замер не удался — сервер не ответил.")

    def _on_failed(self, message: str) -> None:
        self._finish_ui()
        self.gauge.set_stage("замер остановлен", "Мбит/с")
        if "отмен" in message.lower():
            self.context.warn("Замер остановлен.")
            self.verdict.setText("Замер остановлен.")
            return
        self.verdict.setText(message)
        self.context.error(f"Замер не удался: {message}")

    def _finish_ui(self) -> None:
        self.btn_run.setEnabled(True)
        self.btn_run.setText("Замерить ещё раз")
        self._test = None

    # --- прошлый результат -------------------------------------------------

    def _restore_last(self) -> None:
        saved = config.get("speedtest_last", {}) or {}
        if not isinstance(saved, dict) or not saved.get("download"):
            self.route_label.setText(speedtest.describe_route())
            return
        self.stat_down.set_value(
            f"{speedtest.format_speed(float(saved.get('download', 0)))} Мбит/с"
        )
        upload = float(saved.get("upload", 0) or 0)
        self.stat_up.set_value(
            f"{speedtest.format_speed(upload)} Мбит/с" if upload else "—"
        )
        ping = float(saved.get("ping", 0) or 0)
        self.stat_ping.set_value(f"{ping:.0f} мс" if ping else "—")
        jitter = float(saved.get("jitter", 0) or 0)
        self.stat_jitter.set_value(f"{jitter:.0f} мс" if ping else "—")
        self.gauge.set_value(float(saved.get("download", 0)))
        self.gauge.set_stage("прошлый замер", "Мбит/с")

        when = time.localtime(int(saved.get("time", 0) or 0))
        self.source_label.setText(
            f"Прошлый замер: {time.strftime('%d.%m %H:%M', when)} · "
            f"путь: {saved.get('route', '—')}"
        )
        self.route_label.setText(speedtest.describe_route())

    # --- страница ---------------------------------------------------------

    def on_activate(self) -> None:
        self.route_label.setText(speedtest.describe_route())

    def apply_theme(self) -> None:
        self.gauge.update()
