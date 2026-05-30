"""
fetch_news.py — BDC Intelligence 8-K news aggregator.

For every fund in data/universe/fund_directory.json, fetches 8-K filings
from SEC EDGAR (Jan 1, 2020 onward), enriches each with the issuer's
filing-page headline, and writes:

    data/news/{ticker}.json         (per-fund news file)
    data/news/_index.json           (universe-wide summary)
    data/news/_state.json           (incremental fetch state)

Designed for both:
  - Initial backfill: fetches everything from 2020-01-01 to today (~25-30 min one time)
  - Daily incremental: re-runs nightly via GitHub Action, only fetches new filings

Each item's URL points to the actual SEC filing — clicking opens SEC.gov.

USAGE:
    python scripts/fetch_news.py                  # incremental refresh, all funds
    python scripts/fetch_news.py --backfill       # ignore state, full 2020-onward refetch
    python scripts/fetch_news.py --ticker ARCC    # one fund only
    python scripts/fetch_news.py --no-enrich      # skip headline enrichment (faster)
    python scripts/fetch_news.py --since 2024-01-01  # explicit cutoff

PRE-RUN: edit USER_AGENT below to include your real contact email (SEC requirement).
"""
from __future__ import annotations
import argparse, json, os, re, sys, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import urllib.request, urllib.error

# =============================================================================
USER_AGENT = "BDC Intelligence Research qsaif2321@gmail.com"  # ← put your real email
SINCE_DEFAULT = "2020-01-01"
SEC_RATE_DELAY = 0.12  # ~8 req/sec (SEC limit is 10/sec)

ROOT = Path(__file__).resolve().parent.parent
DIR_PATH = ROOT / "data" / "universe" / "fund_directory.json"
OUT_DIR = ROOT / "data" / "news"
STATE_PATH = OUT_DIR / "_state.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ITEM_LABELS = {
    "1.01": "Material Definitive Agreement",
    "1.02": "Termination of Material Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Acquisition or Disposition",
    "2.02": "Results of Operations",
    "2.03": "Material Off-Balance-Sheet Obligation",
    "2.04": "Triggering Event re Material Obligation",
    "2.05": "Costs Re Exit/Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Listing / Delisting / Compliance",
    "3.02": "Unregistered Sale of Equity",
    "3.03": "Modifications to Holder Rights",
    "4.01": "Auditor Changes",
    "4.02": "Non-Reliance on Prior Financials",
    "5.01": "Changes in Control",
    "5.02": "Officer / Director Departure or Appointment",
    "5.03": "Amendments to Charter / Bylaws",
    "5.07": "Submission of Matters to a Vote",
    "5.08": "Shareholder Director Nominations",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# =============================================================================
_last_sec_call = 0.0


def sec_get(url: str, timeout: int = 20) -> Optional[bytes]:
    """Polite SEC fetch with rate limit."""
    global _last_sec_call
    elapsed = time.time() - _last_sec_call
    if elapsed < SEC_RATE_DELAY:
        time.sleep(SEC_RATE_DELAY - elapsed)
    _last_sec_call = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (404, 403):
            return None
        print(f"  [http {e.code}] {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [http err] {e} {url}", file=sys.stderr)
        return None


def enrich_headline(filing_index_url: str) -> Optional[str]:
    """
    Fetch the filing's index page and try to extract more informative item
    descriptions than the bare code labels. Returns None if extraction fails.
    """
    raw = sec_get(filing_index_url)
    if not raw:
        return None
    try:
        html = raw.decode("utf-8", errors="ignore")
    except Exception:
        return None
    # The index page lists "Item X.YZ Description" lines for 8-Ks
    matches = re.findall(r"Item\s+(\d+\.\d+)\s+([^\n<]+)", html)
    if not matches:
        return None
    seen = set()
    parts = []
    for code, descr in matches[:8]:
        if code in seen:
            continue
        seen.add(code)
        descr = re.sub(r"\s+", " ", descr).strip(" .;:")
        if len(descr) > 80:
            descr = descr[:78].rsplit(" ", 1)[0] + "…"
        if descr:
            parts.append(descr)
        if len(parts) >= 3:
            break
    return " · ".join(parts) if parts else None


# =============================================================================
@dataclass
class NewsItem:
    date: str
    title: str               # raw item-description headline from SEC index page
    headline_ai: str = ""    # WSJ-style headline written by Claude Code (filled later, separately)
    snippet: str = ""        # press-release first paragraph (filled by enrich step, optional)
    url: str = ""
    source: str = "edgar"
    source_label: str = "SEC 8-K"
    category: str = "auto"
    accession: str = ""

    def key(self) -> str:
        return self.accession or self.url


def categorize(item_codes: List[str]) -> str:
    """Map 8-K item codes to news.html category keys."""
    if any(c in item_codes for c in ("1.03", "2.04", "2.06", "1.02", "4.02")):
        return "credit-event"
    if "2.02" in item_codes:
        return "earnings"
    if any(c in item_codes for c in ("2.01", "5.01")):
        return "ma"
    if "5.02" in item_codes:
        return "personnel"
    if any(c in item_codes for c in ("1.01", "3.02")):
        return "capital-markets"
    return "other"


def fallback_headline(item_codes: List[str]) -> str:
    labels = [ITEM_LABELS.get(c, f"Item {c}") for c in item_codes]
    return " · ".join(labels) if labels else "8-K Current Report"


def fetch_fund(fund: dict, since: str, last_accession: Optional[str], enrich: bool) -> List[NewsItem]:
    ticker = fund.get("ticker", "")
    cik = (fund.get("cik") or "").lstrip("0")
    if not cik:
        return []
    padded = cik.zfill(10)
    raw = sec_get(f"https://data.sec.gov/submissions/CIK{padded}.json")
    if not raw:
        return []
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return []

    recent = meta.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items_list = recent.get("items", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    out: List[NewsItem] = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        date_str = dates[i] if i < len(dates) else None
        if not date_str or date_str < since:
            continue

        accession = accessions[i] if i < len(accessions) else ""
        if last_accession and accession == last_accession:
            break  # incremental: recent[] is reverse chronological, stop here

        item_codes = [c.strip() for c in (items_list[i] if i < len(items_list) else "").split(",") if c.strip()]
        primary = primary_docs[i] if i < len(primary_docs) else ""
        accession_clean = accession.replace("-", "")

        index_url = f"https://www.sec.gov/Archives/edgar/data/{int(padded)}/{accession_clean}/{accession}-index.htm"
        primary_url = (f"https://www.sec.gov/Archives/edgar/data/{int(padded)}/{accession_clean}/{primary}"
                       if primary else index_url)

        headline = enrich_headline(index_url) if enrich else None
        if not headline:
            headline = fallback_headline(item_codes)

        out.append(NewsItem(
            date=date_str,
            title=f"8-K — {headline}",
            snippet="",
            url=primary_url,
            source="edgar",
            source_label="SEC 8-K",
            category=categorize(item_codes),
            accession=accession,
        ))

    return out


# =============================================================================
def merge_with_existing(ticker: str, new_items: List[NewsItem]) -> List[NewsItem]:
    fpath = OUT_DIR / f"{ticker}.json"
    existing: List[NewsItem] = []
    if fpath.exists():
        try:
            data = json.load(open(fpath))
            for raw in data.get("items", []):
                existing.append(NewsItem(
                    date=raw.get("date", ""),
                    title=raw.get("title", ""),
                    headline_ai=raw.get("headline_ai", ""),
                    snippet=raw.get("snippet", ""),
                    url=raw.get("url", ""),
                    source=raw.get("source", "edgar"),
                    source_label=raw.get("source_label", "SEC 8-K"),
                    category=raw.get("category", "other"),
                    accession=raw.get("accession", ""),
                ))
        except Exception:
            pass

    seen = {}
    for it in existing:
        seen[it.key()] = it
    for it in new_items:
        seen[it.key()] = it
    return sorted(seen.values(), key=lambda x: x.date, reverse=True)


def write_fund_file(ticker: str, items: List[NewsItem]):
    payload = {
        "ticker": ticker,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items),
        "items": [asdict(i) for i in items],
    }
    json.dump(payload, open(OUT_DIR / f"{ticker}.json", "w"), indent=2)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.load(open(STATE_PATH))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    state["_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(state, open(STATE_PATH, "w"), indent=2)


# =============================================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", help="Process only this ticker")
    p.add_argument("--since", default=SINCE_DEFAULT, help=f"ISO date cutoff (default {SINCE_DEFAULT})")
    p.add_argument("--backfill", action="store_true", help="Ignore state, refetch everything since --since")
    p.add_argument("--no-enrich", action="store_true", help="Skip headline enrichment (10x faster)")
    p.add_argument("--limit", type=int, help="Cap funds (testing)")
    args = p.parse_args()

    if not DIR_PATH.exists():
        sys.exit(f"ERROR: {DIR_PATH} not found")

    funds = json.load(open(DIR_PATH)).get("funds", [])
    if args.ticker:
        funds = [f for f in funds if f.get("ticker") == args.ticker]
        if not funds:
            sys.exit(f"Ticker {args.ticker} not in directory.")
    if args.limit:
        funds = funds[:args.limit]

    state = {} if args.backfill else load_state()
    enrich = not args.no_enrich

    print(f"Mode: {'BACKFILL' if args.backfill else 'INCREMENTAL'} · since {args.since} · enrich={enrich}")
    print(f"Funds: {len(funds)}")
    print()

    summary = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": args.since,
        "total_funds": len(funds),
        "funds_with_news": 0,
        "total_items": 0,
        "new_items_this_run": 0,
        "funds": [],
    }

    for fund in funds:
        ticker = fund.get("ticker", "")
        if not ticker:
            continue
        last_acc = state.get(ticker, {}).get("last_accession") if not args.backfill else None
        new_items = fetch_fund(fund, args.since, last_acc, enrich)

        if new_items:
            merged = merge_with_existing(ticker, new_items)
            write_fund_file(ticker, merged)
            state[ticker] = {
                "last_accession": merged[0].accession,
                "last_date": merged[0].date,
                "count": len(merged),
            }
            summary["funds_with_news"] += 1
            summary["total_items"] += len(merged)
            summary["new_items_this_run"] += len(new_items)
            summary["funds"].append({
                "ticker": ticker, "count": len(merged),
                "latest": merged[0].date, "new_this_run": len(new_items),
            })
            print(f"  [{ticker:<14}] +{len(new_items):>3} new · {len(merged):>3} total · latest {merged[0].date}")
        else:
            fpath = OUT_DIR / f"{ticker}.json"
            if fpath.exists():
                try:
                    d = json.load(open(fpath))
                    summary["funds_with_news"] += 1
                    summary["total_items"] += d.get("count", 0)
                    summary["funds"].append({
                        "ticker": ticker, "count": d.get("count", 0),
                        "latest": d.get("items", [{}])[0].get("date", "") if d.get("items") else "",
                        "new_this_run": 0,
                    })
                except Exception:
                    pass

    summary["funds"].sort(key=lambda x: x.get("latest") or "", reverse=True)
    json.dump(summary, open(OUT_DIR / "_index.json", "w"), indent=2)
    save_state(state)

    print()
    print(f"Done. {summary['funds_with_news']}/{summary['total_funds']} funds have news.")
    print(f"Total items in repo: {summary['total_items']} · This run: +{summary['new_items_this_run']}")


if __name__ == "__main__":
    main()
