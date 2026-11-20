param([switch]$Yes)

$ErrorActionPreference = 'Stop'
$script:failed = $false

Write-Host 'OpenCode AI HUB - remove known Hub files and integration settings' -ForegroundColor Cyan
Write-Host 'Stop Hub and OpenCode first. Shared credentials, chats, browser profiles and custom stores will be preserved.'
if (-not $Yes) {
    if ((Read-Host 'This cannot be undone. Continue? Type DELETE') -cne 'DELETE') {
        Write-Host 'Cancelled.'
        exit 0
    }
}

function Try-Cleanup($Label, [scriptblock]$Action) {
    try { & $Action }
    catch {
        $script:failed = $true
        Write-Warning "${Label}: $_"
    }
}

function Get-SafeFile([string]$Path) {
    # Nothing from a migration pointer or a user-supplied config path reaches here.
    $canonical = [IO.Path]::GetFullPath($Path)
    if ($canonical -ine $Path -or $canonical -notmatch '^[A-Za-z]:\\') {
        throw "Not a canonical local path: $Path"
    }
    $parts = [Collections.Generic.List[string]]::new()
    for ($part = $Path; $part; $part = [IO.Path]::GetDirectoryName($part)) {
        $parts.Insert(0, $part)
    }
    foreach ($part in $parts) {
        try { $item = Get-Item -LiteralPath $part -Force }
        catch [System.Management.Automation.ItemNotFoundException] { return }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Link or junction left untouched: $part"
        }
        if ($item.PSIsContainer -eq ($part -ieq $Path)) {
            throw "Unexpected file type left untouched: $part"
        }
    }
    return $item
}

function Remove-SafeFile([string]$Path) {
    if (Get-SafeFile $Path) {
        Remove-Item -LiteralPath $Path -Force
        Write-Host "Removed: $Path"
    }
}

$profileRoot = [Environment]::GetFolderPath('UserProfile')
if (-not $profileRoot) { throw 'Cannot determine the current user profile.' }
$hubRoot = Join-Path $profileRoot 'AppData\Roaming\AntigravityHub'
$configDir = Join-Path $profileRoot '.config\opencode'
$centralConfig = Join-Path $hubRoot 'config\antigravity.json'
$defaultHub = -not $env:ANTIGRAVITY_HUB_DATA_DIR -and $env:APPDATA -and
    (Join-Path $env:APPDATA 'AntigravityHub') -ieq $hubRoot

function Remove-HubPlugin([string]$Path) {
    if (-not (Get-SafeFile $Path)) { return }
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $original = $utf8.GetString([IO.File]::ReadAllBytes($Path))
    $plain = $original.TrimStart([char]0xFEFF)
    $cfg = ConvertFrom-Json -InputObject $plain
    # Avoid a lossy rewrite of the entire OpenCode config. Only change a
    # uniquely matched plugin property with a string or array of strings.
    $package = '^@cortexkit/opencode-antigravity-auth(?:@[^@\s]+)?$'
    $plugin = $cfg.PSObject.Properties | Where-Object { $_.Name -ceq 'plugin' }
    if (-not $plugin) { return }
    $entries = @($plugin.Value)
    $owned = @($entries | Where-Object { $_ -is [string] -and $_ -cmatch $package })
    if (-not $owned.Count) { return }
    if (@($entries | Where-Object { $_ -isnot [string] }).Count) {
        throw 'Plugin list contains structured entries; remove the Hub plugin manually.'
    }
    $quoted = '"(?:\\.|[^"\\])*"'
    $array = '\[\s*(?:' + $quoted + '(?:\s*,\s*' + $quoted + ')*)?\s*\]'
    $match = [regex]::Matches($original, '"plugin"\s*:\s*(?<value>' + $array + '|' + $quoted + ')')
    if ($match.Count -ne 1) { throw 'Cannot identify the plugin field safely.' }
    $value = $match[0].Groups['value']
    $candidate = @((ConvertFrom-Json -InputObject ('{"value":' + $value.Value + '}')).value)
    if ((ConvertTo-Json -InputObject $candidate -Compress) -cne (ConvertTo-Json -InputObject $entries -Compress)) {
        throw 'Cannot verify the plugin field safely.'
    }
    $keep = @($entries | Where-Object { $_ -cnotmatch $package })
    $replacement = ConvertTo-Json -InputObject $keep -Compress
    $updated = $original.Substring(0, $value.Index) + $replacement + $original.Substring($value.Index + $value.Length)
    $parsed = ConvertFrom-Json -InputObject ($updated.TrimStart([char]0xFEFF))
    if ((ConvertTo-Json -InputObject @($parsed.plugin) -Compress) -cne $replacement) {
        throw 'Cannot verify the updated plugin field.'
    }
    $temp = Join-Path (Split-Path -Parent $Path) ('.hub-uninstall-' + [guid]::NewGuid() + '.tmp')
    $stream = [IO.File]::Open($temp, 'CreateNew', 'Write', 'None')
    try {
        try {
            $bytes = $utf8.GetBytes($updated)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
        if ($utf8.GetString([IO.File]::ReadAllBytes($Path)) -cne $original) {
            throw 'The config changed during uninstall; no changes were written.'
        }
        [IO.File]::Replace($temp, $Path, [NullString]::Value)
        Write-Host 'Removed the Hub plugin from OpenCode configuration.'
    } finally {
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
    }
}

if ($env:OPENCODE_CONFIG_DIR) {
    Write-Warning 'Custom OpenCode configuration was left untouched.'
} else {
    Try-Cleanup 'OpenCode configuration' {
        if (Get-SafeFile (Join-Path $configDir 'opencode.jsonc')) {
            throw 'JSONC config was preserved. Remove the Hub plugin using the Hub UI or manually.'
        }
        Remove-HubPlugin (Join-Path $configDir 'opencode.json')
    }
    Try-Cleanup 'OpenCode provider routing plugin' {
        $path = Join-Path $configDir 'plugins\antigravity-hub-routes.js'
        if ((Get-SafeFile $path) -and
            (Get-Content -LiteralPath $path -TotalCount 1) -ceq '// Managed by AI HUB: provider-scoped routes') {
            Remove-SafeFile $path
        }
    }
    Try-Cleanup 'Hub configuration mirror' {
        $mirror = Join-Path $configDir 'antigravity.json'
        if ((Get-SafeFile $mirror) -and $defaultHub -and (Get-SafeFile $centralConfig) -and
            (Get-FileHash -LiteralPath $mirror).Hash -ceq (Get-FileHash -LiteralPath $centralConfig).Hash) {
            Remove-SafeFile $mirror
        }
    }
}

if ($defaultHub) {
    foreach ($file in @(
        'config\antigravity.json', 'config\gemini_domains.json',
        'accounts\openai-accounts.json', 'accounts\claude-accounts.json',
        'accounts\xpiki.json', 'accounts\tokenlavka.json', 'accounts\deepseek-api.json',
        'secure\openrouter.json', 'secure\tokenlavka.json', 'secure\deepseek-api-key.json',
        'vless\config.json', 'vless\core.log'
    )) {
        Try-Cleanup $file { Remove-SafeFile (Join-Path $hubRoot $file) }
    }
} else {
    Write-Warning 'Custom or redirected Hub storage was left untouched.'
}

# Remove only an installation registration stamped by our installer. Never
# recurse into either the registry or Programs; foreign descendants are kept.
$installedScript = Join-Path $profileRoot 'AppData\Local\Programs\AI HUB\uninstall.ps1'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AntigravityHub'
Try-Cleanup 'Hub uninstall registration' {
    if (Test-Path -LiteralPath $uninstallKey) {
        $registration = Get-ItemProperty -LiteralPath $uninstallKey
        $expected = '"' + (Get-Command powershell.exe).Source + '" -NoProfile -ExecutionPolicy Bypass -File "' + $installedScript + '"'
        if ($registration.DisplayName -cne 'AI HUB' -or
            $registration.Publisher -cne 'AI HUB' -or
            $registration.UninstallString -ine $expected -or
            @(Get-ChildItem -LiteralPath $uninstallKey).Count) {
            throw 'Registration does not match the Hub installer; left untouched.'
        }
        Remove-Item -LiteralPath $uninstallKey
        if ($PSCommandPath -ieq $installedScript) { Remove-SafeFile $installedScript }
    }
}

Try-Cleanup 'Hub autostart entry' {
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (Test-Path -LiteralPath $runKey) {
        $entry = Get-ItemProperty -LiteralPath $runKey -Name 'AI HUB' -ErrorAction SilentlyContinue
        if ($null -ne $entry -and $entry.'AI HUB' -match 'AI HUB|antigravity_manager\.pyw|AntigravityHub\.exe') {
            Remove-ItemProperty -LiteralPath $runKey -Name 'AI HUB' -ErrorAction SilentlyContinue
        }
    }
}

Write-Host 'Account-store pointers and all targets, shared provider settings and credentials, and unlisted files were preserved.'
if ($script:failed) {
    Write-Warning 'Cleanup completed with errors or items requiring manual review.'
    exit 1
}
Write-Host 'Cleanup complete. Restart OpenCode before using it again.' -ForegroundColor Green
