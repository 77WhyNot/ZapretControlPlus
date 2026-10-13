"""Страница «О программе»: что это, откуда взялось и кому спасибо."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from app.core import paths, strategies
from app.core.constants import (
    APP_AUTHOR,
    APP_AUTHOR_FULL,
    APP_NAME,
    APP_REPO,
    APP_VERSION,
    UPSTREAM_HOME,
    UPSTREAM_REPO,
)
from app.ui.context import AppContext
from app.ui.pages.base import Page
from app.ui.widgets import (
    Button,
    Card,
    Divider,
    IconLabel,
    StatItem,
    faint_label,
    muted_label,
    section_label,
)


class AboutPage(Page):
    def __init__(self, context: AppContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            context, "Письмо от *автора*",
            "Что это за программа, как она устроена и кому спасибо.",
            parent, eyebrow="Ещё · о программе",
        )

        self._build_hero()
        self._build_how()
        self._build_credits()
        self._build_paths()
        self.apply_theme()

    def _build_hero(self) -> None:
        from app.core.constants import APP_EDITION
        from app.ui import scenes
        from app.ui.ink import InkCanvas
        from app.ui.widgets import MonoLabel, SerifTitle

        card = Card(padding=22, spacing=16)

        top = QHBoxLayout()
        top.setSpacing(24)
        self.logo = IconLabel("shield_check", self.context.color("accent"), 46)
        self.logo.hide()
        envelope = InkCanvas(scenes.envelope(), self.context, plate="plate", radius=18)
        envelope.setFixedWidth(250)
        top.addWidget(envelope, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(6)
        text_box.addWidget(MonoLabel(f"версия {APP_VERSION} {APP_EDITION}".strip(),
                                     self.context, "accent_ink", 11))
        text_box.addWidget(SerifTitle(APP_NAME, self.context, 34))
        text_box.addWidget(muted_label(
            "Обход блокировок, VPN по программам, прокси Telegram и Smart DNS — "
            "в одном окне. В основе обхода — zapret: стратегии, которые раньше "
            "запускали .bat-файлами и меню в консоли. С версии 4.0 программа "
            "называется ZapretCtrl и нарисована от руки: сад, почта и море."
        ))
        author = QLabel(f"Автор — {APP_AUTHOR_FULL}")
        author.setStyleSheet("font-weight: 500; margin-top: 4px;")
        text_box.addWidget(author)
        text_box.addStretch(1)
        top.addLayout(text_box, 1)
        card.add_layout(top)

        card.add(Divider())

        stats = QHBoxLayout()
        stats.setSpacing(30)
        stats.addWidget(StatItem("Версия приложения", APP_VERSION))
        stats.addWidget(StatItem("Версия ядра zapret", strategies.local_core_version()))
        stats.addWidget(StatItem(
            "Стратегий доступно", str(len(self.context.load_strategies()))
        ))
        stats.addStretch(1)
        card.add_layout(stats)

        links = QHBoxLayout()
        links.setSpacing(10)

        btn_upstream = Button("Репозиторий zapret", variant="soft")
        btn_upstream.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(UPSTREAM_HOME))
        )
        links.addWidget(btn_upstream)

        btn_author = Button(f"GitHub автора — {APP_AUTHOR}", variant="ghost")
        btn_author.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/77WhyNot"))
        )
        links.addWidget(btn_author)

        if APP_REPO and "/" in APP_REPO:
            btn_app = Button("Репозиторий приложения", variant="ghost")
            btn_app.clicked.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl(f"https://github.com/{APP_REPO}")
                )
            )
            links.addWidget(btn_app)

        links.addStretch(1)
        card.add_layout(links)

        self.body.addWidget(card)

    def _build_how(self) -> None:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Как это работает"))
        card.add(muted_label(
            "Провайдер определяет запрещённый сайт по первому пакету соединения — "
            "в нём открытым текстом лежит имя домена. zapret разрезает и "
            "подделывает этот пакет так, что оборудование провайдера перестаёт "
            "узнавать домен, а сервер на другом конце собирает всё правильно. "
            "Трафик при этом никуда не перенаправляется: он идёт напрямую, "
            "поэтому скорость не падает, в отличие от VPN."
        ))
        card.add(muted_label(
            "Набор приёмов называется стратегией. Оборудование у провайдеров "
            "разное, поэтому универсальной стратегии нет — нужную подбирают "
            "перебором. Для этого в программе есть автоподбор."
        ))
        card.add(muted_label(
            "VPN устроен иначе: трафик выбранных программ уходит через сервер "
            "вашей подписки, и сайт видит адрес сервера, а не ваш. Туннель "
            "поднимает движок sing-box, а программа решает, кому идти через "
            "него, а кому напрямую — там трафик подхватывает zapret."
        ))
        card.add(Divider())
        card.add(faint_label(
            "Сам обход DPI не скрывает ваш IP-адрес — он лишь мешает "
            "оборудованию провайдера опознать соединение. Адрес меняет только VPN."
        ))
        self.body.addWidget(card)

    def _build_credits(self) -> None:
        card = Card(padding=20, spacing=12)
        card.add(section_label("Благодарности"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        entries = (
            ("bol-van / zapret",
             "Автор winws и всей технологии обхода.",
             "https://github.com/bol-van/zapret"),
            (f"{UPSTREAM_REPO.split('/')[0]} / zapret-discord-youtube",
             "Сборка стратегий и списков, которую использует эта программа.",
             UPSTREAM_HOME),
            ("basil00 / WinDivert",
             "Драйвер перехвата пакетов, на котором всё держится.",
             "https://github.com/basil00/Divert"),
            ("SagerNet / sing-box",
             "Движок VPN: туннель, протоколы, раздельная маршрутизация (GPL-3.0).",
             "https://github.com/SagerNet/sing-box"),
            ("Flowseal / tg-ws-proxy",
             "Прокси Telegram через WebSocket — его ядро работает внутри программы (MIT).",
             "https://github.com/Flowseal/tg-ws-proxy"),
            ("Comss DNS",
             "Smart DNS для сервисов, закрытых по стране, — он стоит в программе по умолчанию.",
             "https://www.comss.ru/page.php?id=7315"),
            ("Literata, Geist, Geist Mono",
             "Шрифты оформления — под свободной лицензией SIL OFL 1.1.",
             "https://openfontlicense.org"),
        )
        for row, (name, description, url) in enumerate(entries):
            # Цвет ссылки задаёт палитра окна (под тему), а не стиль подписи:
            # стиль до текста ссылки не доходит, и в тёмной теме она тонула.
            label = QLabel(f'<a href="{url}">{name}</a>')
            label.setOpenExternalLinks(True)
            label.setStyleSheet("font-weight: 500;")
            grid.addWidget(label, row, 0)
            grid.addWidget(faint_label(description), row, 1)
        grid.setColumnStretch(1, 1)
        card.add_layout(grid)

        self.body.addWidget(card)

    def _build_paths(self) -> None:
        card = Card(padding=20, spacing=10)
        card.add(section_label("Где что лежит"))
        for caption, value in (
            ("Программа", str(paths.app_dir())),
            ("Ядро zapret", str(paths.core_dir())),
            ("Настройки и журнал", str(paths.data_dir())),
        ):
            line = QHBoxLayout()
            line.setSpacing(12)
            name = QLabel(caption)
            name.setStyleSheet("font-weight: 500;")
            name.setFixedWidth(160)
            line.addWidget(name)
            path_label = faint_label(value)
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            line.addWidget(path_label, 1)
            card.add_layout(line)
        self.body.addWidget(card)

    def on_activate(self) -> None:
        pass

    def apply_theme(self) -> None:
        self.logo.set_color(self.context.color("accent"))
