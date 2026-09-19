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
import socket
import ssl
import subprocess
import time
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

# Хост, которым проверяем маршрут: тот же googleapis.com, куда ходит
# языковой сервер Antigravity. Спросить у Google «какую страну ты видишь» без
# ключа нельзя — он сначала проверяет ключ, а уже потом страну, — поэтому
# смотрим прямо в движок: каким выходом он пустил соединение.
ROUTE_PROBE_HOST = "generativelanguage.googleapis.com"

# Страны, где Gemini и Antigravity Google не обслуживает.
UNSUPPORTED_COUNTRIES = {"RU", "BY", "CN", "HK", "MO", "IR", "KP", "SY", "CU"}

CHECK_URLS = (
    ("Gemini", "https://gemini.google.com/"),
    ("AI Studio", "https://aistudio.google.com/"),
    ("Antigravity", "https://antigravity.google/"),
    ("Antigravity API", "https://cloudcode-pa.googleapis.com/"),
    ("Antigravity API (daily)", "https://daily-cloudcode-pa.googleapis.com/"),
)

# Две похожие ошибки с разным смыслом. «Account … not eligible» — отказ самому
# аккаунту по его стране, сеть тут бессильна. «User location is not supported» —
# Google посмотрел на адрес запроса и увидел Россию: запрос ушёл мимо VPN.
ACCOUNT_MARKERS = (
    "not currently available in your location",
    "not eligible for gemini",
    "not eligible for antigravity",
)
LOCATION_MARKERS = (
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

    # Смотрим на самую свежую из ошибок: человек мог уже что-то починить.
    latest: tuple[int, str, str] | None = None
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in LOCATION_MARKERS):
            latest = (index, "location", line)
        elif any(marker in lowered for marker in ACCOUNT_MARKERS):
            latest = (index, "account", line)
        elif any(marker in lowered for marker in NETWORK_MARKERS):
            latest = (index, "network", line)

    if latest is None:
        return Diagnosis(
            "ok",
            "В журнале Antigravity нет ни сетевых ошибок, ни отказов по стране.",
        )
    _index, kind, line = latest
    messages = {
        "location": (
            "Google посмотрел на адрес запроса и увидел Россию — запрос "
            "Antigravity ушёл мимо VPN. Аккаунт тут ни при чём. Обычно "
            "протекает одно из трёх: режим «Прокси» (тогда Antigravity нужно "
            "запускать кнопкой «Запустить через VPN»), «только выбранные "
            "программы» без языкового сервера или IPv6 мимо туннеля. Нажмите "
            "«Проверить Google» — программа покажет, какой путь протекает."
        ),
        "account": (
            "Google отказывает не сети, а аккаунту: «ваш аккаунт недоступен в "
            "вашей стране». VPN тут уже ни при чём — запросы доходят, отказ "
            "приходит от самого Google."
        ),
        "network": (
            "Языковой сервер Antigravity не достучался до серверов Google. "
            "Это как раз лечится: включите VPN и запустите Antigravity кнопкой "
            "ниже — иначе его серверная часть ходит мимо прокси."
        ),
    }
    return Diagnosis(kind, messages[kind], _tail(line))


def _tail(line: str) -> str:
    """Убрать из строки журнала служебный префикс Go."""
    cleaned = re.sub(r"^.*?\]\s*", "", line)
    cleaned = cleaned.replace("ERROR: logging before google.Init:", "").strip()
    return cleaned[:300]


# --- проверки по сети -----------------------------------------------------


@dataclass
class GoogleCheck:
    # Выход VPN: какой адрес и какую страну видит мир через туннель.
    exit_ip: str = ""
    exit_country: str = ""
    country_ok: bool | None = None
    country_note: str = ""
    # Каким путём движок на деле пускает запросы к серверам Google — тем,
    # которым ходит языковой сервер Antigravity. None — VPN выключен.
    route_ok: bool | None = None
    route_note: str = ""
    # IPv6 мимо туннеля. None — по IPv6 до Google не дойти, утечь нечему.
    ipv6_ok: bool | None = None
    ipv6_note: str = ""
    hosts: list[tuple[str, bool, str]] = field(default_factory=list)
    verdict: str = ""
    verdict_ok: bool = False


def _session(proxy_url: str | None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _exit_country(proxy_url: str | None) -> tuple[str, str]:
    session = _session(proxy_url)
    try:
        data = session.get("https://ipinfo.io/json", timeout=10).json()
        return str(data.get("ip") or ""), str(data.get("country") or "")
    except (requests.RequestException, ValueError):
        return "", ""
    finally:
        session.close()


def _route_to_google(timeout: float = 8.0) -> tuple[bool | None, str]:
    """Открыть соединение к googleapis.com так, как это делает программа на Go,
    — без всякого прокси, — и спросить у движка, каким выходом он его пустил.
    """
    from app.core.vpn.engine import vpn_engine

    if not vpn_engine.status().running:
        return None, "VPN выключен — запросы к Google идут напрямую."

    context = ssl.create_default_context()
    try:
        raw = socket.create_connection((ROUTE_PROBE_HOST, 443), timeout=timeout)
    except OSError as exc:
        return False, f"до серверов Google не достучаться: {type(exc).__name__}"
    try:
        with context.wrap_socket(raw, server_hostname=ROUTE_PROBE_HOST) as tls:
            local_port = tls.getsockname()[1]
            chain: list[str] | None = None
            for _ in range(6):
                for item in vpn_engine.active_connections():
                    meta = item.get("metadata") or {}
                    host = str(meta.get("host") or "")
                    port = str(meta.get("sourcePort") or "")
                    if host == ROUTE_PROBE_HOST and port == str(local_port):
                        chain = [str(part) for part in item.get("chains") or []]
                        break
                if chain is not None:
                    break
                time.sleep(0.25)
    except OSError as exc:
        return False, f"соединение с Google оборвалось: {type(exc).__name__}"

    if chain is None:
        # Движок соединения не видел — значит, оно прошло мимо него.
        return False, ("Запросы к Google идут мимо VPN: движок их даже не видит. "
                       "Так ходят программы, не читающие системный прокси.")
    if not chain or chain[0] == "direct":
        return False, "Движок пустил запрос к Google напрямую, мимо VPN."
    return True, f"Запросы к Google идут через VPN (сервер «{chain[0]}»)."


def _ipv6_to_google(tunnel_ipv6: bool, timeout: float = 4.0) -> tuple[bool | None, str]:
    """Может ли компьютер дойти до Google по IPv6 — мимо туннеля без IPv6."""
    try:
        infos = socket.getaddrinfo(ROUTE_PROBE_HOST, 443, socket.AF_INET6,
                                   socket.SOCK_STREAM)
    except OSError:
        infos = []
    if not infos:
        return None, "IPv6-адресов Google не выдаётся — по IPv6 утечь нечему."
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as raw:
            raw.settimeout(timeout)
            raw.connect(infos[0][4])
    except OSError:
        return None, "IPv6 до Google не проходит — утечки нет."
    if tunnel_ipv6:
        return True, "IPv6 работает и пущен в туннель."
    return False, ("Компьютер ходит к Google по IPv6 напрямую, мимо туннеля — "
                   "Google видит российский адрес.")


def check(proxy_url: str | None = None, vpn_running: bool = False,
          transport: str = "tun", tunnel_ipv6: bool = False) -> GoogleCheck:
    """Каким путём запросы к Google уходят на самом деле и что видит Google.

    Протечь может любой путь: программа мимо системного прокси, программа не
    из списка «выбранных», IPv6. Проверяем все.
    """
    from app.core.vpn.engine import vpn_engine

    result = GoogleCheck()

    # Выход VPN берём через служебный вход движка: он всегда заведён в туннель.
    local = vpn_engine.local_proxy_url() if vpn_running else None
    result.exit_ip, result.exit_country = _exit_country(local)
    if not vpn_running:
        result.country_ok = None
        result.country_note = "VPN выключен."
    elif not result.exit_country:
        result.country_note = "Не удалось узнать страну выхода VPN."
    elif result.exit_country.upper() in UNSUPPORTED_COUNTRIES:
        result.country_ok = False
        result.country_note = (f"Выход VPN — {result.exit_country}: там Gemini и "
                               "Antigravity Google не обслуживает.")
    else:
        result.country_ok = True
        result.country_note = f"Выход VPN — {result.exit_country}, Google её обслуживает."

    result.route_ok, result.route_note = _route_to_google()
    result.ipv6_ok, result.ipv6_note = _ipv6_to_google(tunnel_ipv6)

    session = _session(proxy_url)
    try:
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

    result.verdict, result.verdict_ok = _verdict(result, vpn_running, transport)
    return result


def _verdict(result: GoogleCheck, vpn_running: bool, transport: str) -> tuple[str, bool]:
    """Одна фраза: что протекает и что с этим делать."""
    if not vpn_running:
        return ("VPN выключен — Google видит российский адрес и отвечает «User "
                "location is not supported». Включите VPN.", False)
    if result.country_ok is False:
        return ("VPN выходит в стране, которую Google не обслуживает. Смените "
                "сервер — подойдут Латвия, Нидерланды, Германия, Швеция, США.", False)
    if result.route_ok is False:
        if transport == "proxy":
            return ("Браузер ходит через VPN, а программы, которые не читают "
                    "системный прокси, — напрямую. Среди них языковой сервер "
                    "Antigravity: запускайте его кнопкой «Запустить через VPN» или "
                    "переключите VPN на «Туннель».", False)
        return ("Запросы к Google идут мимо VPN. Включите «Google всегда через "
                "VPN» ниже — или отправьте в туннель весь трафик.", False)
    if result.ipv6_ok is False:
        return ("Запросы по IPv6 идут мимо туннеля. Перезапустите VPN: новая "
                "версия больше не раздаёт IPv6-адреса, и всё пойдёт через туннель.",
                False)
    return ("Сеть в порядке: запросы к Google идут через VPN, страна выхода "
            "подходит, утечек нет. Если Antigravity всё равно отказывает — "
            "нажмите «Почему не работает»: скорее всего, дело в стране аккаунта.",
            True)


# --- ссылки для человека --------------------------------------------------

LINK_ACCOUNT_COUNTRY = "https://myaccount.google.com/payments-and-subscriptions"
LINK_AVAILABILITY = (
    "https://developers.google.com/gemini-code-assist/resources/available-locations"
)
LINK_ANTIGRAVITY = "https://antigravity.google/"
LINK_PATCHER = "https://github.com/AvenCores/open-antigravity-patcher"
