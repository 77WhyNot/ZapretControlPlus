# Сторонние компоненты

Zapret Control+ распространяется по [собственной лицензии](LICENSE), но включает
в себя компоненты других авторов. **Действие лицензии Zapret Control+ на них не
распространяется** — каждый из них остаётся под своими условиями, и запретить их
использование нельзя.

| Компонент | Что делает | Условия |
|---|---|---|
| [zapret](https://github.com/bol-van/zapret) (`winws.exe`) | Сам обход DPI | По условиям проекта bol-van/zapret |
| [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) | Стратегии, списки доменов и IP | По условиям проекта Flowseal |
| [WinDivert](https://github.com/basil00/Divert) (`WinDivert.dll`, `WinDivert64.sys`) | Перехват сетевых пакетов | LGPL v3 / GPL v2 |
| [Qt](https://www.qt.io/) и [PySide6](https://doc.qt.io/qtforpython/) | Графический интерфейс | LGPL v3 |
| [sing-box](https://github.com/SagerNet/sing-box) `1.13.19` | Движок VPN: туннель, протоколы, маршрутизация по программам | **GPL-3.0** |
| [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) `1.10.1` | Прокси Telegram через WebSocket; ядро включено в программу целиком (`app/vendor/tgwsproxy`) | **MIT** |
| [cryptography](https://github.com/pyca/cryptography) | Шифрование AES для прокси Telegram | Apache License 2.0 / BSD |
| [certifi](https://github.com/certifi/python-certifi) | Корневые сертификаты для проверки TLS | MPL 2.0 |
| [requests](https://github.com/psf/requests) | Сетевые запросы | Apache License 2.0 |
| [Python](https://www.python.org/) | Среда выполнения | PSF License |
| [xbox-dns.ru](https://xbox-dns.ru/) | Адреса Smart DNS для обхода гео-ограничений | Публичный сервис, программа лишь подставляет его адреса |
| [core.telegram.org/resources/cidr.txt](https://core.telegram.org/resources/cidr.txt) | Официальный список подсетей Telegram для обхода MTProto | Публичные данные Telegram |

## Про sing-box и GPL-3.0

`sing-box.exe` поставляется **неизменённым** — ровно тот файл, что лежит в
[официальном релизе v1.13.19](https://github.com/SagerNet/sing-box/releases/tag/v1.13.19).
Программа запускает его отдельным процессом и общается с ним по сети через
локальный порт; код sing-box в приложение не встраивается и не компонуется с ним.
Условия GPL-3.0 распространяются на sing-box и остаются в силе независимо от
лицензии Zapret Control+.

## Что это значит на практике

**Для пользователя.** Ничего. Программа работает как есть, скачивать
дополнительно ничего не нужно.

**Для того, кто хочет что-то взять из проекта.** Код, интерфейс и оформление
Zapret Control+ — авторские, и на них нужно письменное разрешение. Компоненты из
таблицы выше берите напрямую у их авторов, по их лицензиям.

## Исходный код компонентов

Библиотеки Qt поставляются отдельными DLL в папке `_internal`, что позволяет
заменить их своей сборкой — этого требует LGPL. Исходный код Qt доступен на
[download.qt.io](https://download.qt.io/), исходники WinDivert и zapret — в их
репозиториях по ссылкам выше.

## Оговорка

Автор не является юристом. Таблица составлена по лицензиям, заявленным самими
проектами. Если вы обнаружили неточность — сообщите через
[issues](https://github.com/77WhyNot/ZapretControlPlus/issues), поправим.
