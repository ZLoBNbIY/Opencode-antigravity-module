@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\apply_antigravity_compat.ps1" %*
echo.
pause
