"""Страница «DNS»: Smart DNS для обхода гео-ограничений."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core import dnsctl
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.widgets import (
    clear_layout,
    Badge,
    Button,
    Card,
    Divider,
    Spinner,
    Worker,
    faint_label,
    section_label,
)


class PresetCard(QFrame):
    """Карточка сервиса DNS."""

    chosen = Signal(str)

    def __init__(self, context: AppContext, preset: dnsctl.DnsPreset,
                 active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.preset = preset
        self.active = active
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(preset.title)
        self.title.setStyleSheet("font-family: 'Literata'; font-size: 18px; "
                                 "background: transparent;")
        head.addWidget(self.title)
        # Родителя передаём явно: компоновка head ещё не прикреплена
        # к виджету, поэтому сама по себе родителя не назначит.
        self.badge = Badge("стоит сейчас", "ok", self)
        head.addWidget(self.badge)
        self.badge.setVisible(active)
        head.addStretch(1)
        if preset.doh:
            head.addWidget(Badge("DoH", "neutral"))
        layout.addLayout(head)

        layout.addWidget(faint_label(preset.description))

        self.addresses = QLabel(preset.label)
        self.addresses.setProperty("role", "mono")
        layout.addWidget(self.addresses)

        if preset.site:
            link = QLabel(f'<a href="{preset.site}">Сайт сервиса</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet(f"color: {context.color('accent_text')};")
            layout.addWidget(link)

        self.apply_theme()

    def set_active(self, value: bool) -> None:
        self.active = value
        self.badge.setVisible(value)
        self.apply_theme()

    def apply_theme(self) -> None:
        self.addresses.setStyleSheet(f"color: {self.context.color('muted')}; "
                                     "background: transparent;")
        if self.active:
            self.setStyleSheet(
                f"QFrame#Card {{ background: {self.context.color('bg')}; "
                f"border: 1.5px solid {self.context.color('ink')}; border-radius: 14px; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#Card {{ background: {self.context.color('surface')}; "
                f"border: 1px solid {self.context.color('border')}; "
                f"border-radius: 14px; }}"
                f"QFrame#Card:hover {{ border-color: {self.context.color('decor')}; }}"
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.preset.key)
        super().mouseReleaseEvent(event)


class DnsPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Куда ведёт *указатель*",
            "Smart DNS отдаёт другой адрес сервисам, которые закрыты для России "
            "по стране. Работает вместе с обходом и не мешает VPN.",
            parent,
            eyebrow="Smart DNS · по стране",
        )
        self._cards: list[PresetCard] = []
        self._busy = False

        from app.ui import scenes
        from app.ui.ink import InkCanvas

        self.scene = InkCanvas(scenes.crossroads(), context, plate="plate", radius=20,
                               max_height=180, fit="slice")
        self.scene.setMinimumHeight(110)
        self.body.addWidget(self.scene)

        # Закрытый Xbox DNS всё ещё стоит в системе — сказать и предложить замену.
        self.banner_retired = Banner(
            context, "warning", "", kind="warn", action_text="Поставить Comss DNS",
        )
        self.banner_retired.action.clicked.connect(lambda: self._apply("comss"))
        self.body.addWidget(self.banner_retired)
        self.banner_retired.setVisible(False)

        self._build_status()
        self._build_presets()
        self._build_retired_note()
        self.apply_theme()
        self._sync_scene(self.context.dns_preset or "auto")

    # --- состояние -------------------------------------------------------

    def _build_status(self) -> None:
        card = Card(padding=20, spacing=13)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(section_label("Сейчас"))
        head.addStretch(1)
        self.spinner = Spinner(16, self.context.color("accent"))
        head.addWidget(self.spinner)
        self.btn_restore = Button("Вернуть как было", variant="ghost")
        self.btn_restore.clicked.connect(self._restore)
        head.addWidget(self.btn_restore)
        card.add_layout(head)

        self.adapters_host = QWidget()
        self.adapters_layout = QVBoxLayout(self.adapters_host)
        self.adapters_layout.setContentsMargins(0, 0, 0, 0)
        self.adapters_layout.setSpacing(7)
        card.add(self.adapters_host)

        card.add(Divider())
        card.add(faint_label(
            "Если включён VPN, он использует собственный DNS внутри туннеля — "
            "системные настройки на туннельный трафик тогда не влияют."
        ))

        self.body.addWidget(card)

    def _refresh_adapters(self, adapters=None) -> None:
        clear_layout(self.adapters_layout)

        if adapters is None:
            adapters = dnsctl.adapters()
        if not adapters:
            self.adapters_layout.addWidget(
                faint_label("Активных сетевых подключений не найдено.")
            )
            return

        for adapter in adapters:
            line = QWidget(self.adapters_host)
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)

            dot = QLabel("●")
            token = "success" if adapter.up else "text_faint"
            dot.setStyleSheet(f"color: {self.context.color(token)}; font-size: 10px;")
            row.addWidget(dot)

            name = QLabel(adapter.name)
            name.setStyleSheet("font-weight: 600;")
            row.addWidget(name)
            row.addStretch(1)

            servers = QLabel(adapter.servers_label)
            servers.setProperty("role", "mono")
            servers.setStyleSheet(f"color: {self.context.color('text_dim')};")
            row.addWidget(servers)

            row.addWidget(Badge("авто" if adapter.automatic else "вручную",
                                "neutral" if adapter.automatic else "accent"))
            self.adapters_layout.addWidget(line)

        self.btn_restore.setVisible(dnsctl.has_backup())

    # --- пресеты ---------------------------------------------------------

    def _build_presets(self) -> None:
        from PySide6.QtWidgets import QGridLayout

        card = Card(padding=20, spacing=13)
        card.add(section_label("Выберите сервис"))
        card.add(faint_label(
            "Настройки применяются ко всем активным подключениям. "
            "Исходные значения сохраняются — вернуть их можно одной кнопкой."
        ))

        current = self.context.dns_preset
        self.presets_grid = QGridLayout()
        self.presets_grid.setHorizontalSpacing(12)
        self.presets_grid.setVerticalSpacing(12)
        for preset in dnsctl.PRESETS:
            item = PresetCard(self.context, preset, preset.key == current)
            item.chosen.connect(self._apply)
            self._cards.append(item)
        self._grid_columns = 0
        self._fit_presets()
        card.add_layout(self.presets_grid)

        self.body.addWidget(card)

    def _fit_presets(self) -> None:
        columns = 2 if self.width() >= 900 else 1
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        for index, item in enumerate(self._cards):
            self.presets_grid.removeWidget(item)
            self.presets_grid.addWidget(item, index // columns, index % columns)
        self.presets_grid.setColumnStretch(1, 1 if columns == 2 else 0)
        self.presets_grid.setColumnStretch(0, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "presets_grid"):
            self._fit_presets()

    def _build_retired_note(self) -> None:
        """Куда делся Xbox DNS — коротко и по делу."""
        note = Card(padding=18, spacing=8, alt=True)
        note.add(section_label("Где Xbox DNS?"))
        note.add(faint_label(
            "Закрыт в октябре 2026 года: по требованию ЦМУ ССОП (Роскомнадзора) "
            "хостинг заблокировал сервис, а DNS-запросы к его адресам провайдеры "
            "начали резать ещё в сентябре. Это ограничение на стороне сети, из "
            "программы его не обойти, поэтому Xbox DNS убран из списка. Игровые "
            "сервисы и нейросети возвращает Comss DNS, а если и он не справится — VPN."
        ))
        self.body.addWidget(note)

    def _apply(self, key: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.spinner.start()

        worker = Worker(self)
        worker.finished.connect(self._applied)
        worker.failed.connect(self._failed)
        worker.run(dnsctl.apply_preset, key)
        self._worker = worker

    def _applied(self, message) -> None:
        self._busy = False
        self.spinner.stop()
        self.context.ok(str(message))
        self._sync()

    def _failed(self, message: str) -> None:
        self._busy = False
        self.spinner.stop()
        self.context.error(str(message))
        self._sync()

    def _restore(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._applied)
        worker.failed.connect(self._failed)
        worker.run(dnsctl.restore)
        self._worker = worker

    def _sync(self) -> None:
        """Настройки адаптеров читаются из реестра десятки миллисекунд — в фоне,
        чтобы открытие вкладки не притормаживало."""
        worker = getattr(self, "_sync_worker", None)
        if worker is not None and worker.busy():
            return
        worker = Worker(self)
        worker.finished.connect(self._synced)
        worker.run(lambda: (dnsctl.current_preset(), dnsctl.adapters()))
        self._sync_worker = worker

    def _synced(self, payload) -> None:
        current, adapters = payload
        for card in self._cards:
            card.set_active(card.preset.key == current)
        self._refresh_adapters(adapters)
        self._sync_scene(current)

    def _sync_scene(self, current: str) -> None:
        retired = current.startswith("retired:")
        preset = dnsctl.PRESET_BY_KEY.get(current)
        on = current not in ("auto", "") and not retired
        self.scene.set_state("on", on)
        if retired:
            sign = "ЗАКРЫТ"
        elif preset is not None and on:
            sign = preset.title.replace(" DNS", "").upper()[:7]
        elif current == "custom":
            sign = "СВОЙ"
        else:
            sign = "АВТО"
        self.scene.set_text("sign", sign)
        if retired:
            title = dnsctl.retired_title(current)
            self.banner_retired.set_text(
                f"В системе всё ещё стоит {title}, а его закрыли по требованию "
                "Роскомнадзора — сайты могут не открываться. Поставьте живой сервис.")
        self.banner_retired.setVisible(retired)

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._sync()

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
        for card in self._cards:
            card.apply_theme()
