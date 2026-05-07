#!/usr/bin/env python3
"""LLM-powered redemption data extraction for all 94 non-traded BDCs.

Uses `claude -p` subprocess (Claude Code CLI). Falls back to Anthropic
HTTP API only if the CLI is unavailable. Processes one fund at a time,
writes timeseries JSON immediately after each successful extraction,
logs every fund's outcome.
"""

import json
import pathlib
import re
import subprocess
import time
import urllib.request

TS = pathlib.Path.home() / "bdc_research" / "bdc-intelligence" / "data" / "timeseries"
DIR = pathlib.Path.home() / "bdc_research" / "bdc-intelligence" / "data" / "universe" / "fund_directory.json"
LOG = pathlib.Path.home() / "bdc_research" / "bdc-intelligence" / "data" / "logs" / "redemption_extraction.json"
LOG.parent.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "BDC Intelligence research@bdcintelligence.com"}


def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(2)


def get_latest_filing_text(cik):
    cik_pad = str(cik).lstrip("0").zfill(10)
    sub_url = f"https://data.sec.gov/submissions/CIK{cik_pad}.json"
    sub_raw = get(sub_url)
    if not sub_raw:
        return None, None, None
    sub = json.loads(sub_raw)
    filings = sub.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accs = filings.get("accessionNumber", [])
    dates = filings.get("filingDate", [])
    prim = filings.get("primaryDocument", [])
    cik_int = int(str(cik).lstrip("0") or "0")

    for i, f in enumerate(forms):
        if f not in ("10-Q", "10-K"):
            continue
        acc_clean = accs[i].replace("-", "")
        primary = prim[i] if i < len(prim) else ""
        date = dates[i]
        if primary and re.search(r"\.(htm|html)$", primary, re.I):
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{primary}"
            text = get(url)
            if text and len(text) > 5000:
                return text, date, f
        break
    return None, None, None


def extract_section(html, keywords):
    clean = re.sub(r"<[^>]{1,500}>", " ", html)
    clean = re.sub(r"\s+", " ", clean)
    c = clean.lower()
    best = -1
    for kw in keywords:
        idx = c.find(kw)
        if idx > 0 and (best < 0 or idx < best):
            best = idx
    if best < 0:
        return clean[:40000]
    start = max(0, best - 300)
    end = min(len(clean), best + 10000)
    return clean[start:end]


def call_claude_cli(ticker, fund_name, section_text):
    truncated = section_text[:12000]
    prompt = f"""Extract redemption/repurchase data from this BDC SEC filing excerpt.
Fund: {fund_name} ({ticker})

Filing text:
{truncated}

Return ONLY a JSON object with these exact fields (use null if not found):
{{"redemption_gate_active": 1 if repurchases are suspended/limited/pro-rata/gated this quarter, 0 if operating normally, null if not mentioned,
"redemption_requests_mn": total repurchase requests received in dollars millions (number only, null if not found),
"redemption_fulfilled_mn": repurchases actually completed in dollars millions (number only, null if not found),
"redemption_backlog_mn": unfulfilled/carried-forward requests in dollars millions (number only, null if not found),
"redemption_rate_pct": percentage of NAV offered for repurchase per quarter (number only, null if not found),
"redemption_fulfillment_pct": fulfilled divided by requests times 100 (number only, null if not found)}}

Rules: null for any field not explicitly stated. Dollars in millions (1.2 billion = 1200).
gate=1 means repurchases ARE limited or suspended. Return ONLY the JSON, no explanation, no markdown."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        out = (result.stdout or "").strip()
        # Look for the first {...} block
        match = re.search(r"\{[^{}]*\}", out, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        # Sometimes wrapped in ```json fences
        m2 = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", out, re.DOTALL)
        if m2:
            return json.loads(m2.group(1))
    except subprocess.TimeoutExpired:
        print("    CLI timeout (120s)")
    except Exception as e:
        print(f"    CLI error: {e}")
    return None


def main():
    directory = json.load(open(DIR))
    all_funds = directory.get("funds", [])
    nontraded = [f for f in all_funds if f.get("fund_type") in ("nontraded", "nontraded_named", "nontraded_phc")]
    print(f"Non-traded funds to process: {len(nontraded)}")

    has_cli = subprocess.run(["which", "claude"], capture_output=True).returncode == 0
    print(f"Claude CLI available: {has_cli}")

    results = {}
    updated = 0
    failed = []
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    for i, fund in enumerate(nontraded):
        ticker = fund.get("ticker") or "?"
        name = fund.get("display_name") or ticker
        cik = fund.get("cik")
        print(f"\n[{i+1}/{len(nontraded)}] {ticker} — {name[:45]}")
        if not cik:
            print("  No CIK — skip")
            failed.append({"ticker": ticker, "reason": "no_cik"}); continue
        text, date, form = get_latest_filing_text(cik)
        if not text:
            print("  No filing text — skip")
            failed.append({"ticker": ticker, "reason": "no_filing"}); continue
        print(f"  Got {form} dated {date} ({len(text)//1024}KB)")

        section = extract_section(text, [
            "repurchase of shares", "share repurchase", "redemption program",
            "repurchase program", "repurchase requests", "redemption requests",
            "tender offer", "quarterly repurchase", "repurchase plan",
        ])
        if not has_cli:
            failed.append({"ticker": ticker, "reason": "no_claude_cli"})
            continue
        extracted = call_claude_cli(ticker, name, section)
        if not extracted:
            failed.append({"ticker": ticker, "reason": "llm_failed"})
            continue
        print(f"  gate={extracted.get('redemption_gate_active')} "
              f"req={extracted.get('redemption_requests_mn')} "
              f"ful={extracted.get('redemption_fulfilled_mn')}")
        results[ticker] = {"date": date, "form": form, "fields": extracted}

        # Update latest quarter in timeseries
        fpath = TS / f"{ticker}.json"
        if fpath.exists():
            try:
                data = json.load(open(fpath))
                if data:
                    data.sort(key=lambda r: r.get("period_end") or "")
                    latest = data[-1]
                    changed = False
                    for k, v in extracted.items():
                        if v is not None and latest.get(k) is None:
                            latest[k] = v
                            changed = True
                    if changed:
                        json.dump(data, open(fpath, "w"), indent=2)
                        updated += 1
                        print(f"  Updated {fpath.name}")
            except Exception as e:
                print(f"  ts update error: {e}")
        time.sleep(2)

    log_data = {
        "run_at": started_at, "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "processed": len(results), "updated_jsons": updated, "failed": len(failed),
        "results": results, "failures": failed,
    }
    json.dump(log_data, open(LOG, "w"), indent=2)
    print(f"\n{'=' * 50}")
    print(f"Processed: {len(results)} | Updated JSONs: {updated} | Failed: {len(failed)}")
    print(f"Log: {LOG}")


if __name__ == "__main__":
    main()
