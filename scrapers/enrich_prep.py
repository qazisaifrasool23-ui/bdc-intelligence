"""
enrich_prep.py — STEP 1 of the free Claude Code enrichment.

Finds filings that don't yet have a smart headline + credit signal, fetches the
relevant text from each (MD&A section for 10-K/10-Q, item text for 8-K), and
writes a bounded work queue to data/news/press/_enrich_queue.json.

You then open Claude Code and follow CLAUDE_ENRICH.md, which reads that queue,
writes _enrich_results.json, and enrich_apply.py merges it back in.

Run in batches (resumable — already-enriched filings are skipped):
    python scrapers/enrich_prep.py --limit 60
"""

import os
import re
import glob
import json
import argparse

from common import (
    log, ensure_dirs, http_get, read_json, atomic_write_json, PRESS_DIR, BYFUND_DIR,
)

BIG_PATH = os.path.join(PRESS_DIR, "big.json")
QUEUE_PATH = os.path.join(PRESS_DIR, "_enrich_queue.json")
EXCERPT_CHARS = 9000


def strip_html(raw):
    t = re.sub(r"(?is)<(script|style|table).*?</\1>", " ", raw)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&#\d+;|&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def excerpt_for(url, form):
    """Fetch the filing doc and return the most signal-bearing text slice."""
    raw = http_get(url, rate_limited=True)
    if not raw:
        return ""
    text = strip_html(raw)
    if not text:
        return ""
    # For 10-K/10-Q, jump to Management's Discussion & Analysis if present.
    if form in ("10-K", "10-Q"):
        m = re.search(r"management.?s discussion and analysis", text, re.I)
        if m:
            start = max(0, m.start())
            return text[start:start + EXCERPT_CHARS]
    # Otherwise (8-K etc.) the item text is near the top.
    return text[:EXCERPT_CHARS]


def collect_targets():
    """De-duplicated list of filings lacking a signal, big.json first."""
    seen, targets = set(), []

    def add(f):
        url = f.get("url")
        if not url or url in seen:
            return
        if f.get("signal"):  # already enriched
            seen.add(url)
            return
        seen.add(url)
        targets.append({
            "id": url, "ticker": f.get("ticker", ""), "name": f.get("name", ""),
            "form": f.get("form", ""), "date": f.get("date", ""), "url": url,
        })

    for f in read_json(BIG_PATH, []):
        add(f)
    for path in sorted(glob.glob(os.path.join(BYFUND_DIR, "*.json"))):
        d = read_json(path, {})
        for f in d.get("filings", []):
            f.setdefault("ticker", d.get("ticker", ""))
            f.setdefault("name", d.get("name", ""))
            add(f)
    return targets


def run(limit):
    ensure_dirs()
    targets = collect_targets()
    log.info("%d filings still need enrichment", len(targets))
    if not targets:
        atomic_write_json(QUEUE_PATH, [])
        log.info("nothing left to enrich — you're done.")
        return
    batch = targets[:limit]
    for i, t in enumerate(batch, 1):
        t["excerpt"] = excerpt_for(t["url"], t["form"])
        if i % 10 == 0:
            log.info("fetched %d/%d excerpts", i, len(batch))
    atomic_write_json(QUEUE_PATH, batch)
    log.info("wrote %d filings to %s — now run Claude Code with CLAUDE_ENRICH.md",
             len(batch), QUEUE_PATH)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="filings per batch")
    args = ap.parse_args()
    run(args.limit)
