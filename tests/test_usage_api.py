import os
import unittest
from datetime import datetime
from unittest.mock import patch

import usage_api
from usage_api import (
    format_tokens, get_base_url, query_window,
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


if __name__ == "__main__":
    unittest.main()
