#!/usr/bin/env python3
"""Phase 1 + 5 derivations. No network. Never overwrites non-null values."""
import json, pathlib, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS   = ROOT/'data'/'timeseries'
LOG  = ROOT/'data'/'logs'/f'phase1_{datetime.date.today():%Y%m%d}.log'
LOG.parent.mkdir(parents=True, exist_ok=True)

def num(x):
    if x is None: return None
    try:
        f=float(x)
        if f != f: return None  # NaN
        return f
    except: return None

def set_if_null(rec, key, val):
    """Set rec[key]=val only if currently null and val is a real number."""
    if val is None: return 0
    v = num(val)
    if v is None: return 0
    cur = rec.get(key)
    if cur is None:
        rec[key] = round(v, 6) if isinstance(v, float) else v
        return 1
    return 0

def safe_div(a,b):
    a=num(a); b=num(b)
    if a is None or b is None or b==0: return None
    return a/b

def derive(records):
    """records is the chronologically-ordered list of quarter dicts."""
    fills = 0
    # First pass: per-record derivations
    for r in records:
        ti  = num(r.get('total_investment_income_mn'))
        pii = num(r.get('pik_income_mn'))
        cash_mn = (ti - pii) if (ti is not None and pii is not None) else None
        if cash_mn is not None:
            fills += set_if_null(r,'cash_income_mn',cash_mn)
            if ti and ti != 0:
                fills += set_if_null(r,'cash_income_pct', cash_mn/ti*100)

        nii_ps  = num(r.get('nii_per_share'))
        div_ps  = num(r.get('dividend_per_share'))
        if nii_ps is not None and div_ps is not None and div_ps != 0:
            fills += set_if_null(r,'nii_coverage', nii_ps/div_ps)

        orig = num(r.get('originations_mn'))
        repay= num(r.get('repayments_mn'))
        if orig is not None and repay is not None:
            fills += set_if_null(r,'net_originations_mn', orig-repay)

        na  = num(r.get('net_assets_mn'))
        if orig is not None and na is not None and na != 0:
            fills += set_if_null(r,'origination_velocity_pct', orig/na*100)

        # na_dollar_amount_mn = na_pct_cost/100 * total_investments_fv_mn  (proxy: FV ≈ cost-basis denom)
        na_pct_c = num(r.get('na_pct_cost'))
        fv       = num(r.get('total_investments_fv_mn'))
        if na_pct_c is not None and fv is not None:
            fills += set_if_null(r,'na_dollar_amount_mn', na_pct_c/100*fv)

        na_pct_f = num(r.get('na_pct_fv'))
        if na_pct_c is not None and na_pct_f is not None and na_pct_c != 0:
            fills += set_if_null(r,'implied_recovery_rate_pct', na_pct_f/na_pct_c*100)

        wy  = num(r.get('weighted_avg_yield'))
        cod = num(r.get('cost_of_debt_pct'))
        if wy is not None and cod is not None:
            fills += set_if_null(r,'net_interest_spread', wy-cod)

        exp = num(r.get('total_expenses_mn'))
        if exp is not None and na is not None and na != 0:
            fills += set_if_null(r,'expense_ratio_pct', exp/na*100)

        mfee = num(r.get('management_fee_mn'))
        ifee = num(r.get('incentive_fee_mn'))
        nii_mn = num(r.get('net_investment_income_mn'))
        if mfee is not None and ifee is not None and nii_mn is not None and nii_mn != 0:
            fills += set_if_null(r,'fee_as_pct_of_nii', (mfee+ifee)/nii_mn*100)

        flt = num(r.get('floating_rate_pct'))
        if flt is not None:
            fills += set_if_null(r,'fixed_rate_pct', 100-flt)

        npc = num(r.get('num_portfolio_companies'))
        if fv is not None and npc is not None and npc != 0:
            fills += set_if_null(r,'avg_position_size_mn', fv/npc)

        uc  = num(r.get('unused_capacity_mn'))
        if uc is not None and fv is not None and fv != 0:
            fills += set_if_null(r,'liquidity_pct', uc/fv*100)

        # net_assets_mn = shares_outstanding * nav_per_share (if missing)
        so   = num(r.get('shares_outstanding'))
        nav  = num(r.get('nav_per_share'))
        if so is not None and nav is not None and r.get('net_assets_mn') is None:
            # if shares_outstanding stored in millions vs raw, try both heuristics
            implied = so * nav
            # heuristic: if implied is < 100k, shares were in millions already → keep
            # if implied is > 1e7, shares were raw, divide by 1e6
            if implied > 1e7: implied = implied/1e6
            fills += set_if_null(r,'net_assets_mn', implied)

        ie = num(r.get('interest_expense_mn'))
        if ti is not None and ie is not None and ie != 0:
            fills += set_if_null(r,'interest_coverage_ratio', ti/ie)

        if mfee is not None and na is not None and na != 0:
            fills += set_if_null(r,'mgmt_fee_pct_of_assets', mfee/na*100)

    # Second pass: cross-quarter derivations
    # cumulative_dividends_paid: running sum of dividend_per_share
    cum = 0.0
    cum_set = False
    for r in records:
        d = num(r.get('dividend_per_share'))
        if d is not None:
            cum += d
            cum_set = True
        if cum_set:
            fills += set_if_null(r,'cumulative_dividends_paid', cum)

    # total_return_index = nav_per_share + cumulative_dividends_paid
    for r in records:
        nav = num(r.get('nav_per_share'))
        cdp = num(r.get('cumulative_dividends_paid'))
        if nav is not None and cdp is not None:
            fills += set_if_null(r,'total_return_index', nav+cdp)

    # nav_per_share_qoq_change, nav_per_share_yoy_pct
    for i,r in enumerate(records):
        nav = num(r.get('nav_per_share'))
        if nav is None: continue
        if i >= 1:
            prev = num(records[i-1].get('nav_per_share'))
            if prev is not None:
                fills += set_if_null(r,'nav_per_share_qoq_change', nav-prev)
        if i >= 4:
            yoy = num(records[i-4].get('nav_per_share'))
            if yoy is not None and yoy != 0:
                fills += set_if_null(r,'nav_per_share_yoy_pct', (nav/yoy-1)*100)

    # net_na_change_mn = na_dollar_amount_mn[t] - [t-1]
    for i,r in enumerate(records):
        if i == 0: continue
        cur  = num(r.get('na_dollar_amount_mn'))
        prev = num(records[i-1].get('na_dollar_amount_mn'))
        if cur is not None and prev is not None:
            fills += set_if_null(r,'net_na_change_mn', cur-prev)

    # data_quality_score = pct of non-null fields
    for r in records:
        total = len(r)
        non_null = sum(1 for v in r.values() if v is not None)
        score = round(non_null/total*100, 2) if total else 0
        # Always update this one (it reflects current state)
        r['data_quality_score'] = score

    return fills


def main():
    files = sorted(TS.glob('*.json'))
    total_fills = 0
    funds_processed = 0
    with open(LOG,'w') as lf:
        lf.write(f'Phase 1 derivations start {datetime.datetime.now().isoformat()}\n')
        for fp in files:
            try:
                data = json.load(open(fp))
                if not isinstance(data, list) or not data: continue
                # sort by period_end ascending (safety)
                data.sort(key=lambda r: (r.get('period_end') or r.get('quarter') or ''))
                f = derive(data)
                total_fills += f
                funds_processed += 1
                tmp = fp.with_suffix('.json.tmp')
                with open(tmp,'w') as o: json.dump(data,o,indent=2,default=str)
                tmp.replace(fp)
                lf.write(f'{fp.stem}: +{f} cells\n')
            except Exception as e:
                lf.write(f'{fp.stem}: ERROR {e}\n')
        lf.write(f'TOTAL funds={funds_processed} cells_filled={total_fills}\n')
    print(f'Phase 1 done: {funds_processed} funds, {total_fills} cells filled')

if __name__=='__main__':
    main()
