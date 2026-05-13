#!/usr/bin/env python3
"""Generate the final enrichment report comparing baseline → current state."""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS   = ROOT/'data'/'timeseries'

FIELDS = [
    'nav_per_share','nii_per_share','dividend_per_share','nii_coverage',
    'total_investment_income_mn','net_investment_income_mn','total_expenses_mn',
    'pik_pct','pik_income_mn','cash_income_pct','na_pct_cost','na_pct_fv',
    'na_dollar_amount_mn','first_lien_pct','floating_rate_pct','leverage',
    'originations_mn','repayments_mn','net_assets_mn','weighted_avg_yield',
    'cost_of_debt_pct','net_interest_spread','num_portfolio_companies',
    'total_investments_fv_mn','total_debt_mn','spillover_per_share',
    'total_return_index','cumulative_dividends_paid',
]

def gap_count(d):
    return sum(1 for r in d for f in FIELDS if r.get(f) is None)

def total():
    nulls=0; cells=0
    for fp in sorted(TS.glob('*.json')):
        d = json.load(open(fp))
        for r in d:
            for f in FIELDS:
                cells += 1
                if r.get(f) is None: nulls += 1
    return nulls, cells

def main():
    print('=== FINAL ENRICHMENT REPORT ===')
    n, c = total()
    print(f'Total nulls across 28 priority fields × 140 funds: {n}/{c} ({n/c*100:.1f}% missing)')
    print(f'Cells populated: {c-n}/{c} ({(c-n)/c*100:.1f}%)')
    print()
    print('Per-fund priority-field gaps (ARCC / BCRED / OBDC):')
    for tk in ['ARCC','BCRED','OBDC']:
        d = json.load(open(TS/f'{tk}.json'))
        g = gap_count(d)
        t = len(d)*len(FIELDS)
        print(f'  {tk}: {g}/{t} ({g/t*100:.1f}%)')

if __name__=='__main__':
    main()
