<div align="center">

<img src="docs/banner.png" alt="Zapret Control+">

[![Релиз](https://img.shields.io/github/v/release/77WhyNot/ZapretControlPlus?style=for-the-badge&label=версия&color=D42250)](https://github.com/77WhyNot/ZapretControlPlus/releases/latest)
[![Загрузки](https://img.shields.io/github/downloads/77WhyNot/ZapretControlPlus/total?style=for-the-badge&label=загрузок&color=D42250)](https://github.com/77WhyNot/ZapretControlPlus/releases)
[![Windows](https://img.shields.io/badge/Windows-10%20и%2011-0078D4?style=for-the-badge)](https://github.com/77WhyNot/ZapretControlPlus/releases/latest)
[![Лицензия](https://img.shields.io/badge/лицензия-проприетарная-555?style=for-the-badge)](LICENSE)

### Обход блокировок Discord, YouTube и Telegram плюс Smart DNS для Xbox — в одном окне

**[⬇ Скачать последнюю версию](https://github.com/77WhyNot/ZapretControlPlus/releases/latest)**

</div>

<div align="center">
<img src="docs/screenshots/home.png" width="860" alt="Главный экран">
</div>

---

## Важно: с версии 3.0 встроенного VPN нет

В версиях 2.x внутри был свой VPN на sing-box. На практике он мешал чужим клиентам:
занимал тот же сетевой адаптер, а при сбое мог оставить адаптер Happ или другого
клиента выключенным. Поэтому VPN из программы убран целиком.

Теперь Zapret Control+ — это **тот же Zapret Control**: обход DPI через zapret, обход
Telegram, Smart DNS для гео-ограничений, диагностика и автообновление. Отличия только
в названии, иконке и тёмной теме по умолчанию. Если сомневаетесь, какую ставить —
берите обычный [Zapret Control](https://github.com/77WhyNot/ZapretControl).

Со своим VPN-клиентом (Happ, Hiddify, WireGuard и другими) программа теперь просто
соседствует: видит живой туннель, показывает его на схеме и по желанию снимает обход
на время работы VPN. Чужой адаптер и процесс не трогает никогда.

**Если после версий 2.x у вас не поднимается VPN-клиент** — откройте вкладку
«Диагностика» и нажмите **«Починить сетевые адаптеры»**: программа включит обратно
всё, что выключали старые версии.

## Что умеет

| | |
|---|---|
| **Обход в один клик** | Переключатель на главном экране. Внизу схема: что идёт напрямую, что через zapret, что через Smart DNS, а что — через ваш VPN. |
| **21 стратегия и автоподбор** | Стратегии читаются прямо из файлов ядра. Автоподбор перебирает варианты и оставляет тот, что реально помог. |
| **Telegram** | Обход MTProto по официальному списку подсетей Telegram, три режима на выбор. |
| **Smart DNS для Xbox** | Xbox Live, Game Pass, ошибка 0x80a40401, ChatGPT, Twitch. Адреса [xbox-dns.ru](https://xbox-dns.ru/), а также Comss, Cloudflare, AdGuard и Google. Исходные настройки сохраняются. |
| **Игровой фильтр и IPSet** | Те же два пункта, что в консольном меню zapret, прямо на главном экране. |
| **Обновления сами** | Ядро zapret ставится автоматически, обход на пару секунд перезапускается. Новая версия программы — плашкой на главном экране с кнопкой. |
| **Диагностика** | 16 проверок с кнопками «Исправить», перезапуск Discord с очисткой кэша, ремонт сетевых адаптеров. |
| **Проверка доступности** | Discord, YouTube, Google, ChatGPT, Claude, Gemini — за один клик. |
| **Оформление** | 5 тем и 8 акцентов, светлая ↔ тёмная одной кнопкой в заголовке окна. |

## Установка

1. Скачайте `ZapretControlPlus-Setup-x.y.z.exe` со страницы [Releases](https://github.com/77WhyNot/ZapretControlPlus/releases/latest).
2. Запустите и нажмите «Установить». Поверх версии 2.x установщик предложит обновить — настройки останутся, а папка старого VPN-движка будет убрана.
3. Ядро zapret уже внутри, доскачивать ничего не нужно.

Программа просит права администратора: WinDivert грузит драйвер режима ядра, а служба
zapret создаётся в системе.

## Сборка из исходников

Нужны Windows 10/11 x64, Python 3.10+ и [Inno Setup 6](https://jrsoftware.org/isdl.php).

```bash
pip install -r requirements.txt
```

```bash
powershell -ExecutionPolicy Bypass -File build\build.ps1
```

## Автор

**ketamine** (Ivan Milyaev) — [github.com/77WhyNot](https://github.com/77WhyNot)

## Благодарности

- [bol-van/zapret](https://github.com/bol-van/zapret) — технология обхода и `winws`.
- [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) — стратегии и списки.
- [basil00/Divert](https://github.com/basil00/Divert) — драйвер WinDivert.
- [xbox-dns.ru](https://xbox-dns.ru/) — Smart DNS для гео-ограничений.

## Лицензия

Программа распространяется по [собственной лицензии](LICENSE): пользоваться и
делиться с друзьями можно свободно, а публиковать форки, изменённые версии и
брать код в свои проекты — **только с письменного разрешения автора**.

Сторонние компоненты остаются под своими лицензиями, см. [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
