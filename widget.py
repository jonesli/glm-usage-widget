"""GLM Coding Plan 用量悬浮窗（tkinter）。置顶徽章 + 悬停展开面板。"""

import json
import os
from datetime import datetime
import tkinter as tk

from usage_api import format_tokens

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "widget.log")

DEFAULTS = {
    "refresh_interval_sec": 60,
    "alert_threshold": 80,
    "warn_threshold": 50,
    "badge_position": [80, 80],
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
                            for v in val)):
                cfg[key] = [int(val[0]), int(val[1])]
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
        self.cfg = load_config()
        self.data = None          # 最近一次成功数据
        self.failures = 0
        self.last_ok = "--:--"
        self.hide_job = None
        self._build_badge()
        self._apply_position()
        self.root.after(200, self.refresh)

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
        # 交互：拖动 / 悬停展开 / 右键退出（无边框窗口的退出途径）
        self.badge.bind("<Button-1>", self._drag_start)
        self.badge.bind("<B1-Motion>", self._drag_move)
        self.badge.bind("<ButtonRelease-1>", self._drag_end)
        self.badge.bind("<Enter>", lambda e: self.show_panel())
        self.badge.bind("<Leave>", self.schedule_hide)
        self.badge.bind("<Button-3>", lambda e: self.root.destroy())

    def _apply_position(self):
        x, y = self.cfg["badge_position"]
        self.badge.geometry(f"+{x}+{y}")

    def _drag_start(self, e):
        self._drag_dx, self._drag_dy = e.x, e.y
        self.hide_panel()

    def _drag_move(self, e):
        x = self.badge.winfo_x() - self._drag_dx + e.x
        y = self.badge.winfo_y() - self._drag_dy + e.y
        self.badge.geometry(f"+{x}+{y}")

    def _drag_end(self, e):
        self.cfg["badge_position"] = [self.badge.winfo_x(), self.badge.winfo_y()]
        save_config(self.cfg)

    def _render_badge(self):
        parts = badge_parts(self.data, self.last_ok,
                            self.cfg["warn_threshold"], self.cfg["alert_threshold"])
        # parts 长度 1 = 异常态：占满 5h 位，MCP 位清空
        if len(parts) == 1:
            self.lb_5h.configure(text=parts[0][0], fg=parts[0][1])
            self.lb_mcp.configure(text="")
        else:
            self.lb_5h.configure(text=parts[0][0], fg=parts[0][1])
            self.lb_mcp.configure(text=parts[1][0], fg=parts[1][1])

    # ---------- 悬停展开/收回（Task 8 填充面板内容，本任务先做空实现）----------
    def show_panel(self):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None

    def schedule_hide(self, e=None):
        px, py = self.root.winfo_pointerxy()
        if self._inside(self.badge, px, py):
            return  # 跨子控件触发的假 Leave
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
        self.hide_job = self.root.after(500, self.hide_panel)

    def hide_panel(self):
        pass

    @staticmethod
    def _inside(win, px, py):
        if not win.winfo_ismapped():
            return False
        x, y = win.winfo_rootx(), win.winfo_rooty()
        return x <= px <= x + win.winfo_width() and y <= py <= y + win.winfo_height()

    # ---------- 数据刷新（Task 9 接入真实拉取，本任务先用静态演示数据）----------
    def refresh(self):
        self._apply_data({"token_windows": [{"percentage": 5.0}, {"percentage": 8.0}],
                          "mcp": {"used": 38, "total": 4000, "percentage": 0.95},
                          "today": {"total_tokens": 5517208, "models": []},
                          "hourly": [], "fetched_at": ""})

    def _apply_data(self, data):
        try:
            self.data = data
            self._render_badge()
        except Exception as exc:
            log(f"UI 更新异常: {exc!r}")


def main():
    root = tk.Tk()
    root.withdraw()
    UsageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
