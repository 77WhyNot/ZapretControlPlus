"""Вкладка «Google»: Gemini, AI Studio и Antigravity.

Здесь собрано всё, что программа может сделать со своей стороны — маршрут,
DNS и запуск Antigravity через VPN, — и честно сказано то, чего сеть не
решает: страна самого аккаунта Google.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core import google
from app.core.config import config
from app.core.vpn import apps as apps_module
from app.core.vpn import config as vpn_config
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.widgets import (
    clear_layout,
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


class GooglePage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context,
            "Google",
            "Gemini, AI Studio и Antigravity Google выдаёт по стране — и смотрит "
            "не только на адрес, но и на сам аккаунт. Всё, что зависит от сети, "
            "программа берёт на себя.",
            parent,
        )
        self._check_worker: Worker | None = None
        self._launch_worker: Worker | None = None

        self._build_antigravity()
        self._build_route()
        self._build_check()
        self._build_account()
        self.apply_theme()

    # --- Antigravity -------------------------------------------------------

    def _build_antigravity(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.ag_icon = IconLabel("sparkles", self.context.color("accent"), 20)
        header.addWidget(self.ag_icon)
        header.addWidget(section_label("Google Antigravity"))
        header.addStretch(1)
        self.ag_badge = Badge("не найден", "neutral")
        header.addWidget(self.ag_badge)
        card.add_layout(header)

        card.add(muted_label(
            "Внутри Antigravity работает языковой сервер на Go, а программы на Go "
            "не читают системный прокси Windows — только переменные окружения. "
            "Поэтому окно открывается, а модели молчат. Кнопка ниже запускает "
            "Antigravity так, что его серверная часть идёт через ваш VPN."
        ))

        self.ag_status = faint_label("")
        card.add(self.ag_status)

        # Самый частый случай «User location is not supported».
        self.ag_proxy_banner = Banner(
            self.context, "warning",
            "VPN сейчас работает как прокси. Antigravity, открытый обычным "
            "ярлыком, пойдёт мимо VPN — Google увидит Россию. Запускайте его "
            "кнопкой ниже или переключите VPN на «Туннель».",
            kind="warn",
        )
        card.add(self.ag_proxy_banner)
        self.ag_proxy_banner.setVisible(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_launch = Button("Запустить через VPN", variant="primary",
                                 icon_name="play", icon_color="#FFFFFF")
        self.btn_launch.clicked.connect(self._launch)
        buttons.addWidget(self.btn_launch)

        self.btn_apps = Button("Добавить в список VPN", variant="soft")
        self.btn_apps.clicked.connect(self._add_to_vpn_apps)
        buttons.addWidget(self.btn_apps)

        self.btn_diag = Button("Почему не работает", variant="ghost")
        self.btn_diag.clicked.connect(self._diagnose)
        buttons.addWidget(self.btn_diag)
        buttons.addStretch(1)
        card.add_layout(buttons)

        self.ag_verdict = Banner(self.context, "info", "", kind="info")
        card.add(self.ag_verdict)
        self.ag_verdict.setVisible(False)

        self.ag_detail = faint_label("")
        card.add(self.ag_detail)
        self.ag_detail.setVisible(False)

        self.body.addWidget(card)

    def _launch(self) -> None:
        from app.core.vpn.engine import vpn_engine
        from app.ui import vpn_actions

        proxy_url = vpn_engine.local_proxy_url()
        if proxy_url is None:
            self.context.warn(
                "Сначала включите VPN на вкладке «VPN» — иначе запускать "
                "Antigravity через него не через что."
            )
            self.context.navigate.emit("vpnconnect")
            return
        if not bool(config.get("google_launch_via_vpn", True)):
            proxy_url = None

        worker = Worker(self)
        worker.finished.connect(lambda message: self._launched(str(message)))
        worker.failed.connect(self._launch_failed)
        worker.run(google.launch, proxy_url)
        self._launch_worker = worker
        transport = vpn_actions.transport()
        self.ag_status.setText(
            "Запускаю Antigravity через "
            + ("служебный вход туннеля…" if transport == vpn_config.TRANSPORT_TUN
               else "локальный прокси VPN…")
        )

    def _launched(self, message: str) -> None:
        self.context.ok(message)
        self._sync_antigravity()

    def _launch_failed(self, message: str) -> None:
        self.context.error(message)
        self.ag_status.setText(message)

    def _add_to_vpn_apps(self) -> None:
        """Языковой сервер — отдельный процесс, без него «выбранные» не помогут."""
        names = list(config.get("vpn_apps", []) or [])
        added = [name for name in google.PROCESSES
                 if name.lower() not in {item.lower() for item in names}]
        if not added:
            self.context.ok("Antigravity уже в списке программ VPN.")
            return
        config.set("vpn_apps", apps_module.normalize(names + added))
        self.context.ok("Antigravity добавлен в список программ VPN: "
                        + ", ".join(added))
        from app.ui import vpn_actions

        self._apps_worker = vpn_actions.restart_if_running(
            self, self.context, "Список программ изменён"
        )

    def _diagnose(self) -> None:
        verdict = google.diagnose_log()
        kinds = {"account": "warn", "location": "warn", "network": "warn",
                 "ok": "ok", "unknown": "info"}
        self.ag_verdict.set_kind(kinds.get(verdict.kind, "info"))
        self.ag_verdict.set_text(verdict.message)
        self.ag_verdict.setVisible(True)
        self.ag_detail.setText(
            f"Из журнала Antigravity: {verdict.detail}" if verdict.detail else ""
        )
        self.ag_detail.setVisible(bool(verdict.detail))
        if verdict.kind == "account":
            self.account_more.set_expanded(True)

    def _sync_antigravity(self) -> None:
        from app.core.vpn.engine import vpn_engine
        from app.ui import vpn_actions

        status = vpn_engine.status()
        self.ag_proxy_banner.setVisible(
            status.running and vpn_actions.transport() == vpn_config.TRANSPORT_PROXY
        )
        app = google.find_app()
        if app is None:
            self.ag_badge.update_state("не найден", "neutral")
            self.ag_status.setText(
                "Antigravity на компьютере не найден. Скачать можно на "
                "antigravity.google — кнопка ниже."
            )
            self.btn_launch.setEnabled(False)
            self.btn_apps.setEnabled(False)
            return

        running = google.is_running()
        self.ag_badge.update_state("запущен" if running else "установлен",
                                   "ok" if running else "accent")
        self.btn_launch.setEnabled(True)
        self.btn_apps.setEnabled(True)
        release = google.version()
        self.ag_status.setText(
            f"Найден: {app} {('· версия ' + release) if release else ''}"
            + ("\nСейчас запущен — чтобы перезапустить через VPN, закройте его полностью."
               if running else "")
        )

    # --- маршрут -----------------------------------------------------------

    def _build_route(self) -> None:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Маршрут для сервисов Google"))

        self.switch_route = Switch(bool(config.get("google_route_vpn", True)))
        self.switch_route.toggled.connect(self._toggle_route)
        card.add(SettingRow(
            "Google всегда через VPN",
            "Домены Gemini, AI Studio, Antigravity и googleapis.com идут через "
            "туннель в любом режиме — даже если в VPN отправлены только "
            "отдельные программы. Имена этих сайтов тоже спрашиваются через "
            "туннель, иначе провайдер приводит нас на российские узлы Google. "
            "YouTube и остальной Google это не затрагивает.",
            self.switch_route,
        ))
        card.add(Divider())
        card.add(faint_label(
            "Smart DNS на вкладке «Smart DNS» отвечает за имена Xbox и другие "
            "сервисы — с этим переключателем он не спорит: для доменов Google "
            "имя берётся через VPN, остальное остаётся как было."
        ))
        self.body.addWidget(card)

    def _toggle_route(self, value: bool) -> None:
        config.set("google_route_vpn", value)
        self.context.ok("Google идёт через VPN" if value
                        else "Google идёт общим правилом")
        from app.ui import vpn_actions

        self._route_worker = vpn_actions.restart_if_running(
            self, self.context, "Маршрут Google изменён"
        )

    # --- проверка ----------------------------------------------------------

    def _build_check(self) -> None:
        card = Card(padding=20, spacing=12)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Проверка"))
        header.addStretch(1)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.check_spinner)
        self.btn_check = Button("Проверить Google", variant="primary")
        self.btn_check.clicked.connect(self._run_check)
        header.addWidget(self.btn_check)
        card.add_layout(header)

        card.add(faint_label(
            "Программа проверит все пути, которыми запросы уходят к Google: в "
            "какой стране выходит VPN, какой выход движок на деле даёт запросам "
            "к серверам Gemini и Antigravity и не утекает ли что-то по IPv6. "
            "Протечь может любой — тогда Google отвечает «User location is not "
            "supported»."
        ))

        self.check_verdict = Banner(self.context, "info", "", kind="info")
        card.add(self.check_verdict)
        self.check_verdict.setVisible(False)

        self.check_host = QWidget()
        self.check_layout = QVBoxLayout(self.check_host)
        self.check_layout.setContentsMargins(0, 0, 0, 0)
        self.check_layout.setSpacing(6)
        card.add(self.check_host)

        self.body.addWidget(card)

    def _run_check(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        from app.core.vpn.engine import vpn_engine
        from app.ui import vpn_actions

        clear_layout(self.check_layout)
        self.btn_check.setEnabled(False)
        self.check_spinner.start()
        worker = Worker(self)
        worker.finished.connect(self._check_ready)
        worker.failed.connect(self._check_failed)
        worker.run(google.check, vpn_engine.proxy_url(),
                   vpn_engine.status().running, vpn_actions.transport(),
                   bool(config.get("vpn_ipv6", False)))
        self._check_worker = worker

    def _check_failed(self, message: str) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(f"Проверка не прошла: {message}")

    def _check_ready(self, result: google.GoogleCheck) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        clear_layout(self.check_layout)

        self.check_layout.addWidget(self._line(
            result.country_ok is True,
            f"Выход VPN{(': ' + result.exit_ip) if result.exit_ip else ''}",
            result.country_note,
        ))
        self.check_layout.addWidget(self._line(
            result.route_ok is True, "Маршрут к Google", result.route_note,
        ))
        self.check_layout.addWidget(self._line(
            result.ipv6_ok is not False, "IPv6", result.ipv6_note,
        ))
        for title, ok, note in result.hosts:
            self.check_layout.addWidget(self._line(ok, title, note))

        self.check_verdict.set_kind("ok" if result.verdict_ok else "warn")
        self.check_verdict.set_text(result.verdict)
        self.check_verdict.setVisible(True)
        (self.context.ok if result.verdict_ok else self.context.warn)(result.verdict)

    def _line(self, ok: bool, title: str, note: str) -> QWidget:
        row = QWidget(self.check_host)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(IconLabel(
            "check" if ok else "cross",
            self.context.color("success" if ok else "danger"), 15, row,
        ))
        label = QLabel(title, row)
        label.setStyleSheet("font-weight: 600;")
        layout.addWidget(label)
        if note:
            hint = faint_label(note)
            layout.addWidget(hint, 1)
        layout.addStretch(0 if note else 1)
        return row

    # --- страна аккаунта ---------------------------------------------------

    def _build_account(self) -> None:
        self.account_more = Collapsible("Google всё равно отказывает", self.context)
        self.account_more.set_hint("страна аккаунта · ссылки")

        card = Card(padding=20, spacing=12)
        card.add(muted_label(
            "Если в журнале Antigravity написано «your current account is not "
            "eligible … not available in your location», сеть уже ни при чём: "
            "запрос дошёл до Google, и он отказал самому аккаунту. Google "
            "смотрит на страну аккаунта — её задаёт платёжный профиль, а не VPN."
        ))
        card.add(faint_label(
            "Что помогает: сменить страну в платёжном профиле Google (страна "
            "меняется не мгновенно и не всегда), либо войти аккаунтом, "
            "привязанным к поддерживаемой стране. Держите при этом VPN "
            "включённым — вход из России сбрасывает страну обратно."
        ))
        card.add(Divider())

        links = QHBoxLayout()
        links.setSpacing(10)
        for title, url in (
            ("Страна аккаунта Google", google.LINK_ACCOUNT_COUNTRY),
            ("Где сервис доступен", google.LINK_AVAILABILITY),
            ("Скачать Antigravity", google.LINK_ANTIGRAVITY),
        ):
            button = Button(title, variant="ghost")
            button.clicked.connect(
                lambda _=False, link=url: QDesktopServices.openUrl(QUrl(link))
            )
            links.addWidget(button)
        links.addStretch(1)
        card.add_layout(links)

        card.add(Divider())
        card.add(faint_label(
            "В сети есть сторонние патчеры, которые снимают проверку страны "
            "внутри самого Antigravity. Мы их не встраиваем: они правят чужую "
            "программу, слетают после каждого обновления и попадают под "
            "антивирус. Если решитесь — ищите их сами и на свой страх и риск."
        ))
        self.account_more.body.addWidget(card)
        self.body.addWidget(self.account_more)

    # --- страница ----------------------------------------------------------

    def on_activate(self) -> None:
        self._sync_antigravity()
        self.switch_route.setChecked(
            bool(config.get("google_route_vpn", True)), animate=False
        )

    def apply_theme(self) -> None:
        accent = self.context.color("accent")
        self.ag_icon.set_color(accent)
        self.check_spinner.set_color(accent)
        for switch in (self.switch_route,):
            switch.set_colors(accent, self.context.color("border_strong"),
                              self.context.color("surface"))
        self.account_more.apply_theme()
        self._sync_antigravity()
