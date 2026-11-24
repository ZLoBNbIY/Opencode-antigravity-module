param(
    [Parameter(Mandatory)][string]$InnoCompiler,
    [Parameter(Mandatory)][string]$WebViewBootstrap,
    [string]$Python = 'python',
    [string]$Version = '2.0.0',
    [string]$OutputDirectory,
    [string]$TrustedBrowserCache
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') { throw 'Use a numeric installer version.' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'artifacts\windows' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$InnoCompiler = (Resolve-Path -LiteralPath $InnoCompiler).Path
$WebViewBootstrap = (Resolve-Path -LiteralPath $WebViewBootstrap).Path
if ([IO.Path]::GetFileName($WebViewBootstrap) -cne 'MicrosoftEdgeWebview2Setup.exe') {
    throw 'Expected MicrosoftEdgeWebview2Setup.exe.'
}
$sig = Get-AuthenticodeSignature -LiteralPath $WebViewBootstrap
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch '(?:^|, )O=Microsoft Corporation(?:,|$)') {
    throw 'The bundled WebView2 bootstrapper must have a valid Microsoft signature.'
}
& $Python -c "import sys,sysconfig; assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,12) and sysconfig.get_platform() == 'win-amd64'"
if ($LASTEXITCODE -ne 0) { throw 'CPython 3.12 x64 is required for building.' }
[void][IO.Directory]::CreateDirectory($OutputDirectory)
$work = Join-Path ([IO.Path]::GetTempPath()) ('hub-build-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($work)
$env:HUB_BUILD_VERSION_FILE = Join-Path $work 'hub-version.txt'
[IO.File]::WriteAllText($env:HUB_BUILD_VERSION_FILE, $Version)
if ($TrustedBrowserCache) {
    $env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path -LiteralPath $TrustedBrowserCache).Path
} else {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $work 'browsers'
    & $Python -m playwright install chromium --no-shell
    if ($LASTEXITCODE -ne 0) { throw "Chromium download failed; build files are in $work" }
}
$dist = Join-Path $work 'dist'
& $Python -m PyInstaller --noconfirm --distpath $dist --workpath (Join-Path $work 'pyinstaller') (Join-Path $PSScriptRoot 'hub.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed; build files are in $work" }
$bundle = Join-Path $dist 'AntigravityHub'
$exe = Join-Path $bundle 'AntigravityHub.exe'
$report = Join-Path $work 'self-test.json'
$smoke = Start-Process -FilePath $exe -ArgumentList @('--package-self-test', ('"' + $report + '"')) -WorkingDirectory $bundle -PassThru
if (-not $smoke.WaitForExit(90000)) { $smoke.Kill(); throw "Packaged self-test timed out; see $work" }
if ($smoke.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) {
    if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
    throw "Packaged self-test failed; see $work"
}
Get-Content -LiteralPath $report
& $InnoCompiler /Qp "/DAppVersion=$Version" "/DBundleRoot=$bundle" "/DOutputRoot=$OutputDirectory" "/DWebViewBootstrap=$WebViewBootstrap" (Join-Path $PSScriptRoot 'AntigravityHub.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed; see $work" }
$setup = Join-Path $OutputDirectory 'AntigravityHub-Setup-x64.exe'
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$setup.sha256", "$hash  AntigravityHub-Setup-x64.exe`n")
if (Test-Path -LiteralPath $work) {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "Installer: $setup"
