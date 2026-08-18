"""Главное окно: безрамочное, с боковым меню и системным треем."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPoint,
    QRect,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.core import logs, paths, updater
from app.core.config import config
from app.core.constants import APP_NAME, APP_VERSION
from app.core.engine import MODE_SERVICE, engine
from app.ui import icons
from app.ui.context import AppContext
from app.ui.pages.about import AboutPage
from app.ui.pages.diagnostics import DiagnosticsPage
from app.ui.pages.dns import DnsPage
from app.ui.pages.home import HomePage
from app.ui.pages.lists import ListsPage
from app.ui.pages.servers import ServersPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.strategies import StrategiesPage
from app.ui.pages.updates import UpdatesPage
from app.ui.pages.vpnapps import VpnAppsPage
from app.ui.widgets import IconLabel, Toast

# --- нативные константы --------------------------------------------------

WM_NCHITTEST = 0x0084
WM_GETMINMAXINFO = 0x0024
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 13, 14, 15, 16, 17
MONITOR_DEFAULTTONEAREST = 2
RESIZE_BORDER = 6
TITLE_HEIGHT = 46


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", POINT), ("ptMaxSize", POINT), ("ptMaxPosition", POINT),
        ("ptMinTrackSize", POINT), ("ptMaxTrackSize", POINT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
    ]


PAGES = (
    ("home", "Маршруты", "shield_check"),
    ("servers", "Серверы", "globe"),
    ("vpnapps", "Приложения", "layers"),
    ("dns", "DNS", "bolt"),
    ("strategies", "Стратегии", "refresh"),
    ("lists", "Списки", "list"),
    ("diagnostics", "Диагностика", "stethoscope"),
    ("updates", "Обновления", "download"),
    ("settings", "Настройки", "settings"),
    ("about", "О программе", "info"),
)


class TitleBar(QWidget):
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(TITLE_HEIGHT)
        self.context = context

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        self.logo = IconLabel("shield_check", context.color("accent"), 22, self)
        layout.addWidget(self.logo)

        title = QLabel(APP_NAME)
        title.setObjectName("TitleText")
        layout.addWidget(title)

        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("TitleVersion")
        layout.addWidget(version)

        self.state_label = QLabel("")
        self.state_label.setObjectName("Faint")
        layout.addSpacing(8)
        layout.addWidget(self.state_label)

        layout.addStretch(1)

        self.btn_min = self._window_button("minimize", "WinButton")
        self.btn_max = self._window_button("maximize", "WinButton")
        self.btn_close = self._window_button("close", "WinClose")
        self.btn_min.clicked.connect(self.minimize_requested.emit)
        self.btn_max.clicked.connect(self.maximize_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)
        for button in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(button)

        context.theme_changed.connect(self.apply_theme)
        context.status_changed.connect(self._on_status)

    def _window_button(self, icon_name: str, object_name: str) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName(object_name)
        button.setProperty("iconName", icon_name)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setIcon(icons.icon(icon_name, self.context.color("text_dim"), 16))
        return button

    def apply_theme(self) -> None:
        self.logo.set_color(self.context.color("accent"))
        for button in (self.btn_min, self.btn_max, self.btn_close):
            name = str(button.property("iconName"))
            button.setIcon(icons.icon(name, self.context.color("text_dim"), 16))

    def set_maximized(self, maximized: bool) -> None:
        name = "restore" if maximized else "maximize"
        self.btn_max.setProperty("iconName", name)
        self.btn_max.setIcon(icons.icon(name, self.context.color("text_dim"), 16))

    def _on_status(self, status) -> None:
        if status.running:
            self.state_label.setText(f"● обход активен — {status.mode_label}")
        else:
            self.state_label.setText("○ обход выключен")

    def is_drag_zone(self, position: QPoint) -> bool:
        child = self.childAt(position)
        return not isinstance(child, QPushButton)


class NavButton(QPushButton):
    def __init__(self, key: str, title: str, icon_name: str,
                 context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setObjectName("NavButton")
        self.key = key
        self.icon_name = icon_name
        self.context = context
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.apply_theme()

    def apply_theme(self) -> None:
        color = (
            self.context.color("accent_text") if self.isChecked()
            else self.context.color("text_dim")
        )
        self.setIcon(icons.icon(self.icon_name, color, 18))
        self.setIconSize(icons.icon_size(18))


class MainWindow(QWidget):
    def __init__(self, on_progress=None) -> None:
        super().__init__()
        self._on_progress = on_progress or (lambda text, value: None)
        self.context = AppContext()
        self._force_quit = False

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 660)
        self.resize(1180, 760)

        self._build_ui()
        self._build_tray()
        self.apply_theme()

        self.context.notify.connect(self._show_toast)
        self.context.navigate.connect(self.show_page)
        engine.on_state_change = self._engine_changed

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_state)
        self._poll.start(2500)
        QTimer.singleShot(150, lambda: self._poll_state(force=True))
        QTimer.singleShot(2500, self._startup_tasks)

        self._restore_geometry()

    # --- построение ------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.root = QWidget(self)
        self.root.setObjectName("Root")
        outer.addWidget(self.root)

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(1, 1, 1, 1)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self.context, self.root)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self.toggle_maximize)
        self.title_bar.close_requested.connect(self.close)
        root_layout.addWidget(self.title_bar)

        body = QWidget(self.root)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, 1)

        self.sidebar = QWidget(body)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(212)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 14, 10, 14)
        sidebar_layout.setSpacing(3)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, NavButton] = {}

        # Полоска, которая едет к выбранному пункту.
        self.nav_marker = QWidget(self.sidebar)
        self.nav_marker.setFixedWidth(3)
        self.nav_marker.hide()
        self._marker_animation = QPropertyAnimation(self.nav_marker, b"geometry", self)
        self._marker_animation.setDuration(220)
        self._marker_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.pages = QStackedWidget(body)
        self.pages.setObjectName("Content")
        self.page_widgets: dict[str, QWidget] = {}

        # Страницы строятся при первом открытии: собирать все десять на старте
        # долго, и окно успевало показаться недостроенным.
        self._factories = {
            "home": HomePage,
            "servers": ServersPage,
            "vpnapps": VpnAppsPage,
            "dns": DnsPage,
            "strategies": StrategiesPage,
            "lists": ListsPage,
            "diagnostics": DiagnosticsPage,
            "updates": UpdatesPage,
            "settings": SettingsPage,
            "about": AboutPage,
        }
        for key, title, icon_name in PAGES:
            if key == "settings":
                sidebar_layout.addStretch(1)
            button = NavButton(key, title, icon_name, self.context, self.sidebar)
            button.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(button)
            sidebar_layout.addWidget(button)
            self.nav_buttons[key] = button

        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.pages, 1)

        self.toast = Toast(self)
        self.show_page("home")

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._tray_activated)

        menu = QMenu(self)
        self.action_show = QAction("Открыть", self)
        self.action_show.triggered.connect(self.show_normal)
        self.action_toggle = QAction("Запустить обход", self)
        self.action_toggle.triggered.connect(self._tray_toggle)
        action_quit = QAction("Выход", self)
        action_quit.triggered.connect(self.quit_app)

        menu.addAction(self.action_show)
        menu.addAction(self.action_toggle)
        menu.addSeparator()
        menu.addAction(action_quit)
        self.tray.setContextMenu(menu)
        # Иконку ставим до show(): иначе Qt пишет «No Icon set».
        self.tray.setIcon(self._app_icon())
        self.tray.show()

        self.context.status_changed.connect(self._update_tray)

    # --- тема ------------------------------------------------------------

    def apply_theme(self) -> None:
        from app.ui import appicons, icons as icon_cache

        # Цвета изменились — кэш нарисованных иконок больше не годится.
        icon_cache.clear_cache()
        appicons.clear_cache()

        qss = self.context.rebuild_theme()

        # Стиль вешаем на окно, а не на приложение: QApplication.setStyleSheet
        # перекрашивает вообще всё дерево и занимает больше секунды, окно —
        # втрое быстрее. Меню трея для этого сделано дочерним к окну.
        self.setUpdatesEnabled(False)
        try:
            self.setStyleSheet(qss)
        finally:
            self.setUpdatesEnabled(True)
        for button in self.nav_buttons.values():
            button.apply_theme()
        marker = getattr(self, 'nav_marker', None)
        if marker is not None and marker.isVisible():
            marker.setStyleSheet(
                f"background: {self.context.color('accent')}; border-radius: 1px;"
            )
        self._update_window_icon()

    def _update_window_icon(self) -> None:
        window_icon = self._app_icon()
        self.setWindowIcon(window_icon)
        self.tray.setIcon(window_icon)

    def _app_icon(self) -> QIcon:
        ico = paths.resource_path("icon.ico")
        if ico.exists():
            return QIcon(str(ico))
        return icons.icon("shield_check", self.context.color("accent"), 64)

    # --- навигация -------------------------------------------------------

    def ensure_page(self, key: str) -> QWidget | None:
        """Создать страницу, если её ещё нет.

        Родителем сразу назначаем контейнер страниц: виджет без родителя Qt
        считает окном и успевает мигнуть им на экране при первом открытии.
        """
        widget = self.page_widgets.get(key)
        if widget is not None:
            return widget
        factory = self._factories.get(key)
        if factory is None:
            return None
        widget = factory(self.context, self.pages)
        widget.hide()
        self.page_widgets[key] = widget
        self.pages.addWidget(widget)
        return widget

    def build_all_pages(self) -> None:
        """Собрать все страницы заранее — под заставкой, а не при первом клике."""
        total = len(PAGES)
        for index, (key, title, _icon) in enumerate(PAGES, start=1):
            self._on_progress(f"Готовим «{title}»…", 0.45 + 0.5 * index / total)
            self.ensure_page(key)

    def show_page(self, key: str) -> None:
        widget = self.ensure_page(key)
        if widget is None:
            return
        changed = self.pages.currentWidget() is not widget
        self.pages.setCurrentWidget(widget)
        if changed:
            self._fade_in(widget)
        for nav_key, button in self.nav_buttons.items():
            button.setChecked(nav_key == key)
            button.apply_theme()
        self._move_marker(key)
        activate = getattr(widget, "on_activate", None)
        if callable(activate):
            activate()

    def _move_marker(self, key: str) -> None:
        """Подвинуть полоску к выбранному пункту меню."""
        button = self.nav_buttons.get(key)
        if button is None:
            return
        target = QRect(2, button.y() + 8, 3, max(button.height() - 16, 8))
        self.nav_marker.setStyleSheet(
            f"background: {self.context.color('accent')}; border-radius: 1px;"
        )
        if not self.nav_marker.isVisible():
            self.nav_marker.setGeometry(target)
            self.nav_marker.show()
            self.nav_marker.raise_()
            return
        self._marker_animation.stop()
        self._marker_animation.setStartValue(self.nav_marker.geometry())
        self._marker_animation.setEndValue(target)
        self._marker_animation.start()
        self.nav_marker.raise_()

    def _fade_in(self, widget: QWidget) -> None:
        """Короткое проявление страницы вместо резкой подмены."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(140)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Эффект снимаем сразу после показа: он рисует виджет через буфер
        # и без нужды замедляет прокрутку.
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # --- окно ------------------------------------------------------------

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.title_bar.set_maximized(self.isMaximized())

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast._reposition()

    def nativeEvent(self, event_type: QByteArray, message) -> tuple[bool, int]:  # noqa: N802
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0

        if msg.message == WM_NCHITTEST:
            return self._hit_test()
        if msg.message == WM_GETMINMAXINFO:
            self._fix_maximized_bounds(msg)
            return False, 0
        return False, 0

    def _hit_test(self) -> tuple[bool, int]:
        position = self.mapFromGlobal(QCursor.pos())
        x, y = position.x(), position.y()
        width, height = self.width(), self.height()

        if not self.isMaximized():
            left = x <= RESIZE_BORDER
            right = x >= width - RESIZE_BORDER
            top = y <= RESIZE_BORDER
            bottom = y >= height - RESIZE_BORDER
            if top and left:
                return True, HTTOPLEFT
            if top and right:
                return True, HTTOPRIGHT
            if bottom and left:
                return True, HTBOTTOMLEFT
            if bottom and right:
                return True, HTBOTTOMRIGHT
            if left:
                return True, HTLEFT
            if right:
                return True, HTRIGHT
            if top:
                return True, HTTOP
            if bottom:
                return True, HTBOTTOM

        if y < TITLE_HEIGHT:
            local = self.title_bar.mapFrom(self, position)
            if self.title_bar.is_drag_zone(local):
                return True, HTCAPTION
        return True, HTCLIENT

    def _fix_maximized_bounds(self, msg) -> None:
        """Без этого развёрнутое безрамочное окно накрывает панель задач."""
        try:
            monitor = ctypes.windll.user32.MonitorFromWindow(
                wintypes.HWND(int(self.winId())), MONITOR_DEFAULTTONEAREST
            )
            if not monitor:
                return
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if not ctypes.windll.user32.GetMonitorInfoW(
                wintypes.HMONITOR(monitor), ctypes.byref(info)
            ):
                return
            work, screen = info.rcWork, info.rcMonitor
            data = MINMAXINFO.from_address(int(msg.lParam))
            data.ptMaxPosition.x = work.left - screen.left
            data.ptMaxPosition.y = work.top - screen.top
            data.ptMaxSize.x = work.right - work.left
            data.ptMaxSize.y = work.bottom - work.top
            data.ptMaxTrackSize.x = work.right - work.left
            data.ptMaxTrackSize.y = work.bottom - work.top
        except (OSError, ValueError, AttributeError):
            return

    # --- трей ------------------------------------------------------------

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_normal()

    def show_normal(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_toggle(self) -> None:
        home = self.ensure_page("home")
        toggle = getattr(home, "toggle_bypass", None)
        if callable(toggle):
            toggle()

    def _update_tray(self, status) -> None:
        if status.running:
            self.action_toggle.setText("Остановить обход")
            self.tray.setToolTip(f"{APP_NAME} — обход активен ({status.mode_label})")
        else:
            self.action_toggle.setText("Запустить обход")
            self.tray.setToolTip(f"{APP_NAME} — обход выключен")

    def _poll_state(self, force: bool = False) -> None:
        self.context.refresh_status(force=force)
        self.context.refresh_vpn_status(force=force)

    def _engine_changed(self) -> None:
        QTimer.singleShot(0, lambda: self._poll_state(force=True))

    # --- уведомления -----------------------------------------------------

    def _show_toast(self, text: str, kind: str) -> None:
        self.toast.show_message(text, kind, self.context.tokens)

    # --- запуск и завершение ---------------------------------------------

    def _startup_tasks(self) -> None:
        updates_page = self.ensure_page("updates")
        if config.get("check_core_updates", True) and updater.is_check_due():
            checker = getattr(updates_page, "check_silently", None)
            if callable(checker):
                checker()
        if config.get("autorun_last_strategy", False) and not self.context.status.running:
            home = self.ensure_page("home")
            starter = getattr(home, "start_bypass", None)
            if callable(starter):
                starter()

    def _restore_geometry(self) -> None:
        saved = str(config.get("window_geometry", ""))
        if not saved:
            self._center()
            return
        try:
            values = [int(part) for part in saved.split(",")]
            if len(values) == 4:
                screen = QGuiApplication.primaryScreen()
                available = screen.availableGeometry() if screen else None
                self.setGeometry(*values)
                if available is not None and not available.intersects(self.geometry()):
                    self._center()
                return
        except (ValueError, TypeError):
            pass
        self._center()

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(
            available.center().x() - self.width() // 2,
            available.center().y() - self.height() // 2,
        )

    def _save_geometry(self) -> None:
        if self.isMaximized() or self.isMinimized():
            return
        rect = self.geometry()
        config.set(
            "window_geometry",
            f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        if self._force_quit:
            event.accept()
            return
        if config.get("close_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                "Программа свёрнута в трей и продолжает работать.",
                self._app_icon(),
                3000,
            )
            return
        self.quit_app()
        event.accept()

    def quit_app(self) -> None:
        status = self.context.status
        keep_running = status.running and status.mode == MODE_SERVICE
        if (
            status.running
            and not keep_running
            and config.get("confirm_exit_while_running", True)
        ):
            answer = QMessageBox.question(
                self,
                "Выход",
                "Обход работает в режиме процесса и остановится вместе с программой.\n\n"
                "Чтобы обход работал всегда, переключитесь на режим службы "
                "на вкладке «Стратегии».\n\nВыйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._force_quit = True
        self._save_geometry()
        logs.info("Выход из приложения")
        engine.shutdown(stop_running=False)
        self.tray.hide()
        application = QApplication.instance()
        if application is not None:
            application.quit()
