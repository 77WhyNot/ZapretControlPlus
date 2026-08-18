"""Тонкая обёртка над WinAPI.

Намеренно используем ctypes вместо разбора вывода sc.exe / tasklist:
на локализованной Windows их вывод переведён, а коды и структуры WinAPI —
всегда одинаковые.

Все прототипы объявлены явно: без argtypes/restype ctypes считает результат
32-битным int и обрезает 64-битные HANDLE на x64.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Iterator

CREATE_NO_WINDOW = 0x08000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)


# =========================================================================
# Структуры
# =========================================================================

MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


class SERVICE_DESCRIPTION(ctypes.Structure):
    _fields_ = [("lpDescription", wintypes.LPWSTR)]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG),
    ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.c_void_p),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.ULONG),
    ("Flags", wintypes.ULONG),
    ("Mtu", wintypes.ULONG),
    ("IfType", wintypes.DWORD),
    ("OperStatus", wintypes.DWORD),
]


# =========================================================================
# Прототипы
# =========================================================================

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]
shell32.ShellExecuteW.restype = ctypes.c_void_p

kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
advapi32.OpenSCManagerW.restype = wintypes.HANDLE
advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
advapi32.OpenServiceW.restype = wintypes.HANDLE
advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
advapi32.CloseServiceHandle.restype = wintypes.BOOL
advapi32.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(SERVICE_STATUS)]
advapi32.QueryServiceStatus.restype = wintypes.BOOL
advapi32.CreateServiceW.argtypes = [
    wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPDWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR,
]
advapi32.CreateServiceW.restype = wintypes.HANDLE
advapi32.StartServiceW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.LPCWSTR)
]
advapi32.StartServiceW.restype = wintypes.BOOL
advapi32.ControlService.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(SERVICE_STATUS)
]
advapi32.ControlService.restype = wintypes.BOOL
advapi32.DeleteService.argtypes = [wintypes.HANDLE]
advapi32.DeleteService.restype = wintypes.BOOL
advapi32.ChangeServiceConfig2W.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p
]
advapi32.ChangeServiceConfig2W.restype = wintypes.BOOL

iphlpapi.GetAdaptersAddresses.argtypes = [
    wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
    ctypes.POINTER(IP_ADAPTER_ADDRESSES), ctypes.POINTER(wintypes.ULONG),
]
iphlpapi.GetAdaptersAddresses.restype = wintypes.ULONG


# =========================================================================
# Права администратора
# =========================================================================


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(extra_args: Iterable[str] = ()) -> bool:
    """Перезапустить себя с повышением прав. True — запрос отправлен."""
    args = list(sys.argv[1:]) + list(extra_args)
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = subprocess.list2cmdline(args)
    else:
        exe = sys.executable
        params = subprocess.list2cmdline([os.path.abspath(sys.argv[0])] + args)
    result = shell32.ShellExecuteW(None, "runas", exe, params or None, None, 1)
    return int(result or 0) > 32


# =========================================================================
# Запуск консольных утилит без мелькающих окон
# =========================================================================


def run_hidden(args: list[str] | str, timeout: int = 30,
               cwd: str | None = None) -> tuple[int, str]:
    """Запустить утилиту скрыто и вернуть (код возврата, объединённый вывод)."""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            startupinfo=startupinfo,
            creationflags=CREATE_NO_WINDOW,
            shell=isinstance(args, str),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 1, ""
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, decode_console((proc.stdout or b"") + (proc.stderr or b""))


def decode_console(raw: bytes) -> str:
    for codec in ("oem", "utf-8", "cp1251"):
        try:
            return raw.decode(codec, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("latin-1", errors="replace")


# =========================================================================
# Процессы
# =========================================================================

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def iter_processes() -> Iterator[tuple[int, str]]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return
        while True:
            yield int(entry.th32ProcessID), str(entry.szExeFile)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)


def find_processes(name: str) -> list[int]:
    target = name.lower()
    return [pid for pid, exe in iter_processes() if exe.lower() == target]


def process_running(name: str) -> bool:
    return bool(find_processes(name))


def kill_processes(name: str) -> int:
    killed = 0
    for pid in find_processes(name):
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            continue
        try:
            if kernel32.TerminateProcess(handle, 1):
                killed += 1
        finally:
            kernel32.CloseHandle(handle)
    return killed


def process_path(pid: int) -> str:
    """Полный путь к исполняемому файлу процесса. Пусто, если недоступен."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(MAX_PATH * 2)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_processes_by_path(name: str, executable: str) -> list[int]:
    """Только те процессы с этим именем, что запущены из указанного файла.

    Нужно, чтобы не трогать одноимённые процессы чужих программ: sing-box,
    например, запускают и другие VPN-клиенты.
    """
    target = os.path.normcase(os.path.abspath(executable))
    result: list[int] = []
    for pid in find_processes(name):
        path = process_path(pid)
        if path and os.path.normcase(os.path.abspath(path)) == target:
            result.append(pid)
    return result


def kill_processes_by_path(name: str, executable: str) -> int:
    killed = 0
    for pid in find_processes_by_path(name, executable):
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            continue
        try:
            if kernel32.TerminateProcess(handle, 1):
                killed += 1
        finally:
            kernel32.CloseHandle(handle)
    return killed


def foreign_processes(name: str, executable: str) -> list[int]:
    """Одноимённые процессы, запущенные не нами."""
    ours = set(find_processes_by_path(name, executable))
    return [pid for pid in find_processes(name) if pid not in ours]


ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)
user32.EnumWindows.argtypes = [ENUM_WINDOWS_PROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND

GW_OWNER = 4


def windowed_pids() -> set[int]:
    """Процессы, у которых есть видимое окно верхнего уровня.

    По этому признаку отличаем программы пользователя от фоновых служб:
    в списке маршрутов нужны первые.
    """
    found: set[int] = set()

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True  # дочернее окно, а не главное
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            found.add(int(pid.value))
        return True

    try:
        user32.EnumWindows(ENUM_WINDOWS_PROC(callback), 0)
    except OSError:
        return set()
    return found


# =========================================================================
# Службы
# =========================================================================

SC_MANAGER_CONNECT = 0x0001
SC_MANAGER_CREATE_SERVICE = 0x0002

SERVICE_QUERY_STATUS = 0x0004
SERVICE_START = 0x0010
SERVICE_STOP = 0x0020
DELETE = 0x00010000
SERVICE_ALL_ACCESS = 0xF01FF

SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_AUTO_START = 0x00000002
SERVICE_DEMAND_START = 0x00000003
SERVICE_ERROR_NORMAL = 0x00000001
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONFIG_DESCRIPTION = 1

ERROR_ACCESS_DENIED = 5
ERROR_SERVICE_ALREADY_RUNNING = 1056
ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_SERVICE_EXISTS = 1073
ERROR_SERVICE_MARKED_FOR_DELETE = 1072

STATE_NAMES = {
    1: "stopped",
    2: "start_pending",
    3: "stopping",
    4: "running",
    5: "continue_pending",
    6: "pause_pending",
    7: "paused",
}


class ServiceError(RuntimeError):
    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


def _service_error_text(code: int) -> str:
    table = {
        ERROR_ACCESS_DENIED: "Недостаточно прав. Запустите программу от имени администратора.",
        ERROR_SERVICE_DOES_NOT_EXIST: "Служба не установлена.",
        ERROR_SERVICE_MARKED_FOR_DELETE: "Служба помечена на удаление — требуется перезагрузка.",
        ERROR_SERVICE_EXISTS: "Служба с таким именем уже существует.",
        1053: "Служба не ответила вовремя при запуске.",
    }
    if code in table:
        return table[code]
    try:
        detail = ctypes.FormatError(code).strip()
    except (ValueError, OSError):
        detail = ""
    return f"Ошибка Windows {code}" + (f": {detail}" if detail else "")


class _Scm:
    """Контекстный менеджер для дескриптора диспетчера служб."""

    def __init__(self, access: int) -> None:
        self.access = access
        self.handle = None

    def __enter__(self):
        self.handle = advapi32.OpenSCManagerW(None, None, self.access)
        if not self.handle:
            code = ctypes.get_last_error()
            raise ServiceError(_service_error_text(code), code)
        return self.handle

    def __exit__(self, *exc):
        if self.handle:
            advapi32.CloseServiceHandle(self.handle)
        return False


def service_state(name: str) -> str | None:
    """``None`` — службы нет. Иначе состояние из STATE_NAMES."""
    try:
        with _Scm(SC_MANAGER_CONNECT) as scm:
            handle = advapi32.OpenServiceW(scm, name, SERVICE_QUERY_STATUS)
            if not handle:
                return None
            try:
                status = SERVICE_STATUS()
                if not advapi32.QueryServiceStatus(handle, ctypes.byref(status)):
                    return None
                return STATE_NAMES.get(int(status.dwCurrentState), "unknown")
            finally:
                advapi32.CloseServiceHandle(handle)
    except ServiceError:
        return None


def service_exists(name: str) -> bool:
    return service_state(name) is not None


def service_running(name: str) -> bool:
    return service_state(name) in ("running", "start_pending")


def service_binpath(name: str) -> str | None:
    """ImagePath из реестра — короче, чем QueryServiceConfigW."""
    return reg_read(
        winreg.HKEY_LOCAL_MACHINE,
        rf"System\CurrentControlSet\Services\{name}",
        "ImagePath",
    )


def service_create(name: str, display: str, binpath: str,
                   description: str = "", autostart: bool = True) -> None:
    start_type = SERVICE_AUTO_START if autostart else SERVICE_DEMAND_START
    with _Scm(SC_MANAGER_CONNECT | SC_MANAGER_CREATE_SERVICE) as scm:
        handle = advapi32.CreateServiceW(
            scm, name, display, SERVICE_ALL_ACCESS,
            SERVICE_WIN32_OWN_PROCESS, start_type, SERVICE_ERROR_NORMAL,
            binpath, None, None, None, None, None,
        )
        if not handle:
            code = ctypes.get_last_error()
            raise ServiceError(_service_error_text(code), code)
        try:
            if description:
                desc = SERVICE_DESCRIPTION(ctypes.c_wchar_p(description))
                advapi32.ChangeServiceConfig2W(
                    handle, SERVICE_CONFIG_DESCRIPTION, ctypes.byref(desc)
                )
        finally:
            advapi32.CloseServiceHandle(handle)


def service_start(name: str) -> None:
    with _Scm(SC_MANAGER_CONNECT) as scm:
        handle = advapi32.OpenServiceW(scm, name, SERVICE_START | SERVICE_QUERY_STATUS)
        if not handle:
            code = ctypes.get_last_error()
            raise ServiceError(_service_error_text(code), code)
        try:
            if not advapi32.StartServiceW(handle, 0, None):
                code = ctypes.get_last_error()
                if code != ERROR_SERVICE_ALREADY_RUNNING:
                    raise ServiceError(_service_error_text(code), code)
        finally:
            advapi32.CloseServiceHandle(handle)


def service_stop(name: str, timeout: float = 15.0) -> None:
    with _Scm(SC_MANAGER_CONNECT) as scm:
        handle = advapi32.OpenServiceW(scm, name, SERVICE_STOP | SERVICE_QUERY_STATUS)
        if not handle:
            code = ctypes.get_last_error()
            if code == ERROR_SERVICE_DOES_NOT_EXIST:
                return
            raise ServiceError(_service_error_text(code), code)
        try:
            status = SERVICE_STATUS()
            if not advapi32.ControlService(
                handle, SERVICE_CONTROL_STOP, ctypes.byref(status)
            ):
                code = ctypes.get_last_error()
                if code != ERROR_SERVICE_NOT_ACTIVE:
                    raise ServiceError(_service_error_text(code), code)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not advapi32.QueryServiceStatus(handle, ctypes.byref(status)):
                    break
                if int(status.dwCurrentState) == 1:
                    break
                time.sleep(0.25)
        finally:
            advapi32.CloseServiceHandle(handle)


def service_delete(name: str) -> None:
    with _Scm(SC_MANAGER_CONNECT) as scm:
        handle = advapi32.OpenServiceW(scm, name, DELETE)
        if not handle:
            code = ctypes.get_last_error()
            if code == ERROR_SERVICE_DOES_NOT_EXIST:
                return
            raise ServiceError(_service_error_text(code), code)
        try:
            if not advapi32.DeleteService(handle):
                code = ctypes.get_last_error()
                if code != ERROR_SERVICE_MARKED_FOR_DELETE:
                    raise ServiceError(_service_error_text(code), code)
        finally:
            advapi32.CloseServiceHandle(handle)


def installed_service_names() -> set[str]:
    """Все зарегистрированные службы: чтение реестра быстрее перебора SCM."""
    names: set[str] = set()
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"System\CurrentControlSet\Services"
        ) as key:
            index = 0
            while True:
                try:
                    names.add(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except OSError:
        pass
    return names


# =========================================================================
# Сетевые адаптеры (определение активного VPN)
# =========================================================================

AF_UNSPEC = 0
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
GAA_FLAG_SKIP_DNS_SERVER = 0x0008
IF_TYPE_PPP = 23
IF_TYPE_TUNNEL = 131
IF_OPER_STATUS_UP = 1
ERROR_BUFFER_OVERFLOW = 111


@dataclass(frozen=True)
class NetAdapter:
    name: str
    description: str
    if_type: int
    up: bool


def list_adapters() -> list[NetAdapter]:
    flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER
    size = wintypes.ULONG(15 * 1024)
    for _ in range(4):
        buffer = ctypes.create_string_buffer(size.value)
        pointer = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
        rc = iphlpapi.GetAdaptersAddresses(
            AF_UNSPEC, flags, None, pointer, ctypes.byref(size)
        )
        if rc == ERROR_BUFFER_OVERFLOW:
            continue
        if rc != 0:
            return []
        result: list[NetAdapter] = []
        node = pointer
        while node:
            item = node.contents
            result.append(
                NetAdapter(
                    name=item.FriendlyName or "",
                    description=item.Description or "",
                    if_type=int(item.IfType),
                    up=int(item.OperStatus) == IF_OPER_STATUS_UP,
                )
            )
            node = item.Next
        return result
    return []


VPN_KEYWORDS = (
    "wireguard", "wintun", "openvpn", "tap-windows", "tap-nordvpn", "nordlynx",
    "protonvpn", "amneziawg", "amnezia", "outline", "hiddify", "warp",
    "expressvpn", "surfshark", "mullvad", "tailscale", "zerotier", "hamachi",
    "radmin vpn", "psiphon", "windscribe", "hotspot shield", "vpn", "tunnel",
    "sing-box", "v2ray", "xray", "clash", "adguard vpn", "browsec", "planet vpn",
)


# Системные псевдо-интерфейсы Windows: формально туннели, но не VPN.
PSEUDO_TUNNELS = ("teredo", "isatap", "6to4", "ip-https", "loopback")


def active_vpn_adapters() -> list[NetAdapter]:
    """Поднятые адаптеры, похожие на VPN-туннель."""
    found: list[NetAdapter] = []
    for adapter in list_adapters():
        if not adapter.up:
            continue
        haystack = f"{adapter.name} {adapter.description}".lower()
        if any(word in haystack for word in PSEUDO_TUNNELS):
            continue
        if adapter.if_type in (IF_TYPE_PPP, IF_TYPE_TUNNEL):
            found.append(adapter)
            continue
        if any(word in haystack for word in VPN_KEYWORDS):
            found.append(adapter)
    return found


# =========================================================================
# Реестр и системные настройки
# =========================================================================


def reg_read(root: int, path: str, name: str) -> str | None:
    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


def reg_write(root: int, path: str, name: str, value: str) -> bool:
    try:
        with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        return True
    except OSError:
        return False


def system_proxy() -> str | None:
    """Прокси, настроенный в системе (важно для пользователей VPN/прокси)."""
    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not int(enabled):
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return str(server) or None
    except OSError:
        return None


def doh_configured() -> bool:
    """Настроен ли DNS-over-HTTPS хотя бы на одном интерфейсе."""
    base = r"System\CurrentControlSet\Services\Dnscache\InterfaceSpecificParameters"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return False
    with root:
        index = 0
        while True:
            try:
                iface = winreg.EnumKey(root, index)
            except OSError:
                return False
            index += 1
            for suffix in ("DohInterfaceSettings\\Doh", "DohInterfaceSettings\\Doh6"):
                try:
                    node = winreg.OpenKey(root, f"{iface}\\{suffix}")
                except OSError:
                    continue
                with node:
                    sub = 0
                    while True:
                        try:
                            server = winreg.EnumKey(node, sub)
                        except OSError:
                            break
                        sub += 1
                        try:
                            with winreg.OpenKey(node, server) as leaf:
                                flags, _ = winreg.QueryValueEx(leaf, "DohFlags")
                                if int(flags) > 0:
                                    return True
                        except OSError:
                            continue


def enable_tcp_timestamps() -> bool:
    """zapret использует fooling=ts, которому нужны TCP timestamps."""
    rc, _ = run_hidden(
        ["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"], timeout=20
    )
    return rc == 0


def tcp_timestamps_state() -> bool | None:
    """True/False, либо None если вывод netsh распознать не удалось."""
    rc, out = run_hidden(["netsh", "interface", "tcp", "show", "global"], timeout=20)
    if rc != 0:
        return None
    for line in out.splitlines():
        low = line.lower()
        if "timestamp" in low or "метк" in low:
            if "enabled" in low or "включ" in low:
                return True
            if "disabled" in low or "отключ" in low or "выключ" in low:
                return False
    return None


def hosts_file() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(root, "System32", "drivers", "etc", "hosts")


# =========================================================================
# Автозапуск через планировщик (без запроса UAC при каждом входе)
# =========================================================================


def autostart_enabled(task_name: str) -> bool:
    rc, _ = run_hidden(["schtasks", "/query", "/tn", task_name], timeout=15)
    return rc == 0


def autostart_enable(task_name: str, target: str, args: str = "") -> tuple[bool, str]:
    command = f'"{target}" {args}'.strip()
    rc, out = run_hidden(
        ["schtasks", "/create", "/f", "/tn", task_name, "/tr", command,
         "/sc", "onlogon", "/rl", "highest"],
        timeout=25,
    )
    return rc == 0, out.strip()


def autostart_disable(task_name: str) -> bool:
    rc, _ = run_hidden(["schtasks", "/delete", "/f", "/tn", task_name], timeout=20)
    return rc == 0
