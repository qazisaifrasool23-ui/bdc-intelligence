# SOI Recovery Triage — V2 → V1 `data/soi/`

_Generated 2026-05-27. Records which quarantined Schedule-of-Investments (SOI) filings
were recovered into `data/soi/`, which were deferred, and why. Every recovery passes the
**same balance-sheet tie gate** that quarantined the data in the first place:
`|Σtranche_fv − bs_total| ≤ max($2mn, 2% of bs_total)`. Nothing was forced past that gate._

## Outcome at a glance

| | Funds matched to V1 | Snapshots | Holdings rows |
|---|---|---|---|
| Before | 100 | 404 | 109,729 |
| **After** | **102** | **413** | **110,997** |

Net new joins: **TPVG, MRCC**. All other recovery attempts either pass the gate already
(none did beyond these) or remain quarantined for the documented reasons below.

## ✅ Recovered (cheap, done)

- **TPVG** — *parser fix.* TPVG's FY2025 10-K tags holdings with 3-segment identifiers
  `"Company | Type | Non-Affiliated"`. The extractor mis-classified this as BCRED style and
  treated every `"Non-Affiliated"` (a normal noncontrolled holding) as an *unrecognized JV*,
  silently dropping 95 holdings / $645M → −82% mismatch. Added a `pipe3` identifier style to
  `extract_soi.py` (`detect_style` + `parse_identifier`). Validated: ARCC/BCRED/MAIN ties
  unchanged. **FY2025 now ties (Σ=783.4 vs bs=783.5, 333 holdings, correct company names)**;
  the most-recent 10-Q also loads. 2 captured snapshots + 3 gaps.
- **MRCC** — *crawl.* Was absent from the V2 universe (it **withdrew its BDC election**,
  N-54C 2026-04-14, so V2 excluded it). Crawled its iXBRL-era filings; **FY2024 (331 holdings)
  and FY2025 (267) pass the tie and load.** FY2022/FY2023 quarantine on look-through (+16%, +7.5%).
  Historical SOI (filed while a BDC) is valid; the fund is no longer a BDC going forward.

## ⚠️ Crawled but quarantined (gate rejected — not joined)

- **CSWC** — crawled FY2023–FY2026; **all four fail the tie** (+16%, +11%, +5.4%, −4.x%).
  Carries a consolidated credit-fund JV (look-through) — same unsolved pattern as FSK below.
- **LRFIN** — crawled; FY2023/FY2024 fail on look-through (+14%, +17%); FY2022 is cover-only
  iXBRL (no tagged tranches). Also **withdrew BDC election** (N-54C 2025-07-15).

## ⛔ Deferred — hard tier (no recovery that passes the gate exists yet)

- **RAND** — *not* a balance-sheet-total wobble (my initial triage was wrong). The filing's own
  iXBRL tags investments-at-FV = 48.5 under two agreeing concepts (`bs_total` is correct), but
  the tranche side over-counts and **no dedup level reconciles** (L1 +9.8%, L2 −19.5%), noisy/
  sign-flipping across years. Multi-axis double-count; needs the unsolved look-through logic.
- **FSK, HTGC, CGBD, WHF, PFLT, PNNT** — genuine JV / credit-fund look-through. `soi_dedup_lab.py`
  measured every candidate structural rule across 104 quarantined mismatch filings:
  **no rule recovers more than 1**, and the aggressive rules (`ps`, `best_ps`) overshoot 5–6
  (drop real data). Residuals after the best rule are +27% → +686%. This is unsolved research;
  any fund-specific hack would overfit and/or fail the tie.
- **TPVG FY2022–FY2024** — different tagging again: holdings under custom `tpvg:PortfolioCompaniesAxis`
  explicit members across up to 4 axes (industry × type × instrument), not the typed
  `InvestmentIdentifierAxis`. Needs a multi-axis leaf-selection parser — deferred. (FY2025+ uses
  the standard typed axis and is recovered above.)
- **HRZN, OXSQ, SSSS** — cover-only iXBRL: SOI not tagged at the holding level; recovering needs
  an HTML-table SOI parser (same class of work as pre-2023 plain-HTML).

## ⏭️ Skipped (not worth crawling)

- **OBDE** — absorbed into OBDC (Jan 2025); ≤1 clean iXBRL annual; defunct entity.
- **EQS** — tiny legacy fund; primary 10-Ks are plain-HTML (non-iXBRL); only 10-K/A amendments
  tagged. High effort, negligible coverage.

## Code change

`extract_soi.py`: added `pipe3` identifier style (3-segment `Company | Type | Control`).
Validated against ARCC/BCRED/MAIN (ties unchanged) before applying. A future full
`extract_soi.py --replace` run would apply `pipe3` fund-wide (may surface additional
TPVG-style recoveries beyond TPVG itself).

## Provenance / safety

- DB backed up to `bdc.duckdb.pre_recovery_20260527.bak`; manifest + V2 universe to
  `*.pre_crawl.bak` before changes.
- All writes idempotent (DELETE-then-INSERT per `filing_accession`).
- V2 universe gained 3 entries (MRCC/CSWC/LRFIN); manifest gained 37 crawled filings.
