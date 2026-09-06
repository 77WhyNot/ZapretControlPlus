"""Рендер страниц в PNG для проверки вёрстки без запуска настоящего окна."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Настоящая платформа: в offscreen нет системных шрифтов, текст
# рисуется квадратами. Окно при этом на экране не появляется.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import config  # noqa: E402

DOCS = "--docs" in sys.argv
ARGS = [item for item in sys.argv[1:] if not item.startswith("--")]
OUTPUT = Path(ARGS[0]) if ARGS else Path("build/preview")


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv[:1])
    OUTPUT.mkdir(parents=True, exist_ok=True)

    from app.ui.window import PAGES, MainWindow

    window = MainWindow()
    window.resize(1240, 820)
    window.show()
    application.processEvents()

    combos = [
        ("rails", "cyan"),
        ("light", "ruby"),
        ("midnight", "sapphire"),
    ]
    pages = [key for key, _title, _icon in PAGES]

    if DOCS:
        # Кадры для README: без плашек о правах и чужом VPN — они про
        # конкретную машину, а не про программу. Диагностику и проверку
        # обновлений запускаем, чтобы страницы не были пустыми.
        combos = [("light", "ruby"), ("rails", "ruby")]
        home = window.ensure_page("home")
        for name in ("banner_admin", "banner_tunnel"):
            banner = getattr(home, name, None)
            if banner is not None:
                banner.hide()
                banner.setVisible = lambda *_a, **_k: None  # noqa: E731
        diagnostics = window.ensure_page("diagnostics")
        diagnostics.run_checks()
        updates = window.ensure_page("updates")
        updates.check_core(manual=False)
        updates.check_app(manual=False)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            application.processEvents()

    for theme_key, accent_key in combos:
        config.set("theme", theme_key, save=False)
        config.set("accent", accent_key, save=False)
        window.apply_theme()
        application.processEvents()
        for page in pages:
            window.show_page(page)
            # Страница проявляется 140 мс — снимок раньше выйдет пустым.
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                application.processEvents()
            path = OUTPUT / f"{theme_key}-{accent_key}-{page}.png"
            window.grab().save(str(path))
            print(f"  {path}")

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
