param([switch]$PruebaLocal)
$ErrorActionPreference = 'Stop'
$ClientRoot = $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Python = $null
$PythonCandidates = @((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'))
# The python.exe in WindowsApps is only a Microsoft Store shortcut, not a real Python.
foreach ($Name in @('py.exe','python.exe')) { $Found = Get-Command $Name -ErrorAction SilentlyContinue; if ($Found -and $Found.Source -notlike '*\WindowsApps\*') { $PythonCandidates += $Found.Source } }
foreach ($Candidate in $PythonCandidates) { if (Test-Path -LiteralPath $Candidate) { & $Candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; if ($LASTEXITCODE -eq 0) { $Python = $Candidate; break } } }
if (-not $Python) {
    Write-Host 'Esta PC no tiene Python. Descargando e instalando Python oficial (unos minutos)...' -ForegroundColor Cyan
    $PythonInstaller = Join-Path $env:TEMP 'python-3.13.16-amd64.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe' -OutFile $PythonInstaller
    $Signature = Get-AuthenticodeSignature -LiteralPath $PythonInstaller
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') { throw 'No se pudo verificar la firma oficial de Python.' }
    # Per-user install: no administrator password needed.
    $Installation = Start-Process -FilePath $PythonInstaller -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=0' -Wait -PassThru -WindowStyle Hidden
    if ($Installation.ExitCode -notin @(0,3010)) { throw ('Python no se instalo. Codigo ' + $Installation.ExitCode) }
    Remove-Item -LiteralPath $PythonInstaller -ErrorAction SilentlyContinue
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { throw 'No se encontro Python despues de instalarlo.' }
    Write-Host 'Python instalado.' -ForegroundColor Green
}
& $Python -m venv (Join-Path $ClientRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
$ClientPython = Join-Path $ClientRoot '.venv\Scripts\python.exe'
& $ClientPython -m pip install -r (Join-Path $ClientRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar Pillow y NumPy.' }
& (Join-Path $ClientRoot 'INSTALAR-VIDEO.ps1')
if ($PruebaLocal) {
    & (Join-Path $ClientRoot 'CONFIGURAR-PRUEBA.ps1')
    Write-Host 'Listo. Ejecutar PROBAR-VIDEO.cmd.' -ForegroundColor Green
} else {
    & (Join-Path $ClientRoot 'CONFIGURAR.ps1')
    Write-Host 'Instalado. Ejecutar INICIAR.cmd para abrir el panel. Para cambiar vMix/OBS o las IP: CONFIGURAR.cmd.' -ForegroundColor Green
}

if (-not $PruebaLocal) {
    $DesktopFolder = [Environment]::GetFolderPath('Desktop')
    $ShellLink = New-Object -ComObject WScript.Shell
    $PanelLink = $ShellLink.CreateShortcut((Join-Path $DesktopFolder 'Panel Go - Tablero.lnk'))
    $PanelLink.TargetPath = Join-Path $ClientRoot 'INICIAR.cmd'
    $PanelLink.WorkingDirectory = $ClientRoot
    $PanelLink.Save()
    Write-Host 'Acceso directo Panel Go - Tablero creado en el escritorio.' -ForegroundColor Green
}
