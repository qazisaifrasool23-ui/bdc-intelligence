# Phase 3 — non-accrual rollforward extraction outcome

## Summary

Both fields remain at **0% coverage**:
- `na_new_additions_mn`
- `na_resolutions_mn`

Two extraction attempts (`enrich_phase3_nonaccrual.py`) were made and both
were reverted because the values produced were not real rollforward data.

## Attempt 1 — initial parser

Searched the Notes-to-Financial-Statements section for non-accrual headers
plus FORMAT A/B/C anchor phrases (`Additions`, `Removals`, `Placed on
non-accrual`, etc.). Walked forward to the next number-bearing line.

**Failure mode**: in BeautifulSoup-stripped 10-Q text, the line immediately
after a label like `Additions` is often a footnote marker — `(1)`, `(2)`,
`1`, `2` — not a dollar value. The parser grabbed those small integers.

Examples of garbage produced:
- TRIN multiple quarters: `additions=1.0, resolutions=2.0` (footnote refs)
- FDUS multiple quarters: `additions=0.002, resolutions=0.003`
- NMFC Q3 2021: `additions=17160` (accession-number digits)

## Attempt 2 — footnote-skipping parser

Added rules to skip lines matching `^\(?\s*\d{1,2}\s*\)?$` (footnote markers)
and to require dollar-formatted values (`$`-prefix, comma-formatted, or
multi-decimal). Re-ran end-to-end.

**Failure mode**: the next dollar-shaped tokens after a label are frequently
**dates** (`March 31, 2024` → after stripping commas/punctuation becomes
fragments like `3.31.2024` or `302.024`) or **years** (`2023`, `2024`).
Asymmetric extraction (CION/TRIN/WHF showed 0 additions but many
"resolutions") was the giveaway — real rollforwards have ~equal additions
and resolutions over time.

Examples of garbage produced:
- CION Q1 2020: `resolutions=312.02` — clearly the date 3/12/2020 parsed
- WHF Q1 2024: `resolutions=2.024` — clearly the year 2024
- TRIN Q3 2021: `resolutions=302021.0` — date-like junk

## Why this is hard

BDC non-accrual rollforward tables exist in 10-Q Notes, but:

1. **Layout is lost** when BeautifulSoup strips HTML. A table that visually
   reads `Beginning $X / Additions $Y / Removals $(Z) / Ending $W` becomes
   an unstructured stream of label lines and number lines, intermixed with
   footnote markers, period-end dates, and column headers.

2. **Heterogeneous formats across funds.** ARCC, FSK, OBDC, OCSL, GBDC,
   and BBDC each present their non-accrual disclosure differently. A
   single regex strategy can't cover all of them.

3. **Many funds don't disclose a quarterly rollforward at all** — only the
   ending balance. So even with a perfect extractor, the realistic ceiling
   is probably ~10-15 funds out of 47.

## Realistic paths to non-zero coverage

1. **LLM-API reading** (claude-haiku-4-5 via Anthropic API): pass the
   non-accrual section text and ask for additions/resolutions in $M
   at cost. Estimated cost ~$5-15 for the full 47-fund × 24-quarter pass.
   Quality would be high because the LLM understands table layout.

2. **HTML-aware table extractor**: instead of BeautifulSoup stripping,
   parse the HTML `<table>` elements directly, identify rollforward
   columns by header text, and extract cell values by row label. More
   engineering effort but no LLM cost.

3. **Hand curation for the 10-15 funds that disclose**: compile a
   per-fund prompt template, manually verify a handful of quarters,
   and accept null for the rest.

## What this directory contains

- `enrich_phase3_nonaccrual.py`: kept in-repo for reference, but the
  pattern-based approach is documented as unreliable.
- `data/logs/llm_extraction_log.csv`: contains 94 metadata rows
  (one per fund per field) tagged `phase3-attempt` explaining the
  null state.
- `data/logs/phase3_progress.json`: empty (any future run starts fresh).

## Net effect on the database

`na_new_additions_mn` and `na_resolutions_mn` remain null across all
1,084 quarter-records. Per the rule "null over fabrication — always",
this is the correct state. No false positives leaked into the timeseries.
