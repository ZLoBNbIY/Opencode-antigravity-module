# Antigravity Hub for Linux (experimental)

Linux work is isolated on the `linux` Git branch. The Windows release remains on
`V2`; Linux-specific tray code and launch instructions are maintained here.

## Requirements

- OpenCode CLI (`opencode`) installed and available on `PATH`
- Python 3.10+, Tk support, and pip
- A desktop session with a system-tray/AppIndicator implementation
- Node.js, required by the Antigravity CLI

On Debian/Ubuntu, install the OS packages first:

```bash
sudo apt install python3 python3-tk python3-venv python3-pip python3-gi gir1.2-ayatanaappindicator3-0.1
```

Then install the Hub's Python dependencies and start it:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r gui-manager/requirements-linux.txt
bash gui-manager/start_manager.sh
```

If the system tray backend cannot start, closing to tray is prevented so the
window is not hidden with no way to restore it. OpenCode management is best-effort
and targets processes named `opencode` / `opencode-cli`; test it in your desktop
environment before relying on start/stop actions.

## Current scope

The Linux branch adapts the Hub GUI, tray, single-instance lock, path opening,
and OpenCode process checks/actions. Authentication, quotas, custom DNS and the
embedded tunnel use the existing shared implementation. This is an experimental
port; the GUI and tray need validation on real Linux desktop environments
(GNOME, KDE, and Wayland/X11 differ in tray support).
