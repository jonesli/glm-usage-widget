import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import usage_api
from usage_api import (
    format_tokens, get_base_url, query_window, parse_quota,
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

    def test_boundaries(self):
        self.assertEqual(format_tokens(1_000_000), "1.0M")
        self.assertEqual(format_tokens(999_999), "1.0M")      # 不出现 1000.0K
        self.assertEqual(format_tokens(999_949), "999.9K")

    def test_nonfinite_and_overflow(self):
        self.assertEqual(format_tokens(float("nan")), "0")
        self.assertEqual(format_tokens(float("inf")), "0")
        self.assertEqual(format_tokens(10**400), "0")


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

    def test_schemeless_url(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
        with patch.dict(os.environ, {**env, "ANTHROPIC_BASE_URL": "open.bigmodel.cn/api"}):
            self.assertIsNone(get_base_url())

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "  https://open.bigmodel.cn "}):
            self.assertEqual(get_base_url(), "https://open.bigmodel.cn")


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


if __name__ == "__main__":
    unittest.main()
