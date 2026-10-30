@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY_EXE="
set "PYW_EXE="

:: 1. Проверка через py launcher
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 -c "import sys; sys.exit(0)" >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY_EXE=%%i"
    )
)

:: 2. Проверка python в PATH (проверяем реальную работоспособность, исключая заглушку WindowsApps)
if not defined PY_EXE (
    where python >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        python -c "import sys; sys.exit(0)" >nul 2>nul
        if !ERRORLEVEL! equ 0 (
            for /f "delims=" %%i in ('where python 2^>nul') do (
                if not defined PY_EXE (
                    echo "%%i" | findstr /i "WindowsApps" >nul
                    if !ERRORLEVEL! neq 0 (
                        set "PY_EXE=%%i"
                    )
                )
            )
            if not defined PY_EXE (
                for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY_EXE=%%i"
            )
        )
    )
)

:: 3. Поиск по стандартным путям установки Python
if not defined PY_EXE (
    for %%D in (Python313 Python312 Python311 Python310) do (
        if not defined PY_EXE (
            if exist "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" (
                "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" -c "import sys; sys.exit(0)" >nul 2>nul
                if !ERRORLEVEL! equ 0 set "PY_EXE=%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
            )
            if not defined PY_EXE if exist "%ProgramFiles%\Python\%%D\python.exe" (
                "%ProgramFiles%\Python\%%D\python.exe" -c "import sys; sys.exit(0)" >nul 2>nul
                if !ERRORLEVEL! equ 0 set "PY_EXE=%ProgramFiles%\Python\%%D\python.exe"
            )
            if not defined PY_EXE if exist "C:\%%D\python.exe" (
                "C:\%%D\python.exe" -c "import sys; sys.exit(0)" >nul 2>nul
                if !ERRORLEVEL! equ 0 set "PY_EXE=C:\%%D\python.exe"
            )
        )
    )
)

:: Если Python так и не найден — выводим ошибку с инструкциями и НЕ закрываем окно
if not defined PY_EXE (
    cls
    echo ================================================================
    echo   [ОШИБКА] Python 3 не обнаружен на вашем компьютере!
    echo ================================================================
    echo.
    echo   Для работы Antigravity Hub требуется установленный Python 3 ^(3.10+^).
    echo.
    echo   Рекомендации по установке:
    echo     1. Скачайте официальный установщик Python:
    echo        https://www.python.org/downloads/
    echo        ^(или в PowerShell: winget install Python.Python.3.12^)
    echo.
    echo     2. ВАЖНО при установке:
    echo        Обязательно отметьте галочку:
    echo        [X] "Add python.exe to PATH" ^("Добавить Python в PATH"^)
    echo.
    echo     3. Если Python уже установлен:
    echo        Убедитесь, что путь к нему добавлен в системную переменную PATH,
    echo        либо отключите плейсхолдер Windows:
    echo        Параметры -^> Приложения -^> Дополнительные параметры -^> Псевдонимы приложений.
    echo.
    echo ================================================================
    echo.
    pause
    exit /b 1
)

:: Поиск pythonw.exe рядом с найденным python.exe
for %%F in ("!PY_EXE!") do set "PY_DIR=%%~dpF"
if exist "!PY_DIR!pythonw.exe" (
    set "PYW_EXE=!PY_DIR!pythonw.exe"
) else (
    where pythonw >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        pythonw -c "import sys; sys.exit(0)" >nul 2>nul
        if !ERRORLEVEL! equ 0 set "PYW_EXE=pythonw"
    )
)

:: Проверка зависимостей интерфейса (customtkinter, pillow и т.д.)
"!PY_EXE!" -c "import customtkinter, PIL, pywinstyles, httpx, webview" >nul 2>nul
if !ERRORLEVEL! neq 0 (
    echo [*] Первый запуск: установка необходимых библиотек GUI...
    "!PY_EXE!" -m pip install -r "%~dp0requirements.txt"
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [!] Не удалось автоматически установить библиотеки через pip.
        echo     Попробуйте вручную: "!PY_EXE!" -m pip install -r "%~dp0requirements.txt"
        echo.
        pause
        exit /b 1
    )
)

:: Запуск Antigravity Hub
if defined PYW_EXE (
    start "" "!PYW_EXE!" "%~dp0antigravity_manager.pyw"
) else (
    start "" "!PY_EXE!" "%~dp0antigravity_manager.pyw"
)
exit /b 0
