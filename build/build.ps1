<#
    Полная сборка Zapret Control.

    Запуск из корня проекта:
        powershell -ExecutionPolicy Bypass -File build\build.ps1

    Результат:
        dist\ZapretControl\            — распакованная программа
        dist\ZapretControl-Setup-X.exe — установщик для раздачи
#>

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

# --- версия ---------------------------------------------------------------
$version = & python -c "import re,pathlib;print(re.search(r'APP_VERSION = \x22([^\x22]+)\x22', pathlib.Path('app/core/constants.py').read_text(encoding='utf-8')).group(1))"
if (-not $version) { throw "Не удалось определить версию из app/core/constants.py" }
Write-Host "Zapret Control+ $version" -ForegroundColor Green

# version.txt читает автообновление приложения с GitHub.
# Без BOM: иначе проверка обновлений не признаёт версию за версию.
[System.IO.File]::WriteAllText((Join-Path $root "version.txt"), $version)

# --- ресурсы --------------------------------------------------------------
Step "Иконка и картинки установщика"
& python build\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "make_icon.py завершился с ошибкой" }
& python build\make_installer_art.py
if ($LASTEXITCODE -ne 0) { throw "make_installer_art.py завершился с ошибкой" }

# --- проверки -------------------------------------------------------------
if (-not $SkipTests) {
    Step "Проверка кода"
    & python build\smoke_test.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_test.py не прошёл" }
}

# --- сборка exe -----------------------------------------------------------
Step "Сборка приложения (PyInstaller)"
$distApp = Join-Path $root "dist\ZapretControlPlus"
if (Test-Path $distApp) { Remove-Item -LiteralPath $distApp -Recurse -Force }
& python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyi build\ZapretControlPlus.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

$appMB = [math]::Round((Get-ChildItem $distApp -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "Папка программы: $appMB МБ"

# --- установщик -----------------------------------------------------------
if (-not $SkipInstaller) {
    Step "Сборка установщика (Inno Setup)"
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $iscc) {
        Write-Warning "ISCC.exe не найден. Установите Inno Setup 6: winget install JRSoftware.InnoSetup"
    }
    else {
        & $iscc "/DAppVersion=$version" "build\installer.iss"
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой" }

        $setup = Join-Path $root "dist\ZapretControlPlus-Setup-$version.exe"
        $setupMB = [math]::Round((Get-Item $setup).Length / 1MB, 1)
        Write-Host ""
        Write-Host "Готово: $setup ($setupMB МБ)" -ForegroundColor Green
    }
}

Step "Сборка завершена"


