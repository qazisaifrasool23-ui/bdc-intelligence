"""
build_stats.py — compute the universe ground-truth stats the opinion verdict
uses. Cheap counts/AUM plus median non-accrual, PIK, yield and gate counts from
the timeseries. Cached to data/news/_universe_stats.json. Run in `base` and
occasionally (weekly is plenty); the nightly opinion job reads the cache.
"""

import os
import glob
import statistics
from common import log, ensure_dirs, load_funds, read_json, atomic_write_json, now_iso, DATA_DIR, NEWS_DIR

STATS_PATH = os.path.join(NEWS_DIR, "_universe_stats.json")


def run():
    ensure_dirs()
    funds = load_funds()
    ftype = {f["ticker"]: f["fund_type"] for f in funds}
    traded = sum(1 for f in funds if f["fund_type"] == "traded")

    aum = read_json(os.path.join(DATA_DIR, "aum_index.json"), {})
    total_aum = sum(v["net_assets_mn"] for v in (aum.get("funds", {}) or {}).values()
                    if isinstance(v, dict) and v.get("net_assets_mn"))

    na, pik, yld = [], [], []
    gates_active, gates_total = 0, 0
    ts_dir = os.path.join(DATA_DIR, "timeseries")
    for path in glob.glob(os.path.join(ts_dir, "*.json")):
        tk = os.path.splitext(os.path.basename(path))[0]
        d = read_json(path, None)
        if not isinstance(d, list) or not d:
            continue
        L = d[-1]
        try:
            v = L.get("na_pct_fv")
            if v is None:
                v = L.get("na_pct_cost")
            if v is not None:
                na.append(float(v))
            if L.get("pik_pct") is not None:
                pik.append(float(L["pik_pct"]))
            if L.get("weighted_avg_yield") is not None:
                yld.append(float(L["weighted_avg_yield"]))
            if ftype.get(tk, "") != "traded":
                gates_total += 1
                if L.get("redemption_gate_active"):
                    gates_active += 1
        except Exception:
            continue

    def med(a):
        return round(statistics.median(a), 2) if a else None

    stats = {
        "updated": now_iso(),
        "funds_total": len(funds),
        "funds_traded": traded,
        "funds_nontraded": len(funds) - traded,
        "aum_bn": round(total_aum / 1000, 1) if total_aum else None,
        "median_non_accrual": med(na),
        "avg_pik": round(sum(pik) / len(pik), 2) if pik else None,
        "median_yield": med(yld),
        "gates_active": gates_active,
        "gates_total": gates_total,
    }
    atomic_write_json(STATS_PATH, stats)
    log.info("universe stats: %s", stats)


if __name__ == "__main__":
    run()
