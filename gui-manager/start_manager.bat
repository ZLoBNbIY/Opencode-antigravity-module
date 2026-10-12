@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" pythonw antigravity_manager.pyw
) else (
    python antigravity_manager.pyw
)
