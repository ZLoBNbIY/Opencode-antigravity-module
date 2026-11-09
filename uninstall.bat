@echo off
setlocal
set "SCRIPT=%~dp0uninstall.ps1"

if not exist "%SCRIPT%" goto missing_script

where powershell.exe >nul 2>nul
if errorlevel 1 goto try_pwsh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:try_pwsh
where pwsh.exe >nul 2>nul
if errorlevel 1 goto missing_powershell
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:missing_script
echo [ERROR] uninstall.ps1 must be next to this launcher.
pause
exit /b 1

:missing_powershell
echo [ERROR] Windows PowerShell or PowerShell 7 was not found.
pause
exit /b 1
