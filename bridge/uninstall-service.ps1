# Остановка и удаление сервиса 1C Host Bridge
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'
$svcName = '1CHostBridge'
if (Get-Service $svcName -ErrorAction SilentlyContinue) {
    sc.exe stop $svcName
    Start-Sleep -Seconds 2
    sc.exe delete $svcName
    Write-Host "Сервис $svcName удалён (конфиг и логи не тронуты)." -ForegroundColor Green
} else {
    Write-Host "Сервис $svcName не установлен."
}
