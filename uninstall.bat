@echo off
setlocal
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%uninstall.ps1"
if not exist "%SCRIPT%" (
    echo [ОШИБКА] Рядом с uninstall.bat не найден uninstall.ps1.
    pause
    exit /b 1
)

where powershell.exe >nul 2>nul
if not errorlevel 1 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where pwsh.exe >nul 2>nul
if not errorlevel 1 (
    pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo [ОШИБКА] Для удаления требуется Windows PowerShell 5 или PowerShell 7.
pause
exit /b 1
