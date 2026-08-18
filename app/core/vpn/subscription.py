"""Загрузка и хранение подписки.

Ссылка на подписку — это личные данные пользователя, поэтому она хранится
только на его машине, рядом с остальными настройками, и никуда не отправляется.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.core import logs, paths
from app.core.config import config
from app.core.constants import USER_AGENT
from app.core.vpn.links import Server, parse_many

FETCH_TIMEOUT = (8, 25)
# Часть панелей отдаёт разный формат в зависимости от клиента.
CLIENT_AGENTS = (USER_AGENT, "v2rayNG/1.8.5", "sing-box/1.13.0")


@dataclass
class SubscriptionInfo:
    """Сведения из заголовка subscription-userinfo."""

    title: str = ""
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0
    updated_at: int = 0
    server_count: int = 0

    @property
    def used(self) -> int:
        return self.upload + self.download

    @property
    def has_quota(self) -> bool:
        return self.total > 0

    @property
    def left_bytes(self) -> int:
        return max(self.total - self.used, 0)

    @property
    def used_ratio(self) -> float:
        return min(self.used / self.total, 1.0) if self.total else 0.0

    @property
    def expire_date(self) -> datetime | None:
        if not self.expire:
            return None
        try:
            return datetime.fromtimestamp(self.expire, tz=timezone.utc).astimezone()
        except (OverflowError, OSError, ValueError):
            return None

    @property
    def days_left(self) -> int | None:
        date = self.expire_date
        if date is None:
            return None
        return max((date - datetime.now(date.tzinfo)).days, 0)

    @property
    def expire_label(self) -> str:
        date = self.expire_date
        if date is None:
            return "бессрочная"
        return date.strftime("%d.%m.%Y")


def format_bytes(value: int) -> str:
    step = 1024.0
    amount = float(value)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(amount) < step:
            return f"{amount:.0f} {unit}" if unit == "Б" else f"{amount:.1f} {unit}"
        amount /= step
    return f"{amount:.1f} ПБ"


def _parse_userinfo(header: str) -> dict[str, int]:
    """Разбор строки вида upload=0; download=100; total=200; expire=1700000000."""
    result: dict[str, int] = {}
    for chunk in header.split(";"):
        match = re.match(r"\s*(\w+)\s*=\s*(-?\d+)\s*$", chunk)
        if match:
            result[match.group(1).lower()] = int(match.group(2))
    return result


def _cache_path() -> Path:
    return paths.data_dir() / "subscription.json"


def load_cached() -> tuple[list[Server], SubscriptionInfo]:
    """Серверы из кэша — чтобы программа работала без сети."""
    path = _cache_path()
    if not path.exists():
        return [], SubscriptionInfo()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], SubscriptionInfo()

    servers = parse_many("\n".join(data.get("links") or []))
    info_data = data.get("info") or {}
    info = SubscriptionInfo(**{
        key: info_data.get(key, getattr(SubscriptionInfo(), key))
        for key in SubscriptionInfo().__dict__
    })
    info.server_count = len(servers)
    return servers, info


def save_cache(servers: list[Server], info: SubscriptionInfo) -> None:
    payload = {
        "links": [server.uri for server in servers if server.uri],
        "info": asdict(info),
    }
    try:
        _cache_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logs.warn(f"Не удалось сохранить подписку: {exc}")


def _session() -> requests.Session:
    session = requests.Session()
    custom = str(config.get("custom_proxy", "")).strip()
    if custom:
        session.proxies = {"http": custom, "https": custom}
        session.trust_env = False
    else:
        session.trust_env = bool(config.get("use_system_proxy", True))
    return session


def fetch(url: str) -> tuple[list[Server], SubscriptionInfo]:
    """Скачать подписку и разобрать её. Бросает RuntimeError с понятным текстом."""
    url = url.strip()
    if not url:
        raise RuntimeError("Ссылка на подписку не указана.")
    if not url.lower().startswith(("http://", "https://")):
        # Иногда вместо ссылки вставляют сам ключ — это тоже принимаем.
        servers = parse_many(url)
        if not servers:
            raise RuntimeError(
                "Это не похоже ни на ссылку-подписку, ни на ключ vless:// или ss://."
            )
        info = SubscriptionInfo(
            title="Ключ вручную", updated_at=int(time.time()), server_count=len(servers)
        )
        save_cache(servers, info)
        return servers, info

    session = _session()
    last_error = ""
    try:
        for agent in CLIENT_AGENTS:
            try:
                response = session.get(
                    url,
                    timeout=FETCH_TIMEOUT,
                    headers={"User-Agent": agent, "Accept": "*/*"},
                )
            except requests.RequestException as exc:
                last_error = type(exc).__name__
                continue

            if response.status_code >= 400:
                last_error = f"сервер ответил {response.status_code}"
                continue

            servers = parse_many(response.text)
            if not servers:
                last_error = "в ответе нет ни одного понятного сервера"
                continue

            info = SubscriptionInfo(
                title=response.headers.get("profile-title", "").strip(),
                updated_at=int(time.time()),
                server_count=len(servers),
            )
            userinfo = response.headers.get("subscription-userinfo", "")
            if userinfo:
                values = _parse_userinfo(userinfo)
                info.upload = values.get("upload", 0)
                info.download = values.get("download", 0)
                info.total = values.get("total", 0)
                info.expire = values.get("expire", 0)

            save_cache(servers, info)
            logs.info(f"Подписка обновлена: серверов {len(servers)}")
            return servers, info
    finally:
        session.close()

    raise RuntimeError(
        f"Не удалось получить подписку ({last_error}). "
        "Проверьте ссылку и доступ к интернету — иногда панель открывается только под VPN."
    )


def subscription_url() -> str:
    return str(config.get("vpn_subscription_url", ""))


def set_subscription_url(url: str) -> None:
    config.set("vpn_subscription_url", url.strip())
