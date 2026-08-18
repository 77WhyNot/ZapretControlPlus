# Сторонние компоненты

Zapret Control+ распространяется по [собственной лицензии](LICENSE), но включает
компоненты других авторов. **Действие лицензии Zapret Control+ на них не
распространяется** — каждый остаётся под своими условиями.

| Компонент | Что делает | Условия |
|---|---|---|
| [sing-box](https://github.com/SagerNet/sing-box) `1.13.19` | Движок VPN: туннель, протоколы, маршрутизация по программам | **GPL-3.0** |
| [zapret](https://github.com/bol-van/zapret) (`winws.exe`) | Обход DPI | По условиям проекта bol-van/zapret |
| [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) | Стратегии, списки доменов и IP | По условиям проекта Flowseal |
| [WinDivert](https://github.com/basil00/Divert) | Перехват сетевых пакетов | LGPL v3 / GPL v2 |
| [Qt](https://www.qt.io/) и [PySide6](https://doc.qt.io/qtforpython/) | Графический интерфейс | LGPL v3 |
| [requests](https://github.com/psf/requests) | Сетевые запросы | Apache License 2.0 |
| [Python](https://www.python.org/) | Среда выполнения | PSF License |

## Про sing-box и GPL-3.0

`sing-box.exe` поставляется **неизменённым** — ровно тот файл, что лежит в
[официальном релизе v1.13.19](https://github.com/SagerNet/sing-box/releases/tag/v1.13.19).
Программа запускает его отдельным процессом и общается с ним по сети через
локальный порт; код sing-box в приложение не встраивается и не компонуется с ним.

Исходный код sing-box доступен в его репозитории по ссылке выше. Условия GPL-3.0
распространяются на sing-box и остаются в силе независимо от лицензии
Zapret Control+.

## Подсети Telegram

Список подсетей берётся с официального адреса
[core.telegram.org/resources/cidr.txt](https://core.telegram.org/resources/cidr.txt)
и обновляется кнопкой в программе.

## Что это значит на практике

**Для пользователя.** Ничего. Программа работает как есть, скачивать
дополнительно ничего не нужно.

**Для того, кто хочет что-то взять из проекта.** Код, интерфейс и оформление
Zapret Control+ — авторские, нужно письменное разрешение. Компоненты из таблицы
берите напрямую у их авторов, по их лицензиям.

## Оговорка

Автор не является юристом. Таблица составлена по лицензиям, заявленным самими
проектами. Нашли неточность — сообщите в
[issues](https://github.com/77WhyNot/ZapretControlPlus/issues).
