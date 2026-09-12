"""GLM Coding Plan 用量数据层：请求 monitor 接口并解析为统一结构。

认证使用环境变量 ANTHROPIC_AUTH_TOKEN（与 Claude Code 相同的 token），
接口域名取 ANTHROPIC_BASE_URL 的根。解析函数永不抛异常。
"""

import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

TIMEOUT_SEC = 10


class UsageError(Exception):
    """网络或接口错误。"""


def _to_float(x, default=0.0):
    try:
        val = float(x)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(val):
        return default
    return val


def format_tokens(n):
    """1234 -> '1.2K'，76548147 -> '76.5M'；非法输入返回 '0'。"""
    n = _to_float(n, default=None)
    if n is None:
        return "0"
    if n >= 999_950:
        return f"{n / 1_000_000:.1f}M"
    if n >= 999.5:
        return f"{n / 1_000:.1f}K"
    return f"{int(n)}"


def query_window(now=None):
    """查询窗口：昨天 00:00 -> 现在。返回 (start, end) 字符串。"""
    if now is None:
        now = datetime.now()
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), now.strftime(fmt)


def get_base_url():
    """从 ANTHROPIC_BASE_URL 提取协议+域名；未设置或非法返回 None。"""
    raw = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None
