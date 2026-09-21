"""GLM Coding Plan 用量悬浮窗（tkinter）。置顶徽章 + 悬停展开面板。"""

import json
import math
import os
import threading
import time
import urllib.parse
from datetime import datetime
import tkinter as tk

from trayicon import TrayIcon
from usage_api import fetch_all, format_tokens, get_base_url

APP_DIR = os.path.dirname(os.path.abspath(__file__))
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

BG = "#1e1e2e"        # 深色底
FG = "#cdd6f4"        # 主文字
COL_DIM = "#9399b2"   # 次要文字
COL_OK = "#a6e3a1"    # 绿
COL_WARN = "#f9e2af"  # 黄
COL_ALERT = "#f38ba8" # 红
FONT = ("Microsoft YaHei UI", 9)


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
        parts = urllib.parse.urlsplit(cfg["base_url"])
        cfg["base_url"] = f"{parts.scheme}://{parts.netloc}"
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
        self.badge_menu.add_command(label="手动刷新", command=self.refresh)
        self.badge_menu.add_command(label="最小化到系统任务栏",
                                    command=self.minimize_to_tray)
        self.badge_menu.add_command(label="退出", command=self.quit_app)
        self.tray_menu = tk.Menu(self.root, tearoff=0)
        self.tray_menu.add_command(label="恢复", command=self.restore_from_tray)
        self.tray_menu.add_command(label="手动刷新", command=self.refresh)
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

        self.p_title = tk.Label(g, text="GLM Coding Plan", font=FONT, bg=BG, fg=FG)
        self.p_title.grid(row=0, column=0, columnspan=3, sticky="w")

        self.p_bars = []          # [(name_label, canvas, rect, pct_label), ...]
        for i, name in enumerate(("窗口1", "窗口2")):
            name_lab = tk.Label(g, text=name, font=FONT, bg=BG, fg=COL_DIM)
            name_lab.grid(row=1 + i, column=0, sticky="w")
            c, rect = self._make_bar(g)
            c.grid(row=1 + i, column=1, pady=2)
            lab = tk.Label(g, text="0%", font=FONT, bg=BG, fg=FG, width=5)
            lab.grid(row=1 + i, column=2, sticky="w")
            self.p_bars.append((name_lab, c, rect, lab))

        self.p_today = tk.Label(g, text="今日 Token  0", font=FONT, bg=BG, fg=FG,
                                justify="left", anchor="w")
        self.p_today.grid(row=3, column=0, columnspan=3, sticky="we", pady=(6, 0))
        self.p_models = [
            tk.Label(g, text="", font=FONT, bg=BG, fg=COL_DIM, anchor="w")
            for _ in range(4)
        ]
        for i, lab in enumerate(self.p_models):
            lab.grid(row=4 + i, column=0, columnspan=3, sticky="we")

        self.p_mcp_txt = tk.Label(g, text="MCP月度额度\n已用 0/0", font=FONT, bg=BG, fg=FG,
                                  justify="left", anchor="w")
        self.p_mcp_txt.grid(row=8, column=0, sticky="w", pady=(6, 0))
        c, rect = self._make_bar(g)
        c.grid(row=8, column=1, pady=2, sticky="w")
        self.p_mcp_bar = (c, rect)
        self.p_mcp_pct = tk.Label(g, text="0%", font=FONT, bg=BG, fg=FG, width=5)
        self.p_mcp_pct.grid(row=8, column=2, sticky="w", pady=(6, 0))

        self.spark = tk.Canvas(g, width=228, height=40, bg=BG, highlightthickness=0)
        self.spark.grid(row=9, column=0, columnspan=3, pady=(6, 0))

    def _draw_spark(self):
        c = self.spark
        c.delete("all")
        c.create_rectangle(0, 0, 227, 39, outline=COL_DIM)
        hourly = (self.data or {}).get("hourly") or []
        if not hourly:
            return
        peak = max(v for _, v in hourly) or 1.0
        n = len(hourly)
        bw = max(2, 224 // n - 1)
        for i, (_, v) in enumerate(hourly):
            if v <= 0:
                continue
            h = max(1, int(v / peak * 34))
            x = 2 + i * (bw + 1)
            c.create_rectangle(x, 37 - h, x + bw, 37, fill=COL_OK, width=0)

    def _render_panel(self):
        latest = self.latest or {}
        warn, alert = self.cfg["warn_threshold"], self.cfg["alert_threshold"]
        if latest.get("error") in ("NO_TOKEN", "NO_BASE_URL"):
            self.p_title.configure(text="未配置 Token")
            self.p_today.configure(text="请在 config.json 中设置 token 与 base_url\n"
                                        "（token 不会提交到 git）后重新启动本程序")
            return
        d = self.data or {}
        if latest.get("error"):
            self.p_title.configure(text=f"GLM Coding Plan   更新失败 {self.last_ok}，重试中")
        else:
            self.p_title.configure(text=f"GLM Coding Plan   更新 {self.last_ok}")
        wins = d.get("token_windows") or []
        for i, (name_lab, canvas, rect, lab) in enumerate(self.p_bars):
            win = wins[i] if i < len(wins) else {}
            pct = win.get("percentage", 0.0)
            self._update_bar(canvas, rect, pct, color_for(pct, warn, alert))
            name = win.get("label", f"窗口{i + 1}")
            reset = humanize_reset(win.get("next_reset"))
            name_lab.configure(text=f"{name}\n{reset}" if reset else name)
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
        mcp_name = f"MCP月度额度\n已用 {mcp['used']}/{mcp['total']}"
        if mcp_reset:
            mcp_name += f" · {mcp_reset}"
        self.p_mcp_txt.configure(text=mcp_name)
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
    def refresh(self):
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
    UsageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
