# Headline Rewriting Workflow — Claude Code Driver

This file is the **prompt to paste into Claude Code** to rewrite News headlines.

## Setup (one time)

You need Claude Code installed and authenticated to your Anthropic Pro/Max account.
From your repo root, open Claude Code:

```bash
cd /path/to/bdc-intelligence
claude
```

Then paste the prompt below. Claude Code will run the steps autonomously.

---

## The prompt

Copy everything from `>>> START PROMPT` through `<<< END PROMPT` into Claude Code.

>>> START PROMPT

You are rewriting SEC 8-K filing headlines for the News page of BDC Intelligence,
a research product for credit analysts covering Business Development Companies.

Your goal: produce sharp, informative, WSJ-style news headlines from corporate
press releases. The user (a credit analyst) should be able to skim a feed of
these headlines and instantly know what happened.

### Workflow

1. Run `python3 scripts/rewrite_headlines.py stats` to see how many items still
   need headlines.

2. Get a batch of pending items:
   `python3 scripts/rewrite_headlines.py pending --limit 25`

3. For each item in the batch:
   a. Note the `ticker`, `accession`, `category`, current `title`, and `index_url`.
   b. Fetch the press release:
      `python3 scripts/rewrite_headlines.py fetch --index-url '<index_url>'`
   c. Read the returned text. The press release usually starts with a corporate
      headline ("Ares Capital Corporation Reports..."), then a dateline, then
      the lead paragraph. The lead paragraph is where the real news is.
   d. Write a WSJ-style headline. Style rules below.
   e. Also extract a one-sentence `snippet` (≤180 chars) capturing the key fact.

4. Once you've drafted all headlines in the batch, write a single Python script
   that calls `save_headlines()` with the full list of updates and run it.
   Use this template:

```python
import sys
sys.path.insert(0, 'scripts')
from rewrite_headlines import save_headlines

updates = [
    {"ticker": "ARCC", "accession": "0001193125-26-XXXXX",
     "headline_ai": "Ares Capital lifts dividend 4% as Q1 NII beats estimates",
     "snippet": "Q1 net investment income of $0.58/share vs $0.55 consensus; dividend raised to $0.50."},
    # ... more
]
print(save_headlines(updates))
```

5. After saving, run `stats` again to confirm progress. Repeat batches until
   you hit your time budget or pending = 0.

### Headline style rules (the most important part)

**Length:** 8–14 words. Hard cap at 16. WSJ headlines are short.

**Voice:** Active, present tense for news that just happened. "Ares lifts dividend"
not "Dividend was raised by Ares." Use "Ares" not "Ares Capital Corporation" —
the ticker chip already shows which fund it is, so the headline can be terse.

**Lead with the news, not the ceremony.** Bad: "Sixth Street Specialty Lending
Reports First Quarter 2026 Financial Results." Good: "Sixth Street Q1 NII tops
estimates as non-accruals tick higher" — assuming that's what the body says.

**Be specific where the numbers matter.** "Ares raises dividend to $0.50" beats
"Ares raises dividend." "Q1 NII of $0.58 beats $0.55 consensus" beats "Q1
earnings beat." Use specific numbers from the press release when they're
material. Round to whole percentages/cents as appropriate.

**Capture the credit analyst's lens.** What matters to someone evaluating a
BDC's credit health is: dividend coverage, non-accruals, leverage, NAV
direction, deployment vs. repayments, fee income. When the press release
mentions these, lead with them. "BCRED monthly NAV slips to $25.04 from $25.12"
is more useful than "Blackstone Private Credit reports May NAV."

**Be honest about ambiguous filings.** Many 8-Ks are pro-forma — auditor
changes, bylaw amendments, Reg FD disclosures of investor day slides. For
these, a clean factual headline is fine: "Ares changes auditor to PwC." Don't
manufacture drama.

**Categories already exist** in `it.category` — `earnings`, `dividend`,
`credit-event`, `ma`, `capital-markets`, `personnel`, `other`. Use that as a
guide for what type of news you're framing.

**Never speculate beyond the press release.** If the PR doesn't say *why* a
director resigned, your headline must not either. "Director X resigns from
board" is the ceiling; "Director X resigns amid strategy dispute" is invented
unless the PR says so.

**If `fetch_pr_body` returns `found: false`** (no EX-99.1 attached), don't make
up a headline. Set `headline_ai` to empty string `""`. The page will fall back
to the raw item-code title. Better honest blank than fabricated.

### Edge cases to handle gracefully

- **Earnings 8-Ks**: lead with the most-watched metric. For BDCs, that's NII
  per share, NAV/share change Q/Q, and dividend coverage. If the PR gives those,
  use them.

- **Dividend declarations**: include the dollar amount and direction vs. prior.
  "Main Street holds monthly dividend at $0.245; declares Q3 supplemental of $0.30"

- **Material agreements / debt facilities**: lead with the size and structure.
  "Owl Rock closes $500M senior notes at 6.25% due 2031"

- **Non-accrual / credit events**: name the borrower if disclosed.
  "FS KKR places XYZ Industries on non-accrual; $42M FV impacted"

- **Personnel**: be neutral and clean. "Ares appoints J. Smith CFO effective June 1"

- **Other Events (Item 8.01)**: read the body — these can be anything from
  monthly NAV updates to share repurchase authorizations.

### Pacing

Anthropic Pro allows generous Claude Code usage. Realistic batch size:
20–30 items per pass before you wait a moment for rate. The SEC rate limit
in `fetch_pr_body` is already built into the script (~8 req/sec). Doing
500 items in a sitting is fine. Don't try to do all 10,000 backfill items
in one session — break it into a few sessions across days.

When you're done with this session, just stop. The script tracks progress
in the JSON files themselves, so next session resumes where you left off.

<<< END PROMPT

---

## What this gives you

After running this workflow once over your backfill (~10,000 historical 8-Ks),
every news item gets a `headline_ai` field. The News page reads this field
when present and falls back to the raw `title` (item-code label) when not.

For daily incrementals (the GitHub Action that runs `fetch_news.py` nightly),
new items will arrive without `headline_ai` set. Once a day or once a week,
open Claude Code and run the prompt again — it'll find the new ones and
rewrite just those. Pending count drops to zero, you stop.

## Cost

Using Claude Code on Anthropic Pro ($20/month): effectively free for this
workload, well within Pro allowances even at 10,000-item backfill.

## When to skip the rewrite

If the raw `title` is already clear (a substantial percentage of earnings and
M&A 8-Ks have descriptive index-page text), you can set `headline_ai` to the
existing title verbatim and move on. The point isn't to rewrite every headline
— it's to fix the bad ones.
