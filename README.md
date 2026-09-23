# GLM Coding Plan 用量悬浮窗

Windows 桌面置顶悬浮徽章，实时显示 GLM Coding Plan 消耗：
5 小时窗口用量、今日 Token、MCP 月度用量、24 小时趋势。零第三方依赖。

## 启动

```bash
cd D:\workspace\ai\glm-usage-widget
pythonw widget.py
```

前提：认证配置在 config.json 的 `token` / `base_url` 字段（该文件不会提交到 git）。
首次启动会自动从环境变量 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` 迁移写入；
环境变量仅作兜底。未配置时徽章显示"未配置"，此时点面板上的
**「填写 token / 接口地址」按钮**即可在界面里填写（接口地址预填
`https://open.bigmodel.cn`，自动规范化），保存后立即生效，无需重启。

## 操作

| 操作 | 效果 |
|------|------|
| 鼠标悬停徽章 | 展开详细面板 |
| 移出面板 | 约 0.5s 后自动收回 |
| 左键拖动 | 移动位置（松手自动保存） |
| 右键徽章/面板 | 弹出菜单：手动刷新 / 最小化到系统任务栏 / 退出 |
| 未配置时点面板按钮 | 弹出配置窗口（url 已预填），保存立即生效 |
| 托盘图标左键 | 恢复徽章 |
| 托盘图标右键 | 菜单：恢复 / 手动刷新 / 退出 |

## 开机自启（可选）

1. `Win+R` 输入 `shell:startup` 回车
2. 在该文件夹新建快捷方式，目标：
   `"C:\...\pythonw.exe" D:\workspace\ai\glm-usage-widget\widget.py`
   （pythonw.exe 的完整路径用
   `python -c "import sys; print(sys.executable.replace('python.exe','pythonw.exe'))"` 查询）
3. 注意：config.json 已含认证配置，无额外环境变量要求；若依赖环境变量兜底，
   则变量需是"系统/用户级"设置（仅会话级 set 的开机自启读不到）

## 配置（config.json，可手工编辑，改完重启程序生效）

| 字段 | 默认 | 说明 |
|------|------|------|
| refresh_interval_sec | 60 | 刷新间隔秒数（正整数，小数会取整，<1 视为非法回退默认） |
| alert_threshold | 80 | >=此百分比变红 |
| warn_threshold | 50 | >=此百分比变黄 |
| badge_position | [80,80] | 徽章位置（拖动自动更新） |
| token | （空） | 接口认证 token，自动从环境变量迁移；不会提交到 git |
| base_url | （空） | 接口域名，**只填协议+域名**（见下方说明），同样自动迁移 |

**base_url 填写规则**（程序只在此域名后拼接 `/api/monitor/usage/...`，路径会自动剥离）：

| 填写值 | 结果 |
|--------|------|
| `https://open.bigmodel.cn` | ✅ 正确（智谱国内版） |
| `https://api.z.ai` | ✅ 正确（智谱国际版） |
| `https://open.bigmodel.cn/api` | ❌ 错误——启动时会自动剥离成纯域名并写回 |
| 留空 `""` | ✅ 从环境变量 `ANTHROPIC_BASE_URL` 迁移（同样自动规范化） |

配置为异常时按字段回退默认值。注意：**warn 与 alert 是成对校验的**——
若 alert <= warn，两个字段会整体回退默认值，不会出现"只改一个"的中间态。

## 行为说明

- **手动刷新说明**：点击后重新拉取全部最新数据（今日 Token 消耗量 + 双窗口
  额度百分比 + 24 小时趋势），面板标题会短暂显示"刷新中…"。注意：额度百分比
  随时间窗口滑动自然下降是正常现象（不是重置）；若刷新后消耗量没变，说明
  查询时刻确实没有新的 token 消耗，或网络瞬断（徽章会显示 ⚠）。
- **面板里「5小时」「每周」两条是官方双限额机制**：智谱套餐采用
  "每 5 小时限额 + 每周限额"（见 docs.bigmodel.cn FAQ），两条独立计算、独立重置；
  每条下方显示各自的重置倒计时；徽章上的 `5h:%` 指其中 5 小时窗口的用量
  （不是两者取大）。「MCP月度额度」行显示已用次数/总量、重置时间与用量进度条。
- **位置钳制仅在启动时生效**：若保存的位置因换显示器/改分辨率完全失效，
  启动时会钳回主屏；拖动摆放（含副屏）不作干预。
- **失败退避**：连续失败 >=3 次后，刷新间隔自动放宽到 300s；网络恢复后最长
  需等 5 分钟才会恢复数据（想立即恢复可右键退出重开，或把 refresh_interval_sec
  临时调小）。断网时徽章显示黄色 `⚠ 最后成功时间`。
- **错误与日志**：接口异常（含 token 过期，服务端返回 code 非 200）会走错误
  路径并在 `widget.log` 记录（超过 1MB 自动清空重写），不会静默显示假数据。
- **最小化到托盘**：徽章隐藏后通知区域（右下角）出现图标，后台轮询照常；左键图标
  恢复。托盘创建失败时徽章保持显示、可再次右键重试（不会藏起来找不回）。
- **更换 token**：直接编辑 config.json 的 token 字段后重启；清空该字段并移除环境
  变量再重启则回到"未配置"状态（仅清 config 而留环境变量会被重新迁移）。

## 资源占用

实测常驻约 50-53MB（含 Tcl/Tk 运行时），空闲 CPU 0%。

## 测试

```bash
python -m unittest -v                      # 88 项单元/组件测试
python tests/e2e_acceptance.py             # 20 项端到端验收（屏幕会闪现窗口/托盘图标）
```

## 打包为可执行文件

```bash
pip install pyinstaller      # 首次需要
build.bat                    # 单文件 exe（默认），产物 dist\onefile\GLMUsageWidget.exe
build.bat onedir             # 目录形式：启动更快、杀软误报更少
```

运行 exe 后 config.json / widget.log 生成在 **exe 同目录**（不会写进临时目录）。
首次运行自动从环境变量迁移认证，或把已填好的 config.json 放到 exe 旁边。

## 数据来源

`https://open.bigmodel.cn/api/monitor/usage/*`（与官方用量页同源），
认证：config.json 的 `token`（环境变量兜底）经 `Authorization` 头发送，无 cookies、无登录。
