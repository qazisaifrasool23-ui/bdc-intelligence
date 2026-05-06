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

---

## Phase 4 Findings (HTML Table Parser — May 2026)

After Phase 3 was reverted, a third attempt was built and tested:
`enrich_phase4_table_parser.py`. It addressed the root cause of Phase 3
by reading `<table>` elements directly with `pandas.read_html`, preserving
the row × column structure that BeautifulSoup HTML-stripping had flattened
into ambiguous text streams.

### Method

For each filing the parser:

1. Walks every `<table>` element in the document.
2. Filters to tables that mention "non-accrual" in the table body **or**
   in the preceding heading (the captured "caption" — table caption,
   prior siblings, parent's prior siblings).
3. Further filters to tables whose body contains rollforward labels
   (`Additions`, `Removals`, `Beginning`, `Ending`, `Placed on
   non-accrual`, `Removed from non-accrual`, etc.).
4. For each candidate, parses with `pandas.read_html`, locates the
   "amortized cost" / "principal" column (over fair value when both
   exist), and reads the additions and resolutions rows.

### Results

`--test` mode was run on the three highest-priority disclosure funds
(ARCC, FSK, OCSL) plus a survey of four more (NMFC, OBDC, CCAP, GBDC).
**Zero non-accrual rollforward tables were found in any of the seven funds.**

| Fund | Filing | Tables w/ "non-accrual" mentioned | Tables w/ rollforward labels | Real rollforward? |
|---|---|---:|---:|---|
| ARCC | Q1 2026 10-Q | 0 | 0 | no |
| OCSL | Q3 2025 10-K | 0 | 0 | no |
| FSK | Q4 2025 10-K | 2 | 0 | no |
| NMFC | Q1 2026 10-Q | 0 | 0 | no |
| OBDC | Q4 2025 10-K | 1 | 0 | no |
| CCAP | Q4 2025 10-K | 1 | 0 | no |
| GBDC | Q3 2025 10-K | 5 | 6 | no — see below |

### What BDCs DO disclose

- **Ending non-accrual balance** at cost (already captured as
  `na_dollar_amount_mn`).
- **% of portfolio on non-accrual** at cost and at fair value
  (already captured as `na_pct_cost` and `na_pct_fv`).
- **Loan-by-loan footnote markers** in the Schedule of Investments
  (an asterisk or numbered footnote next to the position; the footnote
  text says "this loan is on non-accrual status as of period end").

### What BDCs do NOT disclose

A quarterly Beginning / + Additions / − Removals / Ending rollforward
in any structured `<table>`, in any of the seven funds tested. This
disclosure simply isn't there to be extracted, regardless of the
extraction technology.

### GBDC exception note

GBDC's Q3 2025 10-K had six tables that matched both the "non-accrual"
substring and our rollforward-label regex. **All six were false positives**.
The matched tables were:

- *Weighted average rate of new investment fundings* (table about
  yields on new portfolio additions, not non-accrual)
- *Internal Performance Ratings* (the GC Advisors 1–5 rating definitions)
- Three tables (#110, #112, #163) where the "additions" word appears in
  a footnote describing the *investment-portfolio* rollforward (gross
  additions to the portfolio at cost), not non-accrual specifically.
  Worse, `pandas.read_html` returned `NaN` for nearly all data cells in
  these three tables — the modern XBRL-encoded structure is too deeply
  nested for `pandas.read_html` to parse meaningfully.

### Conclusion

`na_new_additions_mn` and `na_resolutions_mn` are not extractable from
public SEC filings at scale for the 47-fund traded BDC universe. Three
extraction technologies (text-pattern, footnote-skipping pattern,
HTML-aware table parser) have all converged on the same finding: the
data isn't disclosed.

The only viable paths to non-zero coverage on these two specific
fields are:

1. **LLM-API reading** (claude-haiku-4-5 via the Anthropic SDK) — would
   read the non-accrual section narrative and identify gross
   additions / resolutions where they're disclosed inline. Estimated
   cost ~$5–15 for a full 47-fund × ~25-quarter pass.
2. **Hand curation** for the rare quarters where a fund discloses a
   rollforward in narrative form rather than a table.

Both paths are deferred. Both fields remain null.

### Net effect

- `na_new_additions_mn`: 0 / 1,084 quarters (0% coverage)
- `na_resolutions_mn`: 0 / 1,084 quarters (0% coverage)

No false positives. The platform displays "—" for these fields with
the footnote: *Non-accrual activity not separately disclosed in
quarterly filings; only ending balance is reported.*

A derived substitute field, `net_na_change_mn`, is computed instead —
see `CALCULATION_STANDARDS.md`.
