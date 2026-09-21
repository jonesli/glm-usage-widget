# 认证配置文件化 + 右键菜单/托盘 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** token/base_url 从环境变量迁入 config.json（自动迁移 + env 兜底），右键改为弹出菜单（最小化到托盘 / 退出），新增 ctypes 系统托盘图标。

**Architecture:** 配置层扩展 load_config 字符串字段与 resolve_auth 迁移；fetch 传参走 fetch_all 已有的 token/base_url 形参（接口层零改动）；新文件 trayicon.py 用 Shell_NotifyIconW + 后台消息线程实现托盘，事件经 `root.event_generate` 回 Tk 主线程；UsageApp 增加三态（normal/minimized/quit）。

**Tech Stack:** Python 3.12 标准库（tkinter、ctypes、threading、unittest），零第三方依赖。

**Spec:** `docs/superpowers/specs/2026-09-15-auth-config-and-tray-design.md`

**工作目录约定：** 均在 `D:/workspace/ai/glm-usage-widget` 下执行。当前基线 HEAD `35deb9b`，57/57 单测、14/14 e2e 全绿。

**执行约定（用户已授权全程自行判断）：** 每任务提交带 `git add docs/`；发现计划缺陷直接修计划并提交（模式同 2026-09-12 计划）。

**对 spec 的一处实施级简化（不改变行为承诺）：** 托盘菜单为 [恢复, 退出] 两项——spec 原文"在徽章菜单基础上多一项恢复"中的"最小化"项在 minimized 态无意义，省去。

> **审查后加固（P2-Task1 质量审查，①②已实施；③④为待办 ride-along）：** ① TestResolveAuth 四个测试一律使用密闭 env（`hermetic_env` + `clear=True`——注意 patch.dict 不带 clear=True 不会移除已存在的键，过滤会失效）；② 测试内 `open()` 改 with 消除 ResourceWarning；③ **Task 4 待实施**：`_drag_end` 收窄为只持久化 `badge_position`（防止拖动把用户手工删除的 token"复活"写回）；④ **Task 6 待实施**：README 增加"更换 token：直接改 config.json（或清空该字段后重启即重新从 env 迁移）；彻底停用需同时清空 config 字段并移除环境变量"说明。
>
> **审查后加固（P2-Task2 质量审查，随下一个提交落地）：** ⑤ 应用级测试构造 UsageApp 必须用 `patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg)` 隔离（patch `CONFIG_PATH` 无效——`load_config`/`save_config` 的 path 默认参数在定义时绑定），否则全新克隆 + 有 env 的机器上跑测试会把真实 token 写进仓库 config.json；⑥ 零参 fetch 桩改用 `lambda *a, **k: ...` 惯用法；⑦ usage_api 的 env token 读取补 `.strip()`（纯空白 token 不再绕过 NO_TOKEN）；⑧ 计划 Task 2 的面板文案测试已修正为 `show_panel()` 后再 `_apply_data`（`_apply_data` 只重渲染已映射面板）。

---

### Task 1: 配置层——字符串字段 + resolve_auth 迁移

**Files:**
- Modify: `widget.py`（DEFAULTS、load_config、新函数 resolve_auth、import 行）
- Test: `tests/test_widget_helpers.py`

- [ ] **Step 1: 写失败测试**

`tests/test_widget_helpers.py`：from-import 行加入 `resolve_auth`（字母序放 `next_interval_sec` 之后）：

```python
from widget import (
    COL_ALERT, COL_DIM, COL_OK, COL_WARN, DEFAULTS,
    badge_parts, color_for, load_config, next_interval_sec, resolve_auth,
    save_config,
)
```

在 `TestConfig` 类末尾追加两个方法：

```python
    def test_auth_string_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"token": "  abc  ", "base_url": 123}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["token"], "abc")      # strip 后入库
            self.assertEqual(cfg["base_url"], "")      # 非字符串回退默认空串

    def test_auth_missing_fields_default_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_config(os.path.join(d, "nope.json"))
            self.assertEqual(cfg["token"], "")
            self.assertEqual(cfg["base_url"], "")
```

文件末尾（`if __name__ == "__main__":` 之前）追加：

```python
class TestResolveAuth(unittest.TestCase):
    def test_migrates_from_env_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            env = {"ANTHROPIC_AUTH_TOKEN": "  tok-1  ",
                   "ANTHROPIC_BASE_URL": "https://x.example/api/anthropic"}
            with patch.dict(os.environ, env):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "tok-1")
            self.assertEqual(cfg["base_url"], "https://x.example")   # 规范化为协议+域名
            saved = json.load(open(path, encoding="utf-8"))
            self.assertEqual(saved["token"], "tok-1")
            self.assertEqual(saved["base_url"], "https://x.example")

    def test_existing_config_not_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"token": "cfg-token"}, f)
            with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "cfg-token")

    def test_empty_env_leaves_file_unwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
            with patch.dict(os.environ, env, clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "")
            self.assertFalse(os.path.exists(path))

    def test_base_url_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "  https://x.example "}):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["base_url"], "https://x.example")
```

（`patch` 已在测试文件导入。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_widget_helpers -v`
Expected: FAIL，`ImportError: cannot import name 'resolve_auth'`

- [ ] **Step 3: 实现**

`widget.py`：

1. import 区的 usage_api 行改为：

```python
from usage_api import fetch_all, format_tokens, get_base_url
```

2. `DEFAULTS` 字典末尾（`badge_position` 之后）加：

```python
    "token": "",
    "base_url": "",
```

3. `load_config` 的字段分支链（`elif isinstance(val, (int, float)) ...` 之后、`return cfg` 之前）加一个分支：

```python
        elif key in ("token", "base_url"):
            if isinstance(val, str):
                val = val.strip()
                if val:
                    cfg[key] = val
```

4. 在 `load_config` 与 `save_config` 之间追加：

```python
def resolve_auth(cfg, path=CONFIG_PATH):
    """token/base_url 为空时从环境变量迁移写入 config（值不打印）。

    base_url 经 get_base_url 规范化为协议+域名（env 原值带 /api 路径，
    直接传给 fetch_all 会拼错端点）。config 已填的值优先，env 永不覆盖。
    """
    changed = False
    if not cfg.get("token"):
        val = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
        if val:
            cfg["token"] = val
            changed = True
    if not cfg.get("base_url"):
        root = get_base_url()
        if root:
            cfg["base_url"] = root
            changed = True
    if changed:
        save_config(cfg, path)
    return cfg
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest -v`
Expected: 63 tests, all PASS（57 + 6 新增）

- [ ] **Step 5: 提交**

```bash
git add widget.py tests/test_widget_helpers.py docs/
git commit -m "feat: 配置层支持 token/base_url 并支持环境变量自动迁移

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: fetch 接线（cfg 传参）与未配置文案

**Files:**
- Modify: `widget.py`（`_fetch_worker`、`_render_panel` 的 NO_TOKEN 文案、`UsageApp.__init__` 的 cfg 行）
- Test: `tests/test_widget_helpers.py`

- [ ] **Step 1: 写失败测试**

`tests/test_widget_helpers.py` 顶部补 `import tkinter as tk`（若已存在则跳过）；`TestErrorStates` 类末尾追加：

```python
    def test_fetch_uses_config_auth(self):
        root = tk.Tk()
        root.withdraw()
        try:
            captured = {}

            def fake_fetch_all(token=None, base_url=None):
                captured["token"] = token
                captured["base_url"] = base_url
                return {"error": "stop"}

            with patch.object(widget, "fetch_all", fake_fetch_all):
                app = widget.UsageApp(root)
                app.cfg["token"] = "cfg-tok"
                app.cfg["base_url"] = "https://x.example"
                app._fetch_worker()          # 直接调用线程体；after(0) 入队
                root.update()                # 处理队列回调
            self.assertEqual(captured.get("token"), "cfg-tok")
            self.assertEqual(captured.get("base_url"), "https://x.example")

    def test_panel_no_token_mentions_config(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(widget, "fetch_all", lambda: {"error": "off"}):
                app = widget.UsageApp(root)
            app._apply_data({"error": "NO_TOKEN"})
            root.update()
            self.assertIn("config.json", app.p_today.cget("text"))
        finally:
            root.destroy()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_widget_helpers -v`
Expected: FAIL，两个新测试失败（fetch 收到的 token 是 None / 文案仍是环境变量指引）

- [ ] **Step 3: 实现**

`widget.py`：

1. `UsageApp.__init__` 第一处：`self.cfg = load_config()` 改为：

```python
        self.cfg = resolve_auth(load_config())
```

2. `_fetch_worker` 的 `data = fetch_all()` 行改为：

```python
            data = fetch_all(token=self.cfg.get("token") or None,
                             base_url=self.cfg.get("base_url") or None)
```

3. `_render_panel` 的 NO_TOKEN 分支文案改为：

```python
            self.p_today.configure(text="请在 config.json 中设置 token 与 base_url\n"
                                        "（token 不会提交到 git）后重新启动本程序")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest -v`
Expected: 65 tests, all PASS

- [ ] **Step 5: 真实链路冒烟（验证迁移后 fetch 正常）**

Run:
```bash
python -c "import widget; c = widget.resolve_auth(widget.load_config()); from usage_api import fetch_all; d = fetch_all(token=c['token'] or None, base_url=c['base_url'] or None); print('error' in d, sorted(d.keys()))"
```
Expected: `False` + 五个数据键（真实 config 已含迁移的 token）。同时 config.json 出现 token/base_url 字段（不要 cat 出 token 值，只 grep 键名：`grep -c '"token"' config.json` → 1）。

- [ ] **Step 6: 提交**

```bash
git add widget.py tests/test_widget_helpers.py docs/
git commit -m "feat: fetch 使用 config.json 认证，未配置文案指向配置文件

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: trayicon.py——托盘图标（ctypes）

**Files:**
- Create: `trayicon.py`
- Test: `tests/test_trayicon.py`

- [ ] **Step 1: 写失败测试（纯函数部分）**

创建 `tests/test_trayicon.py`：

```python
import unittest

from trayicon import make_icon_pixels


class TestMakeIconPixels(unittest.TestCase):
    def test_size_and_corners_transparent(self):
        buf = make_icon_pixels(16)
        self.assertEqual(len(buf), 16 * 16 * 4)
        self.assertEqual(buf[0:4], b"\x00\x00\x00\x00")        # 角落透明

    def test_center_bright_inner_dark(self):
        buf = make_icon_pixels(16)
        i = (8 * 16 + 8) * 4                                    # 中心：亮心
        self.assertEqual(buf[i:i + 4], b"\xa1\xe3\xa6\xff")
        j = (1 * 16 + 8) * 4                                    # 圆环内：深底
        self.assertEqual(buf[j:j + 4], b"\x2e\x1e\x1e\xff")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_trayicon -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'trayicon'`

- [ ] **Step 3: 实现 trayicon.py**

创建 `trayicon.py`（完整文件）：

```python
"""系统托盘图标（Windows，纯标准库 ctypes 实现）。

后台消息线程持有托盘图标；图标左键/右键事件经注入回调通知调用方。
Tk 侧应在回调里用 root.event_generate(...) 切回主线程。
"""

import ctypes
import threading
from ctypes import wintypes

# --- Win32 常量 ---
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
WM_APP_TRAY = 0x8001                # WM_APP+1：托盘回调消息
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
HWND_MESSAGE = -3
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
        self._wndproc_ref = None        # 保住回调引用防 GC
        self._class_name = None

    def show(self):
        """创建托盘图标并启动消息线程；成功返回 True（最多等 5 秒）。"""
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
        self._thread = None

    # ---- 以下均在消息线程内执行 ----
    def _run(self):
        try:
            self._run_inner()
        except Exception:
            self._ok = False
            self._ready.set()

    def _run_inner(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hinst = kernel32.GetModuleHandleW(None)

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
        self._hwnd = user32.CreateWindowExW(0, self._class_name, "glm-tray", 0,
                                            0, 0, 0, 0, HWND_MESSAGE, None,
                                            hinst, None)
        if not self._hwnd:
            self._ok = False
            self._ready.set()
            return

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self._build_icon(user32)
        nid.szTip = self.tip
        self._hicon = nid.hIcon
        self._ok = bool(user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        self._ready.set()
        if not self._ok:
            return

        msg = wintypes.MSG()
        while not self._stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        user32.DestroyWindow(self._hwnd)
        user32.UnregisterClassW(self._class_name, hinst)
        if self._hicon:
            user32.DestroyIcon(self._hicon)
        self._hwnd = None
        self._hicon = None

    @staticmethod
    def _build_icon(user32):
        """内存位图 → HICON；失败回退系统信息图标。"""
        size = 16
        pixels = make_icon_pixels(size)
        gdi32 = ctypes.windll.gdi32
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size,
                               1, 32, 0, 0, 0, 0, 0, 0)
        ptr = ctypes.c_void_p()
        hbm_color = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0,
                                           ctypes.byref(ptr), None, 0)
        if not hbm_color or not ptr:
            return user32.LoadIconW(None, IDI_INFORMATION)
        ctypes.memmove(ptr, pixels, len(pixels))
        hbm_mask = gdi32.CreateBitmap(size, size, 1, 1, None)
        ii = ICONINFO(True, 0, 0, hbm_mask, hbm_color)
        hicon = user32.CreateIconIndirect(ctypes.byref(ii))
        gdi32.DeleteObject(hbm_mask)
        gdi32.DeleteObject(hbm_color)
        return hicon or user32.LoadIconW(None, IDI_INFORMATION)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest -v`
Expected: 69 tests, all PASS（66 + 2 纯函数 + 1 孤儿防护；质量审查加固后）

- [ ] **Step 5: 真实托盘冒烟（创建→存活→移除，屏幕右下角会出现图标数秒）**

```bash
PYTHONIOENCODING=utf-8 python -c "
import time, trayicon
fired = []
t = trayicon.TrayIcon(tip='e2e-smoke', on_restore=lambda: fired.append('r'),
                      on_menu=lambda: fired.append('m'))
assert t.show() is True, 'show 失败'
time.sleep(2)
t.hide()
print('TRAY SMOKE OK')
"
```
Expected: `TRAY SMOKE OK`（真实点击无法自动化；事件回调由 Task 5 的 e2e 直接调用验证）

- [ ] **Step 6: 提交**

```bash
git add trayicon.py tests/test_trayicon.py docs/
git commit -m "feat: ctypes 系统托盘图标（Shell_NotifyIcon 消息线程方案）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

> **审查修正（P2-Task3 实现发现计划代码 3 处 ctypes x64 编组 bug，已修复并经 spec 审查独立复现验证）：** ① `HWND_MESSAGE = ctypes.c_void_p(-3)`（裸 int 在 x64 被零扩展为 0xFFFFFFFD，CreateWindowExW 报 err 1400）；② `user32.DefWindowProcW` 需声明 argtypes/restype（否则 WM_CREATE 的 64 位 CREATESTRUCT 指针在回调内抛 ArgumentError 中止窗口创建）；③ `Shell_NotifyIconW` 从 `ctypes.windll.shell32` 调用（本机 user32 不导出，且异常会被 `_run` 的 except 吞成 show()=False）。**计划正文的 Task 3 代码以这三处修正为准，勿回退。**

> **审查后加固（P2-Task3 质量审查，随 Task 4 落地）：** ① trayicon 的 `UnregisterClassW` 移出 `if self._hwnd:` 守卫（类注册成功但建窗失败时类泄漏、实例烧毁——try 内类必然已注册，无条件注销即可），并在 TestShowGuard 补 `t._thread is th` 不变量断言；② **Task 4 ride-along（落实 P2-Task1 审查遗留项③）**：`_drag_end` 保存改为"以磁盘文件为基底合并"——`load_config(CONFIG_PATH)` 显式传当前值（调用时求值，可测试），仅覆盖四个运行时键，磁盘上的 token/base_url 原样保留（用户手工删除不被复活）。③ TaskbarCreated 重建（explorer 崩溃后图标消失）明确推迟到后续加固，不在本计划。

### Task 4: UsageApp 三态——右键菜单 / 最小化 / 恢复 / quit_app

**Files:**
- Modify: `widget.py`（import、`UsageApp.__init__`、徽章/面板 Button-3 绑定、新增方法）
- Test: `tests/test_widget_helpers.py`

- [ ] **Step 1: 写失败测试**

`tests/test_widget_helpers.py`：from-import 行无需变化；文件末尾（`if __name__` 之前）追加：

```python
class TestTrayStates(unittest.TestCase):
    def _make_app(self):
        root = tk.Tk()
        root.withdraw()
        with patch.object(widget, "fetch_all", lambda: {"error": "off"}):
            app = widget.UsageApp(root)
        root.update()
        return root, app

    def test_badge_menu_has_two_items(self):
        root, app = self._make_app()
        try:
            labels = [app.badge_menu.entrycget(i, "label")
                      for i in range(app.badge_menu.index("end") + 1)]
            self.assertEqual(labels, ["最小化到系统任务栏", "退出"])
        finally:
            root.destroy()

    def test_tray_menu_items(self):
        root, app = self._make_app()
        try:
            labels = [app.tray_menu.entrycget(i, "label")
                      for i in range(app.tray_menu.index("end") + 1)]
            self.assertEqual(labels, ["恢复", "退出"])
        finally:
            root.destroy()

    def test_minimize_hides_badge_and_creates_tray(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = True
                app.minimize_to_tray()
                root.update()
            self.assertTrue(app.minimized)
            self.assertFalse(bool(app.badge.winfo_ismapped()))
            FakeTray.return_value.hide.assert_not_called()
        finally:
            root.destroy()

    def test_restore_shows_badge_and_hides_tray(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = True
                app.minimize_to_tray()
                root.update()
                app.restore_from_tray()
                root.update()
            self.assertFalse(app.minimized)
            self.assertTrue(bool(app.badge.winfo_ismapped()))
            FakeTray.return_value.hide.assert_called_once()
        finally:
            root.destroy()

    def test_minimize_failure_keeps_badge_visible(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = False
                app.minimize_to_tray()
                root.update()
            self.assertFalse(app.minimized)
            self.assertTrue(bool(app.badge.winfo_ismapped()))
            self.assertEqual(app.badge_menu.index("end"), 0)   # 只剩"退出"
        finally:
            root.destroy()

    def test_quit_app_hides_tray_then_destroys(self):
        root, app = self._make_app()
        with patch.object(widget, "TrayIcon") as FakeTray:
            FakeTray.return_value.show.return_value = True
            app.minimize_to_tray()
            root.update()
            app.quit_app()
            FakeTray.return_value.hide.assert_called_once()
            with self.assertRaises(tk.TclError):
                root.update()          # root 已销毁
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_widget_helpers -v`
Expected: FAIL，`AttributeError: 'UsageApp' object has no attribute 'badge_menu'`

- [ ] **Step 3: 实现**

`widget.py`：

1. import 区加（`import tkinter as tk` 之后）：`from trayicon import TrayIcon`

2. `UsageApp.__init__` 改为（新增 4 行 + 2 个 bind）：

```python
    def __init__(self, root):
        self.root = root
        self.cfg = resolve_auth(load_config())
        self.data = None          # 最近一次成功数据
        self.latest = None        # 最新一次拉取结果（含错误态）
        self.failures = 0
        self.last_ok = "--:--"
        self.hide_job = None
        self._dragging = False
        self._drag_dx = self._drag_dy = 0
        self.minimized = False
        self._tray = None
        self._build_menus()
        self._build_badge()
        self._build_panel()
        self._apply_position()
        self.root.bind("<<TrayRestore>>", lambda e: self.restore_from_tray())
        self.root.bind("<<TrayMenu>>", lambda e: self.show_tray_menu())
        self.root.after(200, self.refresh)
```

3. 徽章绑定：`self.badge.bind("<Button-3>", lambda e: self.root.destroy())` 改为

```python
        self.badge.bind("<Button-3>", self.popup_badge_menu)
```

面板绑定：`self.panel.bind("<Button-3>", lambda e: self.root.destroy())` 改为

```python
        self.panel.bind("<Button-3>", self.popup_badge_menu)
```

4. 在 `_build_panel` 之前加菜单构建，在 `hide_panel` 之后加三态方法：

```python
    # ---------- 右键菜单与托盘三态 ----------
    def _build_menus(self):
        self.badge_menu = tk.Menu(self.root, tearoff=0)
        self.badge_menu.add_command(label="最小化到系统任务栏",
                                    command=self.minimize_to_tray)
        self.badge_menu.add_command(label="退出", command=self.quit_app)
        self.tray_menu = tk.Menu(self.root, tearoff=0)
        self.tray_menu.add_command(label="恢复", command=self.restore_from_tray)
        self.tray_menu.add_command(label="退出", command=self.quit_app)

    def popup_badge_menu(self, e=None):
        try:
            self.badge_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.badge_menu.grab_release()

    def show_tray_menu(self):
        """托盘右键：在屏幕右下角（托盘附近）弹菜单。"""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        try:
            self.tray_menu.tk_popup(sw - 160, sh - 140)
        finally:
            self.tray_menu.grab_release()

    def minimize_to_tray(self):
        if self.minimized:
            return
        if self._tray is None:
            self._tray = TrayIcon(
                tip="GLM 用量悬浮窗",
                on_restore=lambda: self.root.event_generate("<<TrayRestore>>"),
                on_menu=lambda: self.root.event_generate("<<TrayMenu>>"),
            )
        if not self._tray.show():
            log("托盘图标创建失败，右键菜单已移除最小化项")
            self._tray = None
            try:
                self.badge_menu.delete(0)      # 只剩"退出"
            except tk.TclError:
                pass
            return
        self.minimized = True
        self.hide_panel()
        self.badge.withdraw()

    def restore_from_tray(self):
        if not self.minimized:
            return
        self.minimized = False
        if self._tray:
            self._tray.hide()
        self.badge.deiconify()

    def quit_app(self):
        try:
            if self._tray:
                self._tray.hide()
        except Exception as exc:
            log(f"托盘清理异常: {exc!r}")
        self.root.destroy()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest -v`
Expected: 75 tests, all PASS（69 + 6 新增）

- [ ] **Step 5: 快速冒烟（屏幕上会出现徽章；右键应弹菜单而非退出）**

```bash
PYTHONIOENCODING=utf-8 python -c "
import tkinter as tk, widget
r = tk.Tk(); r.withdraw()
app = widget.UsageApp(r)
r.update()
app.minimize_to_tray(); r.update()
print('minimized:', app.minimized, '| badge hidden:', not app.badge.winfo_ismapped())
app.restore_from_tray(); r.update()
print('restored:', not app.minimized, '| badge mapped:', bool(app.badge.winfo_ismapped()))
app.quit_app()
print('STATES OK')
"
```
Expected: `minimized: True | badge hidden: True` / `restored: True | badge mapped: True` / `STATES OK`（期间右下角托盘图标出现又消失）

- [ ] **Step 6: 提交**

```bash
git add widget.py tests/test_widget_helpers.py docs/
git commit -m "feat: 右键菜单（最小化到托盘/退出）与托盘三态

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

> **审查后修复（P2-Task4 质量审查 fix-first，已实施）：** ① **C1**：托盘左键恢复经 event_generate 同步封送，绑定内 `tray.hide()` join 消息线程形成循环等待（实测冻结 3.01s）——`restore_from_tray` 改为先 deiconify、再 `root.after(0, tray.hide)` 延后清理并置 `_tray=None`；② **I1**：`hide()` 首行置 `_ok=False`（超时后 show() 不得谎报成功——"藏起来找不回"死局）；③ **I2**：`_drag_end` 改为直接读盘 JSON（严格失败→log+跳过保存），不再用可能为默认值的合并基底覆盖真实凭据；顺带保留磁盘未知键；④ M2 修正：show() 失败不再删除菜单项（每次点击自然重试，spec 意图"绝不藏起来找不回"保持）；⑤ M3：minimize 前 `_cancel_hide()`；⑥ M4：托盘菜单位置改 `winfo_pointerxy()`；⑦ M5(e)：刷新定时器改存句柄、重排时取消旧任务、quit_app 取消；⑧ M6：trayicon 的 `_build_icon` 移入 try。**Task 5 的 T13 必须走真实桥接并限时断言（上文已改），直接调用 restore_from_tray 无法发现 C1 类回归。** 新增 3 个单测：桥接 lambda、restore 幂等、拖动读盘失败跳过保存。

### Task 5: e2e 验收改造与新增

**Files:**
- Modify: `tests/e2e_acceptance.py`

- [ ] **Step 1: 新增 --auth 子进程模式**

`widget.py` 无改动。在 `tests/e2e_acceptance.py` 中，`run_memory` 之后加：

```python
def run_auth():
    """子进程：备份真实 config → 假 env 触发迁移 → 断言写入与 ⚠ → 恢复备份。"""
    cfg_path = widget.CONFIG_PATH
    backup = None
    if os.path.exists(cfg_path):
        backup = open(cfg_path, "rb").read()
    try:
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
        env["ANTHROPIC_AUTH_TOKEN"] = "e2e-fake-token"
        env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
        env["PYTHONIOENCODING"] = "utf-8"
        code = f"""
import sys, tkinter as tk
sys.path.insert(0, r'{APP_DIR}')
import widget
root = tk.Tk(); root.withdraw()
app = widget.UsageApp(root)
deadline = __import__('time').time() + 12
def poll():
    txt = app.lb_5h.cget('text')
    if txt.startswith('…') and __import__('time').time() < deadline:
        root.after(250, poll); return
    try:
        written = 'e2e-fake-token' in open(widget.CONFIG_PATH, encoding='utf-8').read()
    except OSError:
        written = False
    ok = written and txt.startswith('⚠')
    print(('PASS ' if ok else 'FAIL ') + f'T14 认证迁移 | badge={{txt}} written={{written}}', flush=True)
    if not ok:
        _fails.append('T14 认证迁移')
    root.destroy()
_fails = []
app.refresh()
root.after(250, poll)
root.mainloop()
if _fails:
    sys.stdout.flush(); __import__('os')._exit(1)
sys.stdout.flush(); __import__('os')._exit(0)
"""
        subprocess.run([sys.executable, "-c", code], env=env, cwd=APP_DIR, timeout=40)
    finally:
        if backup is not None:
            open(cfg_path, "wb").write(backup)
        elif os.path.exists(cfg_path):
            os.remove(cfg_path)
```

（子进程打印以 PASS/FAIL 开头即可被汇总识别；备份恢复放 finally，保证主流程 config 不被假 token 污染。）

- [ ] **Step 2: 改造 run_e2e 的收尾段**

把现有"T7 右键退出"块（`app.badge.event_generate("<Button-3>")` 起）整体替换为：

```python
    # T11 右键菜单（不再直接退出）
    app.badge.event_generate("<Button-3>")
    root.update()
    check("T11a 菜单弹出", bool(app.badge_menu.winfo_ismapped()))
    labels = [app.badge_menu.entrycget(i, "label")
              for i in range(app.badge_menu.index("end") + 1)]
    check("T11b 菜单项", labels == ["最小化到系统任务栏", "退出"], str(labels))
    app.badge_menu.unpost()
    root.update()

    # T12 最小化到托盘（真实 Shell_NotifyIcon，右下角会短暂出现图标）
    app.minimize_to_tray()
    root.update()
    check("T12a 最小化状态", app.minimized and not app.badge.winfo_ismapped())
    check("T12b 托盘图标创建", app._tray is not None and app._tray._ok)

    # T13 托盘恢复——必须走真实桥接（PostMessage → 消息线程 → event_generate → 绑定），
    # 并限时断言（<0.5s 映射），防止"恢复冻结 3 秒"（C1）回归。直接调 restore_from_tray()
    # 无法发现该类回归（消息线程空闲时 join 立即返回）。
    tray_hwnd = app._tray._hwnd
    user32 = ctypes.windll.user32
    user32.PostMessageW(tray_hwnd, 0x8001, 0, 0x0202)   # WM_APP_TRAY + WM_LBUTTONUP
    t0 = time.time()
    while not app.badge.winfo_ismapped() and time.time() - t0 < 2:
        root.update()
    check("T13 托盘恢复(真实桥接<0.5s)",
          (not app.minimized) and bool(app.badge.winfo_ismapped()) and (time.time() - t0) < 0.5,
          f"elapsed={time.time() - t0:.2f}s")

    # T7 退出（走 quit_app：含托盘清理）
    app.quit_app()
    try:
        root.update()
        gone = False
    except tk.TclError:
        gone = True
    check("T7 退出(quit_app)", gone)
```

（原 T7 的 try/except `winfo_exists` 断言删除——销毁后 update 直接抛 TclError，即上面的 gone 判定。）

- [ ] **Step 3: main() 挂载新子进程**

`main()` 中无参主流程里，`subprocess.run(... "--offline" ...)` 之后、`--memory` 之前插入：

```python
    if "--auth" in sys.argv:
        run_auth()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)
```

（放在 `if "--offline"` 分支之后定义顺序即可；主流程在 offline 之前加：）

```python
    subprocess.run([sys.executable, os.path.abspath(__file__), "--auth"], env=env,
                   cwd=APP_DIR, timeout=40)
```

注意：`--auth` 与 offline 共用同一份 `env` 字典（都覆盖 BASE_URL），但 `run_auth` 内部已自行构造 env，主流程里直接把同一 env 传入亦可。

- [ ] **Step 4: 运行全量 e2e**

Run: `PYTHONIOENCODING=utf-8 python tests/e2e_acceptance.py`
Expected: 原 14 项全部 PASS + 新增 T11a/T11b/T12a/T12b/T13/T14 共 6 项 PASS，`== E2E 验收全部通过 ==`，EXIT=0

- [ ] **Step 5: 提交**

```bash
git add tests/e2e_acceptance.py docs/
git commit -m "test: e2e 覆盖右键菜单/托盘三态/认证迁移

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: README 更新与全量回归

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 定向更新**

1. "## 启动"一节的前提段替换为：

```markdown
前提：认证配置在 config.json 的 `token` / `base_url` 字段（该文件不会提交到 git）。
首次启动会自动从环境变量 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` 迁移写入；
环境变量仅作为兜底（config 未填时生效）。未配置时徽章显示"未配置"。
```

2. "## 操作"表替换为：

```markdown
| 操作 | 效果 |
|------|------|
| 鼠标悬停徽章 | 展开详细面板 |
| 移出面板 | 约 0.5s 后自动收回 |
| 左键拖动 | 移动位置（松手自动保存） |
| 右键徽章/面板 | 弹出菜单：最小化到系统任务栏 / 退出 |
| 托盘图标左键 | 恢复徽章 |
| 托盘图标右键 | 菜单：恢复 / 退出 |
```

3. "## 配置"表追加两行（badge_position 之后）：

```markdown
| token | （空） | 接口认证 token，自动从环境变量迁移；不会提交到 git |
| base_url | （空） | 接口域名（协议+域名即可），同样自动迁移 |
```

4. "## 行为说明"列表追加一条：

```markdown
- **最小化到托盘**：徽章隐藏后通知区域（右下角）出现图标，后台轮询照常；
  左键图标恢复。托盘创建失败时右键菜单会移除最小化项（不会藏起来找不回）。
```

5. "## 测试"节数量更新：

```markdown
```bash
python -m unittest -v                      # 75 项单元/组件测试
python tests/e2e_acceptance.py             # 20 项端到端验收（屏幕会闪现窗口/托盘图标）
```
```

- [ ] **Step 2: 全量回归**

Run: `python -m unittest -v` → Expected: 73/73 PASS
Run: `PYTHONIOENCODING=utf-8 python tests/e2e_acceptance.py` → Expected: 全部 PASS，EXIT=0

- [ ] **Step 3: 提交**

```bash
git add README.md docs/
git commit -m "docs: README 更新认证配置与托盘操作说明

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 手动验收总清单（对照 spec，全部已自动化进 e2e）

- [ ] config.json 迁移写入 token/base_url，env 兜底仍有效（T14 + 单测）
- [ ] 右键弹出两项菜单而非直接退出（T11）
- [ ] 最小化后徽章消失、托盘图标出现（T12，真实 Shell_NotifyIcon）
- [ ] 托盘左键恢复徽章（T13；真实点击路径经 TrayRestore 事件，e2e 直调 restore_from_tray 覆盖状态机）
- [ ] 退出无孤儿托盘图标（quit_app 先 hide）
- [ ] 未配置时指引指向 config.json（单测）
- [ ] 既有 57 项测试与既有 e2e 全部不回归（旧 T7 由 T11/T7 新版替代）
