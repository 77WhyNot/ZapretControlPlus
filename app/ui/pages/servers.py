"""Вкладка «VPN»: выключатель, способ подключения, подписка и табло серверов."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import config
from app.core.vpn import config as vpn_config
from app.core.vpn import probe, subscription
from app.core.vpn.engine import VpnError, vpn_engine
from app.core.vpn.links import Server
from app.ui import vpn_actions
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.widgets import (
    MonoLabel,
    StatusChip,
    IconLabel,
    clear_layout,
    Button,
    Card,
    Spinner,
    Switch,
    Worker,
    faint_label,
    section_label,
)

# Очертания островов на табло: у каждого берега свой (из макета).
ISLANDS = (
    "M6 16 C 8 9, 18 7, 26 10 C 34 12, 38 15, 34 18 Z",
    "M8 17 C 10 8, 22 5, 30 9 C 38 12, 38 17, 30 18 Z",
    "M12 17 C 12 7, 20 3, 26 6 C 32 9, 34 15, 28 18 Z",
    "M5 17 C 9 11, 15 10, 20 12 C 26 8, 36 10, 38 17 Z",
    "M14 18 C 10 12, 18 6, 24 7 C 30 8, 32 14, 26 18 Z",
)
WAVE = "q4 -5 8 0 q4 5 8 0"


def wave_count(latency: int) -> int:
    """Сколько волн из четырёх «спокойны»: чем меньше задержка, тем больше."""
    if latency < 0:
        return 0
    if latency <= 60:
        return 4
    if latency <= 110:
        return 3
    if latency <= 200:
        return 2
    return 1


class ServerRow(QWidget):
    """Строка «Табло берегов»: остров, страна, задержка, волнение, протокол."""

    chosen = Signal(str)

    def __init__(self, context: AppContext, server: Server, latency: int,
                 active: bool, index: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.ink import parse_path

        self.context = context
        self.server = server
        self.latency = latency
        self.active = active
        self._hover = False
        self._island = parse_path(ISLANDS[index % len(ISLANDS)])
        self._waves = parse_path("M2 20 q4 -3 8 0 q4 3 8 0 M26 21 q4 -3 8 0 q4 3 8 0")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setToolTip(f"{server.name} · {server.endpoint}")

    def set_latency(self, latency: int) -> None:
        self.latency = latency
        self.update()

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def apply_theme(self) -> None:
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.chosen.emit(self.server.name)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen

        from app.ui import fonts
        from app.ui.ink import parse_path
        from app.ui.naming import server_code, server_place

        c = self.context
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self.active or self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("bg" if self.active else "card2")))
            painter.drawRoundedRect(rect, 10, 10)
            if self.active:
                pen = QPen(QColor(c.color("border_strong")))
                pen.setWidthF(1.0)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        width = self.width()
        compact = width < 720
        x = 10.0
        cy = rect.center().y()
        # Остров.
        painter.save()
        painter.translate(x, cy - 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.color("kraft" if self.active else "pencil")))
        painter.drawPath(self._island)
        pen = QPen(QColor(c.color("decor")))
        pen.setWidthF(1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._waves)
        painter.restore()
        x += 46 + 14

        # Код и название.
        right_cols = (124 + 90 + (0 if compact else 130) + 118 + 14 * 3)
        name_w = max(80.0, width - x - right_cols - 10)
        painter.setFont(fonts.mono(10.5, 500, 0.1))
        painter.setPen(QColor(c.color("muted")))
        code = server_code(self.server.name)
        metrics = painter.fontMetrics()
        painter.drawText(QPointF(x, cy + metrics.ascent() / 2 - 1), code)
        code_w = metrics.horizontalAdvance(code) + 8
        painter.setFont(fonts.serif(17, 400))
        painter.setPen(QColor(c.color("ink")))
        metrics = painter.fontMetrics()
        place = metrics.elidedText(server_place(self.server.name), Qt.TextElideMode.ElideRight,
                                   int(name_w - code_w))
        painter.drawText(QPointF(x + code_w, cy + metrics.ascent() / 2 - 2), place)
        x += name_w + 14

        # Задержка: полоска и миллисекунды.
        if self.latency >= 0:
            bar = max(6.0, 64.0 - self.latency / 4.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("sky")))
            painter.drawRoundedRect(QRectF(x, cy - 1.5, bar, 3), 1.5, 1.5)
            text = f"{self.latency} мс"
            tx = x + bar + 8
        else:
            text = "— мс"
            tx = x
        painter.setFont(fonts.mono(12, 500, 0.0))
        painter.setPen(QColor(c.color("ink2")))
        metrics = painter.fontMetrics()
        painter.drawText(QPointF(tx, cy + metrics.ascent() / 2 - 1), text)
        x += 124 + 14

        # Волнение: четыре волны, спокойные — оливковые.
        calm = wave_count(self.latency)
        for k in range(4):
            path = parse_path(f"M{x + 2 + k * 20} {cy} {WAVE}")
            pen = QPen(QColor(c.color("olive" if k < calm else "pencil")))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(path)
        x += 90 + 14

        if not compact:
            painter.setFont(fonts.mono(10.5, 500, 0.08))
            painter.setPen(QColor(c.color("ink3")))
            metrics = painter.fontMetrics()
            proto = metrics.elidedText(self.server.transport_label.upper(),
                                       Qt.TextElideMode.ElideRight, 130)
            painter.drawText(QPointF(x, cy + metrics.ascent() / 2 - 1), proto)
            x += 130 + 14

        # «В пути» или «Плыть сюда →».
        if self.active:
            painter.setFont(fonts.mono(10, 500, 0.1))
            metrics = painter.fontMetrics()
            label = "В ПУТИ"
            w = metrics.horizontalAdvance(label) + 16
            chip = QRectF(x, cy - 11, w, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.color("clay")))
            painter.drawRoundedRect(chip, 6, 6)
            painter.setPen(QColor("#141413"))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), label)
        else:
            painter.setFont(fonts.sans(13, 400))
            painter.setPen(QColor(c.color("ink" if self._hover else "ink3")))
            metrics = painter.fontMetrics()
            shift = 3 if self._hover else 0
            painter.drawText(QPointF(x, cy + metrics.ascent() / 2 - 1), "Плыть сюда")
            painter.drawText(QPointF(x + metrics.horizontalAdvance("Плыть сюда ") + shift,
                                     cy + metrics.ascent() / 2 - 1), "→")
        painter.end()


class VpnPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Дальние *берега*",
            "Ваша подписка, выбор сервера и способ подключения. Ссылка хранится "
            "только на этом компьютере и никуда не отправляется.",
            parent,
            eyebrow="VPN · ваша подписка",
        )
        self._servers: list[Server] = []
        self._info = subscription.SubscriptionInfo()
        self._rows: list[ServerRow] = []
        self._latency: dict[str, int] = {}
        self._busy = False
        self._vpn_worker: Worker | None = None
        self._check_worker: Worker | None = None

        self._build_map()
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        self._cards_grid = cards
        self._cards_columns = 0
        self.body.addLayout(cards)
        self._build_control()
        self._build_subscription()
        self._fit_cards()
        self._build_board()
        self._build_shop()

        context.vpn_status_changed.connect(lambda _: self._sync_control())
        context.tunnels_changed.connect(lambda _: self._sync_control())
        self.apply_theme()
        self._load_cached()

    # --- карта: из сада морем ---------------------------------------------

    def _build_map(self) -> None:
        from app.ui import scenes
        from app.ui.ink import InkCanvas

        self.map = InkCanvas(scenes.sea_map(), self.context, plate="plate", radius=20,
                             max_height=190, fit="slice")
        self.map.setMinimumHeight(120)
        self.body.addWidget(self.map)

    def _sync_map(self) -> None:
        from app.ui.naming import server_code, server_place

        status = self.context.vpn_status
        name = status.server if status.running and status.server else \
            self.context.selected_server()
        if not self._servers:
            self.map.set_text("name", "берег не выбран")
            self.map.set_text("sub", "НУЖНА ПОДПИСКА")
        else:
            latency = self._latency.get(name, -1)
            self.map.set_text("name", server_place(name) if name else "берег не выбран")
            self.map.set_text("sub", server_code(name) + (f" · {latency} МС" if latency >= 0 else ""))
        others = [server for server in self._servers if server.name != name][:2]
        self.map.set_text("alt1", server_code(others[0].name) if others else "")
        self.map.set_text("alt2", server_code(others[1].name) if len(others) > 1 else "")
        self.map.set_state("on", bool(status.running))
        # Лодка плывёт быстрее, если до берега близко.
        latency = self._latency.get(name, -1)
        period = 6.0 + (latency / 30.0 if latency > 0 else 3.0)
        self.map.scene.motion_period["boat"] = min(period, 16.0)

    def _fit_cards(self) -> None:
        """«Как плыть» и «Подписка» — рядом, а в узком окне одна под другой."""
        columns = 2 if self.width() >= 980 else 1
        if columns == self._cards_columns:
            return
        self._cards_columns = columns
        for index, card in enumerate((self.control_card, self.sub_card)):
            self._cards_grid.removeWidget(card)
            self._cards_grid.addWidget(card, 0 if columns == 2 else index,
                                       index if columns == 2 else 0)
        self._cards_grid.setColumnStretch(1, 1 if columns == 2 else 0)
        self._cards_grid.setColumnStretch(0, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "sub_card"):
            self._fit_cards()

    # --- выключатель и способ ---------------------------------------------

    def _build_control(self) -> None:
        card = Card(padding=18, spacing=10)
        self.control_card = card

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(section_label("Как плыть"))
        self.vpn_badge = StatusChip("выключен", self.context, False)
        titles.addWidget(self.vpn_badge)
        header.addLayout(titles, 1)
        self.vpn_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.vpn_spinner)
        self.switch_vpn = Switch(False)
        self.switch_vpn.toggled.connect(self._toggle_vpn)
        header.addWidget(self.switch_vpn)
        card.add_layout(header)

        self.vpn_status = faint_label("")
        card.add(self.vpn_status)

        # Чужой туннель — объясняем прямо здесь, без нравоучений.
        self.banner_foreign = Banner(
            self.context, "globe", "", kind="warn", action_text="Переключить на «Прокси»",
        )
        self.banner_foreign.action.clicked.connect(
            lambda: self._set_transport(vpn_config.TRANSPORT_PROXY)
        )
        card.add(self.banner_foreign)
        self.banner_foreign.setVisible(False)

        row = QHBoxLayout()
        row.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("SegmentBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(3, 3, 3, 3)
        bar_layout.setSpacing(2)
        self._transport_buttons: dict[str, QPushButton] = {}
        for key, title in (
            (vpn_config.TRANSPORT_TUN, "Туннель"),
            (vpn_config.TRANSPORT_PROXY, "Прокси"),
        ):
            button = QPushButton(title, bar)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._set_transport(k))
            bar_layout.addWidget(button)
            self._transport_buttons[key] = button
        row.addWidget(bar)
        self.btn_check = Button("Проверить VPN", variant="ghost")
        self.btn_check.clicked.connect(self._check_exit)
        row.addWidget(self.btn_check)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        row.addWidget(self.check_spinner)
        row.addStretch(1)
        card.add_layout(row)

        self.transport_hint = faint_label("")
        card.add(self.transport_hint)
        self.check_result = faint_label("", wrap=True)
        card.add(self.check_result)
        self.check_result.setVisible(False)

        self._sync_transport()
        self._sync_control()

    def _set_transport(self, key: str) -> None:
        if key == vpn_actions.transport():
            self._sync_transport()
            return
        vpn_actions.set_transport(key)
        self._sync_transport()
        self._sync_control()
        if vpn_engine.status().running:
            self._vpn_worker = vpn_actions.restart_if_running(
                self, self.context, "Способ подключения изменён"
            )

    def _sync_transport(self) -> None:
        current = vpn_actions.transport()
        for key, button in self._transport_buttons.items():
            button.setChecked(key == current)
        if current == vpn_config.TRANSPORT_TUN:
            self.transport_hint.setText(
                "Своя лодка: программа создаёт сетевой адаптер и сама решает, кому "
                "плыть через VPN, а кому идти напрямую (там подхватывает zapret). "
                "С другим VPN-клиентом не уживается — пока работает Happ или "
                "подобный, включиться не сможет."
            )
        else:
            self.transport_hint.setText(
                "Попутный корабль: без адаптера и без смены маршрутов — уживается "
                "с любым другим VPN. Через VPN пойдут браузеры, Discord и всё, что "
                "уважает системный прокси. Выбор программ здесь не действует."
            )

    def _toggle_vpn(self, value: bool) -> None:
        if self._busy:
            return
        self._busy = True
        self.switch_vpn.setEnabled(False)
        self.vpn_spinner.start()

        def done(_ok: bool) -> None:
            self._busy = False
            self.switch_vpn.setEnabled(True)
            self.vpn_spinner.stop()
            self._sync_control()

        if value:
            self._vpn_worker = vpn_actions.start(
                self, self.context, done,
                on_progress=lambda text: self.vpn_status.setText(text),
            )
            if self._vpn_worker is None:
                done(False)
        else:
            self._vpn_worker = vpn_actions.stop(self, self.context, done)

    def _sync_control(self) -> None:
        status = self.context.vpn_status
        tunnels = self.context.tunnels
        self.switch_vpn.blockSignals(True)
        self.switch_vpn.setChecked(status.running, animate=False)
        self.switch_vpn.blockSignals(False)
        self.btn_check.setEnabled(status.running)

        if status.running:
            label = "туннель" if status.transport == vpn_config.TRANSPORT_TUN else "прокси"
            mode = vpn_config.MODE_LABELS.get(status.mode, "").lower()
            self.vpn_badge.set_state(f"в пути · {label}", True)
            self.vpn_status.setText(
                f"Плывём через «{status.server or '—'}»"
                + (f" · {mode}" if mode and status.transport == vpn_config.TRANSPORT_TUN else "")
            )
        else:
            self.vpn_badge.set_state("у причала" if self._servers else "нужна подписка", False)
            self.vpn_status.setText(
                "Выберите берег на табло ниже и включите тумблер."
                if self._servers else
                "Сначала добавьте подписку — справа или ниже."
            )
        self._sync_map()

        blocked = bool(tunnels) and vpn_actions.transport() == vpn_config.TRANSPORT_TUN
        if blocked and not status.running:
            self.banner_foreign.set_text(
                f"Сейчас работает {', '.join(tunnels)}. Туннель рядом с ним не "
                "поднимется, а чужой VPN программа не трогает. Выключите его сами "
                "или переключитесь на «Прокси» — он уживается с кем угодно."
            )
            self.banner_foreign.setVisible(True)
        else:
            self.banner_foreign.setVisible(False)

    def _check_exit(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        self.btn_check.setEnabled(False)
        self.check_spinner.start()
        self.check_result.setText("Спрашиваем, каким адресом нас видят…")
        self.check_result.setVisible(True)

        def done(ok: bool, message: str) -> None:
            self.btn_check.setEnabled(True)
            self.check_spinner.stop()
            self.check_result.setText(message)
            self.check_result.setVisible(bool(message))

        self._check_worker = vpn_actions.check_exit(self, self.context, done)
        if self._check_worker is None:
            done(False, "")

    # --- подписка --------------------------------------------------------

    def _build_subscription(self) -> None:
        card = Card(padding=18, spacing=10)
        self.sub_card = card

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Подписка"))
        header.addStretch(1)
        self.sub_badge = StatusChip("не настроена", self.context, False)
        header.addWidget(self.sub_badge)
        card.add_layout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.url_input = QLineEdit(subscription.subscription_url())
        self.url_input.setPlaceholderText(
            "https://… — ссылка-подписка, либо ключ vless:// целиком"
        )
        self.url_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.url_input.setProperty("secret", True)
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
        card.add(self.quota_bar)
        self.quota_bar.setVisible(False)

        self.sub_details = faint_label(
            "Вставьте ссылку из личного кабинета и нажмите «Обновить»."
        )
        card.add(self.sub_details)

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
        self.sub_badge.set_state("ошибка", False, "error")
        self.sub_details.setText(message)
        self.context.error(message)

    def _subscription_loaded(self, payload) -> None:
        servers, info = payload
        self.btn_update.setEnabled(True)
        self.sub_spinner.stop()
        self._servers, self._info = servers, info
        self.context.set_servers(servers)
        self._render_subscription()
        self._rebuild_board()
        self._sync_shop()
        self._sync_control()
        self.context.ok(f"Загружено серверов: {len(servers)}")
        self.measure_all()

    def _load_cached(self) -> None:
        servers, info = subscription.load_cached()
        if servers:
            self._servers, self._info = servers, info
            self._render_subscription()
            self._rebuild_board()
        self._sync_shop()
        self._sync_control()

    def _render_subscription(self) -> None:
        info = self._info
        if not self._servers:
            self.sub_badge.set_state("не настроена", False)
            return

        days = info.days_left
        if days is None:
            self.sub_badge.set_state("активна", True)
        elif days <= 3:
            self.sub_badge.set_state(f"осталось {days} дн.", True, "error")
        elif days <= 10:
            self.sub_badge.set_state(f"осталось {days} дн.", True, "warn")
        else:
            self.sub_badge.set_state("активна", True)

        parts = [f"Берегов: {len(self._servers)}"]
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

    # --- где взять подписку ----------------------------------------------

    def _build_shop(self) -> None:
        """Пока подписки нет — предложение заметное, потом сворачивается."""
        from app.core.constants import SUBSCRIPTION_SHOP_NAME, SUBSCRIPTION_SHOP_URL

        self.shop_card = Card(padding=18, spacing=11)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.shop_icon = IconLabel("globe", self.context.color("accent"), 20)
        header.addWidget(self.shop_icon)
        header.addWidget(section_label("Нет своей подписки?"))
        header.addStretch(1)
        self.btn_shop = Button(f"Открыть {SUBSCRIPTION_SHOP_NAME}", variant="soft")
        self.btn_shop.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(SUBSCRIPTION_SHOP_URL))
        )
        header.addWidget(self.btn_shop)
        self.shop_card.add_layout(header)

        self.shop_text = faint_label(
            f"Программе нужна ссылка-подписка от любого сервиса. Если её пока нет, "
            f"можно взять у {SUBSCRIPTION_SHOP_NAME} — откроется бот в Telegram. "
            "Сервис сторонний, к программе отношения не имеет: подойдёт и любой "
            "другой, лишь бы выдавал ссылку или ключ vless://."
        )
        self.shop_card.add(self.shop_text)

        self.body.addWidget(self.shop_card)

    def _sync_shop(self) -> None:
        has_subscription = bool(self._servers)
        self.shop_text.setVisible(not has_subscription)
        self.shop_icon.setVisible(not has_subscription)
        self.shop_card.setVisible(not has_subscription)

    # --- табло -----------------------------------------------------------

    def _build_board(self) -> None:
        card = Card(padding=14, spacing=6)

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 6, 0)
        header.setSpacing(12)
        header.addWidget(section_label("Табло берегов"))
        header.addWidget(MonoLabel("задержка · волнение · протокол", self.context, "ink3"),
                         0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        self.board_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.board_spinner)

        self.btn_best = Button("Выбрать лучший", variant="soft")
        self.btn_best.clicked.connect(self._choose_best)
        header.addWidget(self.btn_best)

        self.btn_measure = Button("Проверить задержку", variant="ghost")
        self.btn_measure.clicked.connect(self.measure_all)
        header.addWidget(self.btn_measure)
        card.add_layout(header)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(1)
        card.add(self.rows_host)

        self.board_empty = faint_label(
            "Берегов пока нет. Добавьте ссылку-подписку выше — и табло заполнится."
        )
        self.board_empty.setContentsMargins(6, 4, 6, 6)
        card.add(self.board_empty)

        self.body.addWidget(card)

    def _rebuild_board(self) -> None:
        clear_layout(self.rows_layout)
        self._rows = []

        active = self.context.selected_server()
        for index, server in enumerate(self._servers):
            row = ServerRow(
                self.context, server,
                self._latency.get(server.name, -1),
                server.name == active, index,
                self.rows_host,
            )
            row.chosen.connect(self._select_server)
            self.rows_layout.addWidget(row)
            self._rows.append(row)

        self.board_empty.setVisible(not self._rows)
        self.rows_host.setVisible(bool(self._rows))
        self._sync_map()

    def _select_server(self, name: str) -> None:
        config.set("vpn_selected_server", name)
        for row in self._rows:
            row.set_active(row.server.name == name)
        self.context.servers_changed.emit()
        self._sync_control()

        if not self.context.vpn_status.running:
            self.context.ok(f"Выбран сервер «{name}»")
            return

        # Переключение — запрос к движку, до четырёх секунд. В потоке окна
        # оно замораживало всё окно, поэтому — в фоне.
        def switch() -> str:
            try:
                vpn_engine.switch_server(name)
            except VpnError as exc:
                raise RuntimeError(str(exc)) from exc
            return name

        worker = Worker(self)
        worker.finished.connect(lambda _: (
            self.context.ok(f"Активный сервер: «{name}»"),
            self.context.refresh_vpn_status(force=True),
        ))
        worker.failed.connect(self.context.error)
        worker.run(switch)
        self._switch_worker = worker

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
                return {server.name: vpn_engine.measure_delay(server.name)
                        for server in servers}
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
        self._sync_map()

        alive = [value for value in self._latency.values() if value >= 0]
        if not alive:
            self.context.warn(
                "Ни один берег не ответил. Проверьте интернет или обновите подписку."
            )
        else:
            self.context.ok(f"Ответили берегов: {len(alive)} из {len(self._latency)}")

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
        self._sync_shop()
        self.context.refresh_vpn_status(force=True)
        self.context.refresh_tunnels(force=True)
        self._sync_control()

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        for spinner in (self.vpn_spinner, self.check_spinner, self.sub_spinner,
                        self.board_spinner):
            spinner.set_color(accent)
        self.shop_icon.set_color(accent)
        for row in self._rows:
            row.apply_theme()
        self._sync_transport()
