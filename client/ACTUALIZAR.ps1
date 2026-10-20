$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$PanelFolder = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $PanelFolder 'agent.py'))) { $PanelFolder = 'C:\PanelGo' }
if (-not (Test-Path -LiteralPath (Join-Path $PanelFolder 'agent.py'))) { $PanelFolder = Read-Host 'Carpeta donde instalaste Panel Go' }
$PanelFolder = (Resolve-Path -LiteralPath $PanelFolder).Path
if (-not (Test-Path -LiteralPath (Join-Path $PanelFolder 'agent.py')) -or -not (Test-Path -LiteralPath (Join-Path $PanelFolder 'panel\styles.css'))) { throw 'No se encontro una instalacion de Panel Go en esa carpeta.' }
$UpdateFolder = Join-Path $PanelFolder ('.actualizacion-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $UpdateFolder | Out-Null
$Updates = @{ 'agent.py'='client/agent.py'; 'panel/index.html'='public/index.html'; 'panel/styles.css'='public/styles.css'; 'panel/script.js'='public/script.js' }
foreach ($Item in $Updates.GetEnumerator()) { $Downloaded = Join-Path $UpdateFolder ($Item.Key.Replace('/','_')); Invoke-WebRequest -UseBasicParsing -Uri ('https://raw.githubusercontent.com/kfam2009/PanelGotableroGenerico/main/' + $Item.Value) -OutFile $Downloaded; if ((Get-Item -LiteralPath $Downloaded).Length -lt 100) { throw 'La descarga esta incompleta.' } }
$PanelPython = Join-Path $PanelFolder '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PanelPython)) { throw 'No se encontro Python del panel. Ejecutar INSTALAR.cmd primero.' }
$Readers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -eq $PanelPython -and $_.CommandLine -match 'agent\.py' }
foreach ($Reader in $Readers) { Stop-Process -Id $Reader.ProcessId -ErrorAction Stop; Wait-Process -Id $Reader.ProcessId -Timeout 5 -ErrorAction SilentlyContinue }
foreach ($Item in $Updates.GetEnumerator()) { $Target = Join-Path $PanelFolder $Item.Key; Copy-Item -LiteralPath $Target -Destination (Join-Path $UpdateFolder ($Item.Key.Replace('/','_') + '.anterior')); Copy-Item -LiteralPath (Join-Path $UpdateFolder ($Item.Key.Replace('/','_'))) -Destination $Target -Force }
Write-Host 'Diseno y monitores actualizados. Se conservan config.json, nombres y logos.' -ForegroundColor Green
Start-Process -FilePath (Join-Path $PanelFolder 'INICIAR.cmd') -WorkingDirectory $PanelFolder -WindowStyle Hidden
Start-Process 'https://panelgo-tablero.onrender.com'
