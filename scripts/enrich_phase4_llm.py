#!/usr/bin/env python3
"""Phase 4: LLM extraction (claude -p) for high-priority gaps.

Strategy:
 - For each fund (ordered by AUM desc), fetch SEC submissions index, identify the
   most recent 10-Q and 10-K filings (up to last N quarters).
 - For each filing, fetch primary doc HTML, strip to text, send first 15k chars
   to `claude -p` with a strict extraction prompt.
 - Parse JSON, map fields onto the quarter whose period_end matches the filing's
   periodOfReport. Never overwrites non-null values.

Idempotent: if all HIGH_PRIORITY_FIELDS for a quarter are already non-null, skip it.
Commits to git every COMMIT_EVERY funds so progress is durable.
"""
import json, pathlib, urllib.request, urllib.error, time, datetime, subprocess
import re, sys, html, os

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS   = ROOT/'data'/'timeseries'
LOG  = ROOT/'data'/'logs'/f'phase4_llm_{datetime.date.today():%Y%m%d}.log'
FD   = ROOT/'data'/'universe'/'fund_directory.json'

UA = 'BDC-Research/1.0 (qsaif2321@gmail.com)'
SEC_SLEEP = 0.6
LLM_SLEEP = 1.5
MAX_FILINGS_PER_FUND = 5     # latest 5 filings
TEXT_LIMIT = 40000           # cap on concatenated keyword windows
WINDOW_BEFORE = 400
WINDOW_AFTER  = 2200
KEYWORDS = [
    'non-accrual','non accrual','nonaccrual',
    'weighted average yield','weighted-average yield','portfolio yield',
    'first lien','senior secured','second lien',
    'floating rate','floating-rate','fixed rate',
    'incentive fee','management fee','base management fee',
    'spillover','undistributed net investment','undistributed taxable',
    'origination','repayment','portfolio activity',
    'leverage','debt to equity','asset coverage',
    'portfolio companies','number of portfolio',
    'cost of debt','weighted average interest rate',
    'credit facility','revolving credit','unfunded',
    'PIK',
]
COMMIT_EVERY = 10            # commit & push every N funds
CLAUDE_TIMEOUT = 180

HIGH_PRIORITY_FIELDS = [
    'na_pct_cost','na_pct_fv','floating_rate_pct','pik_pct','weighted_avg_yield',
    'first_lien_pct','second_lien_pct','equity_pct','originations_mn','repayments_mn',
    'cost_of_debt_pct','num_portfolio_companies','leverage','total_debt_mn',
    'spillover_per_share','management_fee_mn','incentive_fee_mn','pik_income_mn',
    'credit_facility_drawn_mn','unused_capacity_mn',
]

def log(msg):
    print(msg, flush=True)
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
    except Exception as e:
        log(f'HTTP err {url}: {e}')
        return None

def get_ticker_to_cik_map():
    raw = http_get('https://www.sec.gov/files/company_tickers.json')
    if not raw: return {}
    try:
        d = json.loads(raw)
        return {v.get('ticker','').upper(): str(v.get('cik_str','')).zfill(10)
                for v in d.values() if v.get('ticker') and v.get('cik_str')}
    except: return {}

def get_recent_filings(cik):
    """Return list of dicts: {form, accn, primaryDoc, periodOfReport, filingDate}."""
    url = f'https://data.sec.gov/submissions/CIK{cik}.json'
    raw = http_get(url)
    if not raw: return []
    try:
        d = json.loads(raw)
    except: return []
    recent = d.get('filings',{}).get('recent',{})
    forms = recent.get('form', [])
    accns = recent.get('accessionNumber', [])
    docs  = recent.get('primaryDocument', [])
    pors  = recent.get('reportDate', []) or recent.get('periodOfReport', [])
    fds   = recent.get('filingDate', [])
    out = []
    for i,form in enumerate(forms):
        if form not in ('10-Q','10-K'): continue
        out.append({
            'form': form, 'accn': accns[i], 'primaryDoc': docs[i] if i<len(docs) else '',
            'periodOfReport': pors[i] if i<len(pors) else None,
            'filingDate': fds[i] if i<len(fds) else None,
        })
    return out[:MAX_FILINGS_PER_FUND]

def strip_html(s):
    """Crude HTML→text. Preserves table-cell whitespace and removes scripts/styles."""
    s = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', s, flags=re.DOTALL|re.IGNORECASE)
    s = re.sub(r'</?(td|th|tr|li|p|br|div|h\d)[^>]*>', ' \n ', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s)
    return s

def extract_keyword_windows(text, keywords=KEYWORDS, before=WINDOW_BEFORE, after=WINDOW_AFTER, cap=TEXT_LIMIT):
    """Find each keyword in text, extract a window around each match, dedupe overlap, cap at `cap` chars."""
    lower = text.lower()
    spans = []
    for kw in keywords:
        start = 0
        while True:
            i = lower.find(kw.lower(), start)
            if i < 0: break
            s = max(0, i - before)
            e = min(len(text), i + after)
            spans.append((s,e))
            start = i + len(kw)
            if len(spans) > 200: break  # safety cap
    if not spans: return text[:cap]
    spans.sort()
    merged = [spans[0]]
    for s,e in spans[1:]:
        ls,le = merged[-1]
        if s <= le: merged[-1] = (ls, max(le,e))
        else:       merged.append((s,e))
    out = []
    used = 0
    for s,e in merged:
        chunk = text[s:e]
        if used + len(chunk) > cap:
            chunk = chunk[: cap - used]
            out.append(chunk)
            break
        out.append(chunk)
        used += len(chunk)
    return '\n…\n'.join(out)

LLM_PROMPT_TEMPLATE = """You are extracting financial data from an SEC filing for BDC ticker {ticker}, three-month period ending {period}.

Filing excerpts (concatenated from sections containing relevant keywords):
---
{text}
---

CRITICAL RULES:
- Flow/income-statement values (originations_mn, repayments_mn, pik_income_mn, management_fee_mn, incentive_fee_mn) MUST be the THREE-MONTH (single quarter) value ending {period}. If only year-to-date is shown, return null — do not return YTD figures as quarterly.
- Point-in-time values (na_pct_*, floating_rate_pct, first_lien_pct, num_portfolio_companies, total_debt_mn, leverage, credit_facility_drawn_mn, unused_capacity_mn, weighted_avg_yield, cost_of_debt_pct, spillover_per_share) should be AS OF {period}.
- Return null whenever the value is not clearly stated FOR THIS QUARTER. Do not infer or estimate.
- Units: percentages as plain numbers (1.8 for 1.8%), dollar amounts in millions of USD, ratios as decimals, counts as whole numbers.

Respond with ONLY a valid JSON object, no prose, no markdown fences. Schema:
{{
  "na_pct_cost": number|null,
  "na_pct_fv": number|null,
  "floating_rate_pct": number|null,
  "first_lien_pct": number|null,
  "second_lien_pct": number|null,
  "equity_pct": number|null,
  "pik_pct": number|null,
  "pik_income_mn": number|null,
  "weighted_avg_yield": number|null,
  "originations_mn": number|null,
  "repayments_mn": number|null,
  "num_portfolio_companies": number|null,
  "cost_of_debt_pct": number|null,
  "leverage": number|null,
  "total_debt_mn": number|null,
  "spillover_per_share": number|null,
  "management_fee_mn": number|null,
  "incentive_fee_mn": number|null,
  "credit_facility_drawn_mn": number|null,
  "unused_capacity_mn": number|null
}}"""

def call_claude(prompt):
    """Run `claude -p PROMPT` and return parsed JSON dict or None."""
    try:
        proc = subprocess.run(
            ['claude','-p', prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
        )
        out = proc.stdout.strip()
        # Try to extract first {...} block
        m = re.search(r'\{[\s\S]*\}', out)
        if not m: return None
        try:
            return json.loads(m.group(0))
        except: return None
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        log(f'claude err: {e}')
        return None

def find_matching_quarter(records, period_str):
    """Given periodOfReport YYYY-MM-DD, return the timeseries record whose period_end matches (within 5 days)."""
    try:
        target = datetime.date.fromisoformat(period_str)
    except: return None
    best = None
    best_dd = 999
    for r in records:
        pe = r.get('period_end')
        if not pe: continue
        try:
            d = datetime.date.fromisoformat(str(pe)[:10])
        except: continue
        dd = abs((d-target).days)
        if dd < best_dd and dd <= 5:
            best, best_dd = r, dd
    return best

def has_all_priority(rec):
    return all(rec.get(f) is not None for f in HIGH_PRIORITY_FIELDS)

def needs_extraction(rec):
    return any(rec.get(f) is None for f in HIGH_PRIORITY_FIELDS)

def git_commit_push(msg):
    try:
        subprocess.run(['git','add','data/timeseries/','data/logs/'], cwd=ROOT, check=False, capture_output=True)
        r = subprocess.run(['git','-c','user.email=qsaif2321@gmail.com','-c','user.name=Qazi Rasool',
                            'commit','-m', msg], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(['git','push','origin','main'], cwd=ROOT, capture_output=True)
            log(f'committed+pushed: {msg}')
        else:
            log(f'commit noop or err: {r.stdout[:200]} {r.stderr[:200]}')
    except Exception as e:
        log(f'git err: {e}')

def process_fund(fund, ticker_map):
    ticker = fund['ticker']
    real = fund.get('real_ticker') or ticker
    cik = fund.get('cik')
    if not cik:
        cik = ticker_map.get(real.upper()) or ticker_map.get(ticker.upper())
    if not cik:
        log(f'{ticker}: no cik, skip')
        return 0
    cik = str(cik).zfill(10)

    ts_path = TS/f'{ticker}.json'
    if not ts_path.exists():
        return 0
    data = json.load(open(ts_path))
    if not data: return 0
    data.sort(key=lambda r: (r.get('period_end') or ''))

    # Early-exit: if every recent quarter already has all priority fields, skip
    recent = data[-MAX_FILINGS_PER_FUND:]
    if all(has_all_priority(r) for r in recent):
        log(f'{ticker}: all priority fields already populated in recent quarters, skip')
        return 0

    filings = get_recent_filings(cik)
    time.sleep(SEC_SLEEP)
    if not filings:
        log(f'{ticker}: no filings index')
        return 0

    total_fills = 0
    for fil in filings:
        por = fil.get('periodOfReport')
        if not por: continue
        rec = find_matching_quarter(data, por)
        if rec is None:
            continue
        if not needs_extraction(rec):
            continue

        # Fetch primary document
        accn_clean = fil['accn'].replace('-','')
        cik_num = str(int(cik))
        url = f'https://www.sec.gov/Archives/edgar/data/{cik_num}/{accn_clean}/{fil["primaryDoc"]}'
        raw = http_get(url, timeout=45)
        time.sleep(SEC_SLEEP)
        if not raw:
            log(f'{ticker} {por}: fetch failed {url}')
            continue
        try:
            text = strip_html(raw.decode('utf-8','ignore'))
        except:
            continue
        text = extract_keyword_windows(text)

        prompt = LLM_PROMPT_TEMPLATE.format(ticker=ticker, period=por, text=text)
        result = call_claude(prompt)
        time.sleep(LLM_SLEEP)

        if not result:
            log(f'{ticker} {por}: LLM no result')
            continue
        fills_here = 0
        for k,v in result.items():
            if k not in HIGH_PRIORITY_FIELDS: continue
            if v is None: continue
            if rec.get(k) is not None: continue
            try:
                fv = float(v)
                if fv != fv: continue
                rec[k] = round(fv, 6)
                fills_here += 1
            except: continue
        total_fills += fills_here
        log(f'{ticker} {por}: +{fills_here} cells from LLM')

    if total_fills:
        tmp = ts_path.with_suffix('.json.tmp')
        with open(tmp,'w') as o: json.dump(data,o,indent=2,default=str)
        tmp.replace(ts_path)
    return total_fills


def main():
    log('=== Phase 4 LLM start ===')
    fd = json.load(open(FD))
    funds = fd['funds']
    ticker_map = get_ticker_to_cik_map()
    funds_sorted = sorted(funds, key=lambda f: f.get('latest_net_assets_mn') or 0, reverse=True)

    total = 0
    processed = 0
    for f in funds_sorted:
        try:
            n = process_fund(f, ticker_map)
            total += n
            processed += 1
        except Exception as e:
            log(f"{f.get('ticker')}: EXCEPTION {type(e).__name__}: {e}")
        if processed % COMMIT_EVERY == 0:
            git_commit_push(f'Phase 4 LLM enrichment: {processed} funds processed, +{total} cells')
    git_commit_push(f'Phase 4 LLM enrichment complete: {processed} funds, +{total} cells')
    log(f'=== Phase 4 done: {processed} funds, {total} cells ===')

if __name__=='__main__':
    main()
