"""Обновления: ядра zapret и самого приложения.

Проверка версии идёт через raw-файл в репозитории, а не через api.github.com:
raw отлично проксируется публичными зеркалами, а API — нет. Ссылка на архив
релиза собирается по неизменному шаблону имени ассета.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core import engine as engine_module
from app.core import logs, net, paths, strategies
from app.core.config import config
from app.core.constants import (
    APP_ID,
    APP_REPO,
    APP_VERSION,
    UPSTREAM_ASSET_TEMPLATE,
    UPSTREAM_BRANCH,
    UPSTREAM_REPO,
    UPSTREAM_VERSION_PATH,
)

Progress = Callable[[str, int], None]

# Файлы, которые обновление не имеет права затирать.
PRESERVED = (
    "lists/list-general-user.txt",
    "lists/list-exclude-user.txt",
    "lists/ipset-exclude-user.txt",
    "lists/ipset-all.txt",
    "lists/ipset-all.txt.backup",
    "utils/game_filter.enabled",
    "utils/check_updates.enabled",
    # Списки Telegram добавлены нами — в релизах апстрима их нет.
    "lists/ipset-telegram.txt",
    "lists/list-telegram.txt",
)


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    available: bool
    notes: str = ""
    download_url: str = ""
    error: str = ""


def _clean_version(raw: str) -> str:
    """Обрезать BOM, кавычки и пробелы.

    PowerShell и текстовые редакторы дописывают в начало файла невидимый
    маркер U+FEFF. Из-за него версия перестаёт начинаться с цифры, и
    проверка обновлений считает ответ сервера мусором.
    """
    return raw.replace("\ufeff", "").strip().strip('"').strip()


def parse_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value or "")
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, baseline: str) -> bool:
    return parse_version(candidate) > parse_version(baseline)


# =========================================================================
# Ядро zapret
# =========================================================================


def core_version() -> str:
    return strategies.local_core_version()


def check_core_update() -> UpdateInfo:
    current = core_version()
    url = (
        f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/"
        f"{UPSTREAM_BRANCH}/{UPSTREAM_VERSION_PATH}"
    )
    try:
        latest = _clean_version(net.fetch_text(url))
    except net.NetworkError as exc:
        return UpdateInfo(current, "—", False, error=str(exc))

    if not re.match(r"^\d", latest):
        return UpdateInfo(current, "—", False, error="Некорректный ответ сервера версий.")

    asset = UPSTREAM_ASSET_TEMPLATE.format(version=latest)
    download = f"https://github.com/{UPSTREAM_REPO}/releases/download/{latest}/{asset}"
    return UpdateInfo(
        current=current,
        latest=latest,
        available=is_newer(latest, current),
        download_url=download,
        notes=fetch_release_notes(UPSTREAM_REPO, latest),
    )


def fetch_release_notes(repo: str, tag: str) -> str:
    """Описание релиза — приятный бонус, без него обновление всё равно работает."""
    try:
        data = net.fetch_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
    except (net.NetworkError, ValueError):
        return ""
    body = str(data.get("body") or "").strip()
    return body[:4000]


def _snapshot_preserved(core: Path, target: Path) -> None:
    for relative in PRESERVED:
        source = core / relative
        if not source.exists():
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError:
            continue


def _restore_preserved(source: Path, core: Path) -> None:
    for relative in PRESERVED:
        saved = source / relative
        if not saved.exists():
            continue
        destination = core / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(saved, destination)
        except OSError:
            continue


def _find_payload_root(extracted: Path) -> Path:
    """В архиве апстрима содержимое лежит внутри одной папки."""
    if (extracted / "bin" / "winws.exe").exists():
        return extracted
    for child in extracted.iterdir():
        if child.is_dir() and (child / "bin" / "winws.exe").exists():
            return child
    raise RuntimeError("В архиве нет bin\\winws.exe — файл повреждён или это не zapret.")


def install_core_update(info: UpdateInfo, progress: Progress | None = None) -> str:
    """Скачать и установить обновление ядра, сохранив пользовательские данные."""

    def report(text: str, percent: int) -> None:
        logs.info(text)
        if progress:
            progress(text, percent)

    if not info.download_url:
        raise RuntimeError("Неизвестен адрес загрузки обновления.")

    core = paths.core_dir()
    engine = engine_module.engine
    status = engine.status()
    was_running = status.running and not status.external
    previous_mode = status.mode
    previous_strategy = status.strategy_id or str(config.get("last_strategy"))

    with tempfile.TemporaryDirectory(prefix="zapret-update-") as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / "core.zip"

        report("Скачивание обновления…", 5)

        def on_progress(done: int, total: int) -> None:
            percent = 5 + int(done / total * 55) if total else 30
            if progress:
                progress("Скачивание обновления…", min(percent, 60))

        net.download(info.download_url, archive, progress=on_progress)

        report("Проверка архива…", 65)
        if not zipfile.is_zipfile(archive):
            raise RuntimeError("Скачанный файл не является ZIP-архивом.")
        unpacked = tmpdir / "unpacked"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(unpacked)
        payload = _find_payload_root(unpacked)

        report("Остановка обхода…", 70)
        engine.stop(quiet=True)

        report("Сохранение ваших списков…", 75)
        preserved = tmpdir / "preserved"
        _snapshot_preserved(core, preserved)

        report("Установка файлов…", 80)
        core.mkdir(parents=True, exist_ok=True)
        # Старые стратегии убираем, иначе исчезнувшие из релиза останутся навсегда.
        for old in core.glob("*.bat"):
            try:
                old.unlink()
            except OSError:
                pass
        _copy_tree(payload, core)

        report("Возврат ваших настроек…", 92)
        _restore_preserved(preserved, core)

    if was_running:
        report("Перезапуск обхода…", 96)
        strategy = strategies.find_strategy(
            previous_strategy, strategies.read_game_filter()
        )
        if strategy is not None:
            try:
                engine.start(strategy, previous_mode)
            except engine_module.EngineError as exc:
                logs.warn(f"Не удалось перезапустить обход: {exc}")

    report("Готово", 100)
    new_version = core_version()
    logs.info(f"Ядро zapret обновлено до версии {new_version}")
    return new_version


def _copy_tree(source: Path, destination: Path) -> None:
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(item, target)
        except OSError as exc:
            raise RuntimeError(
                f"Не удалось записать {relative}: {exc}. "
                "Закройте программу, которая держит файл (например, антивирус)."
            ) from exc


def restore_core_from_bundle() -> bool:
    """Восстановить ядро из копии, вшитой в установщик (аварийный сценарий)."""
    fallback = paths.app_dir() / "core-backup"
    if not (fallback / "bin" / "winws.exe").exists():
        return False
    _copy_tree(fallback, paths.core_dir())
    logs.info("Ядро восстановлено из резервной копии")
    return True


# =========================================================================
# Само приложение
# =========================================================================


def app_version() -> str:
    return APP_VERSION


def check_app_update() -> UpdateInfo:
    if not APP_REPO or "/" not in APP_REPO:
        return UpdateInfo(
            APP_VERSION, "—", False,
            error="Репозиторий приложения не указан, поэтому обновляться неоткуда. "
                  "Впишите APP_REPO в app/core/constants.py.",
        )
    url = f"https://raw.githubusercontent.com/{APP_REPO}/main/version.txt"
    try:
        latest = _clean_version(net.fetch_text(url))
    except net.NetworkError as exc:
        return UpdateInfo(APP_VERSION, "—", False, error=str(exc))
    if not re.match(r"^\d", latest):
        return UpdateInfo(APP_VERSION, "—", False, error="Некорректный ответ сервера версий.")

    asset = f"{APP_ID}-Setup-{latest}.exe"
    download = f"https://github.com/{APP_REPO}/releases/download/v{latest}/{asset}"
    return UpdateInfo(
        current=APP_VERSION,
        latest=latest,
        available=is_newer(latest, APP_VERSION),
        download_url=download,
        notes=fetch_release_notes(APP_REPO, f"v{latest}"),
    )


def install_app_update(info: UpdateInfo, progress: Progress | None = None) -> Path:
    """Скачать установщик новой версии и запустить его в тихом режиме."""
    if not info.download_url:
        raise RuntimeError("Неизвестен адрес загрузки установщика.")
    target = paths.cache_dir() / f"{APP_ID}-Setup-{info.latest}.exe"

    def on_progress(done: int, total: int) -> None:
        if progress and total:
            progress("Скачивание установщика…", int(done / total * 100))

    net.download(info.download_url, target, progress=on_progress)
    if target.stat().st_size < 1_000_000:
        target.unlink(missing_ok=True)
        raise RuntimeError("Установщик скачался не полностью, попробуйте ещё раз.")
    return target


def launch_installer(installer: Path) -> None:
    """Запустить установщик и выйти — обновление продолжится без нас."""
    logs.info(f"Запуск установщика {installer.name}")
    subprocess.Popen(
        [str(installer), "/SILENT", "/NORESTART", "/SUPPRESSMSGBOXES"],
        cwd=str(installer.parent),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def uninstall_leftovers() -> None:
    """Убрать скачанные установщики старых версий."""
    for item in paths.cache_dir().glob(f"{APP_ID}-Setup-*.exe"):
        try:
            if item.stem.endswith(APP_VERSION):
                continue
            item.unlink()
        except OSError:
            continue


def is_check_due() -> bool:
    import time

    interval = float(config.get("update_check_interval_hours", 12)) * 3600
    last = float(config.get("last_update_check", 0))
    return (time.time() - last) > interval


def mark_checked() -> None:
    import time

    config.set("last_update_check", int(time.time()))


def running_from_installed_copy() -> bool:
    """В dev-режиме автообновление приложения смысла не имеет."""
    return getattr(sys, "frozen", False) and os.path.exists(sys.executable)
