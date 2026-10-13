"""Короткие имена для марок и табло: «ALT», «NL», «Comss»."""

from __future__ import annotations

import re

_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def strategy_den(title: str) -> str:
    """Номинал марки обхода: короткое имя стратегии."""
    title = (title or "").strip()
    if not title:
        return "—"
    if len(title) <= 9:
        return title
    words = title.split()
    # FAKE TLS AUTO ALT2 → FTA ALT2: последнее слово целиком, прочие — буквой.
    if len(words) > 1:
        return "".join(word[0] for word in words[:-1]).upper() + " " + words[-1]
    return title[:8] + "…"


def server_code(name: str) -> str:
    """Код страны сервера: из флага-эмодзи или первых букв названия."""
    name = name or ""
    match = _FLAG.search(name)
    if match:
        return "".join(chr(ord(ch) - 0x1F1E6 + ord("A")) for ch in match.group(0))
    match = re.search(r"\b([A-Z]{2})\b", name)
    if match:
        return match.group(1)
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", name)
    return letters[:2].upper() if letters else "VPN"


def server_place(name: str) -> str:
    """Название сервера без флага и лишних пробелов."""
    cleaned = _FLAG.sub("", name or "")
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", cleaned)
    return " ".join(cleaned.split()) or (name or "Сервер")


def join_ru(items: list[str]) -> str:
    """«обход, VPN и Telegram»."""
    items = [item for item in items if item]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " и " + items[-1]


def capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


MONTHS_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
MONTHS_GENITIVE = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                   "августа", "сентября", "октября", "ноября", "декабря")


def postmark_date(stamp=None) -> str:
    """Дата на штемпеле: 13·X·26."""
    import time

    t = time.localtime(stamp)
    return f"{t.tm_mday}·{MONTHS_ROMAN[t.tm_mon - 1]}·{t.tm_year % 100:02d}"


def long_date(stamp=None) -> str:
    """13 ОКТЯБРЯ."""
    import time

    t = time.localtime(stamp)
    return f"{t.tm_mday} {MONTHS_GENITIVE[t.tm_mon - 1]}".upper()
