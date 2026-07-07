# Claude Code enrichment task — headlines + credit signals (free, no API key)

You are enriching SEC filings for the Credit Canon news feed. This runs inside
Claude Code on the user's machine, so it uses their Claude subscription, not an
API key. Work through this end to end.

## The loop
1. Run: `python scrapers/enrich_prep.py --limit 60`
   (fetches text for up to 60 un-enriched filings into `data/news/press/_enrich_queue.json`)
2. Read `data/news/press/_enrich_queue.json`. It is a list of filings, each:
   `{ "id", "ticker", "name", "form", "date", "url", "excerpt" }`
3. For EVERY item, produce three fields from the `excerpt` (and `form`):
   - **headline** — one crisp, factual line, under 16 words, no trailing period,
     no "Current report" boilerplate. Say what actually happened. Lead with the
     concrete fact if there is one (NAV, NII, non-accruals, dividend, a deal, a
     departure). Examples:
       - "NAV per share fell 4% as three portfolio loans went on non-accrual"
       - "Priced $600M of unsecured notes due 2031 at 6.25%"
       - "CFO departed; board named an interim replacement"
       - "Q3 net investment income covered the dividend at 1.08x"
   - **signal** — exactly one of `clean`, `watch`, `negative`. Judge on FACTS
     disclosed in the filing, NOT on how upbeat management sounds. Management spin
     must never move the signal up.
       - `negative` (red) — a real credit-negative disclosure: restatement or
         non-reliance on prior financials, asset impairment/write-down, covenant
         breach or waiver, going-concern doubt, default/acceleration, delisting,
         a dividend/distribution cut, a clear rise in non-accruals, or a jump in
         PIK income.
       - `watch` (yellow) — elevated but not acute, or genuinely mixed: leverage
         creeping up, non-accruals ticking modestly higher, amend-and-extend
         activity, a named risk that isn't yet a loss, guidance softening.
       - `clean` (green) — routine, no credit-negative disclosure: in-line
         results, ordinary offerings, routine governance 8-Ks, dividend declared
         as normal.
   - **signal_note** — under 10 words naming the reason, e.g.
     "Non-accruals rose to 4.1%", "Prior financials restated", "Routine quarterly results".
   If the excerpt is empty or unreadable, use `signal: "clean"`,
   `signal_note: "No adverse disclosure found"`, and a headline from the form + date.
4. Write ALL results to `data/news/press/_enrich_results.json` as a JSON object
   keyed by each item's `id`:
   ```json
   {
     "https://www.sec.gov/.../a8k.htm": {
       "headline": "NAV per share fell 4% on three new non-accruals",
       "signal": "negative",
       "signal_note": "Non-accruals rose to 4.1%"
     }
   }
   ```
5. Run: `python scrapers/enrich_apply.py`
   (merges your results into big.json + the by_fund files, then clears the queue)
6. Repeat from step 1 until `enrich_prep.py` prints "nothing left to enrich".

## Rules
- Do the whole batch in one pass. Don't skip items.
- Be conservative on `negative` — only when the filing actually discloses the bad
  fact. When unsure between two levels, pick the lower-severity one and say why in
  the note.
- Never invent numbers. If a figure isn't in the excerpt, don't cite it.
- The big feed (big.json) filings come first in the queue — those are the most
  visible, so even one or two batches noticeably improves the site.
