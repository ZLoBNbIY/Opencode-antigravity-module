# OpenCode Antigravity Module Installer (run from a reviewed local checkout).
param(
    [switch]$NoShortcut,
    [switch]$SkipPython,
    [switch]$SkipPatch
)

$ErrorActionPreference = 'Stop'

function Get-NodeVersion([string]$Executable) {
    if (-not $Executable) { return }
    try {
        $raw = & $Executable --version 2>$null
        if ($LASTEXITCODE -eq 0 -and "$raw" -match '^v(\d+\.\d+\.\d+)$') {
            return [version]$Matches[1]
        }
    } catch {
        # A broken candidate is not a working runtime.
    }
}

function Find-Node {
    $candidates = @(Get-Command node -CommandType Application -All -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source)
    foreach ($programFilesDir in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($programFilesDir) { $candidates += Join-Path $programFilesDir 'nodejs\node.exe' }
    }
    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and
            ((Get-NodeVersion $candidate) -ge [version]'20.0.0')) {
            return $candidate
        }
    }
}

function Find-Python {
    $candidates = @()
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $candidate = & $launcher.Source -3 -I -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) { $candidates += $candidate }
        } catch {}
    }
    $candidates += @(Get-Command python, python3 -CommandType Application -All -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source)
    if ($env:LOCALAPPDATA) {
        $candidates += @(Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" `
            -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if ($candidate -like '*\Microsoft\WindowsApps\python*.exe') { continue }
        try {
            & $candidate -I -c 'import sys; sys.exit(sys.version_info < (3, 10) or sys.version_info[0] != 3)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
}

function Publish-NewConfig([string]$Source, [string]$Destination, [string[]]$ExistingNames) {
    $parent = Split-Path -Parent $Destination
    $existing = @(Get-ChildItem -LiteralPath $parent -Force |
        Where-Object { $_.Name -in $ExistingNames })
    if ($existing.Count -gt 0) {
        Write-Warning "Existing config left untouched: $($existing.Name -join ', '). Check it against the module template and merge required settings manually."
        return
    }

    $tempPath = Join-Path $parent ('.antigravity-install-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $created = $false
    try {
        $stream = [IO.File]::Open($tempPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $created = $true
        try {
            $template = [IO.File]::OpenRead($Source)
            try { $template.CopyTo($stream) } finally { $template.Dispose() }
        } finally { $stream.Dispose() }

        # Recheck the alternate .jsonc name before publishing. File.Move itself
        # never overwrites an existing destination (including a racing installer).
        $conflict = Get-ChildItem -LiteralPath $parent -Force |
            Where-Object { $_.Name -in $ExistingNames }
        if ($conflict) { throw "Config appeared during installation; it was not modified: $($conflict.Name -join ', ')" }
        [IO.File]::Move($tempPath, $Destination)
        $created = $false
        Write-Host "Created $Destination"
    } finally {
        if ($created) { Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue }
    }
}

try {
    if (-not $PSScriptRoot -or -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'gui-manager\antigravity_manager.pyw') -PathType Leaf)) {
        throw 'Online bootstrap is disabled. Review a local copy of the V2 repository, then run install.ps1 or install.bat from that copy.'
    }
    $scriptDir = $PSScriptRoot
    $openCodeTemplate = Join-Path $scriptDir 'config-templates\opencode.json'
    $antigravityTemplate = Join-Path $scriptDir 'config-templates\antigravity.json'
    $patchScript = Join-Path $scriptDir 'scripts\patch_plugin.mjs'
    $requirements = Join-Path $scriptDir 'gui-manager\requirements.txt'
    $uninstallScript = Join-Path $scriptDir 'uninstall.ps1'
    $launcherBat = Join-Path $scriptDir 'gui-manager\start_manager.bat'
    $required = @($openCodeTemplate, $antigravityTemplate, $uninstallScript)
    if (-not $SkipPython) { $required += $requirements }
    if (-not $SkipPatch) { $required += $patchScript }
    if (-not $NoShortcut) { $required += $launcherBat }
    foreach ($file in $required) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required file is missing: $file" }
    }

    if (-not $SkipPython) {
        $pythonPath = Find-Python
        if (-not $pythonPath) { throw 'Python 3.10 or later is required. Install it from https://www.python.org/downloads/ or use -SkipPython to omit GUI dependencies.' }
        & $pythonPath -I -m pip --version
        if ($LASTEXITCODE -ne 0) { throw "pip is unavailable for $pythonPath (exit $LASTEXITCODE)." }
        $platform = & $pythonPath -I -c "import sys, sysconfig; print('locked' if sys.platform == 'win32' and sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64' else 'unlocked')"
        if ($LASTEXITCODE -ne 0 -or $platform -cnotin @('locked', 'unlocked')) {
            throw 'Could not determine whether this Python interpreter is supported by the Windows dependency lock.'
        }
        if ($platform -ceq 'locked') {
            $lockFile = Join-Path $scriptDir 'gui-manager\requirements-win-py312-x64.lock'
            if (-not (Test-Path -LiteralPath $lockFile -PathType Leaf)) {
                throw "Windows CPython 3.12 x64 dependency lock is missing: $lockFile. Refusing to install unlocked dependencies."
            }
            $pipArgs = @('--isolated', 'install', '--index-url', 'https://pypi.org/simple', '--require-hashes', '-r', $lockFile, '--quiet')
            Write-Host 'Using the hash-locked Windows CPython 3.12 x64 runtime requirements. Isolated build dependencies for source distributions are not covered.'
        } else {
            $pipArgs = @('install', '-r', $requirements, '--quiet')
            Write-Warning 'No dependency lock for this Python platform/version. Installing unlocked requirements.'
        }
    }

    if (-not $SkipPatch) {
        $nodePath = Find-Node
        if (-not $nodePath) {
            $winget = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue
            if (-not $winget) { throw 'Node.js >=20 is required. Install it from https://nodejs.org/ or use -SkipPatch.' }
            Write-Host 'Installing Node.js LTS through WinGet...'
            & $winget.Source install --source winget --id OpenJS.NodeJS.LTS --exact --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw "WinGet failed (exit $LASTEXITCODE). Install or upgrade Node.js LTS manually." }
            $nodePath = Find-Node
            if (-not $nodePath) { throw 'Node.js >=20 was not found after WinGet completed. Open a new terminal and retry.' }
        }
    }

    if ($env:OPENCODE_CONFIG_DIR) {
        if ($env:OPENCODE_CONFIG_DIR -notmatch '^(?:[a-zA-Z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
            throw 'OPENCODE_CONFIG_DIR must be an absolute path to install into it.'
        }
        $configDir = $env:OPENCODE_CONFIG_DIR
    } else {
        $configBase = if ($env:XDG_CONFIG_HOME -match '^(?:[a-zA-Z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
            $env:XDG_CONFIG_HOME
        } else { Join-Path $HOME '.config' }
        $configDir = Join-Path $configBase 'opencode'
    }
    [void][IO.Directory]::CreateDirectory($configDir)
    Publish-NewConfig $openCodeTemplate (Join-Path $configDir 'opencode.json') @('opencode.json', 'opencode.jsonc')
    Publish-NewConfig $antigravityTemplate (Join-Path $configDir 'antigravity.json') @('antigravity.json')

    if ($SkipPatch) {
        Write-Host 'Skipped compatibility patch step (-SkipPatch).'
    } else {
        & $nodePath $patchScript
        if ($LASTEXITCODE -ne 0) { throw "Compatibility patch script failed (exit $LASTEXITCODE)." }
        Write-Host 'Compatibility patch script completed. See its output for changes.'
    }

    if ($SkipPython) {
        Write-Host 'Skipped GUI dependencies (-SkipPython).'
    } else {
        & $pythonPath -I -m pip @pipArgs
        if ($LASTEXITCODE -ne 0) { throw "GUI dependency installation failed (exit $LASTEXITCODE)." }
        Write-Host 'GUI dependency installation completed.'
    }

    $uninstallDir = Join-Path $env:LOCALAPPDATA 'Programs\Antigravity Hub'
    [void][IO.Directory]::CreateDirectory($uninstallDir)
    $installedUninstaller = Join-Path $uninstallDir 'uninstall.ps1'
    Copy-Item -LiteralPath $uninstallScript -Destination $installedUninstaller -Force
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AntigravityHub'
    New-Item -Path $uninstallKey -Force | Out-Null
    $windowsPowerShell = (Get-Command powershell.exe -CommandType Application).Source
    $uninstallCommand = '"' + $windowsPowerShell + '" -NoProfile -ExecutionPolicy Bypass -File "' + $installedUninstaller + '"'
    New-ItemProperty -Path $uninstallKey -Name DisplayName -Value 'Antigravity Hub' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value '2.0' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name Publisher -Value 'Antigravity Hub' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name UninstallString -Value $uninstallCommand -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
    Write-Host 'Registered Antigravity Hub in Windows Installed Apps.'

    if (-not $NoShortcut) {
        $desktopPath = [Environment]::GetFolderPath('Desktop')
        if (-not $desktopPath) { throw 'Could not locate the Desktop to create the shortcut.' }
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktopPath 'Antigravity Hub.lnk'))
        $shortcut.TargetPath = $launcherBat
        $shortcut.WorkingDirectory = $scriptDir
        $shortcut.Description = 'Antigravity Hub'
        $iconPath = Join-Path $scriptDir 'gui-manager\icon.ico'
        if (Test-Path -LiteralPath $iconPath -PathType Leaf) { $shortcut.IconLocation = "$iconPath,0" }
        $shortcut.Save()
        Write-Host 'Created the Antigravity Hub desktop shortcut.'
    }

    Write-Host 'Installer steps completed. Existing configs, if any, were not updated or validated.'
    exit 0
} catch {
    [Console]::Error.WriteLine("Installation stopped: $($_.Exception.Message) Earlier steps may have made changes; no automatic rollback was attempted.")
    exit 1
}
