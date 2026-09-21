# GLM Coding Plan 用量悬浮窗 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 桌面实现一个置顶可折叠的悬浮徽章，实时显示 GLM Coding Plan 的 5 小时窗口用量、今日 Token 消耗、MCP 月度用量和 24 小时趋势。

**Architecture:** 两个 tkinter 无边框置顶窗口（徽章 + 展开面板）；`usage_api.py` 用标准库 urllib 调 2 个 monitor 接口（token 认证，无 cookies），解析为统一结构；后台线程拉取、`after()` 回 UI 线程；配置与错误策略见 spec。

**Tech Stack:** Python 3.12 标准库（tkinter、urllib、unittest、threading），零第三方依赖。

**Spec:** `docs/superpowers/specs/2026-09-12-coding-plan-usage-widget-design.md`

**工作目录约定：** 所有命令均在 `D:\workspace\ai\glm-usage-widget` 下执行（bash 写法 `cd "D:/workspace/ai/glm-usage-widget"`）。

**对 spec 的三点实施级补充**（不改变 spec 行为，属于落地必需）：
1. 徽章**右键退出**程序（无边框窗口没有关闭按钮，必须有退出途径）
2. 接口返回的 `modelSummaryList` 是整窗口径，与"今日"不一致；按模型分项改用 `modelDataList`（每模型逐小时数组）按今日标签聚合，与总数同口径
3. 约定：每个任务的提交同时 `git add docs/`，让计划文档的勾选状态随代码一起进版本库

---

### Task 1: 项目脚手架、fixtures、git 身份

**Files:**
- Create: `.gitignore`
- Create: `tests/__init__.py`（空文件，使 tests 成为包，保证从项目根 `python -m unittest` 能找到根目录的 `usage_api`）
- Create: `tests/fixtures/model_usage.json`
- Create: `tests/fixtures/quota_limit.json`

- [ ] **Step 1: 验证 tkinter 可用**

Run: `python -c "import tkinter; print('tkinter OK')"`
Expected: 输出 `tkinter OK`。若失败，停止并向用户报告（需要重装带 tcl/tk 的 Python）。

- [ ] **Step 2: 配置仓库级 git 身份**

Run:
```bash
cd "D:/workspace/ai/glm-usage-widget"
git config user.name "HUAWEI"
git config user.email "huawei@local"
```
说明：仅对本仓库生效。用户之后可自行 `git config user.name "新名字"` 修改。

- [ ] **Step 3: 创建 .gitignore**

```
__pycache__/
*.pyc
config.json
widget.log
```

- [ ] **Step 4: 创建 tests/__init__.py（空文件）**

- [ ] **Step 5: 写入真实接口响应 fixture `tests/fixtures/model_usage.json`**

```json
{
  "x_time": ["2026-09-11 17:00", "2026-09-11 18:00", "2026-09-11 19:00", "2026-09-11 20:00", "2026-09-11 21:00", "2026-09-11 22:00", "2026-09-11 23:00", "2026-09-12 00:00", "2026-09-12 01:00", "2026-09-12 02:00", "2026-09-12 03:00", "2026-09-12 04:00", "2026-09-12 05:00", "2026-09-12 06:00", "2026-09-12 07:00", "2026-09-12 08:00", "2026-09-12 09:00", "2026-09-12 10:00", "2026-09-12 11:00", "2026-09-12 12:00", "2026-09-12 13:00", "2026-09-12 14:00", "2026-09-12 15:00", "2026-09-12 16:00", "2026-09-12 17:00"],
  "tokensUsage": [1734135, 1558704, 217533, 2837860, 4168835, 2389703, 8469297, 2253571, 0, 0, 0, 0, 0, 0, 277259, 755567, 16467404, 8819925, 5009658, 0, 802250, 8852436, 3260174, 4957906, 3715930],
  "modelDataList": [
    {
      "modelName": "GLM-5.3",
      "sortOrder": 1,
      "tokensUsage": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5215596, 0, 0, 0]
    },
    {
      "modelName": "GLM-5.3-Flash",
      "sortOrder": 2,
      "tokensUsage": [1734135, 1558704, 217533, 2837860, 4168835, 2389703, 8469297, 2253571, 0, 0, 0, 0, 0, 0, 277259, 755567, 16467404, 8819925, 5009658, 0, 802250, 3636840, 3260174, 4957906, 3715930]
    }
  ],
  "granularity": "hourly"
}
```

（2026-09-12 从真实接口抓取后裁剪：仅保留解析所需字段。今日=09-12 的桶共 18 个，逐项和为 55172080，测试将硬编码此期望值。）

- [ ] **Step 6: 写入真实接口响应 fixture `tests/fixtures/quota_limit.json`**

```json
{
  "limits": [
    { "type": "TOKENS_LIMIT", "percentage": 5 },
    { "type": "TOKENS_LIMIT", "percentage": 8 },
    { "type": "TIME_LIMIT", "percentage": 1, "currentUsage": 38, "usage": 4000,
      "usageDetails": [
        { "modelCode": "search-prime", "usage": 36 },
        { "modelCode": "web-reader", "usage": 2 },
        { "modelCode": "zread", "usage": 0 }
      ] }
  ],
  "level": "max"
}
```

- [ ] **Step 7: 提交**

```bash
git add .gitignore tests/
git commit -m "chore: 项目脚手架与真实接口 fixtures"
```

---

### Task 2: usage_api 基础工具（format_tokens / query_window / get_base_url / _to_float）

**Files:**
- Create: `usage_api.py`
- Test: `tests/test_usage_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_usage_api.py`：

```python
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import usage_api
from usage_api import (
    format_tokens, get_base_url, query_window,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class TestFormatTokens(unittest.TestCase):
    def test_zero_and_small(self):
        self.assertEqual(format_tokens(0), "0")
        self.assertEqual(format_tokens(999), "999")

    def test_kilo(self):
        self.assertEqual(format_tokens(1234), "1.2K")

    def test_mega(self):
        self.assertEqual(format_tokens(76_548_147), "76.5M")

    def test_bad_input(self):
        self.assertEqual(format_tokens(None), "0")
        self.assertEqual(format_tokens("abc"), "0")


class TestQueryWindow(unittest.TestCase):
    def test_window_is_yesterday_midnight_to_now(self):
        now = datetime(2026, 9, 12, 19, 30, 5)
        start, end = query_window(now)
        self.assertEqual(start, "2026-09-11 00:00:00")
        self.assertEqual(end, "2026-09-12 19:30:05")


class TestGetBaseUrl(unittest.TestCase):
    def test_strips_path(self):
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic"}):
            self.assertEqual(get_base_url(), "https://open.bigmodel.cn")

    def test_missing_env(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(get_base_url())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_usage_api -v`
Expected: FAIL，`ImportError: cannot import name 'format_tokens'`

- [ ] **Step 3: 最小实现**

创建 `usage_api.py`：

```python
"""GLM Coding Plan 用量数据层：请求 monitor 接口并解析为统一结构。

认证使用环境变量 ANTHROPIC_AUTH_TOKEN（与 Claude Code 相同的 token），
接口域名取 ANTHROPIC_BASE_URL 的根。解析函数永不抛异常。
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

TIMEOUT_SEC = 10


class UsageError(Exception):
    """网络或接口错误。"""


def _to_float(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def format_tokens(n):
    """1234 -> '1.2K'，76548147 -> '76.5M'；非法输入返回 '0'。"""
    n = _to_float(n, default=None)
    if n is None:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n)}"


def query_window(now=None):
    """查询窗口：昨天 00:00 -> 现在。返回 (start, end) 字符串。"""
    now = now or datetime.now()
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), now.strftime(fmt)


def get_base_url():
    """从 ANTHROPIC_BASE_URL 提取协议+域名；未设置或非法返回 None。"""
    raw = os.environ.get("ANTHROPIC_BASE_URL", "")
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_usage_api -v`
Expected: 7 个测试全部 PASS（`format_tokens` 4 + `query_window` 1 + `get_base_url` 2）

- [ ] **Step 5: 提交**

```bash
git add usage_api.py tests/test_usage_api.py
git commit -m "feat: usage_api 基础工具（token 格式化/查询窗口/域名提取）"
```

> **审查后加固（Task 2 质量审查已实施）：** `_to_float` 捕获 `OverflowError` 并对非有限值（NaN/Inf）返回 default（`import math` + `math.isfinite`）；`format_tokens` 阈值改为 `>=999_950` 进 M、`>=999.5` 进 K（避免 999_999 显示成 "1000.0K"）；`get_base_url` 对环境变量值 `.strip()`；`now = now or datetime.now()` 全部改为 `if now is None:` 守卫。Task 3-6 转录时一律以加固后版本为准。

---

### Task 3: parse_quota（5h 窗口 + MCP 月度）

**Files:**
- Modify: `usage_api.py`
- Test: `tests/test_usage_api.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_usage_api.py` 中，`import` 行加入 `parse_quota`：

```python
from usage_api import (
    format_tokens, get_base_url, query_window, parse_quota,
)
```

文件末尾（`if __name__` 之前）追加：

```python
class TestParseQuota(unittest.TestCase):
    def test_real_fixture(self):
        data = json.loads(load_fixture("quota_limit.json"))
        out = parse_quota(data)
        self.assertEqual([w["percentage"] for w in out["token_windows"]], [5.0, 8.0])
        self.assertEqual(out["mcp"], {"used": 38, "total": 4000, "percentage": 0.95})

    def test_missing_fields(self):
        out = parse_quota({})
        self.assertEqual(out, {"token_windows": [], "mcp": None})

    def test_garbage(self):
        out = parse_quota("not a dict")
        self.assertEqual(out["token_windows"], [])
        self.assertIsNone(out["mcp"])

    def test_zero_total_mcp_no_divide_by_zero(self):
        out = parse_quota({"limits": [{"type": "TIME_LIMIT", "percentage": 0,
                                       "currentUsage": 0, "usage": 0}]})
        self.assertEqual(out["mcp"]["percentage"], 0.0)
```

顶部补 `import json`。

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_usage_api -v`
Expected: FAIL，`ImportError: cannot import name 'parse_quota'`

- [ ] **Step 3: 实现 parse_quota**

在 `usage_api.py` 末尾追加：

```python
def parse_quota(data):
    """解析 quota/limit 响应 -> {"token_windows": [...], "mcp": {...}}。永不抛异常。"""
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_usage_api -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add usage_api.py tests/test_usage_api.py
git commit -m "feat: parse_quota 解析 5h 窗口与 MCP 月度用量"
```

---

### Task 4: parse_model_usage（今日聚合 + 24h 趋势，含跨零点）

**Files:**
- Modify: `usage_api.py`
- Test: `tests/test_usage_api.py`

- [ ] **Step 1: 追加失败测试**

import 行加入 `parse_model_usage`，文件末尾追加：

```python
class TestParseModelUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(load_fixture("model_usage.json"))

    def test_hourly_is_last_24_buckets(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        self.assertEqual(len(out["hourly"]), 24)          # fixture 有 25 个桶
        self.assertEqual(out["hourly"][0][0], "2026-09-11 18:00")
        self.assertEqual(out["hourly"][-1][1], 3715930.0)

    def test_today_total(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        self.assertEqual(out["today"]["total_tokens"], 55_172_080)

    def test_today_models_same_source(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        models = {m["name"]: m["tokens"] for m in out["today"]["models"]}
        # GLM-5.3 在 09-12 14:00 有 5215596；Flash 为今日总量减去它
        self.assertEqual(models["GLM-5.3"], 5_215_596)
        self.assertEqual(models["GLM-5.3-Flash"], 55_172_080 - 5_215_596)

    def test_cross_midnight(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 0, 30, 0))
        self.assertEqual(out["today"]["total_tokens"], 2_253_571)  # 仅 09-12 00:00 桶

    def test_missing_or_garbage(self):
        out = parse_model_usage({}, now=datetime(2026, 9, 12))
        self.assertEqual(out["hourly"], [])
        out = parse_model_usage("bad", now=datetime(2026, 9, 12))
        self.assertEqual(out["today"]["total_tokens"], 0)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_usage_api -v`
Expected: FAIL，`ImportError: cannot import name 'parse_model_usage'`

- [ ] **Step 3: 实现 parse_model_usage**

在 `usage_api.py` 末尾追加：

```python
def parse_model_usage(data, now=None):
    """解析 model-usage 响应 -> {"today": {...}, "hourly": [...]}。永不抛异常。

    查询窗口是"昨天 00:00 -> 现在"（最多 48 桶）：
    - hourly 取最后 24 桶作 24h 趋势
    - today 按 x_time 标签属于今天且 <= now 的桶求和（排除未到达的桶）
    - 按模型分项用 modelDataList（每模型逐小时数组）做同口径今日聚合，
      不用 modelSummaryList（那是整窗口径）
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
                per_model[name] = sum(
                    _to_float(v) for v, flag in zip(arr, today_flags) if flag
                )

    out["hourly"] = buckets[-24:]
    out["today"] = {
        "total_tokens": today_total,
        "models": [{"name": k, "tokens": v}
                   for k, v in sorted(per_model.items(), key=lambda kv: -kv[1])],
    }
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_usage_api -v`
Expected: 全部 PASS（含跨零点用例）

- [ ] **Step 5: 提交**

```bash
git add usage_api.py tests/test_usage_api.py
git commit -m "feat: parse_model_usage 今日聚合与 24h 趋势"
```

---

> **审查后加固（Task 4 质量审查已实施，随 Task 5 提交落地）：** ① `per_model[name]` 改为累加 `per_model.get(name, 0.0) + sum(...)`（同名模型多行时保持"分项和==总数"不变式）；② docstring 补两句：标签假定为零填充 `YYYY-MM-DD HH:00` 本地时区格式；modelDataList 的 tokensUsage 与 x_time 按下标对齐（同起点同粒度）；③ 补测试 `test_now_boundary_includes_current_hour_bucket`（now=09-12 14:00 → 今日 43_238_070，含 14:00 桶）及在 test_today_models_same_source 中加"分项和==总数"断言；④ Task 8 面板模型行改为前 3 名 + "其他"折叠行（Task 8 代码已同步更新）。

### Task 5: 网络层 fetch_json / fetch_all（可注入 fetcher，容错不抛异常）

**Files:**
- Modify: `usage_api.py`
- Test: `tests/test_usage_api.py`

- [ ] **Step 1: 追加失败测试**

import 行加入 `fetch_all, fetch_json, UsageError`，文件末尾追加：

```python
class TestFetchAll(unittest.TestCase):
    def test_success_two_calls(self):
        calls = []

        def fake_fetcher(url, token):
            calls.append(url)
            if "model-usage" in url:
                return {"x_time": ["2026-09-12 18:00"], "tokensUsage": [42]}
            return {"limits": [{"type": "TOKENS_LIMIT", "percentage": 8}]}

        out = fetch_all(now=datetime(2026, 9, 12, 19, 0, 0), fetcher=fake_fetcher,
                        token="tok", base_url="https://x.example")
        self.assertNotIn("error", out)
        self.assertEqual(len(calls), 2)
        self.assertIn("startTime=2026-09-11+00%3A00%3A00", calls[0])
        self.assertEqual(out["token_windows"], [{"percentage": 8.0}])
        self.assertEqual(out["today"]["total_tokens"], 42.0)
        self.assertEqual(out["fetched_at"], "2026-09-12 19:00:00")

    def test_network_error_returns_error_key(self):
        def bad_fetcher(url, token):
            raise UsageError("boom")

        out = fetch_all(now=datetime(2026, 9, 12), fetcher=bad_fetcher,
                        token="tok", base_url="https://x.example")
        self.assertEqual(out, {"error": "boom"})

    def test_no_token(self):
        out = fetch_all(now=datetime(2026, 9, 12), token="", base_url="https://x.example")
        self.assertEqual(out, {"error": "NO_TOKEN"})

    def test_no_base_url(self):
        out = fetch_all(now=datetime(2026, 9, 12), token="tok", base_url=None)
        self.assertEqual(out, {"error": "NO_BASE_URL"})

    def test_fetch_json_bad_json(self):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"not json"

        with patch("usage_api.urllib.request.urlopen", return_value=FakeResp()):
            with self.assertRaises(UsageError):
                fetch_json("https://x.example/api", "tok")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_usage_api -v`
Expected: FAIL，`ImportError: cannot import name 'fetch_all'`

- [ ] **Step 3: 实现网络层**

在 `usage_api.py` 末尾追加：

```python
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


def fetch_all(now=None, fetcher=fetch_json, token=None, base_url=None):
    """拉取并解析全部数据。永不抛异常：
    成功返回统一结构；失败返回 {"error": "<信息>"}。"""
    if now is None:
        now = datetime.now()
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") if token is None else token
    base_url = base_url or get_base_url()
    if not token:
        return {"error": "NO_TOKEN"}
    if not base_url:
        return {"error": "NO_BASE_URL"}
    start, end = query_window(now)
    query = urllib.parse.urlencode({"startTime": start, "endTime": end})
    try:
        model_data = fetcher(f"{base_url}/api/monitor/usage/model-usage?{query}", token)
        quota_data = fetcher(f"{base_url}/api/monitor/usage/quota/limit", token)
    except UsageError as exc:
        return {"error": str(exc)}
    result = parse_quota(quota_data)
    result.update(parse_model_usage(model_data, now))
    result["fetched_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    return result
```

- [ ] **Step 4: 运行全量测试确认通过**

Run: `python -m unittest -v`
Expected: 全部 PASS

- [ ] **Step 5: 真实接口冒烟验证（一次性，不自动化）**

Run:
```bash
python -c "from usage_api import fetch_all; import json; print(json.dumps(fetch_all(), ensure_ascii=False)[:400])"
```
Expected: 输出以 `{"token_windows":` 开头、含 `"fetched_at"` 的 JSON 片段（真实数据）。若输出 `{"error": ...`，停下排查网络/token，再继续。

- [ ] **Step 6: 提交**

```bash
git add usage_api.py tests/test_usage_api.py
git commit -m "feat: fetch_json/fetch_all 网络层与容错聚合"
```

---

> **审查修正（Task 5 冒烟发现，原计划遗漏）：** 真实接口返回 `{"code": 200, "msg": ..., "data": {...}}` 信封（fixtures 取自官方脚本已解包的输出，故无信封层；官方脚本用 `json.data || json` 解包）。fetch_all 在解析前用模块级 `_unwrap(payload)` 剥信封：`code` 存在且非 200 → 抛 UsageError（让过期 token 走 ⚠ 错误路径，而不是静默显示 0）；无信封的 payload 原样透传（既有测试不受影响）。
>
> **追加（Task 5 质量审查 fix-first）：** ① fetch_all 增加 `except Exception` 兜底分支，返回 `{"error": "unexpected: ..."}`——Task 9 的轮询线程依赖"永不抛异常"，否则意外异常会永久杀死 pythonw 下的刷新循环；② `_unwrap` 的 code 判断归一化为 `str(code) != "200"`；③ 补两个契约测试：Authorization 头必须携带原值 token（防误改为 Bearer 前缀）、urlopen 抛 HTTPError → UsageError。

### Task 6: widget 纯函数（color_for / next_interval_sec / badge_parts / 配置读写）

**Files:**
- Create: `widget.py`（本任务只写纯函数与常量，UI 类在 Task 7）
- Test: `tests/test_widget_helpers.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_widget_helpers.py`：

```python
import json
import os
import tempfile
import unittest

from widget import (
    COL_ALERT, COL_DIM, COL_OK, COL_WARN, DEFAULTS,
    badge_parts, color_for, load_config, next_interval_sec, save_config,
)


class TestColorFor(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(color_for(10, 50, 80), COL_OK)
        self.assertEqual(color_for(50, 50, 80), COL_WARN)   # >= warn 变黄
        self.assertEqual(color_for(79, 50, 80), COL_WARN)
        self.assertEqual(color_for(80, 50, 80), COL_ALERT)  # >= alert 变红


class TestNextInterval(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(next_interval_sec(0, 60), 60)
        self.assertEqual(next_interval_sec(2, 60), 60)

    def test_backoff(self):
        self.assertEqual(next_interval_sec(3, 60), 300)
        self.assertEqual(next_interval_sec(9, 60), 300)


class TestBadgeParts(unittest.TestCase):
    def test_no_data(self):
        self.assertEqual(badge_parts(None, "--:--"), [("⚡ …", COL_DIM)])

    def test_no_token(self):
        parts = badge_parts({"error": "NO_TOKEN"}, "12:00")
        self.assertEqual(parts, [("⚡ 未配置", COL_WARN)])

    def test_error_shows_last_ok(self):
        parts = badge_parts({"error": "boom"}, "14:32")
        self.assertEqual(parts, [("⚠ 14:32", COL_WARN)])

    def test_success(self):
        data = {"token_windows": [{"percentage": 5.0}, {"percentage": 8.0}],
                "mcp": {"percentage": 0.95}}
        parts = badge_parts(data, "19:00", 50, 80)
        self.assertEqual(parts[0], ("5h:8%", COL_OK))
        self.assertEqual(parts[1], ("MCP:1%", COL_OK))

    def test_success_alert_color(self):
        data = {"token_windows": [{"percentage": 85.0}], "mcp": {"percentage": 0.0}}
        parts = badge_parts(data, "19:00", 50, 80)
        self.assertEqual(parts[0], ("5h:85%", COL_ALERT))


class TestConfig(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            save_config({"refresh_interval_sec": 30, "alert_threshold": 80,
                         "warn_threshold": 50, "badge_position": [10, 20]}, path)
            cfg = load_config(path)
            self.assertEqual(cfg["refresh_interval_sec"], 30)
            self.assertEqual(cfg["badge_position"], [10, 20])

    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_config(os.path.join(d, "nope.json"))
            self.assertEqual(cfg, DEFAULTS)

    def test_corrupted_json_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w") as f:
                f.write("{broken")
            cfg = load_config(path)
            self.assertEqual(cfg["refresh_interval_sec"], DEFAULTS["refresh_interval_sec"])

    def test_bad_field_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"refresh_interval_sec": "fast", "alert_threshold": -1,
                           "badge_position": [1]}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["refresh_interval_sec"], 60)
            self.assertEqual(cfg["alert_threshold"], 80)
            self.assertEqual(cfg["badge_position"], DEFAULTS["badge_position"])
            # 合法字段仍被采纳
            cfg2_path = os.path.join(d, "ok.json")
            with open(cfg2_path, "w", encoding="utf-8") as f:
                json.dump({"warn_threshold": 40}, f)
            self.assertEqual(load_config(cfg2_path)["warn_threshold"], 40)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_widget_helpers -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'widget'`

- [ ] **Step 3: 实现纯函数（widget.py 第一部分）**

创建 `widget.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest -v`
Expected: 全部 PASS（widget.py 尚无 UI 代码，可安全 import）

- [ ] **Step 5: 提交**

```bash
git add widget.py tests/test_widget_helpers.py
git commit -m "feat: widget 纯函数（着色/退避/徽章文案/配置读写）"
```

---

> **审查后加固（Task 6 质量审查已实施）：** ① load_config 接受浮点数值（refresh_interval_sec 取整，阈值保留浮点，bool 仍排除）；② 阈值倒置（alert <= warn）视为配置错误、两者整体回退默认；③ 新增 `BACKOFF_SEC = 300` 常量，退避取 `max(base, BACKOFF_SEC)`（不低于用户配置的间隔）；④ save_config 改为临时文件 + `os.replace` 原子写，异常面扩为 `(OSError, TypeError, ValueError)`；⑤ 相应新增 3 个测试。

### Task 7: 徽章窗口（置顶、拖动、位置记忆、右键退出）

**Files:**
- Modify: `widget.py`（追加 `UsageApp` 类与 `main`）
- Test: 手动验证（UI 无自动化测试，验收点见下）

- [ ] **Step 1: 在 widget.py 末尾追加 UI 骨架**

```python
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

    # ---------- 悬停展开/收回（Task 8 填充面板内容，本任务先做空面板）----------
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
```

- [ ] **Step 2: 确认单测仍全绿（widget.py 可安全导入）**

Run: `python -m unittest -v`
Expected: 全部 PASS

- [ ] **Step 3: 手动验证（需要用户配合观察）**

Run: `python widget.py`（此窗口留着跑，验证完 Ctrl+C 停）

验收点，逐条确认：
1. 屏幕左上角 (80,80) 出现深色小徽章 `⚡ 5h:8% │ MCP:1%`，两段均为绿色
2. 徽章浮在浏览器/其他窗口之上（置顶）
3. 按住拖到别处松手；关闭程序重新 `python widget.py`，徽章出现在上次位置
4. 右键点击徽章 → 程序退出（无残留窗口）
5. config.json 已生成且 `badge_position` 是刚才拖到的坐标

- [ ] **Step 4: 提交**

```bash
git add widget.py
git commit -m "feat: 置顶徽章窗口（拖动/位置记忆/右键退出）"
```

---

> **审查后加固（Task 7 质量审查已实施，随 Task 8 落地）：** ① `_apply_position` 钳制坐标到主屏范围（换显示器/改分辨率后徽章不能消失在屏幕外无法找回，钳制基准 91×31px）；② 新增 `self._dragging` 标志（`_drag_start` 置 True 并取消 pending hide_job，`_drag_end` 置 False），`show_panel` 拖动中直接 return——修复拖动中快速进出徽章会触发面板弹出的问题；③ `_render_badge` 错误态隐藏 ⚡ 图标（badge_parts 错误文案自带 ⚠/未配置 符号，否则显示 "⚡ ⚠" 双图标）；④ `_drag_dx/_dy` 在 `__init__` 初始化为 0。

### Task 8: 展开面板（进度条、今日 Token、MCP、24h 迷你柱状图、悬停逻辑）

**Files:**
- Modify: `widget.py`
- Test: 手动验证

- [ ] **Step 1: 在 UsageApp 中加入面板**

在 `__init__` 的 `self._build_badge()` 之后加一行：

```python
        self._build_panel()
```

在 `_build_badge` 方法后追加面板构建与渲染：

```python
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

    def _build_panel(self):
        self.panel = tk.Toplevel(self.root)
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        self.panel.attributes("-alpha", 0.95)
        self.panel.configure(bg=BG)
        self.panel.withdraw()
        self.panel.bind("<Enter>", lambda e: None)  # 悬停面板时不收回
        self.panel.bind("<Leave>", self.schedule_hide)
        self.panel.bind("<Button-3>", lambda e: self.root.destroy())

        g = tk.Frame(self.panel, bg=BG)
        g.pack(fill="both", expand=True, padx=10, pady=8)

        self.p_title = tk.Label(g, text="GLM Coding Plan", font=FONT, bg=BG, fg=FG)
        self.p_title.grid(row=0, column=0, columnspan=3, sticky="w")

        self.p_bars = []          # [(canvas, rect, pct_label), ...] 窗口A/B
        for i, name in enumerate(("窗口A", "窗口B")):
            tk.Label(g, text=name, font=FONT, bg=BG, fg=COL_DIM)\
                .grid(row=1 + i, column=0, sticky="w")
            c, rect = self._make_bar(g)
            c.grid(row=1 + i, column=1, pady=2)
            lab = tk.Label(g, text="0%", font=FONT, bg=BG, fg=FG, width=5)
            lab.grid(row=1 + i, column=2, sticky="w")
            self.p_bars.append((c, rect, lab))

        self.p_today = tk.Label(g, text="今日 Token  0", font=FONT, bg=BG, fg=FG,
                                justify="left", anchor="w")
        self.p_today.grid(row=3, column=0, columnspan=3, sticky="we", pady=(6, 0))
        self.p_models = [
            tk.Label(g, text="", font=FONT, bg=BG, fg=COL_DIM, anchor="w")
            for _ in range(4)
        ]
        for i, lab in enumerate(self.p_models):
            lab.grid(row=4 + i, column=0, columnspan=3, sticky="we")

        self.p_mcp_txt = tk.Label(g, text="MCP(月)  0/0  0%", font=FONT, bg=BG, fg=FG,
                                  anchor="w")
        self.p_mcp_txt.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        c, rect = self._make_bar(g)
        c.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        self.p_mcp_bar = (c, rect)

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
            h = int(v / peak * 34)
            x = 2 + i * (bw + 1)
            c.create_rectangle(x, 37 - h, x + bw, 37, fill=COL_OK, width=0)

    def _render_panel(self):
        d = self.data or {}
        warn, alert = self.cfg["warn_threshold"], self.cfg["alert_threshold"]
        if d.get("error") in ("NO_TOKEN", "NO_BASE_URL"):
            self.p_title.configure(text="未配置 Token")
            self.p_today.configure(text="请设置环境变量 ANTHROPIC_AUTH_TOKEN 与\n"
                                        "ANTHROPIC_BASE_URL 后重新启动本程序")
            return
        self.p_title.configure(text=f"GLM Coding Plan   更新 {self.last_ok}")
        wins = d.get("token_windows") or []
        for i, (canvas, rect, lab) in enumerate(self.p_bars):
            pct = wins[i].get("percentage", 0.0) if i < len(wins) else 0.0
            self._update_bar(canvas, rect, pct, color_for(pct, warn, alert))
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
        self.p_mcp_txt.configure(
            text=f"MCP(月)  {mcp['used']}/{mcp['total']}  {mcp['percentage']:.0f}%")
        self._draw_spark()
```

把 Task 7 的占位方法替换为真实现：

```python
    def show_panel(self):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        self._render_panel()
        bx, by = self.badge.winfo_x(), self.badge.winfo_y()
        screen_w = self.root.winfo_screenwidth()
        px = min(max(10, bx), screen_w - 280)
        py = by - 230
        if py < 10:                       # 徽章太靠上则翻转到下方
            py = by + 40
        self.panel.geometry(f"+{px}+{py}")
        self.panel.deiconify()

    def hide_panel(self):
        self.panel.withdraw()
```

（`schedule_hide` 保持 Task 7 实现，但把其中 `self._inside(self.badge, px, py)` 一行改为同时检查面板：`if self._inside(self.badge, px, py) or self._inside(self.panel, px, py):`）

- [ ] **Step 2: 面板需要演示数据，临时把 Task 7 的静态 `refresh` 数据补上 hourly**

Task 7 的静态 refresh 演示数据中 `"hourly": []` 改为：

```python
"hourly": [(f"2026-09-12 {h:02d}:00", (h * 37 % 100) * 100_000) for h in range(24)],
```

（24h 趋势需要非零数据才能看出柱状图效果；Task 9 会换回真实数据源。）

- [ ] **Step 3: 手动验证（需要用户配合观察）**

Run: `python widget.py`

验收点：
1. 鼠标悬停徽章 → 上方弹出深色面板：两条窗口进度条（5%/8% 绿色）、今日 Token 5.5M、MCP 进度条、24 根高低不一的迷你柱
2. 鼠标移到面板内 → 面板不收回；移出面板与徽章约半秒后 → 面板收回
3. 徽章贴屏幕顶部时悬停 → 面板翻转到底部弹出，不出屏
4. 拖动徽章时面板不跟随、立即收回，松手后位置已保存
5. 右键面板 → 退出程序
6. `python -m unittest -v` 仍全绿

- [ ] **Step 4: 提交**

```bash
git add widget.py
git commit -m "feat: 展开面板（进度条/今日Token/MCP/24h迷你柱状图）"
```

---

> **审查后修复（Task 8 质量审查，立即落地）：** ① 面板 `<Enter>` 绑定改为真正的 `_cancel_hide()`（取消 pending hide_job），`show_panel`/`_drag_start` 复用它——修复经徽章与面板翻转间隙进入面板时面板被自动收回的问题；② `hide_panel` 收回后清空 `hide_job`（消除过期句柄，`if self.hide_job` 守卫恢复诚实）；③ `show_panel` 的 `_render_panel()` 包 try/except + log（pythonw 下渲染异常不能静默杀死悬停）。
>
> **审查后修复（Task 8 质量审查，随 Task 9 必须同一提交落地）：** ① 面板网格行修正：`p_mcp_txt` → row 8、MCP 进度条 → row 9、`spark` → row 10（消除"其他"折叠行与 MCP 文本的同格叠印）；② `show_panel` 弃用硬编码 280x230（实测面板 299x270），改为 `update_idletasks()` 后用 `winfo_reqwidth()/winfo_reqheight()` 实测，横纵双向钳制、上/下双向翻转（否则面板盖住徽章、右缘裁 19px、贴近底部时柱状图出屏）；③ `_apply_position` 与 `_drag_end` 的屏幕钳制改用徽章实时尺寸（首次渲染后徽章为 161x31 而非 91x31，旧钳制允许右边 70px 出屏）；④ `_draw_spark` 柱高 `max(1, int(...))`（正的极小值画 1px 短柱而非不可见）。行修正会增加面板高度约 26px，几何量必须按最终布局一次算准。

### Task 9: 接入真实数据（后台线程、退避、异常兜底）

**Files:**
- Modify: `widget.py`
- Test: `python -m unittest`（已有测试不回归）+ 手动验证

- [ ] **Step 1: 导入 fetch_all 并替换刷新逻辑**

`widget.py` 顶部 import 区改为：

```python
from usage_api import fetch_all, format_tokens
```

把 Task 7/8 的 `refresh` / `_apply_data` 整体替换为：

```python
    # ---------- 数据刷新 ----------
    def refresh(self):
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        data = fetch_all()          # 永不抛异常
        self.root.after(0, lambda: self._apply_data(data))

    def _apply_data(self, data):
        try:
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
        except Exception as exc:
            log(f"UI 更新异常: {exc!r}")
        finally:
            delay = next_interval_sec(self.failures, self.cfg["refresh_interval_sec"])
            self.root.after(delay * 1000, self.refresh)
```

顶部 import 区补 `import threading`（放在 `import tkinter as tk` 之前，保持字母序）。

- [ ] **Step 2: 回归确认**

Run: `python -m unittest -v`
Expected: 全部 PASS（纯函数测试不涉及 refresh）

- [ ] **Step 3: 手动验证（需要用户配合观察）**

Run: `python widget.py`

验收点：
1. 启动约 1 秒内徽章从 `⚡ …` 变为真实数据（数值与 bigmodel.cn 网页一致）
2. 悬停面板，`更新 HH:MM` 与真实时间相符
3. 断网测试：拔网/关 Wi-Fi 后等下一轮（或临时把 config.json 的 `refresh_interval_sec` 改成 5 观察），徽章变 `⚠ HH:MM` 黄色；恢复网络后下一轮自动恢复绿色真实数据
4. 关掉程序确认 `widget.log` 要么不存在要么只有断网期间的"拉取失败"记录
5. 任务管理器：pythonw/python 进程内存 <50MB，空闲时 CPU 0%

- [ ] **Step 4: 提交**

```bash
git add widget.py
git commit -m "feat: 后台线程拉取真实数据与失败退避"
```

---

> **审查修正（Task 9 质量审查 Critical，计划自身携带的缺陷）：** 原计划中 `_render_badge` 渲染 `self.data`（仅成功时更新），错误态不可达——断网徽章 ⚠ 与"未配置"永远不显示，违反验收标准。修正：新增 `self.latest` 保存最新拉取结果（含错误态），徽章渲染改用 `self.latest`；`_render_panel` 增加通用错误标题"更新失败 HH:MM，重试中"（数字保留最后成功值）；面板定位抽取为 `_position_panel()`，面板展开中收到新数据时原位重渲染并重新定位；`_fetch_worker` 包 try/except + log 兜底；补 2 个应用级错误态测试（真实 Tk 根 + stub fetch_all，防止回归）。
>
> **审查修正（Task 9 质量审查 Important，多显示器决策）：** 拖动松手时按主屏尺寸钳制会把副屏上的徽章弹回主屏并持久化错误位置。决策：`_clamp_badge_position` 保留为**仅启动时**的安全网（换显示器/改分辨率后位置失效时钳回主屏），`_drag_end` 与渲染后的 `after_idle` 钳制均移除——拖动是用户自主摆放，不干预；Task 10 README 说明此策略。
>
> **顺带（Task 9 质量审查 Minor）：** TestLog 两处 `open()` 改为 with 语句消除 ResourceWarning；断网测试用小 `refresh_interval_sec` 并在 README 说明 3 次失败后退避 300s 的恢复延迟。

### Task 10: README 与收尾

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README**

````markdown
# GLM Coding Plan 用量悬浮窗

Windows 桌面置顶悬浮徽章，实时显示 GLM Coding Plan 消耗：
5 小时窗口用量、今日 Token、MCP 月度用量、24 小时趋势。零第三方依赖。

## 启动

```bash
cd D:\workspace\ai\glm-usage-widget
pythonw widget.py
```

前提：环境变量 `ANTHROPIC_AUTH_TOKEN` 与 `ANTHROPIC_BASE_URL` 已设置
（与 Claude Code 使用 GLM 时的配置相同）。未设置时徽章显示"未配置"。

## 操作

| 操作 | 效果 |
|------|------|
| 鼠标悬停徽章 | 展开详细面板 |
| 移出面板 | 约 0.5s 后自动收回 |
| 左键拖动 | 移动位置（自动记忆） |
| 右键 | 退出程序 |

## 开机自启（可选）

1. `Win+R` 输入 `shell:startup` 回车
2. 在该文件夹新建快捷方式，目标：
   `"C:\...\pythonw.exe" D:\workspace\ai\glm-usage-widget\widget.py`
   （pythonw.exe 的完整路径用 `python -c "import sys; print(sys.executable.replace('python.exe','pythonw.exe'))"` 查询）
3. 注意：环境变量需是"系统/用户级"设置，仅会话级 set 设置的开机自启读不到

## 配置（config.json，可手工编辑）

| 字段 | 默认 | 说明 |
|------|------|------|
| refresh_interval_sec | 60 | 刷新间隔秒数 |
| alert_threshold | 80 | >=此百分比变红 |
| warn_threshold | 50 | >=此百分比变黄 |
| badge_position | [80,80] | 徽章位置（拖动自动更新） |

## 测试

```bash
python -m unittest -v
```

## 数据来源

`https://open.bigmodel.cn/api/monitor/usage/*`（与官方用量页同源），
用 `Authorization: <ANTHROPIC_AUTH_TOKEN>` 头认证，无 cookies、无登录。
````

- [ ] **Step 2: 全量回归 + 最终提交**

Run: `python -m unittest -v`
Expected: 全部 PASS

```bash
git add README.md
git commit -m "docs: 使用说明与自启配置"
```

---

## 手动验收总清单（对照 spec）

- [ ] 置顶浮于其他窗口之上
- [ ] 拖动后重启位置还原
- [ ] 悬停展开 / 移出 0.5s 收回 / 顶部翻转
- [ ] 四项指标数值与 bigmodel.cn 用量页一致
- [ ] 断网徽章 ⚠、恢复后自动恢复
- [ ] 阈值着色（可临时把 warn 阈值改 1 验证黄色）
- [ ] 内存 <50MB、空闲 CPU 0%
- [ ] 未配置 token 时显示"未配置"而非崩溃
