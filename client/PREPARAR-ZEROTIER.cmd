@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR.ps1"
  if errorlevel 1 goto fin
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CONFIGURAR-ZEROTIER.ps1"
:fin
pause
