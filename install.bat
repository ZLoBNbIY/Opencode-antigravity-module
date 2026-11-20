@echo off
setlocal DisableDelayedExpansion
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL%" (
    >&2 echo Windows PowerShell is required to run install.ps1.
    exit /b 1
)
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
