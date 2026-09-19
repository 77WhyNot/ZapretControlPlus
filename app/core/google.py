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
    google_country: str = ""     # страна выхода VPN по базе самого Google
    country_ok: bool | None = None
    country_note: str = ""
    smartdns: bool = False       # Gemini и Antigravity идут через прокси Smart DNS
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


def _route_to_google(timeout: float = 8.0,
                     proxy_ip: str = "") -> tuple[bool | None, str]:
    """Открыть соединение к googleapis.com так, как это делает программа на Go,
    — без всякого прокси, — и спросить у движка, каким выходом он его пустил.

    proxy_ip — адрес прокси Smart DNS, если Google пускается через него: тогда
    выход «direct» на этот адрес и есть правильный путь.
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
            destination = ""
            for _ in range(6):
                for item in vpn_engine.active_connections():
                    meta = item.get("metadata") or {}
                    host = str(meta.get("host") or "")
                    port = str(meta.get("sourcePort") or "")
                    if host == ROUTE_PROBE_HOST and port == str(local_port):
                        chain = [str(part) for part in item.get("chains") or []]
                        destination = str(meta.get("destinationIP") or "")
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
    if chain and chain[0] == "direct" and proxy_ip:
        if destination in ("", proxy_ip):
            return True, f"Запросы к Google идут через прокси Smart DNS ({proxy_ip})."
        return False, "Запрос к Google ушёл напрямую, но не на прокси Smart DNS."
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
    из списка «выбранных», IPv6. А ещё Google может считать сам выход VPN
    российским — это видно только по его собственной базе адресов.
    """
    from app.core.config import config
    from app.core.vpn.engine import vpn_engine

    result = GoogleCheck()
    proxy_ip = ""
    if str(config.get("google_route", "smartdns")) == "smartdns":
        cached = config.get("google_proxy", {}) or {}
        if isinstance(cached, dict) and ROUTE_PROBE_HOST in (cached.get("hosts") or []):
            proxy_ip = str(cached.get("ip") or "")
    result.smartdns = bool(proxy_ip)

    # Выход VPN берём через служебный вход движка: он всегда заведён в туннель.
    local = vpn_engine.local_proxy_url() if vpn_running else None
    result.exit_ip, result.exit_country = _exit_country(local)
    result.google_country = google_country(local) if vpn_running else ""
    if not vpn_running:
        result.country_ok = None
        result.country_note = "VPN выключен."
    elif result.google_country and result.google_country in UNSUPPORTED_COUNTRIES:
        result.country_ok = False
        result.country_note = (
            f"По базе Google выход VPN — {result.google_country}"
            + (f", хотя сервер в {result.exit_country}" if result.exit_country
               and result.exit_country != result.google_country else "")
            + ". Через такой выход Gemini и Antigravity не пускают."
        )
    elif result.exit_country.upper() in UNSUPPORTED_COUNTRIES:
        result.country_ok = False
        result.country_note = (f"Выход VPN — {result.exit_country}: там Gemini и "
                               "Antigravity Google не обслуживает.")
    elif result.google_country or result.exit_country:
        result.country_ok = True
        result.country_note = (
            f"По базе Google выход VPN — {result.google_country or result.exit_country}, "
            "эту страну Google обслуживает."
        )
    else:
        result.country_note = "Не удалось узнать страну выхода VPN."

    result.route_ok, result.route_note = _route_to_google(proxy_ip=proxy_ip)
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
    if result.route_ok is False:
        if transport == "proxy":
            return ("Браузер ходит как надо, а программы, которые не читают "
                    "системный прокси, — напрямую. Среди них языковой сервер "
                    "Antigravity: запускайте его кнопкой «Запустить через VPN» или "
                    "переключите VPN на «Туннель».", False)
        return ("Запросы к Google идут мимо нужного пути. Перезапустите VPN — "
                "правила применятся заново.", False)
    if result.smartdns and result.route_ok:
        if result.ipv6_ok is False:
            return ("Запросы по IPv6 идут мимо туннеля. Перезапустите VPN: новая "
                    "версия больше не раздаёт IPv6-адреса.", False)
        return ("Gemini и Antigravity идут через прокси Smart DNS — у него адрес, "
                "который Google не считает российским. Если Antigravity всё равно "
                "отказывает, нажмите «Почему не работает»: дело, скорее всего, в "
                "стране самого аккаунта.", True)
    if result.country_ok is False:
        return ("Google считает выход вашего VPN российским — через него Gemini и "
                "Antigravity не заработают, какой сервер ни выбирай у этой "
                "подписки. Выберите путь «Через прокси Smart DNS» выше.", False)
    if result.ipv6_ok is False:
        return ("Запросы по IPv6 идут мимо туннеля. Перезапустите VPN: новая "
                "версия больше не раздаёт IPv6-адреса, и всё пойдёт через туннель.",
                False)
    return ("Сеть в порядке: запросы к Google идут через VPN, и Google видит "
            "подходящую страну. Если Antigravity всё равно отказывает — нажмите "
            "«Почему не работает»: скорее всего, дело в стране аккаунта.", True)


# --- Google через прокси Smart DNS ----------------------------------------
#
# Главная беда: Google по своей базе считает адреса многих VPN российскими —
# у некоторых подписок все серверы подряд, включая «США» и «Германию». Тогда
# через VPN Gemini и Antigravity отвечают «User location is not supported»,
# и маршрут тут бессилен. Сервисы Smart DNS (Xbox DNS, Comss) держат свои
# прокси с «чистыми» для Google адресами: подключаемся к такому прокси, а в
# TLS называем нужный сайт — прокси передаёт соединение Google как есть,
# шифрование не вскрывается.

# Хосты, которые Google проверяет по стране. Кроме них ничего на прокси не
# отправляем: остальному Google (почта, YouTube) это не нужно.
AI_HOSTS: tuple[str, ...] = (
    "gemini.google.com",
    "aistudio.google.com",
    "generativelanguage.googleapis.com",
    "alkalimakersuite-pa.clients6.google.com",
    "cloudcode-pa.googleapis.com",
    "daily-cloudcode-pa.googleapis.com",
    "antigravity.google",
    "antigravity-unleash.goog",
    "notebooklm.google.com",
)

SMART_DNS = {
    "xbox": ("Xbox DNS", ("https://xbox-dns.ru/dns-query",
                          "https://111.88.96.50/dns-query")),
    "comss": ("Comss DNS", ("https://dns.comss.one/dns-query",)),
}
PROXY_MAX_AGE = 12 * 3600


def _doh_a(urls: tuple[str, ...], name: str) -> str:
    """Один A-запрос по DoH: так ответ не перехватывает наш же туннель."""
    import base64
    import struct

    header = struct.pack(">HHHHHH", 0, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    packet = header + qname + b"\0" + struct.pack(">HH", 1, 1)
    encoded = base64.urlsafe_b64encode(packet).rstrip(b"=").decode()
    session = _session(None)
    try:
        for url in urls:
            try:
                response = session.get(
                    url, params={"dns": encoded}, timeout=8,
                    headers={"accept": "application/dns-message"},
                    # По голому IP сертификат на имя не сойдётся — это запасной путь.
                    verify=not url.startswith("https://111."),
                )
            except requests.RequestException:
                continue
            if response.status_code != 200:
                continue
            data = response.content
            count = struct.unpack(">H", data[6:8])[0]
            offset = 12
            while data[offset]:
                offset += data[offset] + 1
            offset += 5
            for _ in range(count):
                if data[offset] & 0xC0 == 0xC0:
                    offset += 2
                else:
                    while data[offset]:
                        offset += data[offset] + 1
                    offset += 1
                rtype, _cls, _ttl, length = struct.unpack(">HHIH", data[offset:offset + 10])
                offset += 10
                if rtype == 1 and length == 4:
                    return socket.inet_ntoa(data[offset:offset + 4])
                offset += length
    finally:
        session.close()
    return ""


def _passes(proxy_ip: str, host: str, timeout: float = 6.0) -> bool:
    """Пропускает ли прокси этот хост: настоящий сертификат Google и ответ."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((proxy_ip, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                tls.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\n"
                            "Connection: close\r\n\r\n".encode())
                return tls.recv(16).startswith(b"HTTP/")
    except (OSError, ssl.SSLError):
        return False


def discover_proxy(service: str) -> tuple[str, list[str]]:
    """Адрес прокси сервиса и хосты, которые он действительно пропускает."""
    from concurrent.futures import ThreadPoolExecutor

    title, urls = SMART_DNS.get(service, SMART_DNS["xbox"])
    proxy_ip = _doh_a(urls, "gemini.google.com")
    if not proxy_ip or proxy_ip.startswith(("142.", "172.217.", "216.239.", "74.125.")):
        # Сервис ответил адресом самого Google — прокси у него сейчас нет.
        logs.warn(f"{title}: прокси для Google не найден")
        return "", []
    with ThreadPoolExecutor(max_workers=len(AI_HOSTS)) as pool:
        results = list(pool.map(lambda host: (host, _passes(proxy_ip, host)), AI_HOSTS))
    hosts = [host for host, ok in results if ok]
    logs.info(f"{title}: прокси {proxy_ip}, пропускает {len(hosts)} из {len(AI_HOSTS)}")
    return proxy_ip, hosts


def smartdns_route(force: bool = False) -> tuple[str, list[str]]:
    """Прокси для маршрута Google — из кэша, если он свежий.

    Пустой адрес — путь выключен или прокси сейчас недоступен; тогда Google
    идёт общим правилом, через VPN.
    """
    from app.core.config import config

    if str(config.get("google_route", "smartdns")) != "smartdns":
        return "", []
    service = str(config.get("google_smartdns", "xbox"))
    cached = config.get("google_proxy", {}) or {}
    fresh = (isinstance(cached, dict) and cached.get("service") == service
             and cached.get("ip") and time.time() - float(cached.get("time", 0))
             < PROXY_MAX_AGE)
    if fresh and not force:
        return str(cached["ip"]), list(cached.get("hosts") or [])
    proxy_ip, hosts = discover_proxy(service)
    if proxy_ip and hosts:
        config.set("google_proxy", {"service": service, "ip": proxy_ip,
                                    "hosts": hosts, "time": int(time.time())})
        return proxy_ip, hosts
    # Сеть моргнула — лучше вчерашний адрес, чем никакого.
    if isinstance(cached, dict) and cached.get("service") == service and cached.get("ip"):
        return str(cached["ip"]), list(cached.get("hosts") or [])
    return "", []


def google_country(proxy_url: str | None, timeout: float = 20.0) -> str:
    """Какую страну Google видит для этого пути — по его собственной базе.

    YouTube вшивает в страницу код страны, определённый Google по адресу
    ("GL":"XX"). Это та же база, по которой Google решает, пускать ли в
    Gemini и Antigravity. Сервис ipinfo может говорить «Латвия», а Google
    при этом видеть Россию — именно это и ломает Antigravity через VPN.
    """
    session = _session(proxy_url)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "Chrome/126 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.8",
    })
    pattern = re.compile(rb'"GL":"([A-Z]{2})"')
    try:
        response = session.get("https://www.youtube.com/", timeout=timeout, stream=True)
        buffer = b""
        for chunk in response.iter_content(65536):
            buffer += chunk
            found = pattern.search(buffer)
            if found:
                response.close()
                return found.group(1).decode()
            if len(buffer) > 3_000_000:
                break
        response.close()
    except requests.RequestException:
        return ""
    finally:
        session.close()
    return ""


def scan_servers(servers: list) -> list[tuple[str, str, str]]:
    """Какую страну Google видит у каждого сервера подписки.

    Поднимаем отдельный sing-box: по локальному входу на каждый сервер, без
    TUN и без Clash API, — рабочий туннель не трогается. Возвращает
    (сервер, страна по ipinfo, страна по мнению Google).
    """
    import json
    from concurrent.futures import ThreadPoolExecutor

    from app.core import paths
    from app.core.vpn.engine import singbox_path

    outbounds = [dict(server.outbound) for server in servers if server.outbound]
    if not outbounds:
        return []
    ports = []
    for _ in outbounds:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            ports.append(probe.getsockname()[1])
    config = {
        "log": {"level": "error"},
        "dns": {"servers": [{"type": "local", "tag": "local"}], "final": "local"},
        "inbounds": [{"type": "mixed", "tag": f"scan-{index}", "listen": "127.0.0.1",
                      "listen_port": port} for index, port in enumerate(ports)],
        "outbounds": outbounds + [{"type": "direct", "tag": "direct"}],
        "route": {"rules": [{"inbound": [f"scan-{index}"], "outbound": item["tag"]}
                            for index, item in enumerate(outbounds)],
                  "final": "direct", "default_domain_resolver": "local"},
    }
    path = paths.data_dir() / "google-scan.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    exe = singbox_path()
    process = subprocess.Popen(
        [str(exe), "run", "-c", str(path), "--disable-color"], cwd=str(exe.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=winapi.CREATE_NO_WINDOW,
    )

    def one(index: int) -> tuple[str, str, str]:
        proxy = f"http://127.0.0.1:{ports[index]}"
        ip_country = _exit_country(proxy)[1]
        return outbounds[index]["tag"], ip_country, google_country(proxy)

    try:
        time.sleep(2.0)
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(one, range(len(outbounds))))
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
        try:
            path.unlink()
        except OSError:
            pass
    return rows


# --- ссылки для человека --------------------------------------------------

LINK_ACCOUNT_COUNTRY = "https://myaccount.google.com/payments-and-subscriptions"
LINK_AVAILABILITY = (
    "https://developers.google.com/gemini-code-assist/resources/available-locations"
)
LINK_ANTIGRAVITY = "https://antigravity.google/"
LINK_PATCHER = "https://github.com/AvenCores/open-antigravity-patcher"
