#!/usr/bin/env python3
"""Add regulatory asset_coverage_ratio to every timeseries quarter-row.

Formula: (total_assets_mn - total_liabilities_mn + total_debt_mn) / total_debt_mn
Field is set to null (not omitted) when inputs are missing/non-numeric,
total_debt_mn <= 0, or the computed ratio is < 0 or > 20 (data anomaly).
Backs up each original file before overwriting.
"""

import json
import os
import shutil
import glob

TS_DIR = os.path.expanduser("~/Documents/bdc-intelligence/data/timeseries")
BACKUP_DIR = os.path.join(TS_DIR, "_backups", "pre_asset_coverage")

# Anomaly bounds (regulatory range is ~1.5x-3x; allow slack, reject clear noise)
MIN_RATIO = 0.0
MAX_RATIO = 20.0


def as_number(x):
    """Return float(x) if x is a real number, else None."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def compute(row):
    """Return (value_or_None, reason).

    reason is one of: 'ok', 'missing', 'nonpositive_debt', 'anomaly'.
    """
    ta = as_number(row.get("total_assets_mn"))
    tl = as_number(row.get("total_liabilities_mn"))
    td = as_number(row.get("total_debt_mn"))

    if ta is None or tl is None or td is None:
        return None, "missing"
    if td <= 0:
        return None, "nonpositive_debt"

    ratio = (ta - tl + td) / td
    if ratio < MIN_RATIO or ratio > MAX_RATIO:
        return None, "anomaly"
    return round(ratio, 3), "ok"


def insert_field(row, value):
    """Return a new dict with asset_coverage_ratio positioned immediately
    after total_debt_mn (or appended if that key is absent), preserving
    all other keys and their order."""
    new = {}
    inserted = False
    for k, v in row.items():
        new[k] = v
        if k == "total_debt_mn":
            new["asset_coverage_ratio"] = value
            inserted = True
    if not inserted:
        new["asset_coverage_ratio"] = value
    return new


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)

    files = sorted(glob.glob(os.path.join(TS_DIR, "*.json")))

    processed = 0
    skipped = []  # (ticker, reason)
    rows_scanned = 0
    rows_computed = 0
    reason_counts = {"missing": 0, "nonpositive_debt": 0, "anomaly": 0}
    backups_made = 0
    backups_existing = []
    arcc_latest = None

    for path in files:
        ticker = os.path.splitext(os.path.basename(path))[0]

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            skipped.append((ticker, f"unreadable JSON: {e}"))
            continue

        if not isinstance(data, list):
            skipped.append((ticker, f"top-level is {type(data).__name__}, not list"))
            continue
        if len(data) == 0:
            skipped.append((ticker, "empty list"))
            continue

        # Backup before overwrite.
        backup_path = os.path.join(BACKUP_DIR, f"{ticker}.json")
        if os.path.exists(backup_path):
            backups_existing.append(ticker)
            print(f"[backup] {ticker}: backup already exists, not clobbering; still updating timeseries.")
        else:
            shutil.copy2(path, backup_path)
            backups_made += 1

        new_rows = []
        for row in data:
            rows_scanned += 1
            if not isinstance(row, dict):
                # Preserve non-dict entries untouched.
                new_rows.append(row)
                continue
            value, reason = compute(row)
            if reason == "ok":
                rows_computed += 1
            else:
                reason_counts[reason] += 1
            new_rows.append(insert_field(row, value))

        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_rows, f, indent=2, ensure_ascii=False)
        processed += 1

        if ticker == "ARCC":
            # Most recent quarter = row with max 'quarter' string, fallback last.
            dict_rows = [r for r in new_rows if isinstance(r, dict)]
            if dict_rows:
                try:
                    latest = max(dict_rows, key=lambda r: r.get("quarter") or "")
                except Exception:
                    latest = dict_rows[-1]
                arcc_latest = latest

    null_total = sum(reason_counts.values())

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files processed:            {processed}")
    print(f"Backups created:            {backups_made}")
    print(f"Backups already existed:    {len(backups_existing)}"
          + (f" ({', '.join(backups_existing)})" if backups_existing else ""))
    print(f"Files skipped:              {len(skipped)}")
    for t, r in skipped:
        print(f"    - {t}: {r}")
    print(f"Total quarter-rows scanned: {rows_scanned}")
    print(f"Rows field computed:        {rows_computed}")
    print(f"Rows field set to null:     {null_total}")
    print(f"    missing inputs:         {reason_counts['missing']}")
    print(f"    non-positive debt:      {reason_counts['nonpositive_debt']}")
    print(f"    anomaly filter (<0/>20):{reason_counts['anomaly']}")

    print("\nARCC most recent quarter:")
    if arcc_latest is None:
        print("    ARCC.json not found or no dict rows.")
    else:
        print(f"    quarter:              {arcc_latest.get('quarter')}")
        print(f"    total_assets_mn:      {arcc_latest.get('total_assets_mn')}")
        print(f"    total_liabilities_mn: {arcc_latest.get('total_liabilities_mn')}")
        print(f"    total_debt_mn:        {arcc_latest.get('total_debt_mn')}")
        print(f"    asset_coverage_ratio: {arcc_latest.get('asset_coverage_ratio')}")


if __name__ == "__main__":
    main()
