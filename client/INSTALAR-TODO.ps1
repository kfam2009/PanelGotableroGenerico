$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$PanelRoot = 'C:\PanelGo'
$BundleVersion = '2026.10.17-clock-fast-4'
$TempFolder = Join-Path $env:TEMP ('PanelGo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TempFolder | Out-Null
Write-Host 'Preparando Panel Go. OBS y la transmision siguen abiertos.' -ForegroundColor Cyan
$BootstrapLines = Get-Content -LiteralPath $env:PANELGO_BAT
$PayloadStart = [Array]::IndexOf($BootstrapLines,'#PANELGO_ZIP')
if ($PayloadStart -lt 0) { throw 'El archivo esta incompleto. Descargar nuevamente.' }
$BundleZip = Join-Path $TempFolder 'panel.zip'
[IO.File]::WriteAllBytes($BundleZip,[Convert]::FromBase64String(($BootstrapLines[($PayloadStart+1)..($BootstrapLines.Length-1)] -join '')))
$Extracted = Join-Path $TempFolder 'panel'
Expand-Archive -LiteralPath $BundleZip -DestinationPath $Extracted
if (-not (Test-Path -LiteralPath (Join-Path $Extracted 'agent.py'))) { throw 'Faltan archivos del panel.' }
$Python = $null
$PythonCandidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'))
foreach ($Name in @('py.exe','python.exe')) { $Found = Get-Command $Name -ErrorAction SilentlyContinue; if ($Found -and $Found.Source -notlike '*\WindowsApps\*') { $PythonCandidates += $Found.Source } }
foreach ($Candidate in $PythonCandidates) { if (Test-Path -LiteralPath $Candidate) { & $Candidate -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,15) else 1)'; if ($LASTEXITCODE -eq 0) { $Python=$Candidate; break } } }
if (-not $Python) {
    Write-Host 'Instalando Python oficial. Puede tardar unos minutos...'
    $PythonInstaller = Join-Path $TempFolder 'python-3.13.16-amd64.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe' -OutFile $PythonInstaller
    $Signature = Get-AuthenticodeSignature -LiteralPath $PythonInstaller
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') { throw 'No se pudo verificar la firma oficial de Python.' }
    $Installation = Start-Process -FilePath $PythonInstaller -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=0' -Wait -PassThru -WindowStyle Hidden
    if ($Installation.ExitCode -notin @(0,3010)) { throw ('Python no se instalo. Codigo ' + $Installation.ExitCode) }
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { throw 'No se encontro Python despues de instalarlo.' }
}
$RuntimePython = Join-Path $PanelRoot '.venv\Scripts\python.exe'
$VersionFile = Join-Path $PanelRoot '.panelgo-version'
$NeedsUpdate = -not (Test-Path -LiteralPath $VersionFile)
if (-not $NeedsUpdate) { $NeedsUpdate = (Get-Content -LiteralPath $VersionFile -Raw).Trim() -ne $BundleVersion }
if ($NeedsUpdate) {
    New-Item -ItemType Directory -Path $PanelRoot -Force | Out-Null
    $Readers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -eq $RuntimePython -and $_.CommandLine -match 'agent\.py' }
    foreach ($Reader in $Readers) { Stop-Process -Id $Reader.ProcessId -ErrorAction Stop; Wait-Process -Id $Reader.ProcessId -Timeout 5 -ErrorAction SilentlyContinue }
    $Keep = @('config.json','.graphic-settings.json')
    foreach ($File in Get-ChildItem -LiteralPath $Extracted -File) { if ($File.Name -notin $Keep -or -not (Test-Path -LiteralPath (Join-Path $PanelRoot $File.Name))) { Copy-Item -LiteralPath $File.FullName -Destination (Join-Path $PanelRoot $File.Name) -Force } }
    foreach ($Folder in Get-ChildItem -LiteralPath $Extracted -Directory) { Copy-Item -LiteralPath $Folder.FullName -Destination $PanelRoot -Recurse -Force }
    $DefaultConfig = Get-Content -LiteralPath (Join-Path $Extracted 'config.json') -Raw | ConvertFrom-Json
    $LocalConfigPath = Join-Path $PanelRoot 'config.json'
    $LocalConfig = Get-Content -LiteralPath $LocalConfigPath -Raw | ConvertFrom-Json
    foreach ($Key in @('cloud_url','ingest_token','obs_host','monitor_mode')) { $LocalConfig | Add-Member -MemberType NoteProperty -Name $Key -Value $DefaultConfig.$Key -Force }
    $LocalConfig | ConvertTo-Json | Set-Content -LiteralPath $LocalConfigPath -Encoding UTF8
    if (-not (Test-Path -LiteralPath $RuntimePython)) { & $Python -m venv (Join-Path $PanelRoot '.venv'); if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Python para Panel Go.' } }
    Write-Host 'Comprobando dependencias del lector...'
    & $RuntimePython -m pip install -r (Join-Path $PanelRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias. Revisar internet.' }
    Set-Content -LiteralPath $VersionFile -Value $BundleVersion -Encoding ASCII
}
$InstalledBat = Join-Path $PanelRoot 'PanelGo.bat'
if ([IO.Path]::GetFullPath($env:PANELGO_BAT) -ne $InstalledBat) { Copy-Item -LiteralPath $env:PANELGO_BAT -Destination $InstalledBat -Force }
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $Desktop 'Panel Go - Tablero.lnk'))
$Shortcut.TargetPath=$InstalledBat; $Shortcut.WorkingDirectory=$PanelRoot; $Shortcut.Save()
$ExistingReader = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -eq $RuntimePython -and $_.CommandLine -match 'agent\.py' }
if (-not $ExistingReader) {
    $Listener = Get-NetTCPConnection -LocalPort 8771 -State Listen -ErrorAction SilentlyContinue
    if ($Listener) { throw 'El puerto del panel esta ocupado por otro lector. Cerra ese lector y abri Panel Go otra vez.' }
    Start-Process -FilePath $RuntimePython -ArgumentList '-u agent.py' -WorkingDirectory $PanelRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PanelRoot 'lector.log') -RedirectStandardError (Join-Path $PanelRoot 'lector-error.log') | Out-Null
}
if ($NeedsUpdate) {
    $ReaderReady = $false
    for ($Attempt=0; $Attempt -lt 20; $Attempt++) { try { $ReaderState=Invoke-RestMethod 'http://127.0.0.1:8771/api/state' -TimeoutSec 1; $ReaderReady=$ReaderState.service -eq 'panelgo-tablero'; if ($ReaderReady) { break } } catch {}; Start-Sleep -Milliseconds 250 }
    if ($ReaderReady) { & $RuntimePython (Join-Path $PanelRoot 'refresh_graphic.py') }
}
Start-Process 'https://panelgo-tablero.onrender.com'
Write-Host 'Panel Go iniciado. Abrir OBS si todavia esta cerrado.' -ForegroundColor Green
Write-Host 'Si el navegador pregunta por la red local, permitir para ver los monitores.'
