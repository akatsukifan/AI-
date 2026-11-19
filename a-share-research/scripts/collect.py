#!/usr/bin/env python3
"""Public-data-only A-share daily research collector powered by AKShare.

No brokerage API, credentials, orders, personal portfolio or trading advice.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "reports"
OUT.mkdir(parents=True, exist_ok=True)

STOCKS = {"600183": "生益科技", "601138": "工业富联"}
NEEDED = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "换手率"]


def num(v):
    if v is None or pd.isna(v):
        return None
    return round(float(v), 4)


def get_history(code):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    last_error = None
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date="20240101",
                end_date=today,
                adjust="qfq",
            )
            if df is None or df.empty:
                raise ValueError(f"{code}: empty dataset")
            missing = [c for c in NEEDED if c not in df.columns]
            if missing:
                raise ValueError(f"{code}: missing columns {missing}")
            df = df[NEEDED].copy()
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            for col in NEEDED[1:]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["日期", "收盘"]).sort_values("日期")
            df = df.drop_duplicates("日期", keep="last").reset_index(drop=True)
            if len(df) < 25:
                raise ValueError(f"{code}: only {len(df)} trading days")
            return df
        except Exception as ex:
            last_error = ex
            print(f"{code} fetch failed attempt {attempt + 1}/3: {ex}", file=sys.stderr)
            if attempt < 2:
                time.sleep((attempt + 1) * 5)
    raise RuntimeError(f"{code}: failed to retrieve valid data: {last_error}")


def evaluate(code, name, df):
    close = df["收盘"]
    amount = df["成交额"]
    latest = df.iloc[-1]
    peak = close.tail(252).max()

    def ret(days):
        return num((close.iloc[-1] / close.iloc[-(days + 1)] - 1) * 100) if len(close) > days else None

    last20 = amount.tail(20).mean()
    prev20 = amount.iloc[-40:-20].mean() if len(amount) >= 40 else None

    return {
        "code": code,
        "name": name,
        "data_source": "AKShare stock_zh_a_hist (Eastmoney)",
        "price_adjustment": "qfq",
        "latest_trade_date": latest["日期"].strftime("%Y-%m-%d"),
        "last_close_cny": num(latest["收盘"]),
        "last_volume_shares_reported": num(latest["成交量"]),
        "last_turnover_pct": num(latest["换手率"]),
        "last_amount_cny": num(latest["成交额"]),
        "last_20d_avg_amount_cny": num(last20),
        "prev_20d_avg_amount_cny": num(prev20),
        "last_20d_vs_prev_20d_amount_pct": (
            num((last20 / prev20 - 1) * 100)
            if prev20 is not None and pd.notna(prev20) and prev20 > 0 else None
        ),
        "return_20d_pct": ret(20),
        "return_60d_pct": ret(60),
        "return_120d_pct": ret(120),
        "distance_from_252d_high_pct": num((close.iloc[-1] / peak - 1) * 100)
        if peak and pd.notna(peak) else None,
        "history_rows": len(df),
    }


def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    rows = []
    errors = {}
    for code, name in STOCKS.items():
        try:
            df = get_history(code)
            report = evaluate(code, name, df)
            rows.append(report)
            # A full history CSV is intentionally public, and contains market data only.
            df.to_csv(OUT / f"{code}_qfq_daily.csv", index=False, date_format="%Y-%m-%d")
            print(f"{code} {name}: {report['latest_trade_date']}, {report['last_close_cny']}")
        except Exception as exc:
            errors[code] = str(exc)
            print(f"ERROR {code}: {exc}", file=sys.stderr)

    payload = {
        "updated_at_china": now.isoformat(),
        "scope": "public market data only; no trading advice",
        "price_adjustment": "qfq",
        "stocks": rows,
        "errors": errors,
    }
    (OUT / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    md = [
        "# A股公开行情观察",
        f"更新：{now.strftime('%Y-%m-%d %H:%M')}（北京时间）",
        "",
        "数据源：AKShare / 东方财富日线，前复权；不是实时行情，不含私人投资数据。",
        "",
        "| 股票 | 最新交易日 | 收盘价(元) | 20日涨跌幅 | 60日涨跌幅 | 120日涨跌幅 | 距252日最高价 | 换手率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(x):
        return "—" if x is None else f"{x:.2f}"
    for r in rows:
        md.append(
            f"| {r['name']}({r['code']}) | {r['latest_trade_date']} "
            f"| {fmt(r['last_close_cny'])} | {fmt(r['return_20d_pct'])}% "
            f"| {fmt(r['return_60d_pct'])}% | {fmt(r['return_120d_pct'])}% "
            f"| {fmt(r['distance_from_252d_high_pct'])}% | {fmt(r['last_turnover_pct'])}% |"
        )
    if errors:
        md.extend(["", "## 数据失败（不可作为最新行情）"])
        md.extend([f"- {code}: {err}" for code, err in errors.items()])
    (OUT / "latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if errors or len(rows) != len(STOCKS):
        raise SystemExit("Collection incomplete; see latest.json errors. Workflow marked FAILED.")


if __name__ == "__main__":
    main()
