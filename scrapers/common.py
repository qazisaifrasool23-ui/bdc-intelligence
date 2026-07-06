"""
common.py — shared, defensive utilities for the Credit Canon news pipeline.

Design goals: never crash the whole run because one thing failed. Every network
call retries with backoff; every write is atomic; the LLM is optional and always
has a rule-based fallback. Nothing here raises to the top level under normal
failure modes — it logs and returns a safe default.
"""

import os
import re
import json
import time
import random
import logging
import tempfile
from datetime import datetime, timezone, timedelta

import requests

# ----------------------------------------------------------------------------- 
# Paths & constants
# -----------------------------------------------------------------------------

REPO_ROOT = os.environ.get("CC_REPO_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
DATA_DIR = os.path.join(REPO_ROOT, "data")
NEWS_DIR = os.path.join(DATA_DIR, "news")
PRESS_DIR = os.path.join(NEWS_DIR, "press")
BYFUND_DIR = os.path.join(PRESS_DIR, "by_fund")
OPINION_DIR = os.path.join(NEWS_DIR, "opinion")

# SEC requires a descriptive User-Agent with contact info. Override via env.
SEC_UA = os.environ.get("SEC_USER_AGENT", "Credit Canon research pipeline (contact: admin@creditcanon.com)")

# LLM model for headline/verdict generation. Haiku is fast + cheap for high volume.
LLM_MODEL = os.environ.get("CC_LLM_MODEL", "claude-haiku-4-5-20251001")
# Hard cap on LLM calls per run so a bad day can never produce a runaway bill.
LLM_CALL_CAP = int(os.environ.get("CC_LLM_CALL_CAP", "400"))

# How far back the per-fund filing history goes (24 quarters = 6 years).
HISTORY_YEARS = 6

# Marquee BDCs — the "must always be covered / refreshed" set. Finalized list of
# the largest and most systemically watched funds by AUM / market attention.
MARQUEE = [
    "ARCC", "OBDC", "FSK", "BXSL", "MAIN", "GBDC", "BCRED", "OBDE", "PSEC",
    "HTGC", "TSLX", "NMFC", "CGBD", "BBDC", "KBDC", "TCPC", "CSWC", "SLRC",
    "FDUS", "PFLT", "GSBD", "CCAP", "PNNT", "TRIN", "OCSL",
]

# Which SEC forms we treat as material "big ones" for the top section.
BIG_FORMS = {"10-K", "10-Q", "8-K", "N-2", "424B2", "424B3", "424B5", "SC 13D", "SC 13D/A"}

# 8-K item codes that are genuinely significant (SEC's own taxonomy).
MATERIAL_8K_ITEMS = {
    "1.01": "entered a material agreement",
    "1.02": "terminated a material agreement",
    "1.03": "entered bankruptcy or receivership",
    "2.01": "completed an acquisition or disposition",
    "2.02": "reported quarterly results",
    "2.03": "took on a material financial obligation",
    "2.04": "triggered an acceleration of an obligation",
    "2.06": "recorded a material impairment",
    "3.01": "faces delisting or a listing-standard issue",
    "3.03": "modified security holders' rights",
    "4.01": "changed its accounting firm",
    "4.02": "flagged prior financials as unreliable (restatement)",
    "5.01": "underwent a change in control",
    "5.02": "changed a director or senior officer",
    "5.03": "amended its charter or bylaws",
    "7.01": "issued a Regulation FD disclosure",
    "8.01": "disclosed a material event",
}

# Human labels for common forms (used when we don't LLM-summarize).
FORM_LABELS = {
    "10-K": "Annual report (10-K)",
    "10-Q": "Quarterly report (10-Q)",
    "8-K": "Current report (8-K)",
    "N-2": "Registration statement (N-2)",
    "424B2": "Prospectus supplement (offering)",
    "424B3": "Prospectus supplement (offering)",
    "424B5": "Prospectus supplement (offering)",
    "DEF 14A": "Proxy statement",
    "SC 13D": "Beneficial ownership (13D)",
    "SC 13D/A": "Beneficial ownership amendment (13D/A)",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("creditcanon")

# ----------------------------------------------------------------------------- 
# Filesystem helpers (atomic, never leaves a half-written file)
# -----------------------------------------------------------------------------

def ensure_dirs():
    for d in (DATA_DIR, NEWS_DIR, PRESS_DIR, BYFUND_DIR, OPINION_DIR):
        os.makedirs(d, exist_ok=True)


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_json(path, obj):
    """Write to a temp file in the same dir, then os.replace — never a partial file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        log.error("write failed for %s: %s", path, e)
        try:
            os.remove(tmp)
        except Exception:
            pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def cutoff_date(years=HISTORY_YEARS):
    return (datetime.now(timezone.utc) - timedelta(days=365 * years)).date()

# ----------------------------------------------------------------------------- 
# Robust HTTP
# -----------------------------------------------------------------------------

_last_sec_call = [0.0]


def _rate_limit(min_interval=0.15):
    """SEC allows ~10 req/s; we stay well under at ~6-7 req/s."""
    dt = time.time() - _last_sec_call[0]
    if dt < min_interval:
        time.sleep(min_interval - dt)
    _last_sec_call[0] = time.time()


def http_get(url, headers=None, timeout=30, retries=4, rate_limited=False, expect="text"):
    """GET with exponential backoff + jitter. Returns text/json/None; never raises."""
    hdrs = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries):
        try:
            if rate_limited:
                _rate_limit()
            r = requests.get(url, headers=hdrs, timeout=timeout)
            if r.status_code == 200:
                if expect == "json":
                    return r.json()
                return r.text
            if r.status_code in (403, 429) or r.status_code >= 500:
                wait = (2 ** attempt) + random.random()
                log.warning("HTTP %s on %s — retry in %.1fs", r.status_code, url, wait)
                time.sleep(wait)
                continue
            log.warning("HTTP %s on %s — giving up", r.status_code, url)
            return None
        except Exception as e:
            wait = (2 ** attempt) + random.random()
            log.warning("request error on %s: %s — retry in %.1fs", url, e, wait)
            time.sleep(wait)
    return None

# ----------------------------------------------------------------------------- 
# Fund universe / CIK loading
# -----------------------------------------------------------------------------

def _pad_cik(v):
    try:
        return str(int(str(v).strip().lstrip("CIK").strip())).zfill(10)
    except Exception:
        return None


def load_funds():
    """Return [{ticker, cik, name, fund_type}] from fund_directory.json, CIK zero-padded."""
    path = os.path.join(DATA_DIR, "universe", "fund_directory.json")
    raw = read_json(path, {})
    funds = raw.get("funds") if isinstance(raw, dict) else raw
    out = []
    for f in (funds or []):
        cik = None
        for key in ("cik", "cik_str", "CIK", "cikNumber", "cik_number"):
            if f.get(key) not in (None, ""):
                cik = _pad_cik(f.get(key))
                if cik:
                    break
        tk = f.get("ticker") or f.get("symbol")
        if not tk:
            continue
        out.append({
            "ticker": tk,
            "cik": cik,
            "name": f.get("name") or f.get("fund_name") or tk,
            "fund_type": f.get("fund_type") or "",
        })
    log.info("loaded %d funds (%d with CIK)", len(out), sum(1 for x in out if x["cik"]))
    return out

# ----------------------------------------------------------------------------- 
# LLM wrapper (optional, always falls back)
# -----------------------------------------------------------------------------

class LLM:
    def __init__(self):
        self.calls = 0
        self.client = None
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
                log.info("LLM enabled (%s)", LLM_MODEL)
            except Exception as e:
                log.warning("anthropic SDK unavailable (%s) — using rule-based fallback", e)
        else:
            log.info("no ANTHROPIC_API_KEY — using rule-based headlines/verdicts")

    def available(self):
        return self.client is not None and self.calls < LLM_CALL_CAP

    def complete(self, system, prompt, max_tokens=200):
        """Return text or None. Bounded by LLM_CALL_CAP; retries transient errors once."""
        if not self.available():
            return None
        for attempt in range(2):
            try:
                self.calls += 1
                msg = self.client.messages.create(
                    model=LLM_MODEL,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
                return ("".join(parts)).strip() or None
            except Exception as e:
                log.warning("LLM call failed (%s) attempt %d", e, attempt + 1)
                time.sleep(1.5 * (attempt + 1))
        return None
