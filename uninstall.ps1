param([switch]$Yes)

$ErrorActionPreference = 'Continue'
$configDir = if ($env:OPENCODE_CONFIG_DIR) {
    [Environment]::ExpandEnvironmentVariables($env:OPENCODE_CONFIG_DIR)
} else {
    Join-Path $HOME '.config\opencode'
}
$hubDataDir = Join-Path $HOME '.local\share\antigravity-hub'

Write-Host 'OpenCode Antigravity Hub - complete removal' -ForegroundColor Cyan
Write-Host 'This removes Hub accounts/tokens, configuration, plugin cache, and integration settings.'
Write-Host 'OpenCode itself and its chats/history will not be removed.'
if (-not $Yes) {
    $answer = Read-Host 'This cannot be undone. Continue? Type DELETE'
    if ($answer -cne 'DELETE') { Write-Host 'Cancelled.'; exit 0 }
}

# Stop only the Hub manager, not unrelated Python processes.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'antigravity_manager\.pyw' } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { }
    }

# Remove only Hub-owned entries from OpenCode config; retain all other settings.
$opencodeConfig = Join-Path $configDir 'opencode.json'
if (Test-Path -LiteralPath $opencodeConfig) {
    try {
        $cfg = Get-Content -LiteralPath $opencodeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.plugin -is [array]) {
            $cfg.plugin = @($cfg.plugin | Where-Object { $_ -notmatch '^@cortexkit/opencode-antigravity-auth(?:@|$)' })
            if ($cfg.plugin.Count -eq 0) { $cfg.PSObject.Properties.Remove('plugin') }
        } elseif ($cfg.plugin -is [string] -and $cfg.plugin -match '^@cortexkit/opencode-antigravity-auth(?:@|$)') {
            $cfg.PSObject.Properties.Remove('plugin')
        }
        if ($cfg.provider -and $cfg.provider.google -and $cfg.provider.google.options.apiKey -eq 'antigravity') {
            $cfg.provider.google.options.PSObject.Properties.Remove('apiKey')
            if ($cfg.provider.google.options.PSObject.Properties.Count -eq 0) { $cfg.provider.PSObject.Properties.Remove('google') }
            if ($cfg.provider.PSObject.Properties.Count -eq 0) { $cfg.PSObject.Properties.Remove('provider') }
        }
        foreach ($property in @('model','small_model')) {
            if ($cfg.$property -is [string] -and $cfg.$property -match '^(google/antigravity-|opencode-antigravity)') {
                $cfg.PSObject.Properties.Remove($property)
            }
        }
        foreach ($sectionName in @('agent','agents')) {
            $section = $cfg.$sectionName
            if ($section -and $section.title -and $section.title.model -eq 'opencode/big-pickle') {
                $section.title.PSObject.Properties.Remove('model')
                if ($section.title.PSObject.Properties.Count -eq 0) { $section.PSObject.Properties.Remove('title') }
                if ($section.PSObject.Properties.Count -eq 0) { $cfg.PSObject.Properties.Remove($sectionName) }
            }
        }
        $cfg | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $opencodeConfig -Encoding UTF8
        Write-Host 'Removed Hub settings from opencode.json.'
    } catch { Write-Warning "Could not safely update opencode.json; file was preserved: $_" }
}

# Follow the migration pointer before deleting it, if the account store was relocated.
$pointer = Join-Path $configDir 'antigravity-accounts.json.store.pointer.json'
if (Test-Path -LiteralPath $pointer) {
    try {
        $pointerData = Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json
        $legacyPath = $pointerData.relocatedTo.legacyPath
        if ($legacyPath) {
            $storeDir = Split-Path -Parent ([Environment]::ExpandEnvironmentVariables([string]$legacyPath))
            if ((Test-Path -LiteralPath $storeDir) -and $storeDir -match 'antigravity') {
                Remove-Item -LiteralPath $storeDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { Write-Warning "Could not read account-store pointer: $_" }
}

# Remove Hub account/config files, private data, and only its plugin cache.
foreach ($base in @($configDir, $hubDataDir)) {
    if (Test-Path -LiteralPath $base) {
        foreach ($pattern in @('antigravity.json','antigravity-accounts.json*','*antigravity*accounts*','antigravity-auth*','antigravity-vault*')) {
            Get-ChildItem -LiteralPath $base -Filter $pattern -File -ErrorAction SilentlyContinue |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
}
foreach ($path in @(
    $hubDataDir,
    (Join-Path $HOME '.cache\opencode\npm\node_modules\@cortexkit\opencode-antigravity-auth'),
    (Join-Path $HOME '.cache\opencode\packages\@cortexkit\opencode-antigravity-auth@latest')
)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed: $path"
    }
}

# Remove Hub-specific logs only.
$logDir = Join-Path $HOME '.local\share\opencode\log'
if (Test-Path -LiteralPath $logDir) {
    Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'antigravity|hub' } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

# Remove the Windows uninstall registration and desktop shortcut.
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AntigravityHub'
if (Test-Path -LiteralPath $uninstallKey) { Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue }
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Antigravity Hub.lnk'
if (Test-Path -LiteralPath $desktopShortcut) { Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue }

# Delete the registered uninstaller copy after this process exits.
$installedDir = Join-Path $env:LOCALAPPDATA 'Programs\Antigravity Hub'
$currentScript = $PSCommandPath
if ($currentScript -and $currentScript.StartsWith($installedDir, [StringComparison]::OrdinalIgnoreCase)) {
    $cleanup = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$($installedDir.Replace("'", "''"))' -Recurse -Force -ErrorAction SilentlyContinue"
    Start-Process -FilePath (Get-Command powershell.exe).Source -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-Command',$cleanup) -ErrorAction SilentlyContinue
}

Write-Host 'Done. Restart OpenCode. OpenCode and separately installed tools were not removed.' -ForegroundColor Green
