"""Вкладка «Telegram»: два способа вернуть мессенджер — WebSocket-прокси
внутри программы и секции zapret по подсетям Telegram."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSpinBox, QWidget

from app.core import telegram, tgws
from app.core.config import config
from app.ui import tgws_actions
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Collapsible,
    Divider,
    IconLabel,
    SettingRow,
    Spinner,
    Switch,
    Worker,
    faint_label,
    muted_label,
    section_label,
)


class TelegramPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Telegram",
            "Если Telegram не подключается — включите первый способ и нажмите "
            "«Открыть в Telegram». Второй добавляйте, если первого мало.",
            parent,
        )
        self._ws_worker: Worker | None = None
        self._tg_worker: Worker | None = None
        self._busy_ws = False

        self._build_websocket()
        self._build_zapret()

        context.tgws_changed.connect(lambda _: self._sync_ws())
        context.status_changed.connect(lambda _: self._sync_zapret())
        self.apply_theme()

    # --- способ 1: WebSocket-прокси ---------------------------------------

    def _build_websocket(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.ws_icon = IconLabel("telegram", self.context.color("accent"), 20)
        header.addWidget(self.ws_icon)
        header.addWidget(section_label("Через WebSocket-прокси"))
        header.addWidget(Badge("рекомендуется", "accent"))
        header.addStretch(1)
        self.ws_badge = Badge("выключен", "neutral")
        header.addWidget(self.ws_badge)
        self.ws_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.ws_spinner)
        self.switch_ws = Switch(tgws.tgws_engine.is_running())
        self.switch_ws.toggled.connect(self._toggle_ws)
        header.addWidget(self.switch_ws)
        card.add_layout(header)

        card.add(muted_label(
            "Программа поднимает на вашем компьютере маленький прокси, а Telegram "
            "подключается к нему как к обычному MTProto-прокси. Дальше трафик "
            "уходит к серверам Telegram внутри WebSocket — провайдер видит "
            "обычное шифрованное соединение с сайтом. Сторонних серверов нет, "
            "данные шифрует сам Telegram."
        ))

        self.ws_status = faint_label("")
        card.add(self.ws_status)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_open = Button("Открыть в Telegram", variant="primary",
                               icon_name="external", icon_color="#FFFFFF")
        self.btn_open.clicked.connect(lambda: tgws_actions.open_in_telegram(self.context))
        buttons.addWidget(self.btn_open)
        self.btn_copy = Button("Скопировать ссылку", variant="ghost")
        self.btn_copy.clicked.connect(lambda: tgws_actions.copy_link(self.context))
        buttons.addWidget(self.btn_copy)
        buttons.addStretch(1)
        card.add_layout(buttons)

        card.add(faint_label(
            "Telegram спросит, включить ли прокси, — соглашайтесь. Если Telegram "
            "не открылся сам, скопируйте ссылку, отправьте её себе в «Избранное» "
            "и нажмите на неё там."
        ))

        self.ws_more = Collapsible("Дополнительно", self.context)
        self.ws_more.set_hint("порт, советы")

        self.port_box = QSpinBox()
        self.port_box.setRange(1024, 65535)
        self.port_box.setValue(tgws.tgws_engine.port())
        self.port_box.setFixedWidth(110)
        self.port_box.valueChanged.connect(self._change_port)
        self.ws_more.body.addWidget(SettingRow(
            "Порт прокси",
            "Меняйте, только если порт занят другой программой. После смены "
            "перезапустите прокси и заново добавьте его в Telegram.",
            self.port_box,
        ))
        self.ws_more.body.addWidget(Divider())
        self.ws_more.body.addWidget(faint_label(
            "Не грузятся фото и видео? Такое бывает на аккаунтах без Premium: "
            "прокси сам переключается на резервный путь, подождите минуту. "
            "Ядро прокси — tg-ws-proxy от Flowseal, лицензия MIT."
        ))
        card.add(self.ws_more)

        self.body.addWidget(card)
        self._sync_ws()

    def _toggle_ws(self, value: bool) -> None:
        if self._busy_ws:
            return
        self._busy_ws = True
        self.switch_ws.setEnabled(False)
        self.ws_spinner.start()

        def done(_ok: bool) -> None:
            self._busy_ws = False
            self.switch_ws.setEnabled(True)
            self.ws_spinner.stop()
            self._sync_ws()

        self._ws_worker = tgws_actions.toggle(self, self.context, value, done)

    def _change_port(self, value: int) -> None:
        config.set("tg_ws_port", int(value))
        if tgws.tgws_engine.is_running():
            self.context.warn("Порт изменится после перезапуска прокси.")

    def _sync_ws(self) -> None:
        status = self.context.tgws_status
        self.switch_ws.blockSignals(True)
        self.switch_ws.setChecked(status.running, animate=False)
        self.switch_ws.blockSignals(False)
        self.btn_open.setEnabled(status.running)

        if status.running:
            self.ws_badge.update_state("работает", "ok")
            parts = [f"порт {status.port}"]
            if status.active:
                parts.append(f"соединений сейчас: {status.active}")
            if status.websocket:
                parts.append(f"через WebSocket: {status.websocket}")
            if status.fallback:
                parts.append(f"резервным путём: {status.fallback}")
            self.ws_status.setText("Работает · " + " · ".join(parts))
        else:
            self.ws_badge.update_state("выключен", "neutral")
            self.ws_status.setText(
                status.error or "Выключен. Включите переключатель справа."
            )

    # --- способ 2: секции zapret ------------------------------------------

    def _build_zapret(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.tg_icon = IconLabel("shield", self.context.color("accent"), 20)
        header.addWidget(self.tg_icon)
        header.addWidget(section_label("Через zapret"))
        header.addStretch(1)
        self.tg_badge = Badge("выключен", "neutral")
        header.addWidget(self.tg_badge)
        self.switch_tg = Switch(telegram.is_enabled())
        self.switch_tg.toggled.connect(self._toggle_zapret)
        header.addWidget(self.switch_tg)
        card.add_layout(header)

        card.add(muted_label(
            "Telegram общается по протоколу MTProto, где имени домена в пакете "
            "нет, — опознать его по списку сайтов нельзя. Поэтому обход работает "
            "по официальному списку подсетей Telegram и добавляется к выбранной "
            "стратегии zapret. Помогает не у всех провайдеров, зато не требует "
            "ничего настраивать в самом Telegram."
        ))

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.tg_mode = QComboBox()
        for key, label in telegram.MODES.items():
            self.tg_mode.addItem(label, key)
        index = self.tg_mode.findData(telegram.mode())
        if index >= 0:
            self.tg_mode.setCurrentIndex(index)
        self.tg_mode.currentIndexChanged.connect(self._change_zapret_mode)
        controls.addWidget(self.tg_mode)

        self.tg_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.tg_spinner)

        self.btn_tg_update = Button("Обновить подсети", variant="ghost")
        self.btn_tg_update.clicked.connect(self._update_subnets)
        controls.addWidget(self.btn_tg_update)
        controls.addStretch(1)
        card.add_layout(controls)

        self.tg_hint = faint_label("")
        card.add(self.tg_hint)

        self.body.addWidget(card)
        self._sync_zapret()

    def _sync_zapret(self) -> None:
        enabled = telegram.is_enabled()
        self.switch_tg.blockSignals(True)
        self.switch_tg.setChecked(enabled, animate=False)
        self.switch_tg.blockSignals(False)
        self.tg_badge.update_state(
            "включён" if enabled else "выключен", "ok" if enabled else "neutral"
        )
        self.tg_hint.setText(telegram.summary())

    def _toggle_zapret(self, value: bool) -> None:
        telegram.set_enabled(value)
        self._sync_zapret()
        if self.context.status.running:
            self.context.warn("Перезапустите обход, чтобы настройка Telegram вступила в силу.")
        else:
            self.context.ok("Обход Telegram через zapret " + ("включён" if value else "выключен"))

    def _change_zapret_mode(self) -> None:
        telegram.set_mode(str(self.tg_mode.currentData()))
        self._sync_zapret()
        if self.context.status.running and telegram.is_enabled():
            self.context.warn("Перезапустите обход, чтобы применить новый режим.")

    def _update_subnets(self) -> None:
        self.btn_tg_update.setEnabled(False)
        self.tg_spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._subnets_updated)
        worker.failed.connect(self._subnets_failed)
        worker.run(telegram.update_ipset)
        self._tg_worker = worker

    def _subnets_updated(self, result) -> None:
        self.btn_tg_update.setEnabled(True)
        self.tg_spinner.stop()
        self._sync_zapret()
        self.context.ok(str(result) if result else "Подсети Telegram обновлены")

    def _subnets_failed(self, message: str) -> None:
        self.btn_tg_update.setEnabled(True)
        self.tg_spinner.stop()
        self.context.error(str(message))

    # --- страница ---------------------------------------------------------

    def on_activate(self) -> None:
        self.context.refresh_tgws(force=True)
        self._sync_zapret()

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.ws_icon.set_color(accent)
        self.tg_icon.set_color(accent)
        self.ws_spinner.set_color(accent)
        self.tg_spinner.set_color(accent)
        self.ws_more.apply_theme()
        for switch in (self.switch_ws, self.switch_tg):
            switch.set_colors(
                self.context.color("lane_tg"),
                self.context.color("border_strong"),
                self.context.color("surface"),
            )
