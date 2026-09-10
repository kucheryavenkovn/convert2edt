# Установка 1C Host Bridge как Windows-сервиса.
# Параметры (все необязательные):
#   -Login DOMAIN\svc_1c_git -Password ***   сервис-аккаунт (рекомендуется)
#   -Config C:\1c-bridge\bridge_config.json   путь к конфигу (по умолчанию рядом)
#   -Token <токен>                            записать токен в конфиг при создании
[CmdletBinding()]
param(
    [string]$Login,
    [string]$Password,
    [string]$Config = "$PSScriptRoot\bridge_config.json",
    [string]$Token
)

$ErrorActionPreference = 'Stop'
$svcName = '1CHostBridge'

if (-not (Test-Path $Config)) {
    Copy-Item "$PSScriptRoot\bridge_config.example.json" $Config
    Write-Host "Создан конфиг: $Config — проверьте и запустите снова." -ForegroundColor Yellow
    if ($Token) {
        $cfg = Get-Content $Config -Raw | ConvertFrom-Json
        $cfg.token = $Token
        $cfg | ConvertTo-Json -Depth 10 | Set-Content $Config -Encoding UTF8
        Write-Host "Токен записан в конфиг." -ForegroundColor Green
    }
    Write-Host "Минимум проверить: token, allowedStorages, bridgeRoot, pathMappings." -ForegroundColor Yellow
    exit 1
}

$python = (Get-Command python).Source
if (-not $python) { throw "python не найден в PATH" }
python -c "import win32serviceutil" 2>$null
if ($LASTEXITCODE -ne 0) { throw "pywin32 не установлен (pip install pywin32)" }

# каталог конфига должен быть читабелен сервисом
$cfgDir = Split-Path $Config -Parent
if ($cfgDir -eq $PSScriptRoot) {
    Write-Warning "Конфиг лежит в репозитории ($cfgDir). Рекомендуется перенести в служебный каталог (например E:\1c-bridge)."
}

# мост создаёт bridgeRoot сам, но права лучше проверить заранее
$cfg = Get-Content $Config -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $cfg.bridgeRoot | Out-Null

$binPath = '"' + $python + '" "' + "$PSScriptRoot\bridge_service.py" + '" --config "' + $Config + '"'

if (Get-Service $svcName -ErrorAction SilentlyContinue) {
    Write-Host "Сервис $svcName уже существует — удаляю старую регистрацию." -ForegroundColor Yellow
    sc.exe stop $svcName | Out-Null
    sc.exe delete $svcName | Out-Null
    Start-Sleep -Seconds 2
}

if ($Login) {
    if (-not $Password) { throw "Задан -Login, требуется -Password" }
    sc.exe create $svcName binPath= $binPath start= auto obj= $Login password= $Password | Out-Null
} else {
    sc.exe create $svcName binPath= $binPath start= auto | Out-Null
}
if ($LASTEXITCODE -ne 0) { throw "sc.exe create failed" }

sc.exe description $svcName "Allowlisted запуск 1cv8 DESIGNER для Docker-конвертера gitsync (docs/SPEC.md)"
sc.exe failure $svcName reset= 86400 actions= restart/10000/restart/30000/restart/60000 | Out-Null
sc.exe start $svcName | Out-Null
Start-Sleep -Seconds 3
Get-Service $svcName | Format-Table Name, Status, StartType

Write-Host ""
Write-Host "Сервис установлен. Проверка: .\doctor.ps1 -Config $Config" -ForegroundColor Green
Write-Host "Firewall (пример, только для Docker-подсети):" -ForegroundColor Yellow
Write-Host "  New-NetFirewallRule -DisplayName '1C Host Bridge' -Direction Inbound -LocalPort 17833 -Protocol TCP -RemoteAddress 172.16.0.0/12,192.168.0.0/16 -Action Allow"
