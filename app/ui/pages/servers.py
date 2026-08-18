"""Страница «Серверы»: подписка и табло серверов с задержкой."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.core.config import config
from app.core.vpn import probe, subscription
from app.core.vpn.engine import VpnError, vpn_engine
from app.core.vpn.links import Server
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Divider,
    Spinner,
    Worker,
    faint_label,
    section_label,
)

COLUMNS = (
    ("Направление", 3),
    ("Задержка", 1),
    ("Качество", 1),
    ("Протокол", 2),
    ("Статус", 1),
)


class SignalBars(QWidget):
    """Четыре столбика: чем меньше задержка, тем их больше."""

    def __init__(self, context: AppContext, latency: int = -1,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.latency = latency
        self.setFixedSize(30, 16)

    def set_latency(self, latency: int) -> None:
        self.latency = latency
        self.update()

    def _filled(self) -> int:
        if self.latency < 0:
            return 0
        if self.latency <= 60:
            return 4
        if self.latency <= 110:
            return 3
        if self.latency <= 200:
            return 2
        return 1

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        filled = self._filled()
        colors = {
            "good": self.context.color("success"),
            "fair": self.context.color("warning"),
            "poor": self.context.color("danger"),
            "dead": self.context.color("text_faint"),
        }
        active = QColor(colors[probe.quality(self.latency)])
        idle = QColor(self.context.color("border_strong"))

        for index in range(4):
            height = 5 + index * 3
            painter.setBrush(active if index < filled else idle)
            painter.drawRoundedRect(index * 8, 16 - height, 5, height, 1.5, 1.5)
        painter.end()


class ServerRow(QWidget):
    """Строка табло."""

    chosen = Signal(str)

    def __init__(self, context: AppContext, server: Server, latency: int,
                 active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.server = server
        self.latency = latency
        self.active = active
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self.name = QLabel(server.name)
        self.name.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.name, COLUMNS[0][1])

        self.delay = QLabel(self._delay_text())
        self.delay.setProperty("role", "mono")
        layout.addWidget(self.delay, COLUMNS[1][1])

        self.bars = SignalBars(context, latency)
        bars_box = QHBoxLayout()
        bars_box.setContentsMargins(0, 0, 0, 0)
        bars_box.addWidget(self.bars)
        bars_box.addStretch(1)
        container = QWidget()
        container.setLayout(bars_box)
        layout.addWidget(container, COLUMNS[2][1])

        self.protocol = faint_label(server.transport_label, wrap=False)
        layout.addWidget(self.protocol, COLUMNS[3][1])

        self.status = Badge("в работе" if active else "готов",
                            "accent" if active else "neutral")
        layout.addWidget(self.status, COLUMNS[4][1])

        self.apply_theme()

    def _delay_text(self) -> str:
        return f"{self.latency} мс" if self.latency >= 0 else "— мс"

    def set_latency(self, latency: int) -> None:
        self.latency = latency
        self.delay.setText(self._delay_text())
        self.bars.set_latency(latency)
        self.apply_theme()

    def set_active(self, active: bool) -> None:
        self.active = active
        self.status.update_state("в работе" if active else "готов",
                                 "accent" if active else "neutral")
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = {
            "good": self.context.color("success"),
            "fair": self.context.color("warning"),
            "poor": self.context.color("danger"),
            "dead": self.context.color("text_faint"),
        }
        self.delay.setStyleSheet(
            f"color: {colors[probe.quality(self.latency)]}; font-weight: 600;"
        )
        if self.active:
            lane = self.context.color("lane_vpn")
            self.setStyleSheet(
                f"background: {self.context.color('lane_vpn_soft')}; "
                f"border-left: 3px solid {lane};"
            )
        else:
            self.setStyleSheet("background: transparent; border-left: 3px solid transparent;")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.server.name)
        super().mouseReleaseEvent(event)


class ServersPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Серверы",
            "Список приходит из вашей подписки. Ссылка хранится только на этом "
            "компьютере и никуда не отправляется.",
        )
        self._servers: list[Server] = []
        self._info = subscription.SubscriptionInfo()
        self._rows: list[ServerRow] = []
        self._latency: dict[str, int] = {}

        self._build_subscription()
        self._build_board()
        self.apply_theme()
        self._load_cached()

    # --- подписка --------------------------------------------------------

    def _build_subscription(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Подписка"))
        header.addStretch(1)
        self.sub_badge = Badge("не настроена", "neutral")
        header.addWidget(self.sub_badge)
        card.add_layout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.url_input = QLineEdit(subscription.subscription_url())
        self.url_input.setPlaceholderText(
            "https://… — ссылка-подписка, либо ключ vless:// целиком"
        )
        self.url_input.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self.url_input, 1)

        self.btn_show = Button("Показать", variant="ghost")
        self.btn_show.setCheckable(True)
        self.btn_show.clicked.connect(self._toggle_url_visibility)
        row.addWidget(self.btn_show)

        self.sub_spinner = Spinner(16, self.context.color("accent"))
        row.addWidget(self.sub_spinner)

        self.btn_update = Button("Обновить", variant="primary")
        self.btn_update.clicked.connect(self.update_subscription)
        row.addWidget(self.btn_update)
        card.add_layout(row)

        self.quota_bar = QProgressBar()
        self.quota_bar.setVisible(False)
        card.add(self.quota_bar)

        self.sub_details = faint_label(
            "Вставьте ссылку из личного кабинета и нажмите «Обновить»."
        )
        card.add(self.sub_details)

        self.body.addWidget(card)

    def _toggle_url_visibility(self) -> None:
        visible = self.btn_show.isChecked()
        self.url_input.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.btn_show.setText("Скрыть" if visible else "Показать")

    def update_subscription(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self.context.warn("Сначала вставьте ссылку на подписку.")
            return
        subscription.set_subscription_url(url)
        self.btn_update.setEnabled(False)
        self.sub_spinner.start()
        self.sub_details.setText("Загружаем список серверов…")

        worker = Worker(self)
        worker.finished.connect(self._subscription_loaded)
        worker.failed.connect(self._subscription_failed)
        worker.run(subscription.fetch, url)
        self._sub_worker = worker

    def _subscription_failed(self, message: str) -> None:
        self.btn_update.setEnabled(True)
        self.sub_spinner.stop()
        self.sub_badge.update_state("ошибка", "error")
        self.sub_details.setText(message)
        self.context.error(message)

    def _subscription_loaded(self, payload) -> None:
        servers, info = payload
        self.btn_update.setEnabled(True)
        self.sub_spinner.stop()
        self._servers, self._info = servers, info
        self._render_subscription()
        self._rebuild_board()
        self.context.ok(f"Загружено серверов: {len(servers)}")
        self.context.servers_changed.emit()
        self.measure_all()

    def _load_cached(self) -> None:
        servers, info = subscription.load_cached()
        if servers:
            self._servers, self._info = servers, info
            self._render_subscription()
            self._rebuild_board()

    def _render_subscription(self) -> None:
        info = self._info
        if not self._servers:
            self.sub_badge.update_state("не настроена", "neutral")
            return

        days = info.days_left
        if days is None:
            self.sub_badge.update_state("активна", "ok")
        elif days <= 3:
            self.sub_badge.update_state(f"осталось {days} дн.", "error")
        elif days <= 10:
            self.sub_badge.update_state(f"осталось {days} дн.", "warn")
        else:
            self.sub_badge.update_state("активна", "ok")

        parts = [f"Серверов: {len(self._servers)}"]
        if info.title:
            parts.insert(0, info.title)
        if info.has_quota:
            used = subscription.format_bytes(info.used)
            total = subscription.format_bytes(info.total)
            parts.append(f"трафик {used} из {total}")
            self.quota_bar.setVisible(True)
            self.quota_bar.setRange(0, 100)
            self.quota_bar.setValue(int(info.used_ratio * 100))
        else:
            self.quota_bar.setVisible(False)
        parts.append(f"действует до {info.expire_label}")
        self.sub_details.setText(" · ".join(parts))

    # --- табло -----------------------------------------------------------

    def _build_board(self) -> None:
        card = Card(padding=18, spacing=10)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Табло серверов"))
        header.addStretch(1)
        self.board_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.board_spinner)

        self.btn_best = Button("Выбрать лучший", variant="soft")
        self.btn_best.clicked.connect(self._choose_best)
        header.addWidget(self.btn_best)

        self.btn_measure = Button("Проверить задержку")
        self.btn_measure.clicked.connect(self.measure_all)
        header.addWidget(self.btn_measure)
        card.add_layout(header)

        head = QHBoxLayout()
        head.setContentsMargins(12, 0, 12, 0)
        head.setSpacing(12)
        for title, stretch in COLUMNS:
            label = QLabel(title.upper())
            label.setStyleSheet(
                f"color: {self.context.color('text_faint')}; font-size: 10.5px; "
                "letter-spacing: 1.4px; font-weight: 600;"
            )
            head.addWidget(label, stretch)
        card.add_layout(head)
        card.add(Divider())

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        card.add(self.rows_host)

        self.board_empty = faint_label(
            "Серверов пока нет. Добавьте ссылку-подписку выше."
        )
        card.add(self.board_empty)

        self.body.addWidget(card)

    def _rebuild_board(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []

        active = str(config.get("vpn_selected_server", ""))
        for index, server in enumerate(self._servers):
            if index:
                self.rows_layout.addWidget(Divider())
            row = ServerRow(
                self.context, server,
                self._latency.get(server.name, -1),
                server.name == active,
            )
            row.chosen.connect(self._select_server)
            self.rows_layout.addWidget(row)
            self._rows.append(row)

        self.board_empty.setVisible(not self._rows)
        self.rows_host.setVisible(bool(self._rows))

    def _select_server(self, name: str) -> None:
        config.set("vpn_selected_server", name)
        for row in self._rows:
            row.set_active(row.server.name == name)

        if vpn_engine.status().running:
            try:
                vpn_engine.switch_server(name)
                self.context.ok(f"Активный сервер: «{name}»")
            except VpnError as exc:
                self.context.error(str(exc))
        else:
            self.context.ok(f"Выбран сервер «{name}»")
        self.context.servers_changed.emit()

    def measure_all(self) -> None:
        if not self._servers:
            return
        self.btn_measure.setEnabled(False)
        self.board_spinner.start()

        running = vpn_engine.status().running
        servers = list(self._servers)

        def job() -> dict[str, int]:
            if running:
                # Движок меряет полный путь через прокси — это честнее.
                return {
                    server.name: vpn_engine.measure_delay(server.name)
                    for server in servers
                }
            return probe.measure_all(servers)

        worker = Worker(self)
        worker.finished.connect(self._latency_ready)
        worker.failed.connect(self._latency_failed)
        worker.run(job)
        self._probe_worker = worker

    def _latency_failed(self, message: str) -> None:
        self.btn_measure.setEnabled(True)
        self.board_spinner.stop()
        self.context.error(f"Не удалось измерить задержку: {message}")

    def _latency_ready(self, result) -> None:
        self.btn_measure.setEnabled(True)
        self.board_spinner.stop()
        self._latency = dict(result)
        for row in self._rows:
            row.set_latency(self._latency.get(row.server.name, -1))

        alive = [value for value in self._latency.values() if value >= 0]
        if not alive:
            self.context.warn(
                "Ни один сервер не ответил. Проверьте интернет или обновите подписку."
            )
        else:
            self.context.ok(f"Ответили серверов: {len(alive)} из {len(self._latency)}")

    def _choose_best(self) -> None:
        alive = {name: value for name, value in self._latency.items() if value >= 0}
        if not alive:
            self.context.warn("Сначала проверьте задержку.")
            return
        best = min(alive, key=alive.get)
        self._select_server(best)

    # --- страница --------------------------------------------------------

    def servers(self) -> list[Server]:
        return list(self._servers)

    def on_activate(self) -> None:
        if not self._servers:
            self._load_cached()

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.sub_spinner.set_color(accent)
        self.board_spinner.set_color(accent)
        for row in self._rows:
            row.apply_theme()
