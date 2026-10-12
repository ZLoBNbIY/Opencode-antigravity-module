# OpenCode Antigravity Module Installer
param(
    [switch]$NoShortcut,
    [switch]$SkipPython,
    [switch]$SkipPatch
)

$CreateShortcut = -not $NoShortcut

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
    param([string]$Text)
    Write-Host "`n[*] $Text" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host "  [✓] $Text" -ForegroundColor Green
}

function Write-Info {
    param([string]$Text)
    Write-Host "  [i] $Text" -ForegroundColor Gray
}

function Write-WarningMsg {
    param([string]$Text)
    Write-Host "  [!] $Text" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host "  [x] $Text" -ForegroundColor Red
}

Clear-Host
Write-Host "================================================================" -ForegroundColor DarkCyan
Write-Host "   ⚡ OpenCode Antigravity Module — Установщик (PowerShell)   " -ForegroundColor Cyan -BackgroundColor Black
Write-Host "================================================================" -ForegroundColor DarkCyan
Write-Host "  Интеграция Google Antigravity & OpenAI / ChatGPT для OpenCode" -ForegroundColor Gray

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptDir) {
    $ScriptDir = (Get-Location).Path
}

# --- 0. Проверка наличия локальных файлов / Автозагрузка при irm | iex ---
$RepoUrl = "https://github.com/ZLoBNbIY/Opencode-antigravity-module.git"
$ZipUrl  = "https://github.com/ZLoBNbIY/Opencode-antigravity-module/archive/refs/heads/main.zip"

$HasLocalRepo = (Test-Path -LiteralPath (Join-Path $ScriptDir "gui-manager\antigravity_manager.pyw")) -and 
                (Test-Path -LiteralPath (Join-Path $ScriptDir "scripts\patch_plugin.mjs"))

if (-not $HasLocalRepo) {
    Write-Step "Запуск через онлайн-команду (irm | iex). Загрузка файлов модуля..."
    $TargetDir = Join-Path $HOME "Opencode-antigravity-module"
    
    if (-not (Test-Path -LiteralPath $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) {
        Write-Info "Клонирование репозитория через git в $TargetDir..."
        if (Test-Path -LiteralPath (Join-Path $TargetDir ".git")) {
            & git -C "$TargetDir" pull --quiet
        } else {
            & git clone --quiet "$RepoUrl" "$TargetDir"
        }
    } else {
        Write-Info "Git не обнаружен. Загрузка архива репозитория с GitHub..."
        $tempZip = Join-Path $env:TEMP "Opencode-antigravity-module-main.zip"
        $tempExtract = Join-Path $env:TEMP "Opencode-antigravity-module-extract"
        
        try {
            Invoke-RestMethod -Uri $ZipUrl -OutFile $tempZip
            if (Test-Path -LiteralPath $tempExtract) { Remove-Item -LiteralPath $tempExtract -Recurse -Force }
            Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
            
            $sourceDir = Join-Path $tempExtract "Opencode-antigravity-module-main"
            if (Test-Path -LiteralPath $sourceDir) {
                Copy-Item -Path "$sourceDir\*" -Destination $TargetDir -Recurse -Force
            }
            Remove-Item -LiteralPath $tempZip -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Write-ErrorMsg "Не удалось загрузить файлы репозитория: $_"
            return
        }
    }

    $ScriptDir = $TargetDir
    Write-Success "Файлы репозитория загружены в: $ScriptDir"
}

# --- 1. Поиск Node.js ---
Write-Step "Проверка окружения Node.js..."

$NodePath = $null
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $NodePath = $nodeCmd.Source
} else {
    $Candidates = @(
        "C:\Program Files\nodejs\node.exe",
        "C:\Program Files (x86)\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\cursor\resources\app\resources\helpers\node.exe",
        "$env:LOCALAPPDATA\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\Lib\site-packages\playwright\driver\node.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\Lib\site-packages\playwright\driver\node.exe",
        "$env:LOCALAPPDATA\OpenAI\Codex\bin\node.exe",
        "$env:LOCALAPPDATA\ms-playwright-go\1.57.0\node.exe"
    )
    foreach ($cand in $Candidates) {
        if (Test-Path -LiteralPath $cand) {
            $NodePath = $cand
            break
        }
    }
}

if (-not $NodePath) {
    Write-WarningMsg "Node.js не найден в системе. Выполняем автоматическую установку Node.js LTS..."
    $installedOk = $false
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Info "Попытка тихой установки Node.js LTS через winget..."
        try {
            & winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements --silent
            if (Test-Path "C:\Program Files\nodejs\node.exe") {
                $NodePath = "C:\Program Files\nodejs\node.exe"
                $installedOk = $true
            }
        } catch {
            Write-Info "Winget завершился с ошибкой, переходим к установщику MSI..."
        }
    }

    if (-not $installedOk) {
        Write-Info "Загрузка официального MSI-установщика Node.js LTS с nodejs.org..."
        $msiUrl = "https://nodejs.org/dist/v24.20.0/node-v24.20.0-x64.msi"
        $tempMsi = Join-Path $env:TEMP "node-v24.20.0-x64.msi"
        try {
            Invoke-WebRequest -Uri $msiUrl -OutFile $tempMsi -UseBasicParsing
            Write-Info "Установка Node.js в тихом режиме..."
            $msiProc = Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" /qn /norestart" -Wait -PassThru
            Remove-Item -LiteralPath $tempMsi -Force -ErrorAction SilentlyContinue
            if (Test-Path "C:\Program Files\nodejs\node.exe") {
                $NodePath = "C:\Program Files\nodejs\node.exe"
                $installedOk = $true
            }
        } catch {
            Write-WarningMsg "Ошибка при установке Node.js через MSI: $_"
        }
    }

    # Обновление PATH в текущей сессии
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $NodePath -and (Test-Path "C:\Program Files\nodejs\node.exe")) {
        $NodePath = "C:\Program Files\nodejs\node.exe"
    }
}

if ($NodePath) {
    $nodeVer = & "$NodePath" -v 2>$null
    Write-Success "Node.js готов к работе: $NodePath ($nodeVer)"
} else {
    Write-ErrorMsg "Node.js не найден и не удалось установить автоматически. Установите Node.js с https://nodejs.org"
}

# --- 2. Поиск Python ---
Write-Step "Проверка окружения Python..."
$PythonPath = $null
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $PythonPath = $pythonCmd.Source
} else {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) { $PythonPath = $pyCmd.Source }
}

if ($PythonPath) {
    $pyVer = & "$PythonPath" --version 2>&1
    Write-Success "Python обнаружен: $PythonPath ($pyVer)"
} else {
    Write-Info "Python не найден. GUI менеджер можно будет запустить после установки Python."
}

# --- 3. Подготовка каталогов ---
Write-Step "Настройка каталогов конфигурации OpenCode..."

$ConfigDir = Join-Path $HOME ".config\opencode"
$DataDir = Join-Path $HOME ".local\share\opencode"

if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    Write-Success "Создан каталог конфигурации: $ConfigDir"
} else {
    Write-Info "Каталог конфигурации уже существует: $ConfigDir"
}

if (-not (Test-Path -LiteralPath $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    Write-Success "Создан рабочий каталог: $DataDir"
}

# --- 4. Конфигурация opencode.json ---
Write-Step "Настройка opencode.json..."
$OpencodeConfigFile = Join-Path $ConfigDir "opencode.json"
$PluginPackageName = "@cortexkit/opencode-antigravity-auth@latest"

if (Test-Path -LiteralPath $OpencodeConfigFile) {
    try {
        $raw = Get-Content -LiteralPath $OpencodeConfigFile -Raw -Encoding UTF8
        $cfg = $raw | ConvertFrom-Json
        $modified = $false

        if (-not $cfg.plugin) {
            $cfg | Add-Member -MemberType NoteProperty -Name "plugin" -Value @($PluginPackageName)
            $modified = $true
        } elseif (-not ($cfg.plugin -contains $PluginPackageName)) {
            $cfg.plugin += $PluginPackageName
            $modified = $true
        }

        if (-not $cfg.provider) {
            $cfg | Add-Member -MemberType NoteProperty -Name "provider" -Value ([PSCustomObject]@{})
            $modified = $true
        }
        if (-not $cfg.provider.google) {
            $cfg.provider | Add-Member -MemberType NoteProperty -Name "google" -Value ([PSCustomObject]@{
                options = [PSCustomObject]@{ apiKey = "antigravity" }
            })
            $modified = $true
        }

        if ($modified) {
            $cfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OpencodeConfigFile -Encoding UTF8
            Write-Success "Плагин Antigravity добавлен в существующий opencode.json"
        } else {
            Write-Info "opencode.json уже содержит корректную конфигурацию Antigravity"
        }
    } catch {
        Write-WarningMsg "Не удалось распарсить существующий opencode.json. Создаем резервную копию..."
        Copy-Item -LiteralPath $OpencodeConfigFile -Destination "$OpencodeConfigFile.bak" -Force
        Copy-Item -LiteralPath "$ScriptDir\config-templates\opencode.json" -Destination $OpencodeConfigFile -Force
        Write-Success "Шаблон opencode.json успешно установлен"
    }
} else {
    Copy-Item -LiteralPath "$ScriptDir\config-templates\opencode.json" -Destination $OpencodeConfigFile -Force
    Write-Success "Создан файл opencode.json"
}

# --- 5. Конфигурация antigravity.json ---
Write-Step "Настройка antigravity.json..."
$AntigravityConfigFile = Join-Path $ConfigDir "antigravity.json"

if (Test-Path -LiteralPath $AntigravityConfigFile) {
    try {
        $raw = Get-Content -LiteralPath $AntigravityConfigFile -Raw -Encoding UTF8
        $agCfg = $raw | ConvertFrom-Json
        $agMod = $false

        if ($agCfg.soft_quota_threshold_percent -ne 100) {
            $agCfg.soft_quota_threshold_percent = 100
            $agMod = $true
        }
        if (-not $agCfg.account_selection_strategy) {
            $agCfg.account_selection_strategy = "hybrid"
            $agMod = $true
        }
        if ($agCfg.switch_on_first_rate_limit -ne $true) {
            $agCfg.switch_on_first_rate_limit = $true
            $agMod = $true
        }

        if ($agMod) {
            $agCfg | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $AntigravityConfigFile -Encoding UTF8
            Write-Success "Параметр soft_quota_threshold_percent установлен на 100% (защита от ошибок 412)"
        } else {
            Write-Info "antigravity.json уже оптимально настроен"
        }
    } catch {
        Copy-Item -LiteralPath "$ScriptDir\config-templates\antigravity.json" -Destination $AntigravityConfigFile -Force
        Write-Success "Создан файл antigravity.json"
    }
} else {
    Copy-Item -LiteralPath "$ScriptDir\config-templates\antigravity.json" -Destination $AntigravityConfigFile -Force
    Write-Success "Создан файл antigravity.json с оптимальными параметрами"
}

# --- 6. Применение патчей стриминга (Gemini 3.8 / SSE) ---
if (-not $SkipPatch -and $NodePath) {
    Write-Step "Применение патчей совместимости (Gemini 3.8 / SSE / TTY)..."
    $PatchScript = Join-Path $ScriptDir "scripts\patch_plugin.mjs"
    if (Test-Path -LiteralPath $PatchScript) {
        $res = & "$NodePath" "$PatchScript"
        Write-Success "Патчи стриминга и совместимости успешно применены!"
    } else {
        Write-WarningMsg "Скрипт patch_plugin.mjs не найден по пути: $PatchScript"
    }
} elseif ($SkipPatch) {
    Write-Info "Пропуск накатывания патчей (-SkipPatch)."
}

# --- 7. Установка зависимостей Python GUI ---
if (-not $SkipPython -and $PythonPath) {
    Write-Step "Проверка и установка зависимостей GUI-менеджера (Python)..."
    $ReqFile = Join-Path $ScriptDir "gui-manager\requirements.txt"
    if (Test-Path -LiteralPath $ReqFile) {
        & "$PythonPath" -m pip install -r "$ReqFile" --quiet
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Библиотеки CustomTkinter успешно установлены!"
        } else {
            Write-WarningMsg "Предупреждение при установке pip-зависимостей."
        }
    }
}

# --- 8. Создание ярлыка на Рабочем столе ---
if ($CreateShortcut) {
    Write-Step "Создание ярлыка на Рабочем столе..."
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $DesktopPath = [System.Environment]::GetFolderPath('Desktop')
        $ShortcutPath = Join-Path $DesktopPath "Antigravity Hub.lnk"
        $TargetBat = Join-Path $ScriptDir "Запуск_Менеджера.bat"
        $IconPath = Join-Path $ScriptDir "gui-manager\icon.ico"

        if (-not (Test-Path -LiteralPath $TargetBat)) {
            $TargetBat = Join-Path $ScriptDir "gui-manager\start_manager.bat"
        }

        if (Test-Path -LiteralPath $TargetBat) {
            $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
            $Shortcut.TargetPath = $TargetBat
            $Shortcut.WorkingDirectory = $ScriptDir
            $Shortcut.Description = "Менеджер аккаунтов и квот Google Antigravity & OpenAI ChatGPT для OpenCode"
            if (Test-Path -LiteralPath $IconPath) {
                $Shortcut.IconLocation = "$IconPath,0"
            }
            $Shortcut.Save()
            Write-Success "Ярлык 'Antigravity Hub' создан на Рабочем столе с фирменной иконкой!"
        }
    } catch {
        Write-Info "Не удалось автоматически создать ярлык (некритично)."
    }
}

# --- 9. Финальное резюме ---
Write-Host "`n================================================================" -ForegroundColor DarkGreen
Write-Host "              🎉 Установка успешно завершена!                  " -ForegroundColor Green -BackgroundColor Black
Write-Host "================================================================" -ForegroundColor DarkGreen

Write-Host "`nКак использовать модуль:" -ForegroundColor White
Write-Host "  1. Запустите GUI-менеджер:" -ForegroundColor Cyan
Write-Host "     • Через ярлык на Рабочем столе 'Antigravity Hub'" -ForegroundColor Gray
Write-Host "     • Или файлом: Запуск_Менеджера.bat" -ForegroundColor Gray
Write-Host "  2. Подключите аккаунты:" -ForegroundColor Cyan
Write-Host "     • Google (Antigravity): вкладка 'Google' -> '+ Добавить аккаунт Google'" -ForegroundColor Gray
Write-Host "     • OpenAI (ChatGPT):     вкладка 'OpenAI' -> '+ Добавить аккаунт OpenAI'" -ForegroundColor Gray
Write-Host "  3. Откройте OpenCode и выберите любую модель (Gemini 3.8 Flash, Gemini 3.7 Pro, Claude или GPT)!" -ForegroundColor Cyan
Write-Host "`n"
