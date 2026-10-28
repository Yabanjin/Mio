@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Install-Mio.ps1" -InternalOnly
pause
