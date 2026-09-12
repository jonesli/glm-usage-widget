import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import usage_api
from usage_api import (
    UsageError,
    fetch_all, fetch_json, format_tokens, get_base_url, query_window,
    parse_quota, parse_model_usage,
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

    def test_first_time_limit_wins(self):
        out = parse_quota({"limits": [{"type": "TIME_LIMIT", "currentUsage": 1, "usage": 10},
                                      {"type": "TIME_LIMIT", "currentUsage": 9, "usage": 10}]})
        self.assertEqual(out["mcp"]["used"], 1)

    def test_limits_not_list_and_non_dict_entries(self):
        self.assertEqual(parse_quota({"limits": "x"})["token_windows"], [])
        out = parse_quota({"limits": [None, 42, {"type": "TOKENS_LIMIT", "percentage": 5}]})
        self.assertEqual([w["percentage"] for w in out["token_windows"]], [5.0])


class TestParseModelUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(load_fixture("model_usage.json"))

    def test_hourly_is_last_24_buckets(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        self.assertEqual(len(out["hourly"]), 24)          # fixture 有 25 个桶
        self.assertEqual(out["hourly"][0][0], "2026-09-11 18:00")
        self.assertEqual(out["hourly"][-1][1], 3715930.0)

    def test_today_total(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        self.assertEqual(out["today"]["total_tokens"], 55_172_080)

    def test_today_models_same_source(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 19, 0, 0))
        models = {m["name"]: m["tokens"] for m in out["today"]["models"]}
        # GLM-5.3 在 09-12 14:00 有 5215596；Flash 为今日总量减去它
        self.assertEqual(models["GLM-5.3"], 5_215_596)
        self.assertEqual(models["GLM-5.3-Flash"], 55_172_080 - 5_215_596)
        self.assertEqual(sum(m["tokens"] for m in out["today"]["models"]),
                         out["today"]["total_tokens"])

    def test_cross_midnight(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 0, 30, 0))
        self.assertEqual(out["today"]["total_tokens"], 2_253_571)  # 仅 09-12 00:00 桶

    def test_now_boundary_includes_current_hour_bucket(self):
        out = parse_model_usage(self.data, now=datetime(2026, 9, 12, 14, 0))
        self.assertEqual(out["today"]["total_tokens"], 43_238_070)  # 含 14:00 桶

    def test_missing_or_garbage(self):
        out = parse_model_usage({}, now=datetime(2026, 9, 12))
        self.assertEqual(out["hourly"], [])
        out = parse_model_usage("bad", now=datetime(2026, 9, 12))
        self.assertEqual(out["today"]["total_tokens"], 0)


class TestFetchAll(unittest.TestCase):
    def test_success_two_calls(self):
        calls = []

        def fake_fetcher(url, token):
            calls.append(url)
            if "model-usage" in url:
                return {"x_time": ["2026-09-12 18:00"], "tokensUsage": [42]}
            return {"limits": [{"type": "TOKENS_LIMIT", "percentage": 8}]}

        out = fetch_all(now=datetime(2026, 9, 12, 19, 0, 0), fetcher=fake_fetcher,
                        token="tok", base_url="https://x.example")
        self.assertNotIn("error", out)
        self.assertEqual(len(calls), 2)
        self.assertIn("startTime=2026-09-11+00%3A00%3A00", calls[0])
        self.assertEqual(out["token_windows"], [{"percentage": 8.0}])
        self.assertEqual(out["today"]["total_tokens"], 42.0)
        self.assertEqual(out["fetched_at"], "2026-09-12 19:00:00")

    def test_network_error_returns_error_key(self):
        def bad_fetcher(url, token):
            raise UsageError("boom")

        out = fetch_all(now=datetime(2026, 9, 12), fetcher=bad_fetcher,
                        token="tok", base_url="https://x.example")
        self.assertEqual(out, {"error": "boom"})

    def test_no_token(self):
        out = fetch_all(now=datetime(2026, 9, 12), token="", base_url="https://x.example")
        self.assertEqual(out, {"error": "NO_TOKEN"})

    def test_no_base_url(self):
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": ""}):
            out = fetch_all(now=datetime(2026, 9, 12), token="tok", base_url=None)
        self.assertEqual(out, {"error": "NO_BASE_URL"})

    def test_fetch_json_bad_json(self):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"not json"

        with patch("usage_api.urllib.request.urlopen", return_value=FakeResp()):
            with self.assertRaises(UsageError):
                fetch_json("https://x.example/api", "tok")


if __name__ == "__main__":
    unittest.main()
