"""系统托盘图标（Windows，纯标准库 ctypes 实现）。

后台消息线程持有托盘图标；图标左键/右键事件经注入回调通知调用方。
Tk 侧应在回调里用 root.event_generate(...) 切回主线程。
"""

import ctypes
import threading
import traceback
from ctypes import wintypes

# --- Win32 常量 ---
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
WM_APP_TRAY = 0x8001                # WM_APP+1：托盘回调消息
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
# HWND_MESSAGE 是 (HWND)-3：必须以指针宽度传递；裸 Python int 会被 ctypes
# 当 32 位 int 编组，x64 寄存器写入零扩展成 0xFFFFFFFD → CreateWindowExW
# 报 1400 ERROR_INVALID_WINDOW_HANDLE。
HWND_MESSAGE = ctypes.c_void_p(-3)
IDI_INFORMATION = 32515

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


def make_icon_pixels(size=16):
    """size×size BGRA（top-down）：透明底 + 深色圆 + 亮色心。可单测的纯函数。"""
    cx = cy = (size - 1) / 2
    buf = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            i = (y * size + x) * 4
            if d <= 3.5:
                buf[i:i + 4] = b"\xa1\xe3\xa6\xff"     # 亮心 #a6e3a1 (BGRA)
            elif d <= 7.0:
                buf[i:i + 4] = b"\x2e\x1e\x1e\xff"     # 深底 #1e1e2e (BGRA)
    return bytes(buf)


class TrayIcon:
    """托盘图标。回调在消息线程触发，调用方负责切回主线程。"""

    def __init__(self, tip="GLM 用量悬浮窗", on_restore=None, on_menu=None):
        self.tip = tip
        self.on_restore = on_restore
        self.on_menu = on_menu
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._ok = False
        self._hicon = None
        self._hwnd = None
        self._icon_is_shared = False    # LoadIconW 回退的共享图标不可 DestroyIcon
        self._wndproc_ref = None        # 保住回调引用防 GC
        self._class_name = None

    def show(self):
        """创建托盘图标并启动消息线程；成功返回 True（最多等 5 秒）。"""
        if self._thread and self._thread.is_alive():
            return self._ok              # 已有线程在跑：不重复启动（防孤儿图标）
        self._ok = False                 # 清掉上一轮残留，避免误报成功
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self._ok

    def hide(self):
        """移除图标并停止消息线程。"""
        self._stop.set()
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)
            if not self._thread.is_alive():
                self._thread = None      # 只有真正退出才清引用，防孤儿失联

    # ---- 以下均在消息线程内执行 ----
    def _run(self):
        try:
            self._run_inner()
        except Exception:
            traceback.print_exc()        # pythonw 下不可见，控制台开发运行可见
            self._ok = False
            self._ready.set()

    def _run_inner(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # Shell_NotifyIconW 由 shell32 导出；Win11 的 user32 无此前转，
        # 直接 user32.Shell_NotifyIconW 会 AttributeError 被吞成 show()=False
        shell32 = ctypes.windll.shell32
        hinst = kernel32.GetModuleHandleW(None)

        # wparam/lparam 回调进来是 64 位 Python int（如 WM_NCCREATE 的
        # CREATESTRUCT 指针），不声明 argtypes 会被当 32 位 int 编组，
        # 在 DefWindowProcW 里抛 OverflowError。
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_longlong

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_APP_TRAY:
                if lparam == WM_LBUTTONUP and self.on_restore:
                    self.on_restore()
                elif lparam == WM_RBUTTONUP and self.on_menu:
                    self.on_menu()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)
        self._class_name = f"glm_usage_tray_{id(self):x}"
        wc = WNDCLASSW(0, self._wndproc_ref, 0, 0, hinst, None, None,
                       None, None, self._class_name)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._ok = False
            self._ready.set()
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self._build_icon(user32)
        nid.szTip = (self.tip or "")[:127]
        self._hicon = nid.hIcon
        added = False
        try:
            self._hwnd = user32.CreateWindowExW(0, self._class_name, "glm-tray", 0,
                                                0, 0, 0, 0, HWND_MESSAGE, None,
                                                hinst, None)
            if not self._hwnd:
                self._ok = False
                return
            nid.hWnd = self._hwnd

            self._ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
            if not self._ok:
                return
            added = True
            self._ready.set()      # 成功路径立即放行 show()；失败路径由 finally 兜底

            msg = wintypes.MSG()
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            # 成功/失败/异常统一回收注册的窗口类与图标，否则同实例重试会
            # 1410 ERROR_CLASS_ALREADY_EXISTS 永久烧毁
            if added:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
            user32.UnregisterClassW(self._class_name, hinst)   # try 内类必然已注册，无条件注销
            if self._hicon and not self._icon_is_shared:
                user32.DestroyIcon(self._hicon)
            self._hwnd = None
            self._hicon = None
            self._ready.set()      # 所有退出路径统一放行 show() 的等待

    def _build_icon(self, user32):
        """内存位图 → HICON；失败回退系统信息图标（共享，不可 DestroyIcon）。"""
        size = 16
        pixels = make_icon_pixels(size)
        gdi32 = ctypes.windll.gdi32
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size,
                               1, 32, 0, 0, 0, 0, 0, 0)
        ptr = ctypes.c_void_p()
        hbm_color = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0,
                                           ctypes.byref(ptr), None, 0)
        if not hbm_color or not ptr:
            self._icon_is_shared = True
            return user32.LoadIconW(None, IDI_INFORMATION)
        ctypes.memmove(ptr, pixels, len(pixels))
        hbm_mask = gdi32.CreateBitmap(size, size, 1, 1, None)
        ii = ICONINFO(True, 0, 0, hbm_mask, hbm_color)
        hicon = user32.CreateIconIndirect(ctypes.byref(ii))
        gdi32.DeleteObject(hbm_mask)
        gdi32.DeleteObject(hbm_color)
        if hicon:
            self._icon_is_shared = False
            return hicon
        self._icon_is_shared = True
        return user32.LoadIconW(None, IDI_INFORMATION)
