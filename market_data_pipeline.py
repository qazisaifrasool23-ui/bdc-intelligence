#!/usr/bin/env python3
"""market_data_pipeline.py — twice-daily market data refresh for the
47-fund traded BDC universe.

Outputs to data/market/:
  prices.json       price/valuation per fund (refreshed 2x/day)
  index.json        SPX + BIZD series, indexed to 2020-01-02 = 100
  volatility.json   realized vol + max drawdown (refreshed quarterly)
  ownership.json    short interest + institutional ownership
  LAST_REFRESH.txt  ISO timestamp of last successful refresh

Free data sources only — no API keys.
  * yfinance for prices, fundamentals, institutional %
  * FINRA CDN for short-interest volume
  * Computed volatility/drawdown from yfinance price history

CLI:
  --test          ARCC-only dry-run; print, do not write
  --refresh       prices + index + ownership (~2 min)
  --quarterly     full refresh including volatility (~10 min)
  --prices-only   prices.json only
  --index-only    index.json only
"""
from __future__ import annotations
import argparse
import json
import logging
import math
import os
import pathlib
import sys
import time
import warnings
from datetime import datetime, timezone, date
from typing import Optional
warnings.filterwarnings("ignore")

import requests

# yfinance is large; import lazily where possible but module-level is fine
import yfinance as yf  # noqa: E402
import pandas as pd

ROOT = pathlib.Path.home() / "bdc_research"
REPO = ROOT / "bdc-intelligence"
TS_DIR = REPO / "data" / "timeseries"
UNI = REPO / "data" / "universe" / "traded_bdcs.json"
MARKET_DIR = REPO / "data" / "market"
LOGS_DIR = REPO / "data" / "logs"
LOG_FILE = LOGS_DIR / "market_errors.log"

HTTP_HEADERS = {"User-Agent": "BDC Research qsaif2321@gmail.com"}
BASE_DATE = "2020-01-02"  # for indexed series


# --------------------------------------------------------------- logging
def log_error(msg: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} | {msg}\n")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------- universe + nav
def load_universe() -> list[str]:
    return [e["ticker"] for e in json.loads(UNI.read_text())]


def load_nav_from_timeseries(ts_dir: pathlib.Path = TS_DIR) -> dict[str, Optional[float]]:
    """Latest non-null nav_per_share per fund."""
    out: dict[str, Optional[float]] = {}
    for p in ts_dir.glob("*.json"):
        ticker = p.stem
        try:
            arr = json.loads(p.read_text())
        except Exception as e:
            log_error(f"load_nav: failed to parse {p}: {e}")
            out[ticker] = None
            continue
        arr_sorted = sorted(arr, key=lambda r: r.get("period_end") or "")
        latest_nav = None
        for r in reversed(arr_sorted):
            v = r.get("nav_per_share")
            if isinstance(v, (int, float)) and v > 0:
                latest_nav = float(v)
                break
        out[ticker] = latest_nav
    return out


# --------------------------------------------------------------- yfinance fetch
def fetch_prices(tickers: list[str]) -> dict[str, dict]:
    """Per-ticker info dict — uses ticker.info to pull fundamentals + price."""
    out: dict[str, dict] = {}
    for t in tickers:
        # yfinance accepts BRK.B / BRK-B etc; tickers list uses our internal codes
        # which may not all be valid yfinance symbols (e.g. some non-traded
        # placeholders). Try as-is.
        try:
            yt = yf.Ticker(t)
            info = yt.info or {}
            hist1d = yt.history(period="5d", auto_adjust=False)  # last few days
            current = (info.get("currentPrice") or info.get("regularMarketPrice")
                       or info.get("previousClose"))
            prev = info.get("previousClose")
            if current is None and not hist1d.empty:
                current = float(hist1d["Close"].iloc[-1])
            if prev is None and len(hist1d) >= 2:
                prev = float(hist1d["Close"].iloc[-2])
            change_1d = (current - prev) if (isinstance(current, (int, float)) and
                                              isinstance(prev, (int, float))) else None
            change_1d_pct = (change_1d / prev * 100) if (change_1d is not None and prev) else None

            # 1w / 1m / ytd from longer history
            hist_long = yt.history(period="1y", auto_adjust=False)
            change_1w_pct = _pct_change_back(hist_long, 5)
            change_1m_pct = _pct_change_back(hist_long, 21)
            change_ytd_pct = _pct_change_ytd(hist_long, current)

            mc = info.get("marketCap")
            mc_mn = round(mc / 1_000_000, 2) if isinstance(mc, (int, float)) else None

            out[t] = {
                "price": _round(current, 4),
                "price_change_1d": _round(change_1d, 4),
                "price_change_1d_pct": _round(change_1d_pct, 2),
                "price_change_1w_pct": _round(change_1w_pct, 2),
                "price_change_1m_pct": _round(change_1m_pct, 2),
                "price_change_ytd_pct": _round(change_ytd_pct, 2),
                "52w_high": _round(info.get("fiftyTwoWeekHigh"), 4),
                "52w_low": _round(info.get("fiftyTwoWeekLow"), 4),
                "volume_today": int(info.get("regularMarketVolume") or 0) or None,
                "avg_volume_30d": int(info.get("averageVolume") or 0) or None,
                "market_cap_mn": mc_mn,
                "dividend_yield_pct": _round_pct(info.get("dividendYield")),
                "beta": _round(info.get("beta"), 3),
                "short_interest_pct": _round_pct(info.get("shortPercentOfFloat")),
                "institutional_ownership_pct": _round_pct(info.get("heldPercentInstitutions")),
                "as_of_date": date.today().isoformat(),
            }
        except Exception as e:
            log_error(f"fetch_prices [{t}]: {e}")
            out[t] = {
                "price": None, "price_change_1d": None, "price_change_1d_pct": None,
                "price_change_1w_pct": None, "price_change_1m_pct": None,
                "price_change_ytd_pct": None, "52w_high": None, "52w_low": None,
                "volume_today": None, "avg_volume_30d": None, "market_cap_mn": None,
                "dividend_yield_pct": None, "beta": None,
                "short_interest_pct": None, "institutional_ownership_pct": None,
                "as_of_date": date.today().isoformat(),
                "_error": str(e),
            }
    return out


def _pct_change_back(hist: "pd.DataFrame", n_trading_days: int) -> Optional[float]:
    if hist is None or len(hist) <= n_trading_days:
        return None
    last = hist["Close"].iloc[-1]
    prior = hist["Close"].iloc[-(n_trading_days + 1)]
    if prior == 0 or prior is None or pd.isna(prior):
        return None
    return float((last - prior) / prior * 100)


def _pct_change_ytd(hist: "pd.DataFrame", current: Optional[float]) -> Optional[float]:
    if hist is None or hist.empty or current is None:
        return None
    yr = date.today().year
    # Find first trading day of current year in the index
    yr_idx = hist.index[hist.index.year == yr]
    if len(yr_idx) == 0:
        return None
    base = float(hist.loc[yr_idx[0], "Close"])
    if base == 0:
        return None
    return float((current - base) / base * 100)


def _round(v, ndigits=4):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), ndigits)


def _round_pct(v):
    """yfinance reports some percentages as decimals (0.038 = 3.8%) and others
    as percent already. Heuristic: if abs <= 1.5, treat as decimal; else as %."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    v = float(v)
    if abs(v) <= 1.5:
        v *= 100
    return round(v, 2)


def fetch_price_history(tickers: list[str], start: str = "2020-01-01",
                         include_indexes: bool = True) -> "pd.DataFrame":
    """Return MultiIndex DataFrame with (Field, Ticker) columns."""
    syms = list(tickers)
    if include_indexes:
        syms.extend(["^GSPC", "BIZD"])
    df = yf.download(syms, start=start, interval="1d", group_by="ticker",
                     auto_adjust=False, threads=True, progress=False)
    return df


# --------------------------------------------------------------- volatility
def _close_series(price_history: "pd.DataFrame", ticker: str) -> Optional["pd.Series"]:
    try:
        if isinstance(price_history.columns, pd.MultiIndex):
            if ticker in price_history.columns.get_level_values(0):
                return price_history[ticker]["Close"].dropna()
            # Some yfinance versions invert the levels
            if "Close" in price_history.columns.get_level_values(0):
                return price_history["Close"][ticker].dropna()
        else:
            return price_history["Close"].dropna()
    except Exception as e:
        log_error(f"_close_series [{ticker}]: {e}")
    return None


def _realized_vol(close: "pd.Series", n: int) -> Optional[float]:
    rets = close.pct_change().dropna()
    if len(rets) < 5:
        return None
    tail = rets.tail(n) if len(rets) >= n else rets
    sd = tail.std()
    if sd is None or pd.isna(sd):
        return None
    return float(sd * (252 ** 0.5) * 100)


def _max_drawdown(close: "pd.Series") -> Optional[float]:
    if close is None or len(close) < 2:
        return None
    rolling_max = close.cummax()
    dd = (close - rolling_max) / rolling_max
    val = float(dd.min() * 100) if not pd.isna(dd.min()) else None
    return val


def compute_volatility(price_history: "pd.DataFrame", ticker: str) -> dict:
    """Realized vol + max drawdown for one ticker."""
    out = {
        "realized_vol_30d_pct": None, "realized_vol_90d_pct": None,
        "realized_vol_1y_pct": None, "max_drawdown_ytd_pct": None,
        "max_drawdown_1y_pct": None, "max_drawdown_since_2020_pct": None,
        "quarterly_history": {},
    }
    close = _close_series(price_history, ticker)
    if close is None or close.empty:
        return out
    out["realized_vol_30d_pct"] = _round(_realized_vol(close, 21), 2)
    out["realized_vol_90d_pct"] = _round(_realized_vol(close, 63), 2)
    out["realized_vol_1y_pct"] = _round(_realized_vol(close, 252), 2)
    out["max_drawdown_since_2020_pct"] = _round(_max_drawdown(close), 2)

    # YTD drawdown
    yr = date.today().year
    ytd = close[close.index.year == yr]
    out["max_drawdown_ytd_pct"] = _round(_max_drawdown(ytd), 2)
    # 1y drawdown
    one_yr = close.tail(252)
    out["max_drawdown_1y_pct"] = _round(_max_drawdown(one_yr), 2)

    out["quarterly_history"] = compute_quarterly_vol(close)
    return out


def compute_quarterly_vol(close: "pd.Series") -> dict:
    """Per-quarter realized vol, max drawdown, and price return."""
    out = {}
    if close is None or close.empty:
        return out
    # Iterate calendar quarters from 2020 to current
    today = date.today()
    for year in range(2020, today.year + 1):
        for q, (m_start, m_end) in enumerate(((1, 3), (4, 6), (7, 9), (10, 12)), start=1):
            qstart = pd.Timestamp(year, m_start, 1)
            # End of quarter: last day of m_end
            if m_end == 12:
                qend = pd.Timestamp(year, 12, 31)
            else:
                qend = pd.Timestamp(year, m_end + 1, 1) - pd.Timedelta(days=1)
            if qstart > pd.Timestamp(today):
                continue
            window = close.loc[qstart:qend].dropna()
            if len(window) < 5:
                continue
            rets = window.pct_change().dropna()
            sd = rets.std() if len(rets) >= 2 else None
            vol_pct = float(sd * (252 ** 0.5) * 100) if (sd is not None and not pd.isna(sd)) else None
            dd_pct = _max_drawdown(window)
            ret_pct = float((window.iloc[-1] / window.iloc[0] - 1) * 100) if window.iloc[0] != 0 else None
            out[f"Q{q} {year}"] = {
                "realized_vol_pct": _round(vol_pct, 2),
                "max_drawdown_pct": _round(dd_pct, 2),
                "price_return_pct": _round(ret_pct, 2),
            }
    return out


# --------------------------------------------------------------- short interest
def fetch_short_interest_finra() -> dict[str, dict]:
    """Best-effort: download the most recent FINRA CNMS short-volume file.

    Returns {ticker: {"shares": int|None, "date": "YYYY-MM-DD"}}. The CNMS
    short-volume file is *daily* (not "current short interest"), so we sum
    the most recent month's short volume per ticker as a proxy. The proper
    short-interest series is in the FINRA short-interest API which is now
    paid; the CDN file is the closest free substitute.
    """
    out: dict[str, dict] = {}
    today = date.today()
    # try the past 4 months in reverse
    for m_offset in range(0, 4):
        y = today.year
        m = today.month - m_offset
        while m <= 0:
            m += 12; y -= 1
        ym = f"{y:04d}{m:02d}"
        # FINRA daily short-volume files are zip'd by month in the consolidated
        # NMS file pattern. Use monthly aggregate file if available.
        url = f"https://cdn.finra.org/equity/regsho/monthly/CNMSshvol{ym}.txt"
        try:
            r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
            if r.status_code != 200 or len(r.content) < 1000:
                continue
            # Pipe-delimited: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
            text = r.text
            agg: dict[str, list[int]] = {}
            for line in text.splitlines():
                parts = line.split("|")
                if len(parts) < 5 or parts[0] == "Date":
                    continue
                sym = parts[1].strip().upper()
                try:
                    sv = int(parts[2])
                except ValueError:
                    continue
                agg.setdefault(sym, []).append(sv)
            month_end_iso = f"{y:04d}-{m:02d}-{_last_day(y, m):02d}"
            for sym, lst in agg.items():
                out[sym] = {"shares": sum(lst) // max(len(lst), 1), "date": month_end_iso}
            return out
        except Exception as e:
            log_error(f"fetch_short_interest_finra ({ym}): {e}")
            continue
    return out


def _last_day(year: int, month: int) -> int:
    if month == 12:
        nxt = pd.Timestamp(year + 1, 1, 1)
    else:
        nxt = pd.Timestamp(year, month + 1, 1)
    return (nxt - pd.Timedelta(days=1)).day


# --------------------------------------------------------------- 13F (quarterly)
def run_quarterly_ownership_update(tickers: list[str]) -> dict:
    """Quarterly: aggregate 13F-HR institutional holdings per BDC.

    This is computationally heavy — 13F filings for thousands of institutions
    per quarter, cross-referenced to BDC tickers via CUSIP/CIK. Implemented
    as a placeholder that uses yfinance's `heldPercentInstitutions` as a
    proxy. Real 13F aggregation can be plugged in later.
    """
    out = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info or {}
            holders = info.get("heldPercentInstitutions")
            count = info.get("institutionsCount")
            out[t] = {
                "institutional_ownership_pct": _round_pct(holders),
                "institutional_holders_count": int(count) if isinstance(count, (int, float)) else None,
            }
        except Exception as e:
            log_error(f"13F-proxy [{t}]: {e}")
            out[t] = {"institutional_ownership_pct": None, "institutional_holders_count": None}
    return out


# --------------------------------------------------------------- builders
def build_prices_json(price_data: dict, nav_data: dict) -> dict:
    funds = {}
    for t, p in sorted(price_data.items()):
        nav = nav_data.get(t)
        ptn = None
        if isinstance(p.get("price"), (int, float)) and isinstance(nav, (int, float)) and nav > 0:
            ptn = round(p["price"] / nav, 4)
        funds[t] = {
            "price": p.get("price"),
            "price_change_1d": p.get("price_change_1d"),
            "price_change_1d_pct": p.get("price_change_1d_pct"),
            "price_change_1w_pct": p.get("price_change_1w_pct"),
            "price_change_1m_pct": p.get("price_change_1m_pct"),
            "price_change_ytd_pct": p.get("price_change_ytd_pct"),
            "nav_per_share": nav,
            "price_to_nav": ptn,
            "52w_high": p.get("52w_high"),
            "52w_low": p.get("52w_low"),
            "volume_today": p.get("volume_today"),
            "avg_volume_30d": p.get("avg_volume_30d"),
            "market_cap_mn": p.get("market_cap_mn"),
            "dividend_yield_pct": p.get("dividend_yield_pct"),
            "beta": p.get("beta"),
            "short_interest_pct": p.get("short_interest_pct"),
            "institutional_ownership_pct": p.get("institutional_ownership_pct"),
            "as_of_date": p.get("as_of_date"),
        }
    return {"last_updated": now_utc_iso(), "funds": funds}


def _series_to_history(close: "pd.Series") -> dict:
    """Convert a pandas Series of close prices into {YYYY-MM-DD: value}."""
    out = {}
    for idx, val in close.items():
        if pd.isna(val):
            continue
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        out[d] = round(float(val), 4)
    return out


def _index_changes(close: "pd.Series") -> dict:
    out = {}
    if close is None or close.empty:
        return {"current": None, "change_1d_pct": None, "change_1w_pct": None,
                "change_1m_pct": None, "change_ytd_pct": None}
    last = float(close.iloc[-1])
    out["current"] = round(last, 2)
    out["change_1d_pct"] = round(float(close.pct_change().iloc[-1] * 100), 2) if len(close) > 1 else None
    out["change_1w_pct"] = _round(_pct_change_back(pd.DataFrame({"Close": close}), 5), 2)
    out["change_1m_pct"] = _round(_pct_change_back(pd.DataFrame({"Close": close}), 21), 2)
    yr = date.today().year
    yr_close = close[close.index.year == yr]
    if len(yr_close) > 0:
        base = float(yr_close.iloc[0])
        out["change_ytd_pct"] = round((last - base) / base * 100, 2) if base != 0 else None
    else:
        out["change_ytd_pct"] = None
    return out


def build_index_json(price_history: "pd.DataFrame") -> dict:
    spx_close = _close_series(price_history, "^GSPC")
    bizd_close = _close_series(price_history, "BIZD")

    out = {"last_updated": now_utc_iso()}

    if spx_close is not None and not spx_close.empty:
        out["spx"] = _index_changes(spx_close)
        out["spx"]["history"] = _series_to_history(spx_close)
        # indexed series
        base_row = spx_close[spx_close.index >= BASE_DATE]
        if not base_row.empty:
            base_val = float(base_row.iloc[0])
            indexed = (spx_close / base_val * 100).dropna()
            out["spx_indexed"] = {
                "base_date": indexed.index[0].strftime("%Y-%m-%d"),
                "base_value": 100.0,
                "current": round(float(indexed.iloc[-1]), 2),
                "history": _series_to_history(indexed),
            }
    else:
        out["spx"] = {"current": None}
        out["spx_indexed"] = {"current": None}

    if bizd_close is not None and not bizd_close.empty:
        out["bizd"] = _index_changes(bizd_close)
        out["bizd"]["history"] = _series_to_history(bizd_close)
        base_row = bizd_close[bizd_close.index >= BASE_DATE]
        if not base_row.empty:
            base_val = float(base_row.iloc[0])
            indexed = (bizd_close / base_val * 100).dropna()
            out["bizd_indexed"] = {
                "base_date": indexed.index[0].strftime("%Y-%m-%d"),
                "base_value": 100.0,
                "current": round(float(indexed.iloc[-1]), 2),
                "history": _series_to_history(indexed),
            }
    else:
        out["bizd"] = {"current": None}
        out["bizd_indexed"] = {"current": None}
    return out


def build_volatility_json(price_history: "pd.DataFrame", tickers: list[str]) -> dict:
    funds = {}
    for t in tickers:
        try:
            funds[t] = compute_volatility(price_history, t)
        except Exception as e:
            log_error(f"build_volatility [{t}]: {e}")
            funds[t] = {"_error": str(e)}
    return {"last_updated": now_utc_iso(), "funds": funds}


def build_ownership_json(price_data: dict, short_interest_data: dict) -> dict:
    funds = {}
    si_date = None
    for t, p in price_data.items():
        si = short_interest_data.get(t.upper())
        if si:
            si_date = si.get("date")
        avg30 = p.get("avg_volume_30d") or 0
        si_shares = si.get("shares") if si else None
        days_to_cover = None
        if isinstance(si_shares, (int, float)) and avg30:
            days_to_cover = round(si_shares / avg30, 2)
        funds[t] = {
            "short_interest_pct": p.get("short_interest_pct"),
            "short_interest_shares": si_shares,
            "days_to_cover": days_to_cover,
            "institutional_ownership_pct": p.get("institutional_ownership_pct"),
            "institutional_holders_count": None,
            "history": {"short_interest": {}, "institutional_ownership": {}},
        }
    return {
        "last_updated": now_utc_iso(),
        "short_interest_source": "FINRA CNMS monthly aggregate",
        "short_interest_as_of": si_date,
        "institutional_source": "yfinance heldPercentInstitutions",
        "funds": funds,
    }


# --------------------------------------------------------------- atomic writes
def _atomic_write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def write_market_files(output_dir: pathlib.Path, prices=None, idx=None, vol=None,
                        ownership=None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if prices is not None:
        _atomic_write(output_dir / "prices.json", json.dumps(prices, indent=2))
    if idx is not None:
        _atomic_write(output_dir / "index.json", json.dumps(idx, indent=2))
    if vol is not None:
        _atomic_write(output_dir / "volatility.json", json.dumps(vol, indent=2))
    if ownership is not None:
        _atomic_write(output_dir / "ownership.json", json.dumps(ownership, indent=2))
    _atomic_write(output_dir / "LAST_REFRESH.txt", now_utc_iso() + "\n")


# --------------------------------------------------------------- main flows
def run_twice_daily_refresh() -> None:
    print(f"[{now_utc_iso()}] starting twice-daily refresh")
    tickers = load_universe()
    nav = load_nav_from_timeseries()
    price_data = fetch_prices(tickers)
    price_history = fetch_price_history(tickers, include_indexes=True)
    short_interest = fetch_short_interest_finra()

    prices = build_prices_json(price_data, nav)
    idx = build_index_json(price_history)
    ownership = build_ownership_json(price_data, short_interest)
    write_market_files(MARKET_DIR, prices=prices, idx=idx, ownership=ownership)
    print(f"[{now_utc_iso()}] wrote prices.json, index.json, ownership.json")


def run_quarterly_refresh() -> None:
    print(f"[{now_utc_iso()}] starting quarterly refresh (includes volatility)")
    tickers = load_universe()
    nav = load_nav_from_timeseries()
    price_data = fetch_prices(tickers)
    price_history = fetch_price_history(tickers, include_indexes=True)
    short_interest = fetch_short_interest_finra()

    prices = build_prices_json(price_data, nav)
    idx = build_index_json(price_history)
    ownership = build_ownership_json(price_data, short_interest)
    vol = build_volatility_json(price_history, tickers)
    write_market_files(MARKET_DIR, prices=prices, idx=idx, vol=vol, ownership=ownership)
    print(f"[{now_utc_iso()}] wrote all 4 files")


def run_test_mode() -> None:
    """ARCC-only dry run; print and do not write."""
    print(f"[{now_utc_iso()}] TEST MODE — ARCC only, no files written\n")
    nav = load_nav_from_timeseries()
    print(f"NAV from timeseries (latest): ARCC ${nav.get('ARCC')}")
    print(f"Total tickers in universe: {len(load_universe())}\n")

    print("Fetching price for ARCC via yfinance...")
    price_data = fetch_prices(["ARCC"])
    print("ARCC raw price record:")
    print(json.dumps(price_data["ARCC"], indent=2))

    print("\nFetching 5y price history for ARCC, ^GSPC, BIZD...")
    price_history = fetch_price_history(["ARCC"], start="2020-01-01", include_indexes=True)
    arcc_close = _close_series(price_history, "ARCC")
    print(f"ARCC close history: {len(arcc_close) if arcc_close is not None else 0} rows")

    print("\nBuilding prices.json (single-fund)...")
    prices = build_prices_json(price_data, {"ARCC": nav.get("ARCC")})
    print(json.dumps(prices, indent=2)[:1500])

    print("\nBuilding index.json (SPX + BIZD)...")
    idx = build_index_json(price_history)
    # Trim history for display
    for k in ("spx", "bizd", "spx_indexed", "bizd_indexed"):
        if k in idx and isinstance(idx[k], dict) and "history" in idx[k]:
            n = len(idx[k]["history"])
            idx[k]["history"] = {"_history_omitted": f"{n} rows"}
    print(json.dumps(idx, indent=2))

    print("\nComputing ARCC volatility...")
    vol = compute_volatility(price_history, "ARCC")
    qhist_count = len(vol.get("quarterly_history") or {})
    vol["quarterly_history"] = {"_quarters": f"{qhist_count} quarters",
                                "_sample": dict(list((vol.get("quarterly_history") or {}).items())[:3])
                                if False else None}
    print(json.dumps({k: v for k, v in vol.items() if k != "quarterly_history"}, indent=2))
    full_vol = compute_volatility(price_history, "ARCC")
    print(f"\nQuarterly vol history: {len(full_vol['quarterly_history'])} quarters")
    sample_qtrs = list(full_vol["quarterly_history"].items())[:3] + list(full_vol["quarterly_history"].items())[-3:]
    print("First 3 + last 3:")
    for q, v in sample_qtrs:
        print(f"  {q:8}  {v}")

    print("\nFetching FINRA short interest (most recent month)...")
    si = fetch_short_interest_finra()
    arcc_si = si.get("ARCC")
    print(f"ARCC short-interest entry: {arcc_si}")

    print("\nBuilding ownership.json (ARCC entry only)...")
    ownership = build_ownership_json({"ARCC": price_data["ARCC"]}, si)
    print(json.dumps(ownership, indent=2))

    print(f"\n[{now_utc_iso()}] TEST MODE complete — no files written.")


def run_prices_only() -> None:
    tickers = load_universe()
    nav = load_nav_from_timeseries()
    price_data = fetch_prices(tickers)
    prices = build_prices_json(price_data, nav)
    write_market_files(MARKET_DIR, prices=prices)
    print(f"[{now_utc_iso()}] wrote prices.json")


def run_index_only() -> None:
    tickers = load_universe()
    price_history = fetch_price_history(tickers, include_indexes=True)
    idx = build_index_json(price_history)
    write_market_files(MARKET_DIR, idx=idx)
    print(f"[{now_utc_iso()}] wrote index.json")


# --------------------------------------------------------------- CLI
def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--refresh", action="store_true",
                   help="twice-daily refresh: prices, index, ownership")
    g.add_argument("--quarterly", action="store_true",
                   help="quarterly refresh: above plus volatility")
    g.add_argument("--test", action="store_true",
                   help="ARCC-only dry run; no files written")
    g.add_argument("--prices-only", action="store_true",
                   help="prices.json only")
    g.add_argument("--index-only", action="store_true",
                   help="index.json only")
    args = p.parse_args()

    if args.test:
        run_test_mode()
    elif args.refresh:
        run_twice_daily_refresh()
    elif args.quarterly:
        run_quarterly_refresh()
    elif args.prices_only:
        run_prices_only()
    elif args.index_only:
        run_index_only()


if __name__ == "__main__":
    main()
