# -*- mode: python ; coding: utf-8 -*-
"""Сборка Zapret Control.

Собираем onedir: ядро zapret должно лежать рядом с exe и обновляться,
а onefile распаковывал бы всё во временную папку при каждом запуске.
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent

# ZC_TESTBUILD=1 собирает консольную копию без требования прав администратора —
# так можно прогнать --selftest, не показывая пользователю окно UAC.
TEST_BUILD = os.environ.get("ZC_TESTBUILD") == "1"

# Модули Qt, которые нам не нужны: без них папка меньше примерно втрое.
EXCLUDES = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtStateMachine", "PySide6.QtTest", "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets", "PySide6.QtXml",
    "PySide6.QtUiTools", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "PySide6.QtHttpServer", "PySide6.QtGraphs", "PySide6.QtLocation",
    "PySide6.QtNetworkAuth", "PySide6.QtSerialBus",
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "PIL", "numpy", "matplotlib", "pandas", "scipy",
]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "app" / "resources" / "icon.ico"), "resources"),
        (str(ROOT / "app" / "resources" / "icon.png"), "resources"),
    ],
    hiddenimports=["app", "app.ui.window"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)


# PySide6 тянет за собой QML-движок, программный OpenGL и переводы Qt на все
# языки мира. Виджетному приложению это не нужно — экономим больше 35 МБ.
DROP_FILES = {
    "opengl32sw.dll",
    "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll", "qt6qmlmeta.dll",
    "qt6qmlworkerscript.dll", "qt6quickparticles.dll", "qt6quickshapes.dll",
    "qt6quicktemplates2.dll", "qt6quickcontrols2.dll",
    "qt6pdf.dll", "qt6pdfquick.dll", "qt6virtualkeyboard.dll",
}
DROP_DIRS = ("qmltooling", "qml/", "qml\\")


def _keep(entry) -> bool:
    dest = str(entry[0]).replace("\\", "/")
    lowered = dest.lower()
    name = lowered.rsplit("/", 1)[-1]

    if name in DROP_FILES:
        return False
    if any(marker.replace("\\", "/") in lowered for marker in DROP_DIRS):
        return False
    # Из переводов Qt оставляем только русский — интерфейс всё равно русский.
    if "/translations/" in lowered and not name.endswith("_ru.qm"):
        return False
    return True


a.binaries = TOC([entry for entry in a.binaries if _keep(entry)])
a.datas = TOC([entry for entry in a.datas if _keep(entry)])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZapretControlPlusTest" if TEST_BUILD else "ZapretControlPlus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=TEST_BUILD,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "app" / "resources" / "icon.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    # WinDivert грузит драйвер режима ядра — без администратора никак.
    uac_admin=not TEST_BUILD,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZapretControlPlusTest" if TEST_BUILD else "ZapretControlPlus",
)
