param(
    [switch]$SkipNode,
    [switch]$SkipRoute
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir

function Test-PythonExe {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    if ($Path -match 'WindowsApps\\python(3)?\.exe$') { return $false }
    try {
        & $Path -c "import sys; raise SystemExit(0 if sys.version_info[0] >= 3 else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    if ($env:ANTIGRAVITY_PYTHON -and (Test-PythonExe $env:ANTIGRAVITY_PYTHON)) {
        return @{ Exe = $env:ANTIGRAVITY_PYTHON; Prefix = @() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonExe $python.Source)) {
        return @{ Exe = $python.Source; Prefix = @() }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            & $py.Source -3 -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $py.Source; Prefix = @('-3') }
            }
        } catch {}
    }
    $patterns = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        'C:\Program Files\Python3*\python.exe',
        'C:\Program Files (x86)\Python3*\python.exe',
        'C:\Python3*\python.exe'
    )
    foreach ($pattern in $patterns) {
        $candidates = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
        foreach ($candidate in $candidates) {
            if (Test-PythonExe $candidate) {
                return @{ Exe = $candidate; Prefix = @() }
            }
        }
    }
    Write-Warning "Python 3 не найден. Установи Python 3 и повтори запуск."
    exit 1
}

function Find-Node {
    if ($env:ANTIGRAVITY_NODE -and (Test-Path -LiteralPath $env:ANTIGRAVITY_NODE)) {
        return $env:ANTIGRAVITY_NODE
    }
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { return $node.Source }
    foreach ($candidate in @(
        'C:\Program Files\nodejs\node.exe',
        'C:\Program Files (x86)\nodejs\node.exe'
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    Write-Warning "Node.js не найден. Установи Node.js 20+ и повтори запуск."
    exit 1
}

function Invoke-Python {
    param([hashtable]$Python, [string[]]$Arguments)
    $allArgs = @($Python.Prefix) + @($Arguments)
    & $Python.Exe @allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python завершился с кодом $LASTEXITCODE"
    }
}

$python = Find-Python
$env:ANTIGRAVITY_PYTHON = $python.Exe

Write-Host "=== Antigravity compatibility patch ===" -ForegroundColor Cyan
Write-Host "Repo: $Root"
Write-Host "Python: $($python.Exe)"

if (-not $SkipNode) {
    $node = Find-Node
    $patchScript = Join-Path $ScriptDir 'patch_plugin.mjs'
    Write-Host "`n[1/3] Node patches: $patchScript"
    & $node $patchScript
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "patch_plugin.mjs завершился с кодом $LASTEXITCODE, продолжаю Python-патчи."
    }
} else {
    Write-Host "`n[1/3] Node patches skipped (-SkipNode)."
}

if (-not $SkipRoute) {
    Write-Host "`n[2/3] Hub route patch"
    Invoke-Python $python @((Join-Path $Root 'gui-manager\cloudcode_route_patch.py'))
} else {
    Write-Host "`n[2/3] Hub route patch skipped (-SkipRoute)."
}

Write-Host "`n[3/3] Identity / Antigravity body patch"
Invoke-Python $python @((Join-Path $Root 'gui-manager\cloudcode_route_patch.py'), 'identity')

Write-Host "`n=== Status ===" -ForegroundColor Cyan
Invoke-Python $python @((Join-Path $Root 'gui-manager\cloudcode_route_patch.py'), 'status')

Write-Host "`nГотово. Перезапусти OpenCode, чтобы он загрузил пропатченный бандл." -ForegroundColor Green
Write-Host "Если на этом ПК другая версия Antigravity, задай перед запуском:"
Write-Host "  `$env:ANTIGRAVITY_APP_VERSION=`"2.33.0`"; `$env:ANTIGRAVITY_APP_CHANGE_LIST=`"1023160026`""
