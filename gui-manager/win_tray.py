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
WM_CLOSE = 0x0010
_START_TIMEOUT = 3

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
WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _shell32 = ctypes.windll.shell32

    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = LRESULT
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    _user32.LoadIconW.restype = wintypes.HICON
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL
    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.UnregisterClassW.restype = wintypes.BOOL
    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    _user32.AppendMenuW.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    _user32.TrackPopupMenu.restype = wintypes.BOOL
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.DestroyMenu.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = wintypes.BOOL
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL

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


class WindowsTrayIcon:
    def __init__(self, title="AI HUB", icon_path=None, on_show=None, on_refresh=None, on_exit=None):
        self.title = title
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_refresh = on_refresh
        self.on_exit = on_exit

        self.hwnd = None
        self.h_icon = None
        self._owns_icon = False
        self._class_name = None
        self._hinst = None
        self.is_visible = False
        self._wndproc = None
        self._thread = None
        self._startup_done = threading.Event()
        self._state_lock = threading.RLock()
        self._stop_requested = False

    def _load_icon(self):
        if self.icon_path:
            try:
                self.h_icon = ctypes.windll.user32.LoadImageW(
                    None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
                if self.h_icon:
                    self._owns_icon = True
            except Exception:
                self.h_icon = None

        if not self.h_icon:
            self.h_icon = ctypes.windll.user32.LoadIconW(None, wintypes.LPCWSTR(32512))

    def start(self) -> bool:
        """Return True only after Windows has added the tray icon.

        False means the window must remain accessible without the tray. Timed-out
        startup is cancelled; use a new instance to retry a failed or stopped tray.
        """
        if sys.platform != "win32":
            return False
        with self._state_lock:
            if self._stop_requested:
                return False
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                try:
                    self._thread.start()
                except RuntimeError:
                    self._stop_requested = True
                    self._startup_done.set()
                    return False
        self._startup_done.wait(timeout=_START_TIMEOUT)
        with self._state_lock:
            if not self._startup_done.is_set():
                self._stop_requested = True
            return not self._stop_requested and self.is_visible

    def _run(self):
        try:
            self._message_loop()
        finally:
            try:
                with self._state_lock:
                    hwnd = self.hwnd
                    self._stop_requested = True
                    self._delete_icon()
                    self.hwnd = None
                if hwnd:
                    ctypes.windll.user32.DestroyWindow(hwnd)
                if self._class_name:
                    ctypes.windll.user32.UnregisterClassW(self._class_name, self._hinst)
                if self._owns_icon and self.h_icon:
                    ctypes.windll.user32.DestroyIcon(self.h_icon)
                self.h_icon = None
                self._owns_icon = False
            finally:
                self._startup_done.set()

    def _message_loop(self):
        self._load_icon()
        if not self.h_icon:
            return
        class_name = f"AntigravityTrayWin_{id(self)}"
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAYICON:
                    event_type = lparam & 0xFFFF
                    if event_type in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        if self.on_show:
                            threading.Thread(target=self.on_show, daemon=True).start()
                        return 0
                    elif event_type == WM_RBUTTONUP:
                        self._show_context_menu(hwnd)
                        return 0
                elif msg in (WM_CLOSE, WM_DESTROY):
                    ctypes.windll.user32.PostQuitMessage(0)
                    return 0
                res = ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
                return 0 if res is None else res
            except Exception:
                return 0

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

        ctypes.windll.user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        ctypes.windll.user32.RegisterClassExW.restype = wintypes.ATOM
        if not ctypes.windll.user32.RegisterClassExW(ctypes.byref(wcex)):
            return
        self._class_name = class_name
        self._hinst = hinst

        hwnd = ctypes.windll.user32.CreateWindowExW(
            0, class_name, "AntigravityTrayWindow",
            0, 0, 0, 0, 0,
            None, None, hinst, None
        )
        with self._state_lock:
            self.hwnd = hwnd
            if not self.hwnd or self._stop_requested:
                return

        if not self.add():
            return
        with self._state_lock:
            if self._stop_requested:
                return
            self._startup_done.set()

        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _show_context_menu(self, hwnd):
        hmenu = ctypes.windll.user32.CreatePopupMenu()
        ctypes.windll.user32.AppendMenuW(hmenu, MF_STRING, IDM_SHOW, "⚡  Открыть AI HUB")
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
        ctypes.windll.user32.PostMessageW(hwnd, 0, 0, 0)
        ctypes.windll.user32.DestroyMenu(hmenu)

        if cmd == IDM_SHOW and self.on_show:
            threading.Thread(target=self.on_show, daemon=True).start()
        elif cmd == IDM_REFRESH and self.on_refresh:
            threading.Thread(target=self.on_refresh, daemon=True).start()
        elif cmd == IDM_EXIT and self.on_exit:
            threading.Thread(target=self.on_exit, daemon=True).start()

    def add(self):
        with self._state_lock:
            if not self.hwnd:
                return False
            hwnd = self.hwnd
            h_icon = self.h_icon
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1001
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = h_icon
        nid.szTip = self.title[:127]

        res = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        with self._state_lock:
            self.is_visible = bool(res)
            return self.is_visible

    def show_balloon(self, title, msg, is_warning=False):
        with self._state_lock:
            if not self.hwnd or not self.is_visible:
                return
            hwnd = self.hwnd
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1001
        nid.uFlags = NIF_INFO
        nid.szInfo = msg[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_WARNING if is_warning else NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _delete_icon(self):
        with self._state_lock:
            if self.hwnd and self.is_visible:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = self.hwnd
                nid.uID = 1001
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                self.is_visible = False

    def remove(self):
        if sys.platform != "win32":
            return
        with self._state_lock:
            thread = self._thread
            if self._stop_requested:
                already_stopping = True
            else:
                already_stopping = False
                self._stop_requested = True
                if self._startup_done.is_set() and self.hwnd:
                    self._delete_icon()
                    ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if not already_stopping and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
