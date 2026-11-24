import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pandas as pd
import collect


def fixture():
    dates = pd.bdate_range(end="2026-11-23", periods=300)
    return pd.DataFrame({"date": dates, "open": 10., "close": 11., "high": 12.,
                         "low": 9., "volume": 100000., "amount": 1050000.,
                         "turnover": .012})


class CollectorTests(unittest.TestCase):
    def setUp(self):
        collect.BLOCKED.clear()

    def test_sina_units(self):
        df = collect.normalize(fixture(), "Sina", date(2026, 11, 23))
        self.assertEqual(df.iloc[-1]["成交量"], 1000)
        self.assertEqual(df.iloc[-1]["换手率"], 1.2)
        self.assertEqual(df.iloc[-1]["成交额"], 1050000)

    def test_stale_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale history"):
            collect.normalize(fixture(), "Sina", date(2026, 11, 24))

    def test_future_partial_bar_excluded(self):
        df = collect.normalize(fixture(), "Sina", date(2026, 11, 20))
        self.assertEqual(df.iloc[-1]["日期"].date(), date(2026, 11, 20))

    def test_missing_amount_is_not_invented(self):
        df = collect.normalize(fixture().drop(columns=["amount"]), "Sina", date(2026, 11, 23))
        r = collect.evaluate("600183", "test", df, "Sina")
        self.assertIsNone(r["last_amount_cny"])
        self.assertIsNone(r["last_20d_avg_amount_cny"])
        self.assertIsNone(r["last_20d_vs_prev_20d_amount_pct"])

    def test_rate_limit_switch_and_skip(self):
        with patch.object(collect.ak, "stock_zh_a_hist_em", side_effect=RuntimeError("429 rate limit")) as em:
            with patch.object(collect.ak, "stock_zh_a_hist_sina", return_value=fixture(), create=True):
                for code in ["600183", "601138"]:
                    _, provider, warnings = collect.get_history(code, date(2026, 11, 23))
                    self.assertEqual(provider, "Sina")
                    self.assertIn("Eastmoney", warnings)
                self.assertEqual(em.call_count, 1)

    def test_calendar_before_close(self):
        now = datetime(2026, 11, 24, 12, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(collect.ak, "tool_trade_date_hist_sina", return_value=pd.DataFrame({"trade_date": ["2026-11-20", "2026-11-23", "2026-11-24"]})):
            self.assertEqual(collect.expected_session(now)[0], date(2026, 11, 23))


if __name__ == "__main__":
    unittest.main()
