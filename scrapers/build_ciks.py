"""
build_ciks.py — one-time helper. Fills each fund's SEC CIK into
data/universe/fund_directory.json by matching its ticker against the SEC's own
public ticker->CIK file. Safe to re-run: it only fills missing/blank CIKs and
writes a backup first.

Run it once:
    export SEC_USER_AGENT="Credit Canon (you@domain.com)"
    python scrapers/build_ciks.py

Then re-run the News pipeline in base mode.
"""

import os
import re
import json
import shutil

from common import log, http_get, read_json, atomic_write_json, DATA_DIR

DIR_PATH = os.path.join(DATA_DIR, "universe", "fund_directory.json")
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# Field names a CIK might already live under (checked before we look one up).
CIK_KEYS = ("cik", "cik_str", "CIK", "cikNumber", "cik_number", "sec_cik")


def _norm_ticker(t):
    return re.sub(r"[^A-Z0-9]", "", str(t or "").upper())


def load_sec_map():
    """Return {TICKER: '##########'} from the SEC's public file."""
    data = http_get(SEC_TICKERS, expect="json", retries=4)
    m = {}
    if not data:
        log.error("could not fetch SEC ticker map — check SEC_USER_AGENT / network")
        return m
    # File is {"0": {"cik_str": 1287750, "ticker": "ARCC", "title": "..."}, ...}
    rows = data.values() if isinstance(data, dict) else data
    for row in rows:
        try:
            tk = _norm_ticker(row.get("ticker"))
            cik = str(int(row.get("cik_str"))).zfill(10)
            if tk:
                m[tk] = cik
        except Exception:
            continue
    log.info("loaded %d ticker->CIK mappings from SEC", len(m))
    return m


def existing_cik(fund):
    for k in CIK_KEYS:
        v = fund.get(k)
        if v not in (None, "", 0, "0"):
            try:
                return str(int(str(v).strip().lstrip("CIK").strip())).zfill(10)
            except Exception:
                pass
    return None


def run():
    raw = read_json(DIR_PATH, None)
    if raw is None:
        log.error("could not read %s", DIR_PATH)
        return
    funds = raw.get("funds") if isinstance(raw, dict) else raw
    if not isinstance(funds, list):
        log.error("unexpected fund_directory shape")
        return

    sec = load_sec_map()
    if not sec:
        return

    filled, already, missing = 0, 0, []
    for f in funds:
        if existing_cik(f):
            f["cik"] = existing_cik(f)  # normalize into a consistent 'cik' field
            already += 1
            continue
        tk = _norm_ticker(f.get("ticker") or f.get("symbol"))
        cik = sec.get(tk)
        if cik:
            f["cik"] = cik
            filled += 1
        else:
            missing.append(f.get("ticker") or f.get("symbol") or "?")

    # backup, then write in place (same shape we read).
    try:
        shutil.copyfile(DIR_PATH, DIR_PATH + ".bak")
    except Exception as e:
        log.warning("backup failed (%s) — writing anyway", e)
    atomic_write_json(DIR_PATH, raw)

    log.info("CIKs: filled=%d already_present=%d still_missing=%d", filled, already, len(missing))
    if missing:
        log.info("no SEC ticker match for: %s", ", ".join(missing[:40]) + (" ..." if len(missing) > 40 else ""))
        log.info("(these are usually non-traded/private BDCs with no ticker on the SEC map;"
                 " they need a manual CIK, but the traded funds will now work.)")


if __name__ == "__main__":
    run()
