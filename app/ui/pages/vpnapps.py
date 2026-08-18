"""Страница «Приложения»: какой программе каким путём ходить в сеть."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import config
from app.core.vpn import apps as apps_module
from app.core.vpn import config as vpn_config
from app.core.vpn.apps import AppEntry
from app.ui import appicons
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    Switch,
    Worker,
    faint_label,
    section_label,
)

CARD_COLUMNS = 2


class AppCard(QFrame):
    """Карточка программы: иконка, название и переключатель маршрута."""

    toggled = Signal(str, bool)

    def __init__(self, context: AppContext, entry: AppEntry, active: bool,
                 lane_token: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.entry = entry
        self.lane_token = lane_token
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(13)

        self.icon = QLabel()
        self.icon.setFixedSize(36, 36)
        ratio = self.devicePixelRatioF() or 1.0
        self.icon.setPixmap(
            appicons.app_pixmap(entry.path, entry.title, 36, ratio)
        )
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        self.title = QLabel(entry.title)
        self.title.setStyleSheet("font-weight: 600; font-size: 13.5px;")
        title_row.addWidget(self.title)
        if entry.running:
            dot = QLabel("●")
            dot.setToolTip("Программа запущена")
            dot.setStyleSheet(f"color: {context.color('success')}; font-size: 10px;")
            title_row.addWidget(dot)
        title_row.addStretch(1)
        text_box.addLayout(title_row)

        self.subtitle = faint_label(entry.process, wrap=False)
        text_box.addWidget(self.subtitle)
        layout.addLayout(text_box, 1)

        self.switch = Switch(active)
        self.switch.toggled.connect(self._on_switch)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme()

    def _on_switch(self, value: bool) -> None:
        self.apply_theme()
        self.toggled.emit(self.entry.process, value)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # По карточке удобнее попадать, чем по маленькому ползунку.
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            if not isinstance(child, Switch):
                self.switch.setChecked(not self.switch.isChecked())
                self._on_switch(self.switch.isChecked())
        super().mouseReleaseEvent(event)

    def set_active(self, value: bool) -> None:
        self.switch.setChecked(value, animate=False)
        self.apply_theme()

    def apply_theme(self) -> None:
        lane = self.context.color(self.lane_token)
        self.switch.set_colors(
            lane, self.context.color("border_strong"), self.context.color("surface")
        )
        if self.switch.isChecked():
            background = self.context.color(f"{self.lane_token}_soft")
            self.setStyleSheet(
                f"QFrame#Card {{ background: {background}; "
                f"border: 1px solid {lane}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#Card {{ background: {self.context.color('surface')}; "
                f"border: 1px solid {self.context.color('border')}; "
                f"border-radius: 12px; }}"
            )
        ratio = self.devicePixelRatioF() or 1.0
        self.icon.setPixmap(
            appicons.app_pixmap(self.entry.path, self.entry.title, 36, ratio)
        )


class VpnAppsPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Приложения",
            "Кому идти через VPN, а кому напрямую. Всё, что не в туннеле, "
            "выходит обычным путём — там его подхватывает zapret.",
        )
        self._cards: list[AppCard] = []
        self._entries: list[AppEntry] = []
        self._loading = False

        self._build_mode()
        self._build_summary()
        self._build_list()
        self._build_manual()
        self.apply_theme()

    # --- режим -----------------------------------------------------------

    def _build_mode(self) -> None:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Как распределять трафик"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QPushButton] = {}

        for key in (vpn_config.MODE_SELECTED, vpn_config.MODE_EXCEPT, vpn_config.MODE_ALL):
            button = QPushButton(vpn_config.MODE_LABELS[key])
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._set_mode(k))
            self._mode_group.addButton(button)
            row.addWidget(button)
            self._mode_buttons[key] = button
        row.addStretch(1)
        card.add_layout(row)

        self.mode_hint = faint_label("")
        card.add(self.mode_hint)
        self.body.addWidget(card)

    def _current_mode(self) -> str:
        mode = str(config.get("vpn_mode", vpn_config.MODE_SELECTED))
        return mode if mode in vpn_config.MODE_LABELS else vpn_config.MODE_SELECTED

    def _set_mode(self, mode: str) -> None:
        config.set("vpn_mode", mode)
        self._sync_mode()
        self._reload_cards()
        self._update_summary()
        self.context.ok(f"Режим: {vpn_config.MODE_LABELS[mode]}")

    def _sync_mode(self) -> None:
        mode = self._current_mode()
        for key, button in self._mode_buttons.items():
            selected = key == mode
            button.setChecked(selected)
            button.setProperty("variant", "soft" if selected else "ghost")
            style = button.style()
            style.unpolish(button)
            style.polish(button)

        hints = {
            vpn_config.MODE_SELECTED:
                "Через туннель пойдут только те программы, у которых включён "
                "переключатель. Остальные — напрямую.",
            vpn_config.MODE_EXCEPT:
                "Через туннель пойдёт всё, кроме отмеченных программ. Отмечайте "
                "банки, госуслуги и игры — им туннель только мешает.",
            vpn_config.MODE_ALL:
                "Весь трафик идёт через туннель. Выбирать программы не нужно.",
        }
        self.mode_hint.setText(hints[mode])

    def _lane_token(self) -> str:
        return "lane_direct" if self._current_mode() == vpn_config.MODE_EXCEPT else "lane_vpn"

    def _storage_key(self) -> str:
        return ("vpn_direct_apps"
                if self._current_mode() == vpn_config.MODE_EXCEPT else "vpn_apps")

    def _selected_names(self) -> list[str]:
        return list(config.get(self._storage_key(), []) or [])

    # --- сводка ----------------------------------------------------------

    def _build_summary(self) -> None:
        card = Card(padding=18, spacing=10)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.summary_badge = Badge("0", "accent")
        row.addWidget(self.summary_badge)
        self.summary_text = faint_label("")
        row.addWidget(self.summary_text, 1)

        self.btn_clear = Button("Снять все", variant="ghost")
        self.btn_clear.clicked.connect(self._clear_all)
        row.addWidget(self.btn_clear)
        card.add_layout(row)

        self.restart_hint = faint_label("")
        self.restart_hint.setVisible(False)
        card.add(self.restart_hint)
        self.body.addWidget(card)

    def _update_summary(self) -> None:
        names = self._selected_names()
        mode = self._current_mode()
        self.summary_badge.setText(str(len(names)))
        if mode == vpn_config.MODE_ALL:
            self.summary_text.setText("Через туннель идёт весь трафик.")
            self.summary_badge.setText("все")
        elif mode == vpn_config.MODE_EXCEPT:
            self.summary_text.setText(f"Мимо туннеля: {apps_module.describe(names)}")
        else:
            self.summary_text.setText(f"Через туннель: {apps_module.describe(names)}")

        from app.core.vpn.engine import vpn_engine

        running = vpn_engine.status().running
        self.restart_hint.setVisible(running)
        if running:
            self.restart_hint.setText(
                "VPN сейчас работает — чтобы изменения вступили в силу, "
                "перезапустите его на главной странице."
            )

    def _clear_all(self) -> None:
        config.set(self._storage_key(), [])
        for card in self._cards:
            card.set_active(False)
        self._update_summary()

    # --- список ----------------------------------------------------------

    def _build_list(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Программы"))
        header.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter)
        header.addWidget(self.search)

        self.btn_refresh = Button("Обновить", variant="ghost")
        self.btn_refresh.clicked.connect(self._reload_cards)
        header.addWidget(self.btn_refresh)
        card.add_layout(header)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        card.add(self.grid_host)

        self.empty_hint = faint_label(
            "Программы не найдены. Запустите нужную — она появится в списке, "
            "либо добавьте её вручную ниже."
        )
        self.empty_hint.setVisible(False)
        card.add(self.empty_hint)

        self.body.addWidget(card)

    def _reload_cards(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.btn_refresh.setEnabled(False)

        selected = self._selected_names()
        worker = Worker(self)
        worker.finished.connect(self._cards_ready)
        worker.failed.connect(self._cards_failed)
        worker.run(apps_module.catalog, False, selected)
        self._catalog_worker = worker

    def _cards_failed(self, message: str) -> None:
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self.context.error(f"Не удалось получить список программ: {message}")

    def _cards_ready(self, entries) -> None:
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self._entries = list(entries)

        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []

        mode = self._current_mode()
        selected = {name.lower() for name in self._selected_names()}
        lane = self._lane_token()

        for index, entry in enumerate(self._entries):
            card = AppCard(self.context, entry, entry.key in selected, lane)
            card.toggled.connect(self._on_card_toggled)
            card.setEnabled(mode != vpn_config.MODE_ALL)
            self.grid.addWidget(card, index // CARD_COLUMNS, index % CARD_COLUMNS)
            self._cards.append(card)

        self.empty_hint.setVisible(not self._cards)
        self.grid_host.setVisible(bool(self._cards))
        self._filter(self.search.text())
        self._update_summary()

    def _on_card_toggled(self, process: str, active: bool) -> None:
        key = self._storage_key()
        names = list(config.get(key, []) or [])
        lowered = [name.lower() for name in names]
        if active and process.lower() not in lowered:
            names.append(process)
        elif not active:
            names = [name for name in names if name.lower() != process.lower()]
        config.set(key, apps_module.normalize(names))
        self._update_summary()

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible = 0
        for card in self._cards:
            match = (
                not needle
                or needle in card.entry.title.lower()
                or needle in card.entry.process.lower()
            )
            card.setVisible(match)
            visible += 1 if match else 0
        self.empty_hint.setVisible(visible == 0 and bool(self._cards))

    # --- ручное добавление -----------------------------------------------

    def _build_manual(self) -> None:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Добавить вручную"))
        card.add(faint_label(
            "Если программы нет в списке, укажите имя её файла — так, как оно "
            "выглядит в диспетчере задач. Например: Telegram.exe"
        ))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("имя_программы.exe")
        self.manual_input.returnPressed.connect(self._add_manual)
        row.addWidget(self.manual_input, 1)

        add_button = Button("Добавить", variant="soft")
        add_button.clicked.connect(self._add_manual)
        row.addWidget(add_button)
        card.add_layout(row)

        self.body.addWidget(card)

    def _add_manual(self) -> None:
        name = self.manual_input.text().strip()
        if not name:
            return
        if not name.lower().endswith(".exe"):
            name += ".exe"
        key = self._storage_key()
        names = list(config.get(key, []) or []) + [name]
        config.set(key, apps_module.normalize(names))
        self.manual_input.clear()
        self.context.ok(f"«{name}» добавлена")
        self._reload_cards()

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_mode()
        self._reload_cards()

    def apply_theme(self) -> None:
        self._sync_mode()
        for card in self._cards:
            card.lane_token = self._lane_token()
            card.apply_theme()
