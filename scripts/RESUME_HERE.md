# Enrichment Resumption Checkpoint

Last paused: 2026-05-15. The pipeline is **idempotent** — every script
checks for existing non-null values and only fills gaps, so you can re-run
any phase safely without overwriting good data.

## What's already done

- **Phase 1 derivations** — `scripts/enrich_phase1.py` (2987 + 1414 + 106 + 62 = 4,569 derived cells filled across two runs)
- **Phase 2 XBRL** — `scripts/enrich_phase2_xbrl.py` (5,848 cells from data.sec.gov for 130/140 funds)
- **Phase 4 LLM v1** — `scripts/enrich_phase4_llm.py` with MAX_FILINGS_PER_FUND=5 (158 cells)
- **Phase 4 LLM v2** — same script, expanded to MAX_FILINGS_PER_FUND=12 + broader keyword list (115 additional cells)
- **Phase 6 spanGaps** — 88 datasets in traded_template.html + 56 in nontraded_template.html

**Cumulative cells filled across all phases: ≈10,690**
**Remaining priority-field nulls: 29,451 / 64,960 (45.3%)**

## Where the biggest gaps still live

Top fields by % missing (across all 140 funds, all quarters):

1. `spillover_per_share` 92.2%
2. `na_pct_cost` 82.2%
3. `na_pct_fv` 76.9%
4. `second_lien_pct` 73.6%
5. `pik_income_mn` 73.5%
6. `credit_facility_drawn_mn` 68.7%
7. `pik_pct` 68.0%
8. `equity_pct` 65.3%
9. `unused_capacity_mn` 63.2%
10. `cost_of_debt_pct` 62.8%

Most of these aren't standard XBRL tags — they live in narrative MD&A
sections and bespoke tables that vary fund-to-fund. The LLM was conservative
(returned null when ambiguous), so further gains require a different approach.

## Top 20 funds with most remaining gaps

NCAPI, EQS, SPCIB, MCLI, CSRC, TDLEN, MRCC_NT, SSSS, ACBDC, SCCAP,
HPCI, NSI, BPLEN, FSLEN, OXSQ, SCHOL, PFRAI, SHBDC, LRFIN, SMLM

These are mostly small non-traded BDCs with thin filings. Their data
density may be inherently limited.

## To resume

```bash
cd ~/bdc_research/bdc-intelligence

# Option A — broader LLM coverage (more text per filing, ~150K-char windows)
# Edit scripts/enrich_phase4_llm.py:
#   TEXT_LIMIT = 120000
#   WINDOW_AFTER = 5000
# Then: python3 scripts/enrich_phase4_llm.py

# Option B — fund-targeted scraper for top-gap funds
# Write per-fund parsers for NCAPI, EQS, SPCIB etc. — high effort, high yield
# for those specific funds.

# Option C — pull credit facility data from 8-K filings (separate from 10-Q)
# Many BDCs announce facility amendments via 8-K with structured data.

# After any data change, run Phase 5 re-derive:
python3 scripts/enrich_phase1.py
python3 scripts/final_report.py
```

## Funds with no SEC CIK (genuine private/composite tickers)

ASCF, ASCFI, ASIF, CCSI, GS_PCC, TROW_OHA, MRCC_NT (composite), TPPCP

These have no SEC presence under those tickers and can't be enriched via
SEC EDGAR. Data for these funds must come from manager reports or other
sources.
