"""GLM Coding Plan 用量悬浮窗（tkinter）。置顶徽章 + 悬停展开面板。"""

import json
import math
import os
import sys
import threading
import time
import urllib.parse
from datetime import datetime
import tkinter as tk

from trayicon import TrayIcon
from usage_api import fetch_all, format_tokens, get_base_url


def _app_dir():
    """配置/日志所在目录：源码运行=源码目录；打包运行=exe 所在目录。

    PyInstaller 单文件模式下 __file__ 指向临时解压目录，直接用会把
    config.json 写进临时目录导致配置丢失——必须以 sys.executable 为准。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "widget.log")

DEFAULTS = {
    "refresh_interval_sec": 60,
    "alert_threshold": 80,
    "warn_threshold": 50,
    "badge_position": [80, 80],
    "token": "",
    "base_url": "",
}

BACKOFF_SEC = 300
DEFAULT_BASE_URL = "https://open.bigmodel.cn"


def _normalize_base_url(url):
    """base_url 规范化为协议+域名；无协议自动补 https；非法返回空串。"""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if not (parts.scheme and parts.netloc):
        return ""
    return f"{parts.scheme}://{parts.netloc}"

BG = "#1e1e2e"        # 深色底
FG = "#cdd6f4"        # 主文字
COL_DIM = "#9399b2"   # 次要文字
COL_OK = "#a6e3a1"    # 绿
COL_WARN = "#f9e2af"  # 黄
COL_ALERT = "#f38ba8" # 红
FONT = ("Microsoft YaHei UI", 9)
RESET_FONT = ("Microsoft YaHei UI", 8)   # 重置时间等次要小字


def log(msg):
    """追加日志；超过 1MB 删掉重写。日志失败静默（不能影响 UI）。"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1_000_000:
            os.remove(LOG_PATH)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def color_for(pct, warn, alert):
    """阈值着色：<warn 绿，>=warn 黄，>=alert 红。"""
    if pct >= alert:
        return COL_ALERT
    if pct >= warn:
        return COL_WARN
    return COL_OK


def next_interval_sec(failures, base):
    """连续失败 >=3 次把间隔放宽到 BACKOFF_SEC（不低于用户配置值）。"""
    return max(base, BACKOFF_SEC) if failures >= 3 else base


def humanize_reset(ms, now_ms=None):
    """nextResetTime（毫秒时间戳）-> '3小时后重置'；过期/缺失返回友好文案。"""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    try:
        delta_s = (float(ms) - float(now_ms)) / 1000
    except (TypeError, ValueError):
        return ""
    if delta_s <= 0:
        return "即将重置"
    if delta_s >= 86400:
        return f"{int(delta_s // 86400)}天后重置"
    if delta_s >= 3600:
        return f"{int(delta_s // 3600)}小时后重置"
    return f"{max(1, int(delta_s // 60))}分钟后重置"


def badge_parts(data, last_ok, warn=50, alert=80):
    """徽章上的 (文字, 颜色) 列表。data 为 None=尚未拉取，含 error=异常态。"""
    if data is None:
        return [("⚡ …", COL_DIM)]
    err = data.get("error")
    if err in ("NO_TOKEN", "NO_BASE_URL"):
        return [("⚡ 未配置", COL_WARN)]
    if err:
        return [(f"⚠ {last_ok}", COL_WARN)]
    wins = data.get("token_windows") or []
    pct5 = None
    for w in wins:
        if str(w.get("label", "")).startswith("5小时"):
            pct5 = w.get("percentage", 0.0)     # 徽章只看约束最强的 5 小时窗口
            break
    if pct5 is None:                            # 无语义标签时退回最大值（旧数据兼容）
        pct5 = max([w.get("percentage", 0.0) for w in wins], default=0.0)
    mcp_pct = (data.get("mcp") or {}).get("percentage", 0.0)
    return [
        (f"5h:{pct5:.0f}%", color_for(pct5, warn, alert)),
        (f"MCP:{mcp_pct:.0f}%", color_for(mcp_pct, warn, alert)),
    ]


def load_config(path=CONFIG_PATH):
    """读配置；文件缺失/损坏/字段非法一律回退默认值。"""
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    for key, default in DEFAULTS.items():
        val = data.get(key, default)
        if key == "badge_position":
            if (isinstance(val, list) and len(val) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in val)):
                cfg[key] = [int(val[0]), int(val[1])]
        elif key in ("token", "base_url"):
            if isinstance(val, str):
                val = val.strip()
                if val:
                    cfg[key] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            if key != "refresh_interval_sec":
                cfg[key] = val
            elif int(val) > 0:
                cfg[key] = int(val)
    # 阈值倒置视为配置错误，两者整体回退默认
    if cfg["alert_threshold"] <= cfg["warn_threshold"]:
        cfg["alert_threshold"] = DEFAULTS["alert_threshold"]
        cfg["warn_threshold"] = DEFAULTS["warn_threshold"]
    return cfg


def resolve_auth(cfg, path=CONFIG_PATH):
    """token/base_url 为空时从环境变量迁移写入 config（值不打印）。

    base_url 统一规范化为协议+域名：env 原值与手填值都可能带路径
    （如 /api、/api/anthropic），不剥离会与接口路径拼重复导致 404。
    config 已填的值优先（仅做规范化），env 永不覆盖。
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
    elif "/" in cfg["base_url"].split("://", 1)[-1]:
        normalized = _normalize_base_url(cfg["base_url"])
        if normalized:
            cfg["base_url"] = normalized
            changed = True
    if changed:
        save_config(cfg, path)
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        log(f"写入配置失败: {exc}")


class UsageApp:
    def __init__(self, root):
        self.root = root
        self.cfg = resolve_auth(load_config())
        self.data = None          # 最近一次成功数据
        self.latest = None        # 最新一次拉取结果（含错误态），徽章据此渲染 ⚠/未配置
        self.failures = 0
        self.last_ok = "--:--"
        self.hide_job = None
        self._dragging = False
        self._drag_dx = self._drag_dy = 0
        self.minimized = False
        self._tray = None
        self._tray_parking = None
        self._build_menus()
        self._build_badge()
        self._build_panel()
        self._apply_position()
        self.root.bind("<<TrayRestore>>", lambda e: self.restore_from_tray())
        self.root.bind("<<TrayMenu>>", lambda e: self.show_tray_menu())
        self._refresh_job = self.root.after(200, self.refresh)

    # ---------- 徽章 ----------
    def _build_badge(self):
        self.badge = tk.Toplevel(self.root)
        self.badge.overrideredirect(True)
        self.badge.attributes("-topmost", True)
        self.badge.attributes("-alpha", 0.92)
        self.badge.configure(bg=BG)
        bar = tk.Frame(self.badge, bg=BG)
        bar.pack(fill="both", expand=True, padx=8, pady=4)
        self.lb_icon = tk.Label(bar, text="⚡", font=FONT, bg=BG, fg=COL_DIM)
        self.lb_5h = tk.Label(bar, text="…", font=FONT, bg=BG, fg=COL_DIM)
        lb_sep = tk.Label(bar, text="│", font=FONT, bg=BG, fg=COL_DIM)
        self.lb_mcp = tk.Label(bar, text="…", font=FONT, bg=BG, fg=COL_DIM)
        self.lb_icon.pack(side="left")
        self.lb_5h.pack(side="left")
        lb_sep.pack(side="left", padx=3)
        self.lb_mcp.pack(side="left")
        # 交互：拖动 / 悬停展开 / 右键弹菜单（最小化/退出）
        self.badge.bind("<Button-1>", self._drag_start)
        self.badge.bind("<B1-Motion>", self._drag_move)
        self.badge.bind("<ButtonRelease-1>", self._drag_end)
        self.badge.bind("<Enter>", lambda e: self.show_panel())
        self.badge.bind("<Leave>", self.schedule_hide)
        self.badge.bind("<Button-3>", self.popup_badge_menu)

    def _apply_position(self):
        x, y = self.cfg["badge_position"]
        self.badge.geometry(f"+{x}+{y}")
        self._clamp_badge_position()

    def _clamp_badge_position(self):
        """启动时的安全网：徽章位置完全失效（换显示器/改分辨率）时钳回主屏。"""
        self.badge.update_idletasks()
        bw = max(self.badge.winfo_width(), self.badge.winfo_reqwidth(), 1)
        bh = max(self.badge.winfo_height(), self.badge.winfo_reqheight(), 1)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = min(max(self.badge.winfo_x(), 8), sw - bw - 8)
        y = min(max(self.badge.winfo_y(), 8), sh - bh - 8)
        if (x, y) != (self.badge.winfo_x(), self.badge.winfo_y()):
            self.badge.geometry(f"+{x}+{y}")

    def _drag_start(self, e):
        self._drag_dx, self._drag_dy = e.x, e.y
        self._dragging = True
        self._cancel_hide()
        self.hide_panel()

    def _drag_end(self, e):
        self._dragging = False
        self.cfg["badge_position"] = [self.badge.winfo_x(), self.badge.winfo_y()]
        # 严格读盘：失败则跳过保存（不能用可能为默认值的基底覆盖真实凭据）；
        # 直接读 JSON 保留磁盘上的未知键
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                disk = json.load(f)
            if not isinstance(disk, dict):
                raise ValueError("config 根不是对象")
        except (OSError, ValueError) as exc:
            log(f"拖动保存跳过：读取 config 失败 {exc!r}")
            return
        merged = dict(disk)
        for key in ("refresh_interval_sec", "alert_threshold",
                    "warn_threshold", "badge_position"):
            merged[key] = self.cfg[key]
        save_config(merged, CONFIG_PATH)

    def _drag_move(self, e):
        x = self.badge.winfo_x() - self._drag_dx + e.x
        y = self.badge.winfo_y() - self._drag_dy + e.y
        self.badge.geometry(f"+{x}+{y}")

    def _render_badge(self):
        parts = badge_parts(self.latest, self.last_ok,
                            self.cfg["warn_threshold"], self.cfg["alert_threshold"])
        if len(parts) == 1:      # 异常态：错误文案自带图形符号，隐藏 ⚡ 图标
            self.lb_icon.configure(text="")
            self.lb_5h.configure(text=parts[0][0], fg=parts[0][1])
            self.lb_mcp.configure(text="")
        else:
            self.lb_icon.configure(text="⚡")
            self.lb_5h.configure(text=parts[0][0], fg=parts[0][1])
            self.lb_mcp.configure(text=parts[1][0], fg=parts[1][1])

    # ---------- 展开面板 ----------
    def _make_bar(self, parent):
        """200x8 进度条，返回 (canvas, 填充rect)。"""
        c = tk.Canvas(parent, width=200, height=8, bg=BG, highlightthickness=0)
        c.create_rectangle(0, 0, 199, 7, outline=COL_DIM)
        rect = c.create_rectangle(1, 1, 1, 7, fill=COL_OK, width=0)
        return c, rect

    @staticmethod
    def _update_bar(canvas, rect, pct, color):
        w = max(1, int(198 * min(pct, 100) / 100))
        canvas.coords(rect, 1, 1, w, 7)
        canvas.itemconfigure(rect, fill=color)

    # ---------- 右键菜单与托盘三态 ----------
    def _build_menus(self):
        self.badge_menu = tk.Menu(self.root, tearoff=0)
        self.badge_menu.add_command(label="手动刷新", command=lambda: self.refresh(True))
        self.badge_menu.add_command(label="最小化到系统任务栏",
                                    command=self.minimize_to_tray)
        self.badge_menu.add_command(label="退出", command=self.quit_app)
        self.tray_menu = tk.Menu(self.root, tearoff=0)
        self.tray_menu.add_command(label="恢复", command=self.restore_from_tray)
        self.tray_menu.add_command(label="手动刷新", command=lambda: self.refresh(True))
        self.tray_menu.add_command(label="退出", command=self.quit_app)

    def popup_badge_menu(self, e=None):
        try:
            self.badge_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.badge_menu.grab_release()

    def show_tray_menu(self):
        """托盘右键：在指针处（即托盘图标上）弹菜单，天然适配任意任务栏位置。"""
        px, py = self.root.winfo_pointerxy()
        try:
            self.tray_menu.tk_popup(px, py)
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
                log_fn=log,
            )
        if not self._tray.show():
            log("托盘图标创建失败，徽章保持显示（可再次右键重试）")
            self._tray = None
            return
        self.minimized = True
        self._cancel_hide()      # 防悬挂的 hide_job 在最小化→恢复→快速悬停后把面板拽出来
        self.hide_panel()
        self.badge.withdraw()

    def restore_from_tray(self):
        if not self.minimized:
            return
        self.minimized = False
        self.badge.deiconify()
        if self._tray:
            tray, self._tray = self._tray, None
            self._tray_parking = tray
            self.root.after(0, tray.hide)   # hide 会 join 消息线程；此处处于其封送的
            # event_generate 调用内，同步 join 会循环等待 3 秒超时——必须延后到空闲时执行

    def quit_app(self):
        try:
            if self._tray:
                self._tray.hide()
            if self._tray_parking:
                self._tray_parking.hide()
                self._tray_parking = None
        except Exception as exc:
            log(f"托盘清理异常: {exc!r}")
        if getattr(self, "_refresh_job", None):
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
        self.root.destroy()

    # ---------- 配置对话框（未配置/更换凭据时使用） ----------
    def open_config_dialog(self):
        """弹出配置窗口；已打开时仅置前。url 预填默认值。"""
        if getattr(self, "cfg_dialog", None) and self.cfg_dialog.winfo_exists():
            self.cfg_dialog.lift()
            self.cfg_dialog.focus_force()
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("GLM 用量悬浮窗 - 配置")
        dlg.configure(bg=BG)
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        tk.Label(dlg, text="token", font=FONT, bg=BG, fg=FG)\
            .grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        dlg.token_var = tk.StringVar(value=self.cfg.get("token", ""))
        tk.Entry(dlg, textvariable=dlg.token_var, show="*", width=36)\
            .grid(row=1, column=0, padx=10, sticky="we")
        tk.Label(dlg, text="接口地址（只填协议+域名，会自动规范化）", font=FONT,
                 bg=BG, fg=FG).grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        dlg.url_var = tk.StringVar(
            value=self.cfg.get("base_url") or DEFAULT_BASE_URL)
        tk.Entry(dlg, textvariable=dlg.url_var, width=36)\
            .grid(row=3, column=0, padx=10, sticky="we")
        dlg.err_label = tk.Label(dlg, text="", font=RESET_FONT, bg=BG, fg=COL_ALERT)
        dlg.err_label.grid(row=4, column=0, sticky="w", padx=10)
        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=5, column=0, pady=10)
        tk.Button(btns, text="保存", width=8, font=FONT,
                  command=lambda: self._save_credentials_dialog(dlg))\
            .pack(side="left", padx=6)
        tk.Button(btns, text="取消", width=8, font=FONT,
                  command=dlg.destroy).pack(side="left", padx=6)
        dlg.grid_columnconfigure(0, weight=1)
        dlg.save = lambda: self._save_credentials_dialog(dlg)
        self.cfg_dialog = dlg

    def _save_credentials_dialog(self, dlg):
        token = dlg.token_var.get().strip()
        url = _normalize_base_url(dlg.url_var.get().strip() or DEFAULT_BASE_URL)
        if not token:
            dlg.err_label.configure(text="token 不能为空")
            return
        if not url:
            dlg.err_label.configure(text="接口地址无效")
            return
        if self._apply_credentials(token, url):
            dlg.destroy()

    def _apply_credentials(self, token, base_url):
        """校验并写入凭据（规范化 url、保留其他配置），成功后立即刷新。"""
        token = (token or "").strip()
        if not token:
            return False
        self.cfg["token"] = token
        url = _normalize_base_url(base_url)    # 规范化集中在此（对话框/测试共用咽喉点）
        if url:
            self.cfg["base_url"] = url
        save_config(self.cfg, CONFIG_PATH)     # 显式传调用时值（可测试、防默认参数陷阱）
        self.refresh()
        return True

    def _build_panel(self):
        self.panel = tk.Toplevel(self.root)
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        self.panel.attributes("-alpha", 0.95)
        self.panel.configure(bg=BG)
        self.panel.withdraw()
        self.panel.bind("<Enter>", lambda e: self._cancel_hide())
        self.panel.bind("<Leave>", self.schedule_hide)
        self.panel.bind("<Button-3>", self.popup_badge_menu)

        g = tk.Frame(self.panel, bg=BG)
        g.pack(fill="both", expand=True, padx=10, pady=8)
        self._panel_grid = g

        self.p_title = tk.Label(g, text="GLM Coding Plan", font=FONT, bg=BG, fg=FG)
        self.p_title.grid(row=0, column=0, columnspan=3, sticky="w")

        self.p_bars = []          # [(name_label, reset_label, canvas, rect, pct_label), ...]
        for i, name in enumerate(("窗口1", "窗口2")):
            row = 1 + i * 2                       # 1/3 行：额度行；2/4 行：重置时间
            name_lab = tk.Label(g, text=name, font=FONT, bg=BG, fg=FG)
            name_lab.grid(row=row, column=0, sticky="w")
            c, rect = self._make_bar(g)
            c.grid(row=row, column=1, pady=2)
            lab = tk.Label(g, text="0%", font=FONT, bg=BG, fg=FG, width=5)
            lab.grid(row=row, column=2, sticky="w")
            reset_lab = tk.Label(g, text="", font=RESET_FONT, bg=BG, fg=COL_DIM,
                                 anchor="w")
            reset_lab.grid(row=row + 1, column=0, columnspan=3, sticky="w")
            self.p_bars.append((name_lab, reset_lab, c, rect, lab))

        self.p_today = tk.Label(g, text="今日 Token  0", font=FONT, bg=BG, fg=FG,
                                justify="left", anchor="w")
        self.p_today.grid(row=5, column=0, columnspan=3, sticky="we", pady=(6, 0))
        self.p_models = [
            tk.Label(g, text="", font=FONT, bg=BG, fg=COL_DIM, anchor="w")
            for _ in range(4)
        ]
        for i, lab in enumerate(self.p_models):
            lab.grid(row=6 + i, column=0, columnspan=3, sticky="we")

        self.p_mcp_txt = tk.Label(g, text="MCP月度额度", font=FONT, bg=BG, fg=FG,
                                  anchor="w")
        self.p_mcp_txt.grid(row=10, column=0, sticky="w")
        c, rect = self._make_bar(g)
        c.grid(row=10, column=1, pady=2)
        self.p_mcp_bar = (c, rect)
        self.p_mcp_pct = tk.Label(g, text="0%", font=FONT, bg=BG, fg=FG, width=5)
        self.p_mcp_pct.grid(row=10, column=2, sticky="w")
        self.p_mcp_reset = tk.Label(g, text="", font=RESET_FONT, bg=BG, fg=COL_DIM,
                                    anchor="w")
        self.p_mcp_reset.grid(row=11, column=0, columnspan=3, sticky="w")

        # 近 24 小时 Token 消耗趋势（与 MCP 无关，标题写明以免误读）
        self.p_spark_title = tk.Label(g, text="近24小时 Token 消耗趋势（每小时）",
                                      font=RESET_FONT, bg=BG, fg=COL_DIM, anchor="w")
        self.p_spark_title.grid(row=12, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.spark = tk.Canvas(g, width=228, height=40, bg=BG, highlightthickness=0)
        self.spark.grid(row=13, column=0, columnspan=3)
        self.p_spark_start = tk.Label(g, text="← 24小时前", font=RESET_FONT, bg=BG,
                                      fg=COL_DIM)
        self.p_spark_start.grid(row=14, column=0, sticky="w")
        self.p_spark_peak = tk.Label(g, text="", font=RESET_FONT, bg=BG, fg=COL_DIM)
        self.p_spark_peak.grid(row=14, column=1, sticky="w", padx=(8, 0))
        self.p_spark_end = tk.Label(g, text="现在 →", font=RESET_FONT, bg=BG,
                                    fg=COL_DIM)
        self.p_spark_end.grid(row=14, column=2, sticky="e")

        # 未配置时的入口按钮：仅 NO_TOKEN/NO_BASE_URL 状态显示
        self.p_cfg_btn = tk.Button(g, text="填写 token / 接口地址",
                                   font=FONT, command=self.open_config_dialog)
        self.p_cfg_btn.grid(row=15, column=0, columnspan=3, pady=(8, 0))
        self.p_cfg_btn.grid_remove()

    def _draw_spark(self):
        c = self.spark
        c.delete("all")
        c.create_rectangle(0, 0, 227, 39, outline=COL_DIM)
        self.p_spark_peak.configure(text="")
        hourly = (self.data or {}).get("hourly") or []
        if not hourly:
            return
        peak = max(v for _, v in hourly) or 1.0
        n = len(hourly)
        bw = max(2, 224 // n - 1)
        peak_y = None
        for i, (_, v) in enumerate(hourly):
            if v <= 0:
                continue
            h = max(1, int(v / peak * 34))
            x = 2 + i * (bw + 1)
            c.create_rectangle(x, 37 - h, x + bw, 37, fill=COL_OK, width=0)
            if peak_y is None or 37 - h < peak_y:
                peak_y = 37 - h
        if peak_y is not None:      # 峰值参考线（Y 轴刻度），数值见下方轴标注
            c.create_line(1, peak_y, 226, peak_y, fill=COL_DIM, dash=(2, 2))
        self.p_spark_peak.configure(text=f"峰值 {format_tokens(peak)}")

    def _render_panel(self):
        latest = self.latest or {}
        warn, alert = self.cfg["warn_threshold"], self.cfg["alert_threshold"]
        if latest.get("error") in ("NO_TOKEN", "NO_BASE_URL"):
            self.p_title.configure(text="未配置 Token")
            self.p_today.configure(text="点击下方按钮填写 token 与接口地址\n"
                                        "（保存在本目录 config.json，不会提交 git）")
            self.p_cfg_btn.grid()
            return
        self.p_cfg_btn.grid_remove()
        d = self.data or {}
        if latest.get("error"):
            self.p_title.configure(text=f"GLM Coding Plan   更新失败 {self.last_ok}，重试中")
        else:
            self.p_title.configure(text=f"GLM Coding Plan   更新 {self.last_ok}")
        wins = d.get("token_windows") or []
        for i, (name_lab, reset_lab, canvas, rect, lab) in enumerate(self.p_bars):
            win = wins[i] if i < len(wins) else {}
            pct = win.get("percentage", 0.0)
            self._update_bar(canvas, rect, pct, color_for(pct, warn, alert))
            name_lab.configure(text=win.get("label", f"窗口{i + 1}"))
            reset = humanize_reset(win.get("next_reset"))
            reset_lab.configure(text=f"  {reset}" if reset else "")
            lab.configure(text=f"{pct:.0f}%")
        today = d.get("today") or {}
        self.p_today.configure(
            text=f"今日 Token  {format_tokens(today.get('total_tokens', 0))}")
        models = today.get("models") or []
        rows = [f"  {m['name']}  {format_tokens(m['tokens'])}" for m in models[:3]]
        if len(models) > 3:
            extra = sum(m["tokens"] for m in models[3:])
            rows.append(f"  其他({len(models) - 3})  {format_tokens(extra)}")
        for i, lab in enumerate(self.p_models):
            lab.configure(text=rows[i] if i < len(rows) else "")
        mcp = d.get("mcp") or {"used": 0, "total": 0, "percentage": 0.0}
        self._update_bar(self.p_mcp_bar[0], self.p_mcp_bar[1],
                         mcp["percentage"], color_for(mcp["percentage"], warn, alert))
        mcp_reset = humanize_reset(mcp.get("next_reset"))
        mcp_line = f"  已用 {mcp.get('used', 0)}/{mcp.get('total', 0)}"
        if mcp_reset:
            mcp_line += f" · {mcp_reset}"
        self.p_mcp_reset.configure(text=mcp_line)
        self.p_mcp_pct.configure(text=f"{mcp['percentage']:.0f}%")
        self._draw_spark()

    # ---------- 悬停展开/收回 ----------
    def _cancel_hide(self):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None

    def _position_panel(self):
        bx, by = self.badge.winfo_x(), self.badge.winfo_y()
        self.panel.update_idletasks()
        pw = self.panel.winfo_reqwidth()
        ph = self.panel.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        px = min(max(8, bx), sw - pw - 8)
        # 默认在徽章上方；顶部放不下翻转到下方；下方也放不下则钳到底部
        py = by - ph - 6
        if py < 8:
            py = by + self.badge.winfo_height() + 6
        if py + ph > sh - 8:
            py = sh - 8 - ph
        self.panel.geometry(f"+{px}+{py}")

    def show_panel(self):
        if self._dragging:
            return
        self._cancel_hide()
        try:
            self._render_panel()
        except Exception as exc:
            log(f"面板渲染异常: {exc!r}")
        self._position_panel()
        self.panel.deiconify()

    def schedule_hide(self, e=None):
        px, py = self.root.winfo_pointerxy()
        if self._inside(self.badge, px, py) or self._inside(self.panel, px, py):
            return  # 跨子控件触发的假 Leave
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
        self.hide_job = self.root.after(500, self.hide_panel)

    def hide_panel(self):
        self.panel.withdraw()
        self.hide_job = None

    @staticmethod
    def _inside(win, px, py):
        if not win.winfo_ismapped():
            return False
        x, y = win.winfo_rootx(), win.winfo_rooty()
        return x <= px <= x + win.winfo_width() and y <= py <= y + win.winfo_height()

    # ---------- 数据刷新 ----------
    def refresh(self, manual=False):
        if manual:
            # 手动刷新给出即时反馈：正在重新拉取最新额度与消耗量
            try:
                if self.panel.winfo_ismapped():
                    self.p_title.configure(text="GLM Coding Plan   刷新中…")
            except Exception:
                pass
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            data = fetch_all(token=self.cfg.get("token") or None,
                             base_url=self.cfg.get("base_url") or None)  # 永不抛异常
            self.root.after(0, lambda: self._apply_data(data))
        except Exception as exc:
            log(f"后台线程异常: {exc!r}")

    def _apply_data(self, data):
        try:
            self.latest = data    # 无论成败都记录，徽章据此切换 ⚠/未配置
            if data.get("error") in ("NO_TOKEN", "NO_BASE_URL"):
                self.failures = 0
            elif data.get("error"):
                self.failures += 1
                log(f"拉取失败: {str(data['error'])[:200]}")
            else:
                self.failures = 0
                self.last_ok = datetime.now().strftime("%H:%M")
                self.data = data
            self._render_badge()
            if self.panel.winfo_ismapped():
                self._render_panel()
                self._position_panel()
        except Exception as exc:
            log(f"UI 更新异常: {exc!r}")
        finally:
            if getattr(self, "_refresh_job", None):
                try:
                    self.root.after_cancel(self._refresh_job)
                except Exception:
                    pass
            delay = next_interval_sec(self.failures, self.cfg["refresh_interval_sec"])
            self._refresh_job = self.root.after(delay * 1000, self.refresh)


def main():
    root = tk.Tk()
    root.withdraw()
    app = UsageApp(root)
    if os.environ.get("GLM_TRAY_SELFTEST"):
        # 打包版诊断：启动 3 秒后自动触发一次最小化/恢复并记录结果
        def _selftest():
            app.minimize_to_tray()
            ok = bool(app._tray and app._tray._ok)
            log(f"托盘自检: {'成功' if ok else '失败'}")
            app.restore_from_tray()
            root.after(800, root.destroy)
        root.after(3000, _selftest)
    root.mainloop()


if __name__ == "__main__":
    main()
