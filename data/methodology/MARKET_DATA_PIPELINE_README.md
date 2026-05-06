# Market Data Pipeline

Twice-daily price + valuation refresh for the 47-fund traded BDC universe.
Completely separate from the SEC filing enrichment pipeline — different
data sources, different cadence, different output files. Never touches
`data/timeseries/`.

## What it does

For every traded BDC:

1. Fetches latest price + 52w range + market cap + dividend yield + beta
   from yfinance.
2. Computes price-to-NAV using the most recent NAV from the timeseries
   JSON (loaded once at startup; not re-fetched from EDGAR).
3. Pulls SPX (`^GSPC`) and BIZD ETF as benchmark indices, including
   indexed series (2020-01-02 = 100).
4. Computes realized volatility (30d / 90d / 1y) and max drawdown
   (YTD / 1y / since-2020) from yfinance daily price history.
5. Pulls FINRA monthly short-volume aggregate as a free proxy for
   short interest, and computes days-to-cover from short volume /
   30-day average volume.
6. Pulls institutional ownership % from yfinance.

## Data sources (all free, no API keys)

| Source | Used for | Limitation |
|---|---|---|
| **yfinance** | prices, fundamentals, institutional % | ~15 min delayed; coverage gaps for thinly-traded BDCs |
| **FINRA CDN** | short volume (monthly aggregate) | bi-monthly cadence; *short volume*, not short *interest* (real short-interest API now paid) |
| **SEC 13F** | quarterly institutional aggregation (placeholder) | computationally heavy; current implementation uses yfinance proxy |
| **Computed** | realized vol, max drawdown, price/NAV | derived from yfinance price history + timeseries NAV |

## Output files (all in `data/market/`)

| File | Cadence | Schema |
|---|---|---|
| `prices.json` | 2x daily | `{last_updated, funds: {ticker: {price, change_*, nav, p2nav, 52w_*, volume, mcap, divyield, beta, short%, instown%}}}` |
| `index.json` | 2x daily | `{last_updated, spx: {...}, bizd: {...}, spx_indexed: {...}, bizd_indexed: {...}}` |
| `volatility.json` | quarterly | `{last_updated, funds: {ticker: {vol_30/90/1y, dd_ytd/1y/since_2020, quarterly_history}}}` |
| `ownership.json` | 2x daily (with monthly SI lag) | `{last_updated, short_interest_source, short_interest_as_of, funds: {...}}` |
| `LAST_REFRESH.txt` | 2x daily | one line ISO timestamp |

All writes are atomic (`.tmp` then `os.replace`).

## How to run manually

```bash
# Test (ARCC only, prints, writes nothing)
python3 market_data_pipeline.py --test

# Twice-daily refresh (prices + index + ownership; ~2 min)
python3 market_data_pipeline.py --refresh

# Quarterly refresh (above + volatility; ~10 min)
python3 market_data_pipeline.py --quarterly

# Single-file refreshes
python3 market_data_pipeline.py --prices-only
python3 market_data_pipeline.py --index-only
```

Dependencies:
```bash
pip install -r requirements.txt
```

## GitHub Actions automation

`.github/workflows/market_refresh.yml` runs `--refresh` on schedule:
- 11:00 UTC (≈ 6am ET) Mon–Fri
- 22:00 UTC (≈ 5pm ET) Mon–Fri
- manually via `workflow_dispatch`

Required repo setting:  
**Settings → Actions → General → Workflow permissions → Read and write permissions**

The workflow commits `data/market/*.json` only if changed and pushes to `main`.

## Update frequency by file

| File | Updated when |
|---|---|
| `prices.json` | every refresh (2x daily) |
| `index.json` | every refresh (2x daily) |
| `ownership.json` | every refresh; FINRA SI may lag 2-4 weeks |
| `volatility.json` | quarterly (after new 10-Qs file) |
| `LAST_REFRESH.txt` | every successful refresh |

## Known limitations

- yfinance prices are delayed ~15 minutes
- FINRA CNMS aggregate is *short volume* (count of short trades) not the
  formal *short interest* (open short positions). The proper short-interest
  API requires a paid FINRA subscription.
- `institutional_ownership_pct` from yfinance is a snapshot — it doesn't
  give the per-quarter time series you'd get from real 13F aggregation.
  `run_quarterly_ownership_update()` is a placeholder for that.
- Implied volatility is not available via free sources — we compute
  realized vol from price history instead.
- `price_to_nav` uses the most recent filed NAV, which may be 1–3 months
  old. The price changes daily; the NAV doesn't.
- `^GSPC` (SPX) and `BIZD` (UBS BDC ETF) are the standard benchmarks.
  BIZD launched 2013 so all data from 2020 forward is fully covered.

## Error handling

- yfinance failures per ticker → log to `data/logs/market_errors.log`,
  set fields to null, continue.
- FINRA fetch failure → log, leave previous `ownership.json` unchanged.
- All file writes are atomic — partial/corrupt files cannot be observed.
