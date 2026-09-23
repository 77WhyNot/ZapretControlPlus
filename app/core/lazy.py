"""Отложенный импорт тяжёлых библиотек.

requests со всеми зависимостями (urllib3, certifi, http.client) грузится
почти четверть секунды, а в первые секунды после запуска сеть не нужна.
Поэтому библиотека подгружается при первом настоящем обращении — уже после
того, как окно появилось.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class LazyModule:
    """Модуль, который импортируется при первом обращении к его атрибутам."""

    def __init__(self, loader: Callable[[], Any]) -> None:
        self._loader = loader
        self._module: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        module = self._module
        if module is None:
            with self._lock:
                if self._module is None:
                    self._module = self._loader()
                module = self._module
        return module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


def _requests() -> Any:
    # Обычный импорт внутри функции: сборщик (PyInstaller) его видит и кладёт
    # библиотеку в установщик, а выполняется он только при первом обращении.
    import requests

    return requests


requests = LazyModule(_requests)
