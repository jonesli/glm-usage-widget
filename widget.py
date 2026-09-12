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
    """连续失败 >=3 次把间隔放宽到 300s。"""
    return 300 if failures >= 3 else base


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
        elif isinstance(val, int) and not isinstance(val, bool) and val > 0:
            cfg[key] = val
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        log(f"写入配置失败: {exc}")
