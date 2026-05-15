#!/usr/bin/env python3
"""Re-source CIKs for all 140 BDC funds from scratch.

Output: prints a full resolution report and writes
data/universe/cik_resolution_log.json. Does NOT modify
fund_directory.json — that's a separate, deliberate step
after the user reviews this output.
"""
import json, pathlib, urllib.request, urllib.error, urllib.parse, time, datetime, re, sys, gzip
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNI  = ROOT/'data'/'universe'
CACHE = ROOT/'data'/'universe'/'_sec_cache'
CACHE.mkdir(parents=True, exist_ok=True)
LOG_PATH = UNI/'cik_resolution_log.json'

UA = 'BDC Intelligence research@bdcintelligence.ai'
SLEEP = 0.15  # ~6 req/sec, under SEC's 10/sec ceiling

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept-Encoding': 'gzip, deflate',
        'Accept': 'application/json, text/html, */*',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if 'gzip' in resp.headers.get('Content-Encoding',''):
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as e:
        return None
    except Exception:
        return None

def cached_fetch(url, cache_name):
    """Fetch URL once, cache to disk, return raw bytes."""
    p = CACHE/cache_name
    if p.exists():
        return p.read_bytes()
    raw = http_get(url)
    if raw is None: return None
    p.write_bytes(raw)
    time.sleep(SLEEP)
    return raw

def fetch_submissions(cik):
    """Fetch and cache /submissions/CIK#######.json. cik must already be 10-digit zero-padded."""
    cik10 = str(cik).zfill(10)
    p = CACHE/f'sub_{cik10}.json'
    if p.exists():
        try: return json.loads(p.read_bytes())
        except: pass
    url = f'https://data.sec.gov/submissions/CIK{cik10}.json'
    raw = http_get(url)
    if raw is None: return None
    try:
        d = json.loads(raw)
    except:
        return None
    p.write_bytes(json.dumps(d).encode('utf-8'))
    time.sleep(SLEEP)
    return d

# ───────────────────────────────────────────────────────────
# STEP 1 — load SEC master files (cached)
# ───────────────────────────────────────────────────────────
def step1_load_masters():
    print('STEP 1 — fetching SEC master files', flush=True)
    raw_t = cached_fetch('https://www.sec.gov/files/company_tickers.json', 'company_tickers.json')
    raw_e = cached_fetch('https://www.sec.gov/files/company_tickers_exchange.json', 'company_tickers_exchange.json')
    ticker_map = {}    # TICKER → {cik, name, source_url}
    if raw_t:
        d = json.loads(raw_t)
        for v in d.values():
            tk = (v.get('ticker') or '').upper()
            cik = str(v.get('cik_str') or '').zfill(10)
            if tk and cik:
                ticker_map[tk] = {
                    'cik': cik, 'name': v.get('title',''),
                    'source': 'https://www.sec.gov/files/company_tickers.json',
                }
    # company_tickers_exchange has columns: cik, name, ticker, exchange
    if raw_e:
        d = json.loads(raw_e)
        fields = d.get('fields') or []
        rows = d.get('data') or []
        if fields:
            ix = {f:i for i,f in enumerate(fields)}
            for row in rows:
                tk = str(row[ix['ticker']]).upper() if 'ticker' in ix else ''
                cik = str(row[ix['cik']]).zfill(10) if 'cik' in ix else ''
                nm  = row[ix['name']] if 'name' in ix else ''
                ex  = row[ix['exchange']] if 'exchange' in ix else ''
                if tk and cik and tk not in ticker_map:
                    ticker_map[tk] = {
                        'cik': cik, 'name': nm, 'exchange': ex,
                        'source': 'https://www.sec.gov/files/company_tickers_exchange.json',
                    }
    print(f'  ticker_map size: {len(ticker_map)}', flush=True)
    return ticker_map

# ───────────────────────────────────────────────────────────
# STEP 3 — EDGAR full-text company search by name
# ───────────────────────────────────────────────────────────
def edgar_search(name_query):
    """Use EFTS (EDGAR full-text search) to find companies matching name_query.
    Returns list of {cik, name, sic}."""
    q = urllib.parse.quote_plus(name_query)
    url = f'https://efts.sec.gov/LATEST/search-index?q=%22{q}%22&forms=10-K'
    p = CACHE/f'efts_{re.sub(r"[^A-Za-z0-9_]","_",name_query)[:80]}.json'
    if p.exists():
        try: return json.loads(p.read_bytes())
        except: pass
    raw = http_get(url)
    if raw is None: return []
    try:
        d = json.loads(raw)
    except:
        return []
    hits = d.get('hits',{}).get('hits',[])
    out = []
    seen = set()
    for h in hits[:20]:
        src = h.get('_source',{})
        cik_list = src.get('ciks') or []
        for c in cik_list:
            c10 = str(c).zfill(10)
            if c10 in seen: continue
            seen.add(c10)
            out.append({
                'cik': c10,
                'name': (src.get('display_names') or [src.get('name','')])[0] if src.get('display_names') else src.get('name',''),
                'form': src.get('form',''),
                'sic': src.get('sic') or '',
            })
    p.write_bytes(json.dumps(out).encode('utf-8'))
    time.sleep(SLEEP)
    return out

def normalize_name(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    # Strip common entity suffixes
    s = re.sub(r'\b(inc|corp|corporation|llc|lp|ltd|company|co|fund|trust|the)\b', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def name_score(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb: return 0
    if na == nb: return 100
    if na in nb or nb in na: return 80
    aw, bw = set(na.split()), set(nb.split())
    if not aw or not bw: return 0
    overlap = len(aw & bw) / max(len(aw), len(bw))
    return int(overlap * 70)

# ───────────────────────────────────────────────────────────
# STEP 4 — manual overrides for the 6 suspicious cases
# ───────────────────────────────────────────────────────────
MANUAL_HINTS = {
    'ASIF':     'Ares Strategic Income Fund',
    'ASCF':     'Apollo Senior Credit Fund',
    'ASCFI':    'Apollo Senior Floating Rate Fund',
    'CCSI':     'Carlyle Credit Solutions Inc',
    'GS_PCC':   'Goldman Sachs Private Credit Corp',
    'TROW_OHA': 'T Rowe Price OHA Select Private Credit Fund',
}

# ───────────────────────────────────────────────────────────
# STEP 5 — submissions verification
# ───────────────────────────────────────────────────────────
def verify_cik(cik, fund_display_name):
    """Returns dict with verification outcome + captured fields."""
    sub = fetch_submissions(cik)
    if sub is None:
        return {'ok': False, 'reason': 'submissions_fetch_failed'}
    name = sub.get('name','')
    sic = sub.get('sic','')
    et  = sub.get('entityType','')
    fye = sub.get('fiscalYearEnd','')
    fmt = sub.get('formerNames') or []
    recent = sub.get('filings',{}).get('recent',{})
    forms = recent.get('form', []) or []
    has_10k_or_10 = any(f.startswith('10-K') or f=='10' for f in forms)
    score = name_score(fund_display_name, name)
    flags = []
    if not has_10k_or_10:
        flags.append('no_10K_in_recent')
    if sic and sic != '6726':
        flags.append(f'sic_not_6726:{sic}')
    if score < 30:
        flags.append('name_mismatch_hard')
    elif score < 60:
        flags.append('name_mismatch_soft')
    return {
        'ok': True,
        'cik': str(cik).zfill(10),
        'sec_name': name,
        'sec_former_names': fmt,
        'sic': sic,
        'entity_type': et,
        'fiscal_year_end': fye,
        'name_score': score,
        'has_10K_in_recent': has_10k_or_10,
        'recent_form_count': len(forms),
        'flags': flags,
    }

# ───────────────────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────────────────
def main():
    fd_path = UNI/'fund_directory.json'
    fd = json.load(open(fd_path))
    funds = fd['funds']
    existing_cik = {f['ticker']: f.get('cik') for f in funds}

    ticker_map = step1_load_masters()

    audit = []
    resolved = {}  # ticker → resolved record

    print('\nSTEP 2 — matching traded BDCs by ticker', flush=True)
    for f in funds:
        if f.get('fund_type') != 'traded': continue
        tk = (f.get('real_ticker') or f.get('ticker') or '').upper()
        cand = ticker_map.get(tk)
        if not cand and f.get('ticker') and f['ticker'].upper() != tk:
            cand = ticker_map.get(f['ticker'].upper())
        record = {'ticker': f['ticker'], 'display_name': f['display_name'],
                  'fund_type': 'traded', 'method': None, 'cik': None,
                  'cik_status': 'unresolved', 'reason': '', 'verification': None}
        if cand:
            record['method'] = 'ticker_master'
            record['cik'] = cand['cik']
            record['matched_ticker'] = tk
            record['source_url'] = cand['source']
            v = verify_cik(cand['cik'], f['display_name'])
            record['verification'] = v
            if v.get('ok'):
                record['cik_status'] = 'resolved'
        else:
            record['reason'] = f'ticker {tk!r} not in SEC master file'
        resolved[f['ticker']] = record

    print('\nSTEP 3 — matching nontraded BDCs by name', flush=True)
    for f in funds:
        if f.get('fund_type') != 'nontraded': continue
        record = {'ticker': f['ticker'], 'display_name': f['display_name'],
                  'fund_type': 'nontraded', 'method': None, 'cik': None,
                  'cik_status': 'unresolved', 'reason': '', 'verification': None,
                  'candidates': []}

        # If directory already has a CIK, validate it as the primary candidate
        existing = existing_cik.get(f['ticker'])
        candidates = []
        if existing:
            v = verify_cik(existing, f['display_name'])
            candidates.append({'cik': str(existing).zfill(10), 'source': 'existing_directory', 'verification': v})

        # Also try EDGAR search by display_name
        search_q = MANUAL_HINTS.get(f['ticker']) or f['display_name']
        hits = edgar_search(search_q)
        for h in hits[:5]:
            if any(c['cik'] == h['cik'] for c in candidates): continue
            v = verify_cik(h['cik'], f['display_name'])
            candidates.append({'cik': h['cik'], 'source': 'edgar_search',
                               'edgar_hit_name': h['name'], 'verification': v})

        # Pick best candidate: prefer one that passes verification with highest name_score
        def candrank(c):
            v = c.get('verification') or {}
            if not v.get('ok'): return -1
            score = v.get('name_score', 0)
            # bonus for SIC 6726 and existence of 10-K
            if v.get('sic') == '6726': score += 10
            if v.get('has_10K_in_recent'): score += 5
            return score
        candidates.sort(key=candrank, reverse=True)
        record['candidates'] = candidates
        if candidates and candrank(candidates[0]) >= 30:
            top = candidates[0]
            record['method'] = top['source']
            record['cik'] = top['cik']
            record['verification'] = top['verification']
            record['cik_status'] = 'resolved'
        else:
            record['reason'] = 'no candidate scored >= 30'
        resolved[f['ticker']] = record

    print('\nSTEP 4 — explicit searches for the 6 known-tricky tickers', flush=True)
    for tk in ['ASCF','ASCFI','ASIF','CCSI','GS_PCC','TROW_OHA']:
        if tk not in resolved: continue
        rec = resolved[tk]
        if rec.get('cik_status') == 'resolved': continue
        # Run a fresh search with the manual hint name
        hint = MANUAL_HINTS.get(tk)
        if not hint: continue
        hits = edgar_search(hint)
        for h in hits[:5]:
            if any(c['cik'] == h['cik'] for c in rec.get('candidates') or []): continue
            v = verify_cik(h['cik'], hint)
            rec.setdefault('candidates', []).append({
                'cik': h['cik'], 'source': 'edgar_search_manual_hint',
                'hint': hint, 'edgar_hit_name': h['name'], 'verification': v})
        # Re-rank
        def crank(c):
            v = c.get('verification') or {}
            if not v.get('ok'): return -1
            return v.get('name_score',0) + (10 if v.get('sic')=='6726' else 0) + (5 if v.get('has_10K_in_recent') else 0)
        rec['candidates'].sort(key=crank, reverse=True)
        if rec['candidates'] and crank(rec['candidates'][0]) >= 30:
            top = rec['candidates'][0]
            rec['method'] = top['source']
            rec['cik'] = top['cik']
            rec['verification'] = top['verification']
            rec['cik_status'] = 'resolved'
        else:
            rec['cik_status'] = 'no_filer_confirmed'
            rec['reason'] = f'no SEC filer matches manual hint {hint!r}'

    # ─── STEP 5 — global validation ───
    print('\nSTEP 5 — global validation', flush=True)
    resolved_count = sum(1 for r in resolved.values() if r.get('cik_status')=='resolved')
    no_filer = sum(1 for r in resolved.values() if r.get('cik_status')=='no_filer_confirmed')
    unresolved = sum(1 for r in resolved.values() if r.get('cik_status') not in ('resolved','no_filer_confirmed'))

    cik_collisions = Counter()
    for r in resolved.values():
        if r.get('cik'): cik_collisions[r['cik']] += 1
    dupes = {c:n for c,n in cik_collisions.items() if n > 1}

    # Compare to existing directory
    changes = []
    for tk, r in resolved.items():
        new = r.get('cik')
        old = existing_cik.get(tk)
        if not new and not old: continue
        if old == new: continue
        changes.append({'ticker': tk, 'display_name': r['display_name'],
                        'old_cik': old, 'new_cik': new,
                        'reason': r.get('reason') or r.get('method') or 'resolved'})

    # Name divergences (only for resolved)
    divergences = []
    for tk, r in resolved.items():
        if r.get('cik_status') != 'resolved': continue
        v = r.get('verification') or {}
        if not v.get('sec_name'): continue
        score = v.get('name_score', 100)
        if score < 70:
            divergences.append({
                'ticker': tk,
                'display_name': r['display_name'],
                'sec_name': v['sec_name'],
                'name_score': score,
                'cik': r['cik'],
                'sec_former_names': v.get('sec_former_names', []),
            })

    # SIC mismatches
    sic_flags = []
    for tk, r in resolved.items():
        if r.get('cik_status') != 'resolved': continue
        v = r.get('verification') or {}
        if v.get('sic') and v['sic'] != '6726':
            sic_flags.append({'ticker': tk, 'cik': r['cik'], 'sic': v['sic'],
                              'sec_name': v.get('sec_name','')})

    # Write audit log
    LOG_PATH.write_text(json.dumps({
        'generated_at': datetime.datetime.now().isoformat(),
        'sec_master_files_cached_in': str(CACHE),
        'resolved': resolved,
        'changes_vs_existing': changes,
        'duplicate_cik_collisions': dupes,
        'name_divergences': divergences,
        'sic_flags': sic_flags,
        'summary': {
            'total': len(resolved),
            'resolved': resolved_count,
            'no_filer_confirmed': no_filer,
            'unresolved': unresolved,
        },
    }, indent=2))

    # ─── STEP 6 — print the report ───
    print('\n' + '='*70)
    print('CIK RESOLUTION REPORT')
    print('='*70)
    print(f'\nTotals:')
    print(f'  resolved:           {resolved_count}/{len(resolved)}')
    print(f'  no_filer_confirmed: {no_filer}')
    print(f'  unresolved:         {unresolved}')

    print(f'\nDuplicate CIK collisions: {len(dupes)}')
    for c,n in dupes.items():
        owners = [r['ticker'] for r in resolved.values() if r.get('cik')==c]
        print(f'  {c} claimed by {n} funds: {owners}')

    print(f'\nChanges vs. existing fund_directory.json: {len(changes)}')
    for ch in changes:
        print(f'  {ch["ticker"]:10s} {ch["display_name"][:42]:42s}  {ch["old_cik"] or "(none)":>10s} → {ch["new_cik"] or "(none)":>10s}  [{ch["reason"]}]')

    print(f'\nName divergences (display_name ≠ sec_name, score < 70): {len(divergences)}')
    for d in divergences:
        fmt = ''
        if d['sec_former_names']:
            fmt = ' formerNames=' + ','.join(f["name"] for f in d['sec_former_names'][:3])
        print(f'  {d["ticker"]:10s} score={d["name_score"]:3d}  {d["display_name"][:36]:36s}  ↔  {d["sec_name"][:44]:44s}{fmt}')

    print(f'\nSIC ≠ 6726 (unexpected for a BDC): {len(sic_flags)}')
    for s in sic_flags:
        print(f'  {s["ticker"]:10s} cik={s["cik"]} sic={s["sic"]} sec_name={s["sec_name"]}')

    print(f'\nUnresolved / no_filer_confirmed funds:')
    for r in resolved.values():
        if r['cik_status'] in ('unresolved','no_filer_confirmed'):
            print(f'  [{r["cik_status"]:22s}] {r["ticker"]:10s} {r["display_name"][:40]:40s} — {r["reason"]}')

    print(f'\nFull audit log written to: {LOG_PATH}')
    print(f'\nNOTHING WRITTEN TO fund_directory.json. Review the output above.')
    print(f'When you approve, run the apply step (separate script) to write CIKs + sec_* fields back.')

if __name__=='__main__':
    main()
