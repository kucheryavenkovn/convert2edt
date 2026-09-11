# Локальная выгрузка хранилища 1С через gitsync (OneScript) — без Docker.
# Альтернатива нативному конвейеру run-local.ps1 (ctool1cd + ibcmd + 1cedtcli):
#   * версии хранилища читает КОНФИГУРАТОР 1С (1cv8 DESIGNER), не ctool1cd;
#   * XML -> EDT делает плагин gitsync `edtExport` (v2.x, через 1cedtcli,
#     ring НЕ требуется);
#   * git-историю (коммиты, авторы из AUTHORS, даты) формирует сам gitsync.
#
# Требования (автопроверяются/доставляются скриптом):
#   oscript + gitsync (opm install gitsync);
#   плагины: gitsync-plugins >= 2.0.1 (edtfind + 1cedtcli), включён edtExport;
#   edtfind — ставится локально в tools\oscript\oscript_modules (opm install -l),
#   подхватывается через OSCRIPT_CONFIG lib.additional (без прав администратора).
#
# Использование:
#   .\run-gitsync.ps1                                   # fixtures\crs\cf -> output\local-gitsync
#   .\run-gitsync.ps1 -Storage D:\crs\cf -Worktree D:\out\repo -ProjectName configuration
#   .\run-gitsync.ps1 -Limit 2 -VerboseLog              # пробный прогон на 2 версиях
#   .\run-gitsync.ps1 -PrepareOnly                      # только подготовить инструменты
# ================== НАСТРОЙКИ (переопределяются переменными среды) ==================
# CONVERT_PLATFORM_MASK — маска версии платформы 1С (по умолчанию "8.3.")
# CONVERT_EDT_VERSION   — точная версия EDT (по умолчанию: новейший 1c-edt-*)
# CONVERT_JAVA_HOME     — JDK/JRE для EDT (по умолчанию: machine JAVA_HOME / axiom-jdk-full)
# ====================================================================================
param(
    [string]$Storage = "",
    [string]$Worktree = "",
    [string]$ProjectName = "configuration",
    [string]$StorageUser = "Администратор",
    [string]$StoragePwd = "",
    [string]$Domain = "storage.local",
    [int]$Limit = 0,
    [int]$MinVersion = 0,
    [int]$MaxVersion = 0,
    [string]$PlatformMask = "",
    [switch]$VerboseLog,
    [switch]$PrepareOnly
)
if (-not $PlatformMask) {
    $PlatformMask = if ($env:CONVERT_PLATFORM_MASK) { $env:CONVERT_PLATFORM_MASK } else { "8.3." }
}
$ErrorActionPreference = 'Stop'
chcp 65001 | Out-Null
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # корень проекта
$tools = Join-Path $repo 'tools'
if (-not $Storage) { $Storage = Join-Path $repo 'fixtures\crs\cf' }
if (-not $Worktree) { $Worktree = Join-Path $repo 'output\local-gitsync' }

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }

# --- git ------------------------------------------------------------------
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Fail "git не найден в PATH" }
Ok "git: $($git.Source)"

# --- oscript / gitsync ------------------------------------------------------
$gitsync = Get-Command gitsync -ErrorAction SilentlyContinue
if (-not $gitsync) { Fail "gitsync не найден в PATH (opm install gitsync)" }
Ok "gitsync: $($gitsync.Source)"

# --- платформа 1С (конфигуратор для чтения хранилища) -----------------------
$platformRoots = @("$env:ProgramW6432\1cv8", "${env:ProgramFiles(x86)}\1cv8")
$platforms = foreach ($root in $platformRoots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory | Where-Object { $_.Name -match '^8\.\d+\.\d+\.\d+$' } |
            ForEach-Object {
                $bin = Join-Path $_.FullName 'bin'
                if (Test-Path (Join-Path $bin '1cv8.exe')) {
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

# --- Java для EDT (EDT 2026.x требует Java 21/25; берём Axiom Full) ---------
$javaHome = $env:CONVERT_JAVA_HOME
if (-not $javaHome -or -not (Test-Path (Join-Path $javaHome 'bin\javaw.exe'))) {
    $javaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Machine')
}
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

# --- EDT / 1cedtcli (используется плагином edtExport через edtfind) ---------
$edtRoot = "$env:ProgramW6432\1C\1CE\components"
$edt = $null
if (Test-Path $edtRoot) {
    if ($env:CONVERT_EDT_VERSION) {
        $edt = Get-ChildItem $edtRoot -Directory -Filter "1c-edt-$($env:CONVERT_EDT_VERSION)*" |
            Where-Object { Test-Path (Join-Path $_.FullName '1cedtcli.exe') } |
            Sort-Object Name | Select-Object -Last 1
    }
    if (-not $edt) {
        $edt = Get-ChildItem $edtRoot -Directory -Filter '1c-edt-*' |
            Where-Object { Test-Path (Join-Path $_.FullName '1cedtcli.exe') } |
            Sort-Object Name | Select-Object -Last 1
    }
}
if (-not $edt) { Fail "1C:EDT не найдена в $edtRoot (ожидается components\1c-edt-*\1cedtcli.exe)" }
Ok "EDT: $($edt.Name)"

# --- библиотеки oscript для gitsync (без прав администратора) ----------------
# edtExport 2.x требует пакет edtfind. OneScript не использует OSLIB; доп.
# каталоги библиотек задаются через OSCRIPT_CONFIG lib.additional — но задание
# lib.additional ВЫКЛЮЧАЕТ встроенный поиск в <gitsync>\oscript_modules
# (проверено на OneScript 1.9.4: json/gitrunner/... перестают находиться).
# Поэтому зеркалим в tools\oscript\oscript_modules всё, чего нет в системной
# lib, и указываем lib.additional только на наш каталог (путь без пробелов).
$oslib = Join-Path $tools 'oscript\oscript_modules'
# NB: локальная копия edtfind содержит патч НайтиМаркерыВКаталоге (пропуск
# «битых» элементов components\1c-enterprise-element-script-*) — при
# переустановке через opm патч потеряется.
if (-not (Test-Path (Join-Path $oslib 'edtfind'))) {
    $opm = Get-Command opm -ErrorAction SilentlyContinue
    if (-not $opm) { Fail "opm не найден в PATH (нужен для установки edtfind)" }
    Write-Host "ставлю edtfind локально (opm install -l) -> $oslib ..."
    $oscriptDir = Split-Path $oslib -Parent
    New-Item -ItemType Directory -Force -Path $oscriptDir | Out-Null
    Push-Location $oscriptDir
    try { & $opm.Source install -l edtfind | Out-Null } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $oslib 'edtfind'))) { Fail "edtfind не установлен в $oslib" }

$oneScriptRoot = Split-Path (Split-Path $gitsync.Source -Parent) -Parent
$sysLib = Join-Path $oneScriptRoot 'lib'
$gsModules = Join-Path $sysLib 'gitsync\oscript_modules'
if (Test-Path $gsModules) {
    foreach ($pkg in Get-ChildItem $gsModules -Directory) {
        if ((Test-Path (Join-Path $sysLib $pkg.Name)) -or (Test-Path (Join-Path $oslib $pkg.Name))) { continue }
        Copy-Item $pkg.FullName $oslib -Recurse -Force
    }
    if (-not (Test-Path (Join-Path $oslib 'gitsync'))) {
        Copy-Item (Join-Path $sysLib 'gitsync') $oslib -Recurse -Force
    }
}
$env:OSCRIPT_CONFIG = "lib.additional=$oslib"
Ok "oscript libs: $oslib (OSCRIPT_CONFIG lib.additional)"

# --- плагин edtExport --------------------------------------------------------
$plugins = & $gitsync.Source plugins list 2>&1 | Out-String
if ($plugins -notmatch '\[on\].*edtExport') {
    Write-Host "включаю плагин edtExport (gitsync-plugins, актуальная версия)..."
    & $gitsync.Source plugins install gitsync-plugins | Out-Null
    & $gitsync.Source plugins enable edtExport | Out-Null
    $plugins = & $gitsync.Source plugins list 2>&1 | Out-String
}
if ($plugins -notmatch '\[on\].*edtExport') { Fail "плагин edtExport не активен (gitsync plugins enable edtExport)" }
Ok "плагин edtExport активен"

if ($PrepareOnly) { Write-Host "`nИнструменты готовы." -ForegroundColor Cyan; exit 0 }

# --- запуск gitsync ----------------------------------------------------------
$cacheRoot = Join-Path $repo 'cache\gitsync'
New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null

# параметры плагина edtExport — через окружение (см. gitsync sync --help)
$env:GITSYNC_PROJECT_NAME = $ProjectName
$env:GITSYNC_WORKSPACE_LOCATION = Join-Path $cacheRoot 'workspace'

# gitsync ищет исходники в WORKDIR\src, если тот существует (issue #53
# upstream). EDT-проект edtExport сам содержит каталог src — поэтому src
# должен существовать в WORKDIR с ПЕРВОГО запуска, иначе второй запуск
# «переедет» в src и сломается. Итоговая структура (стабильная):
#   <Worktree>\.git               — git-репозиторий проекта
#   <Worktree>\src\VERSION, AUTHORS — служебные файлы gitsync
#   <Worktree>\src\.project, \src\src\... — содержимое EDT-проекта
New-Item -ItemType Directory -Force -Path (Join-Path $Worktree 'src') | Out-Null

# gitsync sync требует инициализированный worktree (файл VERSION в src);
# при отсутствии выполняем `gitsync init`. Плагин edtExport (2.x) мешает init
# (требует project-name, который регистрируется только для sync) — на время
# init отключаем его и включаем обратно.
if (-not (Test-Path (Join-Path $Worktree 'src\VERSION'))) {
    Write-Host "инициализирую worktree (gitsync init) -> $Worktree"
    & $gitsync.Source plugins disable edtExport | Out-Null
    try {
        & $gitsync.Source --v8version $PlatformMask init -u $StorageUser $Storage $Worktree
        if ($LASTEXITCODE -ne 0) { Fail "gitsync init завершился с кодом $LASTEXITCODE" }
    } finally {
        & $gitsync.Source plugins enable edtExport | Out-Null
    }
}
# gitsync init может не создать .git (и worktree внутри другого репозитория
# тогда подхватывает чужой .gitignore) — страхуемся
if (-not (Test-Path (Join-Path $Worktree '.git'))) {
    Write-Host "git init -> $Worktree"
    & git -C $Worktree init -q
    if ($LASTEXITCODE -ne 0) { Fail "git init завершился с кодом $LASTEXITCODE" }
}

$gargs = @('--v8version', $PlatformMask, '--tempdir', (Join-Path $cacheRoot 'temp'), '--domain-email', $Domain)
if ($VerboseLog) { $gargs += '-v' }
$gargs += 'sync'
$gargs += @('-u', $StorageUser)
if ($StoragePwd) { $gargs += @('-p', $StoragePwd) }
if ($Limit -gt 0) { $gargs += @('-l', "$Limit") }
if ($MinVersion -gt 0) { $gargs += @('--minversion', "$MinVersion") }
if ($MaxVersion -gt 0) { $gargs += @('--maxversion', "$MaxVersion") }
$gargs += @($Storage, $Worktree)

Write-Host "`n>>> gitsync $($gargs -join ' ')`n" -ForegroundColor Cyan
& $gitsync.Source @gargs
exit $LASTEXITCODE
