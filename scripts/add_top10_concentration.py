#!/usr/bin/env python3
"""Compute per-snapshot top-1/5/10 borrower concentration from SOI data and
write the results back into the timeseries quarter-rows.

SOI files are read-only. For each SOI snapshot, holdings are grouped by
company_name (summing fair_value_mn), sorted descending, and the top 1/5/10
company fair values are divided by the snapshot denominator
(total_fair_value_mn if > 0, else sum of all holdings' fair_value_mn).

Snapshots are matched to timeseries rows by exact period_end string equality.
Timeseries rows with no matching snapshot get null for all three fields.
"""

import json
import os
import glob
import shutil

TS_DIR = os.path.expanduser("~/Documents/bdc-intelligence/data/timeseries")
SOI_DIR = os.path.expanduser("~/Documents/bdc-intelligence/data/soi")
BACKUP_DIR = os.path.join(TS_DIR, "_backups", "pre_top10_concentration")

FIELDS = ["top_1_concentration_pct", "top_5_concentration_pct", "top_10_concentration_pct"]
NULL_VALS = {f: None for f in FIELDS}


def as_number(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def pct(value, denom):
    """Return rounded pct or None if anomalous (<0 or >100)."""
    p = round(value / denom * 100, 2)
    if p < 0 or p > 100:
        return None, True  # anomaly
    return p, False


def compute_snapshot(snap):
    """Return (vals_dict, top10_reason_or_None, n_holdings).

    top10_reason is one of: None (computed ok), 'bad_denominator',
    'few_holdings', 'anomaly'.
    """
    holdings = snap.get("holdings")
    if not isinstance(holdings, list):
        holdings = []
    n_holdings = len(holdings)

    # Group by company_name, summing fair_value (null/missing -> 0).
    totals = {}
    all_fv_sum = 0.0
    for h in holdings:
        if not isinstance(h, dict):
            continue
        fv = as_number(h.get("fair_value_mn")) or 0.0
        all_fv_sum += fv
        name = h.get("company_name")
        if name is None or (isinstance(name, str) and name.strip() == ""):
            continue
        totals[name] = totals.get(name, 0.0) + fv

    # Denominator.
    denom = as_number(snap.get("total_fair_value_mn"))
    if denom is None or denom <= 0:
        denom = all_fv_sum
    if denom is None or denom <= 0:
        return dict(NULL_VALS), "bad_denominator", n_holdings

    sorted_fv = sorted(totals.values(), reverse=True)

    vals = dict(NULL_VALS)
    anomaly = False

    # top_1 and top_5: compute "if possible" (any companies present).
    if sorted_fv:
        v1, a1 = pct(sum(sorted_fv[:1]), denom)
        v5, a5 = pct(sum(sorted_fv[:5]), denom)
        vals["top_1_concentration_pct"] = v1
        vals["top_5_concentration_pct"] = v5
        anomaly = anomaly or a1 or a5

    # top_10: only when snapshot has >= 10 holdings.
    top10_reason = None
    if n_holdings < 10:
        top10_reason = "few_holdings"
    else:
        v10, a10 = pct(sum(sorted_fv[:10]), denom)
        vals["top_10_concentration_pct"] = v10
        if a10:
            top10_reason = "anomaly"

    return vals, top10_reason, n_holdings


def insert_fields(row, vals):
    """Rebuild row with the three concentration keys positioned after
    num_portfolio_companies, else after asset_coverage_ratio, else appended.
    Existing concentration keys are dropped and re-inserted at that anchor."""
    if "num_portfolio_companies" in row:
        anchor = "num_portfolio_companies"
    elif "asset_coverage_ratio" in row:
        anchor = "asset_coverage_ratio"
    else:
        anchor = None

    new = {}
    for k, v in row.items():
        if k in FIELDS:
            continue  # drop existing; re-added at anchor
        new[k] = v
        if anchor is not None and k == anchor:
            for f in FIELDS:
                new[f] = vals[f]
    if anchor is None:
        for f in FIELDS:
            new[f] = vals[f]
    return new


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # --- Build SOI map: ticker -> {period_end: (vals, reason, n_holdings)} ---
    soi_map = {}
    soi_files_read = 0
    for path in sorted(glob.glob(os.path.join(SOI_DIR, "*.json"))):
        ticker = os.path.splitext(os.path.basename(path))[0]
        if ticker.startswith("_"):  # _index.json etc.
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        soi_files_read += 1
        snaps = data.get("snapshots") if isinstance(data, dict) else None
        if not isinstance(snaps, list):
            continue
        per_period = {}
        for snap in snaps:
            if not isinstance(snap, dict):
                continue
            pe = snap.get("period_end")
            if pe is None:
                continue
            per_period[pe] = compute_snapshot(snap)
        if per_period:
            soi_map[ticker] = per_period

    # --- Process timeseries files ---
    ts_files = sorted(glob.glob(os.path.join(TS_DIR, "*.json")))

    processed = 0
    rows_scanned = 0
    top10_computed = 0
    reasons = {
        "no_soi_file": 0,
        "no_snapshot": 0,
        "few_holdings": 0,
        "bad_denominator": 0,
        "anomaly": 0,
    }
    backups_made = 0
    backups_existing = 0
    unmatched_soi_snapshots = 0
    arcc_report = None

    for path in ts_files:
        ticker = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception:
            continue
        if not isinstance(rows, list) or len(rows) == 0:
            continue

        soi_periods = soi_map.get(ticker)
        ts_periods = {r.get("period_end") for r in rows if isinstance(r, dict)}

        # Log SOI snapshots that match no timeseries row for this ticker.
        if soi_periods:
            for pe in soi_periods:
                if pe not in ts_periods:
                    unmatched_soi_snapshots += 1

        # Backup before overwrite.
        backup_path = os.path.join(BACKUP_DIR, f"{ticker}.json")
        if os.path.exists(backup_path):
            backups_existing += 1
        else:
            shutil.copy2(path, backup_path)
            backups_made += 1

        new_rows = []
        for row in rows:
            rows_scanned += 1
            if not isinstance(row, dict):
                new_rows.append(row)
                continue

            pe = row.get("period_end")
            if soi_periods is None:
                vals = dict(NULL_VALS)
                reasons["no_soi_file"] += 1
            elif pe not in soi_periods:
                vals = dict(NULL_VALS)
                reasons["no_snapshot"] += 1
            else:
                vals, top10_reason, _n = soi_periods[pe]
                if vals["top_10_concentration_pct"] is not None:
                    top10_computed += 1
                elif top10_reason in reasons:
                    reasons[top10_reason] += 1

            new_rows.append(insert_fields(row, vals))

        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_rows, f, indent=2, ensure_ascii=False)
        processed += 1

        if ticker == "ARCC":
            dict_rows = [r for r in new_rows if isinstance(r, dict)]
            if dict_rows:
                latest = max(dict_rows, key=lambda r: r.get("quarter") or "")
                pe = latest.get("period_end")
                nh = None
                if soi_periods and pe in soi_periods:
                    nh = soi_periods[pe][2]
                arcc_report = {
                    "quarter": latest.get("quarter"),
                    "period_end": pe,
                    "top_1": latest.get("top_1_concentration_pct"),
                    "top_5": latest.get("top_5_concentration_pct"),
                    "top_10": latest.get("top_10_concentration_pct"),
                    "n_holdings": nh,
                }

    null_total = sum(reasons.values())

    print("\n" + "=" * 60)
    print("SUMMARY — top-N borrower concentration")
    print("=" * 60)
    print(f"Timeseries files processed:   {processed}")
    print(f"SOI files read:               {soi_files_read}")
    print(f"Total quarter-rows scanned:   {rows_scanned}")
    print(f"Rows top_10 computed:         {top10_computed}")
    print(f"Rows top_10 null:             {null_total}")
    print(f"    no SOI file for ticker:   {reasons['no_soi_file']}")
    print(f"    no matching snapshot:     {reasons['no_snapshot']}")
    print(f"    <10 holdings:             {reasons['few_holdings']}")
    print(f"    bad denominator:          {reasons['bad_denominator']}")
    print(f"    anomaly (<0 / >100):      {reasons['anomaly']}")
    print(f"SOI snapshots w/o ts match:   {unmatched_soi_snapshots} (logged, skipped)")
    print(f"Backups created:              {backups_made}")
    print(f"Backups already existed:      {backups_existing}")

    print("\nARCC most recent quarter:")
    if arcc_report is None:
        print("    ARCC.json not found.")
    else:
        print(f"    quarter:                  {arcc_report['quarter']} ({arcc_report['period_end']})")
        print(f"    holdings that quarter:    {arcc_report['n_holdings']}")
        print(f"    top_1_concentration_pct:  {arcc_report['top_1']}")
        print(f"    top_5_concentration_pct:  {arcc_report['top_5']}")
        print(f"    top_10_concentration_pct: {arcc_report['top_10']}")


if __name__ == "__main__":
    main()
