$ErrorActionPreference = 'Stop'
# ffmpeg recibe el video SRT/RTSP del tablero. Se busca uno existente antes de instalar.
function Find-FFmpeg {
    $Candidates = @((Join-Path $PSScriptRoot 'tools\ffmpeg.exe'), (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ffmpeg.exe'), 'C:\ffmpeg\bin\ffmpeg.exe', 'C:\Program Files\ffmpeg\bin\ffmpeg.exe')
    $OnPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($OnPath) { $Candidates = @($OnPath.Source) + $Candidates }
    foreach ($Candidate in $Candidates) { if ($Candidate -and (Test-Path -LiteralPath $Candidate)) { return $Candidate } }
    return $null
}
$FFmpeg = Find-FFmpeg
if (-not $FFmpeg) {
    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $Winget) { throw 'Falta ffmpeg y no esta winget. Instalar ffmpeg (gyan.dev, build essentials) y volver a ejecutar.' }
    Write-Host 'Instalando ffmpeg con winget (Gyan.FFmpeg)...' -ForegroundColor Cyan
    & winget install --id Gyan.FFmpeg -e --source winget | Out-Host
    $FFmpeg = Find-FFmpeg
    if (-not $FFmpeg) {
        $Installed = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Installed) { $FFmpeg = $Installed.FullName }
    }
    if (-not $FFmpeg) { throw 'No se pudo instalar ffmpeg. Cerrar esta ventana, abrir una nueva y ejecutar de nuevo.' }
}
$Protocols = & $FFmpeg -hide_banner -protocols 2>$null
if (-not ($Protocols | Where-Object { $_.Trim() -eq 'srt' })) { throw "El ffmpeg encontrado ($FFmpeg) no admite SRT. Instalar Gyan.FFmpeg." }
Write-Host "ffmpeg listo: $FFmpeg" -ForegroundColor Green
return $FFmpeg
