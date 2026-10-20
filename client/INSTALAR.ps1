param([switch]$PruebaLocal)
$ErrorActionPreference = 'Stop'
$ClientRoot = $PSScriptRoot
$Python = $null
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $BundledPython) { $Python = $BundledPython }
if (-not $Python) {
    foreach ($PythonName in @('py.exe','python.exe')) {
        $Candidate = Get-Command $PythonName -ErrorAction SilentlyContinue
        if ($Candidate) { $Python = $Candidate.Source; break }
    }
}
if (-not $Python) { throw 'Instalar Python 3.10 o posterior desde python.org, con la opcion Add Python to PATH.' }
& $Python -c 'import sys; assert sys.version_info >= (3,10), "Se requiere Python 3.10 o posterior"'
if ($LASTEXITCODE -ne 0) { throw 'Python no esta disponible o es demasiado antiguo.' }
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
