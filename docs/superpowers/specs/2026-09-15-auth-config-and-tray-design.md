# 认证配置文件化 + 右键菜单/托盘 — 设计文档（spec 增补）

日期：2026-09-15
状态：已确认（方案与设计逐节过目）
基线：2026-09-12 用量悬浮窗 spec（已交付，57 单测 + 14 e2e 全绿）

## 背景与目标

两项用户提出的优化：

1. **认证配置文件化**：token 与 base_url 不再依赖环境变量，迁入工程配置文件 config.json
2. **右键菜单**：徽章右键从"直接退出"改为弹出菜单，含"最小化到系统任务栏"（托盘图标）与"退出"两项

## 需求确认记录

- 配置文件形态：**并入现有 config.json**（用户选定），首次启动自动从环境变量迁移，env 保留兜底
- "最小化到系统任务栏"：**最小化到托盘图标**（用户选定）——徽章消失，通知区域出现图标，左键恢复
- 托盘技术路线：**ctypes Shell_NotifyIcon + 独立消息线程**（纯标准库唯一成熟路线；pystray 违背零依赖约束，弃用）

## 功能 1：认证配置文件化

### config.json 新 schema

```json
{
  "refresh_interval_sec": 60,
  "alert_threshold": 80,
  "warn_threshold": 50,
  "badge_position": [80, 80],
  "token": "",
  "base_url": ""
}
```

### 规则

- **校验**：`load_config` 增加字符串分支——`token`/`base_url` 接受非空字符串（strip 后入库）；缺失/非法/空回退 `""`。两键加入 `DEFAULTS`（默认空串）。数值字段的既有校验不变
- **迁移（`resolve_auth(cfg)`，`UsageApp.__init__` 调用一次）**：
  - cfg 中某键为空且对应 env（`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL`）有值 → 用 env 值填充 cfg 并 `save_config` 持久化
  - 值只写文件、不打印（防泄露）；config 已填的值优先，env 永不覆盖
  - env 也为空 → 不写文件；写失败走 `save_config` 现有原子写 + log 兜底，cfg 内存值仍生效
- **数据流**：`_fetch_worker` 改为 `fetch_all(token=self.cfg.get("token") or None, base_url=self.cfg.get("base_url") or None)`。传 `None` 时 `fetch_all` 内部回落 env（现有逻辑零改动）；两者皆空且 env 无值 → 现有 `NO_TOKEN` 错误路径 → 徽章"未配置"
- **文案**：面板 `未配置 Token` 分支指引改为"请在 config.json 设置 token 与 base_url 后重新启动"；README 同步（env 从"必须"改为"兜底"）

### 安全

- config.json 已在 `.gitignore`，token 不入库
- token 全程仅出现在：config 文件、内存、Authorization 头；不打印、不进日志（沿用既有契约测试）
- 迁移写文件用现有 `save_config`（临时文件 + `os.replace` 原子写）

## 功能 2：右键菜单 + 托盘图标

### 新文件 trayicon.py（单一职责）

```python
class TrayIcon:
    def __init__(self, callbacks)   # on_restore / on_menu，由 Tk 侧注入
    def show(self) -> bool          # 创建图标 + 启动消息线程；成功 True
    def hide(self)                  # 移除图标 + 停线程
```

- Win32：`Shell_NotifyIconW`（NIM_ADD/NIM_DELETE）+ 后台消息线程（自建窗口 + WNDPROC），回调消息 `WM_APP+1`
- 线程 → Tk 通信：托盘左键 → `on_restore` → Tk 侧 `root.event_generate('<<TrayRestore>>')`；托盘右键 → `on_menu` → `'<<TrayMenu>>'`（event_generate 线程安全，是标准做法）
- 图标：程序化生成 16×16 BGRA 内存位图（深底亮心圆点）→ `CreateIconIndirect`；失败回退 `LoadIcon` 默认图标。无图标文件依赖
- 托盘右键菜单的简化取舍：不使用原生 TrackPopupMenu，右键事件回 Tk 侧后由 `tk.Menu` 在屏幕右下角（托盘附近）弹出——与徽章右键复用同一个菜单

### 状态机（UsageApp 三态）

```
normal（徽章显示，无托盘）
   │ 右键菜单→"最小化到系统任务栏"（且 tray.show() 成功）
   ▼
minimized（徽章+面板 withdraw，托盘显示，后台轮询照常）
   │ 托盘左键 / 托盘菜单"恢复"
   ▼
normal
任意态 → "退出" → quit_app()：tray.hide() → root.destroy()
```

- 右键行为替换：徽章与面板的 `<Button-3>` 改为 `popup_menu()`——`tk.Menu(tearoff=0)`，两项："最小化到系统任务栏"、"退出"；托盘菜单在徽章菜单基础上多一项"恢复"（minimized 态下）
- 恢复：按 `badge_position` 落位 + 现有启动钳制；重复最小化幂等（已 minimized 再点无效）
- **退化**：`tray.show()` 失败 → 菜单不出现最小化项（只留"退出"），log 记录原因；徽章保持显示，绝不出现"藏起来找不回"的死局
- 线程异常：消息线程 try/except → log；下次最小化重试创建

## 错误处理汇总

| 场景 | 行为 |
|------|------|
| Shell_NotifyIcon 失败 | 菜单无最小化项，log 记录，UI 不隐藏 |
| 消息线程异常退出 | 线程内捕获 → log，下次最小化重试 |
| token/base_url 带空格 | strip 后入库；空串视为未配置 |
| 迁移写文件失败 | log + cfg 内存生效，下次启动重试 |
| 退出竞态 | 统一 `quit_app()`（先 tray.hide 后 destroy），无孤儿图标 |
| 既有 57 项测试 | 全部保持通过（接口层零改动） |

## 测试策略（全部自动化，无人工肉眼验收）

**单元测试（新增约 8 项）**

- load_config：token/base_url 字符串解析、strip、非法回退
- resolve_auth：env→config 迁移写入（mock env）、config 已填不覆盖、env 全空不动文件
- fetch 传参：stub `widget.fetch_all` 捕获 kwargs，断言 token/base_url 来自 cfg
- trayicon 纯函数：位图像素生成边界

**e2e（现有 14 项改造 + 新增约 5 项）**

- T7 改造：右键 → 断言菜单两项存在；退出经 `quit_app()`
- T11 菜单项断言；T12 最小化（真实 Shell_NotifyIcon）→ 徽章消失 + 托盘创建成功
- T13 托盘左键回调 → 徽章按保存位置恢复
- T14 认证迁移端到端（临时 CONFIG_PATH + mock env → 文件含 token、fetch 收到它）
- T15 整链冒烟：迁移后的真实 token 拉真实数据渲染真实值

## 非目标

- 不做托盘气泡通知 / 动态图标（用量颜色）——YAGNI，后续可加
- 不做多凭据/多账号
- 不改 usage_api.py 的 `fetch_all` 签名与 env 兜底逻辑

## 文档

- README：配置表加 token/base_url（注明不入 git）、操作表加最小化/托盘、env 表述改为兜底
- 本 spec 提交至 docs/superpowers/specs/
