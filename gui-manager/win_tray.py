"""
Native Windows System Tray implementation using ctypes (Win32 API)
Zero external dependencies, works seamlessly with Tkinter/CustomTkinter.
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
NIIF_ERROR = 0x00000003

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

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

class WindowsTrayIcon:
    def __init__(self, hwnd, title="Antigravity Hub", icon_path=None, on_click=None, on_right_click=None):
        self.hwnd = hwnd
        self.title = title
        self.icon_path = icon_path
        self.on_click = on_click
        self.on_right_click = on_right_click
        self.h_icon = None
        self.is_visible = False

        if icon_path:
            try:
                self.h_icon = ctypes.windll.user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
            except Exception:
                self.h_icon = None

        if not self.h_icon:
            # Load default application icon
            self.h_icon = ctypes.windll.user32.LoadIconW(None, wintypes.LPCWSTR(32512)) # IDI_APPLICATION

    def add(self):
        if self.is_visible:
            return
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
        if not self.is_visible:
            self.add()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        nid.uFlags = NIF_INFO
        nid.szInfo = msg[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_WARNING if is_warning else NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def update_tooltip(self, text):
        if not self.is_visible:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        nid.uFlags = NIF_TIP
        nid.szTip = text[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self):
        if not self.is_visible:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1001
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self.is_visible = False
