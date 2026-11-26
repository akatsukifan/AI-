import unittest
from datetime import datetime, date
from zoneinfo import ZoneInfo
import pandas as pd
from collect_intraday import normalize, summarize, required_through

class IntradayTests(unittest.TestCase):
    def test_session_and_low(self):
        raw = pd.DataFrame({"时间": ["2026-11-26 11:30:00", "2026-11-26 12:30:00", "2026-11-26 14:20:00", "2026-11-27 09:31:00"],
                            "开盘": [41, 41, 40.6, 40], "最高": [41.1, 41, 40.7, 40],
                            "最低": [40.9, 41, 40.5, 40], "收盘": [41, 41, 40.6, 40]})
        now = datetime(2026, 11, 26, 14, 25, tzinfo=ZoneInfo("Asia/Shanghai"))
        df = normalize(raw, date(2026,11,26), now)
        self.assertEqual(len(df), 2)
        r = summarize(df, "601138", "test", date(2026,11,26), "Eastmoney", {})
        self.assertEqual(r["afternoon"]["low"], 40.5)
        self.assertEqual(r["morning"]["last_close"], 41)
    def test_lunch_clock(self):
        now = datetime(2026,11,26,12,15,tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(required_through(now, now.date()), datetime(2026,11,26,11,30))

if __name__ == "__main__":
    unittest.main()
