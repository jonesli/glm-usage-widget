import json
import os
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import widget
from widget import (
    COL_ALERT, COL_DIM, COL_OK, COL_WARN, DEFAULTS,
    badge_parts, color_for, load_config, next_interval_sec, resolve_auth,
    save_config,
)


def hermetic_env(**overrides):
    """构造不携带本机真实 ANTHROPIC_* 变量的密闭环境，再叠加覆盖项。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    env.update(overrides)
    return env


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

    def test_backoff_never_below_configured(self):
        self.assertEqual(next_interval_sec(3, 600), 600)


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

    def test_float_values_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"refresh_interval_sec": 90.0, "alert_threshold": 85.5}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["refresh_interval_sec"], 90)
            self.assertEqual(cfg["alert_threshold"], 85.5)

    def test_inverted_thresholds_fall_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"warn_threshold": 90, "alert_threshold": 50}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["warn_threshold"], DEFAULTS["warn_threshold"])
            self.assertEqual(cfg["alert_threshold"], DEFAULTS["alert_threshold"])

    def test_fractional_interval_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"refresh_interval_sec": 0.5}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["refresh_interval_sec"], DEFAULTS["refresh_interval_sec"])

    def test_nan_position_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"badge_position": [float("nan"), 100]}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["badge_position"], DEFAULTS["badge_position"])

    def test_auth_string_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"token": "  abc  ", "base_url": 123}, f)
            cfg = load_config(path)
            self.assertEqual(cfg["token"], "abc")      # strip 后入库
            self.assertEqual(cfg["base_url"], "")      # 非字符串回退默认空串

    def test_auth_missing_fields_default_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_config(os.path.join(d, "nope.json"))
            self.assertEqual(cfg["token"], "")
            self.assertEqual(cfg["base_url"], "")


class TestErrorStates(unittest.TestCase):
    def test_badge_shows_warning_after_generic_error(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(widget, "fetch_all", lambda *a, **k: {"error": "off"}), \
                    patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg):
                app = widget.UsageApp(root)
            app.last_ok = "14:32"
            app._apply_data({"error": "boom"})
            root.update()
            self.assertEqual(app.lb_icon.cget("text"), "")
            self.assertEqual(app.lb_5h.cget("text"), "⚠ 14:32")
        finally:
            root.destroy()

    def test_badge_shows_unconfigured(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(widget, "fetch_all", lambda *a, **k: {"error": "off"}), \
                    patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg):
                app = widget.UsageApp(root)
            app._apply_data({"error": "NO_TOKEN"})
            root.update()
            self.assertEqual(app.lb_5h.cget("text"), "⚡ 未配置")
        finally:
            root.destroy()

    def test_fetch_uses_config_auth(self):
        root = tk.Tk()
        root.withdraw()
        try:
            captured = {}

            def fake_fetch_all(token=None, base_url=None):
                captured["token"] = token
                captured["base_url"] = base_url
                return {"error": "stop"}

            with patch.object(widget, "fetch_all", fake_fetch_all), \
                    patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg):
                app = widget.UsageApp(root)
                app.cfg["token"] = "cfg-tok"
                app.cfg["base_url"] = "https://x.example"
                app._fetch_worker()          # 直接调用线程体；after(0) 入队
                root.update()                # 处理队列回调
            self.assertEqual(captured.get("token"), "cfg-tok")
            self.assertEqual(captured.get("base_url"), "https://x.example")
        finally:
            root.destroy()

    def test_panel_no_token_mentions_config(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(widget, "fetch_all", lambda *a, **k: {"error": "off"}), \
                    patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg):
                app = widget.UsageApp(root)
            app.show_panel()                 # 面板展开后 _apply_data 才会重渲染面板
            root.update()
            app._apply_data({"error": "NO_TOKEN"})
            root.update()
            self.assertIn("config.json", app.p_today.cget("text"))
        finally:
            root.destroy()


class TestLog(unittest.TestCase):
    def test_log_writes_timestamped_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "widget.log")
            with patch.object(widget, "LOG_PATH", path):
                widget.log("hello")
            content = ""
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("hello", content)
            self.assertRegex(content, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} hello\n$")

    def test_log_truncates_over_1mb(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "widget.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x" * 1_100_000)
            with patch.object(widget, "LOG_PATH", path):
                widget.log("fresh")
            self.assertLess(os.path.getsize(path), 10_000)
            with open(path, encoding="utf-8") as f:
                self.assertIn("fresh", f.read())

    def test_log_swallows_os_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(widget, "LOG_PATH", d):   # 目录无法作为文件打开
                widget.log("no crash")


class TestResolveAuth(unittest.TestCase):
    def test_migrates_from_env_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with patch.dict(os.environ, hermetic_env(ANTHROPIC_AUTH_TOKEN="  tok-1  ",
                                                     ANTHROPIC_BASE_URL="https://x.example/api/anthropic"), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "tok-1")
            self.assertEqual(cfg["base_url"], "https://x.example")   # 规范化为协议+域名
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["token"], "tok-1")
            self.assertEqual(saved["base_url"], "https://x.example")

    def test_existing_config_not_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"token": "cfg-token"}, f)
            with patch.dict(os.environ, hermetic_env(ANTHROPIC_AUTH_TOKEN="env-token"), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "cfg-token")

    def test_empty_env_leaves_file_unwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with patch.dict(os.environ, hermetic_env(), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["token"], "")
            self.assertFalse(os.path.exists(path))

    def test_base_url_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with patch.dict(os.environ, hermetic_env(ANTHROPIC_BASE_URL="  https://x.example "), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["base_url"], "https://x.example")

    def test_hand_edited_base_url_path_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"base_url": "https://open.bigmodel.cn/api"}, f)
            with patch.dict(os.environ, hermetic_env(), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["base_url"], "https://open.bigmodel.cn")
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["base_url"], "https://open.bigmodel.cn")   # 规范化写回

    def test_plain_domain_base_url_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"base_url": "https://open.bigmodel.cn"}, f)
            with patch.dict(os.environ, hermetic_env(), clear=True):
                cfg = resolve_auth(load_config(path), path)
            self.assertEqual(cfg["base_url"], "https://open.bigmodel.cn")


class TestTrayStates(unittest.TestCase):
    def _make_app(self):
        root = tk.Tk()
        root.withdraw()
        with patch.object(widget, "fetch_all", lambda *a, **k: {"error": "off"}), \
                patch.object(widget, "resolve_auth", lambda cfg, path=None: cfg):
            app = widget.UsageApp(root)
        root.update()
        return root, app

    def test_badge_menu_has_two_items(self):
        root, app = self._make_app()
        try:
            labels = [app.badge_menu.entrycget(i, "label")
                      for i in range(app.badge_menu.index("end") + 1)]
            self.assertEqual(labels, ["最小化到系统任务栏", "退出"])
        finally:
            root.destroy()

    def test_tray_menu_items(self):
        root, app = self._make_app()
        try:
            labels = [app.tray_menu.entrycget(i, "label")
                      for i in range(app.tray_menu.index("end") + 1)]
            self.assertEqual(labels, ["恢复", "退出"])
        finally:
            root.destroy()

    def test_minimize_hides_badge_and_creates_tray(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = True
                app.minimize_to_tray()
                root.update()
            self.assertTrue(app.minimized)
            self.assertFalse(bool(app.badge.winfo_ismapped()))
            FakeTray.return_value.hide.assert_not_called()
        finally:
            root.destroy()

    def test_restore_shows_badge_and_hides_tray(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = True
                app.minimize_to_tray()
                root.update()
                app.restore_from_tray()
                root.update()
            self.assertFalse(app.minimized)
            self.assertTrue(bool(app.badge.winfo_ismapped()))
            FakeTray.return_value.hide.assert_called_once()
        finally:
            root.destroy()

    def test_minimize_failure_keeps_badge_visible(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = False
                app.minimize_to_tray()
                root.update()
            self.assertFalse(app.minimized)
            self.assertTrue(bool(app.badge.winfo_ismapped()))
            self.assertEqual(app.badge_menu.index("end"), 1)   # 菜单保留两项（可重试）
        finally:
            root.destroy()

    def test_quit_app_hides_tray_then_destroys(self):
        root, app = self._make_app()
        with patch.object(widget, "TrayIcon") as FakeTray:
            FakeTray.return_value.show.return_value = True
            app.minimize_to_tray()
            root.update()
            app.quit_app()
            FakeTray.return_value.hide.assert_called_once()
            with self.assertRaises(tk.TclError):
                root.winfo_exists()    # root 已销毁（update() 在已毁 root 上不抛错）

    def test_drag_end_preserves_disk_auth(self):
        root, app = self._make_app()
        try:
            app.cfg["token"] = "memory-token"
            app.cfg["badge_position"] = [123, 456]
            app.badge.geometry("+123+456")   # 把窗口真移到断言位置，winfo 才报 123,456
            root.update()
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "config.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"token": ""}, f)
                with patch.object(widget, "CONFIG_PATH", path):
                    app._drag_end(SimpleNamespace(x=0, y=0))
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
            self.assertEqual(saved["token"], "")                 # 未复活
            self.assertEqual(saved["badge_position"], [123, 456])
        finally:
            root.destroy()

    def test_tray_restore_bridge_wired(self):
        root, app = self._make_app()
        try:
            with patch.object(widget, "TrayIcon") as FakeTray:
                FakeTray.return_value.show.return_value = True
                app.minimize_to_tray()
                root.update()
                on_restore = FakeTray.call_args.kwargs["on_restore"]
                on_restore()                     # 模拟消息线程回调
                root.update()
            self.assertFalse(app.minimized)
            self.assertTrue(bool(app.badge.winfo_ismapped()))
        finally:
            root.destroy()

    def test_restore_when_not_minimized_is_noop(self):
        root, app = self._make_app()
        try:
            app.restore_from_tray()              # 幂等：非 minimized 态无异常、状态不变
            root.update()
            self.assertFalse(app.minimized)
        finally:
            root.destroy()

    def test_drag_end_skips_save_when_disk_read_fails(self):
        root, app = self._make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "config.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("{corrupted")          # 可写但损坏：旧代码会用默认值基底覆盖它
                with open(path, "rb") as f:
                    before = f.read()
                with patch.object(widget, "CONFIG_PATH", path):
                    app._drag_end(SimpleNamespace(x=0, y=0))
                with open(path, "rb") as f:
                    after = f.read()
            self.assertEqual(before, after)        # 读失败 → 文件原样（真实凭据不被覆盖）
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
