# GLM Coding Plan 用量悬浮窗 — 设计文档

日期：2026-09-12
状态：已确认（用户逐节过目）

## 背景与目标

用户订阅了 GLM Coding Plan，希望在 Windows 桌面上有一个**常驻悬浮小组件**，实时查看套餐消耗，无需打开浏览器登录 bigmodel.cn。

关键事实（已验证）：查询用量的 monitor 接口使用 `ANTHROPIC_AUTH_TOKEN` 环境变量认证（本机已持久化设置），**不需要浏览器 cookies**，不存在登录过期问题。

## 需求

- 形态：置顶悬浮徽章 + 悬停展开面板（用户选定）
- 显示指标（用户选定，全选）：
  1. 5 小时窗口 Token 用量百分比（两个窗口分条显示）
  2. 今日 Token 消耗（总数 + 按模型分项）
  3. MCP 月度用量（已用/总量 + 百分比）
  4. 近 24 小时逐小时消耗迷你柱状图
- 徽章可拖动，位置记忆
- 技术栈：Python 3.12 + tkinter（用户选定），**零第三方依赖**

## 非目标

- 不做弹窗告警（仅徽章/面板内颜色变化）
- 不做 cookies / 浏览器自动化方案
- 不显示 MCP 各工具分项明细（仅月度总量）

## 架构

```
D:\workspace\ai\glm-usage-widget\
├── widget.py      # 入口：tkinter 主程序（置顶、拖动、徽章/面板切换、定时刷新）
├── usage_api.py   # 数据层：读环境变量、urllib 调 monitor 接口、解析为统一结构
├── config.json    # 运行配置（自动生成）
├── widget.log     # 错误日志（自动生成，>1MB 清空重写）
├── tests/
│   ├── fixtures/  # 真实接口响应样例 JSON
│   └── test_usage_api.py
└── docs/superpowers/specs/   # 本文档
```

### 数据流

1. tkinter `after()` 定时器（默认 60s）触发
2. `threading.Thread` 后台线程调用 `usage_api.fetch_all()`（不阻塞 UI）
3. 结果（或异常信息）通过 `root.after(0, ...)` 回到 UI 线程更新界面
4. 徽章始终显示最新摘要；面板展开时实时渲染

### 接口调用（每次刷新仅 2 个请求）

Base URL 取 `ANTHROPIC_BASE_URL` 的域名部分（本机为 `https://open.bigmodel.cn`）。

| 请求 | 用途 |
|------|------|
| `GET {base}/api/monitor/usage/model-usage?startTime=...&endTime=...` | 今日消耗 + 24h 趋势 |
| `GET {base}/api/monitor/usage/quota/limit` | 5h 窗口百分比 + MCP 月度用量 |

- 认证头：`Authorization: <ANTHROPIC_AUTH_TOKEN 原值>`（无 Bearer 前缀），`Content-Type: application/json`
- 时间参数格式 `yyyy-MM-dd HH:mm:ss`，需 URL 编码
- **查询窗口统一取"昨天 00:00 → 现在"**：返回的逐小时数组带时间标签，客户端按标签聚合——标签 ≥ 今天 00:00 的桶求和即"今日消耗"，全量数组即"24h 趋势"，避免重复请求
- `tool-usage` 接口**不调用**：MCP 月度用量已包含在 quota/limit 的 `TIME_LIMIT` 条目中

### 关键响应字段（来自真实抓包，2026-09-12）

`model-usage`：
- `x_time[]`：小时标签数组，如 `"2026-09-12 17:00"`
- `tokensUsage[]`：与标签对齐的每小时 token 数
- `totalUsage.totalTokensUsage`：窗口内总 token
- `totalUsage.modelSummaryList[]`：`{modelName, totalTokens}` 按模型分项

`quota/limit`：
- `limits[]`，其中 `type=TOKENS_LIMIT` 的条目（**可能有两条**，代表两个 5 小时窗口）取 `percentage`
- `type=TIME_LIMIT` 条目：`percentage`、`currentUsage`（已用次数）、`usage`（总量）、`usageDetails[]`（按工具分项，暂不展示）

### 解析后的统一结构（usage_api 返回值）

```python
{
  "token_windows": [{"percentage": 5}, {"percentage": 8}],   # 0~100 数值
  "mcp": {"used": 38, "total": 4000, "percentage": 1.0},
  "today": {"total_tokens": 76548147,
            "models": [{"name": "GLM-5.3", "tokens": 18275017},
                       {"name": "GLM-5.3-Flash", "tokens": 78588249}]},
  "hourly": [("2026-09-11 18:00", 1558704), ...],            # 24h 趋势
  "fetched_at": "2026-09-12 19:00:05"
}
```

任何字段缺失/结构变化 → 对应键返回 `None`，UI 侧显示"数据异常"，**解析函数永不抛异常**。

## UI 规格

### 徽章态

- 约 150×28 px，无边框（`overrideredirect(True)`），`-topmost`，深色背景（#1e1e2e），整体 alpha 0.9
- 内容：`⚡ 5h: 8% │ MCP: 1%`（5h 取两个窗口的最大值）
- 颜色：<50% 绿(#a6e3a1)，50~79% 黄(#f9e2af)，≥80% 红(#f38ba8)（阈值可配置）
- 交互：鼠标进入 → 展开面板；**按住左键即进入拖动模式并强制收回面板**，移动结束（松开）后位置写入 config.json

### 展开态

- 约 260×190 px，同风格深色面板，出现在徽章正上方（越界时自动翻转方向）
- 自上而下：
  1. 两条 5h 窗口进度条（标签"窗口A/窗口B"，右端百分数）
  2. 今日 Token：人性化格式（如 `76.5M`、`1.2K`），下方按模型分项对齐右列
  3. MCP 月度：进度条 + `38/4000`
  4. 24h 趋势：Canvas 迷你柱状图（约 230×40px，零值不画柱）
- 着色规则统一：所有进度条与百分数均按阈值着色（<50% 绿，50~79% 黄，≥80% 红）
- 鼠标移出面板区域 500ms 后自动收回徽章

### 启动与自启（可选，不在首版必做范围）

- 启动命令 `pythonw widget.py`（无控制台窗口）
- 开机自启：手动放快捷方式到 `shell:startup`，文档中说明步骤即可

## 配置（config.json）

```json
{
  "refresh_interval_sec": 60,
  "alert_threshold": 80,
  "warn_threshold": 50,
  "badge_position": [1620, 40]
}
```

- 不存在 → 生成默认值；JSON 损坏或字段类型非法 → 该字段回退默认，继续运行（配置问题不阻断启动）

## 错误处理

| 场景 | 行为 |
|------|------|
| 网络失败/超时(10s) | 徽章显示 `⚠ 14:32`（最后成功时间），保留旧数据 |
| 连续失败 ≥3 次 | 间隔放宽到 300s，成功后恢复 |
| `ANTHROPIC_AUTH_TOKEN` 未设置 | 徽章显示 `⚡ 未配置`，面板给出设置说明 |
| 非 200 / 字段结构变化 | 显示"数据异常"，写入 widget.log |
| 零消耗/新窗口 | 显示 0%，不出现 NaN/除零 |

原则：**任何异常不得使悬浮窗崩溃退出**；UI 线程所有回调包 try/except 兜底，未预期异常记日志。

## 测试

1. **单元测试**（unittest）：`tests/fixtures/` 存放真实响应 JSON；覆盖——百分比提取、今日聚合（跨零点边界）、24h 切分、人性化数字格式化、字段缺失容错。`python -m unittest discover tests` 全绿
2. **手动验收**：置顶浮于其他窗口之上；拖动重启位置还原；悬停展开/移出收回；断网 ⚠ 后恢复自动刷新；任务管理器确认内存 <50MB、空闲 CPU 0%

## 里程碑

1. `usage_api.py` + fixtures + 单元测试
2. `widget.py` 徽章态（置顶/拖动/颜色）
3. 展开面板（进度条/趋势图）
4. 错误处理 + 配置持久化 + 手动验收
