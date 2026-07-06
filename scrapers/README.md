# Credit Canon — News pipeline

Autopilot feed for the News page. Two sources, both robust by design:

- **Press releases** — SEC EDGAR submissions API (official, free, stable). Every
  material filing for all covered BDCs, with an LLM-written one-line gist headline
  linked to the original filing. `scrapers/sec_press.py`.
- **News & opinion** — Google News RSS (surfaces LinkedIn/Medium/Bloomberg/trade
  press headlines legitimately; no blocking). Each article gets a
  converges/diverges verdict vs. our dataset. `scrapers/news_opinion.py`.

## Data contract (what the News page reads)
```
data/news/press/big.json              # ranked "big ones", LLM-headlined
data/news/press/by_fund/{TICKER}.json # every filing per fund, last 24 quarters
data/news/opinion/index.json          # articles + verdict ribbon
data/news/_universe_stats.json        # ground truth for verdicts
```

## One-time setup
1. Repo secrets (Settings > Secrets and variables > Actions):
   - `ANTHROPIC_API_KEY` — for headline + verdict generation.
   - `SEC_USER_AGENT` — e.g. `Credit Canon (you@yourdomain.com)` (SEC requires it).
2. First full backfill (once): Actions > **News pipeline** > Run workflow > mode `base`.
   This builds the full 24-quarter history for every fund and seeds the feeds.

## Nightly
The workflow runs automatically at 02:00 UTC (~9 PM US Eastern). It scrapes only
**new** filings that day, appends them, refreshes stats, updates the opinion feed,
and commits `data/news/` back to the repo. No manual step.

## Run locally
```
pip install -r scrapers/requirements.txt
export ANTHROPIC_API_KEY=sk-...        # optional; without it, rule-based headlines
export SEC_USER_AGENT="Credit Canon (you@domain.com)"
python scrapers/build_stats.py
python scrapers/sec_press.py --mode base       # or incremental
python scrapers/news_opinion.py
```

## Why it doesn't break
Every network call retries with backoff and rate-limits under SEC's cap. Every
file write is atomic. The LLM is optional and always falls back to a rule-based
headline. One bad fund or article is logged and skipped, never fatal. LLM calls
are hard-capped per run so a bad day can't run up a bill.
