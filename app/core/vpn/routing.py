"""«Российские сайты — напрямую»: маршруты по профилю Happ «RU direct».

Сайты в российских зонах, банки, маркетплейсы, Яндекс и VK, а также
российские сети идут мимо VPN: с зарубежного адреса многие из них не
открываются или просят подтверждений. YouTube, Telegram и сервисы, которые
сами закрылись для России, наоборот, остаются в туннеле — даже если их
кэш-сервер стоит у российского провайдера и адрес у него российский.

Списки — проект roscomvpn (github.com/hydraponique): доменные и IP-наборы
в формате sing-box. Доменные наборы (MIT) вшиты в программу на день сборки,
IP-наборы скачиваются при первом включении. Свежие копии — раз в сутки.
Движок сам перечитывает локальный набор, когда файл на диске меняется.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import logs, net, paths
from app.core.config import config

_GEOSITE = ("https://raw.githubusercontent.com/hydraponique/roscomvpn-geosite/"
            "master/release/sing-box/{name}.srs")
_GEOIP = ("https://raw.githubusercontent.com/hydraponique/roscomvpn-geoip/"
          "master/release/sing-box/{name}.srs")

REFRESH_SECONDS = 24 * 3600
# Неудачную попытку не повторяем на каждом запуске VPN — раз в полчаса.
RETRY_SECONDS = 30 * 60


@dataclass(frozen=True)
class RuleSet:
    tag: str
    url: str
    file: str
    kind: str  # "domain" | "ip"


# Мимо VPN: категория «ru», белый список и частные адреса (geosite и geoip).
DIRECT_SETS = (
    RuleSet("ru-sites", _GEOSITE.format(name="category-ru"), "geosite-category-ru.srs", "domain"),
    RuleSet("ru-whitelist", _GEOSITE.format(name="whitelist"), "geosite-whitelist.srs", "domain"),
    RuleSet("ru-private", _GEOSITE.format(name="private"), "geosite-private.srs", "domain"),
    RuleSet("ru-networks", _GEOIP.format(name="direct"), "geoip-direct.srs", "ip"),
    RuleSet("ru-private-ip", _GEOIP.format(name="private"), "geoip-private.srs", "ip"),
)

# Всегда в VPN, даже если адрес российский.
VPN_SETS = (
    RuleSet("vpn-youtube", _GEOSITE.format(name="youtube"), "geosite-youtube.srs", "domain"),
    RuleSet("vpn-telegram", _GEOSITE.format(name="telegram"), "geosite-telegram.srs", "domain"),
    RuleSet("vpn-geoblock", _GEOSITE.format(name="category-geoblock-ru"),
            "geosite-category-geoblock-ru.srs", "domain"),
)

ALL_SETS = DIRECT_SETS + VPN_SETS

# Домены из профиля: зоны .ru, .su, .рф, .москва, .tatar и сервисы на
# других зонах, которым нужен российский адрес. В sing-box «vk.com»
# совпадает и с самим доменом, и со всеми поддоменами.
DIRECT_DOMAINS = (
    "ru", "su", "xn--p1ai", "xn--80adxhks", "moscow", "tatar",
    "2gis.com", "alfabank.com", "avito.st", "dodobrands.io", "dodois.com",
    "dodois.io", "dodostatic.net", "ivi.tv", "lenta.com", "max.ru", "more.tv",
    "mradx.net", "mycdn.me", "okko.tv", "oneme.ru", "ozonusercontent.com",
    "pobeda.aero", "premier.one", "sberbank.com", "tinkoff.com", "uni.rest",
    "userapi.com", "vk-cdn.net", "vk.cc", "vk.com", "vk.company", "vk.me",
    "vkuser.net", "vtb.com", "wbcontent.net", "wbstatic.net", "yadi.sk",
    "yandex.cloud", "yandex.com", "yandex.net", "yandexcloud.net", "yastatic.net",
)

_refresh_lock = threading.Lock()


def enabled() -> bool:
    return bool(config.get("vpn_ru_direct", True))


def folder() -> Path:
    path = paths.data_dir() / "routing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bundled(item: RuleSet) -> Path:
    return paths.resource_path("routing", item.file)


def prepare() -> dict[str, Path]:
    """Наборы для конфига: скачанные или вшитые. Сеть не трогает.

    IP-наборы в программу не вшиты: пока они не скачались, на их месте пустой
    набор. Движок следит за файлом и подхватит настоящий, как только тот
    подменит заглушку, — без перезапуска VPN.
    """
    result: dict[str, Path] = {}
    for item in ALL_SETS:
        target = folder() / item.file
        if not _usable(target):
            source = _bundled(item)
            if not source.exists():
                source = paths.resource_path("routing", "empty.srs")
            if source.exists():
                try:
                    shutil.copyfile(source, target)
                except OSError as exc:
                    logs.warn(f"Не удалось подготовить список {item.file}: {exc}")
        if _usable(target):
            result[item.tag] = target
    return result


def _usable(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def lists_date() -> float:
    """Когда списки последний раз скачивались (0 — пока только вшитые)."""
    return float(config.get("vpn_ru_lists_updated", 0) or 0)


def has_networks() -> bool:
    """Скачаны ли российские сети: без них работают только доменные правила."""
    return lists_date() > 0


def refresh_due() -> bool:
    checked = float(config.get("vpn_ru_lists_checked", 0) or 0)
    # Пока списки ни разу не скачались, пробуем чаще: сетей ещё нет вовсе.
    interval = REFRESH_SECONDS if lists_date() > 0 else RETRY_SECONDS
    return time.time() - checked > interval


def refresh(force: bool = False) -> int:
    """Скачать свежие наборы. Возвращает, сколько файлов обновилось.

    Файл подменяется целиком (через .part), поэтому работающий движок
    никогда не прочтёт его наполовину.
    """
    if not force and not refresh_due():
        return 0
    if not _refresh_lock.acquire(blocking=False):
        return 0
    updated = 0
    try:
        config.set("vpn_ru_lists_checked", int(time.time()))
        session = net.build_session()
        try:
            for item in ALL_SETS:
                target = folder() / item.file
                try:
                    data = net.fetch(item.url, session=session)
                except net.NetworkError:
                    continue
                # Набор sing-box начинается с сигнатуры «SRS».
                if len(data) < 8 or not data.startswith(b"SRS"):
                    logs.warn(f"Список {item.file} пришёл повреждённым — оставляю старый")
                    continue
                temp = target.with_suffix(".part")
                try:
                    temp.write_bytes(data)
                    temp.replace(target)
                    updated += 1
                except OSError as exc:
                    temp.unlink(missing_ok=True)
                    logs.warn(f"Не удалось сохранить {item.file}: {exc}")
        finally:
            session.close()
        # Дату ставим, только если пришло всё: иначе повторим через полчаса.
        if updated == len(ALL_SETS):
            config.set("vpn_ru_lists_updated", int(time.time()))
        if updated:
            logs.info(f"Списки «Российские сайты — напрямую» обновлены: "
                      f"{updated} из {len(ALL_SETS)}")
    finally:
        _refresh_lock.release()
    return updated


def refresh_async(force: bool = False) -> None:
    if force or refresh_due():
        threading.Thread(target=refresh, args=(force,), daemon=True,
                         name="ru-direct-lists").start()


# --- правила для sing-box -------------------------------------------------


def rule_set_entries(available: dict[str, Path]) -> list[dict[str, Any]]:
    return [
        {"type": "local", "tag": tag, "format": "binary", "path": str(path)}
        for tag, path in available.items()
    ]


def _tags(available: dict[str, Path], sets: tuple[RuleSet, ...], kind: str) -> list[str]:
    return [item.tag for item in sets if item.kind == kind and item.tag in available]


def vpn_rule(available: dict[str, Path], outbound: str,
             **match: Any) -> dict[str, Any] | None:
    """YouTube, Telegram и закрытые для России сервисы — в туннель."""
    tags = _tags(available, VPN_SETS, "domain")
    if not tags:
        return None
    return {**match, "rule_set": tags, "outbound": outbound}


def direct_rules(available: dict[str, Path], outbound: str) -> list[dict[str, Any]]:
    """Российские домены и сети — мимо туннеля.

    Домены и сети — отдельными правилами: так их смысл не зависит от того,
    как движок сочетает разнотипные наборы внутри одного правила.
    """
    rules: list[dict[str, Any]] = [{
        "domain_suffix": list(DIRECT_DOMAINS),
        **({"rule_set": _tags(available, DIRECT_SETS, "domain")}
           if _tags(available, DIRECT_SETS, "domain") else {}),
        "outbound": outbound,
    }]
    ip_tags = _tags(available, DIRECT_SETS, "ip")
    if ip_tags:
        rules.append({"rule_set": ip_tags, "outbound": outbound})
    return rules


def dns_rule(available: dict[str, Path], server: str) -> dict[str, Any]:
    """Имена российских сайтов спрашиваем у обычного DNS, а не через туннель."""
    rule: dict[str, Any] = {"domain_suffix": list(DIRECT_DOMAINS), "server": server}
    tags = _tags(available, DIRECT_SETS, "domain")
    if tags:
        rule["rule_set"] = tags
    return rule
