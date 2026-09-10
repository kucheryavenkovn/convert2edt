# Doctor Windows-стороны Host Bridge.
# Проверяет: python/pywin32, платформу 1С, лицензию (реальный smoke), хранилище, bridgeRoot, сервис.
[CmdletBinding()]
param(
    [string]$Config = "$PSScriptRoot\bridge_config.json",
    [switch]$SkipService
)
$ErrorActionPreference = 'Continue'

function Pass($m) { Write-Host "[PASS] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:failed = $true }
function Info($m) { Write-Host "       $m" -ForegroundColor DarkGray }
$script:failed = $false

if (-not (Test-Path $Config)) { Fail "конфиг не найден: $Config (скопируйте bridge_config.example.json)"; exit 1 }
$cfg = Get-Content $Config -Raw | ConvertFrom-Json

# 1. python + pywin32
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Pass "python ($($py.Source))" } else { Fail "python не найден в PATH" }
python -c "import win32serviceutil" 2>$null
if ($LASTEXITCODE -eq 0) { Pass "pywin32" } else { Fail "pywin32 не установлен: pip install pywin32" }

# 2. платформа
$found = @()
foreach ($root in $cfg.platformRoots) {
    if (Test-Path $root) {
        $found += Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^8\.\d+\.\d+\.\d+$' -and (Test-Path (Join-Path $_.FullName 'bin\1cv8.exe')) }
    }
}
if ($found.Count -gt 0) {
    Pass "1cv8 found ($($found.Count) версий)"
    $found | ForEach-Object { Info "$($_.Name) -> $($_.FullName)\bin\1cv8.exe" }
    $sel = & python "$PSScriptRoot\bridge.py" --config $Config --check 2>$null | Select-String 'selected:'
    Info "selected: $sel"
} else {
    Fail "1cv8 не найден в $($cfg.platformRoots -join ', ')"
}

# 3. хранилище
foreach ($s in $cfg.allowedStorages) {
    if (Test-Path (Join-Path $s '1cv8ddb.1CD')) { Pass "storage readable ($s)" }
    else { Fail "хранилище не найдено: $s\1cv8ddb.1CD" }
    $ver = Join-Path $s 'ver'
    if (Test-Path $ver) { Info "ver: " + (Get-Content $ver -Raw) }
}

# 4. bridgeRoot
New-Item -ItemType Directory -Force -Path $cfg.bridgeRoot | Out-Null
$probe = Join-Path $cfg.bridgeRoot '.write-probe'
try {
    Set-Content $probe 'ok' -ErrorAction Stop
    Remove-Item $probe
    Pass "bridge directory writable ($($cfg.bridgeRoot))"
} catch {
    Fail "bridge directory НЕ записывается: $($cfg.bridgeRoot) ($_)"
}

# 5. токен
if ($cfg.token -and $cfg.token -ne 'CHANGE-ME-long-random-string' -and $cfg.listen -notmatch '^127\.0\.0\.1') {
    Pass "bearer token настроен (listen $($cfg.listen))"
} elseif ($cfg.listen -match '^127\.0\.0\.1') {
    Info "listen 127.0.0.1 — токен необязателен (Docker-доступ будет невозможен)"
} else {
    Fail "listen $($cfg.listen) без валидного token — небезопасно"
}

# 6. лицензия (реальный smoke через --check)
if ($py) {
    $out = & python "$PSScriptRoot\bridge.py" --config $Config --check 2>&1
    if ($out -match 'licenseSmoke: ok') { Pass "1C license smoke (CREATEINFOBASE)" }
    elseif ($out -match 'licenseSmoke: disabled') { Info "license smoke отключён в конфиге" }
    else { Fail "1C license smoke: $out" }
}

# 7. сервис
if (-not $SkipService) {
    $svc = Get-Service 1CHostBridge -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq 'Running') { Pass "service 1CHostBridge: Running" }
        else { Fail "service 1CHostBridge: $($svc.Status) (sc start 1CHostBridge)" }
        Info "account: " + (Get-CimInstance Win32_Service -Filter "Name='1CHostBridge'").StartName
    } else {
        Fail "service 1CHostBridge не установлен (install-service.ps1)"
    }
}

Write-Host ""
if ($script:failed) { Write-Host "HOST DOCTOR: есть ошибки" -ForegroundColor Red; exit 1 }
else { Write-Host "HOST DOCTOR: все проверки пройдены" -ForegroundColor Green }
