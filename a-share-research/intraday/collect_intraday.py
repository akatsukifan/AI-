#!/usr/bin/env python3
"""Public unadjusted minute OHLC only; no accounts, orders or trading."""
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
from collect import STOCKS, expected_session

OUT = BASE / "reports" / "intraday"
OUT.mkdir(parents=True, exist_ok=True)
TZ = ZoneInfo("Asia/Shanghai")
FIELDS = ["time", "open", "high", "low", "close"]


def normalize(raw, day, now):
    if raw is None or raw.empty:
        raise ValueError("empty minute data")
    df = raw.rename(columns={"时间": "time", "day": "time", "datetime": "time",
                             "开盘": "open", "最高": "high", "最低": "low", "收盘": "close"})
    if any(c not in df for c in FIELDS):
        raise ValueError(f"missing minute fields: {list(df.columns)}")
    df = df[FIELDS].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if df["time"].dt.tz is not None:
        df["time"] = df["time"].dt.tz_convert(TZ).dt.tz_localize(None)
    df = df.dropna(subset=["time"])
    df = df[(df["time"].dt.date == day) & (df["time"] <= now.replace(tzinfo=None))]
    clock = df["time"].dt.time
    df = df[((clock >= time(9, 30)) & (clock <= time(11, 30))) |
            ((clock >= time(13, 0)) & (clock <= time(15, 0)))]
    for col in FIELDS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().sort_values("time").drop_duplicates("time", keep="last")
    df = df[(df[FIELDS[1:]] > 0).all(axis=1)]
    df = df[(df["high"] >= df[["open", "close", "low"]].max(axis=1)) &
            (df["low"] <= df[["open", "close", "high"]].min(axis=1))]
    if df.empty:
        raise ValueError(f"no valid minute bars for {day}")
    return df.reset_index(drop=True)


def target_session(now):
    cutoff = now if now.time() >= time(9, 30) else now - timedelta(days=1)
    return expected_session(cutoff.replace(hour=16, minute=0, second=0, microsecond=0))


def required_through(now, day):
    if day < now.date() or now.time() >= time(15, 0):
        return datetime.combine(day, time(15, 0))
    if time(11, 30) <= now.time() < time(13, 0):
        return datetime.combine(day, time(11, 30))
    return now.replace(tzinfo=None, second=0, microsecond=0)


def fetch(code, day, now, blocked):
    errors = {}
    for source in ("Eastmoney", "Sina"):
        if source in blocked:
            errors[source] = "skipped after provider failure"
            continue
        try:
            if source == "Eastmoney":
                raw = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="",
                                               start_date=f"{day} 09:30:00", end_date=f"{day} 15:00:00")
            else:
                fn = getattr(ak, "stock_zh_a_minute_sina", None) or getattr(ak, "stock_zh_a_minute", None)
                if fn is None:
                    raise RuntimeError("AKShare Sina minute API unavailable")
                raw = fn(symbol=("sh" if code.startswith("6") else "sz") + code,
                         period="1", adjust="")
            df = normalize(raw, day, now)
            lag = (required_through(now, day) - df.iloc[-1]["time"]).total_seconds() / 60
            if lag > 5:
                raise ValueError(f"stale minute data: {lag:.1f} trading-clock minutes")
            return df, source, errors
        except Exception as exc:
            msg = str(exc)[:400]
            errors[source] = msg
            if any(x in msg.lower() for x in ("429", "限流", "断开", "connection", "timeout", "403", "forbidden")):
                blocked.add(source)
    raise RuntimeError(json.dumps(errors, ensure_ascii=False))


def summarize(df, code, name, day, source, warnings):
    am = df[df["time"].dt.time <= time(11, 30)]
    pm = df[df["time"].dt.time >= time(13, 0)]
    def session(d):
        if d.empty:
            return None
        return {"bars": len(d), "first": str(d.iloc[0]["time"]), "last": str(d.iloc[-1]["time"]),
                "low": float(d["low"].min()), "high": float(d["high"].max()),
                "last_close": float(d.iloc[-1]["close"])}
    return {"code": code, "name": name, "trade_date": str(day), "source": f"AKShare ({source})",
            "price_adjustment": "none", "bar_period": "1m", "first": str(df.iloc[0]["time"]),
            "last": str(df.iloc[-1]["time"]), "last_close": float(df.iloc[-1]["close"]),
            "bars": len(df), "morning": session(am), "afternoon": session(pm),
            "warnings": warnings, "file": f"{day}/{code}.csv"}


def main():
    now = datetime.now(TZ)
    day, calendar = target_session(now)
    rows, errors, blocked = [], {}, set()
    dest = OUT / str(day)
    dest.mkdir(parents=True, exist_ok=True)
    for code, name in STOCKS.items():
        try:
            df, source, warnings = fetch(code, day, now, blocked)
            path = dest / f"{code}.csv"
            if path.exists():
                old = pd.read_csv(path)
                old["time"] = pd.to_datetime(old["time"])
                # Do not splice different providers: reject truncated replacement instead.
                if not set(old["time"]).issubset(set(df["time"])):
                    raise ValueError("incomplete replacement; previous snapshot retained")
            df.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
            rows.append(summarize(df, code, name, day, source, warnings))
        except Exception as exc:
            errors[code] = str(exc)
            print(f"{code}: {exc}", file=sys.stderr)
    payload = {"updated_at_china": now.isoformat(), "target_trade_date": str(day),
               "calendar_source": calendar, "scope": "public minute prices only; no orders",
               "status": "partial_or_failed" if errors else "collected",
               "stocks": rows, "errors": errors}
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
