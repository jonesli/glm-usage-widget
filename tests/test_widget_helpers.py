import json
import os
import tempfile
import unittest
from unittest.mock import patch

import widget
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


class TestLog(unittest.TestCase):
    def test_log_writes_timestamped_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "widget.log")
            with patch.object(widget, "LOG_PATH", path):
                widget.log("hello")
            content = open(path, encoding="utf-8").read()
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
            self.assertIn("fresh", open(path, encoding="utf-8").read())

    def test_log_swallows_os_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(widget, "LOG_PATH", d):   # 目录无法作为文件打开
                widget.log("no crash")


if __name__ == "__main__":
    unittest.main()
