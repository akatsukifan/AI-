#!/usr/bin/env python3
"""Public-data-only A-share daily research collector powered by AKShare.

No brokerage API, credentials, orders, personal portfolio or trading advice.
"""
import json
import sys
from datetime import datetime, timedelta
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


# Never retry a rate-limited provider repeatedly during the same run.
BLOCKED = set()
PROVIDERS = ("Eastmoney", "Sina")
START = "20240101"


def expected_session(now):
    cutoff = now.date() if (now.hour, now.minute) >= (15, 10) else now.date() - timedelta(days=1)
    try:
        calendar_fn = getattr(ak, "calendar_trade_date_hist_sina", None) or getattr(ak, "tool_trade_date_hist_sina", None)
        if calendar_fn is None:
            raise RuntimeError("AKShare trading calendar API unavailable")
        calendar = calendar_fn()
        dates = pd.to_datetime(calendar["trade_date"], errors="coerce").dropna()
        if dates.empty or dates.max().date() < cutoff:
            # The calendar must cover the requested period, even if it is a weekend.
            if dates.empty or (cutoff - dates.max().date()).days > 3:
                raise ValueError("calendar does not cover requested period")
        eligible = dates[dates.dt.date <= cutoff]
        if eligible.empty:
            raise ValueError("empty eligible calendar")
        return eligible.max().date(), "Sina trading calendar"
    except Exception as exc:
        print(f"Calendar unavailable: {exc}", file=sys.stderr)
        while cutoff.weekday() >= 5:
            cutoff -= timedelta(days=1)
        # Conservative fallback: a holiday can be reported stale, never silently current.
        return cutoff, "weekday fallback; holiday calendar unverified"


def normalize(raw, provider, expected):
    if raw is None or raw.empty:
        raise ValueError("empty dataset")
    df = raw.copy()
    if provider == "Sina":
        if "date" not in df.columns and df.index.name == "date":
            df = df.reset_index()
        df = df.rename(columns={"date": "日期", "open": "开盘", "close": "收盘",
                                "high": "最高", "low": "最低", "volume": "成交量",
                                "amount": "成交额", "turnover": "换手率"})
        if "成交额" not in df:
            df["成交额"] = float("nan")
        if "换手率" not in df:
            df["换手率"] = float("nan")
        if "成交量" in df:
            df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce") / 100
        df["换手率"] = pd.to_numeric(df["换手率"], errors="coerce") * 100
    missing = [c for c in NEEDED if c not in df]
    if missing:
        raise ValueError(f"missing columns {missing}")
    df = df[NEEDED].copy()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    for col in NEEDED[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
    df = df.dropna(subset=["日期"]).sort_values("日期")
    df = df[(df["日期"] >= pd.Timestamp("2024-01-01")) & (df["日期"].dt.date <= expected)]
    df = df.drop_duplicates("日期", keep="last").reset_index(drop=True)
    prices = ["开盘", "收盘", "最高", "最低"]
    if len(df) < 253 or df[prices].isna().any().any() or (df[prices] <= 0).any().any():
        raise ValueError("insufficient or invalid OHLC history")
    if (df["最高"] + 0.011 < df[["开盘", "收盘", "最低"]].max(axis=1)).any() or (df["最低"] - 0.011 > df[["开盘", "收盘", "最高"]].min(axis=1)).any():
        raise ValueError("invalid OHLC bounds")
    if df.iloc[-1]["日期"].date() != expected:
        raise ValueError(f"stale history: {df.iloc[-1]['日期'].date()} != {expected}")
    if df["成交量"].isna().any() or (df["成交量"] < 0).any():
        raise ValueError("invalid volume")
    if (df[["成交额", "换手率"]] < 0).any().any():
        raise ValueError("invalid amount/turnover")
    return df


def get_history(code, expected):
    errors = {}
    end = expected.strftime("%Y%m%d")
    for provider in PROVIDERS:
        if provider in BLOCKED:
            errors[provider] = "skipped after provider connection/rate-limit failure"
            continue
        try:
            if provider == "Eastmoney":
                raw = ak.stock_zh_a_hist_em(symbol=code, period="daily",
                                          start_date=START, end_date=end, adjust="qfq")
            else:
                func = (getattr(ak, "stock_zh_a_hist_sina", None) or
                        getattr(ak, "stock_zh_a_daily_sina", None) or
                        getattr(ak, "stock_zh_a_daily", None))
                if func is None:
                    raise RuntimeError("AKShare Sina history API unavailable")
                raw = func(symbol="sh" + code, start_date=START, end_date=end, adjust="qfq")
            df = normalize(raw, provider, expected)
            return df, provider, errors
        except Exception as ex:
            errors[provider] = str(ex)[:500]
            print(f"{code} {provider}: {ex}", file=sys.stderr)
            message = str(ex).lower()
            if any(s in message for s in ("429", "限流", "断开", "connection", "timeout", "timed out", "remote end", "rate limit", "forbidden", "403")):
                BLOCKED.add(provider)
    raise RuntimeError(json.dumps(errors, ensure_ascii=False))


def evaluate(code, name, df, provider="Eastmoney"):
    close = df["收盘"]
    amount = df["成交额"]
    latest = df.iloc[-1]
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    is_intraday = (latest["日期"].date() == now_cn.date() and
                   (now_cn.hour, now_cn.minute) < (15, 10))
    last_complete = df.iloc[-2] if is_intraday else latest
    # A 20-day average should never mix 19 complete sessions with a partial current session.
    complete_amount = amount.iloc[:-1] if is_intraday else amount
    peak = close.tail(252).max()

    def ret(days):
        return num((close.iloc[-1] / close.iloc[-(days + 1)] - 1) * 100) if len(close) > days else None

    last_window = complete_amount.tail(20)
    prev_window = complete_amount.iloc[-40:-20]
    last20 = last_window.mean() if len(last_window) == 20 and last_window.notna().all() else None
    prev20 = prev_window.mean() if len(prev_window) == 20 and prev_window.notna().all() else None

    return {
        "code": code,
        "name": name,
        "data_source": f"AKShare ({provider})",
        "volume_unit": "lots (100 shares)",
        "price_adjustment": "qfq",
        "latest_trade_date": latest["日期"].strftime("%Y-%m-%d"),
        "latest_bar_status": "intraday" if is_intraday else "completed",
        "latest_observed_price_cny": num(latest["收盘"]),
        "last_complete_trade_date": last_complete["日期"].strftime("%Y-%m-%d"),
        "last_complete_close_cny": num(last_complete["收盘"]),
        "last_volume_native_unit": num(latest["成交量"]),
        "last_turnover_pct": num(latest["换手率"]),
        "last_amount_cny": num(latest["成交额"]),
        "last_20d_avg_amount_cny": num(last20),
        "prev_20d_avg_amount_cny": num(prev20),
        "last_20d_vs_prev_20d_amount_pct": (
            num((last20 / prev20 - 1) * 100)
            if last20 is not None and prev20 is not None and pd.notna(prev20) and prev20 > 0 else None
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
    expected, calendar_source = expected_session(now)
    rows = []
    errors = {}
    provider_warnings = {}
    retained_history = {}
    for code, name in STOCKS.items():
        try:
            df, provider, warnings = get_history(code, expected)
            if warnings:
                provider_warnings[code] = warnings
            report = evaluate(code, name, df, provider)
            rows.append(report)
            # A full history CSV is intentionally public, and contains market data only.
            df.to_csv(OUT / f"{code}_qfq_daily.csv", index=False, date_format="%Y-%m-%d")
            print(f"{code} {name}: {report['latest_trade_date']} {report['latest_bar_status']}, {report['latest_observed_price_cny']}")
        except Exception as exc:
            errors[code] = str(exc)
            previous = OUT / f"{code}_qfq_daily.csv"
            if previous.exists():
                try:
                    old = pd.read_csv(previous)
                    retained_history[code] = str(old.iloc[-1]["日期"])
                except Exception:
                    retained_history[code] = "unreadable"
            print(f"ERROR {code}: {exc}", file=sys.stderr)

    payload = {
        "updated_at_china": now.isoformat(),
        "expected_trade_date": expected.isoformat(),
        "calendar_source": calendar_source,
        "collection_status": "failed" if errors else "completed",
        "provider_warnings": provider_warnings,
        "retained_history_dates": retained_history,
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
        f"预期完整交易日：{expected}；状态：{payload['collection_status']}；日历：{calendar_source}",
        "数据源：AKShare / 东方财富优先，新浪备用；全量前复权日线，不包含未完成的当日日线。成交量单位统一为手，成交额为元，换手率为百分比。缺失字段留空。",
        "",
        "| 股票 | 数据源 | 数据日期/状态 | 最新价(元) | 20日涨跌幅 | 60日涨跌幅 | 120日涨跌幅 | 距252日最高价 | 换手率 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(x):
        return "—" if x is None else f"{x:.2f}"
    for r in rows:
        md.append(
            f"| {r['name']}({r['code']}) | {r['data_source']} | {r['latest_trade_date']} / {'盘中' if r['latest_bar_status']=='intraday' else '已收盘'} "
            f"| {fmt(r['latest_observed_price_cny'])} | {fmt(r['return_20d_pct'])}% "
            f"| {fmt(r['return_60d_pct'])}% | {fmt(r['return_120d_pct'])}% "
            f"| {fmt(r['distance_from_252d_high_pct'])}% | {fmt(r['last_turnover_pct'])}% |"
        )
    if provider_warnings:
        md.extend(["", "## 备用源切换记录"])
        md.extend(f"- {code}: {warnings}" for code, warnings in provider_warnings.items())
    if errors:
        md.extend(["", "## 数据失败（不可作为最新行情）"])
        md.extend([f"- {code}: {err}" for code, err in errors.items()])
    (OUT / "latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if errors or len(rows) != len(STOCKS):
        raise SystemExit("Collection incomplete; see latest.json errors. Workflow marked FAILED.")


if __name__ == "__main__":
    main()
