"""GLM Coding Plan 用量数据层：请求 monitor 接口并解析为统一结构。

认证优先来自 config.json 的 token/base_url（由 widget 层经参数传入），
环境变量 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL 仅作为参数缺省时的兜底。
解析函数永不抛异常。
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


def parse_quota(data):
    """解析 quota/limit 响应 -> {"token_windows": [...], "mcp": {...}}。永不抛异常。

    MCP 百分比按 currentUsage/usage 现场重算（API 的 percentage 是四舍五入值）；
    字段映射：currentUsage -> used（已用），usage -> total（总量，API 命名如此）。
    """
    result = {"token_windows": [], "mcp": None}
    if not isinstance(data, dict):
        return result
    limits = data.get("limits")
    if not isinstance(limits, list):
        return result
    for item in limits:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "TOKENS_LIMIT":
            result["token_windows"].append({"percentage": _to_float(item.get("percentage"))})
        elif item.get("type") == "TIME_LIMIT" and result["mcp"] is None:
            used = _to_float(item.get("currentUsage"))
            total = _to_float(item.get("usage"))
            result["mcp"] = {
                "used": int(used),
                "total": int(total),
                "percentage": (used / total * 100) if total > 0 else 0.0,
            }
    return result


def parse_model_usage(data, now=None):
    """解析 model-usage 响应 -> {"today": {...}, "hourly": [...]}。永不抛异常。

    查询窗口是"昨天 00:00 -> 现在"（最多 48 桶）：
    - hourly 取最后 24 桶作 24h 趋势
    - today 按 x_time 标签属于今天且 <= now 的桶求和（排除未到达的桶）
    - 按模型分项用 modelDataList（每模型逐小时数组）做同口径今日聚合，
      不用 modelSummaryList（那是整窗口径）

    标签假定为零填充 "YYYY-MM-DD HH:00" 的本地时区格式；
    modelDataList 的 tokensUsage 与 x_time 按下标对齐（同起点同粒度）。
    """
    if now is None:
        now = datetime.now()
    today_key = now.strftime("%Y-%m-%d")
    now_key = now.strftime("%Y-%m-%d %H:%M")
    out = {"today": {"total_tokens": 0, "models": []}, "hourly": []}
    if not isinstance(data, dict):
        return out
    times = data.get("x_time")
    usage = data.get("tokensUsage")
    if not isinstance(times, list) or not isinstance(usage, list):
        return out

    today_flags = [str(label).startswith(today_key) and str(label) <= now_key
                   for label in times]
    today_total = sum(_to_float(v) for v, flag in zip(usage, today_flags) if flag)
    buckets = [(str(label), _to_float(v)) for label, v in zip(times, usage)]

    per_model = {}
    model_rows = data.get("modelDataList")
    if isinstance(model_rows, list):
        for row in model_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("modelName", "?"))
            arr = row.get("tokensUsage")
            if isinstance(arr, list):
                per_model[name] = per_model.get(name, 0.0) + sum(
                    _to_float(v) for v, flag in zip(arr, today_flags) if flag
                )

    out["hourly"] = buckets[-24:]
    out["today"] = {
        "total_tokens": today_total,
        "models": [{"name": k, "tokens": v}
                   for k, v in sorted(per_model.items(), key=lambda kv: -kv[1])],
    }
    return out


def fetch_json(url, token, timeout=TIMEOUT_SEC):
    """GET 一个接口并返回解析后的 dict；任何失败抛 UsageError。"""
    req = urllib.request.Request(url, headers={
        "Authorization": token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:  # urllib 把 HTTP 非 200 也抛成异常（HTTPError）
        raise UsageError(f"{url} -> {exc}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise UsageError(f"响应不是 JSON: {body[:200]}") from exc


def _unwrap(payload):
    """剥掉 {"code": 200, "data": {...}} 信封；code 非 200 视为接口错误。

    fixtures/官方脚本消费的是解包后的 data；无信封的 payload 原样透传。
    """
    if not isinstance(payload, dict):
        return payload
    code = payload.get("code")
    if code is not None and str(code) != "200":
        raise UsageError(f"接口返回 code={code}: {str(payload.get('msg', ''))[:100]}")
    data = payload.get("data")
    return data if data is not None else payload


def fetch_all(now=None, fetcher=fetch_json, token=None, base_url=None):
    """拉取并解析全部数据。永不抛异常：
    成功返回统一结构；失败返回 {"error": "<信息>"}。"""
    if now is None:
        now = datetime.now()
    token = ((os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
             if token is None else token)
    base_url = base_url or get_base_url()
    if not token:
        return {"error": "NO_TOKEN"}
    if not base_url:
        return {"error": "NO_BASE_URL"}
    start, end = query_window(now)
    query = urllib.parse.urlencode({"startTime": start, "endTime": end})
    try:
        model_data = _unwrap(fetcher(f"{base_url}/api/monitor/usage/model-usage?{query}", token))
        quota_data = _unwrap(fetcher(f"{base_url}/api/monitor/usage/quota/limit", token))
    except UsageError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # 兜底：意外异常不能杀死轮询线程
        return {"error": f"unexpected: {exc!r}"}
    if (not isinstance(quota_data, dict) or not isinstance(quota_data.get("limits"), list)
            or not isinstance(model_data, dict)
            or not isinstance(model_data.get("x_time"), list)
            or not isinstance(model_data.get("tokensUsage"), list)):
        return {"error": "接口数据结构异常"}
    result = parse_quota(quota_data)
    result.update(parse_model_usage(model_data, now))
    result["fetched_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    return result
