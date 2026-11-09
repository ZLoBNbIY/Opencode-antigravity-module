[CmdletBinding()]
param([switch]$Yes)

$ErrorActionPreference = 'Continue'

function Remove-IfExists {
    param([string]$Path, [switch]$Recurse)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return }
    try {
        if ($Recurse) {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        } else {
            Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        }
        Write-Host "  Удалено: $Path" -ForegroundColor DarkGray
    } catch {
        Write-Warning "Не удалось удалить '$Path': $_"
    }
}

function Remove-JsonProperty {
    param($Object, [string]$Name)
    if ($Object -and $Object.PSObject.Properties[$Name]) {
        $Object.PSObject.Properties.Remove($Name)
    }
}

# Resolve user data from the environment, never from the current directory.
$homeDir = [Environment]::GetFolderPath('UserProfile')
if (-not $homeDir) { $homeDir = $HOME }
$configDir = if ($env:OPENCODE_CONFIG_DIR) {
    [Environment]::ExpandEnvironmentVariables($env:OPENCODE_CONFIG_DIR)
} else {
    Join-Path $homeDir '.config\opencode'
}
$hubDataDir = Join-Path $homeDir '.local\share\antigravity-hub'
$localHubDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'AntigravityHub' } else { $null }
$installedDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs\Antigravity Hub' } else { $null }
$cacheRoot = Join-Path $homeDir '.cache\opencode'

Write-Host ''
Write-Host 'Удаление Antigravity Hub и его данных' -ForegroundColor Cyan
Write-Host "Будут удалены настройки и аккаунты Hub, его gateway/кэш и интеграция Hub в OpenCode."
Write-Host 'OpenCode, история чатов, другие плагины и отдельно установленные Python/Node.js останутся.'
Write-Host "Каталог OpenCode: $configDir"
if (-not $Yes) {
    $answer = Read-Host 'Это действие необратимо. Для продолжения введите DELETE'
    if ($answer -cne 'DELETE') { Write-Host 'Отменено.'; exit 0 }
}

# Stop only Hub-owned processes; don't terminate all Python, Node, Xray or OpenCode processes.
try {
    $hubProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match '(?i)antigravity_manager\.pyw' -or
            ($localHubDir -and $_.CommandLine.IndexOf($localHubDir, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
            ($localHubDir -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($localHubDir, [StringComparison]::OrdinalIgnoreCase))
        )
    })
    foreach ($process in $hubProcesses) {
        try { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop } catch { }
    }
} catch { Write-Warning "Не удалось полностью остановить Hub: $_" }

# Remove just the Hub plugin and Hub-owned model/provider selections from OpenCode config.
$opencodeConfig = Join-Path $configDir 'opencode.json'
if (Test-Path -LiteralPath $opencodeConfig) {
    try {
        $cfg = Get-Content -LiteralPath $opencodeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.plugin -is [array]) {
            $cfg.plugin = @($cfg.plugin | Where-Object { $_ -notmatch '^(@cortexkit/opencode-antigravity-auth|opencode-antigravity-multi-auth)(?:@|$)' })
            if ($cfg.plugin.Count -eq 0) { Remove-JsonProperty $cfg 'plugin' }
        } elseif ($cfg.plugin -is [string] -and $cfg.plugin -match '^(@cortexkit/opencode-antigravity-auth|opencode-antigravity-multi-auth)(?:@|$)') {
            Remove-JsonProperty $cfg 'plugin'
        }

        if ($cfg.provider) {
            $google = $cfg.provider.google
            if ($google -and $google.options -and $google.options.apiKey -eq 'antigravity') {
                Remove-JsonProperty $google.options 'apiKey'
                if ($google.options.PSObject.Properties.Count -eq 0) { Remove-JsonProperty $cfg.provider 'google' }
            }
            foreach ($providerName in @('museai', 'xpiki', 'openrouter-free', 'deepseek-web', 'mwapi')) {
                $provider = $cfg.provider.$providerName
                if ($provider -and ($provider.name -match '(?i)Antigravity Hub' -or $providerName -eq 'museai')) {
                    Remove-JsonProperty $cfg.provider $providerName
                }
            }
            if ($cfg.provider.PSObject.Properties.Count -eq 0) { Remove-JsonProperty $cfg 'provider' }
        }

        foreach ($property in @('model', 'small_model')) {
            if ($cfg.$property -is [string] -and $cfg.$property -match '^(google/antigravity-|opencode-antigravity)') {
                Remove-JsonProperty $cfg $property
            }
        }
        foreach ($sectionName in @('agent', 'agents')) {
            $section = $cfg.$sectionName
            if ($section -and $section.title -and $section.title.model -eq 'opencode/big-pickle') {
                Remove-JsonProperty $section.title 'model'
                if ($section.title.PSObject.Properties.Count -eq 0) { Remove-JsonProperty $section 'title' }
                if ($section.PSObject.Properties.Count -eq 0) { Remove-JsonProperty $cfg $sectionName }
            }
        }
        $json = $cfg | ConvertTo-Json -Depth 100
        [System.IO.File]::WriteAllText($opencodeConfig, $json, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host 'Удалены настройки Hub из opencode.json.' -ForegroundColor Green
    } catch {
        Write-Warning "Не удалось безопасно обновить opencode.json; файл оставлен без изменений: $_"
    }
}

# Delete Hub-specific account/config files, including generation-store directories.
$storePointer = Join-Path $configDir 'antigravity-accounts.json.store.pointer.json'
if (Test-Path -LiteralPath $storePointer) {
    try {
        $pointerData = Get-Content -LiteralPath $storePointer -Raw -Encoding UTF8 | ConvertFrom-Json
        $storeName = [string]$pointerData.directoryBasename
        if ($storeName -match '^antigravity-accounts\.json\.store\..+\.generation$') {
            Remove-IfExists (Join-Path $configDir $storeName) -Recurse
        }
    } catch { Write-Warning "Не удалось прочитать указатель хранилища аккаунтов; удаляются только стандартные каталоги: $_" }
}
foreach ($fileName in @(
    'antigravity.json', 'antigravity-accounts.json', 'antigravity-accounts.json.bak',
    'antigravity-accounts.json.store.pointer.json',
    'openai-accounts.json', 'claude-accounts.json', 'xpiki.json', 'gemini_domains.json'
)) {
    Remove-IfExists (Join-Path $configDir $fileName)
}
foreach ($pattern in @('antigravity-accounts.json.store.*', 'antigravity-accounts.json.store.*.generation')) {
    if (Test-Path -LiteralPath $configDir) {
        Get-ChildItem -LiteralPath $configDir -Filter $pattern -Force -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-IfExists $_.FullName -Recurse
        }
    }
}
Remove-IfExists (Join-Path $configDir 'vless') -Recurse
Remove-IfExists (Join-Path $configDir 'claude_profile') -Recurse
foreach ($binary in @('xray.exe', 'sing-box.exe', 'xray', 'sing-box', 'core_archive.zip')) {
    Remove-IfExists (Join-Path (Join-Path $configDir 'bin') $binary)
}

# Hub secrets, local web sessions, bundled Muse gateway and its browser profile.
Remove-IfExists $hubDataDir -Recurse
Remove-IfExists $localHubDir -Recurse

# Remove only this plugin's cached package directories; preserve OpenCode's other cache entries.
foreach ($path in @(
    (Join-Path $cacheRoot 'npm\node_modules\@cortexkit\opencode-antigravity-auth'),
    (Join-Path $cacheRoot 'npm\node_modules\opencode-antigravity-multi-auth'),
    (Join-Path $cacheRoot 'packages\@cortexkit\opencode-antigravity-auth@latest'),
    (Join-Path $cacheRoot 'packages\opencode-antigravity-multi-auth@latest')
)) { Remove-IfExists $path -Recurse }

# Hub logs only.
foreach ($logDir in @((Join-Path $configDir 'logs'), (Join-Path $homeDir '.local\share\opencode\log'))) {
    if (Test-Path -LiteralPath $logDir) {
        Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(?i)antigravity|museai|hub' } |
            ForEach-Object { Remove-IfExists $_.FullName }
    }
}

# Remove the sentinel only if the Hub installer created it; preserve a real user API key.
try {
    if ([Environment]::GetEnvironmentVariable('GOOGLE_GENERATIVE_AI_API_KEY', 'User') -ceq 'antigravity') {
        [Environment]::SetEnvironmentVariable('GOOGLE_GENERATIVE_AI_API_KEY', $null, 'User')
        Write-Host 'Удалён служебный маркер Google, установленный Hub.' -ForegroundColor Green
    }
} catch { Write-Warning "Не удалось удалить переменную среды Google: $_" }

# Hub may have synchronized its ChatGPT OAuth credential into OpenCode's auth store.
# Remove only the OpenAI entry and keep credentials for every other provider.
foreach ($authFile in @(
    (Join-Path $homeDir '.local\share\opencode\auth.json'),
    (Join-Path $homeDir '.opencode\auth.json')
)) {
    if (Test-Path -LiteralPath $authFile) {
        try {
            $auth = Get-Content -LiteralPath $authFile -Raw -Encoding UTF8 | ConvertFrom-Json
            Remove-JsonProperty $auth 'openai'
            [System.IO.File]::WriteAllText($authFile, ($auth | ConvertTo-Json -Depth 50), (New-Object System.Text.UTF8Encoding($false)))
            Write-Host 'Удалена OAuth-запись OpenAI Hub из auth.json.' -ForegroundColor Green
        } catch { Write-Warning "Не удалось безопасно обновить auth.json; файл сохранён: $_" }
    }
}

# OpenCode Desktop 2.x can keep a provider credential in its local database.
# Use its supported logout command when the CLI is installed; never delete the DB.
$opencodeCliCandidates = @()
if ($env:LOCALAPPDATA) {
    $opencodeCliCandidates += (Join-Path $env:LOCALAPPDATA 'Programs\ai.opencode.desktop\resources\opencode-cli.exe')
}
$roamingCliDir = Join-Path $homeDir 'AppData\Roaming\ai.opencode.desktop\cli'
if (Test-Path -LiteralPath $roamingCliDir) {
    $opencodeCliCandidates += @(Get-ChildItem -LiteralPath $roamingCliDir -Filter 'opencode-cli.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
}
$opencodeCli = $opencodeCliCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($opencodeCli) {
    try {
        $logout = Start-Process -FilePath $opencodeCli -ArgumentList @('auth', 'logout', 'openai') -Wait -PassThru -WindowStyle Hidden
        if ($logout.ExitCode -eq 0) { Write-Host 'OpenAI-учётные данные удалены из OpenCode.' -ForegroundColor Green }
    } catch { Write-Warning "Не удалось выполнить OpenCode logout для OpenAI: $_" }
}

# Remove Windows registration and the Hub desktop shortcut only.
Remove-IfExists 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AntigravityHub' -Recurse
$desktop = [Environment]::GetFolderPath('Desktop')
Remove-IfExists (Join-Path $desktop 'Antigravity Hub.lnk')

# If launched from the installed copy, let this process finish before deleting its directory.
$currentScript = $PSCommandPath
if ($installedDir -and $currentScript -and $currentScript.StartsWith($installedDir, [StringComparison]::OrdinalIgnoreCase)) {
    $escapedDir = $installedDir.Replace("'", "''")
    $cleanup = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$escapedDir' -Recurse -Force -ErrorAction SilentlyContinue"
    try {
        Start-Process -FilePath (Get-Command powershell.exe).Source -WindowStyle Hidden `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cleanup) | Out-Null
    } catch { Write-Warning "Не удалось запланировать удаление каталога деинсталлятора: $_" }
}

Write-Host ''
Write-Host 'Готово. Перезапустите OpenCode.' -ForegroundColor Green
Write-Host 'OpenCode, чаты, остальные плагины и системные Python/Node.js не удалялись.'
