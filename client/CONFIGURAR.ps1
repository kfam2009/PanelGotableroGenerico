$ErrorActionPreference = 'Stop'
# Asistente: vMix u OBS, IPs de ZeroTier y origen del video del tablero.
$ConfigFile = Join-Path $PSScriptRoot 'config.json'
$Config = [ordered]@{ obs_port=4455; vmix_port=8088; vmix_overlay=1; source='Camara 2'; game_source='camara 01'; local_port=8771; monitor_mode='program' }
if (Test-Path -LiteralPath $ConfigFile) {
    (Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $Config[$_.Name] = $_.Value }
}
function Ask($Text, $Default) {
    $Answer = Read-Host $(if ($Default) { "$Text (Enter: $Default)" } else { $Text })
    if ($Answer) { return $Answer.Trim() } else { return $Default }
}

Write-Host ''
Write-Host 'PANEL GO - TABLERO' -ForegroundColor Cyan
Write-Host '1) vMix'
Write-Host '2) OBS'
$Choice = Ask 'Con que software trabajas' $(if ($Config['switcher'] -eq 'vmix') { '1' } else { '2' })
$Switcher = if ($Choice -eq '1' -or $Choice -match '^vmix$') { 'vmix' } else { 'obs' }
$Name = if ($Switcher -eq 'vmix') { 'vMix' } else { 'OBS' }

$Detected = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceAlias -like 'ZeroTier*' } | Select-Object -ExpandProperty IPAddress)
$ThisPc = if ($Detected.Count -gt 0) { $Detected[0] } elseif ($Config['bridge_address']) { $Config['bridge_address'] } else { '' }
if ($Detected.Count -eq 0) { Write-Host 'No se detecto ZeroTier en esta PC. Si todo esta en esta misma PC no hace falta.' -ForegroundColor Yellow }
$ThisPc = Ask 'IP de ZeroTier de ESTA PC (donde corre el panel)' $ThisPc
$Production = Ask "IP de ZeroTier de la PC con $Name (igual a la anterior = esta misma PC)" $(if ($Config['production_host'] -and $Config['production_host'] -ne '127.0.0.1') { $Config['production_host'] } else { $ThisPc })
if (-not $Production -or $Production -eq $ThisPc -or $Production -in @('127.0.0.1','localhost')) {
    Write-Host "$Name esta en esta misma PC." -ForegroundColor Green
    $Production = '127.0.0.1'
} else { Write-Host "$Name en otra PC por ZeroTier: $Production" -ForegroundColor Green }

$Config['switcher'] = $Switcher
$Config['production_host'] = $Production
$Config['obs_host'] = $Production
$Config['bridge_address'] = $ThisPc
$SrtHost = if ($Production -eq '127.0.0.1') { '127.0.0.1' } else { $Production }

Write-Host ''
Write-Host 'Acceso remoto (opcional): permite cargar el codigo y calibrar el tablero desde otra PC por ZeroTier.' -ForegroundColor Cyan
$RemoteIp = Ask 'IP de ZeroTier del tecnico que calibra a distancia (Enter: sin acceso remoto)' $Config['remote_admin_ip']
if ($RemoteIp -and $ThisPc) {
    $Config['remote_admin_ip'] = $RemoteIp
    $RemotePass = Ask 'Contrasena del acceso remoto (minimo 8 caracteres)' $Config['remote_password']
    while (-not $RemotePass -or $RemotePass.Length -lt 8) { $RemotePass = Ask 'La contrasena tiene que tener al menos 8 caracteres' '' }
    $Config['remote_password'] = $RemotePass
} else {
    if ($RemoteIp) { Write-Host 'Para el acceso remoto esta PC necesita ZeroTier. Queda desactivado.' -ForegroundColor Yellow }
    $Config['remote_admin_ip'] = ''; $Config['remote_password'] = ''
}

if ($Switcher -eq 'vmix') {
    Write-Host ''
    Write-Host 'En vMix: Settings > Outputs/NDI/SRT > Output 2 (o 3/4) > Source: la camara del tablero > SRT,' -ForegroundColor Cyan
    Write-Host 'Type: Listener, puerto 9000, H.264, 2500 kbps, 1920x1080, Latency 120 (en la misma red) o 400 (por ZeroTier).' -ForegroundColor Cyan
    $Config['board_mode'] = 'stream'
    Write-Host 'Para probar sin vMix se puede poner la ruta de un video o una foto del tablero (C:\...\tablero.mp4).' -ForegroundColor Cyan
    $Config['board_url'] = Ask 'Salida SRT del tablero (IP:puerto, srt://, rtsp:// o archivo)' $(if ($Config['board_url']) { $Config['board_url'] } else { "${SrtHost}:9000" })
    $Config['board_url'] = "$($Config['board_url'])".Trim('"')
    $Config['vmix_overlay'] = [int](Ask 'Canal de overlay de vMix para el marcador (1 a 4)' $Config['vmix_overlay'])
    $Game = Ask 'Monitor de programa: salida SRT del programa de vMix (IP:puerto, Enter: sin monitor)' $Config['game_url']
    $Config['game_url'] = if ($Game) { $Game } else { '' }
} else {
    Write-Host ''
    Write-Host 'Como llega la camara del tablero:'
    Write-Host '1) Fuente de OBS (captura desde OBS)'
    Write-Host '2) Video SRT o RTSP (camara IP o salida SRT), o un archivo de video/foto para probar'
    $Board = Ask 'Opcion' $(if ($Config['board_mode'] -eq 'stream') { '2' } else { '1' })
    if ($Board -eq '2') {
        $Config['board_mode'] = 'stream'
        $Config['board_url'] = "$(Ask 'Video del tablero (IP:puerto para SRT, rtsp://..., o ruta de un archivo)' $Config['board_url'])".Trim('"')
    } else {
        $Config['board_mode'] = 'obs'
        $Config['source'] = Ask 'Nombre exacto de la fuente del tablero en OBS' $Config['source']
    }
    $Config['game_source'] = Ask 'Fuente del juego en OBS para el monitor' $Config['game_source']
    $Secure = Read-Host 'Contrasena del WebSocket de OBS (Enter: sin autenticacion)' -AsSecureString
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure))
    $Config['obs_password'] = $Password
    $Config['game_url'] = ''
}

if ($Config['board_mode'] -eq 'stream' -or $Config['game_url']) {
    $Config['ffmpeg_path'] = & (Join-Path $PSScriptRoot 'INSTALAR-FFMPEG.ps1')
}
$Config | ConvertTo-Json | Set-Content -LiteralPath $ConfigFile -Encoding UTF8

$Port = if ($Switcher -eq 'vmix') { [int]$Config['vmix_port'] } else { [int]$Config['obs_port'] }
$Probe = Test-NetConnection -ComputerName $Production -Port $Port -WarningAction SilentlyContinue
if ($Probe.TcpTestSucceeded) { Write-Host "$Name responde en ${Production}:$Port." -ForegroundColor Green }
elseif ($Switcher -eq 'vmix') { Write-Host "vMix no responde en ${Production}:$Port. En vMix: Settings > Web Controller activado (puerto $Port) y firewall de esa PC." -ForegroundColor Yellow }
else { Write-Host "OBS no responde en ${Production}:$Port. Revisar OBS abierto, WebSocket activo y firewall de esa PC." -ForegroundColor Yellow }
if ($Production -ne '127.0.0.1') {
    Write-Host "La grafica se sirve desde esta PC en http://${ThisPc}:8772/graphics.html. Si Windows pregunta, permitir Python en la red." -ForegroundColor Cyan
}
if ($Config['remote_admin_ip']) {
    Write-Host "Acceso remoto: desde $($Config['remote_admin_ip']) abrir http://${ThisPc}:8773/ (usuario: cualquiera, contrasena: la elegida). Si Windows pregunta, permitir Python en la red." -ForegroundColor Cyan
}
Write-Host 'Configuracion guardada. Ejecutar INICIAR.cmd.' -ForegroundColor Green
