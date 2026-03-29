# SA-3 Developer — Fed Slug Fix Summary
_Date: 2026-03-13_

## Task
Fix the broken Polymarket FOMC lookup in `fed_client.py`. The `tag=fomc` Gamma API filter returns stale/unrelated markets. Replaced with direct slug-based lookup via `/events?slug=`.

---

## Changes Made

### 1. Created `kalshi-bot/logs/fomc_slugs.json`
- Maps FOMC decision dates (ISO) → Polymarket event slugs
- March 2026 slug confirmed: `fed-decision-in-march-885`
- All other 2026 dates set to `null` until slugs become known
- **NOTE**: `logs/` is in `.gitignore` — file exists on disk but CEO must decide whether to `git add -f` or relocate. Not staged.

### 2. Rewrote `get_polymarket_fomc_probabilities()` in `fed_client.py`

#### Old approach (broken):
- `GET /markets?tag=fomc&limit=20&active=true`
- Filtered by `endDate` proximity to meeting_date
- Returned stale/unrelated markets

#### New approach (slug-based):
1. Load `logs/fomc_slugs.json`
2. Look up slug by `meeting_date.isoformat()` key
3. If slug is `None`/missing:
   - Saves `{"status": "no_signal", "skip_reason": "slug_unknown", ...}` to `fed_scan_latest.json`
   - Returns sentinel dict (not `None`)
4. If slug is known:
   - `GET https://gamma-api.polymarket.com/events?slug={slug}`
   - Parses nested `markets[]` from the event
   - **Priority**: finds "no change" market (question contains "no change", case-insensitive) → `outcomePrices[0]` = `maintain` probability
   - Also classifies remaining outcomes via `_classify_polymarket_outcome()`
   - Returns `{'maintain': float, 'cut_25': float, ...}` probs dict

#### New constants added:
- `_FOMC_SLUGS_FILE = _LOGS_DIR / "fomc_slugs.json"`
- `POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"`
- Old `POLYMARKET_FOMC_URL` removed

### 3. Updated `get_fed_signal()` — sentinel handling

Added guard before the existing `if not polymarket_probs` check:
```python
if (
    isinstance(polymarket_probs, dict)
    and polymarket_probs.get("status") == "no_signal"
    and polymarket_probs.get("skip_reason") == "slug_unknown"
):
    return polymarket_probs  # already saved to disk; pass through
```

### 4. Skip reason labels
- `polymarket_unavailable` — kept for API/network errors (unchanged)
- `slug_unknown` — new, for missing/null slug in fomc_slugs.json

---

## Git Status
- `fed_client.py` — **staged** (`git add fed_client.py` ✓)
- `logs/fomc_slugs.json` — **on disk, NOT staged** (`logs/` is gitignored — needs CEO decision)

---

## TODOs / Flags for CEO
1. **`fomc_slugs.json` is gitignored** — CEO needs to decide: `git add -f logs/fomc_slugs.json`, move it outside `logs/`, or add a `config/` directory for non-secret config files.
2. **Slug maintenance** — As each 2026 FOMC meeting approaches, look up the Polymarket event slug and update `fomc_slugs.json`. Slugs typically appear on Polymarket 2–4 weeks before the meeting.
3. **March slug verified working** (`fed-decision-in-march-885`) — test the self-test `python fed_client.py` on 2026-03-11 to 2026-03-16 to confirm live parsing.
SA-3 [2026-03-13]: Fixed FOMC date mismatches (Apr29→May7, Jun10→Jun17, Dec9→Dec16 in fed_client.py; 2026-11-04→2026-10-28 key in fomc_slugs.json) and updated 2 stale logger.info paths from logs/ to config/; staged and committed (1fd4d68).
