@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR.ps1"
  goto fin
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CONFIGURAR.ps1"
:fin
pause
