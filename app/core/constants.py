"""Константы продукта. Единственное место, где меняются имена и репозитории."""

# --- Продукт -------------------------------------------------------------
APP_NAME = "Zapret Control+"
APP_ID = "ZapretControlPlus"
APP_VERSION = "2.3.2"
APP_AUTHOR = "ketamine"
APP_AUTHOR_FULL = "Ivan Milyaev (ketamine)"
APP_PUBLISHER = "Ivan Milyaev (ketamine)"

# Репозиторий самого приложения на GitHub в формате "логин/название".
# Пока строка пустая, автообновление программы просто выключено — всё
# остальное работает как обычно. Впишите свой логин перед публикацией,
# например: APP_REPO = "ivanov/zapret-control"  (подробности в README).
APP_REPO = "77WhyNot/ZapretControlPlus"
APP_REPO_NAME = "ZapretControlPlus"
APP_REPO_URL = f"https://github.com/{APP_REPO}"

# --- Апстрим (ядро zapret) ----------------------------------------------
UPSTREAM_REPO = "Flowseal/zapret-discord-youtube"
UPSTREAM_BRANCH = "main"
UPSTREAM_HOME = f"https://github.com/{UPSTREAM_REPO}"
UPSTREAM_VERSION_PATH = ".service/version.txt"
UPSTREAM_IPSET_PATH = ".service/ipset-service.txt"
UPSTREAM_HOSTS_PATH = ".service/hosts"

# Имя ассета релиза строится по шаблону — это стабильное соглашение апстрима.
UPSTREAM_ASSET_TEMPLATE = "zapret-discord-youtube-{version}.zip"

# --- Служба Windows ------------------------------------------------------
SERVICE_NAME = "zapret"
SERVICE_DISPLAY = "zapret"
SERVICE_DESCRIPTION = "Zapret DPI bypass software"
SERVICE_REG_PATH = r"System\CurrentControlSet\Services\zapret"
SERVICE_REG_VALUE = "zapret-discord-youtube"

WINDIVERT_SERVICES = ("WinDivert", "WinDivert14")
WINWS_EXE = "winws.exe"

# Задача планировщика для автозапуска приложения с правами администратора.
AUTOSTART_TASK = "ZapretControlPlus Autostart"

# Где взять подписку, если своей нет. Сервис сторонний — программа
# с ним никак не связана и ничего о нём не знает.
SUBSCRIPTION_SHOP_URL = "https://t.me/ultimavpnbot/app?startapp=NhYiCVMT"
SUBSCRIPTION_SHOP_NAME = "UltimaVPN"

# --- VPN -----------------------------------------------------------------
SINGBOX_REPO = "SagerNet/sing-box"
SINGBOX_VERSION = "1.13.19"
SINGBOX_PROCESS = "sing-box.exe"

# --- Прочее --------------------------------------------------------------
CONFIG_VERSION = 1
HTTP_TIMEOUT = 12
USER_AGENT = f"{APP_ID}/{APP_VERSION} (+https://github.com/{APP_REPO})"
