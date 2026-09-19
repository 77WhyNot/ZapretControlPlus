"""Приветствие при первом запуске и рассказ о новом после обновления.

Не отдельное окно, а карточка поверх главного: окно за ней приглушается
снимком, поэтому никакой мигающей второй рамки на экране не появляется.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.constants import APP_NAME, APP_VERSION
from app.core.whatsnew import FEATURES, changes_for
from app.ui.context import AppContext
from app.ui.widgets import Button, IconLabel, fade_in, snapshot

CARD_WIDTH = 560
ENTER_MS = 380
LEAVE_MS = 200
LIFT = 26  # на сколько пикселей карточка поднимается, проявляясь


class FeatureRow(QWidget):
    """Строка списка: значок в кружке, заголовок и пояснение."""

    def __init__(self, context: AppContext, icon_name: str, title: str, text: str,
                 token: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        badge = QLabel(self)
        badge.setFixedSize(38, 38)
        badge.setStyleSheet(
            f"background: {context.color(f'{token}_soft', context.color('hover'))};"
            "border-radius: 11px;"
        )
        badge_layout = QHBoxLayout(badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.addWidget(
            IconLabel(icon_name, context.color(token, context.color("accent")), 19, badge),
            0, Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        caption = QLabel(title, self)
        caption.setStyleSheet("font-weight: 650; font-size: 13.5px; background: transparent;")
        texts.addWidget(caption)
        hint = QLabel(text, self)
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        texts.addWidget(hint)
        layout.addLayout(texts, 1)


class Intro(QWidget):
    """Карточка поверх окна: приветствие или «что нового»."""

    closed = Signal()

    def __init__(self, host: QWidget, context: AppContext, kind: str = "welcome") -> None:
        super().__init__(host)
        self.context = context
        self.kind = kind
        self._host = host
        self._progress = 0.0
        self._animations: list = []
        self._closing = False
        self._size = (CARD_WIDTH, 300)
        self._background = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(host.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.card = QFrame(self)
        self.card.setObjectName("IntroCard")
        self.card.setStyleSheet(
            f"QFrame#IntroCard {{ background: {context.color('surface')}; "
            f"border: 1px solid {context.color('border')}; border-radius: 18px; }}"
        )
        self._build_card()

        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._advance)

        # Снимок окна и слежка за его размером — последними: снимок заставляет
        # Qt разложить и нарисовать окно, а значит и эту карточку, поэтому к
        # этому мигу она должна быть готова целиком.
        self._background = snapshot(host, QColor(context.color("bg")))
        host.installEventFilter(self)

    # --- содержимое --------------------------------------------------------

    def _build_card(self) -> None:
        items = FEATURES if self.kind == "welcome" else changes_for()
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(IconLabel("shield_check", self.context.color("accent"), 24, self.card))
        name = QLabel(APP_NAME, self.card)
        name.setStyleSheet("font-weight: 650; font-size: 14px; background: transparent;")
        top.addWidget(name)
        version = QLabel(f"v{APP_VERSION}", self.card)
        version.setObjectName("Faint")
        top.addWidget(version)
        top.addStretch(1)
        layout.addLayout(top)

        head = QVBoxLayout()
        head.setSpacing(4)
        title = QLabel(
            "Добро пожаловать" if self.kind == "welcome" else f"Что нового в {APP_VERSION}",
            self.card,
        )
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        head.addWidget(title)
        subtitle = QLabel(
            "Коротко о том, что программа умеет. Всё главное — на главной, "
            "остальное — в разделах слева."
            if self.kind == "welcome" else
            "Программа обновилась. Вот что изменилось.",
            self.card,
        )
        subtitle.setObjectName("Faint")
        subtitle.setWordWrap(True)
        head.addWidget(subtitle)
        layout.addLayout(head)

        self._rows: list[QWidget] = []
        for icon_name, item_title, text, token in items:
            row = FeatureRow(self.context, icon_name, item_title, text, token, self.card)
            layout.addWidget(row)
            self._rows.append(row)

        self.note = QLabel(
            "Совет: нажмите на любую полоску на схеме — откроется её раздел."
            if self.kind == "welcome" else "",
            self.card,
        )
        self.note.setObjectName("Faint")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch(1)
        self.button = Button("Начать" if self.kind == "welcome" else "Понятно",
                             variant="primary", parent=self.card)
        # Без этого кнопка растягивается на всю ширину, когда подсказки нет.
        self.button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.button.clicked.connect(self.close_animated)
        footer.addWidget(self.button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)

    # --- показ и закрытие ---------------------------------------------------

    def show_animated(self) -> None:
        self._measure()
        self._place()
        self.show()
        self.raise_()
        self.setFocus()
        self._animation.stop()
        self._animation.setDuration(ENTER_MS)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()
        # Строки проявляются по очереди — так карточка читается сверху вниз.
        for index, row in enumerate(self._rows):
            if not row.isHidden():
                fade_in(row, 200, delay=90 + index * 55, keep=self._animations)

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._animation.stop()
        self._animation.setDuration(LEAVE_MS)
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self._finish)
        self._animation.start()

    def _finish(self) -> None:
        # Слежку за окном снимаем сами: удалённая карточка не должна попадать
        # под его следующий размер.
        self._host.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def _advance(self, value) -> None:
        self._progress = float(value)
        self._place()
        self.update()

    def _measure(self) -> None:
        """Подобрать размер карточки под окно — один раз, а не на каждом кадре."""
        width = min(CARD_WIDTH, max(320, self.width() - 60))
        self.card.setFixedWidth(width)
        room = max(220, self.height() - 48)
        for row in self._rows:
            row.setVisible(True)
        self.note.setVisible(bool(self.note.text()))
        layout = self.card.layout()
        if layout is not None:
            # В невысоком окне сперва ужимаем отступы и только потом прячем
            # строки: лучше плотная карточка, чем неполная.
            tight = self._card_height(width) > room
            layout.setSpacing(10 if tight else 16)
            layout.setContentsMargins(*((24, 18, 24, 16) if tight else (28, 24, 28, 22)))
        # В низком окне лучше показать меньше строк, чем обрезать их по половине.
        # Смотрим на isHidden, а не на isVisible: карточка ещё не на экране.
        while self._card_height(width) > room:
            if not self.note.isHidden():
                self.note.hide()
                continue
            shown = [row for row in self._rows if not row.isHidden()]
            if len(shown) <= 2:
                break
            shown[-1].hide()
        self._size = (width, min(self._card_height(width), room))

    def _card_height(self, width: int) -> int:
        """Высота карточки при такой ширине — с учётом переносов в подписях."""
        layout = self.card.layout()
        if layout is not None:
            layout.invalidate()
        hint = self.card.sizeHint().height()
        wrapped = self.card.heightForWidth(width)
        return max(hint, wrapped)

    def _place(self) -> None:
        width, height = self._size
        lift = int(round((1.0 - self._progress) * LIFT))
        self.card.setGeometry((self.width() - width) // 2,
                              (self.height() - height) // 2 + lift, width, height)

    # --- события ------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if (watched is not self._host or self._closing
                or event.type() != QEvent.Type.Resize):
            return False
        try:
            # Размер окна изменили — снимок больше не подходит, дальше просто фон.
            self._background = None
            self.setGeometry(self._host.rect())
            self._measure()
            self._place()
            self.update()
        except RuntimeError:  # карточку уже закрыли и удалили
            pass
        return False

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # Щелчок мимо карточки закрывает её — как любое окно поверх.
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_animated()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter,
                           Qt.Key.Key_Space):
            self.close_animated()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._background is not None:
            painter.drawPixmap(0, 0, self._background)
        else:
            painter.fillRect(self.rect(), QColor(self.context.color("bg")))
        veil = QColor(0, 0, 0, int((70 if self.context.is_dark else 90) * self._progress))
        painter.fillRect(self.rect(), veil)
        painter.end()
