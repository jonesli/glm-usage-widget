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
| 左键拖动 | 移动位置（松手自动保存） |
| 右键 | 退出程序 |

## 开机自启（可选）

1. `Win+R` 输入 `shell:startup` 回车
2. 在该文件夹新建快捷方式，目标：
   `"C:\...\pythonw.exe" D:\workspace\ai\glm-usage-widget\widget.py`
   （pythonw.exe 的完整路径用
   `python -c "import sys; print(sys.executable.replace('python.exe','pythonw.exe'))"` 查询）
3. 注意：环境变量需是"系统/用户级"设置，仅会话级 set 设置的开机自启读不到

## 配置（config.json，可手工编辑，改完重启程序生效）

| 字段 | 默认 | 说明 |
|------|------|------|
| refresh_interval_sec | 60 | 刷新间隔秒数（正整数，小数会取整，<1 视为非法回退默认） |
| alert_threshold | 80 | >=此百分比变红 |
| warn_threshold | 50 | >=此百分比变黄 |
| badge_position | [80,80] | 徽章位置（拖动自动更新） |

配置为异常时按字段回退默认值。注意：**warn 与 alert 是成对校验的**——
若 alert <= warn，两个字段会整体回退默认值，不会出现"只改一个"的中间态。

## 行为说明

- **位置钳制仅在启动时生效**：若保存的位置因换显示器/改分辨率完全失效，
  启动时会钳回主屏；拖动摆放（含副屏）不作干预。
- **失败退避**：连续失败 >=3 次后，刷新间隔自动放宽到 300s；网络恢复后最长
  需等 5 分钟才会恢复数据（想立即恢复可右键退出重开，或把 refresh_interval_sec
  临时调小）。断网时徽章显示黄色 `⚠ 最后成功时间`。
- **错误与日志**：接口异常（含 token 过期，服务端返回 code 非 200）会走错误
  路径并在 `widget.log` 记录（超过 1MB 自动清空重写），不会静默显示假数据。

## 资源占用

实测常驻约 50-53MB（含 Tcl/Tk 运行时），空闲 CPU 0%。

## 测试

```bash
python -m unittest -v                      # 54 项单元/组件测试
python tests/e2e_acceptance.py             # 14 项端到端验收（屏幕会闪现窗口）
```

## 数据来源

`https://open.bigmodel.cn/api/monitor/usage/*`（与官方用量页同源），
用 `Authorization: <ANTHROPIC_AUTH_TOKEN>` 头认证，无 cookies、无登录。
