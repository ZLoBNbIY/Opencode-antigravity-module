"""Linux system-tray integration, kept separate from the Win32 tray backend."""

import shutil
import subprocess


class LinuxTrayIcon:
    def __init__(self, title="Antigravity Hub", icon_path=None, on_show=None, on_refresh=None, on_exit=None):
        self.title = title
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_refresh = on_refresh
        self.on_exit = on_exit
        self.icon = None
        self.is_visible = False

    def start(self):
        import pystray
        from PIL import Image

        image = Image.open(self.icon_path) if self.icon_path else Image.new("RGBA", (64, 64), (2, 132, 199, 255))

        def invoke(callback):
            return lambda _icon, _item: callback() if callback else None

        menu = pystray.Menu(
            pystray.MenuItem("Открыть Antigravity Hub", invoke(self.on_show), default=True),
            pystray.MenuItem("Обновить квоты", invoke(self.on_refresh)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", invoke(self.on_exit)),
        )
        self.icon = pystray.Icon("antigravity-hub", image, self.title, menu)
        self.icon.run_detached()
        self.is_visible = True

    def show_balloon(self, title, message):
        notify_send = shutil.which("notify-send")
        if notify_send:
            try:
                subprocess.Popen([notify_send, title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def remove(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.is_visible = False
