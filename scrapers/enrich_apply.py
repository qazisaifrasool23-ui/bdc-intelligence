"""
enrich_apply.py — STEP 3 of the free Claude Code enrichment.

Reads data/news/press/_enrich_results.json (written by Claude Code) and merges
each filing's smart headline, signal (clean/watch/negative) and signal_note into
big.json and the by_fund files. Then clears the queue so the next prep batch
picks up where you left off.

    python scrapers/enrich_apply.py
"""

import os
import glob
import json

from common import log, ensure_dirs, read_json, atomic_write_json, PRESS_DIR, BYFUND_DIR

BIG_PATH = os.path.join(PRESS_DIR, "big.json")
QUEUE_PATH = os.path.join(PRESS_DIR, "_enrich_queue.json")
RESULTS_PATH = os.path.join(PRESS_DIR, "_enrich_results.json")

VALID = {"clean", "watch", "negative"}


def normalize_results(raw):
    """Accept either {url:{...}} or [{id/url:...}]. Return {url: fields}."""
    out = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = [((r.get("id") or r.get("url")), r) for r in raw]
    else:
        return out
    for url, r in items:
        if not url or not isinstance(r, dict):
            continue
        sig = str(r.get("signal", "")).lower().strip()
        out[url] = {
            "headline": (r.get("headline") or "").strip(),
            "signal": sig if sig in VALID else None,
            "signal_note": (r.get("signal_note") or "").strip(),
        }
    return out


def apply_to(filings, res):
    n = 0
    for f in filings:
        r = res.get(f.get("url"))
        if not r:
            continue
        if r["headline"]:
            f["headline"] = r["headline"]
        if r["signal"]:
            f["signal"] = r["signal"]
        if r["signal_note"]:
            f["signal_note"] = r["signal_note"]
        n += 1
    return n


def run():
    ensure_dirs()
    res = normalize_results(read_json(RESULTS_PATH, None))
    if not res:
        log.error("no results in %s — run Claude Code (CLAUDE_ENRICH.md) first", RESULTS_PATH)
        return

    big = read_json(BIG_PATH, [])
    nb = apply_to(big, res)
    if nb:
        atomic_write_json(BIG_PATH, big)

    nf = 0
    for path in glob.glob(os.path.join(BYFUND_DIR, "*.json")):
        d = read_json(path, {})
        c = apply_to(d.get("filings", []), res)
        if c:
            atomic_write_json(path, d)
            nf += c

    # clear the two work files so the next prep batch is clean
    atomic_write_json(QUEUE_PATH, [])
    atomic_write_json(RESULTS_PATH, {})
    log.info("applied %d enrichments (big=%d, by_fund=%d). Run enrich_prep.py again for the next batch.",
             len(res), nb, nf)


if __name__ == "__main__":
    run()
