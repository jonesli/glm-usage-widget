import json
import os
import tempfile
import tkinter as tk
import unittest
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
            with patch.object(widget, "fetch_all", lambda: {"error": "off"}):
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
            with patch.object(widget, "fetch_all", lambda: {"error": "off"}):
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

            with patch.object(widget, "fetch_all", fake_fetch_all):
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
            with patch.object(widget, "fetch_all", lambda: {"error": "off"}):
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


if __name__ == "__main__":
    unittest.main()
