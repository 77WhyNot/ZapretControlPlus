"""Google: Gemini, AI Studio и Antigravity.

Три вещи мешают сервисам Google работать из России, и лечатся они по-разному:

1. **Маршрут.** Сервисы Google должны идти через VPN целиком — иначе Google
   видит российский адрес. Для этого есть правила по доменам: они работают
   в любом режиме, даже если в туннель отправлены только отдельные программы.
2. **Прокси для языкового сервера Antigravity.** Внутри Antigravity работает
   ``language_server.exe`` на Go, а программы на Go **не читают системный
   прокси Windows** — только переменные окружения ``HTTP(S)_PROXY``. Поэтому
   в режиме «Прокси» окно открывается, а модели не отвечают. Лечится запуском
   Antigravity с нужными переменными — этим и занимается ``launch``.
3. **Страна аккаунта.** Google смотрит не только на адрес, но и на страну
   самого аккаунта Google. Если она российская, ответ будет
   ``Your current account is not eligible … not available in your location``
   даже через идеальный VPN. Сеть тут бессильна, и честнее сказать это прямо,
   чем гонять человека по настройкам.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.core import logs, winapi
from app.core.constants import USER_AGENT

# Домены, которым нужен VPN. Список намеренно узкий: чем меньше уходит в
# туннель, тем быстрее работает всё остальное.
VPN_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "googleapis.com",          # cloudcode-pa, generativelanguage, www
    "antigravity.google",
    "gemini.google.com",
    "aistudio.google.com",
    "notebooklm.google.com",
    "accounts.google.com",
    "ai.google.dev",
    "labs.google",
    ".goog",                   # antigravity-unleash.goog
    "googleusercontent.com",   # аватарки и вложения
)

# Процессы Antigravity. Модели вызывает именно языковой сервер, а не окно —
# поэтому в списке программ VPN должен быть он, иначе «выбранные программы»
# не помогают.
PROCESSES: tuple[str, ...] = (
    "Antigravity.exe",
    "language_server.exe",
    "agy.exe",
)

# Куда Antigravity ставится на Windows.
APP_PATHS = (
    r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe",
    r"%LOCALAPPDATA%\Programs\Antigravity IDE\Antigravity.exe",
    r"%PROGRAMFILES%\Antigravity\Antigravity.exe",
)
LOG_PATH = r"%APPDATA%\Antigravity\logs\language_server.log"

# Проба страны: ключ заведомо неверный, поэтому ответ ничего не раскрывает,
# зато по тексту ошибки видно, годится ли Google наш адрес.
LOCATION_PROBE = "https://generativelanguage.googleapis.com/v1beta/models"
LOCATION_PROBE_KEY = "AIzaSyINVALID-LOCATION-PROBE"

CHECK_URLS = (
    ("Gemini", "https://gemini.google.com/"),
    ("AI Studio", "https://aistudio.google.com/"),
    ("Antigravity", "https://antigravity.google/"),
    ("Antigravity API", "https://cloudcode-pa.googleapis.com/"),
    ("Antigravity API (daily)", "https://daily-cloudcode-pa.googleapis.com/"),
)

ACCOUNT_MARKERS = (
    "not currently available in your location",
    "not eligible for gemini",
    "not eligible for antigravity",
    "user location is not supported",
)
NETWORK_MARKERS = (
    "context deadline exceeded",
    "no such host",
    "connection refused",
    "proxyconnect",
    "i/o timeout",
    "tls handshake",
)


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(path))


# --- Antigravity на диске -------------------------------------------------


def find_app() -> Path | None:
    for candidate in APP_PATHS:
        path = _expand(candidate)
        if path.is_file():
            return path
    return None


def language_server() -> Path | None:
    app = find_app()
    if app is None:
        return None
    candidate = app.parent / "resources" / "bin" / "language_server.exe"
    return candidate if candidate.is_file() else None


def is_running() -> bool:
    return bool(winapi.find_processes("Antigravity.exe"))


def version() -> str:
    """Версию берём из папки product.json — она рядом с exe."""
    app = find_app()
    if app is None:
        return ""
    product = app.parent / "resources" / "app" / "product.json"
    try:
        text = product.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r'"version"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""


# --- запуск через VPN -----------------------------------------------------


def build_environment(proxy_url: str | None) -> dict[str, str]:
    """Окружение для Antigravity: именно оно и заворачивает Go в наш прокси."""
    environment = dict(os.environ)
    proxy_keys = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
    if proxy_url:
        for key in proxy_keys:
            environment[key] = proxy_url
        # Сам себе Antigravity ходит по localhost — туда прокси не нужен.
        for key in ("NO_PROXY", "no_proxy"):
            environment[key] = "localhost,127.0.0.1,::1"
    else:
        # Без VPN переменные только навредят: языковой сервер будет стучаться
        # в несуществующий прокси.
        for key in proxy_keys:
            environment.pop(key, None)
    return environment


def launch(proxy_url: str | None = None) -> str:
    """Запустить Antigravity, подсунув языковому серверу наш прокси."""
    app = find_app()
    if app is None:
        raise RuntimeError(
            "Antigravity не найден. Обычно он ставится в "
            "%LOCALAPPDATA%\\Programs\\Antigravity."
        )
    if is_running():
        raise RuntimeError(
            "Antigravity уже запущен. Закройте его полностью (вместе со значком "
            "в трее) и нажмите ещё раз — переменные окружения читаются только "
            "при старте."
        )

    environment = build_environment(proxy_url)
    logs.info(f"Antigravity запускается через прокси {proxy_url}" if proxy_url
              else "Antigravity запускается без прокси")

    try:
        subprocess.Popen(
            [str(app)], cwd=str(app.parent), env=environment,
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Не удалось запустить Antigravity: {exc}") from exc
    return ("Antigravity запущен через VPN." if proxy_url
            else "Antigravity запущен обычным образом.")


# --- что говорит сам Antigravity ------------------------------------------


@dataclass
class Diagnosis:
    kind: str          # account | network | ok | unknown
    message: str
    detail: str = ""


def read_log_tail(limit: int = 200_000) -> str:
    path = _expand(LOG_PATH)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - limit, 0))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def diagnose_log() -> Diagnosis:
    """Разобрать журнал языкового сервера: сеть виновата или аккаунт."""
    text = read_log_tail()
    if not text:
        return Diagnosis(
            "unknown",
            "Журнал Antigravity пока пуст — запустите его и попробуйте задать "
            "вопрос модели, потом проверьте ещё раз.",
        )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    account = [line for line in lines
               if any(marker in line.lower() for marker in ACCOUNT_MARKERS)]
    network = [line for line in lines
               if any(marker in line.lower() for marker in NETWORK_MARKERS)]

    if account:
        return Diagnosis(
            "account",
            "Google отказывает не сети, а аккаунту: «ваш аккаунт недоступен в "
            "вашей стране». VPN тут уже ни при чём — запросы доходят, отказ "
            "приходит от самого Google.",
            _tail(account[-1]),
        )
    if network:
        return Diagnosis(
            "network",
            "Языковой сервер Antigravity не достучался до серверов Google. "
            "Это как раз лечится: включите VPN и запустите Antigravity кнопкой "
            "ниже — иначе его серверная часть ходит мимо прокси.",
            _tail(network[-1]),
        )
    return Diagnosis(
        "ok",
        "В журнале Antigravity нет ни сетевых ошибок, ни отказов по стране.",
    )


def _tail(line: str) -> str:
    """Убрать из строки журнала служебный префикс Go."""
    cleaned = re.sub(r"^.*?\]\s*", "", line)
    cleaned = cleaned.replace("ERROR: logging before google.Init:", "").strip()
    return cleaned[:300]


# --- проверки по сети -----------------------------------------------------


@dataclass
class GoogleCheck:
    exit_ip: str = ""
    exit_country: str = ""
    location_ok: bool = False
    location_note: str = ""
    hosts: list[tuple[str, bool, str]] = field(default_factory=list)
    error: str = ""


def _session(proxy_url: str | None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def check(proxy_url: str | None = None) -> GoogleCheck:
    """Каким нас видит Google и пускает ли он нас по стране."""
    result = GoogleCheck()
    session = _session(proxy_url)
    try:
        try:
            data = session.get("https://ipinfo.io/json", timeout=10).json()
            result.exit_ip = str(data.get("ip") or "")
            result.exit_country = str(data.get("country") or "")
        except (requests.RequestException, ValueError):
            result.error = "Не удалось узнать свой адрес — проверьте интернет."

        # Ключ неверный намеренно: нас интересует не ответ, а текст ошибки.
        try:
            response = session.get(
                LOCATION_PROBE, params={"key": LOCATION_PROBE_KEY}, timeout=12
            )
            message = ""
            try:
                message = str(response.json().get("error", {}).get("message", ""))
            except ValueError:
                message = response.text[:200]
            lowered = message.lower()
            if "location is not supported" in lowered:
                result.location_ok = False
                result.location_note = (
                    "Google не обслуживает страну, из которой мы выходим. "
                    "Смените сервер VPN — подойдут Нидерланды, Германия, США."
                )
            elif "api key not valid" in lowered or response.status_code in (400, 403):
                result.location_ok = "location is not supported" not in lowered
                result.location_note = (
                    "Страна выхода Google подходит: он дошёл до проверки ключа."
                )
            else:
                result.location_note = message[:200] or "Google ответил молча."
        except requests.RequestException as exc:
            result.location_note = f"Проба страны не прошла: {type(exc).__name__}."

        for title, url in CHECK_URLS:
            try:
                response = session.get(url, timeout=10, allow_redirects=False)
                # 404 у служебных API — это «сервер на месте», а не ошибка.
                ok = response.status_code < 500
                result.hosts.append((title, ok, f"код {response.status_code}"))
            except requests.RequestException as exc:
                result.hosts.append((title, False, type(exc).__name__))
    finally:
        session.close()
    return result


# --- ссылки для человека --------------------------------------------------

LINK_ACCOUNT_COUNTRY = "https://myaccount.google.com/payments-and-subscriptions"
LINK_AVAILABILITY = (
    "https://developers.google.com/gemini-code-assist/resources/available-locations"
)
LINK_ANTIGRAVITY = "https://antigravity.google/"
LINK_PATCHER = "https://github.com/AvenCores/open-antigravity-patcher"
