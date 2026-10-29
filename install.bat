@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

where powershell >nul 2>nul
if %ERRORLEVEL% equ 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    if %ERRORLEVEL% equ 0 goto done
)

echo ========================================================
echo   Установка и настройка Opencode-antigravity-module (CMD Fallback)
echo ========================================================
echo.

set "CONFIG_DIR=%USERPROFILE%\.config\opencode"
if not exist "%CONFIG_DIR%" (
    echo [*] Создание каталога конфигурации: %CONFIG_DIR%
    mkdir "%CONFIG_DIR%"
)

if not exist "%CONFIG_DIR%\antigravity.json" (
    echo [*] Копирование antigravity.json в %CONFIG_DIR%
    copy /y "%~dp0config-templates\antigravity.json" "%CONFIG_DIR%\antigravity.json"
)

if not exist "%CONFIG_DIR%\opencode.json" (
    echo [*] Копирование opencode.json в %CONFIG_DIR%
    copy /y "%~dp0config-templates\opencode.json" "%CONFIG_DIR%\opencode.json"
)

echo.
echo [*] Применение патчей совместимости (Gemini 3.8 / SSE / TTY)...
where node >nul 2>nul
if %ERRORLEVEL% equ 0 (
    node "%~dp0scripts\patch_plugin.mjs"
) else (
    set "PW_NODE=%USERPROFILE%\AppData\Local\Programs\Python\Python312\Lib\site-packages\playwright\driver\node.exe"
    if exist "!PW_NODE!" (
        "!PW_NODE!" "%~dp0scripts\patch_plugin.mjs"
    )
)

echo.
echo [*] Проверка и установка зависимостей GUI Менеджера (Python)...
set "CMD_PY="
python -c "import sys; sys.exit(0)" >nul 2>nul
if %ERRORLEVEL% equ 0 set "CMD_PY=python"
if not defined CMD_PY (
    py -3 -c "import sys; sys.exit(0)" >nul 2>nul
    if !ERRORLEVEL! equ 0 set "CMD_PY=py -3"
)

if defined CMD_PY (
    !CMD_PY! -m pip install -r "%~dp0gui-manager\requirements.txt" --quiet
    if !ERRORLEVEL! equ 0 (
        echo [✓] Зависимости GUI успешно установлены.
    ) else (
        echo [!] Предупреждение при установке зависимостей через pip.
    )
) else (
    echo [x] ОШИБКА: Python 3 не обнаружен!
    echo     Для работы Antigravity Hub требуется установить Python 3: https://www.python.org/downloads/
    echo     Обязательно отметьте галочку: "Add python.exe to PATH".
)

:done
pause
