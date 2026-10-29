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

$ScriptDir = $null
if ($PSScriptRoot) {
    $ScriptDir = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# --- 0. Проверка наличия локальных файлов / Автозагрузка при irm | iex ---
$RepoUrl = "https://github.com/ZLoBNbIY/Opencode-antigravity-module.git"
$ZipUrl  = "https://github.com/ZLoBNbIY/Opencode-antigravity-module/archive/refs/heads/V2.zip"

$HasLocalRepo = $false
if ($ScriptDir) {
    $HasLocalRepo = (Test-Path -LiteralPath (Join-Path $ScriptDir "gui-manager\antigravity_manager.pyw")) -and 
                    (Test-Path -LiteralPath (Join-Path $ScriptDir "scripts\patch_plugin.mjs"))
}

if (-not $HasLocalRepo) {
    Write-Step "Запуск через онлайн-команду (irm | iex). Загрузка файлов модуля..."
    $TargetDir = Join-Path $HOME "Opencode-antigravity-module"
    
    if (-not (Test-Path -LiteralPath $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) {
        Write-Info "Клонирование/обновление репозитория через git (ветка V2) в $TargetDir..."
        if (Test-Path -LiteralPath (Join-Path $TargetDir ".git")) {
            & git -C "$TargetDir" fetch origin V2 --quiet
            & git -C "$TargetDir" reset --hard origin/V2 --quiet
            & git -C "$TargetDir" clean -fd --quiet
        } else {
            & git clone --branch V2 --quiet "$RepoUrl" "$TargetDir"
        }
    } else {
        Write-Info "Git не обнаружен. Загрузка архива репозитория с GitHub (ветка V2)..."
        $tempZip = Join-Path $env:TEMP "Opencode-antigravity-module-V2.zip"
        $tempExtract = Join-Path $env:TEMP "Opencode-antigravity-module-extract"
        
        try {
            Invoke-RestMethod -Uri $ZipUrl -OutFile $tempZip
            if (Test-Path -LiteralPath $tempExtract) { Remove-Item -LiteralPath $tempExtract -Recurse -Force }
            Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
            
            $sourceDir = Join-Path $tempExtract "Opencode-antigravity-module-V2"
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
$MinimumNodeVersion = [version]"20.0.0"

function Get-NodeVersion {
    param([string]$Executable)
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable)) { return $null }
    try {
        $raw = (& $Executable -v 2>$null | Select-Object -First 1) -replace '^v', ''
        return [version]$raw
    } catch {
        return $null
    }
}

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

if (-not $NodePath -or (Get-NodeVersion $NodePath) -lt $MinimumNodeVersion) {
    $currentNodeVersion = Get-NodeVersion $NodePath
    if ($currentNodeVersion) {
        Write-WarningMsg "Найдена Node.js $currentNodeVersion, требуется $MinimumNodeVersion или новее. Попытка обновления до LTS..."
    } else {
        Write-WarningMsg "Node.js не найден. Запуск автоматической установки Node.js LTS..."
    }
    $installedOk = $false
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Info "Попытка установить/обновить Node.js LTS через winget..."
        try {
            if ($currentNodeVersion) {
                & winget upgrade --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements --silent
            } else {
                & winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements --silent
            }
            if (Test-Path "C:\Program Files\nodejs\node.exe") {
                $NodePath = "C:\Program Files\nodejs\node.exe"
                $installedOk = (Get-NodeVersion $NodePath) -ge $MinimumNodeVersion
            }
        } catch {
            Write-Info "Winget завершился с ошибкой, переходим к установщику MSI..."
        }
    }

    if (-not $installedOk) {
        Write-Info "Загрузка официального MSI-установщика Node.js LTS с nodejs.org..."
        $nodeLtsVersion = "24.20.0"
        $msiUrl = "https://nodejs.org/dist/v$nodeLtsVersion/node-v$nodeLtsVersion-x64.msi"
        $tempMsi = Join-Path $env:TEMP "node-v$nodeLtsVersion-x64.msi"
        try {
            Invoke-WebRequest -Uri $msiUrl -OutFile $tempMsi -UseBasicParsing
            Write-Info "Установка Node.js в тихом режиме..."
            $msiProc = Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" /qn /norestart" -Wait -PassThru
            Remove-Item -LiteralPath $tempMsi -Force -ErrorAction SilentlyContinue
            if (Test-Path "C:\Program Files\nodejs\node.exe") {
                $NodePath = "C:\Program Files\nodejs\node.exe"
                $installedOk = (Get-NodeVersion $NodePath) -ge $MinimumNodeVersion
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
    $nodeVer = Get-NodeVersion $NodePath
    if ($nodeVer -ge $MinimumNodeVersion) {
        Write-Success "Node.js готов к работе: $NodePath (v$nodeVer)"
    } else {
        Write-WarningMsg "Не удалось обновить Node.js до $MinimumNodeVersion. Установите Node.js 20 LTS или новее с https://nodejs.org; патчи плагина могут не примениться."
        $NodePath = $null
    }
} else {
    Write-WarningMsg "Node.js $MinimumNodeVersion или новее не найден и не удалось установить автоматически. Установите Node.js 20 LTS или новее с https://nodejs.org; патчи плагина будут пропущены."
}

function Get-PythonEnvironment {
    $candidates = [System.Collections.Generic.List[string]]::new()

    # 1. py launcher (если установлен, он обычно в C:\Windows\py.exe)
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $pyPath = (& $pyCmd.Source -3 -c "import sys; print(sys.executable)" 2>$null | Out-String).Trim()
            if ($pyPath -and (Test-Path -LiteralPath $pyPath)) {
                $candidates.Add($pyPath)
            }
        } catch {}
    }

    # 2. PATH команды (python, python3)
    foreach ($cmdName in @("python", "python3")) {
        $found = Get-Command $cmdName -All -ErrorAction SilentlyContinue
        if ($found) {
            foreach ($item in $found) {
                if ($item.Source) { $candidates.Add($item.Source) }
            }
        }
    }

    # 3. Стандартные пути установки Python в Windows (если не был добавлен в PATH)
    $commonPatterns = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "C:\Program Files\Python3*\python.exe",
        "C:\Program Files (x86)\Python3*\python.exe",
        "C:\Python3*\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe"
    )
    foreach ($pattern in $commonPatterns) {
        try {
            $expanded = $ExecutionContext.InvokeCommand.ExpandString($pattern)
            $resolved = Get-ChildItem -Path $expanded -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
            if ($resolved) {
                foreach ($res in $resolved) { $candidates.Add($res) }
            }
        } catch {}
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($cand in $candidates) {
        if (-not $cand -or $seen.Contains($cand)) { continue }
        $seen.Add($cand) | Out-Null
        if (-not (Test-Path -LiteralPath $cand)) { continue }

        try {
            $prevEA = $ErrorActionPreference
            $ErrorActionPreference = 'SilentlyContinue'
            $verOutput = (& "$cand" --version 2>&1 | Out-String).Trim()
            $code = $LASTEXITCODE
            $ErrorActionPreference = $prevEA

            # Проверяем, что процесс завершился успешно (код 0) и вернул 'Python 3.x'
            # (Заглушка WindowsApps завершается с кодом 9009 и сообщением 'Python was not found...')
            if ($code -eq 0 -and $verOutput -match '^Python\s+([0-9]+\.[0-9]+(\.[0-9]+)?)') {
                $verString = $Matches[1]
                # Дополнительная проверка запуска Python-кода
                $testCode = (& "$cand" -c "import sys; print(sys.version_info[0])" 2>&1 | Out-String).Trim()
                if ($LASTEXITCODE -eq 0 -and $testCode -eq "3") {
                    return [PSCustomObject]@{
                        Path       = $cand
                        Version    = $verString
                        FullOutput = $verOutput
                    }
                }
            }
        } catch {
            continue
        }
    }

    return $null
}

# --- 2. Поиск Python ---
Write-Step "Проверка окружения Python..."
$PythonEnv = Get-PythonEnvironment
$PythonPath = $null

if ($PythonEnv) {
    $PythonPath = $PythonEnv.Path
    Write-Success "Python обнаружен: $PythonPath ($($PythonEnv.FullOutput))"

    # Если найденный python не в системном PATH, добавим его директорию в текущую сессию
    $pyDir = Split-Path -Parent $PythonPath
    $pyScripts = Join-Path $pyDir "Scripts"
    if ($env:Path -notlike "*$pyDir*") {
        $env:Path = "$pyDir;$pyScripts;" + $env:Path
        Write-Info "Каталог Python временно добавлен в PATH текущей сессии: $pyDir"
    }
} else {
    # Проверяем, был ли ложный след от заглушки WindowsApps
    $hasStub = $false
    $stubPath = $null
    $stubCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($stubCmd -and $stubCmd.Source -like "*\Microsoft\WindowsApps\python*.exe") {
        $hasStub = $true
        $stubPath = $stubCmd.Source
    }

    Write-ErrorMsg "Ошибка: Рабочий интерпретатор Python 3 не обнаружен!"
    if ($hasStub) {
        Write-WarningMsg "Внимание: Обнаружен плейсхолдер Windows ($stubPath), но сам Python НЕ установлен!"
    }

    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor DarkRed
    Write-Host "  [!] ОШИБКА ОКРУЖЕНИЯ: ДЛЯ РАБОТЫ ХАБА (GUI) НЕОБХОДИМ PYTHON 3" -ForegroundColor Red
    Write-Host "  ================================================================" -ForegroundColor DarkRed
    Write-Host "  Графический менеджер (Antigravity Hub) не сможет запуститься без Python." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Рекомендации по установке:" -ForegroundColor White
    Write-Host "    1. Установите Python 3 (рекомендуется 3.10, 3.11 или 3.12):" -ForegroundColor White
    Write-Host "       • Скачайте установщик: https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "       • Или выполните в терминале: winget install Python.Python.3.12" -ForegroundColor Cyan
    Write-Host "    2. ВАЖНО при установке через установщик Windows (.exe):" -ForegroundColor Yellow
    Write-Host "       • На первом же экране установщика ОБЯЗАТЕЛЬНО отметьте галочку:" -ForegroundColor White
    Write-Host "         [✓] 'Add python.exe to PATH' ('Добавить Python в PATH')" -ForegroundColor Green
    Write-Host "    3. Если Python уже установлен на ПК, но не найден:" -ForegroundColor White
    Write-Host "       • Добавьте путь к папке Python в системную переменную PATH," -ForegroundColor White
    Write-Host "       • или отключите системную заглушку в Windows:" -ForegroundColor White
    Write-Host "         Параметры -> Приложения -> Дополнительные параметры -> Псевдонимы приложений" -ForegroundColor White
    Write-Host "    4. После установки Python запустите этот установщик снова или файл 'Запуск_Менеджера.bat'." -ForegroundColor White
    Write-Host "  ================================================================`n" -ForegroundColor DarkRed
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

        if (-not $cfg.model -or $cfg.model -like "opencode/*") {
            $cfg | Add-Member -MemberType NoteProperty -Name "model" -Value "google/antigravity-gemini-3.8-flash" -Force
            $modified = $true
        }

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

        # Бесплатная встроенная модель OpenCode для именования сессий (защита от устаревшего Gemini 3.5 Flash)
        if (-not $cfg.small_model -or $cfg.small_model -like "*3.5*") {
            $cfg | Add-Member -MemberType NoteProperty -Name "small_model" -Value "opencode/big-pickle" -Force
            $modified = $true
        }
        if (-not $cfg.agent) {
            $cfg | Add-Member -MemberType NoteProperty -Name "agent" -Value ([PSCustomObject]@{
                title = [PSCustomObject]@{ model = "opencode/big-pickle" }
            }) -Force
            $modified = $true
        } elseif (-not $cfg.agent.title -or $cfg.agent.title.model -like "*3.5*") {
            if (-not $cfg.agent.title) {
                $cfg.agent | Add-Member -MemberType NoteProperty -Name "title" -Value ([PSCustomObject]@{
                    model = "opencode/big-pickle"
                }) -Force
            } else {
                $cfg.agent.title.model = "opencode/big-pickle"
            }
            $modified = $true
        }
        if (-not $cfg.agents) {
            $cfg | Add-Member -MemberType NoteProperty -Name "agents" -Value ([PSCustomObject]@{
                title = [PSCustomObject]@{ model = "opencode/big-pickle" }
            }) -Force
            $modified = $true
        } elseif (-not $cfg.agents.title -or $cfg.agents.title.model -like "*3.5*") {
            if (-not $cfg.agents.title) {
                $cfg.agents | Add-Member -MemberType NoteProperty -Name "title" -Value ([PSCustomObject]@{
                    model = "opencode/big-pickle"
                }) -Force
            } else {
                $cfg.agents.title.model = "opencode/big-pickle"
            }
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

# OpenCode 2 native Google SDK validates that an API-key value exists before
# the Antigravity GA http.request hook can rewrite the request to the OAuth
# bridge. This is a sentinel only; the Antigravity plugin supplies the actual
# Google OAuth credentials and the sentinel is never used as a Google API key.
$GoogleKeySentinel = "antigravity"
$ExistingGoogleKey = [Environment]::GetEnvironmentVariable("GOOGLE_GENERATIVE_AI_API_KEY", "User")
if ([string]::IsNullOrWhiteSpace($ExistingGoogleKey)) {
    [Environment]::SetEnvironmentVariable("GOOGLE_GENERATIVE_AI_API_KEY", $GoogleKeySentinel, "User")
    Write-Success "Настроен служебный маркер Google для OAuth-маршрутизации Antigravity (не API-ключ)"
} else {
    Write-Info "GOOGLE_GENERATIVE_AI_API_KEY уже задан; значение не изменено"
}
$env:GOOGLE_GENERATIVE_AI_API_KEY = [Environment]::GetEnvironmentVariable("GOOGLE_GENERATIVE_AI_API_KEY", "User")

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
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Патчи стриминга и совместимости успешно применены!"
        } else {
            Write-WarningMsg "Не удалось применить патчи совместимости (код $LASTEXITCODE). Установка продолжится, но часть исправлений плагина может быть недоступна."
        }
    } else {
        Write-WarningMsg "Скрипт patch_plugin.mjs не найден по пути: $PatchScript"
    }
} elseif ($SkipPatch) {
    Write-Info "Пропуск накатывания патчей (-SkipPatch)."
}

# --- 7. Установка зависимостей Python GUI ---
if (-not $SkipPython) {
    Write-Step "Проверка и установка зависимостей GUI-менеджера (Python)..."
    if ($PythonPath) {
        $ReqFile = Join-Path $ScriptDir "gui-manager\requirements.txt"
        if (Test-Path -LiteralPath $ReqFile) {
            Write-Info "Установка библиотек интерфейса из requirements.txt..."
            & "$PythonPath" -m pip install -r "$ReqFile" --quiet
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Пакеты CustomTkinter успешно установлены!"
            } else {
                Write-WarningMsg "Предупреждение при установке pip-зависимостей. Попробуйте выполнить вручную: & `"$PythonPath`" -m pip install -r `"$ReqFile`""
            }
        }
    } else {
        Write-ErrorMsg "Пропуск установки зависимостей GUI: Python 3 не обнаружен."
        Write-WarningMsg "Библиотеки интерфейса (customtkinter, pillow и др.) не установлены. Хаб не запустится без Python!"
    }
} else {
    Write-Info "Пропуск установки зависимостей Python (-SkipPython)."
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
if ($PythonPath) {
    Write-Host "`n================================================================" -ForegroundColor DarkGreen
    Write-Host "              🎉 Установка успешно завершена!                  " -ForegroundColor Green -BackgroundColor Black
    Write-Host "================================================================" -ForegroundColor DarkGreen
} else {
    Write-Host "`n================================================================" -ForegroundColor DarkYellow
    Write-Host "      ⚠️  Конфигурация завершена, но ТРЕБУЕТСЯ PYTHON!         " -ForegroundColor Yellow -BackgroundColor Black
    Write-Host "================================================================" -ForegroundColor DarkYellow
}

Write-Host "`nКак использовать модуль:" -ForegroundColor White
if ($PythonPath) {
    Write-Host "  1. Запустите GUI-менеджер:" -ForegroundColor Cyan
    Write-Host "     • Через ярлык на Рабочем столе 'Antigravity Hub'" -ForegroundColor Gray
    Write-Host "     • Или файлом: Запуск_Менеджера.bat" -ForegroundColor Gray
} else {
    Write-Host "  1. Запуск GUI-менеджера (Antigravity Hub):" -ForegroundColor Red
    Write-Host "     • [!] Сначала установите Python 3 с https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "           (с обязательной галочкой 'Add python.exe to PATH')!" -ForegroundColor Yellow
    Write-Host "     • После установки Python запустите ярлык 'Antigravity Hub' или 'Запуск_Менеджера.bat' —" -ForegroundColor Gray
    Write-Host "       скрипт автоматически установит зависимости интерфейса и откроет Хаб." -ForegroundColor Gray
}
Write-Host "  2. Подключите аккаунты:" -ForegroundColor Cyan
Write-Host "     • Google (Antigravity): вкладка 'Google' -> '+ Добавить аккаунт Google'" -ForegroundColor Gray
Write-Host "     • OpenAI (ChatGPT):     вкладка 'OpenAI' -> '+ Добавить аккаунт OpenAI'" -ForegroundColor Gray
Write-Host "  3. Откройте OpenCode и выберите любую модель (Gemini 3.8 Flash, Gemini 3.7 Pro, Claude или GPT)!" -ForegroundColor Cyan
Write-Host "`n"
