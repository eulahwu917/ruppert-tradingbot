# SA-3 Developer Summary — Fed Module Polymarket Migration
_Date: 2026-03-12 | Commit: f13b292_

## Task
Replace CME FedWatch API (paid, $25/mo, not subscribed) with Polymarket FOMC market
prices as the probability source for the Fed signal module.

## What Was Done

### File Modified
`kalshi-bot/fed_client.py`

### Removed (CME FedWatch)
- `_parse_fedwatch_json()` — CME JSON response parser
- `get_fedwatch_probabilities()` — CME API caller (tried 2 endpoints)
- `_scrape_fedwatch_html()` — CME HTML fallback scraper
- Unused `import re` (no more regex HTML scraping)

### Added (Polymarket)
- `POLYMARKET_FOMC_URL` constant — `https://gamma-api.polymarket.com/markets?tag=fomc&limit=20&active=true`
- `_classify_polymarket_outcome(question)` — maps question text to standard outcomes
  - Checks cut_50 before cut_25 to avoid false positive matches
  - Handles: maintain/hold/pause/unchanged, cut_25/25bps/decrease, cut_50/50bps, hike/raise
- `get_polymarket_fomc_probabilities(meeting_date)` — main fetch function
  - Fetches active FOMC markets from Polymarket gamma API
  - Filters by `endDate` within 5 days of target meeting date
  - Parses `outcomePrices[0]` as YES price (already on 0-1 scale)
  - Returns `{outcome: float}` dict matching the same shape as the old FedWatch dict

### Updated in `get_fed_signal()`
- `get_fedwatch_probabilities()` → `get_polymarket_fomc_probabilities()`
- Signal dict: `fedwatch_probs` → `polymarket_probs`
- Signal dict: added `prob_source: 'polymarket'`
- skip_reason: `fedwatch_unavailable` → `polymarket_unavailable`
- SIGNAL log line: `FedWatch=` → `Polymarket=`
- Docstring updated to reflect Polymarket source

### Unchanged
- All edge calculation logic (edge = abs(polymarket_prob - kalshi_price))
- Confidence calculation
- 2-7 day window filter
- FED_MIN_EDGE (12%), FED_MIN_CONFIDENCE (55%), FED_MIN_KALSHI_PRICE (15¢)
- Favorite-longshot bias filter
- FRED FEDFUNDS rate fetch
- Kalshi KXFEDDECISION market fetch
- `_save_scan_result()`, `run_fed_scan()`
- Self-test (`__main__`) — updated to call Polymarket function

## Internal Variable Note
The local variable `fedwatch_p` is retained inside the edge-calculation loop
(per task spec: "use that as fedwatch_prob in the existing edge calculation").
It is NOT exposed in the public signal dict — that uses `polymarket_probs` and `prob_source`.

## Git
- Staged: `git add fed_client.py`
- Committed: `f13b292` — "fed_client: replace CME FedWatch with Polymarket FOMC probability source"
- NOT pushed (CEO pushes EOD per workflow rules)

## Status
✅ Complete — ready for QA review (SA-4)

## Potential Issues for QA to Verify
1. Polymarket `outcomePrices` format — assumed `["yes_price", "no_price"]` as string floats on 0-1 scale. If the API returns cents (0-100), prices will be wrong. Should be validated against a live API call.
2. `endDate` proximity filter is ±5 days — may need tuning if Polymarket uses settlement date rather than meeting announcement date.
3. No markets may exist >30 days before a meeting — this is expected behavior, falls through to `polymarket_unavailable` skip.
