$ErrorActionPreference = 'Stop'
$ConfigFile = Join-Path $PSScriptRoot 'config.json'
$Config = [ordered]@{ obs_port=4455; source='Camara 2'; game_source='camara 01'; local_port=8771; monitor_mode='program' }
if (Test-Path -LiteralPath $ConfigFile) {
    (Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $Config[$_.Name] = $_.Value }
}

Write-Host 'Lector en esta PC, OBS en otra PC por ZeroTier.' -ForegroundColor Cyan
$Detected = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceAlias -like 'ZeroTier*' } | Select-Object -ExpandProperty IPAddress)
if ($Detected.Count -eq 0) { Write-Host 'No se detecto ZeroTier en esta PC. Revisar que este conectado a la red.' -ForegroundColor Yellow }
$Suggested = if ($Detected.Count -gt 0) { $Detected[0] } else { $Config['bridge_address'] }

$ObsHost = Read-Host 'IP de ZeroTier de la PC con OBS'
if (-not $ObsHost) { throw 'Falta la IP de la PC con OBS.' }
$Bridge = Read-Host "IP de ZeroTier de ESTA PC (Enter: $Suggested)"
if (-not $Bridge) { $Bridge = $Suggested }
if (-not $Bridge) { throw 'Falta la IP de ZeroTier de esta PC.' }
$Secure = Read-Host 'Contrasena del WebSocket de OBS (Enter: sin autenticacion)' -AsSecureString
$Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure))
if (-not $Password) { Write-Host 'OBS sin clave: cualquier equipo de la red ZeroTier puede controlar OBS.' -ForegroundColor Yellow }
$Board = Read-Host "Fuente del tablero en OBS (Enter: $($Config['source']))"
if ($Board) { $Config['source'] = $Board }
$Game = Read-Host "Fuente del juego en OBS (Enter: $($Config['game_source']))"
if ($Game) { $Config['game_source'] = $Game }

$Config['obs_host'] = $ObsHost
$Config['obs_password'] = $Password
$Config['bridge_address'] = $Bridge
$Config['monitor_mode'] = 'program'
$Config | ConvertTo-Json | Set-Content -LiteralPath $ConfigFile -Encoding UTF8

$Probe = Test-NetConnection -ComputerName $ObsHost -Port ([int]$Config['obs_port']) -WarningAction SilentlyContinue
if ($Probe.TcpTestSucceeded) { Write-Host "OBS responde en ${ObsHost}:$($Config['obs_port'])." -ForegroundColor Green }
else { Write-Host "Todavia no responde OBS en ${ObsHost}:$($Config['obs_port']). Revisar OBS abierto, WebSocket activo y firewall de esa PC." -ForegroundColor Yellow }
Write-Host 'Configuracion guardada. Ejecutar INICIAR.cmd.' -ForegroundColor Green
