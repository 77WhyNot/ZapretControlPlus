"""Рендер страниц в PNG для проверки вёрстки без запуска настоящего окна."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import config  # noqa: E402

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/preview")


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

    for theme_key, accent_key in combos:
        config.set("theme", theme_key, save=False)
        config.set("accent", accent_key, save=False)
        window.apply_theme()
        application.processEvents()
        for page in pages:
            window.show_page(page)
            for _ in range(3):
                application.processEvents()
            path = OUTPUT / f"{theme_key}-{accent_key}-{page}.png"
            window.grab().save(str(path))
            print(f"  {path}")

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
