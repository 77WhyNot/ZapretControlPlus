"""Страница настроек: внешний вид, поведение, сеть."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from app.core import net, paths, winapi
from app.core.config import config
from app.core.constants import AUTOSTART_TASK
from app.ui import theme
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Button,
    Card,
    Divider,
    FlowLayout,
    SettingRow,
    Spinner,
    Switch,
    Worker,
    confirm,
    faint_label,
    section_label,
)


class ThemePreview(QWidget):
    """Окошко-пейзаж темы: бумага — день, ночь — луна, «как в Windows» — и то и другое."""

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui import scenes
        from app.ui.ink import SceneRenderer, scene_palette

        self.mode = mode
        light = scene_palette(theme.build_tokens("light"))
        dark = scene_palette(theme.build_tokens("dark"))
        self.day = SceneRenderer(scenes.day_card(), light)
        self.night = SceneRenderer(scenes.night_card(), dark)
        self.night.dark = True
        self.night._invalidate(rebuild_units=True)
        self._plates = (QColor(light["plate"]), QColor(dark["plate"]))
        self.setFixedHeight(92)
        self.setMinimumWidth(150)

    def frame_divider(self) -> int:
        return 2

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        from app.ui.ink import motion_level
        from app.ui.widgets import frame_clock

        for renderer in (self.day, self.night):
            renderer.motion = motion_level()
        if motion_level() != "off":
            frame_clock().subscribe(self)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        from app.ui.widgets import frame_clock

        frame_clock().unsubscribe(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath, QPolygonF
        from PySide6.QtCore import QPointF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        dpr = self.devicePixelRatioF()
        # Сцена вписывается по ширине и прижимается к низу окошка.
        scene_h = rect.width() * 90 / 160
        target = QRectF(0, rect.height() - scene_h, rect.width(), scene_h)
        parts = {"light": [(self.day, 0)], "dark": [(self.night, 1)],
                 "system": [(self.day, 0), (self.night, 1)]}[self.mode]
        for renderer, index in parts:
            painter.save()
            if self.mode == "system":
                w, h = rect.width(), rect.height()
                if index == 0:
                    polygon = [QPointF(0, 0), QPointF(w * 0.62, 0), QPointF(w * 0.38, h), QPointF(0, h)]
                else:
                    polygon = [QPointF(w * 0.62, 0), QPointF(w, 0), QPointF(w, h), QPointF(w * 0.38, h)]
                half = QPainterPath()
                half.addPolygon(QPolygonF(polygon))
                painter.setClipPath(half, Qt.ClipOperation.IntersectClip)
            painter.fillRect(rect, self._plates[index])
            renderer.paint(painter, target, dpr)
            painter.restore()
        painter.end()


class ThemeChoice(QWidget):
    """Карточка выбора темы: пейзаж, название и пара слов."""

    picked = Signal(str)

    def __init__(self, context: AppContext, key: str, title: str, text: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        self.context = context
        self.key = key
        self.selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(170)
        self.setMaximumWidth(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(6)
        self.preview = ThemePreview(key, self)
        layout.addWidget(self.preview)
        name = QLabel(title, self)
        name.setStyleSheet("font-family: 'Literata'; font-size: 17px; background: transparent;")
        layout.addWidget(name)
        hint = QLabel(text, self)
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def set_selected(self, value: bool) -> None:
        self.selected = value
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.context.color("bg" if self.selected else "card")))
        painter.drawRoundedRect(rect, 16, 16)
        pen = QPen(QColor(self.context.color("ink" if self.selected else "border")))
        pen.setWidthF(1.6 if self.selected else 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 16, 16)
        if self.selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.context.color("clay")))
            # Точка выбора — на строке названия, справа.
            painter.drawEllipse(QRectF(rect.right() - 22, 114, 8, 8))
        painter.end()


MOTION_CHOICES = (
    ("full", "Живое", "Линии дышат, листья качаются, всё прорисовывается"),
    ("calm", "Спокойное", "Без дыхания линии, покачивание вполовину"),
    ("off", "Неподвижное", "Рисунки стоят, переходы мгновенные"),
)


class SettingsPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Всё *по-своему*",
            "Тема, движение рисунков, поведение при запуске и сеть.",
            parent,
            eyebrow="Настройки",
        )
        self._switches: list[Switch] = []
        self._build_appearance()
        self._build_behaviour()
        context.theme_changed.connect(self._theme_changed_outside)
        self._build_network()
        self._build_danger()
        self.apply_theme()

    # --- внешний вид -----------------------------------------------------

    def _build_appearance(self) -> None:
        from PySide6.QtWidgets import QPushButton

        card = Card(padding=20, spacing=14)
        card.add(section_label("Бумага или ночь"))
        card.add(faint_label("Тема меняется сразу. Луна и солнце в заголовке окна "
                             "переключают её в один щелчок."))

        themes_row = FlowLayout(spacing=12)
        self.theme_cards: list[ThemeChoice] = []
        for key, title, text in theme.THEME_CHOICES:
            widget = ThemeChoice(self.context, key, title, text)
            widget.picked.connect(self._pick_theme)
            themes_row.addWidget(widget)
            self.theme_cards.append(widget)
        card.add_layout(themes_row)

        card.add(Divider())
        from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

        motion = QHBoxLayout()
        motion.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        label = QLabel("Движение рисунков")
        label.setStyleSheet("font-weight: 500;")
        texts.addWidget(label)
        self.motion_hint = faint_label("")
        texts.addWidget(self.motion_hint)
        motion.addLayout(texts, 1)
        bar = QFrame()
        bar.setObjectName("SegmentBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(3, 3, 3, 3)
        bar_layout.setSpacing(2)
        self.motion_buttons: dict[str, QPushButton] = {}
        for key, title, _text in MOTION_CHOICES:
            button = QPushButton(title, bar)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._pick_motion(k))
            bar_layout.addWidget(button)
            self.motion_buttons[key] = button
        motion.addWidget(bar, 0, Qt.AlignmentFlag.AlignVCenter)
        card.add_layout(motion)

        card.add(Divider())
        tour = QHBoxLayout()
        tour.setSpacing(10)
        tour_text = QVBoxLayout()
        tour_text.setSpacing(2)
        tour_label = QLabel("Знакомство с программой")
        tour_label.setStyleSheet("font-weight: 500;")
        tour_text.addWidget(tour_label)
        tour_text.addWidget(faint_label("Короткая прогулка по разделам — что где лежит."))
        tour.addLayout(tour_text, 1)
        btn_tour = Button("Показать снова", variant="soft")
        btn_tour.clicked.connect(self._start_tour)
        tour.addWidget(btn_tour, 0, Qt.AlignmentFlag.AlignVCenter)
        btn_news = Button("Что нового в 4.0", variant="ghost")
        btn_news.clicked.connect(self._show_news)
        tour.addWidget(btn_news, 0, Qt.AlignmentFlag.AlignVCenter)
        card.add_layout(tour)

        self.body.addWidget(card)

    def _pick_theme(self, key: str) -> None:
        if theme.normalize_theme_key(str(config.get("theme"))) == key:
            return
        config.set("theme", key)
        self._apply_theme_globally()
        self._sync_appearance()

    def _pick_motion(self, key: str) -> None:
        config.set("motion", key)
        # Сцены перечитывают уровень движения вместе с темой.
        window = self.window()
        apply_theme = getattr(window, "apply_theme", None)
        if callable(apply_theme):
            apply_theme()
        self._sync_appearance()

    def _start_tour(self) -> None:
        starter = getattr(self.window(), "start_tour", None)
        if callable(starter):
            starter()

    def _show_news(self) -> None:
        shower = getattr(self.window(), "show_whats_new", None)
        if callable(shower):
            shower()

    def _apply_theme_globally(self) -> None:
        window = self.window()
        apply_theme = (getattr(window, "apply_theme_animated", None)
                       or getattr(window, "apply_theme", None))
        if callable(apply_theme):
            apply_theme()

    def _sync_appearance(self) -> None:
        current_theme = theme.normalize_theme_key(str(config.get("theme")))
        for widget in self.theme_cards:
            widget.set_selected(widget.key == current_theme)
        motion = str(config.get("motion", "full"))
        for key, button in self.motion_buttons.items():
            button.setChecked(key == motion)
        text = next((t for k, _n, t in MOTION_CHOICES if k == motion), "")
        from app.ui.ink import system_motion_enabled

        if not system_motion_enabled():
            text += ". Сейчас анимации выключены в Windows — рисунки стоят."
        self.motion_hint.setText(text)

    # --- поведение -------------------------------------------------------

    def _add_switch(self, card: Card, key: str, title: str, description: str,
                    on_change=None) -> Switch:
        switch = Switch(bool(config.get(key)))

        def handler(value: bool) -> None:
            config.set(key, value)
            if on_change is not None:
                on_change(value)

        switch.toggled.connect(handler)
        card.add(SettingRow(title, description, switch))
        self._switches.append(switch)
        return switch

    def _build_behaviour(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Поведение"))

        self._add_switch(
            card, "close_to_tray", "Сворачивать в трей при закрытии",
            "Крестик прячет окно, а программа продолжает работать рядом с часами.",
        )
        card.add(Divider())

        self._add_switch(
            card, "autostart_app", "Запускать вместе с Windows",
            "Создаётся задача планировщика с правами администратора, "
            "поэтому окно UAC при входе появляться не будет.",
            on_change=self._toggle_autostart,
        )
        card.add(Divider())

        self._add_switch(
            card, "start_minimized", "Запускаться свёрнутым в трей",
            "Окно не появится на экране — программа сразу уйдёт в трей.",
        )
        card.add(Divider())

        self._add_switch(
            card, "autorun_last_strategy", "Включать обход при запуске",
            "Последняя выбранная стратегия стартует автоматически. "
            "Для постоянной работы надёжнее режим службы.",
        )
        card.add(Divider())

        self._add_switch(
            card, "confirm_exit_while_running", "Спрашивать при выходе",
            "Предупреждать, если обход работает в режиме процесса и остановится.",
        )
        card.add(Divider())

        self._add_switch(
            card, "pause_zapret_with_vpn", "Уступать дорогу стороннему VPN",
            "Пока поднят чужой туннель (Happ, Hiddify, WireGuard), обход "
            "снимается сам, а после выключения VPN возвращается. Через "
            "туннель трафик и так идёт мимо блокировок, а обход правит "
            "пакеты уже на входе в него — из-за этого VPN может рваться.",
        )
        card.add(Divider())

        self._add_switch(
            card, "warn_about_vpn", "Предупреждать о включённом VPN",
            "Показывать плашку, когда обнаружен сторонний туннель.",
        )
        card.add(Divider())

        self._add_switch(
            card, "diagnostics_autorun", "Запускать диагностику автоматически",
            "Проверки стартуют при первом открытии вкладки «Диагностика».",
        )

        self.body.addWidget(card)

    def _toggle_autostart(self, enabled: bool) -> None:
        import sys

        if not getattr(sys, "frozen", False):
            self.context.warn(
                "Автозапуск настраивается только в установленной версии программы."
            )
            return
        if enabled:
            ok, message = winapi.autostart_enable(
                AUTOSTART_TASK, sys.executable, "--tray"
            )
            if ok:
                self.context.ok("Автозапуск включён")
            else:
                config.set("autostart_app", False)
                self.context.error(f"Не удалось создать задачу автозапуска. {message}")
        else:
            winapi.autostart_disable(AUTOSTART_TASK)
            self.context.ok("Автозапуск выключен")

    # --- сеть ------------------------------------------------------------

    def _build_network(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Сеть и доступ к GitHub"))
        card.add(faint_label(
            "Обновления скачиваются с GitHub. Если он заблокирован, программа "
            "сама переберёт зеркала. Здесь можно задать прокси вручную."
        ))

        self.switch_proxy = Switch(bool(config.get("use_system_proxy", True)))
        self.switch_proxy.toggled.connect(
            lambda value: config.set("use_system_proxy", value)
        )
        self._switches.append(self.switch_proxy)
        card.add(SettingRow(
            "Использовать системный прокси",
            "Берём настройки прокси из Windows и переменных окружения.",
            self.switch_proxy,
        ))
        card.add(Divider())

        proxy_row = QHBoxLayout()
        proxy_row.setSpacing(10)
        self.proxy_input = QLineEdit(str(config.get("custom_proxy", "")))
        self.proxy_input.setPlaceholderText("http://127.0.0.1:8080 — оставьте пустым, если не нужен")
        self.proxy_input.editingFinished.connect(self._save_proxy)
        proxy_row.addWidget(self.proxy_input, 1)

        self.net_spinner = Spinner(16, self.context.color("accent"))
        proxy_row.addWidget(self.net_spinner)

        self.btn_test_net = Button("Проверить связь", variant="soft")
        self.btn_test_net.clicked.connect(self._test_connection)
        proxy_row.addWidget(self.btn_test_net)
        card.add_layout(proxy_row)

        self.net_status = faint_label(f"Текущий режим: {net.connectivity_hint()}.")
        card.add(self.net_status)

        self.body.addWidget(card)

    def _save_proxy(self) -> None:
        value = self.proxy_input.text().strip()
        if config.get("custom_proxy", "") == value:
            return
        config.set("custom_proxy", value)
        self.net_status.setText(f"Текущий режим: {net.connectivity_hint()}.")
        self.context.ok("Настройки прокси сохранены")

    def _test_connection(self) -> None:
        self.btn_test_net.setEnabled(False)
        self.net_spinner.start()
        self.net_status.setText("Проверяем доступ к GitHub…")

        from app.core.constants import UPSTREAM_REPO, UPSTREAM_VERSION_PATH

        url = (
            f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/main/"
            f"{UPSTREAM_VERSION_PATH}"
        )

        worker = Worker(self)
        worker.finished.connect(self._connection_ok)
        worker.failed.connect(self._connection_failed)
        worker.run(net.fetch_text, url)
        self._net_worker = worker

    def _connection_ok(self, payload) -> None:
        self.btn_test_net.setEnabled(True)
        self.net_spinner.stop()
        mirror = str(config.get("preferred_mirror", "")) or "direct"
        titles = {item.key: item.title for item in net.MIRRORS}
        titles["jsdelivr"] = "cdn.jsdelivr.net"
        self.net_status.setText(
            f"Связь есть. Сработал канал: {titles.get(mirror, mirror)}. "
            f"Версия ядра на сервере: {str(payload).strip()}."
        )
        self.context.ok("GitHub доступен")

    def _connection_failed(self, message: str) -> None:
        self.btn_test_net.setEnabled(True)
        self.net_spinner.stop()
        self.net_status.setText(message)
        self.context.error("GitHub недоступен ни напрямую, ни через зеркала")

    # --- сервис ----------------------------------------------------------

    def _build_danger(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add(section_label("Служебное"))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        btn_folder = Button("Папка с настройками", variant="ghost")
        btn_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))
        )
        buttons.addWidget(btn_folder)

        btn_core = Button("Папка ядра zapret", variant="ghost")
        btn_core.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.core_dir())))
        )
        buttons.addWidget(btn_core)

        btn_reset = Button("Сбросить настройки", variant="ghost")
        btn_reset.clicked.connect(self._reset)
        buttons.addWidget(btn_reset)
        buttons.addStretch(1)
        card.add_layout(buttons)

        self.body.addWidget(card)

    def _reset(self) -> None:
        if not confirm(
            self,
            "Сброс настроек",
            "Вернуть все настройки программы к значениям по умолчанию?\n"
            "Списки доменов и ядро zapret не пострадают.",
            yes="Сбросить", no="Отмена", default_yes=False,
        ):
            return
        config.reset()
        self._apply_theme_globally()
        self.on_activate()
        self.context.ok("Настройки сброшены")

    # --- страница --------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_appearance()

    def _theme_changed_outside(self) -> None:
        """Тему сменили кнопкой в заголовке — карточки должны это показать."""
        if hasattr(self, "theme_cards"):
            self._sync_appearance()
        self.proxy_input.setText(str(config.get("custom_proxy", "")))
        self.net_status.setText(f"Текущий режим: {net.connectivity_hint()}.")

    def apply_theme(self) -> None:
        if hasattr(self, "theme_cards"):
            self._sync_appearance()
        if hasattr(self, "net_spinner"):
            self.net_spinner.set_color(self.context.color("accent"))
