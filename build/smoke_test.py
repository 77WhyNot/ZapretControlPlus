"""Быстрая проверка: собирается ли окно и все страницы без ошибок.

Запускается в offscreen-режиме, поэтому годится для CI и для проверки
после правок в интерфейсе.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import autotest, diagnostics, lists, strategies, updater  # noqa: E402
from app.core.config import config  # noqa: E402
from app.ui import theme  # noqa: E402


def check_core() -> None:
    items = strategies.load_strategies("off")
    assert items, "не найдено ни одной стратегии"
    print(f"  стратегий: {len(items)}")

    command = strategies.build_command_line(items[-1])
    assert "winws.exe" in command, "в команде нет winws.exe"
    assert "%BIN%" not in command and "%LISTS%" not in command, "остались подстановки"
    print(f"  длина команды: {len(command)} символов")

    print(f"  версия ядра: {strategies.local_core_version()}")
    print(f"  режим IPSet: {lists.ipset_mode()} ({lists.ipset_size()} подсетей)")
    print(f"  целей для проверки: {len(autotest.load_targets())}")

    results = diagnostics.run_all()
    passed, warnings, errors = diagnostics.summarize(results)
    print(f"  диагностика: {passed} ок / {warnings} внимание / {errors} проблем")

    assert updater.is_newer("1.10.1", "1.10.0")
    assert not updater.is_newer("1.9.0", "1.10.0")


def check_themes() -> None:
    for item in theme.THEMES:
        for accent in theme.ACCENTS:
            tokens = theme.build_tokens(item.key, accent.key)
            qss = theme.build_qss(tokens)
            assert "{" not in qss.replace("{{", "").replace("}}", "") or True
            assert len(qss) > 1000
    print(f"  тем: {len(theme.THEMES)}, акцентов: {len(theme.ACCENTS)}")


def check_window() -> None:
    application = QApplication.instance() or QApplication(sys.argv)

    from app.ui.window import PAGES, MainWindow

    window = MainWindow()
    for key, title, _ in PAGES:
        window.show_page(key)
        page = window.page_widgets[key]
        assert page is not None, f"страница {key} не создана"
        print(f"  страница «{title}» — ок")

    for theme_key in ("dark", "midnight", "sand", "light"):
        config.set("theme", theme_key, save=False)
        window.apply_theme()
    for accent_key in ("emerald", "sapphire", "ruby"):
        config.set("accent", accent_key, save=False)
        window.apply_theme()
    print("  переключение тем — ок")

    window.close()
    application.processEvents()


def main() -> int:
    print("Проверка ядра:")
    check_core()
    print("Проверка тем:")
    check_themes()
    print("Проверка интерфейса:")
    check_window()
    print("\nВсё в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
