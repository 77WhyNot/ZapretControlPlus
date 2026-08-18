"""Обход блокировки Telegram.

Два экземпляра winws одновременно работать не могут — они дерутся за драйвер
WinDivert. Поэтому Telegram делается не отдельной стратегией, а дополнительными
секциями, которые приписываются к выбранной. Так Discord, YouTube и Telegram
обходятся одним процессом.

Особенность Telegram: клиент общается с серверами по протоколу MTProto, где
имени домена в пакете нет вообще. Опознать такой трафик по хостлисту нельзя,
поэтому секции работают по списку подсетей Telegram с ключом
--dpi-desync-any-protocol=1.
"""

from __future__ import annotations

import os
import re

from app.core import net, paths
from app.core.config import config

# Официальный список подсетей: https://core.telegram.org/resources/cidr.txt
CIDR_URL = "https://core.telegram.org/resources/cidr.txt"
IPSET_FILE = "ipset-telegram.txt"
HOSTLIST_FILE = "list-telegram.txt"

# MTProto ходит по этим портам. 5222 нет в стандартном --wf-tcp, поэтому
# его придётся добавить, иначе пакеты просто не дойдут до фильтра.
MTPROTO_PORTS = ("443", "80", "5222")
EXTRA_WF_TCP = "5222"

MODES = {
    "split": "Разрезание (по умолчанию)",
    "fake": "Фейковые пакеты",
    "disorder": "Перестановка пакетов",
}


def ipset_path() -> str:
    return str(paths.lists_dir() / IPSET_FILE)


def hostlist_path() -> str:
    return str(paths.lists_dir() / HOSTLIST_FILE)


def is_available() -> bool:
    return os.path.isfile(ipset_path()) and os.path.isfile(hostlist_path())


def is_enabled() -> bool:
    return bool(config.get("telegram_bypass", False)) and is_available()


def set_enabled(value: bool) -> None:
    config.set("telegram_bypass", value)


def mode() -> str:
    value = str(config.get("telegram_mode", "split"))
    return value if value in MODES else "split"


def set_mode(value: str) -> None:
    if value in MODES:
        config.set("telegram_mode", value)


def _bin(name: str) -> str:
    return str(paths.bin_dir() / name)


def _sections(chosen_mode: str) -> list[list[str]]:
    """Секции winws для Telegram. Каждая начинается с --new."""
    ipset = ipset_path()
    hostlist = hostlist_path()
    google_tls = _bin("tls_clienthello_www_google_com.bin")
    google_quic = _bin("quic_initial_www_google_com.bin")

    # Веб-версия и t.me — обычный TLS, тут работает разрезание по SNI.
    web = [
        "--new",
        "--filter-tcp=443",
        f"--hostlist={hostlist}",
        "--dpi-desync=multisplit",
        "--dpi-desync-split-seqovl=681",
        "--dpi-desync-split-pos=1",
        f"--dpi-desync-split-seqovl-pattern={google_tls}",
    ]

    # MTProto: домена в пакете нет, опознаём по подсетям Telegram.
    if chosen_mode == "fake":
        mtproto = [
            "--new",
            f"--filter-tcp={','.join(MTPROTO_PORTS)}",
            f"--ipset={ipset}",
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-cutoff=n3",
            f"--dpi-desync-fake-tls={google_tls}",
        ]
    elif chosen_mode == "disorder":
        mtproto = [
            "--new",
            f"--filter-tcp={','.join(MTPROTO_PORTS)}",
            f"--ipset={ipset}",
            "--dpi-desync=multidisorder",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-split-pos=1,midsld",
            "--dpi-desync-cutoff=n3",
        ]
    else:
        mtproto = [
            "--new",
            f"--filter-tcp={','.join(MTPROTO_PORTS)}",
            f"--ipset={ipset}",
            "--dpi-desync=multisplit",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-split-seqovl=568",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-cutoff=n3",
            f"--dpi-desync-split-seqovl-pattern={_bin('tls_clienthello_4pda_to.bin')}",
        ]

    # Звонки и медиа Telegram ходят по UDP.
    udp = [
        "--new",
        "--filter-udp=443",
        f"--ipset={ipset}",
        "--dpi-desync=fake",
        "--dpi-desync-any-protocol=1",
        "--dpi-desync-repeats=6",
        f"--dpi-desync-fake-quic={google_quic}",
    ]
    return [web, mtproto, udp]


def augment(tokens: list[str]) -> list[str]:
    """Дописать секции Telegram к аргументам выбранной стратегии."""
    if not is_enabled():
        return tokens

    result = list(tokens)

    # Без порта 5222 в глобальном фильтре пакеты MTProto до нас не дойдут.
    for index, token in enumerate(result):
        if token.startswith("--wf-tcp="):
            ports = token.split("=", 1)[1]
            if EXTRA_WF_TCP not in re.split(r"[,\s]+", ports):
                result[index] = f"{token},{EXTRA_WF_TCP}"
            break

    for section in _sections(mode()):
        result.extend(section)
    return result


def update_ipset() -> int:
    """Обновить подсети Telegram с официального адреса."""
    text = net.fetch_text(CIDR_URL)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    valid = [line for line in lines if re.match(r"^[0-9a-fA-F:.]+/\d+$", line)]
    if len(valid) < 5:
        raise RuntimeError("Список подсетей Telegram пришёл повреждённым.")
    path = paths.lists_dir() / IPSET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(valid) + "\n", encoding="utf-8")
    return len(valid)


def summary() -> str:
    if not is_available():
        return "списки Telegram не найдены"
    try:
        count = sum(
            1 for line in open(ipset_path(), encoding="utf-8") if line.strip()
        )
    except OSError:
        count = 0
    return f"{count} подсетей, режим «{MODES[mode()]}»"
