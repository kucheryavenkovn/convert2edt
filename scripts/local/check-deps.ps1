# Проверка зависимостей локального режима convert2edt (без Docker).
# Печатает по каждой зависимости статус и что поставить, если её нет.
#
#   .\check-deps.ps1            # полная проверка (оба движка)
#   .\check-deps.ps1 -Engine tool1cd   # только нативный движок
#   .\check-deps.ps1 -Engine gitsync   # только движок gitsync
#
# Код выхода: 0 — обязательные зависимости на месте, 1 — чего-то не хватает.
param(
    [ValidateSet('all', 'tool1cd', 'gitsync')]
    [string]$Engine = 'all'
)
$ErrorActionPreference = 'Continue'
chcp 65001 | Out-Null
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$tools = Join-Path $repo 'tools'
$missing = 0

function Ok($msg)      { Write-Host "[OK]      $msg" -ForegroundColor Green }
function Miss($msg, $hint) {
    Write-Host "[НЕТ]     $msg" -ForegroundColor Red
    Write-Host "          -> поставить: $hint" -ForegroundColor Yellow
    $script:missing++
}
function Opt($msg, $hint) {
    Write-Host "[ОПЦИЯ]  $msg" -ForegroundColor DarkYellow
    Write-Host "          -> $hint" -ForegroundColor DarkGray
}

# ============================ общие ============================
Write-Host "`n=== Общие ===" -ForegroundColor Cyan

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pv = & $python.Source -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    if ([version]$pv -ge [version]'3.11') { Ok "python $pv ($($python.Source))" }
    else { Miss "python $pv — нужен 3.11+ (tomllib)" , 'https://www.python.org/downloads/' }
} else { Miss 'python не найден в PATH' 'https://www.python.org/downloads/ (3.11+)' }

$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) { Ok "git: $($git.Source)" } else { Miss 'git не найден в PATH' 'https://git-scm.com/download/win' }

# ===================== платформа 1С и EDT ======================
Write-Host "`n=== Платформа 1С и EDT (оба движка) ===" -ForegroundColor Cyan

$platformRoots = @("$env:ProgramW6432\1cv8", "${env:ProgramFiles(x86)}\1cv8")
$platforms = foreach ($root in $platformRoots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^8\.\d+\.\d+\.\d+$' } |
            Where-Object { Test-Path (Join-Path $_.FullName 'bin\1cv8.exe') } |
            ForEach-Object { $_.Name }
    }
}
if ($platforms) { Ok "платформа 1С: $($platforms -join ', ')" }
else { Miss 'платформа 1С не найдена' 'releases.1c.ru -> Технологическая платформа 8.3 (Windows)' }

$edtRoot = "$env:ProgramW6432\1C\1CE\components"
$edt = Get-ChildItem $edtRoot -Directory -Filter '1c-edt-*' -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName '1cedtcli.exe') } |
    Sort-Object Name | Select-Object -Last 1
if ($edt) { Ok "1C:EDT: $($edt.Name) (1cedtcli)" }
else { Miss '1C:EDT не найдена (components\1c-edt-*\1cedtcli.exe)' 'releases.1c.ru -> 1C:EDT (offline-установщик, ставить через 1ce-installer/1cedtstart)' }

$javaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Machine')
$axiom = Get-ChildItem $edtRoot -Directory -Filter 'axiom-jdk-full-*' -ErrorAction SilentlyContinue |
    Sort-Object Name | Select-Object -Last 1
if ($axiom) { Ok "Java для EDT: $($axiom.Name)" }
elseif ($javaHome) { Ok "Java для EDT: machine JAVA_HOME = $javaHome (проверьте версию: EDT 2026.x требует 21/25)" }
else { Miss 'JDK для EDT не найден' 'Axiom JDK Full ставится вместе с EDT (components\axiom-jdk-full-*) или $env:CONVERT_JAVA_HOME' }

# ===================== движок tool1cd ==========================
if ($Engine -in 'all', 'tool1cd') {
    Write-Host "`n=== Движок tool1cd (по умолчанию) ===" -ForegroundColor Cyan

    $ibcmd = Get-ChildItem $platformRoots -Recurse -Filter 'ibcmd.exe' -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ibcmd) { Ok "ibcmd: $($ibcmd.FullName)" }
    else { Miss 'ibcmd.exe не найден' 'платформа 1С: в установке выбрать компоненту ibcmd (утилита автономного сервера)' }

    $ctool = Join-Path $tools 'ctool1cd.exe'
    if (Test-Path $ctool) { Ok "ctool1cd: $ctool" }
    else {
        Miss 'ctool1cd.exe нет в tools\' 'запустить run-local.ps1 — соберётся из upstream e8tools/tool1cd (нужен MSYS2/mingw, см. ниже)'
    }

    $msys = 'C:\msys64\usr\bin\bash.exe'
    if (Test-Path $msys) { Ok "MSYS2: $msys (сборка ctool1cd из upstream)" }
    else { Opt 'MSYS2 не найден — ctool1cd будет взят из релиза beta2 БЕЗ depot ver100 (хранилища расширений не читаются)' 'https://www.msys2.org/ + pacman -S mingw-w64-x86_64-gcc/cmake/boost/make' }

    if (Get-Command docker -ErrorAction SilentlyContinue) { Ok 'docker: доступен (fallback-шим для EDT)' }
    else { Opt 'docker не найден' 'нужен только как fallback, если локальный 1cedtcli не отвечает' }
}

# ===================== движок gitsync ==========================
if ($Engine -in 'all', 'gitsync') {
    Write-Host "`n=== Движок gitsync (опциональный) ===" -ForegroundColor Cyan

    # библиотеки gitsync/edtfind подключаются через OSCRIPT_CONFIG
    # (см. run-gitsync.ps1); без этого любой вызов gitsync падает
    $oslib = Join-Path $tools 'oscript\oscript_modules'
    if (Test-Path $oslib) { $env:OSCRIPT_CONFIG = "lib.additional=$oslib" }

    $oscript = Get-Command oscript -ErrorAction SilentlyContinue
    if ($oscript) {
        $ov = & $oscript.Source -version 2>$null
        Ok "oscript $ov ($($oscript.Source))"
    } else { Miss 'oscript не найден в PATH' 'https://oscript.io/downloads (OneScript) или ovm' }

    $opm = Get-Command opm -ErrorAction SilentlyContinue
    if ($opm) { Ok "opm: $($opm.Source)" } else { Miss 'opm не найден в PATH' 'идёт с OneScript; проверьте установку' }

    $gitsync = Get-Command gitsync -ErrorAction SilentlyContinue
    if ($gitsync) {
        $gv = & $gitsync.Source --version 2>$null
        Ok "gitsync $gv ($($gitsync.Source))"
    } else { Miss 'gitsync не найден в PATH' 'opm install gitsync' }

    if ($gitsync) {
        $plugins = & $gitsync.Source plugins list 2>&1 | Out-String
        if ($plugins -match '\[on\].*edtExport') { Ok 'плагин gitsync edtExport активен' }
        else {
            Miss 'плагин edtExport не активен' 'gitsync plugins install gitsync-plugins@2.0.3; gitsync plugins enable edtExport (нужна версия >= 2.0.1 — поддержка 1cedtcli без ring)'
        }
    }

    $oslib = Join-Path $tools 'oscript\oscript_modules'
    if (Test-Path (Join-Path $oslib 'edtfind')) { Ok "edtfind: $oslib\edtfind (локально, без прав админа)" }    else { Miss 'edtfind не установлен локально' 'cd tools\oscript; opm install -l edtfind  (или просто запустить run-gitsync.ps1 — поставит сам)' }

    if ($platforms) { Ok 'конфигуратор 1С есть — gitsync читает хранилище через DESIGNER (лицензия не нужна)' }
    Ok 'ring НЕ требуется: edtExport 2.x работает через 1cedtcli'
}

Write-Host ''
if ($missing -gt 0) {
    Write-Host "ИТОГ: не хватает $missing обязательных зависимостей — см. подсказки выше." -ForegroundColor Red
    exit 1
}
Write-Host 'ИТОГ: все обязательные зависимости на месте.' -ForegroundColor Green
exit 0
