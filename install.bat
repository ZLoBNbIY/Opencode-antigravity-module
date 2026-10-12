@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================================
echo   Установка и настройка Opencode-antigravity-module
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
) else (
    echo [i] Файл antigravity.json уже существует в %CONFIG_DIR% (пропускаем перезапись).
)

if not exist "%CONFIG_DIR%\opencode.json" (
    echo [*] Копирование opencode.json в %CONFIG_DIR%
    copy /y "%~dp0config-templates\opencode.json" "%CONFIG_DIR%\opencode.json"
) else (
    echo [i] Файл opencode.json уже существует в %CONFIG_DIR%.
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
    ) else (
        echo [!] Node.js не найден в PATH. Убедитесь, что Node.js установлен для применения патчей.
    )
)

echo.
echo [*] Установка зависимостей для GUI Менеджера аккаунтов (Python)...
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    pip install -r "%~dp0gui-manager\requirements.txt" --quiet
    echo [✓] Зависимости GUI успешно установлены.
) else (
    echo [i] Python не найден в PATH. GUI менеджер можно запустить позже после установки Python.
)

echo.
echo ========================================================
echo   Установка завершена!
echo ========================================================
echo.
echo 1. Для входа в аккаунт Google запустите:
echo    node plugin\dist\cli.js login
echo    или запустите GUI менеджер: gui-manager\start_manager.bat
echo.
echo 2. Запустите OpenCode и выберите любую модель Gemini 3.8 / Gemini 3.7.
echo.
pause
