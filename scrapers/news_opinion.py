"""
news_opinion.py — "News & opinion" feed with a data-alignment verdict.

Source: Google News RSS (free, stable, no key, no blocking). It surfaces the
headlines of LinkedIn/Medium/Bloomberg/trade press legitimately. Direct scraping
of those sites is fragile and against their terms, so we don't.

For each recent article (last 6 months) we ask the LLM whether the article's
claims about private credit / BDCs point in the SAME direction as Credit Canon's
own dataset, and attach a verdict ribbon: converges / diverges / mixed / unread.

IMPORTANT framing (baked into the prompt): the verdict is "consistent with vs.
diverges from OUR dataset" as an observation, and must name the point of
difference. It is never a verdict on the publication's credibility.

Output:
    data/news/opinion/index.json  -> [{title, source, url, published, verdict, note}]
    data/news/opinion/_state.json -> {last_run, seen: {url: true}}
"""

import os
import re
import json
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from common import (
    log, ensure_dirs, load_funds, http_get, read_json, atomic_write_json,
    now_iso, LLM, OPINION_DIR, DATA_DIR, MARQUEE,
)

STATE_PATH = os.path.join(OPINION_DIR, "_state.json")
INDEX_PATH = os.path.join(OPINION_DIR, "index.json")
STATS_PATH = os.path.join(os.path.dirname(OPINION_DIR), "_universe_stats.json")
MAX_ITEMS = 120
MONTHS_BACK = 6

QUERIES = [
    "private credit",
    "business development company BDC",
    "direct lending private credit",
    "non-traded BDC redemptions",
    "private credit non-accrual",
    "BDC NAV mark",
    "private credit default",
]


def rss_url(q):
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % quote_plus(q + " when:6m")


def parse_rss(xml_text):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        log.warning("rss parse error: %s", e)
        return items
    for it in root.iter("item"):
        def tx(tag):
            el = it.find(tag)
            return el.text if el is not None and el.text else ""
        title = tx("title")
        link = tx("link")
        pub = tx("pubDate")
        src_el = it.find("source")
        source = src_el.text if src_el is not None and src_el.text else ""
        if not title or not link:
            continue
        # strip trailing " - Source" that Google appends to titles
        clean = re.sub(r"\s+-\s+[^-]+$", "", title).strip()
        items.append({"title": clean or title, "url": link, "source": source, "pub": pub})
    return items


def within_window(pub):
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return True  # keep if unparseable rather than silently drop
    return dt >= datetime.now(timezone.utc) - timedelta(days=30 * MONTHS_BACK)


def load_stats():
    """Ground-truth facts for the LLM. Cheap counts/AUM always; deep stats if cached."""
    s = read_json(STATS_PATH, {})
    if not s:
        funds = load_funds()
        traded = sum(1 for f in funds if f["fund_type"] == "traded")
        aum = read_json(os.path.join(DATA_DIR, "aum_index.json"), {})
        total_aum = 0
        for v in (aum.get("funds", {}) or {}).values():
            if isinstance(v, dict) and v.get("net_assets_mn"):
                total_aum += v["net_assets_mn"]
        s = {
            "funds_total": len(funds),
            "funds_traded": traded,
            "funds_nontraded": len(funds) - traded,
            "aum_bn": round(total_aum / 1000, 1) if total_aum else None,
        }
    return s


def stats_text(s):
    lines = ["Credit Canon dataset (universe-scale, sourced from SEC filings):"]
    if s.get("funds_total"):
        lines.append("- Coverage: %s BDCs (%s traded, %s non-traded)."
                     % (s.get("funds_total"), s.get("funds_traded"), s.get("funds_nontraded")))
    if s.get("aum_bn"):
        lines.append("- Aggregate net assets: about $%sB." % s.get("aum_bn"))
    for k, label in (("median_non_accrual", "median non-accrual rate"),
                     ("avg_pik", "average PIK share of income"),
                     ("median_yield", "median portfolio yield"),
                     ("gates_active", "non-traded BDCs currently gating redemptions"),
                     ("gates_total", "non-traded BDCs tracked for gate status")):
        if s.get(k) is not None:
            lines.append("- %s: %s." % (label, s[k]))
    return "\n".join(lines)


def fetch_article_text(url):
    raw = http_get(url, timeout=20, retries=2)
    if not raw:
        return ""
    txt = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", raw)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt[:5000]


def verdict_for(llm, article, ground_truth):
    """Return (verdict, note). verdict in converges/diverges/mixed/unread."""
    if not llm.available():
        return "unread", "Awaiting analysis."
    body = fetch_article_text(article["url"])
    system = (
        "You compare a news/opinion article about private credit or BDCs against a "
        "reference dataset. Decide whether the article's directional claims are "
        "CONSISTENT WITH or DIVERGE FROM the dataset. This is a statement about "
        "agreement with our data, never a judgment of the publication's credibility. "
        "Reply as strict JSON: {\"verdict\":\"converges|diverges|mixed|unclear\","
        "\"note\":\"<=18 words naming the specific point of agreement or difference\"}."
    )
    prompt = (
        "%s\n\nArticle title: %s\nSource: %s\n\nArticle text (may be truncated or "
        "just a snippet):\n%s\n\nReturn only the JSON."
        % (ground_truth, article["title"], article["source"], body or "(could not fetch full text; judge from the title)")
    )
    out = llm.complete(system, prompt, max_tokens=120)
    if not out:
        return "unread", "Analysis unavailable."
    try:
        m = re.search(r"\{.*\}", out, re.S)
        obj = json.loads(m.group(0)) if m else {}
        v = str(obj.get("verdict", "unclear")).lower().strip()
        if v not in ("converges", "diverges", "mixed", "unclear"):
            v = "unclear"
        note = str(obj.get("note", "")).strip()[:160] or "\u2014"
        return v, note
    except Exception:
        return "unclear", "Could not parse analysis."


def run():
    ensure_dirs()
    llm = LLM()
    state = read_json(STATE_PATH, {"last_run": None, "seen": {}})
    seen = state.get("seen", {})
    prior = read_json(INDEX_PATH, [])
    by_url = {a["url"]: a for a in prior}

    ground = stats_text(load_stats())

    # Gather candidate articles across all queries (+ a few marquee-name queries).
    candidates = {}
    for q in QUERIES + ["%s BDC" % t for t in MARQUEE[:6]]:
        xml_text = http_get(rss_url(q), timeout=25, retries=3)
        if not xml_text:
            continue
        for it in parse_rss(xml_text):
            if not within_window(it["pub"]):
                continue
            candidates[it["url"]] = it
    log.info("collected %d candidate articles", len(candidates))

    processed = 0
    for url, it in candidates.items():
        if url in seen:
            continue
        try:
            v, note = verdict_for(llm, it, ground)
            pub_iso = it["pub"]
            try:
                pub_iso = parsedate_to_datetime(it["pub"]).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
            by_url[url] = {
                "title": it["title"],
                "source": it["source"],
                "url": url,
                "published": pub_iso,
                "verdict": v,
                "note": note,
                "checked": now_iso(),
            }
            seen[url] = True
            processed += 1
        except Exception as e:
            log.error("article failed (%s): %s", url, e)
            continue

    # Keep the most recent MAX_ITEMS; re-verdict of old items is skipped (seen).
    items = sorted(by_url.values(), key=lambda a: a.get("published", ""), reverse=True)[:MAX_ITEMS]
    atomic_write_json(INDEX_PATH, items)
    atomic_write_json(STATE_PATH, {"last_run": now_iso(), "seen": seen})
    log.info("DONE opinion: kept=%d new=%d llm_calls=%d", len(items), processed, llm.calls)


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
