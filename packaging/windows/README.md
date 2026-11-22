# Windows x64 installer

For users, distribute `AntigravityHub-Setup-x64.exe` and the accompanying
`.sha256` file. The bundled app supplies Python, Node.js (from Playwright), and
Chromium. The setup installs per-user; Microsoft WebView2 is installed only
when missing, using the bundled signed Microsoft bootstrapper. The bootstrapper
needs Internet access. OpenCode itself is a separate product.

The optional OpenCode setup task copies starter configs only if they don't
already exist. It doesn't replace an existing JSON/JSONC config or register a
second copy of an existing plugin. Users with an existing config can add
`@cortexkit/opencode-antigravity-auth@3.0.0` under `plugins` if they need it.
The local Hub bundle's CLI and the npm plugin are separate.

The GitHub Actions workflow **Windows installer** runs on pushes to `V2`, or
manually with `V2` selected. Each successful push releases its tip commit as
the next patch version (`v2.0.1` if no stable tag exists, then `v2.0.2`, etc.).
It tests a temporary install, a packaged self-test, and uninstall before
creating the tag and publishing both files in GitHub Releases. Runs queue
to avoid version collisions; rerunning an already published commit does not
create a second release. A failed upload can be retried using the same tag
and draft. Repository rules must allow GitHub Actions to create `v*` tags and
publish releases.

Automatic releases currently ship an unsigned installer. Windows SmartScreen
may warn about the publisher; enabling signing requires a code-signing
certificate or service.

Close any already-running Hub, including one launched from the Git checkout,
before installing an update. Setup checks this and does not force-close it.

To build locally, use Windows x64 with CPython 3.12, PyInstaller 6.22.3, Inno
Setup 6.5.4 and Microsoft's official WebView2 Evergreen bootstrapper. From a
build environment, run:

```powershell
python -m pip install --require-hashes -r gui-manager/requirements-win-py312-x64.lock
python -m pip install pyinstaller==6.22.3
.\packaging\windows\build.ps1 -InnoCompiler 'C:\path\ISCC.exe' `
    -WebViewBootstrap 'C:\path\MicrosoftEdgeWebview2Setup.exe'
```

The build verifies the Microsoft signature, bundles Chromium, and checks the
frozen application against a local test page and the bundled plugin CLI before
creating the installer. It writes the EXE and checksum to `artifacts/windows/`.
For local builds only, `-TrustedBrowserCache` can reuse a trusted Playwright
download cache for the exact driver revision. CI downloads a fresh copy.
For a public release, also test installation, first launch and uninstall
in a clean Windows VM under a standard user account, including the scenario
without WebView2.

## Troubleshooting a clean installation

- Setup writes a log to `%TEMP%` by default. To choose its location, run
  `.\AntigravityHub-Setup-x64.exe /LOG="C:\path\hub-setup.log"` in a writable folder.
- The windowed Hub logs startup and patch results to
  `%APPDATA%\AntigravityHub\logs\hub.log`. Review logs for personal paths before sharing.
- The installer does not install OpenCode. The optional OpenCode task creates
  missing starter configuration without replacing existing user configuration.
  Open a project in OpenCode with Antigravity configured before using the patch
  buttons. Hub restores its bundled files only over a matching installed plugin
  version; it does not downgrade newer plugins.
