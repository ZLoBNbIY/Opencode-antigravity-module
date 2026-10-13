"""
Fully interactive Windows System Tray using a dedicated hidden Win32 message window.
Configured with proper 64-bit / 32-bit Win32 types (LRESULT, LPARAM, WPARAM).
Supports:
- Left Click: restore/toggle window
- Double Click: restore window
- Right Click: native Win32 popup menu (⚡ Открыть, 🔄 Обновить квоты, ✕ Выход)
- Balloon tooltips
Zero external dependencies.
"""

import sys
import ctypes
from ctypes import wintypes
import threading

# Win32 Constants
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002

WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002

TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

# Menu Command IDs
IDM_SHOW = 101
IDM_REFRESH = 102
IDM_EXIT = 103

# Correct 64-bit compatible Win32 types
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

ctypes.windll.user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
ctypes.windll.user32.DefWindowProcW.restype = LRESULT

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WindowsTrayIcon:
    def __init__(self, title="Antigravity Hub", icon_path=None, on_show=None, on_refresh=None, on_exit=None):
        self.title = title
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_refresh = on_refresh
        self.on_exit = on_exit

        self.hwnd = None
        self.h_icon = None
        self.is_visible = False
        self._wndproc = None
        self._thread = None
        self._ready_event = threading.Event()

        if icon_path:
            try:
                self.h_icon = ctypes.windll.user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
            except Exception:
                self.h_icon = None

        if not self.h_icon:
            self.h_icon = ctypes.windll.user32.LoadIconW(None, wintypes.LPCWSTR(32512))

    def start(self):
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=3)

    def _message_loop(self):
        class_name = f"AntigravityTrayWin_{id(self)}"
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAYICON:
                event_type = lparam & 0xFFFF
                if event_type in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    if self.on_show:
                        self.on_show()
                    return 0
                elif event_type == WM_RBUTTONUP:
                    self._show_context_menu(hwnd)
                    return 0
            elif msg == WM_DESTROY:
                ctypes.windll.user32.PostQuitMessage(0)
                return 0
            return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wnd_proc)

        wcex = WNDCLASSEXW()
        wcex.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wcex.style = 0
        wcex.lpfnWndProc = self._wndproc
        wcex.cbClsExtra = 0
        wcex.cbWndExtra = 0
        wcex.hInstance = hinst
        wcex.hIcon = self.h_icon
        wcex.hCursor = None
        wcex.hbrBackground = None
        wcex.lpszMenuName = None
        wcex.lpszClassName = class_name
        wcex.hIconSm = self.h_icon

        ctypes.windll.user32.RegisterClassExW(ctypes.byref(wcex))

        self.hwnd = ctypes.windll.user32.CreateWindowExW(
            0, class_name, "AntigravityTrayWindow",
            0, 0, 0, 0, 0,
            None, None, hinst, None
        )

        self.add()
        self._ready_event.set()

        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _show_context_menu(self, hwnd):
        hmenu = ctypes.windll.user32.CreatePopupMenu()
        ctypes.windll.user32.AppendMenuW(hmenu, MF_STRING, IDM_SHOW, "⚡  Открыть Antigravity Hub")
        ctypes.windll.user32.AppendMenuW(hmenu, MF_STRING, IDM_REFRESH, "🔄  Обновить квоты")
        ctypes.windll.user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        ctypes.windll.user32.AppendMenuW(hmenu, MF_STRING, IDM_EXIT, "✕  Выход")

        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

        ctypes.windll.user32.SetForegroundWindow(hwnd)
        cmd = ctypes.windll.user32.TrackPopupMenu(
            hmenu,
            TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
            pt.x, pt.y,
            0,
            hwnd,
            None
        )
        ctypes.windll.user32.DestroyMenu(hmenu)

        if cmd == IDM_SHOW and self.on_show:
            self.on_show()
        elif cmd == IDM_REFRESH and self.on_refresh:
            self.on_refresh()
        elif cmd == IDM_EXIT and self.on_exit:
            self.on_exit()

    def add(self):
        if not self.hwnd:
            return False
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.h_icon
        nid.szTip = self.title[:127]

        res = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self.is_visible = bool(res)
        return self.is_visible

    def show_balloon(self, title, msg, is_warning=False):
        if not self.hwnd or not self.is_visible:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        nid.uFlags = NIF_INFO
        nid.szInfo = msg[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_WARNING if is_warning else NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self):
        if not self.hwnd or not self.is_visible:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self.is_visible = False
        ctypes.windll.user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
