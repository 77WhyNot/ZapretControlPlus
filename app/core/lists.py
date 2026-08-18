"""Работа со списками доменов и IP, а также с файлом hosts."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core import logs, net, paths, winapi
from app.core.constants import (
    UPSTREAM_BRANCH,
    UPSTREAM_HOSTS_PATH,
    UPSTREAM_IPSET_PATH,
    UPSTREAM_REPO,
)

# Заглушка из service.bat: адрес из документационного диапазона TEST-NET-3,
# который заведомо никому не принадлежит.
IPSET_STUB = "203.0.113.113/32"

RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_BRANCH}"
IPSET_URL = f"{RAW_BASE}/{UPSTREAM_IPSET_PATH}"
HOSTS_URL = f"{RAW_BASE}/{UPSTREAM_HOSTS_PATH}"

HOSTS_MARKER_START = "# >>> zapret-discord-youtube >>>"
HOSTS_MARKER_END = "# <<< zapret-discord-youtube <<<"


@dataclass(frozen=True)
class UserList:
    key: str
    filename: str
    title: str
    description: str
    placeholder: str


USER_LISTS: tuple[UserList, ...] = (
    UserList(
        key="general",
        filename="list-general-user.txt",
        title="Свои домены",
        description="Сайты, которые нужно дополнительно обходить. По одному домену в строке.",
        placeholder="# Не оставляйте файл пустым\ndomain.example.abc",
    ),
    UserList(
        key="exclude",
        filename="list-exclude-user.txt",
        title="Исключения по доменам",
        description="Сайты, которые zapret трогать не должен (банки, госуслуги, локальные сервисы).",
        placeholder="domain.example.abc",
    ),
    UserList(
        key="ipset_exclude",
        filename="ipset-exclude-user.txt",
        title="Исключения по IP",
        description="Подсети, которые обходить не нужно. Формат CIDR, например 10.0.0.0/8.",
        placeholder=IPSET_STUB,
    ),
)

USER_LIST_BY_KEY = {item.key: item for item in USER_LISTS}


def ensure_user_lists() -> None:
    """Создать пользовательские списки, если их нет (аналог load_user_lists)."""
    lists = paths.lists_dir()
    try:
        lists.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for item in USER_LISTS:
        path = lists / item.filename
        if not path.exists():
            try:
                path.write_text(item.placeholder + "\n", encoding="utf-8")
            except OSError:
                continue


def read_user_list(key: str) -> str:
    item = USER_LIST_BY_KEY[key]
    path = paths.lists_dir() / item.filename
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return item.placeholder + "\n"


def write_user_list(key: str, content: str) -> None:
    item = USER_LIST_BY_KEY[key]
    path = paths.lists_dir() / item.filename
    text = content.strip()
    # Пустой hostlist zapret воспринимает как ошибку конфигурации.
    if not text:
        text = item.placeholder
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    logs.info(f"Сохранён список {item.filename}")


# --- IPSet ---------------------------------------------------------------

IPSET_MODES = {
    "loaded": "Полный список",
    "none": "Отключён",
    "any": "Без ограничений",
}


def _ipset_path() -> Path:
    return paths.lists_dir() / "ipset-all.txt"


def _ipset_backup() -> Path:
    return paths.lists_dir() / "ipset-all.txt.backup"


def ipset_mode() -> str:
    """Режим определяется так же, как в service.bat."""
    path = _ipset_path()
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "any"
    stripped = content.strip()
    if not stripped:
        return "any"
    if IPSET_STUB in content:
        return "none"
    return "loaded"


def ipset_size() -> int:
    """Сколько подсетей в полном списке (в файле или в резервной копии)."""
    for path in (_ipset_path(), _ipset_backup()):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if IPSET_STUB in text or not text.strip():
            continue
        return sum(1 for line in text.splitlines() if line.strip())
    return 0


def _preserve_full_list() -> None:
    """Перед подменой файла сохраняем настоящий список в .backup."""
    if ipset_mode() != "loaded":
        return
    try:
        shutil.copy2(_ipset_path(), _ipset_backup())
    except OSError as exc:
        logs.warn(f"Не удалось сохранить резервную копию ipset: {exc}")


def set_ipset_mode(mode: str) -> None:
    if mode not in IPSET_MODES:
        raise ValueError(mode)
    current = ipset_mode()
    if current == mode:
        return

    path = _ipset_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "loaded":
        backup = _ipset_backup()
        if not backup.exists() or not backup.stat().st_size:
            raise RuntimeError(
                "Нет сохранённого списка IP. Сначала обновите список кнопкой «Обновить IPSet»."
            )
        shutil.copy2(backup, path)
    elif mode == "none":
        _preserve_full_list()
        path.write_text(IPSET_STUB + "\n", encoding="utf-8")
    else:  # any
        _preserve_full_list()
        path.write_text("", encoding="utf-8")

    logs.info(f"Режим IPSet: {IPSET_MODES[mode]}")


def update_ipset() -> int:
    """Скачать свежий список IP. Возвращает число строк."""
    data = net.fetch(IPSET_URL)
    text = data.decode("utf-8", errors="replace")
    count = sum(1 for line in text.splitlines() if line.strip())
    if count < 100:
        raise RuntimeError("Скачанный список подозрительно короткий, обновление отменено.")

    mode = ipset_mode()
    backup = _ipset_backup()
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(text, encoding="utf-8")
    if mode == "loaded":
        _ipset_path().write_text(text, encoding="utf-8")
    logs.info(f"Список IPSet обновлён: {count} подсетей")
    return count


# --- hosts ---------------------------------------------------------------


@dataclass(frozen=True)
class HostsStatus:
    ok: bool
    missing: int
    total: int
    message: str
    conflicting: bool = False


def _read_hosts() -> str:
    try:
        return Path(winapi.hosts_file()).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def hosts_status() -> HostsStatus:
    """Сравнить системный hosts с рекомендованным из репозитория."""
    current = _read_hosts()
    conflicting = any(
        token in current.lower() for token in ("youtube.com", "youtu.be")
    ) and HOSTS_MARKER_START not in current

    try:
        recommended = net.fetch_text(HOSTS_URL)
    except net.NetworkError:
        return HostsStatus(
            ok=False, missing=0, total=0,
            message="Не удалось получить эталонный hosts из репозитория.",
            conflicting=conflicting,
        )

    wanted = [
        line.strip() for line in recommended.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    existing = {
        " ".join(line.split()) for line in current.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [line for line in wanted if " ".join(line.split()) not in existing]

    if not wanted:
        return HostsStatus(True, 0, 0, "Для этой версии записи hosts не нужны.", conflicting)
    if not missing:
        return HostsStatus(True, 0, len(wanted), "Файл hosts в актуальном состоянии.", conflicting)
    return HostsStatus(
        False, len(missing), len(wanted),
        f"Не хватает {len(missing)} из {len(wanted)} записей.",
        conflicting,
    )


def apply_hosts() -> int:
    """Дописать недостающие записи в hosts. Возвращает число добавленных строк."""
    hosts_path = Path(winapi.hosts_file())
    recommended = net.fetch_text(HOSTS_URL)
    wanted = [
        line.strip() for line in recommended.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not wanted:
        return 0

    current = _read_hosts()
    existing = {
        " ".join(line.split()) for line in current.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [line for line in wanted if " ".join(line.split()) not in existing]
    if not missing:
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = paths.backup_dir() / f"hosts-{stamp}.bak"
    try:
        shutil.copy2(hosts_path, backup)
    except OSError as exc:
        raise RuntimeError(f"Не удалось создать резервную копию hosts: {exc}") from exc

    block = "\n".join([HOSTS_MARKER_START, *missing, HOSTS_MARKER_END])
    body = current.rstrip("\r\n")
    new_content = f"{body}\n\n{block}\n" if body else f"{block}\n"
    try:
        hosts_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Не удалось записать hosts: {exc}. Проверьте, что файл не заблокирован антивирусом."
        ) from exc

    logs.info(f"В hosts добавлено записей: {len(missing)} (копия: {backup.name})")
    return len(missing)


def revert_hosts() -> bool:
    """Убрать блок, добавленный приложением."""
    hosts_path = Path(winapi.hosts_file())
    current = _read_hosts()
    if HOSTS_MARKER_START not in current:
        return False
    lines = current.splitlines()
    result: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == HOSTS_MARKER_START:
            skipping = True
            continue
        if line.strip() == HOSTS_MARKER_END:
            skipping = False
            continue
        if not skipping:
            result.append(line)
    hosts_path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    logs.info("Записи zapret удалены из hosts")
    return True
