#!/usr/bin/env python3
"""Apply user-approved CIK resolution decisions.

Writes candidate file to data/universe/fund_directory.candidate.json
and prints a full pre-commit diff. Does NOT modify fund_directory.json.
"""
import json, pathlib, urllib.request, urllib.error, urllib.parse, time, datetime, re, gzip, sys
from collections import OrderedDict

ROOT  = pathlib.Path(__file__).resolve().parent.parent
UNI   = ROOT/'data'/'universe'
CACHE = UNI/'_sec_cache'
CACHE.mkdir(parents=True, exist_ok=True)
CANDIDATE_PATH = UNI/'fund_directory.candidate.json'

UA = 'BDC Intelligence research@bdcintelligence.ai'
SLEEP = 0.15

# ─────────────────────────────────────────────────────────────────────────
# User decisions
# ─────────────────────────────────────────────────────────────────────────
DELETIONS = [
    'CCSI',     # dupe of CCSO
    'GS_PCC',   # dupe of GCRED
    'BCIC',     # ghost — entity merged 2018, ticker now belongs to BCP Investment Corp
    'CSRC',     # SIC 6798 REIT, not a BDC
    'MSIF',     # broken row, replaced by new MSIF below
    'TROW_OHA', # duplicate of TBKCF (both = T. Rowe Price OHA Select Private Credit Fund, CIK 1901164)
]

REPOINTS = {
    # ANT_PCF / APCRE were swapped in the original directory.
    # SEC: 0001976336 = "Antares Private Credit Fund", 0001993402 = "Antares Strategic Credit Fund"
    'ANT_PCF': {'cik': '0001976336', 'display_name': 'Antares Private Credit Fund'},
    'APCRE':   {'cik': '0001993402', 'display_name': 'Antares Strategic Credit Fund'},
    'LPCL':    {'cik': '0002041841', 'display_name': 'Lord Abbett Private Credit Fund S'},
    # ADS existing CIK 0001634452 = "AB Private Credit Investors Corp" (wrong entity).
    # Real Apollo Debt Solutions BDC CIK from SEC ticker master:
    'ADS':     {'cik': '0001837532', 'display_name': 'Apollo Debt Solutions BDC'},
}

RENAMES_WITH_CIK_CONFIRM = {
    'OCIC':  {'display_name': 'Blue Owl Credit Income Corp.'},
    'MMAIP': {'display_name': 'MidCap Apollo Institutional Private Lending'},
    'PSMML': {'display_name': 'Phillip Street BDC LLC'},
    'ICMB':  {'display_name': 'Investcorp Credit Management BDC, Inc.',
              'cik': '0001578348'},  # ICMB had no CIK in directory; explicitly set
    'ACSL':  {'display_name': 'John Hancock Comvest Private Income Fund',
              'cik': '0001987221'},  # manual approve (already correct in dir)
}

# Net effect: delete old MSIF row, add a fresh one
NEW_ROWS = [
    {'ticker': 'MSIF', 'display_name': 'MSC Income Fund, Inc.',
     'fund_type': 'traded', 'manager': 'MSC Adviser I, LLC (Main Street Capital)',
     'real_ticker': 'MSIF', 'cik': '0001535778', 'exchange': None},
    # MSDL — ensure CIK is set (row exists with cik=None)
    {'ticker': 'MSDL', 'display_name': 'Morgan Stanley Direct Lending Fund',
     'fund_type': 'traded', 'manager': 'Morgan Stanley Direct Lending Fund Advisers LLC',
     'real_ticker': 'MSDL', 'cik': '0001782524', 'exchange': None},
    # AB Private Credit Investors Corp — real 1940-Act BDC, was mis-attached to ADS
    # previously (CIK 0001634452 was on ADS row). N-54A elected BDC; regular 10-K filer.
    {'ticker': 'ABPCIC', 'display_name': 'AB Private Credit Investors Corp',
     'fund_type': 'nontraded', 'manager': 'AllianceBernstein',
     'real_ticker': None, 'cik': '0001634452', 'exchange': None},
]

# Direct EDGAR-by-name lookups for the unresolved
SEARCH_OVERRIDES = {
    'OBDE':  ['Blue Owl Capital Corp III', 'Blue Owl Capital Corporation III'],
    'MRCC':  ['Monroe Capital Corporation'],
    'OSCF':  ['Owl Rock Senior Credit Fund'],
    'ASCF':  ['Ares Strategic Credit Fund'],
    'ASCFI': ['Ares Strategic Credit Fund II'],
    'ASIF':  ['Ares Strategic Income Fund'],
    'APCIF': ['Apollo Private Credit Income Fund'],
}

# OBTIC special case: OTIC isn't in directory, so the dedup conditional is moot.
# Keep OBTIC but realign display_name to SEC's recorded entity at that CIK.
OBTIC_REALIGN = True

# ─────────────────────────────────────────────────────────────────────────
# SEC helpers (cached)
# ─────────────────────────────────────────────────────────────────────────
def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding':'gzip, deflate'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if 'gzip' in r.headers.get('Content-Encoding',''):
                data = gzip.decompress(data)
            return data
    except Exception:
        return None

def fetch_submissions(cik):
    cik10 = str(cik).zfill(10)
    p = CACHE/f'sub_{cik10}.json'
    if p.exists():
        try: return json.loads(p.read_bytes())
        except: pass
    raw = http_get(f'https://data.sec.gov/submissions/CIK{cik10}.json')
    if not raw: return None
    try: d = json.loads(raw)
    except: return None
    p.write_bytes(json.dumps(d).encode('utf-8'))
    time.sleep(SLEEP)
    return d

def edgar_search(query):
    q = urllib.parse.quote_plus(query)
    p = CACHE/f'efts_{re.sub(r"[^A-Za-z0-9_]","_",query)[:80]}.json'
    if p.exists():
        try: return json.loads(p.read_bytes())
        except: pass
    raw = http_get(f'https://efts.sec.gov/LATEST/search-index?q=%22{q}%22&forms=10-K')
    if not raw:
        # try without form filter
        raw = http_get(f'https://efts.sec.gov/LATEST/search-index?q=%22{q}%22')
        if not raw: return []
    try: d = json.loads(raw)
    except: return []
    hits = d.get('hits',{}).get('hits',[])
    out = []; seen = set()
    for h in hits[:20]:
        src = h.get('_source',{})
        for c in src.get('ciks') or []:
            c10 = str(c).zfill(10)
            if c10 in seen: continue
            seen.add(c10)
            out.append({'cik': c10, 'name': (src.get('display_names') or [''])[0]})
    p.write_bytes(json.dumps(out).encode('utf-8'))
    time.sleep(SLEEP)
    return out

def load_ticker_master():
    p = CACHE/'company_tickers.json'
    if not p.exists():
        raw = http_get('https://www.sec.gov/files/company_tickers.json')
        if raw: p.write_bytes(raw); time.sleep(SLEEP)
    if not p.exists(): return {}
    d = json.loads(p.read_bytes())
    return {(v.get('ticker') or '').upper(): str(v.get('cik_str') or '').zfill(10)
            for v in d.values() if v.get('ticker') and v.get('cik_str')}

def normalize_name(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    s = re.sub(r'\b(inc|corp|corporation|llc|lp|ltd|company|co|fund|trust|the)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def name_score(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb: return 0
    if na == nb: return 100
    if na in nb or nb in na: return 80
    aw, bw = set(na.split()), set(nb.split())
    if not aw or not bw: return 0
    return int(len(aw & bw) / max(len(aw), len(bw)) * 70)

def capture_sec_fields(cik, fund_display_name):
    sub = fetch_submissions(cik)
    if not sub:
        return None
    forms = sub.get('filings',{}).get('recent',{}).get('form',[]) or []
    return {
        'sec_name': sub.get('name'),
        'sec_former_names': sub.get('formerNames', []),
        'sic': sub.get('sic',''),
        'entity_type': sub.get('entityType',''),
        'fiscal_year_end': sub.get('fiscalYearEnd',''),
        '_has_10K': any(f.startswith('10-K') or f=='10' for f in forms),
        '_name_score': name_score(fund_display_name, sub.get('name','') or ''),
    }

# ─────────────────────────────────────────────────────────────────────────
# Main apply flow
# ─────────────────────────────────────────────────────────────────────────
def main():
    fd_orig = json.load(open(UNI/'fund_directory.json'))
    orig_funds = fd_orig['funds']
    funds = OrderedDict((f['ticker'], dict(f)) for f in orig_funds)

    ticker_master = load_ticker_master()
    changes = []  # list of (action, ticker, detail)
    cik_source_map = {}  # ticker → 'ticker_master' | 'edgar_search' | 'user_repoint' | …
    today_iso = datetime.date.today().isoformat()

    # 1. Deletions
    for tk in DELETIONS:
        if tk in funds:
            display = funds[tk].get('display_name')
            funds.pop(tk)
            changes.append(('DELETE', tk, display))

    # 2. Repointings
    for tk, override in REPOINTS.items():
        if tk not in funds: continue
        f = funds[tk]
        old_cik = f.get('cik'); old_name = f.get('display_name')
        f['cik'] = override['cik']
        if 'display_name' in override:
            f['display_name'] = override['display_name']
        sec = capture_sec_fields(override['cik'], f['display_name'])
        if sec:
            f['sec_name'] = sec['sec_name']
            f['sec_former_names'] = sec['sec_former_names']
            f['sic'] = sec['sic']
            f['entity_type'] = sec['entity_type']
            f['fiscal_year_end'] = sec['fiscal_year_end']
        cik_source_map[tk] = 'user_repoint'
        changes.append(('REPOINT', tk,
            f'cik {old_cik or "(none)"} → {override["cik"]}; name "{old_name}" → "{f["display_name"]}"'))

    # 3. Renames (+ optional CIK confirm)
    for tk, override in RENAMES_WITH_CIK_CONFIRM.items():
        if tk not in funds: continue
        f = funds[tk]
        old_name = f.get('display_name')
        old_cik = f.get('cik')
        if 'cik' in override:
            f['cik'] = override['cik']
        if 'display_name' in override:
            f['display_name'] = override['display_name']
        cik = f.get('cik')
        if cik:
            sec = capture_sec_fields(cik, f['display_name'])
            if sec:
                f['sec_name'] = sec['sec_name']
                f['sec_former_names'] = sec['sec_former_names']
                f['sic'] = sec['sic']
                f['entity_type'] = sec['entity_type']
                f['fiscal_year_end'] = sec['fiscal_year_end']
        detail = f'name "{old_name}" → "{f["display_name"]}"'
        if old_cik != f.get('cik'):
            detail += f'; cik {old_cik or "(none)"} → {f.get("cik")}'
            cik_source_map[tk] = 'user_rename_with_cik'
        else:
            cik_source_map.setdefault(tk, 'directory_preserved_renamed')
        changes.append(('RENAME', tk, detail))

    # 4. OBTIC realignment
    if OBTIC_REALIGN and 'OBTIC' in funds:
        f = funds['OBTIC']
        old_name = f.get('display_name')
        cik = f.get('cik')
        if cik:
            sec = capture_sec_fields(cik, f['display_name'])
            if sec:
                f['sec_name'] = sec['sec_name']
                f['sec_former_names'] = sec['sec_former_names']
                f['sic'] = sec['sic']
                f['entity_type'] = sec['entity_type']
                f['fiscal_year_end'] = sec['fiscal_year_end']
                # Realign display_name to SEC name (the real entity at this CIK)
                f['display_name'] = sec['sec_name'] or old_name
                cik_source_map['OBTIC'] = 'directory_preserved_realigned'
                changes.append(('REALIGN', 'OBTIC',
                    f'name "{old_name}" → "{f["display_name"]}" (OTIC not in directory; OBTIC kept as canonical row for this CIK)'))

    # 5. New rows / upserts
    for new in NEW_ROWS:
        tk = new['ticker']
        if tk in funds:
            f = funds[tk]
            changed_fields = []
            for k,v in new.items():
                if k == 'ticker': continue
                if f.get(k) != v:
                    changed_fields.append(f'{k}={f.get(k)!r}→{v!r}')
                    f[k] = v
            sec = capture_sec_fields(new['cik'], f['display_name'])
            if sec:
                f['sec_name'] = sec['sec_name']
                f['sec_former_names'] = sec['sec_former_names']
                f['sic'] = sec['sic']
                f['entity_type'] = sec['entity_type']
                f['fiscal_year_end'] = sec['fiscal_year_end']
            cik_source_map[tk] = 'user_upsert'
            if changed_fields:
                changes.append(('UPSERT', tk, '; '.join(changed_fields)))
            else:
                changes.append(('UPSERT', tk, '(already present, no field changes)'))
        else:
            funds[tk] = dict(new)
            sec = capture_sec_fields(new['cik'], new['display_name'])
            if sec:
                funds[tk]['sec_name'] = sec['sec_name']
                funds[tk]['sec_former_names'] = sec['sec_former_names']
                funds[tk]['sic'] = sec['sic']
                funds[tk]['entity_type'] = sec['entity_type']
                funds[tk]['fiscal_year_end'] = sec['fiscal_year_end']
            cik_source_map[tk] = 'user_add'
            changes.append(('ADD', tk, f'new row: {new["display_name"]} cik={new["cik"]}'))

    # 6. Direct EDGAR-by-name lookups for remaining unresolved.
    # APCIF has wrong CIK (= ADS's). OSCF has wrong CIK (= Oaktree Strategic Credit Fund).
    # Force re-resolve for both regardless of existing CIK.
    FORCE_SEARCH = {'APCIF', 'OSCF'}
    for tk, queries in SEARCH_OVERRIDES.items():
        if tk not in funds: continue
        f = funds[tk]
        if f.get('cik') and tk not in FORCE_SEARCH:
            continue
        if tk in FORCE_SEARCH:
            f['cik'] = None  # clear known-wrong CIK before re-resolving
        best = None
        for q in queries:
            hits = edgar_search(q)
            for h in hits[:5]:
                sub = fetch_submissions(h['cik'])
                if not sub: continue
                sec_name = sub.get('name','') or ''
                score = name_score(f['display_name'], sec_name)
                # Bonuses
                if sub.get('sic') == '6726': score += 10
                forms = sub.get('filings',{}).get('recent',{}).get('form',[]) or []
                if any(fm.startswith('10-K') or fm=='10' for fm in forms): score += 5
                cand = {'cik': h['cik'], 'sec_name': sec_name, 'sub': sub,
                        'score': score, 'query': q}
                if best is None or score > best['score']:
                    best = cand
        if best and best['score'] >= 30:
            f['cik'] = best['cik']
            f['sec_name'] = best['sub'].get('name')
            f['sec_former_names'] = best['sub'].get('formerNames', [])
            f['sic'] = best['sub'].get('sic','')
            f['entity_type'] = best['sub'].get('entityType','')
            f['fiscal_year_end'] = best['sub'].get('fiscalYearEnd','')
            cik_source_map[tk] = 'edgar_search'
            changes.append(('RESOLVE', tk,
                f'cik {best["cik"]} via query "{best["query"]}" score={best["score"]} sec_name="{best["sec_name"]}"'))
        else:
            # Per-fund fallbacks. APCIF is a known feeder of ADS.
            # For ASCF/ASCFI/OSCF: quoted EFTS returned 0 hits → no separate SEC filer exists.
            if tk == 'APCIF':
                f['cik_status'] = 'feeder_no_separate_filings'
                f['parent_cik'] = '0001837532'  # ADS
                changes.append(('FLAG', tk, 'feeder_no_separate_filings, parent_cik=0001837532 (ADS)'))
            elif tk in ('OSCF','ASCF','ASCFI'):
                f['cik_status'] = 'no_filer_confirmed'
                changes.append(('FLAG', tk, f'no_filer_confirmed (quoted EFTS returned 0 hits for {queries!r})'))
            else:
                f['cik_status'] = 'unresolved'
                changes.append(('UNRESOLVED', tk, f'no candidate scored ≥ 30; best={best!r}'))

    # 7. Fix ADS (and any other) via ticker-master lookup if cik wrong/missing
    # ADS existing CIK 0001634452 is Antares Holdings (wrong). Look up via real_ticker.
    for tk, f in list(funds.items()):
        if f.get('cik'):
            # verify this CIK isn't a known-wrong one
            existing_cik = f['cik']
            sub = fetch_submissions(existing_cik)
            if sub:
                sec_name = sub.get('name','') or ''
                score = name_score(f['display_name'], sec_name)
                # If name divergence is severe AND we have a ticker that resolves better, fix it
                if score < 30:
                    real_tk = (f.get('real_ticker') or f.get('ticker') or '').upper()
                    master_cik = ticker_master.get(real_tk)
                    if master_cik and master_cik != existing_cik:
                        master_sub = fetch_submissions(master_cik)
                        if master_sub:
                            master_score = name_score(f['display_name'], master_sub.get('name','') or '')
                            if master_score > score:
                                f['cik'] = master_cik
                                f['sec_name'] = master_sub.get('name')
                                f['sec_former_names'] = master_sub.get('formerNames', [])
                                f['sic'] = master_sub.get('sic','')
                                f['entity_type'] = master_sub.get('entityType','')
                                f['fiscal_year_end'] = master_sub.get('fiscalYearEnd','')
                                cik_source_map[tk] = 'ticker_master_autofix'
                                changes.append(('AUTOFIX', tk,
                                    f'cik {existing_cik} (sec_name "{sec_name}", score {score}) → '
                                    f'{master_cik} (sec_name "{master_sub.get("name")}", score {master_score})'))
            # If we didn't change anything, ensure source defaults to directory_preserved
            cik_source_map.setdefault(tk, 'directory_preserved')
            continue
        # No CIK: try ticker master
        real_tk = (f.get('real_ticker') or f.get('ticker') or '').upper()
        master_cik = ticker_master.get(real_tk)
        if master_cik:
            f['cik'] = master_cik
            sec = capture_sec_fields(master_cik, f['display_name'])
            if sec:
                f['sec_name'] = sec['sec_name']
                f['sec_former_names'] = sec['sec_former_names']
                f['sic'] = sec['sic']
                f['entity_type'] = sec['entity_type']
                f['fiscal_year_end'] = sec['fiscal_year_end']
            cik_source_map[tk] = 'ticker_master'
            changes.append(('TICKER_MATCH', tk, f'cik={master_cik} via ticker_master sec_name="{f.get("sec_name")}"'))

    # 8. Capture sec_* for everyone else (already has CIK but no sec_name yet)
    for tk, f in funds.items():
        if 'sec_name' in f: continue
        cik = f.get('cik')
        if not cik: continue
        sec = capture_sec_fields(cik, f.get('display_name',''))
        if sec:
            f['sec_name'] = sec['sec_name']
            f['sec_former_names'] = sec['sec_former_names']
            f['sic'] = sec['sic']
            f['entity_type'] = sec['entity_type']
            f['fiscal_year_end'] = sec['fiscal_year_end']
        cik_source_map.setdefault(tk, 'directory_preserved')

    # 9. Stamp audit fields cik_status, cik_source, cik_resolved_at on every fund
    for tk, f in funds.items():
        if f.get('cik'):
            f.setdefault('cik_status', 'resolved')
        else:
            # Preserve no_filer_confirmed / feeder_no_separate_filings flags set earlier
            f.setdefault('cik_status', 'unresolved')
        f['cik_source'] = cik_source_map.get(tk, 'directory_preserved')
        f['cik_resolved_at'] = today_iso

    # Build candidate
    funds_out = list(funds.values())
    new_fd = {
        'last_updated': datetime.date.today().isoformat(),
        'total': len(funds_out),
        'by_type': {
            'traded':    sum(1 for f in funds_out if f.get('fund_type')=='traded'),
            'nontraded': sum(1 for f in funds_out if f.get('fund_type')=='nontraded'),
        },
        'funds': funds_out,
    }
    CANDIDATE_PATH.write_text(json.dumps(new_fd, indent=2))

    # ─── Diff report ───
    print('='*72)
    print('PRE-COMMIT DIFF — fund_directory.candidate.json')
    print('='*72)
    print(f'\nCounts:')
    print(f'  original total:     {len(orig_funds)}  (traded {fd_orig.get("by_type",{}).get("traded")} / nontraded {fd_orig.get("by_type",{}).get("nontraded")})')
    print(f'  candidate total:    {new_fd["total"]}  (traded {new_fd["by_type"]["traded"]} / nontraded {new_fd["by_type"]["nontraded"]})')
    print(f'  changes recorded:   {len(changes)}')
    print()
    by_action = {}
    for action, tk, detail in changes:
        by_action.setdefault(action, []).append((tk, detail))
    for action in ['DELETE','REPOINT','RENAME','REALIGN','UPSERT','ADD','RESOLVE','TICKER_MATCH','AUTOFIX','FLAG','UNRESOLVED']:
        if action not in by_action: continue
        print(f'── {action} ({len(by_action[action])}) ──')
        for tk, detail in by_action[action]:
            print(f'  {tk:10s} {detail}')
        print()

    # Final state check: every fund's CIK status + sec_name mismatch flags
    print('── FINAL STATE ──')
    no_cik = []; bad_sic = []; soft_mismatch = []; hard_mismatch = []
    for f in funds_out:
        cik = f.get('cik')
        status = f.get('cik_status','resolved' if cik else 'unresolved')
        if not cik: no_cik.append((f['ticker'], status, f.get('display_name')))
        sic = f.get('sic','')
        if cik and sic and sic != '6726':
            bad_sic.append((f['ticker'], sic, f.get('sec_name')))
        if cik and f.get('sec_name'):
            sc = name_score(f.get('display_name',''), f.get('sec_name',''))
            if sc < 30: hard_mismatch.append((f['ticker'], sc, f.get('display_name'), f.get('sec_name')))
            elif sc < 70: soft_mismatch.append((f['ticker'], sc, f.get('display_name'), f.get('sec_name')))

    print(f'\nFunds without CIK ({len(no_cik)}):')
    for tk,st,dn in no_cik:
        print(f'  {tk:10s} status={st:30s} {dn}')

    print(f'\nFunds with SIC ≠ 6726 ({len(bad_sic)}):')
    for tk,sic,name in bad_sic:
        print(f'  {tk:10s} sic={sic} sec_name={name}')

    print(f'\nHard name mismatches (score < 30, {len(hard_mismatch)}):')
    for tk,sc,dn,sn in hard_mismatch:
        print(f'  {tk:10s} score={sc:3d}  display: "{dn}"  ↔  sec_name: "{sn}"')

    print(f'\nSoft name mismatches (30 ≤ score < 70, {len(soft_mismatch)}):')
    for tk,sc,dn,sn in soft_mismatch:
        print(f'  {tk:10s} score={sc:3d}  display: "{dn}"  ↔  sec_name: "{sn}"')

    # CIK collisions
    from collections import Counter
    cik_count = Counter(f['cik'] for f in funds_out if f.get('cik'))
    dupes = {c:n for c,n in cik_count.items() if n>1}
    print(f'\nCIK collisions: {len(dupes)}')
    for c,n in dupes.items():
        owners = [f['ticker'] for f in funds_out if f.get('cik')==c]
        print(f'  {c} claimed by {owners}')

    print(f'\nCandidate written to {CANDIDATE_PATH}')
    print('Run scripts/commit_directory.py (separate step) to copy candidate → fund_directory.json.')

if __name__=='__main__':
    main()
