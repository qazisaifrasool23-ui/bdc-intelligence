"""
rewrite_headlines.py — Claude Code companion for News headline rewriting.

This script is designed to be invoked by Claude Code (not run standalone).
Claude Code reads this file, calls its functions to fetch + write data, and
provides the intelligence for the actual headline rewriting.

WORKFLOW:
    1. Claude Code calls list_pending() to find items that need rewriting
    2. For a batch (e.g. 20 items), calls fetch_pr_body() to get press release text
    3. Claude Code writes a sharp WSJ-style headline for each
    4. Claude Code calls save_headlines() to write back to data/news/{ticker}.json

See scripts/REWRITE_HEADLINES.md for the exact prompt to give Claude Code.
"""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path
from typing import List, Dict, Optional
import urllib.request, urllib.error

ROOT = Path(__file__).resolve().parent.parent
NEWS_DIR = ROOT / "data" / "news"

USER_AGENT = "BDC Intelligence Research qsaif2321@gmail.com"  # ← same as fetch_news.py
SEC_RATE_DELAY = 0.13
_last_call = 0.0


def _http_get(url: str, timeout: int = 25) -> Optional[str]:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < SEC_RATE_DELAY:
        time.sleep(SEC_RATE_DELAY - elapsed)
    _last_call = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code in (404, 403): return None
        print(f"  [http {e.code}] {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [http err] {e}", file=sys.stderr)
        return None


def _strip_html(html: str) -> str:
    """Aggressive HTML stripper — keep readable text only."""
    # Remove script/style entirely
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace common block-level closers with newline
    html = re.sub(r"</(p|div|tr|h[1-6]|li|br)>", "\n", html, flags=re.IGNORECASE)
    # Drop tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode HTML entities (basic set)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
                .replace("&apos;", "'").replace("&mdash;", "—").replace("&rsquo;", "'")
                .replace("&lsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"'))
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _find_press_release_doc(index_url: str) -> Optional[str]:
    """Given the filing index page URL, find the EX-99.1 press release doc URL."""
    html = _http_get(index_url)
    if not html: return None
    # Look for table rows like: <td>EX-99.1</td>...<td><a href="...">doc.htm</a></td>
    # or modern format with .htm/.txt exhibits
    # Match EX-99 (any subnumber) preferring .htm over .txt
    candidates = re.findall(
        r'<a[^>]+href="([^"]+\.(?:htm|html|txt))"[^>]*>[^<]*</a>[^<]*</td>\s*<td[^>]*>\s*EX-99',
        html, flags=re.IGNORECASE,
    )
    if not candidates:
        # Try reverse pattern: EX-99 column, then link
        rows = re.findall(
            r'<tr[^>]*>.*?EX-99[.\d]*.*?</tr>',
            html, flags=re.DOTALL | re.IGNORECASE,
        )
        for row in rows:
            m = re.search(r'href="([^"]+\.(?:htm|html|txt))"', row, flags=re.IGNORECASE)
            if m:
                candidates.append(m.group(1))
                break
    if not candidates:
        return None
    href = candidates[0]
    # Resolve relative
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.sec.gov" + href
    # Same dir as index
    base = index_url.rsplit("/", 1)[0] + "/"
    return base + href


def list_pending(limit: int = 20, only_ticker: Optional[str] = None) -> List[Dict]:
    """
    Return items needing a headline_ai. Each entry has:
        ticker, accession, date, category, title (raw), url, index_url
    Claude Code will then call fetch_pr_body() for each, write a headline,
    and call save_headlines() to persist.
    """
    pending = []
    files = sorted(NEWS_DIR.glob("*.json"))
    for fpath in files:
        if fpath.name.startswith("_"):
            continue
        if only_ticker and fpath.stem != only_ticker:
            continue
        try:
            data = json.load(open(fpath))
        except Exception:
            continue
        ticker = data.get("ticker", fpath.stem)
        for it in data.get("items", []):
            if it.get("headline_ai"):
                continue
            url = it.get("url", "")
            # Reconstruct index_url from primary doc URL
            # primary: https://www.sec.gov/Archives/edgar/data/{cik}/{accNoDash}/{doc}
            # index:   https://www.sec.gov/Archives/edgar/data/{cik}/{accNoDash}/{accession}-index.htm
            acc = it.get("accession", "")
            index_url = ""
            if url and acc:
                base = url.rsplit("/", 1)[0]
                index_url = f"{base}/{acc}-index.htm"
            pending.append({
                "ticker": ticker,
                "accession": acc,
                "date": it.get("date", ""),
                "category": it.get("category", ""),
                "title": it.get("title", ""),
                "url": url,
                "index_url": index_url,
            })
            if len(pending) >= limit:
                return pending
    return pending


def fetch_pr_body(index_url: str, max_chars: int = 6000) -> Dict:
    """
    Find and fetch the EX-99.1 press release for a filing.
    Returns: { 'found': bool, 'pr_url': str, 'text': str (trimmed), 'first_para': str }
    """
    pr_url = _find_press_release_doc(index_url)
    if not pr_url:
        return {"found": False, "pr_url": "", "text": "", "first_para": ""}
    raw = _http_get(pr_url)
    if not raw:
        return {"found": False, "pr_url": pr_url, "text": "", "first_para": ""}
    text = _strip_html(raw)
    # First paragraph heuristic: text up to first period followed by capital letter, capped at 400 chars
    fp = text[:400]
    m = re.search(r"\.\s+[A-Z]", text[:600])
    if m:
        fp = text[:m.start() + 1]
    fp = fp.strip()
    return {
        "found": True,
        "pr_url": pr_url,
        "text": text[:max_chars],
        "first_para": fp,
    }


def save_headlines(updates: List[Dict]) -> Dict:
    """
    Persist Claude-written headlines back to per-fund JSON files.
    updates = [{ticker, accession, headline_ai, snippet (optional)}, ...]
    Returns: {written: N, by_ticker: {...}, skipped: N}
    """
    by_ticker: Dict[str, List[Dict]] = {}
    for u in updates:
        by_ticker.setdefault(u["ticker"], []).append(u)

    written = 0
    skipped = 0
    summary: Dict[str, int] = {}
    for ticker, ups in by_ticker.items():
        fpath = NEWS_DIR / f"{ticker}.json"
        if not fpath.exists():
            skipped += len(ups)
            continue
        data = json.load(open(fpath))
        by_acc = {u["accession"]: u for u in ups if u.get("accession")}
        n = 0
        for it in data.get("items", []):
            u = by_acc.get(it.get("accession"))
            if not u: continue
            it["headline_ai"] = u.get("headline_ai", "").strip()
            if u.get("snippet"):
                it["snippet"] = u["snippet"].strip()
            n += 1
        if n:
            with open(fpath, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            written += n
            summary[ticker] = n
    return {"written": written, "by_ticker": summary, "skipped": skipped}


def stats() -> Dict:
    """Quick health check — total items vs. items with headline_ai set."""
    total = 0; with_ai = 0; by_cat: Dict[str, int] = {}
    for fpath in NEWS_DIR.glob("*.json"):
        if fpath.name.startswith("_"): continue
        try:
            data = json.load(open(fpath))
        except Exception:
            continue
        for it in data.get("items", []):
            total += 1
            if it.get("headline_ai"): with_ai += 1
            by_cat[it.get("category", "?")] = by_cat.get(it.get("category", "?"), 0) + 1
    return {"total": total, "with_headline_ai": with_ai, "pending": total - with_ai, "by_category": by_cat}


# Make functions easy to call from a Claude Code session
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["stats", "pending", "fetch"], help="What to do")
    p.add_argument("--ticker", help="Limit to one ticker")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--index-url", help="For 'fetch' command")
    args = p.parse_args()

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "pending":
        print(json.dumps(list_pending(args.limit, args.ticker), indent=2))
    elif args.cmd == "fetch":
        if not args.index_url:
            sys.exit("--index-url required")
        print(json.dumps(fetch_pr_body(args.index_url), indent=2))
