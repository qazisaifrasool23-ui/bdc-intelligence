"""
news_opinion.py — "News & opinion" feed.

Primary source: GDELT Doc API (free, no key, built for server-side access and far
more reliable from datacenter IPs than Google News RSS). Google News RSS is kept
as a fallback. Collection needs no LLM; if ANTHROPIC_API_KEY is set, each article
also gets a converges/diverges verdict vs. our dataset, otherwise it's stored
plain for a clean press feed.
"""

import os
import re
import json
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, quote
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
    "private credit", "business development company BDC", "direct lending",
    "non-traded BDC redemptions", "private credit default", "BDC dividend",
]
BROWSER_UA = "Mozilla/5.0 (compatible; CreditCanonBot/1.0; +https://creditcanon.com)"


def gdelt_url(q):
    phrase = '"%s"' % q if " " in q else q
    return ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s"
            "&mode=artlist&maxrecords=75&format=json&timespan=%dmonths&sort=datedesc"
            % (quote(phrase + " sourcelang:english"), MONTHS_BACK))


def parse_gdelt(js):
    items = []
    arts = (js or {}).get("articles", []) if isinstance(js, dict) else []
    for a in arts:
        title, url = a.get("title"), a.get("url")
        if not title or not url:
            continue
        items.append({"title": title.strip(), "url": url,
                      "source": a.get("domain", ""), "pub": a.get("seendate", ""), "fmt": "gdelt"})
    return items


def rss_url(q):
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % quote_plus(q + " when:6m")


def parse_rss(xml_text):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items
    for it in root.iter("item"):
        def tx(tag):
            el = it.find(tag)
            return el.text if el is not None and el.text else ""
        title, link, pub = tx("title"), tx("link"), tx("pubDate")
        src_el = it.find("source")
        source = src_el.text if src_el is not None and src_el.text else ""
        if not title or not link:
            continue
        clean = re.sub(r"\s+-\s+[^-]+$", "", title).strip()
        items.append({"title": clean or title, "url": link, "source": source, "pub": pub, "fmt": "rss"})
    return items


def to_iso(pub, fmt):
    try:
        if fmt == "gdelt":
            return datetime.strptime(pub[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).isoformat()
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def within_window(iso):
    if not iso:
        return True
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=30 * MONTHS_BACK)


def load_stats():
    s = read_json(STATS_PATH, {})
    if not s:
        funds = load_funds()
        traded = sum(1 for f in funds if f["fund_type"] == "traded")
        aum = read_json(os.path.join(DATA_DIR, "aum_index.json"), {})
        total = sum(v["net_assets_mn"] for v in (aum.get("funds", {}) or {}).values()
                    if isinstance(v, dict) and v.get("net_assets_mn"))
        s = {"funds_total": len(funds), "funds_traded": traded,
             "funds_nontraded": len(funds) - traded, "aum_bn": round(total / 1000, 1) if total else None}
    return s


def stats_text(s):
    lines = ["Credit Canon dataset (universe-scale, from SEC filings):"]
    if s.get("funds_total"):
        lines.append("- Coverage: %s BDCs (%s traded, %s non-traded)."
                     % (s.get("funds_total"), s.get("funds_traded"), s.get("funds_nontraded")))
    if s.get("aum_bn"):
        lines.append("- Aggregate net assets: about $%sB." % s.get("aum_bn"))
    for k, label in (("median_non_accrual", "median non-accrual rate"),
                     ("avg_pik", "average PIK share of income"),
                     ("median_yield", "median portfolio yield"),
                     ("gates_active", "non-traded BDCs currently gating redemptions")):
        if s.get(k) is not None:
            lines.append("- %s: %s." % (label, s[k]))
    return "\n".join(lines)


def verdict_for(llm, article, ground_truth):
    if not llm.available():
        return "unread", ""
    body = ""
    raw = http_get(article["url"], timeout=20, retries=2, headers={"User-Agent": BROWSER_UA})
    if raw:
        body = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", raw)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body)[:5000]
    system = ("You compare a news/opinion article about private credit or BDCs against a reference "
              "dataset. Decide whether the article's directional claims are CONSISTENT WITH or DIVERGE "
              "FROM the dataset. About agreement with our data, never a judgment of the publication. "
              "Reply strict JSON: {\"verdict\":\"converges|diverges|mixed|unclear\",\"note\":\"<=18 words\"}.")
    prompt = ("%s\n\nArticle title: %s\nSource: %s\n\nArticle text (may be truncated):\n%s\n\nReturn only the JSON."
              % (ground_truth, article["title"], article["source"], body or "(title only)"))
    out = llm.complete(system, prompt, max_tokens=120)
    if not out:
        return "unread", ""
    try:
        m = re.search(r"\{.*\}", out, re.S)
        obj = json.loads(m.group(0)) if m else {}
        v = str(obj.get("verdict", "unclear")).lower().strip()
        if v not in ("converges", "diverges", "mixed", "unclear"):
            v = "unclear"
        return v, str(obj.get("note", "")).strip()[:160]
    except Exception:
        return "unclear", ""


def collect():
    cand = {}
    queries = QUERIES + ["%s BDC" % t for t in MARQUEE[:6]]
    gd_hits = 0
    for q in queries:
        js = http_get(gdelt_url(q), timeout=30, retries=3, expect="json", headers={"User-Agent": BROWSER_UA})
        for it in parse_gdelt(js):
            it["published"] = to_iso(it["pub"], "gdelt")
            if within_window(it["published"]):
                cand[it["url"]] = it
                gd_hits += 1
    log.info("GDELT returned %d articles", gd_hits)
    if gd_hits < 20:
        for q in QUERIES:
            xml_text = http_get(rss_url(q), timeout=25, retries=2, headers={"User-Agent": BROWSER_UA})
            if not xml_text:
                continue
            for it in parse_rss(xml_text):
                it["published"] = to_iso(it["pub"], "rss")
                if within_window(it["published"]):
                    cand.setdefault(it["url"], it)
    return cand


def run():
    ensure_dirs()
    llm = LLM()
    state = read_json(STATE_PATH, {"last_run": None, "seen": {}})
    seen = state.get("seen", {})
    prior = read_json(INDEX_PATH, [])
    by_url = {a["url"]: a for a in prior}
    ground = stats_text(load_stats())

    cand = collect()
    log.info("collected %d unique candidate articles", len(cand))

    processed = 0
    for url, it in cand.items():
        if url in seen:
            continue
        try:
            v, note = verdict_for(llm, it, ground)
            by_url[url] = {"title": it["title"], "source": it["source"], "url": url,
                           "published": it.get("published", ""), "verdict": v, "note": note, "checked": now_iso()}
            seen[url] = True
            processed += 1
        except Exception as e:
            log.error("article failed (%s): %s", url, e)

    items = sorted(by_url.values(), key=lambda a: a.get("published", ""), reverse=True)[:MAX_ITEMS]
    atomic_write_json(INDEX_PATH, items)
    atomic_write_json(STATE_PATH, {"last_run": now_iso(), "seen": seen})
    log.info("DONE opinion: kept=%d new=%d llm_calls=%d", len(items), processed, llm.calls)


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
