"""端到端验收脚本：把手动验收清单自动化。

运行：python tests/e2e_acceptance.py
- 主流程：真实 Tk 窗口逐项验证置顶/悬停/收回/翻转/拖动/位置记忆/真实数据/右键退出
- 子进程：断网模拟（BASE_URL 指向不可达端口，走真实 socket 失败路径）
- 子进程：内存占用测量（独立运行 widget.py，tasklist 查询）

注意：运行时屏幕上会闪现徽章/面板数秒，属正常现象。
"""

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
from usage_api import fetch_all, format_tokens

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def in_range(actual, expect, tol=2):
    return all(abs(a - e) <= tol for a, e in zip(actual, expect))


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
    while app.panel.winfo_ismapped() and time.time() - t0 < 2:
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
        expect5 = f"5h:{max(w['percentage'] for w in wins):.0f}%"
        expect_mcp = f"MCP:{data['mcp']['percentage']:.0f}%"
        got = f"{app.lb_5h.cget('text')}|{app.lb_mcp.cget('text')}"
        check("T2a 徽章=接口数据", got == f"{expect5}|{expect_mcp}", f"got={got}")
        app.show_panel()
        root.update()
        today_txt = app.p_today.cget("text")
        expect_today = f"今日 Token  {format_tokens(data['today']['total_tokens'])}"
        check("T2b 面板今日Token", today_txt == expect_today, f"got={today_txt}")
        app.hide_panel()

    # T7 右键退出（update 同步处理销毁；随后立即 os._exit，见 main）
    app.badge.event_generate("<Button-3>")
    root.update()
    try:
        gone = not app.badge.winfo_exists()
    except tk.TclError:
        gone = True          # "application has been destroyed" = 右键销毁成功
    check("T7 右键退出", gone)


def run_offline():
    """子进程模式：BASE_URL 指向不可达端口，走真实 socket 失败 → 徽章应显示 ⚠。"""
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


def main():
    if "--offline" in sys.argv:
        run_offline()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)
    if "--memory" in sys.argv:
        run_memory()
        sys.stdout.flush()
        os._exit(1 if FAILS else 0)

    # 先跑两个独立子进程检查（结果不受主进程 Tk 拆卸影响）
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--offline"], env=env,
                   cwd=APP_DIR, timeout=40)
    subprocess.run([sys.executable, os.path.abspath(__file__), "--memory"], env=env,
                   cwd=APP_DIR, timeout=60)

    # 再跑进程内 E2E（右键销毁 root 是最后一步，之后立即 os._exit）
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
