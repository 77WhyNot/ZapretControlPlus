"""HTTP с учётом того, что GitHub у пользователя может быть недоступен.

Порядок попыток: зеркало, сработавшее в прошлый раз → прямое соединение →
остальные зеркала. Если человек сидит под VPN, прямое соединение обычно
работает и всё заканчивается на первом шаге.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import requests

from app.core import logs
from app.core.config import config
from app.core.constants import HTTP_TIMEOUT, USER_AGENT

CONNECT_TIMEOUT = 7
READ_TIMEOUT = HTTP_TIMEOUT


@dataclass(frozen=True)
class Mirror:
    key: str
    title: str
    prefix: str  # "" — прямое соединение

    def apply(self, url: str) -> str | None:
        if not self.prefix:
            return url
        if not url.startswith("https://"):
            return None
        return f"{self.prefix}{url}"


# Публичные реверс-прокси к GitHub. Работают по схеме <зеркало>/<полный URL>.
MIRRORS: tuple[Mirror, ...] = (
    Mirror("direct", "Прямое соединение", ""),
    Mirror("ghproxy", "ghproxy.net", "https://ghproxy.net/"),
    Mirror("ghproxy_com", "gh-proxy.com", "https://gh-proxy.com/"),
    Mirror("ghfast", "ghfast.top", "https://ghfast.top/"),
    Mirror("gitmirror", "hub.gitmirror.com", "https://hub.gitmirror.com/"),
)

MIRROR_BY_KEY = {mirror.key: mirror for mirror in MIRRORS}


class NetworkError(RuntimeError):
    pass


def _jsdelivr(url: str) -> str | None:
    """raw.githubusercontent.com → CDN jsDelivr (обычно не блокируется)."""
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix):]
    parts = rest.split("/")
    if len(parts) < 4:
        return None
    owner, repo, ref = parts[0], parts[1], parts[2]
    if ref == "refs" and len(parts) > 4 and parts[3] == "heads":
        ref = parts[4]
        path = "/".join(parts[5:])
    else:
        path = "/".join(parts[3:])
    if not path:
        return None
    return f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}"


def _ordered_mirrors() -> list[Mirror]:
    preferred = config.get("preferred_mirror", "")
    mirrors = list(MIRRORS)
    if preferred and preferred in MIRROR_BY_KEY:
        chosen = MIRROR_BY_KEY[preferred]
        mirrors.remove(chosen)
        mirrors.insert(0, chosen)
    return mirrors


def candidate_urls(url: str) -> list[tuple[str, str]]:
    """Список (ключ зеркала, url) в порядке попыток."""
    result: list[tuple[str, str]] = []
    for mirror in _ordered_mirrors():
        candidate = mirror.apply(url)
        if candidate:
            result.append((mirror.key, candidate))
    cdn = _jsdelivr(url)
    if cdn:
        result.append(("jsdelivr", cdn))
    return result


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Cache-Control": "no-cache",
    })
    custom = str(config.get("custom_proxy", "")).strip()
    if custom:
        session.proxies = {"http": custom, "https": custom}
        session.trust_env = False
    else:
        # trust_env берёт системный прокси и переменные HTTP(S)_PROXY.
        session.trust_env = bool(config.get("use_system_proxy", True))
    return session


def _remember(mirror_key: str) -> None:
    if mirror_key != config.get("preferred_mirror"):
        config.set("preferred_mirror", mirror_key)


def fetch(url: str, session: requests.Session | None = None,
          timeout: tuple[int, int] | None = None) -> bytes:
    """Скачать небольшой ресурс, перебирая зеркала. Бросает NetworkError."""
    own_session = session is None
    session = session or build_session()
    timeout = timeout or (CONNECT_TIMEOUT, READ_TIMEOUT)
    errors: list[str] = []
    try:
        for mirror_key, candidate in candidate_urls(url):
            try:
                response = session.get(candidate, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                _remember(mirror_key)
                return response.content
            except requests.RequestException as exc:
                errors.append(f"{mirror_key}: {type(exc).__name__}")
                continue
    finally:
        if own_session:
            session.close()
    logs.warn(f"Не удалось получить {url} ({'; '.join(errors)})")
    raise NetworkError(
        "Нет доступа к GitHub ни напрямую, ни через зеркала. "
        "Проверьте интернет, VPN или прокси в настройках."
    )


def fetch_text(url: str, session: requests.Session | None = None) -> str:
    return fetch(url, session).decode("utf-8", errors="replace")


def fetch_json(url: str, session: requests.Session | None = None):
    import json

    return json.loads(fetch_text(url, session))


def download(url: str, destination: Path,
             progress: Callable[[int, int], None] | None = None,
             session: requests.Session | None = None) -> Path:
    """Скачать файл с перебором зеркал и докладом о прогрессе."""
    own_session = session is None
    session = session or build_session()
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    try:
        for mirror_key, candidate in candidate_urls(url):
            temp = destination.with_suffix(destination.suffix + ".part")
            try:
                with session.get(
                    candidate, stream=True,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT * 3),
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("Content-Length") or 0)
                    done = 0
                    with temp.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, total)
                if temp.stat().st_size == 0:
                    raise requests.RequestException("пустой ответ")
                temp.replace(destination)
                _remember(mirror_key)
                return destination
            except (requests.RequestException, OSError) as exc:
                errors.append(f"{mirror_key}: {type(exc).__name__}")
                temp.unlink(missing_ok=True)
                continue
    finally:
        if own_session:
            session.close()
    logs.warn(f"Не удалось скачать {url} ({'; '.join(errors)})")
    raise NetworkError(
        "Не удалось скачать файл ни через одно зеркало. "
        "Попробуйте включить VPN или указать прокси в настройках."
    )


def probe(urls: Iterable[str], timeout: int = 6) -> dict[str, tuple[bool, float]]:
    """Быстрая проверка доступности адресов: {url: (успех, миллисекунды)}."""
    session = build_session()
    session.trust_env = False  # проверяем настоящий канал, а не прокси
    result: dict[str, tuple[bool, float]] = {}
    try:
        for url in urls:
            started = time.perf_counter()
            try:
                response = session.get(
                    url, timeout=(timeout, timeout), stream=True, allow_redirects=True
                )
                ok = response.status_code < 500
                response.close()
            except requests.RequestException:
                ok = False
            result[url] = (ok, (time.perf_counter() - started) * 1000)
    finally:
        session.close()
    return result


def connectivity_hint() -> str:
    """Короткая подсказка о том, как приложение ходит в сеть."""
    custom = str(config.get("custom_proxy", "")).strip()
    if custom:
        return f"через прокси {custom}"
    if config.get("use_system_proxy", True):
        return "системные настройки прокси"
    return "прямое соединение"
