# Локальный запуск конвертера без Docker (Windows).
# Использует установленные платформу 1С, EDT и git; ctool1cd.exe/v8unpack.exe
# скачиваются в tools\ с публичных CI-хранилищ e8tools (при отсутствии).
#
# Использование:
#   .\run-local.ps1                                              # sync-all по scripts\local\sync.local.toml
#   .\run-local.ps1 -CommandArgs info                            # любая команда 1c-convert
#   .\run-local.ps1 -CommandArgs @('storage-info','D:\crs\cf')
#   .\run-local.ps1 -DownloadOnly                                # только подготовить инструменты
#
# Примечание: локальный EDT может отличаться от EDT в docker-образе —
# для одного монорепо держите один канал конвертации (docker ИЛИ local),
# иначе EDT-проекты будут «прыгать» между версиями EDT.
[CmdletBinding()]
param(
    [string]$Config,
    [string[]]$CommandArgs,
    [string]$PlatformMask = "8.3.",
    [switch]$DownloadOnly
)
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'sync.local.toml' }
if (-not $CommandArgs) { $CommandArgs = @('sync-all', '--config', $Config) }

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # корень проекта
$tools = Join-Path $repo 'tools'

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }

# --- python ---------------------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Fail "python не найден в PATH (требуется Python 3.10+)" }
Ok "python: $($python.Source)"

# --- git ------------------------------------------------------------------
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Fail "git не найден в PATH" }
Ok "git: $($git.Source)"

# --- платформа 1С ---------------------------------------------------------
$platformRoots = @("$env:ProgramW6432\1cv8", "${env:ProgramFiles(x86)}\1cv8")
$platforms = foreach ($root in $platformRoots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory | Where-Object { $_.Name -match '^8\.\d+\.\d+\.\d+$' } |
            ForEach-Object {
                $bin = Join-Path $_.FullName 'bin'
                if ((Test-Path (Join-Path $bin 'ibcmd.exe')) -and (Test-Path (Join-Path $bin '1cv8.exe'))) {
                    [pscustomobject]@{ Version = $_.Name; Bin = $bin }
                }
            }
    }
}
$platform = $platforms | Where-Object { $_.Version -like "$PlatformMask*" } |
    Sort-Object { [version]$_.Version } | Select-Object -Last 1
if (-not $platform) {
    $platform = $platforms | Sort-Object { [version]$_.Version } | Select-Object -Last 1
}
if (-not $platform) { Fail "платформа 1С не найдена в $($platformRoots -join ', ')" }
Ok "платформа: $($platform.Version) ($($platform.Bin))"

# --- Java для EDT (EDT 2026.2 требует Java 25; берём Axiom Full, НЕ из PATH) --
$javaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Machine')
if (-not $javaHome -or -not (Test-Path (Join-Path $javaHome 'bin\javaw.exe'))) {
    $javaHome = Get-ChildItem "$env:ProgramW6432\1C\1CE\components" -Directory -Filter 'axiom-jdk-full-*' -ErrorAction SilentlyContinue |
        Sort-Object Name | Select-Object -Last 1 | ForEach-Object { $_.FullName }
}
if ($javaHome -and (Test-Path (Join-Path $javaHome 'bin\javaw.exe'))) {
    $env:JAVA_HOME = $javaHome
    $env:PATH = "$(Join-Path $javaHome 'bin');$env:PATH"
    Ok "Java (для EDT): $javaHome"
} else {
    Write-Host "[WARN] Axiom JDK не найден — EDT возьмёт Java из PATH (может не подойти)" -ForegroundColor Yellow
}

# --- EDT / 1cedtcli -------------------------------------------------------
$edtRoot = "$env:ProgramW6432\1C\1CE\components"
$edt = $null
if (Test-Path $edtRoot) {
    $edt = Get-ChildItem $edtRoot -Directory -Filter '1c-edt-*' |
        Where-Object { Test-Path (Join-Path $_.FullName '1cedtcli.exe') } |
        Sort-Object Name | Select-Object -Last 1
}
if (-not $edt) { Fail "1C:EDT не найдена в $edtRoot (ожидается components\1c-edt-*\1cedtcli.exe)" }
Ok "EDT: $($edt.Name)"

# preflight локального 1cedtcli: известная проблема — Windows EDT 2026.2 CLI
# может виснуть на любых командах; проверяем с watchdog и при необходимости
# переключаем EDT-шаг на docker-шим (образ convert2edt/converter).
$edtExe = Join-Path $edt.FullName '1cedtcli.exe'
$probeWs = Join-Path $env:TEMP ('edt-probe-' + [guid]::NewGuid().ToString('N'))
$probe = Start-Process -FilePath $edtExe -ArgumentList '-data', $probeWs, '-timeout', '280', '-command', 'version' `
    -RedirectStandardOutput "$env:TEMP\edt-probe-out.txt" -RedirectStandardError "$env:TEMP\edt-probe-err.txt" -PassThru
$edtOk = $probe.WaitForExit(300000)
if (-not $edtOk) { Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force $probeWs -ErrorAction SilentlyContinue
# ExitCode у Start-Process бывает пуст даже при успехе — считаем успехом ответ с версией
$probeFirst = Get-Content "$env:TEMP\edt-probe-out.txt" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $probeFirst) { $probeFirst = '' }
$edtOk = $edtOk -and ($probeFirst -match '\d')

$useShim = $false
if ($edtOk) {
    Ok "EDT preflight: локальный 1cedtcli отвечает ($probeOut)"
} else {
    Write-Host "[WARN] локальный 1cedtcli не прошёл preflight (code=$($probe.ExitCode)) — известная проблема EDT 2026.2 Windows CLI" -ForegroundColor Yellow
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $shimPy = Join-Path $repo 'scripts\local\edt_docker_shim.py'
        $env:EDTCLI_TOOL = 'python "' + $shimPy + '"'
        $useShim = $true
        Ok "EDT preflight: использую docker-шим (EDTCLI_TOOL -> образ convert2edt/converter)"
    } else {
        Fail "локальный 1cedtcli не отвечает, docker недоступен для шима"
    }
}

# --- ctool1cd ---------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$ctool = Join-Path $tools 'ctool1cd.exe'
if (-not (Test-Path $ctool)) {
    # лучший путь: сборка из upstream (включая depot ver100, PR #295) через MSYS2/mingw
    $msys = 'C:\msys64'
    if (Test-Path "$msys\usr\bin\bash.exe") {
        Write-Host "собираю ctool1cd.exe из upstream (MSYS2/mingw, depot ver100)..."
        & "$msys\usr\bin\bash.exe" -lc "pacman -S --noconfirm --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-boost mingw-w64-x86_64-make >/dev/null 2>&1; rm -rf /out; mkdir -p /out && bash /d/git/convert2edt/scripts/local/build-ctool1cd-mingw.sh" 2>&1 | Select-Object -Last 2
        if (Test-Path "$msys\out\ctool1cd.exe") {
            Copy-Item "$msys\out\*" $tools -Force
        }
    }
}
if (-not (Test-Path $ctool)) {
    # fallback: релиз e8tools (БЕЗ depot ver100 — хранилища расширений локально не синканутся)
    Write-Host "[WARN] собираю fallback: релиз beta2 без depot ver100 (расширения локально недоступны)" -ForegroundColor Yellow
    try {
        $zip = Join-Path $env:TEMP 'tool1cd-rel.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/e8tools/tool1cd/releases/download/v1.0.0-beta2/tool1cd-1.0.0.10.zip' -OutFile $zip
        $tmp = Join-Path $env:TEMP 'tool1cd-rel'
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive $zip -DestinationPath $tmp -Force
        $rel = Get-ChildItem $tmp -Recurse -Filter 'ctool1cd.exe' | Select-Object -First 1
        if (-not $rel) { Fail "ctool1cd.exe не найден в архиве tool1cd" }
        foreach ($name in @('ctool1cd.exe', 'libtool1cd.dll', 'libgcc_s_dw2-1.dll', 'libstdc++-6.dll', 'libwinpthread-1.dll')) {
            $f = Get-ChildItem $tmp -Recurse -Filter $name | Select-Object -First 1
            if ($f) { Copy-Item $f.FullName $tools -Force }
        }
    } catch { Fail "не удалось скачать tool1cd: $($_.Exception.Message)" }
}
Ok "ctool1cd: $ctool"

if ($DownloadOnly) { Write-Host "`nИнструменты готовы." -ForegroundColor Cyan; exit 0 }

# --- запуск -----------------------------------------------------------------
if ($useShim) {
    $env:PATH = "$tools;$($platform.Bin);$($env:PATH)"
} else {
    $env:PATH = "$($platform.Bin);$($edt.FullName);$tools;$($env:PATH)"
}
$env:PYTHONPATH = Join-Path $repo 'converter'

$isSyncAll = $CommandArgs.Count -ge 1 -and $CommandArgs[0] -eq 'sync-all'
if ($isSyncAll -and -not (Test-Path $Config)) {
    Copy-Item (Join-Path $PSScriptRoot 'sync.local.toml.example') $Config
    Write-Host "[WARN] создан $Config — проверьте пути и перезапустите." -ForegroundColor Yellow
    exit 1
}

Write-Host "`n>>> python -m onec_convert $($CommandArgs -join ' ')`n" -ForegroundColor Cyan
& $python.Source -m onec_convert @CommandArgs
exit $LASTEXITCODE
