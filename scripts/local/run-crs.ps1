# Сервер хранилища конфигураций 1С (crserver) локально на Windows.
# Запускает crserver.exe из установленной платформы; каталог репозиториев
# хранится на диске (по умолчанию <repo>\storage-crs).
#
# Использование:
#   .\run-crs.ps1                       # каталог storage-crs, порт 1542
#   .\run-crs.ps1 -Port 1543 -DataDir D:\crs-data
#   .\run-crs.ps1 -PlatformMask 8.3.27.
# Затем строка подключения: tcp://127.0.0.1:<порт>/<имя_репозитория>
# (из Docker-контейнера: tcp://host.docker.internal:<порт>/<имя>).
# Остановка: Ctrl+C.
param(
    [int]$Port = 1542,
    [string]$DataDir = "",
    [string]$PlatformMask = ""
)
if (-not $PlatformMask) {
    $PlatformMask = if ($env:CONVERT_PLATFORM_MASK) { $env:CONVERT_PLATFORM_MASK } else { "8.3." }
}
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $DataDir) { $DataDir = Join-Path $repo 'storage-crs' }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

$roots = @("$env:ProgramW6432\1cv8", "${env:ProgramFiles(x86)}\1cv8")
$platforms = foreach ($root in $roots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory |
            Where-Object { $_.Name -match '^8\.\d+\.\d+\.\d+$' } |
            Where-Object { Test-Path (Join-Path $_.FullName 'bin\crserver.exe') } |
            ForEach-Object { [pscustomobject]@{ Version = $_.Name; Exe = Join-Path $_.FullName 'bin\crserver.exe' } }
    }
}
$platform = $platforms | Where-Object { $_.Version -like "$PlatformMask*" } |
    Sort-Object { [version]$_.Version } | Select-Object -Last 1
if (-not $platform) { $platform = $platforms | Sort-Object { [version]$_.Version } | Select-Object -Last 1 }
if (-not $platform) { Fail "crserver.exe не найден (нужен серверный компонент платформы 1С)" }

Write-Host "[OK]   сервер хранилища: $($platform.Version)"
Write-Host "[OK]   каталог репозиториев: $DataDir"
Write-Host "[OK]   tcp://0.0.0.0:$Port/<имя_репозитория>  (Ctrl+C — стоп)"
& $platform.Exe -d $DataDir -port $Port
exit $LASTEXITCODE
