"""端到端验收脚本：把手动验收清单自动化。

运行：python tests/e2e_acceptance.py
- 主流程：真实 Tk 窗口逐项验证置顶/悬停/收回/翻转/拖动/位置记忆/真实数据/右键菜单/托盘三态/退出
- 子进程：认证迁移（暂存真实 config → 假 env 触发 token 写入与 ⚠ → 恢复 config）
- 子进程：断网模拟（BASE_URL 指向不可达端口，走真实 socket 失败路径）
- 子进程：内存占用测量（独立运行 widget.py，tasklist 查询）

注意：运行时屏幕上会闪现徽章/面板/托盘图标数秒，属正常现象。
"""

import contextlib
import ctypes
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import tkinter as tk

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import widget
from trayicon import WM_APP_TRAY, WM_LBUTTONUP
from usage_api import fetch_all, format_tokens

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def in_range(actual, expect, tol=2):
    return all(abs(a - e) <= tol for a, e in zip(actual, expect))


@contextlib.contextmanager
def staged_config():
    """暂存真实 config.json（sidecar 落盘防硬杀丢失），with 块内处于"无 config"状态。

    子进程被硬杀时 finally 不会执行——sidecar 兜底：main() 启动时恢复遗留 sidecar。
    """
    cfg_path = widget.CONFIG_PATH
    backup_path = cfg_path + ".e2e-backup"
    backup = None
    if os.path.exists(cfg_path):
        backup = open(cfg_path, "rb").read()
        with open(backup_path, "wb") as f:
            f.write(backup)
        os.remove(cfg_path)
    try:
        yield
    finally:
        if backup is not None:
            tmp = backup_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(backup)
            os.replace(tmp, cfg_path)
            if os.path.exists(backup_path):
                os.remove(backup_path)
        elif os.path.exists(backup_path):
            os.replace(backup_path, cfg_path)


def run_e2e():
    root = tk.Tk()
    root.withdraw()
    app = widget.UsageApp(root)
    root.update()

    # T1 置顶
    top_badge = bool(app.badge.attributes("-topmost"))
    app.show_panel()
    root.update()
    top_panel = bool(app.panel.attributes("-topmost"))
    check("T1 置顶(topmost)", top_badge and top_panel, f"badge={top_badge} panel={top_panel}")

    # T3 悬停展开
    check("T3a 悬停展开", bool(app.panel.winfo_ismapped()))
    check("T3b 面板标题", "GLM Coding Plan" in app.p_title.cget("text"),
          app.p_title.cget("text"))

    # T4 自动收回（直接驱动 500ms 定时器路径）
    app.hide_job = root.after(300, app.hide_panel)
    t0 = time.time()
    while app.panel.winfo_ismapped() and time.time() - t0 < 4:
        root.update()
    check("T4 自动收回", not app.panel.winfo_ismapped())

    # T5 顶部翻转（徽章贴顶时面板应翻到下方）
    app.badge.geometry("+10+10")
    root.update()
    app.show_panel()
    root.update()
    py = app.panel.winfo_y()
    badge_bottom = app.badge.winfo_y() + app.badge.winfo_height()
    check("T5 顶部翻转", py >= badge_bottom - 2,
          f"panel_y={py} badge_bottom={badge_bottom}")
    app.hide_panel()
    root.update()

    # T6 拖动：面板不弹 + 松手位置持久化（模拟事件流 +3,+4）
    app._dragging = True
    app.show_panel()
    root.update()
    check("T6a 拖动中面板不弹", not app.panel.winfo_ismapped())
    app._dragging = False
    app.badge.geometry("+300+200")
    root.update()
    app._drag_start(SimpleNamespace(x=5, y=5))
    app._drag_move(SimpleNamespace(x=8, y=9))
    root.update()          # 让 Tk 处理 geometry 请求，再读回位置
    app._drag_end(SimpleNamespace(x=8, y=9))
    root.update()
    check("T6b 拖动清除标志", app._dragging is False)
    saved = json.load(open(widget.CONFIG_PATH, encoding="utf-8")).get("badge_position")
    check("T6c 位置持久化", in_range(saved, [303, 204]), f"saved={saved}")

    # T9 位置记忆（模拟重启后按配置落位）
    app.cfg["badge_position"] = [150, 150]
    app._apply_position()
    root.update()
    actual = (app.badge.winfo_x(), app.badge.winfo_y())
    check("T9 启动位置应用", actual == (150, 150), f"actual={actual}")

    # T2 真实数据一致性（徽章/面板渲染值 == 接口返回值）
    data = fetch_all()
    if "error" in data:
        check("T2 真实数据一致性", False, f"接口错误: {data['error'][:120]}")
    else:
        app._apply_data(data)
        root.update()
        wins = data["token_windows"]
        pct5 = next((w["percentage"] for w in wins
                     if str(w.get("label", "")).startswith("5小时")),
                    max((w["percentage"] for w in wins), default=0.0))
        expect5 = f"5h:{pct5:.0f}%"
        expect_mcp = f"MCP:{data['mcp']['percentage']:.0f}%"
        got = f"{app.lb_5h.cget('text')}|{app.lb_mcp.cget('text')}"
        check("T2a 徽章=接口数据", got == f"{expect5}|{expect_mcp}", f"got={got}")
        app.show_panel()
        root.update()
        today_txt = app.p_today.cget("text")
        expect_today = f"今日 Token  {format_tokens(data['today']['total_tokens'])}"
        check("T2b 面板今日Token", today_txt == expect_today, f"got={today_txt}")
        app.hide_panel()

    # T11 右键菜单。Windows 的 tk_popup 走原生 TrackPopupMenu 模态循环（阻塞在
    # post 内，winfo_ismapped 观察不到原生菜单）：after 回调能在该循环内执行即证明
    # 菜单真实弹出，随后 EndMenu() 退出循环。绑定被替换为探针但内部仍走真实 handler。
    # 依赖：Tk 会在原生模态循环内服务 after 定时器（Win11/Tk8.6 实测成立）；若失效 T11a 会 FAIL 且菜单残留，Esc 可关。运行期间误点鼠标也可能假失败。
    menu_state = {"binding": False, "in_modal": False, "returned": False}
    orig_popup = app.popup_badge_menu

    def popup_probe(e=None):
        menu_state["binding"] = True
        orig_popup(e)
        menu_state["returned"] = True

    def in_modal_probe():
        menu_state["in_modal"] = True
        ctypes.windll.user32.EndMenu()

    app.badge.bind("<Button-3>", popup_probe)
    root.after(300, in_modal_probe)
    app.badge.event_generate("<Button-3>", x=5, y=5)   # 同步进入原生菜单模态循环
    root.update()
    check("T11a 菜单弹出", all(menu_state.values()), str(menu_state))
    labels = [app.badge_menu.entrycget(i, "label")
              for i in range(app.badge_menu.index("end") + 1)]
    check("T11b 菜单项", labels == ["手动刷新", "最小化到系统任务栏", "退出"], str(labels))

    # T12 最小化到托盘（真实 Shell_NotifyIcon，通知区域会短暂出现图标）
    app.minimize_to_tray()
    root.update()
    check("T12a 最小化状态", app.minimized and not app.badge.winfo_ismapped())
    check("T12b 托盘图标创建", app._tray is not None and app._tray._ok)

    # T13 托盘恢复——必须走真实桥接（PostMessage → 消息线程 → event_generate → 绑定）。
    # 跨线程 event_generate 要求主线程在 mainloop 内（update 轮询会得到
    # "main thread is not in main loop"），故在 mainloop 里限时轮询；
    # <0.5s 映射断言防止“恢复冻结 3 秒”（C1）回归——直接调 restore_from_tray()
    # 无法发现该类回归（消息线程空闲时 join 立即返回）。
    tray_hwnd = app._tray._hwnd
    user32 = ctypes.windll.user32
    t0 = time.time()

    def poll_restore():
        if app.badge.winfo_ismapped() or time.time() - t0 > 2:
            root.quit()
        else:
            root.after(25, poll_restore)

    root.after(25, poll_restore)
    user32.PostMessageW(tray_hwnd, WM_APP_TRAY, 0, WM_LBUTTONUP)
    root.mainloop()
    elapsed = time.time() - t0
    check("T13 托盘恢复(真实桥接<0.5s)",
          (not app.minimized) and bool(app.badge.winfo_ismapped()) and elapsed < 0.5,
          f"elapsed={elapsed:.2f}s")

    # T7 退出（走 quit_app：含托盘清理）。mainloop 之后 update() 不再抛销毁异常，
    # 用 winfo_exists 探测（老 T7 同款手法）
    app.quit_app()
    try:
        gone = not app.badge.winfo_exists()
    except tk.TclError:
        gone = True          # "application has been destroyed" = 销毁成功
    check("T7 退出(quit_app)", gone)


def run_offline():
    """子进程模式：BASE_URL 指向不可达端口，走真实 socket 失败 → 徽章应显示 ⚠。

    凭据优先取 config（env 永不覆盖），真实 config 已带凭据时 env 失效、
    会真连生产接口——故先暂存移走 config 模拟未配置环境，结束后恢复；
    token 缺失时给占位值（端口不可达，凭据从不真正外发）。
    """
    with staged_config():
        os.environ["ANTHROPIC_AUTH_TOKEN"] = \
            os.environ.get("ANTHROPIC_AUTH_TOKEN") or "e2e-offline-token"
        os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
        root = tk.Tk()
        root.withdraw()
        app = widget.UsageApp(root)
        deadline = time.time() + 12          # socket 失败可能要等满 10s 超时
        state = {"done": False}

        def poll():
            txt = app.lb_5h.cget("text")
            if txt.startswith("…") and time.time() < deadline:
                root.after(250, poll)
                return
            state["done"] = True
            ok = txt.startswith("⚠")
            diag = (f"badge={txt} failures={app.failures} "
                    f"latest={'error' in (app.latest or {}) and app.latest['error'][:60]}")
            print(("PASS " if ok else "FAIL ") + f"T8 断网模拟 | {diag}", flush=True)
            if not ok:
                FAILS.append("T8 断网模拟")
            root.destroy()

        app.refresh()
        root.after(250, poll)
        root.mainloop()
        if not state["done"]:                # mainloop 提前结束（异常路径）
            print("FAIL T8 断网模拟 | mainloop 提前退出", flush=True)
            FAILS.append("T8 断网模拟")


def run_memory():
    """独立进程运行 widget.py，测量内存占用。"""
    proc = subprocess.Popen([sys.executable, os.path.join(APP_DIR, "widget.py")])
    time.sleep(6)
    out = subprocess.run(["tasklist", "/FI", f"PID eq {proc.pid}"],
                         capture_output=True, text=True).stdout
    ok, detail = False, "进程未找到"
    for line in out.splitlines():
        if str(proc.pid) in line:
            parts = line.split()
            mem_kb = int(parts[-2].replace(",", ""))
            detail = f"{mem_kb} K"
            ok = mem_kb < 61440          # 预算 60MB（实测典型 ~53MB，含 Tcl/Tk 运行时）
    proc.terminate()
    print(("PASS " if ok else "FAIL ") + "T10 内存占用(<60MB) | " + detail, flush=True)
    if not ok:
        FAILS.append("T10 内存占用")


def run_auth():
    """子进程：备份真实 config → 假 env 触发迁移 → 断言写入与 ⚠ → 恢复备份。"""
    with staged_config():
        # 迁移仅在 config 缺凭据时发生：暂存移走真实 config 模拟全新环境
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
        env["ANTHROPIC_AUTH_TOKEN"] = "e2e-fake-token"
        env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
        env["PYTHONIOENCODING"] = "utf-8"
        code = f"""
import sys, tkinter as tk
sys.path.insert(0, r'{APP_DIR}')
import widget
_fails = []
root = tk.Tk(); root.withdraw()
app = widget.UsageApp(root)
deadline = __import__('time').time() + 12
def poll():
    txt = app.lb_5h.cget('text')
    if txt.startswith('…') and __import__('time').time() < deadline:
        root.after(250, poll); return
    try:
        written = 'e2e-fake-token' in open(widget.CONFIG_PATH, encoding='utf-8').read()
    except OSError:
        written = False
    ok = written and txt.startswith('⚠')
    print(('PASS ' if ok else 'FAIL ') + f'T14 认证迁移 | badge={{txt}} written={{written}}', flush=True)
    if not ok:
        _fails.append('T14 认证迁移')
    root.destroy()
app.refresh()
root.after(250, poll)
root.mainloop()
if _fails:
    sys.stdout.flush(); __import__('os')._exit(1)
sys.stdout.flush(); __import__('os')._exit(0)
"""
        result = subprocess.run([sys.executable, "-c", code], env=env, cwd=APP_DIR,
                                timeout=40, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        sys.stdout.flush()
        for line in (result.stdout or "").splitlines():   # FAIL 行回填，让退出码有意义
            if line.startswith("FAIL"):
                FAILS.append(line.split("|")[0].strip()[len("FAIL "):])
        if result.returncode != 0 and not any("T14" in line
                                              for line in (result.stdout or "").splitlines()):
            FAILS.append("T14 认证迁移(子进程异常退出)")
            print("FAIL T14 认证迁移(子进程异常退出)", flush=True)


def main():
    # 崩溃恢复：上次运行被硬杀时 staged_config 的 finally 未执行，遗留 sidecar
    # （真实 config 在其中）。config 缺失则恢复之；config 存在则以 config 为准弃 sidecar。
    leftover = widget.CONFIG_PATH + ".e2e-backup"
    if os.path.exists(leftover) and not os.path.exists(widget.CONFIG_PATH):
        os.replace(leftover, widget.CONFIG_PATH)
        print("PASS T0 恢复上次运行遗留的 config 备份", flush=True)
    elif os.path.exists(leftover):
        os.remove(leftover)
    if "--auth" in sys.argv:
        run_auth()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)
    if "--offline" in sys.argv:
        run_offline()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)
    if "--memory" in sys.argv:
        run_memory()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)

    # 先跑独立子进程检查（结果不受主进程 Tk 拆卸影响）。顺序执行无并发；
    # auth-first 只是让最有风险的暂存最先跑。
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
    env["PYTHONIOENCODING"] = "utf-8"
    children = []
    for name, arg, timeout in (("auth", "--auth", 40), ("offline", "--offline", 40),
                               ("memory", "--memory", 60)):
        result = subprocess.run([sys.executable, os.path.abspath(__file__), arg],
                                env=env, cwd=APP_DIR, timeout=timeout,
                                capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        print(result.stdout or "", end="", flush=True)   # 回显子进程 PASS/FAIL 行
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
        children.append((name, result))
    # 统一规则：子进程成功必退出 0；非 0（崩溃/异常路径）一律计入父进程 FAILS，
    # 防止子进程静默失败而父进程仍宣称"全部通过"。
    for name, result in children:
        if result.returncode != 0:
            FAILS.append(f"子进程异常退出: {name}")
            print(f"FAIL 子进程异常退出: {name} (rc={result.returncode})", flush=True)

    # 再跑进程内 E2E（quit_app 销毁 root 是最后一步，之后立即 os._exit）
    run_e2e()
    print()
    if FAILS:
        print(f"== E2E 验收未通过：{len(FAILS)} 项 FAIL -> {FAILS} ==")
    else:
        print("== E2E 验收全部通过 ==")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
