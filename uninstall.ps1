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
$defaultHub = -not $env:ANTIGRAVITY_HUB_DATA_DIR -and $env:APPDATA -and
    (Join-Path $env:APPDATA 'AntigravityHub') -ieq $hubRoot

function Get-JsonValueEnd($Tokens, [int]$Start) {
    if ($Tokens[$Start].Value -cnotin @('[', '{')) { return $Start }
    $depth = 1
    for ($i = $Start + 1; $i -lt $Tokens.Count; $i++) {
        switch -CaseSensitive ($Tokens[$i].Value) {
            { $_ -cin @('[', '{') } { $depth++ }
            { $_ -cin @(']', '}') } { $depth-- }
        }
        if (-not $depth) { return $i }
    }
    throw 'Incomplete JSON value.'
}

function Get-JsonString($Token) {
    if ($Token.Value.StartsWith('"')) {
        # Wrap the token so PS 5.1 does not have to parse a top-level scalar.
        return (ConvertFrom-Json -InputObject ('{"value":' + $Token.Value + '}')).value
    }
}

function Test-HubPluginEntry($Tokens, [int]$Start, [int]$End, [string]$Field) {
    $value = Get-JsonString $Tokens[$Start]
    if ($Field -ceq 'plugin' -and $Tokens[$Start].Value -ceq '[' -and
        $End -gt ($Start + 4) -and $Tokens[$Start + 2].Value -ceq ',' -and
        $Tokens[$Start + 3].Value -ceq '{' -and (Get-JsonValueEnd $Tokens ($Start + 3)) -eq ($End - 1)) {
        $value = Get-JsonString $Tokens[$Start + 1]
    } elseif ($Field -ceq 'plugins' -and $Tokens[$Start].Value -ceq '{') {
        $seen = $false
        for ($i = $Start + 1; $i -lt $End; $i = $j + 2) {
            $j = Get-JsonValueEnd $Tokens ($i + 2)
            if ((Get-JsonString $Tokens[$i]) -ceq 'package') {
                if ($seen) { throw 'Duplicate plugin package key; no changes were written.' }
                $seen = $true
                $value = Get-JsonString $Tokens[$i + 2]
            }
        }
    }
    return ($value -cmatch '^@cortexkit/opencode-antigravity-auth(?:@[^@\s]+)?$')
}

function Get-HubPluginRemoval([string]$Text) {
    # Validate JSON, then locate only the root plugin fields in the original
    # text. Never round-trip user settings (large numbers, escapes, spacing).
    $offset = if ($Text.StartsWith([string][char]0xFEFF, [StringComparison]::Ordinal)) { 1 } else { 0 }
    $null = ConvertFrom-Json -InputObject $Text.Substring($offset)
    $pattern = '\G[ \t\r\n]*(?:"(?:\\(?:["\\/bfnrt]|u[0-9A-Fa-f]{4})|[^"\\\x00-\x1f])*"|[{}\[\],:]|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)'
    $tokens = [regex]::new($pattern).Matches($Text, $offset)
    # Strip the leading JSON whitespace from token spans, keeping it in the file.
    $tokens = @(foreach ($token in $tokens) {
        $value = $token.Value.TrimStart([char[]]" `t`r`n")
        [pscustomobject]@{ Value = $value; Index = $token.Index + $token.Length - $value.Length; Length = $value.Length }
    })
    if ($tokens.Count -lt 2 -or $tokens[0].Value -cne '{' -or $tokens[-1].Value -cne '}' -or
        $Text.Substring($tokens[-1].Index + 1).Trim([char[]]" `t`r`n")) {
        throw 'Expected a plain JSON object; no changes were written.'
    }
    for ($i = 1; $i -lt $tokens.Count; $i++) {
        if ($tokens[$i - 1].Value -ceq ',' -and $tokens[$i].Value -cin @('}', ']')) {
            throw 'Trailing comma in config; no changes were written.'
        }
    }
    $root = Get-JsonValueEnd $tokens 0
    if ($root -ne ($tokens.Count - 1)) { throw 'Unexpected text after JSON object.' }
    $seen = @{}
    $edits = @{}
    for ($i = 1; $i -lt $root; $i = $end + 2) {
        $field = Get-JsonString $tokens[$i]
        if ($null -eq $field -or $tokens[$i + 1].Value -cne ':') { throw 'Invalid root JSON property.' }
        $first = $i + 2
        $end = Get-JsonValueEnd $tokens $first
        if ($field -cnotin @('plugin', 'plugins')) { continue }
        if ($seen.ContainsKey($field)) { throw "Duplicate '$field' key; no changes were written." }
        $seen[$field] = $true
        if ($tokens[$first].Value -cne '[') {
            if ($field -ceq 'plugin' -and (Test-HubPluginEntry $tokens $first $end $field)) {
                $edits[$tokens[$first].Index] = @($tokens[$first].Length, '[]')
            }
            continue
        }
        $lastKept = $null
        $commas = @()
        for ($j = $first + 1; $j -lt $end; $j = $tail + 2) {
            $tail = Get-JsonValueEnd $tokens $j
            $owned = Test-HubPluginEntry $tokens $j $tail $field
            if ($owned) {
                $edits[$tokens[$j].Index] = @(($tokens[$tail].Index + $tokens[$tail].Length - $tokens[$j].Index), '')
            } else {
                if ($null -ne $lastKept) { $commas += $lastKept }
                $lastKept = $tail + 1
            }
        }
        for ($j = $first + 1; $j -lt $end; $j = $tail + 2) {
            $tail = Get-JsonValueEnd $tokens $j
            if ($tail + 1 -lt $end -and ($tail + 1) -notin $commas) {
                $edits[$tokens[$tail + 1].Index] = @(1, '')
            }
        }
    }
    foreach ($index in ($edits.Keys | Sort-Object -Descending)) {
        $length, $replacement = $edits[$index]
        $Text = $Text.Remove($index, $length).Insert($index, $replacement)
    }
    $null = ConvertFrom-Json -InputObject $Text.Substring($offset)
    return $Text
}

function Remove-HubPlugin([string]$Path) {
    if (-not (Get-SafeFile $Path)) { return }
    if ([IO.Path]::GetExtension($Path) -ieq '.jsonc') {
        throw 'JSONC config was preserved. Remove the Hub plugin using the Hub UI or manually.'
    }
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $original = $utf8.GetString([IO.File]::ReadAllBytes($Path))
    $updated = Get-HubPluginRemoval $original
    if ($updated -ceq $original) { return }
    $temp = Join-Path (Split-Path -Parent $Path) ('.hub-uninstall-' + [guid]::NewGuid() + '.tmp')
    $stream = [IO.File]::Open($temp, 'CreateNew', 'Write', 'None')
    try {
        try {
            $bytes = $utf8.GetBytes($updated)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
        if (-not (Get-SafeFile $Path) -or $utf8.GetString([IO.File]::ReadAllBytes($Path)) -cne $original) {
            throw 'The config changed during uninstall; no changes were written.'
        }
        [IO.File]::Replace($temp, $Path, [NullString]::Value)
        Write-Host 'Removed the Hub plugin from OpenCode configuration.'
    } finally {
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
    }
}

$installedScript = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\AI HUB\uninstall.ps1'
$uninstallBase = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
$uninstallKey = Join-Path $uninstallBase 'AntigravityHub'
$packageKey = Join-Path $uninstallBase '{D8A77D35-0449-4719-AC3D-D2B42CE9DFBD}_is1'
$registeredSource = $null
$sourceCheckout = if ($PSCommandPath -ine $installedScript) { $PSScriptRoot }

function Test-SourceAutostart([string]$Command, [string]$Checkout) {
    if (-not $Checkout -or $Command -notmatch '^"(?<python>[A-Za-z]:\\[^"]+)" "(?<script>[^"]+)"$') { return $false }
    $pythonPath = $Matches.python
    return ($Matches.script -ieq (Join-Path $Checkout 'gui-manager\antigravity_manager.pyw') -and
        [IO.Path]::GetFileName($pythonPath) -in @('python.exe', 'pythonw.exe') -and
        [IO.Path]::GetFullPath($pythonPath) -ieq $pythonPath)
}

function Test-SourceShortcut($Shortcut, [string]$Checkout) {
    if (-not $Checkout -or $Shortcut.Arguments) { return $false }
    if ($Shortcut.TargetPath -ieq (Join-Path $Checkout 'gui-manager\start_manager.bat')) { return $true }
    # Windows PowerShell 5.1 reads BOM-less scripts using its ANSI code page.
    $legacyName = -join ([char[]]@(0x417,0x430,0x43F,0x443,0x441,0x43A,0x5F,0x41C,0x435,
        0x43D,0x435,0x434,0x436,0x435,0x440,0x430)) + '.bat'
    return ($Shortcut.TargetPath -ieq (Join-Path $Checkout $legacyName))
}

Try-Cleanup 'Source uninstall registration' {
    if (-not (Test-Path -LiteralPath $uninstallKey)) { return }
    $registration = Get-ItemProperty -LiteralPath $uninstallKey
    $expected = '"' + (Get-Command powershell.exe -CommandType Application).Source + '" -NoProfile -ExecutionPolicy Bypass -File "' + $installedScript + '"'
    $allowed = @('DisplayName', 'DisplayVersion', 'Publisher', 'UninstallString', 'NoModify', 'NoRepair', 'SourceCheckout', 'UninstallerHash')
    $key = Get-Item -LiteralPath $uninstallKey
    if ($registration.DisplayName -cne 'AI HUB' -or $registration.Publisher -cne 'AI HUB' -or
        $registration.UninstallString -ine $expected -or
        $registration.SourceCheckout -notmatch '^[A-Za-z]:\\' -or
        ($sourceCheckout -and $registration.SourceCheckout -ine $sourceCheckout) -or
        $registration.UninstallerHash -cnotmatch '^[0-9A-F]{64}$' -or
        $key.SubKeyCount -or @($key.GetValueNames() | Where-Object { $_ -notin $allowed }).Count -or
        -not (Get-SafeFile $installedScript) -or
        (Get-FileHash -LiteralPath $installedScript).Hash -cne $registration.UninstallerHash) {
        Write-Warning 'Registration cannot be attributed to this checkout; it was left untouched.'
        return
    }
    $script:registeredSource = $registration
    $script:sourceCheckout = $registration.SourceCheckout
}

$isSource = $false
Try-Cleanup 'Source checkout' {
    if ($sourceCheckout -and (Get-SafeFile (Join-Path $sourceCheckout 'gui-manager\antigravity_manager.pyw')) -and
        (Get-SafeFile (Join-Path $sourceCheckout 'gui-manager\start_manager.bat'))) {
        $script:isSource = $true
    } else {
        Write-Warning 'Source checkout could not be verified; shared configuration and launcher entries were left untouched.'
    }
}
$packageInstalled = Test-Path -LiteralPath $packageKey
if ($packageInstalled) {
    Write-Warning 'Packaged AI HUB is also installed; retaining the shared OpenCode integration and Hub data.'
}

if (-not $isSource -or $packageInstalled) {
    # Integration and data are shared; leave them for the other installation.
} elseif ($env:OPENCODE_CONFIG_DIR -or
    $env:OPENCODE_CONFIG -or $env:OPENCODE_CONFIG_CONTENT -or
    ($env:XDG_CONFIG_HOME -match '^(?:[a-zA-Z]:[\\/]|\\\\[^\\]+\\[^\\]+)')) {
    Write-Warning 'Custom OpenCode configuration was left untouched.'
} else {
    Try-Cleanup 'OpenCode JSONC configuration' { Remove-HubPlugin (Join-Path $configDir 'opencode.jsonc') }
    Try-Cleanup 'OpenCode JSON configuration' { Remove-HubPlugin (Join-Path $configDir 'opencode.json') }
    Try-Cleanup 'OpenCode provider routing plugin' {
        $path = Join-Path $configDir 'plugins\antigravity-hub-routes.js'
        if ((Get-SafeFile $path) -and
            (Get-Content -LiteralPath $path -TotalCount 1) -ceq '// Managed by AI HUB: provider-scoped routes') {
            Remove-SafeFile $path
        }
    }
}

if ($isSource -and -not $packageInstalled -and $defaultHub) {
    foreach ($file in @(
        'config\antigravity.json', 'config\gemini_domains.json',
        'accounts\openai-accounts.json', 'accounts\claude-accounts.json',
        'accounts\xpiki.json', 'accounts\tokenlavka.json', 'accounts\deepseek-api.json',
        'secure\openrouter.json', 'secure\tokenlavka.json', 'secure\deepseek-api-key.json',
        'vless\config.json', 'vless\core.log'
    )) {
        Try-Cleanup $file { Remove-SafeFile (Join-Path $hubRoot $file) }
    }
} elseif (-not $defaultHub) {
    Write-Warning 'Custom or redirected Hub storage was left untouched.'
}

Try-Cleanup 'Hub autostart entry' {
    if (-not $isSource) { return }
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (Test-Path -LiteralPath $runKey) {
        $entry = Get-ItemProperty -LiteralPath $runKey -Name 'AI HUB' -ErrorAction SilentlyContinue
        if ($null -ne $entry -and (Test-SourceAutostart $entry.'AI HUB' $sourceCheckout)) {
            Remove-ItemProperty -LiteralPath $runKey -Name 'AI HUB'
        }
    }
}

Try-Cleanup 'Hub desktop shortcuts' {
    if (-not $isSource) { return }
    $desktopPath = [Environment]::GetFolderPath('Desktop')
    if (-not $desktopPath) { return }
    $shell = New-Object -ComObject WScript.Shell
    # Both the current name and the pre-rebrand name can exist on a machine
    # upgraded from an older install; remove only shortcuts pointing at the Hub.
    foreach ($name in @('AI HUB.lnk', 'Antigravity Hub.lnk')) {
        $path = Join-Path $desktopPath $name
        if (-not (Get-SafeFile $path)) { continue }
        $shortcut = $shell.CreateShortcut($path)
        if (Test-SourceShortcut $shortcut $sourceCheckout) {
            Remove-SafeFile $path
        } else {
            Write-Warning "Desktop shortcut '$name' was left untouched: unexpected target '$($shortcut.TargetPath)'."
        }
    }
}

Try-Cleanup 'Remove source uninstall registration' {
    if (-not $registeredSource) { return }
    Remove-Item -LiteralPath $uninstallKey
    Remove-SafeFile $installedScript
}

Write-Host 'Account-store pointers and all targets, shared provider settings and credentials, and unlisted files were preserved.'
if ($script:failed) {
    Write-Warning 'Cleanup completed with errors or items requiring manual review.'
    exit 1
}
Write-Host 'Cleanup complete. Restart OpenCode before using it again.' -ForegroundColor Green
