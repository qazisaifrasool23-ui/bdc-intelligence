"""
sec_press.py — Press-release / material-filing feed for all covered BDCs.

Source: SEC EDGAR submissions API (official, free, stable):
    https://data.sec.gov/submissions/CIK##########.json

Two run modes:
    --mode base         Full 6-year history for every fund. Seeds everything.
    --mode incremental  Only filings not seen before. Runs nightly. Cheap.

Outputs (the contract the News page reads):
    data/news/press/big.json            -> the "big ones", LLM-headlined, ranked
    data/news/press/by_fund/{TICKER}.json -> every filing per fund, last 24 quarters
    data/news/press/_state.json         -> {last_run, seen: {accession: true}}

Nothing here crashes on a single bad fund/filing — it logs and moves on.
"""

import os
import re
import sys
import argparse
from datetime import datetime

from common import (
    log, ensure_dirs, load_funds, http_get, read_json, atomic_write_json,
    now_iso, cutoff_date, LLM, PRESS_DIR, BYFUND_DIR, MARQUEE, BIG_FORMS,
    MATERIAL_8K_ITEMS, FORM_LABELS,
)

STATE_PATH = os.path.join(PRESS_DIR, "_state.json")
BIG_PATH = os.path.join(PRESS_DIR, "big.json")
BIG_MAX = 250  # how many "big ones" to keep in the top feed

# Materiality weights for ranking the big feed.
FORM_WEIGHT = {"8-K": 5, "10-K": 4, "10-Q": 4, "N-2": 3, "424B2": 3, "424B3": 3, "424B5": 3, "SC 13D": 4, "SC 13D/A": 3}
HOT_8K_ITEMS = {"1.03": 10, "4.02": 10, "2.06": 8, "2.04": 8, "3.01": 8, "5.01": 7, "2.01": 6, "2.02": 5, "5.02": 4}


def accession_nodash(acc):
    return (acc or "").replace("-", "")


def filing_url(cik, accession, primary_doc):
    cik_int = str(int(cik))
    accn = accession_nodash(accession)
    if primary_doc:
        return "https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (cik_int, accn, primary_doc)
    return "https://www.sec.gov/Archives/edgar/data/%s/%s/%s-index.htm" % (cik_int, accn, accession)


def is_material(form, items):
    if form not in BIG_FORMS:
        return False
    if form == "8-K":
        codes = _item_codes(items)
        return any(c in MATERIAL_8K_ITEMS for c in codes)
    return True


def _item_codes(items):
    if not items:
        return []
    return re.findall(r"\d\.\d\d", items)


def rule_label(form, items, report_date, doc_desc):
    """Human, LLM-free label for the per-fund history list."""
    if form == "8-K":
        codes = _item_codes(items)
        phrases = [MATERIAL_8K_ITEMS[c] for c in codes if c in MATERIAL_8K_ITEMS]
        if phrases:
            return "Current report: " + "; ".join(phrases[:2])
        return "Current report (8-K)"
    base = FORM_LABELS.get(form, form)
    if form in ("10-Q", "10-K") and report_date:
        return "%s for period ending %s" % (base, report_date)
    if doc_desc and len(doc_desc) < 90:
        return "%s — %s" % (base, doc_desc)
    return base


def materiality_score(form, items, filing_date):
    score = FORM_WEIGHT.get(form, 1)
    if form == "8-K":
        for c in _item_codes(items):
            score += HOT_8K_ITEMS.get(c, 0)
    # recency: newer filings rank higher (days since epoch / 400 as a mild boost)
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d")
        score += max(0, (d - datetime(2015, 1, 1)).days) / 400.0
    except Exception:
        pass
    return round(score, 2)


def fetch_submissions(cik):
    url = "https://data.sec.gov/submissions/CIK%s.json" % cik
    return http_get(url, rate_limited=True, expect="json")


def parse_recent(sub):
    """Yield normalized filing dicts from a submissions payload's recent block."""
    recent = (sub or {}).get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    items = recent.get("items", [])
    descs = recent.get("primaryDocDescription", [])
    reps = recent.get("reportDate", [])
    n = len(forms)

    def at(a, i):
        return a[i] if i < len(a) else ""

    for i in range(n):
        yield {
            "form": at(forms, i),
            "date": at(dates, i),
            "accession": at(accns, i),
            "doc": at(docs, i),
            "items": at(items, i),
            "desc": at(descs, i),
            "report_date": at(reps, i),
        }


def llm_headline(llm, fund, f):
    """One-line factual gist for a material filing. Falls back to the rule label."""
    fallback = rule_label(f["form"], f["items"], f["report_date"], f["desc"])
    if not llm.available():
        return fallback, False
    # Pull a slice of the primary document for grounding (best-effort).
    text = ""
    url = filing_url(fund["cik"], f["accession"], f["doc"])
    if f["doc"] and f["doc"].lower().endswith((".htm", ".html", ".txt")):
        raw = http_get(url, rate_limited=True)
        if raw:
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text)[:6000]
    system = (
        "You write one-line, factual news headlines for SEC filings by business "
        "development companies (BDCs). Be specific and neutral. No hype, no "
        "speculation, under 16 words, no trailing period. If numbers are present "
        "(NAV, NII, non-accruals, dividend, leverage), lead with the concrete fact."
    )
    prompt = (
        "Fund: %s (%s)\nForm: %s  Date: %s  Items: %s\nDoc description: %s\n\n"
        "Filing text (may be truncated):\n%s\n\n"
        "Write the single best one-line headline capturing the gist."
        % (fund["name"], fund["ticker"], f["form"], f["date"], f["items"], f["desc"], text or "(not fetched)")
    )
    out = llm.complete(system, prompt, max_tokens=60)
    if out:
        return out.strip().strip('"').rstrip("."), True
    return fallback, False


def process_fund(fund, llm, seen, incremental):
    """Return (byfund_record, big_items, newly_seen_accessions)."""
    if not fund["cik"]:
        return None, [], []
    sub = fetch_submissions(fund["cik"])
    if not sub:
        log.warning("no submissions for %s (CIK %s)", fund["ticker"], fund["cik"])
        return None, [], []

    cut = cutoff_date()
    history = []
    big_items = []
    new_seen = []
    marquee = fund["ticker"] in MARQUEE

    for f in parse_recent(sub):
        if not f["form"] or not f["date"] or not f["accession"]:
            continue
        try:
            fdate = datetime.strptime(f["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if fdate < cut:
            continue

        url = filing_url(fund["cik"], f["accession"], f["doc"])
        # Per-fund history (all forms, rule-labelled — cheap).
        history.append({
            "form": f["form"],
            "date": f["date"],
            "label": rule_label(f["form"], f["items"], f["report_date"], f["desc"]),
            "category": _category(f["form"], f["items"]),
            "url": url,
            "material": is_material(f["form"], f["items"]),
        })

        # Big feed: material filings only. LLM-headline the unseen ones.
        if is_material(f["form"], f["items"]):
            already = f["accession"] in seen
            if incremental and already:
                continue  # nightly: skip anything we've already processed
            headline, used_llm = (rule_label(f["form"], f["items"], f["report_date"], f["desc"]), False)
            # Only spend an LLM call on genuinely notable, unseen filings.
            if not already:
                headline, used_llm = llm_headline(llm, fund, f)
                new_seen.append(f["accession"])
            big_items.append({
                "ticker": fund["ticker"],
                "name": fund["name"],
                "form": f["form"],
                "date": f["date"],
                "headline": headline,
                "category": _category(f["form"], f["items"]),
                "url": url,
                "score": materiality_score(f["form"], f["items"], f["date"]) + (2 if marquee else 0),
                "llm": used_llm,
            })

    history.sort(key=lambda x: x["date"], reverse=True)
    byfund = {
        "ticker": fund["ticker"],
        "name": fund["name"],
        "cik": fund["cik"],
        "updated": now_iso(),
        "filings": history,
    }
    return byfund, big_items, new_seen


def _category(form, items):
    if form in ("10-K", "10-Q"):
        return "Earnings"
    if form in ("424B2", "424B3", "424B5", "N-2"):
        return "Capital markets"
    if form == "8-K":
        codes = _item_codes(items)
        if "2.02" in codes:
            return "Earnings"
        if "5.02" in codes:
            return "Personnel"
        if any(c in ("1.03", "2.04", "2.06", "3.01", "4.02") for c in codes):
            return "Credit event"
        if any(c in ("1.01", "2.01", "2.03") for c in codes):
            return "M&A"
    if form in ("SC 13D", "SC 13D/A"):
        return "M&A"
    return "Other"


def run(mode):
    ensure_dirs()
    funds = load_funds()
    llm = LLM()
    state = read_json(STATE_PATH, {"last_run": None, "seen": {}})
    seen = state.get("seen", {})
    incremental = (mode == "incremental")

    # In incremental mode, always refresh the marquee funds even if seen, so the
    # top feed stays current; process everyone for genuinely new filings.
    prior_big = read_json(BIG_PATH, []) if incremental else []
    big_by_key = {(b["ticker"], b["url"]): b for b in prior_big}

    ok, fail = 0, 0
    for i, fund in enumerate(funds, 1):
        try:
            byfund, big_items, new_seen = process_fund(fund, llm, seen, incremental)
            if byfund is not None:
                atomic_write_json(os.path.join(BYFUND_DIR, "%s.json" % fund["ticker"]), byfund)
                ok += 1
            for b in big_items:
                big_by_key[(b["ticker"], b["url"])] = b
            for acc in new_seen:
                seen[acc] = True
            if i % 25 == 0:
                log.info("progress %d/%d funds (llm calls: %d)", i, len(funds), llm.calls)
        except Exception as e:
            fail += 1
            log.error("fund %s failed: %s", fund.get("ticker"), e)
            continue

    big = sorted(big_by_key.values(), key=lambda x: (x["score"], x["date"]), reverse=True)[:BIG_MAX]
    atomic_write_json(BIG_PATH, big)
    atomic_write_json(STATE_PATH, {"last_run": now_iso(), "seen": seen, "mode": mode})
    log.info("DONE mode=%s funds_ok=%d funds_fail=%d big=%d llm_calls=%d",
             mode, ok, fail, len(big), llm.calls)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["base", "incremental"], default="incremental")
    args = ap.parse_args()
    run(args.mode)
