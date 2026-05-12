#!/usr/bin/env python3
"""Phase 2: SEC EDGAR XBRL company-facts re-extraction across all 140 funds.

For each fund with a CIK, fetch /api/xbrl/companyfacts/CIK#######.json and map each
us-gaap / cef fact to a quarter record by period-end date. Never overwrites non-null.
"""
import json, pathlib, urllib.request, urllib.error, time, datetime, sys, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS   = ROOT/'data'/'timeseries'
LOG  = ROOT/'data'/'logs'/f'phase2_xbrl_{datetime.date.today():%Y%m%d}.log'
LOG.parent.mkdir(parents=True, exist_ok=True)
FD   = ROOT/'data'/'universe'/'fund_directory.json'

UA = 'BDC-Research/1.0 (qsaif2321@gmail.com)'
SLEEP_BETWEEN = 0.6  # seconds between SEC calls

# Field map: tag name -> (timeseries_field, scale)
#   scale: divide value by this to get the JSON unit. e.g. millions = 1_000_000.
TAG_MAP = {
    # USD values reported in dollars; JSON stores millions
    'NetInvestmentIncome':                          ('net_investment_income_mn', 1_000_000),
    'NetInvestmentIncomeLoss':                      ('net_investment_income_mn', 1_000_000),
    'InvestmentIncomeNet':                          ('total_investment_income_mn', 1_000_000),
    'InvestmentIncomeInterest':                     ('interest_income_mn', 1_000_000),
    'NetAssets':                                    ('net_assets_mn', 1_000_000),
    'StockholdersEquity':                           ('net_assets_mn', 1_000_000),
    'Assets':                                       ('total_assets_mn', 1_000_000),
    'AssetsFairValueDisclosure':                    ('total_investments_fv_mn', 1_000_000),
    'InvestmentOwnedFairValue':                     ('total_investments_fv_mn', 1_000_000),
    'InvestmentsFairValueDisclosure':               ('total_investments_fv_mn', 1_000_000),
    'CashAndCashEquivalents':                       ('cash_mn', 1_000_000),
    'CashAndCashEquivalentsAtCarryingValue':        ('cash_mn', 1_000_000),
    'Liabilities':                                  ('total_liabilities_mn', 1_000_000),
    'OperatingExpenses':                            ('total_expenses_mn', 1_000_000),
    'InterestExpense':                              ('interest_expense_mn', 1_000_000),
    'InvestmentAdvisoryFee':                        ('management_fee_mn', 1_000_000),
    'InvestmentAdvisoryFeesExpense':                ('management_fee_mn', 1_000_000),
    'IncentiveFeeExpense':                          ('incentive_fee_mn', 1_000_000),
    'IncentiveDistributionPayments':                ('incentive_fee_mn', 1_000_000),
    'DividendsCommonStockCash':                     ('dividends_paid_mn', 1_000_000),
    'DividendsCommonStock':                         ('dividends_paid_mn', 1_000_000),
    'PaymentsOfDividends':                          ('dividends_paid_mn', 1_000_000),
    'LongTermDebt':                                 ('total_debt_mn', 1_000_000),
    'DebtCurrent':                                  ('short_term_debt_mn', 1_000_000),
    'LineOfCreditFacilityMaximumBorrowingCapacity': ('credit_facility_limit_mn', 1_000_000),
    'LineOfCreditFacilityRemainingBorrowingCapacity': ('unused_capacity_mn', 1_000_000),
    'NetRealizedAndUnrealizedGainLossOnInvestments':('net_unrealized_gains_mn', 1_000_000),
    # per-share quantities
    'EarningsPerShareBasic':                        ('nii_per_share', 1),
    'NetInvestmentIncomePerShareBasic':             ('nii_per_share', 1),
    'CommonStockDividendsPerShareCashPaid':         ('dividend_per_share', 1),
    'CommonStockDividendsPerShareDeclared':         ('dividend_per_share', 1),
    # share count
    'CommonStockSharesOutstanding':                 ('shares_outstanding', 1),
    'SharesOutstanding':                            ('shares_outstanding', 1),
    'WeightedAverageNumberOfSharesOutstandingBasic':('shares_outstanding_avg', 1),
    # cef-namespaced (BDC-specific)
    'NetAssetValuePerShare':                        ('nav_per_share', 1),
    'WtdAvgPortfolioYield':                         ('weighted_avg_yield', 1),
    'DistributionsDeclaredPerShare':                ('dividend_per_share', 1),
}

def log(msg):
    with open(LOG,'a') as f:
        f.write(f'[{datetime.datetime.now():%H:%M:%S}] {msg}\n')

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding':'gzip, deflate'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            enc = resp.headers.get('Content-Encoding','')
            if 'gzip' in enc:
                import gzip; data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as e:
        log(f'HTTP {e.code} on {url}')
        return None
    except Exception as e:
        log(f'ERR {type(e).__name__} on {url}: {e}')
        return None

def get_ticker_to_cik_map():
    log('Fetching SEC ticker→CIK master file')
    raw = http_get('https://www.sec.gov/files/company_tickers.json')
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        mp = {}
        for k,v in d.items():
            tk = v.get('ticker','').upper()
            cik = str(v.get('cik_str','')).zfill(10)
            if tk and cik:
                mp[tk] = cik
        log(f'Loaded {len(mp)} ticker→CIK pairs')
        return mp
    except Exception as e:
        log(f'Parse error on ticker map: {e}')
        return {}

def parse_period_end(s):
    """Return YYYY-MM-DD from various inputs."""
    if not s: return None
    s = str(s)[:10]
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    return None

def near_period(target, candidate, tol_days=20):
    """Check if XBRL fact end date is within tol_days of target period_end."""
    try:
        d1 = datetime.date.fromisoformat(target)
        d2 = datetime.date.fromisoformat(candidate)
        return abs((d1-d2).days) <= tol_days
    except: return False

def process_fund(fund, ticker_map):
    """Return (cells_filled, error_or_none)."""
    ticker = fund['ticker']
    real = fund.get('real_ticker') or ticker
    cik = fund.get('cik')
    if not cik:
        cik = ticker_map.get(real.upper()) or ticker_map.get(ticker.upper())
        if not cik:
            return 0, 'no_cik'
    cik = str(cik).zfill(10)

    ts_path = TS/f'{ticker}.json'
    if not ts_path.exists():
        return 0, 'no_timeseries'

    facts_url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
    raw = http_get(facts_url)
    if not raw:
        return 0, 'fetch_failed'
    try:
        facts = json.loads(raw)
    except Exception as e:
        return 0, f'parse_failed:{e}'

    # Tags that are flow (income statement, cash flow) — we want quarterly (~90-day) spans only
    FLOW_TAGS = {
        'NetInvestmentIncome','NetInvestmentIncomeLoss','InvestmentIncomeNet',
        'InvestmentIncomeInterest','OperatingExpenses','InterestExpense',
        'InvestmentAdvisoryFee','InvestmentAdvisoryFeesExpense',
        'IncentiveFeeExpense','IncentiveDistributionPayments',
        'DividendsCommonStockCash','DividendsCommonStock','PaymentsOfDividends',
        'NetRealizedAndUnrealizedGainLossOnInvestments',
        'EarningsPerShareBasic','NetInvestmentIncomePerShareBasic',
        'CommonStockDividendsPerShareCashPaid','CommonStockDividendsPerShareDeclared',
        'DistributionsDeclaredPerShare',
    }
    # Build flat index: tag → list of {end, val, fy, fp, form, unit, span_days}
    tag_idx = {}
    for taxonomy in ('us-gaap','cef','dei','srt'):
        tagdict = facts.get('facts',{}).get(taxonomy,{})
        for tag, body in tagdict.items():
            if tag not in TAG_MAP: continue
            units = body.get('units',{})
            for unit, arr in units.items():
                for entry in arr:
                    end = entry.get('end')
                    start = entry.get('start')
                    val = entry.get('val')
                    if end is None or val is None: continue
                    span = None
                    if start and end:
                        try:
                            span = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
                        except: pass
                    # For flow tags, only keep ~quarterly spans (80–100 days)
                    if tag in FLOW_TAGS:
                        if span is None or not (75 <= span <= 100):
                            continue
                    tag_idx.setdefault(tag, []).append({
                        'end': end, 'val': val, 'unit': unit, 'span': span,
                        'fp': entry.get('fp',''), 'fy': entry.get('fy',0),
                        'form': entry.get('form','')
                    })

    if not tag_idx:
        return 0, 'no_relevant_tags'

    data = json.load(open(ts_path))
    if not isinstance(data, list) or not data:
        return 0, 'empty_ts'

    fills = 0
    for rec in data:
        pe = parse_period_end(rec.get('period_end'))
        if not pe: continue
        for tag, entries in tag_idx.items():
            field, scale = TAG_MAP[tag]
            if rec.get(field) is not None:
                continue
            # Find best matching entry near this period_end
            best = None
            for e in entries:
                if not near_period(pe, e['end'], tol_days=20): continue
                # Prefer 10-K/10-Q forms over amendments; prefer fy/fp match
                priority = 0
                if e['form'] in ('10-Q','10-K'): priority += 2
                if e['fp']: priority += 1
                if best is None or priority > best['_p']:
                    e2 = dict(e); e2['_p'] = priority
                    best = e2
            if best:
                v = best['val'] / scale
                # Sanity: skip absurd values
                if abs(v) < 1e12:
                    rec[field] = round(v, 6)
                    fills += 1

    if fills:
        tmp = ts_path.with_suffix('.json.tmp')
        with open(tmp,'w') as o: json.dump(data,o,indent=2,default=str)
        tmp.replace(ts_path)
    return fills, None

def main():
    log(f'=== Phase 2 XBRL start ===')
    fd = json.load(open(FD))
    funds = fd['funds']
    ticker_map = get_ticker_to_cik_map()
    time.sleep(SLEEP_BETWEEN)

    # Sort by latest_net_assets_mn desc (largest first)
    funds_sorted = sorted(funds, key=lambda f: f.get('latest_net_assets_mn') or 0, reverse=True)

    total_fills = 0
    funds_done = 0
    funds_with_data = 0
    errors = {}
    for f in funds_sorted:
        tk = f['ticker']
        try:
            n, err = process_fund(f, ticker_map)
            funds_done += 1
            if err:
                errors[err] = errors.get(err,0)+1
                log(f'{tk}: skip ({err})')
            else:
                if n: funds_with_data += 1
                total_fills += n
                log(f'{tk}: +{n} cells')
        except Exception as e:
            log(f'{tk}: EXCEPTION {type(e).__name__}: {e}')
            errors['exception'] = errors.get('exception',0)+1
        time.sleep(SLEEP_BETWEEN)
    log(f'=== Phase 2 done: funds_done={funds_done} funds_with_data={funds_with_data} total_fills={total_fills} errors={errors}')
    print(f'Phase 2 done: {funds_done} funds, {total_fills} cells filled (errors: {errors})')

if __name__=='__main__':
    main()
