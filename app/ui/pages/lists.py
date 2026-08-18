"""Страница списков: свои домены, исключения, IPSet и hosts."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
)

from app.core import lists as lists_module
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Badge,
    Button,
    Card,
    IconLabel,
    Spinner,
    Worker,
    faint_label,
    section_label,
)


class ListsPage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Списки",
            "Что обходить, а что трогать не нужно. Изменения применяются "
            "после перезапуска обхода.",
        )
        self._current_key = lists_module.USER_LISTS[0].key
        self._dirty = False

        self._build_editor()
        self._build_ipset()
        self._build_hosts()
        self.apply_theme()

    # --- редактор пользовательских списков -------------------------------

    def _build_editor(self) -> None:
        card = Card(padding=20, spacing=14)

        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        for index, item in enumerate(lists_module.USER_LISTS):
            button = QPushButton(item.title)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(button.cursor())
            button.setProperty("variant", "ghost" if index else "soft")
            button.clicked.connect(lambda _=False, key=item.key: self.switch_list(key))
            self._tab_group.addButton(button)
            tabs.addWidget(button)
        tabs.addStretch(1)

        self.save_button = Button("Сохранить", variant="primary")
        self.save_button.clicked.connect(self.save_current)
        self.save_button.setEnabled(False)
        tabs.addWidget(self.save_button)
        card.add_layout(tabs)

        self.description = faint_label("")
        card.add(self.description)

        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(220)
        self.editor.textChanged.connect(self._on_edited)
        card.add(self.editor)

        self.body.addWidget(card)
        self.switch_list(self._current_key)

    def switch_list(self, key: str) -> None:
        if self._dirty:
            self.save_current(silent=True)
        self._current_key = key
        item = lists_module.USER_LIST_BY_KEY[key]
        self.description.setText(item.description)
        self.editor.blockSignals(True)
        self.editor.setPlainText(lists_module.read_user_list(key))
        self.editor.blockSignals(False)
        self._dirty = False
        self.save_button.setEnabled(False)

        for button in self._tab_group.buttons():
            selected = button.text() == item.title
            button.setProperty("variant", "soft" if selected else "ghost")
            button.setChecked(selected)
            style = button.style()
            style.unpolish(button)
            style.polish(button)

    def _on_edited(self) -> None:
        self._dirty = True
        self.save_button.setEnabled(True)

    def save_current(self, silent: bool = False) -> None:
        try:
            lists_module.write_user_list(self._current_key, self.editor.toPlainText())
        except OSError as exc:
            self.context.error(f"Не удалось сохранить список: {exc}")
            return
        self._dirty = False
        self.save_button.setEnabled(False)
        if not silent:
            title = lists_module.USER_LIST_BY_KEY[self._current_key].title
            message = f"Список «{title}» сохранён"
            if self.context.status.running:
                message += ". Перезапустите обход, чтобы применить."
            self.context.ok(message)

    # --- IPSet -----------------------------------------------------------

    def _build_ipset(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.ipset_icon = IconLabel("list", self.context.color("accent"), 20)
        header.addWidget(self.ipset_icon)
        header.addWidget(section_label("Список IP-адресов (IPSet)"))
        header.addStretch(1)
        self.ipset_badge = Badge("—", "neutral")
        header.addWidget(self.ipset_badge)
        card.add_layout(header)

        card.add(faint_label(
            "Диапазоны IP заблокированных сервисов — нужны, когда домен "
            "определить нельзя, например для голосовых серверов Discord."
        ))

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.ipset_mode = QComboBox()
        for key, label in lists_module.IPSET_MODES.items():
            self.ipset_mode.addItem(label, key)
        self.ipset_mode.currentIndexChanged.connect(self._change_ipset_mode)
        controls.addWidget(self.ipset_mode)

        self.ipset_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.ipset_spinner)

        self.btn_ipset_update = Button("Обновить из GitHub", variant="soft")
        self.btn_ipset_update.clicked.connect(self._update_ipset)
        controls.addWidget(self.btn_ipset_update)
        controls.addStretch(1)
        card.add_layout(controls)

        self.body.addWidget(card)
        self._refresh_ipset()

    def _refresh_ipset(self) -> None:
        mode = lists_module.ipset_mode()
        size = lists_module.ipset_size()
        self.ipset_mode.blockSignals(True)
        index = self.ipset_mode.findData(mode)
        if index >= 0:
            self.ipset_mode.setCurrentIndex(index)
        self.ipset_mode.blockSignals(False)
        self.ipset_badge.update_state(
            f"{size} подсетей" if size else "список пуст",
            "ok" if size else "warn",
        )

    def _change_ipset_mode(self) -> None:
        mode = str(self.ipset_mode.currentData())
        try:
            lists_module.set_ipset_mode(mode)
        except (RuntimeError, OSError) as exc:
            self.context.error(str(exc))
            self._refresh_ipset()
            return
        self._refresh_ipset()
        self.context.ok(f"Режим IPSet: {lists_module.IPSET_MODES[mode]}")

    def _update_ipset(self) -> None:
        self.btn_ipset_update.setEnabled(False)
        self.ipset_spinner.start()

        worker = Worker(self)
        worker.finished.connect(self._ipset_updated)
        worker.failed.connect(self._ipset_failed)
        worker.run(lists_module.update_ipset)
        self._ipset_worker = worker

    def _ipset_updated(self, count) -> None:
        self.btn_ipset_update.setEnabled(True)
        self.ipset_spinner.stop()
        self._refresh_ipset()
        self.context.ok(f"Список IP обновлён: {count} подсетей")

    def _ipset_failed(self, message: str) -> None:
        self.btn_ipset_update.setEnabled(True)
        self.ipset_spinner.stop()
        self.context.error(message)

    # --- hosts -----------------------------------------------------------

    def _build_hosts(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.hosts_icon = IconLabel("globe", self.context.color("accent"), 20)
        header.addWidget(self.hosts_icon)
        header.addWidget(section_label("Файл hosts"))
        header.addStretch(1)
        self.hosts_badge = Badge("не проверено", "neutral")
        header.addWidget(self.hosts_badge)
        card.add_layout(header)

        card.add(faint_label(
            "Некоторым сервисам нужны фиксированные адреса в системном файле "
            "hosts. Программа добавит их отдельным блоком и сохранит копию "
            "исходного файла."
        ))

        self.hosts_message = faint_label("")
        card.add(self.hosts_message)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.hosts_spinner = Spinner(16, self.context.color("accent"))
        controls.addWidget(self.hosts_spinner)

        self.btn_hosts_check = Button("Проверить")
        self.btn_hosts_check.clicked.connect(self._check_hosts)
        controls.addWidget(self.btn_hosts_check)

        self.btn_hosts_apply = Button("Добавить записи", variant="soft")
        self.btn_hosts_apply.clicked.connect(self._apply_hosts)
        self.btn_hosts_apply.setEnabled(False)
        controls.addWidget(self.btn_hosts_apply)

        self.btn_hosts_revert = Button("Убрать записи", variant="ghost")
        self.btn_hosts_revert.clicked.connect(self._revert_hosts)
        controls.addWidget(self.btn_hosts_revert)
        controls.addStretch(1)
        card.add_layout(controls)

        self.body.addWidget(card)

    def _check_hosts(self) -> None:
        self.btn_hosts_check.setEnabled(False)
        self.hosts_spinner.start()

        worker = Worker(self)
        worker.finished.connect(self._hosts_checked)
        worker.failed.connect(self._hosts_failed)
        worker.run(lists_module.hosts_status)
        self._hosts_worker = worker

    def _hosts_checked(self, status) -> None:
        self.btn_hosts_check.setEnabled(True)
        self.hosts_spinner.stop()
        self.hosts_message.setText(status.message)
        if status.ok:
            self.hosts_badge.update_state("в порядке", "ok")
            self.btn_hosts_apply.setEnabled(False)
        else:
            self.hosts_badge.update_state("нужны записи", "warn")
            self.btn_hosts_apply.setEnabled(status.missing > 0)
        if status.conflicting:
            self.hosts_message.setText(
                status.message + " Кроме того, в hosts есть посторонние записи "
                "для YouTube — они могут мешать доступу."
            )

    def _hosts_failed(self, message: str) -> None:
        self.btn_hosts_check.setEnabled(True)
        self.hosts_spinner.stop()
        self.context.error(message)

    def _apply_hosts(self) -> None:
        self.btn_hosts_apply.setEnabled(False)
        self.hosts_spinner.start()

        worker = Worker(self)
        worker.finished.connect(self._hosts_applied)
        worker.failed.connect(self._hosts_failed)
        worker.run(lists_module.apply_hosts)
        self._hosts_worker = worker

    def _hosts_applied(self, count) -> None:
        self.hosts_spinner.stop()
        if count:
            self.context.ok(f"В hosts добавлено записей: {count}")
        else:
            self.context.ok("Всё уже на месте")
        self._check_hosts()

    def _revert_hosts(self) -> None:
        try:
            removed = lists_module.revert_hosts()
        except OSError as exc:
            self.context.error(f"Не удалось изменить hosts: {exc}")
            return
        if removed:
            self.context.ok("Записи zapret удалены из hosts")
        else:
            self.context.warn("В hosts нет записей, добавленных программой")
        self._check_hosts()

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        lists_module.ensure_user_lists()
        self.switch_list(self._current_key)
        self._refresh_ipset()

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.ipset_icon.set_color(accent)
        self.hosts_icon.set_color(accent)
        self.ipset_spinner.set_color(accent)
        self.hosts_spinner.set_color(accent)
